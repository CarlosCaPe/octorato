#!/usr/bin/env python3
"""Claude Code usage aggregator.

Parses ~/.claude/projects/**/*.jsonl files and reports token usage and
estimated API cost by day, week, month, model, and project.

Output is human-readable. Pricing is approximate (Anthropic public list price);
update PRICING dict when models or prices change.

Usage:
    python3 usage_report.py [--days N] [--json] [--projects-dir PATH]
"""
import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

# Pricing per 1M tokens (USD). Update when Anthropic changes list prices.
PRICING = {
    "claude-opus-4-7":           {"in": 15.00, "out": 75.00, "cache_w": 18.75, "cache_r": 1.50},
    "claude-opus-4-6":           {"in": 15.00, "out": 75.00, "cache_w": 18.75, "cache_r": 1.50},
    "claude-opus-4":             {"in": 15.00, "out": 75.00, "cache_w": 18.75, "cache_r": 1.50},
    "claude-sonnet-4-6":         {"in":  3.00, "out": 15.00, "cache_w":  3.75, "cache_r": 0.30},
    "claude-sonnet-4-5":         {"in":  3.00, "out": 15.00, "cache_w":  3.75, "cache_r": 0.30},
    "claude-sonnet-4":           {"in":  3.00, "out": 15.00, "cache_w":  3.75, "cache_r": 0.30},
    "claude-haiku-4-5":          {"in":  0.80, "out":  4.00, "cache_w":  1.00, "cache_r": 0.08},
    "claude-haiku-4":            {"in":  0.80, "out":  4.00, "cache_w":  1.00, "cache_r": 0.08},
    "claude-3-5-sonnet":         {"in":  3.00, "out": 15.00, "cache_w":  3.75, "cache_r": 0.30},
    "claude-3-5-haiku":          {"in":  0.80, "out":  4.00, "cache_w":  1.00, "cache_r": 0.08},
}


def price(model: str, usage: dict) -> float:
    base = model.split("[")[0].lower()  # strip suffixes like [1m]
    # strip date suffix like -20251001
    if base.count("-") >= 4:
        parts = base.rsplit("-", 1)
        if parts[1].isdigit() and len(parts[1]) == 8:
            base = parts[0]
    p = PRICING.get(base)
    if not p:
        if "opus" in base:
            p = PRICING["claude-opus-4-7"]
        elif "haiku" in base:
            p = PRICING["claude-haiku-4-5"]
        else:
            p = PRICING["claude-sonnet-4-6"]
    return (
        usage.get("input_tokens", 0) * p["in"] / 1e6
        + usage.get("output_tokens", 0) * p["out"] / 1e6
        + usage.get("cache_creation_input_tokens", 0) * p["cache_w"] / 1e6
        + usage.get("cache_read_input_tokens", 0) * p["cache_r"] / 1e6
    )


def fmt_tokens(n: int) -> str:
    if n >= 1e9:
        return f"{n/1e9:.2f}B"
    if n >= 1e6:
        return f"{n/1e6:.2f}M"
    if n >= 1e3:
        return f"{n/1e3:.1f}K"
    return str(n)


def empty_bucket():
    return {"in": 0, "out": 0, "cw": 0, "cr": 0, "cost": 0.0, "msgs": 0, "sessions": set()}


