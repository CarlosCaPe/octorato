# Feature: Build Loop Until Excellence

> **Status:** draft
> **Spec-Format:** ears-1
> **Date:** 2026-11-20
> **Classification:** LARGE (score 8: 10+ files, new feature, behavior change of a live gate)

Operator directive (2026-11-20): every request to build something another entity will use, human or not (a person, a client, another agent, an API consumer), goes through one loop: imagine, think, plan, execute, test, run it for real, and again, until it is excellent. Always, whatever the size of the task.

Three things stood in the way. The implement ⇄ converge loop applied only to LARGE tasks (score 6+). A criterion counted as `met` when the verifier "ran or read" something, so reading code was enough and no real run was required. And `CONVERGED` meant "every criterion met", which is a lower bar than "good enough to hand over".

## Summary

The loop becomes a rule of the constitution with its own registry entry. The orchestrator skill applies it at every score: TRIVIAL and MEDIUM run a light loop (test, run receipt, independent verdict) and LARGE keeps the full SDD flow. The converge skill requires a real run for `met` on a behavioural criterion, re-runs the builder's receipts and adds a five-check excellence pass, so `CONVERGED` now means excellent. The spec linter reads run receipts under `## Run evidence` and the push gate refuses a `Status: converged` flip on a spec that carries none.

## Glossary

- **Constitution**: `CLAUDE.md`.
- **Orchestrator_Skill**: `skills/4d-spec/SKILL.md`.
- **Converge_Skill**: `skills/sdd-converge/SKILL.md`.
- **Implement_Skill**: `skills/sdd-implement/SKILL.md` and the implement step of `skills/sdd-yolo/SKILL.md`.
- **Spec_Linter**: `scripts/spec_lint.py`, the plain lint of a spec directory.
- **Push_Gate**: `scripts/spec_lint.py --push-range`, run by `.githooks/pre-push` per pushed ref.
- **Run_Receipt**: a line `- RUN-## [AC-##, AC-##] <what was executed, in backticks>: <what was observed>` under the `## Run evidence` heading of `feature.md`, outside any fenced block.
- **Registry**: `registry/rules.yaml` and `registry/fixtures/`.
- **Contract_Doc**: `docs/architecture/v9-done-is-a-verdict.md`.

## Functional Requirements

### FR-01: The rule

