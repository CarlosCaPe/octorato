# v11 reply panel

Spec: `docs/specs/202610141340-v11-reply-panel/` (FR-01 to FR-05, AC-01 to AC-17). This page is the source the registry row `FLOW.panel-before-reply` points at from its CLAUDE.md anchor "Reply panel".

v7 made an unverified send to a third party impossible: no message leaves without a PASS panel receipt for its exact digest (`FLOW.panel-before-send`). v11 moves that floor to the operator. Every reply the main loop gives him carries a PASS panel receipt for its exact text, recorded by a hook from an independent reviewer, or the turn is sent back.

## Why Stop, and not before display

Claude Code has no hook that can stop text before it is displayed: "MessageDisplay hooks have no decision control. They can't block the message" (code.claude.com/docs/en/hooks). MessageDisplay can replace a streamed delta on screen, but it runs per streamed batch, before the whole reply and its digest exist. So the gate runs at Stop, after the reply was shown. The protocol keeps an unreviewed reply off the screen: draft the reply, have a reviewer read it, then emit exactly the reviewed text. The gate makes skipping the protocol cost a rewrite turn, every time.

## The protocol

1. Write the reply to a file and run `python3 ~/.claude/scripts/panel_digest.py --panel-request --to operator --body-file <file>`. It prints the reviewer block (`PANEL-TO: operator`, `PANEL-BODY-BEGIN` ... `PANEL-BODY-END`, `PANEL-SHA256`).
2. Launch a reviewer subagent with that block. Its agent type must match `receipt_ledger.PANEL_AGENT_TYPE` (`qa|review|reality|evidence|checker|verif|audit|panel`: Reality Checker, Code Reviewer, Evidence Collector). general-purpose, claude and fork do not match. The reviewer repeats the block and ends with `PANEL-VERDICT: PASS | NEEDS-WORK` and `PANEL-SHA256`.
3. `r__subagent-stop__qa-receipt.py` records a `panel` receipt only when the reviewer's own report carries the block and it recomputes to the stated digest. No new receipt machinery: a recipient is free text in `PANEL-TO`.
4. Emit exactly the reviewed text as the final reply.

Reviewers run in the background in this harness, so the main loop can end a turn while it waits. That waiting stop is a status line of at most 30 words, and the gate lets it through once per pending reviewer.

## The gate

`scripts/g__stop__reply-panel.py`, on Stop, timeout 20 seconds. It reads the Stop payload (`last_assistant_message`, `stop_hook_active`, `transcript_path`, `session_id`). The digest is `panel_digest.digest(last_assistant_message, recipients=["operator"])`: whitespace layout does not change it, one changed word does.

It exits 0 when the first of these holds, in this order:

| # | Condition |
|---|---|
| 1 | `OCTO_REPLY_PANEL=off` in the hook's own environment. Read before any import that can fail. |
| 2 | `last_assistant_message` is an empty or whitespace string. An absent key is not empty: the gate cannot decide and exits 2 ("payload has no last_assistant_message"). |
| 3 | The operator's own prompt for the turn carries the word `panel-skip`. |
| 4 | A pending panel reviewer exists and the reply is at most 30 whitespace-split words. |
| 5 | `receipt_ledger.panel_pass_for(digest, session)` returns a PASS whose `verdict_ts` is strictly newer than the operator's prompt. |

Otherwise it exits 2. Its stderr names the digest, the panel-request command and the accepted reviewer types, and never the skip word, so its own feedback cannot read as a waiver. `stop_hook_active` changes nothing: there is no block-once.

**The operator's prompt.** The gate walks the transcript backwards with the send gate's `_prompt_entries_reversed`, `_origin`, `_is_operator_opener` and `_entry_text`, loaded by file name. It passes over tool results, task notifications, peer messages and hand-backs, compact summaries, sidechain entries and every `isMeta` entry (Stop-hook feedback lands as a user entry with `isMeta: true`). The first entry whose `origin.kind` is `human`, or that has no origin, is the prompt; if that entry is not harness-written (`_is_operator_opener` fails), there is no prompt and the gate exits 2. An entry with any other origin kind also ends the walk with no prompt, as the send gate's `turn_read` does. A helper missing from the send gate is an error that names it.

