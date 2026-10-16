# Implementation Plan: harness independence and opt-in tracing

> **Spec:** `feature.md` in this directory (`Spec-Format: ears-1`, status draft)
> **Date:** 2026-10-14

## Overview

Three phases, one pull request each, every one from a worktree. The census comes first, because which harness is supported is a measurement, not a choice. After the census the harness track and the tracing track are independent and can run in parallel.

Phase 4 (appended 2026-10-16) is independent of phases 2 and 3: it reads the census records of phase 1 and the Arm_Resolution and Export_Policy of phase 3, and changes neither.

## Architecture Decisions

- **Support is measured, not declared.** Gemini CLI and Codex CLI become `supported` only on a census record with blocking evidence. A harness that blocks shell but not file edits is a `gap`, because Octorato's write gates would silently not fire. Claude Code and Cursor are not re-censused; their evidence is the gate selftests and the existing Cursor hook-sync check.
- **Deterministic census, one live call.** Blocking is measured by feeding each documented payload shape to the projected hooks, which needs no model. One live end-to-end call per harness confirms the harness actually invokes them; it uses an operator account and a sandbox prompt with no client data.
- **One shim, many projectors.** Gates keep their Claude-shaped contract. Each harness gets a projector with a tool-name map (the `_TOOL_MAP` pattern of `merge-hooks-cursor.py`) and shares one Hook_Shim for payloads and exit codes.
- **Fail closed on an unreadable payload.** A shim that cannot parse a payload for a fail-closed gate blocks, so a harness upgrade that changes the payload cannot turn every gate into an allow.
- **The guard decides whether the vendor hook runs.** The upstream LangSmith plugin is never installed on its own. Octorato ships a wrapper plugin, signed through `octo pkg` (new kind `plugin`), whose hook commands call the Export_Guard; the guard starts the unmodified upstream hook script only for an `allow` arm. Rejected: patching the upstream `hooks.json`, which breaks its tree hash and signature; and a brain hook beside the plugin, which cannot cancel a sibling hook.
- **The policy lives in the arm, and only the operator opens it.** `telemetry.export` is read from `arm.json` at send time with `deny` as the default, and the Export_Flip_Gate denies an agent write that sets it to `allow`.
- **No LangChain or LangGraph.** Recorded in Out of Scope with the census behind it.
- **Phase 4: the receipt wraps the call, not the reviewer.** A Bash hook pair writes the External_Review_Receipt around `codex exec` or `gemini -p`, keyed by the harness `tool_use_id` the way seek receipts are, so the model never types the line. Rejected: a Claude subagent quoting the external output (today's route; the receipt is the subagent's) and a wrapper script the model calls (the model owns its arguments and its output).
- **Phase 4: an external receipt adds to a quorum, never forms one.** The judgment-tier invariant ("the verifier must run on a model at least as strong as the builder", `multi-runtime.md`) stays with the harness reviewer. A SELF reply's quorum of three can become one harness reviewer plus two allowed external engines; a SOURCED reply's quorum of one is unchanged.
- **Phase 4: the bound is 0.05 on catch rate and 0.10 on false alarms.** With at least 40 NEEDS-WORK cases one case is 0.025, so 0.05 is two cases: the smallest margin a single flipped case cannot cross. Missing a defect ships a wrong fact; a false alarm costs one more panel round (v11 cost table), so the false-alarm margin is twice as loose. Since an allowed engine never stands alone (AC-22), a miss it lets through still meets the harness reviewer.
- **Phase 4: synthetic replay, not historical bodies.** The ledger stores digests and agent transcript pointers; the bodies sit in private transcripts that hold arm and operator data. The fixture set is written from the defect classes those receipts show, so it can be tracked, reviewed and rerun on any machine.

## Implementation Steps

### Phase 1: census and registry

- [ ] T01 [AC-02] scripts/runtime_census.py: feed each Block_Fixture as Gemini CLI and Codex CLI hook payloads per tool class; trust the projected hooks through Codex `/hooks` in the sandbox first and record whether that step is scriptable; run one live call per harness; write `registry/census/<harness>.json` with binary, version and account tier (Gemini CLI or Antigravity CLI).
- [ ] T02 [AC-01, AC-03] registry/runtimes.yaml, docs/architecture/multi-runtime.md, scripts/brain_doctor.py: create the registry with the four harnesses and their status from the census or the stated evidence; rename the doc's table to "Runtimes", add a Status column and the Gemini and Codex rows in the same change; add the doctor checks for presence, status agreement and a `supported` status backed by its census record.
- [ ] T03 [AC-17] scripts/g__pretool__arming-surface.py, registry/fixtures/ARCHITECTURE.arming-surface/: add `registry/runtimes.yaml` to the live arming set, with a violation and a benign fixture.
- [ ] T04 [AC-15] registry/rules.yaml: register the census, the registry check and the arming-surface change.

