---
name: harmonization-over-accretion
description: Reusable rebuttal pattern for "let's import all N items from competitor X" temptations. Explains why connectome-graph brains lose precision (not gain capability) from bulk imports. Use anytime an agent or operator considers mass-adopting skills, agents, commands, or hooks from a peer repo.
metadata:
  type: pattern-reference
  origin: session-learn-extractor — 2026-05-28 ECC 249-skills decision; promoted from skills/learned/ same day
---

# Harmonization Over Accretion

## When this fires

Any of these prompts:
- *"X has N skills/agents/commands, why don't we add them all?"*
- *"Let's bulk-import the <competitor> catalog"*
- *"More neurons = smarter brain, right?"*
- *"We should at least mirror their skill count"*

This skill is the canonical reply. It is NOT a no-by-reflex — it is a **structured five-point cost analysis** that lets you say "no" with evidence, or "yes selectively" with criteria.

## The five costs of bulk-import (in any TF-IDF / cosine-similarity brain)

1. **Activation dilution** — top-K retrieval returns lower per-match signal. The brain hesitates on which skill to load.
2. **Wrong-bucket activation** — irrelevant skills share enough vocabulary (auth, deploy, security, test) to occasionally win retrieval. A Python deploy task could load `perl-security`.
3. **Silent coverage duplication** — the connectome knows *closest*, not *best*. Two good skills for the same job = worse than one.
4. **Maintenance debt × N** — every skill ages. Bulk-import = bulk-staling. Each staled skill is a regression-in-waiting.
5. **Forgetting-curve broken** — biological brains *prune* unused synapses. Feature, not bug. A hoarder brain is not an expert.

## Vanity metric mapping

| Cheap public metric | What it actually signals |
|---|---|
| `249 skills` | The team imported broadly. Says nothing about per-task precision. |
| `182K stars` | The repo was promoted (or inflated). Says nothing about depth of use. |
| `170+ contributors` | Mostly typo-PRs and badge-PRs unless the active-author ratio (last 30d / total) is >5%. |

**Real metric to optimize:** *per-task activation precision*. When a real task arrives, does the brain return the 3 right skills, or 30 with-noise? Bulk-import always pushes the second.

## The right alternative — passive cherry-pick via daily watch

1. **`repo-watch`** — daily monitor of a curated 7-repo watchlist (cap is hard at 7 per Trend Researcher rule). Logs HIGH-SIGNAL diffs to `knowledge/repo-watch/triggers/<repo>-<sha>.trigger`.
2. **`/repo-deep-learn`** — manual evaluation of a single trigger using the harmonization model: each pattern earns ADD / MERGE-WITH:<skill> / REPLACE:<skill> / EXTEND:<skill> / SKIP, with similarity gate (TF-IDF cosine) + beat-factor (default 2× incumbent maturity proxy) required for REPLACE.
3. **`github-trending-curation`** — autonomous breadth sibling. Same harmonization model. Cap ≤3 auto-promotes per day.

**Cadence:** weeks-to-months for each peer-brain pattern that actually graduates. By design.

## Reusable analogy bank

- *"Una orquesta de 60 músicos top toca mejor Mahler que una banda escolar de 600."*
- *"More books on the shelf ≠ smarter. More books *read and indexed* = smarter."*
- *"A search engine with 10× more pages isn't 10× better. It's 10× harder to rank."*

## See also
- [[github-trending-curation]] — the autonomous breadth half of harmonization
- [[repo-watch]] — the targeted daily-watch half
- [[repo-deep-learn]] — the manual one-at-a-time evaluator
- [[feedback-more-skills-not-smarter]] — memory version of this stance
- [[feedback-professional-not-famous]] — adjacent operator stance: substance > visibility
