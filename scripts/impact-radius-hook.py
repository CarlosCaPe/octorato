#!/usr/bin/env python3
"""impact-radius-hook — PostToolUse Write|Edit reflex (the cerebellum's feedback arm).

When a CONCEPT file (a skill's SKILL.md) is edited, automatically run
impact-radius and surface every OTHER file that references the same concept, so
the agent reconciles them in the SAME change instead of leaving stale references
— the "pixelation" failure (codify in one place, leave refs stale), the #1
recurrent miss. Involuntary: it fires on the write itself, not on the agent
remembering to scan. Advisory (systemMessage), exits 0 — never blocks the edit.

This is the feedforward⇄feedback loop's feedback half made autonomic: the 4D
Gate Manifest predicts the target file-set (feedforward); this hook + the
Provenance `Touched` reconcile what was actually touched (feedback).
"""
import sys
import json
import subprocess
from pathlib import Path

CLAUDE_DIR = Path(__file__).resolve().parent.parent
PREFIXES = ("skills/", "agents/", "commands/", "docs/", "CLAUDE.md",
            "README", "WHITEPAPER", "ROADMAP", "SHOWCASE", "CONTRIBUTING")


def main():
    try:
        ev = json.loads(sys.stdin.read() or "{}")
    except Exception:
        sys.exit(0)
    fp = (ev.get("tool_input", {}) or {}).get("file_path") or ""
    if not fp:
        sys.exit(0)
    try:
        rel = Path(fp).resolve().relative_to(CLAUDE_DIR).as_posix()
    except Exception:
        sys.exit(0)
    # Only react to concept files: a skill's SKILL.md. CLAUDE.md is too broad to
    # auto-derive a single term; the ULTRA rule covers it manually.
    if not rel.endswith("/SKILL.md"):
        sys.exit(0)
    term = Path(rel).parent.name
    try:
        out = subprocess.run(
            ["python3", str(CLAUDE_DIR / "scripts" / "impact-radius.py"), term],
            capture_output=True, text=True, timeout=20,
        ).stdout
    except Exception:
        sys.exit(0)
    files = [ln.strip() for ln in out.splitlines() if ln.strip().startswith(PREFIXES)]
    files = [f for f in files if f != rel]
    if files:
        shown = ", ".join(files[:6]) + (" …" if len(files) > 6 else "")
        print(json.dumps({"systemMessage":
            f"♥ Impact Radius — concept '{term}' is referenced in {len(files)} other "
            f"file(s): {shown}. Reconcile your Provenance `Touched` against these "
            f"(update each, or consciously skip) — don't leave stale refs."}))
    sys.exit(0)


if __name__ == "__main__":
    main()
