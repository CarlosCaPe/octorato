#!/usr/bin/env python3
"""
chart.py — observability surface 8. Brain Charts on Demand.

Lightweight chart renderer for the brain's observability data. Reads from
the existing adapters (trace, cost profiler, Hebbian matrix, git log) and
emits either:

  - ASCII sparkline + table (default — for terminal / chat)
  - SVG inline (--svg — for digest emails, embedding, share-outs)

PNG via matplotlib was deferred (decision §9 Q5: ASCII + SVG only for MVP).

Subcommands:
  trace    — fires per day per name+event from ~/.claude/traces/
  cost     — token totals from skill-cost-profiler
  hebbian  — top edges in the co-activation matrix
  git      — commits per day in the brain repo

Examples:
  chart.py trace --window 30d
  chart.py trace --window 7d --by event
  chart.py cost --window 30d --top 10
  chart.py hebbian --top 10
  chart.py git --window 14d --svg > out.svg

Stdlib only — no matplotlib.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from _brain_obs import (
    TRACES_DIR,
    iter_trace_records,
    parse_record_ts,
    parse_window as _parse_window_cutoff,
)

# Force UTF-8 on stdout/stderr so the ✓ / ✗ / em-dash glyphs in reports
# survive on Windows shells defaulting to cp1252. Without this, a script
# can do its work correctly and still crash with UnicodeEncodeError when
# printing success. Applied repo-wide by _apply-utf8-reconfigure.py.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

NEURAL_ACTIVITY = Path.home() / ".claude" / "company" / "neural_activity.json"
SCRIPTS_DIR = Path.home() / ".claude" / "scripts"
BRAIN_DIR = Path.home() / ".claude"

# Unicode sparkline blocks — 8 levels.
SPARK_BLOCKS = "▁▂▃▄▅▆▇█"


def parse_window(s: str) -> timedelta:
    # brain-chart adapters need a `timedelta` (window length) rather than a
    # datetime cutoff. Translate via the shared parser, then subtract.
    cutoff = _parse_window_cutoff(s)
    if cutoff is None:
        raise argparse.ArgumentTypeError(f"invalid window '{s}'.")
    return datetime.now(timezone.utc) - cutoff


_parse_ts = parse_record_ts


# ── ASCII sparkline ────────────────────────────────────


def sparkline(values: list[float]) -> str:
    """Render a Unicode sparkline from a sequence of numbers."""
    if not values:
        return ""
    lo = min(values)
    hi = max(values)
    if hi == lo:
        return SPARK_BLOCKS[0] * len(values)
    step = (hi - lo) / (len(SPARK_BLOCKS) - 1)
    return "".join(SPARK_BLOCKS[min(int((v - lo) / step), len(SPARK_BLOCKS) - 1)] for v in values)


# ── SVG renderer ────────────────────────────────────────


def svg_bars(title: str, labels: list[str], values: list[float]) -> str:
    """Minimal bar chart SVG. labels are short (date or name), values aligned."""
    if not values:
        return f"<svg><text x='0' y='20'>{title}: no data</text></svg>"
    W = max(420, len(values) * 35 + 60)
    H = 220
    pad_l, pad_b, pad_t = 50, 30, 30
    hi = max(values) or 1.0
    bar_w = max(8, (W - pad_l - 20) // len(values) - 4)

    svg: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
        f'<style>text{{font-family:monospace;font-size:11px}} .bar{{fill:#dc2626}} .lbl{{fill:#1a1a1a}}</style>',
        f'<text x="10" y="20" font-size="14" font-weight="bold">{title}</text>',
    ]
    chart_h = H - pad_t - pad_b
    for i, (lab, v) in enumerate(zip(labels, values)):
        x = pad_l + i * (bar_w + 4)
        h = (v / hi) * chart_h if v > 0 else 0
        y = pad_t + chart_h - h
        svg.append(
            f'<rect class="bar" x="{x}" y="{y:.1f}" width="{bar_w}" height="{h:.1f}"/>'
        )
        svg.append(
            f'<text class="lbl" x="{x + bar_w / 2:.1f}" y="{H - pad_b + 14}" text-anchor="middle">{lab}</text>'
        )
        svg.append(
            f'<text class="lbl" x="{x + bar_w / 2:.1f}" y="{y - 4:.1f}" text-anchor="middle">{int(v)}</text>'
        )
    svg.append(f'<line x1="{pad_l}" y1="{pad_t + chart_h}" x2="{W - 10}" y2="{pad_t + chart_h}" stroke="#1a1a1a"/>')
    svg.append("</svg>")
    return "\n".join(svg)


# ── Adapter: trace ──────────────────────────────────────


def adapter_trace(window: timedelta, group_by: str) -> tuple[str, list[tuple[str, int]]]:
    since = datetime.now(timezone.utc) - window
    if group_by == "day":
        # Build a daily series from `since` to today inclusive.
        days = []
        cur = since.replace(hour=0, minute=0, second=0, microsecond=0)
        end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        while cur <= end:
            days.append(cur.strftime("%m-%d"))
            cur += timedelta(days=1)
        counts: dict[str, int] = {d: 0 for d in days}
        for rec in _iter_trace(since):
            if rec.get("event") not in ("skill_fire", "agent_activate"):
                continue
            ts = _parse_ts(rec.get("ts", ""))
            if ts is None:
                continue
            key = ts.strftime("%m-%d")
            if key in counts:
                counts[key] += 1
        title = f"Trace events per day (last {format_td(window)})"
        return title, [(d, counts[d]) for d in days]
    # group_by name or event
    c: Counter[str] = Counter()
    for rec in _iter_trace(since):
        if rec.get("event") not in ("skill_fire", "agent_activate"):
            continue
        key = rec.get(group_by) or "(unknown)"
        c[str(key)] += 1
    title = f"Trace events by {group_by} (last {format_td(window)})"
    return title, c.most_common(20)


_iter_trace = iter_trace_records  # alias to shared lib


# ── Adapter: cost ──────────────────────────────────────


def adapter_cost(days: int, top: int) -> tuple[str, list[tuple[str, int]]]:
    cost_script = SCRIPTS_DIR / "skill-cost-profiler.py"
    if not cost_script.exists():
        print("✗ skill-cost-profiler.py not found (Port 2 must ship first)", file=sys.stderr)
        sys.exit(2)
    result = subprocess.run(
        ["python3", str(cost_script), "--days", str(days), "--json"],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        print(f"✗ cost profiler failed: {result.stderr[:200]}", file=sys.stderr)
        sys.exit(2)
    data = json.loads(result.stdout)
    skills = [r for r in data if r["skill"] != "__conversation__"][:top]
    title = f"Top {len(skills)} cost-heaviest skills (last {days}d)"
    return title, [(r["skill"], r["total_tokens"]) for r in skills]


# ── Adapter: hebbian ──────────────────────────────────


def adapter_hebbian(top: int) -> tuple[str, list[tuple[str, int]]]:
    if not NEURAL_ACTIVITY.exists():
        print(f"✗ {NEURAL_ACTIVITY} not found (Port 1 task #7 must ship first)", file=sys.stderr)
        sys.exit(2)
    data = json.loads(NEURAL_ACTIVITY.read_text(encoding="utf-8"))
    matrix = data.get("co_activation_matrix", {})
    pairs = sorted(matrix.items(), key=lambda kv: kv[1], reverse=True)[:top]
    title = f"Top {len(pairs)} Hebbian co-activation edges"
    return title, [(k, int(v)) for k, v in pairs]


# ── Adapter: git ──────────────────────────────────────


def adapter_git(window: timedelta) -> tuple[str, list[tuple[str, int]]]:
    days = int(window.total_seconds() / 86400) + 1
    since_str = (datetime.now(timezone.utc) - window).strftime("%Y-%m-%d")
    try:
        result = subprocess.run(
            ["git", "-C", str(BRAIN_DIR), "log", f"--since={since_str}", "--format=%aI"],
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.SubprocessError, OSError) as e:
        print(f"✗ git log failed: {e}", file=sys.stderr)
        sys.exit(2)
    counts: dict[str, int] = defaultdict(int)
    for line in result.stdout.splitlines():
        ts = _parse_ts(line.strip())
        if ts is None:
            continue
        counts[ts.strftime("%m-%d")] += 1
    # Build daily series same as trace
    days_list = []
    cur = datetime.now(timezone.utc) - window
    end = datetime.now(timezone.utc)
    cur = cur.replace(hour=0, minute=0, second=0, microsecond=0)
    end = end.replace(hour=0, minute=0, second=0, microsecond=0)
    while cur <= end:
        days_list.append(cur.strftime("%m-%d"))
        cur += timedelta(days=1)
    title = f"Brain commits per day (last {format_td(window)})"
    return title, [(d, counts.get(d, 0)) for d in days_list]


# ── Rendering ─────────────────────────────────────────


def format_td(td: timedelta) -> str:
    days = int(td.total_seconds() / 86400)
    if days >= 7 and days % 7 == 0:
        return f"{days // 7}w"
    if days >= 1:
        return f"{days}d"
    hours = int(td.total_seconds() / 3600)
    return f"{hours}h"


def render_ascii(title: str, series: list[tuple[str, int]]) -> str:
    if not series:
        return f"{title}\n(no data)\n"
    labels = [s[0] for s in series]
    values = [float(s[1]) for s in series]
    spark = sparkline(values)
    # Table
    max_label = max(len(l) for l in labels)
    lines = [
        title,
        "",
        f"  Sparkline: {spark}",
        "",
    ]
    lines.append(f"  {'Label':<{max_label}}  Value")
    lines.append(f"  {'-' * max_label}  -----")
    for l, v in series:
        lines.append(f"  {l:<{max_label}}  {int(v):,}")
    return "\n".join(lines) + "\n"


def render_svg(title: str, series: list[tuple[str, int]]) -> str:
    labels = [s[0] for s in series]
    values = [float(s[1]) for s in series]
    return svg_bars(title, labels, values)


# ── Entry point ───────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Brain Charts on Demand — Phase C Port 8.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("trace", help="Trace events from ~/.claude/traces/")
    sp.add_argument("--window", type=parse_window, default=parse_window("7d"))
    sp.add_argument("--by", choices=["day", "name", "event"], default="day")
    sp.add_argument("--svg", action="store_true")

    sp = sub.add_parser("cost", help="Cost from skill-cost-profiler")
    sp.add_argument("--days", type=int, default=30)
    sp.add_argument("--top", type=int, default=10)
    sp.add_argument("--svg", action="store_true")

    sp = sub.add_parser("hebbian", help="Top co-activation edges")
    sp.add_argument("--top", type=int, default=10)
    sp.add_argument("--svg", action="store_true")

    sp = sub.add_parser("git", help="Commits per day in the brain repo")
    sp.add_argument("--window", type=parse_window, default=parse_window("14d"))
    sp.add_argument("--svg", action="store_true")

    args = parser.parse_args(argv)

    if args.cmd == "trace":
        title, series = adapter_trace(args.window, args.by)
    elif args.cmd == "cost":
        title, series = adapter_cost(args.days, args.top)
    elif args.cmd == "hebbian":
        title, series = adapter_hebbian(args.top)
    elif args.cmd == "git":
        title, series = adapter_git(args.window)
    else:
        parser.error(f"unknown command {args.cmd}")
        return 1

    if args.svg:
        sys.stdout.write(render_svg(title, series))
    else:
        sys.stdout.write(render_ascii(title, series))
    return 0


if __name__ == "__main__":
    sys.exit(main())
