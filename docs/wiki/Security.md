# Security

Octorato has an unusual security posture. Most projects defend a private codebase against external attackers. Octorato is the opposite: **the repository *is* a running brain, and it is published open-source.** The artifact you are reading — `~/.claude/` — is simultaneously the operator's live working memory *and* a public GitHub repo (`github.com/CarlosCaPe/octorato`) whose every commit, branch, tag, and filename is visible to the world forever.

That inversion drives the entire model. The primary threat is not someone breaking *in*; it is the operator's private world leaking *out* — a client name, a coworker, a secret, a ticket ID — committed once and preserved in public git history permanently. Git is append-only by design; a leak is not a bug you patch, it is a disclosure you cannot fully retract.

This page is the security and generic-safety reference: the threat model, the two enforcement layers, the rules that keep the brain publishable, the agent-safety constraints, and the reporting + recovery protocols. For how the layers fit together architecturally see [[Architecture]]; for the pre-write gate that stops most leaks before they reach git see [[The-4D-Paradigm]].

---

## 1. The threat model

### The core asset is *absence*

In a normal threat model you enumerate assets (a database, an API key, a user table) and defend them. Here the asset to protect is **the operator's private world staying absent from a public history**:

- **Secrets** — API keys, OAuth tokens, bearer tokens, private keys, connection strings with embedded credentials.
- **Identities** — client/customer names, coworker names, internal project codenames, vendor names.
- **Operational context** — ticket IDs, internal URLs, incident details, per-user captured data, financial config.
- **Cross-arm linkage** — anything that reveals that two clients ("arms") are served by the same operator, or moves data from one arm into another.

A breach is any of these reaching the public remote on **any surface git records** — not just file *contents*, but commit messages, branch names, tags, PR descriptions, and **filenames themselves**.

### Why the usual instincts fail here

| Normal instinct | Why it is wrong for Octorato |
|---|---|
| "Secrets go in a private repo, so we're safe." | This repo is public *by design*. There is no private fallback. |
| "We'll scrub it before release." | There is no release event; every push is the release. History is immediate and permanent. |
| "A `.gitignore` entry is enough." | `.gitignore` stops accidental `git add` of whole files, but not a secret pasted into a tracked skill, a commit message, or a branch name. |
| "We can force-push the mistake away." | Force-push removes the tip, but forks, clones, the GitHub events API, and caches may already hold it. Recovery is mitigation, not erasure. |

### Attacker model

The relevant adversaries are mostly passive and opportunistic:

- **Scrapers / credential harvesters** that crawl public GitHub diffs for key-shaped strings within seconds of a push. A leaked key is compromised the moment it is pushed — treat it as burned, not "exposed for a while."
- **Competitive / social intelligence** — anyone correlating client names, coworker names, or codenames across the operator's public footprint.
- **Supply-chain consumers** — because Octorato is a *product* others install and run, a prompt-injection sink or an unsafe destructive default in a skill becomes an attack on *every downstream operator*, not just the author.

The defense strategy is **prevention over reaction**: stop the leak at commit and push time, because once it is public the cleanup is expensive and never perfectly complete.

---

## 2. The "Brain Stays Generic" rule

This is the single non-negotiable rule of the framework, restated here as a security control.

> **Nothing operator-private may enter any surface git records.**

Forbidden content includes — across file contents, filenames, branch names, tags, PR/commit descriptions:

- Client names and customer data
- Coworker / personal names
- Internal project codenames
- Ticket / issue IDs from private trackers
- Internal URLs and hostnames
- Vendor-incident specifics

The discipline that makes this workable is **upward distillation**: a lesson learned inside a client arm is rewritten into a *generic, anonymized skill* before it is ever committed to the brain. The pattern survives; the identifying context does not. A good commit message describes the framework change and nothing about who triggered it or where the lesson came from:

```
✅ feat(brain): add ado-refactor-performance-gate skill
❌ feat(brain): add perf gate from <ClientCorp> ticket PROJ-1423
```

### The `company/` firebreak

The operator's genuinely private context — real client names, the blocklist, identity, connection registries — lives in **`~/.claude/company/`, which is gitignored**. It is the deliberate boundary between "the public brain" and "the operator's private world." Nothing in `company/` ever flows to the public remote. This is also where the private blocklist (below) lives, so the enforcement tooling can read the secret patterns without those patterns themselves becoming public.

### SDD artifacts never at the repo root

Spec-driven-development artifacts — files matching `feature*.md`, `plan*.md`, `spec*.md` — must **never** sit at the brain root. Even when they contain zero client identifiers, a roadmap or "inspiration source" parked at root leaks *intent*: what the operator is building and why. They belong in `docs/specs-archive/`, in `templates/`, in the arm itself, or in `company/`. The commit-time check (below) rejects root-level SDD filenames outright, treating the *filename* as a leak surface in its own right.

