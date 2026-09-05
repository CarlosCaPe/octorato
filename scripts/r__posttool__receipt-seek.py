#!/usr/bin/env python3
"""r__posttool__receipt-seek.py: PostToolUse reflex that writes a SEEK receipt.

v7 phase 1 (docs/architecture/v7-nothing-ships-unverified.md). A seek is a
lookup that could refute a claim of fact: chat history, mail history, the
memory graph, the lineage graph. When one runs, this hook records it in the
session ledger with the harness-supplied tool_use_id. The outward-send gate
later accepts the receipt only if that id is a real tool_use in the current
turn of the transcript, so a hand-typed ledger line never counts.

Matched tools (hooks.json matcher): the WhatsApp/Gmail read tools by name, and
Bash when a sub-command, at a command boundary, invokes a memory or chat seek
(query_connectome.py memory, impact-radius.py, sqlite3 on messages.db). The
predicate lives in receipt_ledger.is_seek_tool, shared with the consumers.

Never blocks, never prints. Fail-open on every error.
Stdin: {"session_id", "transcript_path", "tool_name", "tool_input", "tool_use_id", ...}
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def main() -> int:
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        return 0
    name = str(data.get("tool_name", ""))
    inp = data.get("tool_input") or {}
    try:
        import receipt_ledger
    except Exception:
        return 0
    # One predicate, shared with every consumer: a seek tool by name, or a Bash
    # sub-command that invokes a seek at a command boundary (`echo list_messages`
    # and `grep list_messages` are not seeks).
    if not receipt_ledger.is_seek_tool(name, inp):
        return 0
    session_id = data.get("session_id") or os.environ.get("CLAUDE_SESSION_ID") or ""
    if not session_id:
        return 0
    try:
        import receipt_ledger
        query = ""
        if isinstance(inp, dict):
            query = str(inp.get("query") or inp.get("q") or inp.get("command") or "")[:200]
        receipt_ledger.append_session(session_id, {
            "kind": "seek",
            "tool_use_id": data.get("tool_use_id") or "",
            "tool_name": name,
            "query": query,
            "event": data.get("hook_event_name", "PostToolUse"),
        })
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
