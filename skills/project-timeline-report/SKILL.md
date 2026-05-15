---
name: project-timeline-report
description: Generate a "Journey Into [Project]" narrative report analyzing a project's entire development history from git log, CHANGELOG, and release notes. Use when user asks for a timeline report, project history analysis, development journey, full project report, or "what's the story of this project?". No external dependencies.
---

# Project Timeline Report

Generate comprehensive narrative analysis of a project's development history using git log, CHANGELOG, release notes, and workspace artifacts as the timeline source.

## When to Use

- "Write a timeline report"
- "Journey into [project]"
- "Analyze my project history"
- "Summarize the entire development history"
- "What's the story of this project?"
- Sprint retrospectives, client handoffs, portfolio updates

## Prerequisites

- Git repository with commit history
- Optional: CHANGELOG.md, RELEASE_NOTES*.md, tags

## Workflow

### Step 1: Determine Project Scope

Identify the project root and name:

```bash
PROJECT_ROOT="$(git rev-parse --show-toplevel)"
PROJECT_NAME="$(basename "$PROJECT_ROOT")"

# If monorepo, user may specify a subpath
# e.g., projects/website within portfolio_repo
```

### Step 2: Gather Timeline Data (parallel)

Run all data-gathering commands in one batch:

```bash
# --- Quantitative overview ---
echo "=== STATS ==="
git log --oneline | wc -l                              # Total commits
git log --format="%ai" | head -1                        # Latest
git log --format="%ai" | tail -1                        # Earliest
git shortlog -sn --no-merges | head -10                 # Contributors
git tag -l --sort=-v:refname | head -10                 # Tags/releases

# --- Monthly activity ---
echo "=== MONTHLY ==="
git log --format="%Y-%m" | sort | uniq -c | sort -rn

# --- Top changed files ---
echo "=== HOTSPOTS ==="
git log --pretty=format: --name-only | sort | uniq -c | sort -rn | head -20

# --- Commit type distribution (if conventional commits) ---
echo "=== TYPES ==="
git log --oneline | grep -oP "^[a-f0-9]+ \K(feat|fix|refactor|docs|chore|style|test|perf|ci|build)" | sort | uniq -c | sort -rn

# --- Key milestones ---
echo "=== MILESTONES ==="
ls CHANGELOG.md RELEASE_NOTES*.md 2>/dev/null
git tag -l -n1 | head -20
```

### Step 3: Estimate Scope and Token Budget

| Project Size | Commits | Timeline Tokens | Approach |
|---|---|---|---|
| Small | < 100 | ~5K | Full git log, direct analysis |
| Medium | 100-1,000 | ~15K | Monthly summaries + key commits |
| Large | 1,000-10,000 | ~50K | Phase-based with subagent |
| Huge | 10,000+ | ~100K+ | Sampled analysis (milestones + tags only) |

Report to user: "Project has N commits spanning DATE1 to DATE2. Estimated ~Xk tokens for analysis. Proceed?"

### Step 4: Build Timeline Phases

Group history into natural phases by detecting:

```bash
# Phase boundaries (pick the most relevant)
git tag -l --sort=v:refname                            # Tags = releases
git log --oneline --grep="initial\|v0\|v1\|launch\|deploy\|migrate" -20  # Milestone commits
git log --oneline --diff-filter=A -- "*.md" | head -10  # Doc creation points
```

For each phase, extract:
```bash
# Phase N: TAG_START..TAG_END (or date range)
git log --oneline TAG_START..TAG_END --stat | head -40
git log --oneline TAG_START..TAG_END --grep="fix" | wc -l      # Bug fixes
git log --oneline TAG_START..TAG_END --grep="feat" | wc -l     # Features
```

### Step 5: Deploy Analysis Subagent

For medium+ projects, use a subagent with the gathered data:

```
Deploy subagent with:
- Timeline statistics from Step 2
- Phase breakdown from Step 4
- CHANGELOG.md content (if exists)
- RELEASE_NOTES*.md content (if exists)
- Analysis prompt (see below)
```

### Step 6: Save Report

Default output: `./journey-into-PROJECT_NAME.md`

Report completion:
- Where saved
- Date range covered
- Commits analyzed
- Phases identified

## Analysis Prompt Template

The subagent should produce these sections:

1. **Project Genesis** - First commits, initial vision, founding decisions
2. **Architectural Evolution** - Major structural changes, pivots, why
3. **Key Breakthroughs** - "Aha" moments visible in commit patterns
4. **Work Patterns** - Debug cycles, feature sprints, refactoring phases
5. **Technical Debt** - Shortcuts taken and when repaid
6. **Challenges** - Hardest problems (multi-commit debugging, dead ends)
7. **Timeline Statistics** - Date range, total commits, types, hottest files, most active periods
8. **Lessons and Meta-Observations** - Recurring themes, principles

**Writing style:**
- Technical narrative, not bullet lists
- Reference specific commits (SHA short + message) when citing events
- Connect events across time - show cause and effect
- Be honest about struggles, not just successes
- 2,000-5,000 words depending on project size

## 4D Integration

| Phase | Role |
|---|---|
| 1D Describe | State project name, expected scope, output location |
| 2D Delegate | Subagent for large projects (1000+ commits) |
| 3D Diligent | Verify report covers full date range, no phantom data |
| 4D Disclose | Report token cost, commit count, phases identified |

## Anti-Patterns

- Reading every commit message into a single prompt (token explosion)
- Fabricating milestones not present in git history
- Ignoring CHANGELOG/RELEASE_NOTES when they exist
- Generating reports without citing specific commits
- Analyzing monorepo root when user asked about specific subproject

## Lessons Learned

<!-- Append new patterns as they emerge -->

---
*Adapted from claude-mem timeline-report skill. Uses git log + docs as timeline instead of SQLite/Chroma/worker API.*
