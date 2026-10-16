# Feature: harness independence and opt-in tracing (next v11 minor)

> **Status:** draft
> **Spec-Format:** ears-1
> **Date:** 2026-10-14
> **Classification:** LARGE (score 9: 4 to 10 files, new feature, architecture decision, multiple modules)

Octorato's brain is plain files, but today it runs on two harnesses: Claude Code and Cursor. This minor release adds the harnesses that block a tool call from a hook, and an opt-in trace view per arm that can never upload from an arm that forbids it. It does not add LangChain or LangGraph.

## Summary

**Why harnesses, not a model library.** A research pass on 2026-10-14 (deep-research run `wf_0e7bf9d3-12e`, 24 of 25 claims confirmed by 3-vote verification) compared LangChain 1.x and LangGraph 1.x with Octorato. Model independence in Octorato does not live in code: the harness picks the model, and `docs/architecture/multi-runtime.md` maps four vendor-agnostic tiers onto each harness's model slugs. The command `grep -rlE "import (openai|anthropic)|from (openai|anthropic)|google\.generativeai|litellm|api\.openai\.com|api\.anthropic\.com" scripts skills --include=*.py` (vendored packages excluded) returns 7 files: `scripts/anthropic-analytics-pull.py`, `scripts/finops-digest.py`, `skills/image-analyzer/scripts/analyze_image.py`, `skills/speech/scripts/text_to_speech.py`, `skills/imagegen/scripts/image_gen.py`, `skills/sora/scripts/sora.py`, `skills/transcribe/scripts/transcribe_diarize.py`. Two read Anthropic usage and cost; five use vendor-specific media features. None gains from a model abstraction library, so independence grows by adding harnesses.

**Which harnesses.** Gemini CLI documents `BeforeTool` hooks in `.gemini/settings.json` (project) and `~/.gemini/settings.json` (user) that block with exit code 2 and use stderr as the reason, or with a JSON `deny` decision; its payload carries `tool_name`, `tool_input` and `mcp_context`, and MCP tools are named `mcp_<server>_<tool>` (geminicli.com/docs/hooks/reference). The same site states that Gemini CLI "was replaced by Antigravity CLI on June 18th, 2026" for unpaid and Google One tiers. OpenAI Codex CLI documents `PreToolUse`, `PostToolUse`, `Stop` and nine more events, configured in `~/.codex/hooks.json` or `[hooks]` tables in `config.toml` at user or repository level; it blocks with `permissionDecision: deny` or exit 2 with a stderr reason; `PreToolUse` covers shell (matched as `Bash`), `apply_patch` edits, MCP and local tools, but not hosted tools; hooks are on by default, and hooks not set by a managed policy must be trusted through `/hooks` before they run (learn.chatgpt.com/docs/hooks). Neither harness is accepted until the census measures it.

**Why tracing, and why off.** LangSmith ships an official Claude Code plugin (`langsmith-tracing`) that sends each turn as a trace: user messages, tool calls, compaction and subagent runs. It is switched on by `TRACE_TO_LANGSMITH` in a project's `.claude/settings.local.json`, in the global `~/.claude/settings.json`, or as a shell export. Secret redaction is on by default, and the same page calls it "a safety net rather than a guarantee" (docs.langchain.com/langsmith/trace-claude-code). Arms hold client data, and at least one arm has a signed commitment not to export real data outside the client's tenant. So tracing must be off unless an arm explicitly allows it, the decision must be read from the arm at send time, and the upstream hook must not run at all when the arm says no.

