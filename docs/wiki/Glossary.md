# Glossary

> Every Octorato concept and term in one place, A→Z. If a word on another wiki page is unfamiliar, decode it here; entries cross-link to the deeper page where one exists.

Octorato is an open-source AI-agent operating system. Its name fuses two ideas — *octopus* + *tesseract* — and that fusion runs all the way down through the architecture. Most of the vocabulary below falls into one of five families: **structure** (Brain, Arm, Company brain, CLASS/OBJECT/ARM), **flow** (4D Paradigm and its gates), **intelligence** (Connectome, Skills, Agents, Divisions), **money** (FinOps, Budget cap, Trace event), and **operations** (the sync scripts, the generic-safety guard, the self-growth loop).

---

## A

### Activation stack
The three layers that fire **simultaneously** on every task: **Agent** (WHO — persona/expertise), **Skill** (HOW — technique), and **Arm** (FOR WHOM — client context). A database audit, for example, activates the *Database Optimizer* agent, loads the `explain-analyze-validation` skill, and operates inside one client's arm — never blending into another. See [[The-4D-Paradigm|4D Paradigm]] and [[Agents]].

### Agent (persona)
A specialist AI persona — the **neuron** of the brain. Each agent is a full persona file under `~/.claude/agents/<division>/<name>.md` with expertise, voice, and cross-references. There are <!--canon:agents.count-->160+<!--/canon--> agents across 13 [[Agents]] divisions. Agents are *WHO* does the work; they inherit all brain rules (4D, security, arm isolation) and complement — never replace — [[Skills]]. See [[Agents]].

