#!/usr/bin/env python3
"""
update_neural_activity.py — observability surface 1 — connectome integration.

Reads the JSONL trace files under ~/.claude/traces/ and updates the Hebbian
co-activation matrix in ~/.claude/company/neural_activity.json:

  - For each task_id, find the unique (agent_name, skill_name) pairs that
    co-fired in that task (skill_fire + agent_activate only; phase_boundary
    excluded as noise — 47 phase records per session would dominate).
  - For each pair, increment the matrix edge `<agent>::<skill>`.
  - Apply ~69d half-life decay to ALL existing weights BEFORE incrementing,
    using metadata.traces_last_processed_ts as the reference timestamp.
  - Track which traces have been processed via traces_last_processed_ts
    so re-runs are idempotent.

CLI:
  update_neural_activity.py [--since 7d] [--dry-run] [--verbose]

Schema (input):  ~/.claude/schemas/trace-event.schema.json
Storage layout:  ~/.claude/docs/architecture/trace-storage.md
Target:          ~/.claude/company/neural_activity.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from _brain_obs import iter_trace_records, parse_record_ts, parse_window

NEURAL_ACTIVITY_PATH = Path.home() / ".claude" / "company" / "neural_activity.json"

HALF_LIFE_DAYS = 69.0

# Aliases for local idiom; resolved via the shared lib.
_parse_since = parse_window
_parse_record_ts = parse_record_ts
_iter_records = iter_trace_records


def _now_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _decay_factor(last_update_ts: str | None) -> float:
    # 0.5 ^ (days_since_last / 69)
    if not last_update_ts:
        return 1.0
    last_dt = _parse_record_ts(last_update_ts)
    if not last_dt:
        return 1.0
    days = (datetime.now(timezone.utc) - last_dt).total_seconds() / 86400.0
    if days <= 0:
        return 1.0
    return math.pow(0.5, days / HALF_LIFE_DAYS)


def _co_pairs_per_task(records: list[dict]) -> dict[str, set[tuple[str, str]]]:
    # Group by task_id, collect distinct agent_name and skill_name within each.
    by_task: dict[str, dict[str, set[str]]] = defaultdict(lambda: {"agent": set(), "skill": set()})
    for r in records:
        ev = r.get("event")
        name = r.get("name")
        tid = r.get("task_id")
        if not (ev and name and tid):
            continue
        if ev == "agent_activate":
            by_task[tid]["agent"].add(name)
        elif ev == "skill_fire":
            by_task[tid]["skill"].add(name)
        # phase_boundary skipped by design — too noisy
    pairs_per_task: dict[str, set[tuple[str, str]]] = {}
    for tid, groups in by_task.items():
        pairs = {(a, s) for a in groups["agent"] for s in groups["skill"]}
        if pairs:
            pairs_per_task[tid] = pairs
    return pairs_per_task


def _format_key(agent: str, skill: str) -> str:
    # Matches existing matrix convention: lowercase, slug-style join.
    return f"{agent.strip()}::{skill.strip()}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Update Hebbian co-activation matrix from JSONL traces."
    )
    parser.add_argument(
        "--since",
        type=_parse_since,
        default=_parse_since("7d"),
        help="Time window of traces to ingest (default: 7d). Overridden by metadata.traces_last_processed_ts if newer.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be updated without writing.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Print per-task contributions."
    )
    args = parser.parse_args(argv)

    if not NEURAL_ACTIVITY_PATH.exists():
        print(f"✗ neural_activity.json not found at {NEURAL_ACTIVITY_PATH}", file=sys.stderr)
        return 2
    data = json.loads(NEURAL_ACTIVITY_PATH.read_text(encoding="utf-8"))
    metadata = data.setdefault("metadata", {})
    matrix = data.setdefault("co_activation_matrix", {})
    statistics = data.setdefault("statistics", {})

    # Idempotency: skip records older than the last processed timestamp.
    last_processed_ts = metadata.get("traces_last_processed_ts")
    effective_since = args.since
    if last_processed_ts:
        lp_dt = _parse_record_ts(last_processed_ts)
        if lp_dt and lp_dt > args.since:
            effective_since = lp_dt
    if args.verbose:
        print(f"Effective `since`: {effective_since.isoformat()}")

    # Read traces
    records = list(_iter_records(effective_since))
    print(f"Loaded {len(records)} trace records since {effective_since.isoformat()}")

    pairs_per_task = _co_pairs_per_task(records)
    new_pairs_total = sum(len(p) for p in pairs_per_task.values())
    print(f"  → {len(pairs_per_task)} task(s) with co-activations, {new_pairs_total} pair-fires total")

    if not records:
        print("  Nothing to update.")
        return 0

    # Apply decay to existing matrix
    decay = _decay_factor(last_processed_ts)
    if decay < 1.0:
        print(f"  Decay factor (vs last_processed): {decay:.4f}")
        if not args.dry_run:
            for k in matrix:
                matrix[k] = round(matrix[k] * decay, 4)

    # Increment per-pair counts
    added_edges = 0
    strengthened = 0
    for tid, pairs in pairs_per_task.items():
        if args.verbose:
            print(f"  task {tid[:12]}…: {len(pairs)} pair(s)")
        for agent, skill in pairs:
            key = _format_key(agent, skill)
            if key in matrix:
                matrix[key] += 1
                strengthened += 1
            else:
                matrix[key] = 1.0
                added_edges += 1
            if args.verbose:
                print(f"    {key} → {matrix[key]}")

    # Refresh stats + idempotency marker
    statistics["total_co_activations"] = round(sum(matrix.values()), 4)
    statistics["unique_pairs"] = len(matrix)
    # strongest_pair
    if matrix:
        top = max(matrix.items(), key=lambda kv: kv[1])
        statistics["strongest_pair"] = f"{top[0]} (count={top[1]})"
    metadata["traces_last_processed_ts"] = _now_iso()

    print(f"  +{added_edges} new edge(s), {strengthened} strengthened")
    print(f"  Matrix size: {len(matrix)} unique pairs")
    print(f"  Sum of weights: {statistics['total_co_activations']}")

    if args.dry_run:
        print("\nDRY RUN — no file written.")
        return 0

    NEURAL_ACTIVITY_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"\n✓ Wrote {NEURAL_ACTIVITY_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
