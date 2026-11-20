# Plan: Quiet Provenance

> **Status:** draft
> **Spec-Format:** ears-1
> **Feature:** feature.md

Worktree `~/.octorato/wt/quiet-provenance`; the live `~/.claude` copy is never edited (arming surface).

## Tasks

- [ ] T01 [AC-01, AC-02, AC-19, AC-20, AC-22] scripts/provenance_ledger.py: `record` / `show` CLI, `fresh_all`, `effective_ts`, `reply_anchor` (stop = end_turn or a follower with no tool_result), `reply_view` on the reply panel's own functions, `--selftest`.
- [ ] T02 [AC-07, AC-08, AC-09, AC-10, AC-11, AC-18, AC-19] scripts/g__stop__reply-panel.py: `source_class(text, entries)`, `ledger_entries`, `bound_reply_text` for the digest, fixture key `provenance`.
- [ ] T03 [AC-07, AC-08, AC-09, AC-10, AC-11, AC-18, AC-19, AC-20, AC-22, AC-23] registry/fixtures/FLOW.panel-before-reply: `*_qp_*` legs incl. SELF-then-SOURCED, recorded-after-PASS, consumed-by-earlier-reply (notification follower), status-line, narration with a tool call, SELF-narration-SOURCED, future entry.
- [ ] T04 [AC-03, AC-04, AC-05, AC-06, AC-16] scripts/source-attribution-check.py: ledger fallback after the marker check, block text names the CLI and keeps `no provenance footer`.
- [ ] T05 [AC-03, AC-04, AC-05, AC-06, AC-19, AC-20] registry/fixtures/CODE.cite-sources: `home/.claude/.cache/provenance/provenance.jsonl` seed plus fresh, stale, empty-basis, no-entry, other-session, consumed, status-line and future legs.
- [ ] T06 [AC-12, AC-17, AC-21] scripts/panel_preflight.py, scripts/panel_digest.py: `OCTO_PROVENANCE_SESSION` for children, Fresh_Entries into `source_class`, FAIL line on a ledger error, Bound_Text in the reviewed block and digest.
- [ ] T07 [AC-13] scripts/4d-reminder.py: record, do not print; footer only on request.
- [ ] T08 [AC-14] CLAUDE.md, skills/4d-paradigm-protocol/SKILL.md: recorded always, hidden by default, shown on request.
- [ ] T09 [AC-15] scripts/g__pretool__arming-surface.py, docs/CAPABILITIES.md, registry/fixtures/ARCHITECTURE.arming-surface, connectome/lineage.yaml: closure entry, fixture pair, lineage edge, regenerated manifest.
- [ ] T10 [AC-01, AC-02, AC-07, AC-08, AC-12, AC-13, AC-17, AC-18, AC-20, AC-21, AC-22] scripts/tests/test_quiet_provenance.py: CLI, classifier, bound text, panel request, preflight FAIL, reply_anchor, future cap, after-PASS and reminder tests.
