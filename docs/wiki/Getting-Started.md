# Getting Started

> **Organ:** embryology. The organism grows step by step, from a bare clone to a wired brain that writes its first spec.

This page installs **Octorato**, the open-source AI-agent operating system that lives in `~/.claude/`, and walks you to your first spec. The path is the same one the README shows: clone, then one command. Everything after that is optional and can wait.

One thing to know before you start: **the brain (`~/.claude/`) is a public git repo.** The install keeps your private files out of it, and the push guard it turns on blocks a secret before it can leave your machine.

> **New here?** [[Home]] has the one-paragraph pitch, and [[Architecture]] has the model behind it. You do not need either to install.

---

## Prerequisites

| Tool | Required? | Why | Check |
|---|---|---|---|
| A **runtime**: [Claude Code](https://docs.anthropic.com/en/docs/claude-code) **or** [Cursor](https://cursor.com) | **Yes (one)** | The editor or CLI that loads `~/.claude/` and runs the assistant. Cursor is a supported peer; its limits are listed in `docs/architecture/multi-runtime.md` | `claude --version` **or** Cursor Agent with `CURSOR_AGENT=1` |
| `git` | **Yes** | The brain is a git repo | `git --version` |
| `python3` (3.10+) | **Yes** | The checks are Python scripts | `python3 --version` |

> **Already have a `~/.claude/`?** Move it aside first (`mv ~/.claude ~/.claude.bak`), then clone. Copy any personal `settings.json` keys back in afterward; quickstart only replaces its `hooks` section.

---

## Install: clone, then one command

```bash
git clone https://github.com/CarlosCaPe/octorato.git ~/.claude
python3 ~/.claude/scripts/quickstart.py
```

That second command does every setup step, in this order, and is safe to run again:

| # | Step | What it does |
|---|---|---|
| 1 | Prerequisites | Checks Python, git, and which runtime you have. |
| 2 | Runners | Creates `ai-sync`, `ai-push`, `ai-pull`, `sync-ai-docs` and `octo` in `~/.local/bin/`. |
| 3 | Connectome | Builds the index that matches a task to the right skill or agent. |
| 4 | Claude Code hooks | Copies the automatic checks from `hooks.json` into `~/.claude/settings.json`, then reads the file back to confirm. |
| 5 | Push guard | Sets `git config core.hooksPath .githooks`, so every `git push` from the brain is scanned for secrets. |
| 6 | Cursor hooks | Projects the same checks into Cursor when `~/.cursor` exists. Skipped otherwise. |
| 7 | Health check | Runs `brain_doctor.py --fast`, the quick profile (under 30 seconds on a populated machine). The full check, which proves every gate blocks, is `python3 ~/.claude/scripts/brain_doctor.py`. |
| 8 | First spec | Writes an example spec and checks it with `spec_lint.py`. |

If step 4, 5 or 8 fails, quickstart says which one and exits non-zero. A health-check finding is reported but does not stop the install, because a fresh clone is expected to miss optional parts (a private blocklist, optional Python packages listed in `requirements.txt`).

---

## Your first spec

Quickstart writes it to `~/.claude/company/docs/specs/<date>-first-spec/`. The `company/` folder is your private layer and git ignores it, so the example never ends up in the public repo. To put it in your own project instead, which is where real specs belong:

```bash
python3 ~/.claude/scripts/quickstart.py --project ~/projects/my-app
```

The folder holds two short files. Together they teach the four ideas you need on day one:

| Idea | What it is | Where |
|---|---|---|
| **Spec** | What must be true, one checkable sentence per requirement. | `feature.md` |
| **Plan** | How you will get there, in steps. | `plan.md` |
| **Tasks** | The plan's numbered lines. Each one names the requirements it serves and the files it touches. | `plan.md` |
| **Verdict** | A second assistant that did not write the code reads the code and the tests and decides when it is done. | a receipt, recorded for you |

Check a spec any time:

```bash
python3 ~/.claude/scripts/spec_lint.py ~/.claude/company/docs/specs/*-first-spec
```

Then open your runtime and ask it to build the example. The skills `sdd-feature`, `sdd-plan` and `sdd-converge` carry the rest of the method, and [[The-4D-Paradigm]] explains when a task is big enough to need a spec.

---

## Your first session

Open a terminal in any folder and start Claude Code:

```bash
claude
```

### How the brain greets you

On startup, Claude Code loads `~/.claude/CLAUDE.md` (the constitution), then the folder's own `.claude/CLAUDE.md` when it has one (an arm), then your session memory `MEMORY.md`. Inside an arm, the assistant knows the generic rules and that client's context, and nothing about any other arm.

### How the 4D gate works on your first file change

Ask for something concrete, e.g. *"add a README to this project."* Before writing a single byte, the agent runs the **2D Delegate** check (who knows? has it got an API? who does it?) and then presents a **Change Manifest**, the way `terraform plan` comes before `terraform apply`:

```
## Change Manifest

| # | Action | File                    | Reason                  |
|---|--------|-------------------------|-------------------------|
| 1 | CREATE | ~/projects/my-client/README.md | Project overview |

Impact: 1 file created.
Confirm? (yes/no)
```

Nothing is written until you reply `yes` (or `sí`, `ok`, `dale`). After the write, the agent runs **3D Diligent** (validates the result and reports PASS/FAIL with evidence), then **4D Disclose** (states the impact radius: everywhere the changed object is referenced). This four-phase cycle is mandatory on every action. Full protocol: [[The-4D-Paradigm]].

### How to invoke a skill

Skills are reusable techniques (the synapses). You usually don't have to name one, because the connectome picks them, but you can ask directly:

```text
Use the querymaster-postgresql skill to review this query.
```

Or peek at what *would* fire for a task, straight from the shell:

```bash
python3 ~/.claude/scripts/query_connectome.py query "deploy a Svelte app to Cloudflare Workers"
```

That ranks every agent and skill by similarity to your task, the same lookup the agent runs internally.

### How to activate an agent

Agents are specialist personas (the neurons). Activate one by name:

```text
Activate the Code Reviewer for this change.
```

The agent loads its persona (WHO), the connectome attaches the right skills (HOW), and everything runs scoped to the current arm (FOR WHOM). That three-layer stack (agent × skill × arm) is the core of how work gets done. See [[Architecture]] for the full activation model.

---

## Going further (optional, when you need it)

None of this is part of the install. Come back when you have a reason.

### Your private company brain

The public brain is generic. Your own details (who you are, your clients' short codes, your voice) live in `~/.claude/company/`, which git ignores. Start it from the template:

```bash
cp -r ~/.claude/templates/company/ ~/.claude/company/
mv ~/.claude/company/COMPANY.md.template ~/.claude/company/COMPANY.md
git -C ~/.claude check-ignore company/COMPANY.md   # prints the path: ignored, as it should be
```

If `check-ignore` prints nothing, stop: `company/` is not ignored and private data could leak. Put the client names and internal URLs that must never appear in a public commit in `company/brain-blocklist.txt`; `check-generic.py` reads it before every `ai-push`.

### Your first sealed arm

An **arm** is one client, project or topic in its own folder, with its own `.claude/CLAUDE.md`. Arms never see each other.

```bash
mkdir -p ~/projects/my-client/.claude
cp ~/.claude/templates/arm/CLAUDE.md.template ~/projects/my-client/.claude/CLAUDE.md
```

The full procedure (`.gitignore`, `.env`, AI-doc sync, the arm's own index) is on [[Arms-and-Sync]]. Do not improvise the structure; the template carries the isolation rules.

### Several machines

The runners quickstart installed keep every machine on the same brain:

| Command | What it does |
|---|---|
| `ai-sync ["msg"]` | The daily command. Pulls first, then pushes, and retries if another machine pushed in between. |
| `ai-push "msg"` | Publish only: checks for private content, commits, pushes, rebuilds the index, syncs your arms. |
| `ai-pull [arm]` | Integrate only: pulls the brain and syncs every arm, or one. |
| `sync-ai-docs` | Copies brain rules into each arm's `.github/copilot-instructions.md` and `.cursorrules`. |

On a second machine: clone, run quickstart, then `ai-pull`. Session memory (`~/.claude/projects/`) stays on each machine by design.

### How to see what your agents did

Every session and every subagent runs as a kernel process: a pid, a parent, a worktree, and an append-only hash-chained journal of its tool calls. Three commands read it:

| Command | What it shows |
|---|---|
| `octo ps` | Every process the kernel knows: pid, parent, agent type, tool count, exit status, age, worktree. Live ones first |
| `octo top` | The busiest processes, live plus the last 24 hours, by tool calls and refusals |
| `octo replay <pid>` | One run as it happened: the start, every tool call in order, every refusal folded into the call it stopped, the children, the exit. Add `--verify` to exit non-zero on a broken hash chain |

`octo journal <pid>` hands back the raw lines when you want the JSON rather than the reading, and `octo bench` measures what the journaling costs per tool call on your machine. Design and guarantees: [`docs/architecture/v8-kernel.md`](../architecture/v8-kernel.md).

### How to install a skill someone else wrote

Skills you install run on every prompt, so the brain treats one as a package, not as a
copied folder. Run these from your brain checkout (`cd ~/.claude`):

```bash
python3 scripts/octo_pkg.py list
python3 scripts/octo_pkg.py verify --all
python3 scripts/octo_pkg.py manifests
```

`list` shows what is installed, `verify --all` re-checks every entry. `manifests` asks
the other question, about the skills the brain ships itself rather than the ones it
installed: how many of them carry a `skill.json`. It prints `n/N`, names the ones that
do not, and hands you the exact `gen_skill_manifests.py` command to mint them. Pre-push
runs both, and only their FAIL tier stops a push, so a brain that has never installed a
package and has not been backfilled yet still pushes normally. Installing takes a
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
drifted from what was signed. `verify` also sweeps `skills/vendor` on disk, so a tree
sitting there with no row in the lock is a failure and not a silence: deleting the row
does not delete the check.

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

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `claude` doesn't pick up the rules | Brain not at `~/.claude/` | Confirm `ls ~/.claude/CLAUDE.md` resolves; re-clone if missing |
| Quickstart says "clone the brain to ~/.claude" | The checkout is somewhere else, and Claude Code only loads `~/.claude` | Clone to `~/.claude` and run quickstart from there |
| Quickstart says a first spec path "is inside the brain and git does not ignore it" | `--project` pointed inside the brain repo | Point `--project` at your own project folder, or drop the flag |
| Push rejected by a hook | Secret or forbidden pattern found (working as designed) | Remove the offending content; never `--force`. If it was already pushed, rewrite history and rotate the secret ([[Security]]) |
| `check-generic.py` warns about a missing blocklist | `company/brain-blocklist.txt` not created yet | Expected on a fresh clone; see "Your private company brain" above |
| `ai-push` / `ai-pull` "command not found" | `~/.local/bin` is not on `PATH` | Add `~/.local/bin` to `PATH`, or re-run quickstart, which recreates the runners |
| `query_connectome.py` errors | Wrong Python or missing index | Use `python3` (3.10+) and re-run quickstart, which rebuilds `neural_map.json` |
| `git push` succeeds but the hook never ran | `core.hooksPath` not set | Re-run quickstart, or `git -C ~/.claude config core.hooksPath .githooks` |
| The health check reports missing packages | Optional Python packages not installed | `python3 -m pip install --user -r ~/.claude/requirements.txt` |
| `origin` points at the old `dotclaude` repo | Repo was renamed | `git -C ~/.claude remote set-url origin https://github.com/CarlosCaPe/octorato.git` |

### Where to get help

- **Security vulnerabilities** (secret-leak vectors, arm-isolation escapes, injection paths): **do not open a public issue.** Disclose privately per `SECURITY.md` (subject `SECURITY: octorato`). See also [[Security]].
- **Bugs, questions, feature requests:** open a [GitHub issue](https://github.com/CarlosCaPe/octorato/issues).
- **Understanding the model:** [[Architecture]] (CLASS/OBJECT/ARM), [[The-4D-Paradigm]] (the nervous-system protocol), [[Arms-and-Sync]] (full arm onboarding + sync internals).

---

## Contributing

The brain uses a **staged-promotion** branching model. All pull requests (community contributions, day-to-day work, and bot-authored skills) target **`test`**, the integration branch where changes are iterated and reviewed. **`master`** is the curated, public canonical and is **promotion-only**: it advances solely through a weekly, operator-reviewed `test → master` promotion (the `/promote-test` ritual).

```
fork → branch off test → PR against test → weekly /promote-test → master
```

So: fork the repo, branch off `test`, and open your PR against `test`, never `master`. Full rules (generic-safety, agent/skill structure, commit format) are in the in-repo `CONTRIBUTING.md`. *(The daily dataqbs.com content feed is the exception: it ships to its own repo's `master` daily; staging is for the brain.)*

---

## What you've built

Two commands gave you a brain at `~/.claude/` with its checks wired into your runtime, a push guard that blocks secrets, and a first spec that shows the method: spec, plan, tasks, verdict. The first session showed the 4D gate, skills and agents.

Next: [[The-4D-Paradigm]] explains *why* the agent stops before every write, and [[Arms-and-Sync]] onboards your real clients. Back to [[Home]].
