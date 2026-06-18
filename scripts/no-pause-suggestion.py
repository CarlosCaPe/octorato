#!/usr/bin/env python3
"""
Stop hook — block "let's pause / leave for tomorrow / take a break" framing.

The operator has flagged this anti-pattern 3 times in 2 days. Memories
(feedback_do_it_today, execution-bias, do-not-ask-to-pause) sit passively
in context but I keep slipping. This hook enforces the rule at the
runtime layer: scan the assistant's last response for forbidden padding
and surface a correction to stderr (exit 2) so Claude Code feeds it
back to the model.

Triggered: Stop event (after each assistant turn).
Input via stdin: JSON with `transcript_path` (JSONL of the conversation).
"""
from __future__ import annotations

import json
import os
import re
import sys
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



# Patterns that signal paternalistic session-close framing.
# Case-insensitive substring match. Word-boundary-aware where needed.
# Designed to catch padding around a genuine blocker, NOT factual time
# references like "el cron corre a las 6am mañana" or "ayer pasó X".
FORBIDDEN = [
    # Spanish "let's leave it for later"
    r"\bpara\s+ma[ñn]ana\b",
    r"\bpa['\s]+ma[ñn]ana\b",
    r"\blo\s+deja[sm]?\s+pendiente\b",
    r"\bse\s+queda\s+pendiente\b",
    r"\bata(?:c|qu)\w*\s+ma[ñn]ana\b",
    r"\blo\s+ve(?:o|mos|s)?\s+ma[ñn]ana\b",
    r"\bsigues\s+ma[ñn]ana\b",
    r"\bdescansa\b",
    r"\bd[éee]jalo\s+(?:para|pa['\s]?)\s*ma[ñn]ana\b",
    r"\bse\s+queda\s+para\s+ma[ñn]ana\b",
    # English equivalents
    r"\bleave\s+(?:it\s+)?for\s+tomorrow\b",
    r"\bor\s+wait\s+till\s+tomorrow\b",
    r"\bwait\s+until\s+tomorrow\b",
    r"\btake\s+a\s+break\b",
    r"\bor\s+pause\s+for\b",
    r"\bfollow[-\s]up\s+tomorrow\b",
    r"\battack(?:s|ing|ed)?\s+it\s+tomorrow\b",
    # Trailing "or shall we wrap up / or leave it"
    r"\bor\s+(?:do\s+you\s+want\s+to\s+)?(?:wrap\s+(?:up|it\s+up)|leave\s+it)\b",
    # Ambiguous "or X / or Y" patterns at end of message
    r"\bo\s+lo\s+dejas?\s+pendiente\b",
    r"\bo\s+(?:lo\s+)?atacas?\s+ma[ñn]ana\b",
]

COMPILED = [re.compile(p, re.IGNORECASE) for p in FORBIDDEN]

# Asking PERMISSION to perform the obvious next executable step, while a standing
# "cierra todo / no pares hasta terminar" directive is in force. Distinct from a
# genuine fork that needs the operator's decision (that stays allowed, with a
# recommendation). This is the closed set of permission-to-proceed phrasings the
# operator has repeatedly flagged ("¿reescribo? ¿continúo? ¿le doy?").
PERMISSION_ASK = [
    r"¿\s*(?:lo\s+|los\s+|las\s+|la\s+)?reescribo\b",
    r"¿\s*contin[úu]o\b",
    r"¿\s*sigo\b",
    r"¿\s*procedo\b",
    r"¿\s*le\s+doy\b",
    r"¿\s*lo\s+hago(?:\s+ya)?\b",
    r"¿\s*(?:lo|los|las|la)\s+ejecuto\b",
    r"¿\s*(?:lo|los|las|la)\s+escribo\s+ya\b",
    r"\bshall\s+i\s+(?:proceed|continue|rewrite|go\s+ahead)\b",
    r"\b(?:do\s+you\s+)?want\s+me\s+to\s+(?:continue|proceed|rewrite|go\s+ahead)\b",
    r"\bshould\s+i\s+(?:continue|proceed|rewrite|go\s+ahead)\b",
]
COMPILED_PERM = [re.compile(p, re.IGNORECASE) for p in PERMISSION_ASK]


def last_assistant_text(transcript_path: str) -> str:
    """Read the JSONL transcript and return the most recent assistant
    message's text content."""
    p = Path(transcript_path)
    if not p.exists():
        return ""
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except Exception:
        return ""
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        msg = rec.get("message") or {}
        if rec.get("type") == "assistant" or msg.get("role") == "assistant":
            content = msg.get("content") if isinstance(msg, dict) else None
            # content can be a string or a list of blocks
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts: list[str] = []
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "text":
                        parts.append(block.get("text") or "")
                return "\n".join(parts)
    return ""


def main() -> int:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw) if raw else {}
    except Exception:
        data = {}
    transcript_path = data.get("transcript_path") or ""
    if not transcript_path:
        # Nothing to check — exit clean to avoid blocking the loop.
        return 0
    text = last_assistant_text(transcript_path)
    if not text:
        return 0

    perm_hits: list[str] = []
    for pattern in COMPILED_PERM:
        m = pattern.search(text)
        if m:
            perm_hits.append(m.group(0))
    if perm_hits:
        msg = (
            "no-pause-suggestion hook: your reply ENDS BY ASKING PERMISSION to do "
            "the obvious next step (" + ", ".join(repr(h) for h in perm_hits[:4]) +
            "). Under a standing 'cierra todo / no pares hasta terminar' directive "
            "this is the forbidden ask-to-continue. Execute everything that is yours "
            "to execute now; stop ONLY for a genuine missing fact or an irreducible "
            "operator-only act (a payment, a signature, a phone call, a consent click). "
            "Do not ask permission to proceed with work you can already do."
        )
        print(msg, file=sys.stderr)
        return 2

    hits: list[str] = []
    for pattern in COMPILED:
        m = pattern.search(text)
        if m:
            hits.append(m.group(0))

    if not hits:
        return 0

    # Stop-hook policy: exit code 2 surfaces stderr back to the model.
    # The model sees this in the next turn and self-corrects.
    msg = (
        "no-pause-suggestion hook: your last response contains the "
        "forbidden 'leave for tomorrow / take a break / let's pause' "
        "framing. Phrases detected: " + ", ".join(repr(h) for h in hits[:5]) +
        ". The operator has flagged this anti-pattern 3 times. State the "
        "real blocker without 'or wait / or do tomorrow' padding. If "
        "you need operator authorization, say exactly that — do not "
        "offer to defer as an alternative."
    )
    print(msg, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
