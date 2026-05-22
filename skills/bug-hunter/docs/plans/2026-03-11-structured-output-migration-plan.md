# Canonical Structured Outputs For Bug Hunter

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This repository does not contain a checked-in `PLANS.md`, but this document is written to the same standard as the machine-local ExecPlan reference at `/Users/codex/Downloads/Code Files/PLANS.md`. Keep this plan self-contained as implementation proceeds.

## Purpose / Big Picture

After this change, Bug Hunter will use one canonical structured contract from end to end. Each phase will emit validated JSON as the source of truth, while Markdown becomes a rendered report for humans. This matters because the current system mixes Markdown prompts, ad hoc parsing, and JSON side channels, which makes the pipeline slower, harder to validate, and more likely to drift into false positives, silent false negatives, or broken fix eligibility.

The user-visible result is simple to verify. A bug-hunter run should create phase artifacts such as `.bug-hunter/recon.json`, `.bug-hunter/findings.json`, `.bug-hunter/skeptic.json`, `.bug-hunter/referee.json`, `.bug-hunter/coverage.json`, and `.bug-hunter/fix-report.json`. The same run should still produce readable Markdown reports, but those Markdown files must be generated from the JSON artifacts rather than being the only source of truth. A failed or malformed phase output should be rejected immediately with a precise validation error and a retry path instead of slipping through as an empty or partially parsed report.

## Progress

- [x] (2026-03-11 18:40Z) Create versioned JSON schemas for `recon`, `findings`, `skeptic`, `referee`, `coverage`, `fix-report`, plus shared definitions under `schemas/`.
- [x] (2026-03-11 18:40Z) Add `scripts/schema-runtime.cjs` and `scripts/schema-validate.cjs`, ship `schemas/` in the npm package, and add example valid/invalid `findings.json` fixtures.
- [x] (2026-03-11 18:40Z) Wire strict findings validation into `payload-guard.cjs`, `bug-hunter-state.cjs`, and `run-bug-hunter.cjs`, including retry-on-invalid-findings inside the chunk worker loop.
- [x] (2026-03-11 20:05Z) Replace Markdown-only phase prompting with JSON-first prompting plus rendered Markdown output guidance, including `scripts/render-report.cjs`.
- [x] (2026-03-11 20:05Z) Normalize confidence to numeric values in canonical findings/referee contracts and fix-plan eligibility.
- [x] (2026-03-11 20:05Z) Replace `coverage.md` as canonical loop state with `coverage.json` and keep `coverage.md` as a derived summary.
- [x] (2026-03-10 21:06Z) Add strict inbound and outbound validation, retry logic, and eval coverage for malformed outputs and stale contracts.
- [x] (2026-03-11 20:05Z) Update core documentation, mode docs, wrapper templates, and eval text so they match the full-queue loop semantics and the new structured contracts.

## Surprises & Discoveries

- Observation: the orchestrator already has a JSON worker path, but the main prompts still tell agents to write Markdown reports.
  Evidence: `scripts/run-bug-hunter.cjs` writes and reads `chunk-<id>-findings.json`, while `prompts/hunter.md` still directs output to `.bug-hunter/findings.md`.

- Observation: fix planning expects numeric confidence, but the Referee prompt still emits `High/Medium/Low`.
  Evidence: `scripts/run-bug-hunter.cjs` filters fix eligibility with `confidence >= confidenceThreshold`, while `prompts/referee.md` asks for `Confidence: High/Medium/Low`.

- Observation: loop state is still a machine-parseable Markdown document, which is more brittle than the rest of the JSON-capable pipeline.
  Evidence: `modes/loop.md` defines `.bug-hunter/coverage.md` with line-based sections and a checksum format instead of a JSON state file.

- Observation: evaluation fixtures still encode the earlier `CRITICAL/HIGH` stopping rule.
  Evidence: `evals/evals.json` case `id: 6` still expects completion once all CRITICAL and HIGH files are done.

- Observation: once schema refs become real runtime assets, isolated skill copies must include `schemas/` as well as `scripts/`.
  Evidence: the preflight isolation test needed `schemas/findings.schema.json` and the new schema helper scripts copied into the sandbox to stay representative.