**Why reviewers on other engines, and why a receipt (phase 4).** The judgment tier prefers "a **different vendor** than the builder when available" (`docs/architecture/multi-runtime.md`, judgment row), yet every receipt the ledger honours is written for a harness subagent: a panel receipt needs an agent type matching `PANEL_AGENT_TYPE` and a harness-shaped agent transcript of the same session (`scripts/receipt_ledger.py`, `panel_receipts_for`), and a QA receipt is written by `scripts/r__subagent-stop__qa-receipt.py` from a subagent's final report. A review run through `codex exec` or `gemini -p` counts today only when a Claude subagent quotes it, so the receipt belongs to the Claude subagent; the v11 reply panel states the gap as R-05, "The reviewer is independent in context, not in model" (`docs/architecture/v11-reply-panel.md`). Phase 4 adds a receipt written by a Bash hook pair around the external call, so a verdict can name a non-Claude engine. It does not trust a cheaper engine by assumption: the local ledger holds 127 panel NEEDS-WORK and 470 panel PASS receipts (read-only count of the gitignored `~/.claude/.cache/receipts/global.jsonl`, 2026-10-16), and the v11 cost measurement credits NEEDS-WORK receipts with 6 wrong facts and 7 overstatements caught over 103 replies. An engine that misses those is cheaper only on paper, so it joins a quorum only on a replayed catch rate. Both CLIs are installed on the measuring machine (`codex-cli 0.159.3`, `gemini 0.62.0`, `--version` on 2026-10-16); in `codex exec` the flag `-m` names the model and `-p` a config profile, while for `gemini` `-p` is the prompt, so the command parser is per engine. Codex CLI and Gemini CLI stay `gap` as runtimes (AC-03): reviewing text is not running Octorato's gates.

## Glossary

Every acceptance criterion names one of these components as its subject.

- **Runtime_Registry**: a new tracked file `registry/runtimes.yaml`, one entry per harness with its instruction file, hook config path, block contract, tool-name map, tier binding, unprojected gates, and a status of `supported` or `gap`.
- **Runtime_Census**: a new script `scripts/runtime_census.py`. For each harness it feeds the Block_Fixtures as that harness's documented hook payloads (deterministic), and runs one live end-to-end call per harness from a sandbox prompt with no client data. It writes one tracked record per harness to `registry/census/<harness>.json`.
- **Block_Fixture**: a tool call that a projected gate must deny, plus its benign twin derived by one edit, both taken from that gate's existing `registry/fixtures/` directory.
- **Hook_Shim**: a new script `scripts/g__shim__hook.py` that translates a harness's hook payload into the fields a gate reads, and the gate's deny into the harness's block.
- **Hook_Projector**: one new script per supported harness, `scripts/merge-hooks-gemini.py` and `scripts/merge-hooks-codex.py`, following `scripts/merge-hooks-cursor.py` and its tool-name map.
- **Instruction_Sync**: the `sync-ai-docs` step of `scripts/ai_sync.py`, extended to write `AGENTS.md` and `GEMINI.md`.
- **Arm_Resolution**: the arm of a session is the registered arm path (from `company/config/arms-paths.json`, candidate arrays resolved as `load_arms()` does) whose real path contains the real path of the session's working directory. A brain session or a working directory under no registered arm resolves to no arm.
- **Export_Policy**: a new optional field `telemetry.export` in an arm's `arm.json`, with values `deny` or `allow`.
- **Tracing_Wrapper**: a new Octorato plugin package of kind `plugin` whose hook commands call the Export_Guard; it carries the upstream LangSmith plugin's hook scripts unmodified.
- **Export_Guard**: a new script `scripts/g__wrap__export-guard.py`, called by every Tracing_Wrapper hook command, that applies the Export_Policy of the session's arm and starts the upstream hook script only on `allow`.
- **Export_Flip_Gate**: a new PreToolUse gate `scripts/g__pretool__export-flip.py` that guards writes to `telemetry.export`.
- **Arming_Gate**: `scripts/g__pretool__arming-surface.py`, the v8 gate that denies writes to the live copy of the files that arm the gates.
- **Package_Installer**: `scripts/octo_pkg.py`.
- **Doctor**: `scripts/brain_doctor.py`.
- **External_Reviewer_CLI**: a command listed in the Reviewer_Registry with its engine, its command-boundary pattern (`codex exec`; `gemini` with `-p` or `--prompt`), its model argument and the prompt sources it reads (argv, stdin).
- **External_Review_Reflex**: a new hook pair, `scripts/r__pretool-bash__external-review.py` (PreToolUse Bash) and `scripts/r__posttool-bash__external-review.py` (PostToolUse Bash), that never blocks and fails open, like `scripts/r__subagent-stop__qa-receipt.py`.
- **External_Review_Receipt**: a ledger line of kind `external` in `~/.claude/.cache/receipts/global.jsonl`, written only by the External_Review_Reflex around one Bash call to an External_Reviewer_CLI.
- **Reviewer_Registry**: a new tracked file `registry/reviewers.yaml`: the External_Reviewer_CLI entries, and one entry per engine and model pair with a quorum status of `allowed` or `not-allowed` and the Replay_Record it rests on.
- **Panel_Ledger**: the panel functions of `scripts/receipt_ledger.py` (`panel_receipts_for`, `panel_latest_for`, `panel_pass_for`) that the send gate and the reply-panel gate read.
- **QA_Receipt_Reflex**: `scripts/r__subagent-stop__qa-receipt.py`, the SubagentStop reflex that writes `qa`, `converge` and `panel` receipts.
- **Replay_Fixture_Set**: a new tracked directory `registry/replay/fixtures/` of synthetic panel cases with a known expected verdict.
- **Replay_Harness**: a new script `scripts/review_replay.py` that runs the Replay_Fixture_Set through one engine and model.
- **Replay_Record**: a tracked file `registry/replay/records/<engine>-<model>.json` written by the Replay_Harness.

