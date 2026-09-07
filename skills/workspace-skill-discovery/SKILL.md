---
name: workspace-skill-discovery
description: Discover and include ALL skills across the workspace — not just global ones. Use at the start of every session or when the user asks about available skills. Ensures project-level skills (under .claude/skills/ or skills/ in any repo) are never missed.
metadata:
  short-description: Find all skills across workspace
---

# Workspace Skill Discovery

## Purpose

The global skills in `~/.claude/skills/` are auto-registered in the system prompt, but **project-level skills** stored inside workspace repos are NOT. This skill ensures you always discover and acknowledge ALL skills.

## When to Trigger

- **Always** when the user asks "what skills are available?" or similar
- **At session start** if the user asks about capabilities
- **Before any task** that might benefit from project-specific knowledge

## Discovery Procedure

1. **Search the entire workspace** for skills directories:
   ```bash
   find <workspace_folders> -type d -name "skills" 2>/dev/null
   ```

2. **List skill files** in each discovered directory:
   ```bash
   find <skills_dir> -type f \( -name "SKILL.md" -o -name "*.md" \) | head -50
   ```

3. **Report ALL skills** organized by location:
   - Global (`~/.claude/skills/`) — curated/installed skills
   - Project-level (`.claude/skills/` inside repos) — custom workflow skills
   - Repo-level (`skills/` folders) — domain-specific knowledge

4. **Read project-level SKILL.md files** when they are relevant to the current task — they contain domain-specific workflows the global skills don't cover.

## Installed packages (vendor) are a third source

A signed package installed with `octo pkg` lives in `skills/vendor/<name>` and is
reachable at `skills/<name>` through a symlink. Both are gitignored, so a `git ls-files`
or a diff of the brain will not show them, and the tracked connectome deliberately does
not index them either (a package name can be private). They still run on every prompt.
List them at session start:

```bash
python3 ~/.claude/scripts/octo_pkg.py list
```

Report them as their own group, with their version and signer, next to the global and
project-level skills. A package whose row reads WARN is in the lock but not on disk
(`octo pkg sync` restores it); one that reads FAIL has drifted from its signature and
should not be trusted until it is reinstalled.

## Known Skill Locations (Update as needed)

| Location | Type | Example Topics |
|----------|------|----------------|
| `~/.claude/skills/` | Global (36+) | Deploys, security, docs, media, etc. |
| `~/.claude/skills/vendor/` | Installed packages | Signed, locked in `packages.lock.json`; list with `octo pkg list` |
| `portfolio_repo/projects/portfolio_site/.claude/skills/` | Project | CV update, CV sync audit, security audit, deploy |
| `client-a/skills/` | Project | 45 PostgreSQL/DB engineering patterns |

## Key Rule

**Never list only global skills.** Always run the filesystem search to find project-level skills too. Project skills often contain the most valuable, context-specific workflows.
