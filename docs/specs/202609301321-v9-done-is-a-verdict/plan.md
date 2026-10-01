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
- [x] T03 [AC-01, AC-22] skills/sdd-feature/SKILL.md: require the `Spec-Format` header, a Glossary, EARS criteria and inline markers. Remove the "Open Questions" section and the step that asks up to 5 questions at once. End by running the linter.
- [x] T04 [AC-04, AC-05, AC-21] skills/sdd-plan/SKILL.md: run `spec_lint.py --ready` first and stop on failure. Replace the per-layer checkbox steps with the task grammar. Drop the Acceptance Criteria Mapping table, which the grammar now carries.
- [x] T05 [AC-19] skills/sdd-refine/SKILL.md: one question at a time with a recommended answer, applied before the next question. Keep Revision History as the only log.
- [x] T06 [AC-20] docs/specs/202609301321-v9-done-is-a-verdict/feature.md, docs/specs/202609301321-v9-done-is-a-verdict/plan.md: run the linter on this spec and this plan and fix whatever it reports.

### Phase 2: the verdict skills and the flow

- [x] T07 [AC-07] skills/sdd-analyze/SKILL.md, skills/sdd-analyze/skill.json: read-only pass over spec, plan and rules file. Findings carry stable ids, a severity and a cap of 50. It runs as a verifier persona on the judgment tier.
- [x] T08 [AC-10, AC-11, AC-12] skills/sdd-converge/SKILL.md, skills/sdd-converge/skill.json: judge each criterion from code and tests. Append a `## Convergence <n>` task section on gaps, leave the plan untouched when converged, and end with the two protocol lines.
- [x] T09 [AC-08] skills/sdd-implement/SKILL.md: remove step 5. `impl-summary.md` lists files and deviations only.
- [x] T10 [AC-09, AC-22] skills/sdd-review/SKILL.md, skills/sdd-archive/SKILL.md: remove Dimension 1 and the instruction to tick criteria. The review keeps its 7 quality dimensions and reads the converge verdict. Archive stops requiring ticked criteria and requires a `CONVERGED` verdict, and stops scanning the removed Open Questions section.
- [x] T11 [AC-18] skills/4d-spec/SKILL.md, skills/sdd-yolo/SKILL.md: describe the LARGE flow with analyze before implement and the implement and converge loop. TRIVIAL and MEDIUM stay as they are.
- [x] T12 [AC-18] CLAUDE.md, docs/ANATOMY.md, docs/wiki/Skills.md, docs/wiki/The-4D-Paradigm.md, docs/wiki/Glossary.md, docs/CAPABILITIES.md, connectome/lineage.yaml: update the 4D+S section, ANATOMY and the hand-written wiki pages to the new flow, regenerate the capability manifest and docs/wiki/Skills.md (generated by scripts/generate-octorato-wiki.py, never hand-edited), add the `sdd` edge to the lineage graph.

### Phase 3: the receipt, the push gate and the wiring

- [x] T13 [AC-13] scripts/receipt_ledger.py, scripts/r__subagent-stop__qa-receipt.py, scripts/tests/test_receipt_ledger.py: add `parse_converge()` and `converge_pass_for(spec_dir)`. The reflex records `kind: converge`. Tests cover a forged line, a non-verifier persona and a verdict quoted earlier in the message.
- [x] T14 [AC-14] scripts/spec_lint.py: add `--push-range <base> <head>`. For each spec whose status became `converged` in the range, require a fresh receipt as defined in the architecture decisions.
- [x] T15 [AC-14, AC-15] .githooks/pre-push: add one stanza that lints every `ears-1` spec and runs the push-range check for each ref. A missing linter blocks the push, as the other stanzas do.
- [x] T16 [AC-17] registry/rules.yaml, registry/fixtures/FLOW.done-is-a-verdict/: register `FLOW.spec-contract` and `FLOW.done-is-a-verdict` with their proofs. Fixtures hold a status flip with no receipt (blocks), with a stale receipt (blocks) and with a fresh one (allows).
- [x] T17 [AC-17] scripts/brain_doctor.py: add the `spec-contract` check. It confirms the pre-push stanza, lints every ears-1 spec on disk, and warns on a converged spec with no receipt on this machine. The two selftests already run through `gate-liveness`, so a second row would duplicate it.
- [x] T18 [AC-17] CLAUDE.md, docs/architecture/v9-done-is-a-verdict.md: register the "Done is a verdict" paragraph phase 2 added as the rule anchor and the contract document. The document states the measured residuals: whether `git push --no-verify` from a worktree is denied, receipts local to one machine, a transcript that can be forged under `$HOME`.

### Phase 4: release

