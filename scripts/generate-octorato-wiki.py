#!/usr/bin/env python3
"""Regenerate the octorato wiki catalog pages from the live brain.

The wiki (docs/wiki/) is a SOURCE that gets published to the separate octorato.wiki
repo. Its skill/agent catalogs used to be hand-maintained and drifted (189 vs the
202 skills actually on disk). This script is the single source the lineage edge
`wiki-generated` always promised: it derives the catalogs from the filesystem so
"update the docs" is one deterministic command, never a hand-edit.

Sources of truth (never invented):
  skills/<slug>/SKILL.md   -> Skills.md   (grouped by frontmatter metadata.type)
  agents/REGISTRY.md       -> Agents.md   (the declared source for personas/divisions)

Targets:
  docs/wiki/Skills.md      (fully regenerated)
  docs/wiki/Agents.md      (fully regenerated)
  docs/wiki/Home.md        (count tokens patched in place — prose preserved)
  docs/wiki/_Sidebar.md    (count tokens patched in place)

Usage:
  python3 scripts/generate-octorato-wiki.py            # dry-run: print counts + planned writes
  python3 scripts/generate-octorato-wiki.py --write    # apply
  python3 scripts/generate-octorato-wiki.py --date 2026-06-01 --write   # pin the "Live as of" date

Dry-run by default (dry-run-gate-pattern). Counts are reported old->new so a
divergence (e.g. a stale agent count) is surfaced, never silently clobbered.
"""
import datetime
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "skills"
REGISTRY = ROOT / "agents" / "REGISTRY.md"
WIKI = ROOT / "docs" / "wiki"
REPO_BLOB = "https://github.com/CarlosCaPe/octorato/blob/master"
DESC_MAX = 280  # truncation budget for a one-line catalog entry (incl. the " …")


