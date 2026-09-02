#!/usr/bin/env python3
"""g__stop__unsourced-attribute.py — Stop gate: no unsourced classifying attribute
about the counterpart's property inside an outward draft.

The failure this exists for. A counterpart said, textually and repeatedly, "the
desktop computer at my house". From that CIRCUMSTANCE (where the machine sits)
a categorical ATTRIBUTE was derived and written into a formal consent email:
"your home computer is yours and is personal". She never said personal. The
machine belonged to the firm. That adjective was not decoration: in a consent
document it decides WHO may authorize (if the thing is the person's, the company
cannot consent for her; if it is the company's, its officer can). Inventing it
falsified the document's premise, and it read to her as not being listened to.

Why a gate and not prose. The class was already captured in memory two months
earlier and did not fire, because "do not assume" is not a detectable moment —
there is no instant where the model decides to assume. What IS detectable is the
ADJECTIVE: a word classifying something that belongs to the other party, that
cannot be traced to their own words.

Fires only on the CONJUNCTION of two conditions in the last assistant reply:
  1. an outward-draft marker is present (borrador / para pegar / Asunto: ...) —
     ordinary analysis prose about a client is NOT policed, only what ships;
  2. some sentence asserts a classifying attribute about the counterpart's
     property: a second-person possessive, then a copula, then an ownership or
     nature adjective (personal, privado, tuyo, familiar, corporativo, ...).

What makes a sentence SOURCED (and therefore allowed):
  - the attribute sits inside quoted text (double, curly, guillemet) or a '>'
    blockquote line — those are the counterpart's own words, which is exactly
    the prescribed fix;
  - the sentence is a QUESTION — asking instead of asserting is the other
    prescribed fix.

On a hit, BLOCK once so the adjective is quoted, turned into a question, or cut
before the operator ever sends it.

Loop safety: stop_hook_active=true means we already blocked this turn — pass,
never loop. Fail-open on every error: a broken linter must never hold a
conversation hostage.

Escape hatch: put 'attribute-ok' on a line to keep it deliberately.

Stdin:  {"transcript_path": str, "stop_hook_active": bool, ...}
Stdout: {"decision": "block", "reason": "..."} on a hit, else nothing.
Exit:   always 0.
"""
from __future__ import annotations

import json
import re
import sys
# Force UTF-8 on stdout/stderr so the glyphs in reports survive on Windows
# shells defaulting to cp1252. Applied repo-wide by _apply-utf8-reconfigure.py.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


_FOOTER = re.compile(r"^\s*(Provenance|Procedencia|Herkunft)\s*:", re.IGNORECASE)

# A draft ships INSIDE a fence (the paste-ready-raw rule), so stripping every
# fence would blind this gate to the exact text it polices. Keep PROSE fences,
# drop CODE fences. Same split as the draft-promise sibling.
_FENCE_BLOCK = re.compile(r"```([^\n`]*)\n(.*?)```", re.DOTALL)
_FENCE_TAIL = re.compile(r"```([^\n`]*)\n(.*)\Z", re.DOTALL)
_INLINE = re.compile(r"`[^`\n]*`")
_PROSE_LANGS = {"", "text", "txt", "md", "markdown", "plaintext", "plain",
                "email", "message", "msg", "quote"}

_CODE_SIGNAL = re.compile(
    r"^\s*(#!|import\s|from\s+\S+\s+import\b|def\s|class\s|function\s"
    r"|const\s|let\s|var\s|return\s|SELECT\s|INSERT\s|UPDATE\s|DELETE\s"
    r"|CREATE\s|ALTER\s|\$\s|git\s|cd\s|npm\s|pip\s|python3?\s|docker\s"
    r"|</|<[a-z]+[ >]|[{}])"
    r"|[;{}]\s*$|=>|::|\)\s*\{",
    re.IGNORECASE,
)


def _looks_like_code(body: str) -> bool:
    lines = [ln for ln in body.splitlines() if ln.strip()]
    if not lines:
        return True
    hits = sum(1 for ln in lines if _CODE_SIGNAL.search(ln))
    return hits * 4 >= len(lines)


def _keep_fence(lang: str, body: str) -> str:
    """Fence body when it reads as prose (a draft), empty when it reads as code."""
    if (lang or "").strip().lower() in _PROSE_LANGS and not _looks_like_code(body):
        return "\n" + body + "\n"
    return "\n"


# Condition 1: the reply hands the operator something that goes OUT.
# Deliberately narrow. Analysis prose about a client must stay unpoliced,
# otherwise the gate fires on the very reasoning that catches the error.
_DRAFT_MARKER = re.compile(
    r"(para pegar|p[ée]galo|listo para (pegar|enviar|mandar)|paste[- ]ready"
    r"|ready to (paste|send)|text to send|copy[- ]paste"
    r"|\bborrador\b|\bdraft\b|\baddenda\b"
    r"|te (dejo|paso|propongo) (el|este) (correo|mensaje|texto|borrador)"
    r"|^\s*(asunto|subject)\s*:)",
    re.IGNORECASE | re.MULTILINE,
)

