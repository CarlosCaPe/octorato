---
name: model-routing-by-complexity
description: "Enruta el trabajo por complejidad a traves del ladder de modelos (mechanical, bulk, build, judgment), vendor-agnostico. Carga al abanicar sub-agentes o al elegir el override de model en un Workflow/Agent."
---

# Model Routing by Complexity

**Principle:** the expensive model is the default reflex, not the default *requirement*. Most of any multi-agent run is mechanical (grep, list, transform, extract, format-check, summarize-one-file). That 80% does not need frontier reasoning. Route it to a cheap tier; build defaults to the build tier; and ALL judgment (QA, code review, second opinion, adversarial verification) runs on the judgment tier. The judgment pin is an invariant, not a preference: **the verifier must run on a model at least as strong as the builder**. A weaker reviewer approves what it cannot see, and the QA verdict is the merge gate.

## The shape: frontier brain, tiered arms

There are two ways to use a cheaper model. Only one is correct:

| Approach | Verdict |
|---|---|
| Downgrade the **main loop / orchestrator** for "simple" turns | ❌ You degrade the thing that *decides everything downstream*. Pennies saved, decision quality risked. |
| Keep the orchestrator on a frontier model and **delegate mechanical work to sub-agents on cheap engines** | ✅ Reasoning stays sharp; the grep/extract/format goes to a cheap arm. |

This is the octopus made literal: a frontier **brain** that reasons and orchestrates, plus tiered **arms** that execute. It wins twice:

1. **Decision quality intact** — the agent that delegates the work stays frontier-grade.
2. **Context stays cheap too** — a sub-agent reads the 20 files in *its own* ephemeral context and returns only the conclusion; the expensive main context never pays to read those 20 files. You save on **tier** *and* on **context tokens** at once.

The decision "do I (build-tier) do this, or hand it to a mechanical arm?" *is* the 2D-Delegate decision — the moment the brain hands a task to an arm is the moment it sizes the effort.

This is the FinOps complement to [[finops-budget-policy]]:
- **Budget caps** = the ceiling (hard_stop refuses the tool when an arm burns through its cap).
- **Complexity routing** = the floor (each run costs less to begin with).
Caps stop catastrophe; routing improves margin on every single run.

