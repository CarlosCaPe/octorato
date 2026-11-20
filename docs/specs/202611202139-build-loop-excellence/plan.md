# Plan: Build Loop Until Excellence

> **Status:** draft
> **Spec-Format:** ears-1
> **Feature:** feature.md

## Tasks

- [ ] T01 [AC-05, AC-06] scripts/spec_lint.py: `_run_section`, `run_receipts`, `_lint_run_evidence` for the shape, ids and criteria of every `RUN-##` bullet, called from `lint_feature`.
- [ ] T02 [AC-01, AC-02, AC-03, AC-04] scripts/spec_lint.py: in `push_findings`, a flip to converged with no run receipt is a finding, next to the converge receipt check.
- [ ] T03 [AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-10] registry/fixtures/FLOW.build-loop-excellence: push cases (flip without the section, section with no receipt, receipt in a fence, flip with a receipt, approved spec without one) and lint cases (well-formed, no observation, code read instead of run, unknown criterion, duplicate id).
- [ ] T04 [AC-02] registry/fixtures/FLOW.done-is-a-verdict: the five benign flips carry a run receipt.
- [ ] T05 [AC-10] registry/rules.yaml: entry `FLOW.build-loop-excellence`.
- [ ] T06 [AC-09] CLAUDE.md: the ULTRA RULE paragraph after "Done is a verdict", paid for by folding the 4D+S table into one sentence.
- [ ] T07 [AC-08] skills/4d-spec/SKILL.md: the build loop section, the light loop in TRIVIAL and MEDIUM, the run step in LARGE.
- [ ] T08 [AC-07] skills/sdd-converge/SKILL.md: `met` needs a run, `unrun`, receipts re-run, the excellence pass, `CONVERGE-EXCELLENCE`.
- [ ] T09 [AC-11] skills/sdd-implement/SKILL.md, skills/sdd-yolo/SKILL.md: run it for real and record the receipts.
- [ ] T10 [AC-07, AC-08, AC-11] scripts/tests/test_sdd_skill_contract.py: pin the new sentences.
- [ ] T11 [AC-01, AC-03, AC-05] scripts/tests/test_spec_lint.py: the ladder passes, goes red when the check is disabled, and receipts are not read in a fence.
- [ ] T12 [AC-12] docs/architecture/v9-done-is-a-verdict.md, docs/wiki/The-4D-Paradigm.md, connectome/lineage.yaml, docs/CAPABILITIES.md: the run receipt check, the build loop row, the lineage concept and the regenerated manifest.
- [ ] T17 [AC-13, AC-14] scripts/spec_lint.py: `_is_placeholder` and `_receipt`; an unfilled template is a lint finding and is not counted by `run_receipts`.
- [ ] T18 [AC-03, AC-15, AC-16, AC-17, AC-18] scripts/spec_lint.py: `_run_lines`, the reader of run evidence: fences and HTML comments hide to their close or to the end, inline code spans keep a comment opener literal, every Run_Heading is read and a non-canonical one is a finding, and `_RUN_START` catches a `RUN-##` id behind any markup.

## Convergence 1

- [ ] T13 [AC-03] scripts/spec_lint.py: a receipt after an opening fence that never closes under `## Run evidence` is counted (`run_receipts` returns `['RUN-01']` and the lint prints `ok`), although an unclosed fence is a fenced block to the end of the file; a receipt inside an HTML comment is counted too, a case the spec does not name, so `/sdd-refine` adds the criterion or the residual.
- [ ] T14 [AC-05] scripts/spec_lint.py: the unfilled template ``- RUN-01 [AC-01] `<what was executed>`: <what was observed>`` passes the lint and satisfies the push gate, so the text the gate's own finding and `sdd-implement` print is accepted as a run; the spec names no criterion for a placeholder, so `/sdd-refine` adds one.
- [ ] T15 [AC-05] scripts/spec_lint.py: under `## Run evidence` a `RUN-01 [AC-01] ...` line with no bullet or a numbered one is skipped with `ok`, and a second section whose heading differs only in case (`## RUN EVIDENCE`) is never read, so its malformed receipt (`- RUN-01 [AC-77] bad`) is not reported; the spec does not name either case.
- [ ] T16 [AC-03, AC-05] registry/fixtures/FLOW.build-loop-excellence, scripts/tests/test_spec_lint.py: no case pins the unclosed fence, the HTML comment, the placeholder receipt, the bullet-less line or the second miscased section, and no push fixture pins a receipt under another heading (only the `run_receipts` unit test does).
