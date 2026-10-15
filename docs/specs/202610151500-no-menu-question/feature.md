# Feature: No Menu Questions

> **Status:** draft
> **Spec-Format:** ears-1
> **Date:** 2026-10-15
> **Classification:** LARGE (score 8: 10+ files, new feature, multiple modules)

Operator directive 2026-10-15, verbatim: "cada que termines en pregunta de opción múltiple, quiero que apliques choice, siempre, hasta que me llegues ya con una sugerencia, 0% de preguntas de opción múltiple". A reply that closes on "¿Dale a X o Y?" or "Shall I proceed?" hands back a decision the agent could make with `/choice` and execute. This feature wires that directive as a Stop gate, in the same class as `g__stop__defer-today.py` and `g__stop__draft-promise.py`.

## Summary

The gate reads the last assistant reply, discards the Provenance footer, the Disclose one-liners, fenced and inline code, blockquotes and quoted spans, and takes the closing sentence. When that sentence ends in `?` and either offers alternatives or opens with a go-ahead or preference ask, the gate blocks once and tells the model to run `/choice` and return the decision. A question naming an irreducible operator step (money, consent, an outward send, a merge approval, a version cut, a login) passes. Openers and irreducible steps are config in `registry/no-menu-question.yaml`.

## Glossary

- **Menu_Gate**: `scripts/g__stop__no-menu-question.py`, a Stop hook.
- **Closing_Sentence**: the last sentence of the reply's prose after the Menu_Gate discards the Provenance footer, lines starting with the Disclose markers (`💡 Unlock-suggestion`, `☠ Prune-suggestion`), fenced and inline code, lines starting with `>`, lines carrying the Hatch, and spans inside double, curly or guillemet quotes.
- **Choice_Question**: a Closing_Sentence that ends in `?` and either contains a whole-word `o`, `u` or `or` between alternatives, or opens (after an optional `¿`) with an entry of the `openers` list.
- **Irreducible_Step**: an entry of the `irreducible` list, matched case- and accent-folded as a substring of the Closing_Sentence.
- **Config**: `registry/no-menu-question.yaml`, a two-level YAML subset (`key:` then `  - item`) with the keys `openers` and `irreducible`, parsed by the Menu_Gate itself.
- **Hatch**: the literal `menu-ok` on a line of the reply.
- **Rule_Registry**: `registry/rules.yaml` with fixtures under `registry/fixtures/COMMS.no-menu-question/`.
- **Rule_Text**: the `CLAUDE.md` paragraph with anchor "No menu questions".
- **Doctor**: `scripts/brain_doctor.py`.

## Functional Requirements

### FR-01: What fires

The Menu_Gate blocks when the Closing_Sentence is a Choice_Question and names no Irreducible_Step. The block reason names `/choice`, the irreducible-step exception and the Hatch, and carries the signature `SIN-MENÚ` for the friction ledger.

### FR-02: What does not fire

A quoted question, a question inside a code block or a blockquote, a question followed by a decision, an information question without alternatives or an opener, a question naming an Irreducible_Step, a line carrying the Hatch, and an empty reply all pass.

### FR-03: Block once, fail open

The Menu_Gate returns silently when `stop_hook_active` is true, and exits 0 with no output on any internal error, the contract of its sibling draft gates.

### FR-04: Config-first

The Menu_Gate reads the Config when it is readable and replaces a built-in default list only for a key that lists at least one item; an unreadable Config keeps the built-in defaults so a deleted file never disarms the gate.

### FR-05: Wiring

The rule `COMMS.no-menu-question` is registered in the Rule_Registry with strength GATE, enforcement fail-closed, a `--selftest` proof over its fixtures and `liveness_required: FIRES`; the Menu_Gate is registered on Stop in `hooks.json`; the Rule_Text holds the anchor; `registry/friction-signatures.json` maps the block text to the gate.

## Acceptance Criteria

- [ ] AC-01: WHEN the Closing_Sentence is a Choice_Question in Spanish or English and names no Irreducible_Step, THE Menu_Gate SHALL print a block decision whose reason names `/choice`.
- [ ] AC-02: WHEN the Closing_Sentence is a decision, or a question followed by a decision, THE Menu_Gate SHALL print nothing.
- [ ] AC-03: WHEN the only question is inside quotes, a code block or a blockquote, THE Menu_Gate SHALL print nothing.
- [ ] AC-04: WHEN a line of the reply carries the Hatch, THE Menu_Gate SHALL print nothing.
- [ ] AC-05: WHEN the Closing_Sentence names an Irreducible_Step, THE Menu_Gate SHALL print nothing.
- [ ] AC-06: WHILE `stop_hook_active` is true, THE Menu_Gate SHALL print nothing.
- [ ] AC-07: IF the Menu_Gate cannot read its stdin or its transcript, THEN THE Menu_Gate SHALL exit 0 with no output.
- [ ] AC-08: IF the Config is unreadable, THEN THE Menu_Gate SHALL keep its built-in default lists, and WHEN the Config lists items under a key, THE Menu_Gate SHALL use those items for that key.
- [ ] AC-09: THE Rule_Registry SHALL hold `COMMS.no-menu-question` with a `--selftest` proof whose fixtures carry a violation and benign twin for the Spanish, English, opener, quoted, code-block, blockquote and irreducible cases.
- [ ] AC-10: THE Doctor SHALL report the rule wired only when the Menu_Gate is registered on Stop, its selftest passes and the Rule_Text holds the anchor.

## Residuals

- R-01: A menu phrased without `?`, or without alternatives or an opener (a bullet list of options ending in a period), is not seen. Widening the net would block every information question.
- R-02: The Spanish `o` as a whole word can appear inside a non-menu question ("¿Está bien el nombre A o B del archivo?"); the Hatch covers it.
- R-03: Like every Stop gate, the harness cap on consecutive continuations and the parallel run with the other Stop gates apply (see `docs/architecture/v11-reply-panel.md` R-02, R-04).
