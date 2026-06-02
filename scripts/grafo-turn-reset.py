#!/usr/bin/env python3
"""UserPromptSubmit hook — reset the per-turn graph ledger.

The Stop-hook teeth (grafo-ledger-check) judge graph-before-grep behaviour for the
CURRENT turn, not the whole session. Truncating the per-turn ledger at the start of
each turn gives those teeth a clean, turn-scoped ground truth. Fail-open and silent.
"""
import os
from pathlib import Path

sid = os.environ.get("CLAUDE_SESSION_ID", "adhoc")
f = Path.home() / ".claude" / ".cache" / "graph-ledger" / f"{sid}.turn.jsonl"
try:
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("", encoding="utf-8")
except OSError:
    pass
