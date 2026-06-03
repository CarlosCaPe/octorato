# Arms and Sync

> **Organ:** limbs and circulation — sealed arms execute in total isolation; sync is the bloodstream that keeps every machine and every arm current with the brain.

> **The operations reference for client workspaces and multi-machine brain replication.** An *arm* is one sealed client repo that never knows another arm exists. The *brain* is the shared `~/.claude/` repo that cascades rules and skills down to every arm and absorbs anonymized lessons back up. This page covers how to onboard an arm, how knowledge flows both directions, and how to keep the brain consistent across machines.

If you have not yet read [[Architecture]], do that first — it explains *why* arms are isolated. This page explains *how* to run them.

---

## What an arm is

An **arm** is a single client's workspace: an ordinary git repository under `~/Documents/github/<CLIENT>/`, fully sealed from every other arm. (For the octopus biology behind the shape, see [[Architecture]] §9.)

Three properties define an arm:

| Property | Meaning |
|---|---|
| **Sealed** | An arm NEVER knows another arm exists. No file, no environment variable, no skill, no commit references a second client. The seal is mandatory and absolute. |
| **Single source of truth** | The arm's `.claude/CLAUDE.md` is the one authoritative file for that client's context — stack, conventions, connections. Everything else (Copilot, Cursor instructions) is *generated* from it. |
| **Brain-inheriting** | The arm carries only *client-specific* context. All universal rules (4D paradigm, security, git discipline) are inherited from `~/.claude/CLAUDE.md` automatically — never copy-pasted into the arm. |

### Why the seal matters

The isolation guarantee is not a convenience; it is the product. A solo consultant or small agency runs many client engagements from one machine and one AI brain. The risk that client A's data, code, or even *name* leaks into client B's workspace is existential — legally, reputationally, contractually. Octorato makes that leak structurally impossible by giving every client its own repo and forbidding any cross-arm reference. See [[Security]] for the enforcement layers and [[Architecture]] for the full isolation model.

> **The Arm→Arm rule:** Nothing flows between arms. Ever. Not patterns, not config, not lessons — *nothing*. The only path between two arms runs through the human operator's head (see [Upward learning](#upward-learning) below).

---

## Arm onboarding

