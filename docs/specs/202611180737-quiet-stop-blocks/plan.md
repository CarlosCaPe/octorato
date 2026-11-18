# Plan: Quiet Stop Blocks

> **Status:** draft
> **Spec-Format:** ears-1
> **Feature:** feature.md

Worktree `~/.octorato/wt/gates-quiet-block`; the live `~/.claude` copy is never edited (arming surface).

## Tasks

- [ ] T01 [AC-01, AC-02, AC-03, AC-06] scripts/stop_block.py: `shown()` writes the Detail_File and `blocks.jsonl`, reads back, returns the Shown_Line or the Full_Reason; `--selftest`.
- [ ] T02 [AC-01, AC-02, AC-03, AC-04, AC-08] scripts/cadence-stop-hook.py, scripts/g__stop__draft-promise.py, scripts/g__stop__unsourced-attribute.py, scripts/g__stop__unsourced-absence.py, scripts/g__stop__paste-ready-raw.py, scripts/g__stop__defer-today.py, scripts/g__stop__no-menu-question.py: print the reason through a guarded `_quiet()` helper.
- [ ] T03 [AC-01, AC-02, AC-03, AC-04, AC-08] scripts/g__stop__diagram-first.py, scripts/source-attribution-check.py, scripts/claim-verify-stop.py, scripts/g__stop__delegation-audit.py, scripts/d__stop__wa-guardia.py, scripts/g__stop__goal-anchor.py: same helper, short line with the measured fact.
- [ ] T04 [AC-01, AC-02, AC-03, AC-04, AC-05] scripts/g__stop__reply-panel.py: `_short()` and `_quiet()` on the exit-2 stderr; the selftest checks one line and runs `stderr_has` / `stderr_lacks` on the Detail_File.
- [ ] T05 [AC-01, AC-02, AC-03, AC-05, AC-07] scripts/tests/test_stop_block.py: every JSON gate on its violation fixtures, with and without a broken ledger; reply-panel fallback and short line; hooks.json coverage.
- [ ] T06 [AC-01, AC-02] scripts/tests/test_no_menu_question.py, scripts/tests/test_diagram_first.py: point the ledger at a temp dir and assert hatch text on the Detail_File.
- [ ] T07 [AC-01] docs/architecture/hook-orchestration.md: section "Stop block reasons: one line on screen, full text for the model".
- [ ] T08 [AC-01, AC-02] scripts/tests/test_goal_anchor_receipt.py, scripts/tests/test_hook_stdin_utf8.py, scripts/tests/test_panel_preflight.py: normalise the per-run HOME in the compared decision, read the digest from the Detail_File, keep preflight blocks out of the live ledger.
- [ ] T09 [AC-03] scripts/g__pretool__arming-surface.py, docs/CAPABILITIES.md: put `stop_block.py` in the arming-surface closure of run-time gate imports; regenerate the capability manifest.
