# Feature: v11, No Reply Unreviewed

> **Status:** converged
> **Spec-Format:** ears-1
> **Date:** 2026-10-14
> **Classification:** LARGE (score 9: 4-10 files, new feature, architectural decision, multiple modules)

v7 made an unverified send impossible: no message leaves for a third party without a panel receipt for its exact digest. v11 moves that boundary to the operator. Every reply the main loop gives the operator carries a PASS panel receipt for its exact text, recorded by a hook from an independent reviewer, or the turn is sent back.

## Summary

Operator directive 2026-10-14: every reply, not only messages to third parties, goes through a panel of one to three reviewer subagents, and the rule is enforced in code, not by model discipline. On the same day the first manual panel of a design reply found 8 defects (a wrong 4D+S score, a false "first gate" claim, missing residuals, a verdict written before the reviewer returned).

The panel machinery already exists: `panel_digest.py` computes the digest, the SubagentStop reflex records a `panel` receipt only when the reviewer's own report carries the block and recomputes to the stated digest, and `receipt_ledger.panel_pass_for` returns the deciding PASS. A recipient is free text in `PANEL-TO`, so `panel_digest.py --panel-request --to operator --body-file <f>` already prints a valid block (measured 2026-10-14, exit 0, recompute matches). What is missing is a consumer at the reply boundary.

Claude Code has no hook that can stop text before it is displayed: "MessageDisplay hooks have no decision control. They can't block the message" (code.claude.com/docs/en/hooks). MessageDisplay's `displayContent` can replace a streamed delta on screen, but it runs per streamed batch, before the whole reply and its digest exist, so it cannot judge the reply. The reply gate therefore runs at Stop, after the text was shown. The protocol (draft, panel, then emit the approved text) keeps an unreviewed reply off the screen; the gate makes skipping the protocol cost a rewrite turn, every time.

Reviewer subagents run in the background in this harness, so the main loop ends a turn while it waits for one. That waiting stop is a status line, not a reply, and the gate lets it through under a word cap; the reply that follows the reviewer's return is judged in full.

## Glossary

Every acceptance criterion names one of these components as its subject.

