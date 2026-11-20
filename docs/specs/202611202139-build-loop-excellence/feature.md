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
- **Run_Receipt**: a line of the Run_Section that is, to the character, `- RUN-## [AC-##, AC-##] <what was executed, in backticks>: <what was observed>`: a dash and one space at column 0, an id of two or more digits, one or more criteria joined by a comma and a space, one code span, a colon, a space and the observation. Neither part is a Placeholder.
- **Placeholder**: a value that, with the brackets, quotes, emphasis marks and punctuation around it stripped and case ignored, is empty, is a member of the linter's `PLACEHOLDERS` set (`todo`, `tbd`, `fixme`, `pending`, `placeholder`, `n/a`, `na`, `none`, `command`, `observation`, and the words of the two templates the Push_Gate and the Implement_Skill print, such as `what was executed`), is a run of two or more `x`, or is made only of angle-bracket groups. The comparison is with the whole value: a value that only starts with one of those words is real.
- **Run_Section**: the lines from the one heading that is exactly `## Run evidence` at column 0 to the next `#` or `##` heading at column 0. The heading is found the way the linter finds every section, so a heading quoted inside a closed fenced block is not one. The section is a strict machine grammar, not Markdown: only blank lines and Run_Receipts are allowed in it.
- **Run_Heading_Form**: any other line that reads as a run evidence heading: another level, another case, a tail, an indent, bold text, a setext title.
- **Hider**: markup a renderer hides or shows raw from its opener to its closer, whatever sits between, blank lines included: an HTML comment, a `script`, `style`, `pre` or `textarea` element, a CDATA section, a processing instruction. Any other HTML block ends at a blank line.
- **Plain_Fence**: a fenced block whose opener starts at column 0 with three or more of one fence character and no backtick after that run, and whose closer is a line at column 0 of the same character, at least as long, with nothing else on it.
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

The Implement_Skill records each real run as a Run_Receipt. The Push_Gate refuses a flip to `converged` on a spec with no Run_Receipt.

The Run_Section is read as a machine grammar, not as Markdown. Two converge passes found a new mismatch each time the reader tried to follow what a renderer shows (fences, comments, indents, code spans), so the reader no longer interprets: inside the section only blank lines and exact receipts are allowed, any other line is a finding that names it, and nothing in the section counts until the section is clean. Above the section the same idea applies to what could hide it from a reader: a fenced block must be a Plain_Fence, no Hider may be left open, and the line right above the heading is blank. Where the linter and a renderer could disagree, the answer is a finding, never a guess.

Every pattern the linter runs is linear in the length of the line. Three were not (the two loose header patterns and the clarification marker); they are rewritten so that each still reads everything it read before.


### FR-05: Wired

The Registry holds `FLOW.build-loop-excellence` with the linter as its mechanism and a fixture ladder as its proof.

## Acceptance Criteria