def aggregate(projects_dir: Path):
    by_day = defaultdict(empty_bucket)
    by_week = defaultdict(empty_bucket)
    by_month = defaultdict(empty_bucket)
    by_model = defaultdict(empty_bucket)
    by_project = defaultdict(empty_bucket)
    total_lines = total_msgs = 0

    files = list(projects_dir.glob("**/*.jsonl"))
    for f in files:
        # Project name = parent dir, with home-prefix stripped for readability.
        # Generic transform — no client-specific knowledge.
        project = f.parent.name
        home_prefix = f"-{str(Path.home()).lstrip('/').replace('/', '-')}"
        if project.startswith(home_prefix):
            project = project[len(home_prefix):].lstrip("-") or "~"
        try:
            fh = open(f, "r", encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                total_lines += 1
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = rec.get("message", {})
                if not isinstance(msg, dict):
                    continue
                usage = msg.get("usage")
                if not usage:
                    continue
                model = msg.get("model", "unknown")
                ts = rec.get("timestamp", "")
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except Exception:
                    continue
                d_key = dt.strftime("%Y-%m-%d")
                yr, wk, _ = dt.isocalendar()
                w_key = f"{yr}-W{wk:02d}"
                m_key = dt.strftime("%Y-%m")
                cost = price(model, usage)
                in_t = usage.get("input_tokens", 0)
                out_t = usage.get("output_tokens", 0)
                cw_t = usage.get("cache_creation_input_tokens", 0)
                cr_t = usage.get("cache_read_input_tokens", 0)
                sid = rec.get("sessionId", "")
                for agg, key in [(by_day, d_key), (by_week, w_key), (by_month, m_key)]:
                    b = agg[key]
                    b["in"] += in_t; b["out"] += out_t
                    b["cw"] += cw_t; b["cr"] += cr_t
                    b["cost"] += cost; b["msgs"] += 1
                    b["sessions"].add(sid)
                for agg, key in [(by_model, model), (by_project, project)]:
                    b = agg[key]
                    b["in"] += in_t; b["out"] += out_t
                    b["cw"] += cw_t; b["cr"] += cr_t
                    b["cost"] += cost; b["msgs"] += 1
                    b["sessions"].add(sid)
                total_msgs += 1

    return {
        "files": len(files),
        "lines": total_lines,
        "messages": total_msgs,
        "by_day": by_day,
        "by_week": by_week,
        "by_month": by_month,
        "by_model": by_model,
        "by_project": by_project,
    }


def render_text(data: dict, days: int = 14):
    print("=== Claude Code Usage Report ===")
    print(
        f"Files scanned: {data['files']}  |  Lines: {data['lines']:,}  |  "
        f"Messages with usage: {data['messages']:,}"
    )
    print()

    print(f"=== ÚLTIMOS {days} DÍAS ===")
    today = datetime.now().date()
    by_day = data["by_day"]
    for i in range(days - 1, -1, -1):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        if d in by_day:
            v = by_day[d]
            print(
                f"  {d}  sess={len(v['sessions']):>2}  msgs={v['msgs']:>4}  "
                f"in={fmt_tokens(v['in']):>7}  out={fmt_tokens(v['out']):>7}  "
                f"cache_r={fmt_tokens(v['cr']):>8}  ${v['cost']:>8.2f}"
            )
        else:
            print(f"  {d}  (sin actividad)")
    print()

    print("=== POR SEMANA (últimas 8) ===")
    for w in sorted(data["by_week"].keys())[-8:]:
        v = data["by_week"][w]
        print(
            f"  {w}  sess={len(v['sessions']):>2}  msgs={v['msgs']:>5}  "
            f"in={fmt_tokens(v['in']):>7}  out={fmt_tokens(v['out']):>7}  "
            f"cache_r={fmt_tokens(v['cr']):>8}  ${v['cost']:>9.2f}"
        )
    print()

    print("=== POR MES ===")
    for m in sorted(data["by_month"].keys()):
        v = data["by_month"][m]
        print(
            f"  {m}    sess={len(v['sessions']):>3}  msgs={v['msgs']:>6}  "
            f"in={fmt_tokens(v['in']):>7}  out={fmt_tokens(v['out']):>7}  "
            f"cache_r={fmt_tokens(v['cr']):>8}  ${v['cost']:>9.2f}"
        )
    print()

    print("=== POR MODELO ===")
    for model, v in sorted(data["by_model"].items(), key=lambda x: -x[1]["cost"]):
        print(
            f"  {model:<32}  msgs={v['msgs']:>6}  "
            f"in={fmt_tokens(v['in']):>7}  out={fmt_tokens(v['out']):>7}  "
            f"${v['cost']:>9.2f}"
        )
    print()

    print("=== POR PROYECTO (top 10 por costo) ===")
    sorted_proj = sorted(data["by_project"].items(), key=lambda x: -x[1]["cost"])[:10]
    for proj, v in sorted_proj:
        print(
            f"  {proj[:45]:<45}  sess={len(v['sessions']):>3}  "
            f"msgs={v['msgs']:>6}  ${v['cost']:>9.2f}"
        )
    print()

    total_cost = sum(v["cost"] for v in data["by_model"].values())
    total_in = sum(v["in"] for v in data["by_model"].values())
    total_out = sum(v["out"] for v in data["by_model"].values())
    total_cw = sum(v["cw"] for v in data["by_model"].values())
    total_cr = sum(v["cr"] for v in data["by_model"].values())
    all_sessions = set()
    for v in data["by_project"].values():
        all_sessions.update(v["sessions"])

    print("=== TOTAL ACUMULADO ===")
    print(f"  Sesiones únicas:        {len(all_sessions):,}")
    print(f"  Mensajes asistente:     {data['messages']:,}")
    print(f"  Tokens input:           {fmt_tokens(total_in)}")
    print(f"  Tokens output:          {fmt_tokens(total_out)}")
    print(f"  Tokens cache write:     {fmt_tokens(total_cw)}")
    print(f"  Tokens cache read:      {fmt_tokens(total_cr)}")
    print(f"  Costo API equivalente:  ${total_cost:,.2f} USD")
    print()
    print("  NOTA: con suscripción Claude Max/Pro, este costo es lo que pagarías")
    print("        a precio API público. Es referencia de 'valor extraído'.")


def render_json(data: dict):
    out = {
        "files_scanned": data["files"],
        "messages": data["messages"],
        "by_day": {k: {**v, "sessions": len(v["sessions"])} for k, v in data["by_day"].items()},
        "by_week": {k: {**v, "sessions": len(v["sessions"])} for k, v in data["by_week"].items()},
        "by_month": {k: {**v, "sessions": len(v["sessions"])} for k, v in data["by_month"].items()},
        "by_model": {k: {**v, "sessions": len(v["sessions"])} for k, v in data["by_model"].items()},
        "by_project": {k: {**v, "sessions": len(v["sessions"])} for k, v in data["by_project"].items()},
    }
    print(json.dumps(out, indent=2, default=str))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--days", type=int, default=14, help="Days of detail in text mode")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    parser.add_argument(
        "--projects-dir",
        type=Path,
        default=Path.home() / ".claude" / "projects",
        help="Path to Claude Code projects directory",
    )
    args = parser.parse_args()

    if not args.projects_dir.exists():
        print(f"ERROR: projects dir not found: {args.projects_dir}", file=sys.stderr)
        sys.exit(1)

    data = aggregate(args.projects_dir)
    if args.json:
        render_json(data)
    else:
        render_text(data, days=args.days)


if __name__ == "__main__":
    main()
