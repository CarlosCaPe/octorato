# The Skills System

> **Organ:** synapses — learned reflexes that connect any agent to a validated technique, loaded on demand, never all at once.

> How Octorato turns a general-purpose model into a specialist on demand — without ever loading everything at once.

A **skill** is the smallest unit of reusable know-how in the Octorato brain: a self-contained folder holding a procedure, a convention, or a tool integration that the agent should reach for in a specific situation. Skills are the **HOW** layer of the framework. They sit between the rules in [`CLAUDE.md`](Home) and the per-client context of an [[Arms-and-Sync|arm]], and they are loaded *progressively* so that the context window stays cheap.

This page explains skills **as a system** — what they are, how a `SKILL.md` is built, how the agent discovers and loads the right one, how new skills are born, and how they evolve. For the **catalog of every skill that ships with the brain**, see [[Skills]]. For the *personas* that wield skills, see [[Agents-System]]. For how skills grow over time, see [[Self-Growth]].

---

## 1. Skill vs Agent vs Arm — three different questions

The framework cleanly separates three concerns that are easy to conflate. Each answers a different question.

| Layer | Question it answers | Lives in | Example |
|-------|--------------------|----------|---------|
| **Skill** | *HOW* do I do this technique? | `~/.claude/skills/<name>/` | `querymaster-postgresql` — how to write safe parameterized Postgres SQL |
| **Agent** | *WHO* is doing this work? | `~/.claude/agents/` | `database-engineer` — the persona that owns DB work |
| **Arm** | *FOR WHOM* am I doing it? | `<client-repo>/.claude/` | a sealed client repository with its own context |

The activation stack composes them top-down:

```
BRAIN (rules)  →  AGENT (persona / WHO)  →  SKILLS (technique / HOW)  →  ARM (context / FOR WHOM)
```

A useful way to hold this distinction:

- An **agent** is a *role you hire* — it has judgment, a point of view, and a review style. It does not contain step-by-step procedures.
- A **skill** is a *playbook the role consults* — it is procedural, reusable, and persona-agnostic. The same `cache-bust-deploy-validation` skill is used by a backend engineer, an SRE, and a QA agent alike.
- An **arm** is the *job site* — sealed per client, never aware that other arms exist.

> **Why the separation matters.** Because skills are persona-agnostic, one playbook serves every agent. Because they are arm-agnostic (see §6), one playbook serves every client. That is what makes the brain compounding: a lesson learned in one place becomes a capability everywhere, exactly once.

---

## 2. The anatomy of a `SKILL.md`

Every skill is a folder. The only required file is `SKILL.md`; everything else is optional and loaded only when needed.

```
skill-name/
├── SKILL.md            (required)  — frontmatter + body
├── scripts/            (optional)  — executable code run without entering context
├── references/         (optional)  — docs loaded into context on demand
└── assets/             (optional)  — templates/icons used in output, never read into context
```

### 2.1 YAML frontmatter — the part that's *always* loaded

The frontmatter is the **only** part of a skill that lives in the context window at all times. It is the triggering surface — the agent reads `name` + `description` for *every* skill at session start and uses them to decide what to load. Two fields are required:

```yaml
---
name: cache-bust-deploy-validation
description: After a production deploy of a CDN-fronted site, force cache-bust on
  every validation request and inspect Age/cache-status headers — the CDN can serve
  a stale 200 with old content for hours, hiding a broken deploy. Use whenever
  validating a freshly-deployed web app, debugging "deploy completed but the live
  site shows the old version", or building a post-deploy smoke test.
---
```

- **`name`** — lowercase, digits, hyphens only; ≤ 64 chars; verb-led where possible (`gh-address-comments`, not `GitHub Comment Helper`). The folder name must match exactly.
- **`description`** — the single most important line in the whole skill. It must state **both** *what the skill does* **and** *when to use it* (the explicit triggers). This is covered in depth in §5 because description quality literally equals discoverability.

Some brain skills carry an **optional `metadata` block** for skills that are more than passive playbooks — for example a scheduled brain routine declares its runner and cadence:

```yaml
metadata:
  type: brain-routine
  schedule: daily 07:30 UTC
  runner: ~/dataqbs-local-cron/runner.py → workflow brain-trending-digest
```

> Note: upstream tooling (`skill-creator`, validators) treats `name` and `description` as the canonical fields. Keep extra metadata minimal and only where it earns its tokens — the connectome and CI read it, the model mostly does not.

### 2.2 The body — loaded only *after* the skill triggers

The Markdown body is the actual playbook. It is **never** in context until the skill is selected, so a `## When to Use This Skill` section in the body is wasted — "when to use" belongs in the `description`. The body should contain, in order:

1. **Trigger** — a one-liner restating the activation condition (helpful for humans browsing the repo).
2. **How to use** — the procedure itself, in imperative voice ("Run X", "Verify Y"), at the right *degree of freedom*.
3. **Examples** — concise, real, runnable. Prefer one good example over three paragraphs of prose.

