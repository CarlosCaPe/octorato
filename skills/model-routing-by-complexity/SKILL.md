---
name: model-routing-by-complexity
description: "Frontier brain, tiered arms: keep the orchestrator on a frontier model and DELEGATE by complexity; never downgrade the main loop itself. The ladder (operator directive 2026-07-01): mechanical (grep, extract, transform, format-check) → Haiku · well-specified bulk build → Sonnet (conscious downgrade, never the default) · build DEFAULT → Opus · ALL judgment (QA, code review, second opinion, adversarial verify) → Fable, no exceptions. Cuts per-client token spend at the baseline, not just at the cap. Load when fanning out many sub-agents (Workflow/Agent), when an arm's FinOps cost needs lowering without changing the deliverable, or when deciding the `model` override for a Workflow stage or Agent call. Pairs with budget caps: caps stop runaway spend; routing lowers the floor."
---

# Model Routing by Complexity

**Principle:** the expensive model is the default reflex, not the default *requirement*. Most of any multi-agent run is mechanical (grep, list, transform, extract, format-check, summarize-one-file). That 80% does not need frontier reasoning. Route it to a cheap model; build defaults to Opus; and ALL judgment (QA, code review, second opinion, adversarial verification) runs on Fable, no exceptions. The judgment pin is an invariant, not a preference: **the verifier must run on a model at least as strong as the builder**. A weaker reviewer approves what it cannot see, and the QA verdict is the merge gate.

## The shape: Opus brain, Haiku arms

There are two ways to use a cheaper model. Only one is correct:

| Approach | Verdict |
|---|---|
| Downgrade the **main loop / orchestrator** for "simple" turns | ❌ You degrade the thing that *decides everything downstream*. Pennies saved, decision quality risked. |
| Keep the orchestrator on a frontier model and **delegate mechanical work to sub-agents on cheap engines** | ✅ Reasoning stays sharp; the grep/extract/format goes to a cheap arm. |

This is the octopus made literal: a frontier **brain** (Fable) that reasons and orchestrates, plus tiered **arms** (Haiku for mechanical, Opus for build, Fable for judgment) that execute. It wins twice:

1. **Decision quality intact** — the agent that delegates the work stays frontier-grade.
2. **Context stays cheap too** — a sub-agent reads the 20 files in *its own* ephemeral context and returns only the conclusion; the expensive main context never pays to read those 20 files. You save on **tier** *and* on **context tokens** at once.

The decision "do I (Opus) do this, or hand it to a Haiku arm?" *is* the 2D-Delegate decision — the moment the brain hands a task to an arm is the moment it sizes the effort.

This is the FinOps complement to [[finops-budget-policy]]:
- **Budget caps** = the ceiling (hard_stop refuses the tool when an arm burns through its cap).
- **Complexity routing** = the floor (each run costs less to begin with).
Caps stop catastrophe; routing improves margin on every single run.

> Idea generalized from a public peer pattern (Moonshift's router — deterministic majority to cheap models, hard minority to expensive ones, landing a build at a low flat cost). The pattern is adopted; no code is taken.

## How to apply in Octorato tooling

Both layers already expose a per-call `model` override — **default to omitting it** (inherit the session model), and set it explicitly only when the task's complexity clearly justifies a tier change:

- **Workflow** — `agent(prompt, { model: 'haiku' })` per call, or `model` on a `phase` entry. Inside `pipeline()`/`parallel()`, set the cheap tier on the mechanical stage and the strong tier on the synthesis/verify stage.
- **Agent tool**: the `model` parameter (`haiku` | `sonnet` | `opus` | `fable`).

## Decision rubric (harmonized with Anthropic's "Claude model family")

One table, not two. The brain's task-shape routing IS Anthropic's tier guidance applied. Cheap to expensive, so they can never drift apart:

| Tier | Anthropic positioning | Reasoning | Route here (brain task shapes) |
|---|---|---|---|
| **Haiku** | Lowest cost, lowest latency. | **No** | grep/list/find, file inventory, mechanical transform, rename, format/lint check, data extraction and categorization, translation, content moderation, high-volume straightforward text. |
| **Sonnet** | Balances quality, speed, cost. | Yes | conscious downgrade for WELL-SPECIFIED bulk build: extract and summarize a source, batch edits with a clear spec, schema-validate, doc regeneration, copywriting, data and image analysis, process automation. Never the default; ambiguity sends it up a tier. |
| **Opus** | Highest intelligence in the 4.x family. | Yes | the build DEFAULT: common coding, cross-file synthesis, design trade-offs, ambiguous requirements, architecture decisions, strategic multi-step problem solving. |
| **Fable** | Mythos-class, above Opus. | Yes | ALL judgment, no exceptions (operator directive 2026-07-01): QA, code review, second opinion of another agent, adversarial verification, "a wrong answer is expensive here". The verifier runs at least as strong as the builder. |

**Hard line: Haiku does not support reasoning.** Route to Haiku only when the work is mechanical and needs no multi-step inference. A task that has to weigh, infer, or catch a subtle trap goes to Sonnet or Opus, never Haiku, no matter how small it looks. The corollary holds the other way too: image and data analysis are Sonnet-grade, not Haiku. (Source: Anthropic "Claude model family" table.)

## Honest caveats (do not skip)

- **Measure, don't assume.** A cheap model that fails the task and triggers a retry/rework can cost *more* than doing it once on the strong model. Downgrade only where output quality holds.
- **Verify after downgrading** (3D Diligent): spot-check that the cheap-tier output is actually correct before trusting it in a pipeline. Silent quality loss is the real risk, not token cost.
- **Verification stays strongest.** The adversarial/verify/QA step is pinned to Fable; its whole job is to catch the builder's mistakes, so it can never run on a weaker tier than the builder did. Session evidence 2026-07-01: Fable QA passes caught a fail-open merge gate, a secrets-guard pipe bypass, and an unreviewed-wiki-publish path that green CI had waved through.
- **Spawn overhead is real — don't delegate the trivial.** Spawning a sub-agent costs a fixed amount (latency + the orchestrator pays to read the returned summary). For a one-line grep, doing it inline on the brain is cheaper than dispatching a Haiku arm. The win is for mechanical work that is **token-heavy or parallelizable** (read many files, bulk extract/transform). Rule of thumb: *delegate the heavy mechanical 80%; keep the trivial and the reasoning in the brain.*
- **Routing is opt-in per call**, like the budget cap is opt-in per arm. The mechanism is real; the savings depend on actually classifying the work.

## Net

One brain, sealed arms, one ledger per client. On that ledger, routing lowers the baseline while caps stop the spikes. Related: [[finops-budget-policy]], [[token-efficient-prompting]].
