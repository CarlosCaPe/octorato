# Plan: Diagram-First Replies

> **Status:** draft
> **Spec-Format:** ears-1
> **Feature:** feature.md

Worktree `~/.octorato/wt/diagram-first`; the live `~/.claude` copy is never edited (arming surface). The gate is modelled on `scripts/g__stop__paste-ready-raw.py` (transcript tail reader, last operator prompt, fence parser) and `scripts/g__stop__no-menu-question.py` (prose stripping, footer and Disclose markers).

## Tasks

- [ ] T01 [AC-10] registry/fixtures/COMMS.diagram-first/: violation and benign twins for flow, numbered, before/after, Spanish, status, structure and late-diagram, plus the benign short, paste-ready, input-needed, status-line, hatch, code, blockquote and plain-prose fixtures.
- [ ] T02 [AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-13] scripts/g__stop__diagram-first.py: the Stop gate (prose stripping, word floor, the four shapes, opening-diagram check, paste-ask and input-needed exemptions, hatch, block once, fail open, kernel journal mirror, `--selftest`).
- [ ] T03 [AC-10, AC-11, AC-13, AC-14] registry/rules.yaml, hooks.json, registry/friction-signatures.json: the rule entry mirroring COMMS.no-menu-question, the Stop registration next to its siblings, and the `DIAGRAM-FIRST` signature.
- [ ] T04 [AC-11] CLAUDE.md: the "Diagram-first" paragraph in the Communication section; to stay under the 12,000-token ceiling (11,954 before), cut the Do-it-today sentence that restates the do-it-right reconciliation (about 33 tokens, the reconciliation stays in the do-it-right bullet) and re-measure with `brain_doctor.py --fast` (claude-md-budget).
- [ ] T05 [AC-12] skills/human-cadence/SKILL.md: the HOW section with grammar, scope, exemptions, hatch and one example.
- [ ] T06 [AC-11, AC-15] connectome/lineage.yaml, CHANGELOG.md, docs/CAPABILITIES.md: the lineage node, the Unreleased changelog line and the regenerated capability manifest.
- [ ] T07 [AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-13, AC-14, AC-15] scripts/tests/test_diagram_first.py: matcher, process and wiring tests.

## Convergence 1

- [ ] T08 [AC-01] scripts/g__stop__diagram-first.py: `_flow` resets the numbered run on any non-blank non-numbered line, so three numbered steps each followed by an indented sub-bullet (`1. a / - x / 2. b / - y / 3. c`, 90 words of prose) pass unblocked although they are three consecutive items of one numbered list; keep the run across lines indented deeper than the numbered item and pin the case with a violation fixture and a test in scripts/tests/test_diagram_first.py.