> Idea generalized from a public peer pattern (Moonshift's router — deterministic majority to cheap models, hard minority to expensive ones, landing a build at a low flat cost). The pattern is adopted; no code is taken.

## Vendor-agnostic tiers (the ladder)

One table of **jobs**. Vendor model names are *bindings*, not the ladder itself. Never hard-code "Haiku" into a Cursor Task call, and never hard-code `grok-4.5` into a Claude Code Agent call — pick the binding for the runtime you are in.

| Tier | Reasoning needed? | Route here (task shapes) |
|---|---|---|
| **mechanical** | **No** | grep/list/find, file inventory, mechanical transform, rename, format/lint check, data extraction and categorization, translation, content moderation, high-volume straightforward text. |
| **bulk** | Yes (light) | conscious downgrade for WELL-SPECIFIED bulk build: extract and summarize a source, batch edits with a clear spec, schema-validate, doc regeneration, copywriting, data and image analysis, process automation. Never the default; ambiguity sends it up a tier. |
| **build** | Yes | the build DEFAULT: common coding, cross-file synthesis, design trade-offs, ambiguous requirements, architecture decisions, strategic multi-step problem solving. |
| **judgment** | Yes (strongest) | ALL judgment, no exceptions: QA, code review, second opinion of another agent, adversarial verification, "a wrong answer is expensive here". The verifier runs at least as strong as the builder. |

**Hard line: mechanical does not support multi-step reasoning.** Route to mechanical only when the work needs no inference. A task that has to weigh, infer, or catch a subtle trap goes up a tier (build by default), never mechanical, no matter how small it looks. Image and data analysis are bulk-grade, not mechanical.

## Runtime bindings (2026-07-10)

### Claude Code (Anthropic)

| Tier | Model alias / slug | Notes |
|---|---|---|
| mechanical | `haiku` | Lowest cost/latency in the Claude family. |
| bulk | `sonnet` | Conscious downgrade only. |
| build | `opus` | Build default. |
| judgment | `fable` | **No exceptions** on Claude Code (operator directive 2026-07-01). |

Pass these via the Agent/Workflow `model` parameter (`haiku` \| `sonnet` \| `opus` \| `fable`).

### Cursor + xAI Grok (and other Cursor engines)

Detect with `CURSOR_AGENT=1`. Use **only** Cursor Task `model` slugs the harness allow-lists (passing an unlisted slug fails or is ignored). API-only xAI names below are for FinOps / direct API — **not** for `Task` unless the harness lists them.

| Tier | Preferred Cursor Task slug (allow-listed) | API-only / if unavailable |
|---|---|---|
| mechanical | `composer-2.5-fast` | `grok-build-0.1` (xAI API) / smallest fast slug the harness lists |
| bulk | `gpt-5.5-medium` (or mid GPT the harness lists) | mid Grok API (`grok-4.3` / `grok-4.20-*`) — only if Task allow-lists them |
| build | `grok-4.5-fast-xhigh` (or session Grok 4.5) | inherit session model when already on build-tier Grok |
| judgment | strongest **independent** engine ≥ builder (e.g. `claude-opus-4-8-thinking-high` for a Grok builder) | Prefer a *different vendor* when Cursor offers one. If only Grok is available, spawn a **fresh** Task on the same Grok tier (independent context). Never drop below the builder. |

List prices for FinOps live in `scripts/_pricing.py` (Anthropic + xAI). Composer / bundled GPT have **no list row yet** — FinOps reports `$0` list rather than inventing Sonnet rates. Cursor subscription billing may differ from list — treat USD as value-extracted unless reconciling a real invoice.

## How to apply in Octorato tooling

Both layers already expose a per-call `model` override. Set `model` by the **tier**, then bind to the runtime's slug:

- **Claude Code Workflow / Agent** — `model: 'haiku' | 'sonnet' | 'opus' | 'fable'` per call or phase. Judgment ALWAYS pins `'fable'` explicitly (no inherit).
- **Cursor Task** — `model` must be a slug from the Cursor allow-list (see bindings above). Judgment pins an independent ≥-builder slug explicitly.
- Omitting `model` is correct only when the session engine already sits on the task's ladder tier.

## Honest caveats (do not skip)

- **Measure, don't assume.** A cheap model that fails the task and triggers a retry/rework can cost *more* than doing it once on the strong model. Downgrade only where output quality holds.
- **Verify after downgrading** (3D Diligent): spot-check that the cheap-tier output is actually correct before trusting it in a pipeline. Silent quality loss is the real risk, not token cost.
- **Verification stays strongest.** The adversarial/verify/QA step is pinned to judgment; its whole job is to catch the builder's mistakes, so it can never run on a weaker tier than the builder did.
- **Spawn overhead is real — don't delegate the trivial.** Spawning a sub-agent costs a fixed amount (latency + the orchestrator pays to read the returned summary). For a one-line grep, doing it inline on the brain is cheaper than dispatching a mechanical arm. The win is for mechanical work that is **token-heavy or parallelizable**. Rule of thumb: *delegate the heavy mechanical 80%; keep the trivial and the reasoning in the brain.*
- **Routing is opt-in per call**, like the budget cap is opt-in per arm. The mechanism is real; the savings depend on actually classifying the work.
- **Runtime mismatch is a hard failure.** Passing `haiku` into Cursor Task, or requiring `claude mcp list` inside a Grok session, is not "close enough" — it is a broken binding. See `docs/architecture/multi-runtime.md`.

## Net

One brain, sealed arms, one ledger per client — **multiple runtimes and engines**. On that ledger, routing lowers the baseline while caps stop the spikes. Related: [[finops-budget-policy]], [[token-efficient-prompting]], `docs/architecture/multi-runtime.md`.
