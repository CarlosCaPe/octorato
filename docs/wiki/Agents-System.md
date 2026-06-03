# Agents System

> **Organ:** neurons — specialist personas that supply the WHO, firing when the connectome routes a task to their domain.

The **agent layer** is Octorato's roster of specialist personas. Where a [[Skills-System|skill]] answers *how* a task is done, an agent answers *who* does it. This page explains how that distinction works, how agents are activated, the rules they inherit, and how to add a new one. For the full agent roster (<!--canon:agents.count-->160+<!--/canon--> personas across the divisions), see [[Agents]].

---

## The Three Axes: WHO / HOW / FOR WHOM

Octorato separates three concerns that other agent frameworks routinely collapse into one. Keeping them orthogonal is what lets the same technique serve many roles and the same role serve many clients without cross-contamination.

| Axis | Layer | Lives in | Answers | Example |
|------|-------|----------|---------|---------|
| **WHO** | Agent / persona | `~/.claude/agents/` | What role, judgment, and priorities are in play? | *Database Optimizer* |
| **HOW** | Skill | `~/.claude/skills/` | What is the concrete technique or procedure? | `explain-analyze-validation` |
| **FOR WHOM** | Arm | `<CLIENT>/.claude/` | What client context, data, and constraints apply? | a sealed client repo |

The **activation stack** assembles these top-down:

```
Brain  →  AGENT (persona / WHO)  →  SKILLS (technique / HOW)  →  ARM (client context / FOR WHOM)
```

A persona without a technique is opinion without execution; a technique without a persona is a tool with no hand on it. Octorato insists on both, scoped to exactly one arm at a time.

### Agents complement skills — they never replace them

An agent is **not** a bundle of code. It is a role definition: domain priorities, a point of view, a quality bar, and the judgment to choose among techniques. The actual *doing* still flows through skills.

- An agent **decides** that a slow query needs an index and that the index must ship without locking the table.
- A skill (`index-creation-concurrently`) **carries out** the `CREATE INDEX CONCURRENTLY` procedure correctly, edge cases and all.

Remove the agent and the skill still runs — you just lose the judgment about *whether* and *when*. Remove the skill and the agent still reasons — it just has no validated procedure to lean on and may improvise. The two are designed to be loaded together, which is exactly what the activation protocol does.

> **Mental model:** the agent is the senior engineer in the room; the skills are the runbooks on the shelf; the arm is the client whose system is on the screen. Octorato is the team lead that puts the right person, the right runbook, and the right client together for the task in front of it.

---

## The Divisions

The registry (`~/.claude/agents/REGISTRY.md`) organizes personas into **13 divisions that contain agents**, plus **2 reference directories** that hold orchestration material rather than individual personas — 15 top-level groupings in all. Each line below is the division's scope in one sentence.

### Divisions with agents (13)

| # | Division | Scope (one line) |
|---|----------|------------------|
| 1 | **Academic** | Research-grade analysis across anthropology, geography, history, narratology, and psychology. |
| 2 | **Design** | Brand, UI, UX architecture and research, visual storytelling, inclusive and delightful interfaces. |
| 3 | **Engineering** | The largest division — backend/frontend/mobile build, data, security, SRE, DevOps, firmware, smart contracts, and docs. |
| 4 | **Game Development** | Engine-specific build for Unity, Unreal, Godot, Roblox, and Blender — design, scripting, shaders, multiplayer, audio. |
| 5 | **Marketing** | Content, SEO/AEO, and platform strategy across Western and Chinese social/commerce ecosystems. |
| 6 | **Paid Media** | Paid-acquisition specialists — PPC, paid social, programmatic, creative, tracking, and account audits. |
| 7 | **Product** | Product management, roadmap and sprint prioritization, feedback synthesis, trend and behavioral research. |
| 8 | **Project Management** | Delivery orchestration — specs-to-tasks, scope, cross-functional coordination, studio operations and production. |
| 9 | **Sales** | Full B2B motion — outbound, discovery, deal strategy, sales engineering, proposals, pipeline, and coaching. |
| 10 | **Spatial Computing** | XR / visionOS / macOS-Metal immersive interfaces, spatial interaction, and terminal integration. |
| 11 | **Specialized** | Cross-domain experts — compliance, MCP building, Salesforce, civil engineering, identity graphs, payments, and more. |
| 12 | **Support** | Analytics reporting, executive summaries, finance tracking, infra maintenance, legal compliance, customer support. |
| 13 | **Testing** | Quality gates — accessibility, API, performance, evidence collection, reality checks, and workflow optimization. |

### Reference directories (2)

| # | Directory | Holds |
|---|-----------|-------|
| 14 | **Strategy** | Multi-agent orchestration docs, phase playbooks, and scenario runbooks (the NEXUS coordination material) — not individual agents. |
| 15 | **Examples** | End-to-end workflow walkthroughs (book chapter, landing page, startup MVP, memory-enabled flows) — not individual agents. |

The per-agent breakdown, emoji, file paths, and trigger keywords for every persona live in [[Agents]].

---

## Activation Protocol

There are three ways a persona comes online. All three converge on the same end state: **persona + relevant skills, scoped to the active arm.**

### 1. Automatic (brain-triggered)

The brain reads the registry and activates the best-fit agent on its own when any of these hold:

1. A task **matches an agent's trigger keywords** (each registry row carries a trigger list, e.g. *"schema design, query optimization, indexing, PostgreSQL"* for the Database Optimizer).
2. The agent's **expertise is needed for the current arm's work**.
3. **Multi-step work requires a specialist handoff** mid-flow.

This is wired into the **2D Delegate Gate** that fires at the start of every non-trivial task:

