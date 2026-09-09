# Getting Started

> **Organ:** embryology — the organism grows step by step, from a bare clone to a fully wired brain with sealed arms and cross-machine circulation.

This is the install-and-first-run guide for adopting **Octorato** — the open-source AI-agent operating system that lives in `~/.claude/`. By the end you will have a working brain, a private company layer that never leaks to the public, your first client *arm*, multi-machine sync, and a feel for how the agent greets you and gates its first file change.

If you only read one thing: **the brain (`~/.claude/`) is a public git repo.** Everything in Step 2 and Step 3 exists to keep your private world out of it.

> **New here?** Start with [[Home]] for the one-paragraph pitch, then [[Architecture]] for the CLASS / OBJECT / ARM model this guide instantiates.

---

## Prerequisites

| Tool | Required? | Why | Check |
|---|---|---|---|
| A **runtime** — [Claude Code](https://docs.anthropic.com/en/docs/claude-code) **or** [Cursor](https://cursor.com) | **Yes (one)** | The harness that loads `~/.claude/` and *runs* Octorato. Claude Code was first; Cursor is a **supported peer** (hooks projected by `merge-hooks-cursor.py`; see Honest gaps in `docs/architecture/multi-runtime.md`). More editors get a binding as they are used — see [[Architecture]] / `docs/architecture/multi-runtime.md` | `claude --version` **or** Cursor Agent with `CURSOR_AGENT=1` |
| An **engine** the runtime can select (Claude family, Grok, GPT, Composer, …) | **Yes** | The model that reasons. Octorato is engine-agnostic; the ladder binds tiers to whatever the runtime exposes | Session model picker |
| `git` | **Yes** | The brain is a git repo; sync is git push/pull | `git --version` |
| GitHub account | **Yes** | To clone the public brain and (optionally) push your fork | `gh auth status` |
| `python3` (3.10+) | **Yes** | The enforcement scripts — connectome query, delegate-check, gate-check | `python3 --version` |
| `node` + `npm` | Optional | Only if an arm's stack needs it (Astro, Svelte, Workers, etc.) | `node --version` |

A blank slate is fine. You do not need to know the architecture before starting — the first session teaches it. **Octorato is for all models and all editors**; it grows as new ones are known.

---

## Step 1 — Clone the brain to `~/.claude` (the central brain)

The brain installs at `~/.claude/` — the historical path Claude Code reads natively. **Cursor and other runtimes load the same files** (project rules, arm `CLAUDE.md`, projected hooks). Cloning Octorato there is what turns a stock editor into an Octorato-powered agent OS, regardless of which engine (Claude, Grok, GPT, …) the operator picks.

```bash
git clone https://github.com/CarlosCaPe/octorato.git ~/.claude
```

> **Already have a `~/.claude/`?** Back it up first — `mv ~/.claude ~/.claude.bak` — then clone. Copy any personal `settings.json` back in afterward.

**Cursor operators (after clone):** project hooks into Cursor so fail-closed gates fire in the IDE too:

```bash
python3 ~/.claude/scripts/merge-hooks-cursor.py
```

Verify the clone landed and the scripts are present:

```bash
ls ~/.claude/CLAUDE.md ~/.claude/scripts/gate-check ~/.claude/.githooks/pre-push
```

All three paths should exist. `CLAUDE.md` is the constitution every runtime reads; `scripts/` holds the enforcement scripts; `.githooks/` is the secret guard you enable next.

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

This creates `ai-sync`, `ai-push`, `ai-pull`, `sync-ai-docs` and `octo` in `~/.local/bin/` for both POSIX and Windows.

**Daily workflow:**

| Command | What it does |
|---|---|
| `ai-sync ["msg"]` | **The canonical daily command.** Integrates first (`git pull --rebase --autostash`), then publishes (`push`), and retries the loop when a sibling machine pushed mid-flight. One command, race-safe and idempotent, built for running one brain across many machines at once |
| `ai-push "msg"` | Primitive: the publish half only. Runs the generic-content check, commits + pushes `~/.claude/`, regenerates the neural connectome, syncs all arms |
| `ai-pull` | Primitive: the integrate half only. Pulls the brain from the remote and syncs every arm down |
| `ai-pull <arm-code>` | Pulls + syncs a single arm only |
| `ai-pull --status` | Shows sync status without changing anything |
| `sync-ai-docs` | Cascades brain rules into each arm's `.github/copilot-instructions.md` + `.cursorrules` |

On a brand-new workstation the bootstrap is: clone the brain (Step 1), enable the hook (Step 2), run the installer (above), then run `ai-pull`. From then on, `ai-sync "..."` whenever you've improved the brain; reach for `ai-push` or `ai-pull` only when you want just one half of the cycle.

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

### How to see what your agents did

Every session and every subagent runs as a kernel process: a pid, a parent, a worktree, and an append-only hash-chained journal of its tool calls. Three commands read it:

| Command | What it shows |
|---|---|
| `octo ps` | Every process the kernel knows: pid, parent, agent type, tool count, exit status, age, worktree. Live ones first |
| `octo top` | The busiest processes, live plus the last 24 hours, by tool calls and refusals |
| `octo replay <pid>` | One run as it happened: the start, every tool call in order, every refusal folded into the call it stopped, the children, the exit. Add `--verify` to exit non-zero on a broken hash chain |

`octo journal <pid>` hands back the raw lines when you want the JSON rather than the reading, and `octo bench` measures what the journaling costs per tool call on your machine. Design and guarantees: [`docs/architecture/v8-kernel.md`](../architecture/v8-kernel.md).

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

### How to install a skill someone else wrote

Skills you install run on every prompt, so the brain treats one as a package, not as a
copied folder. Run these from your brain checkout (`cd ~/.claude`):

```bash
python3 scripts/octo_pkg.py list
python3 scripts/octo_pkg.py verify --all
```

`list` shows what is installed, `verify --all` re-checks every entry. Installing takes a
source in any of four spellings: a GitHub URL like
`https://github.com/<owner>/<repo>/tree/<ref>/skills/<name>` paired with
`--path skills/<name>`, an `<owner>/<repo>` pair with `--path`, a git repository (a
remote URL or a local path), or a plain directory holding the package. There is nothing
to install yet from a public source, because a package has to be signed by a principal
you trust before it is allowed in; the next section builds and installs one end to end,
which is also the fastest way to see the checks fire.

Before a single byte is copied, the installer validates the package's `skill.json`,
recomputes a hash over every file in the tree and compares it to the one the manifest
claims, then checks the detached signature with `ssh-keygen -Y verify` against the
principals in `registry/pkg-signers.pub`. Anything that does not line up is refused and
nothing is written, so an unsigned or drifted package never reaches your skills
directory. What lands is `skills/vendor/<name>` plus a `skills/<name>` symlink, both kept
out of git, and a row in the tracked `packages.lock.json`.

That row is what makes a second machine reproducible: `ai-pull` runs `octo pkg sync`,
which reinstalls from the lock and verifies. `brain_doctor` reports the same ladder as
`packages-verified`, and pre-push refuses to publish while an installed package has
drifted from what was signed.

### How to publish a skill of your own

Four steps, and every line below runs as written from the brain checkout. It uses a
throwaway key and a copy of the sample package under `/tmp`, so nothing in your repo is
touched.

```bash
cp -r registry/fixtures/META.kernel-package/signed /tmp/my-skill
python3 scripts/octo_pkg.py hash /tmp/my-skill --write
ssh-keygen -t ed25519 -N "" -C my-release -f /tmp/my-release-key
ssh-keygen -Y sign -f /tmp/my-release-key -n octorato-pkg /tmp/my-skill/skill.json
```

`hash --write` computes the tree hash with the same function the installer will use and
embeds it as `tree_sha256`; computing it any other way guarantees a refusal nobody can
read. It also deletes any `skill.json.sig` sitting there, and that deletion matters more
than it looks: `ssh-keygen -Y sign` asks before overwriting an existing `.sig`, and with
no terminal to answer (a script, a CI step, a heredoc) it declines, keeps the OLD
signature and still exits 0. Re-signing an edited package would silently ship a
signature made over a manifest nobody has. So always re-run `hash --write` before
signing again, never `ssh-keygen -Y sign` on its own.

`ssh-keygen -Y sign` needs `-f <your private key>` and the `octorato-pkg` namespace, and
writes the detached `skill.json.sig` beside the manifest. Ship both.

To install what you just signed, your principal has to be trusted. Add its public line
to the gitignored `company/config/pkg-signers` (one line, `<principal> <keytype>
<base64>`, no email and no hostname), then install from the directory:

```bash
mkdir -p company/config
awk '{print "my-release " $1 " " $2}' /tmp/my-release-key.pub >> company/config/pkg-signers
python3 scripts/octo_pkg.py install /tmp/my-skill
python3 scripts/octo_pkg.py verify --all
python3 scripts/octo_pkg.py uninstall sample-package
```

Start a real package from `templates/skill/skill.json.template`. The `octorato-release`
principal in `registry/pkg-signers.pub` is the project's own; adopters add their own
principals in that private file rather than editing the tracked one.

An unsigned third-party skill is still installable, on the Codex `--dest` path of the
`skill-installer` skill, outside the lock and without any claim that it was verified.

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

- **Security vulnerabilities** (secret-leak vectors, arm-isolation escapes, injection paths): **do not open a public issue.** Disclose privately per `SECURITY.md` (subject `SECURITY: octorato`). See also [[Security]].
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