### ai-pull
Sync script (in `~/.local/bin/`) that pulls the latest brain from the `octorato` GitHub remote into `~/.claude/` on any workstation, then runs `sync-ai-docs` to refresh arm config. `ai-pull --status` checks for available updates without applying them. The "absorb" half of multi-machine sync; see also [[#ai-push]] and [[#sync-ai-docs]].

### ai-push
Sync script that commits and pushes all `~/.claude/` changes to GitHub, regenerates the [[#Connectome (neural_map.json)]], and syncs every arm. It runs [[#check-generic]] first as a safety gate. The "broadcast" half of multi-machine sync. Usage: `ai-push "feat(brain): add new skill"`.

### Arm
An **isolated client project** — one sealed repo per client, living outside the brain (e.g. `~/projects/<client>/`). Each arm carries its own `.claude/CLAUDE.md` as its single source of truth and its own sealed **[[#Arm memory]]** repo for client-specific knowledge. Arms are the *PROPERTIES* in the [[#CLASS / OBJECT / ARM]] model and the *WHERE* (FOR WHOM) in the [[#Activation stack]]. Named for the octopus's eight semi-autonomous arms, two-thirds of whose neurons live in the limb, not the central brain — most operational knowledge is arm-local.

### Arm isolation
The framework's hardest invariant: **an arm never knows another arm exists.** No client data, names, or credentials ever flow arm→arm. The brain sees each arm's cost data but the arms never see each other. This is a *deliberate departure from the biology* — real octopus arms have some peripheral cross-talk; Octorato enforces total sideways isolation for client-data security. Marketed as "air-gapped arms" (software-level isolation between workspaces).

### Arm memory
Per-arm, client-specific knowledge — facts, conventions, and context that belong to one arm only. Stored in that arm's own **private** repo (loaded via symlink into the arm; never synced to the central brain or to another arm). A lesson that would help other arms is distilled up to the central brain as a generic skill — see [[#Upward learning]]. See [[#Two-tier memory]] and `docs/architecture/memory-model.md`.

### Arm onboarding
The procedure for creating a new client arm: scaffold `.claude/CLAUDE.md` (source of truth), `.github/copilot-instructions.md` + `.cursorrules` (auto-synced via [[#sync-ai-docs]]), `README.md`, and a `.gitignore` that **must** include `.env`, `.env.*`, and `.dev.vars`. Full step-by-step lives in `skills/arm-onboarding/SKILL.md`.

---

## B

### Brain
The shared, open-source core: `~/.claude/` itself — *which IS the `octorato` repo*. It holds the rules (`CLAUDE.md`), the [[Skills]] (HOW), the [[Agents]] (WHO), the [[#Connectome (neural_map.json)]], the enforcement scripts, and templates. It is the **CLASS** (the DNA) in the [[#CLASS / OBJECT / ARM]] model and the central brain in the octopus metaphor: sets high-level intent, distributes generic knowledge down to arms. Octorato runs **1 + N brains** (applying the [[#8→∞ (lemniscate)]] anchor): one central brain here, plus one sealed [[#Arm memory]] brain per arm, N unbounded. It is *not* anyone's identity, client list, or credentials — those live in the [[#Company brain]].

### Brain memory
Cross-arm, generic knowledge held in the central brain: distilled lessons, operator identity, framework rules. Lives in a **private standalone repo** owned by the brain (separate from the public `octorato` repo and from any arm repo); the public framework ships only the mechanism, never the content. Loaded into `~/.claude/` at runtime. See [[#Two-tier memory]] and `docs/architecture/memory-model.md`.

### Brain stays generic
See [[#Generic-safety / "brain stays generic"]].

### Budget cap
A per-arm spending ceiling defined in `budgets.yaml`. `budget-check.py` computes month-to-date spend per arm and **exits with code 2 when the cap is burned through**. Wired into a `PreToolUse` hook so it can actually *halt* Agent / subagent / browser tool calls — not just warn. This "budget cap that halts agents" is one of Octorato's three FinOps differentiators. See [[#FinOps]] and `skills/finops-budget-policy/SKILL.md`.

---

## C

### check-generic
`scripts/check-generic.py` — the commit-time guard. It scans staged files **and the commit message** against the private (gitignored) `company/brain-blocklist.txt` and hard-blocks any commit that would leak an arm code, client name, internal URL, or token. Also rejects [[#SDD]] artifacts at the brain root. Called by [[#ai-push]] before committing; soft-fails only when the blocklist is absent. See [[#Generic-safety / "brain stays generic"]].

### CLASS / OBJECT / ARM
The object-oriented inheritance model of the framework:
- **CLASS** = the [[#Brain]] (`~/.claude/`, open-source, the DNA — paradigms, agents, skills, scripts).
- **OBJECT** = your [[#Company brain]] (`~/.claude/company/`, gitignored — your identity, your arm definitions).
- **ARM** = the client projects themselves (isolated repos, each with its own `CLAUDE.md`).

The CLASS *instantiates* into your OBJECT, which *manages* the ARMS. Generic knowledge inherits downward; nothing private leaks upward into the public CLASS.

### Company brain
Your **private instance** of the framework: `~/.claude/company/`, gitignored so it never reaches the public repo. It holds professional identity (name, rates, CV), arm definitions (which clients, which codes), company-specific skills, voice style, and connection configs. The **OBJECT** in [[#CLASS / OBJECT / ARM]]. Build one from `templates/company/`.

### Connectome (neural_map.json)
The brain's **weighted knowledge graph** — `~/.claude/neural_map.json`, auto-generated by `scripts/generate_neural_map.py` on every [[#ai-push]] (never hand-edited). It reads the *full content* of every agent and skill, vectorizes with TF-IDF, and computes cosine similarity across all pairs to produce Agent↔Skill, Agent↔Agent, and Skill↔Skill edges. Queried via `query_connectome.py` (the "suction cups") during 2D [[#Delegate]] to find the right specialist. Also carries [[#Hebbian learning]] weights. See [[#Cost-spike watchdog]] for an analytics consumer of the same substrate.

### Cost-spike watchdog
`scripts/watchdog.py` — a FinOps anomaly detector. It computes a **z-score over tokens/day per skill·arm against a 30-day baseline** and flags spikes (with a 100k-token floor to suppress noise). Run on a daily cron with `--execute`. The cliff/quality-drop sibling of the budget cap: budget caps *stop* spend, the watchdog *alerts* on abnormal spend. See [[#Trace event]] and [[#FinOps]].

---

## D

### Delegate
The **2D phase** of the [[#4D Paradigm]] (afferent — "who can solve this, what's the plan?"). Before any work, the agent answers three mandatory questions: **Q1 ¿Quién sabe?** (graph search via `query_connectome.py`), **Q2 ¿Tiene API?** (MCP-first capability check: MCP > REST > SDK > scraping), **Q3 ¿Quién lo hace?** (rule match via [[#Delegate-check]]). The combined verdict is ACTIVATE / LOAD / SELF.

### Delegate-check
`scripts/delegate-check` — the Q3 tool of 2D [[#Delegate]]. It parses `agents/REGISTRY.md` triggers and skill descriptions to rule-match a task to agents and skills, outputting **ACTIVATE** (agent + skills + persona), **LOAD** (skills only), or **SELF** (proceed on general knowledge — only when Q1 and Q3 both find no strong match).

### Describe
The **1D phase** of the [[#4D Paradigm]] (afferent). The agent states *what* it will do and *why* before acting — task type, scope, files involved. No silent changes. "I will do X because Y."

### Diligent
The **3D phase** of the [[#4D Paradigm]] (efferent — motor signal going out). After acting, the agent **validates with evidence**: build, lint, test, render, grep, or query result — whatever fits the task type. No task is "done" without a PASS/FAIL report. A failure here subtracts the agent↔skill edge weight in the connectome (see [[#Hebbian learning]]).

### Disclose
The **4D phase** of the [[#4D Paradigm]] (efferent). The agent reports side effects and runs an **Impact Radius** scan: where else is the changed object referenced, who produces it, who consumes it downstream, what becomes orphaned. "No object is an island. Every change radiates."

### Division
One of the **13 specialist groupings** of agents: Engineering, Design, Marketing, Sales, Product, Project Management, Testing, Support, Specialized, Spatial Computing, Game Development, Academic, and Paid Media. Full taxonomy and auto-activation triggers live in `agents/REGISTRY.md`. See [[Agents]].

### Downward distribution
The flow of **generic** brain knowledge (rules, paradigms, skills, identity) *down* to all arms via [[#sync-ai-docs]] and [[#ai-pull]]. Its counterpart is [[#Upward learning]]. Other arms' data never flows down to an arm. One of the four Core Principles in `CLAUDE.md`.

---

## F

### FinOps
**Financial Operations for AI agents** — Octorato's commercial wedge. Three capabilities that observability tools (LangSmith, Datadog) lack: **per-arm cost attribution** (every [[#Trace event]] tags the client), **air-gapped multi-tenancy** ([[#Arm isolation]]), and **[[#Budget cap]]s that actually halt agents**. The pipeline tags every trace with the client who incurred it, rolls up USD per project/month/skill via a shared `_pricing.py` table, and reconciles estimated vs. billed cost against the Anthropic Enterprise Analytics API. Built so consultants can bill clients fairly per token.

### 4D Gate
The **Change Gate** — the synapse between the afferent and efferent halves of the [[#4D Paradigm]]. Before the first file create/modify/delete in any response, the agent runs an Impact Radius scan, assembles a **Change Manifest** (a table of every file it will touch + reason), presents it, and **waits for explicit human confirmation** ("yes/sí/dale/ok") before executing. Like `terraform plan` before `terraform apply`. Enforced by `scripts/gate-check`. Read-only ops and "hazlo directo" are exceptions.

### 4D Paradigm
The framework's **nervous system protocol** — every signal (brain↔arm↔agent↔human) follows four phases: **[[#Describe]] → [[#Delegate]] → [[#Diligent]] → [[#Disclose]]**. The first two are *afferent* (sensory, before acting); the last two are *efferent* (motor, after acting); the [[#4D Gate]] sits between them. Named "4D" after the **tesseract** (the 4-dimensional analog of a cube): the four phases are not sequential steps but *dimensions* active simultaneously in every action — the control plane, not a checklist. Full protocol in `skills/4d-paradigm-protocol/SKILL.md`.

### 4D+S
**4D + Spec-Driven Development.** For tasks above trivial complexity, the 4D Paradigm integrates with an [[#SDD]] workflow, scaled by a complexity score: **0–2 TRIVIAL** (4D only), **3–5 MEDIUM** (4D + `plan.md`), **6+ LARGE** (4D + full SDD: `feature.md` → `plan.md` → implement → `review.md` → archive). Orchestrated by the `4d-spec` skill. Signals raise the score: +2 for touching 4–10 files, +4 for 10+, +3 for an architecture decision, +5 if the user requests a spec.

---

## G

### Generic-safety / "brain stays generic"
The non-negotiable rule that the public brain **never** records anything client-specific — across every git surface (commits, branches, tags, PR text, filenames, file contents). Lessons from an arm are distilled into anonymized generic skills *before* they enter the brain (see [[#Upward learning]]). Enforced in two layers: commit-time [[#check-generic]] and push-time [[#githooks pre-push]]. The consequence of the brain being open-source: every diff is publicly visible on GitHub forever.

### githooks pre-push
`.githooks/pre-push` — the **push-time** generic-safety layer. It scans every commit being pushed against `.githooks/push-policy.txt` (universal path + secret patterns) and, when present, layers `company/brain-blocklist.txt` on top. Always runs, no soft-fail. Enable on a fresh clone with `git config core.hooksPath .githooks`. Added after a blunt remote-URL guardrail was found to block legitimate generic contributions while not actually inspecting content. Complements commit-time [[#check-generic]].

---

## H

### Harmonization (ADD / MERGE / REPLACE / EXTEND)
The discipline applied to new knowledge in the [[#Self-growth loop]]: **the brain is a connected graph, not a pile of skills.** Each discovered candidate is tagged with an integration *action* — `ADD` (net-new skill), `MERGE-WITH` (fold into an existing one), `REPLACE` (supersede a weaker skill), `EXTEND` (augment one), or `SKIP`. Only net-new `ADD` candidates auto-apply; structural MERGE/REPLACE/EXTEND are left for human review. The point is *harmonization, not accretion*.

### Hebbian learning
The connectome's reinforcement mechanism (inspired by Hebb's principle — *not* biological LTP). When an agent and skill **co-fire on a successful task** (3D [[#Diligent]] PASS), their edge weight is boosted; failures subtract; unused boosts decay with a **~69-day half-life**. Closest ML analog: bandit reward priors over a static graph. Stored in `company/neural_activity.json`, updated from [[#Trace event]]s by `update_neural_activity.py`.

### HISTORY ledger
`knowledge/github-trending/HISTORY.md` — the single append-only audit ledger of the [[#Self-growth loop]]. Every day's decisions are recorded: items **added**, **deferred**, and **ignored-with-reason**. The operator audits the ledger on their own cadence rather than gatekeeping every candidate — the AI-tooling landscape moves faster than any one person can review.

---

## O

### Octopus (the biology)
The architectural inspiration, not a forced metaphor. *Octopus vulgaris* has ~500M neurons with **two-thirds distributed in the arms**, each arm operating with high local autonomy. That solves the exact problem Octorato faces — *one consciousness, many workspaces, no cross-contamination*. The central brain sets intent; arms execute with local intelligence; information flows up and down. Software borrows the vocabulary (brain, arms, neurons=agents, synapses=skills, suction-cups=connectome query) as a *design analogy*, flagging every point where the mapping departs from real biology (e.g. total [[#Arm isolation]] vs. the octopus's peripheral cross-talk).

### Octorato
The framework itself: an **open-source AI-agent operating system with built-in [[#FinOps]]**, where one human operator directs a shared [[#Brain]] of specialist [[#Agents]] across clients and machines without mixing their data or bills. The name = **octopus + tesseract** — an eight-armed brain operating in a 4D activation space (Agent × Skill × Arm × 4D-phase). `~/.claude/` *is* the `octorato` repo (`github.com/CarlosCaPe/octorato`); it is also a product brand on dataqbs.com. See [[#8→∞ (lemniscate)]] and [[#Tesseract]].

---

## Q

### QueryMaster
The brain's **multi-engine database CLI** — `qm -e <engine> -c <conn> "<query>" [--execute]`. Dry-run by default (live execution needs `--execute`). Supported engines: PostgreSQL, Snowflake, SQL Server, ADX (KQL), SQLite, Databricks. Connections are registered in `~/.config/querymaster/connections.json` with **no passwords**. Per-engine best practices live in the `querymaster-*` skill cluster — load the master skill plus the engine-specific one before generating a query.

---

## S

### Self-growth loop
The daily routine by which **the brain grows itself**. A scheduled loop scans GitHub Trending, Hacker News, and Product Hunt for new tools, runs each candidate through a deterministic brain-fit classifier plus an LLM quality gate, [[#Harmonization (ADD / MERGE / REPLACE / EXTEND)|harmonizes]] it against the existing connectome, and **auto-promotes** survivors into real [[Skills]] — then publishes what it learned. Discovery lives in the `github-trending-curation` skill; promotion via [[#trending-promote]]; the audit trail in the [[#HISTORY ledger]].

### Skill
A reusable **technique** — the **synapse** of the brain. Stored as `~/.claude/skills/<name>/SKILL.md` with YAML frontmatter (`name:` + `description:` = the trigger). Skills are *HOW* work gets done: loaded on demand when 2D [[#Delegate]] matches them (semantic Q1 + rule Q3), then reinforced or decayed by [[#Hebbian learning]]. One skill connects N agents to one capability. They are born from arms ([[#Upward learning]]), can be pruned when stale, and cluster into families (e.g. `querymaster-*`, `sdd-*`). See [[Skills]].

### Skill-creator
The skill (`skills/skill-creator/SKILL.md`) that governs **how new skills are authored** — directory structure, SKILL.md format, and the *Auto-Skill Creation Protocol*: when a pattern appears **3+ times** in an arm, it gets distilled (anonymized) into a generic skill. Also carries the self-improvement / lessons-learned protocol triggered on errors.

### sync-ai-docs
The sync script that propagates one arm's `.claude/CLAUDE.md` into the tool-specific config files — `.github/copilot-instructions.md` (Copilot) and `.cursorrules` (Cursor) — so **one source of truth keeps three AI tools in sync**. Run `sync-ai-docs` for all arms or `sync-ai-docs <arm>` for one. Called automatically by [[#ai-push]] and [[#ai-pull]]. Part of the "glial layer" — infrastructure that doesn't fire signals but keeps the neurons alive.

### SDD
**Spec-Driven Development** — a phased implementation pipeline (`feature.md` → `plan.md` → implement → `review.md` → archive) handled by the `sdd-*` skill cluster and activated by [[#4D+S]] on larger tasks. Archived specs in `docs/specs-archive/` become institutional memory. **SDD artifacts (`feature*.md`, `plan*.md`, `spec*.md`) must never sit at the brain root** — even client-free, they leak roadmap; [[#check-generic]] rejects them there.

---

## T

### Tesseract
The 4-dimensional analog of a cube (a hypercube) — the second symbol behind the name *Octorato* and the namesake of the [[#4D Paradigm]]. The point: the four phases (Describe/Delegate/Diligent/Disclose) are **dimensions active simultaneously**, not sequential steps. To act inside the brain is to act in 4-space and from there shape 3-space outcomes: the codebase, the deliverable, the invoice. Intellectual lineage: Charles Howard Hinton, *A New Era of Thought* (1888) — *not* the Marvel artifact. See `skills/octorato-symbolism/SKILL.md`.

### Two-tier memory
The memory architecture Octorato uses across its **1 + N brains**: a **central tier** ([[#Brain memory]] — generic, cross-arm lessons + operator identity, in a private brain-owned repo) and an **arm tier** ([[#Arm memory]] — client-specific facts, sealed in each arm's own private repo). Knowledge flows up (arm lesson → distilled generic skill → central brain) but never sideways (arm → arm). The public framework ships the mechanism; both tiers' content stays private. See `docs/architecture/memory-model.md`.

### Trace event
The atomic unit of [[#FinOps]] and observability — a structured JSONL record appended to `~/.claude/traces/YYYY-MM-DD.jsonl` (gitignored, 30-day retention) by `trace-hook.py`. Three classes: `skill_fire`, `agent_activate`, and `phase_boundary` (one of the six 4D phases). Each shares a strict schema with `task_id`, `ts` (ISO 8601 UTC), **`arm`** (auto-derived from CWD — this is what enables per-client cost attribution), `status`, and optional token usage. Read by the cost profiler, [[#Cost-spike watchdog]], SLOs, and the Hebbian updater.

### trending-promote
The slash command (`/trending-promote <date> <repo>`) that **promotes a discovered candidate into a real skill** in one shot — and, as a deliberate carve-out, also auto-publishes a news article (crediting the source repo) and a social post. The single exception to the brain's otherwise pull-model curation. Part of the [[#Self-growth loop]].

---

## U

### Upward learning
The flow of **arm-discovered patterns** *up* into the brain — but only after they are distilled into **generic, anonymized skills** (no client names, data, or credentials). The cycle: arm discovers a pattern → human approves capture → brain stores it as an anonymized skill → [[#Downward distribution]] sends it to all arms. The human is the **only** gateway; the AI never bridges arms autonomously. Counterpart to downward distribution.

---

## Numerals & Symbols

### 8→∞ (lemniscate)
The first symbol behind *Octorato*. An octopus has eight arms; rotate the numeral **8** ninety degrees and it becomes **∞**, the lemniscate (the symbol for the unbounded). The framework is built for an *unbounded* number of sealed arms because the brain distributes only generic knowledge downward and arms never see each other — **multi-tenancy without ceiling**. The 8 is symbolic; the ∞ is the engineering claim. Lineage: John Wallis, *De sectionibus conicis* (1655). See `skills/octorato-symbolism/SKILL.md` and [[#Arm isolation]].

---

*See also: [[Home]] · [[Agents]] · [[Skills]] · [[The-4D-Paradigm|4D Paradigm]]. Term missing? The brain stays generic — if a concept here ever referenced a real client, that would be a [[#Generic-safety / "brain stays generic"|generic-safety]] violation.*
