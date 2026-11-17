#!/usr/bin/env python3
"""UserPromptSubmit hook — reset the per-turn graph ledger.

The Stop-hook teeth (grafo-ledger-check) judge graph-before-grep behaviour for the
CURRENT turn, not the whole session. Truncating the per-turn ledger at the start of
each turn gives those teeth a clean, turn-scoped ground truth. Fail-open and silent.

It also consumes the advisory grafo-ledger-check.py left at the last Stop
(`<sid>.advisory.txt`) and hands it to the model as additionalContext, so the
advisory reaches the agent without a systemMessage on the operator's screen. The
file is keyed by the payload's `session_id` (env CLAUDE_SESSION_ID as fallback);
with no real session id nothing is read or relayed, so one session's advisory
never reaches another. An unreadable or undecodable file is deleted anyway.
"""
import json
import os
from pathlib import Path
import sys

# Force UTF-8 on stdout/stderr so the ✓ / ✗ / em-dash glyphs in reports
# survive on Windows shells defaulting to cp1252. Without this, a script
# can do its work correctly and still crash with UnicodeEncodeError when
# printing success. Applied repo-wide by _apply-utf8-reconfigure.py.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


sid = os.environ.get("CLAUDE_SESSION_ID", "adhoc")
f = Path.home() / ".claude" / ".cache" / "graph-ledger" / f"{sid}.turn.jsonl"
try:
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("", encoding="utf-8")
except OSError:
    pass


def payload_session_id(raw: str) -> str:
    """The hook payload's session_id, or "" when absent or unparsable."""
    try:
        data = json.loads(raw) if raw and raw.strip() else {}
    except ValueError:
        return ""
    got = data.get("session_id") if isinstance(data, dict) else ""
    return got.strip() if isinstance(got, str) else ""


try:
    _raw = "" if sys.stdin is None or sys.stdin.isatty() else sys.stdin.read()
except (OSError, ValueError):
    _raw = ""
adv_sid = payload_session_id(_raw) or os.environ.get("CLAUDE_SESSION_ID", "").strip()
text = ""
if adv_sid and adv_sid != "adhoc" and "/" not in adv_sid and "\\" not in adv_sid:
    adv = f.parent / f"{adv_sid}.advisory.txt"
    if adv.exists():
        try:
            text = adv.read_text(encoding="utf-8").strip()
        except (OSError, ValueError):
            text = ""
        finally:
            try:
                adv.unlink()
            except OSError:
                pass
if text:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                             "additionalContext": text}}))
