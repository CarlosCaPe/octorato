# Architecture

> **Organ:** anatomy atlas — the complete map of every layer, how they inherit, and why the organism takes this shape.

The deep architecture reference for Octorato — the open-source AI-agent operating system that lives in `~/.claude/`. This page explains *why* the framework takes the shape it does, the object model that governs inheritance, the activation stack that fires on every task, the layers and their isolation guarantees, and the connectome that wires it all together.

If you want the philosophy in one sentence: **one human consciousness directs a shared brain of specialist agents across many sealed client workspaces, and the data never crosses sideways.** That single constraint — and the biology that solves it — produces everything below.

> **Companion pages:** [[The-4D-Paradigm]] (the nervous-system protocol every signal obeys) · [[Skills-System]] (the *HOW* layer) · [[Agents-System]] (the *WHO* layer) · [[Arms-and-Sync]] (the *FOR WHOM* layer + multi-machine sync) · [[Self-Growth]] (how the brain extends itself).

---

## 1. The mental model: CLASS / OBJECT / ARM

Octorato is an object-oriented inheritance model expressed in the filesystem. Three tiers, each instantiating the one above it.

```
┌──────────────────────────────────────────────────────────────┐
│   BRAIN = CLASS  (this repo, open-source, the DNA)           │
│   ~/.claude/                                                 │
│                                                              │
│   What it IS:                                                │
│     - The 4D Paradigm (Describe·Delegate·Diligent·Disclose)  │
│     - The Octopus Architecture (brain/arm isolation)         │
│     - The connectome engine (TF-IDF, cosine similarity)      │
│     - Generic agent personas (the WHO)                       │
│     - Generic skills (techniques, not client workflows)      │
│     - Enforcement scripts (delegate-check, gate-check, etc.) │
│     - Templates for building your own company brain + arms   │
│                                                              │
│   What it is NOT:                                            │
│     - Anyone's personal identity                             │
│     - Anyone's client list, data, or credentials             │
└──────────────────────┬───────────────────────────────────────┘
                       │  instantiates
┌──────────────────────▼───────────────────────────────────────┐
│   COMPANY BRAIN = OBJECT  (your private instance)            │
│   ~/.claude/company/   (gitignored from the framework repo)  │
│                                                              │
│     - Your professional identity (name, rates, certs, CV)    │
│     - Your arm definitions (which clients, which codes)      │
│     - Your company-specific skills and workflows             │
│     - Your connection configs, assets, voice style           │
└──────────────────────┬───────────────────────────────────────┘
                       │  manages
┌──────────────────────▼───────────────────────────────────────┐
│   ARMS = PROPERTIES  (client projects, isolated)             │
│   ~/Documents/github/<CLIENT>/                               │
│                                                              │
│   Each arm is a sealed client repo.                          │
│   Arms never see each other's data.                          │
│   Each has its own .claude/CLAUDE.md (single source of truth)│
└──────────────────────────────────────────────────────────────┘
```

Why this matters in practice:

