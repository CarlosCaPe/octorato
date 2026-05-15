# SkillsMP - Agent Skills Marketplace Integration

Search, discover, and install agent skills from [skillsmp.com](https://skillsmp.com) — the largest collection of open-source SKILL.md files.

## When to Use

Activate this skill when the user:
- Asks to search for skills on a topic (e.g., "find skills for PDF manipulation")
- Wants to install a skill from skillsmp.com
- Needs recommendations for skills to automate a workflow
- Asks about available community skills

## Configuration

API key stored in `~/.skillsmp/config.yaml`:
```yaml
api_key: sk_live_your_api_key  # Get from https://skillsmp.com/auth/login
```

Alternative: environment variable `SKILLSMP_API_KEY`

## API Reference

### Search Skills (keyword)
```bash
curl -X GET "https://skillsmp.com/api/v1/skills/search?q=QUERY&limit=20&sortBy=stars" \
  -H "Authorization: Bearer $SKILLSMP_API_KEY"
```

### AI Semantic Search
```bash
curl -X GET "https://skillsmp.com/api/v1/skills/ai-search?q=QUERY" \
  -H "Authorization: Bearer $SKILLSMP_API_KEY"
```

### Rate Limits
- 500 requests/day per API key (resets midnight UTC)
- Headers: `X-RateLimit-Daily-Limit`, `X-RateLimit-Daily-Remaining`

## Workflow: Search and Install a Skill

### Step 1: Search
Use the CLI tool or curl to search:
```bash
skillsmp search "code review"
# or with AI semantics:
skillsmp ai-search "how to automate PR reviews"
```

### Step 2: Review Results
Results show:
- Skill name and description
- GitHub repo URL
- Star count and last updated date
- Installation path

### Step 3: Install
Skills are cloned from GitHub to the appropriate location:
```bash
skillsmp install <skill-id> --global    # ~/.claude/skills/
skillsmp install <skill-id> --project   # .claude/skills/
```

## Installation Locations

| Scope | Path | Use Case |
|-------|------|----------|
| Global (personal) | `~/.claude/skills/<name>/` | Available in ALL projects |
| Project | `.claude/skills/<name>/` | Project-specific skills |
| Codex CLI | `~/.codex/skills/<name>/` | OpenAI Codex integration |

## CLI Tool Location

The `skillsmp` CLI is available at:
```
~/Documents/github/path/to/portfolio/tools/skillsmp/cli.py
```

Run with:
```bash
python ~/Documents/github/path/to/portfolio/tools/skillsmp/cli.py search "query"
```

Or add alias to shell:
```bash
alias skillsmp='python ~/Documents/github/path/to/portfolio/tools/skillsmp/cli.py'
```

## Example Queries

| User Request | API Call |
|--------------|----------|
| "Find PDF skills" | `/search?q=pdf` |
| "Skills for web scraping" | `/ai-search?q=web+scraping+automation` |
| "Git automation skills" | `/search?q=git&sortBy=stars` |
| "Code review best practices" | `/ai-search?q=code+review+best+practices` |

## Error Handling

| Code | Meaning | Action |
|------|---------|--------|
| `MISSING_API_KEY` | No API key | Add to config or env var |
| `INVALID_API_KEY` | Wrong key | Regenerate at skillsmp.com |
| `DAILY_QUOTA_EXCEEDED` | 500 req limit hit | Wait until midnight UTC |

## Best Practices

1. **Search first** — Use AI search for vague queries, keyword search for specific terms
2. **Review before install** — Check GitHub repo, read the SKILL.md content
3. **Global vs Project** — Use global for general-purpose skills, project for domain-specific
4. **Version control** — Commit project-level skills to your repo

## Related Resources

- [SkillsMP Docs](https://skillsmp.com/docs)
- [Official Anthropic Skills](https://github.com/anthropics/skills)
- [Agent Skills Spec](https://agentskills.io/)
