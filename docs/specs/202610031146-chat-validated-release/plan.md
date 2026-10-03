# Implementation Plan: Chat-validated release

> **Spec:** `feature.md` in this directory (`Spec-Format: ears-1`)
> **Date:** 2026-10-03

## Overview

One pull request. The release logic in the gate, the text and release key in the sent ledger, the fixture builder and fixtures, the rule, the tests and the rule text.

## Architecture Decisions

- **A waiver of the send ask, nothing more.** The panel check still runs last and still has no hatch; the release needs the panel PASS as its first condition anyway.
- **The logic stays in the gate file.** It is on the arming surface; a helper module outside it would be a live file a hooked process could rewrite.
- **Times come from three clocks, compared conservatively.** The panel receipt's harness timestamp, the sent ledger's write time (later than the real send) and the bridge store's message time; V's time is the later of its ledger time and its store row.
- **The support replica's `is_from_me` is the bot.** Only the personal store's `is_from_me` is the operator.

## Implementation Steps

- [ ] T01 [AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-09, AC-10, AC-15] scripts/g__pretool-mcp__outward-send.py: approvers from the allowlist, validation message lookup, store reads, closed yes-list, retraction, release key.
- [ ] T02 [AC-07, AC-08, AC-11] scripts/g__pretool-mcp__outward-send.py: single use from the sent ledger, message sends only, the failed condition in the send-ask deny.
- [ ] T03 [AC-12] scripts/r__posttool__sent-ledger.py: normalized text on WhatsApp lines and the release key on a released send.
- [ ] T04 [AC-13] scripts/chat_release_fixture_seed.py: build the fixture home (config, personal store, sent ledger, panel receipts, gate receipt) from synthetic ids.
- [ ] T05 [AC-13] registry/fixtures/FLOW.chat-validated-release: one benign per release path and one violation per condition.
- [ ] T06 [AC-12] registry/fixtures/FLOW.sent-message-ledger: expected lines carry the text field.
- [ ] T07 [AC-13] registry/rules.yaml: `FLOW.chat-validated-release` fail-closed with its selftest proof.
- [ ] T08 [AC-01, AC-03, AC-09, AC-10, AC-12, AC-15] scripts/tests/test_chat_release.py: yes-list, sender ids, support replica path, own-message exclusion, attachment names, reflex key.
- [ ] T09 [AC-14] CLAUDE.md: the chat-validated release under "Nothing ships unverified", with its residuals.

## QA cycle 1

- [ ] T10 [AC-06, AC-07, AC-15, AC-16, AC-17, AC-18] scripts/g__pretool-mcp__outward-send.py: equality against the validation shape, one approval bound to the latest validation message, key per approval id, is_from_me never approves, empty approvers release nothing, operator retraction.
- [ ] T11 [AC-06] scripts/panel_digest.py: validation_text and `--validation-request`.
- [ ] T12 [AC-06, AC-07, AC-15, AC-16, AC-17, AC-18] scripts/chat_release_fixture_seed.py, registry/fixtures/FLOW.chat-validated-release: one violation per QA finding (truncated send, recipient substring, cc missing, one yes two validations, agent yes with no message id, empty approvers, operator retraction, mejor no).
- [ ] T13 [AC-06, AC-16] scripts/tests/test_chat_release.py: whole-token and equality checks, attachment token, key per approval.
- [ ] T14 [AC-14] CLAUDE.md: the new rules and residuals.

## QA cycle 2

- [ ] T15 [AC-06, AC-16] scripts/panel_digest.py, scripts/g__pretool-mcp__outward-send.py: closed validation shape with a fixed trailer compared whole; ambiguity when two validation messages sit inside the window before an approval.
- [ ] T16 [AC-06, AC-16] scripts/chat_release_fixture_seed.py, registry/fixtures/FLOW.chat-validated-release: text after the block, text before the shape, changed trailer, an ok between two validation messages.
