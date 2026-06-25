#!/usr/bin/env python3
"""
capability_manifest.py -- v5.0 Capability Manifest Generator for Octorato.

Scans skills/, agents/, scripts/, registry/rules.yaml, and hooks.json then
writes docs/CAPABILITIES.md -- the canonical, accumulative offering document.

Usage:
    python3 scripts/capability_manifest.py           # write docs/CAPABILITIES.md
    python3 scripts/capability_manifest.py --check   # exit non-zero if doc is stale
"""

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BRAIN = Path(__file__).resolve().parent.parent  # ~/.claude/


def _yaml_frontmatter(text: str) -> dict:
    """Parse YAML frontmatter delimited by '---' lines. Stdlib-only, no PyYAML."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    end = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end = i
            break
    if end is None:
        return {}
    fm: dict = {}
    for line in lines[1:end]:
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip().lstrip("-").strip()
            val = val.strip().strip('"').strip("'")
            # multi-line YAML values (">", "|") -- just grab the first non-empty word
            if val in (">", "|", ">-", "|-"):
                val = ""
            if key and not key.startswith("#"):
                fm[key] = val
    return fm


def _first_heading(text: str) -> str:
    for line in text.splitlines():
        m = re.match(r"^#+\s+(.+)", line)
        if m:
            return m.group(1).strip()
    return ""


def _trunc(s: str, n: int = 120) -> str:
    s = s.strip()
    return s[:n] + "..." if len(s) > n else s


# ---------------------------------------------------------------------------
# 1. Scan Skills
# ---------------------------------------------------------------------------

def scan_skills() -> list[dict]:
    skills_dir = BRAIN / "skills"
    results = []
    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue
        text = skill_file.read_text(encoding="utf-8", errors="replace")
        fm = _yaml_frontmatter(text)
        name = fm.get("name") or skill_dir.name
        desc = fm.get("description") or ""
        if not desc:
            # try metadata.short-description
            desc = fm.get("short-description") or ""
        if not desc:
            desc = _first_heading(text)
        results.append({
            "name": name,
            "description": desc,
            "path": str(skill_file.relative_to(BRAIN)),
        })
    return results


# ---------------------------------------------------------------------------
# 2. Scan Agents
# ---------------------------------------------------------------------------

def scan_agents() -> list[dict]:
    agents_dir = BRAIN / "agents"
    results = []
    for division_dir in sorted(agents_dir.iterdir()):
        if not division_dir.is_dir():
            continue
        division = division_dir.name
        for agent_file in sorted(division_dir.glob("*.md")):
            if agent_file.name == "REGISTRY.md":
                continue
            text = agent_file.read_text(encoding="utf-8", errors="replace")
            fm = _yaml_frontmatter(text)
            name = fm.get("name") or agent_file.stem
            desc = fm.get("description") or fm.get("vibe") or _first_heading(text)
            results.append({
                "name": name,
                "division": division,
                "description": desc,
                "path": str(agent_file.relative_to(BRAIN)),
            })
    return results


# ---------------------------------------------------------------------------
# 3. Scan Scripts
# ---------------------------------------------------------------------------

def _script_purpose(path: Path) -> str:
    """Return first non-shebang comment line or module docstring (one line)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    lines = text.splitlines()
    # module docstring: first non-empty, non-shebang, non-comment line that is '"""' or "'''"
    in_docstring = False
    docstring_lines: list[str] = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if i == 0 and stripped.startswith("#!"):
            continue
        if not in_docstring:
            if stripped.startswith('"""') or stripped.startswith("'''"):
                delim = stripped[:3]
                rest = stripped[3:]
                if rest.endswith(delim) and len(rest) > 3:
                    return rest[: -3].strip()
                if rest.strip():
                    return rest.strip()
                in_docstring = True
                continue
            # first comment line
            if stripped.startswith("#"):
                return stripped.lstrip("#").strip()
            if stripped:  # non-empty non-comment line before any docstring = no purpose
                return ""
        else:
            if stripped.endswith('"""') or stripped.endswith("'''"):
                docstring_lines.append(stripped[:-3].strip())
                break
            docstring_lines.append(stripped)
    if docstring_lines:
        return " ".join(l for l in docstring_lines if l)[:120]
    return ""


def scan_scripts() -> list[dict]:
    scripts_dir = BRAIN / "scripts"
    results = []
    skip = {"__pycache__", "lib", "tests"}
    for entry in sorted(scripts_dir.iterdir()):
        if entry.name in skip or entry.name.startswith("."):
            continue
        if entry.is_file():
            purpose = _script_purpose(entry)
            results.append({
                "filename": entry.name,
                "purpose": purpose,
                "path": str(entry.relative_to(BRAIN)),
            })
    return results


# ---------------------------------------------------------------------------
# 4. Scan Rules
# ---------------------------------------------------------------------------