- Observation: deduplicated findings now inherit the strongest numeric confidence for the shared `file|lines|claim` key, which changes low-confidence metrics compared with the previous loose merge.
  Evidence: `scripts/bug-hunter-state.cjs` now validates findings before merge and keeps the maximum `confidenceScore` for duplicate keys, which required updating the state test expectation.

- Observation: the remaining validation gap closed cleanly once the runner exposed a generic schema-validated phase command instead of baking phase-specific logic into docs.
  Evidence: `scripts/run-bug-hunter.cjs` now exposes `phase`, validates any named artifact after each attempt, and retries malformed Skeptic/Referee/Fix outputs before the phase succeeds.

## Decision Log

- Decision: use provider-agnostic local JSON schemas as the source of truth, and treat provider-native structured outputs as an optimization layer.
  Rationale: Bug Hunter runs across multiple agent backends and CLIs. Native structured outputs from Claude, OpenAI, and Gemini can improve reliability where available, but the skill must remain correct on backends that only support plain prompting and local validation.
  Date/Author: 2026-03-11 / Codex

- Decision: keep Markdown reports, but generate them from validated JSON artifacts.
  Rationale: humans still need readable reports, but machine-state should not depend on brittle line parsing or prompt formatting quirks.
  Date/Author: 2026-03-11 / Codex

- Decision: normalize confidence to both `confidence_score` and `confidence_label`.
  Rationale: numeric confidence is required for fix eligibility and consistency checks, while a short label remains useful for readable reports.
  Date/Author: 2026-03-11 / Codex

- Decision: migrate loop state from `coverage.md` to `coverage.json` and keep a rendered `coverage.md` for visibility.
  Rationale: the loop is the long-lived state carrier. It benefits the most from strict schema validation, resumability, and safe retries.
  Date/Author: 2026-03-11 / Codex

- Decision: ship the schema files as package assets and treat missing schema files as a preflight failure.
  Rationale: payload guards and worker validation now depend on the checked-in schema files at runtime, so an install missing `schemas/` is broken even if the scripts themselves exist.
  Date/Author: 2026-03-11 / Codex

## Outcomes & Retrospective

This migration milestone is now complete. Bug Hunter rejects malformed `findings.json` artifacts before they reach state, retries the worker when those artifacts are invalid, ships explicit schemas plus a validator CLI, renders Markdown from canonical JSON, writes canonical `coverage.json` loop state with a derived `coverage.md` companion, and now enforces Skeptic/Referee/Fixer artifact validation through the orchestrated `run-bug-hunter.cjs phase` path as well as the manual/local path.

## Context and Orientation

Bug Hunter is a skill package rooted at `/Users/codex/.agents/skills/bug-hunter`. The important files for this work are spread across prompts, mode documents, helper scripts, and tests.

`prompts/hunter.md`, `prompts/skeptic.md`, `prompts/referee.md`, and `prompts/fixer.md` define what each analysis phase writes today. They currently emphasize Markdown output with free-form sections and line-oriented formats. This is the main place where drift enters the system.

`scripts/run-bug-hunter.cjs` is the orchestration helper that manages chunk execution, retries, delta expansion, consistency reports, and fix-plan generation. It already understands JSON findings files written by workers. This file is the best anchor for the migration because it already behaves like a JSON pipeline in the tests.

`scripts/bug-hunter-state.cjs` stores durable scan state such as chunk progress, a bug ledger, fact cards, consistency information, and fix plans. It currently records findings from JSON files, but it does not validate rich schemas and it accepts incomplete objects as long as basic fields exist.

`scripts/payload-guard.cjs` validates worker payloads before launch. Right now it only checks that required top-level fields exist and that `outputSchema` is “an object”. It does not enforce real schemas for either inbound or outbound data.

`modes/loop.md` and `modes/fix-loop.md` define the iterative audit loop. They currently store machine state in `.bug-hunter/coverage.md`, which is a Markdown file with line-based sections. That format is readable but brittle and expensive to maintain compared with JSON.

