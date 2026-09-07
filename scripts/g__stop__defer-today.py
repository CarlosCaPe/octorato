#!/usr/bin/env python3
"""g__stop__defer-today.py: Stop gate: "no dejes para mañana lo que puedas hacer hoy" (do not put off until tomorrow what you can do today).

Operator directive, repeated to exhaustion and raised to canonical on
2026-08-18: *"NO DEJES PARA MAÑANA LO QUE PUEDAS HACER HOY, canónico. Todos los
días te lo tengo que recordar, ya cablealo de una vez en octorato."* Having to
be reminded daily is the proof that prose is not enough: a backlog that depends
on the model remembering gets skipped under load. This is the
`reflexes-over-discipline` rule applied to deferral.

The subtle form of deferral is not saying "I will not do it". It is REPORTING a
pending item I could have executed myself, and leaving it in the operator inbox.
So the gate does not look for declared laziness, it looks for the closing
sentence that pushes my own work forward in time.

WHEN IT FIRES. In the last assistant response, when a deferral marker shows up
in FIRST PERSON about my own work ("lo dejo para mañana", "queda pendiente", "lo
retomo la próxima sesión") and NEITHER of the two legitimate exits is present:

  1. The pending item is the operator own and travels with his exact action: a
     command block or a line starting with "! ". An irreducible step of his (a
     consent click, a password, a permission) is a valid pending item, and
     delivered that way it costs him no work: it costs him a paste.
  2. The line names the real, verified blocker (the classifier denied it, the
     repository rule rejected it, it needs his decision). A measured blocker is
     not a deferral.

A "tomorrow" that is not about my work does not count: quoting the client saying
"espero mañana me puedas contestar", or reporting that an office opens tomorrow,
are facts, not backlog. That is why a first-person deferral verb is required
near the marker and quoted spans are discarded.

Blocks ONCE (stop_hook_active), like its siblings. It forces you to SEE, not to
obey: if it really cannot be done today, the second pass goes through.

FAILS OPEN. Any error exits 0 and silently.

Deliberate escape: put `defer-ok` on the line.

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


_FOOTER = re.compile(r"^\s*(Provenance|Procedencia|Herkunft)\s*:", re.IGNORECASE)
_FENCE = re.compile(r"```.*?```", re.DOTALL)
_INLINE = re.compile(r"`[^`\n]*`")
_QUOTED = re.compile(r'"[^"]*"|[“”][^“”]*[“”]|«[^»]*»', re.DOTALL)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")

# Aplazamiento de trabajo PROPIO. Cada patrón trae su propio sujeto en primera
# persona o su propio "queda/sigue pendiente", que es lo mismo dicho en pasiva.
_DEFER = re.compile(
    r"\blo\s+(dejo|dejamos|vemos|retomo|retomamos|hago|har[ée]|termino)\s+"
    r"(para\s+)?(ma[ñn]ana|luego|despu[ée]s|m[áa]s tarde|la pr[óo]xima|el lunes)\b"
    r"|\b(queda|sigue|se\s+queda)\s+pendiente\b"
    r"|\blo\s+dejo\s+(para|pendiente)\b"
    r"|\bma[ñn]ana\s+(lo|te\s+lo|se\s+lo)\s+\w+"
    r"|\bpendiente\s+para\s+(ma[ñn]ana|la pr[óo]xima|el lunes)\b"
    r"|\ben\s+la\s+(pr[óo]xima|siguiente)\s+sesi[óo]n\b"
    r"|\bel\s+siguiente\s+sync\b"
    r"|\bI['’]?ll\s+(do|finish|pick|handle|leave)\s+(it|this|that)?\s*"
    r"(up\s+)?(tomorrow|later|next session|next time)\b"
    r"|\bleave\s+(it|this|that)\s+for\s+(tomorrow|later|the next session)\b"
    r"|\b(remains|stays)\s+pending\b",
    re.IGNORECASE,
)

# El pendiente es del operador y está medido: no es rezago mío.
_BLOQUEO_REAL = re.compile(
    r"(clasificador|me lo neg[óo]|lo neg[óo]|denied by|rechaz[óo]|remote rejected"
    r"|rule violations|requiere tu|necesita tu|solo t[úu]|tu decisi[óo]n"
    r"|tu aprobaci[óo]n|operator-only|only you can|needs your|no tengo (acceso|permiso)"
    r"|blocked by)",
    re.IGNORECASE,
)


def _tail_lines(path: str, max_bytes: int = 262144) -> list:
    import os
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        fh.seek(max(0, size - max_bytes))
        return fh.read().decode("utf-8", errors="replace").splitlines()


def _last_assistant_text(transcript_path: str) -> str:
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
        break
    return "\n".join(text_parts)


def entrega_la_accion(raw: str) -> bool:
    """¿La respuesta entrega la acción exacta que el operador tiene que correr?

    Se mide sobre el texto CRUDO, antes de quitar los bloques de código, porque
    el bloque pegable es justo la evidencia que estamos buscando.
    """
    if re.search(r"^\s*!\s+\S", raw, re.MULTILINE):
        return True
    return "```" in raw


def _strip_non_prose(text: str) -> str:
    text = _FENCE.sub("", text)
    text = re.sub(r"```.*", "", text, flags=re.DOTALL)
    text = _INLINE.sub("", text)
    kept = [ln for ln in text.splitlines()
            if not _FOOTER.match(ln) and "defer-ok" not in ln]
    return "\n".join(kept)


def find_deferrals(text: str, raw: str) -> list:
    """Fragmentos de aplazamiento sin salida legítima en su misma frase."""
    hits = []
    tiene_accion = entrega_la_accion(raw)
    text = _QUOTED.sub(" ", text)
    for sentence in _SENTENCE_SPLIT.split(text):
        if not sentence.strip():
            continue
        m = _DEFER.search(sentence)
        if not m:
            continue
        if _BLOQUEO_REAL.search(sentence):
            continue          # bloqueo medido, no rezago
        if tiene_accion:
            continue          # va con el comando exacto para el operador
        hits.append(m.group(0))
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
        raw = _last_assistant_text(transcript)
        text = _strip_non_prose(raw)
        if not text.strip():
            return 0
        deferrals = find_deferrals(text, raw)
    except Exception:
        return 0

    if not deferrals:
        return 0

    listing = "; ".join(f"…{frag[:60]}…" for frag in deferrals[:6])
    extra = f" (+{len(deferrals) - 6} más)" if len(deferrals) > 6 else ""
    try:
        print(json.dumps({
            "decision": "block",
            "reason": (
                f"⏳ HOY-NO-MAÑANA: estás cerrando el turno aplazando trabajo tuyo "
                f"({listing}{extra}). Hazlo ahora. Si de verdad no se puede, el "
                f"pendiente solo vale cuando es un paso irreducible del operador "
                f"(consentimiento, contraseña, permiso) o un bloqueo MEDIDO, y en "
                f"ambos casos viaja con su comando exacto para pegar. Reportar un "
                f"pendiente que tú podías ejecutar es la forma sutil de aplazar. "
                f"Ver CLAUDE.md 'Do-it-today'."
            ),
        }))
    except Exception:
        pass
    return 0


def _selftest() -> int:
    import gate_selftest
    argv = sys.argv
    fixture = argv[argv.index("--selftest") + 1] if len(argv) > argv.index("--selftest") + 1 \
        else "registry/fixtures/FLOW.do-it-today"
    return gate_selftest.run_gate_selftest(__file__, fixture)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
