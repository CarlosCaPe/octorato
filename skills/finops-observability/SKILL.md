---
name: finops-observability
description: "Measure brain/agent cost so it can be managed — 'lo que no se mide no crece'. Routes a cost/FinOps question to the right existing tool: per-arm spend, routing KPI ($ saved vs all-Opus), marginal cost of each new capability, est-vs-billed reconciliation, per-skill ROI. Load when the operator asks how much we spent, whether something is cheap or expensive, 'cuánto gastamos/cuesta', which arm/model/skill is eating tokens, whether model-routing is working, or whether a new capability made us pricier."
---

# FinOps Observability

The brain already measures cost across several surfaces. This skill is the map so you pick the right one instead of rebuilding. All use list-price ESTIMATES from local session JSONL (attributed by repo path) — honest scope: an estimate with a small unattributed remainder, not a per-request invoice. On a subscription, "estimated $" is API-equivalent value, not what's billed.

## Which tool for which question

| Question | Tool |
|---|---|
| Per-arm $ + routing KPI ($ saved vs all-Opus) + est-vs-billed | `python3 scripts/finops-digest.py [--days N] [--json]` |
| Did a NEW capability make me cheaper/more expensive? | `python3 scripts/cost-vs-change.py [--days N] [--window W]` — correlates daily cost curve with the git log of skills/scripts merged |
| Daily roll-up (skills/agents activity + the FinOps routing section) | `python3 scripts/brain-digest.py --stdout` |
| Usage by day/week/month/model/project | `python3 skills/claude-usage-report/scripts/usage_report.py` |
| Per-skill token ROI (which skill earns its tokens) | `python3 scripts/skill-cost-profiler.py --days N --json` |
| Reconcile estimate vs ACTUAL billed (needs Admin API key) | `python3 scripts/anthropic-analytics-pull.py` then re-run finops-digest |
| Enforce a per-arm cap (not just measure) | [[finops-budget-policy]] — set `budgets.yaml` (template: `budgets.yaml.example`) |

`usage_report.py` owns the canonical PRICING table — every other tool reuses its `price()`; never fork the rates.

## The two levers (measure → act)

- **Caps** ([[finops-budget-policy]]) = the ceiling: a `PreToolUse` hook refuses the expensive tool when an arm burns through its cap.
- **Routing** ([[model-routing-by-complexity]]) = the floor: Opus brain, Haiku arms — delegate mechanical work to cheap engines. The `finops-digest` routing KPI ($ saved vs all-Opus) is what proves routing is actually happening; if spend is ~100% Opus, routing is unused.

## Honest reading

- Daily cost tracks how much you worked, not only new capabilities — `cost-vs-change` surfaces signals to investigate, not proof (correlation ≠ causation).
- The blog/news pipeline runs on Groq + GH Actions + CF, NOT Claude — those costs are in OTHER meters this suite doesn't see yet. Cost-per-output for content needs Groq ingestion (not built).
- Make the digest recurring (it's folded into `brain-digest.py`); a metric nobody reads doesn't grow.
