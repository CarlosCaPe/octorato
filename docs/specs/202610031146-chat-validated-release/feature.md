# Feature: Chat-validated release

> **Status:** draft
> **Spec-Format:** ears-1
> **Date:** 2026-10-03
> **Classification:** LARGE (score 9: 4-10 files, a new release path on the outward-send gate, a new rule, multiple modules)

Operator directive 2026-10-03: the gate must change, because the operator cannot be the one person watching every send, and another admin of the same chat holds the same authority. Earlier the same day the operator approved the method: post in the chat what the email says, only to validate it. Until now an email to a third party left only with the operator's own `send-ok` in his prompt, and a `send-ok` typed in a chat released only message sends and only from the operator's own phone.

## Summary

A chat on the private autonomous allowlist may name `approvers`: the bridge sender ids of the people whose word in that chat counts as the operator's. The agent posts the exact message it wants to send, with its recipients, to that chat (the validation message). When an approver answers with a plain yes inside the chat's window, and nobody with that authority takes it back, the gate treats that one send as asked for. It waives the send ask only: the panel receipt, the gate receipt and the phrase checks still run, and deploys and releases never pass this way.

## Glossary

Every acceptance criterion names one of these components as its subject.

- **Send_Gate**: `scripts/g__pretool-mcp__outward-send.py`, the PreToolUse gate on the send tools and Bash.
- **Sent_Ledger_Reflex**: `scripts/r__posttool__sent-ledger.py`, the PostToolUse reflex that writes `sent.jsonl`.
- **Fixture_Seed**: `scripts/chat_release_fixture_seed.py`, the builder of the rule's fixture home.
- **Rule_Registry**: `registry/rules.yaml` with its fixtures under `registry/fixtures/`.
- **Rule_Text**: the "Nothing ships unverified" section of `CLAUDE.md`.

## User Stories

- As the operator, I want another admin of a chat to approve a send in that chat, so that I am not the only one watching every outgoing message.
- As the operator, I want the approver to see the exact text and recipients before saying yes, so that a yes never covers a message nobody read.
- As the operator, I want any approver to stop a send by answering no or wait, so that a yes can be taken back before the message leaves.

## Functional Requirements

### FR-01: Approvers live in the private allowlist

A chat row in `company/config/outward-send-autonomous.json` may carry `approvers`, a list of sender ids as the bridge stores them: LID digits, phone digits or full JIDs. Ids are compared after dropping the `@server` part and any `:device` suffix. The operator is always an approver through `is_from_me` in the personal bridge store. The window is the row's `window_minutes` (default 60, valid 1..240; any other value disables the row). The file stays the operator's: the agent never writes it.

### FR-02: The validation message

The sent-message ledger records the normalized text of every WhatsApp message the agent sends. A validation message V for a send S is a ledger line, on a WhatsApp channel, to an allowlisted chat C that has approvers, written after the PASS panel receipt that decides S, whose text contains every text field of S (subject, body, htmlBody, forwardText, message; panel_digest normalization) and names every recipient of S and the file name of every attachment.

### FR-03: The approval

In C, after V and inside the window counted from V, an approver posts a message whose text, lower-cased, without accents, mentions, punctuation or emoji, is one of a closed list: `si`, `si asi`, `si asi envialo`, `envialo`, `mandalo`, `ok`, `dale`, `send-ok`, `yes`, `go ahead`. A message that also carries `no`, `espera`, `cambia` or `pero` never approves. Approver messages are read from the personal bridge store when C has rows there, else from the support bridge's local replica, both at fixed paths. In the support replica `is_from_me` is the bridge's own account, never the operator, so it never approves. A store row whose id is a message the agent itself sent never approves. A missing or unreadable store releases nothing.

### FR-04: Retraction and single use

A later approver message in C, before the send, that carries `no`, `espera`, `para`, `cancela`, `cambia`, `stop`, `wait` or `cancel` withdraws the approval. One V plus one approval releases one send: the Sent_Ledger_Reflex records the release key (chat, V, approval) on the line of the send it released, and the gate refuses a key already on a line whose channel did not report failure.

### FR-05: Scope and denies

Only message sends qualify: the Gmail send, reply and forward tools, the WhatsApp send tools, and a plain support-bridge call. Deploys and releases never do. A send that does not qualify falls back to the existing rules. When the send ask denies and an allowlisted chat carries approvers, the deny names the condition of the release that failed.

