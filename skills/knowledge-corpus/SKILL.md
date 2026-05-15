---
name: knowledge-corpus
description: Build and query focused knowledge corpora from brain skills, git history, and workspace files. Use when users want to compile expertise on a specific topic, ask "what do we know about X?", build a domain briefing, or synthesize knowledge from multiple sources into an actionable summary. No external dependencies.
---

# Knowledge Corpus

Build and query focused knowledge corpora from the Octopus brain without external infrastructure. Skills, agents, git history, and workspace files ARE the corpus.

## When to Use

- "What do we know about X?"
- "Build me a briefing on topic Y"
- "Compile everything about Z"
- "What skills/patterns do we have for this domain?"
- Before starting work in an unfamiliar domain
- When onboarding to a new client/project

## Concept: Skills as Pre-Built Corpora

Each `~/.claude/skills/<name>/SKILL.md` is already a focused corpus:
- **Purpose** - what it solves
- **Triggers** - when it activates
- **Workflow** - step-by-step procedures
- **Lessons Learned** - error patterns and fixes from real usage

The neural map (`~/.claude/neural_map.json`) provides:
- **Skill clusters** - related skills that co-occur (793 edges)
- **Agent-skill connections** - which agents use which skills (1,744 edges)
- **TF-IDF vocabulary** - 17,378 terms for similarity matching

## 3-Step Workflow

### Step 1: Discover Sources (cheap)

Identify what the brain knows about the topic:

```bash
# Find skills by keyword
grep -rl "keyword" ~/.claude/skills/*/SKILL.md | head -20

# Find skills by neural map cluster
python3 -c "
import json
m = json.load(open('$HOME/.claude/neural_map.json'))
# Find skills connected to a known skill
for edge in m.get('skill_skill_edges', []):
    if 'target-skill' in [edge.get('source'), edge.get('target')]:
        print(f\"{edge.get('source')} <-> {edge.get('target')} ({edge.get('weight', 0):.2f})\")
" 2>/dev/null | head -10

# Find agents with domain expertise
grep -n "keyword" ~/.claude/agents/REGISTRY.md | head -10

# Find in external refs
grep -rl "keyword" ~/.claude/*-ref/ 2>/dev/null | head -10
```

### Step 2: Build Corpus (targeted reads)

Read ONLY the relevant sources found in Step 1:

```
For each matching skill:
  -> read_file SKILL.md (focus on Workflow + Lessons Learned)

For each matching agent:
  -> read agent file (focus on triggers + cross-referenced skills)

For git history (if needed):
  -> git log --all --oneline --grep="keyword" -10
  -> git show SHA for the most relevant commits
```

**Token budget per corpus:** aim for 2,000-5,000 tokens total. If corpus exceeds 5,000 tokens, summarize each source into 1-3 key findings.

### Step 3: Synthesize Answer

Combine corpus sources into a structured response:

```markdown
## Knowledge Corpus: [Topic]

### What We Know
- [Key findings from skills]
- [Patterns from Lessons Learned]
- [Decisions from git history]

### Available Tools
- Skills: [list of relevant skills]
- Agents: [list of matching agents]
- External refs: [patterns from *-ref/ repos]

### Gaps
- [What we DON'T know about this topic]
- [Suggested: create skill for X]

### Sources
- skill: [name] (section)
- agent: [name]
- commit: [SHA] ([date])
```

## Corpus Types

| Type | Sources | Use Case |
|---|---|---|
| **Domain** | Skills + agents by keyword | "What do we know about PostgreSQL?" |
| **Project** | Git log + workspace files | "Summarize this project's patterns" |
| **Decision** | Git log --grep + CHANGELOG | "What architectural decisions were made?" |
| **Error** | Lessons Learned sections | "What errors have we seen with X?" |
| **Identity** | professional-identity + cv.ts | "What's my experience with X?" |

## 4D Integration

| Phase | Role |
|---|---|
| 1D Describe | State the knowledge question before building corpus |
| 2D Delegate | knowledge-corpus IS the delegate check for domain knowledge |
| 3D Diligent | Verify corpus is complete (check skill count, git range, gaps) |
| 4D Disclose | Cite every source (skill name, commit SHA, file path) |

## Anti-Patterns

- Reading ALL skills to answer one question (use grep first)
- Building a corpus without checking the neural map for clusters
- Returning raw skill text instead of synthesized findings
- Ignoring Lessons Learned sections (highest-value content)
- Creating a new skill for something already covered by existing corpus

## Lessons Learned

<!-- Append new patterns as they emerge -->

---
*Adapted from claude-mem knowledge-agent skill. Uses brain skills + neural map as corpus instead of SQLite/Chroma/worker.*
