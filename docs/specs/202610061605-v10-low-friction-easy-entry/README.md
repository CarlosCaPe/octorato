# v10, Low Friction and Easy Entry

Implemented on: 2026-10-13

Every check from v7 to v9 stays; v10 makes them cheaper to live with and easier to start. Spec `feature.md` (25 acceptance criteria, `Spec-Format: ears-1`), plan `plan.md` (T01 to T32 across four Convergence passes). The converge verdict that closes it is the CONVERGED receipt of 2026-10-13 recorded by an independent verifier on commit 3526981.

Key files: `scripts/quickstart.py` (one-command install), `scripts/friction_ledger.py` and `scripts/r__stop__friction-ledger.py` (every refusal counted), `scripts/replay_harness.py` and `registry/friction-baseline.json` (private replay corpus, baseline counts only), `scripts/octo.py` (`octo friction`, `octo dash`), `scripts/octo_dash.py` and `scripts/statusline.py` (the visible brain), `scripts/budget-check.py` (spend cache), `commands/requa.md` (re-review after a base update), `scripts/g__stop__goal-anchor.py` (read receipts, fewer blocks).

Notable decisions: the replay rates the goal-anchor check on the Stops it recorded a read receipt for (AC-25, amended 2026-10-13), because history before the receipts cannot be rebuilt by any replay; the gate's fixture violation legs stand in as labelled true positives while the corpus holds none (AC-10). One part of the release criterion is read after the cut: the send check's false-positive rate over the first 7 days of post-release friction data must stay under 15%.
