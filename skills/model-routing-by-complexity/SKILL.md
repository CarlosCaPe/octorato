---
name: model-routing-by-complexity
description: "Route agent/sub-agent work to the cheapest model that can do it — deterministic/mechanical work to Haiku, hard reasoning to Opus/Sonnet — so per-client token spend drops at the baseline, not just at the cap. Load when fanning out many sub-agents (Workflow/Agent), when an arm's FinOps cost needs lowering without changing the deliverable, or when deciding the `model` override for a Workflow stage or Agent call. Pairs with budget caps: caps stop runaway spend; routing lowers the floor."
---

# Model Routing by Complexity

**Principle:** the expensive model is the default reflex, not the default *requirement*. Most of any multi-agent run is mechanical (grep, list, transform, extract, format-check, summarize-one-file). That 80% does not need frontier reasoning. Route it to a cheap model; reserve Opus/Sonnet for the hard 20% (architecture, ambiguous synthesis, adversarial verification, anything where a wrong answer is expensive).

This is the FinOps complement to [[finops-budget-policy]]:
- **Budget caps** = the ceiling (hard_stop refuses the tool when an arm burns through its cap).
- **Complexity routing** = the floor (each run costs less to begin with).
Caps stop catastrophe; routing improves margin on every single run.

> Idea generalized from a public peer pattern (Moonshift's router — deterministic majority to cheap models, hard minority to expensive ones, landing a build at a low flat cost). The pattern is adopted; no code is taken.

## How to apply in Octorato tooling

Both layers already expose a per-call `model` override — **default to omitting it** (inherit the session model), and set it explicitly only when the task's complexity clearly justifies a tier change:

- **Workflow** — `agent(prompt, { model: 'haiku' })` per call, or `model` on a `phase` entry. Inside `pipeline()`/`parallel()`, set the cheap tier on the mechanical stage and the strong tier on the synthesis/verify stage.
- **Agent tool** — the `model` parameter (`haiku` | `sonnet` | `opus`).

## Decision rubric

| Task shape | Tier |
|---|---|
| grep/list/find, file inventory, mechanical transform, rename, format/lint check | **haiku** |
| extract structured data, summarize one source, single-file edit, schema-validate | **haiku / sonnet** |
| cross-file synthesis, design trade-offs, ambiguous requirements, code review | **sonnet / opus** |
| adversarial verification, architecture decision, "a wrong answer is expensive here" | **opus** |

## Honest caveats (do not skip)

- **Measure, don't assume.** A cheap model that fails the task and triggers a retry/rework can cost *more* than doing it once on the strong model. Downgrade only where output quality holds.
- **Verify after downgrading** (3D Diligent): spot-check that the cheap-tier output is actually correct before trusting it in a pipeline. Silent quality loss is the real risk, not token cost.
- **Verification stays strong.** Never route the adversarial/verify step to the cheapest tier — that's the step whose job is to catch the others' mistakes.
- **Routing is opt-in per call**, like the budget cap is opt-in per arm. The mechanism is real; the savings depend on actually classifying the work.

## Net

One brain, sealed arms, one ledger per client — and on that ledger, routing lowers the baseline while caps stop the spikes. Related: [[finops-budget-policy]], [[token-efficient-prompting]].