def scan_rules() -> list[dict]:
    rules_file = BRAIN / "registry" / "rules.yaml"
    text = rules_file.read_text(encoding="utf-8", errors="replace")
    rules = []
    # parse manually -- avoid PyYAML dependency
    # each rule starts with "- id:" in the rules list
    current: dict = {}
    in_rules = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "rules:":
            in_rules = True
            continue
        if not in_rules:
            continue
        if stripped.startswith("- id:"):
            if current:
                rules.append(current)
            rule_id = stripped[len("- id:"):].strip().strip('"').strip("'")
            # derive category from id (part before first dot) or wait for explicit field
            cat = rule_id.split(".")[0] if "." in rule_id else "UNCATEGORIZED"
            current = {"id": rule_id, "category": cat}
        elif stripped.startswith("category:") and current:
            current["category"] = stripped[len("category:"):].strip().strip('"').strip("'")
    if current:
        rules.append(current)
    return rules


# ---------------------------------------------------------------------------
# 5 + 6. Scan Hooks + Wiring Status
# ---------------------------------------------------------------------------

def scan_hooks() -> dict[str, list[str]]:
    """Return {event: [script_basename, ...]}."""
    hooks_file = BRAIN / "hooks.json"
    with hooks_file.open(encoding="utf-8") as f:
        data = json.load(f)

    events = ["PostToolUse", "PreToolUse", "SessionStart", "Stop", "UserPromptSubmit"]
    result: dict[str, list[str]] = {}
    for event in events:
        entries = data.get(event, [])
        basenames: list[str] = []
        for entry in entries:
            hook_list = entry.get("hooks", [])
            for hook in hook_list:
                cmd = hook.get("command", "")
                # extract the script basename from the command
                # e.g. "python3 ~/.claude/scripts/trace-hook.py" -> "trace-hook.py"
                parts = cmd.split()
                for part in reversed(parts):
                    if "/" in part or part.endswith(".py") or part.endswith(".sh"):
                        basenames.append(Path(part).name)
                        break
        result[event] = sorted(set(basenames))
    return result


def _build_wiring_index(hooks: dict[str, list[str]]) -> set[str]:
    """Collect all script basenames mentioned in hooks, rules.yaml, CLAUDE.md, README.md,
    and by invocation within other scripts. Returns a set of basenames (with and without .py)."""
    wired: set[str] = set()

    # from hooks
    for basenames in hooks.values():
        for b in basenames:
            wired.add(b)
            wired.add(Path(b).stem)

    # from rules.yaml
    rules_text = (BRAIN / "registry" / "rules.yaml").read_text(encoding="utf-8", errors="replace")
    for m in re.finditer(r"[\w\-]+\.py", rules_text):
        wired.add(m.group())
        wired.add(Path(m.group()).stem)
    for m in re.finditer(r"scripts/([\w\-]+)", rules_text):
        wired.add(m.group(1))

    # from CLAUDE.md
    claude_text = (BRAIN / "CLAUDE.md").read_text(encoding="utf-8", errors="replace")
    for m in re.finditer(r"[\w\-]+\.py", claude_text):
        wired.add(m.group())
        wired.add(Path(m.group()).stem)
    for m in re.finditer(r"scripts/([\w\-]+)", claude_text):
        wired.add(m.group(1))

    # from README.md
    readme = BRAIN / "README.md"
    if readme.exists():
        readme_text = readme.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"[\w\-]+\.py", readme_text):
            wired.add(m.group())
            wired.add(Path(m.group()).stem)
        for m in re.finditer(r"scripts/([\w\-]+)", readme_text):
            wired.add(m.group(1))

    # invocations within scripts/ themselves
    scripts_dir = BRAIN / "scripts"
    skip = {"__pycache__", "lib", "tests"}
    for entry in scripts_dir.iterdir():
        if entry.name in skip or not entry.is_file():
            continue
        try:
            text = entry.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for m in re.finditer(r"[\w\-]+\.py", text):
            wired.add(m.group())
            wired.add(Path(m.group()).stem)
        for m in re.finditer(r"scripts/([\w\-]+)", text):
            wired.add(m.group(1))

    return wired


