# Feature: No message leaves without a panel

> **Status:** draft
> **Spec-Format:** ears-1
> **Date:** 2026-10-02
> **Classification:** LARGE (score 9: 10+ files, a new receipt kind on the outward-send gate, multiple modules)

Operator directive 2026-10-02: no message is sent without a panel, however insignificant it looks, and the rule is wired in code. Until now the outward-send gate checked receipts, phrases and the send ask, but a message nobody reviewed could still leave whenever those checks were quiet.

## Summary

A panel is an independent reviewer subagent. Its verdict counts only when a hook records it from the reviewer's own transcript and the gate can tell that the message about to leave is the message the panel read. Both sides compute one digest, `scripts/panel_digest.py`: sha256 over the outgoing text, normalized for whitespace, plus the sha256 of every attachment's bytes. The reviewer ends with `PANEL-VERDICT` and `PANEL-SHA256`; the SubagentStop reflex records a `panel` receipt anchored to that transcript entry; the outward-send gate denies every message send unless the receipt that decides that exact digest, in this session and inside 120 minutes, says PASS. A PostToolUse reflex then records every message that left, with the id its channel returned, for a later recall step.

## Glossary

Every acceptance criterion names one of these components as its subject.

- **Panel_Digest**: `scripts/panel_digest.py`, the digest library and CLI.
- **Panel_Reviewer**: a reviewer subagent whose agent type matches the receipt ledger's reviewer persona set (the QA set plus `panel`).
- **Receipt_Reflex**: `scripts/r__subagent-stop__qa-receipt.py`, the SubagentStop hook that records QA, converge and panel receipts.
- **Receipt_Ledger**: `scripts/receipt_ledger.py`.
- **Send_Gate**: `scripts/g__pretool-mcp__outward-send.py`, the PreToolUse gate on the send tools and Bash.
- **Sent_Ledger_Reflex**: `scripts/r__posttool__sent-ledger.py`, the PostToolUse reflex on the same send tools.
- **Rule_Registry**: `registry/rules.yaml` with its fixtures under `registry/fixtures/`.
- **Rule_Text**: the "Nothing ships unverified" section of `CLAUDE.md`.

## User Stories

- As the operator, I want every message that leaves to have been read by an independent panel, so that a careless line never reaches a client or a chat.
- As the operator, I want an edit after the panel to need a new panel, so that a reviewed message cannot be swapped for an unreviewed one.
- As the operator, I want a record of every message that left with its channel id, so that a later step can recall it.

## Functional Requirements

### FR-01: One digest for both sides

The digest is sha256 over the normalized text, a newline, and the sorted sha256 hashes of the attachment bytes. Text fields are read in a fixed order (subject, body, htmlBody, forwardText, message, caption). The support bridge message is every positional after the recipient joined by one space, as the script builds it. Whitespace layout does not change the digest; one word or one attachment byte does.

### FR-02: The panel receipt

A reviewer ends its report with `PANEL-VERDICT: PASS|NEEDS-WORK` and `PANEL-SHA256: <64 hex>`. The reflex records `kind: panel` with the digest, verdict, agent id and type, transcript path, session id and the harness uuid and timestamp of the entry. A consumer re-reads that entry. The newest receipt for a digest decides; a NEEDS-WORK at an equal time wins.

### FR-03: The gate

Every message send the gate already covers is checked after requirements 1-4, so each earlier check keeps its own deny: mail send, reply and forward on both Gmail servers, WhatsApp `send_message`, `send_file` and `send_audio_message`, and the support bridge, `--archivo` included. There is no hatch. `send-ok`, the autonomous-chat allowlist and a chat-typed `send-ok` waive the send ask only. Deploys and releases are not messages and stay out of scope.

### FR-04: The sent-message ledger

After a message send, the reflex reads the tool result and appends one line per message to `~/.claude/.cache/receipts/sent.jsonl` (gitignored): channel (gmail, wa-personal, wa-support), recipient, message id, chat id when the channel returns one, digest, the panel receipt's entry uuid, session id, tool use id, time and the channel's own success flag. It never blocks.

## Acceptance Criteria