- [ ] AC-01: IF the Status of an ears-1 spec becomes converged in a push and its feature.md holds no Run_Receipt, THEN THE Push_Gate SHALL report a finding that names `## Run evidence`.
- [ ] AC-02: WHEN the Status of an ears-1 spec becomes converged in a push that carries a Run_Receipt and a fresh CONVERGED receipt, THE Push_Gate SHALL report no finding.
- [ ] AC-03: IF the Run_Section of a spec holds any line that is neither blank nor a Run_Receipt, THEN THE Push_Gate SHALL count no Run_Receipt of that spec, whatever the line is: a fence line, a line inside a fenced block, a comment, prose, an indented line, a nested bullet or a heading in another form.
- [ ] AC-04: WHEN a push changes a spec whose Status stays draft or approved, or a spec that was converged before the push, THE Push_Gate SHALL not require a Run_Receipt.
- [ ] AC-05: IF a line of the Run_Section starts with `- RUN-` and lacks the two-digit id, the criteria in brackets, the executed text in one code span or the observation after the colon and the space, THEN THE Spec_Linter SHALL report it as a receipt that does not follow the grammar.
- [ ] AC-06: IF a Run_Receipt repeats an id of the Run_Section or names a criterion the spec does not have, THEN THE Spec_Linter SHALL report it.
- [ ] AC-07: THE Converge_Skill SHALL require a real run for `met` on a behavioural criterion, define `unrun` as a gap, re-run every Run_Receipt, define the five excellence checks, and allow `CONVERGED` only with `EXCELLENT`.
- [ ] AC-08: THE Orchestrator_Skill SHALL apply the loop at every score, with the light loop for TRIVIAL and MEDIUM, and SHALL say that a build without a spec is not mechanically forced.
- [ ] AC-09: THE Constitution SHALL carry the anchor `Build loop until excellence` with the scope, the RUN step and the exit, and SHALL stay within the 12,000 ceiling of the `claude-md-budget` check.
- [ ] AC-10: THE Registry SHALL hold `FLOW.build-loop-excellence` with id, category, firing mode, canonical name, mechanism and proof, and a fixture ladder whose benign flip differs from a violating one by one line.
- [ ] AC-11: THE Implement_Skill SHALL instruct the builder to run the shipped artifact and record each run as a Run_Receipt.
- [ ] AC-12: THE Contract_Doc SHALL describe the run receipt check of the push gate and its residuals.
- [ ] AC-13: IF the executed text or the observation of a line in receipt shape is a Placeholder, THEN THE Spec_Linter SHALL report the line as an unfilled template, and WHEN the value only starts with or contains a placeholder word THE Spec_Linter SHALL accept it.
- [ ] AC-14: IF the only receipt-shaped line of a spec that becomes converged in a push holds a Placeholder, THEN THE Push_Gate SHALL report that the spec has no Run_Receipt.
- [ ] AC-15: IF a line of the Run_Section carries a `RUN-##` id in any other shape (no bullet, a numbered, starred or plus bullet, a checkbox, a quote mark, a table bar, an indent, a lower-case id, a tab or a no-break space for a space), THEN THE Spec_Linter SHALL report it and SHALL not skip it.
- [ ] AC-16: IF a spec holds a Run_Heading_Form, or more than one `## Run evidence` heading, THEN THE Spec_Linter SHALL report the heading by its line.
- [ ] AC-17: IF a line of the Run_Section is neither blank nor in receipt shape, THEN THE Spec_Linter SHALL report it by its line as not allowed under `## Run evidence`.
- [ ] AC-18: WHEN a spec holds a Plain_Fence or a closed Hider above the Run_Section, or any fenced block or comment below it, THE Spec_Linter SHALL report nothing for it and THE Push_Gate SHALL count the Run_Receipts of a clean section.
- [ ] AC-19: IF a fence line above the Run_Section is not part of a Plain_Fence, or a fenced block is still open where the section starts, THEN THE Spec_Linter SHALL report it and THE Push_Gate SHALL count no Run_Receipt.
- [ ] AC-20: IF the last Hider opener above the Run_Section has no closer of its kind after it and before the section, or the line right above the heading is not blank, or a Run_Receipt holds a comment opener, THEN THE Spec_Linter SHALL report it and THE Push_Gate SHALL count no Run_Receipt.
- [ ] AC-21: WHEN a line of 200,000 characters of any shape sits in a spec, THE Spec_Linter SHALL finish the lint of that spec in under one second.
- [ ] AC-22: THE Spec_Linter SHALL read as a header every line its earlier loose header patterns read, and SHALL find the same clarification markers at the same offsets as its earlier marker pattern.

## Run evidence

