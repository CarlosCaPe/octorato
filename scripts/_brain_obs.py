"""
_brain_obs.py — Shared helpers for the brain observability layer.

NOT a CLI. Imported by:
  - trace-hook.py     (Phase A) — capture hook
  - brain-trace.py    (Phase A) — query CLI
  - update_neural_activity.py (Phase A) — Hebbian update
  - watchdog.py       (Phase B) — anomaly detector
  - slos.py           (Phase B) — SLO evaluator
  - skill-cost-profiler.py (Phase B) — cost aggregator
  - brain-digest.py   (Phase C) — daily report
  - brain-chart.py    (Phase C) — charts on demand

The underscore prefix marks this as private — no external consumer should
import it; it exists purely to dedupe ~120 lines of copy-paste across the 8
observability scripts (window parsing, trace iteration, dry-run argparse).

Stdlib only — the observability layer's AC-1 contract.

Conventions enforced by this module:
- All time windows: `<digits><m|h|d|w>` parser, or ISO 8601 UTC. One canon.
- All destructive scripts: `--execute` opt-in (defaults to dry-run). Watchdog
  and SLOs already follow this; this module makes it the standard.
- Trace records iterate from `~/.claude/traces/<YYYY-MM-DD>.jsonl`. Day-file
  filtering skips whole files outside the window for efficiency on 30+ days
  of data.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

TRACES_DIR = Path.home() / ".claude" / "traces"

_WINDOW_RE = re.compile(r"^(\d+)([mhdw])$")
_WINDOW_SECONDS = {"m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_window(s: str | None) -> datetime | None:
    """Parse a window string into a tz-aware UTC datetime cutoff.

    Returns the moment `s` ago from now, or None if `s` is falsy.
    Raises argparse.ArgumentTypeError on invalid input so argparse renders a
    clean error instead of a traceback. Use as `type=parse_window`.

    Accepts: `30m`, `6h`, `7d`, `2w`, or ISO 8601 UTC.
    """
    if not s:
        return None
    m = _WINDOW_RE.match(s)
    if m:
        n, suffix = int(m.group(1)), m.group(2)
        return datetime.now(timezone.utc) - timedelta(seconds=n * _WINDOW_SECONDS[suffix])
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"invalid time value '{s}'. Use 30m / 6h / 7d / 2w, or ISO 8601 UTC."
        )


def parse_record_ts(ts: str) -> datetime | None:
    """Parse a trace record's `ts` field. Returns None on bad input (caller decides)."""
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def iter_trace_records(
    since: datetime | None = None, until: datetime | None = None
) -> Iterator[dict]:
    """Yield trace records from `~/.claude/traces/*.jsonl`, filtered by [since, until).

    Skips files whose stem (YYYY-MM-DD) is entirely outside the window.
    Silently swallows malformed JSON lines (per AC: never block the agent).
    """
    if not TRACES_DIR.exists():
        return
    cutoff_day = since.strftime("%Y-%m-%d") if since else None
    end_day = until.strftime("%Y-%m-%d") if until else None
    for f in sorted(TRACES_DIR.glob("*.jsonl")):
        if cutoff_day and f.stem < cutoff_day:
            continue
        if end_day and f.stem > end_day:
            continue
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                rec_ts = parse_record_ts(rec.get("ts", ""))
                if rec_ts is None:
                    continue
                if since and rec_ts < since:
                    continue
                if until and rec_ts >= until:
                    continue
                yield rec
        except OSError:
            continue


def add_dry_run_args(parser: argparse.ArgumentParser, default_execute: bool = False) -> None:
    """Add the standard `--execute` flag (and `--dry-run` if execute is the default).

    Pattern:
      - Most observability scripts default to dry-run (safe). Pass --execute to
        actually mutate state (open issues, write to neural_activity, etc.).
      - For scripts that *historically* default to execute (e.g.
        update_neural_activity), pass default_execute=True. The flag then
        flips to `--dry-run` (opt-in safety check).

    Resulting `args.execute` is a single boolean callers can use uniformly.
    """
    if default_execute:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview the run without writing state.",
        )
        # The 'execute' boolean is the inverse of --dry-run when default is execute.
        # Resolver below.
        parser.set_defaults(_default_execute=True)
    else:
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Apply the run (writes state / opens issues). Default is dry-run.",
        )
        parser.set_defaults(_default_execute=False)


def resolve_execute(args: argparse.Namespace) -> bool:
    """Return the canonical `execute` boolean given the args produced by add_dry_run_args."""
    default_execute = getattr(args, "_default_execute", False)
    if default_execute:
        return not getattr(args, "dry_run", False)
    return getattr(args, "execute", False)
