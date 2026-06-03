# Getting Started

> **Organ:** embryology — the organism grows step by step, from a bare clone to a fully wired brain with sealed arms and cross-machine circulation.

This is the install-and-first-run guide for adopting **Octorato** — the open-source AI-agent operating system that lives in `~/.claude/`. By the end you will have a working brain, a private company layer that never leaks to the public, your first client *arm*, multi-machine sync, and a feel for how the agent greets you and gates its first file change.

If you only read one thing: **the brain (`~/.claude/`) is a public git repo.** Everything in Step 2 and Step 3 exists to keep your private world out of it.

> **New here?** Start with [[Home]] for the one-paragraph pitch, then [[Architecture]] for the CLASS / OBJECT / ARM model this guide instantiates.

---

## Prerequisites

| Tool | Required? | Why | Check |
|---|---|---|---|
| [Claude Code](https://docs.anthropic.com/en/docs/claude-code) | **Yes** | The runtime that reads `~/.claude/` and *is* Octorato | `claude --version` |
| `git` | **Yes** | The brain is a git repo; sync is git push/pull | `git --version` |
| GitHub account | **Yes** | To clone the public brain and (optionally) push your fork | `gh auth status` |
| `python3` (3.10+) | **Yes** | The enforcement scripts — connectome query, delegate-check, gate-check | `python3 --version` |
| `node` + `npm` | Optional | Only if an arm's stack needs it (Astro, Svelte, Workers, etc.) | `node --version` |

A blank slate is fine. You do not need to know the architecture before starting — the first session teaches it.

---

## Step 1 — Clone the brain to `~/.claude` (the central brain)

The brain installs *as* your Claude Code config directory. Claude Code reads `~/.claude/CLAUDE.md` on every session; cloning Octorato there is what turns a stock Claude Code into Octorato.

```bash
git clone https://github.com/CarlosCaPe/octorato.git ~/.claude
```

> **Already have a `~/.claude/`?** Back it up first — `mv ~/.claude ~/.claude.bak` — then clone. Copy any personal `settings.json` back in afterward.

Verify the clone landed and the scripts are present:

```bash
ls ~/.claude/CLAUDE.md ~/.claude/scripts/gate-check ~/.claude/.githooks/pre-push
```

All three paths should exist. `CLAUDE.md` is the constitution Claude reads every session; `scripts/` holds the enforcement scripts; `.githooks/` is the secret guard you enable next.

---

## Step 2 — Enable the push-time secret guard (the immune membrane)

**Do this before you ever push.** The brain is published open-source, and git history is permanent and public. One leaked secret or client name in a commit lives on GitHub forever.

Octorato ships a push-time hook that scans every commit you push against a policy file of secret patterns and forbidden paths. It is **not active until you point git at it**:

```bash
git -C ~/.claude config core.hooksPath .githooks
```

### Why this matters

| Layer | Script | When it runs | What it blocks |
|---|---|---|---|
| Commit-time | `scripts/check-generic.py` | Called by `ai-push` before committing | Staged files + commit message vs your private blocklist (soft-fails if the blocklist is missing) |
| **Push-time** | `.githooks/pre-push` | **Every** `git push` once `core.hooksPath` is set | Every pushed commit vs `.githooks/push-policy.txt` (universal secret patterns + paths) — **no soft-fail** |

The push-time layer is the one that always runs and never skips. A blocklist hit blocks the push — no exceptions, no `--force`. If a leak ever reaches the remote: rewrite history (`git filter-repo` or squash), force-push immediately, and rotate the exposed credential. See [[Security]] and the in-repo `SECURITY.md` for the full protocol.

Confirm the hook is wired:

```bash
git -C ~/.claude config --get core.hooksPath   # → .githooks
```

---

## Step 3 — Create your private company brain (the cortex, your private OBJECT)

The public brain is the **CLASS** (generic DNA). Your **company brain** is the private **OBJECT** that instantiates it: your identity, your rates, your client/arm list, your voice, your connection configs. It lives at `~/.claude/company/` and is **gitignored** — nothing in it ever flows to the public repo.

Scaffold it from the shipped template:

```bash
cp -r ~/.claude/templates/company/ ~/.claude/company/
mv ~/.claude/company/COMPANY.md.template ~/.claude/company/COMPANY.md
```

Then edit `~/.claude/company/COMPANY.md` and replace the `{{PLACEHOLDERS}}` with your real details (name, business, the short codes you'll use for each client arm). Open it in your editor of choice:

```bash
${EDITOR:-nano} ~/.claude/company/COMPANY.md
```

**Verify it is actually gitignored** — this is the single most important safety check in the whole setup:

```bash
git -C ~/.claude check-ignore company/COMPANY.md   # → company/COMPANY.md  (means: ignored ✅)
```

If that command prints nothing, **stop** — `company/` is *not* ignored and you risk leaking private data. Confirm `company/` appears in `~/.claude/.gitignore` before continuing.

> Your private blocklist lives here too: `company/brain-blocklist.txt` (also gitignored). Populate it with the client names, codenames, and internal URLs that must never appear in a public commit. `check-generic.py` reads it at commit-time.

---

## Step 4 — Create your first client arm (the first limb, sealed)

An **arm** is a sealed, per-client repo (a **PROPERTY** in the inheritance model). Arms never see each other — that is the core isolation guarantee. Each arm's single source of truth is its own `.claude/CLAUDE.md`, which inherits all brain rules and adds client-specific context.

Quick scaffold for one arm (placeholder name `my-client`):

```bash
mkdir -p ~/projects/my-client/.claude
cp ~/.claude/templates/arm/CLAUDE.md.template ~/projects/my-client/.claude/CLAUDE.md
```

Every arm also needs a `.gitignore` that excludes secrets (`.env`, `.env.*`, `.dev.vars`) and an `.env` for credentials that is **never** committed. The auto-synced AI-tool configs (`.github/copilot-instructions.md`, `.cursorrules`) are generated for you in Step 5.

> **Full procedure** — README, AI-doc sync, the complete checklist — is in [[Arms-and-Sync]]. Do not improvise arm structure; the template encodes the isolation guarantees.

The golden rule, restated: **what flows where.**

| Direction | What flows | What NEVER flows |
|---|---|---|
| Arm → Brain | Generic patterns, anonymized skills, lessons | Client names, data, credentials |
| Brain → Arm | Rules, paradigms, skills, identity | Other arms' data |
| Arm → Arm | **Nothing** | Everything |
| Human → Agent | Explicit cross-arm requests | (you decide) |

Only you, the human operator, ever bridge knowledge between arms. The agent never does it autonomously.

---

## Step 5 — Multi-machine sync (the glial layer)

`~/.claude/` is a git repo, so syncing the brain across laptops is just push/pull — wrapped in three helper scripts that also regenerate the connectome and propagate brain rules down into every arm's AI-doc files.

**One-time setup per machine** — run the installer to generate the helper thunks in `~/.local/bin/`:

```bash
python3 ~/.claude/scripts/install-runners.py
```

This creates `ai-push`, `ai-pull`, and `sync-ai-docs` in `~/.local/bin/` for both POSIX and Windows.

**Daily workflow:**

| Command | What it does |
|---|---|
| `ai-push "msg"` | Runs the generic-content check, commits + pushes `~/.claude/`, regenerates the neural connectome, syncs all arms |
| `ai-pull` | Pulls the brain from the remote and syncs every arm down |
| `ai-pull <arm-code>` | Pulls + syncs a single arm only |
| `ai-pull --status` | Shows sync status without changing anything |
| `sync-ai-docs` | Cascades brain rules into each arm's `.github/copilot-instructions.md` + `.cursorrules` |

On a brand-new workstation the bootstrap is: clone the brain (Step 1), enable the hook (Step 2), run the installer (above), then run `ai-pull`. From then on, `ai-pull` at the start of a work block and `ai-push "..."` when you've improved the brain.

> **Note:** episodic memory (`~/.claude/projects/`) is gitignored and stays per-machine by design — it contains absolute paths and arm context that must not go public. Brain stays generic; memory stays sovereign.

---

## Your first session — a walkthrough

Open a terminal in your new arm and start Claude Code:

```bash
cd ~/projects/my-client
claude
```

### How the brain greets you

On startup, Claude Code loads `~/.claude/CLAUDE.md` (the constitution), then the arm's `.claude/CLAUDE.md`, then your episodic `MEMORY.md`. You're now talking to Octorato operating *inside this arm's context* — it knows the generic rules, the client context, and nothing about any other arm.

### How the 4D gate works on your first file change

Ask for something concrete, e.g. *"add a README to this project."* Before writing a single byte, the agent runs the **2D Delegate** check (who knows? has it got an API? who does it?) and then presents a **Change Manifest** — think `terraform plan` before `terraform apply`:

```
## Change Manifest

| # | Action | File                    | Reason                  |
|---|--------|-------------------------|-------------------------|
| 1 | CREATE | ~/projects/my-client/README.md | Project overview |

Impact: 1 file created.
Confirm? (yes/no)
```

Nothing is written until you reply `yes` (or `sí`, `ok`, `dale`). After the write, the agent runs **3D Diligent** — validates the result and reports PASS/FAIL with evidence — then **4D Disclose** — states the impact radius (everywhere the changed object is referenced). This four-phase cycle is mandatory on every action. Full protocol: [[The-4D-Paradigm]].

### How to invoke a skill

Skills are reusable techniques (the synapses). You usually don't have to name one — the connectome auto-selects them — but you can ask directly:

```text
Use the querymaster-postgresql skill to review this query.
```

Or peek at what *would* fire for a task, straight from the shell:

```bash
python3 ~/.claude/scripts/query_connectome.py query "deploy a Svelte app to Cloudflare Workers"
```

That ranks every agent and skill by similarity to your task — the same lookup the agent runs internally.

### How to activate an agent

Agents are specialist personas (the neurons). Activate one by name:

```text
Activate the Database Optimizer for this audit.
```

The agent loads its persona (WHO), the connectome attaches the right skills (HOW), and everything runs scoped to the current arm (FOR WHOM). That three-layer stack — agent × skill × arm — is the core of how work gets done. See [[Architecture]] for the full activation model.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `claude` doesn't pick up the rules | Brain not at `~/.claude/` | Confirm `ls ~/.claude/CLAUDE.md` resolves; re-clone if missing |
| Push rejected by a hook | Secret/forbidden pattern detected (working as designed) | Remove the offending content; never `--force`. If already pushed, rewrite history + rotate the secret ([[Security]]) |
| `check-generic.py` "soft-fails" / warns about missing blocklist | `company/brain-blocklist.txt` not created | Create it in Step 3; it's expected to be absent on a fresh clone |
| `ai-push` / `ai-pull` "command not found" | Scripts not on `PATH` | Re-run the Step 5 copy + `chmod +x`; ensure `~/.local/bin` is on `PATH` |
| `query_connectome.py` errors | Wrong Python or missing connectome | Use `python3` (3.10+); run `ai-push` once to regenerate `neural_map.json` |
| `git push` succeeds but the hook never ran | `core.hooksPath` not set | Re-run Step 2: `git -C ~/.claude config core.hooksPath .githooks` |
| `origin` points at the old `dotclaude` repo | Repo was renamed | `git -C ~/.claude remote set-url origin https://github.com/CarlosCaPe/octorato.git` |

### Where to get help

- **Security vulnerabilities** (secret-leak vectors, arm-isolation escapes, injection paths): **do not open a public issue.** Email `carlos.carrillo@dataqbs.com` with subject `SECURITY: octorato`. See `SECURITY.md` and [[Security]].
- **Bugs, questions, feature requests:** open a [GitHub issue](https://github.com/CarlosCaPe/octorato/issues).
- **Understanding the model:** [[Architecture]] (CLASS/OBJECT/ARM), [[The-4D-Paradigm]] (the nervous-system protocol), [[Arms-and-Sync]] (full arm onboarding + sync internals).

---

## Contributing

The brain uses a **staged-promotion** branching model. All pull requests — community contributions, day-to-day work, and bot-authored skills — target **`test`**, the integration branch where changes are iterated and reviewed. **`master`** is the curated, public canonical and is **promotion-only**: it advances solely through a weekly, operator-reviewed `test → master` promotion (the `/promote-test` ritual).

```
fork → branch off test → PR against test → weekly /promote-test → master
```

So: fork the repo, branch off `test`, and open your PR against `test` — never `master`. Full rules (generic-safety, agent/skill structure, commit format) are in the in-repo `CONTRIBUTING.md`. *(The daily dataqbs.com content feed is the exception — it ships to its own repo's `master` daily; staging is for the brain.)*

---

## What you've built

After these five steps you have: a public brain at `~/.claude/`, a secret guard that blocks leaks at push time, a private gitignored company layer, a first sealed client arm, and cross-machine sync. The first session showed you the 4D gate, skill invocation, and agent activation — the three reflexes you'll use every day.

Next: read [[The-4D-Paradigm]] to understand *why* the agent stops before every write, and [[Arms-and-Sync]] to onboard your real clients. Back to [[Home]].