**Degree of freedom** is a deliberate design choice the author makes per task:

| Freedom | Form | Use when |
|---------|------|----------|
| High | Prose heuristics | Many valid approaches; decisions are contextual |
| Medium | Pseudocode / parameterized scripts | A preferred pattern exists, some variation OK |
| Low | Exact scripts, few parameters | Fragile, error-prone, must follow one sequence |

> Think of the agent crossing terrain. A narrow bridge over a cliff needs guardrails (low freedom — ship a tested script). An open field allows many routes (high freedom — give heuristics and trust the model).

### 2.3 Bundled resources

| Folder | Loaded into context? | Purpose |
|--------|---------------------|---------|
| `scripts/` | No — executed directly | Deterministic, repeatedly-rewritten code (e.g. `rotate_pdf.py`). Token-free to *run*. |
| `references/` | Yes — on demand | Schemas, API docs, long workflow guides the agent reads while working. |
| `assets/` | No — copied into output | Templates, fonts, boilerplate, logos used in the deliverable. |

**Do not** add `README.md`, `CHANGELOG.md`, `INSTALLATION_GUIDE.md`, or other meta-docs to a skill. A skill contains only what *another instance of the agent* needs to do the job — not the story of how the skill was made.

### 2.4 A complete, minimal template

```markdown
---
name: my-skill
description: <What it does> — <one sharp sentence on the failure mode it prevents
  or value it adds>. Use when <trigger phrase 1>, <trigger phrase 2>, or <context>.
---

# My Skill

## Trigger
Activates when <restate the condition for humans>.

## How to use
1. <imperative step>
2. <imperative step — call out the fragile part>
3. Verify with <the 3D Diligent check that proves it worked>.

## Example
\`\`\`bash
<the shortest runnable example that demonstrates the happy path>
\`\`\`

## Notes
- <non-obvious gotcha the model wouldn't already know>
```

---

## 3. Progressive disclosure — the three-level loading system

Skills exist to make the agent specialist *without* paying for every specialty up front. The context window is a public good shared by the system prompt, conversation history, and the live request. Skills honor that with **three loading levels**:

| Level | What loads | Cost | When |
|-------|-----------|------|------|
| 1. Metadata | `name` + `description` of every skill | ~100 words each | Always (session start) |
| 2. Body | One skill's `SKILL.md` Markdown | < 5k words | When that skill triggers |
| 3. Resources | `references/*.md`, `scripts/*` | Effectively unlimited | Only when the body points to them |

This is why the `description` is sacred and why bodies stay under ~500 lines: Level 1 is paid constantly, so it must be tiny and high-signal; Level 2 is paid occasionally; Level 3 — especially scripts, which *execute without being read* — is effectively free. A skill that crams reference material into its body taxes every session for knowledge most sessions never need. Split it into `references/` and link it.

---

## 4. Discovery and loading — how the right skill gets chosen

Octorato selects skills through layered reflexes plus a graph, not by scanning the whole catalog each time.

### 4.1 Universal reflexes — loaded at session start

A small set of baseline-hygiene skills are treated as defaults the agent internalizes every session (from the **Skill-First Behavior** section of [`CLAUDE.md`](Home)):

- `workspace-skill-discovery` — find arm-level skills under a repo's `.claude/skills/`
- `session-memory-search` — "did we already solve this?" before re-solving
- `progressive-code-exploration` — index-first for files > 100 lines
- `token-efficient-prompting` — compact tables, no preamble
- `post-check-verification` — enforces the 3D Diligent gate; never declare "done" on a write
- `dry-run-gate-pattern` — destructive ops preview first

### 4.2 Domain reflexes — keyword-triggered

Specific phrases route straight to a skill. Examples: web inspection → `agent-browser`; "imagen / screenshot / mira la imagen" → `image-analyzer`; database work → the relevant `querymaster-*` engine skill. These are the fast path — no graph lookup needed when the trigger is unambiguous.

### 4.3 Connectome-based selection — the graph

When the match isn't obvious, the agent asks the **connectome**: `~/.claude/neural_map.json`, a TF-IDF + cosine-similarity graph over every skill and agent (neurons, synapses, pathways, clusters). It is auto-regenerated on every `ai-push` and **never hand-edited**. The agent queries it at the start of a non-trivial task:

```bash
python3 ~/.claude/scripts/query_connectome.py query "build a PDF report from SQL"
```

This returns the optimal *agent → skills* path for the task — the graph-search half of the **2D Delegate** gate (see [[The-4D-Paradigm]]). Combined with the rule-based `delegate-check`, it yields one of three verdicts:

- **ACTIVATE** — load an agent persona *plus* its skills.
- **LOAD** — pull in skills only; no persona needed.
- **SELF** — general model knowledge suffices (only when both graph and rules return no strong match).