def _frontmatter(text: str) -> dict:
    """Minimal front-matter parse: name (slug overrides), metadata.type, description.
    Avoids a yaml dependency edge case where description spans lines."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    fm = text[3:end]
    out, cur_key = {}, None
    in_meta = False
    for raw in fm.splitlines():
        if not raw.strip():
            continue
        if re.match(r"^\S", raw):  # top-level key
            in_meta = raw.startswith("metadata:")
            m = re.match(r"^(\w[\w-]*):\s*(.*)$", raw)
            if m:
                cur_key = m.group(1)
                if m.group(2):
                    out[cur_key] = m.group(2).strip()
        elif in_meta:
            m = re.match(r"^\s+(\w[\w-]*):\s*(.*)$", raw)
            if m and m.group(1) == "type":
                out["type"] = m.group(2).strip()
        elif cur_key == "description":  # continuation line of a folded description
            out["description"] = (out.get("description", "") + " " + raw.strip()).strip()
    return out


def _one_line(desc: str) -> str:
    desc = re.sub(r"\s+", " ", desc).strip().strip('"')
    if len(desc) > DESC_MAX:
        desc = desc[: DESC_MAX - 2].rstrip() + " …"
    return desc


def parse_skills():
    skills = []
    for sk in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        slug = sk.parent.name
        fm = _frontmatter(sk.read_text(encoding="utf-8", errors="replace"))
        skills.append({
            "slug": slug,
            "type": fm.get("type", "general"),
            "desc": _one_line(fm.get("description", "")),
        })
    return skills


EXCLUDED_AGENT_DIRS = {"examples", "strategy"}


def _registry_triggers():
    """slug -> triggers, harvested from REGISTRY.md rows. Best-effort enrichment only;
    correctness of the count never depends on REGISTRY (it comes from the filesystem)."""
    out = {}
    if not REGISTRY.exists():
        return out
    for line in REGISTRY.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.search(r"\]\(([a-z0-9/_.-]+?\.md)\)\s*\|\s*(.*?)\s*\|?\s*$", line)
        if m:
            out[Path(m.group(1)).stem] = m.group(2).strip()
    return out


def parse_agents():
    """Source of truth = the filesystem, matching brain-stats.py / count_agents()
    EXACTLY: every persona `*.md` under agents/, excluding meta files and the
    reference divisions (examples/, strategy/). Grouped by top-level division dir.
    REGISTRY.md is used only to enrich the Triggers column, never to count."""
    triggers = _registry_triggers()
    agents_root = ROOT / "agents"
    divisions = {}
    for p in sorted(agents_root.rglob("*.md")):
        rel = p.relative_to(agents_root)
        if rel.parts[0] in EXCLUDED_AGENT_DIRS:
            continue
        if p.name.upper().startswith(("README", "REGISTRY", "_", "INDEX")):
            continue
        fm = _frontmatter(p.read_text(encoding="utf-8", errors="replace"))
        divisions.setdefault(rel.parts[0], []).append({
            "name": fm.get("name", p.stem),
            "triggers": triggers.get(p.stem, ""),
        })
    return {d: sorted(a, key=lambda x: x["name"].lower()) for d, a in divisions.items() if a}


def render_skills(skills):
    by_type = {}
    for s in skills:
        by_type.setdefault(s["type"], []).append(s)
    out = [f"# Skills — the *HOW* ({len(skills)} total)", "",
           "Every technique the brain can apply. Grouped by declared `type`. "
           "Each skill lives at `skills/<slug>/SKILL.md` in the repo.", ""]
    for t in sorted(by_type):
        rows = sorted(by_type[t], key=lambda s: s["slug"])
        out.append(f"## {t} ({len(rows)})")
        out.append("")
        for s in rows:
            out.append(f"- **[`{s['slug']}`]({REPO_BLOB}/skills/{s['slug']}/SKILL.md)** — {s['desc']}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def render_agents(divisions, total):
    out = [f"# Agents — the *WHO* ({total} personas, {len(divisions)} divisions)", "",
           "Specialist personas the brain activates as subagents. Agent = who (role), "
           "skill = how (technique), arm = for whom (client). Source: persona files on "
           "disk under `agents/` (count matches brain-stats), enriched by `agents/REGISTRY.md`.", ""]
    for d in sorted(divisions, key=str.lower):
        agents = divisions[d]
        out.append(f"## {d.lower()} ({len(agents)})")
        out.append("")
        out.append("| Agent | Triggers |")
        out.append("|---|---|")
        for a in agents:
            out.append(f"| {a['name']} | {a['triggers']} |")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def patch_counts(path: Path, nskills: int, nagents: int, date: str):
    txt = path.read_text(encoding="utf-8")
    orig = txt
    txt = re.sub(r"\*\*Live as of \d{4}-\d{2}-\d{2}:\*\*", f"**Live as of {date}:**", txt)
    txt = re.sub(r"\b\d+\s+skills\b", f"{nskills} skills", txt)
    txt = re.sub(r"\b\d+\s+agent personas\b", f"{nagents} agent personas", txt)
    txt = re.sub(r"catalog of \d+ techniques", f"catalog of {nskills} techniques", txt)
    txt = re.sub(r"(\[\[Skills\]\]\*\*\s*\()\d+(\))", rf"\g<1>{nskills}\g<2>", txt)
    txt = re.sub(r"(\[\[Agents\]\]\*\*\s*\()\d+(\))", rf"\g<1>{nagents}\g<2>", txt)
    return txt, (txt != orig)


def main():
    args = sys.argv[1:]
    write = "--write" in args
    date = datetime.date.today().isoformat()
    if "--date" in args:
        date = args[args.index("--date") + 1]

    skills = parse_skills()
    divisions = parse_agents()
    nagents = sum(len(a) for a in divisions.values())
    nskills = len(skills)

    types = {}
    for s in skills:
        types[s["type"]] = types.get(s["type"], 0) + 1

    print(f"SKILLS: {nskills}  ({', '.join(f'{t}={n}' for t, n in sorted(types.items()))})")
    print(f"AGENTS: {nagents} across {len(divisions)} divisions  "
          f"({', '.join(f'{d.lower()}={len(a)}' for d, a in sorted(divisions.items()))})")

    renders = {
        WIKI / "Skills.md": render_skills(skills),
        WIKI / "Agents.md": render_agents(divisions, nagents),
    }
    for p in (WIKI / "Home.md", WIKI / "_Sidebar.md"):
        if p.exists():
            new, changed = patch_counts(p, nskills, nagents, date)
            renders[p] = new
            print(f"  patch {p.relative_to(ROOT)}: {'CHANGED' if changed else 'no-op'}")

    if not write:
        print("\nDRY-RUN — no files written. Re-run with --write to apply.")
        return 0

    for p, content in renders.items():
        p.write_text(content, encoding="utf-8")
        print(f"  wrote {p.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
