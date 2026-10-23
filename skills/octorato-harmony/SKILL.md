---
name: octorato-harmony
description: "When the same value reads 10 in one place and 12 in another, converge both to a canonical one referenced everywhere, never forked. Triggers when editing design tokens, styles or conventions across several files, and on 'converge' or 'armoniza'."
metadata:
  type: pattern-reference
  origin: octorato-harmony-canon + innate-harmony-research panels — 2026-05-30
---

# Octorato Harmony — the octopus moves as one

> The complement of [[harmonization-over-accretion]]. That skill stops you *adding* noise.
> This one *converges* the noise already present into one coherent motion.

## The principle (one line)

**No conductor — one tempo: each cell plays its own part, and the whole moves as one because they all keep tuning to the same canonical note, never knowing they tuned at all.**

Autonomy in *behavior*, convergence in *vocabulary*. A cell decides WHAT to do; it never re-decides what a shared value IS — it references the one canonical token. The body moves together without any cell seeing the others.

## The cellular model (why this is real, not metaphor)

Every git file is a **cell**. There is no arm/brain hierarchy — the brain is *also* made of cells; no cell is above another ([[octorato-symbolism]]: 8→∞ at the value layer). Coherence is **morphogenesis**: global form emerges from cells that (a) read the **same genome** — the canonical source of truth — and (b) respond to **local signals** (imports, neighbors), with **no central planner**. Grounded in established science:

| Phenomenon | What it proves | Our mechanism |
|---|---|---|
| Octopus jet propulsion (Pumphrey–Young; J.Z. Young 1939) | total synchrony comes from **synchrony engineered into the wiring** (graded axon diameters equalize arrival), NOT a faster central command | every cell references the *same* canonical token → all "equidistant from truth" → move together |
| Brain sends **goals, not trajectories** (Frontiers Robotics 2022; the brain↔arm channel is a deliberate bottleneck) | a controller that *can't* micromanage is forced to delegate → autonomy is structural, not granted | ship canonical VALUES + primitives down; never per-cell step-lists ([[feedback-transcend-the-marionette]]) |
| Turing reaction–diffusion; Kuramoto coupled-oscillator sync; Laplacian consensus | global pattern / phase-lock / agreement emerge from **local rules + weak coupling** — provably, with no center | average-to-the-middle (consensus) + neighbor-weighted drift gossip (Kuramoto) |
| Fiedler *Fix Your Timestep* (fixed sim tick + interpolation) | smoothness = a **steady high tick**, not raw speed; jitter is worse than slow | the reflex must fire reliably every event (frame pacing), not "sometimes" |

## The rule

> **One canonical value per property, cited everywhere, copied nowhere.**

When a shared primitive diverges (`10px` here, `12px` there) do **not** pick a winner and do **not** fork. **Average to the middle** (`round(mean) → 11`), write it ONCE into the canonical note, and rewrite both call-sites to *reference* it. Steady state is pure reference: the only legal path to a value is the canonical token. Change the canon once → every cell shifts with zero per-cell edits and zero cell referencing another. That is the octopus moving as one.

## How to apply

1. **Single source of truth** — `tokens/canon.json` (per arm; the CHECKER is generic, the VALUES are the arm's — Arm Isolation). One entry per property = one atomic gene. Scope real context so it isn't flattened (`space.gutter.mobile` vs `.desktop`); mark per-instance brand keys `"perArm": true` ([[lesson-fachada-cimientos-pattern]]).
2. **Detect + converge drift** — `python3 scripts/harmony-check.py --report` (dry-run table), `--fix` (converge behind the 4D Gate), `--audit` (one number = the Unison Test signal).
3. **Witness deliberate divergence, never suppress it** — annotate `// canon:exempt(reason)`; the checker records it instead of flagging. A load-bearing 12 (an alert red that must NOT average into brand red) is a sanctioned exception, not drift.

## The reflex — multi-Hz, like the octopus

Harmony is **innate**, not commanded — reflexes at different rates (the octopus has fast and slow ones):

| Reflex | Cadence (Hz) | Hard / soft |
|---|---|---|
| `PreToolUse` hook on UI/token edits + `.githooks/pre-push` | every edit / push | **hard** (enforces; same belt as `check-generic.py`) |
| connectome heartbeat injects "this value is canonical" | every prompt | soft (advisory — for judgment) |
| scheduled audit (cron) over all surfaces | daily | escalation gate (fix locally, surface only distilled drift — [[feedback-error-is-improvement]]) |

Soft reflexes for **judgment**; hard reflexes for **invariants**. The soft heartbeat *informs* (the model may ignore it → intermittent); a hard hook *cannot forget* (deterministic) → that is how the beat becomes total.

**Three hearts (why redundant beats).** An octopus has *three* hearts — two **branchial** (one per gill, pumping at the periphery) and one **systemic** (circulating to the whole body). Harmony is the same: **two-plus local beats** (per-cell `PreToolUse`/pre-push hooks at the periphery) **+ one systemic beat** (the connectome heartbeat / scheduled reconciliation circulating the canon). The totality of the beat comes from **redundancy**, not from one perfect pump — if any single reflex misfires the others sustain circulation, so *"sometimes it fails"* is cured by having three. And as the octopus's systemic heart *pauses* during a jet-propulsion swim, during a big synchronized canonical change the **local beats carry the load while the center rests** — converge peripherally first, escalate only the distilled result.

## Coherence test — the Unison Test

Change one canonical value in `tokens/canon.json` exactly once. The body is dancing as one if **every cell shifts with zero per-cell edits and zero cell reaching into another**, and `harmony-check.py --audit` prints `DRIFT = 0`. It has DRIFTED the moment the same concept is hardcoded at two different values in two places, OR one cell reaches into another to stay synced (that's a choreographer, not emergence). Language is the early-warning: when people start saying "align" / "synergy" instead of "tune to the same note", the canon has decayed into jargon.

## Risks (honest)

- **Monoculture** — averaging is right for arbitrary tokens, catastrophic for semantically load-bearing values (a price, a security threshold, an alert color). Mitigation: operate only inside a declared canonical namespace; **dry-run by default**; `canon:exempt(reason)`.
- **Wrong canonical value propagating as orthodoxy** — keep the pre-convergence spread visible in the registry; never collapse it to a lossy single number silently.
- **Taste is not a token** — values converge to total harmony (mechanical, hookable); aesthetic *judgment* never reaches 100% (it is cognition). The rule there: every string the operator pulls once becomes a permanent reflex (token/hook/skill), so it is never pulled again — asymptotic, not instant ([[feedback-transcend-the-marionette]]).

Ties: [[harmonization-over-accretion]] · [[feedback-harmonize-converge-to-middle]] · [[feedback-transcend-the-marionette]] · [[octorato-symbolism]] · [[4d-paradigm-protocol]] (dry-run gate).