---

## 3. Two enforcement layers

Prevention is mechanized, not left to discipline. Two independent layers guard every change, and they are intentionally redundant so that bypassing one still hits the other.

```
            git add / commit                         git push
                  │                                      │
                  ▼                                      ▼
   ┌──────────────────────────────┐      ┌──────────────────────────────┐
   │ Layer 1 — COMMIT-TIME         │      │ Layer 2 — PUSH-TIME           │
   │ scripts/check-generic.py      │      │ .githooks/pre-push            │
   │ • staged file contents        │      │ • universal secret patterns   │
   │ • commit message              │      │ • path denylist               │
   │ • root-level SDD filenames    │      │ • blocklist re-check (if any)  │
   │ • private blocklist tokens    │      │ ALWAYS runs, no soft-fail      │
   │ soft-fails if blocklist absent │      │                              │
   └──────────────────────────────┘      └──────────────────────────────┘
        invoked by the ai-push workflow        fires on EVERY git push
```

### Layer 1 — commit-time: `scripts/check-generic.py`

Runs as part of the `ai-push` workflow, before the commit is finalized. It scans:

1. **Staged file contents** — only the files git is about to commit (binary/vendored files are skipped).
2. **The commit message** — passed via `--message` or `--message-file`.
3. **Root-level filenames** — rejects `feature*.md` / `plan*.md` / `spec*.md` at the brain root.
4. **Private blocklist tokens** — loaded from `company/brain-blocklist.txt` (gitignored), matched **case-insensitively as whole words** (`\b` boundaries) so substrings of legitimate words don't trip it.

Exit codes: `0` clean, `1` leak detected (commit blocked, matches shown), `2` config error.

**The soft-fail caveat:** if `company/brain-blocklist.txt` is missing, this layer warns that generic enforcement is disabled rather than hard-blocking — a fresh clone shouldn't be unable to commit. That gap is exactly why Layer 2 exists and never soft-fails.

### Layer 2 — push-time: `.githooks/pre-push`

A bash hook that runs on **every** `git push`, including a plain `git commit && git push` that skips the `ai-push` workflow entirely. It iterates the refs being pushed and, against the added lines and commit messages, applies:

- **Path denylist** (`[paths]` in `push-policy.txt`) — POSIX-extended-regex patterns for paths that must never be pushed (captured tokens/sessions, per-user data, operator-private directories, finops config, raw incident reports).
- **Content patterns** (`[content]`) — universal secret shapes: JWT/bearer tokens, API-key shapes for the common providers, private-key PEM blocks, and connection strings with embedded `user:pass@host` credentials.
- **Private blocklist** — when `company/brain-blocklist.txt` is present, its tokens are layered on top (same case-insensitive whole-word semantics as Layer 1), so the push-time net is as tight as the commit-time one.

`push-policy.txt` is **committed**, so every clone inherits the same universal baseline. The operator-specific identifiers stay in the gitignored blocklist and are merged in at runtime — the policy is shared, the secrets are not.

### Enabling enforcement on a fresh clone

Git does not version `core.hooksPath`, so the hook must be activated once per clone:

```bash
git config core.hooksPath .githooks
chmod +x ~/.claude/.githooks/pre-push      # macOS / Linux: executable on disk
```

Verify it is live:

```bash
git config --get core.hooksPath            # → .githooks
ls .githooks/pre-push                       # → file exists
```

Smoke-test with a deliberately bad commit (then undo it):

```bash
printf 'FAKE_KEY=sk-1234567890abcdef1234567890abcdef\n' > .env
git add .env && git commit -m "test"
git push                                    # expect: REFUSED by pre-push
git reset --hard HEAD~1 && rm .env          # clean up
```

### The `--no-verify` override

`git push --no-verify` bypasses Layer 2. It exists for the rare case where the universal policy is provably too strict for a specific generic contribution. **Treat every `--no-verify` as a small audit event.** If you reach for it often, the policy needs *updating* — not bypassing. There is no `--force` exception to leaking: a blocklist hit means stop, fix, retry.

### Anti-pattern: URL-level guardrails

An earlier guardrail set the push remote to a sentinel like `DO-NOT-PUSH-FROM-*` to block pushes from the wrong machine. It was *blunt*: it blocked **all** pushes — including legitimate generic-skill contributions — while never actually inspecting content. The two-layer content-aware model replaced it precisely so that **generic content flows and sensitive content blocks, regardless of workflow**. Do not regress to URL-level blocking after enabling the hook.

---

## 4. Arm isolation as a security boundary

The brain serves multiple client "arms," each a sealed per-client repository (`~/Documents/github/<CLIENT>/`). Arm isolation is not just an organizing principle — it is a **confidentiality boundary**:

