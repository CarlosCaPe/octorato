# Feature: Build Loop Until Excellence

> **Status:** draft
> **Spec-Format:** ears-1
> **Date:** 2026-11-20
> **Classification:** LARGE (score 8: 10+ files, new feature, behavior change of a live gate)

Operator directive (2026-11-20): every request to build something another entity will use, human or not (a person, a client, another agent, an API consumer), goes through one loop: imagine, think, plan, execute, test, run it for real, and again, until it is excellent. Always, whatever the size of the task.

Three things stood in the way. The implement ⇄ converge loop applied only to LARGE tasks (score 6+). A criterion counted as `met` when the verifier "ran or read" something, so reading code was enough and no real run was required. And `CONVERGED` meant "every criterion met", which is a lower bar than "good enough to hand over".

## Summary

The loop becomes a rule of the constitution with its own registry entry. The orchestrator skill applies it at every score: TRIVIAL and MEDIUM run a light loop (test, run receipt, independent verdict) and LARGE keeps the full SDD flow. The converge skill requires a real run for `met` on a behavioural criterion, re-runs the builder's receipts and adds a five-check excellence pass, so `CONVERGED` now means excellent. The receipts live in `run-evidence.txt`, a plain-text file next to `feature.md`. The spec linter reads it, and the push gate refuses a `Status: converged` flip on a spec whose file is missing, holds no receipt or holds one finding.

## Glossary

- **Constitution**: `CLAUDE.md`.
- **Orchestrator_Skill**: `skills/4d-spec/SKILL.md`.
- **Converge_Skill**: `skills/sdd-converge/SKILL.md`.
- **Implement_Skill**: `skills/sdd-implement/SKILL.md` and the implement step of `skills/sdd-yolo/SKILL.md`.
- **Spec_Linter**: `scripts/spec_lint.py`, the plain lint of a spec directory.
- **Push_Gate**: `scripts/spec_lint.py --push-range`, run by `.githooks/pre-push` per pushed ref.
- **Evidence_File**: `run-evidence.txt` in the spec directory, next to `feature.md`. Plain text, read as bytes: UTF-8, a line ends at a line feed, and one carriage return right before that line feed is dropped. A line is blank (empty or spaces), a comment (`#` at column 0) or a Run_Receipt.
- **Run_Receipt**: a line of the Evidence_File that is, to the character, `RUN-## [AC-##, AC-##] <what was executed, in backticks>: <what was observed>`: `RUN-` and two or more ASCII digits at column 0, one space, one or more criteria (`AC-` and ASCII digits) in brackets joined by a comma and a space, one space, one code span, a colon, a space and the observation. Trailing spaces are ignored. Neither part is a Placeholder.
- **Placeholder**: a value that, with the brackets, quotes, emphasis marks and punctuation around it stripped and case ignored, is empty, is a member of the linter's `PLACEHOLDERS` set (`todo`, `tbd`, `fixme`, `pending`, `placeholder`, `n/a`, `na`, `none`, `command`, `observation`, and the words of the two templates the Push_Gate and the Implement_Skill print, such as `what was executed`), is a run of two or more `x`, or is made only of angle-bracket groups. The comparison is with the whole value: a value that only starts with one of those words is real.
- **Unsafe_Character**: a character that breaks a line for some reader, hides, or reorders text: U+0000 to U+001F (tab, form feed, vertical tab, the four information separators and a carriage return that is not right before the line feed among them), U+007F to U+009F (U+0085 among them), U+00AD, U+061C, U+180E, U+200B to U+200F, U+2028 to U+202E, U+2060 to U+206F, U+FEFF, U+FFF9 to U+FFFB, U+E0001 and U+E0020 to U+E007F.
- **Stale_Heading**: a line of `feature.md` that reads as a run evidence heading: `## Run evidence` at any level, in any case, with a tail or an indent, as bold text or as a setext title, outside a closed fenced block.
- **Registry**: `registry/rules.yaml` and `registry/fixtures/`.
- **Contract_Doc**: `docs/architecture/v9-done-is-a-verdict.md`.

## Functional Requirements

### FR-01: The rule

