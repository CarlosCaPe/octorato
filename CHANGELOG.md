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
- chore(brain): ignorar el wrapper local del native host de Chrome (#222)

## [2026-08-25]: v6.20.3
Nothing yet: the next release harvests this section.

---

### Other
- chore(brain): daily reflection (#242)

## [2026-08-24]: v6.20.2
Nothing yet: the next release harvests this section.

---

### Other
- reflexión 24-ago: ausencia probada por label, no por forma (#241)

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
- fix(gate): ancla de objetivo con filtro y fixtures de regresion (#232)

## [2026-08-19]: v6.17.5

### Fixes
- fix(impact-radius): filtra worktrees, colapsa directorios y rechaza patrones como concepto (#231)

## [2026-08-19]: v6.17.4

### Other
- chore(brain): cierre de sesion 2026-08-19 (#230)

## [2026-08-19]: v6.17.3

### Fixes
- fix(gates+doctor): tres mecanismos que se reportaban vivos estando ciegos (#227)

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
- feat(gate): `FLOW.do-it-today`: Stop gate fail-closed contra aplazar trabajo propio.
  Un pendiente solo vale si es un paso irreducible del operador o un bloqueo medido, y
  en ambos casos viaja con su comando exacto.
- feat(wa-soporte): `--archivo` sends attachments through the support channel; the file
  travels to the bridge's own disk and both intermediate copies are always deleted,
  including when the send fails.
### Other
- docs(changelog): registrar los arreglos de la sesion (#228)

## [2026-08-18]: v6.17.0

### Features
- feat(wa-soporte): mandar adjuntos con --archivo (#226)

## [2026-08-18]: v6.16.0

### Features
- feat(gate): cablear do-it-today como Stop gate fail-closed (#225)

## [2026-08-18]: v6.15.4

### Fixes
- fix(ai-sync): co-tenencia por arbol y host, y correr dentro de un worktree (#224)

## [2026-08-18]: v6.15.2

### Fixes
- fix(wa-latido): measure and heal the bridge where it lives, not where it used to (#223)

## [2026-08-14]: v6.15.1

### Other
- reflection 14-ago: access-is-not-attention, wire the trigger (#221)

## [2026-08-14]: v6.15.0

### Features
- feat(vigia): add whatsapp alert sink to wa-sin-respuesta (WA_VIGIA_CANAL=whatsapp) (#219)

## [2026-08-14]: v6.14.3

### Other
- reflection 14-ago: confirmed-input-is-not-closure lesson (#218)

## [2026-08-12]: v6.14.2

### Fixes
- fix(memoria): read ALL entries in a compacted index line (#217)

## [2026-08-12]: v6.14.1

### Other
- brain: índice residente más chico, vigía de silencio, y tres gates nuevos (#215)

## [2026-08-12]: v6.14.0

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
### Features
- feat(multi-runtime): Octorato is for **all models and all editors**. New canon
  `docs/architecture/multi-runtime.md`: brain vs runtime vs engine; growth rule
  (new editor/model = binding row, not a fork); Claude Code + Cursor supported peers;
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
- feat(4d): Provenance footer paths must be absolute and openable (#210)

## [2026-08-04]: v6.13.0
### Fixed
- fix(finops): Grok `cache_r` for 4.3 / 4.20-* / build is **$0.20**/1M (docs.x.ai), not = input;
  Composer/GPT unknown engines report `$0` list instead of silent Sonnet fallback.
- fix(census): `capability-census.collect_mcps()` reads Cursor `.cursor/mcp.json` (user +
  workspace + parent walk) so Q2 is not Claude-file-only prose.
- fix(4d-protocol): Q2 skill matches CLAUDE.md — MCP-first, runtime-aware census.
- fix(routing): Cursor Task bindings prefer harness allow-list slugs; mark xAI API-only names.
- docs(multi-runtime): Honest gaps (Skill/Agent matcher drop, pricing TBD, allow-list ≠ API);
  Architecture wiki points at multi-runtime; tone "supported peer" not overclaim.
- chore(quickstart): project Cursor hooks + accept Cursor as a valid runtime prerequisite.

### Features
- feat(multi-runtime): Octorato is for **all models and all editors**. New canon
  `docs/architecture/multi-runtime.md` — brain vs runtime vs engine; growth rule
  (new editor/model = binding row, not a fork); Claude Code + Cursor supported peers;
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

## [2026-08-04]: v6.12.6
### Fixed
- fix(finops): Grok `cache_r` for 4.3 / 4.20-* / build is **$0.20**/1M (docs.x.ai), not = input;
  Composer/GPT unknown engines report `$0` list instead of silent Sonnet fallback.
- fix(census): `capability-census.collect_mcps()` reads Cursor `.cursor/mcp.json` (user +
  workspace + parent walk) so Q2 is not Claude-file-only prose.
- fix(4d-protocol): Q2 skill matches CLAUDE.md — MCP-first, runtime-aware census.
- fix(routing): Cursor Task bindings prefer harness allow-list slugs; mark xAI API-only names.
- docs(multi-runtime): Honest gaps (Skill/Agent matcher drop, pricing TBD, allow-list ≠ API);
  Architecture wiki points at multi-runtime; tone "supported peer" not overclaim.
- chore(quickstart): project Cursor hooks + accept Cursor as a valid runtime prerequisite.

### Features
- feat(multi-runtime): Octorato is for **all models and all editors**. New canon
  `docs/architecture/multi-runtime.md` — brain vs runtime vs engine; growth rule
  (new editor/model = binding row, not a fork); Claude Code + Cursor supported peers;
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

### Other
- Track the bridge heartbeat and catch an unlinked account (#213)

## [2026-07-28]: v6.12.5
### Fixed
- fix(finops): Grok `cache_r` for 4.3 / 4.20-* / build is **$0.20**/1M (docs.x.ai), not = input;
  Composer/GPT unknown engines report `$0` list instead of silent Sonnet fallback.
- fix(census): `capability-census.collect_mcps()` reads Cursor `.cursor/mcp.json` (user +
  workspace + parent walk) so Q2 is not Claude-file-only prose.
- fix(4d-protocol): Q2 skill matches CLAUDE.md — MCP-first, runtime-aware census.
- fix(routing): Cursor Task bindings prefer harness allow-list slugs; mark xAI API-only names.
- docs(multi-runtime): Honest gaps (Skill/Agent matcher drop, pricing TBD, allow-list ≠ API);
  Architecture wiki points at multi-runtime; tone "supported peer" not overclaim.
- chore(quickstart): project Cursor hooks + accept Cursor as a valid runtime prerequisite.

### Features
- feat(multi-runtime): Octorato is for **all models and all editors**. New canon
  `docs/architecture/multi-runtime.md` — brain vs runtime vs engine; growth rule
  (new editor/model = binding row, not a fork); Claude Code + Cursor supported peers;
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

### Other
- brain: skill index diet + connectome walks the cold subtrees (#212)

## [2026-07-28]: v6.12.4
### Fixed
- fix(finops): Grok `cache_r` for 4.3 / 4.20-* / build is **$0.20**/1M (docs.x.ai), not = input;
  Composer/GPT unknown engines report `$0` list instead of silent Sonnet fallback.
- fix(census): `capability-census.collect_mcps()` reads Cursor `.cursor/mcp.json` (user +
  workspace + parent walk) so Q2 is not Claude-file-only prose.
- fix(4d-protocol): Q2 skill matches CLAUDE.md — MCP-first, runtime-aware census.
- fix(routing): Cursor Task bindings prefer harness allow-list slugs; mark xAI API-only names.
- docs(multi-runtime): Honest gaps (Skill/Agent matcher drop, pricing TBD, allow-list ≠ API);
  Architecture wiki points at multi-runtime; tone "supported peer" not overclaim.
- chore(quickstart): project Cursor hooks + accept Cursor as a valid runtime prerequisite.

### Features
- feat(multi-runtime): Octorato is for **all models and all editors**. New canon
  `docs/architecture/multi-runtime.md` — brain vs runtime vs engine; growth rule
  (new editor/model = binding row, not a fork); Claude Code + Cursor supported peers;
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

### Other
- reflection 2026-07-28: declarar el alcance ciego de una verificacion (#211)

## [2026-07-26]: v6.12.3
### Fixed
- fix(finops): Grok `cache_r` for 4.3 / 4.20-* / build is **$0.20**/1M (docs.x.ai), not = input;
  Composer/GPT unknown engines report `$0` list instead of silent Sonnet fallback.
- fix(census): `capability-census.collect_mcps()` reads Cursor `.cursor/mcp.json` (user +
  workspace + parent walk) so Q2 is not Claude-file-only prose.
- fix(4d-protocol): Q2 skill matches CLAUDE.md — MCP-first, runtime-aware census.
- fix(routing): Cursor Task bindings prefer harness allow-list slugs; mark xAI API-only names.
- docs(multi-runtime): Honest gaps (Skill/Agent matcher drop, pricing TBD, allow-list ≠ API);
  Architecture wiki points at multi-runtime; tone "supported peer" not overclaim.
- chore(quickstart): project Cursor hooks + accept Cursor as a valid runtime prerequisite.

### Features
- feat(multi-runtime): Octorato is for **all models and all editors**. New canon
  `docs/architecture/multi-runtime.md` — brain vs runtime vs engine; growth rule
  (new editor/model = binding row, not a fork); Claude Code + Cursor supported peers;
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

### Fixes
- fix(connectome): name cross-layer gaps for what they measure (#209)

## [2026-07-24]: v6.12.2
### Fixed
- fix(finops): Grok `cache_r` for 4.3 / 4.20-* / build is **$0.20**/1M (docs.x.ai), not = input;
  Composer/GPT unknown engines report `$0` list instead of silent Sonnet fallback.
- fix(census): `capability-census.collect_mcps()` reads Cursor `.cursor/mcp.json` (user +
  workspace + parent walk) so Q2 is not Claude-file-only prose.
- fix(4d-protocol): Q2 skill matches CLAUDE.md — MCP-first, runtime-aware census.
- fix(routing): Cursor Task bindings prefer harness allow-list slugs; mark xAI API-only names.
- docs(multi-runtime): Honest gaps (Skill/Agent matcher drop, pricing TBD, allow-list ≠ API);
  Architecture wiki points at multi-runtime; tone "supported peer" not overclaim.
- chore(quickstart): project Cursor hooks + accept Cursor as a valid runtime prerequisite.

### Features
- feat(multi-runtime): Octorato is for **all models and all editors**. New canon
  `docs/architecture/multi-runtime.md` — brain vs runtime vs engine; growth rule
  (new editor/model = binding row, not a fork); Claude Code + Cursor supported peers;
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

### Other
- reflect: send-ack-is-not-delivery lesson (#208)

## [2026-07-23]: v6.12.1
### Fixed
- fix(finops): Grok `cache_r` for 4.3 / 4.20-* / build is **$0.20**/1M (docs.x.ai), not = input;
  Composer/GPT unknown engines report `$0` list instead of silent Sonnet fallback.
- fix(census): `capability-census.collect_mcps()` reads Cursor `.cursor/mcp.json` (user +
  workspace + parent walk) so Q2 is not Claude-file-only prose.
- fix(4d-protocol): Q2 skill matches CLAUDE.md — MCP-first, runtime-aware census.
- fix(routing): Cursor Task bindings prefer harness allow-list slugs; mark xAI API-only names.
- docs(multi-runtime): Honest gaps (Skill/Agent matcher drop, pricing TBD, allow-list ≠ API);
  Architecture wiki points at multi-runtime; tone "supported peer" not overclaim.
- chore(quickstart): project Cursor hooks + accept Cursor as a valid runtime prerequisite.

### Features
- feat(multi-runtime): Octorato is for **all models and all editors**. New canon
  `docs/architecture/multi-runtime.md` — brain vs runtime vs engine; growth rule
  (new editor/model = binding row, not a fork); Claude Code + Cursor supported peers;
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

### Fixes
- fix(brain): stable manifest sort + backfill CHANGELOG v6.0.1..v6.3.0 (#192)

## [2026-07-23]: v6.12.0
### Fixed
- fix(finops): Grok `cache_r` for 4.3 / 4.20-* / build is **$0.20**/1M (docs.x.ai), not = input;
  Composer/GPT unknown engines report `$0` list instead of silent Sonnet fallback.
- fix(census): `capability-census.collect_mcps()` reads Cursor `.cursor/mcp.json` (user +
  workspace + parent walk) so Q2 is not Claude-file-only prose.
- fix(4d-protocol): Q2 skill matches CLAUDE.md — MCP-first, runtime-aware census.
- fix(routing): Cursor Task bindings prefer harness allow-list slugs; mark xAI API-only names.
- docs(multi-runtime): Honest gaps (Skill/Agent matcher drop, pricing TBD, allow-list ≠ API);
  Architecture wiki points at multi-runtime; tone "supported peer" not overclaim.
- chore(quickstart): project Cursor hooks + accept Cursor as a valid runtime prerequisite.

### Features
- feat(multi-runtime): Octorato is for **all models and all editors**. New canon
  `docs/architecture/multi-runtime.md` — brain vs runtime vs engine; growth rule
  (new editor/model = binding row, not a fork); Claude Code + Cursor supported peers;
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
- feat(brain): bulk-fetch delegation gate (turn ledger + Stop audit) (#207)

## [2026-07-23]: v6.11.0
### Fixed
- fix(finops): Grok `cache_r` for 4.3 / 4.20-* / build is **$0.20**/1M (docs.x.ai), not = input;
  Composer/GPT unknown engines report `$0` list instead of silent Sonnet fallback.
- fix(census): `capability-census.collect_mcps()` reads Cursor `.cursor/mcp.json` (user +
  workspace + parent walk) so Q2 is not Claude-file-only prose.
- fix(4d-protocol): Q2 skill matches CLAUDE.md — MCP-first, runtime-aware census.
- fix(routing): Cursor Task bindings prefer harness allow-list slugs; mark xAI API-only names.
- docs(multi-runtime): Honest gaps (Skill/Agent matcher drop, pricing TBD, allow-list ≠ API);
  Architecture wiki points at multi-runtime; tone "supported peer" not overclaim.
- chore(quickstart): project Cursor hooks + accept Cursor as a valid runtime prerequisite.

### Features
- feat(multi-runtime): Octorato is for **all models and all editors**. New canon
  `docs/architecture/multi-runtime.md` — brain vs runtime vs engine; growth rule
  (new editor/model = binding row, not a fork); Claude Code + Cursor supported peers;
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
- feat(brain): inject today's weekday as data in the 4D reminder (#206)

## [2026-07-20]: v6.10.0
### Fixed
- fix(finops): Grok `cache_r` for 4.3 / 4.20-* / build is **$0.20**/1M (docs.x.ai), not = input;
  Composer/GPT unknown engines report `$0` list instead of silent Sonnet fallback.
- fix(census): `capability-census.collect_mcps()` reads Cursor `.cursor/mcp.json` (user +
  workspace + parent walk) so Q2 is not Claude-file-only prose.
- fix(4d-protocol): Q2 skill matches CLAUDE.md — MCP-first, runtime-aware census.
- fix(routing): Cursor Task bindings prefer harness allow-list slugs; mark xAI API-only names.
- docs(multi-runtime): Honest gaps (Skill/Agent matcher drop, pricing TBD, allow-list ≠ API);
  Architecture wiki points at multi-runtime; tone "supported peer" not overclaim.
- chore(quickstart): project Cursor hooks + accept Cursor as a valid runtime prerequisite.

### Features
- feat(multi-runtime): Octorato is for **all models and all editors**. New canon
  `docs/architecture/multi-runtime.md` — brain vs runtime vs engine; growth rule
  (new editor/model = binding row, not a fork); Claude Code + Cursor supported peers;
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
- feat(brain): chat-context block-once gate on outbound chat sends (#205)

## [2026-07-20]: v6.9.0
### Fixed
- fix(finops): Grok `cache_r` for 4.3 / 4.20-* / build is **$0.20**/1M (docs.x.ai), not = input;
  Composer/GPT unknown engines report `$0` list instead of silent Sonnet fallback.
- fix(census): `capability-census.collect_mcps()` reads Cursor `.cursor/mcp.json` (user +
  workspace + parent walk) so Q2 is not Claude-file-only prose.
- fix(4d-protocol): Q2 skill matches CLAUDE.md — MCP-first, runtime-aware census.
- fix(routing): Cursor Task bindings prefer harness allow-list slugs; mark xAI API-only names.
- docs(multi-runtime): Honest gaps (Skill/Agent matcher drop, pricing TBD, allow-list ≠ API);
  Architecture wiki points at multi-runtime; tone "supported peer" not overclaim.
- chore(quickstart): project Cursor hooks + accept Cursor as a valid runtime prerequisite.

### Features
- feat(multi-runtime): Octorato is for **all models and all editors**. New canon
  `docs/architecture/multi-runtime.md` — brain vs runtime vs engine; growth rule
  (new editor/model = binding row, not a fork); Claude Code + Cursor supported peers;
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
- feat(brain): link /ai-sync and daily-reflection as one ritual (#204)

## [2026-07-17]: v6.8.1
### Fixed
- fix(finops): Grok `cache_r` for 4.3 / 4.20-* / build is **$0.20**/1M (docs.x.ai), not = input;
  Composer/GPT unknown engines report `$0` list instead of silent Sonnet fallback.
- fix(census): `capability-census.collect_mcps()` reads Cursor `.cursor/mcp.json` (user +
  workspace + parent walk) so Q2 is not Claude-file-only prose.
- fix(4d-protocol): Q2 skill matches CLAUDE.md — MCP-first, runtime-aware census.
- fix(routing): Cursor Task bindings prefer harness allow-list slugs; mark xAI API-only names.
- docs(multi-runtime): Honest gaps (Skill/Agent matcher drop, pricing TBD, allow-list ≠ API);
  Architecture wiki points at multi-runtime; tone "supported peer" not overclaim.
- chore(quickstart): project Cursor hooks + accept Cursor as a valid runtime prerequisite.

### Features
- feat(multi-runtime): Octorato is for **all models and all editors**. New canon
  `docs/architecture/multi-runtime.md` — brain vs runtime vs engine; growth rule
  (new editor/model = binding row, not a fork); Claude Code + Cursor supported peers;
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

### Other
- chore: session sync (hannon, mudanza, mascotas, responsivas) (#203)

## [2026-07-16]: v6.8.0
### Fixed
- fix(finops): Grok `cache_r` for 4.3 / 4.20-* / build is **$0.20**/1M (docs.x.ai), not = input;
  Composer/GPT unknown engines report `$0` list instead of silent Sonnet fallback.
- fix(census): `capability-census.collect_mcps()` reads Cursor `.cursor/mcp.json` (user +
  workspace + parent walk) so Q2 is not Claude-file-only prose.
- fix(4d-protocol): Q2 skill matches CLAUDE.md — MCP-first, runtime-aware census.
- fix(routing): Cursor Task bindings prefer harness allow-list slugs; mark xAI API-only names.
- docs(multi-runtime): Honest gaps (Skill/Agent matcher drop, pricing TBD, allow-list ≠ API);
  Architecture wiki points at multi-runtime; tone "supported peer" not overclaim.
- chore(quickstart): project Cursor hooks + accept Cursor as a valid runtime prerequisite.

### Features
- feat(multi-runtime): Octorato is for **all models and all editors**. New canon
  `docs/architecture/multi-runtime.md` — brain vs runtime vs engine; growth rule
  (new editor/model = binding row, not a fork); Claude Code + Cursor supported peers;
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
- feat: graphify deep-learn — code-graph skill + connectome shrink-guard (#202)

## [2026-07-13]: v6.7.3
### Fixed
- fix(finops): Grok `cache_r` for 4.3 / 4.20-* / build is **$0.20**/1M (docs.x.ai), not = input;
  Composer/GPT unknown engines report `$0` list instead of silent Sonnet fallback.
- fix(census): `capability-census.collect_mcps()` reads Cursor `.cursor/mcp.json` (user +
  workspace + parent walk) so Q2 is not Claude-file-only prose.
- fix(4d-protocol): Q2 skill matches CLAUDE.md — MCP-first, runtime-aware census.
- fix(routing): Cursor Task bindings prefer harness allow-list slugs; mark xAI API-only names.
- docs(multi-runtime): Honest gaps (Skill/Agent matcher drop, pricing TBD, allow-list ≠ API);
  Architecture wiki points at multi-runtime; tone "supported peer" not overclaim.
- chore(quickstart): project Cursor hooks + accept Cursor as a valid runtime prerequisite.

### Features
- feat(multi-runtime): Octorato is for **all models and all editors**. New canon
  `docs/architecture/multi-runtime.md` — brain vs runtime vs engine; growth rule
  (new editor/model = binding row, not a fork); Claude Code + Cursor supported peers;
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

### Other
- chore(brain): refresh connectome + CAPABILITIES after multi-runtime (#201)

## [2026-07-10]: v6.7.2
### Fixed
- fix(finops): Grok `cache_r` for 4.3 / 4.20-* / build is **$0.20**/1M (docs.x.ai), not = input;
  Composer/GPT unknown engines report `$0` list instead of silent Sonnet fallback.
- fix(census): `capability-census.collect_mcps()` reads Cursor `.cursor/mcp.json` (user +
  workspace + parent walk) so Q2 is not Claude-file-only prose.
- fix(4d-protocol): Q2 skill matches CLAUDE.md — MCP-first, runtime-aware census.
- fix(routing): Cursor Task bindings prefer harness allow-list slugs; mark xAI API-only names.
- docs(multi-runtime): Honest gaps (Skill/Agent matcher drop, pricing TBD, allow-list ≠ API);
  Architecture wiki points at multi-runtime; tone "supported peer" not overclaim.
- chore(quickstart): project Cursor hooks + accept Cursor as a valid runtime prerequisite.

### Features
- feat(multi-runtime): Octorato is for **all models and all editors**. New canon
  `docs/architecture/multi-runtime.md` — brain vs runtime vs engine; growth rule
  (new editor/model = binding row, not a fork); Claude Code + Cursor supported peers;
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

### Other
- sync (#200)

## [2026-07-10]: v6.7.1
### Fixed
- fix(finops): Grok `cache_r` for 4.3 / 4.20-* / build is **$0.20**/1M (docs.x.ai), not = input;
  Composer/GPT unknown engines report `$0` list instead of silent Sonnet fallback.
- fix(census): `capability-census.collect_mcps()` reads Cursor `.cursor/mcp.json` (user +
  workspace + parent walk) so Q2 is not Claude-file-only prose.
- fix(4d-protocol): Q2 skill matches CLAUDE.md — MCP-first, runtime-aware census.
- fix(routing): Cursor Task bindings prefer harness allow-list slugs; mark xAI API-only names.
- docs(multi-runtime): Honest gaps (Skill/Agent matcher drop, pricing TBD, allow-list ≠ API);
  Architecture wiki points at multi-runtime; tone "supported peer" not overclaim.
- chore(quickstart): project Cursor hooks + accept Cursor as a valid runtime prerequisite.

### Features
- feat(multi-runtime): Octorato is for **all models and all editors**. New canon
  `docs/architecture/multi-runtime.md` — brain vs runtime vs engine; growth rule
  (new editor/model = binding row, not a fork); Claude Code + Cursor supported peers;
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

### Fixes
- fix(multi-runtime): Grok cache_r + Cursor MCP census + Q2 parity (#198)

## [2026-07-10]: v6.7.0
### Features
- feat(multi-runtime): Octorato is for **all models and all editors**. New canon
  `docs/architecture/multi-runtime.md` — brain vs runtime vs engine; growth rule
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
- feat(skills): agent-browser real-mouse protocol for React-class widgets; whatsapp-bridge outbound anti-spam discipline (#199)

## [2026-07-10]: v6.6.0
### Features
- feat(multi-runtime): Octorato is for **all models and all editors**. New canon
  `docs/architecture/multi-runtime.md` — brain vs runtime vs engine; growth rule
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
- feat(templates): brand-neutral cotización DOCX/PDF generator.

## [2026-07-02]: v6.0.1
### Other
- docs(changelog): backfill v5.9.1, v5.10.0, v6.0.0 via changelog-sync.

## [2026-07-02]: v6.0.0
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
- test(harness): prove the prover — broken gate must FAIL the doctor
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

## [2026-06-26]: v5.0.0 "Capability Manifest"
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

## [2026-06-23]: v4.0.0 "Wired or Corrupt"

The brain stopped trusting its own prose. Most of CLAUDE.md was discipline the model could skip; only a small fraction had a real reflex. RULE #1 inverts that. Every rule must be wired, an unwired rule means the brain is CORRUPT, and brain_doctor enforces it. A missing mechanism blocks the push. No exceptions.

### Added: the registry

- **RULE #1 (constitutional keystone)**: every CLAUDE.md rule maps to a live mechanism in `registry/rules.yaml`, or the brain is CORRUPT. Self-wired: its own mechanism is `brain_doctor`, invoked from `.githooks/pre-push`. (`CLAUDE.md` §"RULE #1", `docs/architecture/wired-or-corrupt.md`)
- **The rule registry**: `registry/rules.yaml` (42 rules, 100% of CLAUDE.md anchors covered) + `registry/rules.schema.json`, validated like skill manifests.
- **brain_doctor enforcement**: D0 bootstrap self-check, D1 schema, D2 anchors (both directions, fail-closed), D3 per-rule wiring, a printed Coverage Ledger, and a `--registry` gate the pre-push runs. Kills the phantom-script class: a documented-but-absent hook can no longer ship.
- **OO mechanism hierarchy**: `Gate`/`Reflex`/`Detector`/`Presence` with polymorphic `verify()`; the Presence-escape-hatch closed in the schema so a model-behavior label cannot dodge a real gate.
- **Hook-naming policy**: `registry/naming-policy.yaml`. New hook scripts must follow `<prefix>__<event>__<slug>.py` (prefix agrees with kind); the 18 existing scripts are grandfathered, zero churn.

### Fixed

- **The drift defect**: `brain-memory-recall.py`, the brain's life-memory reflex, was documented as wired but never fired because the live `settings.json` had drifted from the tracked `hooks.json`. Reconciled via `merge-hooks.py`. The reflex is live and surfacing memories again.

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