- **The CLASS is public.** The brain repo ships under an open-source license; its git history is visible on GitHub forever. So the CLASS must stay *generic* — see [§7 Arm isolation](#7-arm-isolation--the-cardinal-invariant) and the [[Self-Growth]] page for how lessons get sanitized before they can enter it.
- **The OBJECT is private.** `company/` is gitignored. Identity, rates, the actual list of clients — all of it lives here and never flows into the public CLASS.
- **The PROPERTIES are sealed.** Each arm is a separate repo with its own instructions. An arm inherits the CLASS rules (4D, security, isolation) and the OBJECT's identity, but it knows nothing about its sibling arms.

The inheritance direction is strict: **CLASS → OBJECT → ARM**, never the reverse, never sideways.

---

## 2. The flow: HUMAN → BRAIN → ARMS → AGENT

The runtime control flow is a four-stage loop. Intent originates in the human, descends through the brain into a sealed arm, and is executed by the AI agent acting as the nervous system.

```
HUMAN (Operator) — consciousness, decisions, intent
   │
   ▼
BRAIN  ~/.claude/  — CLAUDE.md (rules) + skills/ (HOW) + agents/ (WHO) + .git
   │  ↓ distributes generic knowledge   ↑ absorbs lessons learned
   ▼
ARMS   client-a, client-b, ... (isolated per client repo)
   ▲
AI AGENT — nervous system, executes via 4D paradigm
```

| Stage | Role | Responsibility |
|---|---|---|
| **HUMAN** | Consciousness | Sets intent, makes irreversible decisions, is the *only* bridge between arms. |
| **BRAIN** | Central nervous system | Holds rules, paradigms, agents, skills. Distributes generic knowledge down; absorbs anonymized lessons up. |
| **ARMS** | Peripheral execution sites | Sealed client repos. Each carries client context but no awareness of other arms. |
| **AI AGENT** | The nervous system itself | Reads brain + arm, selects the persona, loads skills, executes — all governed by the [[The-4D-Paradigm]]. |

The two vertical arrows on the BRAIN line are the entire economic argument for the framework:

- **↓ Downward distribution** — rules and skills cascade to every arm (`sync-ai-docs`, `ai-pull`). Write a technique once; every client benefits.
- **↑ Upward learning** — a pattern discovered in one arm is *distilled to generic* and promoted into the brain, where it becomes available everywhere. The client-specific details are stripped at the boundary.

Sideways — arm to arm — **nothing** flows. That asymmetry is the cardinal invariant, formalized in [§5](#5-information-flow-rules) and [§7](#7-arm-isolation--the-cardinal-invariant).

---

## 3. The activation stack: Brain → Agent → Skills → Arm

Every non-trivial task activates **three layers simultaneously**, on top of the brain that hosts them. Read it as a sentence: *the brain dispatches a **who**, equips them with a **how**, and points them at a **for whom**.*

```
BRAIN     hosts everything, enforces the rules
  └─ AGENT   = WHO       (persona, expertise, voice)
       └─ SKILL  = HOW       (technique, workflow, best practices)
            └─ ARM    = FOR WHOM  (client context, data, config)
```

| Layer | Question | Concretely |
|---|---|---|
| **Brain** | Under what rules? | 4D Paradigm, security, isolation — inherited by everything below. |
| **Agent** | WHO does it? | A specialist persona with a role, domain expertise, and a voice. |
| **Skill** | HOW is it done? | A reusable technique loaded into context for this task only. |
| **Arm** | FOR WHOM? | The sealed client repo whose data and config scope the work. |

**Worked example — a client needs a database audit:**

1. **Brain** matches the task domain and dispatches the **Database Optimizer** agent *(WHO)*.
2. It loads `explain-analyze-validation` + `index-creation-concurrently` skills *(HOW)*.
3. It operates strictly inside that client's **arm** *(FOR WHOM)*.
4. **Result:** a specialist persona writing idempotent DDL, scoped to a single client, under the brain's 4D rules — and to no other client's data.

The stack is why the same brain can serve unbounded clients without code duplication: the *who* and the *how* are generic and shared; only the *for whom* is sealed and private.

---

## 4. The layers

Four architectural layers, each with a fixed location on disk and a defined isolation property. This is the canonical table from `CLAUDE.md`.

| Layer | Location | Isolation |
|---|---|---|
| **Brain** | `~/.claude/` | Shared across all arms — the generic CLASS. |
| **Agents** | `~/.claude/agents/` (+ `REGISTRY.md`) | Generic personas, no client data. |
| **Skills** | `~/.claude/skills/` | Generic techniques, no client data. |
| **Arm** | `<WORLD>/` (one sealed repo per world, e.g. `~/Documents/github/<WORLD>/`) | Per-world repo, fully sealed: a client, a project, a topic, a course. |
| **Arm instructions** | `<CLIENT>/.claude/CLAUDE.md` | Single source of truth for that arm. |

Two properties to internalize:

- **The Agents and Skills layers live *inside* the Brain layer** and inherit its genericity. An agent or skill that referenced a client name would corrupt the public CLASS — so the [[Agents-System]] and [[Skills-System]] are curated to be technique-only.
- **The Arm layer is the only place client data legally exists.** Its instructions file (`<CLIENT>/.claude/CLAUDE.md`) is the *single source of truth* for that client and is generated/maintained per the [[Arms-and-Sync]] onboarding flow. Brain-side AI docs (`copilot-instructions.md`, `.cursorrules`) are auto-synced down from the brain — never hand-edited per arm.

### 4a. Two-tier memory model

The `1 + N` brain count the octopus biology implies extends to *memory*. Most operational knowledge lives arm-local (recall: two-thirds of an octopus's neurons are in its arms); the central brain stays lean and generic.

| Tier | Scope | Location | What lives here |
|---|---|---|---|
| **Brain memory** | Cross-arm, generic | Private `octorato-memory` repo (gitignored from this public repo, holds its own `.git` → private remote) | Operator identity, cross-arm lessons already distilled to generic, global context that survives arm changes |
| **Arm memory** | Per-arm, client-specific | Each arm's own private repo, loaded via symlink | Client-specific facts, project history, local lessons not yet (or never) promoted |

The wall between tiers mirrors the Arm Isolation invariant: arm memory never crosses to another arm or enters the public brain. Only the mechanism ships publicly (`scripts/memory_sync.py` + a template); the private remote URL and any memory content stay out of this repo entirely — same boundary as `company/`.

Generic lessons distil **upward** (arm memory → brain memory, stripped of client details) following the same cycle as skills: see [§6](#6-upward-learning-and-downward-distribution). The full data model, sync protocol, and directory layout are in [`docs/architecture/memory-model.md`](../architecture/memory-model.md).

---

## 5. Information-flow rules

The isolation model reduces to one table. Memorize it; it is the constitution.

| Direction | What flows | What NEVER flows |
|---|---|---|
| **Arm → Brain** | Generic patterns, skills, lessons | Client names, data, credentials |
| **Brain → Arm** | Rules, paradigms, skills, identity | Other arms' data |
| **Arm → Arm** | **NOTHING** | Everything |
| **Human → Agent** | Explicit cross-arm requests | (the human decides what to bridge) |

Reading the rows:

- **Arm → Brain** is *upward learning*, but gated: a pattern must be distilled to a generic, anonymized skill **before** it can cross the boundary. The "what never flows" column is enforced by the generic-check tooling (see [§7](#7-arm-isolation--the-cardinal-invariant)).
- **Brain → Arm** is *downward distribution*: rules, the 4D paradigm, skills, and the operator's identity cascade down. Crucially, **another arm's data is never part of that payload.**
- **Arm → Arm = NOTHING** is the load-bearing row. There is no direct channel. No shared cache, no shared session, no cross-mount.
- **Human → Agent** is the *only* legitimate bridge between arms. If knowledge must move from client A's context to client B's, a human makes that decision explicitly. The AI never does it autonomously — the **Human Gateway** principle.

---

## 6. Upward learning and downward distribution

The two vertical flows are what make the brain compound in value over time.

### Downward distribution (Brain → Arms)

```
~/.claude/CLAUDE.md + skills/  ──sync-ai-docs / ai-pull──▶  every arm's .claude/, .github/, .cursorrules
```

- Generic rules and skills are written once and cascade to all arms.
- Per-arm AI-tooling configs (`copilot-instructions.md`, `.cursorrules`) are *derived* from the brain, keeping every client workspace consistent with the latest paradigm.
- Triggered by `ai-pull` on each workstation and `ai-push` after a brain change. Full mechanics in [[Arms-and-Sync]].

### Upward learning (Arm → Brain), the distill-to-generic cycle

```
1. ARM discovers a pattern    → "this query fix cut sequential scans 10×"
2. HUMAN approves capture      → "yes, make it a skill"
3. BRAIN stores a generic skill → ~/.claude/skills/<name>/SKILL.md
                                  (anonymized: no client name, no table names, no data)
4. BRAIN distributes to ALL    → ai-push regenerates the connectome + sync
5. OTHER ARMS benefit          → the next project loads the skill automatically
```

The non-negotiable step is **(3)**: the lesson is *distilled to generic* before it ever touches the brain. The transformation strips client names, internal URLs, ticket IDs, table names, and any data, leaving only the reusable technique. See [[Self-Growth]] for the auto-skill-creation protocol (a pattern recurring 3+ times triggers a candidate skill) and the daily discovery loop.

---

## 7. Arm isolation — the cardinal invariant

Everything else is an optimization. **Arm isolation is the rule that cannot be broken.**

> **An arm NEVER knows another arm exists. No cross-contamination, ever.**

It is enforced at four levels:

1. **Architectural** — arms are *separate git repositories* on disk. There is no shared directory through which data could leak. The only common ancestor is the generic brain.
2. **Protocol** — the [[The-4D-Paradigm]]'s *Disclose* phase runs an **Impact Radius** scan before any change, surfacing every place an object is referenced — making accidental cross-arm writes visible before they happen.
3. **Human Gateway** — the AI is forbidden from bridging arms autonomously. Only the operator decides to move knowledge across the boundary, and only as explicitly anonymized generic skills.
4. **Publication guards** — because the brain is public, two scripted layers protect the boundary at the moment knowledge tries to enter the CLASS:
   - **Commit-time** — `scripts/check-generic.py` scans staged files and the commit message against a private blocklist before committing.
   - **Push-time** — a `pre-push` hook scans every commit against a universal policy (paths + secret patterns) plus the private blocklist. Always runs, no soft-fail.

   Any blocklist hit blocks the commit/push. No exceptions, no `--force`. If a leak reaches the public history, the response is to rewrite history and force-push immediately — never silently patch and hope.

The reason this is so heavily defended: the brain's genericity is not a style preference, it is the multi-tenancy security boundary. A client name in a public skill file is a data breach, not a typo.

---

## 8. The connectome

The brain is not a flat pile of agents and skills — it is a **weighted graph**. The connectome (`neural_map.json`) is what turns "I have a task" into "here is the right specialist and the right techniques."

### What it is

`neural_map.json` is a TF-IDF + cosine-similarity graph built over the **full content** of every agent and skill file. It is **auto-generated by `scripts/generate_neural_map.py` on every `ai-push`** and is **never edited by hand**.

| Graph element | Maps to | Meaning |
|---|---|---|
| **Nodes (neurons)** | Agents | The *WHO* — processing units. |
| **Nodes (synapses)** | Skills | The *HOW* — functional connections. |
| **Agent ↔ Skill edges** | Which techniques a persona uses | Weighted by content similarity + Hebbian co-activation. |
| **Agent ↔ Agent edges** | Collaboration pathways | Which personas work well together. |
| **Skill ↔ Skill edges** | Skill clusters | Capability families that fire together. |

### How it is built

`generate_neural_map.py` reads every agent and skill file, vectorizes the text with TF-IDF (top terms per document), and computes cosine similarity across all pairs to produce the edges. It then layers **Hebbian-style learning** on top: agent↔skill edges that co-fire on *successful* tasks gain weight; stale edges decay exponentially (half-life ~69 days); failures subtract weight.

> **A note on the metaphor:** "Hebbian", "connectome", and "regeneration" are software primitives here, not biological claims. The closest ML analog to the edge-weight learning is *bandit reward priors over a static graph* — there is no NMDA-style coincidence detector. And the full graph rebuilds from scratch on every `ai-push` (a software convenience for index freshness), where real synapses remodel gradually. The biology *grounds* the design; it does not validate the math.

### What it is used for

| Use | How |
|---|---|
| **Agent selection** | Given a task, rank personas by cosine similarity to the task description. |
| **Skill loading** | Surface the top skills to load into context for the task. |
| **Gap detection** | Find isolated nodes — capabilities with no strong connections. |
| **Hub / "god node" detection** | Identify the highest-degree skills that many agents depend on. |
| **Cluster discovery** | Community detection groups related skills into families. |

The connectome is queried at the **Delegate** phase of every task. The full query mechanics — the three mandatory delegate questions, the scoring, the example output — live in [[The-4D-Paradigm]], and the lifecycle of the nodes it indexes lives in [[Skills-System]] and [[Agents-System]].

```bash
python3 ~/.claude/scripts/query_connectome.py query "deploy a Svelte app to Cloudflare Workers"
python3 ~/.claude/scripts/query_connectome.py gods 15        # top hub skills
python3 ~/.claude/scripts/query_connectome.py communities    # skill clusters
```

---

## 9. Why an octopus?

The architecture was not a metaphor applied after the fact. It emerged from studying how *Octopus vulgaris* actually solves the problem the operator faces: **one consciousness, many semi-autonomous limbs, no cross-contamination.**

### The biology

An octopus has roughly **500 million neurons** — and *two-thirds of them live in the arms, not the central brain.* Each arm can taste, smell, and execute local reflexes without consulting the brain; the brain sets high-level intent. Information flows **up** (arm discoveries reach the brain) and **down** (brain strategy reaches the arms). The central learning structure — the vertical lobe — performs a biological dimensionality reduction, converging millions of input cells onto far fewer output neurons.

### The software mapping

| Octopus biology | Framework architecture | What it does |
|---|---|---|
| Central brain | `~/.claude/` (this repo) | Shared rules, paradigms, agent personas, skills. |
| Arms | Client project repos | Isolated workspaces — each client is a sealed arm. |
| Neurons | Agent personas | Specialist processing units across 13 divisions. |
| Synapses | Skills | Reusable techniques that connect agents to capabilities. |
| Chemoreceptors (suckers) | `query_connectome.py` | TF-IDF cosine retrieval against the agent/skill corpus — *touch and know what it is*. |
| Afferent/efferent cycle | The 4D Paradigm | Sense → plan → act → evaluate, every signal in 4 phases. |
| Co-activation reinforcement | Hebbian-style edge weighting | Successful co-firings strengthen agent↔skill edges; stale ones decay. |
| Chromatophores | Dynamic agent loading | Personas loaded on demand, like real-time color-cell changes. |
| Arm autonomy *(with inter-arm comms)* | Arm isolation *(total)* | **A deliberate departure:** biology allows some peripheral inter-arm signaling; the framework enforces **total** sideways isolation for client-data security. |

The one place the software intentionally *breaks* with the biology is the most important one: real octopus arms have limited peripheral cross-talk; Octorato arms have **none**. That divergence is not an oversight — it is the multi-tenancy security boundary from [§7](#7-arm-isolation--the-cardinal-invariant).

### The two symbolic anchors

Two symbols sit behind the name **Octorato** (*octopus* + *tesseract*). Both are mathematical, neither is mystical.

- **The 8 → ∞.** An octopus has eight arms. Rotate the numeral **8** ninety degrees and it becomes **∞**, the lemniscate. The brain is built for an *unbounded* number of sealed arms — because it distributes only generic knowledge downward and arms never see each other. Multi-tenancy without a ceiling. *The 8 is symbolic; the ∞ is the engineering claim.*
- **The Tesseract → 4D.** The **4D Paradigm** — Describe → Delegate → Diligent → Disclose — is named *4D* on purpose. A tesseract is the 4-dimensional analog of a cube. The four phases are not sequential steps but **dimensions**, active simultaneously in every action: D1 (what) × D2 (who) × D3 (whether it works) × D4 (what it changes). To act inside the brain is to act in 4-space, and from there shape outcomes in 3-space — the codebase, the deliverable, the invoice. The 4D is not a workflow checklist; it is the control plane.

The intellectual lineage is math and biology, deliberately: **∞** from John Wallis (1655), **tesseract** from Charles Howard Hinton (1888), octopus distributed intelligence from van Giesen et al. (*Cell*, 2020) and Sumbre et al. (*Science*, 2001). Full naming rationale lives in the symbolism skill; the paradigm itself is detailed in [[The-4D-Paradigm]].

---

## 10. Wired or Corrupt: the self-enforcing constitution

Rules used to be prose the model could skip under load. RULE #1 ends that: every rule in `CLAUDE.md` must be wired to a live mechanism, registered in `registry/rules.yaml`. A rule with no registered, live mechanism is not a rule. It is rot, and a brain carrying it is CORRUPT.

`brain_doctor` is RULE #1's own mechanism. It reconciles the registry in **both directions**: every constitution rule has a mechanism, and every live hook has a rule (no orphans). One miss and the doctor exits non-zero, and `.githooks/pre-push` blocks the push. A documented-but-absent hook can no longer ship, which is how the original "phantom script" bug died.

"Wired" means covered, not mechanically forced. Model-behavior rules (tone, no-hallucination, identity) are backed by a registered detector or a presence-assert, and the Coverage Ledger prints the enforcement strength per rule, so coverage is never confused with force. Full design: [`wired-or-corrupt.md`](../architecture/wired-or-corrupt.md).

The same principle now covers the whole capability set. A generated manifest, [`docs/CAPABILITIES.md`](../CAPABILITIES.md), is the single source of the offering: every skill, agent, script, rule, and hook the brain holds, produced by `scripts/capability_manifest.py` and regenerated on every push. The pre-push gate that blocks an unwired rule also blocks a push whose manifest is stale, making regression-by-replacement impossible at the push boundary. Architecture: [`docs/architecture/v5-capability-manifest.md`](../architecture/v5-capability-manifest.md).

---

## See also

- [[The-4D-Paradigm]] — the nervous-system protocol; the Change Gate, the three delegate questions, and the Impact Radius scan.
- [[Skills-System]] — the *HOW* layer: synapse lifecycle, clusters, god nodes.
- [[Agents-System]] — the *WHO* layer: 13 divisions, personas, activation modes.
- [[Arms-and-Sync]] — the *FOR WHOM* layer: arm onboarding, isolation, multi-machine sync.
- [[Self-Growth]] — upward learning, auto-skill creation, the daily discovery loop.
- [`docs/architecture/hook-orchestration.md`](../architecture/hook-orchestration.md) — the reactive-control spec: ECA atoms, Behavior-Tree priority, Statechart 4D, Spreading-Activation recall, and Bandit tier-routing that wire the hooks into an autonomous reflex layer.
