#!/usr/bin/env python3
"""
trace.py — observability surface 1 — query helper.

Read-only inspector for the JSONL trace files written by trace-hook.py.

Subcommands:
  grep --event <ev> --name <n> --since <window> [--status <s>] [--json]
       Filter records and print as a text table (or raw JSONL with --json).

  top  --by <field> --window <window> [--limit N] [--json]
       Group by a field (default: name), count, sort desc, print top N.

  tail [-n N] [-f]
       Print last N records of today's file (default 10). With -f, follow
       new appends like `tail -f`.

Time windows: 30m, 6h, 7d, 2w (digits + suffix m/h/d/w).

Schema: ~/.claude/schemas/trace-event.schema.json
Storage: ~/.claude/docs/architecture/trace-storage.md
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

from _brain_obs import TRACES_DIR, iter_trace_records, parse_record_ts, parse_window
# Force UTF-8 on stdout/stderr so the ✓ / ✗ / em-dash glyphs in reports
# survive on Windows shells defaulting to cp1252. Without this, a script
# can do its work correctly and still crash with UnicodeEncodeError when
# printing success. Applied repo-wide by _apply-utf8-reconfigure.py.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


# Local idiom — names used below; resolved via the shared lib.
_parse_since = parse_window
_parse_record_ts = parse_record_ts


def _iter_records(since: datetime | None = None) -> Iterator[dict]:
    # Thin wrapper for backwards-compatible signature within this file.
    yield from iter_trace_records(since=since)


def _print_table(records: Iterable[dict], columns: list[str]) -> None:
    rows = []
    for r in records:
        rows.append([str(r.get(c) if r.get(c) is not None else "") for c in columns])
    if not rows:
        print("(no records)")
        return
    widths = [max(len(c), *(len(row[i]) for row in rows)) for i, c in enumerate(columns)]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*columns))
    print(fmt.format(*("-" * w for w in widths)))
    for row in rows:
        print(fmt.format(*row))


def _print_jsonl(records: Iterable[dict]) -> None:
    for r in records:
        print(json.dumps(r, ensure_ascii=False, separators=(",", ":")))


# ── Subcommand: grep ─────────────────────────────────────────────────

def cmd_grep(args: argparse.Namespace) -> int:
    since = args.since  # Already parsed by argparse via type=_parse_since
    matched = []
    for r in _iter_records(since):
        if args.event and r.get("event") != args.event:
            continue
        if args.name and args.name.lower() not in str(r.get("name", "")).lower():
            continue
        if args.status and r.get("status") != args.status:
            continue
        matched.append(r)
    if args.json:
        _print_jsonl(matched)
    else:
        _print_table(matched, ["ts", "event", "name", "status", "task_id"])
        print(f"\n  {len(matched)} record(s)")
    return 0


# ── Subcommand: top ──────────────────────────────────────────────────

def cmd_top(args: argparse.Namespace) -> int:
    since = args.window  # Already parsed by argparse
    counter: Counter[str] = Counter()
    for r in _iter_records(since):
        key = r.get(args.by, "(missing)")
        counter[str(key)] += 1
    items = counter.most_common(args.limit)
    if args.json:
        for key, count in items:
            print(json.dumps({args.by: key, "count": count}))
    else:
        if not items:
            print("(no records)")
            return 0
        kw = max(len(args.by), max(len(k) for k, _ in items))
        print(f"{args.by:<{kw}}  count")
        print(f"{'-' * kw}  -----")
        for key, count in items:
            print(f"{key:<{kw}}  {count}")
        print(f"\n  Total distinct: {len(counter)}, sum: {sum(counter.values())}")
    return 0


# ── Subcommand: tail ─────────────────────────────────────────────────

def _today_file() -> Path:
    return TRACES_DIR / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.jsonl"


def cmd_tail(args: argparse.Namespace) -> int:
    f = _today_file()
    if not f.exists():
        print(f"(no trace file yet: {f})")
        return 0
    if args.follow:
        # Live tail: print existing tail then poll for new lines.
        lines = f.read_text(encoding="utf-8").splitlines()[-args.lines :]
        for line in lines:
            print(line)
        position = f.stat().st_size
        try:
            while True:
                time.sleep(0.5)
                size = f.stat().st_size
                if size > position:
                    with f.open("r", encoding="utf-8") as fh:
                        fh.seek(position)
                        chunk = fh.read()
                    for line in chunk.splitlines():
                        if line.strip():
                            print(line, flush=True)
                    position = size
        except KeyboardInterrupt:
            return 0
    else:
        lines = f.read_text(encoding="utf-8").splitlines()[-args.lines :]
        for line in lines:
            print(line)
    return 0


# ── Entry point ──────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Query the trace JSONL files (observability surface 1).",
        epilog="Time windows: 30m, 6h, 7d, 2w, or ISO 8601 (2026-05-19T00:00Z).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("grep", help="Filter records by event/name/status/since")
    g.add_argument("--event", choices=["skill_fire", "agent_activate", "phase_boundary"])
    g.add_argument("--name", help="Substring match on the name field (case-insensitive)")
    g.add_argument("--status", choices=["ok", "error", "partial"])
    g.add_argument("--since", type=_parse_since, help="Time window (e.g. 30m, 7d) or ISO 8601 UTC")
    g.add_argument("--json", action="store_true", help="Emit raw JSONL instead of table")
    g.set_defaults(func=cmd_grep)

    t = sub.add_parser("top", help="Group records by a field and rank")
    t.add_argument("--by", default="name", help="Field to group by (default: name)")
    t.add_argument("--window", type=_parse_since, default=_parse_since("30d"), help="Time window (default: 30d)")
    t.add_argument("--limit", type=int, default=20, help="Top N results (default: 20)")
    t.add_argument("--json", action="store_true")
    t.set_defaults(func=cmd_top)

    ta = sub.add_parser("tail", help="Show last N records of today's file")
    ta.add_argument("-n", "--lines", type=int, default=10)
    ta.add_argument("-f", "--follow", action="store_true", help="Follow new appends like tail -f")
    ta.set_defaults(func=cmd_tail)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
