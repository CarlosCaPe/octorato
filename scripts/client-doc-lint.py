#!/usr/bin/env python3
"""client-doc-lint.py — pre-send QA reflex for generated CLIENT deliverables.

cadence-lint.py covers PROSE SOURCE text. This linter covers the GENERATED
ARTIFACT (a PDF/DOCX cotización, propuesta, contrato) right before "listo para
enviar". It exists because in one session a whole Spanish client proposal was
generated with ZERO accents AND an already-past kickoff date, and both slipped
through two regeneration rounds until a manual visual render caught them. An
instruction ("be careful with accents") depends on discipline and never reaches
a sub-agent's doc-gen; this turns the regex-provable subset into a REFLEX.

Checks (Spanish client docs):
  1 accents   — a long Spanish doc with a near-zero accent ratio = stripped
                accents (looks unprofessional). FAIL.
  2 em-dash   — any '—' in the rendered text (human-cadence rule 1). FAIL.
  3 stale     — a forward-looking line (kickoff/agendar/semana del ...) whose
                date is already in the past relative to --today. FAIL.
  4 iva       — a Spanish doc that quotes $ amounts with ZERO mention of the
                word IVA = fiscal ambiguity: the client can read the price as
                tax-included and cut the PO for the gross. FAIL.
  5 figures   — informational inventory of every $ amount found, so a human
                can eyeball consistency across sections (no auto-verdict).

Usage:
  client-doc-lint.py <file.pdf|.txt|.md>     CLI report; exit 1 on any FAIL
  ... | client-doc-lint.py                   lint stdin text
  client-doc-lint.py <file> --today 2026-06-09   pin "today" (tests/repro)
  client-doc-lint.py <file> --lang es        language for accent check (es default)

Requires `pdftotext` (poppler-utils) for .pdf input.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import re
import subprocess
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ACCENTED = "áéíóúüñÁÉÍÓÚÜÑ"
# One source of truth for $-amounts: optional space after $ covers the common
# Mexican "$ 85,000.00" typography and pdftotext extraction artifacts.
AMOUNT_RE = re.compile(r"\$\s?[\d][\d,]*(?:\.\d{2})?")
# Solid IVA word or fully dotted I.V.A. — never "IV.A" (roman-numeral sections).
IVA_RE = re.compile(r"\bIVA\b|(?<![A-Za-z])I\.V\.A\.?(?![A-Za-z])", re.IGNORECASE)
MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}
# Forward-intent keywords: a date on these lines is meant to be in the FUTURE.
FORWARD = re.compile(r"(kickoff|agend|semana del|arranqu|antes del|antes de fin)", re.I)
# Reference/emission lines legitimately carry past dates (FX, DOF, emission).
REFERENCE = re.compile(r"(FIX|DOF|tipo de cambio|emisi[óo]n|referencia|Banxico|exhibici[óo]n)", re.I)


def read_text(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    p = Path(path)
    if not p.exists():
        sys.exit(f"client-doc-lint: no existe {path}")
    if p.suffix.lower() == ".pdf":
        try:
            out = subprocess.run(["pdftotext", str(p), "-"], capture_output=True,
                                 text=True, timeout=60)
        except FileNotFoundError:
            sys.exit("client-doc-lint: falta pdftotext (apt install poppler-utils)")
        if out.returncode != 0:
            sys.exit(f"client-doc-lint: pdftotext falló: {out.stderr.strip()}")
        return out.stdout
    return p.read_text(encoding="utf-8", errors="replace")


def check_accents(text: str, lang: str) -> tuple[bool, str]:
    if lang != "es":
        return True, "accents: omitido (lang != es)"
    letters = sum(1 for c in text if c.isalpha())
    accented = sum(1 for c in text if c in ACCENTED)
    ratio = accented / letters if letters else 0
    if letters > 800 and ratio < 0.005:
        return False, (f"accents: FAIL — {accented} acentos en {letters} letras "
                       f"(ratio {ratio:.3%}); un texto en español sano ronda 3-6%. "
                       f"Probable pérdida de acentos.")
    return True, f"accents: OK — ratio {ratio:.2%} ({accented}/{letters})"


def check_emdash(text: str) -> tuple[bool, str]:
    n = text.count("—")
    if n:
        sample = [ln.strip() for ln in text.splitlines() if "—" in ln][:3]
        return False, "em-dash: FAIL — " + str(n) + " ocurrencia(s). Ej: " + " | ".join(sample)
    return True, "em-dash: OK — 0"


def _parse_dates(line: str, today: _dt.date):
    """Yield (date, has_year) for full and week-style Spanish dates in a line."""
    mes = "|".join(MONTHS)
    for m in re.finditer(rf"(\d{{1,2}})\s+de\s+({mes})\s+de\s+(\d{{4}})", line, re.I):
        yield _dt.date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1))), True
    for m in re.finditer(rf"semana del\s+(\d{{1,2}})\s+de\s+({mes})(?!\s+de\s+\d)", line, re.I):
        yield _dt.date(today.year, MONTHS[m.group(2).lower()], int(m.group(1))), False


def check_stale(text: str, today: _dt.date) -> tuple[bool, str]:
    bad = []
    for ln in text.splitlines():
        if not FORWARD.search(ln) or REFERENCE.search(ln):
            continue
        for d, _hy in _parse_dates(ln, today):
            if d < today:
                bad.append(f"{d.isoformat()} :: {ln.strip()[:90]}")
    if bad:
        return False, "stale-dates: FAIL — fecha futura ya vencida:\n    " + "\n    ".join(bad[:5])
    return True, f"stale-dates: OK (hoy {today.isoformat()})"


def check_iva(text: str, lang: str) -> tuple[bool, str]:
    if lang != "es":
        return True, "iva: omitido (lang != es)"
    amounts = AMOUNT_RE.findall(text)
    if not amounts:
        return True, "iva: OK — sin montos $, no aplica"
    if IVA_RE.search(text):
        return True, f"iva: OK — nota fiscal presente ({len(amounts)} monto(s) $)"
    return False, (f"iva: FAIL — {len(amounts)} monto(s) $ y cero menciones de 'IVA'. "
                   "Un doc con precios debe declarar 'más IVA' o 'IVA incluido'; "
                   "sin la nota, la orden de compra puede llegar por el monto como IVA incluido.")


def figures(text: str) -> str:
    found = sorted(set(AMOUNT_RE.findall(text)))
    return f"figures: {len(found)} montos distintos → " + ", ".join(found[:20]) + (
        " ..." if len(found) > 20 else "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file", nargs="?", default="-")
    ap.add_argument("--today", help="YYYY-MM-DD (default: hoy del sistema)")
    ap.add_argument("--lang", default="es")
    a = ap.parse_args()
    today = (_dt.date.fromisoformat(a.today) if a.today else _dt.date.today())

    text = read_text(a.file)
    results = [check_accents(text, a.lang), check_emdash(text), check_stale(text, today),
               check_iva(text, a.lang)]
    print(f"── client-doc-lint: {a.file} ──")
    ok_all = True
    for ok, msg in results:
        print(("  ✓ " if ok else "  ✗ ") + msg)
        ok_all = ok_all and ok
    print("  · " + figures(text))
    print("VERDICT:", "PASS (listo para enviar)" if ok_all else "FAIL (corregir antes de enviar)")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
