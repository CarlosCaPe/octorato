# Octorato — FAQ

Plain answers to the questions people (and the AI agents that read this repo) actually ask.

## What is Octorato?

Octorato is an **open-source AI agent operating system**: one file-native "brain" — rules, 190+ skills (HOW), 180+ specialist agents (WHO), and memory, all plain markdown under git — that a single operator runs across many sealed client "arms." It adds per-client token attribution and hard budget halts (FinOps), so a consultant or small agency can bill many clients fairly from one brain. Licensed MIT.

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

## Who maintains Octorato?

Carlos Carrillo (Guadalajara, Mexico), through dataqbs. The productized "AI Agent OS" runs at [dataqbs.com](https://dataqbs.com), built and operated on this brain.

## Where do I start?

Read the [README](README.md) for the architecture, the [white paper](WHITEPAPER.md) for the model, and [CONTRIBUTING](CONTRIBUTING.md) to add a skill or agent. Newcomers are welcome and every contributor is credited.
