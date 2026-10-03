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

A chat row in `company/config/outward-send-autonomous.json` may carry `approvers`, a list of sender ids as the bridge stores them: LID digits, phone digits or full JIDs. Ids are compared after dropping the `@server` part and any `:device` suffix. A chat whose `approvers` is missing or empty releases nothing. An `is_from_me` row never approves in either store: in the personal store it is the operator or the agent sending through his account, which the store cannot tell apart, and in the support replica it is the bridge's own account. The operator approves through his id in `approvers` (support replica) or through the existing `send_ok_from_chat` token (personal store). The window is the row's `window_minutes` (default 60, valid 1..240; any other value disables the row). The file stays the operator's: the agent never writes it.

### FR-02: The validation message

The sent-message ledger records the normalized text of every WhatsApp message the agent sends. A validation message V for a send S is a ledger line, on a WhatsApp channel, to an allowlisted chat C that has approvers, written after the PASS panel receipt that decides S, in the shape `panel_digest.py --validation-request` prints: one `sha256:<first 12 hex of S's panel digest>` token, a `To:` line, an `Attach:` line when S carries files, S's text inside exactly one «...» block, and a fixed trailer line. The shape is closed: the whole text, whitespace-normalized, must equal what `--validation-request` prints for S, so any word before, between or after those lines denies. Nothing is matched as a substring: the block, normalized, equals S's normalized text; the digest prefix equals S's; the set of address tokens outside the block (whole mail-shaped tokens, `message:<id>`, standalone runs of 6+ digits) equals S's recipients, case-insensitive; every attachment file name is a whole token. A send of more than one message is never released this way.

### FR-03: The approval

In C, after V and inside the window counted from V, an approver posts a message whose text, lower-cased, without accents, mentions, punctuation or emoji, is one of a closed list: `si`, `si asi`, `si asi envialo`, `envialo`, `mandalo`, `ok`, `dale`, `send-ok`, `yes`, `go ahead`. A message that also carries `no`, `espera`, `cambia` or `pero` never approves. Approver messages are read from the personal bridge store when C has rows there, else from the support bridge's local replica, both at fixed paths. An approval binds to exactly one V: the latest validation message the agent posted to C before the approval. It releases S only when that V is S's, and it is ambiguous, releasing nothing, when the agent posted more than one validation message to C inside the window before the approval. A store row whose id is a message the agent itself sent never approves. A missing or unreadable store releases nothing.

### FR-04: Retraction and single use

A later message in C from an approver, or from `is_from_me` in the personal store, before the send, that carries `no`, `espera`, `para`, `cancela`, `cambia`, `stop`, `wait` or `cancel` withdraws the approval. One approval releases one send: the Sent_Ledger_Reflex records the release key (chat, approval message id) on the line of the send it released, and the gate refuses a key already on a line whose channel did not report failure.

### FR-05: Scope and denies

Only message sends qualify: the Gmail send, reply and forward tools, the WhatsApp send tools, and a plain support-bridge call. Deploys and releases never do. A send that does not qualify falls back to the existing rules. When the send ask denies and an allowlisted chat carries approvers, the deny names the condition of the release that failed.

## Acceptance Criteria

- [ ] AC-01: WHEN a message send has a PASS panel receipt, a validation message in an allowlisted chat with approvers, and an affirmative reply from an approver after it inside the window, THE Send_Gate SHALL waive the explicit send ask for that send.
- [ ] AC-02: IF the affirmative reply comes from a sender that is not an approver, THEN THE Send_Gate SHALL not release the send.
- [ ] AC-03: IF the affirmative reply was posted before the validation message, or the validation message was posted before the panel receipt, THEN THE Send_Gate SHALL not release the send.
- [ ] AC-04: IF more than the chat's window has passed since the validation message, THEN THE Send_Gate SHALL not release the send.
- [ ] AC-05: IF an approver posts a retraction after the approval, THEN THE Send_Gate SHALL not release the send.
- [ ] AC-06: IF the validation message, whitespace-normalized, is not exactly the text `--validation-request` prints for the send (text before, between or after its lines included), the quoted block is not equal to the send's normalized text, its digest prefix is not the send's, its set of address tokens is not equal to the send's recipients, or an attachment file name is not a whole token of it, THEN THE Send_Gate SHALL not release the send.
- [ ] AC-07: IF the sent ledger already carries the release key (chat, approval message id) on a send that did not report failure, THEN THE Send_Gate SHALL not release a second send.
- [ ] AC-08: IF the send is a deploy or a release, THEN THE Send_Gate SHALL not release it through a chat approval.
- [ ] AC-09: IF the reply is not on the closed affirmative list, or carries `no`, `espera`, `cambia` or `pero`, THEN THE Send_Gate SHALL not treat it as an approval.
- [ ] AC-10: IF the store that holds the chat is missing or unreadable, THEN THE Send_Gate SHALL not release the send.
- [ ] AC-11: WHEN the send ask denies and an allowlisted chat carries approvers, THE Send_Gate SHALL name the release condition that failed in the deny reason.
- [ ] AC-12: WHEN a WhatsApp message send completes, THE Sent_Ledger_Reflex SHALL record its normalized text, and WHEN a send was released by a chat approval it SHALL record the release key.
- [ ] AC-13: THE Rule_Registry SHALL hold `FLOW.chat-validated-release` as a fail-closed gate with a violation and benign fixture pair built by the Fixture_Seed from synthetic ids only.
- [ ] AC-14: THE Rule_Text SHALL describe the approvers key, the release conditions and the residuals.
- [ ] AC-15: IF a store row that would approve is a message the agent itself sent, or is an `is_from_me` row in either store, THEN THE Send_Gate SHALL not treat it as an approval.
- [ ] AC-16: IF the latest validation message the agent posted to the chat before the approval is not the send's own, or the agent posted more than one validation message to the chat inside the window before the approval, THEN THE Send_Gate SHALL not release the send.
- [ ] AC-17: IF the chat's `approvers` is missing or empty, THEN THE Send_Gate SHALL not release any send through that chat.
- [ ] AC-18: WHEN an `is_from_me` row in the personal store carries a retraction word after the approval, THE Send_Gate SHALL treat the approval as withdrawn.

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
- The operator's plain yes in the personal store does not release: that store cannot tell his phone from the agent sending through his account, so his approval there stays the `send-ok` token (`send_ok_from_chat`).
- Residual: an approver reads the attachment's file name, not its bytes; the panel receipt still covers the bytes.
- Residual: parallel tool calls can race single use, as with the panel receipt.
- Residual: an approval binds by time, not by a quoted message id (the store keeps no reply reference), so an "ok" meant for a validation message posted outside the window can still bind to a newer one posted alone inside it.

## Revision History

| Date | Change |
|---|---|
| 2026-10-03 | Initial spec. |
| 2026-10-03 | QA on 3c7781f (PASS with two loosenings): text after the «...» block was ignored, now the shape is closed and compared whole (AC-06); two validation messages inside the window before an approval make it ambiguous (AC-16). |
| 2026-10-03 | QA on 07cf9ee (NEEDS-WORK): substring binding let a truncated send pass and `notbob@example.test.evil` name `bob@example.test`; one yes released two sends; the agent's own yes counted when its ledger id was empty. Now: equality against the `--validation-request` shape (AC-06), one approval binds to the latest validation message before it and is spent by its own id (AC-07, AC-16), `is_from_me` never approves (AC-15), empty approvers release nothing (AC-17), the operator's phone can retract (AC-18). |
