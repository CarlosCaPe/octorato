# Plan: v11, No Reply Unreviewed

> **Status:** draft
> **Spec-Format:** ears-1
> **Feature:** feature.md

The worktree is `~/.octorato/wt/v11-reply-panel`; the live `~/.claude` copy is never edited (arming surface). T01 first, then T02 to T04, then T05 to T09, T10 last.

## Tasks

- [x] T01 [AC-07, AC-12] scripts/g__stop__reply-panel.py: the Prompt_Reader, built on the backward reader and origin helpers of `g__pretool-mcp__outward-send.py` loaded by file name (no copy), walking back over notifications, peer entries, compact summaries and `isMeta` entries.
- [x] T02 [AC-17, AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-08, AC-09, AC-10] scripts/g__stop__reply-panel.py: read the Stop payload, compute the Reply_Digest with `panel_digest.digest`, decide per FR-02 to FR-04 with `receipt_ledger.panel_pass_for`, exit 0 or 2 with the stderr of AC-03.
- [x] T03 [AC-11] scripts/g__stop__reply-panel.py: Pending_Panel detection from the turn's `Agent` tool uses (panel block in `input.prompt`, completion by notification tool-use id or non-acknowledgment tool_result), the 30-word Status_Cap and the spent ledger.
- [x] T04 [AC-13] scripts/g__stop__reply-panel.py, scripts/panel_fixture_seed.py: `--selftest <fixture_dir>` that scrubs `CLAUDE_CODE_CHILD_SESSION` and the Off_Switch, pins the clock to the fixture (as `_now_for` does in the send gate) and seeds receipts with `seed_receipt`; add to panel_fixture_seed.py only what a Stop case needs.
- [x] T05 [AC-13] registry/fixtures/FLOW.panel-before-reply/: one case per AC-02 to AC-12, each with its expected exit code, including Stop-feedback-last, notification-opened and isMeta-skip-token cases.
- [x] T06 [AC-13] registry/rules.yaml: the `FLOW.panel-before-reply` entry with source anchor "Reply panel", modelled on `FLOW.panel-before-send`.
- [x] T07 [AC-14] hooks.json: register the Reply_Gate on Stop with timeout 20.
- [x] T08 [AC-14, AC-16] scripts/brain_doctor.py: confirm the generic registry wiring and anchor reconciliation cover the rule, add a check only if they do not, and warn on an arm settings file that sets `OCTO_REPLY_PANEL`.
- [x] T09 [AC-14, AC-15] CLAUDE.md, docs/architecture/v11-reply-panel.md: the "Reply panel" paragraph naming the rule, the gate, the Skip_Token, the Off_Switch and R-01; the architecture doc with the contract and residuals R-01 to R-13.
- [x] T10 [AC-13, AC-14] docs/specs/202610141340-v11-reply-panel/review.md: run the selftest, `brain_doctor --fast` and `spec_lint.py`, and record each output and one measured panel latency.
- [x] T14 [AC-18, AC-19, AC-20, AC-21] scripts/g__stop__reply-panel.py, scripts/receipt_ledger.py: read the Source_Class from `last_assistant_message`, and count distinct PASS reviewers through a new `receipt_ledger` reader built from the same validation `panel_latest_for` applies (refactor, no copy; `panel_pass_for` and the send gate keep their behaviour).
- [x] T15 [AC-18, AC-19, AC-20, AC-21] registry/fixtures/FLOW.panel-before-reply/: SELF with 1 and 2 reviewers (exit 2), SELF with 3 (exit 0), SELF with 3 where the deciding receipt is NEEDS-WORK (exit 2), SOURCED with 1 (exit 0), footer missing and Basis missing (classified SELF).
- [x] T16 [AC-15] docs/architecture/v11-reply-panel.md, CLAUDE.md: the quorum rule and residual R-13; keep CLAUDE.md under its token ceiling.

## Convergence 1

- [x] T11 [AC-07] registry/fixtures/FLOW.panel-before-reply/: add a violation case whose `last_assistant_message` itself carries `panel-skip` while the operator prompt does not; a mutation that also searches the reply for the Skip_Token passes the current selftest (only an earlier assistant entry carries it today).
- [x] T12 [AC-09] scripts/g__stop__reply-panel.py: make the selftest pin the "raises on the Receipt_Ledger" path (for example a unit check with `panel_pass_for` raising) so the exit is 2 and stderr names the exception; replacing the `receipt ledger raised` GateError with `return False` passes the current selftest, because `violation_ac09_ledger_unreadable` only reaches the pre-check.
- [x] T13 [AC-16] scripts/brain_doctor.py: pin `check_reply_panel_arm_env` with a repeatable test (listed arm sets the switch: WARN naming the file; unlisted directory that sets it: not reported); today only the one-off run recorded in review.md shows it.

## Convergence 2

- [x] T17 [AC-18] registry/fixtures/FLOW.panel-before-reply/: add SELF violation cases where three distinct reviewers hold receipts and the deciding one is a fresh PASS, but one of the three is a PASS older than the Operator_Prompt, and another where one of the three is an older NEEDS-WORK; each must exit 2 with "it has 2 of 3". Dropping `newer(r)` or the `verdict == "PASS"` filter from the count in `pass_reviewers` passes the current selftest.
- [x] T18 [AC-18, AC-21] scripts/g__stop__reply-panel.py: make `source_class` match the Source_Class glossary, which makes a Basis that "contains" SELF a SELF reply (case-insensitive). The word-bounded `_SELF_BASIS` classifies `Basis: myself`, `Basis: self-evident` and `Basis: selfcheck` as SOURCED (quorum 1). Either match the substring or have /sdd-refine narrow the glossary to a whole word first, then pin the chosen reading with a fixture; swapping the regex to a plain substring passes the current selftest.
- [x] T19 [AC-18, AC-21] scripts/g__stop__reply-panel.py, registry/fixtures/FLOW.panel-before-reply/: apply the refined Source_Class (substring `self`, any SELF line wins over a later SOURCED one, `none`/`n/a`/`-` Basis is SELF) with fixtures for `Basis: myself`, two provenance lines with SOURCED last, and `Basis: none`.
- [x] T20 [AC-05] scripts/receipt_ledger.py: in panel_receipts_for, treat a candidate whose `_anchor_stands` raises as not standing, so a malformed older reviewer transcript cannot raise out of panel_latest_for for the send gate or the sent ledger; add a test for it.
