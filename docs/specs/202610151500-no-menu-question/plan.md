# Plan: No Menu Questions

> **Status:** draft
> **Spec-Format:** ears-1
> **Feature:** feature.md

Worktree `~/.octorato/wt/no-menu-question`; the live `~/.claude` copy is never edited (arming surface).

## Tasks

- [x] T01 [AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07] scripts/g__stop__no-menu-question.py: the Stop gate, modelled on g__stop__defer-today.py (transcript tail reader, prose stripping, block once, fail open, kernel journal mirror, `--selftest`).
- [x] T02 [AC-08] registry/no-menu-question.yaml, scripts/g__stop__no-menu-question.py: the two-level YAML config with `openers` and `irreducible`, and the loader that keeps built-in defaults per key.
- [x] T03 [AC-09] registry/fixtures/COMMS.no-menu-question/: violation and benign twins for the Spanish, English, opener, quoted, code-block, blockquote and irreducible cases, plus the hatch, the second pass and the information question.
- [x] T04 [AC-09, AC-10] registry/rules.yaml, hooks.json, CLAUDE.md, registry/friction-signatures.json: the rule entry, the Stop registration, the "No menu questions" paragraph and the friction signature.
- [x] T05 [AC-10] docs/architecture/v7-nothing-ships-unverified.md, connectome/lineage.yaml, CHANGELOG.md: full text under "The draft gates in full", the lineage node and the changelog line.
- [x] T06 [AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10] scripts/tests/test_no_menu_question.py: matcher, config, process and wiring tests.
