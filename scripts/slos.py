#!/usr/bin/env python3
"""
slos.py — Datadog Port 3 (Phase B). Brain SLOs + error budget burn rate.

Reads the SLO config (`~/.claude/slos.yaml` if PyYAML is installed,
otherwise `~/.claude/slos.json` as a stdlib fallback), computes the
current SLI against trace data, renders SLO_REPORT.md, and optionally
opens a GitHub issue when an SLO has burned 100% of its budget.

Config schema (YAML or JSON, same shape):

    slos:
      - name: querymaster-postgresql      # skill or agent name
        event: skill_fire                  # or agent_activate
        sli: success_rate                  # success_rate is the only SLI today
        target: 0.95
        window_days: 30

Future iterations:
- Auto-baseline from Watchdog output (decision §9 Q4 — deferred to Port 3.1)
- Exception markers ("this miss was expected") — AC-5

Stdlib only by default. PyYAML is optional sugar.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from _brain_obs import iter_trace_records, parse_record_ts  # shared helpers

CONFIG_YAML = Path.home() / ".claude" / "slos.yaml"
CONFIG_JSON = Path.home() / ".claude" / "slos.json"
REPORT_PATH = Path.home() / ".claude" / "SLO_REPORT.md"
STATE_DIR = Path.home() / ".claude" / "slos"
ISSUES_TODAY_FILE = STATE_DIR / "issues-today.json"

GH_REPO = "CarlosCaPe/octorato"
GH_LABEL = "brain-slos"


# ── Config loading ──────────────────────────────────────


def _try_load_yaml(path: Path) -> dict | None:
    try:
        import yaml  # type: ignore
    except ImportError:
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, Exception):
        return None


def load_config() -> dict:
    if CONFIG_YAML.exists():
        data = _try_load_yaml(CONFIG_YAML)
        if data is not None:
            return data
        sys.stderr.write(
            f"⚠ {CONFIG_YAML} exists but PyYAML missing/failed — falling back to JSON.\n"
        )
    if CONFIG_JSON.exists():
        try:
            return json.loads(CONFIG_JSON.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            sys.stderr.write(f"✗ Could not parse {CONFIG_JSON}: {e}\n")
            return {}
    return {}


# Trace ingestion + ts parsing — imported from _brain_obs.
_parse_ts = parse_record_ts
_iter_records = iter_trace_records


# ── SLI computation ────────────────────────────────────


def compute_success_rate(name: str, event: str, window_days: int) -> tuple[int, int]:
    """Return (total, ok_count) for the given name+event in the window."""
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    total = 0
    ok = 0
    for rec in _iter_records(since):
        if rec.get("event") != event:
            continue
        if rec.get("name") != name:
            continue
        total += 1
        if rec.get("status") == "ok":
            ok += 1
    return total, ok


def evaluate_slo(slo: dict) -> dict:
    name = slo.get("name")
    event = slo.get("event")
    sli = slo.get("sli", "success_rate")
    target = float(slo.get("target", 0.95))
    window_days = int(slo.get("window_days", 30))

    out = {
        "name": name,
        "event": event,
        "sli": sli,
        "target": target,
        "window_days": window_days,
        "current": None,
        "total": 0,
        "ok": 0,
        "budget_remaining": None,
        "burning_at_rate": None,
        "status": "unknown",
    }

    if sli != "success_rate":
        out["status"] = "unsupported_sli"
        return out

    total, ok = compute_success_rate(name, event, window_days)
    out["total"] = total
    out["ok"] = ok
    if total == 0:
        out["status"] = "no_data"
        return out

    current_rate = ok / total
    out["current"] = current_rate

    # Error budget math.
    # allowed_misses = (1 - target) * total  (total observations in window)
    # actual_misses  = total - ok
    # budget_remaining = max(0, 1 - actual_misses / allowed_misses)
    allowed_misses = (1 - target) * total
    actual_misses = total - ok
    if allowed_misses <= 0:
        # Pathological — target = 1.0 (no misses allowed)
        budget_remaining = 0.0 if actual_misses > 0 else 1.0
    else:
        budget_remaining = max(0.0, 1.0 - actual_misses / allowed_misses)
    out["budget_remaining"] = budget_remaining
    # Burning at rate: misses per day vs daily budget
    daily_allowed = allowed_misses / window_days if window_days > 0 else 0
    daily_actual = actual_misses / window_days if window_days > 0 else 0
    if daily_allowed > 0:
        out["burning_at_rate"] = daily_actual / daily_allowed
    else:
        out["burning_at_rate"] = float("inf") if daily_actual > 0 else 0.0

    if budget_remaining <= 0:
        out["status"] = "exhausted"
    elif budget_remaining < 0.25:
        out["status"] = "burning_fast"
    elif current_rate < target:
        out["status"] = "miss"
    else:
        out["status"] = "ok"
    return out


# ── Reporting ──────────────────────────────────────────


def _pct(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v * 100:.2f}%"


def render_report(results: list[dict]) -> str:
    if not results:
        return "_No SLOs defined. Create `~/.claude/slos.yaml` (or .json) — see slos.py docstring._\n"
    lines = [
        f"# SLO Report — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "| Skill/Agent | Event | Window | Target | Current | Budget left | Burning at | Status |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for r in results:
        burn = r.get("burning_at_rate")
        burn_s = "—" if burn is None else (f"{burn:.2f}×" if burn != float("inf") else "∞×")
        lines.append(
            "| `{name}` | {ev} | {win}d | {tgt} | {cur} | {bud} | {burn} | **{status}** |".format(
                name=r["name"],
                ev=r["event"],
                win=r["window_days"],
                tgt=_pct(r["target"]),
                cur=_pct(r.get("current")),
                bud=_pct(r.get("budget_remaining")),
                burn=burn_s,
                status=r["status"],
            )
        )
    return "\n".join(lines) + "\n"


# ── GH issue ───────────────────────────────────────────


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load_json(p: Path, default):
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _save_json(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def open_issue(slo_result: dict) -> str | None:
    title = (
        f"[slos] {slo_result['name']} ({slo_result['event']}) "
        f"budget exhausted — {_pct(slo_result['current'])} vs {_pct(slo_result['target'])}"
    )
    body = (
        f"SLO budget exhausted for `{slo_result['name']}` ({slo_result['event']}).\n\n"
        f"- Window: {slo_result['window_days']}d\n"
        f"- Target: {_pct(slo_result['target'])}\n"
        f"- Current: {_pct(slo_result['current'])}\n"
        f"- Total observations: {slo_result['total']}\n"
        f"- OK / Miss: {slo_result['ok']} / {slo_result['total'] - slo_result['ok']}\n"
        f"- Budget remaining: {_pct(slo_result['budget_remaining'])}\n"
        f"- Burning at: "
        f"{slo_result['burning_at_rate'] if slo_result['burning_at_rate'] != float('inf') else '∞'}× allowance\n\n"
        "Action: investigate the skill/agent for regression. Dismiss this "
        "issue to suppress; mark a miss as 'expected' to recover budget (AC-5 — manual today).\n"
    )
    try:
        result = subprocess.run(
            [
                "gh", "issue", "create",
                "--repo", GH_REPO,
                "--title", title,
                "--body", body,
                "--label", GH_LABEL,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        sys.stderr.write(f"gh issue create failed: {result.stderr}\n")
        return None
    except (subprocess.SubprocessError, OSError) as e:
        sys.stderr.write(f"gh CLI invocation error: {e}\n")
        return None


# ── Entry point ────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Brain SLOs — Phase B Port 3.",
        epilog="Default mode is dry-run (prints report + writes SLO_REPORT.md). "
        "--execute opens gh issues for exhausted budgets.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually open GitHub issues. Without this flag, prints report only.",
    )
    parser.add_argument(
        "--write-report",
        action="store_true",
        help="Write report to ~/.claude/SLO_REPORT.md (always written in --execute mode).",
    )
    args = parser.parse_args(argv)

    cfg = load_config()
    slos = cfg.get("slos") if isinstance(cfg, dict) else None
    if not isinstance(slos, list):
        slos = []

    results = [evaluate_slo(s) for s in slos]

    report = render_report(results)
    print(report)

    if args.write_report or args.execute:
        try:
            REPORT_PATH.write_text(report, encoding="utf-8")
            print(f"Wrote {REPORT_PATH}")
        except OSError as e:
            sys.stderr.write(f"Could not write report: {e}\n")

    if not args.execute:
        exhausted = [r for r in results if r["status"] == "exhausted"]
        if exhausted:
            print(
                f"(Dry-run — {len(exhausted)} exhausted SLO(s) would open issues. "
                "Pass `--execute`.)"
            )
        return 0

    # Live mode — open issues for exhausted, dedup per day
    issues_today = _load_json(ISSUES_TODAY_FILE, {"date": _today_utc(), "names": []})
    if issues_today.get("date") != _today_utc():
        issues_today = {"date": _today_utc(), "names": []}

    created = 0
    for r in results:
        if r["status"] != "exhausted":
            continue
        key = f"{r['event']}::{r['name']}"
        if key in issues_today.get("names", []):
            print(f"  · {key} — already opened today, skip")
            continue
        url = open_issue(r)
        if url:
            print(f"  ✓ {key} → {url}")
            issues_today.setdefault("names", []).append(key)
            created += 1
        else:
            print(f"  ✗ {key} — failed (see stderr)")

    if created:
        _save_json(ISSUES_TODAY_FILE, issues_today)
    print(f"\nCreated {created} issue(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