## Acceptance Criteria

- [ ] AC-01: WHEN a message send has a PASS panel receipt, a validation message in an allowlisted chat with approvers, and an affirmative reply from an approver after it inside the window, THE Send_Gate SHALL waive the explicit send ask for that send.
- [ ] AC-02: IF the affirmative reply comes from a sender that is not an approver, THEN THE Send_Gate SHALL not release the send.
- [ ] AC-03: IF the affirmative reply was posted before the validation message, or the validation message was posted before the panel receipt, THEN THE Send_Gate SHALL not release the send.
- [ ] AC-04: IF more than the chat's window has passed since the validation message, THEN THE Send_Gate SHALL not release the send.
- [ ] AC-05: IF an approver posts a retraction after the approval, THEN THE Send_Gate SHALL not release the send.
- [ ] AC-06: IF the validation message does not contain every text field of the send, or does not name every recipient and attachment file name, THEN THE Send_Gate SHALL not release the send.
- [ ] AC-07: IF the sent ledger already carries the release key on a send that did not report failure, THEN THE Send_Gate SHALL not release a second send.
- [ ] AC-08: IF the send is a deploy or a release, THEN THE Send_Gate SHALL not release it through a chat approval.
- [ ] AC-09: IF the reply is not on the closed affirmative list, or carries `no`, `espera`, `cambia` or `pero`, THEN THE Send_Gate SHALL not treat it as an approval.
- [ ] AC-10: IF the store that holds the chat is missing or unreadable, THEN THE Send_Gate SHALL not release the send.
- [ ] AC-11: WHEN the send ask denies and an allowlisted chat carries approvers, THE Send_Gate SHALL name the release condition that failed in the deny reason.
- [ ] AC-12: WHEN a WhatsApp message send completes, THE Sent_Ledger_Reflex SHALL record its normalized text, and WHEN a send was released by a chat approval it SHALL record the release key.
- [ ] AC-13: THE Rule_Registry SHALL hold `FLOW.chat-validated-release` as a fail-closed gate with a violation and benign fixture pair built by the Fixture_Seed from synthetic ids only.
- [ ] AC-14: THE Rule_Text SHALL describe the approvers key, the release conditions and the residuals.
- [ ] AC-15: IF a store row that would approve is a message the agent itself sent, THEN THE Send_Gate SHALL not treat it as an approval.

## Technical Scope

### Affected Modules

- `scripts/g__pretool-mcp__outward-send.py`, `scripts/r__posttool__sent-ledger.py`
- `scripts/chat_release_fixture_seed.py` (new), `registry/fixtures/FLOW.chat-validated-release/` (new), `registry/fixtures/FLOW.sent-message-ledger/`
- `registry/rules.yaml`, `CLAUDE.md`, `scripts/tests/test_chat_release.py` (new)

### Integration Points

The release is one more waiver of requirement 4 (the explicit send ask), next to the autonomous-chat allowlist and the chat-typed `send-ok`. It reads the panel receipt through `receipt_ledger.panel_pass_for`, the sent ledger through `receipt_ledger.read_sent`, and the bridge stores read-only through sqlite. The sent-ledger reflex loads the gate by path to compute the same release key the gate checked.

## Non-Functional Requirements

- No network call. Stores open read-only (`mode=ro`).
- The release logic lives in the gate file, which is on the arming surface, so the live copy cannot be edited by a hooked process.

## Out of Scope

- Writing `approvers` into the config: the operator adds them by hand.
- Natural phrasings outside the closed list ("perfecto, mándalo ya"): they fail closed and the operator's prompt `send-ok` remains the fallback.
- Residual: the bridge stores, `sent.jsonl` and the config are files under `$HOME` a hooked process can write, so a forged store row plus a forged ledger line can release a send (visible in the bridge database and the kernel journal, not prevented).
- Residual: outgoing messages of the personal bridge are not always persisted to its store, so the own-message exclusion works by message id and only where the sent ledger holds that id.
- Residual: an approver reads the attachment's file name, not its bytes; the panel receipt still covers the bytes.
- Residual: parallel tool calls can race single use, as with the panel receipt.

## Revision History

| Date | Change |
|---|---|
| 2026-10-03 | Initial spec. |
