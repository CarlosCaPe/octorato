#!/usr/bin/env python3
"""r__stop__friction-ledger.py: Stop reflex that keeps the Friction_Ledger current (v10 FR-01, AC-01).

At every Stop it reads what the harness appended to this session's transcript
(and to each of its subagent transcripts) since the last Stop, and hands the
new bytes to `friction_ledger.ingest_paths()`: every PreToolUse deny and every
Stop block recorded there becomes one ledger line, with no gate body changed.

A Stop block of THIS stop is not in the transcript yet (the harness writes the
`hook_blocking_error` attachment after the hooks return), so it is ledgered at
the next Stop, which a block always causes.

Never blocks, never prints, exits 0 on every path, including a crash: this is a
recorder on the Stop hot path, and a recorder that can stop a turn is a gate
nobody reviewed. Cost: incremental, only the bytes since the previous Stop are
read, and at most MAX_BYTES_PER_STOP per Stop, so a session that predates the
ledger is caught up over several Stops (offsets advance over whole lines only).

Stdin: the Stop payload {"session_id", "transcript_path", ...}. Stdout: nothing.
"""
from __future__ import annotations

import json
import os
import sys

# A session that predates the ledger is caught up in chunks, one per Stop, so
# no single Stop pays for the whole history. Measured 2026-10-06 on a 76 MB
# session with its subagent transcripts, subprocess wall incl. interpreter,
# idle laptop: first Stop 0.27 s median of 5 (0.45 max), later Stops 0.13 s
# median of 20 (0.48 max while still catching up). Uncapped, the first Stop
# cost 1.26 s.
MAX_BYTES_PER_STOP = 24 * 1024 * 1024


def main() -> int:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        tp = payload.get("transcript_path") or ""
        if not tp:
            return 0
        tp = os.path.expanduser(tp)
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import friction_ledger
        friction_ledger.ingest_paths(
            friction_ledger.session_paths(tp, payload.get("session_id") or ""),
            max_bytes=MAX_BYTES_PER_STOP)
    except Exception:  # noqa: BLE001 - a recorder never fails the turn
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
