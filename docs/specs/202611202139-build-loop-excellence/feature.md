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
- **Run_Receipt**: a line `- RUN-## [AC-##, AC-##] <what was executed, in backticks>: <what was observed>` under a run evidence heading of `feature.md`, with both parts filled in, outside any fenced block and any HTML comment.
- **Placeholder**: text that stands where a command or an observation should be: text made only of angle-bracket groups (the template the gate and the skills print), the template's own words without the brackets, or `TODO`, `TBD`, `FIXME`, `pending`, `placeholder`, `n/a`, `none`, an ellipsis, or a run of `x`, `-` or `?`. A command that only contains an angle-bracket argument is not a Placeholder.
- **Run_Heading**: a heading of any level, in any case and with any trailing text, whose text starts with `run evidence`. The canonical form is exactly `## Run evidence`.
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

The Implement_Skill records each real run as a Run_Receipt. The Spec_Linter checks every line that starts with a `RUN-##` id, whatever markup precedes it, and refuses a Placeholder and a Run_Heading that is not canonical. The Push_Gate refuses a flip to `converged` on a spec with no Run_Receipt.

What counts follows what a reader of the rendered spec sees. A fenced block and an HTML comment hide their content, and for receipts one that never closes hides everything after it. That is the opposite of how the linter reads headers, where an unclosed fence hides nothing so a spec cannot skip the lint; the two readers answer different questions and each fails closed.

### FR-05: Wired

The Registry holds `FLOW.build-loop-excellence` with the linter as its mechanism and a fixture ladder as its proof.

## Acceptance Criteria

- [ ] AC-01: IF the Status of an ears-1 spec becomes converged in a push and its feature.md holds no Run_Receipt, THEN THE Push_Gate SHALL report a finding that names `## Run evidence`.
- [ ] AC-02: WHEN the Status of an ears-1 spec becomes converged in a push that carries a Run_Receipt and a fresh CONVERGED receipt, THE Push_Gate SHALL report no finding.
- [ ] AC-03: IF the only receipt-shaped line of a spec sits inside a fenced code block (closed only by a line of the same fence character, at least as long), after an opening fence that never closes, inside an HTML comment, after a comment opener that never closes, or under a heading that is not a Run_Heading, THEN THE Push_Gate SHALL not count it as a Run_Receipt.
- [ ] AC-04: WHEN a push changes a spec whose Status stays draft or approved, or a spec that was converged before the push, THE Push_Gate SHALL not require a Run_Receipt.
- [ ] AC-05: IF a line under a Run_Heading starts with a `RUN-##` id behind a `- ` bullet and lacks the executed text in backticks or the observation after the colon, THEN THE Spec_Linter SHALL report it.
- [ ] AC-06: IF a Run_Receipt repeats an id used anywhere in the run evidence of the spec, or names a criterion the spec does not have, THEN THE Spec_Linter SHALL report it.
- [ ] AC-07: THE Converge_Skill SHALL require a real run for `met` on a behavioural criterion, define `unrun` as a gap, re-run every Run_Receipt, define the five excellence checks, and allow `CONVERGED` only with `EXCELLENT`.
- [ ] AC-08: THE Orchestrator_Skill SHALL apply the loop at every score, with the light loop for TRIVIAL and MEDIUM, and SHALL say that a build without a spec is not mechanically forced.
- [ ] AC-09: THE Constitution SHALL carry the anchor `Build loop until excellence` with the scope, the RUN step and the exit, and SHALL stay within the 12,000 ceiling of the `claude-md-budget` check.
- [ ] AC-10: THE Registry SHALL hold `FLOW.build-loop-excellence` with id, category, firing mode, canonical name, mechanism and proof, and a fixture ladder whose benign flip differs from a violating one by one line.
- [ ] AC-11: THE Implement_Skill SHALL instruct the builder to run the shipped artifact and record each run as a Run_Receipt.
- [ ] AC-12: THE Contract_Doc SHALL describe the run receipt check of the push gate and its residuals.
- [ ] AC-13: IF the executed text or the observation of a receipt-shaped line is a Placeholder, THEN THE Spec_Linter SHALL report the line as an unfilled template.
- [ ] AC-14: IF the only receipt-shaped line of a spec that becomes converged in a push holds a Placeholder, THEN THE Push_Gate SHALL report that the spec has no Run_Receipt.
- [ ] AC-15: IF a line under a Run_Heading starts with a `RUN-##` id with no bullet, behind a numbered or starred bullet, a checkbox, a quote mark or a table bar, or with the id in lower case, THEN THE Spec_Linter SHALL report it and SHALL not skip it.
- [ ] AC-16: IF a Run_Heading is not exactly `## Run evidence`, THEN THE Spec_Linter SHALL report the heading by its line and SHALL still read the lines under it.
- [ ] AC-17: WHEN a spec holds more than one Run_Heading, THE Spec_Linter SHALL read the lines under every one of them.
- [ ] AC-18: WHEN a spec mentions a comment opener inside an inline code span, or quotes the receipt template inside a closed fenced block next to a Run_Receipt, THE Spec_Linter SHALL report nothing for it.

