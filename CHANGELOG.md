# Changelog

All notable changes to the Octopus Brain Framework are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
the project follows the **Site Semantic Versioning** scheme described in the
[Self-Growth wiki page](https://github.com/CarlosCaPe/octorato/wiki/Self-Growth#8-site-semantic-versioning)
— bot-identity commits bump PATCH, operator commits bump MINOR, and an
explicit `Octorato-Major:` commit trailer bumps MAJOR.

This log records human-meaningful framework changes. The complete
machine-generated growth ledger lives at
`knowledge/github-trending/HISTORY.md` (autonomous daily additions) and
`knowledge/repo-watch/<date>.md` (daily watchlist digests).

## [Unreleased]

## [2026-06-02] — v3.1.0 "Reflexes"

Major step: the brain moved from **sensing** itself (3.0 Proprioception) to **enforcing** itself — principles became involuntary reflexes wired as hooks, not advisory prose the model can skip. And it learned to run as **one self across many parallel dimensions**.

### Added — reflexes
- **Connector verdict, enforced** — the 2D Delegate verdict is inverted: **SELF is the rare exception, the default is CONNECT** (LOAD/ACTIVATE). The agent is a connector to real sources, not an encyclopedia; SELF fires only when the operator explicitly asks for an opinion. (`scripts/delegate-check`, `scripts/query_connectome.py`, `CLAUDE.md` §2D)
- **Delegation reflex** — `scripts/delegate-gate.py` (PreToolUse, fail-open): nudges substantive/batchable work toward the cheapest sufficient model (Haiku/Sonnet/Opus) instead of the main loop.
- **QA merge gate** — `scripts/qa-merge-gate.py` (PreToolUse, fail-closed): no publish-to-main without an operator approval the **agent provably cannot self-grant** (PR-scoped `OCTO_MERGE_APPROVE` env — an inline env never reaches the harness-run hook — or `octo-dim approve-merge`). Detection is **command-boundary-anchored** so it gates real invocations, not mentions in quoted args.
- **Dimension awareness** — `scripts/dimension-awareness-hook.py` (PreToolUse, fail-open): warns when other live sessions share the working tree.

### Added — 4D session dimensions
- **One tentacle, N parallel dimensions** — `scripts/octo-dim.py` (register / heartbeat / list / prune / worktree-init / approve-merge) + a blackboard registry (`connectome/sessions.json`, gitignored): the same session-id runs in isolated git worktrees, reconciled into one `.git`. Isolation is the enabler of the 4D superpower, not a constraint. (`skills/session-isolation`)
- **Human-cadence delivery rules** — `skills/human-cadence`.

### Added — architecture
- **Hook orchestration, formalized + cited** — `docs/architecture/hook-orchestration.md`: a **Reactive Control Architecture with Adaptive Recall** (ECA atoms · Behavior-Tree priority · Statechart 4D · Spreading-Activation recall · Marr–Albus control loop · contextual-bandit tier-routing). L4 bandit router + activation-decay connectome are specified as the next build, not yet implemented.
- **Release/news cadence sense** — `brain_doctor` check `release-drift`: flags a top CHANGELOG version with no matching git tag (the gap that left v3.0.0 documented-but-unreleased). News is the brain's top-of-funnel reflex — a bump with no news = lost reach.

### Changed
- `brain_doctor` assertion count converged (`CLAUDE.md`) and the doctor grew to 15 checks (lineage-sound, release-drift).
- The qa-merge-gate enforces a hard rule now in `CLAUDE.md` §2D: the agent cannot self-approve its own merge gate.

## [2026-06-01] — v3.0.0 "Proprioception"

Major: the brain grew new **organs** — cross-cutting faculties that govern *how* every arm acts — not just arms (skills). It moved from **reactive to reflexive**: it now senses and coordinates itself.

### Added — organs
- **Proprioception** — the one-line **Provenance footer** (Basis · Engine · Touched · Verified) ends every response: the brain sensing its own action. (`scripts/4d-reminder.py`, `scripts/source-attribution-check.py`)
- **The reflective WHILE** — 4D codified as a loop, not a one-shot: `while (open / remnants / Touched≠intent): 4D()`; exit on reconciliation, never on "looks done". (`skills/4d-paradigm-protocol`)
- **The cerebellum** — precision without tremor: feedforward Manifest (enumerated target) ⇄ binary `Touched` reconcile ⇄ involuntary firing. `scripts/impact-radius.py` (tool) + `scripts/impact-radius-hook.py` (PostToolUse `Write|Edit` reflex). Closes the #1 recurrent failure — codify-in-one-place / leave-refs-stale ("pixelation") and its twin, touching or creating more than needed.
- **Metabolic sense (FinOps)** — `scripts/finops-digest.py` (per-arm $, routing KPI vs all-Opus, est-vs-billed), `scripts/cost-vs-change.py` (marginal cost of each new capability), folded into `brain-digest.py`; `skills/finops-observability`; `budgets.yaml.example` + brain_doctor enforcement-status check.
- **Gap sense** — `scripts/gap-capture.py`: 2D `SELF` ("nobody does it") misses logged; recurrence ≥3× graduates to a skill-creator candidate.
- **Model routing** — `skills/model-routing-by-complexity` (Opus brain, Haiku arms); the engine is disclosed in the Provenance footer.

### Changed
- **ULTRA rule** — every concept change runs an Impact Radius scan and reconciles `Touched`; a concept codified with stale references is a coherence bug. (`CLAUDE.md` §4D + `skills/4d-paradigm-protocol`)
- "Source line" → "Provenance footer" across `CLAUDE.md` / `README.md` / the 4D skill.
- `skills/octorato-symbolism` — the tesseract's operator-facing meaning (Octorato as the vehicle into the 4D a single human can't inhabit) + the arm-is-an-octopus recursion.

