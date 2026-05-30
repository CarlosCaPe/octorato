#!/usr/bin/env python3
"""Sync the skill/agent counts cited in README.md to the real numbers on disk.

The README quoted '190+ skills' and '150+/160+ agents' in ~16 places (prose,
headings, TOC anchors, ASCII diagrams) and they drifted apart. This script makes
those numbers DESCEND from the filesystem (the source of truth) so they can never
drift again. Idempotent: run it as often as you like; it only writes when a count
actually changed. Wire into pre-commit / ai-push to keep it honest forever.

Counting rule (matches `delegate-check` / the connectome's reported totals):
  skills = number of directories under skills/
  agents = number of *.md under agents/ excluding meta (README/REGISTRY/_*) and examples/
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"


def count_skills() -> int:
    return sum(1 for p in (ROOT / "skills").iterdir() if p.is_dir())


def count_agents() -> int:
    return sum(
        1 for p in (ROOT / "agents").rglob("*.md")
        if not p.name.upper().startswith(("README", "REGISTRY", "_"))
        and "examples" not in p.parts
    )


SKILL_WORDS = r"(skills|Skills|reusable techniques|synapses|generic skills|by name)"
AGENT_WORDS = r"(agent personas|agents|Agents|specialist agents|specialist processors|generic agent personas|AI agent personas)"


def _restore_box_width(original: str, new: str) -> str:
    """If a line is part of an ASCII box (contains '│'), keep the closing border
    aligned by padding/trimming the space run before the last '│'."""
    if "│" not in original or len(new) == len(original):
        return new
    diff = len(original) - len(new)  # >0 => new shorter, add spaces
    idx = new.rfind("│")
    if idx <= 0:
        return new
    j = idx
    while j > 0 and new[j - 1] == " ":
        j -= 1
    if diff > 0:
        return new[:idx] + " " * diff + new[idx:]
    if (idx - j) >= -diff:  # enough spaces to remove
        return new[: idx + diff] + new[idx:]
    return new


def sync(write: bool = True) -> bool:
    skills, agents = count_skills(), count_agents()
    lines = README.read_text(encoding="utf-8").split("\n")
    out, changed = [], 0
    for line in lines:
        new = re.sub(rf"\b\d{{2,4}}\+\s+{SKILL_WORDS}", lambda m: f"{skills} {m.group(1)}", line)
        new = re.sub(rf"\b\d{{2,4}}\+\s+{AGENT_WORDS}", lambda m: f"{agents} {m.group(1)}", new)
        # TOC anchors (no '+', hyphenated)
        new = re.sub(r"-\d{2,4}-agents\b", f"-{agents}-agents", new)
        new = re.sub(r"-\d{2,4}-reusable-techniques\b", f"-{skills}-reusable-techniques", new)
        new = _restore_box_width(line, new)
        if new != line:
            changed += 1
        out.append(new)
    result = "\n".join(out)
    if result != README.read_text(encoding="utf-8"):
        if write:
            README.write_text(result, encoding="utf-8")
        print(f"sync-readme-counts: {skills} skills · {agents} agents — updated {changed} line(s)")
        return True
    print(f"sync-readme-counts: {skills} skills · {agents} agents — already in sync")
    return False


if __name__ == "__main__":
    check = "--check" in sys.argv
    drifted = sync(write=not check)
    # In --check (pre-commit) mode, exit non-zero if drift was found.
    sys.exit(1 if (check and drifted) else 0)
