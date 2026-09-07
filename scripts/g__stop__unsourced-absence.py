#!/usr/bin/env python3
"""g__stop__unsourced-absence.py: Stop gate: no "this has no origin" claim ships
outward without a seek receipt in the same turn.

THE FAILURE THIS EXISTS FOR
A bank charge the operator did not remember was described to a vendor, in a
formal complaint email, as "does not correspond to any service I contracted".
It was a purchase the operator himself had itemized to that same vendor in a
chat six weeks earlier. Both the brain memory and the chat transcript held the
answer; neither was looked at. The operator's own words were "I paid it
directly, I think", a doubt, and the draft turned that doubt into a categorical
absence claim addressed to a third party. A correction had to go out minutes
later, and a correction of a money claim discredits the claims that were right.

WHY A GATE AND NOT PROSE
"Adversarially verify the operator" is a rule of this brain and it did not fire,
because "verify" names no detectable moment. The ABSENCE CLAIM is one: a
sentence that says "no record / not recognized / never contracted / no origin"
about a concrete thing is precisely the sentence that a one-line seek can
refute. The check that was skipped cost one `list_messages` call with the
amount as the query.

WHAT FIRES (three conditions, all required)
  1. Delivery. Something in this turn goes outward: a send/draft tool call, a
     paste phrase, a hand-over line ending in ':' that is not an analysis
     header, or a prose fence. Analysis prose that diagnoses a charge is not
     delivery and is never blocked.
  2. Absence claim. Inside that outward text, a sentence asserts that a thing
     has no origin, is not recognized, was never contracted, or has no record
     (_ABSENCE, ES + EN). A question is not a claim ("¿a qué corresponde?") and
     is exactly the prescribed fix, so interrogative sentences are exempt. A
     '>' blockquote or a substantial quotation is the counterpart's own words
     and is exempt too.
  3. No seek receipt. The same turn holds no tool call that could have refuted
     the claim: no chat search, no mail search, no memory seek (_SEEK_TOOL by
     tool name, or a Bash command invoking one of those). A seek that ran and
     found nothing is a receipt; the gate cannot judge the result, only that the
     look happened. A seek in an EARLIER turn does not count: the transcript
     walk stops at the last human prompt, so the receipt has to be in the turn
     that ships.

THIS IS A TRIPWIRE, NOT A FENCE
The vocabulary is the boundary. An absence claim phrased outside _ABSENCE ships
unblocked; when one bites, widen the list. Never widen delivery back to "any
mention of borrador", which is the false-positive mode the sibling gates
measured at 70% and disarmed themselves on.

Loop safety: stop_hook_active=true means we already blocked this turn. Fail-open
on every error: a broken linter must never hold a conversation hostage.

Escape hatch: put 'absence-ok' on a line to keep it deliberately.

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


# A quotation shorter than this is a scare quote, not a citation.
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

# Tools whose arguments ARE an outward message.
_SEND_TOOL = re.compile(
    r"(send_message|send_email|draft_email|create_draft|update_draft|reply"
    r"|forward|send_file|send_audio_message|wa-soporte)",
    re.IGNORECASE,
)
_BODY_KEYS = ("body", "message", "text", "content", "html", "snippet",
              "caption", "subject", "description", "title")

# Tools (or Bash invocations) that could have refuted an absence claim: chat
# history, mail history, the memory graph, the connectome memory seek.
_SEEK_TOOL = re.compile(
    r"(list_messages|get_message_context|get_chat|search_emails|search_threads"
    r"|get_thread|read_email|get_message|query_connectome|memory_map"
    r"|impact-radius|list_chats|get_last_interaction)",
    re.IGNORECASE,
)
_SEEK_CMD = re.compile(
    r"(query_connectome\.py\s+memory|list_messages|messages\.db|search_emails"
    r"|wa-guardia|sqlite3\s+\S*messages)",
    re.IGNORECASE,
)

_PASTE_PHRASE = re.compile(
    r"(para pegar|p[ée]galo|listo para (pegar|enviar|mandar)|paste[- ]ready"
    r"|ready to (paste|send)|text to send|copy[- ]paste"
    r"|puedes (mandarle|enviarle|pasarle) esto|m[áa]ndale esto"
    r"|te (dejo|paso|propongo)(?:\s+\w+){0,2}\s+(el|este|la|esta)?\s*"
    r"(correo|mensaje|texto|borrador|respuesta|nota))",
    re.IGNORECASE,
)
_HANDOVER_LINE = re.compile(
    r"^\s*(?:[^\n]{0,80}\b(borrador|draft|correo|mensaje|texto|carta|addenda"
    r"|email|message|asunto|subject|respuesta|reply|nota|note)\b[^\n]{0,80}):\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_ANALYSIS_HEADER = re.compile(
    r"\b(puntos?|errores?|hallazgos?|correcciones?|revisi[óo]n"
    r"|an[áa]lisis|issues?|findings?|corrections?|review)\b"
    r"|\b(pasos?|instrucciones|gu[íi]a|checklist|steps?|how\s+to)\b"
    r"|\b(corrig[íi]|revis[ée]|encontr[ée]|detect[ée]|found|fixed|reviewed)\b",
    re.IGNORECASE,
)

# The absence claim itself: a categorical "no origin / not recognized / never
# contracted / no record" about a thing. Doubt markers ("creo", "I think") do not
# rescue it: the sibling incident shipped exactly that doubt as a fact.
_ABSENCE = re.compile(
    r"\b(no\s+(?:lo\s+)?reconozco|no\s+reconocemos|desconozco|cargo\s+fantasma"
    r"|sin\s+origen|no\s+tiene\s+origen|carece\s+de\s+origen"
    r"|no\s+corresponde\s+a\s+(?:ning[úu]n|ninguna|nada)"
    r"|no\s+(?:me\s+)?corresponde\s+a\s+(?:un|una)\s+\w+\s+que\s+(?:yo\s+)?(?:haya|hubiera)"
    r"|nunca\s+(?:lo\s+)?(?:contrat[ée]|compr[ée]|autoric[ée]|solicit[ée]|pagu[ée])"
    r"|no\s+(?:lo\s+)?(?:contrat[ée]|autoric[ée]|solicit[ée])\b"
    r"|no\s+existe\s+(?:ning[úu]n|ninguna|reserva|recibo|registro|contrato)"
    r"|no\s+hay\s+(?:ning[úu]n|ninguna)\s+(?:reserva|recibo|registro|servicio|contrato)"
    r"|no\s+recib[íi]\s+(?:ning[úu]n\s+recibo|ning[úu]n\s+comprobante|recibo|comprobante)"
    r"|no\s+tengo\s+(?:ning[úu]n\s+|ninguna\s+)?(?:recibo|comprobante|registro|constancia|reserva|factura)"
    r"|(?:i|we)\s+(?:do\s+not|don'?t)\s+recogni[sz]e|unrecogni[sz]ed\s+charge"
    r"|unauthori[sz]ed\s+charge|no\s+record\s+of|never\s+(?:purchased|contracted|authori[sz]ed|ordered)"
    r"|(?:did|do)\s+not\s+(?:authori[sz]e|contract|purchase|order)"
    r"|not\s+(?:linked|tied|associated)\s+to\s+any)\b",
    re.IGNORECASE,
)

_QUOTED = re.compile(r'"[^"]*"|[“”][^“”]*[“”]|«[^»]*»', re.DOTALL)
_INTERROGATIVE = re.compile(
    r"^\s*(¿|(qu[ée]|cu[áa]l(?:es)?|c[óo]mo|qui[ée]n(?:es)?|d[óo]nde|cu[áa]ndo"
    r"|a\s+qu[ée]|es|son|est[áa]s?|tienes?|tienen|puedes?|pueden|what|which|who"
    r"|how|where|when|is|are|do|does|did|can|could|would)\b)",
    re.IGNORECASE,
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])[,;]?\s+|\n{2,}")


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
    """(prose, outward_tool_text, seek_receipt) for every assistant entry since
    the last HUMAN prompt. Tool results are also type "user" and must not stop
    the walk (measured: 656 of 764 user entries in a real session are results)."""
    prose, tool_text, seek = [], [], False
    try:
        lines = _tail_lines(transcript_path)
    except OSError:
        return "", "", False
    entries = []
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") == "user":
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
            elif block.get("type") == "tool_use":
                name = str(block.get("name", ""))
                inp = block.get("input") or {}
                if _SEEK_TOOL.search(name):
                    seek = True
                elif name == "Bash" and _SEEK_CMD.search(str(inp.get("command", ""))):
                    seek = True
                if _SEND_TOOL.search(name):
                    found: list = []
                    _walk_strings(inp, found)
                    tool_text.extend(found)
    return "\n".join(prose), "\n".join(tool_text), seek


def _strip_non_prose(text: str) -> str:
    text = _FENCE_BLOCK.sub(lambda m: _keep_fence(m.group(1), m.group(2)), text)
    tail = _FENCE_TAIL.search(text)
    if tail:
        text = text[:tail.start()] + _keep_fence(tail.group(1), tail.group(2))
    text = _INLINE.sub("", text)
    return "\n".join(
        ln for ln in text.splitlines()
        if not _FOOTER.match(ln)
        and "absence-ok" not in ln
        and not ln.lstrip().startswith(">")
    )


def _mask_real_quotes(text: str) -> str:
    def repl(m):
        span = m.group(0)
        return " " * len(span) if len(span) - 2 >= MIN_QUOTE else span
    return _QUOTED.sub(repl, text)


def is_outward(prose: str, tool_text: str, raw: str = "") -> bool:
    if tool_text.strip():
        return True
    if _PASTE_PHRASE.search(prose):
        return True
    for m in _HANDOVER_LINE.finditer(prose):
        if not _ANALYSIS_HEADER.search(m.group(0)):
            return True
    for fm in _FENCE_BLOCK.finditer(raw):
        lang, body = fm.group(1), fm.group(2)
        if (lang or "").strip().lower() in _PROSE_LANGS and not _looks_like_code(body):
            return True
    return False


# "No lo autoricé yo, lo hizo el equipo": names WHO did, so it attributes and
# explains the clause before it. "no sé quién lo hizo" / "lo hizo alguien más"
# name nobody: they exempt nothing (QA cycle 4).
_ATTRIBUTED = re.compile(
    r"\b(?:lo\s+(?:hizo|autoriz[óo]|contrat[óo]|solicit[óo]|pidi[óo])"
    r"|(?:was\s+(?:done|authori[sz]ed|ordered)\s+by))\s+"
    r"(?:el|la|los|las|un|una|mi|mis|nuestr[oa]s?|su|sus|the|our|my|[A-ZÁÉÍÓÚ]\w+)\b"
    r"|\bfue\s+(?:el|la|un|una|mi|nuestr[oa])\s+\w+",
    re.IGNORECASE,
)
_NOBODY = re.compile(r"no\s+s[ée]\s+qui[ée]n|alguien\s+m[áa]s|someone\s+else|no\s+idea\s+who", re.IGNORECASE)


def find_absence_claims(text: str, mask_quotes: bool = True) -> list:
    """Absence phrases in declarative sentences of the outward text. A sentence
    that OPENS as a question is the prescribed fix and is skipped; one that
    asserts and then asks still asserts. `mask_quotes=False` is for
    a SEND body, where a quotation is the model quoting itself."""
    hits = []
    if mask_quotes:
        text = _mask_real_quotes(text)
    for part in _SENTENCE_SPLIT.split(text):
        s = part.strip()
        if not s or "absence-ok" in s:
            continue
        # Asking INSTEAD of asserting is the fix; a sentence that asserts and
        # then asks ("..., ¿verdad?", "... ¿me lo aclaran?") still asserts, so
        # only a sentence that OPENS as a question is exempt (QA cycles 2-3).
        if "?" in s and _INTERROGATIVE.match(s):
            continue
        # Attribution ("lo hizo el equipo") explains the comma-clause it sits
        # in and the one right before it, inside the same conjunction segment;
        # it never reaches across "y"/"and"/";" and never launders a claim that
        # comes after it.
        hit = None
        for segment in re.split(r"\s*;\s*|\s+y\s+|\s+and\s+", s):
            clauses = [c for c in re.split(r"\s*,\s*", segment) if c]
            attributed = {i for i, c in enumerate(clauses)
                          if _ATTRIBUTED.search(c) and not _NOBODY.search(c)}
            exempt = attributed | {i - 1 for i in attributed if i > 0}
            for i, clause in enumerate(clauses):
                if i in exempt:
                    continue
                m = _ABSENCE.search(clause)
                if m:
                    hit = m.group(0)
                    break
            if hit:
                break
        if hit:
            hits.append(hit)
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
        prose_raw, tool_text, seek = collect_turn(transcript)
        if seek:
            return 0
        prose = _strip_non_prose(prose_raw)
        if not is_outward(prose, tool_text, prose_raw):
            return 0
        # Tool bodies are outward already; strip their blockquotes only.
        tool_clean = "\n".join(ln for ln in tool_text.splitlines()
                               if not ln.lstrip().startswith(">"))
        claims = find_absence_claims(prose + "\n" + tool_clean)
    except Exception:
        return 0

    if not claims:
        return 0

    listing = "; ".join(f"«{c}»" for c in claims[:6])
    extra = f" (+{len(claims) - 6} más)" if len(claims) > 6 else ""
    try:
        print(json.dumps({
            "decision": "block",
            "reason": (
                f"🔎 AUSENCIA-SIN-BÚSQUEDA: lo que va a salir afirma que algo no "
                f"tiene origen o no se reconoce ({listing}{extra}) y en este turno "
                f"no hubo ninguna búsqueda que pudiera refutarlo. Un 'no lo "
                f"reconozco' del operador es hipótesis, no dato. Antes de mandar: "
                f"query_connectome.py memory \"<monto o concepto>\", list_messages "
                f"con el monto (con y sin coma) en las fechas del cargo, y el "
                f"expediente del arm. Si los tres vienen vacíos, redáctalo como "
                f"pregunta a la contraparte, no como afirmación. Para dejarlo a "
                f"propósito, pon 'absence-ok' en la línea. Ver CLAUDE.md "
                f"'Unsourced-absence'."
            ),
        }))
    except Exception:
        pass
    return 0


def _selftest() -> int:
    import gate_selftest
    argv = sys.argv
    fixture = argv[argv.index("--selftest") + 1] if len(argv) > argv.index("--selftest") + 1 \
        else "registry/fixtures/COMMS.unsourced-absence"
    return gate_selftest.run_gate_selftest(__file__, fixture)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