- [ ] AC-01: THE Panel_Digest SHALL return the same digest for two texts that differ only in whitespace layout, and a different digest when one word or one attachment byte differs.
- [ ] AC-02: IF an attachment is not a readable regular file, a base64 attachment does not decode, a draft is sent by id, or a support-bridge call sits behind a wrapper, a variable, a substitution or a heredoc, THEN THE Panel_Digest SHALL raise an error instead of returning a digest.
- [ ] AC-03: WHEN a Panel_Reviewer's final report carries `PANEL-VERDICT` and a 64-hex `PANEL-SHA256`, THE Receipt_Reflex SHALL record a `panel` receipt with that digest and the harness uuid and timestamp of the entry.
- [ ] AC-04: THE Receipt_Ledger SHALL honour a panel receipt only when its entry re-reads to the same verdict and digest, its transcript is a harness agent transcript of the asking session, its agent type is a reviewer persona and its entry is at most 120 minutes old, and SHALL let the newest such receipt for a digest decide.
- [ ] AC-05: IF a message send carries no PASS panel receipt for its exact digest, THEN THE Send_Gate SHALL deny it and print the digest and the command that computes it.
- [ ] AC-06: IF a NEEDS-WORK panel receipt for a digest is newer than its PASS, THEN THE Send_Gate SHALL deny the send.
- [ ] AC-07: IF the body or an attachment changed after the panel, THEN THE Send_Gate SHALL deny the send.
- [ ] AC-08: WHEN the recipient is on the autonomous-chat allowlist or the operator typed `send-ok`, THE Send_Gate SHALL still deny a send that carries no PASS panel receipt.
- [ ] AC-09: IF the Panel_Digest cannot determine what a send carries, THEN THE Send_Gate SHALL deny the send.
- [ ] AC-10: THE Send_Gate SHALL run the panel check after its receipt, absence, attribute, promise, thread and send-ask checks, so every existing violation fixture is still denied by its own check.
- [ ] AC-11: WHEN a message send completes, THE Sent_Ledger_Reflex SHALL append one line per message with channel, recipient, message id, digest, panel receipt id, session id and time to the sent ledger.
- [ ] AC-12: THE Rule_Registry SHALL hold `FLOW.panel-before-send` as a fail-closed gate with a violation and benign fixture pair, and `FLOW.sent-message-ledger` as a reflex with its own selftest.
- [ ] AC-13: THE Rule_Text SHALL describe the panel receipt, the absence of a hatch and the sent-message ledger.

## Technical Scope

### Affected Modules

- `scripts/panel_digest.py` (new), `scripts/panel_fixture_seed.py` (new), `scripts/r__posttool__sent-ledger.py` (new)
- `scripts/receipt_ledger.py`, `scripts/r__subagent-stop__qa-receipt.py`, `scripts/g__pretool-mcp__outward-send.py`
- `hooks.json`, `registry/rules.yaml`, `registry/fixtures/FLOW.panel-before-send/`, `registry/fixtures/FLOW.sent-message-ledger/`, `registry/fixtures/COMMS.outward-send-gate/`
- `CLAUDE.md`, `scripts/tests/test_panel_receipt.py`

### Integration Points

The gate imports the digest library and the ledger. The Bash path reuses the merge gate's two shell readings through `receipt_ledger.subcommands`, and both must agree on what the bridge sends.

## Non-Functional Requirements

- The sent-ledger reflex leaves before any import for a Bash command that does not name the support bridge, because every Bash call reaches it.
- No network call in the gate or the reflexes.

## Out of Scope

- Deploys and releases: the gate keeps its existing checks there, no panel.
- Recall (Deferred): a separate spec will revoke WhatsApp messages by id (the support bridge's `/api/revoke`, the personal MCP's `revoke_message`) and hold mails in a cancel window, reading the sent ledger this spec writes.
- Hashing the recipient, and hashing the forwarded original of a Gmail forward (residuals, stated in `panel_digest.py`).

## Revision History

| Date | Change |
|---|---|
| 2026-10-02 | Initial spec; scope addition from the operator the same day: the sent-message ledger (AC-11) with recall deferred. |
