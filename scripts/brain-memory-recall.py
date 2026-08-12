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
INDEX_RE = re.compile(r"^- \[(?P<title>[^\]]+)\]\((?P<file>[^)]+)\)\s*[:\-]\s*(?P<hook>.*)$")
# Una linea del indice puede compactar VARIAS entradas separadas por " · ".
# Leer solo la primera (INDEX_RE.match) dejaba muda a toda entrada en segunda
# posicion: mitad del canon sin recall y el doctor contandola como no-indexada.
ENTRY_RE = re.compile(r"\[(?P<title>[^\]]+)\]\((?P<file>[^)]+)\)\s*[:\-]\s*(?P<hook>[^·]*)")
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
        if not ln.startswith("- ") or not INDEX_RE.match(ln):
            continue
        for m in ENTRY_RE.finditer(ln):
            _score_entry(out, m, ptoks)
    out.sort(key=lambda x: (-x[0], x[1]))
    return out[:MAX_HITS]


def _score_entry(out, m, ptoks):
    title, fname, hook = m.group("title"), m.group("file"), m.group("hook")
    ltoks = tokenize(title + " " + fname + " " + hook)
    overlap = ptoks & ltoks
    score = len(overlap)
    if score >= MIN_SCORE:
        out.append((score, title, fname))


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
