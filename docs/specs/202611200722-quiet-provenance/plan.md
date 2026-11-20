# Plan: Quiet Provenance

> **Status:** draft
> **Spec-Format:** ears-1
> **Feature:** feature.md

Worktree `~/.octorato/wt/quiet-provenance`; the live `~/.claude` copy is never edited (arming surface).

## Tasks

- [ ] T01 [AC-01, AC-02] scripts/provenance_ledger.py: `record` / `show` CLI, `fresh` and `prompt_ts` library on the reply panel's prompt walk, `--selftest`.
- [ ] T02 [AC-07, AC-08, AC-09, AC-10, AC-11] scripts/g__stop__reply-panel.py: `source_class(text, entry)`, `ledger_basis_is_self`, `fresh_provenance` in `decide`, fixture key `provenance`.
- [ ] T03 [AC-07, AC-08, AC-09, AC-10] registry/fixtures/FLOW.panel-before-reply: `benign_qp_*` and `violation_qp_*` legs for fresh, stale, equal, other-session, empty, self and footer-vs-ledger cases.
- [ ] T04 [AC-03, AC-04, AC-05, AC-06, AC-16] scripts/source-attribution-check.py: ledger fallback after the marker check, block text names the CLI and keeps `no provenance footer`.
- [ ] T05 [AC-03, AC-04, AC-05, AC-06] registry/fixtures/CODE.cite-sources: `home/.claude/.cache/provenance/provenance.jsonl` seed plus fresh, stale, empty-basis, no-entry and other-session legs.
- [ ] T06 [AC-12] scripts/panel_preflight.py: `OCTO_PROVENANCE_SESSION` for children, Fresh_Entry into `source_class`.
- [ ] T07 [AC-13] scripts/4d-reminder.py: record, do not print; footer only on request.
- [ ] T08 [AC-14] CLAUDE.md, skills/4d-paradigm-protocol/SKILL.md: recorded always, hidden by default, shown on request.
- [ ] T09 [AC-15] scripts/g__pretool__arming-surface.py, docs/CAPABILITIES.md: add `provenance_ledger.py` to the closure; regenerate the capability manifest.
- [ ] T10 [AC-01, AC-02, AC-07, AC-08, AC-12, AC-13] scripts/tests/test_quiet_provenance.py: CLI, classifier, preflight and reminder tests.
