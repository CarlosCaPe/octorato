#!/usr/bin/env python3
"""arm-recall-hook.py — UserPromptSubmit beat: force recall of an ARM's own stored
elements (its knowledge.json files + arm-memory index) BEFORE researching or asking.

Why this exists
---------------
The `connectome-heartbeat` circulates only the BRAIN's skills/agents. It is blind to
an arm's local `knowledge.json` knowledge bases and its `.claude/memory/`. So the model
re-researches (a full deep-research) or asks the operator for things ALREADY captured in
the arm. That is a recurrent, costly bug: not a discipline failure, a missing reflex.

This hook is that reflex. When the current work is inside an arm (detected from the
transcript tail + prompt), it injects a compact index of that arm's stored elements so
the model SEEKS them first. It does not read their contents (cheap), it points at them.

Contract (UserPromptSubmit):
  stdin : {"prompt": str, "transcript_path": str, ...}
  stdout: {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "..."}}

Budget / safety: globs with directory pruning + depth cap, a hard SIGALRM self-timeout,
and fail-open everywhere. A skipped beat is survivable; a hung prompt is not.
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
BRAIN = Path(__file__).resolve().parent.parent
ARMS_CFG = BRAIN / "company" / "config" / "arms-paths.json"

TIMEOUT_S = 3
MAX_KJSON = 14
DEPTH_CAP = 5
TAIL_BYTES = 80_000
SKIP_DIRS = {
    "node_modules", ".venv", ".git", "__pycache__", "dist", ".wrangler",
    ".pytest_cache", ".ruff_cache", ".astro", ".next", "build", "coverage",
    # worktree checkouts hold duplicate copies of the canonical knowledge.json
    "worktrees", ".worktrees",
}


def emit(ctx: str) -> None:
    if ctx:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit", "additionalContext": ctx}}))


def load_arms() -> dict:
    try:
        return json.loads(ARMS_CFG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def arm_roots(arms: dict):
    """Resolve each arm code to the first existing absolute root dir."""
    out = []
    for code, val in arms.items():
        cands = val if isinstance(val, list) else [val]
        for c in cands:
            p = Path(c) if os.path.isabs(c) else (HOME / c)
            if p.is_dir():
                out.append((code, p))
                break
    return out


def active_arm(prompt: str, transcript_path: str, roots):
    """Pick the arm whose root path appears latest in (prompt + transcript tail).
    Path-fragment match wins; the arm code as a bare token is a weak fallback."""
    text = prompt or ""
    try:
        if transcript_path and os.path.exists(transcript_path):
            with open(transcript_path, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - TAIL_BYTES))
                text += f.read().decode("utf-8", "replace")
    except Exception:
        pass

    best, best_idx = None, -1
    for code, root in roots:
        idx = text.rfind(str(root))
        if idx < 0:
            matches = list(re.finditer(r"\b" + re.escape(code) + r"\b", text))
            idx = matches[-1].start() if matches else -1
        if idx > best_idx:
            best, best_idx = (code, root), idx
    return best


def find_knowledge(root: Path):
    """os.walk with dir pruning + depth cap so a big arm (node_modules, etc.)
    never blows the budget."""
    found = []
    root_parts = len(root.parts)
    for dirpath, dirnames, filenames in os.walk(root):
        depth = len(Path(dirpath).parts) - root_parts
        if depth >= DEPTH_CAP:
            dirnames[:] = []
        else:
            dirnames[:] = [d for d in dirnames
                           if d not in SKIP_DIRS and not d.startswith(".octorato")]
        if "knowledge.json" in filenames:
            found.append(Path(dirpath) / "knowledge.json")
            if len(found) >= MAX_KJSON:
                break
    return sorted(found)


def kj_header(p: Path) -> str:
    """Cheap one-line descriptor: label/description + last_updated. Never full-parse a huge file blindly."""
    try:
        if p.stat().st_size > 500_000:
            return ""
        d = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(d, dict):
            return ""
        lbl = d.get("label") or d.get("description") or d.get("domain") or ""
        upd = d.get("last_updated") or ""
        s = str(lbl).replace("\n", " ").strip()[:90]
        return s + (f" ({upd})" if upd else "")
    except Exception:
        return ""


def memory_line(root: Path) -> str:
    mem = root / ".claude" / "memory" / "MEMORY.md"
    if not mem.exists():
        return ""
    try:
        n = sum(1 for ln in mem.read_text(encoding="utf-8").splitlines()
                if ln.strip().startswith("- ["))
        return f"  - .claude/memory/MEMORY.md  ({n} arm-memory entries — recall before asking)"
    except Exception:
        return "  - .claude/memory/MEMORY.md"


def main() -> int:
    try:
        data = json.load(sys.stdin) or {}
    except Exception:
        data = {}
    prompt = data.get("prompt", "") or ""
    tpath = data.get("transcript_path", "") or ""

    roots = arm_roots(load_arms())
    if not roots:
        return 0
    arm = active_arm(prompt, tpath, roots)
    if not arm:
        return 0
    code, root = arm

    kjs = []
    for kp in find_knowledge(root):
        rel = kp.relative_to(root)
        hdr = kj_header(kp)
        kjs.append(f"  - {rel}" + (f"  — {hdr}" if hdr else ""))
    mem = memory_line(root)
    if not kjs and not mem:
        return 0

    lines = [
        f"♦ ARM RECALL ('{code}') — this arm already holds stored elements. SEEK them "
        f"(Read) before researching or asking the operator; do NOT re-derive what is already "
        f"captured. The connectome-heartbeat is blind to arm knowledge; this is its arm-side twin:"
    ]
    lines.extend(kjs)
    if mem:
        lines.append(mem)
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