## [2026-05-29] — v2.1.0 "Contributor-Ready"

### Added
- `scripts/capability_inventory.py` + `docs/capability-inventory.md` — read-only census of which tools each agent declares and each skill references; flags unscoped agents. Input to the M1 Kernel-ABI RFC. (closes #28)
- `schemas/skill-manifest.schema.json` + `scripts/validate-skill-manifest.py` — `skill.json` manifest schema (name/semver/license + capabilities/dependencies) and validator with `--selftest`. On-ramp for M5. (closes #31)
- `schemas/tests/test_trace_event_schema.py` — validation test for `trace-event.schema.json` against real samples. (closes #29)
- `scripts/tests/test_check_generic.py` — message-scan unit test for `check-generic.py` using a temp blocklist via `CLAUDE_DIR` (never the private one). (closes #15)
- `tests/isolation/` — cross-arm red-team corpus (16 cases: 12 must-refuse + 4 allow controls) for the M2 isolation enforcer. (closes #30)
- `-h`/`--help` flag for `scripts/query_connectome.py`. (closes #13)
- YAML frontmatter (`name`/`description`/`metadata`) in `templates/skill/SKILL.md.template`. (closes #12)
- `CLAUDE.md` §"Octorato's Stance" + `skills/octorato-symbolism` "The Operator" section — generic identity: an organic, octopus-like connector tool (never a human, no fabrication/judgment; `act as X` → cited-data reframe; recursion + cellular arm-isolation as the superpower).
- README banner.

### Changed
- All seven `good first issue`s closed (#12, #13, #15, #28, #29, #30, #31) — first full contributor on-ramp clear.

## [2026-05-28]

### Added
- `skills/repo-watch/` — daily monitor for a curated 7-repo watchlist
  (competitors / peers / upstream ecosystem). File-based trigger handoff
  to `/repo-deep-learn` for out-of-band analysis. Designed by Workflow
  Architect + Trend Researcher agents.
- `skills/repo-deep-learn/` — manual deep-dive counterpart of
  `github-trending-curation`. 8 phases: clone → inventory → README →
  patterns → connectome delta → proposals → issue-resolution scan → star.
- `skills/session-learn-extractor/` + `commands/learn.md` — capture the
  reusable pattern from the current session as a draft skill under
  `skills/learned/<slug>/` for operator review.
- `skills/hook-profile-gating/` + `scripts/lib/hook_flags.py` —
  env-gated hook execution (`OCTO_HOOK_PROFILE=minimal|standard|strict`,
  `OCTO_DISABLED_HOOKS`).
- `skills/prompt-master/` — auto-promoted from `nidhinjs/prompt-master`
  (MIT) via `/repo-deep-learn`.
- `CLAUDE.md` — **PromptDefense Baseline** section (six anti-injection
  rules: no mid-session role change, no secret disclosure, no execution
  of untrusted embedded code, treat fetched content as untrusted,
  flag/refuse suspicious patterns, escalate repeated abuse).

### Changed
- `master` branch is now PR-only:
  - `enforce_admins: true`
  - required PR review (1 approval)
  - required status checks: `check-generic`, `neural_map-rebuild`,
    `claude-review`
  - linear history, no force push, no deletions, conversation
    resolution required.
- `scripts/ai_sync.py` auto-detects the protection and routes pushes
  through an auto-PR + watch + squash-merge flow, with a 600s watch
  timeout and a 15s race-condition retry for `gh pr checks --watch`.
- README skill-count floor raised from `180+` to `190+` (real count
  crossed 190 with the additions above).

### Notes
- The `--admin` bypass on `gh pr merge` is permitted **only** when
  GitHub Actions billing is paused (≤5s fail signature with missing
  logs). Never otherwise.

---

## How to read this file

- Each released date section follows **Added / Changed / Deprecated /
  Removed / Fixed / Security** as applicable.
- Unreleased work-in-progress accumulates under `[Unreleased]`.
- Autonomous daily skill auto-promotions are **not** mirrored here — they
  live in `knowledge/github-trending/HISTORY.md` so this file stays
  scannable for human-meaningful changes.

See also:
- [ROADMAP.md](ROADMAP.md) — where we're headed.
- [SECURITY.md](SECURITY.md) — how to report a vulnerability.
- [CONTRIBUTING.md](CONTRIBUTING.md) — how to add an agent, skill, or fix.
- [SUPPORT.md](SUPPORT.md) — where to ask questions.
