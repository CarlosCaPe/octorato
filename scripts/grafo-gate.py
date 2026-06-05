#!/usr/bin/env python3
"""PreToolUse Bash hook — the forcing function for graph-before-grep.

When a Bash command is an impact-shaped SCAN of the brain (a recursive grep/rg over
~/.claude surfaces — NOT a one-off content grep, NOT `git log --grep`), this RECORDS
the scan to the per-turn ledger and injects a "¿y el grafo?" reminder. The Stop hook
(grafo-ledger-check) later decides — off the hot path — whether the scanned concept was
one the graph already KNOWS (then it nudges the model to seek) or an unlit cold-start
(legitimate, never nudged).

Design: this hook is FAST (no seek here — just a regex + a ledger append) and FAIL-OPEN.
It NEVER denies a command; a broken hook must not break the user's bash.
"""
import os
import re
import sys
import json
from pathlib import Path
# Force UTF-8 on stdout/stderr so the ✓ / ✗ / em-dash glyphs in reports
# survive on Windows shells defaulting to cp1252. Without this, a script
# can do its work correctly and still crash with UnicodeEncodeError when
# printing success. Applied repo-wide by _apply-utf8-reconfigure.py.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


LEDGER = Path.home() / ".claude" / ".cache" / "graph-ledger"


def turn_file():
    sid = os.environ.get("CLAUDE_SESSION_ID", "adhoc")
    return LEDGER / f"{sid}.turn.jsonl"


def is_brain_scan(cmd: str) -> bool:
    if not re.search(r"\b(grep|rg)\b", cmd):
        return False
    if "git log" in cmd or "git grep" in cmd:
        return False  # git's own index, legitimate
    # recursive scan only (grep -r / -rl / -rn / -ril, or ripgrep)
    if not (re.search(r"\bgrep\b[^|]*\s-[a-zA-Z]*r", cmd) or re.search(r"\brg\b", cmd)):
        return False
    # targeting a brain surface?
    return bool(re.search(r"~/\.claude|\$HOME/\.claude|/\.claude/|(?<![\w/])skills/|(?<![\w/])agents/|CLAUDE\.md", cmd))


def extract_term(cmd: str):
    m = re.search(r"""(?:grep|rg)\b[^'"]*?['"]([^'"]+)['"]""", cmd)
    return m.group(1) if m else None


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    cmd = (data.get("tool_input", {}) or {}).get("command", "") or ""
    if not is_brain_scan(cmd):
        return 0
    term = extract_term(cmd) or "?"
    try:
        tf = turn_file()
        tf.parent.mkdir(parents=True, exist_ok=True)
        with tf.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"event": "brain_scan", "term": term}) + "\n")
    except OSError:
        pass
    # Best-effort nudge (harmless if the harness ignores additionalContext on PreToolUse).
    try:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": (
                f"♦ ¿y el grafo? You are SCANNING the brain (grep '{term}'). If the graph "
                f"knows this, SEEK instead: impact-radius.py \"{term}\" (surfaces) or "
                f"query_connectome.py query \"{term}\" (skills/agents) — deterministic, ~100x cheaper."
            ),
        }}))
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # fail-open: never break the user's command
