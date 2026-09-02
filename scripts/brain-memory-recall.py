#!/usr/bin/env python3
"""brain-memory-recall.py - UserPromptSubmit beat: surface the BRAIN's own life-memories
(its auto-memory MEMORY.md index) relevant to the current prompt, BEFORE asking or asserting.

Why this exists
---------------
Two existing reflexes leave a hole:
  - connectome-heartbeat circulates only the brain's SKILLS/AGENTS (technique), not life-memories.
  - arm-recall-hook circulates an ARM's knowledge.json + arm memory, and ONLY fires inside an arm.
So when a task touches the operator's own life (family, relocation, school, visa, rates) the
relevant project/feedback memory never surfaces, and the model re-asks what was already captured.
This hook is that missing reflex: it scores the MEMORY.md index against the prompt and points at
the few relevant entries. It does not read their bodies (cheap), it points so the model SEEKS them.

Contract (UserPromptSubmit):
  stdin : {"prompt": str, "transcript_path": str, ...}
  stdout: {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "..."}}

Budget / safety: hard SIGALRM self-timeout, threshold-gated (silent when nothing is relevant, so it
never spams), and fail-open everywhere. A skipped beat is survivable; a hung prompt is not.
"""
from __future__ import annotations

import json
import os
import re
import signal
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

HOME = Path.home()
PROJECTS = HOME / ".claude" / "projects"

TIMEOUT_S = 3
TAIL_BYTES = 20_000
MAX_HITS = 5
MIN_SCORE = 2           # need at least this much token overlap to surface a line
# Una linea del indice puede compactar VARIAS entradas separadas por " · ".
# Leerlas todas (finditer) o toda entrada en segunda posicion queda muda: mitad
# del canon sin recall y el doctor contandola como no-indexada. El gancho
# ': hook' es OPCIONAL: el indice compactado escribe entradas sin gancho
# (`[Titulo](archivo.md) · [Otra](otra.md)`); exigirlo dejaba fuera 120 de 122
# ficheros. La entrada se puntua por titulo+archivo aunque no traiga hook.
ENTRY_RE = re.compile(r"\[(?P<title>[^\]]+)\]\((?P<file>[^)]+)\)(?:\s*[:\-]\s*(?P<hook>[^·]*))?")
TOKEN_RE = re.compile(r"[a-z0-9áéíóúñü]{3,}")

STOP = {
    "the", "and", "for", "with", "that", "this", "from", "you", "your", "are", "was",
    "what", "when", "where", "who", "how", "why", "all", "any", "can", "not", "but",
    "una", "uno", "los", "las", "del", "que", "con", "por", "para", "como", "este",
    "esta", "esto", "mas", "muy", "sus", "ese", "esa", "son", "fue", "han", "hay",
    "ami", "mis", "tus", "les", "nos", "ver", "haz", "hazlo", "dale", "porque", "pero",
    "ingles", "spanish", "english", "draft", "borrador", "mensaje", "message", "ayuda",
    "ayudame", "quiero", "necesito", "tengo", "todo", "todos", "nada", "solo",
}


def emit(ctx: str) -> None:
    if ctx:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit", "additionalContext": ctx}}))


def find_memory_md(transcript_path: str) -> Path | None:
    """Prefer the MEMORY.md next to this session's transcript; fall back to the
    most-recently-touched brain-project MEMORY.md."""
    if transcript_path:
        cand = Path(transcript_path).parent / "memory" / "MEMORY.md"
        if cand.exists():
            return cand
    try:
        mds = list(PROJECTS.glob("*/memory/MEMORY.md"))
    except Exception:
        return None
    if not mds:
        return None
    try:
        return max(mds, key=lambda p: p.stat().st_mtime)
    except Exception:
        return mds[0]


def tokenize(text: str) -> set[str]:
    return {t for t in TOKEN_RE.findall(text.lower()) if t not in STOP}


def prompt_tokens(prompt: str, transcript_path: str) -> set[str]:
    text = prompt or ""
    try:
        if transcript_path and os.path.exists(transcript_path):
            with open(transcript_path, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - TAIL_BYTES))
                text += " " + f.read().decode("utf-8", "replace")
    except Exception:
        pass
    return tokenize(text)


def score_lines(md: Path, ptoks: set[str]):
    out = []
    try:
        lines = md.read_text(encoding="utf-8").splitlines()
    except Exception:
        return out
    for ln in lines:
        ln = ln.strip()
        if not ln.startswith("- ["):
            continue
        for m in ENTRY_RE.finditer(ln):
            _score_entry(out, m, ptoks)
    out.sort(key=lambda x: (-x[0], x[1]))
    return out[:MAX_HITS]


