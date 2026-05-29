#!/usr/bin/env python3
"""capability_inventory.py — read-only capability census of skills + agents (issue #28).

Scans every agent (`agents/**/*.md`) and skill (`skills/**/SKILL.md`) and counts
which tools / privileged actions each one declares or invokes:

  - Agents declare tools in YAML front-matter: `tools: Read, Write, Bash` (or
    "All tools" / "*" for the unrestricted set).
  - Skills rarely declare front-matter tools; they reference tool names in their
    body (e.g. "use Bash to…", "@Agent"). We count whole-word body references.

Output: a Markdown frequency table written to `docs/capability-inventory.md`
(tool → agent count → skill count → total → example files). This is the input
to the M1 Kernel-ABI RFC: it shows what privileged actions agents actually take.

Pure stdlib, read-only, no network. Deterministic output (sorted), so re-runs
produce a stable diff.

    python3 scripts/capability_inventory.py            # writes docs/capability-inventory.md
    python3 scripts/capability_inventory.py --stdout   # print to stdout instead
    python3 scripts/capability_inventory.py --check     # exit 1 if output is stale
"""
import argparse
import os
import re
import sys
from pathlib import Path

CLAUDE_DIR = Path(os.environ.get("CLAUDE_DIR", Path.home() / ".claude"))
AGENTS_DIR = CLAUDE_DIR / "agents"
SKILLS_DIR = CLAUDE_DIR / "skills"
OUTPUT = CLAUDE_DIR / "docs" / "capability-inventory.md"

# The Claude Code tool vocabulary we census. Whole-word, case-sensitive match
# (these are PascalCase tool identifiers, distinct from common English words).
TOOL_VOCAB = [
    "Bash", "Read", "Write", "Edit", "MultiEdit", "NotebookEdit",
    "Grep", "Glob", "Agent", "Task", "WebFetch", "WebSearch",
    "Skill", "TodoWrite",
]
ALL_TOOLS_MARKERS = ("all tools", "*")


def split_frontmatter(text):
    """Return (frontmatter_dict_subset, body). Only parses the leading --- block."""
    fm = {}
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            block = text[3:end]
            body = text[end + 4:]
            for line in block.splitlines():
                if ":" in line and not line.lstrip().startswith("#"):
                    key, _, val = line.partition(":")
                    fm[key.strip().lower()] = val.strip()
    return fm, body


def parse_agent_tools(fm):
    """Classify an agent's tool declaration.

    Returns (tools_set, kind) where kind is one of:
      - "explicit"  : a comma-separated `tools:` list (tools_set populated)
      - "all"       : `tools: All tools` / `*` (explicitly unrestricted)
      - "unscoped"  : no `tools:` key at all (implicitly unrestricted at runtime)
    The distinction matters for the M1 ABI: "unscoped" agents take every
    privileged action by default, which is the security fact the RFC needs.
    """
    raw = fm.get("tools", "")
    if not raw:
        return set(), "unscoped"
    if raw.strip().lower() in ALL_TOOLS_MARKERS:
        return set(), "all"
    tools = {t.strip() for t in raw.split(",") if t.strip()}
    return tools, "explicit"


def body_tool_refs(body):
    """Whole-word tool identifiers referenced in a skill/agent body."""
    found = set()
    for tool in TOOL_VOCAB:
        if re.search(r"\b" + re.escape(tool) + r"\b", body):
            found.add(tool)
    return found


def scan():
    # tool -> {"agents": set(paths), "skills": set(paths)}
    inv = {t: {"agents": set(), "skills": set()} for t in TOOL_VOCAB}
    all_tools_agents = []   # explicit "All tools" / "*"
    unscoped_agents = []    # no tools: key — implicitly unrestricted

    for path in sorted(AGENTS_DIR.rglob("*.md")):
        if path.name == "REGISTRY.md":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        fm, body = split_frontmatter(text)
        tools, kind = parse_agent_tools(fm)
        rel = path.relative_to(CLAUDE_DIR).as_posix()
        if kind == "all":
            all_tools_agents.append(rel)
            for t in TOOL_VOCAB:
                inv[t]["agents"].add(rel)
        elif kind == "unscoped":
            unscoped_agents.append(rel)
        else:  # explicit list — the signal we want per-tool
            for t in tools:
                if t in inv:
                    inv[t]["agents"].add(rel)

    for path in sorted(SKILLS_DIR.rglob("SKILL.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        _, body = split_frontmatter(text)
        rel = path.relative_to(CLAUDE_DIR).as_posix()
        for t in body_tool_refs(body):
            inv[t]["skills"].add(rel)

    return inv, all_tools_agents, unscoped_agents


def render(inv, all_tools_agents, unscoped_agents):
    rows = []
    for tool in TOOL_VOCAB:
        a = inv[tool]["agents"]
        s = inv[tool]["skills"]
        total = len(a) + len(s)
        if total == 0:
            continue
        example = sorted(s)[0] if s else (sorted(a)[0] if a else "")
        rows.append((tool, len(a), len(s), total, example))
    rows.sort(key=lambda r: (-r[3], r[0]))

    out = []
    out.append("# Capability Inventory\n")
    out.append(
        "> Generated by `scripts/capability_inventory.py` (read-only). "
        "Counts which tools/actions each agent declares (front-matter `tools:`) "
        "and which each skill references (body). Input to the M1 Kernel-ABI RFC.\n"
    )
    out.append(f"- Agents scanned: **{_agent_count()}**")
    out.append(f"- Skills scanned: **{_skill_count()}**")
    out.append(f"- Agents explicitly unrestricted (`All tools`/`*`): **{len(all_tools_agents)}**")
    out.append(
        f"- Agents **unscoped** (no `tools:` key → implicitly every tool at runtime): "
        f"**{len(unscoped_agents)}**"
    )
    out.append(
        "\n> ⚠️ The per-tool counts below reflect *explicit* declarations only. "
        "The unscoped agents above take every privileged action by default — "
        "closing that gap is the point of the M1 Kernel boundary.\n"
    )
    out.append("| Tool / action | Agents (explicit) | Skills | Total | Example file |")
    out.append("|---|---:|---:|---:|---|")
    for tool, na, ns, total, example in rows:
        out.append(f"| `{tool}` | {na} | {ns} | {total} | `{example}` |")
    out.append("")
    return "\n".join(out) + "\n"


def _agent_count():
    return sum(1 for p in AGENTS_DIR.rglob("*.md") if p.name != "REGISTRY.md")


def _skill_count():
    return sum(1 for _ in SKILLS_DIR.rglob("SKILL.md"))


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--stdout", action="store_true", help="print to stdout instead of writing the file")
    ap.add_argument("--check", action="store_true", help="exit 1 if docs/capability-inventory.md is stale")
    args = ap.parse_args()

    inv, all_tools_agents, unscoped_agents = scan()
    content = render(inv, all_tools_agents, unscoped_agents)

    if args.stdout:
        sys.stdout.write(content)
        return 0
    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != content:
            print("capability-inventory.md is stale — run scripts/capability_inventory.py", file=sys.stderr)
            return 1
        print("capability-inventory.md is up to date")
        return 0

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(content, encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(CLAUDE_DIR).as_posix()} "
          f"({_agent_count()} agents, {_skill_count()} skills)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
