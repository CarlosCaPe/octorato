---
name: repo-deep-learn
description: Manual deep-analysis of a single GitHub repository (URL or local path). Clones if needed, inventories the codebase, extracts the concepts/patterns that could land as a new brain skill or improve an existing one, writes a structured report to ~/.claude/knowledge/repo-deep-learn/<repo>/<YYYY-MM-DD>.md, scans open octorato issues for resolution candidates, stars the source repo as thanks, and surfaces concrete brain-improvement proposals (new skill / update existing / new agent / pattern-reference / SKIP). Manual counterpart to the autonomous github-trending-curation routine — use when the operator hands you a specific repo and asks "what can we learn from this?".
metadata:
  type: brain-routine
  trigger: manual (operator-initiated)
  args:
    - url-or-path: required — github.com URL OR absolute local path to an already-cloned repo
---

# Repo Deep-Learn (Manual Counterpart of Trending Curation)

## When to invoke

Operator hands you a single repo and asks any of:
- *"clónalo, analízalo, dime qué le sacamos a octo"*
- *"aprende de este repo"*
- *"qué podemos mejorar con esto"*
- *"deep-dive on github.com/owner/repo"*

This is the **manual + high-research** sibling of [[github-trending-curation]]. Trending = autonomous breadth (pulls many, filters cheap). Repo-deep-learn = single-target depth (one repo, no filter, full investigation, concrete proposals).

## Inputs

| Form | Example | Behavior |
|---|---|---|
| GitHub URL | `https://github.com/nidhinjs/prompt-master` | Clone into the knowledge dir if not present |
| Local path | `/home/carloscarrillo/Documents/github/some-repo` | Use directly, no clone |
| Owner/repo shorthand | `nidhinjs/prompt-master` | Treat as github.com/<that> |

Cache location: `~/.claude/knowledge/repo-deep-learn/<repo-name>/` (the clone) and `~/.claude/knowledge/repo-deep-learn/<repo-name>/<YYYY-MM-DD>.md` (the report).

## Workflow (8 phases)

### 1. Clone or locate

```bash
REPO_URL="$1"  # or path
REPO_NAME="$(basename "$REPO_URL" .git)"
KNOWLEDGE_DIR="$HOME/.claude/knowledge/repo-deep-learn/$REPO_NAME"

if [[ "$REPO_URL" =~ ^https?:// || "$REPO_URL" =~ / ]]; then
  if [ ! -d "$KNOWLEDGE_DIR" ]; then
    git clone --depth 50 "$REPO_URL" "$KNOWLEDGE_DIR"
  else
    git -C "$KNOWLEDGE_DIR" pull --ff-only
  fi
else
  KNOWLEDGE_DIR="$REPO_URL"  # operator gave a local path
fi
```

Always `--depth 50` to keep the clone light; we want code + recent history, not full archaeology.

### 2. Inventory

Compute at minimum:
- `wc -l` total lines, primary language (gh CLI: `gh api repos/<owner>/<name> --jq '.language'`)
- Top-level files: README, LICENSE, package manifests, CI config
- Directory shape: `find . -maxdepth 2 -type d | head -30`
- Dependency count: parse `package.json` / `requirements.txt` / `Cargo.toml` / etc.
- Stars / forks / open issues (gh api)
- Last commit date (`git log -1 --format=%ai`)
- License (gh api `.license.spdx_id`)

### 3. Read the README + docs