## User Stories

- As the operator, I want Octorato to run with the same gates on a second harness, so that switching vendor is a choice and not a rebuild.
- As the operator, I want to see a session's turns, tool calls and subagents as a trace when I debug, so that I stop reading transcripts by hand.
- As a client, I want my data never to reach a third-party trace service unless my project allows it, so that the consultant's tooling does not break what we signed.

## Functional Requirements

### FR-01: A harness is supported only when it blocks

A harness becomes `supported` only after the Runtime_Census shows it blocking the shell, file write and file edit classes. Anything less is a `gap` with the classes it does not block. Claude Code and Cursor keep their status on their existing evidence.

### FR-02: The same gates, projected and shimmed

Each supported harness gets a Hook_Projector that writes its hook config from `hooks.json` through a per-harness tool-name map, and every projected gate runs through the Hook_Shim. A gate that cannot be projected is listed by matcher token, never dropped silently.

### FR-03: Each harness reads the brain in its own file

The Instruction_Sync writes the arm instructions to the file each supported harness reads, from the same `CLAUDE.md` source of truth, with the same commit convention as `.cursorrules`.

### FR-04: Tracing is a per-arm opt-in that defaults to off

An arm that says nothing is `deny`. The upstream tracing hook runs only for a session whose arm is `allow`; only the operator flips an arm to `allow`; and a tracing failure never blocks a turn and stays within a measured bound.

### FR-05: A non-Claude reviewer is receipted by a hook

A review run through an external CLI leaves a receipt that a hook wrote, binding the engine, the model, the exact prompt and the exact output, so a panel or QA verdict can name that engine without a Claude subagent owning the receipt.

### FR-06: An engine joins a quorum on a measured catch rate

An engine and model pair counts toward a panel quorum only when its catch rate on a tracked, synthetic replay set is within a stated bound of the judgment-tier baseline, and never forms a quorum alone.

### FR-07: Reviewing is not running

Phase 4 changes no runtime status. Codex CLI and Gemini CLI stay `gap` until their census records show shell, file write and file edit blocked (FR-01); a reviewer receipt or a replay record is not evidence for that.

## Acceptance Criteria

