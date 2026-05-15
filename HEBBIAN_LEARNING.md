# Hebbian Learning — Connectome Adaptation

What this is
- A lightweight Hebbian-style feedback loop for the connectome: when nodes (agents/skills) are activated together during `ventosas` queries, we record the co-activation and gradually boost the edge weights between frequently co-activated pairs.

Goals
- Improve routing accuracy over time by learning real user workflows.
- Preserve cold-start safety: TF-IDF and structural signals remain dominant until enough sessions are observed.

How it works (summary)
- Each `ventosas` command that traverses the graph (`query`, `path`, `4d`) returns a set of `activated_nodes` which are logged to `~/.claude/neural_activity.json` via `log_session()`.
- The `co_activation_matrix` counts pairwise co-activations using keys of the form `nodeA::nodeB`.
- On graph build (`build_graph()`), `compute_hebbian_boosters()` reads the matrix and produces a small boost multiplier per pair.
- `apply_hebbian_weights()` multiplies edge weights by `(1 + boost)` with a cap and writes `hebbian_boost` on affected edges.

Cold-start rules
- Sessions < 50: boosters are dampened by 50% (conservative; TF-IDF dominates).
- Pairs with fewer than 3 (decayed) co-activations are ignored as noise.
- Boost formula (query-time): linear capped at 50%: `boost = min(0.5, (decayed_count - 3) / 100)`.
- Boost formula (build-time): logarithmic capped at 50%: `boost = min(0.5, log1p(decayed_count) * 0.1)`.

Time decay
- Each session's contribution decays exponentially: `weight = e^(-λ × age_days)`.
- λ = 0.01 → half-life ≈ 69 days. Patterns persist ~2 months, then fade.
- Tunable: increase λ for faster forgetting, decrease for longer memory.
- A session from 69 days ago contributes half what a session from today contributes.
- A session from 230 days ago contributes ~10%.

Negative signals (success field)
- Failed sessions (`success: false`) subtract from co-activation counts instead of adding.
- Negative weight = 0.5 → a failure subtracts half what a success adds (after decay).
- This prevents one bad query from killing a well-established pattern.
- The `success` field is already captured by `log_session()`. Currently all automated queries log `success=true`; manual negative feedback can be added by editing the sessions array.

Storage format (`~/.claude/neural_activity.json`)
- `metadata`: descriptive fields and version.
- `sessions`: append-only list of sessions with `timestamp`, `command`, `activated_nodes`, `pair_count`, `success`.
- `co_activation_matrix`: mapping `nodeA::nodeB` → integer count.
- `statistics`: total_sessions, total_co_activations, unique_pairs, strongest_pair.

Monitoring and commands
- View recent sessions:
```bash
jq '.sessions | .[-10:]' ~/.claude/neural_activity.json
```
- View top co-activated pairs:
```bash
python - <<'PY'
import json
a=json.load(open('~/.claude/neural_activity.json'))
items=sorted(a['co_activation_matrix'].items(), key=lambda x:-int(x[1]))[:20]
print('\n'.join(f"{k}: {v}" for k,v in items))
PY
```
- Inspect Hebbian boosts applied when building the graph (debug):
```bash
python -c "from pathlib import Path; exec(Path('~/.claude/scripts/query_connectome.py').read_text()); print('load and build graph')"
```

Safety & privacy
- The log stores only node identifiers (agent/skill IDs). It contains no user PII or message contents.
- The log file is rotated to last 1000 sessions by `log_session()` to bound growth.

Known issues (resolved)
- **Format mismatch — FIXED:** `generate_neural_map.py`'s `load_hebbian_weights()` now reads the structured JSON format written by `query_connectome.py`, parsing the `co_activation_matrix` dict with `::` keys. Hebbian patterns load correctly (verified: 256 patterns from 5806 unique pairs).
- **Key scheme mismatch — FIXED:** Generator now parses `::` keys into sorted tuples for consistent lookup.
- **TF-IDF vectors discarded — FIXED:** `generate_neural_map.py` now stores the IDF dictionary and top-200 TF-IDF terms per document in a `tfidf_index` section of neural_map.json. `query_connectome.py` builds a query vector at runtime and computes cosine similarity against all stored vectors.
- **No decay — FIXED:** Both `compute_hebbian_boosters()` and `load_hebbian_weights()` now apply exponential time decay (`e^(-0.01 × age_days)`, half-life ~69 days) by iterating the sessions array instead of the flat co_activation_matrix. Falls back to raw matrix for backward compatibility.
- **No negative signals — FIXED:** Failed sessions (`success: false`) now subtract 0.5× (after decay) from co-activation counts instead of adding. Prevents reinforcing bad routing patterns.

Known issues (open)
- **No automated failure logging:** All queries currently log `success=true`. A feedback mechanism (e.g., user says "wrong result") to log `success=false` is not yet implemented. Manual editing of sessions is possible.

Next steps and tuning
- Evaluate after 50 sessions: check whether decayed boosters align with expected workflows.
- If boosters overfit, increase `min_coactivations`, decrease cap, or increase `decay_lambda`.
- If patterns fade too fast, decrease `decay_lambda` (e.g., 0.005 → half-life ~139 days).
- Consider implementing automated failure detection (e.g., if user re-runs query with different terms within 30s, log first as failure).

Contact
- For changes to the formula or to reset the learning state: edit `~/.claude/scripts/query_connectome.py` or delete/rotate `~/.claude/neural_activity.json`.

----
Generated: 2026-05-09 — by automation during Hebbian integration.