# Condition 2, part A: the thing belongs to the counterpart.
# 'su/sus' is third-person in general Spanish but second-person FORMAL inside an
# outward draft, which is precisely the register this gate polices.
_POSSESSIVE = re.compile(r"\b(tu|tus|su|sus|your)\b", re.IGNORECASE)

_COPULA = re.compile(r"\b(es|son|est[áa]|est[áa]n|is|are|ser[áa]|ser[áa]n)\b",
                     re.IGNORECASE)

# Condition 2, part B: an adjective that CLASSIFIES ownership or nature. Kept
# tight on purpose: this is the class that decides a consent document's premise.
# Condition adjectives (viejo, nuevo, lento) are left out — they add false
# positives without carrying the legal weight that made this rule necessary.
_ATTRIBUTE = re.compile(
    r"\b(personal(?:es)?|privad[oa]s?|t?uy[oa]s?|suy[oa]s?|propi[oa]s?"
    r"|particular(?:es)?|familiar(?:es)?|dom[ée]stic[oa]s?|compartid[oa]s?"
    r"|corporativ[oa]s?|empresarial(?:es)?|laboral(?:es)?"
    r"|private|yours|domestic|corporate|shared|work[- ]issued|company[- ]owned)\b",
    re.IGNORECASE,
)

# Quoted spans and blockquotes carry the COUNTERPART's own words. An attribute
# they themselves stated is sourced, which is the whole point: quote it and ship.
# Not single quotes / apostrophes (they wrap contractions).
_QUOTED = re.compile(r'"[^"]*"|[“”][^“”]*[“”]|«[^»]*»', re.DOTALL)

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
    """Text blocks of the LAST assistant entry. Stops at that entry whether or
    not it has text: falling through to an OLDER message lints a stale reply."""
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
    text = _FENCE_BLOCK.sub(lambda m: _keep_fence(m.group(1), m.group(2)), text)
    tail = _FENCE_TAIL.search(text)
    if tail:
        text = text[:tail.start()] + _keep_fence(tail.group(1), tail.group(2))
    text = _INLINE.sub("", text)
    kept = [
        ln for ln in text.splitlines()
        if not _FOOTER.match(ln)
        and "attribute-ok" not in ln
        and not ln.lstrip().startswith(">")  # blockquote = their words
    ]
    return "\n".join(kept)


def find_attributes(text: str) -> list:
    """Sentences asserting a classifying attribute about the counterpart's
    property, with no quote backing it and not phrased as a question."""
    hits = []
    text = _QUOTED.sub(" ", text)
    for sentence in _SENTENCE_SPLIT.split(text):
        s = sentence.strip()
        if not s:
            continue
        # Asking instead of asserting is the prescribed fix, so it must pass.
        if "?" in s or "¿" in s:
            continue
        poss = _POSSESSIVE.search(s)
        attr = _ATTRIBUTE.search(s)
        if not poss or not attr:
            continue
        # The possessive must introduce the thing being classified, so the
        # attribute has to come after it. "es personal, tu decides" is not a
        # claim about her property.
        if poss.start() >= attr.start():
            continue
        if not _COPULA.search(s[poss.end():attr.start()] or s):
            continue
        hits.append(f"{poss.group(0)} … {attr.group(0)}")
    return hits


def main() -> int:
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        return 0

    if data.get("stop_hook_active"):
        # One-shot contract: set true on the Stop event AFTER our block.
        # Intended: one forced rewrite per turn, never a loop.
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
        attrs = find_attributes(text)
    except Exception:
        return 0  # fail-open: a broken linter never holds the conversation

    if not attrs:
        return 0

    listing = "; ".join(f"«{frag}»" for frag in attrs[:6])
    extra = f" (+{len(attrs) - 6} más)" if len(attrs) > 6 else ""
    try:
        print(json.dumps({
            "decision": "block",
            "reason": (
                f"🏷 ATRIBUTO-SIN-FUENTE: tu borrador clasifica algo de la contraparte "
                f"con un adjetivo que ella no dijo ({listing}{extra}). Una circunstancia "
                f"(dónde está, quién lo usa) no autoriza la categoría (de quién es, qué "
                f"es), y en un consentimiento ese adjetivo decide QUIÉN firma. Para cada "
                f"uno: pega su frase textual, conviértelo en pregunta dentro del mismo "
                f"mensaje, o quítalo. Nunca viaja adentro. Para dejarlo a propósito, pon "
                f"'attribute-ok' en la línea. Ver CLAUDE.md 'Unsourced-attribute'."
            ),
        }))
    except Exception:
        pass
    return 0


def _selftest() -> int:
    import gate_selftest
    argv = sys.argv
    fixture = argv[argv.index("--selftest") + 1] if len(argv) > argv.index("--selftest") + 1 \
        else "registry/fixtures/COMMS.unsourced-attribute"
    return gate_selftest.run_gate_selftest(__file__, fixture)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
