# Feature: v9, Done Is a Verdict

> **Status:** converged
> **Spec-Format:** ears-1
> **Date:** 2026-09-30
> **Classification:** LARGE (score 11: 10+ files, new feature, architectural decision, multiple modules)

v7 made a send without receipts impossible. v8 made a run a process. v9 makes "done" a verdict computed against a spec, never a claim typed by the agent that did the work.

## Summary

Today the SDD flow lets the builder grade itself. `sdd-implement` writes `impl-summary.md` with `[x] AC-01: Passed`, and `sdd-review` ticks the acceptance criteria in `feature.md`. Both are completion claims made by the process that wrote the code. Nothing checks the plan against the spec before implementation, and nothing deterministic can read a spec, because acceptance criteria are free prose.

v9 closes that in three layers. Acceptance criteria are written in EARS, so a script can parse them. A deterministic linter checks the spec and the plan, including that every criterion is covered by a task. Completion is decided by an independent converge pass whose verdict is recorded by a hook, and the word `converged` on a spec cannot merge without that receipt.

The method is benchmarked against two public products read on 2026-09-30: GitHub Spec Kit v1.0.13 (clarify, analyze, converge, a marker cap) and the Kiro documentation (EARS acceptance criteria with a glossary of named components). Neither enforces its flow with fail-closed gates. That enforcement is what this brain adds.

## Glossary

Every acceptance criterion names one of these components as its subject.

- **Spec**: a `feature.md` that declares `Spec-Format: ears-1` in its header.
- **Spec_Author**: the `sdd-feature` skill.
- **Refiner**: the `sdd-refine` skill.
- **Planner**: the `sdd-plan` skill.
- **Spec_Linter**: `scripts/spec_lint.py`, a deterministic stdlib-only CLI. No model call.
- **Analyzer**: the new `sdd-analyze` skill, run as a subagent on the judgment tier.
- **Implementer**: the `sdd-implement` skill.
- **Converger**: the new `sdd-converge` skill, run as a subagent on the judgment tier.
- **Reviewer**: the `sdd-review` skill.
- **Orchestrator**: the `4d-spec` skill and the `sdd-yolo` fast path.
- **Receipt_Ledger**: `scripts/receipt_ledger.py` plus a SubagentStop reflex.
- **Push_Gate**: `.githooks/pre-push`.
- **Doctor**: `scripts/brain_doctor.py`.

## User Stories

- As the operator, I want "done" to be decided by a pass that did not write the code, so that a confident summary cannot stand in for working software.
- As the operator, I want a spec a script can read, so that coverage gaps are found by a command and not by my review.
- As an agent building a LARGE change, I want the plan checked against the spec before I write code, so that a missing requirement costs one report and not one rework.

## Functional Requirements

### FR-01: EARS acceptance criteria

Acceptance criteria use the five EARS patterns: ubiquitous (`THE <Component> SHALL`), event (`WHEN <trigger>, THE <Component> SHALL`), state (`WHILE <state>, THE <Component> SHALL`), unwanted behaviour (`IF <condition>, THEN THE <Component> SHALL`), optional (`WHERE <feature>, THE <Component> SHALL`). Open questions become inline `NEEDS CLARIFICATION` markers in square brackets, which replace the old "Open Questions" section.

### FR-02: Task grammar and mechanical coverage

Plan tasks follow one grammar: `- [ ] T## [AC-##, AC-##] <path>, <path>: <action>`, with one or more criterion ids and one or more paths. With that grammar, criterion-to-task coverage is computed, not judged.

### FR-03: Analyze before implement

A read-only pass by an agent that did not write the plan compares `feature.md`, `plan.md` and the governing rules file, and reports findings. It runs for LARGE tasks only.

### FR-04: Converge decides completion

After implementation, an independent pass verifies each criterion against the code and tests in the working tree. Gaps become appended tasks. With no gaps, the plan is left untouched. The builder and the reviewer stop asserting criterion status.

### FR-05: Converge receipt and the push gate

The converge verdict is recorded by a hook, the same way the QA verdict is. A spec can only be marked `converged` in a push that carries that receipt. The check lives in the push gate and not in the merge gate, because the merge gate runs in a 5 second hook with no network call and sees only the pull request number, never its diff. The push gate sees the exact commits and belongs to this repository only, which is the scope the operator chose.

### FR-06: Wiring

Every new rule is registered, fixture-proven and anchored, per RULE #1.

### FR-07: Flow surfaces