**A receipt is not spent.** It is bound to one exact text and one operator turn. A receipt from an earlier turn never covers this one, and a NEEDS-WORK newer than the PASS revokes it (the ledger's own rule). Repeating the identical text in the same turn is the same reply.

**Pending reviewer.** An `Agent` call in this turn, after the operator's prompt, whose `subagent_type` matches `PANEL_AGENT_TYPE` and whose `input.prompt` holds a block that `panel_digest.recompute_from_report` accepts with `operator` as its only recipient. It completes when a user entry carries `<tool-use-id>` with its id (a task notification) or when its own `tool_result` arrives with `toolUseResult.isAsync` not true; the `isAsync: true` result is the background-launch acknowledgment. Each pending reviewer exempts one stop chain: the gate appends its id to `~/.claude/.cache/receipts/reply-pending.jsonl`, and a recorded id still exempts while `stop_hook_active` is true, because another Stop gate running in parallel may have blocked the same stop.

**Fail-closed.** An unparseable payload, a payload without `last_assistant_message`, no operator prompt, an unreadable transcript, an import error, a missing helper, a receipt ledger that is not a readable file, an unreadable or unwritable `reply-pending.jsonl`, or an exception from the ledger exits 2 with the error named. A missing receipts directory is no receipt, not an error. The way out is the operator's: `panel-skip` for one turn, `OCTO_REPLY_PANEL=off` in the launching shell for the session. The main loop cannot set the second one: a Bash export does not reach hook processes. The harness sets `CLAUDE_CODE_CHILD_SESSION=1` in hook commands; the gate ignores it.

## Proof

`python3 scripts/g__stop__reply-panel.py --selftest registry/fixtures/FLOW.panel-before-reply`. Each `violation_*.json` must exit exactly 2, each `benign_*.json` exactly 0, every case in its own sandbox HOME. A case's optional `_fixture` key (stripped before the gate sees the payload) seeds receipts through `panel_fixture_seed.seed_reply_receipt`, pre-records spent ids, breaks the ledger, sets env, and asserts on stderr and on the spent ledger. The run scrubs `OCTO_REPLY_PANEL`, sets `CLAUDE_CODE_CHILD_SESSION=1`, and pins the clock to the newest transcript entry under `CLAUDE_SESSION_ID=__selftest__`, so the 120-minute window never ages the fixtures out. Two unit checks run first: the digest (AC-01) and a copy of the gate whose send gate lacks `_origin` (AC-17), which must exit 2 naming it. Every blocked case must also be journaled under `FLOW.panel-before-reply`.

`brain_doctor` covers the rule through its generic checks: `registry-wiring` (the gate in `hooks.json` at Stop), `registry-anchors` (the "Reply panel" anchor in CLAUDE.md) and `gate-liveness` (the selftest). `reply-panel-arm-env` warns when an arm settings file sets the off switch (R-10).

## Residuals

| Id | Residual | Source |
|---|---|---|
| R-01 | No pre-display gate exists. A reply that skipped the protocol is shown, then sent back for a reviewed rewrite. | code.claude.com/docs/en/hooks, quoted in feature.md Summary |
| R-02 | The harness overrides a Stop block after 8 consecutive continuations (`CLAUDE_CODE_STOP_HOOK_BLOCK_CAP`, reset by any tool call, shared by every Stop hook). When hit, the unreviewed reply stands. Raising the cap is a settings change for the operator. | spec analysis 2026-10-14, feature.md R-02 |
| R-03 | Text written before a tool call is outside `last_assistant_message` and is not covered. Hashing the whole turn from the transcript was rejected: the docs say the transcript "may lag". | code.claude.com/docs/en/hooks, quoted in feature.md R-03 |
| R-04 | Other Stop gates can force a rewrite, which changes the digest and needs a new panel. Stop hooks run in parallel, so no ordering mitigates it. | docs/architecture/hook-orchestration.md section 5, rule 4 (hooks on one event run in parallel) |
| R-05 | The reviewer is independent in context, not in model. | feature.md R-05 |
| R-06 | Cost and latency: one or more subagents per reply. Measured in review.md, not before. | docs/specs/202610141340-v11-reply-panel/review.md |
| R-07 | A gate that exceeds its 20-second timeout lets the stop through. | hooks.json (timeout 20), feature.md FR-04 |
| R-08 | A reply that itself contains a `PANEL-BODY-END` line cannot be matched by any receipt (the block parser stops there). `panel-skip` is the way through. | scripts/panel_digest.py `_BLOCK` |
| R-09 | A status line under 30 words while a reviewer runs is unreviewed by design. | feature.md FR-03 step 4 |
| R-10 | Any `.claude/settings*.json` outside the live root (an arm's, or one the main loop writes in another directory) can set the off switch for later sessions launched there; the arming surface does not see those scopes. The doctor warns for the arm paths in arms-paths.json; it does not block. Same residual as `OCTO_MERGE_APPROVE`. | docs/architecture/v8-arming-surface.md, brain_doctor `reply-panel-arm-env` |
| R-11 | Every throwaway panel request with a dummy body buys one stop chain of at most 30 unreviewed words, repeatable every turn. Each costs a reviewer run and is visible in the transcript. A spent id also re-exempts a second status stop inside the same operator turn while `stop_hook_active` is true. | feature.md R-11 |
| R-12 | Unattended top-level `claude -p` runs pay up to 8 continuations per reply unless launched with the off switch. | feature.md R-12 (follows from R-02) |
