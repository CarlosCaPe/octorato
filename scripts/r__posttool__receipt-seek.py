#!/usr/bin/env python3
"""r__posttool__receipt-seek.py: PostToolUse reflex that writes a SEEK receipt.

v7 phase 1 (docs/architecture/v7-nothing-ships-unverified.md). A seek is a
lookup that could refute a claim of fact: chat history, mail history, the
memory graph, the lineage graph. When one runs, this hook records it in the
session ledger with the harness-supplied tool_use_id. The outward-send gate
later accepts the receipt only if that id is a real tool_use in the current
turn of the transcript, so a hand-typed ledger line never counts.

Matched tools (hooks.json matcher): the WhatsApp/Gmail read tools by name, and
Bash when the command invokes a memory or chat seek (query_connectome memory,
list_messages, the support-bridge messages.db, impact-radius).

Never blocks, never prints. Fail-open on every error.
Stdin: {"session_id", "transcript_path", "tool_name", "tool_input", "tool_use_id", ...}
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_SEEK_TOOL = re.compile(
    r"(list_messages|get_message_context|get_chat|get_direct_chat_by_contact"
    r"|get_last_interaction|search_emails|search_threads|get_thread|read_email"
    r"|get_message|list_chats)$",
    re.IGNORECASE,
)
_SEEK_CMD = re.compile(
    r"(query_connectome\.py\s+memory|impact-radius\.py|list_messages|messages\.db"
    r"|search_emails|sqlite3\s+\S*messages)",
    re.IGNORECASE,
)


def main() -> int:
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        return 0
    name = str(data.get("tool_name", ""))
    inp = data.get("tool_input") or {}
    is_seek = bool(_SEEK_TOOL.search(name))
    if not is_seek and name == "Bash":
        is_seek = bool(_SEEK_CMD.search(str(inp.get("command", ""))))
    if not is_seek:
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
