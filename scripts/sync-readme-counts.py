#!/usr/bin/env python3
"""Sync the skill/agent counts cited in README.md + FAQ.md to the numbers on disk.

The docs quoted skill/agent counts in ~16 places (prose, headings, TOC anchors,
ASCII diagrams) and they drifted apart. This script makes those numbers DESCEND
from the filesystem (the source of truth) so they can never drift again.
Idempotent: run it as often as you like; it only writes when a count changed.
Wire into pre-commit / ai-push to keep it honest forever.

Two output formats:
  exact (default)  ->  "197 skills · 183 specialist agents"
  --floor          ->  "190+ skills · 180+ specialist agents"
                       (real count rounded DOWN to the nearest ten, so the floor
                        is always TRUE and stable across small changes — the
                        operator's stat convention, also enforced by
                        check-stats-drift.py)

--floor additionally normalizes the agent label to "specialist agents" in prose
(but NOT in headings, TOC links, or ASCII boxes, where doing so would break
anchor slugs or fixed-width borders).

Counting rule (matches `delegate-check` / the connectome's reported totals):
  skills = number of directories under skills/
  agents = number of *.md under agents/ excluding meta (README/REGISTRY/_*) and examples/
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = [ROOT / "README.md", ROOT / "FAQ.md"]


def count_skills() -> int:
    # A skill is a dir that actually carries a SKILL.md — container dirs like
    # learned/ (draft staging) don't count. Matches the wiki catalog's rule so
    # the public exact numbers agree everywhere.
    return sum(
        1 for p in (ROOT / "skills").iterdir()
        if p.is_dir() and (p / "SKILL.md").exists()
    )


def count_agents() -> int:
    # Match brain-stats.py exactly: recursive personas, excluding the reference
    # divisions (examples/, strategy/ — playbooks/runbooks/briefs, not personas).
    return sum(
        1 for p in (ROOT / "agents").rglob("*.md")
        if not p.name.upper().startswith(("README", "REGISTRY", "_", "INDEX"))
        and "examples" not in p.parts
        and "strategy" not in p.parts
    )


def floor_ten(n: int) -> int:
    """Round DOWN to the nearest ten (188 -> 180, 197 -> 190)."""
    return (n // 10) * 10


# A *total* count token: 3-4 digits (150..197, with optional '+'), or any digits
# that already carry a '+'. This deliberately EXCLUDES bare 1-2 digit numbers so
# per-division counts ("28 agents", "← 8 agents") are never clobbered.
NUM = r"(?:\d{3,4}\+?|\d{1,4}\+)"
SKILL_WORDS = r"(skills|Skills|reusable techniques|synapses|generic skills|by name)"
AGENT_WORDS = r"(AI agent personas|generic agent personas|agent personas|specialist agents|specialist processors|agents|Agents)"


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


def sync(write: bool = True, floor: bool = False) -> bool:
    skills, agents = count_skills(), count_agents()
    if floor:
        skills_tok, agents_tok = f"{floor_ten(skills)}+", f"{floor_ten(agents)}+"
        skills_anchor, agents_anchor = floor_ten(skills), floor_ten(agents)
    else:
        skills_tok, agents_tok = str(skills), str(agents)
        skills_anchor, agents_anchor = skills, agents

    changed_total = 0
    wrote_any = False
    for target in TARGETS:
        if not target.exists():
            continue
        before = target.read_text(encoding="utf-8")
        out, changed = [], 0
        for line in before.split("\n"):
            is_box = "│" in line
            is_heading = line.lstrip().startswith("#")
            is_toc = "](#" in line
            relabel = floor and not is_box and not is_heading and not is_toc

            new = re.sub(rf"\b{NUM}\s+{SKILL_WORDS}",
                         lambda m: f"{skills_tok} {m.group(1)}", line)
            if relabel:
                new = re.sub(rf"\b{NUM}\s+{AGENT_WORDS}",
                             lambda m: f"{agents_tok} specialist agents", new)
            else:
                new = re.sub(rf"\b{NUM}\s+{AGENT_WORDS}",
                             lambda m: f"{agents_tok} {m.group(1)}", new)
            # TOC / heading anchors (no '+', hyphenated)
            new = re.sub(r"-\d{2,4}-agents\b", f"-{agents_anchor}-agents", new)
            new = re.sub(r"-\d{2,4}-reusable-techniques\b", f"-{skills_anchor}-reusable-techniques", new)
            new = _restore_box_width(line, new)
            if new != line:
                changed += 1
            out.append(new)
        result = "\n".join(out)
        if result != before:
            changed_total += changed
            wrote_any = True
            if write:
                target.write_text(result, encoding="utf-8")
            print(f"sync-readme-counts: {target.name} — updated {changed} line(s)")

    fmt = f"{skills_tok} skills · {agents_tok} specialist agents"
    if wrote_any:
        print(f"sync-readme-counts: {fmt} — {changed_total} line(s) total")
    else:
        print(f"sync-readme-counts: {fmt} — already in sync")
    return wrote_any


if __name__ == "__main__":
    check = "--check" in sys.argv
    floor = "--floor" in sys.argv
    drifted = sync(write=not check, floor=floor)
    # In --check (pre-commit) mode, exit non-zero if drift was found.
    sys.exit(1 if (check and drifted) else 0)