| Direction | Allowed to flow | Must never flow |
|---|---|---|
| Arm → Brain | Generic, anonymized patterns and skills | Client names, data, credentials |
| Brain → Arm | Rules, paradigms, skills, identity | Any *other* arm's data |
| **Arm → Arm** | **Nothing** | **Everything** |
| Human → Agent | Explicit, operator-initiated cross-arm requests | (the human decides) |

The hard invariant: **an arm never knows another arm exists.** An agent operating inside one arm must never read, reference, or carry data from another. The *only* bridge between arms is the human operator making a deliberate, explicit decision. An agent that autonomously moves data from arm A to arm B — even "helpfully" — has breached the boundary.

Security consequence: a leak that links two arms (revealing they share an operator, or copying one arm's data into another's repo or into the public brain) is a confidentiality breach even if no secret-shaped string is involved. Contributions must never introduce a cross-arm data path. See [[Architecture]] for the full octopus topology.

---

## 5. Agent safety

Because Octorato ships skills and agents that other operators install and run, skill/agent code is **dual-use by default** and is held to security standards as if it were production software:

- **No prompt-injection sinks.** A skill must not construct prompts or tool calls in a way that lets untrusted content (a scraped page, a file, an email body) silently redirect the agent's behavior or exfiltrate context. Untrusted input is data, never instructions.
- **Destructive operations require a dry-run gate.** Anything that deletes, overwrites, force-pushes, or mutates external state must default to *preview* and require explicit opt-in to execute live. This is the `dry-run-gate-pattern` reflex, and it is enforced procedurally by the 4D pre-write gate — see [[The-4D-Paradigm]].
- **No detection-evasion or offensive-only tooling.** Capabilities that exist primarily to evade controls or attack third parties don't belong in the brain.
- **Dual-use security tooling needs authorized context.** Scanners, scrapers, and credential-handling helpers are legitimate *within a clear defensive or authorized scope*. The skill should state that context and refuse to operate as a generic weapon.
- **Never echo back secrets.** An agent must not print user-provided secrets into a transcript, a log, or a commit — including when grepping config/`.env` files, where a label and its value can share a line. Pipe through a redactor.

### The 4D pre-write gate as a leak preventer

The strongest leak prevention happens *before* git is even involved. The [[The-4D-Paradigm]] gate requires a **Change Manifest** — a `terraform plan`-style preview of every file to be created, modified, or deleted — to be shown and confirmed before any write. That human checkpoint catches the client name about to be written into a skill long before `check-generic.py` would catch it at commit time. The enforcement layers are the safety net; the 4D gate is the first line of defense.

---

## 6. Reporting a vulnerability

If you find a security issue — a secret-leak vector, a prompt-injection sink, a way to make an agent cross the arm-isolation boundary, an unsafe destructive default, or anything that could harm an operator running this framework:

- **Do not open a public GitHub issue.** A public issue describing a leak vector is itself a disclosure.
- **Email** `carlos.carrillo@dataqbs.com` with subject `SECURITY: octorato`.
- Include the affected file/path, reproduction steps, and impact.
- Expect acknowledgement within **72 hours**.
- **Coordinated disclosure preferred** — a timeline is agreed before any public write-up.

Fixes land on `master`; this is a single-operator framework with no long-lived release branches, so pull `master` to stay current.

---

## 7. Leak-recovery protocol

If operator-private content reaches the public remote despite both layers, act immediately and in this order. The goal is to minimize the exposure window, not to pretend it didn't happen.

1. **Rotate first, always.** If anything secret-shaped leaked (key, token, password, connection string), **rotate/revoke the credential before touching git.** A leaked secret is compromised the instant it is public; history rewriting does not un-leak it. Rotation is the only real fix.
2. **Rewrite history.** Remove the offending content with `git filter-repo` (preferred for surgical path/content removal) or a squash that drops the bad commit.
3. **Force-push the rewritten history** to the remote immediately to shrink the exposure window.
4. **Tell the operator.** Never silently fix and hope. Disclose what leaked, where, and what was rotated. (For non-secret identity leaks — a client name in a commit message — steps 2–4 still apply; there is no credential to rotate, but the disclosure and rewrite are mandatory.)
5. **Harden the gap.** Add the missed pattern to `push-policy.txt` (if universal) or to `company/brain-blocklist.txt` (if operator-specific) so the same class of leak is caught automatically next time.

Recovery is **mitigation, not erasure** — forks, clones, and GitHub's events API may already hold the leaked commit. That permanence is exactly why the two enforcement layers and the 4D gate exist: the cheapest leak to handle is the one that never gets committed.

---

## Related pages

- [[Architecture]] — the octopus topology: brain, arms, agents, and the isolation boundaries that security depends on.
- [[The-4D-Paradigm]] — the Describe → Delegate → Diligent → Disclose protocol and the pre-write Change Manifest gate that catches leaks before git.
