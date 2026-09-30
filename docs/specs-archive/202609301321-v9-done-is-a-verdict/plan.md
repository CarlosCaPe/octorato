# Implementation Plan: v9, Done Is a Verdict

> **Spec:** `feature.md` in this directory (`Spec-Format: ears-1`, status approved)
> **Date:** 2026-09-30

## Overview

Four phases, one pull request each, every one from its own worktree. The order follows the dependency: a spec a script can read comes first, the verdict skills that use it second, the receipt and the push gate third, the release last. Phase 1 is useful alone, so a stop after any phase leaves master coherent.

## Architecture Decisions

- **The linter is one CLI, `scripts/spec_lint.py`.** Standard library only. It owns the EARS grammar, the task grammar, coverage, the marker cap and the push-range check. One script means one fixture set and one place where the grammar lives.
- **The converge check sits in the push gate.** `qa-merge-gate.py` runs under a 5 second hook timeout, makes no network call and knows only the pull request number (`scripts/qa-merge-gate.py:491-530`, `hooks.json:154-157`). It cannot see which files a pull request changes. `.githooks/pre-push` sees the exact commits and is local to this repository.
- **No new hook.** The existing SubagentStop reflex `r__subagent-stop__qa-receipt.py` already parses a verdict protocol and writes to the global ledger. It gains a second protocol, `CONVERGE-VERDICT` and `CONVERGE-SCOPE`. The lookup `converge_pass_for()` copies `qa_pass_for()` (`scripts/receipt_ledger.py:583-601`): verifier persona, harness-shaped transcript, last assistant text re-parsed.
- **Freshness is computed from git.** A receipt counts only if its `ts` is later than the newest commit in the pushed range that touches a path outside the spec directory. The status flip is then a commit of its own that touches only the spec.
- **Registry rows follow `META.skill-manifest-coverage`** (`registry/rules.yaml:1990-2020`): mechanism at `PrePush`, an `EXIT_CODE` selftest proof, a grep proof that the stanza is in `.githooks/pre-push`, and `ANCHOR_PRESENT`.
- **Old specs are untouched.** The linter skips any `feature.md` without `Spec-Format: ears-1`.
- **Two skills are added and two verifiers are removed.** `sdd-converge` takes over what `sdd-implement` step 5 and `sdd-review` Dimension 1 do today, so the number of places that decide "done" goes from two to one.

## Implementation Steps

### Phase 1: a spec a script can read

- [x] T01 [AC-02, AC-03, AC-06, AC-16] scripts/spec_lint.py: write the CLI. It checks EARS shape, unique criterion ids, glossary subjects, the 3 marker cap, the task grammar, the 20 task cap and coverage in both directions. It skips files without `Spec-Format: ears-1`. Flags: `--ready` fails while any marker remains, `--selftest <dir>` runs the fixtures.
- [x] T02 [AC-02, AC-03, AC-06, AC-16, AC-17] registry/fixtures/FLOW.spec-contract/, scripts/tests/test_spec_lint.py: add fixture spec directories. Each benign fixture is its violation with one edit removed. Cover a non-EARS criterion, 4 markers, an uncovered criterion, an unknown criterion id, 21 tasks and a legacy spec that must be skipped.
- [x] T03 [AC-01] skills/sdd-feature/SKILL.md: require the `Spec-Format` header, a Glossary, EARS criteria and inline markers. Remove the "Open Questions" section and the step that asks up to 5 questions at once. End by running the linter.
- [x] T04 [AC-04, AC-05, AC-21] skills/sdd-plan/SKILL.md: run `spec_lint.py --ready` first and stop on failure. Replace the per-layer checkbox steps with the task grammar. Drop the Acceptance Criteria Mapping table, which the grammar now carries.
- [x] T05 [AC-19] skills/sdd-refine/SKILL.md: one question at a time with a recommended answer, applied before the next question. Keep Revision History as the only log.
- [x] T06 [AC-20] docs/specs-archive/202609301321-v9-done-is-a-verdict/feature.md, docs/specs-archive/202609301321-v9-done-is-a-verdict/plan.md: run the linter on this spec and this plan and fix whatever it reports.

### Phase 2: the verdict skills and the flow

