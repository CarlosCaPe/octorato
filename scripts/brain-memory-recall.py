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
SEEK_SLOTS = 2          # slots reserved for the graph seek, never leftovers
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


def _central_slug() -> str | None:
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from generate_memory_map import brain_project_slug
        return brain_project_slug()
    except Exception:
        return None


def find_memory_md(transcript_path: str) -> Path | None:
    """This session's own MEMORY.md, else the CENTRAL brain's. Never another arm's.

    The old fallback picked the most-recently-touched MEMORY.md across ALL
    project dirs. That is a cross-arm path and the widest one left in this hook:
    the literal passes then read that dir's index AND every memory body in it,
    and the header names that dir as the base. It fires whenever the session's
    own dir has no memory yet (a new arm's first sessions) or the transcript
    path is absent. It looked benign only because the central dir happened to be
    the most recently written; `ls -t` puts two arms next in line, and the order
    flips on every memory save.

    Central is the correct fallback and the only safe one: it holds the generic
    lessons and operator identity that are meant to reach every session.
    """
    if transcript_path:
        cand = Path(transcript_path).parent / "memory" / "MEMORY.md"
        if cand.exists():
            return cand
    slug = _central_slug()
    if not slug:
        return None
    central = PROJECTS / slug / "memory" / "MEMORY.md"
    return central if central.exists() else None


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


def session_project(transcript_path: str):
    """The project dir this session actually belongs to, or None.

    Derived from the TRANSCRIPT path, never from the MEMORY.md that
    find_memory_md resolved. That fallback picks the most-recently-touched
    MEMORY.md across ALL project dirs, so in a session whose own dir has no
    memory yet it can land on ANOTHER ARM's dir. Trusting it to name the
    session would then hand that arm's memories to this one: the isolation
    filter would be seeded with the wrong arm. No transcript means no
    session-scoped dir, and the seek falls back to the central brain only.
    """
    if not transcript_path:
        return None
    try:
        parent = Path(transcript_path).parent
        return parent.name if parent.parent.name == "projects" else None
    except Exception:
        return None


def seek_index(prompt: str, mem_dir, want: int, session_dir=None):
    """Cosine seek over memory_map.json. Returns [(label, title, fname)] or [].

    UNION with the existing token overlap, never a replacement. The two are blind
    in different directions: overlap catches a literal term the index may have
    down-weighted as common; the index catches a memory that shares NO literal
    term with the prompt (different phrasing, or English memory vs Spanish
    prompt, bridged by the ES<->EN lexicon). Replacing one with the other would
    trade one blindness for another.

    Fail-open in every branch: a missing or stale index costs nothing.
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from generate_memory_map import load_index, score_prompt
    except Exception:
        return []
    idx = load_index()
    if not idx:
        return []
    try:
        from generate_memory_map import brain_project_slug
        # ARM ISOLATION. Only this session's own project dir and the CENTRAL
        # brain dir. A cwd-scoped dir belonging to another arm is that arm's
        # sealed memory, and routing it here would make this the first hook to
        # tell one arm that another exists. Filter, never bias.
        allowed = {brain_project_slug()}
        if session_dir:
            allowed.add(session_dir)
        hits = score_prompt(idx, prompt, top_n=want, min_score=0.06, projects=allowed)
    except Exception:
        return []
    out = []
    for score, _key, node in hits:
        # Emit the STORED ABSOLUTE PATH, not id + ".md". The header announces one
        # base directory, and a hit from the central brain dir does not exist
        # under an arm's dir: the model was being told to Read a missing file.
        path = node.get("path") or ""
        out.append((f"seek {score:.2f}", node.get("title", node.get("id", "")), path))
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
    # One file, one slot. MEMORY.md can list the same memory under two titles,
    # and both scored rows were emitted, burning a slot on a duplicate.
    seen_files = set()
    deduped = []
    for row in hits:
        if row[2] in seen_files:
            continue
        seen_files.add(row[2])
        deduped.append(row)
    hits = deduped

    indexed = {f for _, _, f in hits}
    body = score_bodies(md.parent, ptoks, indexed)
    hits = (hits + body)[:MAX_HITS] if len(hits) < MAX_HITS else hits[:MAX_HITS]

    # Third pass: the graph. It reaches what neither literal pass can — a memory
    # that shares NO token with the prompt (different phrasing, or an English
    # memory under a Spanish prompt, bridged by the ES<->EN lexicon).
    #
    # It gets a RESERVED budget, not the leftovers. The literal passes routinely
    # saturate MAX_HITS with weak overlaps, and a "add it if there is room" union
    # then never fires: measured on this brain, the seek contributed 0 rows
    # because 5/5 slots were already taken by token noise. Reserving is what
    # makes the union real.
    seek = seek_index(prompt, md.parent, SEEK_SLOTS * 2, session_project(tpath))
    if seek:
        # Identity is the RESOLVED PATH, never the bare filename. The index
        # deliberately keys nodes as project/stem so two memories CAN share a
        # slug across project dirs; deduping on the filename threw one away.
        def ident(row):
            f = row[2]
            return f if f.startswith("/") else str(md.parent / f)

        seen = {ident(r) for r in hits}
        fresh = [r for r in seek if ident(r) not in seen]
        # Reserve only what the seek can actually FILL. Truncating literal hits
        # before knowing how many seek rows are new sacrificed rows for slots
        # that then went unused.
        keep = MAX_HITS - min(SEEK_SLOTS, len(fresh))
        hits = hits[:keep]
        seen = {ident(r) for r in hits}
        for row in fresh:
            if len(hits) >= MAX_HITS:
                break
            if ident(row) not in seen:
                hits.append(row)
                seen.add(ident(row))

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