`evals/evals.json` and `scripts/tests/*.test.cjs` are the safety net. They currently prove parts of the JSON worker path, but they do not yet enforce full end-to-end structured outputs or the newly required full-queue loop semantics.

In this plan, “structured output” means a phase result that conforms to a versioned JSON schema that can be validated locally with no guesswork. “Canonical artifact” means the file every later phase trusts as the source of truth. “Rendered report” means a human-readable Markdown file generated from a validated JSON artifact.

## Plan of Work

The work starts by defining stable versioned schemas in a new directory, `schemas/`, under the skill root. Create one schema module per artifact: `recon`, `findings`, `skeptic`, `referee`, `coverage`, `fix-report`, and any shared types such as file coverage entries, cross-reference items, STRIDE/CWE metadata, and confidence values. Use plain JSON Schema stored in `.json` files or JavaScript schema builders that output JSON Schema, but keep the final schemas serializable and versioned. Each schema must include a `schemaVersion` field. Confidence must be represented as `confidenceScore` on a numeric 0–100 scale, and optionally `confidenceLabel` derived from it for rendered reports.

Next, add a schema runtime helper under `scripts/`, for example `scripts/schema-validate.cjs`, that can validate any named artifact file and print a short machine-readable result. This helper must be used in three places: when generating payloads, when reading worker outputs, and when reading persisted loop state. Expand `scripts/payload-guard.cjs` so the role templates point to real output schemas rather than placeholder `format/version` objects. The guard should reject missing or mismatched schema names before work starts.

Then migrate the prompts. `prompts/hunter.md`, `prompts/skeptic.md`, `prompts/referee.md`, and `prompts/fixer.md` should stop treating Markdown as the primary output. Instead they should instruct the agent to write a JSON array or object to the assigned canonical path, and optionally write a rendered Markdown companion file if the assignment requests it. The JSON contract must be concrete. For example, Hunter findings must include `bugId`, `severity`, `category`, `file`, `lines`, `claim`, `evidence`, `runtimeTrigger`, `crossReferences`, and `confidenceScore`. Referee verdicts must include `verdict`, `trueSeverity`, `confidenceScore`, `confidenceLabel`, `verificationMode`, and enriched security fields where applicable. Keep the prose reasoning, but move it into explicitly typed fields such as `analysisSummary` instead of free-form blocks.

Once the prompts are changed, update the orchestrator and state layer to consume the new contracts only. In `scripts/run-bug-hunter.cjs`, treat missing worker JSON output as a hard phase failure unless the phase explicitly allows zero results via a valid empty array. Validate every worker output before recording it in state. If validation fails, journal the schema error, mark the chunk or phase as failed, and let the retry logic rerun the worker. In `scripts/bug-hunter-state.cjs`, reject findings entries that omit required fields, and enrich ledger entries with normalized keys such as `confidenceScore`, `severity`, `category`, and `verificationMode`. Do not silently continue when a result is malformed.

After the phase artifacts are stable, migrate loop state. Add a new canonical file, `.bug-hunter/coverage.json`, and make it the state the loop reads and writes. It should contain top-level metadata, file coverage entries, cumulative bugs, fix ledger entries, and the current loop status. Keep `.bug-hunter/coverage.md`, but generate it from `coverage.json` after each iteration so humans can still inspect progress. Update `modes/loop.md` and `modes/fix-loop.md` to describe the JSON state as canonical and Markdown as derived.

The provider-specific structured-output layer comes next. Add a small capability adapter under `scripts/` or `templates/` that can describe three modes: native structured output supported, native unsupported but JSON prompting available, and plain-text fallback with local validation. Do not make provider-native structured outputs mandatory for correctness. When the backend supports them, use the local schema definitions to generate provider-specific requests. For Claude this means schema-constrained output or strict tool result patterns where available. For OpenAI this means strict structured outputs using JSON Schema and handling refusals or first-schema latency explicitly. For Gemini this means `responseMimeType: application/json` with `responseSchema`. If a backend does not support native structured output, keep the prompt JSON-first and validate locally after the response.