The orchestrator, the fast path and the documentation describe one flow: feature, refine, plan, analyze, implement and converge in a loop, review, archive. TRIVIAL and MEDIUM tasks keep their current flow.

### FR-08: Clarify one question at a time

Refinement asks one question, offers a recommended answer, and writes the answer into the spec before asking the next.

## Acceptance Criteria

- [ ] AC-01: THE Spec_Author SHALL write every acceptance criterion as a single EARS sentence with a unique `AC-##` id whose subject is a Glossary component.
- [ ] AC-02: WHEN the Spec_Linter reads a Spec containing an acceptance criterion that matches no EARS pattern, THE Spec_Linter SHALL exit non-zero and print the file and line.
- [ ] AC-03: IF a Spec carries more than 3 `[NEEDS CLARIFICATION]` markers, THEN THE Spec_Linter SHALL exit non-zero.
- [ ] AC-04: WHILE a Spec carries any `[NEEDS CLARIFICATION]` marker, THE Planner SHALL refuse to write `plan.md` and SHALL name the open markers.
- [ ] AC-05: THE Planner SHALL write every task as `- [ ] T## [AC-##] <path>: <action>`, with one or more criterion ids and one or more paths.
- [ ] AC-06: WHEN the Spec_Linter reads a `plan.md` beside a Spec, THE Spec_Linter SHALL exit non-zero if any acceptance criterion is referenced by no task or any task references an unknown criterion id.
- [ ] AC-07: WHEN a LARGE task has a Spec and a `plan.md` and no implementation file has been written, THE Analyzer SHALL produce a findings report with stable ids, capped at 50 findings, and SHALL modify no file.
- [ ] AC-08: THE Implementer SHALL NOT record acceptance criterion status in `impl-summary.md` or in the Spec.
- [ ] AC-09: THE Reviewer SHALL NOT change acceptance criterion checkboxes in the Spec.
- [ ] AC-10: WHEN the Implementer reports completion, THE Converger SHALL judge each acceptance criterion from the code and tests in the working tree and SHALL ignore `impl-summary.md` and checkbox state as evidence.
- [ ] AC-11: IF the Converger finds a criterion unmet, partial or contradicted, THEN THE Converger SHALL append a `## Convergence <n>` section of tasks to `plan.md`, SHALL change no other byte of it, and SHALL end with `CONVERGE-VERDICT: GAPS`.
- [ ] AC-12: WHEN the Converger finds every criterion met, THE Converger SHALL leave `plan.md` byte-identical and SHALL end with `CONVERGE-VERDICT: CONVERGED` and `CONVERGE-SCOPE: <spec directory>`.
- [ ] AC-13: WHEN a subagent of a verifier persona ends with `CONVERGE-VERDICT` and `CONVERGE-SCOPE` lines, THE Receipt_Ledger SHALL record the verdict with the harness-written agent transcript path.
- [ ] AC-14: IF a pushed commit range changes a Spec header to `Status: converged` and the latest converge receipt for that spec directory is not a `CONVERGED` verdict whose transcript timestamp is newer than the newest commit on the branch that touches a path outside that directory, THEN THE Push_Gate SHALL block the push.
- [ ] AC-15: IF a pushed commit changes a Spec or its `plan.md` and the Spec_Linter exits non-zero on it, THEN THE Push_Gate SHALL block the push.
- [ ] AC-16: THE Spec_Linter SHALL skip any `feature.md` that does not declare `Spec-Format: ears-1`.
- [ ] AC-17: WHEN the Doctor runs, THE Doctor SHALL report each v9 rule as wired, with its violation fixture blocking and its benign fixture allowing.
- [ ] AC-18: THE Orchestrator SHALL route LARGE tasks through feature, refine, plan, analyze, implement, converge, review and archive in that order, and SHALL repeat implement and converge until the verdict is `CONVERGED`.
- [ ] AC-19: WHEN the Refiner needs a clarification, THE Refiner SHALL ask one question with a recommended answer and SHALL apply the answer to the affected section before asking another.
- [ ] AC-20: WHEN the Spec_Linter reads this Spec with its markers resolved, THE Spec_Linter SHALL exit zero.
- [ ] AC-21: THE Planner SHALL write at most 20 tasks above the first Convergence section.
- [ ] AC-22: THE Spec_Author SHALL create each Spec in its own directory `docs/specs/<yyyymmddHHMM>-<feature-name>/`, and no later step SHALL move a Spec out of it.

## Technical Scope

### Affected Modules

