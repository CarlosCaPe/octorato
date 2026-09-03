#!/usr/bin/env python3
"""g__stop__unsourced-attribute.py — Stop gate: no unsourced classifying attribute
about the counterpart's property in anything that ships outward.

THE FAILURE THIS EXISTS FOR
A counterpart said, textually and repeatedly, "the desktop computer at my house".
From that CIRCUMSTANCE (where the machine sits) a categorical ATTRIBUTE was
derived and written into a formal consent email: "your home computer is yours and
is personal". She never said personal; the machine belonged to her firm. In a
consent document that adjective is not decoration: it decides WHO may authorize
(if the thing is the person's, the company cannot consent for her; if it is the
company's, its officer can). Inventing it falsified the document's premise, and
it read to her as not being listened to.

WHY A GATE AND NOT PROSE
The class sat in memory for two months without firing, because "do not assume"
names no detectable moment. The ADJECTIVE is one.

WHY THIS IS A REWRITE (v4)
v1 anchored on a copula: possessive -> "es" -> adjective. Independent review found
that anchor is simply wrong. The most natural phrasing of the very incident it
memorializes, "tu computadora personal de casa", is ATTRIBUTIVE and carries no
copula at all, so v1 passed it. v1 also read only text blocks of the last
assistant entry, which is blind to a draft composed inside a tool call, and that
is exactly how email ships here. Meanwhile a bare "borrador" anywhere flipped it
on, so it blocked the analysis prose that DIAGNOSES the error.

v2 fixed the anchor but shipped a worse bug: it walked back through the
transcript and stopped at the first `type:"user"` entry, on the assumption that
those are human prompts. Measured on a real session transcript, 656 of 764 user
entries are TOOL RESULTS and only 108 are prompts. So the walk halted at the last
tool result, and both of v2's headline fixes (tool-call scanning, multi-entry
scanning) never ran in production. The v2 selftest stayed green because its
fixtures used entry shapes the system never emits: a green proof over a dead
path, which is precisely what the fixture discipline exists to prevent. Every
fixture here is now built from real transcript shapes, tool_result entries and
all.

v3 kept the PROXIMITY anchor and rebuilt around it; v4 adds condition 3:

  Condition 1 (delivery). Something in this turn goes outward: a handover marker
    in delivery position (a line that ends in ':' introducing the text, or an
    explicit paste phrase), a prose fence, or a tool call to a known send/draft
    tool. A bare mention of "borrador" mid-sentence is NOT delivery.

  Condition 2 (unsourced attribution). Inside that outward text, a second-person
    possessive and an ownership/nature category word occur within WINDOW
    characters of each other, in EITHER order, with no verb requirement. This
    catches attributive, predicative, fronted, cross-sentence, and any verb
    ("resulta ser", "se considera", "era") in one rule.

Sourcing exemptions, each being one of the two prescribed fixes:
  - the span sits inside a SUBSTANTIAL quotation (>= MIN_QUOTE chars) or a '>'
    blockquote: those are the counterpart's own words. A one-word scare quote
    ("personal") is not a citation and does not exempt.
  - the sentence is genuinely INTERROGATIVE (opens with ¿ or an interrogative
    head and ends in '?'). A tag question ("..., de acuerdo?") still asserts, so
    it does not exempt.
  - a first-person possessive between the two anchors means the sentence turned
    to the writer's own things ("Para tu tranquilidad: mi equipo es privado").

v4 NARROWS THE SCOPE, and that is the most important line in this file
v3 policed any second-person category word in anything outward. Measured against
a battery of ordinary support drafts, it blocked 9 of 10: "tu licencia es
empresarial", "tu calendario ya es privado", "tu buzón es compartido con
recepción". At that rate a person disarms the gate, and a disarmed gate misses
everything. The v3 answer to this was an exemption for a narrated first-person
act, which review showed launders real violations the moment an unrelated action
shares the sentence ("Ayer instalé el agente y tu computadora de casa es
personal"). Exemptions were the wrong lever.

The right one was scope. The rule was never "police every adjective"; it is that
this adjective DECIDES WHO MAY AUTHORIZE. So a third condition now applies: the
text must also be asking for, granting, or documenting authorization
(_CONSENT_CONTEXT). "Tu licencia es empresarial" decides nothing and is none of
the gate's business. "Te pido tu permiso ... tu computadora es personal" decides
who signs, and is the incident. The same battery now blocks 1 of 10, and that one
literally says "contrato".

WHAT THIS DELIBERATELY GIVES UP
An unsourced category about the counterpart's property, OUTSIDE any authorization
context, now ships unblocked. That is a real hole and it is chosen: outside a
consent document the adjective is usually an operational fact the writer
established himself, and the cost of policing it (a disarmed gate) exceeds the
cost of missing it. If the class ever bites outside consent, widen
_CONSENT_CONTEXT rather than removing the condition.

REMAINING FALSE POSITIVE, accepted: a message that merely mentions a contract
while stating a category ("Tu contrato es laboral, así que el equipo va por
inventario"). One rewrite or one 'attribute-ok'. Against a falsified consent
document reaching a client, that is the cheap side of the trade.

Loop safety: stop_hook_active=true means we already blocked this turn. Fail-open
on every error: a broken linter must never hold a conversation hostage.

Escape hatch: put 'attribute-ok' on a line to keep it deliberately.

Stdin:  {"transcript_path": str, "stop_hook_active": bool, ...}
Stdout: {"decision": "block", "reason": "..."} on a hit, else nothing.
Exit:   always 0.
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


# How close the possessive and the category word must be to count as one claim.
# 120 chars spans an adjacent sentence pair without joining distant mentions.
WINDOW = 120
# A quotation shorter than this is a scare quote, not a citation, so it does not
# launder an unsourced attribute. Sized above a quoted word or two.
MIN_QUOTE = 25

_FOOTER = re.compile(r"^\s*(Provenance|Procedencia|Herkunft)\s*:", re.IGNORECASE)

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

# Tools whose arguments ARE an outward message. v1 was blind to these, which is
# the path the motivating incident actually took (a formal email via the mail MCP).
_SEND_TOOL = re.compile(
    r"(send_message|send_email|draft_email|create_draft|update_draft|reply"
    r"|forward|send_file|send_audio_message|wa-soporte)",
    re.IGNORECASE,
)
# Argument keys that carry human-readable body text in those tools.
_BODY_KEYS = ("body", "message", "text", "content", "html", "snippet",
              "caption", "subject", "description", "title")

# Delivery in POSITION, not a bare mention. Either an explicit paste phrase, or a
# handover line that ENDS in a colon (the shape that actually introduces a draft).
_PASTE_PHRASE = re.compile(
    r"(para pegar|p[ée]galo|listo para (pegar|enviar|mandar)|paste[- ]ready"
    r"|ready to (paste|send)|text to send|copy[- ]paste"
    r"|puedes (mandarle|enviarle|pasarle) esto|m[áa]ndale esto"
    # up to two words may sit between the verb and the noun ("te dejo ABAJO el
    # mensaje"); one adverb used to defeat the whole condition.
    r"|te (dejo|paso|propongo)(?:\s+\w+){0,2}\s+(el|este|la|esta)?\s*"
    r"(correo|mensaje|texto|borrador|respuesta|nota))",
    re.IGNORECASE,
)
_HANDOVER_LINE = re.compile(
    r"^\s*(?:[^\n]{0,80}\b(borrador|draft|correo|mensaje|texto|carta|addenda"
    r"|email|message|asunto|subject|respuesta|reply|nota|note)\b[^\n]{0,80}):\s*$",
    re.IGNORECASE | re.MULTILINE,
)
# A colon header can equally introduce ANALYSIS about a message, and structured
# lists are the house style for that. "Puntos que corregí del correo:" is not a
# hand-over, and treating it as one re-admits the v1 false positive where the
# reply diagnosing the error got blocked for quoting it.
_ANALYSIS_HEADER = re.compile(
    r"\b(puntos?|errores?|hallazgos?|correcciones?|revisi[óo]n"
    r"|an[áa]lisis|issues?|findings?|corrections?|review)\b"
    r"|\b(pasos?|instrucciones|gu[íi]a|checklist|steps?|how\s+to)\b"
    r"|\b(corrig[íi]|revis[ée]|encontr[ée]|detect[ée]|found|fixed|reviewed)\b",
    re.IGNORECASE,
)

# SCOPE, added in v4 after measurement. Condition 1 used to be "anything that
# ships outward", and a battery of ordinary support drafts showed the cost: 9 of
# 10 benign messages blocked ("tu licencia es empresarial", "tu calendario ya es
# privado"). A gate at that rate gets disarmed, and a disarmed gate misses 100%.
# The rule it enforces was never that broad: the adjective matters because it
# decides WHO MAY AUTHORIZE. So the text must also be asking for, granting, or
# documenting authorization. "Tu licencia es empresarial" decides nothing and is
# none of the gate's business; "te pido tu permiso ... tu computadora es
# personal" decides who signs, which is the incident.
_CONSENT_CONTEXT = re.compile(
    r"\b(permiso|permisos|autoriza(?:ci[óo]n|r|s|do|da)?|consentimiento|consiente"
    r"|contrato|contractual|addenda|adenda|cl[áa]usula|anexo|convenio|acuerdo"
    r"|firmar?|firmas?|firmado|titular|responsabilidad legal"
    r"|permission|authoriz(?:e|es|ed|ation)|consent|contract|addendum|clause"
    r"|agreement|sign(?:s|ed)?\s+off|liability|data\s+processing)\b"
    r"|\b(a\s+ti\s+y\s+no\s+al?|directamente\s+a\s+ti|en\s+tu\s+nombre"
    r"|qui[ée]n\s+(?:firma|autoriza)|rather\s+than\s+the\s+(?:firm|company|office)"
    r"|not\s+the\s+(?:firm|company)|on\s+your\s+behalf|who\s+(?:signs|authorizes))\b",
    re.IGNORECASE,
)

_POSSESSIVE = re.compile(r"\b(tu|tus|su|sus|your)\b", re.IGNORECASE)
# A switch PREDICATES something of the new subject; an appositive only renames
# the old one. To a regex they look identical, and the verb is what separates
# them: ", el relay del servicio ES privado" switches, ", un equipo personal,"
# does not. Without this, killing the appositive miss re-opens the pair-join
# false positive, and vice versa.
_PREDICATES = re.compile(
    r"\b(es|son|est[áa]|est[áa]n|era|eran|fue|fueron|ser[áa]|resulta|parece"
    r"|is|are|was|were|becomes?|seems?)\b", re.IGNORECASE)
# When the attribute comes BEFORE the possessive, it may already belong to its
# own determiner-headed subject ("El repositorio del proyecto es privado, te
# agrego con tu cuenta"): two unrelated claims that "either order" would fuse.
_OWN_SUBJECT = re.compile(
    r"\b(el|la|los|las|un|una|unos|unas|the|an?)\s+"
    r"(?!de[l]?\b|que\b|cual\b|of\b|that\b|which\b)\w+", re.IGNORECASE)
# Two ways a sentence stops being about the counterpart's property between the
# anchors, both found by review as real false positives:
#   (a) it turns to the writer's own things ("mi equipo es privado");
#   (b) the subject switches to a DIFFERENT noun phrase after a comma
#       ("Para tu tranquilidad, el relay que monté es privado") — there the
#       possessive attaches to "tranquilidad" and the attribute to "el relay".
# (b) requires the comma: "tu computadora de la oficina es personal" has a
# determiner too, but no clause break, and must still fire.
_FIRST_PERSON = re.compile(
    r"\b(mi|mis|mío|mia|m[íi]os?|m[íi]as?|nuestr[oa]s?|my|our|ours|yo)\b",
    re.IGNORECASE,
)
# The word after the determiner must be a real noun head, not a preposition or
# relative: "Tu computadora, la de casa, es personal" is an APPOSITIVE naming the
# same machine (and the incident's own phrasing), so it must still fire, while
# "Para tu tranquilidad, el relay que monté es privado" genuinely switches.
_SUBJECT_SWITCH = re.compile(
    r",\s*(el|la|los|las|un|una|unos|unas|the|an?)\s+"
    r"(?!de[l]?\b|que\b|cual\b|of\b|that\b|which\b|one\b)\w+",
    re.IGNORECASE,
)

# Ownership / nature categories only. Condition words (viejo, lento, nuevo) are
# deliberately excluded: they add false positives without carrying the weight
# that decides who signs a document.
_ATTRIBUTE = re.compile(
    r"\b(personal(?:es)?|privad[oa]s?|tuy[oa]s?|suy[oa]s?|propi[oa]s?"
    r"|particular(?:es)?|familiar(?:es)?|dom[ée]stic[oa]s?|compartid[oa]s?"
    r"|corporativ[oa]s?|empresarial(?:es)?|laboral(?:es)?"
    r"|private|yours|domestic|corporate|shared)\b"
    r"|\b(?:de\s+tu\s+propiedad|te\s+pertenece|le\s+pertenece"
    r"|del\s+despacho|de\s+la\s+(?:empresa|oficina|compa[ñn][íi]a|firma)"
    r"|your\s+own|belongs?\s+to\s+you|work[- ]issued|company[- ]owned)\b",
    re.IGNORECASE,
)

_QUOTED = re.compile(r'"[^"]*"|[“”][^“”]*[“”]|«[^»]*»', re.DOTALL)

# Genuinely interrogative: opens the question, rather than tagging one on the end.
_INTERROGATIVE = re.compile(
    r"^\s*(¿|(qu[ée]|cu[áa]l(?:es)?|c[óo]mo|qui[ée]n(?:es)?|d[óo]nde|cu[áa]ndo"
    r"|es|son|est[áa]s?|tienes?|tienen|puedes?|what|which|who|how|where|when"
    r"|is|are|do|does|did|can|could|would)\b)",
    re.IGNORECASE,
)

# "?," and "!," split too: without this a trailing assertion rides along
# inside an interrogative span and never gets scanned.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])[,;]?\s+|\n{2,}")

# REMOVED in v3: a "first-person act" exemption (configuré/hablé/I checked).
# It was meant to treat the writer's own verified act as a source, and it did
# clear two false positives. But review showed it launders real violations
# whenever an unrelated action shares the sentence: "Ayer instalé el agente y tu
# computadora de casa es personal" passed, and narrating an action about one
# object never sources a category about another. Separating the two is semantic,
# not lexical. Given the stated asymmetry (a false positive costs one rewrite; a
# false negative costs a falsified consent document), an exemption that
# manufactures false negatives is the wrong trade. Those two cases now block and
# are handled by the 'attribute-ok' hatch.


def _looks_like_code(body: str) -> bool:
    lines = [ln for ln in body.splitlines() if ln.strip()]
    if not lines:
        return True
    return sum(1 for ln in lines if _CODE_SIGNAL.search(ln)) * 4 >= len(lines)


def _keep_fence(lang: str, body: str) -> str:
    if (lang or "").strip().lower() in _PROSE_LANGS and not _looks_like_code(body):
        return "\n" + body + "\n"
    return "\n"


def _tail_lines(path: str, max_bytes: int = 262144) -> list:
    import os
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        fh.seek(max(0, size - max_bytes))
        return fh.read().decode("utf-8", errors="replace").splitlines()


def _walk_strings(obj, out: list) -> None:
    """Collect body-ish strings from a tool_use input of any nesting."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and str(k).lower() in _BODY_KEYS:
                out.append(v)
            else:
                _walk_strings(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk_strings(v, out)


def collect_turn(transcript_path: str) -> tuple:
    """(prose_text, outward_tool_text) for every assistant entry since the last
    user turn. v1 read only the LAST entry, so a draft followed by a one-line
    closer went unseen, and a draft inside a tool call was never visible at all."""
    prose, tool_text = [], []
    try:
        lines = _tail_lines(transcript_path)
    except OSError:
        return "", ""
    entries = []
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") == "user":
            # A tool RESULT is also type "user". Measured on a real session
            # transcript: 656 of 764 user entries are tool_results and only 108
            # are human prompts. Breaking on any of them stops the walk at the
            # last tool result, so a send-tool call (always followed by its
            # result) and any draft preceding a tool call are never seen. The
            # v2 fixtures passed only because they used entry shapes production
            # never emits: green selftest over a dead path.
            content = (entry.get("message") or {}).get("content")
            if isinstance(content, list) and any(
                    isinstance(b, dict) and b.get("type") == "tool_result"
                    for b in content):
                continue
            break
        if entry.get("type") == "assistant":
            entries.append(entry)
    for entry in entries:
        content = (entry.get("message") or {}).get("content") or []
        if isinstance(content, str):
            prose.append(content)
            continue
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                prose.append(block.get("text", ""))
            elif block.get("type") == "tool_use" and _SEND_TOOL.search(
                    str(block.get("name", ""))):
                found: list = []
                _walk_strings(block.get("input") or {}, found)
                tool_text.extend(found)
    return "\n".join(prose), "\n".join(tool_text)


def _strip_non_prose(text: str) -> str:
    text = _FENCE_BLOCK.sub(lambda m: _keep_fence(m.group(1), m.group(2)), text)
    tail = _FENCE_TAIL.search(text)
    if tail:
        text = text[:tail.start()] + _keep_fence(tail.group(1), tail.group(2))
    text = _INLINE.sub("", text)
    return "\n".join(
        ln for ln in text.splitlines()
        if not _FOOTER.match(ln)
        and "attribute-ok" not in ln
        and not ln.lstrip().startswith(">")
    )


def _mask_real_quotes(text: str) -> str:
    """Blank out substantial quotations (the counterpart's own words). A short
    scare quote is left in place: quoting one adjective is not sourcing it."""
    def repl(m):
        span = m.group(0)
        return " " * len(span) if len(span) - 2 >= MIN_QUOTE else span
    return _QUOTED.sub(repl, text)


def is_outward(prose: str, tool_text: str, raw: str = "") -> bool:
    """Delivery is positional, never a bare keyword."""
    if tool_text.strip():
        return True
    if _PASTE_PHRASE.search(prose):
        return True
    for m in _HANDOVER_LINE.finditer(prose):
        if not _ANALYSIS_HEADER.search(m.group(0)):
            return True
    # A raw draft ships INSIDE a prose fence with no intro at all (the
    # paste-ready canonical shape). The docstring always claimed a fence counts;
    # until v3 the code never looked, so the most stripped-down hand-over of all
    # was invisible.
    for fm in _FENCE_BLOCK.finditer(raw):
        lang, body = fm.group(1), fm.group(2)
        if (lang or "").strip().lower() in _PROSE_LANGS and not _looks_like_code(body):
            return True
    return False


def find_attributes(text: str) -> list:
    """Possessive and category word within WINDOW, either order, no verb needed."""
    hits = []
    text = _mask_real_quotes(text)
    parts = [p.strip() for p in _SENTENCE_SPLIT.split(text) if p.strip()]
    # Asking instead of asserting is one of the two prescribed fixes, so an
    # interrogative sentence is EMPTIED before anything else. Doing it after
    # pairing fails: a statement joined to a question yields a span with no
    # interrogative head, and the question's anchors sneak back in.
    # A tag question ("..., de acuerdo?") still asserts and is not emptied.
    parts = ["" if ("?" in p and _INTERROGATIVE.match(p)) else p for p in parts]
    # Each sentence AND each adjacent pair: "Tu computadora esta en tu casa. Es
    # personal." splits the claim across the period, and scanning sentences in
    # isolation is blind to exactly that. The WINDOW still bounds the reach.
    # Pairs are joined with a COMMA so the subject-switch guard sees the
    # boundary: "Gracias por tu nota. El repositorio es privado" becomes a
    # switch and passes, while "Tu computadora esta en tu casa. Es personal"
    # does not ("Es" is no determiner) and still fires.
    spans = parts + [f"{a}, {b}" for a, b in zip(parts, parts[1:])]
    for s in spans:
        if not s.strip():
            continue
        for pm in _POSSESSIVE.finditer(s):
            for am in _ATTRIBUTE.finditer(s):
                lo, hi = sorted((pm.start(), am.start()))
                if hi - lo > WINDOW:
                    continue
                between = s[lo:hi]
                if _FIRST_PERSON.search(between):
                    continue
                sw = _SUBJECT_SWITCH.search(between)
                # A real switch predicates of the new subject before reaching
                # the attribute; an appositive just renames and must still fire.
                if sw and _PREDICATES.search(between[sw.end():]):
                    continue
                # Reverse order: the attribute already has its own subject, so
                # the possessive further along is a different claim entirely.
                if am.start() < pm.start():
                    head = s[:am.start()]
                    om = None
                    for cand in _OWN_SUBJECT.finditer(head):
                        # An adverbial ("Como marca la politica, es personal…")
                        # is closed by a comma; a real subject is not.
                        if "," not in head[cand.end():]:
                            om = cand
                    if om is not None:
                        continue
                hits.append(f"{pm.group(0)} … {am.group(0)}")
                break
            else:
                continue
            break
    return hits


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
        prose_raw, tool_text = collect_turn(transcript)
        prose = _strip_non_prose(prose_raw)
        if not is_outward(prose, tool_text, prose_raw):
            return 0
        # Outward is not enough: the adjective is policed where it decides who
        # may authorize. See _CONSENT_CONTEXT for the measurement behind this.
        if not _CONSENT_CONTEXT.search(prose + "\n" + tool_text):
            return 0
        # A tool-call body is already outward text; it needs no fence stripping.
        attrs = find_attributes(prose + "\n" + tool_text)
    except Exception:
        return 0  # fail-open: a broken linter never holds the conversation

    if not attrs:
        return 0

    listing = "; ".join(f"«{f}»" for f in attrs[:6])
    extra = f" (+{len(attrs) - 6} más)" if len(attrs) > 6 else ""
    try:
        print(json.dumps({
            "decision": "block",
            "reason": (
                f"🏷 ATRIBUTO-SIN-FUENTE: lo que va a salir clasifica algo de la "
                f"contraparte con una categoría que ella no dijo ({listing}{extra}). "
                f"Una circunstancia (dónde está, quién lo usa) no autoriza la "
                f"categoría (de quién es, qué es), y en un consentimiento ese "
                f"adjetivo decide QUIÉN firma. Para cada uno: pega su frase "
                f"textual, conviértelo en pregunta dentro del mismo mensaje, o "
                f"quítalo. Nunca viaja adentro. Para dejarlo a propósito, pon "
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
