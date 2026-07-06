#!/usr/bin/env python3
"""g__stop__draft-promise.py — Stop gate: no future-tense promises in paste-ready drafts.

Operator directive (2026-07-06, repeated): any paste-ready draft message handed
to the operator must NOT contain first-person future commitments ("I'll check X
and get back", "voy a revisar y te digo"). The work must be done (or disproven)
BEFORE drafting, so messages ship with everything possible already done. A
promise in a draft is deferred work the operator then has to carry; a receipt
(data found, or a verified blocker) is the deliverable.

Fires only on the CONJUNCTION of two conditions in the last assistant reply:
  1. a paste-draft marker is present ("listo para pegar", "paste-ready", ...)
  2. after stripping non-prose, some sentence carries a first-person future
     commitment — and that sentence does NOT also carry an offer/conditional
     marker ("happy to pair if you want" is an offer, not a promise; offers
     are fine, promises are not).

On a hit, BLOCK once so the model executes (or disproves) the promised action
and rewrites the draft around the RESULT before the operator ever sees it.

Loop safety: payload field stop_hook_active=true means we already blocked this
turn — pass, never loop. Fail-open on every error: a broken linter must never
hold a conversation hostage.

What gets stripped before matching (not prose):
  - fenced code blocks (``` ... ```)
  - inline code spans (`...`)
  - the Provenance/Procedencia/Herkunft footer line (machine receipt, exempt)
  - lines containing 'draft-promise-ok' (deliberate quotation / exemption)

Stdin:  {"transcript_path": str, "stop_hook_active": bool, ...}
Stdout: {"decision": "block", "reason": "..."} on a hit, else nothing.
Exit:   always 0.
"""
from __future__ import annotations

import json
import re
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


_FOOTER = re.compile(r"^\s*(Provenance|Procedencia|Herkunft)\s*:", re.IGNORECASE)
_FENCE = re.compile(r"```.*?```", re.DOTALL)
_INLINE = re.compile(r"`[^`\n]*`")

# Condition 1: the reply hands the operator a paste-ready draft.
_DRAFT_MARKER = re.compile(
    r"(para pegar|p[ée]galo|listo para (pegar|enviar)|paste[- ]ready"
    r"|ready to (paste|send)|text to send|copy[- ]paste)",
    re.IGNORECASE,
)

# Condition 2: a sentence carries a first-person future commitment.
_PROMISE = re.compile(
    r"\bI['’]?ll\s+\w+"
    r"|\bI\s+will\s+\w+"
    r"|\bI['’]?m\s+going\s+to\b"
    r"|\bgoing to (check|pull|verify|review|look)\b"
    r"|\b(get|come|circle)\s+back\s+to\s+you\b"
    r"|\bfollow\s+up\s+(with|on)\b"
    r"|\bvoy\s+a\s+\w+"
    r"|\bluego\s+te\s+\w+"
    r"|\bte\s+(confirmo|aviso|digo)\s+(luego|despu[ée]s|m[áa]s tarde)\b",
    re.IGNORECASE,
)

# Offers/conditionals are fine; only unconditional promises block.
_EXEMPT = re.compile(
    r"(happy to|glad to|if you (want|agree|prefer|need)|if the team"
    r"|let me know|si (quieres|prefieres|el equipo|gustas)|dime y"
    r"|can join|puedo )",
    re.IGNORECASE,
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def _tail_lines(path: str, max_bytes: int = 262144) -> list:
    """Read only the transcript tail: the last assistant entry lives in the
    final KBs, and late-session transcripts run tens of MB."""
    import os
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        fh.seek(max(0, size - max_bytes))
        return fh.read().decode("utf-8", errors="replace").splitlines()


def _last_assistant_text(transcript_path: str) -> str:
    """Text blocks of the LAST assistant entry in the JSONL. Stops at that
    entry whether or not it has text: falling through to an OLDER message
    lints a stale reply, producing spurious blocks when the final action was
    a tool call."""
    text_parts: list = []
    try:
        lines = _tail_lines(transcript_path)
    except OSError:
        return ""
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "assistant":
            continue
        content = (entry.get("message") or {}).get("content") or []
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
        elif isinstance(content, str):
            text_parts.append(content)
        break  # ALWAYS stop at the last assistant entry, text or not
    return "\n".join(text_parts)


def _strip_non_prose(text: str) -> str:
    text = _FENCE.sub("", text)
    # Unclosed trailing fence: drop it and everything after, else its code
    # content gets matched as prose and false-blocks.
    text = re.sub(r"```.*", "", text, flags=re.DOTALL)
    text = _INLINE.sub("", text)
    kept = [
        ln for ln in text.splitlines()
        if not _FOOTER.match(ln) and "draft-promise-ok" not in ln
    ]
    return "\n".join(kept)


def find_promises(text: str) -> list:
    """Promise fragments in sentences that carry no offer/conditional marker."""
    hits = []
    for sentence in _SENTENCE_SPLIT.split(text):
        if not sentence.strip():
            continue
        m = _PROMISE.search(sentence)
        if m and not _EXEMPT.search(sentence):
            hits.append(m.group(0))
    return hits


def main() -> int:
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        return 0

    if data.get("stop_hook_active"):
        # One-shot contract: Claude Code sets this true on the Stop event
        # AFTER our block. Intended: one forced rewrite per turn, never a loop.
        return 0

    transcript = data.get("transcript_path") or ""
    if not transcript:
        return 0

    try:
        text = _strip_non_prose(_last_assistant_text(transcript))
        if not text.strip():
            return 0
        if not _DRAFT_MARKER.search(text):
            return 0
        promises = find_promises(text)
    except Exception:
        return 0  # fail-open: a broken linter never holds the conversation

    if not promises:
        return 0

    listing = "; ".join(f"…{frag[:60]}…" for frag in promises[:6])
    extra = f" (+{len(promises) - 6} more)" if len(promises) > 6 else ""
    try:
        print(json.dumps({
            "decision": "block",
            "reason": (
                f"✍ DRAFT-PROMISE: a paste-ready draft in your reply promises future "
                f"work ({listing}{extra}). Execute or disprove that action NOW, then "
                f"rewrite the draft around the RESULT (data found, or a verified "
                f"blocker). Messages ship with everything possible already done. "
                f"Offers stay ('happy to pair if you want'); promises go. See "
                f"feedback_dont_stop_on_readonly_next_step (drafted-message corollary)."
            ),
        }))
    except Exception:
        pass
    return 0


def _selftest() -> int:
    import gate_selftest
    argv = sys.argv
    fixture = argv[argv.index("--selftest") + 1] if len(argv) > argv.index("--selftest") + 1 \
        else "registry/fixtures/COMMS.deliverable-complete-before-send"
    return gate_selftest.run_gate_selftest(__file__, fixture)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
