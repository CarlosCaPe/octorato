# Implementation Plan: v10, Low Friction and Easy Entry

> **Spec:** `feature.md` in this directory (`Spec-Format: ears-1`, status approved)
> **Date:** 2026-10-06

## Overview

Four phases, one pull request each, every one from its own worktree. Measurement comes first, because every later change ships with its before/after on the replay corpus and a friction fix without a baseline is an opinion. Entry and the visible brain follow, and they are independent of each other. The v9 pull request backlog is cleared alongside phase 1, outside this plan, because it is triage and not new code.

## Architecture Decisions

- **One ledger, one helper.** Gates import `scripts/friction_ledger.py` and call one function on deny. No gate grows its own log format. A helper that fails never changes the gate's decision.
- **The corpus is frozen and private.** It is built once from the 2026-09-06 to 2026-10-06 transcripts by the census scripts and stays in the gitignored `company/friction-corpus/`, because the send-ask and goal-anchor replays need prompt text that names people and arms. The tracked repo holds only baseline counts and per-case hashes. Labels are reviewed by a verifier subagent before they become the regression set.
- **Loosening is proven, never assumed.** Every gate change runs the Replay_Harness; a labelled true positive that flips to allow fails the change. This is the v8 lesson that a gate fix must be diffed for what it loosens, made mechanical.
- **Rejected: a carry inside the gate.** The first T08 let the merge gate accept a reviewed head's PASS for a rebased head with the same diff hash over its merge base. QA showed the merge base came from a local master ref the agent can move in one allowed call, so a carried PASS could land on unreviewed code. The re-review now runs as a verifier that reads the remote master, and the gate stays unchanged.
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
- [ ] T08 [AC-12, AC-13] commands/requa.md, skills/pre-merge-qa-gate/SKILL.md: add the `/requa <pr>` command, a QA subagent protocol that reads the remote master with `gh`, compares the pull request diff with the reviewed head's diff, and ends with the QA receipt lines for the new head only on a byte-identical match; the merge gate is not edited.

### Phase 3: entry

- [ ] T09 [AC-14] scripts/quickstart.py: wire hooks through `merge-hooks.py`, set `core.hooksPath`, and finish by creating a first spec that `spec_lint.py` accepts.
- [ ] T10 [AC-15] scripts/brain_doctor.py: add a fast profile under 30 s and use it from quickstart.
- [ ] T11 [AC-16] .github/workflows/fresh-clone.yml: run quickstart in a clean container on install-path changes and fail on unwired hooks or a run over 5 minutes.
- [ ] T12 [AC-14] README.md, docs/wiki/Getting-Started.md: one install path, the same in both, with the 4 concepts a newcomer needs first.
- [ ] T13 [AC-17, AC-18] CLAUDE.md, docs/architecture/: translate the Spanish sections, move mechanism narratives into the architecture docs they summarise, and keep every registry anchor; measure tokens before and after with one estimator.

### Phase 4: visible

- [ ] T14 [AC-19] scripts/octo_dash.py, scripts/octo.py, registry/rules.yaml: add `octo dash` and `octo dash --refresh` writing one self-contained HTML page from local state and a PR snapshot.
- [ ] T15 [AC-20] scripts/statusline.py, scripts/merge-hooks.py, registry/rules.yaml: add the status line and register it, measured over 100 calls.
- [ ] T23 [AC-22, AC-11] scripts/budget-check.py, scripts/tests/test_budget_cache.py: answer from a stale cache of this month (at most 24 hours old) and start one background refresh, recompute synchronously only for a missing, foreign-month, future-stamped, torn or 24-hour-old cache; measure 100 calls with a stale cache.

### Phase 5: live source

- [ ] T21 [AC-23] scripts/delegate-check, registry/rules.yaml, CLAUDE.md: print the live-source demand on a SELF verdict or an opinion request, add `--selftest` with a negative control, register the rule and anchor it.
- [ ] T22 [AC-24] scripts/connectome-heartbeat.py, registry/rules.yaml: put the live-source demand on every SELF lean of the beat, add `--selftest`, register it as a second mechanism and proof of the rule.

## Risks

- Phase 2 edits sit on the arming surface: every one goes through a worktree and a pull, and its QA receipt pins its head.
- The labels behind every false-positive rate are sampled judgment (±15 to 25 points in the census); the verifier review in T02 is what turns them into a regression set.

## Convergence 1

- [ ] T16 [AC-10] scripts/replay_harness.py, registry/friction-baseline.json: replay the Stop-gate cases of each session in order through one sandbox HOME per session so goal-anchor state carries across turns, and commit the resulting goal-anchor before/after block count; today the harness marks the gate LOW-FIDELITY (9 of 103 historical blocks reproduced, `replay` prints "these counts prove nothing") and the 21.4% figure lives only in the PR #385 body from a reconstruction script that is not in the repo.
- [ ] T17 [AC-12] scripts/tests/test_requa_protocol.py, commands/requa.md: pin the Base_Update_Verifier with an executable test over a fixture repo (two-parent check with the reviewed head among the parents, remote-read merge bases, normalized patch compare that rejects any content difference and accepts a pure base update); today AC-12 is prose in commands/requa.md with no test, and `requa` carries no registry/rules.yaml entry.
- [ ] T18 [AC-17] scripts/brain_doctor.py: add a check that estimates CLAUDE.md tokens with the committed estimator and fails above 12,000, plus a non-English section detector; today master measures 11,920 tiktoken cl100k tokens (11,881 by chars/4) with nothing pinning the ceiling or the language.