Onboarding a new client = creating a new isolated repo with a brain-aware structure. The canonical sequence lives in [`skills/arm-onboarding/SKILL.md`](https://github.com/CarlosCaPe/octorato/blob/master/skills/arm-onboarding/SKILL.md); this section is the operations walkthrough.

### Files every arm needs

| Path | Purpose | Edit by hand? |
|---|---|---|
| `.claude/CLAUDE.md` | **Single source of truth** — project stack, DB connections, conventions, arm-specific security notes | ✅ Yes — this is the *only* file you edit |
| `.github/copilot-instructions.md` | Auto-synced copy of `.claude/CLAUDE.md` for GitHub Copilot | ❌ Never — `sync-ai-docs` overwrites it |
| `.cursorrules` | Auto-synced copy of `.claude/CLAUDE.md` for the Cursor editor | ❌ Never — `sync-ai-docs` overwrites it |
| `README.md` | Human-readable repo intro + quick-start | ✅ Yes |
| `.gitignore` | Must include `.env`, `.env.*`, `.dev.vars` | ✅ Yes |
| `.env` | Local secrets — **never committed**, lives only on the operator's machine | ✅ Yes (locally only) |

### Step-by-step

```bash
# 1. Create the arm directory + initialize git
mkdir <CLIENT> && cd <CLIENT> && git init

# 2. Create the brain-aware structure
mkdir -p .claude .github
touch README.md .gitignore .env

# 3. Author .claude/CLAUDE.md — stack, conventions, connections
#    (template below). This is the ONE file that matters.

# 4. Sync — propagate .claude/CLAUDE.md → .github/copilot-instructions.md + .cursorrules
~/.local/bin/sync-ai-docs <ARM_CODE>     # no arg = sync all arms

# 5. (Optional) Register database connections in QueryMaster
#    Edit ~/.config/querymaster/connections.json — NO passwords here.
#    Connections live operator-side, OUTSIDE the arm repo, never committed.

# 6. Harden .gitignore BEFORE the first commit
printf '%s\n' '.env' '.env.*' '.dev.vars' >> .gitignore

# 7. First commit
git add . && git commit -m "chore: bootstrap arm with brain-aligned structure"
```

### The arm `.claude/CLAUDE.md` template

The arm's source-of-truth file declares only **client-specific** context. Universal rules are inherited — do not repeat them.

```markdown
# <CLIENT> — AI Agent Instructions

> Universal constraints (4D paradigm, security, brain rules) live in `~/.claude/CLAUDE.md`.
> This file covers <CLIENT>-specific context only.
> **Single source of truth.** `.github/copilot-instructions.md` + `.cursorrules` are auto-synced.
> Run `sync-ai-docs <CLIENT>` to propagate changes.

## Project Overview
<1-2 sentence summary>

## Stack
- Backend: <e.g., Node + Fastify on Cloudflare Workers>
- DB: <e.g., D1 + KV>
- Frontend: <e.g., Astro + Svelte>
- Deploy: <e.g., npx wrangler pages deploy dist>

## QueryMaster Connections
| Conn name | Engine     | Purpose          |
|-----------|------------|------------------|
| <conn_id> | postgresql | <production DB>  |

## Conventions
- <project-specific naming, file layout, build/test commands>

## Security Rules (Mandatory)
<arm-specific notes — most arms inherit only the universal brain rules>
```

### The One-File Rule

**Edit ONLY `.claude/CLAUDE.md`.** Never hand-edit `.github/copilot-instructions.md` or `.cursorrules` — they are generated artifacts, and the next `sync-ai-docs` run silently overwrites your changes. After *every* edit to `.claude/CLAUDE.md`:

```bash
~/.local/bin/sync-ai-docs <ARM_CODE>
```

Skipping this is the most common onboarding mistake: Copilot and Cursor go stale and start handing the agent conflicting guidance against what Claude reads from `.claude/CLAUDE.md`.

### Registering the arm with the brain

If the arm should participate in `ai-push` / `ai-pull` cascades:

1. Add the arm's path to `~/.claude/company/config/arms-paths.json` (a string or candidate-array path relative to `$HOME`, gitignored) — this is what `scripts/ai_sync.py` reads for all sync operations.
2. Add the arm code + path to `~/.claude/company/COMPANY.md` — the private operator config, gitignored, never published.
3. Claude Code session logs written from the arm auto-tag by `cwd`, so the FinOps cost-rollup picks the arm up with no extra wiring.

### What the arm inherits for free

Once synced, the arm automatically obeys everything the brain defines — you copy *none* of it into the arm:

- The **4D Paradigm** (Describe → Delegate → Diligent → Disclose).
- **Arm isolation** — the new arm cannot see any other arm's data.
- **Security rules** — no secret commits, sanitize inputs, `.env` gitignored ([[Security]]).
- **Git discipline** — atomic `type(scope): description` commits, no force-push to main, no `v1`/`_final` filename suffixes.
- All **universal-reflex skills** — `workspace-skill-discovery`, `session-memory-search`, and the rest ([[Skills-System]]).

The agent loads the brain's `CLAUDE.md` and the arm's `CLAUDE.md` *together* in every session. The arm carries the delta; the brain carries the constant.

### Onboarding anti-patterns

| Anti-pattern | Why it bites | Fix |
|---|---|---|
| Editing `.github/copilot-instructions.md` by hand | Overwritten on next `sync-ai-docs` | Edit `.claude/CLAUDE.md`, then sync |
| Copy-pasting brain rules into the arm | Duplication that drifts out of sync | Put only arm-specific context in the arm |
| Committing `.env` | Secrets leak even on private repos | `.gitignore` it *before* first commit; rotate if leaked |
| Skipping `sync-ai-docs` after editing | Copilot + Cursor go stale and conflict | Make `sync` a reflex after every edit |
| Referencing another client anywhere | Breaks the seal | Never. Each arm is a universe of one client |

---

## Downward distribution — brain to arms

The brain is the *source* of generic knowledge; arms are *consumers*. Rules and skills cascade **down** from `~/.claude/` to every registered arm through `sync-ai-docs`.

```
BRAIN  ~/.claude/CLAUDE.md + skills/        (the constant)
   │
   │  sync-ai-docs  →  regenerates per-arm:
   │                   .github/copilot-instructions.md
   │                   .cursorrules
   ▼
ARMS   client-a/   client-b/   client-c/    (the deltas, sealed)
```

| Flows down | Never flows down |
|---|---|
| Rules, the 4D paradigm, skills, identity | Any *other* arm's data |

When you improve a universal rule or ship a new generic skill in the brain, a single `sync-ai-docs` (no argument) propagates the change to all arms at once, regenerating each arm's editor-instruction files from the brain plus that arm's own `.claude/CLAUDE.md`. Every arm stays current with the brain without ever learning what the other arms contain.

---

## Upward learning — arms to brain

Knowledge also flows **up** — but never raw. A useful pattern discovered while working in an arm must be **distilled into a generic, anonymized skill *before* it is allowed into the brain.**

```
ARM (client-a)            BRAIN (~/.claude/)
  pattern discovered  ──►  HUMAN distills + anonymizes  ──►  generic skill committed
  (may contain client     (strips client names, data,      (publicly visible forever
   names, specifics)        ticket IDs, internal URLs)        — must be generic)
```

Two non-negotiable constraints govern upward flow:

1. **The human is the only gateway.** The AI agent NEVER moves knowledge from one arm to another on its own, and NEVER lifts an arm pattern into the brain autonomously. The operator decides what is generalizable, strips the client-specific surface, and authors the skill. This is the *Human Gateway* principle — only the operator bridges arms.
2. **The brain stays generic.** `~/.claude/` is published open-source; its git history is public forever. Nothing referencing a client name, coworker, internal codename, ticket ID, internal URL, or customer data may enter *any* surface git records — file contents, filenames, commit messages, branches, tags. A lesson from `client-a` becomes, for example, the skill `cron-bridge-daily-publisher` — with every trace of `client-a` removed.

### Enforcement

The generic guarantee is enforced mechanically, not by trust alone (full detail in [[Security]]):

- **Commit-time** — `scripts/check-generic.py` scans staged files and the commit message against the private, gitignored `company/brain-blocklist.txt`. `ai-push` runs it before committing.
- **Push-time** — `.githooks/pre-push` scans every outbound commit against the universal `push-policy.txt` (paths + secret patterns) and layers the blocklist on top when present. Always runs; no soft-fail.

Any blocklist hit blocks the commit or push outright — no `--force`, no exceptions. A correct commit message describes the *framework change* only, never who triggered it or which arm it came from:

- ✅ `feat(brain): add cron-bridge-daily-publisher skill`
- ❌ `feat(brain): add cron skill from client-a arm`

---

## Multi-machine sync

`~/.claude/` *is* the `octorato` git repo — the brain and the repo are the same thing. To run the same brain on a laptop and a desktop, you replicate that repo and re-sync the arms on each machine.

### The two daily commands

| Command | What it does |
|---|---|
| `ai-push "msg"` | Commit + push all of `~/.claude/` to GitHub, **regenerate the connectome** (`neural_map.json`), and run `sync-ai-docs` across all registered arms. One command takes a brain change from "edited" to "live everywhere on this machine + pushed to remote." |
| `ai-pull [arm-code\|--status]` | Pull the latest brain from remote into `~/.claude/`, then re-sync — one arm if you pass an arm code, or all arms by default. `--status` reports state without pulling. |

`ai-push` is the write path: it runs the generic-content check, commits, regenerates the TF-IDF connectome graph so agent/skill selection stays accurate ([[Skills-System]]), pushes, and cascades the change down to every arm. `ai-pull` is the read path on a second machine: get the newest brain, then make every local arm consistent with it.

> **Always pull before you push.** Sync with remote first to avoid divergent brain histories across machines.

### The scripts

Three scripts live in `~/.local/bin/`:

| Script | Role |
|---|---|
| `sync-ai-docs` | Regenerate per-arm editor-instruction files from the brain + each arm's `.claude/CLAUDE.md`. Called by both `ai-push` and `ai-pull`. |
| `ai-push` | Commit + push the brain, regenerate the connectome, sync all arms. |
| `ai-pull` | Pull the brain from remote, sync. |

Active projects are registered in `~/.claude/company/config/arms-paths.json` (read by `scripts/ai_sync.py`) and in the private `~/.claude/company/COMPANY.md`.

### First-time setup on a new machine

```bash
# 1. Clone the brain into place — ~/.claude IS the octorato repo
git clone git@github.com:CarlosCaPe/octorato.git ~/.claude

# 2. Enable the push-time generic-content guard (pre-push hook)
git -C ~/.claude config core.hooksPath .githooks

# 3. Generate the sync script thunks in ~/.local/bin/
python3 ~/.claude/scripts/install-runners.py

# 4. Pull + sync everything
ai-pull
```

After step 4 the machine has the full brain and every registered arm re-synced against it. From then on, `ai-push` / `ai-pull` keep all your machines in lockstep.

---

## Quick reference

| I want to… | Do this |
|---|---|
| Create a new client workspace | Follow [Arm onboarding](#arm-onboarding); edit `.claude/CLAUDE.md`, run `sync-ai-docs` |
| Change an arm's stack/conventions | Edit `.claude/CLAUDE.md` only, then `sync-ai-docs <ARM_CODE>` |
| Ship a generic skill from an arm lesson | Distill + anonymize by hand, commit to brain, `ai-push` |
| Push a brain change everywhere | `ai-push "feat(brain): ..."` |
| Refresh the brain on another machine | `ai-pull` |
| Set up the brain on a fresh machine | Clone `octorato` → `~/.claude`, enable hooks, copy scripts, `ai-pull` |

---

### See also

- [[Architecture]] — the octopus model and why arms are isolated
- [[Security]] — the commit-time + push-time generic-content enforcement layers
- [[Skills-System]] — how skills are authored, loaded, and ranked by the connectome
- [`skills/arm-onboarding/SKILL.md`](https://github.com/CarlosCaPe/octorato/blob/master/skills/arm-onboarding/SKILL.md) — the canonical onboarding sequence