### Phase 2: harnesses (only for harnesses the census marks supported)

- [ ] T05 [AC-05, AC-17] scripts/g__shim__hook.py: map each supported harness's payload to the gate fields and the gate's deny to that harness's block; selftest with an unparseable payload that must block; add the shim to the arming set with fixtures.
- [ ] T06 [AC-04] scripts/merge-hooks-gemini.py: project `hooks.json` into `.gemini/settings.json` hooks through the tool-name map (`run_shell_command`, file tools, `mcp_<server>_<tool>`); write unprojected matcher tokens to the registry.
- [ ] T07 [AC-04] scripts/merge-hooks-codex.py: same for `~/.codex/hooks.json` (`Bash`, `apply_patch`, MCP), only if Codex is supported.
- [ ] T08 [AC-06] scripts/runtime_census.py: add a `--gates` mode that runs every projected fail-closed gate's `--selftest` through the shim under each supported harness; keep the run log as evidence.
- [ ] T09 [AC-07] scripts/ai_sync.py: read the registry, then write `AGENTS.md` and `GEMINI.md` per arm from `.claude/CLAUDE.md`, committed in the arm like `.cursorrules`; test idempotence with a second run.
- [ ] T10 [AC-08] registry/runtimes.yaml, docs/architecture/multi-runtime.md: tier bindings per supported harness in the registry, mirrored as rows and honest gaps in the doc.
- [ ] T11 [AC-15] registry/rules.yaml: register the shim, projectors and sync change.

### Phase 3: opt-in tracing

- [ ] T12 [AC-09] templates/arm/arm.json.template: add `telemetry.export: "deny"` and document the field.
- [ ] T13 [AC-09, AC-10, AC-11, AC-17] scripts/g__wrap__export-guard.py: implement the Arm_Resolution with real-path containment and start the upstream hook only on `allow`; fixtures for no field, `deny`, `allow`, a brain session and a path outside any arm, each asserting whether the upstream process was spawned; add the guard to the arming set with fixtures.
- [ ] T14 [AC-16] scripts/g__pretool__export-flip.py: deny a Write, Edit or shell write that sets `telemetry.export` to `allow`; violation and benign fixtures.
- [ ] T15 [AC-13, AC-17] scripts/octo_pkg.py: add kind `plugin` that installs under `~/.claude/plugins` with signature and lock entry; build the Tracing_Wrapper package around the upstream hook scripts, disabled for every arm on install; the agent prints the operator's install command and never runs it in a session; add the installed tree and the plugin registration files to the arming set with fixtures.
- [ ] T16 [AC-12, AC-13] scripts/brain_doctor.py: fail on a tracing switch in a `deny` or absent arm's project settings or in global settings, on an installed wrapper tree that does not hash to its lock entry, and on the upstream plugin installed outside the wrapper.
- [ ] T17 [AC-14] scripts/g__wrap__export-guard.py: add a `--bench` mode that measures, for every event the wrapper registers, that event's hook list with and without the wrapper over 100 events, for a closed local port and a non-routable address; record median, p95 and the upstream version.
- [ ] T18 [AC-15] registry/rules.yaml: register the guard, the flip gate, the package kind and the doctor checks.

### Phase 4: LLM independence for reviewers

- [ ] T19 [AC-15, AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24, AC-25, AC-32] scripts/r__pretool-bash__external-review.py, scripts/r__posttool-bash__external-review.py, scripts/receipt_ledger.py, scripts/r__subagent-stop__qa-receipt.py, registry/reviewers.yaml, hooks.json, scripts/g__pretool__arming-surface.py, scripts/brain_doctor.py, registry/rules.yaml, docs/architecture/v11-reply-panel.md: write the hook pair with per-engine parsers for `codex exec` and `gemini -p` (model argument, prompt from argv or a named-file redirection, else an empty digest), store the output copy, teach `panel_receipts_for` the `external` kind with the AC-21 anchors, the harness-reviewer floor and the Export_Policy check, add `external_reviewers` to the QA_Receipt_Reflex, keep the runtime-status derivation census-only with a fixture where an `allowed` reviewer meets a `gap` census, add the arming fixtures, register the reflexes, and restate R-05.
- [ ] T20 [AC-15, AC-26, AC-27, AC-28, AC-29, AC-30, AC-31, AC-32] registry/replay/fixtures/, scripts/review_replay.py, registry/replay/records/, registry/reviewers.yaml, scripts/brain_doctor.py, registry/rules.yaml: write the 80-case synthetic set, the harness that runs it through Fable (Opus on refusal) and through each candidate engine and model, record the baseline and candidate Replay_Records, set each Reviewer_Registry status from the AC-30 bound, add the doctor checks for fixture hygiene and the recomputed bound, and register both.