- **Reply_Gate**: `scripts/g__stop__reply-panel.py`, a new Stop hook.
- **Reply_Digest**: `panel_digest.digest(text, recipients=["operator"])` over the Stop payload's `last_assistant_message`.
- **Panel_Reviewer**: a reviewer subagent whose agent type matches `receipt_ledger.PANEL_AGENT_TYPE` (QA set plus `panel`; general-purpose, claude and fork do not match).
- **Receipt_Ledger**: `scripts/receipt_ledger.py`, read through `panel_pass_for`.
- **Prompt_Reader**: a reader of the session transcript that walks backwards from the newest entry, skipping task notifications, peer messages and hand-backs, compact summaries and `isMeta` entries (Stop-hook feedback, hook-injected text), and returns the text and timestamp of the newest entry whose `origin.kind` is `human` (or that has no origin and is none of the skipped kinds). It reuses the backward reader and origin helpers of `g__pretool-mcp__outward-send.py`; it does not copy them.
- **Operator_Prompt**: what the Prompt_Reader returns.
- **Skip_Token**: the literal word `panel-skip` inside the Operator_Prompt.
- **Pending_Panel**: an `Agent` tool use in the current turn, after the Operator_Prompt, whose `subagent_type` matches `PANEL_AGENT_TYPE` and whose `input.prompt` carries a panel block (`PANEL-TO: operator`, `PANEL-BODY-BEGIN` ... `PANEL-BODY-END`) that `panel_digest.recompute_from_report` accepts, and which has not completed. It completes when a task notification naming its tool use id arrives, or when its own `tool_result` arrives and that entry's `toolUseResult.isAsync` is not true (an entry with `isAsync: true` is the background-launch acknowledgment, not a completion). Each Pending_Panel exempts at most one stop chain: the Reply_Gate records the tool use id it spent in `~/.claude/.cache/receipts/reply-pending.jsonl`, and a spent id still exempts while `stop_hook_active` is true, because another Stop gate running in parallel may have blocked the same stop. A failed write to that file is an FR-04 error and exits 2.
- **Status_Cap**: 30 words, counted on whitespace-split `last_assistant_message`.
- **Off_Switch**: the environment variable `OCTO_REPLY_PANEL=off` in the shell that launched Claude Code, read from the hook's own environment. The main loop cannot set it: a Bash tool export does not reach hook processes.
- **Rule_Registry**: `registry/rules.yaml` with fixtures under `registry/fixtures/FLOW.panel-before-reply/`.
- **Rule_Text**: the "Nothing ships unverified" section of `CLAUDE.md`, paragraph anchor "Reply panel".
- **Doctor**: `scripts/brain_doctor.py`.
- **Architecture_Doc**: `docs/architecture/v11-reply-panel.md`.
- **Source_Class**: SELF or SOURCED, read from `last_assistant_message`. Every line starting with `Provenance:`, `Procedencia:` or `Herkunft:` (after optional leading blanks, `>` and `*`/`_` around the label) is a provenance line. The reply is SELF when it has no provenance line, when ANY provenance line has no `Basis` field, an empty Basis, or a Basis that is only (ignoring case, surrounding blanks and trailing punctuation) `none`, `nothing`, `n/a`, `na`, or any run of hyphens, en dashes or em dashes, or when ANY Basis contains, as a case-insensitive substring, `self`, `own reasoning`, `razonamiento propio`, `eigene Überlegung` or `eigene Ueberlegung`. Otherwise it is SOURCED. A Basis naming a path that contains `self` (for example `selftest.py`) is therefore SELF: the cost is two more reviewers, never a weaker check.
- **Panel_Quorum**: the number of distinct Panel_Reviewer agent ids that must each hold a PASS receipt for the Reply_Digest newer than the Operator_Prompt: 3 for a SELF reply, 1 for a SOURCED reply.

## User Stories

- As the operator, I want every reply to have been read by an independent reviewer before I act on it, so that a confident wrong claim is caught by the panel and not by me.
- As the operator, I want a reply that skipped the panel to be sent back automatically, so that I never have to ask for the review.
- As the operator, I want to waive the panel for one turn, or switch it off for a session, by my own action only, so that a trivial exchange or a broken gate never traps me.

## Functional Requirements

### FR-01: The reply digest

The Reply_Gate computes the Reply_Digest from `last_assistant_message`. Whitespace layout does not change it; one changed word does. Text written earlier in the turn, before a tool call, is not part of it (R-03).

### FR-02: The receipt that counts

A receipt counts when `panel_pass_for(Reply_Digest, session_id)` returns a PASS whose `verdict_ts` is strictly newer than the Operator_Prompt timestamp. A receipt from an earlier operator turn never covers this one. A receipt is not spent: it is bound to one exact text and one operator turn, and repeating the identical text in that turn is the same reply.

### FR-03: The gate decision

The Reply_Gate exits 0 when any of these holds, checked in this order:
1. the Off_Switch is set;
2. `last_assistant_message` is empty;
3. the Operator_Prompt carries the Skip_Token;
4. a Pending_Panel exists and `last_assistant_message` is at most the Status_Cap;
5. FR-02 finds a receipt.

Otherwise it exits 2 with a stderr message naming the Reply_Digest, the `panel_digest.py --panel-request --to operator` command and the accepted reviewer types. The stderr never names the Skip_Token, so the gate's own feedback cannot read as a waiver. It decides the same way when `stop_hook_active` is true: there is no block-once.

### FR-04: Fail-closed, with an exit only the operator holds

