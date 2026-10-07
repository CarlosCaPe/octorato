# Octorato — FAQ

Plain answers to the questions people (and the AI agents that read this repo) actually ask.

## What is Octorato?

A folder of plain-text files that gives your AI coding assistant a lasting memory, house rules, and a receipt for everything it does. In its own vocabulary: an **open-source AI agent operating system**, one file-native "brain" (rules, 240+ skills, 160+ specialist agents, memory, all markdown under git) that one operator runs across many sealed client "arms", with per-client cost attribution (an estimate from local logs at list price) and budget halts that arm once you write a `budgets.yaml`. MIT licensed.

## Are the agents people?

No. An "agent" in Octorato is a text file that describes a role (a code reviewer, a data engineer, a copywriter), the way a job description does. The AI assistant reads the card and works in that role. There are no humans inside the system, and Octorato itself is a tool that never pretends to be a person: it answers from sources and signs every answer with a receipt.

## Do I need to be a programmer to use it?

No. If you can edit a text file and run three commands in a terminal, you can install it and write your own rules. Programming helps if you want to add hooks (automatic checks) or contribute scripts.

## What is an "AI agent operating system"?

A persistent, portable layer that holds an agent's *self* — its rules, skills, identity, and memory — independent of any vendor runtime. In Octorato that self is plain text under version control, so it can be read, diffed, forked, moved between machines, and audited. The agent is grown by use rather than configured in code.

## What does "one brain, many arms" mean?

It's the octopus model: one **brain** (the shared self) and many **arms** (sealed deployments, one per client). The brain pushes generic knowledge down to the arms; the arms send anonymized lessons back up. Like an octopus, most of the work happens in the arms, not the head.

## What is "arm isolation"?

Software-level isolation between client workspaces: **an arm never knows another arm exists.** No client's data, names, or secrets ever flow between arms — the only bridge is the human operator. Isolation is enforced at git commit and at push, before anything leaves the body. This is what makes one brain safe to run across competing clients.

## How is Octorato different from CrewAI, LangGraph, or AutoGen?

Those are excellent **Python agent-runtime frameworks**: you define agents and graphs in code, and they execute inside that runtime. Octorato is a different layer — the agent's *self as files*, runtime-agnostic (it runs on Claude Code today). Its defensible differences are **multi-tenant arm isolation** and **built-in per-client FinOps/token attribution**, which runtime frameworks do not target. Honest trade-off: CrewAI/LangGraph have far larger communities and own in-process orchestration; Octorato owns portability, isolation, and cost governance.

## How is it different from Octopoda-OS or other "memory OS" projects?

Memory-OS projects focus on giving an agent durable memory. Octorato's scope is broader and operator-centric: not just memory, but the whole self (rules + skills + agents + memory) as files, plus multi-client isolation and FinOps governance for someone serving many principals.

## Is Octorato free and open source?

Yes — MIT licensed, public on GitHub. You can read, fork, and self-host the entire brain.

## What is the "4D paradigm"?

Every action follows four phases: **Describe** (state what and why), **Delegate** (search/verify before generating), **Diligent** (validate output with evidence), **Disclose** (state side effects and impact). It is the nervous system that makes each action describable, delegated, verified, and disclosed.

## What stops a rule from being just ignored prose?

**RULE #1: every rule must be wired, or the brain is corrupt.** A rule counts as real only when `registry/rules.yaml` maps it to a live mechanism (a hook, a gate, a detector). `brain_doctor` checks this in both directions: every rule in the constitution has a mechanism, and every live hook has a rule. If one is missing, the doctor declares the brain corrupt and the pre-push hook blocks the push. No force, no exception, no soft-fail. So a rule cannot quietly decay into advisory prose the model skips under load. Model-behavior rules (tone, no-hallucination, identity) are still registered, backed by a detector or a presence-assert. Full design: [`docs/architecture/wired-or-corrupt.md`](docs/architecture/wired-or-corrupt.md).

The same principle extends to the whole capability set. A generated manifest, [`docs/CAPABILITIES.md`](docs/CAPABILITIES.md), lists every skill, agent, script, rule, and hook the brain holds. It is produced by `scripts/capability_manifest.py` and regenerated on every push. The pre-push gate blocks a push whose manifest is stale, so a capability cannot be silently dropped from the offering by a later change. Architecture: [`docs/architecture/v5-capability-manifest.md`](docs/architecture/v5-capability-manifest.md).

## What is v10, "Low Friction, Easy Entry"?

Work in progress since October 2026. Most of it is merged on master, and v10.0.0 is not released yet (the latest tag is <!--canon:v10.latest_tag-->v9.13.1<!--/canon-->). It keeps every check from v7 to v9 and makes them cheaper to live with. Install is the clone plus one command, `python3 ~/.claude/scripts/quickstart.py`, which wires the checks, turns on the push guard and writes a first spec (about <!--canon:v10.quickstart.measured-->21 s<!--/canon--> on a clean clone; a CI job fails past <!--canon:v10.quickstart.ci_budget-->5 minutes<!--/canon-->). The checks now count their own refusals: `octo friction` shows per check how often it said no and how long it took, and a replay of <!--canon:v10.replay.cases-->1,654<!--/canon--> real past cases blocks a change that drops a refusal that was right. `octo dash` writes one offline HTML page of specs, reviews, the gate receipt and live runs, and a status line shows the short form. The house rules (`CLAUDE.md`) went from <!--canon:v10.constitution.tokens_before-->24,000<!--/canon--> to <!--canon:v10.constitution.tokens_after-->11,920<!--/canon--> tokens, and the health check fails them above <!--canon:v10.constitution.ceiling-->12,000<!--/canon-->.

What is not done: the goal-anchor check (AC-10) should block at most <!--canon:v10.goal_anchor.target-->25%<!--/canon--> of its old count and measures <!--canon:v10.goal_anchor.measured-->42%<!--/canon--> on a replay that cannot reproduce its own history well, so live data is being collected. The budget check answers in <!--canon:v10.budget.spawn_after-->73 to 254 ms<!--/canon--> from a warm cache, but a cache older than 15 minutes is recomputed on the spot, and the live p95 reached <!--canon:v10.budget.live_p95-->about 10 s<!--/canon-->. Measurement method: [`docs/architecture/v10-friction.md`](docs/architecture/v10-friction.md).

## What is v8, "The Kernel"?

The September 2026 release. Until then the brain could say what the assistant should do; v8 adds the part that watches each run. Every process gets a record and an append-only journal you can replay line by line, a cap on how many calls or minutes it may take, and one-writer-per-file isolation so two runs cannot overwrite each other. A skill installed with `octo pkg` is checked (manifest, tree hash, signature) before it lands; a folder copied by hand is outside that check. On Cursor the kernel records the main session only. Contract: [`docs/architecture/v8-kernel.md`](docs/architecture/v8-kernel.md).

## Who maintains Octorato?

Carlos Carrillo (Guadalajara, Mexico), through dataqbs. The productized "AI Agent OS" runs at [dataqbs.com](https://dataqbs.com), built and operated on this brain.

## Where do I start?

Read the [README](README.md) for the plain-words overview, [the long tour](docs/ANATOMY.md) for the architecture, the [white paper](WHITEPAPER.md) for the model, and [CONTRIBUTING](CONTRIBUTING.md) to add a skill or agent. Newcomers are welcome and every contributor is credited.