### 4.4 Installing skills from outside the brain

New skills don't have to be written from scratch. The `skill-installer` skill pulls curated or arbitrary skills from GitHub repos (including private ones) into the skills directory. Listing, single-install, and multi-install are all supported; restart the agent to pick up newly installed skills.

---

## 5. Authoring a good skill — discoverability is everything

A skill that never triggers is dead weight. Two properties decide whether a skill earns its place.

### 5.1 The description *is* the product

Because the `description` is the only thing in context at decision time, it is the entire user interface of the skill. A weak description ("Helps with deploys") is invisible; the agent will never connect a real task to it. A strong description names the **action**, the **failure mode it prevents**, and **concrete trigger phrases** the operator might actually type:

> ✅ *"After a production deploy of a CDN-fronted site, force cache-bust on every validation request and inspect Age/cache-status headers — the CDN can serve a stale 200 with old content for hours, hiding a broken deploy. Use whenever validating a freshly-deployed web app, debugging 'deploy completed but the live site shows the old version', or building a post-deploy smoke test."*

That description wins because it (a) states the technique, (b) states the *pain* it removes, and (c) embeds the literal words a stuck operator would type. Put every "when to use" cue here — the body is loaded too late to help triggering.

### 5.2 Generic by construction

The brain is **open-source and publicly versioned on GitHub forever** (see [[Security]]). Therefore a skill must be born generic:

- **No client data** — no client names, internal URLs, ticket IDs, credentials, codenames. Ever. Not in the body, not in examples, not in the folder name.
- **Distill, don't dump** — a lesson learned on one arm becomes an *anonymized pattern* before it enters the brain. The shape of the problem is generic; the client who exposed it is not.
- **One concept per skill** — keep the body lean (< 500 lines), split variants into `references/`, and avoid deeply nested references (keep them one level from `SKILL.md`).

This is enforced at commit-time (`check-generic.py`) and push-time (`.githooks/pre-push`). A leak blocks the push — no exceptions, no `--force`.

---

## 6. How skills are born — the self-improvement loop

Skills are created via the **`skill-creator`** skill (`skills/skill-creator/SKILL.md`), which formalizes a six-step process: understand the use cases with concrete examples → plan reusable contents (scripts/references/assets) → scaffold the skill folder and write `SKILL.md` → validate generically with `python3 scripts/check-generic.py` before pushing → iterate on real usage.

Two triggers spawn a new skill automatically:

1. **The rule of three** — when the *same pattern* appears **3 or more times** across tasks, it stops being a coincidence and becomes a skill. (The brain's memory is full of "3× same failure in one session" notes — exactly the signal to codify.)
2. **Lessons-learned on errors** — when the operator catches a real failure, the response is not a survey of options; it is to *patch the brain immediately* — add or update the skill (or a memory entry, or a `CLAUDE.md` rule), verify, and move on. An error is an improvement opportunity, not an approval gate.

This is the **Upward Learning** core principle in action: arm → distilled pattern → generic skill → cascaded back down to every arm via `sync-ai-docs`. The operator is the only gateway that carries knowledge between arms; the agent never does it autonomously.

---

## 7. The skill lifecycle in the self-growth loop

A skill is not write-once. Over its life it moves through four operations, governed by the [[Self-Growth]] loop:

| Operation | When it applies |
|-----------|-----------------|
| **ADD** | A genuinely new capability the brain lacks — no existing skill covers it. |
| **MERGE** | Two skills overlap so heavily that maintaining both invites drift. Consolidate into one canonical skill. |
| **REPLACE** | A better technique, tool, or library supersedes the old approach. The old skill is rewritten, not duplicated (git is the version history — never `skill-v2`). |
| **EXTEND** | The skill is right but incomplete — add a `reference/` for a new variant, a new trigger phrase to the description, or a gotcha to the body. |

Before ADDing, always check whether an EXTEND or MERGE is the honest move — a sprawling catalog of near-duplicates is worse than a smaller set of sharp, well-described skills. Discovery candidates for new skills also flow in daily via the `github-trending-curation` routine, which surfaces only trending tools that beat what the brain already has.

See [[Self-Growth]] for the full decision tree, the gap-detection mechanics over the connectome, and how the loop closes.

---

## 8. Where to go next

- **[[Skills]]** — the full catalog of every skill the brain ships with.
- **[[Agents-System]]** — the personas (WHO) that wield skills.
- **[[Self-Growth]]** — ADD / MERGE / REPLACE / EXTEND and how the brain grows itself.
- **[[The-4D-Paradigm]]** — the Describe → Delegate → Diligent → Disclose protocol that governs *when* skills load and *how* their output is validated.
- **[[Security]]** — why every skill must be client-free, and the two enforcement layers that guarantee it.