The Off_Switch is read before any import that can fail, so it recovers from an import error. When the Reply_Gate cannot decide (unreadable transcript, ledger or import error) it exits 2 with the error named. A missing receipts directory is not an error: it reads as no receipt. The recovery paths are the Skip_Token for one turn and the Off_Switch for a session, both operator actions. The gate is registered with a 20-second timeout; a timeout lets the stop through (R-07).

### FR-06: The panel scales with the source

Operator directive 2026-10-14: a reply whose basis is SELF is treated as a likely hallucination and needs a panel of three; a reply that names a source needs one reviewer. FR-02 counts a receipt only when the deciding receipt for the Reply_Digest says PASS and the Panel_Quorum is met. A footer that names a source is still model-written, so the single reviewer of a SOURCED reply is the check on that source (R-13).

### FR-05: Wiring

The rule `FLOW.panel-before-reply` is registered in the Rule_Registry with strength GATE, enforcement fail-closed, firing_mode hook, source anchor "Reply panel", a `--selftest` proof over its fixtures and `liveness_required: FIRES`. The Reply_Gate is registered on Stop in `hooks.json`. Stop hooks run in parallel and no gate may assume array order (`docs/architecture/hook-orchestration.md`), so the position in the array carries no meaning. The Rule_Text gains the "Reply panel" paragraph. `docs/architecture/v11-reply-panel.md` states the contract and every residual.

## Acceptance Criteria

- [ ] AC-01: THE Reply_Gate SHALL compute the same Reply_Digest for two replies that differ only in whitespace layout, and a different one when one word differs.
- [ ] AC-02: WHEN a PASS panel receipt for the exact Reply_Digest, newer than the Operator_Prompt, exists in the session, THE Reply_Gate SHALL exit 0, including when the newest transcript entry is Stop-hook feedback.
- [ ] AC-03: IF no PASS panel receipt for the exact Reply_Digest exists in the session, THEN THE Reply_Gate SHALL exit 2 and print the digest, the panel-request command and the accepted reviewer types, and SHALL NOT print the Skip_Token.
- [ ] AC-04: IF the only PASS receipt for the Reply_Digest is older than the Operator_Prompt, THEN THE Reply_Gate SHALL exit 2.
- [ ] AC-05: IF a NEEDS-WORK receipt for the Reply_Digest is newer than its PASS, THEN THE Reply_Gate SHALL exit 2.
- [ ] AC-06: IF the reply text changed after the panel, THEN THE Reply_Gate SHALL exit 2.
- [ ] AC-07: WHEN the Operator_Prompt carries the Skip_Token, THE Reply_Gate SHALL exit 0, also after another Stop gate's feedback was appended, and IF the Skip_Token appears only in assistant text, a tool result or an `isMeta` entry, THEN THE Reply_Gate SHALL exit 2.
- [ ] AC-08: WHILE `stop_hook_active` is true, THE Reply_Gate SHALL apply the same decision as on a first stop.
- [ ] AC-09: IF the Reply_Gate cannot read the transcript or raises on the Receipt_Ledger, THEN THE Reply_Gate SHALL exit 2 and name the error, and WHEN the receipts directory is missing, THE Reply_Gate SHALL treat it as no receipt.
- [ ] AC-10: WHEN the Off_Switch is set or `last_assistant_message` is empty, THE Reply_Gate SHALL exit 0, and THE Reply_Gate SHALL ignore `CLAUDE_CODE_CHILD_SESSION`.
- [ ] AC-11: WHEN an unspent Pending_Panel exists and `last_assistant_message` is at most the Status_Cap, THE Reply_Gate SHALL exit 0 and record the Pending_Panel as spent, and IF the reply exceeds the Status_Cap, the agent is not a Panel_Reviewer, its prompt carries no valid panel block, it already completed (by notification or by a non-acknowledgment tool_result) or it was already spent, THEN THE Reply_Gate SHALL exit 2.
- [ ] AC-12: WHEN the turn was opened by a task notification or a hand-back, THE Prompt_Reader SHALL return the newest human prompt behind it.
- [ ] AC-13: THE Rule_Registry SHALL hold `FLOW.panel-before-reply` with a `--selftest` proof that passes over fixtures covering AC-02 to AC-12, run with `CLAUDE_CODE_CHILD_SESSION=1` and the Off_Switch scrubbed, on a fixture clock so the cases do not age out.
- [ ] AC-14: THE Doctor SHALL report the rule wired only when the Reply_Gate is registered on Stop, its selftest passes and the Rule_Text holds the "Reply panel" anchor.
- [ ] AC-16: IF any arm settings file listed in the operator's arm paths sets `OCTO_REPLY_PANEL` in its `env` block, THEN THE Doctor SHALL report it as a warning naming the file; directories outside the arm paths are not scanned (R-10).
- [ ] AC-17: THE Reply_Gate SHALL exit 2 with the missing name when a helper it loads from the send gate is absent, and its selftest SHALL fail in that case.
- [ ] AC-18: WHEN the reply is SELF and fewer than 3 distinct Panel_Reviewer agent ids hold a PASS receipt for the Reply_Digest newer than the Operator_Prompt, THE Reply_Gate SHALL exit 2 and print the Source_Class and the quorum count.
- [ ] AC-19: WHEN the reply is SELF and 3 distinct Panel_Reviewer agent ids hold such PASS receipts and the deciding receipt is PASS, THE Reply_Gate SHALL exit 0.
- [ ] AC-20: WHEN the reply is SOURCED and one PASS receipt meets FR-02, THE Reply_Gate SHALL exit 0.
- [ ] AC-21: IF the reply has no provenance line or no Basis field, THEN THE Reply_Gate SHALL classify it as SELF.
- [ ] AC-15: THE Architecture_Doc SHALL list residuals R-01 to R-13 with their source.

