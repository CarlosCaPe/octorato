#!/usr/bin/env python3
"""d__posttool__delegation-ledger.py: PostToolUse detector (matcher *) for FLOW.bulk-fetch-delegation.

Appends one JSON line per tool call to the per-session turn ledger
~/.claude/.cache/delegation-ledger/{session_id}.turn.jsonl (sid = payload
session_id, else env CLAUDE_SESSION_ID, else "adhoc"):

  {"tool": <name>, "b": <approx response bytes>}   normal tools
  {"tool": <name>, "delegation": true}             Agent / Task / Workflow

The Stop gate g__stop__delegation-audit.py consumes and truncates this ledger at
turn end. Same side-channel pattern as the grafo turn ledger: PreToolUse cannot
tell main loop from sub-agent (see the FLOW.delegate-gate waiver), but a
Stop-time audit of the whole turn CAN see whether bulk external fetching
happened with zero delegation, because Stop only fires for the main loop.

Always exits 0; never blocks. Fail-silent by design: an observability hook must
never break a tool call.
"""
import json
import os
import sys
from pathlib import Path

DELEGATION_TOOLS = {"Agent", "Task", "Workflow"}


def main() -> int:
    data = json.loads(sys.stdin.read() or "{}")
    tool = data.get("tool_name") or ""
    if not tool:
        return 0
    # payload session_id first: env-less concurrent sessions must not share 'adhoc'
    sid = data.get("session_id") or os.environ.get("CLAUDE_SESSION_ID", "adhoc")
    led = Path.home() / ".claude" / ".cache" / "delegation-ledger" / f"{sid}.turn.jsonl"
    led.parent.mkdir(parents=True, exist_ok=True)
    if tool in DELEGATION_TOOLS:
        rec = {"tool": tool, "delegation": True}
    else:
        try:
            b = len(json.dumps(data.get("tool_response", ""), default=str))
        except Exception:
            b = 0
        rec = {"tool": tool, "b": b}
    with led.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
