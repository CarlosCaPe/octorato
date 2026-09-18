# Octorato — FAQ

Plain answers to the questions people (and the AI agents that read this repo) actually ask.

## What is Octorato?

A folder of plain-text files that gives your AI coding assistant a lasting memory, house rules, and a receipt for everything it does. In its own vocabulary: an **open-source AI agent operating system**, one file-native "brain" (rules, 230+ skills, 160+ specialist agents, memory, all markdown under git) that one operator runs across many sealed client "arms", with per-client cost attribution and hard budget halts. MIT licensed.

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

## What is v8, "The Kernel"?

The September 2026 release. Until then the brain could say what the assistant should do; v8 adds the part that watches each run. Every process gets a record and an append-only journal you can replay line by line, a cap on how many calls or minutes it may spend, and one-writer-per-file isolation so two runs cannot overwrite each other. A skill installed from outside has to be signed before it loads. Contract: [`docs/architecture/v8-kernel.md`](docs/architecture/v8-kernel.md).

## Who maintains Octorato?

Carlos Carrillo (Guadalajara, Mexico), through dataqbs. The productized "AI Agent OS" runs at [dataqbs.com](https://dataqbs.com), built and operated on this brain.

## Where do I start?

Read the [README](README.md) for the plain-words overview, [the long tour](docs/ANATOMY.md) for the architecture, the [white paper](WHITEPAPER.md) for the model, and [CONTRIBUTING](CONTRIBUTING.md) to add a skill or agent. Newcomers are welcome and every contributor is credited.
