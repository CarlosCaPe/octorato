# v5.0: Capability Manifest and the Anti-Regression Gate

> The first version that holds the whole accumulated offering, not just the latest change.

**Status: SHIPPED in v5.0.0 (2026-06-26); the drift table below is the snapshot at v4.3.1.**

## The problem (verified)

The operator's report: every change seems to become the only thing that survives; prior specs get forgotten. Investigation across the full version history (v3.0.0 → v4.3.1) confirms the symptom but corrects the cause.

Nothing is being deleted. The skill count grew monotonically to 232. The real defect: **the offering is narrated by hand on each change instead of generated from the capability set**, and it lives in three surfaces that drift independently:

- `CLAUDE.md`: the constitution an agent actually reads at session start. The lossy layer.
- `README.md`: the public marketing of "what we offer".
- `hooks.json`: the real wiring.

A feature lands in one surface and not the others, so it becomes invisible depending on which you read. Each release note describes only its own diff, never the accumulated total. There is no single canonical document listing everything Octorato does.

Verified drift at HEAD:

| Surface | Claim | Reality |
|---|---|---|
| README agents | `160+` | 189 |
| README divisions | `13` | 15 (`strategy/`, `paid-media/` missing from the narrative) |
| README FinOps budget halt | "shipped" | `grep budget hooks.json` → 0, not wired at v4.3.1. Wired since: `FLOW.budget-halt`, fail-closed, `scripts/budget-check.py --selftest`. |
| `/learn`, canon-heal, staged-promotion | live in skills/hooks/README | absent from `CLAUDE.md` |
| Observability cluster (budget-check, slos, watchdog, brain-trace, skill-cost-profiler, incident-capture, arm-synthetics) | 7 scripts on disk | wired to nothing; last trace JSONL 2026-05-28 |

The most dangerous instance: the docs assert a capability the wiring does not enforce. That is the brain violating its own "Wired or Corrupt" principle, applied to capabilities instead of rules.

## The architecture

Octorato already solved this for the RULE corpus: RULE #1 (Wired or Corrupt) says a rule that is not wired to a live mechanism is rot. v5.0 extends that exact principle from rules to **every capability**.

A capability that exists but is not wired and not represented in the manifest is not a feature. It is debt.

Three load-bearing pieces:

1. **One generated manifest.** A generator scans `skills/`, `agents/`, `scripts/`, `registry/rules.yaml`, and `hooks.json` and emits `docs/CAPABILITIES.md`: the canonical, accumulative offering, with a wiring-status column that flags orphans. It regenerates on every `ai-push`. The offering is never hand-narrated again. This is distinct from the existing `scripts/capability_inventory.py`, which is a narrow tool/ABI counter, not an offering manifest.

2. **Canon everywhere.** The canon-token mechanism (`scripts/canon.py`, `sync-readme-counts.py`) already keeps the skills count fresh. Extend it to every quantitative claim: agents, divisions, rules, hooks, scripts. After this, no number in README can drift silently. `README.md` and the capability sections of `CLAUDE.md` are regenerated from the manifest, not the reverse.

3. **The anti-regression gate.** A pre-push / CI check that fails when either:
   - a `skill/agent/script/rule` exists in the repo but is absent from `docs/CAPABILITIES.md`, or
   - a doc (`README.md`, `CLAUDE.md`) claims a capability that is not wired (no hook, rule, or runner backing it).

   This is the mechanism that makes v5.0 the last time regression-by-replacement happens. It is structural, not disciplinary: the next change physically cannot drop a prior spec from the offering without failing the push.

## Phases

| Phase | Output |
|---|---|
| 0 | This spec. |
| 1 | The manifest generator + `docs/CAPABILITIES.md`. |
| 2 | Canon tokens for agents/divisions/rules/hooks/scripts; README + CLAUDE.md reconciled from canon; stale TOC slug fixed; unsurfaced features backfilled into CLAUDE.md. |
| 3 | Wire the observability cluster (operator decision: resucitar). Each script gets a real hook or scheduled runner so the FinOps offering is true. |
| 4 | The anti-regression gate, wired into `.githooks/pre-push`. |
| 5 | Cut v5.0.0. Release notes are the full accumulated manifest, not the diff. |

## Decisions recorded

- Target product: `octorato` (the public AI Agent OS), v4.3.1 → v5.0.0.
- Observability cluster: wire it (resucitar), not cut. The FinOps pipeline becomes a real differentiator instead of a false claim.