Finally, update every test and eval path. Add tests for schema validation failures, malformed worker outputs, missing `confidenceScore`, invalid coverage state, and rendered Markdown generation from JSON. Update `evals/evals.json` to require full queued coverage semantics and the presence of canonical JSON artifacts. Keep the existing worker fixture tests, but add one fully integrated smoke path that simulates a Hunter JSON output, a Skeptic JSON output, a Referee JSON output, and the resulting fix-plan eligibility.

## Milestones

### Milestone 1: Define the canonical data contracts

At the end of this milestone, the repository has explicit versioned schemas for every phase artifact, and a local validator can reject malformed files deterministically. Nothing user-visible changes yet, but the implementation gains a stable foundation. This milestone is complete when a novice can run schema validation against a sample `findings.json` and see success, then remove a required field and see a validation failure with a helpful error.

### Milestone 2: Convert prompts and orchestrator to JSON-first phase outputs

At the end of this milestone, Hunter, Skeptic, Referee, and Fixer all emit canonical JSON artifacts, and the orchestrator only accepts validated JSON for state updates. Markdown reports still exist, but they are generated from JSON. This milestone is complete when a simulated worker run produces `findings.json`, the orchestrator records it, and a malformed output fails fast with retry instead of silently succeeding.

### Milestone 3: Migrate loop state to JSON and align semantics

At the end of this milestone, `.bug-hunter/coverage.json` is the canonical loop state, the loop uses full queued coverage semantics, and `.bug-hunter/coverage.md` is a rendered summary. This milestone is complete when a loop simulation can resume from `coverage.json`, continue through queued files, and render a readable Markdown view from the same state.

### Milestone 4: Add provider-native structured output adapters and end-to-end safety tests

At the end of this milestone, the skill can optionally use native structured outputs for Claude, OpenAI, or Gemini capable backends, but still behaves correctly without them. The tests and evals enforce the new contracts. This milestone is complete when the provider adapter selects the correct mode, malformed outputs are rejected across all supported execution paths, and evals no longer encode the obsolete `CRITICAL/HIGH` stopping rule.

## Concrete Steps

Work from `/Users/codex/.agents/skills/bug-hunter`.

1. Create the schema directory and files.

    mkdir -p docs/plans schemas

    Add files such as:
      schemas/findings.schema.json
      schemas/skeptic.schema.json
      schemas/referee.schema.json
      schemas/coverage.schema.json
      schemas/fix-report.schema.json
      schemas/recon.schema.json
      schemas/shared.schema.json

    Expected result: the `schemas/` directory exists and each schema file includes `schemaVersion`.

2. Add a validation helper.

    Create `scripts/schema-validate.cjs` and teach it:
      - how to load a schema by name
      - how to validate a file path
      - how to print JSON success or JSON error output

    Expected result:

      node scripts/schema-validate.cjs findings schemas/examples/findings.valid.json
      {"ok":true,"artifact":"findings"}

      node scripts/schema-validate.cjs findings schemas/examples/findings.invalid.json
      {"ok":false,"artifact":"findings","errors":["missing required property: claim"]}

3. Update `scripts/payload-guard.cjs` and `scripts/run-bug-hunter.cjs`.

    Replace placeholder `outputSchema` objects with real schema references. Validate worker outputs before calling `record-findings` or any equivalent state write.

    Expected result: a malformed findings file causes the chunk to fail with a schema error instead of being recorded as partial success.

4. Update the prompts and rendered-report flow.

    Change prompt files so JSON is the primary output. Add a renderer script such as `scripts/render-report.cjs` if needed.

    Expected result: a run produces both JSON and Markdown, with Markdown fully derivable from JSON.

5. Migrate loop state.

    Add `coverage.json`, update `modes/loop.md` and `modes/fix-loop.md`, and render `coverage.md` from JSON.

    Expected result: the loop resumes from JSON state and no longer depends on parsing Markdown line structure.

