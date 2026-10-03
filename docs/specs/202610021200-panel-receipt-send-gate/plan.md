# Implementation Plan: No message leaves without a panel

> **Spec:** `feature.md` in this directory (`Spec-Format: ears-1`)
> **Date:** 2026-10-02

## Overview

One pull request. The digest library first, then the receipt kind in the ledger and the reflex, then the gate, the sent ledger, the fixtures and the rule text.

## Architecture Decisions

- **The digest names bytes, not paths.** A different file at the same path is a different message.
- **The panel check runs last.** Every existing violation fixture keeps its own deny; existing benign fixtures carry a seeded PASS (`panel_fixture_seed.py`) so they still prove their own allow.
- **No hatch.** A token in the prompt would be one the model can ask for; a token in the body ships to the recipient.
- **Fail closed on uncertainty.** A body the gate cannot read with certainty denies, so the bridge must be called as a plain command with a literal message.
- **Fixture receipts use `~` paths.** The ledger reader expands `~` under the hook's HOME, so seeded rows resolve inside the selftest sandbox and still have to land in the harness projects dir.

## Implementation Steps

- [ ] T01 [AC-01, AC-02] scripts/panel_digest.py: normalize, digest, message_parts for MCP sends and support-bridge calls under both shell readings, PanelDigestError, CLI.
- [ ] T02 [AC-04] scripts/receipt_ledger.py: parse_panel, PANEL_AGENT_TYPE, panel_latest_for and panel_pass_for with the 120 minute window and the anchor check; sent_path and append_sent.
- [ ] T03 [AC-03] scripts/r__subagent-stop__qa-receipt.py: record the panel kind with its digest and anchor; skip a verdict with no valid digest.
- [ ] T04 [AC-05, AC-06, AC-07, AC-08, AC-09, AC-10] scripts/g__pretool-mcp__outward-send.py: requirement 5, checked after requirements 1-4, no hatch, fail closed.
- [ ] T05 [AC-11] scripts/r__posttool__sent-ledger.py, hooks.json: PostToolUse reflex writing the sent ledger, with a selftest.
- [ ] T06 [AC-10, AC-12] scripts/panel_fixture_seed.py, registry/fixtures/COMMS.outward-send-gate: seed a PASS receipt for every existing message-send fixture; move the archivo fixture's attachment into the fixture home.
- [ ] T07 [AC-05, AC-06, AC-07, AC-08, AC-09, AC-12] registry/fixtures/FLOW.panel-before-send: violation and benign pairs (no receipt, newer NEEDS-WORK, edited body, changed attachment, missing attachment, allowlisted chat, send-ok, other session, stale, forged row, non-reviewer persona, substitution, draft by id).
- [ ] T08 [AC-11, AC-12] registry/fixtures/FLOW.sent-message-ledger, registry/rules.yaml: sent-ledger cases and both rule entries.
- [ ] T09 [AC-01, AC-03, AC-04, AC-11] scripts/tests/test_panel_receipt.py: digest, reflex, newest-decides, session and window, and all three selftests.
- [ ] T10 [AC-13] CLAUDE.md, docs/architecture/v7-nothing-ships-unverified.md, docs/ANATOMY.md: panel receipt and sent-message ledger under "Nothing ships unverified"; the outward-send bullet names the panel and its lack of a hatch.

## QA cycle 1

- [ ] T11 [AC-14, AC-15, AC-16, AC-17] scripts/panel_digest.py: per-tool known key sets, recipients in the digest, the panel block and its recompute, the bridge as the only command.
- [ ] T12 [AC-14, AC-18] scripts/receipt_ledger.py, scripts/r__subagent-stop__qa-receipt.py: record and honour only a recomputed digest; panel_receipt_consumed.
- [ ] T13 [AC-18, AC-19] scripts/g__pretool-mcp__outward-send.py: raw bridge send detection, single-use deny, the --panel-request instruction.
- [ ] T14 [AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20] registry/fixtures/FLOW.panel-before-send, registry/fixtures/COMMS.outward-send-gate, registry/fixtures/FLOW.sent-message-ledger, scripts/panel_fixture_seed.py: one violation per finding, `.txt` attachment seeds, reseed with blocks.
- [ ] T15 [AC-14, AC-15, AC-16, AC-17, AC-18] scripts/tests/test_panel_receipt.py: block round trip, recompute refusal, unknown keys, chained bridge, recipient, single use.

## QA cycle 2

- [ ] T16 [AC-21, AC-22, AC-23] scripts/g__pretool-mcp__outward-send.py: any-host port match after quote removal, SSM payload inspection, inline interpreter and run-time URL detection.
- [ ] T17 [AC-21, AC-22, AC-23] registry/fixtures/FLOW.panel-before-send: one violation per shape plus benign plain SSM read, remote requests, header variable and lsof.
