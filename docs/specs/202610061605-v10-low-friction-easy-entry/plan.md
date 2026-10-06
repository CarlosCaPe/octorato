# Implementation Plan: v10, Low Friction and Easy Entry

> **Spec:** `feature.md` in this directory (`Spec-Format: ears-1`, status approved)
> **Date:** 2026-10-06

## Overview

Four phases, one pull request each, every one from its own worktree. Measurement comes first, because every later change ships with its before/after on the replay corpus and a friction fix without a baseline is an opinion. Entry and the visible brain follow, and they are independent of each other. The v9 pull request backlog is cleared alongside phase 1, outside this plan, because it is triage and not new code.

## Architecture Decisions

- **One ledger, one helper.** Gates import `scripts/friction_ledger.py` and call one function on deny. No gate grows its own log format. A helper that fails never changes the gate's decision.
- **The corpus is frozen and private.** It is built once from the 2026-09-06 to 2026-10-06 transcripts by the census scripts and stays in the gitignored `company/friction-corpus/`, because the send-ask and goal-anchor replays need prompt text that names people and arms. The tracked repo holds only baseline counts and per-case hashes. Labels are reviewed by a verifier subagent before they become the regression set.
- **Loosening is proven, never assumed.** Every gate change runs the Replay_Harness; a labelled true positive that flips to allow fails the change. This is the v8 lesson that a gate fix must be diffed for what it loosens, made mechanical.
- **A diff hash, not trust.** A rebased head inherits a QA PASS only when a whitespace-sensitive hash of its diff over the merge base equals the reviewed head's, with both commits local. `git patch-id` was rejected: it ignores whitespace, so a re-indent during conflict resolution would keep the id.
- **Each mechanism is registered in the PR that ships it.** Rule #1 makes an unregistered mechanism rot, so `registry/rules.yaml` is in every task that adds a gate, reflex or command.
- **The Dashboard reads, never writes.** It consumes `brain_doctor --json`, `spec_lint.py`, the receipt ledger, the kernel table and the friction ledger, and writes one HTML file. Publishing it as a private Artifact is the operator's choice, not a default.

## Implementation Steps

### Phase 1: measure

- [ ] T01 [AC-01] scripts/friction_ledger.py, scripts/r__stop__friction-ledger.py, hooks.json, registry/rules.yaml: build the ledger from the harness transcript (every PreToolUse deny and Stop block the harness recorded, so no gate body changes), run it as a Stop reflex that never blocks, register it, and test it against a transcript fixture holding one deny and one Stop block.
- [ ] T02 [AC-03, AC-04] scripts/replay_harness.py, registry/friction-baseline.json: build the private corpus in `company/friction-corpus/` from the census scripts, have a verifier subagent review the labels, track only counts and hashes, and exit non-zero on a lost true positive.
- [ ] T03 [AC-02] scripts/octo.py: add `octo friction` reading the ledger and the corpus labels, with median and p95 latency per gate.

### Phase 2: friction

- [ ] T04 [AC-05, AC-06, AC-07, AC-08] scripts/g__pretool-mcp__outward-send.py, registry/send-ask.yaml, registry/fixtures/FLOW.panel-before-send/: read the send ask from the last genuine operator prompt, recognise Spanish and English asks, treat support-script reads as reads; replay before and after.
- [ ] T05 [AC-09, AC-10] scripts/g__stop__goal-anchor.py, registry/fixtures/FLOW.root-goal-anchor/: never anchor an acknowledgement or a hatch token, re-anchor on a topic change; replay the Stop corpus.
- [ ] T06 [AC-21, AC-04] scripts/d__stop__wa-guardia.py, scripts/claim-verify-stop.py, scripts/g__stop__delegation-audit.py, scripts/secrets-grep-guard.py: tune the remaining census top-10 sources, one replay result per script in the commit body.
- [ ] T07 [AC-11, AC-22] scripts/budget-check.py, hooks.json: answer from a cache refreshed at SessionStart and after each spawn, recompute synchronously when it is older than 15 minutes, keep the fail-closed decision; measure 100 consecutive calls.
- [ ] T08 [AC-12, AC-13] scripts/qa-merge-gate.py, scripts/receipt_ledger.py, scripts/r__subagent-stop__qa-receipt.py, registry/fixtures/, CLAUDE.md, docs/specs/202610012100-qa-receipt-bound-to-head/feature.md: carry a QA PASS across a base-only rebase by the diff hash, with violation fixtures for a whitespace-only change and a missing local commit, and restate the merge contract and its residual.

### Phase 3: entry

- [ ] T09 [AC-14] scripts/quickstart.py: wire hooks through `merge-hooks.py`, set `core.hooksPath`, and finish by creating a first spec that `spec_lint.py` accepts.
- [ ] T10 [AC-15] scripts/brain_doctor.py: add a fast profile under 30 s and use it from quickstart.
- [ ] T11 [AC-16] .github/workflows/fresh-clone.yml: run quickstart in a clean container on install-path changes and fail on unwired hooks or a run over 5 minutes.
- [ ] T12 [AC-14] README.md, docs/wiki/Getting-Started.md: one install path, the same in both, with the 4 concepts a newcomer needs first.
- [ ] T13 [AC-17, AC-18] CLAUDE.md, docs/architecture/: translate the Spanish sections, move mechanism narratives into the architecture docs they summarise, and keep every registry anchor; measure tokens before and after with one estimator.

### Phase 4: visible

- [ ] T14 [AC-19] scripts/octo_dash.py, scripts/octo.py, registry/rules.yaml: add `octo dash` and `octo dash --refresh` writing one self-contained HTML page from local state and a PR snapshot.
- [ ] T15 [AC-20] scripts/statusline.py, scripts/merge-hooks.py, registry/rules.yaml: add the status line and register it, measured over 100 calls.

## Risks

- Phase 2 edits sit on the arming surface: every one goes through a worktree and a pull, and its QA receipt pins its head.
- The labels behind every false-positive rate are sampled judgment (±15 to 25 points in the census); the verifier review in T02 is what turns them into a regression set.