## Run evidence

- RUN-01 [AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-10, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18] `python3 scripts/spec_lint.py --selftest registry/fixtures/FLOW.build-loop-excellence`: exit 0, `selftest PASS: 26 violation(s) block, 9 benign(s) allow`
- RUN-02 [AC-01, AC-03, AC-13, AC-14, AC-15, AC-16, AC-17] `python3 -m unittest -v scripts.tests.test_spec_lint.RunEvidenceTest`: exit 0, 11 tests OK. Seven of them disable one check each (any spec counts as run, the shape is not read, a placeholder counts, the first-pass reader, comments read as text, dash bullets only, any heading form) and assert the fixture ladder exits 1
- RUN-03 [AC-02, AC-04] `python3 scripts/spec_lint.py --selftest registry/fixtures/FLOW.done-is-a-verdict`: exit 0, `selftest PASS: 36 violation(s) block, 11 benign(s) allow`
- RUN-04 [AC-07, AC-08, AC-11] `python3 -m unittest scripts/tests/test_sdd_skill_contract.py`: exit 0, 5 tests OK
- RUN-05 [AC-05, AC-06, AC-18] `python3 scripts/spec_lint.py docs/specs/202611202139-build-loop-excellence`: exit 0, `ok docs/specs/202611202139-build-loop-excellence/feature.md`, so the linter reads this section's own receipts and the template quoted in the Glossary
- RUN-06 [AC-09, AC-10] `python3 scripts/brain_doctor.py --fast`: exit 0, `claude-md-budget` passes at 12,000 of 12,000 and `registry-wiring` reports all 109 rules wired
- RUN-07 [AC-01, AC-02, AC-13, AC-14] `python3 -m unittest -v scripts.tests.test_spec_lint.RunEvidenceTest.test_the_cli_refuses_a_flip_until_a_receipt_is_committed`: exit 0. The test runs `spec_lint.py --repo <dir> --push-range <base> HEAD` as a subprocess against a repository it builds: exit 1 naming `## Run evidence` on a flip with no section, the same finding plus `RUN-01 is an unfilled template` once the template line is committed, and neither once a filled receipt is committed (only the missing converge receipt is left)
- RUN-08 [AC-12] `grep -c "FLOW.build-loop-excellence" docs/architecture/v9-done-is-a-verdict.md`: exit 0, prints `2`

## Residuals

- R-01: The gate fires only on a spec, at push. A TRIVIAL or MEDIUM build carries no spec, so its loop is covered by the Constitution anchor and the Orchestrator_Skill, not mechanically forced. Nothing detects a small build that skipped its run or its verdict.
- R-02: The Spec_Linter reads the shape of a Run_Receipt and refuses a Placeholder from a fixed list. It cannot tell whether the command was executed or whether the observation is true, and a made-up receipt that reads like a real one passes it. The Converge_Skill re-runs every receipt, and a receipt that does not reproduce is a gap, so a false receipt needs the verifier to miss it.
- R-03: The Push_Gate asks for at least one Run_Receipt, not one per behavioural criterion. Which criteria are behavioural is a judgment the linter cannot make; the Converge_Skill makes it, with the status `unrun`.
- R-04: The excellence pass is a judgment by the verifier. `CONVERGE-EXCELLENCE` is not parsed by the receipt hook: the hook keeps reading `CONVERGE-VERDICT`, and the skill ties `CONVERGED` to `EXCELLENT`. A verifier that prints `CONVERGED` after `NOT-YET` is recorded as converged.
- R-05: `BUILD-VERDICT` of the light loop is a convention of the Orchestrator_Skill. No hook records it.
- R-06: A spec that was converged before this check is not asked for a Run_Receipt, and neither is a flip that reaches a branch from the default branch by merge.
- R-07: The Constitution sits at its 12,000 ceiling, so the rule paid for its tokens: the 4D+S score table became one sentence and its signal list now lives only in the Orchestrator_Skill.
- R-08: Every residual of the push stanza stated in the Contract_Doc (skippable from a worktree, one machine's receipts, this repository only) applies to this check unchanged.
- R-09: A prose line under a Run_Heading that happens to start with a `RUN-##` id is reported as a malformed receipt. It blocks in the safe direction; reword the sentence.
- R-10: Other markup a renderer hides or shows as code (a `<details>` block, a link reference definition, a four-space indented block, a setext heading) is not modelled. An indented `RUN-##` line is reported as malformed, and run evidence under a setext heading is not read, so both block. The fenced block and the HTML comment are the two cases read.
