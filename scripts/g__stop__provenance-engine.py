#!/usr/bin/env python3
"""Stop gate: a non-trivial reply ships with a Provenance footer that names its Engine.

WHY THIS IS A GATE AND NOT A PROMPT LINE
    Every answer is supposed to end with a Provenance footer (Basis · Engine ·
    Touched · Verified). Until now that requirement was INJECTED into the prompt
    on every turn, so it held only while the model remembered it under load,
    which is exactly the failure class CLAUDE.md names: a rule that depends on
    the model remembering it WILL be skipped.

    The competitive dossier on the @grok bot (2026-09-03) made the contrast
    concrete. Its best-verified defect (3 votes to 0): which model serves the
    bot's answers is not documented in any primary source. Octorato's stance is
    the opposite, "connect, don't fabricate, and say which engine connected",
    but a stance that lives in a prompt injection is a claim, not a property.
    This gate makes it a property: a substantive reply cannot leave without
    naming the engine that produced it.

WHAT COUNTS
    Footer:   a line starting with Provenance / Procedencia / Herkunft and a
              colon (the three labels the spec allows), containing the token
              "Engine". The label anchors at line start with a colon, so the
              word "provenance" inside prose never satisfies it, and "Engine"
              is required INSIDE that line, so a mention elsewhere does not.
    Trivial:  replies under PROSE_FLOOR chars of prose (after stripping code
              fences and inline code) are exempt. "Listo." needs no footer.
    Exempt:   a line containing `provenance-ok` (deliberate: a quoted footer, a
              pure paste-ready block, an explicit operator waiver).

DESIGN CHOICES, STATED SO THEY ARE NOT RE-LITIGATED
    PROSE_FLOOR = 300 is a floor, not a judgment of substance: a 299-char reply
    passes by construction. Real replies of 250-290 chars exist and are usually
    a status line plus one fact; the cost of a missed footer there is low, the
    cost of blocking every short answer is high.
    The label match is case-insensitive; the `Engine` token is case-sensitive.
    The label is a fixed vocabulary of three words; the field name is a proper
    noun in the spec, and matching it exactly keeps "engine" in prose from
    counting.
    Footer POSITION is not enforced here. The paste-ready gate owns ordering
    (footer before the final block); this gate owns existence.

    Loop safety: stop_hook_active=true means we already blocked this turn; one
    forced rewrite, never a loop. Fail-open on any parse or IO error: a broken
    gate must never hold the conversation.

Stdin:  {"transcript_path": str, "stop_hook_active": bool, ...}
Stdout: {"decision": "block", "reason": "..."} on a hit, else nothing.
"""
from __future__ import annotations

import json
import re
import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# A reply shorter than this (prose only) is trivial and needs no footer.
PROSE_FLOOR = 300

_FOOTER = re.compile(r"^\s*(Provenance|Procedencia|Herkunft)\s*:", re.IGNORECASE)
_ENGINE = re.compile(r"\bEngine\b")
_EXEMPT = "provenance-ok"
_FENCE_BLOCK = re.compile(r"```[^\n`]*\n.*?```", re.DOTALL)
_FENCE_TAIL = re.compile(r"```[^\n`]*\n.*\Z", re.DOTALL)
_INLINE = re.compile(r"`[^`\n]*`")


def _tail_lines(path: str, max_bytes: int = 262144) -> list:
    """Only the transcript tail: the last assistant entry lives in the final KBs."""
    import os
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        fh.seek(max(0, size - max_bytes))
        return fh.read().decode("utf-8", errors="replace").splitlines()


def _last_assistant_text(transcript_path: str) -> str:
    """Text blocks of the LAST assistant entry. Stops at that entry whether or
    not it has text, so a final tool call never makes us lint a stale reply."""
    parts: list = []
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
                    parts.append(block.get("text", ""))
        elif isinstance(content, str):
            parts.append(content)
        break
    return "\n".join(parts)


def _prose_only(text: str) -> str:
    text = _FENCE_BLOCK.sub(" ", text)
    text = _FENCE_TAIL.sub(" ", text)
    text = _INLINE.sub(" ", text)
    return text


def verdict(text: str) -> str | None:
    """None when the reply is fine; otherwise the reason it is not."""
    if not text.strip():
        return None
    if any(_EXEMPT in ln for ln in text.splitlines()):
        return None
    prose = _prose_only(text)
    if len(prose.strip()) < PROSE_FLOOR:
        return None  # trivial reply
    # Search the PROSE, not the raw text. Independent QA caught the gap: the
    # length floor was computed on prose while the footer was searched raw, so a
    # footer typed inside a code fence satisfied the gate. A fenced footer is a
    # quotation, and the docstring already said quotations need the waiver.
    footers = [ln for ln in prose.splitlines() if _FOOTER.match(ln)]
    if not footers:
        return "no Provenance footer at all"
    if not any(_ENGINE.search(ln) for ln in footers):
        return "Provenance footer present but it does not name the Engine"
    return None


def main() -> int:
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        return 0
    if data.get("stop_hook_active"):
        return 0
    transcript = data.get("transcript_path") or ""
    if not transcript:
        return 0
    try:
        why = verdict(_last_assistant_text(transcript))
    except Exception:
        return 0
    if not why:
        return 0
    try:
        print(json.dumps({
            "decision": "block",
            "reason": (
                f"🧾 PROVENANCE: this reply is substantive and {why}. Every "
                f"non-trivial answer ends with one line "
                f"'Provenance/Procedencia/Herkunft: Basis … · Engine <model + any "
                f"sub-agent engine> · Touched … · Verified … · Graph …'. Naming "
                f"the engine is the property that separates a connector from a "
                f"bot whose model nobody can name. Add the footer and resend; put "
                f"'{_EXEMPT}' on a line only for a deliberate waiver."
            ),
        }))
    except Exception:
        pass
    return 0


def _selftest() -> int:
    import gate_selftest
    argv = sys.argv
    i = argv.index("--selftest")
    fixture = argv[i + 1] if len(argv) > i + 1 else "registry/fixtures/COMMS.provenance-footer"
    return gate_selftest.run_gate_selftest(__file__, fixture)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