def _score_entry(out, m, ptoks):
    title, fname, hook = m.group("title"), m.group("file"), (m.group("hook") or "")
    ltoks = tokenize(title + " " + fname + " " + hook)
    overlap = ptoks & ltoks
    score = len(overlap)
    if score >= MIN_SCORE:
        out.append((score, title, fname))


# --- segunda pasada: el CUERPO, no solo el indice ------------------------
# El indice resume; una memoria de una linea no puede nombrar cada entidad que
# guarda. Un acreedor, un folio de siniestro o un numero de contrato viven en el
# CUERPO, y puntuar solo contra titulo+archivo+gancho los deja invisibles: el
# recall calla, el modelo declara la ausencia, y el operador descubre que su
# propio expediente no se consulto. Leer los 231 ficheros cuesta ~40 ms contra un
# presupuesto de 3 s, asi que la ceguera nunca fue por coste.
#
# El peso es por RAREZA a proposito. Un termino presente en casi todas las
# memorias no distingue nada; uno presente en dos o tres ES la entidad nombrada
# que se busca. Sin ese peso, el escaneo del cuerpo devolveria ruido y seria peor
# que callar.
RARE_MAX_DF = 3         # aparece en <=3 memorias: entidad nombrada, peso alto
COMMON_MAX_DF = 15      # hasta aqui aun discrimina; mas alla es palabra de fondo
RARE_W, MID_W = 3, 1
BODY_MIN_LEN = 4        # 'ya', 'con' no son entidades; exigir algo de cuerpo


def score_bodies(mem_dir: Path, ptoks: set[str], indexed: set[str]):
    """Puntua el CUERPO de cada memoria contra los tokens del prompt.

    Devuelve [(score, titulo, fichero)] para ficheros que el indice NO trajo ya.
    Fail-open: cualquier problema de lectura sale como lista vacia.
    """
    cands = [t for t in ptoks if len(t) >= BODY_MIN_LEN]
    if not cands:
        return []
    try:
        files = sorted(mem_dir.glob("*.md"))
    except Exception:
        return []
    corpus = {}
    for f in files:
        if f.name == "MEMORY.md":
            continue
        try:
            corpus[f.name] = f.read_text(encoding="utf-8", errors="ignore").lower()
        except Exception:
            continue
    if not corpus:
        return []
    df = {t: sum(1 for txt in corpus.values() if t in txt) for t in cands}
    out = []
    for fname, txt in corpus.items():
        if fname in indexed:
            continue
        score = 0
        for t in cands:
            d = df.get(t, 0)
            if d == 0:
                continue
            if d <= RARE_MAX_DF and t in txt:
                score += RARE_W
            elif d <= COMMON_MAX_DF and t in txt:
                score += MID_W
        if score >= MIN_SCORE:
            out.append((score, fname[:-3].replace("_", " "), fname))
    out.sort(key=lambda x: (-x[0], x[1]))
    return out


def main() -> int:
    try:
        data = json.load(sys.stdin) or {}
    except Exception:
        data = {}
    prompt = data.get("prompt", "") or ""
    tpath = data.get("transcript_path", "") or ""

    # A bare prompt with no real tokens (a "yes"/"dale") carries no recall signal.
    ptoks = prompt_tokens(prompt, tpath)
    if len(tokenize(prompt)) < 1:
        return 0

    md = find_memory_md(tpath)
    if not md:
        return 0
    hits = score_lines(md, ptoks)
    # El indice primero (barato y curado), el cuerpo despues para lo que el
    # indice no sabe nombrar. Sin esta segunda pasada el recall es ciego a toda
    # entidad que viva dentro de una memoria en vez de en su titular.
    indexed = {f for _, _, f in hits}
    body = score_bodies(md.parent, ptoks, indexed)
    hits = (hits + body)[:MAX_HITS] if len(hits) < MAX_HITS else hits[:MAX_HITS]
    if not hits:
        return 0

    lines = [
        "\U0001f9e0 BRAIN MEMORY RECALL - your own stored life-memories match this prompt. "
        "SEEK them (Read the file) before asking the operator or asserting a fact about his life; "
        "the connectome-heartbeat is blind to these. Relative to "
        + f"{md.parent}:"
    ]
    for score, title, fname in hits:
        lines.append(f"  - {fname}  ({title}) [match {score}]")
    emit("\n".join(lines))
    return 0


if __name__ == "__main__":
    try:
        signal.signal(signal.SIGALRM, lambda *_: sys.exit(0))
        signal.setitimer(signal.ITIMER_REAL, TIMEOUT_S)
    except (AttributeError, ValueError):
        pass  # Windows: no SIGALRM; rely on the harness hook timeout instead
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # fail-open: a skipped beat must never block the prompt