def annotate_wiring(scripts: list[dict], hooks: dict[str, list[str]]) -> list[dict]:
    wired_set = _build_wiring_index(hooks)
    for s in scripts:
        name = s["filename"]
        stem = Path(name).stem
        s["wired"] = (name in wired_set) or (stem in wired_set)
    return scripts


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def render(
    skills: list[dict],
    agents: list[dict],
    scripts: list[dict],
    rules: list[dict],
    hooks: dict[str, list[str]],
) -> str:
    lines: list[str] = []

    # Header
    lines.append("# Octorato Capabilities")
    lines.append("")
    lines.append("> Generated by scripts/capability_manifest.py. Do not hand-edit.")
    lines.append("")

    # Totals
    divisions = sorted({a["division"] for a in agents})
    wired_scripts = [s for s in scripts if s["wired"]]
    orphan_scripts = [s for s in scripts if not s["wired"]]
    total_hook_entries = sum(len(v) for v in hooks.values())

    lines.append("## Totals")
    lines.append("")
    lines.append("| Metric | Count |")
    lines.append("|---|---|")
    lines.append(f"| Skills | {len(skills)} |")
    lines.append(f"| Agents | {len(agents)} |")
    lines.append(f"| Divisions | {len(divisions)} |")
    lines.append(f"| Scripts: wired | {len(wired_scripts)} |")
    lines.append(f"| Scripts: orphan | {len(orphan_scripts)} |")
    lines.append(f"| Rules | {len(rules)} |")
    lines.append(f"| Hook entries | {total_hook_entries} |")
    lines.append("")

    # Skills
    lines.append(f"## Skills ({len(skills)})")
    lines.append("")
    lines.append("| Name | Description |")
    lines.append("|---|---|")
    for s in skills:
        desc = _trunc(s["description"])
        lines.append(f"| {s['name']} | {desc} |")
    lines.append("")

    # Agents by division
    lines.append(f"## Agents by Division ({len(agents)} across {len(divisions)} divisions)")
    lines.append("")
    for div in divisions:
        div_agents = [a for a in agents if a["division"] == div]
        lines.append(f"### {div} ({len(div_agents)})")
        lines.append("")
        lines.append("| Name | Description |")
        lines.append("|---|---|")
        for a in div_agents:
            desc = _trunc(a["description"])
            lines.append(f"| {a['name']} | {desc} |")
        lines.append("")

    # Scripts
    lines.append(f"## Scripts ({len(scripts)})")
    lines.append("")
    lines.append("| Script | Purpose | Status |")
    lines.append("|---|---|---|")
    for s in scripts:
        purpose = _trunc(s["purpose"], 100)
        status = "wired" if s["wired"] else "orphan"
        lines.append(f"| {s['filename']} | {purpose} | {status} |")
    lines.append("")

    # Rules by category
    from itertools import groupby
    rules_sorted = sorted(rules, key=lambda r: (r["category"], r["id"]))
    lines.append(f"## Rules ({len(rules)})")
    lines.append("")
    for cat, group in groupby(rules_sorted, key=lambda r: r["category"]):
        ids = [r["id"] for r in group]
        lines.append(f"### {cat}")
        lines.append("")
        for rid in ids:
            lines.append(f"- {rid}")
        lines.append("")

    # Hooks
    events = ["PostToolUse", "PreToolUse", "SessionStart", "Stop", "UserPromptSubmit"]
    lines.append("## Hooks")
    lines.append("")
    lines.append("| Event | Wired Scripts |")
    lines.append("|---|---|")
    for event in events:
        scripts_list = hooks.get(event, [])
        cell = ", ".join(scripts_list) if scripts_list else "(none)"
        lines.append(f"| {event} | {cell} |")
    lines.append("")

    content = "\n".join(lines)

    # Hard constraint: no em-dashes in output
    # Replace any that crept in from descriptions with a comma
    content = content.replace("—", ",")

    return content


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Octorato v5.0 Capability Manifest Generator")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if docs/CAPABILITIES.md is stale (does not write)",
    )
    args = parser.parse_args()

    skills = scan_skills()
    agents = scan_agents()
    scripts_raw = scan_scripts()
    rules = scan_rules()
    hooks = scan_hooks()
    scripts = annotate_wiring(scripts_raw, hooks)

    output = render(skills, agents, scripts, rules, hooks)

    out_path = BRAIN / "docs" / "CAPABILITIES.md"

    if args.check:
        if out_path.exists():
            current = out_path.read_text(encoding="utf-8")
            if current == output:
                print("PASS: docs/CAPABILITIES.md is up to date.")
                sys.exit(0)
            else:
                print("FAIL: docs/CAPABILITIES.md is stale. Run: python3 scripts/capability_manifest.py")
                sys.exit(1)
        else:
            print("FAIL: docs/CAPABILITIES.md does not exist.")
            sys.exit(1)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(output, encoding="utf-8")
    print(f"Written: {out_path}")

    # Print summary
    divisions = sorted({a["division"] for a in agents})
    wired = [s for s in scripts if s["wired"]]
    orphans = [s for s in scripts if not s["wired"]]
    total_hooks = sum(len(v) for v in hooks.values())
    print(
        f"Totals: skills={len(skills)} agents={len(agents)} divisions={len(divisions)} "
        f"scripts={len(scripts)} (wired={len(wired)} orphan={len(orphans)}) "
        f"rules={len(rules)} hook-entries={total_hooks}"
    )
    if orphans:
        print("Orphan scripts:", ", ".join(s["filename"] for s in orphans))


if __name__ == "__main__":
    main()