6. Update tests and evals.

    Run:

      node --test scripts/tests/*.test.cjs

    Add tests for malformed artifacts, missing confidence scores, bad coverage state, and rendered Markdown output. Update `evals/evals.json` so loop completion requires full queued coverage, not just CRITICAL and HIGH completion.

## Validation and Acceptance

Acceptance is behavior-based.

First, run the script tests from `/Users/codex/.agents/skills/bug-hunter`:

    node --test scripts/tests/*.test.cjs

Expect all tests to pass, including new tests that fail before the migration because the old code accepted malformed outputs or textual confidence.

Second, run a local orchestrator smoke path with a valid worker fixture. It must produce canonical JSON output files and a rendered Markdown report. Observe:

    .bug-hunter/findings.json
    .bug-hunter/referee.json
    .bug-hunter/fix-report.json
    .bug-hunter/coverage.json
    .bug-hunter/report.md

Third, deliberately break one phase artifact by removing a required field such as `claim` or `confidenceScore`. Re-run the same smoke path and expect:

    - the phase fails
    - the journal records a schema validation error
    - state is not updated from the malformed artifact
    - retry logic is allowed to rerun the worker

Fourth, run a loop simulation and verify that completion only occurs when every queued scannable file is marked done in `coverage.json`, not merely when CRITICAL and HIGH files are done.

## Idempotence and Recovery

The migration should be safe to run incrementally. Schema files and validators are additive. During implementation, keep Markdown outputs in parallel with JSON outputs until all consumers are switched over. Do not remove Markdown files until JSON-based rendering and validation are proven.

If a phase fails because of schema validation, the safe recovery path is to fix the producer prompt or fixture and rerun the same command. Because the state update happens after validation, malformed outputs should not poison the state file.

When migrating loop state, keep a one-time importer from `coverage.md` to `coverage.json` or, if that is too brittle, explicitly start fresh and document that old Markdown loop state is not resumable across the migration. Choose one path and document it in the implementation notes.

## Artifacts and Notes

The most important implementation artifacts should be:

    schemas/*.schema.json
    scripts/schema-validate.cjs
    scripts/render-report.cjs
    .bug-hunter/*.json
    .bug-hunter/report.md
    .bug-hunter/coverage.md

Expected evidence after completion:

    $ node scripts/schema-validate.cjs findings .bug-hunter/findings.json
    {"ok":true,"artifact":"findings"}

    $ node --test scripts/tests/*.test.cjs
    ℹ pass <updated-count>
    ℹ fail 0

## Interfaces and Dependencies

Define these stable interfaces by the end of the work:

In `schemas/findings.schema.json`, define a findings artifact that is an array of finding objects. Each finding object must include:

    bugId: string
    severity: "Critical" | "Medium" | "Low"
    category: string
    file: string
    lines: string
    claim: string
    evidence: string
    runtimeTrigger: string
    crossReferences: array
    confidenceScore: number

In `schemas/referee.schema.json`, define a verdict artifact with:

    bugId: string
    verdict: "REAL_BUG" | "NOT_A_BUG" | "MANUAL_REVIEW"
    trueSeverity: "Critical" | "Medium" | "Low"
    confidenceScore: number
    confidenceLabel: string
    verificationMode: "INDEPENDENTLY_VERIFIED" | "EVIDENCE_BASED"
    analysisSummary: string

In `schemas/coverage.schema.json`, define loop state with:

    schemaVersion: number
    iteration: number
    status: "IN_PROGRESS" | "COMPLETE"
    files: array of file coverage entries
    bugs: array of confirmed bug summaries
    fixes: array of fix ledger entries

In `scripts/schema-validate.cjs`, implement a CLI with:

    node scripts/schema-validate.cjs <artifact-name> <file-path>

In `scripts/render-report.cjs`, implement a CLI that renders Markdown from JSON artifacts:

    node scripts/render-report.cjs report .bug-hunter/findings.json .bug-hunter/referee.json > .bug-hunter/report.md

Provider-native structured output adapters, if added, must consume these local schemas rather than inventing provider-specific contracts.

## Change Log For This Plan

2026-03-11: Initial ExecPlan created after the structured-output audit. The plan chooses provider-agnostic local schemas as the foundation and treats Claude/OpenAI/Gemini native structured outputs as optional accelerators rather than the source of truth.