The Constitution states the loop, its scope (anything built for another entity), the RUN step (a receipt from executing the shipped artifact, never from reading its code) and the exit (an independent judgment-tier verifier's `EXCELLENT`). It extends "Done is a verdict" and does not repeat it.

### FR-02: Every score loops

The Orchestrator_Skill applies the loop at any score. TRIVIAL and MEDIUM run the light loop and end on `BUILD-VERDICT: EXCELLENT | ITERATE` from the verifier. LARGE runs it through SDD.

### FR-03: Met needs a run, converged means excellent

The Converge_Skill marks a behavioural criterion `met` only after running the shipped artifact, has a status `unrun` for code that reads right but was not seen working, re-runs every Run_Receipt, and makes an excellence pass over five checks: correctness, run evidence, edge cases, consumer experience (UX or DX) and no known defects. `CONVERGED` requires every criterion `met` and `EXCELLENT`. The two protocol lines the receipt hook reads do not change.

### FR-04: The receipts are in a text file

The Implement_Skill records each real run as a Run_Receipt in the Evidence_File. The Push_Gate refuses a flip to `converged` on a spec whose Evidence_File is missing, holds no Run_Receipt, or holds one finding.

Why a text file. The receipts first lived in a `## Run evidence` section of `feature.md`. Three converge passes each found Markdown that a renderer shows as code, or hides, while the linter counted it: an unclosed fence, a tilde line inside a backtick fence, a fence line inside an HTML block, an unclosed HTML declaration, a form feed that broke a line for the linter alone. The class of defect is "a renderer may show something different from what the linter reads", and it exists only because the receipts sat inside Markdown. A plain-text file has one reading, so the class is gone and not patched. The Markdown reader, its rules for what sits above the section and their fixtures are deleted, and a Stale_Heading is a finding that points to the file, so a spec written the old way fails loudly.

The one way text itself can still be read two ways is the line break and the invisible character, so the Evidence_File is read as bytes, split at line feeds only, and any Unsafe_Character is a finding.

Every pattern the linter runs is linear in the length of the line. Three were not (the two loose header patterns and the clarification marker); they are rewritten so that each still reads everything it read before.

### FR-05: Wired

The Registry holds `FLOW.build-loop-excellence` with the linter as its mechanism and a fixture ladder as its proof.

## Acceptance Criteria

- [ ] AC-01: IF the Status of an ears-1 spec becomes converged in a push and the spec has no Evidence_File, THEN THE Push_Gate SHALL report a finding that names `run-evidence.txt`.
- [ ] AC-02: WHEN the Status of an ears-1 spec becomes converged in a push that carries an Evidence_File with at least one Run_Receipt and no finding, and a fresh CONVERGED receipt, THE Push_Gate SHALL report no finding.
- [ ] AC-03: IF the Evidence_File of a spec that becomes converged in a push holds no Run_Receipt, or holds one finding of any kind, THEN THE Push_Gate SHALL report that no run receipt counts.
- [ ] AC-04: WHEN a push changes a spec whose Status stays draft or approved, or a spec that was converged before the push and has no Evidence_File before or after it, THE Push_Gate SHALL not require an Evidence_File.
- [ ] AC-05: IF a line of the Evidence_File carries a `RUN-` id and is not, to the character, a Run_Receipt (the id, the criteria in brackets, the executed text in one code span, the observation after the colon and the space), THEN THE Spec_Linter SHALL report it as a receipt that does not follow the grammar.
- [ ] AC-06: IF a Run_Receipt repeats an id of the Evidence_File or names a criterion the spec does not have, THEN THE Spec_Linter SHALL report it.
- [ ] AC-07: THE Converge_Skill SHALL require a real run for `met` on a behavioural criterion, define `unrun` as a gap, re-run every Run_Receipt, define the five excellence checks, and allow `CONVERGED` only with `EXCELLENT`.
- [ ] AC-08: THE Orchestrator_Skill SHALL apply the loop at every score, with the light loop for TRIVIAL and MEDIUM, and SHALL say that a build without a spec is not mechanically forced.
- [ ] AC-09: THE Constitution SHALL carry the anchor `Build loop until excellence` with the scope, the RUN step and the exit, and SHALL stay within the 12,000 ceiling of the `claude-md-budget` check.
- [ ] AC-10: THE Registry SHALL hold `FLOW.build-loop-excellence` with id, category, firing mode, canonical name, mechanism and proof, and a fixture ladder whose benign flip differs from a violating one by one line.
- [ ] AC-11: THE Implement_Skill SHALL instruct the builder to run the shipped artifact and record each run as a Run_Receipt in the Evidence_File.
- [ ] AC-12: THE Contract_Doc SHALL describe the run receipt check of the push gate and its residuals.
- [ ] AC-13: IF the executed text or the observation of a line in receipt shape is a Placeholder, THEN THE Spec_Linter SHALL report the line as an unfilled template, and WHEN the value only starts with or contains a placeholder word THE Spec_Linter SHALL accept it.
- [ ] AC-14: IF the only receipt-shaped line of the Evidence_File of a spec that becomes converged in a push holds a Placeholder, THEN THE Push_Gate SHALL report that no run receipt counts.
- [ ] AC-15: IF a line of the Evidence_File carries a `RUN-` id in any other shape (a Markdown bullet, a number, a checkbox, a quote mark, an indent, a lower-case id, a one-digit id, an id or a criterion in non-ASCII digits, criteria joined by a bare comma), THEN THE Spec_Linter SHALL report it and SHALL not skip it.
- [ ] AC-16: IF `feature.md` holds a Stale_Heading, THEN THE Spec_Linter SHALL report it by its line and point to the Evidence_File.
- [ ] AC-17: IF a line of the Evidence_File is neither blank, a comment nor in receipt shape, THEN THE Spec_Linter SHALL report it by its line.
- [ ] AC-18: WHEN a push changes only the Evidence_File of a spec, THE Push_Gate SHALL lint that spec with the file as it is at the pushed head, and WHEN the Evidence_File is clean THE Push_Gate SHALL report nothing for it.
- [ ] AC-19: IF the Evidence_File holds an Unsafe_Character anywhere, a comment line included, THEN THE Spec_Linter SHALL report the line and the code point, and THE Push_Gate SHALL count no Run_Receipt of that file.
- [ ] AC-20: IF the Evidence_File is not valid UTF-8, THEN THE Spec_Linter SHALL report it and THE Push_Gate SHALL count no Run_Receipt, and WHEN the file is valid THE Spec_Linter SHALL break its lines at line feeds only.
- [ ] AC-21: WHEN a line of 200,000 characters of any shape sits in `feature.md` or in the Evidence_File, THE Spec_Linter SHALL finish the lint of that spec in under one second.
- [ ] AC-22: THE Spec_Linter SHALL read as a header every line its earlier loose header patterns read, and SHALL find the same clarification markers at the same offsets as its earlier marker pattern.
- [ ] AC-23: IF a push removes the Evidence_File of a converged spec, or leaves it with no Run_Receipt that counts, THEN THE Push_Gate SHALL report it, flip or not.

## Residuals

- R-01: The gate fires only on a spec, at push. A TRIVIAL or MEDIUM build carries no spec, so its loop is covered by the Constitution anchor and the Orchestrator_Skill, not mechanically forced. Nothing detects a small build that skipped its run or its verdict.
- R-02: The Spec_Linter reads the shape of a Run_Receipt and refuses a Placeholder from a fixed list of whole values. It cannot tell whether the command was executed or whether the observation is true, and a made-up receipt that reads like a real one passes it. The Evidence_File is written by the builder, so it carries the trust of any text the builder writes; it is not a harness receipt. The Converge_Skill re-runs every receipt, and a receipt that does not reproduce is a gap, so a false receipt needs the verifier to miss it.
- R-03: The Push_Gate asks for at least one Run_Receipt, not one per behavioural criterion. Which criteria are behavioural is a judgment the linter cannot make; the Converge_Skill makes it, with the status `unrun`.
- R-04: The excellence pass is a judgment by the verifier. `CONVERGE-EXCELLENCE` is not parsed by the receipt hook: the hook keeps reading `CONVERGE-VERDICT`, and the skill ties `CONVERGED` to `EXCELLENT`. A verifier that prints `CONVERGED` after `NOT-YET` is recorded as converged.
- R-05: `BUILD-VERDICT` of the light loop is a convention of the Orchestrator_Skill. No hook records it.
- R-06: A spec that was converged before this check is not asked for an Evidence_File, and neither is a flip that reaches a branch from the default branch by merge.
- R-07: The Constitution sits at its 12,000 ceiling, so the rule paid for its tokens: the 4D+S score table became one sentence and its signal list now lives only in the Orchestrator_Skill.
- R-08: Every residual of the push stanza stated in the Contract_Doc (skippable from a worktree, one machine's receipts, this repository only) applies to this check unchanged.
- R-09: A receipt is one line. A command that holds a backtick cannot be written as one (write `$(...)` for a substitution), a tab inside a command is refused, and an observation does not wrap. Notes go in comment lines.
- R-10: The Evidence_File sits in the spec directory, which the freshness check of the converge receipt leaves out. A receipt edited after the verdict does not stale the verdict; the same is true of `feature.md` and `plan.md` today. The lint still runs on the edited file at every push that changes it.
- R-11: The two loose header patterns now read a few more lines as header-shaped than before (an underscore before a list marker, emphasis marks mixed with spaces around the colon). Each such line must then be canonical, so the change can add a finding and cannot remove one.

- R-12: Only the receipt reader is limited to ASCII digits. The patterns for criterion and task ids in `feature.md` and `plan.md` still take any Unicode digit, as they did; a criterion written in other digits cannot be named by a receipt, so it shows up as an unknown criterion and not as a silent match.
- R-13: A spec in flight that kept its receipts in a `## Run evidence` section now fails the lint on that heading. That is the intent: the section is no longer read, and a silent skip would let the spec converge with no receipt the gate can see.
- R-14: The Unsafe_Character list is a fixed set of code points, chosen so the answer does not move with the Unicode tables of the interpreter. A character added to Unicode later that hides or reorders text is not in it.
