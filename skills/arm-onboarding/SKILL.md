---
name: arm-onboarding
description: "Step-by-step protocol to create a new client arm: required files, sync-ai-docs, the arm's sealed lineage graph, QueryMaster registration and gitignore hygiene. Triggers on 'crear un arm' or 'onboard a un cliente'."
metadata:
  type: workflow
  short-description: "How to onboard a new client arm: required files, sync-ai-docs, sealed lineage graph, QueryMaster connections, one-file rule"
---

# Arm Onboarding — Creating a New Client Repo

A "new arm" = a new isolated client repository under `~/Documents/github/<CLIENT>/`. Arms inherit all brain rules automatically through `sync-ai-docs`. This skill is the canonical sequence.

## Required Files (per arm)

Every arm MUST have:

| Path | Purpose | Notes |
|---|---|---|
| `.claude/CLAUDE.md` | Single source of truth for the arm — project stack, connections, conventions | Edit this one only; sync propagates the rest |
| `.github/copilot-instructions.md` | Auto-synced copy of `.claude/CLAUDE.md` | NEVER edit directly. `sync-ai-docs` overwrites it |
| `.cursorrules` | Auto-synced copy for Cursor editor | NEVER edit directly. `sync-ai-docs` overwrites it |
| `README.md` | Human-readable repo intro | Project overview + quick-start |
| `.gitignore` | Must include `.env`, `.env.*`, `.dev.vars` | Belt-and-suspenders against secret leaks |
| `.env` | Local secrets, never committed | Gitignored — only on operator's machine |
| `.claude/memory/` | Arm-brain: arm-specific memories, MEMORY.md index, one-fact-per-file | Committed to the arm's own private repo; loaded by the harness via a symlink from `~/.claude/projects/<arm-slug>/memory` |

## Sequence

```bash
# 1. Create the arm directory + initialize git
mkdir <CLIENT> && cd <CLIENT> && git init

# 2. Create the brain-aware structure
mkdir -p .claude .github
touch README.md .gitignore .env

# 3. Write .claude/CLAUDE.md (project stack, conventions, connections)
#    See "Arm CLAUDE.md template" below for what to put inside

# 4. Sync — propagates .claude/CLAUDE.md → .github/copilot-instructions.md + .cursorrules
~/.local/bin/sync-ai-docs <ARM_CODE>   # or sync-ai-docs (no arg = all arms)

# 5. Wire the arm-brain (two-tier memory model)
mkdir -p .claude/memory
# Create MEMORY.md index inside the arm (committed to the arm's private repo)
# Then link it into the brain's harness so it loads automatically:
ln -sfn "$(pwd)/.claude/memory" ~/.claude/projects/<arm-slug>/memory
# Arm-specific facts stay here. A lesson useful to OTHER arms distils UP to the
# central brain (generic, anonymized) — see docs/architecture/memory-model.md
# and the feedback_brain_is_independent lesson in the brain memory.

# 6. Seed the arm's lineage graph (sealed, arm-scoped seek > scan)
mkdir -p .claude/connectome
cp ~/.claude/templates/arm/connectome/lineage.yaml .claude/connectome/lineage.yaml
# impact-radius.py auto-detects this file when run from inside the arm and
# traverses the ARM's graph (receipts say layer=arm). Declare the arm's own
# sync surfaces here (deploy planes, generated artifacts, duplicated facts).
# Never reference another arm; never sync this upward.

# 7. (Optional) Register database connections in QueryMaster
# Edit ~/.config/querymaster/connections.json — add the arm's DB connections
# Connections live OUTSIDE the arm repo (operator-side, not committed)

# 8. First commit
git add . && git commit -m "chore: bootstrap arm with brain-aligned structure"
```

## Arm `.claude/CLAUDE.md` template

The arm's CLAUDE.md should declare:

```markdown
# <CLIENT> — AI Agent Instructions

> Universal constraints (4D paradigm, security, brain rules) are in `~/.claude/CLAUDE.md`.
> This file covers <CLIENT>-specific context only.
> **Single source of truth.** `.github/copilot-instructions.md` is auto-synced from this file.
> Run `sync-ai-docs <CLIENT>` to propagate changes.

## Project Overview
<1-2 sentence summary>

## Stack
- Backend: <e.g., Node + Fastify on Cloudflare Workers>
- DB: <e.g., D1 + KV>
- Frontend: <e.g., Astro + Svelte>
- Deploy: <e.g., `npx wrangler pages deploy dist`>

## QueryMaster Connections
| Conn name | Engine | Purpose |
|---|---|---|
| <conn_id> | postgresql | <production main DB> |

## Conventions
- <project-specific naming, file organization, build commands>

## Security Rules (Mandatory)
<arm-specific security notes — most arms inherit only the universal brain rules>
```

## The One-File Rule

**Edit ONLY `.claude/CLAUDE.md`.** Never hand-edit `.github/copilot-instructions.md` or `.cursorrules` — `sync-ai-docs` overwrites them on the next sync. After every change to `.claude/CLAUDE.md`, run:

```bash
~/.local/bin/sync-ai-docs <ARM_CODE>
```

## All Brain Rules Apply Automatically

Once the arm is registered + synced, it inherits:

- The 4D Paradigm (Describe → Delegate → Diligent → Disclose)
- Arm isolation (the new arm CANNOT see other arms' data)
- Security rules (no secret commits, sanitize inputs, `.env` gitignored)
- Git discipline (atomic commits `type(scope): description`, no force-push to main, no `v1`/`_final` suffixes)
- File organization (config-first, no unrequested changelog files)
- All universal-reflex skills (workspace-skill-discovery, session-memory-search, etc.)

You do NOT need to copy-paste any of the brain's universal rules into the arm's CLAUDE.md. The agent loads both files together; only put **arm-specific** context in the arm's CLAUDE.md.

## Registering the Arm with the Brain

If the arm needs to participate in `ai-push` / `ai-pull` cascades:

1. Add the arm's path to `~/.claude/scripts/sync-ai-docs.ps1` (or the bash equivalent) — the active-projects list
2. Add the arm code + path to `~/.claude/company/COMPANY.md` (private operator config, gitignored)
3. If you're going to write Claude Code session JSONLs from this arm, they'll automatically tag with the arm via `cwd` — the FinOps pipeline picks it up

## Anti-patterns

- **Editing `.github/copilot-instructions.md` by hand** — gets overwritten by `sync-ai-docs`. Edit `.claude/CLAUDE.md` only.
- **Copy-pasting brain rules into the arm's CLAUDE.md** — duplication. The agent loads both files together; the arm should carry only arm-specific context.
- **Committing `.env`** — even on a private repo. Habit-form against this; secrets get rotated when leaked.
- **Skipping `sync-ai-docs` after a `.claude/CLAUDE.md` edit** — copilot + Cursor go stale, get conflicting guidance.

## Lessons Learned

<!-- Append patterns as new arms get onboarded — failures, surprises, gotchas. -->