- [x] T07 [AC-07] skills/sdd-analyze/SKILL.md, skills/sdd-analyze/skill.json: read-only pass over spec, plan and rules file. Findings carry stable ids, a severity and a cap of 50. It runs as a verifier persona on the judgment tier.
- [x] T08 [AC-10, AC-11, AC-12] skills/sdd-converge/SKILL.md, skills/sdd-converge/skill.json: judge each criterion from code and tests. Append a `## Convergence <n>` task section on gaps, leave the plan untouched when converged, and end with the two protocol lines.
- [x] T09 [AC-08] skills/sdd-implement/SKILL.md: remove step 5. `impl-summary.md` lists files and deviations only.
- [x] T10 [AC-09] skills/sdd-review/SKILL.md, skills/sdd-archive/SKILL.md: remove Dimension 1 and the instruction to tick criteria. The review keeps its 7 quality dimensions and reads the converge verdict. Archive stops requiring ticked criteria and requires a `CONVERGED` verdict, and stops scanning the removed Open Questions section.
- [x] T11 [AC-18] skills/4d-spec/SKILL.md, skills/sdd-yolo/SKILL.md: describe the LARGE flow with analyze before implement and the implement and converge loop. TRIVIAL and MEDIUM stay as they are.
- [x] T12 [AC-18] CLAUDE.md, docs/wiki/Skills.md, docs/wiki/The-4D-Paradigm.md, docs/wiki/Glossary.md, docs/CAPABILITIES.md, connectome/lineage.yaml: update the 4D+S section and the wiki to the new flow, regenerate the capability manifest, add the `sdd` edge to the lineage graph.

### Phase 3: the receipt, the push gate and the wiring

- [ ] T13 [AC-13] scripts/receipt_ledger.py, scripts/r__subagent-stop__qa-receipt.py, scripts/tests/test_receipt_ledger.py: add `parse_converge()` and `converge_pass_for(spec_dir)`. The reflex records `kind: converge`. Tests cover a forged line, a non-verifier persona and a verdict quoted earlier in the message.
- [ ] T14 [AC-14] scripts/spec_lint.py: add `--push-range <base> <head>`. For each spec whose status became `converged` in the range, require a fresh receipt as defined in the architecture decisions.
- [ ] T15 [AC-14, AC-15] .githooks/pre-push: add one stanza that lints every `ears-1` spec and runs the push-range check for each ref. A missing linter blocks the push, as the other stanzas do.
- [ ] T16 [AC-17] registry/rules.yaml, registry/fixtures/FLOW.done-is-a-verdict/: register `FLOW.spec-contract` and `FLOW.done-is-a-verdict` with their proofs. Fixtures hold a status flip with no receipt (blocks), with a stale receipt (blocks) and with a fresh one (allows).
- [ ] T17 [AC-17] scripts/brain_doctor.py: add two `CHECKS` rows that run the two selftests and confirm the pre-push stanza is present.
- [ ] T18 [AC-17] CLAUDE.md, docs/architecture/v9-done-is-a-verdict.md: add the "Done is a verdict" anchor and the contract document. The document states the measured residuals: whether `git push --no-verify` from a worktree is denied, receipts local to one machine, a transcript that can be forged under `$HOME`.

### Phase 4: release

- [ ] T19 [AC-12, AC-20] docs/specs-archive/202609301321-v9-done-is-a-verdict/feature.md: run the converge pass on this spec with a verifier persona. On `CONVERGED`, commit the status change alone and push it through the new gate.
- [ ] T20 [AC-18] ROADMAP.md, CHANGELOG.md: describe v9 next to v8. The operator cuts v9.0.0 with the `Octorato-Major:` trailer.

## Verification per Phase

Every pull request passes these before merge:

- `python3 scripts/brain_doctor.py` with 0 FAIL.
- `python3 -m unittest discover scripts/tests -p 'test_*.py'`.
- `python3 scripts/octo_pkg.py manifests` still at n/n, and `python3 scripts/capability_manifest.py --check`.
- A QA receipt from a verifier persona on the judgment tier, then the operator's `OCTO_MERGE_APPROVE`.

Phase 2 adds a rehearsal in a scratch directory. A toy feature is implemented with one criterion left broken. The converge pass must append a Convergence section and end with `GAPS`. After the fix, the sha256 of `plan.md` must be equal before and after the pass, and the verdict must be `CONVERGED`.

Phase 3 adds a live test of the gate: a push that flips the status with no receipt must be blocked.

## Risks and Mitigations

- The EARS regex rejects a valid sentence. Mitigation: the fixtures hold one benign case per pattern, and the 20 criteria of this spec serve as a second corpus.
- A spec with many criteria turns the converge pass expensive. Mitigation: it runs for LARGE tasks only, and the rehearsal measures its token cost before Phase 3 depends on it.
- The push gate blocks a second machine that pulled a converged spec. Mitigation: the check reads only status changes inside the pushed range, never the whole tree.
- Phase 3 edits gate surfaces. Mitigation: all edits happen in a worktree, and the doctor records a new gate receipt on the clean tree after merge.

## Estimated Complexity

High. About 30 files over four pull requests, with two gate surfaces and one new CLI.
