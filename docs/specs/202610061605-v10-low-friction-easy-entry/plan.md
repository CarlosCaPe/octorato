# Implementation Plan: v10, Low Friction and Easy Entry

> **Spec:** `feature.md` in this directory (`Spec-Format: ears-1`, status draft)
> **Date:** 2026-10-06

## Overview

Four phases, one pull request each, every one from its own worktree. Measurement comes first, because every later change ships with its before/after on the replay corpus and a friction fix without a baseline is an opinion. Entry and the visible brain follow, and they are independent of each other. The v9 pull request backlog is cleared alongside phase 1, outside this plan, because it is triage and not new code.

## Architecture Decisions

- **One ledger, one helper.** Gates import `scripts/friction_ledger.py` and call one function on deny. No gate grows its own log format. A helper that fails never changes the gate's decision.
- **The corpus is frozen and redacted.** It is built once from the 2026-09-06 to 2026-10-06 transcripts by the census scripts, message bodies and secrets replaced by digests, and stored as fixtures. Labels (true positive or false positive) are reviewed by a verifier subagent before they become the regression set.
- **Loosening is proven, never assumed.** Every gate change runs the Replay_Harness; a labelled true positive that flips to allow fails the change. This is the v8 lesson that a gate fix must be diffed for what it loosens, made mechanical.
- **Patch-id, not trust.** A rebased head inherits a QA PASS only when `git patch-id --stable` of its diff equals the reviewed head's. That is the exact check a human re-QA performed by hand on 2026-10-06.
- **The Dashboard reads, never writes.** It consumes `brain_doctor --json`, `spec_lint.py`, the receipt ledger, the kernel table and the friction ledger, and writes one HTML file. Publishing it as a private Artifact is the operator's choice, not a default.

## Implementation Steps

### Phase 1: measure

- [ ] T01 [AC-01] scripts/friction_ledger.py, scripts/g__pretool-mcp__outward-send.py, scripts/qa-merge-gate.py, scripts/g__stop__goal-anchor.py: add the append helper and call it from every fail-closed gate and Stop block, with a test that a helper failure leaves the decision unchanged.
- [ ] T02 [AC-03, AC-04] scripts/replay_harness.py, registry/fixtures/friction-corpus/: build the redacted corpus from the census scripts, have a verifier subagent review the labels, and add the harness with its baseline file and non-zero exit on a lost true positive.
- [ ] T03 [AC-02] scripts/octo.py: add `octo friction` reading the ledger and the corpus labels, with median and p95 latency per gate.

### Phase 2: friction

- [ ] T04 [AC-05, AC-06, AC-07, AC-08] scripts/g__pretool-mcp__outward-send.py, registry/fixtures/FLOW.panel-before-send/: read the send ask from the last genuine operator prompt, recognise Spanish and English asks, treat support-script reads as reads; replay before and after.
- [ ] T05 [AC-09, AC-10] scripts/g__stop__goal-anchor.py, registry/fixtures/FLOW.root-goal-anchor/: never anchor an acknowledgement or a hatch token, re-anchor on a topic change; replay the Stop corpus.
- [ ] T06 [AC-10] scripts/d__stop__wa-guardia.py, scripts/claim-verify-stop.py, scripts/g__stop__delegation-audit.py, scripts/secrets-grep-guard.py: tune the remaining census top-10 sources, one replay result per script in the commit body.
- [ ] T07 [AC-11] scripts/budget-check.py: answer from a cache refreshed out of band; measure 100 consecutive calls.
- [ ] T08 [AC-12, AC-13] scripts/qa-merge-gate.py, scripts/receipt_ledger.py, registry/fixtures/: carry a QA PASS across a base-only rebase by patch-id, with a violation fixture where the patch differs.

### Phase 3: entry

- [ ] T09 [AC-14] scripts/quickstart.py: wire hooks through `merge-hooks.py`, set `core.hooksPath`, and finish by creating a first spec that `spec_lint.py` accepts.
- [ ] T10 [AC-15] scripts/brain_doctor.py: add a fast profile under 30 s and use it from quickstart.
- [ ] T11 [AC-16] .github/workflows/fresh-clone.yml: run quickstart in a clean container on install-path changes and fail on unwired hooks or a run over 5 minutes.
- [ ] T12 [AC-14] README.md, docs/wiki/Getting-Started.md: one install path, the same in both, with the 4 concepts a newcomer needs first.
- [ ] T13 [AC-17, AC-18] CLAUDE.md, docs/architecture/: translate the Spanish sections, move mechanism narratives into the architecture docs they summarise, and keep every registry anchor; measure tokens before and after with one estimator.

### Phase 4: visible

- [ ] T14 [AC-19] scripts/octo_dash.py, scripts/octo.py: add `octo dash` writing one self-contained HTML page from local state.
- [ ] T15 [AC-20] scripts/statusline.py, scripts/merge-hooks.py: add the status line and register it, measured under 200 ms.
- [ ] T16 [AC-01, AC-19, AC-20] registry/rules.yaml: register the new rules with their mechanisms and proofs so the Doctor wires them.

## Risks

- Phase 2 edits sit on the arming surface: every one goes through a worktree and a pull, and its QA receipt pins its head.
- The labels behind every false-positive rate are sampled judgment (±15 to 25 points in the census); the verifier review in T02 is what turns them into a regression set.