- RUN-01 [AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-10, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20] `python3 scripts/spec_lint.py --selftest registry/fixtures/FLOW.build-loop-excellence`: exit 0, `selftest PASS: 54 violation(s) block, 14 benign(s) allow`
- RUN-02 [AC-01, AC-03, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-22] `python3 -m unittest scripts.tests.test_spec_lint.RunEvidenceTest`: exit 0, 16 tests OK. Nine of them break one check each and assert the fixture ladder exits 1; one times 44 lints of a 200,000 character line, each under one second; one compares the three rewritten patterns with their old form on the repository's specs and fixtures plus seeded random text
- RUN-03 [AC-02, AC-04] `python3 scripts/spec_lint.py --selftest registry/fixtures/FLOW.done-is-a-verdict`: exit 0, `selftest PASS: 36 violation(s) block, 11 benign(s) allow`
- RUN-04 [AC-07, AC-08, AC-11] `python3 -m unittest scripts/tests/test_sdd_skill_contract.py`: exit 0, 5 tests OK
- RUN-05 [AC-05, AC-06, AC-18] `python3 scripts/spec_lint.py docs/specs/202611202139-build-loop-excellence`: exit 0, `ok docs/specs/202611202139-build-loop-excellence/feature.md`, so the linter accepts this section as a clean one
- RUN-06 [AC-09, AC-10] `python3 scripts/brain_doctor.py --fast`: exit 0, `claude-md-budget` passes at 12,000 of 12,000 and `registry-wiring` reports all 109 rules wired
- RUN-07 [AC-01, AC-02, AC-13, AC-14] `python3 -m unittest scripts.tests.test_spec_lint.RunEvidenceTest.test_the_cli_refuses_a_flip_until_a_receipt_is_committed`: exit 0. The test runs `spec_lint.py --push-range` as a subprocess against a repository it builds: exit 1 naming `## Run evidence` on a flip with no section, the same finding plus `RUN-01 is an unfilled template` once the template line is committed, neither once a filled receipt is committed, and neither for the command `todo add milk` with the observation `pending migrations 0, exit 0`
- RUN-08 [AC-12] `grep -c "FLOW.build-loop-excellence" docs/architecture/v9-done-is-a-verdict.md`: exit 0, prints `2`
- RUN-09 [AC-22] `python3 scripts/spec_lint.py --selftest registry/fixtures/FLOW.spec-contract`: exit 0, `selftest PASS: 25 violation(s) block, 10 benign(s) allow`, so the header and marker fixtures read the same with the rewritten patterns

## Residuals

- R-01: The gate fires only on a spec, at push. A TRIVIAL or MEDIUM build carries no spec, so its loop is covered by the Constitution anchor and the Orchestrator_Skill, not mechanically forced. Nothing detects a small build that skipped its run or its verdict.
- R-02: The Spec_Linter reads the shape of a Run_Receipt and refuses a Placeholder from a fixed list of whole values. It cannot tell whether the command was executed or whether the observation is true, and a made-up receipt that reads like a real one passes it. The Converge_Skill re-runs every receipt, and a receipt that does not reproduce is a gap, so a false receipt needs the verifier to miss it.
- R-03: The Push_Gate asks for at least one Run_Receipt, not one per behavioural criterion. Which criteria are behavioural is a judgment the linter cannot make; the Converge_Skill makes it, with the status `unrun`.
- R-04: The excellence pass is a judgment by the verifier. `CONVERGE-EXCELLENCE` is not parsed by the receipt hook: the hook keeps reading `CONVERGE-VERDICT`, and the skill ties `CONVERGED` to `EXCELLENT`. A verifier that prints `CONVERGED` after `NOT-YET` is recorded as converged.
- R-05: `BUILD-VERDICT` of the light loop is a convention of the Orchestrator_Skill. No hook records it.
- R-06: A spec that was converged before this check is not asked for a Run_Receipt, and neither is a flip that reaches a branch from the default branch by merge.
- R-07: The Constitution sits at its 12,000 ceiling, so the rule paid for its tokens: the 4D+S score table became one sentence and its signal list now lives only in the Orchestrator_Skill.
- R-08: Every residual of the push stanza stated in the Contract_Doc (skippable from a worktree, one machine's receipts, this repository only) applies to this check unchanged.
- R-09: The Run_Section holds nothing but receipts, so a note about the runs goes under another heading. A wrapped observation is refused too: a receipt is one line.
- R-10: The reader does not interpret Markdown, so two things stay outside it, stated. It is stricter than a renderer above the section: a fenced block inside a list item (indented), a line that starts with three backticks and holds a code span, and a Hider opener mentioned in a code span with no closer after it are findings although a renderer shows them harmlessly; move the section above them or reword. And it does not model what a host adds on top of Markdown: a `details` element closed above a blank line still folds what follows it on some hosts, and a stylesheet can hide anything. The pairing of fences below the section, and the hiding of a heading quoted in a fence, follow the linter's own section reader, which pairs fence lines one after the other.
- R-11: The two loose header patterns now read a few more lines as header-shaped than before (an underscore before a list marker, emphasis marks mixed with spaces around the colon). Each such line must then be canonical, so the change can add a finding and cannot remove one.
