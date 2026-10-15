# Implementation Plan: harness independence and opt-in tracing

> **Spec:** `feature.md` in this directory (`Spec-Format: ears-1`, status draft)
> **Date:** 2026-10-14

## Overview

Three phases, one pull request each, every one from a worktree. The census comes first, because which harness is supported is a measurement, not a choice. After the census the harness track and the tracing track are independent and can run in parallel.

## Architecture Decisions

- **Support is measured, not declared.** Gemini CLI and Codex CLI become `supported` only on a census record with blocking evidence. A harness that blocks shell but not file edits is a `gap`, because Octorato's write gates would silently not fire. Claude Code and Cursor are not re-censused; their evidence is the gate selftests and the existing Cursor hook-sync check.
- **Deterministic census, one live call.** Blocking is measured by feeding each documented payload shape to the projected hooks, which needs no model. One live end-to-end call per harness confirms the harness actually invokes them; it uses an operator account and a sandbox prompt with no client data.
- **One shim, many projectors.** Gates keep their Claude-shaped contract. Each harness gets a projector with a tool-name map (the `_TOOL_MAP` pattern of `merge-hooks-cursor.py`) and shares one Hook_Shim for payloads and exit codes.
- **Fail closed on an unreadable payload.** A shim that cannot parse a payload for a fail-closed gate blocks, so a harness upgrade that changes the payload cannot turn every gate into an allow.
- **The guard decides whether the vendor hook runs.** The upstream LangSmith plugin is never installed on its own. Octorato ships a wrapper plugin, signed through `octo pkg` (new kind `plugin`), whose hook commands call the Export_Guard; the guard starts the unmodified upstream hook script only for an `allow` arm. Rejected: patching the upstream `hooks.json`, which breaks its tree hash and signature; and a brain hook beside the plugin, which cannot cancel a sibling hook.
- **The policy lives in the arm, and only the operator opens it.** `telemetry.export` is read from `arm.json` at send time with `deny` as the default, and the Export_Flip_Gate denies an agent write that sets it to `allow`.
- **No LangChain or LangGraph.** Recorded in Out of Scope with the census behind it.

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

## Risks

- **Version order.** v11 is merged on master (#417, `e3b5141`) but tagged `v10.1.0` until its release PR cuts v11.0.0. Every phase PR stays a draft until that tag exists, or its bump would land as v10.x. v11 changed `hooks.json`, `brain_doctor.py`, `registry/rules.yaml` and `octo_pkg.py`, all on this plan's path: each phase rebases on master before QA and re-runs its fixtures.
- **Harness drift.** Gemini CLI was replaced by Antigravity CLI for some tiers on 2026-06-18, and Codex requires a per-machine `/hooks` trust step for non-managed hooks. T01 records the binary and whether trust is scriptable; if it is not, Codex `supported` carries an operator step per machine, written in its registry entry.
- **Plugin packaging.** `octo pkg` installs skills and arms today (`--kind skill|arm`); kind `plugin` is new work in T15. Claude Code enables a plugin through `enabledPlugins` in `settings.json`, which the Arming_Gate protects, so the install is the operator's terminal step and the Arming_Gate is not loosened. If the plugin loader cannot be pointed at a signed tree, the spec returns to the operator before any other route.
- **Arm settings are not on the arming surface.** The arming-surface gate leaves an arm's own `.claude/` settings to the arm, so an agent can set the tracing switch there. The guard makes that switch inert for a `deny` arm, the Doctor detects it, and the flip of `telemetry.export` itself is gated (AC-16). An agent editing `arm.json` by a route the flip gate does not parse is the accepted residual.
- **Redaction is not a guarantee.** The vendor calls it a safety net; that is why `allow` is a per-arm decision of the operator and not a default.

## Notes

- T01 records translation only; AC-02 (violation blocked, benign allowed) and the Codex `/hooks` trust scriptability close in T08 once T05's shim exists.
