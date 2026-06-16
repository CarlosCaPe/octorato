#!/usr/bin/env python3
"""inbox-sweep-reflex.py - UserPromptSubmit hook.

The recurring failure: when the operator says "lee mi correo" / "dame mis
pendientes", the model improvises filtered/recent Gmail searches and misses real
threads, instead of firing the inbox-triage reflex. A passive memory note gets
skipped under load (see skills/reflexes-over-discipline). So this is the ganglion:
on any email-read trigger it injects an unconditional FULL-SWEEP directive, so the
behavior no longer depends on the model remembering.

Emits the UserPromptSubmit contract on match:
  {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "..."}}
On no match, or any error, it stays silent and exits 0 (fail-open: a skipped beat
is survivable, a hung prompt is not).
"""
import json
import re
import sys
import unicodedata


def _strip(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


# verb (read/check/sweep/triage) near (correo/inbox/email/bandeja/pendientes),
# plus the standalone "mis pendientes" / "pendientes a seguir" forms.
_VERB = r"(lee|leer|le|revisa|revisar|checa|chequea|barre|barri|read|check|sweep|triage|abre)"
_OBJ = r"(correo|correos|inbox|bandeja|e?-?mail|emails|pendientes)"
PATTERNS = [
    re.compile(_VERB + r"\w*\s+(\w+\s+){0,3}?" + _OBJ),
    re.compile(r"\b(mis|los|tus)\s+pendientes\b"),
    re.compile(r"\bpendientes\s+(a\s+seguir|de\s+(correo|email|inbox))"),
]

DIRECTIVE = (
    "<inbox-sweep-reflex> El operador pidio leer correo / pendientes. "
    "REFLEJO OBLIGATORIO (no improvisar busquedas filtradas): "
    "1) Carga el skill inbox-triage-classifier. "
    "2) Barrido COMPLETO del inbox, no por termino ni fecha corta: "
    "`in:inbox newer_than:14d` sin filtros restrictivos (sube la ventana si hace falta). "
    "3) Agrupa por hilo/tema; separa ruido (Amazon, escuela Idukay, CFDI automaticos, "
    "estados de cuenta, marketing) de lo accionable. "
    "4) Lista TODO lo accionable aunque no lo haya pedido por nombre, con el siguiente paso de cada uno. "
    "El MCP de correo solo ve la cuenta conectada; tramites gubernamentales pueden vivir en otra cuenta "
    "personal del operador (revisar memoria/preferencias del operador). "
    "Una muestra filtrada = fallo recurrente; el barrido debe ser completo. "
    "Ref: skills/inbox-triage-classifier, memory feedback_email_full_sweep_not_filtered.</inbox-sweep-reflex>"
)


def main() -> None:
    try:
        prompt = (json.load(sys.stdin) or {}).get("prompt", "") or ""
    except Exception:
        return
    norm = _strip(prompt)
    if any(p.search(norm) for p in PATTERNS):
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit", "additionalContext": DIRECTIVE}}))


if __name__ == "__main__":
    main()