## Residuals

- R-01: No pre-display gate exists. A reply that skipped the protocol is shown, then sent back for a reviewed rewrite.
- R-02: The harness overrides a Stop block after 8 consecutive continuations (`CLAUDE_CODE_STOP_HOOK_BLOCK_CAP`, reset by any tool call, shared by every Stop hook). When hit, the unreviewed reply stands. Raising the cap is a settings change for the operator.
- R-03: Text written before a tool call is outside `last_assistant_message` and is not covered. Hashing the whole turn from the transcript was rejected: the docs say the transcript "may lag".
- R-04: Other Stop gates can force a rewrite, which changes the digest and needs a new panel. Stop hooks run in parallel, so there is no ordering mitigation.
- R-05: The reviewer is independent in context, not in model.
- R-06: Cost and latency: one or more subagents per reply. Measured in review.md, not before.
- R-07: A gate that exceeds its 20-second timeout lets the stop through.
- R-08: A reply that itself contains a `PANEL-BODY-END` line cannot be matched by any receipt (the block parser stops there). The Skip_Token is the way through.
- R-09: A status line under the Status_Cap while a Pending_Panel runs is unreviewed by design.
- R-10: Any `.claude/settings*.json` outside the live root (an arm's, or one the main loop writes in another directory) can set the Off_Switch for later sessions launched there; the arming surface does not see those scopes. The Doctor warns (AC-16); it does not block. Same residual as `OCTO_MERGE_APPROVE`.
- R-11: Every throwaway panel request with a dummy body buys one stop chain of at most 30 unreviewed words, repeatable every turn. Each costs a reviewer run and is visible in the transcript. A spent id also re-exempts a second status stop inside the same operator turn while `stop_hook_active` is true.
- R-12: Unattended top-level `claude -p` runs pay up to 8 continuations per reply unless launched with the Off_Switch.
- R-13: The Source_Class is read from a footer the main loop writes. A reply can name a source it never opened and drop to a quorum of one; that one reviewer is the check on the source. Three PASS receipts from three runs of the same model are independent in context only (R-05).