Full read of `README.md` + every `.md` under `docs/`. Extract:
- **What problem does it solve?** (1-sentence)
- **Hero example** (the README's main "look how easy" code snippet)
- **Architecture claims** (any "we built X because Y" rationale)
- **Comparable tools they cite** (other projects they position against)

### 4. Code-pattern extraction

Use `Read` / `Grep` to identify:
- **Entry points** (main / index / cli / bin)
- **Public API surface** (exported symbols, route handlers, CLI commands)
- **Notable techniques** — examples to look for:
  - Custom AST / parser?
  - LLM prompt patterns (system prompts, few-shot, output formats)
  - Caching strategy
  - Plugin system / hooks architecture
  - Config-driven behavior (YAML/JSON schemas)
  - Test patterns (golden files, property-based, snapshot)
  - Build / deploy automation
- **Anti-patterns to flag** (DON'T copy these)

### 5. Brain delta analysis

```bash
python3 ~/.claude/scripts/query_connectome.py query "<topic from step 3>"
```

For each notable pattern from step 4, query the connectome. Three outcomes per pattern:

| Outcome | What it means | Action |
|---|---|---|
| **MATCH ≥ 0.5** | Brain already has equivalent skill | Note as "covered by [[skill-name]]" |
| **PARTIAL 0.2-0.5** | Adjacent skill exists but doesn't fully cover | Propose UPDATE to that skill |
| **NO MATCH < 0.2** | Genuinely new for the brain | Propose NEW skill |

### 6. Improvement proposals

For each pattern, pick exactly one verdict:

- **NEW SKILL** — create `skills/<kebab-name>/SKILL.md`. Include the operator-rule: "auto-promoted YYYY-MM-DD from repo-deep-learn (<repo-url>)".
- **UPDATE SKILL** — patch existing skill with new technique; cross-link to source.
- **NEW AGENT** — only if the repo defines a whole persona/role missing from `agents/REGISTRY.md` (rare).
- **REFERENCE-ONLY** — add a `See also: <url>` line to an existing skill. Use when the repo is interesting but small / not skill-worthy on its own.
- **SKIP** — covered, lower quality, or out of scope. Document the *why* in the report so we don't re-evaluate later.

### 7. Issue-resolution scan (canonical operator rule)

Before writing PRs, scan open octorato issues for resolution candidates. **Strict 3-rule filter:**

```bash
gh issue list --repo CarlosCaPe/octorato --state open \
  --json number,title,assignees,body,labels \
  --jq '.[] | select(
    # rule A: open
    # rule B: unassigned OR assigned to operator
    (.assignees == [] or any(.assignees[]; .login == "CarlosCaPe"))
  )'
```

For each open issue:
- **Does the new knowledge from this repo resolve it?** (semantic match — read the issue body, compare to extracted patterns)
- **Is there a third-party PR already linked?** Check `gh issue view <num> --json projectItems` and look at linked PRs. If yes → **DO NOT CLOSE**. Let the contributor close their own proposal (operator rule 2026-05-28).
- **If resolved AND no third-party PR:** propose close via `gh issue close <num> --comment "Resolved by deep-learn of <repo-url> — see knowledge/repo-deep-learn/<repo>/<date>.md"`.

**Dry-run first.** The skill must print "Would close: #N — title — reason" for review BEFORE invoking `gh issue close`. Operator confirms with "ciérralos" / "sí" / "ok".

### 8. Star the repo (thanks layer)

```bash
gh api -X PUT "user/starred/<owner>/<repo>"
```

Check existing star status first (`gh api user/starred/<owner>/<repo>` → 204 = starred, 404 = not). Don't re-star. This is a courtesy emission — when the brain learns from a public repo, the operator's account stars it back as attribution.

## Output: the report file

Path: `~/.claude/knowledge/repo-deep-learn/<repo-name>/<YYYY-MM-DD>.md`

Template:

```markdown
# Deep-learn: <owner>/<repo> — <YYYY-MM-DD>

> Source: <repo-url>
> Stars: <N> · Forks: <N> · Language: <L> · License: <spdx>
> Last commit: <date> · Issues: <N> open

## 1. Problem solved
<1-sentence>

## 2. Hero example
\`\`\`<lang>
<README main snippet>
\`\`\`

## 3. Notable patterns extracted
| # | Pattern | Brain coverage | Verdict |
|---|---|---|---|
| 1 | … | NO MATCH | NEW SKILL `<name>` |
| 2 | … | PARTIAL ([[skill-x]] 0.34) | UPDATE [[skill-x]] |

## 4. Proposed brain changes
- **NEW**: `skills/<name>/SKILL.md` — draft attached below
- **UPDATE**: `skills/<existing>/SKILL.md` — add section "X"
- **SKIP**: <pattern> — already covered by [[skill-y]]

## 5. Issue-resolution candidates (dry-run)
| Issue | Title | Resolved by | Third-party PR? | Proposal |
|---|---|---|---|---|
| #N | … | this learn | No | CLOSE with comment |
| #M | … | partial | Yes (#PR-X by @user) | LEAVE OPEN |

## 6. Star status
[x] Starred github.com/<owner>/<repo> as thanks

## 7. Anti-patterns observed (don't copy)
- …
```

Save the report **regardless of verdict** — even a SKIP-only result is valuable for "we already looked at this, don't re-evaluate".

## Output: optional brain PR(s)

If verdict includes NEW or UPDATE: open ONE PR per skill, via `ai-push` flow (handles master protection automatically). PR title pattern:
- `feat(skill): add <name> — learned from <owner>/<repo>`
- `feat(skill): extend <name> with <technique> — learned from <owner>/<repo>`

PR body must include the deep-learn report path + the source repo URL.

## Why this is the manual counterpart of trending-curation

| Dimension | github-trending-curation | repo-deep-learn |
|---|---|---|
| Trigger | Daily 07:30 UTC cron | Operator says "analyze this" |
| Breadth | 100 repos/day | 1 repo |
| Depth per repo | ~30s heuristic + LLM gate | minutes of code reading + connectome query |
| Output | Daily digest markdown + Notion | Per-repo report + optional brain PR |
| Auto-promote? | No (manual `/trending-promote`) | Optional — surface to operator |
| Issue scan? | No | YES (canonical rule) |
| Star repo? | No | YES (thanks) |

## See also
- [[github-trending-curation]] — autonomous breadth sibling
- [[trending-promote]] — manual promote command (similar PR pattern)
- [[skill-creator]] — skill scaffold conventions
- [[do-not-ask-to-pause]] — keep going through all 8 phases without mid-flow "should I continue?" prompts