## Risks

- **Version order.** v11 is merged on master (#417, `e3b5141`) but tagged `v10.1.0` until its release PR cuts v11.0.0. Every phase PR stays a draft until that tag exists, or its bump would land as v10.x. v11 changed `hooks.json`, `brain_doctor.py`, `registry/rules.yaml` and `octo_pkg.py`, all on this plan's path: each phase rebases on master before QA and re-runs its fixtures.
- **Harness drift.** Gemini CLI was replaced by Antigravity CLI for some tiers on 2026-06-18, and Codex requires a per-machine `/hooks` trust step for non-managed hooks. T01 records the binary and whether trust is scriptable; if it is not, Codex `supported` carries an operator step per machine, written in its registry entry.
- **Plugin packaging.** `octo pkg` installs skills and arms today (`--kind skill|arm`); kind `plugin` is new work in T15. Claude Code enables a plugin through `enabledPlugins` in `settings.json`, which the Arming_Gate protects, so the install is the operator's terminal step and the Arming_Gate is not loosened. If the plugin loader cannot be pointed at a signed tree, the spec returns to the operator before any other route.
- **Arm settings are not on the arming surface.** The arming-surface gate leaves an arm's own `.claude/` settings to the arm, so an agent can set the tracing switch there. The guard makes that switch inert for a `deny` arm, the Doctor detects it, and the flip of `telemetry.export` itself is gated (AC-16). An agent editing `arm.json` by a route the flip gate does not parse is the accepted residual.
- **Redaction is not a guarantee.** The vendor calls it a safety net; that is why `allow` is a per-arm decision of the operator and not a default.
- **Phase 4: an external engine reads the reply.** A panel body can carry arm data, and an External_Reviewer_CLI sends it to another vendor. The reflex never blocks, so AC-23 removes the incentive instead (no receipt from a non-`allow` arm counts), and the replay set is synthetic; an agent that runs an external review in a `deny` arm anyway is the accepted residual, visible in the kernel journal.
- **Phase 4: the named model is not proof of the answering model.** The receipt records the model the command asked for. The Gemini census live call returned a 429 naming `gemini-3.8-flash` (`registry/census/gemini.json`, `live.attempts`), so a CLI can answer from another model or fail on quota; a non-zero exit does not count (AC-21), a silent fallback inside a zero exit is a residual.
- **Phase 4: 40 cases is a screen, not a proof.** At a catch rate near 0.9 with n=40 the 95% Wilson interval for 36 of 40 runs from about 0.77 to 0.96, wider than the 0.05 bound. The bound decides on the recorded fixture hash; growing the set narrows the interval and reruns every record (AC-31 fails a stale hash).
- **Phase 4: unattended baseline runs.** Running Fable or Opus from the Replay_Harness is a top-level `claude -p` call, which pays up to 8 Stop continuations per reply under the reply panel (v11 R-12). The harness states how it launches the baseline and its measured cost per run.
- **Phase 4: the transcript anchor is a file.** The output copy and the session transcript live under `$HOME`, writable through Bash; same residual as every v7 receipt (`receipt_ledger.py` docstring): visible and recorded, not impossible.

## Notes

- T01 records translation only; AC-02 (violation blocked, benign allowed) and the Codex `/hooks` trust scriptability close in T08 once T05's shim exists.
- T02 QA fix, `runtime-census-evidence` fails closed: both census harness keys must be present, any id outside the census and evidence allowlists (claude-code, cursor) fails, and every `supported` entry carries `evidence` naming a brain_doctor check (`runtime-registry` also fails a `supported` entry with no `evidence`). Severity follows the doctor's convention that only FAIL is exit-nonzero: a named check that FAILs fails this check; a named check that is WARN (for example `cursor-hooks-sync` drift) degrades it to WARN with that check's message; a named check in SLOW_CHECKS that did not run (`--fast`, or a standalone call) is reported WARN "not verified", never PASS. Inside a run, the named check's result is read from the run in progress, not executed twice.
- Phase 4 task cap: T19 and T20 take the last 2 of the 20 planned tasks this plan may hold (`scripts/spec_lint.py` `MAX_TASKS`). Each spans more files than a single-session task; if analyze or converge needs more than two tasks for phase 4, it moves to its own spec directory that references this one, and this plan does not grow past 20.
