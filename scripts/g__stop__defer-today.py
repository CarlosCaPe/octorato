#!/usr/bin/env python3
"""g__stop__defer-today.py — Stop gate: no dejes para mañana lo que puedas hacer hoy.

Directiva del operador, repetida hasta el hartazgo y elevada a canónica el
18-ago-2026: *"NO DEJES PARA MAÑANA LO QUE PUEDAS HACER HOY, canónico. Todos los
días te lo tengo que recordar, ya cablealo de una vez en octorato."* Que haya que
recordarlo a diario es la prueba de que la prosa no basta: un rezago que depende
de que el modelo se acuerde se salta bajo carga. Esto es la regla
`reflexes-over-discipline` aplicada al aplazamiento.

La forma sutil del aplazamiento no es decir "no lo hago". Es REPORTAR un pendiente
que yo mismo podía ejecutar, y dejárselo al operador en la bandeja. Por eso el
gate no busca pereza declarada, busca la frase de cierre que empuja trabajo mío
hacia adelante.

CUÁNDO DISPARA. En la última respuesta del asistente, cuando aparece un marcador
de aplazamiento en PRIMERA PERSONA sobre trabajo propio ("lo dejo para mañana",
"queda pendiente", "lo retomo la próxima sesión") y NO hay ninguna de las dos
salidas legítimas:

  1. El pendiente es del operador y viaja con su acción exacta: un bloque de
     comando o una línea que empieza con "! ". Un paso irreducible suyo (un clic
     de consentimiento, una contraseña, un permiso) es un pendiente válido, y
     entregado así no le cuesta trabajo: le cuesta pegar.
  2. La línea nombra el bloqueo real y verificado (el clasificador lo negó, la
     regla del repositorio lo rechazó, requiere su decisión). Un bloqueo medido
     no es un aplazamiento.

Un "mañana" que no habla de trabajo mío no cuenta: citar a la clienta diciendo
"espero mañana me puedas contestar", o informar que una oficina abre mañana, son
hechos, no rezagos. Por eso se exige un verbo de aplazamiento en primera persona
cerca del marcador y se descartan los tramos entrecomillados.

Bloquea UNA vez (stop_hook_active), como sus hermanos. Obliga a VER, no a
obedecer: si de verdad no se puede hoy, la segunda pasada sigue.

FALLA ABIERTO. Cualquier error sale con 0 y en silencio.

Escape deliberado: poner `defer-ok` en la línea.

Stdin:  {"transcript_path": str, "stop_hook_active": bool, ...}
Stdout: {"decision": "block", "reason": "..."} si pega, si no nada.
Exit:   siempre 0.
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