- Skills: `4d-spec`, `sdd-feature`, `sdd-refine`, `sdd-plan`, `sdd-implement`, `sdd-review`, `sdd-yolo`, `sdd-archive`.
- Gates: `.githooks/pre-push`, `scripts/brain_doctor.py`, `scripts/receipt_ledger.py`, `scripts/r__subagent-stop__qa-receipt.py`.
- Registry: `registry/rules.yaml`, `registry/fixtures/`. No hook is added; the existing SubagentStop reflex is extended.
- Docs: `CLAUDE.md` (the 4D+S section plus a new anchor), `docs/CAPABILITIES.md`, `docs/wiki/Skills.md`, `docs/wiki/The-4D-Paradigm.md`, `docs/wiki/Glossary.md`, `ROADMAP.md`, `CHANGELOG.md`.
- Graph: `connectome/lineage.yaml` (the `sdd` concept has no edge today).
- Docs: `docs/ANATOMY.md` (its 4D+S table).

### New Components Required

- `skills/sdd-analyze/` and `skills/sdd-converge/`, each with `SKILL.md` and `skill.json`.
- `scripts/spec_lint.py` with `--selftest` and a fixture pair.
- `docs/architecture/v9-done-is-a-verdict.md`, the contract document, following the v7 and v8 precedent.

### Integration Points

- The receipt ledger and the QA receipt reflex (`QA-VERDICT` and `QA-SCOPE` are the pattern the converge lines copy).
- The arming surface: gate bodies are edited in a worktree, never on the live tree.
- `octo pkg manifests`: two new skill directories need manifests or the count turns partial and fails.

## Non-Functional Requirements

- **Determinism:** the Spec_Linter uses the standard library only and gives the same answer on the same input.
- **Hot path:** no new `PreToolUse *` hook. The linter runs at push time and on demand.
- **Cost:** analyze and converge run for LARGE tasks only. TRIVIAL and MEDIUM add zero agent calls.
- **Honesty of the claim:** the receipt is anchored to a transcript under `$HOME`, so it is visible and recorded, not unforgeable. Same residual v7 states. Receipts are local to the machine that ran the converge pass, so that machine is the one that pushes the status change.
- **Licensing:** skill text is written new. If any Spec Kit template text is copied, its MIT notice travels with it.
- **Language:** English only, per the public-repo rule.

## Release Criterion

v9.0.0 is cut by the operator with an `Octorato-Major:` trailer once every criterion above holds on master and the Converger returns `CONVERGED` for this spec. This follows the v8 precedent, where v8.0.0 was cut after all phases had landed and the criterion read true on the live tree.

## Out of Scope

- Scoped steering (loading rules by glob or description in place of the full `CLAUDE.md`). Candidate for a later v9 minor. It needs a check of what the harness already offers and a change to how the Doctor reconciles anchors.
- A bugfix lane with its own spec shape.
- Parallel task markers, a complexity tracking table, reviewer-owned checklists.
- Property-based tests derived from criteria.
- Converting the three existing archived specs to `ears-1`.
- Roadmap milestone M4 (scheduler, messaging). v9 is about the contract of the work, not about concurrency.

## Revision History

| Date | Change Summary |
|------|----------------|
| 2026-09-30 | Initial spec |
| 2026-09-30 | Re-QA of the phase 3 fix: freshness takes the later of the author and committer dates, since an amend or a cherry-pick keeps the old author date; a rebase after the verdict now stales it. |
| 2026-09-30 | QA of phase 3: freshness is measured against the branch's own code commits by author date, not only the pushed range, and reads the transcript's timestamp, not the ledger line (AC-14). Headers must be canonical, since the gate reads only that form. |
| 2026-09-30 | Operator decision: a Spec lives in `docs/specs/<yyyymmddHHMM>-<feature-name>/` from creation and never moves, so the converge scope, the receipt and the push gate share one key (AC-22). This spec moved there from `docs/specs-archive/`. |
| 2026-09-30 | QA of phase 2: no hook is added (hooks.json leaves the scope), ANATOMY joins the flow surfaces, analyze ids name their subject so they survive a re-run. |
| 2026-09-30 | QA of phase 1: AC-05 split, the 20 task cap moves to AC-21 (one behaviour per criterion). `sdd-archive` joins the affected skills, since it requires ticked criteria. |
| 2026-09-30 | AC-14 resolved: brain repository only (operator). Enforcement moved from the merge gate to the push gate, since the merge gate cannot see a diff. Receipt freshness added to AC-14. The existing QA receipt reflex is extended, no new hook. Task grammar accepts several paths. |