| Q | Question | Tool |
|---|----------|------|
| Q1 | ¿Quién sabe? (graph search) | `query_connectome.py query "<task>"` |
| Q3 | ¿Quién lo hace? (rule match) | `delegate-check "<task>"` |

The combined verdict is one of:

- **ACTIVATE** — load the agent persona **plus** its skills **plus** apply the arm context.
- **LOAD** — skills only; no specialist persona warranted.
- **SELF** — general knowledge; chosen only when Q1 *and* Q3 both return no strong match.

### 2. Manual

The operator can name a persona directly:

```
Activate Database Optimizer for this task
Use Security Engineer mode
```

Manual activation overrides the automatic verdict — useful when you want a specific lens applied even if the keywords didn't trip.

### 3. Combined with skills (always)

Activation is never "persona alone." When an agent comes online it pulls in the skills relevant to the active arm. The registry maintains an explicit **Agent ↔ Skills cross-reference** so this binding is deterministic rather than guessed. For example:

- Brain activates the **Database Optimizer** persona.
- Persona loads `explain-analyze-validation`, `index-creation-concurrently`, `autovacuum-bloat-management`, and related skills.
- The arm supplies the client-specific schema, connection, and constraints.
- **Result:** specialist judgment + validated technique + the right client context — assembled for this one task.

---

## Inherited Rules: Every Agent Obeys the Brain

A persona is a *lens*, not an escape hatch. Activating an agent **never** relaxes a single brain rule. Every agent inherits the full constraint set from `~/.claude/CLAUDE.md`:

- **The 4D Paradigm** — Describe → Delegate → Diligent → Disclose governs every action an agent takes. An activated persona still presents a Change Manifest at the 4D Gate before writing files, still validates output at the 3D Diligent Gate, and still discloses its Impact Radius. The persona changes *what* gets prioritized, never *whether* the gates fire.
- **Security (non-negotiable)** — no secrets committed, no user secrets echoed back, inputs sanitized. A persona cannot opt out of this.
- **Arm Isolation (mandatory)** — and this is the hard wall.

### Arm isolation: an agent never sees another arm's data

The single most important inherited rule. An agent operating inside one arm **cannot read, reference, or carry data from any other arm** — an arm does not even know other arms exist. Personas are generic by construction (see *Adding an Agent* below) precisely so the same *Database Optimizer* can serve every arm without becoming a bridge between them. Only the human operator moves knowledge across arms, and only deliberately; the agent never does it autonomously. The full information-flow contract lives in [[Architecture]] (§5) and [[Security]] (§4).

---

## The Connectome's Role in Selection

The **connectome** (`~/.claude/neural_map.json`) is the brain's TF-IDF + cosine-similarity graph over every skill and agent — see [[Architecture]] (§8) for how it is built and maintained.

In agent selection it powers **Q1 of the 2D Delegate Gate** (`query_connectome.py query "<task>"`): the task description is vectorized and scored against the graph to surface the *closest* personas and skills by semantic similarity, not just literal keyword hits. This catches the cases where a task's wording doesn't match a trigger list verbatim but is conceptually adjacent to a persona's domain.

Beyond per-task selection, the connectome also drives:

- **Skill loading** — once a persona is chosen, the graph helps pull the most-related skills for it.
- **Gap detection** — clusters with weak coverage flag where the roster (or skill set) is thin and a new persona or skill might be warranted.

Together with `delegate-check` (the deterministic rule match in Q3), the connectome gives selection two independent signals — semantic similarity and explicit rules — that must agree before the brain commits to **ACTIVATE**.

---

## Adding a New Agent Persona

Agents live in the public, open-source brain. The cardinal rule therefore applies: **a persona must be 100% generic — no client data, no client names, no internal codenames, no ticket IDs, nothing the [[Architecture|brain-stays-generic]] policy forbids.** If a need arose from a specific client engagement, distill it to its generic professional essence *before* it enters the brain.

Steps:

1. **Confirm the gap is real.** Run the task through the connectome (`query_connectome.py`) and skim [[Agents]]. If an existing persona already covers it, extend that one rather than adding a near-duplicate.
2. **Pick the division.** Place the persona under the right division directory in `~/.claude/agents/<division>/`. Use the existing file-naming convention (`<division>-<role>.md`).
3. **Write the persona file (generic).** Define the role's mission, judgment, priorities, quality bar, and communication style — the way the *Studio Producer* or *Database Optimizer* files read. Describe the *role*, never a specific client's situation.
4. **Register it in `REGISTRY.md`.** Add a row to the division's table with: emoji, agent name, file link, and a focused **trigger keyword list**. The triggers are what the automatic activation path keys on — make them specific and non-overlapping.
5. **Cross-reference complementary skills.** If the persona pairs naturally with existing skills, add it to the *Agents ↔ Existing Skills* table so combined activation is deterministic. If no skill fits, that's a signal a new skill may be warranted (see [[Skills-System]]).
6. **Update the statistics block** (totals + per-division count) at the foot of the registry.
7. **`ai-push`.** This regenerates the connectome so the new persona becomes discoverable by Q1 semantic search, and runs the generic-content guardrails (`check-generic.py` at commit-time, `pre-push` at push-time). A blocklist hit blocks the commit — no exceptions.

Once pushed, the persona is immediately live: the next matching task will surface it automatically, or the operator can summon it by name.

---

## See Also

- [[Agents]] — the full roster: every persona, division-by-division, with emoji, file paths, and trigger keywords.
- [[Skills-System]] — how the *HOW* layer works, and how skills bind to personas.
- [[Architecture]] — the octopus model, the layers, arm isolation, and the brain-stays-generic policy that personas inherit.
