# Changelog

All notable changes to the Octopus Brain Framework are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
the project follows the **Site Semantic Versioning** scheme described in the
[Self-Growth wiki page](https://github.com/CarlosCaPe/octorato/wiki/Self-Growth#8-site-semantic-versioning)
, bot-identity commits bump PATCH, operator commits bump MINOR, and an
explicit `Octorato-Major:` commit trailer bumps MAJOR.

This log records human-meaningful framework changes. The complete
machine-generated growth ledger lives at
`knowledge/github-trending/HISTORY.md` (autonomous daily additions) and
`knowledge/repo-watch/<date>.md` (daily watchlist digests).

## [Unreleased]

## [2026-09-06]: v7.2.0
### Features
- feat(ci): version-bump heals CHANGELOG.md through an auto-merged bot PR (#268)
### Other
- docs(changelog): backfill v7.1.0 (#267)

## [2026-09-06]: v7.1.0
### Features
- feat(doctor): stale-merged-branches audit (#266)
### Other
- docs(changelog): promote the v7.0.0 notes from Unreleased to the dated entry (#265)

## [2026-09-06]: v7.0.0
**v7.0.0 "Nothing Ships Unverified"**

### The contract
An outward action (mail, chat, PR merge, deploy, release) leaves the brain only with machine receipts that a hook wrote in the harness process and a consumer re-verified against something the model does not own. v4 made an unwired rule a corruption; v6 made every gate prove it blocks; v7 makes a send without receipts impossible at the tool boundary, and states the residual plainly: the transcripts are files under HOME, so an anchor is a bar and a trail, never a proof. The only unforgeable boundary is the harness environment.
### Receipts (accumulated, v6.25.0 to v6.26.0)
- Receipt ledger (`scripts/receipt_ledger.py`, `~/.claude/.cache/receipts/`): seek receipts written by `r__posttool__receipt-seek.py` with the harness `tool_use_id`, honored only when that id names a real seek tool_use in the current turn; gate receipts written by `brain_doctor` on a clean tree, keyed on the git tree hash of `scripts/`, `registry/` and `hooks.json`; QA receipts written by `r__subagent-stop__qa-receipt.py` from a subagent's `QA-VERDICT` / `QA-SCOPE`, honored only from this session's subagent transcript with harness fields, last verdict, whole-token scope, QA persona.
- One outward-send gate (`g__pretool-mcp__outward-send.py`, PreToolUse on mail send/reply/forward, WhatsApp send, and Bash sends found by argv token): denies without a gate receipt, on an absence claim without a seek, on an unsourced attribute in a consent context, on a first-person promise, and on a Re:/Fwd: mail send without its thread. 35 violation and 14 benign fixtures, one per bypass five adversarial QA cycles demonstrated.
- `qa-merge-gate` requires a QA receipt for the PR on top of the operator's `OCTO_MERGE_APPROVE`; `.githooks/pre-push` runs `brain_doctor --gate-receipt`, so a push and a receipt are one event.
### Floor and triage
- Enforcement floor FORCED 27/27 gateable (100%), waivers 0: five formerly waived rules recorded as detector or reflex by design (`v7_decision`), `FLOW.budget-halt` promoted to fail-closed with path-scoped caps and a `spend_json` source; `waiver-age` voids any waiver undated or older than 90 days.
- `incident-fixture-coverage`: a memory naming a brain mechanism must resolve to a live script and, for a gate, a fixture pair. `fixture-seeds-tracked`: a fixture file git would not ship fails the doctor. `reflex-triage`: every recurrent lesson carries a decision in `registry/reflex-triage.yaml` (10 gate, 21 demote), zero pending.
- Hardening found on the way: git exports `GIT_DIR`/`GIT_INDEX_FILE` to hooks, so every doctor and selftest subprocess now scrubs them; `git update-index --assume-unchanged` no longer hides a gate edit.
### Release criterion (printed by brain_doctor at this tag)
Floor 100%, waived 0, 29 gate selftests live, incident-fixture coverage 100%, reflex-triage 0 pending, 41 checks passed.

## [2026-09-06]: v6.26.0
### Features
- feat(v7): reflex-triage decisions for every recurrent lesson (phase 5 to zero) (#263)
### Other
- docs(changelog): backfill v6.25.0 and v6.25.1 (#262)

## [2026-09-05]: v6.25.1
### Fixes
- fix(v7): ship the fixture seeds git was ignoring; doctor asserts every seed is tracked (#261)

## [2026-09-05]: v6.25.0
### Features
- feat(v7): receipt ledger, outward-send gate, QA receipt, waiver retirement, incident-fixture coverage (#260)
### Other
- docs(changelog): backfill v6.24.0 and v6.24.1 (#259)

## [2026-09-05]: v6.24.1
### Other
- docs(architecture): v7 plan, nothing ships unverified (#258)

## [2026-09-05]: v6.24.0
### Features
- feat(gate): block unsourced absence claims in outward drafts without a seek receipt (#257)
### Other
- docs(changelog): backfill v6.23.1 (#256)

## [2026-09-04]: v6.23.1
### Fixes
- fix(registry): single anchor line for Do-it-today; backfill CHANGELOG v6.23.0 (#255)
### Other
- docs(changelog): backfill v6.21.4 through v6.21.6 (#254)

## [2026-09-03]: v6.23.0
### Features
- feat(gate): block unsourced classifying attributes in outward drafts (#250)

## [2026-09-03]: v6.22.0
### Features
- feat(connectome): index life-memories as a third seekable graph (#248)

## [2026-09-03]: v6.21.6
### Fixes
- fix(connectome): fold accents in the tokenizer, on both sides (#249)

## [2026-09-03]: v6.21.5
### Fixes
- fix(security): resolve the leak blocklist from the main checkout, not the worktree (#252)

## [2026-09-02]: v6.21.4
### Fixes
- fix(memory): parse hookless compacted index entries (recall + corpus-coverage) (#247)

## [2026-09-01]: v6.21.3
### Fixes
- fix(fixtures): stop tracking derived wa-guardia selftest DBs (#245)

## [2026-09-01]: v6.21.2
### Fixes
- fix(gate): make the merge gate agent-proof (close self-approval hole) (#244)

## [2026-08-26]: v6.21.1
### Other
- brain-sync: per-chat bridge declaration + memory body-scoring recall (#243)

## [2026-08-26]: v6.21.0
### Features
- feat(gate): commit-msg English-only gate for the public octorato repo (#220)

## [2026-08-26]: v6.20.6
### Fixes
- fix(runners): install the extensionless bash twin on Windows (#240)

## [2026-08-26]: v6.20.5
### Fixes
- fix(release): changelog-only merges cut no tag; ai-sync heals drift (#239)

## [2026-08-26]: v6.20.4
Nothing yet: the next release harvests this section.

---

### Other
- chore(brain): ignore the local wrapper of the Chrome native host (#222)

## [2026-08-25]: v6.20.3
Nothing yet: the next release harvests this section.

---

### Other
- chore(brain): daily reflection (#242)

## [2026-08-24]: v6.20.2
Nothing yet: the next release harvests this section.

---

### Other
- reflection 24-Aug: absence proven by label, not by shape (#241)

## [2026-08-21]: v6.20.1
### Fixes
- fix(changelog): backfill releases v6.14.0 through v6.20.0 (#237)

## [2026-08-21]: v6.20.0
### Features
- feat(readme): hero terminal demo, real footage of doctor plus leak gate (#236)

## [2026-08-21]: v6.19.0
### Features
- feat(skill): gate lessons from the OpenBot runtime gateway (#235)

## [2026-08-21]: v6.18.0
### Features
- feat(skill): cross-link AstrBot sandbox and MCP client patterns (#234)

## [2026-08-21]: v6.17.7
### Other
- chore(brain): session reflection (#233)

## [2026-08-19]: v6.17.6
### Fixes
- fix(gate): goal anchor with a filter and regression fixtures (#232)

## [2026-08-19]: v6.17.5
### Fixes
- fix(impact-radius): filter worktrees, collapse directories, reject patterns as a concept (#231)

## [2026-08-19]: v6.17.4
### Other
- chore(brain): session close 2026-08-19 (#230)

## [2026-08-19]: v6.17.3
### Fixes
- fix(gates+doctor): three mechanisms that reported themselves live while blind (#227)

## [2026-08-18]: v6.17.2
### Other
- update: registry/fixtures/FLOW.wa-guardia-on-pending/home/.wa-fixture/con-espera.db, registry/fixtures/FLOW.wa-guardia-on-pending/home/.wa-fixture/humano-desde-el-telefono.db, registry/fixtures/FLOW.wa-guardia-on-pending/home/.wa-fixture/puente-sin-api-sends.db, registry/fixtures/FLOW.wa-guardia-on-pending/home/.wa-fixture/sin-espera.db (#229)

## [2026-08-18]: v6.17.1
### Fixed
- fix(ai-sync): co-tenancy is counted per **working tree and host**, not per session.
  Counting it per session punished exactly the sessions that had already isolated
  themselves, and its message told them to fork a worktree they were already in.
  `_is_repo()` now uses `git rev-parse --is-inside-work-tree`: ai-sync had refused to
  run inside a worktree, where `.git` is a file rather than a directory.
- fix(ai-sync): the semver tag **only moves on the trunk**. From a dimension branch it
  tagged a commit that the squash left orphaned, which is how tag v6.15.3 was cut and
  later withdrawn. Pushing from a branch now opens the PR instead of ending in silence.
- fix(check-generic): scans the **current tree**, not always `$HOME/.claude`. From a
  worktree it read an empty index and printed "clean, scanned 0 staged file(s)" with
  twelve files left unexamined.
- fix(wa-latido): measures and heals the bridge **where it lives**. After the cutover it
  kept reading the local replica, refreshed every 5 minutes, so the stamp never appeared
  inside the 40s window, and its healing started the local binary, cloning the WhatsApp
  session.
### Features
- feat(gate): `FLOW.do-it-today`: fail-closed Stop gate against deferring my own work.
  A pending item counts only when it is an irreducible operator step or a measured
  blocker, and in both cases it travels with its exact command.
- feat(wa-soporte): `--archivo` sends attachments through the support channel; the file
  travels to the bridge's own disk and both intermediate copies are always deleted,
  including when the send fails.
### Other
- docs(changelog): record the fixes made during the session (#228)

## [2026-08-18]: v6.17.0
### Features
- feat(wa-soporte): send attachments with --archivo (#226)

## [2026-08-18]: v6.16.0
### Features
- feat(gate): wire do-it-today as a fail-closed Stop gate (#225)

## [2026-08-18]: v6.15.4
### Fixes
- fix(ai-sync): co-tenancy per tree and host, and running inside a worktree (#224)

## [2026-08-18]: v6.15.2
### Fixes
- fix(wa-latido): measure and heal the bridge where it lives, not where it used to (#223)

## [2026-08-14]: v6.15.1
### Other
- reflection 14-Aug: access-is-not-attention, wire the trigger (#221)

## [2026-08-14]: v6.15.0
### Features
- feat(vigia): add whatsapp alert sink to wa-sin-respuesta (WA_VIGIA_CANAL=whatsapp) (#219)

## [2026-08-14]: v6.14.3
### Other
- reflection 14-Aug: confirmed-input-is-not-closure lesson (#218)

## [2026-08-12]: v6.14.2
### Fixes
- fix(memoria): read ALL entries in a compacted index line (#217)

## [2026-08-12]: v6.14.1
### Other
- brain: smaller resident index, silence watcher, and three new gates (#215)

## [2026-08-12]: v6.14.0
### Fixed
- fix(4d-protocol): Q2 skill matches CLAUDE.md: MCP-first, runtime-aware census.
### Features
- feat(4d): Provenance footer paths must be absolute and openable (#210)

## [2026-08-04]: v6.13.0
- No user-facing change beyond the version bump.

## [2026-08-04]: v6.12.6
### Other
- Track the bridge heartbeat and catch an unlinked account (#213)

## [2026-07-28]: v6.12.5
### Other
- brain: skill index diet + connectome walks the cold subtrees (#212)

## [2026-07-28]: v6.12.4
### Other
- reflection 2026-07-28: state the blind scope of a verification (#211)

## [2026-07-26]: v6.12.3
### Fixes
- fix(connectome): name cross-layer gaps for what they measure (#209)

## [2026-07-24]: v6.12.2
### Other
- reflect: send-ack-is-not-delivery lesson (#208)

## [2026-07-23]: v6.12.1
### Fixes
- fix(brain): stable manifest sort + backfill CHANGELOG v6.0.1..v6.3.0 (#192)

## [2026-07-23]: v6.12.0
### Features
- feat(brain): bulk-fetch delegation gate (turn ledger + Stop audit) (#207)

## [2026-07-23]: v6.11.0
### Features
- feat(brain): inject today's weekday as data in the 4D reminder (#206)

## [2026-07-20]: v6.10.0
### Features
- feat(brain): chat-context block-once gate on outbound chat sends (#205)

## [2026-07-20]: v6.9.0
### Features
- feat(brain): link /ai-sync and daily-reflection as one ritual (#204)

## [2026-07-17]: v6.8.1
### Other
- chore: session sync (hannon, mudanza, mascotas, responsivas) (#203)

## [2026-07-16]: v6.8.0
### Features
- feat: graphify deep-learn: code-graph skill + connectome shrink-guard (#202)

## [2026-07-13]: v6.7.3
### Other
- chore(brain): refresh connectome + CAPABILITIES after multi-runtime (#201)

## [2026-07-10]: v6.7.2
### Other
- sync (#200)

## [2026-07-10]: v6.7.1
### Fixed
- fix(finops): Grok `cache_r` for 4.3 / 4.20-* / build is **$0.20**/1M (docs.x.ai), not = input;
  Composer/GPT unknown engines report `$0` list instead of silent Sonnet fallback.
- fix(census): `capability-census.collect_mcps()` reads Cursor `.cursor/mcp.json` (user +
  workspace + parent walk) so Q2 is not Claude-file-only prose.
- fix(4d-protocol): Q2 skill matches CLAUDE.md: MCP-first, runtime-aware census.
- fix(routing): Cursor Task bindings prefer harness allow-list slugs; mark xAI API-only names.
- docs(multi-runtime): Honest gaps (Skill/Agent matcher drop, pricing TBD, allow-list ≠ API);
  Architecture wiki points at multi-runtime; tone "supported peer" not overclaim.
- chore(quickstart): project Cursor hooks + accept Cursor as a valid runtime prerequisite.

### Fixes
- fix(multi-runtime): Grok cache_r + Cursor MCP census + Q2 parity (#198)

## [2026-07-10]: v6.7.0
### Features
- feat(skills): agent-browser real-mouse protocol for React-class widgets; whatsapp-bridge outbound anti-spam discipline (#199)

## [2026-07-10]: v6.6.0
### Features
- feat(multi-runtime): Octorato is for **all models and all editors**. New canon
  `docs/architecture/multi-runtime.md`: brain vs runtime vs engine; growth rule
  (new editor/model = binding row, not a fork); Claude Code + Cursor first-class;
  Q2 MCP census is runtime-aware; identity = engine, OS = Octorato.
- feat(routing): model ladder is **tier-first, vendor-second** (mechanical · bulk ·
  build · judgment). Claude Code bindings unchanged (Haiku/Sonnet/Opus/Fable);
  Cursor+xAI bindings added (`composer-2.5-fast` / mid-Grok / `grok-4.5*` /
  strongest independent ≥ builder). Skill `model-routing-by-complexity` rewritten.
- feat(finops): `_pricing.py` meters xAI Grok list prices (grok-4.5, grok-4.3,
  grok-4.20-*, grok-build-0.1) alongside Anthropic; family heuristics for unknown
  Grok slugs.

### Changed
- docs(Getting-Started): prerequisites accept Claude Code **or** Cursor; Step 1
  documents `merge-hooks-cursor.py` for Cursor operators.
- docs(4D): Q2 no longer hard-requires `claude mcp list` inside Cursor sessions.
- chore(delegate-gate): nudge text uses vendor-agnostic tier names.

---

### Features
- feat(multi-runtime): wire Cursor+Grok as first-class peers (tier-first ladder, xAI pricing, runtime-aware Q2)

## [2026-07-10]: v6.5.0
### Features
- feat(client-doc-lint): fiscal-note (IVA) check + tax clause in cotizacion-legal-baseline (#196)

## [2026-07-07]: v6.4.1
### Fixes
- fix(ai-sync): empty-cycle guard + tree-always-returns-to-target invariant (#195)

## [2026-07-07]: v6.4.0
### Features
- feat(commands): add missing /ai-sync command (canonical sync had no invocable skill) (#194)

## [2026-07-07]: v6.3.1
### Other
- docs(skill): whatsapp bridge send-dial + liveness/verification gotchas (#193)

## [2026-07-06]: v6.3.0
### Features
- feat(brain): wire the deliverable-complete-before-send stop gate (no future-tense
  self-promises in paste-ready drafts) via `scripts/g__stop__draft-promise.py` (#191).

## [2026-07-06]: v6.2.0
### Features
- feat(brain): deliverable-complete-before-send stop gate for draft promises (initial wiring).

## [2026-07-02]: v6.1.0
### Features
- feat(templates): brand-neutral quote DOCX/PDF generator.

## [2026-07-02]: v6.0.1
### Other
- docs(changelog): backfill v5.9.1, v5.10.0, v6.0.0 via changelog-sync.

## [2026-07-02]: v6.0.0
- No user-facing change beyond the version bump.

## [2026-07-02]: v5.10.0
### Features
- feat(v6): "from coverage to enforcement": the gate-liveness harness. Every fail-closed
  gate now ships a `--selftest` that feeds it a `registry/fixtures/<rule-id>/violation.json`
  (must block) and `benign.json` (must allow) through its real main path; a shared
  `scripts/gate_selftest.py` runs both legs and the mandatory benign leg makes a
  block-everything gate FAIL, so gaming the harness is impossible.
- feat(doctor): new `gate-liveness` check runs every gate's selftest and a computed
  `enforcement-floor` ledger line (`FORCED N/M gateable (P%, selftest-proven) | detect-tier |
  waived | coverage`), never hand-edited, FAILing on a false fail-closed label. Floor moved
  from 11/19 (58%) to 14/20 (70%).
- feat(schema): `rules.schema.json` requires an `EXIT_CODE --selftest` proof for any
  fail-closed rule whose gate blocks a PreToolUse/Stop tool-call (wired-or-corrupt §8 risk 1).
- feat(G1): `CODE.cite-sources` promoted to a Stop block-once gate (provenance footer);
  waiver closed.
- feat(G2): `GIT.version-control` partial fail-closed gate (`g__pretool-bash__git-discipline.py`):
  deny force-push to main/master and `_old/_backup/_final/_copy` filenames.
- feat(G3): `FLOW.graph-before-grep` narrow fail-closed gate (deny recursive brain-content
  grep with no seek this turn; the 3 legit grep classes pass); waiver closed.
### Refactors
- refactor(relabel): `canon-heal`, `drift-self-heal`, `impact-radius` are DETECTORs not
  REFLEXes (they self-execute), each with a firing `--selftest`.
### Notes
- Deferred to a follow-up behind a telemetry week (false-positive risk): D1 injection-scan,
  D2 machine-register greeting detector, D5 no-pause proposal detector. The STAYS-REFLEX list
  (4D obedience, delegate verdicts, tool choice, identity, mood-inference) stays un-forced by
  design; coverage remains 100% and is never conflated with the 70% enforcement floor.

---

### Features
- feat(doctor+schema): gate-liveness check, enforcement-floor ledger, schema teeth
- feat(G3): FLOW.graph-before-grep narrow fail-closed gate
- feat(G2): GIT.version-control partial fail-closed gate
- feat(G1): CODE.cite-sources is now a fail-closed block-once gate
- feat(harness): gate-liveness fixtures + --selftest on the existing fail-closed gates
### Fixes
- fix(gates): strip env/command wrapper tokens before the git/gh anchor (QA HIGH)
### Other
- chore(manifest): regenerate docs/CAPABILITIES.md for v6 rules and scripts
- docs(v6): record the coverage-to-enforcement shift; close wired-or-corrupt risk 1
- test(harness): prove the prover: broken gate must FAIL the doctor
- refactor(relabel): canon-heal, drift-self-heal, impact-radius are DETECTORs not REFLEXes
- audit(registry): D4 dry-run-first is ask-on-narrow-trigger, residual documented

## [2026-07-02]: v5.9.1
### Other
- docs(changelog): backfill v5.8.0 and v5.9.0 from tags and releases
- docs(coverage): reconcile corpus-coverage prose to honest FAIL-armed 100%

## [2026-07-02]: v5.9.0
### Features
- feat(doctor): arm corpus-coverage teeth, FAIL on any uncovered rule
- feat(registry+doctor): wire skills canon + memory-directive class, honest corpus coverage
### Fixes
- fix(review): detector asserts full security canon + runs in doctor; preserve never-gives-up stance

## [2026-07-02]: v5.8.0
### Features
- feat(routing): model ladder v2, Opus build default, Fable pinned for all judgment
### Fixes
- fix(review): ladder coherence pass from QA findings
### Other
- docs(changelog): self-heal v5.7.0 entry via changelog-sync

## [2026-07-01]: v5.7.0
### Features
- feat(sync): publish-wiki mechanism, docs/wiki to the GitHub wiki on push
### Fixes
- fix(review): wiki publish fires only from master/main
- fix(docs): reconcile stale claims across README, wiki, hooks doc, roadmap
### Other
- docs(changelog): self-heal v5.6.0 entry via changelog-sync

## [2026-07-01]: v5.6.0
### Release self-heal
- New `scripts/changelog-sync.py`: reconciles missing CHANGELOG entries from semver tags, promoting the curated `[Unreleased]` body into the newest missing version and pulling GitHub Release notes (commit-subject fallback) for the rest. Dry-run by default, `--check` for CI, `--apply` idempotent.
- `brain_doctor --fix` repairs `release-drift` locally by running changelog-sync; the entry still lands through the normal PR flow.
- `brain-version-bump` prepends a non-empty `[Unreleased]` body to the GitHub Release notes, so the curated summary reaches the Release even when the CHANGELOG commit lags behind the tag.

## [2026-07-01]: v5.5.0
### Doctor teeth
- Waiver expiry enforced: a gateable fail-open rule whose `waiver.expires` is missing, unparseable, or past now counts as UNWAIVED and fails the meta-gate.
- `release-drift` is bidirectional: the newest semver tag ahead of the CHANGELOG top now WARNs (releases cut without entries), with tags sorted by semver.
- New `registry-anchor-ambiguity` check: a rule anchor that substring-covers another rule's anchor line, or covers 2+ anchor lines, WARNs with the ambiguous pairs.
- New `corpus-coverage` WARN-only Coverage Ledger: skills canon (ULTRA RULE / MANDATORY / NON-NEGOTIABLE) and memory feedback directives join the denominator, so coverage can no longer read 100% from CLAUDE.md headings alone.

### Gates fail closed
- `.githooks/pre-push`: missing gate inputs (lineage doctor, registry, capability manifest, Python interpreter) now block the push instead of silently skipping. A constitutional gate must never vanish silently.
- `qa-merge-gate.py`: a crash after a merge/publish path is identified exits 2 (fail-closed) instead of silently opening the gate.
- `secrets-grep-guard.py`: a bare pipe to jq/python/awk no longer counts as a redactor; only visible masking passes (sed/awk substitution, cut field selection, grep -o, an explicit redact script).

### Registry honesty
- check-generic.py rows remodeled: the PrePush mechanism is `.githooks/pre-push` (it inlines its own scan); check-generic.py fires via the ai-push runner.
- FLOW.budget-halt waiver reason corrected: budgets.yaml is active, every `action_on_breach` is `alert` by operator choice, so HARD_STOP is unreachable by config.
- COMMS.no-pause got its own distinct anchor; duplicate grafo-gate hook removed from hooks.json.

### Docs
- CHANGELOG backfilled v4.1.0 through v5.4.0; README badge and narration updated to the v4 registry + v5 manifest state; wired-or-corrupt.md phases marked shipped.

## [2026-06-29]: v5.4.0
- Waived the 7 known fail-open gateable rules with operator-signed, expiry-dated waivers so the meta-gate could arm.
- Armed the meta-gate teeth: any NEW gateable rule left fail-open and unwaived now FAILs and blocks the push.
- Propagated v5 manifest + gate + real budget-halt/digest across wiki, FAQ, whitepaper, and README.

## [2026-06-29]: v5.3.0
- Fail-closed meta-gate: `gateable: true` demands `enforcement: fail-closed` or an operator-signed waiver (#180).
- Classified the full rule corpus with explicit `gateable` flags; gate-shape is derived from the mechanism so omission cannot evade the gate.

## [2026-06-26]: v5.2.1
- Reflected v5 (capability manifest + gate) across README, wiki, FAQ, and whitepaper (#179).

## [2026-06-26]: v5.2.0
- Flipped capability-manifest freshness to a pre-push hard block, after cross-machine determinism was verified.

## [2026-06-26]: v5.1.0
- Scheduled the daily brain digest (slos / watchdog / finops) via a local systemd timer; it reads local session data, so no dataless CI cron.

## [2026-06-26]: v5.0.0
Release name: "Capability Manifest".

- One generated manifest: `docs/CAPABILITIES.md` is produced from the live capability set by `scripts/capability_manifest.py` and regenerated on every push; hand narration retired.
- Anti-regression gate: `brain_doctor` asserts the manifest is fresh, extending Wired or Corrupt from the rule corpus to every capability.
- FinOps budget halt wired for real: `budget-check.py` runs as a PreToolUse[Agent] gate, registered as `FLOW.budget-halt`.
- Counts reconciled to the brain's own rules (231 skills, 167 agents, 13 divisions); inflated counts were caught during review.
- Honest deferrals recorded: local-data digest needs a local schedule, and the pre-push hard block waited for determinism proof (landed in v5.2.0).

## [2026-06-25]: v4.3.1
- Declared the jsonschema dependency in requirements.txt and propagated it via ai-push (#175).

## [2026-06-25]: v4.3.0
- Cursor support: hooks.json is projected into the native `~/.cursor/hooks.json` (#174).

## [2026-06-25]: v4.2.1
- 4d-reminder fires last with the verdict ask at string end; dropped the duplicate grafo-turn-reset hook (#173).

## [2026-06-23]: v4.2.0
- `brain_doctor` closes the create-to-register loop (RULE #1 Phase 5): a new hook script lands together with its registry row (#172).

## [2026-06-23]: v4.1.1
- Documented the Wired or Corrupt (RULE #1) architecture everywhere (#171).

## [2026-06-23]: v4.1.0
- Phase 4b: bidirectional 100% anchor coverage (D4), drift self-heal, remaining gaps closed (#170).

## [2026-06-23]: v4.0.0
Release name: "Wired or Corrupt".

The brain stopped trusting its own prose. Most of CLAUDE.md was discipline the model could skip; only a small fraction had a real reflex. RULE #1 inverts that. Every rule must be wired, an unwired rule means the brain is CORRUPT, and brain_doctor enforces it. A missing mechanism blocks the push. No exceptions.

### Added: the registry

- **RULE #1 (constitutional keystone)**: every CLAUDE.md rule maps to a live mechanism in `registry/rules.yaml`, or the brain is CORRUPT. Self-wired: its own mechanism is `brain_doctor`, invoked from `.githooks/pre-push`. (`CLAUDE.md` §"RULE #1", `docs/architecture/wired-or-corrupt.md`)
- **The rule registry**: `registry/rules.yaml` (42 rules, 100% of CLAUDE.md anchors covered) + `registry/rules.schema.json`, validated like skill manifests.
- **brain_doctor enforcement**: D0 bootstrap self-check, D1 schema, D2 anchors (both directions, fail-closed), D3 per-rule wiring, a printed Coverage Ledger, and a `--registry` gate the pre-push runs. Kills the phantom-script class: a documented-but-absent hook can no longer ship.
- **OO mechanism hierarchy**: `Gate`/`Reflex`/`Detector`/`Presence` with polymorphic `verify()`; the Presence-escape-hatch closed in the schema so a model-behavior label cannot dodge a real gate.
- **Hook-naming policy**: `registry/naming-policy.yaml`. New hook scripts must follow `<prefix>__<event>__<slug>.py` (prefix agrees with kind); the 18 existing scripts are grandfathered, zero churn.

### Fixed

- **The drift defect**: `brain-memory-recall.py`, the brain's life-memory reflex, was documented as wired but never fired because the live `settings.json` had drifted from the tracked `hooks.json`. Reconciled via `merge-hooks.py`. The reflex is live and surfacing memories again.

## [2026-06-23]: v3.24.0
### Features
- feat(brain): Phase 3: hook-naming convention + grandfather (rename dropped) (#168)

## [2026-06-23]: v3.23.0
### Features
- feat(brain): Phase 2: OO mechanism hierarchy + schema hardening (#167)

## [2026-06-23]: v3.22.0
### Features
- feat(brain): Phase 1: Wired or Corrupt 100% coverage + fail-closed (#166)

## [2026-06-23]: v3.21.0
### Features
- feat(brain): Phase 0: Wired or Corrupt (RULE #1 registry + brain_doctor gate) (#165)

## [2026-06-20]: v3.20.0
### Features
- feat(brain): track brain-memory-recall + arm-recall hooks in hooks.json; compress MEMORY.md index (#164)

## [2026-06-20]: v3.19.0
### Features
- feat(brain): add brain-memory-recall UserPromptSubmit hook (#163)

## [2026-06-19]: v3.18.0
### Features
- feat(brain): add ownership-by-authorship skill (ownership = git authorship, not repo location) (#162)

## [2026-06-18]: v3.17.1
### Fixes
- fix(hook): inbox-sweep uses in:all (includes Spam and Trash) (#161)

## [2026-06-18]: v3.17.0
### Features
- feat(brain): arm-recall UserPromptSubmit hook (arm-side twin of connectome-heartbeat) (#158)

## [2026-06-18]: v3.16.0
### Features
- feat(brain): no-pause hook also catches ask-permission-to-continue endings (#159)

## [2026-06-18]: v3.15.0
### Features
- feat(brain): ULTRA RULE: adversarially verify the operator, never accept a claim on his word (#160)

## [2026-06-17]: v3.14.1
### Fixes
- fix(cadence): rule 6 flattery openers (good/great question, thanks all, good news) + rule 12 happy-to closings (#157)

## [2026-06-16]: v3.14.0
### Features
- feat(hooks): add inbox-sweep-reflex UserPromptSubmit hook (#155)
### Fixes
- fix(brain): harden core from Opus self-review (leak, secrets-guard, drift, dupe) (#156)

## [2026-06-14]: v3.12.0
### Features
- feat(brain): 4 reflex hooks: secrets guard, config-ship verify, claim-verify stop, cadence machine-register rules (#154)

## [2026-06-14]: v3.11.0
### Features
- feat(brain): capability-census UserPromptSubmit hook (#153)

## [2026-06-13]: v3.10.1
### Other
- chore(canon): re-render stale skill/agent counts (220+ -> 230+) (#151)

## [2026-06-13]: v3.10.0
### Features
- feat(brain): ULTRA RULE: machine register, no human-social filler (#152)

## [2026-06-13]: v3.9.1
### Other
- chore(funding): add GitHub Sponsors handle to FUNDING.yml (#150)

## [2026-06-13]: v3.9.0
### Features
- feat(brain): daily-reflection skill: honest session retro that becomes a reflex (#149)

## [2026-06-12]: v3.8.4
### Other
- docs(memory): complete the bio-trio: immune system (learning) + ant stigmergy (coordination) (#145)

## [2026-06-12]: v3.8.3
### Other
- docs(brain): add capture-ends-with-triage skill (#148)

## [2026-06-12]: v3.8.2
### Other
- Feat/skills batch 2026 06 12 (#147)

## [2026-06-12]: v3.8.1
### Other
- docs: broaden "arm" to any sealed world + wire the first-user funnel (#146)

## [2026-06-11]: v3.8.0
### Features
- feat(brain): first-user quickstart: zero-to-alive in one command + broaden the arm framing (#143)

## [2026-06-11]: v3.7.1
### Other
- docs(readme): reposition the top to the broad-but-sharp pitch (an *octorato*, the brain layer) (#144)

## [2026-06-11]: v3.7.0
### Features
- feat(brain): ai-sync: canonical race-safe reconcile (pull --rebase then push) (#142)

## [2026-06-11]: v3.6.1
### Other
- docs(brain): add verify-generated-config-identifiers skill (#140)

## [2026-06-11]: v3.6.0
### Features
- feat(brain): two stakeholder-comms skills (teams-ready-message + verify-root-cause) (#127)

## [2026-06-11]: v3.5.1
### Other
- chore(brain): repo-watch +aitmpl, social-video-mining TikTok gotcha (#141)

## [2026-06-11]: v3.5.0
### Features
- feat(skills): snowflake-dbt-pitfalls + tramite-mx-assistant (#139)

## [2026-06-10]: v3.4.1
### Other
- ci(brain): bump semver autolabel on every merge to master (#138)

## [2026-06-10]: v3.4.0
### Features
- feat(brain): whatsapp-mcp bridge gotchas (403 directpath fix + install lessons) (#135)
- feat(brain): ULTRA RULE: do it right, not fast (root cause over palliative) (#134)
- feat(brain): extend dimension isolation to arms (broad-stage gate + worktree-init --repo) (#133)
- feat(brain): client-doc-lint reflex + cotizacion-legal-baseline (#132)
- feat(brain): emit GitHub Release + queued news draft on version bump (#130)
### Other
- docs(learn): correct stale gitignore note in /learn command (#131)

## [2026-06-09]: v3.3.0
### Features
- feat(brain): auto semver label + 3 upward-learning skills (#128)
- feat(brain): news-article-curation skill + /news-promote (inbound learning loop); fix connectome dedup parsing agents instead of skills (#126)
### Other
- docs(skill): harmonize model-routing rubric with Anthropic Claude model family table (#129)

## [2026-06-06]: v3.2.0
### Features
- feat(brain): submission-checklist-gate skill, completeness audit for outbound formal submissions (#125)
- feat(brain): octopus ganglia: reflexes-over-discipline skill + Q2 MCP-first actionable + restore Windows graph seek (#124)
- feat(brain): canary-symbiont skill, the cross-plane sentinel pattern (#121)
- feat(brain): adopt session-isolation + cadence hook wiring into hooks.json canon (#118)
- feat(brain): wiki anatomy F1-F5, skill promotions, memory-sync mechanism, dead-cell detection (#116)
- feat(brain): cadence stop-hook: the 10 no-rules enforced on CHAT replies (#117)
- feat(brain): structural session isolation + cadence lint (#115)
- feat(brain): unlock-suggestion ULTRA rule (Disclose-time twin of ☠ Prune) (#114)
- feat(brain): lane enforcement: first-writer claims, agent-proof deny on cross-dimension writes (#112)
- feat(graph): arm-level lineage graphs: every arm carries its own sealed seek (#110)
- feat(brain): 1+N two-tier memory + graph dead-cell detection + stat-floor fixes (#109)
- feat(brain): promote 3 learned skills (agent-proof-gate · command-boundary-matching · stacked-pr-gotcha) (#106)
- feat(brain): light the session-isolation lineage edge (seek > grep) (#107)
- feat(brain): inc-2b: live graph-before-grep teeth: PreToolUse grafo-gat (#94)
- feat(brain): ai-push co-tenancy guard, abort when another live session shares the tree (#104)
### Fixes
- fix(brain): teach install-runners to drop a Windows python3 shim (closes B3) + doc --floor (closes B2) (#123)
- fix(brain): Windows-portability of pre-push lineage check (sparse-checkout + python3 stub) + ask-with-recommendation skill (#122)
- fix(brain): repo-scope the qa-merge-gate: only protected repos are gated (#120)
- fix(brain): hooks.json timeouts within schema max (5s) (#119)
- fix(brain): harden ai-push co-tenancy guard with a conservative grace window (#108)
### Other
- ci(brain): counts-render drift guard + brain-ci lineage edge (#113)
- docs(brain): re-render stat floors after today's PR-merged work (209 skills live) (#111)

## [2026-06-02]: v3.1.0
Release name: "Reflexes".

Major step: the brain moved from **sensing** itself (3.0 Proprioception) to **enforcing** itself: principles became involuntary reflexes wired as hooks, not advisory prose the model can skip. And it learned to run as **one self across many parallel dimensions**.

### Added: reflexes
- **Connector verdict, enforced**: the 2D Delegate verdict is inverted: **SELF is the rare exception, the default is CONNECT** (LOAD/ACTIVATE). The agent is a connector to real sources, not an encyclopedia; SELF fires only when the operator explicitly asks for an opinion. (`scripts/delegate-check`, `scripts/query_connectome.py`, `CLAUDE.md` §2D)
- **Delegation reflex**: `scripts/delegate-gate.py` (PreToolUse, fail-open): nudges substantive/batchable work toward the cheapest sufficient model (Haiku/Sonnet/Opus) instead of the main loop.
- **QA merge gate**: `scripts/qa-merge-gate.py` (PreToolUse, fail-closed): no publish-to-main without an operator approval the **agent provably cannot self-grant** (PR-scoped `OCTO_MERGE_APPROVE` env: an inline env never reaches the harness-run hook: or `octo-dim approve-merge`). Detection is **command-boundary-anchored** so it gates real invocations, not mentions in quoted args.
- **Dimension awareness**: `scripts/dimension-awareness-hook.py` (PreToolUse, fail-open): warns when other live sessions share the working tree.

### Added: 4D session dimensions
- **One tentacle, N parallel dimensions**: `scripts/octo-dim.py` (register / heartbeat / list / prune / worktree-init / approve-merge) + a blackboard registry (`connectome/sessions.json`, gitignored): the same session-id runs in isolated git worktrees, reconciled into one `.git`. Isolation is the enabler of the 4D superpower, not a constraint. (`skills/session-isolation`)
- **Human-cadence delivery rules**: `skills/human-cadence`.

### Added: architecture
- **Hook orchestration, formalized + cited**: `docs/architecture/hook-orchestration.md`: a **Reactive Control Architecture with Adaptive Recall** (ECA atoms · Behavior-Tree priority · Statechart 4D · Spreading-Activation recall · Marr–Albus control loop · contextual-bandit tier-routing). L4 bandit router + activation-decay connectome are specified as the next build, not yet implemented.
- **Release/news cadence sense**: `brain_doctor` check `release-drift`: flags a top CHANGELOG version with no matching git tag (the gap that left v3.0.0 documented-but-unreleased). News is the brain's top-of-funnel reflex: a bump with no news = lost reach.

### Changed
- `brain_doctor` assertion count converged (`CLAUDE.md`) and the doctor grew to 15 checks (lineage-sound, release-drift).
- The qa-merge-gate enforces a hard rule now in `CLAUDE.md` §2D: the agent cannot self-approve its own merge gate.

## [2026-06-01]: v3.0.0
Release name: "Proprioception".

Major: the brain grew new **organs**: cross-cutting faculties that govern *how* every arm acts: not just arms (skills). It moved from **reactive to reflexive**: it now senses and coordinates itself.

### Added: organs
- **Proprioception**: the one-line **Provenance footer** (Basis · Engine · Touched · Verified) ends every response: the brain sensing its own action. (`scripts/4d-reminder.py`, `scripts/source-attribution-check.py`)
- **The reflective WHILE**: 4D codified as a loop, not a one-shot: `while (open / remnants / Touched≠intent): 4D()`; exit on reconciliation, never on "looks done". (`skills/4d-paradigm-protocol`)
- **The cerebellum**: precision without tremor: feedforward Manifest (enumerated target) ⇄ binary `Touched` reconcile ⇄ involuntary firing. `scripts/impact-radius.py` (tool) + `scripts/impact-radius-hook.py` (PostToolUse `Write|Edit` reflex). Closes the #1 recurrent failure: codify-in-one-place / leave-refs-stale ("pixelation") and its twin, touching or creating more than needed.
- **Metabolic sense (FinOps)**: `scripts/finops-digest.py` (per-arm $, routing KPI vs all-Opus, est-vs-billed), `scripts/cost-vs-change.py` (marginal cost of each new capability), folded into `brain-digest.py`; `skills/finops-observability`; `budgets.yaml.example` + brain_doctor enforcement-status check.
- **Gap sense**: `scripts/gap-capture.py`: 2D `SELF` ("nobody does it") misses logged; recurrence ≥3× graduates to a skill-creator candidate.
- **Model routing**: `skills/model-routing-by-complexity` (Opus brain, Haiku arms); the engine is disclosed in the Provenance footer.

### Changed
- **ULTRA rule**: every concept change runs an Impact Radius scan and reconciles `Touched`; a concept codified with stale references is a coherence bug. (`CLAUDE.md` §4D + `skills/4d-paradigm-protocol`)
- "Source line" → "Provenance footer" across `CLAUDE.md` / `README.md` / the 4D skill.
- `skills/octorato-symbolism`: the tesseract's operator-facing meaning (Octorato as the vehicle into the 4D a single human can't inhabit) + the arm-is-an-octopus recursion.

## [2026-05-29]: v2.1.0
Release name: "Contributor-Ready".

### Added
- `scripts/capability_inventory.py` + `docs/capability-inventory.md`: read-only census of which tools each agent declares and each skill references; flags unscoped agents. Input to the M1 Kernel-ABI RFC. (closes #28)
- `schemas/skill-manifest.schema.json` + `scripts/validate-skill-manifest.py`: `skill.json` manifest schema (name/semver/license + capabilities/dependencies) and validator with `--selftest`. On-ramp for M5. (closes #31)
- `schemas/tests/test_trace_event_schema.py`: validation test for `trace-event.schema.json` against real samples. (closes #29)
- `scripts/tests/test_check_generic.py`: message-scan unit test for `check-generic.py` using a temp blocklist via `CLAUDE_DIR` (never the private one). (closes #15)
- `tests/isolation/`: cross-arm red-team corpus (16 cases: 12 must-refuse + 4 allow controls) for the M2 isolation enforcer. (closes #30)
- `-h`/`--help` flag for `scripts/query_connectome.py`. (closes #13)
- YAML frontmatter (`name`/`description`/`metadata`) in `templates/skill/SKILL.md.template`. (closes #12)
- `CLAUDE.md` §"Octorato's Stance" + `skills/octorato-symbolism` "The Operator" section: generic identity: an organic, octopus-like connector tool (never a human, no fabrication/judgment; `act as X` → cited-data reframe; recursion + cellular arm-isolation as the superpower).
- README banner.

### Changed
- All seven `good first issue`s closed (#12, #13, #15, #28, #29, #30, #31): first full contributor on-ramp clear.

### Added (shipped 2026-05-28, between v2.0.0 and v2.1.0)
- `skills/repo-watch/`: daily monitor for a curated 7-repo watchlist
  (competitors / peers / upstream ecosystem). File-based trigger handoff
  to `/repo-deep-learn` for out-of-band analysis. Designed by Workflow
  Architect + Trend Researcher agents.
- `skills/repo-deep-learn/`: manual deep-dive counterpart of
  `github-trending-curation`. 8 phases: clone → inventory → README →
  patterns → connectome delta → proposals → issue-resolution scan → star.
- `skills/session-learn-extractor/` + `commands/learn.md`: capture the
  reusable pattern from the current session as a draft skill under
  `skills/learned/<slug>/` for operator review.
- `skills/hook-profile-gating/` + `scripts/lib/hook_flags.py` ,
  env-gated hook execution (`OCTO_HOOK_PROFILE=minimal|standard|strict`,
  `OCTO_DISABLED_HOOKS`).
- `skills/prompt-master/`: auto-promoted from `nidhinjs/prompt-master`
  (MIT) via `/repo-deep-learn`.
- `CLAUDE.md`: **PromptDefense Baseline** section (six anti-injection
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

## [2026-05-25]: v2.0.0
### Features
- feat(brain): product showcase + 4D-reminder & source-attribution hooks
- feat(workflow): staged-promotion model: test integration branch → weekly master
- feat(brain): stats-drift guard wired into ai-push
- feat(brain): auto-promoted claude-plugins-official skill + UA fix + growth ledger
- feat(brain): github-trending-curation skill + /trending-promote + brain-discovery spec (generic-safe)
- feat(skills): wrangler-installed CF/Workers skills bundle + runtime gitignore
- feat(hook): no-pause-suggestion Stop hook: block 'leave for tomorrow/take a break' framing
- feat(skills): bug-hunter adversarial QA gate (Hunter→Skeptic→Referee) + demote single-shot Reality Checker to specialist
- feat(skill): add schema-as-code-three-layer-sync: canonical discipline for ER/DD/Code alignment
- feat(skills): add inbox-triage-classifier + lessons in browser-bearer & phi-aware
- feat(brain): add .githooks/pre-push enforcement layer
- feat(skills): add canonical operator-time mandates
- feat(skills): add execution-bias: don't defer in auto-mode, ship now
- feat(skill): add pre-merge-qa-gate + cross-ref from 4d-paradigm-protocol
- feat(skill): add ado-pr-merge-via-api
- feat(brain): add stripe-payments skill (tiers + key hygiene + MCP + CLI + CF webhooks)

### Fixes
- fix(hooks): default source line to English for non-EN/ES/DE input
- fix(hooks): neutral source noun per locale: Source/Fuente/Quelle (EN/ES/DE)
- fix(hooks): source line must match input language (EN/ES), not hardcoded Spanish
- fix(hooks): make source-attribution Stop check advisory-only (no false blocks)
- fix(hooks): tolerate transcript flush race in source-attribution Stop check
- fix(trending-promote): enforce content quality bar; stop dumping raw GitHub taglines

### Docs
- docs(brain): add dataqbs Facebook page link to README
- docs(brain): add README badges, launch-article link, demo placeholder
- docs: align wiki/registry layer to exact 152/189/13
- docs(readme): round ALL count references to floors (full alignment)
- docs(readme): round headline figures to stable floors (180+/150+)
- docs(wiki): custom footer: product + CV + sponsor/donate on every page
- docs(wiki): comprehensive Octorato wiki: 14 pages, 10 specialists + 2 reviews
- docs(community): SECURITY, CODE_OF_CONDUCT, PR + issue templates
- docs(brain): README self-growth section + connectome regen + traffic-title fix

### Other
- metrics: traffic snapshot 2026-05-24
- metrics: traffic snapshot 2026-05-23
- metrics: traffic snapshot 2026-05-22
- sync-ai-docs.ps1: PS 5.1 compat: chain 2-arg Join-Path (variadic is PS7+)
- chore(funding): point GitHub Sponsor button to dataqbs.com/donate
- metrics: traffic snapshot 2026-05-21
- chore(funding): point GitHub Sponsor button to Stripe PL directly

## [2026-05-20]: v1.0.0
Initial public release of the brain.

### Features
- feat(brain): add repomix-codebase-packer skill + FUNDING.yml (v1.0.0 prep)
- feat(brain): add octorato symbolic layer (#7)
- feat(brain): ship Claude Cowork integration shape as quarantined pseudo-arm (#6)
- feat(finops): Anthropic Enterprise Analytics API ingest (Feature 4/4) (#4)
- feat(finops): budget caps + PreToolUse halt mechanism (Feature 3/4) (#3)
- feat(finops): cost-spike watchdog (Feature 2/4) (#2)
- feat(finops): per-arm cost rollup + USD conversion (1/4) (#1)
- feat(positioning): pivot README to FinOps for AI agents + brain-pr-checks workflow
- feat(skills): batch-import-relative-paths: sed batch-imports w/ variable depth hide silently in Vite/esbuild
- feat(skills): 4 new skills from operational lessons (sentinel-blocks-rerun, horizontal-scroll-html-vs-body, fb-carousel-cap-4, pr-first-on-auto-deploy-main)
- feat(skill): sentinel-blocks-rerun: diagnose daily-idempotent no-op
- feat(skills): pages-function-checkpoint-debug + tiered-rotation extension
- feat(brain): Phase D Ports 6 + 7: Incident Capture & Brain Synthetics (closes Datadog spec 8/8)
- feat(brain): Phase C Port 8: Brain Charts on Demand (closes Phase C)
- feat(brain): Phase C Port 5: Brain Digest (daily markdown dashboard)
- feat(brain): Phase B Port 3: Brain SLOs (closes Phase B)
- feat(brain): Phase B Port 2: Skill Cost Profiler (turn-level attribution)
- feat(brain): Phase B Port 4: Watchdog MVP (cliff + quality drops from traces)
- feat(brain): add cache-bust-deploy-validation skill
- feat(skills): 2 new skills from real_estate session
- feat(brain): Phase A task #7: Hebbian update from traces (Phase A done)
- feat(brain): Phase A task #6: trace.py CLI query helper (read-only)
- feat(obs): scripts/trace.py: Datadog Port 1 query helper
- feat(brain): Phase A task #5: phase_boundary heuristic via lifecycle proxy
- feat(hooks): trace-hook extracts token usage from tool_response when exposed
- feat(brain): Phase A task #3: skill_fire capture hook (Port 1 first telemetry)
- feat(brain): add Phase A trace event schema + validating samples
- feat(hooks): add readme-sync soft-block to pre-commit
- feat(brain): social-video digest worker + .gitignore for worker outputs
- feat(brain): add Universal reflexes (Tier A) to Skill-First Behavior
- feat(skills): add 8 OSS-replacement and technique skills
- feat(metrics): daily octorato traffic watcher with spike alerts
- feat(brain): add summarize-100 skill
- feat(skills): add claude-usage-report: token/cost aggregator over local JSONL logs
- feat(migration): self-heal origin dotclaude→octorato + migration script + README section
- feat(skill): schema-row-counts: exact row counts per table for PostgreSQL/MSSQL/Databricks

### Fixes
- fix(traffic-watch): use OCTORATO_PAT: Traffic API needs Administration scope

### Docs
- docs(readme): flip FinOps roadmap: all 4 in-flight items shipped (#5)
- docs(brain): scrub inspiration-source references from README + observability layer
- docs(brain): add Self-Awareness block: ~/.claude/ IS octorato
- docs(brain): Datadog spec 8/8 shipped: flip README roadmap to "all shipped"
- docs(brain): add Observability section + update Repository Structure for Datadog Port 1
- docs(brain): Phase A task #2: trace storage layout + gitignore traces/
- docs(readme): add Synapses, Memory, Reflexes sections + glia/afferent framing
- docs: bump skill count 142 → 153 in README

### Other
- chore(brain): add FUNDING.yml: custom donate link dataqbs.com/donate
- metrics: traffic snapshot 2026-05-20
- refactor(brain): slim CLAUDE.md from 557 to 226 lines (60% reduction) (#8)
- security(brain): enforce no SDD artifacts at brain root
- metrics: traffic snapshot 2026-05-19
- metrics: traffic snapshot 2026-05-19
- refactor(brain): extract _brain_obs.py + rename trace→brain-trace, chart→brain-chart
- chore: drop tracked policy-limits.json (machine-local state, not source of truth)
- chore(brain): ignore paste-cache/ runtime dir
- Octopus Brain Framework v0.1.1

---

## How to read this file
- Each released date section follows **Added / Changed / Deprecated /
  Removed / Fixed / Security** as applicable.
- Unreleased work-in-progress accumulates under `[Unreleased]`.
- Autonomous daily skill auto-promotions are **not** mirrored here: they
  live in `knowledge/github-trending/HISTORY.md` so this file stays
  scannable for human-meaningful changes.

See also:
- [ROADMAP.md](ROADMAP.md): where we're headed.
- [SECURITY.md](SECURITY.md): how to report a vulnerability.
- [CONTRIBUTING.md](CONTRIBUTING.md): how to add an agent, skill, or fix.
- [SUPPORT.md](SUPPORT.md): where to ask questions.
