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

## Known Skill Locations (Update as needed)

| Location | Type | Example Topics |
|----------|------|----------------|
| `~/.claude/skills/` | Global (36+) | Deploys, security, docs, media, etc. |
| `portfolio_repo/projects/portfolio_site/.claude/skills/` | Project | CV update, CV sync audit, security audit, deploy |
| `client-a/skills/` | Project | 45 PostgreSQL/DB engineering patterns |

## Key Rule

**Never list only global skills.** Always run the filesystem search to find project-level skills too. Project skills often contain the most valuable, context-specific workflows.
