#!/usr/bin/env python3
"""
watchdog.py — Datadog Port 4 (Phase B, MVP) anomaly detector.

Reads the JSONL trace files written by trace-hook.py and computes two
anomaly classes per skill/agent name:

  cliff_drop   — baseline fires regularly but current 7d window = 0 (likely broken)
  quality_drop — baseline success_rate is normal but current is >2σ worse

Cost spike (the third anomaly in the spec) is deferred until Port 2
Skill Cost Profiler ships — `tokens` data is currently sparse.

Default mode is DRY-RUN (prints a markdown table to stdout). Pass
`--execute` to actually open GitHub issues. Suppressions and dedup live
under `~/.claude/watchdog/` (gitignored). One issue per skill per day,
14-day suppression after operator dismissal.

Stdlib only — AC-1 of the spec.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from _brain_obs import iter_trace_records, parse_record_ts  # shared helpers

STATE_DIR = Path.home() / ".claude" / "watchdog"
SUPPRESSIONS_FILE = STATE_DIR / "suppressions.json"
ISSUES_TODAY_FILE = STATE_DIR / "issues-today.json"

# Tunables — spec defaults.
CURRENT_WINDOW_DAYS = 7
BASELINE_WINDOW_DAYS = 30
SIGMA_THRESHOLD = 2.0
MIN_BASELINE_FIRINGS = 5
SUPPRESS_AFTER_DISMISS_DAYS = 14

# GH issue config.
GH_REPO = "CarlosCaPe/octorato"
GH_LABEL = "brain-watchdog"


# Trace ingestion + ts parsing — imported from _brain_obs.
# Aliases keep the local idiom (`_parse_ts`, `_iter_records`) used below.
_parse_ts = parse_record_ts
_iter_records = iter_trace_records


# ── Stats helpers ───────────────────────────────────────


def _poisson_z(observed: float, expected: float) -> float:
    """Z-score for a Poisson count. Returns +∞ when expected=0 and observed>0,
    -∞ when expected>0 and observed=0 (the cliff-drop signal)."""
    if expected <= 0:
        return float("inf") if observed > 0 else 0.0
    return (observed - expected) / math.sqrt(expected)


def _bernoulli_z(observed_rate: float, baseline_rate: float, n: int) -> float:
    """Z-score for a Bernoulli success rate. n is the current-window count.
    Returns 0 if the observed sample is too small to compare."""
    if n <= 0:
        return 0.0
    p = baseline_rate
    sd = math.sqrt(max(p * (1 - p), 1e-9) / n)
    return (observed_rate - baseline_rate) / sd


# ── Suppression / dedup state ──────────────────────────


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _is_suppressed(name: str, suppressions: dict) -> bool:
    until = suppressions.get(name)
    if not until:
        return False
    until_dt = _parse_ts(until)
    return until_dt is not None and until_dt > datetime.now(timezone.utc)


def _issue_already_open_today(name: str, issues_today: dict) -> bool:
    return issues_today.get("date") == _today_utc() and name in issues_today.get("names", [])


# ── Core analysis ──────────────────────────────────────


def analyse() -> list[dict]:
    """Return a list of anomaly dicts. Each has keys:
    name, kind, current, baseline_mean, z, success_current, success_baseline.
    """
    now = datetime.now(timezone.utc)
    current_start = now - timedelta(days=CURRENT_WINDOW_DAYS)
    baseline_start = now - timedelta(days=CURRENT_WINDOW_DAYS + BASELINE_WINDOW_DAYS)

    by_name_current: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"total": 0, "ok": 0}
    )
    by_name_baseline: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"total": 0, "ok": 0}
    )

    for rec in _iter_records(baseline_start):
        ev = rec.get("event")
        if ev not in ("skill_fire", "agent_activate"):
            continue
        name = rec.get("name") or "(unknown)"
        ts = _parse_ts(rec.get("ts", ""))
        if ts is None:
            continue
        bucket = by_name_current if ts >= current_start else by_name_baseline
        key = (ev, name)
        bucket[key]["total"] += 1
        if rec.get("status") == "ok":
            bucket[key]["ok"] += 1

    anomalies: list[dict] = []
    # Iterate over the union of keys; report on each with sufficient baseline data
    all_keys = set(by_name_current.keys()) | set(by_name_baseline.keys())
    for key in all_keys:
        ev, name = key
        base = by_name_baseline[key]
        curr = by_name_current[key]
        baseline_total = base["total"]
        if baseline_total < MIN_BASELINE_FIRINGS:
            continue

        # Cliff drop (Poisson count comparison)
        # Project the baseline to a 7-day expected window.
        expected_7d = baseline_total * (CURRENT_WINDOW_DAYS / BASELINE_WINDOW_DAYS)
        z_count = _poisson_z(curr["total"], expected_7d)
        if z_count <= -SIGMA_THRESHOLD:
            anomalies.append(
                {
                    "name": name,
                    "event": ev,
                    "kind": "cliff_drop",
                    "current": curr["total"],
                    "expected": round(expected_7d, 2),
                    "z": round(z_count, 2),
                    "baseline_total": baseline_total,
                }
            )

        # Quality drop (Bernoulli success rate). Need at least 1 current sample.
        if curr["total"] >= 1:
            baseline_rate = base["ok"] / baseline_total
            current_rate = curr["ok"] / curr["total"]
            z_rate = _bernoulli_z(current_rate, baseline_rate, curr["total"])
            if z_rate <= -SIGMA_THRESHOLD and baseline_rate > 0.5:
                # Only alert when baseline was healthy (>50% ok) — otherwise the
                # skill is just consistently flaky and we'd alert every week.
                anomalies.append(
                    {
                        "name": name,
                        "event": ev,
                        "kind": "quality_drop",
                        "current_rate": round(current_rate, 3),
                        "baseline_rate": round(baseline_rate, 3),
                        "z": round(z_rate, 2),
                        "current_total": curr["total"],
                    }
                )
    return anomalies


# ── Reporting ──────────────────────────────────────────


def _render_markdown(anomalies: list[dict]) -> str:
    if not anomalies:
        return "_No anomalies detected this run._\n"
    out: list[str] = []
    cliff = [a for a in anomalies if a["kind"] == "cliff_drop"]
    qual = [a for a in anomalies if a["kind"] == "quality_drop"]
    if cliff:
        out.append("### Cliff drops")
        out.append("| Event | Name | Current 7d | Expected | z-score | Baseline 30d total |")
        out.append("|---|---|---|---|---|---|")
        for a in cliff:
            out.append(
                f"| {a['event']} | `{a['name']}` | {a['current']} | {a['expected']} | "
                f"{a['z']} | {a['baseline_total']} |"
            )
        out.append("")
    if qual:
        out.append("### Quality drops")
        out.append("| Event | Name | Current rate | Baseline rate | z-score | Current count |")
        out.append("|---|---|---|---|---|---|")
        for a in qual:
            out.append(
                f"| {a['event']} | `{a['name']}` | {a['current_rate']} | "
                f"{a['baseline_rate']} | {a['z']} | {a['current_total']} |"
            )
        out.append("")
    return "\n".join(out)


def _issue_body(anomaly: dict) -> str:
    n = anomaly["name"]
    if anomaly["kind"] == "cliff_drop":
        return (
            f"**Cliff drop** detected for `{n}` ({anomaly['event']}).\n\n"
            f"- Current 7d fires: **{anomaly['current']}**\n"
            f"- Expected (from 30d baseline): **{anomaly['expected']}**\n"
            f"- z-score: **{anomaly['z']}** (threshold {-SIGMA_THRESHOLD})\n"
            f"- Baseline 30d total fires: {anomaly['baseline_total']}\n\n"
            "Possible causes: skill broken, dependency change, tool removed. "
            "Dismiss this issue to suppress further alerts for 14 days.\n"
        )
    if anomaly["kind"] == "quality_drop":
        return (
            f"**Quality drop** detected for `{n}` ({anomaly['event']}).\n\n"
            f"- Current 7d success rate: **{anomaly['current_rate']}**\n"
            f"- Baseline 30d success rate: **{anomaly['baseline_rate']}**\n"
            f"- z-score: **{anomaly['z']}** (threshold {-SIGMA_THRESHOLD})\n"
            f"- Current 7d total fires: {anomaly['current_total']}\n\n"
            "Possible causes: upstream API drift, prompt regression, "
            "auth failure. Dismiss to suppress for 14 days.\n"
        )
    return f"Anomaly for `{n}`: {anomaly}"


def _open_gh_issue(anomaly: dict) -> str | None:
    title = (
        f"[watchdog] {anomaly['kind']}: {anomaly['name']} "
        f"({anomaly['event']}, z={anomaly['z']})"
    )
    body = _issue_body(anomaly)
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
            return result.stdout.strip()  # URL of created issue
        sys.stderr.write(f"gh issue create failed for {anomaly['name']}: {result.stderr}\n")
        return None
    except (subprocess.SubprocessError, OSError) as e:
        sys.stderr.write(f"gh CLI invocation error: {e}\n")
        return None


# ── Entry point ────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Brain Watchdog — Phase B Port 4 (MVP, traces-only).",
        epilog="Default mode is dry-run (prints report). --execute opens gh issues.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually open GitHub issues. Without this flag, prints the report only.",
    )
    parser.add_argument(
        "--no-suppress",
        action="store_true",
        help="Ignore suppressions.json for this run (debugging).",
    )
    args = parser.parse_args(argv)

    anomalies = analyse()

    # Apply suppressions + per-day dedup
    suppressions = {} if args.no_suppress else _load_json(SUPPRESSIONS_FILE, {})
    issues_today = _load_json(ISSUES_TODAY_FILE, {"date": _today_utc(), "names": []})
    if issues_today.get("date") != _today_utc():
        issues_today = {"date": _today_utc(), "names": []}

    actionable: list[dict] = []
    for a in anomalies:
        if _is_suppressed(a["name"], suppressions):
            continue
        if _issue_already_open_today(a["name"], issues_today):
            continue
        actionable.append(a)

    # Always render the report (anomalies + suppressed counts)
    report = _render_markdown(anomalies)
    print("# Watchdog report — " + _today_utc())
    print(f"Mode: **{'EXECUTE' if args.execute else 'dry-run'}**")
    print(f"Anomalies detected: {len(anomalies)}")
    print(f"Actionable after suppression/dedup: {len(actionable)}")
    print()
    print(report)

    if not args.execute:
        if anomalies:
            print("(Dry-run — pass `--execute` to open GitHub issues.)")
        return 0

    # Live mode: open issues
    created = 0
    for a in actionable:
        url = _open_gh_issue(a)
        if url:
            print(f"✓ {a['name']} ({a['kind']}) → {url}")
            issues_today.setdefault("names", []).append(a["name"])
            created += 1
        else:
            print(f"✗ {a['name']} ({a['kind']}) — failed (see stderr)")

    if created:
        _save_json(ISSUES_TODAY_FILE, issues_today)
    print(f"\nCreated {created} issue(s).")
    return 0 if created == len(actionable) else 1


if __name__ == "__main__":
    sys.exit(main())
