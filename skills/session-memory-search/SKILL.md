---
name: session-memory-search
description: Search past work across sessions using native tools (git log, grep, Lessons Learned). Use when user asks "did we already solve this?", "how did we do X last time?", "what happened last week?", or needs to recall work from previous sessions. No external dependencies required.
---

# Session Memory Search

Search past work across sessions using git history, workspace grep, and brain skills as persistent memory. No external worker or database required.

## When to Use

- "Did we already fix this?"
- "How did we solve X last time?"
- "What happened last week?"
- "Have we seen this error before?"
- Any question about PREVIOUS sessions (not current conversation)

## 3-Layer Workflow (Index -> Filter -> Fetch)

**NEVER read full git history or all skills. Filter first. 10x token savings.**

### Layer 1: Search Index (cheap - ~50 tokens/result)

Pick the best index for the question:

| Question Type | Command | Returns |
|---|---|---|
| Past code changes | `git log --all --oneline --grep="keyword" -20` | Commit SHAs + messages |
| Code that contained X | `git log --all --oneline -S "keyword" -20` | Commits where string was added/removed |
| Past file modifications | `git log --oneline --follow -- path/to/file -20` | File history |
| Error patterns | `grep -rn "keyword" ~/.claude/skills/*/SKILL.md \| grep -i "lesson"` | Lessons Learned sections |
| Past decisions | `git log --all --oneline --grep="decision\|chose\|decided" -20` | Decision commits |
| Date range | `git log --oneline --since="2025-01-01" --until="2025-02-01" -20` | Period activity |
| Brain knowledge | `grep -rn "keyword" ~/.claude/skills/*/SKILL.md` | Matching skills |

### Layer 2: Filter (visual scan - 0 tokens)

Review the index results. Identify the 2-5 most relevant entries by:
- Commit message relevance to the question
- Date proximity (recent = more likely relevant)
- File paths matching the topic
- Skill names matching the domain

**Discard everything else. Never fetch all results.**

### Layer 3: Fetch Details (expensive - ~500+ tokens each)

Only for the filtered entries:

| Source | Fetch Command | Returns |
|---|---|---|
| Git commit | `git show SHA --stat` | Full diff + stats |
| Git commit (code only) | `git show SHA -- path/to/file` | Specific file changes |
| Skill lesson | `read_file` on the SKILL.md | Full context |
| File at point in time | `git show SHA:path/to/file` | File snapshot |
| Neural map connections | `python3 -c "import json; m=json.load(open('~/.claude/neural_map.json')); ..."` | Related skills/agents |

## Memory Sources (ranked by reliability)

1. **Git log** - Immutable, timestamped, complete history of all code changes
2. **Lessons Learned** - Curated patterns in `~/.claude/skills/*/SKILL.md` ## Lessons Learned sections
3. **CHANGELOG / RELEASE_NOTES** - Documented milestones and decisions
4. **Neural map** - Weighted connections between skills and agents
5. **Conversation context** - Current session (handled by LLM natively)

## Examples

**Find how we fixed a specific bug:**
```bash
# Layer 1: Search
git log --all --oneline --grep="fix.*auth" -10

# Layer 2: Filter (visual) -> pick SHA abc1234

# Layer 3: Fetch
git show abc1234 --stat
git show abc1234 -- src/auth/handler.ts
```

**Check if this error pattern was seen before:**
```bash
# Layer 1: Search Lessons Learned
grep -rn "ConnectionTimeout\|ETIMEDOUT" ~/.claude/skills/*/SKILL.md

# Layer 2: Filter -> relevant skill found

# Layer 3: Read the lesson
# -> read_file on the matched SKILL.md
```

**Find what we did last week on this project:**
```bash
# Layer 1: Date-scoped search
git log --oneline --since="7 days ago" --stat -20

# Layer 2: Filter -> interesting commits

# Layer 3: Deep dive
git show SHA
```

**Search across all arms for a pattern:**
```bash
# Layer 1: Multi-repo search
for repo in ~/Documents/github/*/; do
  echo "=== $(basename $repo) ==="
  git -C "$repo" log --oneline --grep="keyword" -5 2>/dev/null
done
```

## 4D Integration

| Phase | Role |
|---|---|
| 1D Describe | State the recall question clearly before searching |
| 2D Delegate | mem-search IS the delegate - search before re-inventing |
| 3D Diligent | Verify recalled solution still applies to current context |
| 4D Disclose | Cite the source: commit SHA, skill name, date |

## Anti-Patterns

- Reading entire git log without `--grep` or `-S` filter
- Reading all SKILL.md files to find one lesson
- Re-solving a problem without checking if it was solved before
- Trusting recalled code without verifying it still compiles/works

## Lessons Learned

<!-- Append new patterns as they emerge -->

---
*Adapted from claude-mem mem-search skill. Uses git + grep as persistent memory instead of SQLite/worker.*