The Constitution states the loop, its scope (anything built for another entity), the RUN step (a receipt from executing the shipped artifact, never from reading its code) and the exit (an independent judgment-tier verifier's `EXCELLENT`). It extends "Done is a verdict" and does not repeat it.

### FR-02: Every score loops

The Orchestrator_Skill applies the loop at any score. TRIVIAL and MEDIUM run the light loop and end on `BUILD-VERDICT: EXCELLENT | ITERATE` from the verifier. LARGE runs it through SDD.

### FR-03: Met needs a run, converged means excellent

The Converge_Skill marks a behavioural criterion `met` only after running the shipped artifact, has a status `unrun` for code that reads right but was not seen working, re-runs every Run_Receipt, and makes an excellence pass over five checks: correctness, run evidence, edge cases, consumer experience (UX or DX) and no known defects. `CONVERGED` requires every criterion `met` and `EXCELLENT`. The two protocol lines the receipt hook reads do not change.

### FR-04: The receipt is in the spec

The Implement_Skill records each real run as a Run_Receipt. The Spec_Linter checks the shape of every `RUN-##` bullet. The Push_Gate refuses a flip to `converged` on a spec with no Run_Receipt.

### FR-05: Wired

The Registry holds `FLOW.build-loop-excellence` with the linter as its mechanism and a fixture ladder as its proof.

## Acceptance Criteria

- [ ] AC-01: IF the Status of an ears-1 spec becomes converged in a push and its feature.md holds no Run_Receipt, THEN THE Push_Gate SHALL report a finding that names `## Run evidence`.
- [ ] AC-02: WHEN the Status of an ears-1 spec becomes converged in a push that carries a Run_Receipt and a fresh CONVERGED receipt, THE Push_Gate SHALL report no finding.
- [ ] AC-03: IF the only receipt-shaped line of a spec sits inside a fenced code block or under another heading, THEN THE Push_Gate SHALL not count it as a Run_Receipt.
- [ ] AC-04: WHEN a push changes a spec whose Status stays draft or approved, or a spec that was converged before the push, THE Push_Gate SHALL not require a Run_Receipt.
- [ ] AC-05: IF a `RUN-##` bullet under `## Run evidence` lacks the executed text in backticks or the observation after the colon, THEN THE Spec_Linter SHALL report it.
- [ ] AC-06: IF a `RUN-##` bullet repeats an id or names a criterion the spec does not have, THEN THE Spec_Linter SHALL report it.
- [ ] AC-07: THE Converge_Skill SHALL require a real run for `met` on a behavioural criterion, define `unrun` as a gap, re-run every Run_Receipt, define the five excellence checks, and allow `CONVERGED` only with `EXCELLENT`.
- [ ] AC-08: THE Orchestrator_Skill SHALL apply the loop at every score, with the light loop for TRIVIAL and MEDIUM, and SHALL say that a build without a spec is not mechanically forced.
- [ ] AC-09: THE Constitution SHALL carry the anchor `Build loop until excellence` with the scope, the RUN step and the exit, and SHALL stay within the 12,000 ceiling of the `claude-md-budget` check.
- [ ] AC-10: THE Registry SHALL hold `FLOW.build-loop-excellence` with id, category, firing mode, canonical name, mechanism and proof, and a fixture ladder whose benign flip differs from a violating one by one line.
- [ ] AC-11: THE Implement_Skill SHALL instruct the builder to run the shipped artifact and record each run as a Run_Receipt.
- [ ] AC-12: THE Contract_Doc SHALL describe the run receipt check of the push gate and its residuals.

## Run evidence

- RUN-01 [AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-10] `python3 scripts/spec_lint.py --selftest registry/fixtures/FLOW.build-loop-excellence`: exit 0, `selftest PASS: 7 violation(s) block, 3 benign(s) allow`
- RUN-02 [AC-01] `python3 <copy of spec_lint.py with the run check replaced by "if False:"> --selftest registry/fixtures/FLOW.build-loop-excellence`: exit 1, the three `violation_flip_*` cases print `expected findings, got none`, so the fixtures guard the check
- RUN-03 [AC-02, AC-04] `python3 scripts/spec_lint.py --selftest registry/fixtures/FLOW.done-is-a-verdict`: exit 0, `selftest PASS: 36 violation(s) block, 11 benign(s) allow`
- RUN-04 [AC-07, AC-08, AC-11] `python3 -m unittest scripts/tests/test_sdd_skill_contract.py scripts/tests/test_spec_lint.py`: exit 0, every test OK
- RUN-05 [AC-05, AC-06] `python3 scripts/spec_lint.py docs/specs/202611202139-build-loop-excellence`: exit 0, `ok docs/specs/202611202139-build-loop-excellence/feature.md`, so the linter reads this section's own receipts
- RUN-06 [AC-09, AC-10] `python3 scripts/brain_doctor.py --fast`: exit 0, `claude-md-budget` passes at 12,000 of 12,000 and RULE #1 reports every rule wired
- RUN-07 [AC-01, AC-02] `python3 scripts/spec_lint.py --repo <throwaway repo> --push-range <base> HEAD`: exit 1 with `has no run receipt under ## Run evidence` on a flip without the section, and after one `RUN-01` line is committed the same command no longer prints that finding (only the missing converge receipt remains)

## Residuals

- R-01: The gate fires only on a spec, at push. A TRIVIAL or MEDIUM build carries no spec, so its loop is covered by the Constitution anchor and the Orchestrator_Skill, not mechanically forced. Nothing detects a small build that skipped its run or its verdict.
- R-02: The Spec_Linter reads the shape of a Run_Receipt. It cannot tell whether the command was executed or whether the observation is true. The Converge_Skill re-runs every receipt, and a receipt that does not reproduce is a gap, so a false receipt needs the verifier to miss it.
- R-03: The Push_Gate asks for at least one Run_Receipt, not one per behavioural criterion. Which criteria are behavioural is a judgment the linter cannot make; the Converge_Skill makes it, with the status `unrun`.
- R-04: The excellence pass is a judgment by the verifier. `CONVERGE-EXCELLENCE` is not parsed by the receipt hook: the hook keeps reading `CONVERGE-VERDICT`, and the skill ties `CONVERGED` to `EXCELLENT`. A verifier that prints `CONVERGED` after `NOT-YET` is recorded as converged.
- R-05: `BUILD-VERDICT` of the light loop is a convention of the Orchestrator_Skill. No hook records it.
- R-06: A spec that was converged before this check is not asked for a Run_Receipt, and neither is a flip that reaches a branch from the default branch by merge.
- R-07: The Constitution sits at its 12,000 ceiling, so the rule paid for its tokens: the 4D+S score table became one sentence and its signal list now lives only in the Orchestrator_Skill.
- R-08: Every residual of the push stanza stated in the Contract_Doc (skippable from a worktree, one machine's receipts, this repository only) applies to this check unchanged.
