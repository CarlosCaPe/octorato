#!/usr/bin/env python3
"""claim_vocab.py: vocabulario compartido de CLAIMS DE CIERRE.

Un claim de cierre es la frase con la que el agente declara terminado un
trabajo: "listo", "quedo", "resuelto", "arreglado", "ya funciona", "fixed",
"done", "PASS", "✅".

Vive aqui, en un solo lugar, a proposito. Varios gates Stop necesitan la misma
pregunta ("¿esta respuesta declara cierre?") y una segunda copia del regex
forkea el vocabulario: se le agrega un termino a una copia, la otra se queda
ciega, y las dos compuertas dejan de coincidir sobre que es cerrar. Un termino
nuevo se agrega AQUI y todos los consumidores lo heredan.

Nota de procedencia: el diseño original apuntaba a importarlo de
claim-verify-stop.py, pero ese modulo nunca tuvo esta lista (solo cubre claims
de VERIFICACION visual/runtime y de cobertura total, otro concepto). Asi que se
extrajo a este lugar compartido en vez de duplicarla.

No es un hook. No se registra en settings.json.
"""
from __future__ import annotations

import re

# Vocabulario de cierre, español e ingles. `✅` va sin frontera de palabra
# porque no es caracter de palabra. Los plurales y el par o/a van explicitos
# para no atrapar por prefijo ("quedan" no es "quedo").
CLOSURE_CLAIM_RE = re.compile(
    r"\blist[oa]s?\b"
    r"|\bqued[oó]\b"
    r"|\bresuelt[oa]s?\b"
    r"|\barreglad[oa]s?\b"
    r"|\bya\s+funciona\b"
    r"|\bfixed\b"
    r"|\bdone\b"
    r"|\bpass\b"
    r"|✅",
    re.IGNORECASE,
)


def is_closure_claim(text: str) -> bool:
    """True si el texto declara cierre de trabajo."""
    if not text:
        return False
    return bool(CLOSURE_CLAIM_RE.search(text))


def closure_claim_fragment(text: str) -> str:
    """El fragmento exacto que disparo, o cadena vacia. Sirve para el recibo."""
    if not text:
        return ""
    m = CLOSURE_CLAIM_RE.search(text)
    return m.group(0) if m else ""
