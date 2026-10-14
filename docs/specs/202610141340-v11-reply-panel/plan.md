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
- [x] T09 [AC-14, AC-15] CLAUDE.md, docs/architecture/v11-reply-panel.md: the "Reply panel" paragraph naming the rule, the gate, the Skip_Token, the Off_Switch and R-01; the architecture doc with the contract and residuals R-01 to R-12.
- [x] T10 [AC-13, AC-14] docs/specs/202610141340-v11-reply-panel/review.md: run the selftest, `brain_doctor --fast` and `spec_lint.py`, and record each output and one measured panel latency.
