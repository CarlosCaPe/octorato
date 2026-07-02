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
# Force UTF-8 on stdout/stderr so the ✓ / ✗ / em-dash glyphs in reports
# survive on Windows shells defaulting to cp1252. Without this, a script
# can do its work correctly and still crash with UnicodeEncodeError when
# printing success. Applied repo-wide by _apply-utf8-reconfigure.py.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


CLAUDE_DIR = Path(__file__).resolve().parent.parent
PREFIXES = ("skills/", "agents/", "commands/", "docs/", "CLAUDE.md",
            "README", "WHITEPAPER", "ROADMAP", "SHOWCASE", "CONTRIBUTING")


def _concept_rel(fp: str):
    """The repo-relative path IFF *fp* is a concept file we react to (a skill's
    SKILL.md), else None. Factored so the trigger is selftest-provable."""
    if not fp:
        return None
    try:
        rel = Path(fp).resolve().relative_to(CLAUDE_DIR).as_posix()
    except Exception:
        return None
    # CLAUDE.md is too broad to auto-derive a single term; the ULTRA rule covers it manually.
    return rel if rel.endswith("/SKILL.md") else None


def main():
    try:
        ev = json.loads(sys.stdin.read() or "{}")
    except Exception:
        sys.exit(0)
    fp = (ev.get("tool_input", {}) or {}).get("file_path") or ""
    rel = _concept_rel(fp)
    if rel is None:
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


def _selftest() -> int:
    """Prove the detector fires on the right surface and stays silent on the wrong
    one: a SKILL.md is a concept file (reacts), a plain script is not (silent)."""
    pos = _concept_rel(str(CLAUDE_DIR / "skills" / "human-cadence" / "SKILL.md"))
    neg = _concept_rel(str(CLAUDE_DIR / "scripts" / "impact-radius-hook.py"))
    ok = bool(pos) and neg is None
    print("selftest PASS: reacts to SKILL.md, silent on scripts" if ok
          else f"selftest FAIL: pos={pos!r} neg={neg!r}",
          file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    main()