- [ ] T19 [AC-12, AC-20] docs/specs/202609301321-v9-done-is-a-verdict/feature.md: run the converge pass on this spec with a verifier persona. On `CONVERGED`, commit the status change alone and push it through the new gate.
- [x] T20 [AC-18] ROADMAP.md, CHANGELOG.md: describe v9 next to v8. The operator cuts v9.0.0 with the `Octorato-Major:` trailer.

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

## Convergence 1

- [x] T21 [AC-14, AC-15] scripts/spec_lint.py, registry/fixtures/FLOW.done-is-a-verdict/: a spec change made in a merge commit never reaches the push check, because `_changed_paths` runs `git diff-tree` without `-m` or `-c` (spec_lint.py:371-372) and that prints nothing for a merge; measured in a scratch repository, `--push-range` exits 0 for a merge commit that flips Status to converged with no receipt and for a merge commit that breaks an EARS criterion, while the same edit in an ordinary commit exits 1, so read merge commits too and add one violation fixture per case.
- [x] T22 [AC-14] scripts/spec_lint.py, registry/fixtures/FLOW.done-is-a-verdict/: the state a flip is compared against is the first parent of the last commit `git rev-list` prints (spec_lint.py:455-457), and that list is ordered by commit date, not by topology; measured with base, then F (ordinary commit, flips to converged, dated 12:00), then K (child of F, committer date 11:00), then a merge M with parents K and F, where `--push-range base M` exits 0 with no receipt because the before state is read from F, while `--push-range base K` exits 1, so take the before state from the pushed base (the merge base on a new branch) and add a violation fixture.
- [x] T23 [AC-16] scripts/spec_lint.py, registry/fixtures/FLOW.spec-contract/: a `feature.md` whose header reads `> **Spec-Format:** ears-2` does not declare ears-1 and is not skipped, since `_LOOSE_FORMAT` opts in any `ears-<digits>` (spec_lint.py:108-109, 181-184) and the lint exits 1 with "Spec-Format header must be exactly"; no fixture pins either behaviour, so skip that file, or keep the refusal, pin it with a fixture and have AC-16 reworded through /sdd-refine.
- [x] T24 [AC-04, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-18, AC-19, AC-22] scripts/tests/test_sdd_skill_contract.py: the skill text read on 2026-10-01 matches each of these criteria, but nothing pins it, since no test, fixture, registry proof or doctor check reads skills/sdd-plan, sdd-analyze, sdd-implement, sdd-review, sdd-converge, sdd-refine, sdd-archive, sdd-yolo or 4d-spec (the only test that names a skill is the pre-push echo string in test_spec_lint.py:112), so a skill edited back to ticking criteria, to writing a plan over open markers or to moving a spec passes every check; add a test that asserts the contract lines of each skill and fails when one is removed.

## Convergence 2

- [x] T25 [AC-14] scripts/spec_lint.py, registry/fixtures/FLOW.done-is-a-verdict/: a spec that leaves ears-1 while its directory is renamed slips past the push check, because renames are not paired (`--no-renames`, spec_lint.py:400), the old path reads as a deleted spec (spec_lint.py:524-525) and the new path as a file that was never ears-1 (spec_lint.py:526-530); measured in a scratch repository, `git mv` of the spec directory plus dropping the Spec-Format header (or changing it to ears-2) plus the flip to `Status: converged` makes `--push-range` exit 0 with an empty ledger, and the same push with a broken criterion in place of the flip also exits 0, while each of those edits without the rename exits 1 with "stops being ears-1" and the rename with the header kept exits 1 with "holds no converge receipt", so refuse a `feature.md` that was ears-1 in the before state and is not at the pushed head whatever its path, and add a violation fixture for the renamed flip.

## Convergence 3

- [ ] T26 [AC-14] scripts/spec_lint.py, registry/fixtures/FLOW.done-is-a-verdict/: the pairing T25 added reads only the `feature.md` files that sit in a spec directory (`features` is built from `spec_paths`, spec_lint.py:514-515, 533), so a spec moved in one push to a path the gate does not read flips with no receipt; measured in a scratch repository with an empty ledger, `git mv` of `docs/specs/<name>/feature.md` to `docs/specs/<name>/v2/feature.md`, to `docs/specs/<other>/v2/feature.md` or to `notes/toy/feature.md` plus the flip to `Status: converged` makes `--push-range` exit 0, with the Spec-Format header kept and with it dropped, while the same move to `docs/specs/<other>/` or `docs/specs-archive/<name>/` exits 1, so when a push removes an ears-1 spec, refuse every `feature.md` it adds outside a spec directory, and add a violation fixture for the nested move with the header kept and one with it dropped.