- [ ] AC-01: THE Runtime_Registry SHALL hold one entry per row of the "Runtimes" table of `docs/architecture/multi-runtime.md`, and THE Doctor SHALL fail when a harness appears in one and not the other or when their statuses disagree.
- [ ] AC-02: WHEN the Runtime_Census runs for a harness, THE Runtime_Census SHALL record, for each of the shell, file write, file edit and MCP tool classes, whether the documented-payload Block_Fixture was blocked and its benign twin allowed, the result of one live end-to-end call, and the harness binary, version and account tier it ran against.
- [ ] AC-03: THE Runtime_Registry SHALL mark Gemini CLI or Codex CLI `supported` only when its record in `registry/census/` shows the shell, file write and file edit classes blocked and their benign twins allowed, and SHALL otherwise mark it `gap` and list the classes that did not block; Claude Code and Cursor SHALL keep `supported` on the evidence of the gate selftests and the Doctor's Cursor hook-sync check; and THE Doctor SHALL fail when a Gemini CLI or Codex CLI entry is `supported` without a census record that satisfies this criterion.
- [ ] AC-04: WHERE a harness is `supported`, THE Hook_Projector SHALL write that harness's hook configuration from `hooks.json` through the harness's tool-name map, projecting only events and tool classes its census record shows as blocking, and SHALL write every matcher token it did not project into that harness's Runtime_Registry entry.
- [ ] AC-05: WHEN a projected fail-closed gate denies, THE Hook_Shim SHALL make the harness block the call with the gate's reason, and IF the Hook_Shim cannot parse the payload for a fail-closed gate, THEN THE Hook_Shim SHALL block the call.
- [ ] AC-06: WHEN the `--selftest` of a projected fail-closed gate runs through the Hook_Shim under a `supported` harness, THE Hook_Shim SHALL make the harness block the violation leg and allow the benign leg.
- [ ] AC-07: THE Instruction_Sync SHALL read the Runtime_Registry and write `AGENTS.md` for Codex CLI and `GEMINI.md` for Gemini CLI in each arm only for harnesses marked `supported`, from that arm's `.claude/CLAUDE.md`, and a second run with no source change SHALL leave every file byte-identical.
- [ ] AC-08: WHERE a harness is `supported`, THE Runtime_Registry SHALL map the four tiers (mechanical, bulk, build, judgment) to that harness's model slugs.
- [ ] AC-09: IF an arm's `arm.json` has no `telemetry.export` field, THEN THE Export_Guard SHALL treat the arm's Export_Policy as `deny`.
- [ ] AC-10: IF the Arm_Resolution of the session finds no arm, or finds an arm whose Export_Policy is `deny`, THEN THE Export_Guard SHALL exit 0 with no output, which every harness event treats as a no-op, without starting the upstream hook process.
- [ ] AC-11: WHERE the session's arm has Export_Policy `allow`, THE Export_Guard SHALL start the upstream hook script with its original input and environment, with redaction left on.
- [ ] AC-12: THE Doctor SHALL fail when the tracing switch is set in the project settings of an arm whose Export_Policy is `deny` or absent, or in the global settings while any registered arm has Export_Policy `deny` or absent.
- [ ] AC-13: THE Package_Installer SHALL install the Tracing_Wrapper as kind `plugin` with a verified signature and a lock entry, disabled for every arm on install, run by the operator in a terminal outside any session from a command the agent prints, the agent never enabling a plugin itself; and THE Doctor SHALL fail when the installed wrapper tree does not hash to its lock entry or when the upstream `langsmith-tracing` plugin is installed in `~/.claude/plugins` outside the Tracing_Wrapper.
- [ ] AC-14: WHEN LangSmith is unreachable, measured once with the endpoint pointed at a closed local port and once at a non-routable address, THE Tracing_Wrapper SHALL let the turn finish and SHALL add, for every hook event it registers (read from the upstream plugin's hook list at measurement time), at most 50 ms at the median and 200 ms at p95 to the wall time of that event's hook list, against the same list without the wrapper, over 100 consecutive events, with the upstream plugin version recorded.
- [ ] AC-15: WHEN a pull request of this spec merges, THE Doctor SHALL report the brain WIRED, with every new script, gate and reflex it ships registered in `registry/rules.yaml`.
- [ ] AC-16: IF a write would set an arm's `telemetry.export` to `allow`, THEN THE Export_Flip_Gate SHALL deny it, leaving the flip to the operator's own hand.
- [ ] AC-17: THE Arming_Gate SHALL treat `scripts/g__shim__hook.py`, `scripts/g__wrap__export-guard.py`, `registry/runtimes.yaml`, the installed Tracing_Wrapper tree and the plugin registration files under `~/.claude/plugins/` (including `known_marketplaces.json`) as live arming files, with a violation fixture writing the live copy and a benign fixture writing a worktree copy, or, for the gitignored paths under `~/.claude/plugins/`, writing the same relative path under the temporary HOME that `gate_selftest.py` provides.
- [ ] AC-18: WHEN a Bash tool call's command invokes an External_Reviewer_CLI at a command boundary, THE External_Review_Reflex SHALL append from PreToolUse a pending External_Review_Receipt with the engine, the model, the SHA-256 of the exact prompt, the harness `tool_use_id` and the session id, and SHALL complete it from PostToolUse for the same `tool_use_id` with the SHA-256 of the full output, the exit code and a copy of the output at `~/.claude/.cache/receipts/external/<tool_use_id>.out`, without ever blocking the call.
- [ ] AC-19: THE External_Review_Reflex SHALL record the model named by the command's explicit model argument (`-m`, `--model`, or a Codex `-c model=` override) and SHALL record `unknown` when the command names none.
- [ ] AC-20: IF the prompt of the call is not readable whole from its argv text or from a stdin redirection of a named file (a pipe and a command substitution are not), THEN THE External_Review_Reflex SHALL record an empty prompt digest.
- [ ] AC-21: THE Panel_Ledger SHALL count an External_Review_Receipt as one distinct reviewer for a digest, keyed by its `tool_use_id`, only when it is complete with exit code 0, a model other than `unknown` and a non-empty prompt digest, its stored output re-hashes to its output digest and ends on a panel block whose recomputed digest equals that digest, its `tool_use_id` is a Bash `tool_use` in this session's transcript, its PostToolUse time is inside the 120-minute window, and the Reviewer_Registry marks its engine and model `allowed`, with the newest-decides and NEEDS-WORK-revokes rules unchanged.
- [ ] AC-22: THE Panel_Ledger SHALL report a quorum as met only when at least one of its receipts comes from a harness reviewer subagent, so an External_Review_Receipt adds to a quorum and never forms one alone.
- [ ] AC-23: IF the Arm_Resolution of the session finds an arm whose Export_Policy is not `allow`, THEN THE Panel_Ledger SHALL count no External_Review_Receipt of that session.
- [ ] AC-24: WHEN a reviewer subagent's final report carries a `REVIEW-EXTERNAL: <tool_use_id>` line naming a complete External_Review_Receipt of the same session whose stored output ends on the same verdict, THE QA_Receipt_Reflex SHALL add that receipt's engine and model to the `qa` or `panel` receipt it writes as `external_reviewers`, leaving the receipt's agent type, verdict and every qa-merge-gate requirement unchanged.
- [ ] AC-25: THE Doctor SHALL derive the Runtime_Registry status of Codex CLI and Gemini CLI only from their census records as AC-03 states, so an `allowed` Reviewer_Registry entry or a Replay_Record for either engine leaves its runtime status `gap` until its census record shows shell, file write and file edit blocked.
- [ ] AC-26: THE Replay_Fixture_Set SHALL hold at least 40 cases whose expected verdict is NEEDS-WORK, at least 15 of them wrong facts and at least 15 overstatements (the two classes the v11 cost measurement names), and at least 40 cases whose expected verdict is PASS, each with a synthetic reply body, the source excerpts the reviewer is given, the expected verdict and, for a NEEDS-WORK case, its defect class and the line that carries the defect, written from the defect classes of historical NEEDS-WORK receipts and never copied from a transcript, an arm or the ledger.
- [ ] AC-27: THE Doctor SHALL fail when a file of the Replay_Fixture_Set or a Replay_Record holds an absolute user path, a `$HOME` path or a hit of `scripts/check-generic.py`.
- [ ] AC-28: WHEN the Replay_Harness runs for an engine and model, THE Replay_Harness SHALL give each case to the reviewer as the block `panel_digest.py --panel-request` prints plus its source excerpts, read the verdict with `receipt_ledger.parse_panel`, count an unparseable, failed or timed-out answer as a miss on a NEEDS-WORK case and as a false alarm on a PASS case, and write a Replay_Record with the catch rate (NEEDS-WORK cases answered NEEDS-WORK over all NEEDS-WORK cases), the false-alarm rate (PASS cases not answered PASS over all PASS cases), the counts, the engine, the model, the CLI version, the git tree hash of the Replay_Fixture_Set and the date.
- [ ] AC-29: THE Replay_Harness SHALL run the baseline on Fable, fall back to Opus only when the Fable call is refused for quota or credits, and record in the baseline Replay_Record which model ran and why.
- [ ] AC-30: THE Reviewer_Registry SHALL mark an engine and model `allowed` only when its Replay_Record and the baseline Replay_Record carry the same fixture tree hash, its catch rate is at least the baseline catch rate minus 0.05, and its false-alarm rate is at most the baseline false-alarm rate plus 0.10.
- [ ] AC-31: THE Doctor SHALL recompute every `allowed` entry of the Reviewer_Registry from its Replay_Record and the baseline Replay_Record, and fail when the AC-30 bound does not hold or when either record's fixture tree hash differs from the tracked Replay_Fixture_Set.
- [ ] AC-32: THE Arming_Gate SHALL treat both External_Review_Reflex scripts, `registry/reviewers.yaml` and `registry/replay/` as live arming files, with a violation fixture writing the live copy and a benign fixture writing a worktree copy.

## Technical Scope

- New: `registry/runtimes.yaml`, `registry/census/`, `scripts/runtime_census.py`, `scripts/g__shim__hook.py`, `scripts/merge-hooks-gemini.py`, `scripts/merge-hooks-codex.py` (only if Codex is `supported`), `scripts/g__wrap__export-guard.py`, `scripts/g__pretool__export-flip.py`, the Tracing_Wrapper package.
- Changed: `scripts/octo_pkg.py` (kind `plugin`), `scripts/brain_doctor.py` (registry, export and plugin checks), `scripts/ai_sync.py` (Instruction_Sync), `scripts/g__pretool__arming-surface.py` (new arming files), `templates/arm/arm.json.template` (`telemetry.export`), `docs/architecture/multi-runtime.md`, `registry/rules.yaml`, `hooks.json`.
- `hooks.json`, gate scripts, `brain_doctor.py` and `registry/rules.yaml` are on the arming surface: every edit is written in a worktree and reaches the live tree only by pull.
- Phase 4, new: `scripts/r__pretool-bash__external-review.py`, `scripts/r__posttool-bash__external-review.py`, `registry/reviewers.yaml`, `registry/replay/fixtures/`, `registry/replay/records/`, `scripts/review_replay.py`. Changed: `scripts/receipt_ledger.py` (Panel_Ledger), `scripts/r__subagent-stop__qa-receipt.py`, `scripts/brain_doctor.py`, `scripts/g__pretool__arming-surface.py`, `hooks.json`, `registry/rules.yaml`, `docs/architecture/v11-reply-panel.md` (R-05 restated against AC-21 and AC-22).

## Non-Functional Requirements

- No guarantee from v7 to v11 is weakened on Claude Code: every existing gate keeps its fixtures and its decisions.
- No census, fixture or test reads client data; tracked census records and fixtures carry no arm name and no `$HOME` path, and guard fixtures use synthetic arm roots under the temporary HOME that `gate_selftest.py` already isolates.
- No secret, API key or message body is written to any tracked file.
- Every number in a commit or doc carries its measurement mode and source.

## Release Criterion

The minor release ships when every criterion has a CONVERGED verdict, and only after v11.0.0 is cut, so the version bump lands on v11.1.0. It becomes a major release (v12, cut with the `Octorato-Major:` trailer) only if the `plugin` kind or the census changes the schema of `packages.lock.json` or the block contract of an existing gate; an additive change stays minor (`docs/wiki/Self-Growth.md`). If the Runtime_Census marks both new harnesses as `gap`, the release ships the registry, the census and the whole tracing track, with both gaps documented, and adds no harness.

## Out of Scope

- LangChain and LangGraph as a dependency of the brain. Model choice belongs to the harness, and the 7 scripts above use vendor-specific features a model abstraction does not cover. A durable workflow engine is a different product; an arm that needs one adopts it on its own.
- LangSmith Deployment and any self-hosted LangSmith.
- The OpenTelemetry route to LangSmith. LangSmith documents only OTLP traces, and Claude Code's trace export is beta; revisit when both are stable.
- Hosted tools in Codex CLI, which its `PreToolUse` does not cover.
- The v11 work merged in #417 (no reply unreviewed); this spec builds on it and does not change it.
- Phase 4: an external engine forming a quorum alone, replacing the judgment-tier reviewer, or acting as a QA reviewer that qa-merge-gate honours without a harness QA subagent.
- Phase 4: any runtime status change for Codex CLI or Gemini CLI; FR-01 and AC-03 stay the only route to `supported`.
- Phase 4: replaying real panel bodies; the ledger stores digests, and the bodies live in private transcripts, so the replay set is synthetic.

## Revision History

- 2026-10-15: rebased on master after v11 (#417, `e3b5141`); retargeted from the next v10 minor to the next v11 minor; Release Criterion states when it would become v12.
- 2026-10-14: draft from the LangChain and LangGraph deep research, the Gemini CLI and Codex CLI hook documentation, and the LangSmith Claude Code plugin documentation.
- 2026-10-14: analyze pass (A01 to A18) applied. The tracer is a signed wrapper plugin whose guard decides whether the upstream hook process starts; octo pkg gains kind `plugin`; the flip to `allow` gets its own gate; shim, guard and registry join the arming surface; Gemini and Codex facts restated from primary pages, the unsupported Enterprise and experimental-flag claims removed; Claude Code and Cursor keep status on existing evidence; census method made deterministic plus one live call; failure modes for the latency bound named.
- 2026-10-14: analyze pass 2 (B01 to B07) applied. The installed wrapper and the plugin registration files join the arming surface and the Doctor hashes the wrapper against its lock; the plugin install is an operator terminal step; the latency bound covers every event the wrapper registers; the guard's no-arm and deny exit is a no-op; the Doctor recomputes a `supported` status from its census record.
- 2026-10-14: analyze pass 3 PASS; wording fixes C01 (table name) and C02 (benign fixture for gitignored plugin paths) applied.
- 2026-10-16: phase 4 appended, LLM independence for reviewers (FR-05 to FR-07, AC-18 to AC-32, T19 and T20); no earlier criterion or task changed. Grounded in `scripts/receipt_ledger.py`, `scripts/r__subagent-stop__qa-receipt.py`, `scripts/panel_digest.py` and `docs/architecture/v11-reply-panel.md` R-05.
