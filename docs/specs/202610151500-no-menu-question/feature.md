# Feature: No Menu Questions

> **Status:** draft
> **Spec-Format:** ears-1
> **Date:** 2026-10-15
> **Classification:** LARGE (score 8: 10+ files, new feature, multiple modules)

Operator directive 2026-10-15, verbatim: "cada que termines en pregunta de opción múltiple, quiero que apliques choice, siempre, hasta que me llegues ya con una sugerencia, 0% de preguntas de opción múltiple". A reply that closes on "¿Dale a X o Y?" or "Shall I proceed?" hands back a decision the agent could make with `/choice` and execute. This feature wires that directive as a Stop gate, in the same class as `g__stop__defer-today.py` and `g__stop__draft-promise.py`.

## Summary

The gate reads the last assistant reply, discards the Provenance footer, the Disclose one-liners, fenced and inline code, blockquotes and quoted spans, and takes the closing sentence. When that sentence ends in `?` (after trimming trailing emphasis, brackets, emoji and "(y/n)") and is a go-ahead ask, a short yes/no permission ask, an alternatives menu the agent could choose, or a selection after a list, the gate blocks once and tells the model to run `/choice` and return the decision. A question naming an irreducible operator step (money, consent, an outward send, a merge approval, a version cut, a login) passes. Openers and irreducible steps are config in `registry/no-menu-question.yaml`.

## Glossary

- **Menu_Gate**: `scripts/g__stop__no-menu-question.py`, a Stop hook.
- **Closing_Sentence**: the last sentence of the reply's prose after the Menu_Gate discards the Provenance footer, lines starting with the Disclose markers (`💡 Unlock-suggestion`, `☠ Prune-suggestion`), fenced and inline code, lines starting with `>`, lines carrying the Hatch, and spans inside double, curly or guillemet quotes.
- **Choice_Question**: a Closing_Sentence that asks the operator to choose. Ending in `?` once trailing emphasis, brackets, emoji and a `(y/n)` suffix are trimmed, it opens with an entry of `openers`, matches a `permission_patterns` or `selection_openers` regex, contains a whole-word `o`, `u` or `or` between alternatives the agent could choose, or matches a `selection_patterns` regex after a list of two or more items. Without `?`, it matches a `statement_menu_patterns` regex, or a `solicit_patterns` regex right after a sentence that carries alternatives. Short `filler` after a question does not hide it.
- **Agent_Action**: an `openers` entry, a `permission_patterns` or `selection_openers` regex, a whole-word `choice_verbs` entry, or an `agent_action_patterns` regex (a clitic plus a first-person verb) in the Closing_Sentence.
- **Diagnostic_Question**: an `o`/`or` Closing_Sentence with no Agent_Action that carries an `info_verbs` regex (a verb about state or the operator's past: "quedó", "revocaste", "está", "is"), opens with an `info_interrogatives` entry, names an `info_markers` entry, or matches a `diagnostic_patterns` regex (a second-person verb about the operator's world, "¿Ves el banner rojo o el amarillo?", "¿Necesitas el CSV o el Excel?", "¿Te refieres al repo viejo o al nuevo?"; a clitic `te`/`le` plus a non-first-person verb, "¿Te sale el 403 o el 401?"; an environment verb in third person, "¿Abre en Chrome o en Safari?"; or "do/did/are/were/have/had you" plus a verb that is not a preference, "Do you see / get / need / mean A or B?"). It is information, not a menu. A bare `o`/`or` fragment with no verb ("¿Stop o PreToolUse?") stays a Choice_Question.
- **Preference_Line**: a preference verb (prefer, want, like, wish, mind, rather, think, feel, `prefieres`, `quieres`) asks the operator to pick what the agent produces or does next, so "¿Prefieres A o B?", "Do you want A or B?" and "Do you think A or B?" stay Choice_Questions even with no first-person verb in the sentence. A state or perception verb (see, get, need, mean, `ves`, `necesitas`, `te sale`, `te refieres`) asks for a fact about the operator's world and passes, unless the same question also carries an Agent_Action ("¿Ves el banner rojo o lo cambio?", "Do you need the CSV or should I build the Excel?"), which blocks.
- **Irreducible_Step**: an entry of the `irreducible` list, matched case- and accent-folded as a whole word of the Closing_Sentence and only as its object: the question ends, punctuation follows, or the next word is in `object_followers`. It exempts the question only when the operator performs it: the question carries no Agent_Action ("¿Me das el login?", "¿Confirmas el pago?"), or the alternative holding the term matches an `operator_action_patterns` regex (a second-person verb or an imperative: "¿Exportas OCTO_MERGE_APPROVE=417 o lo dejo en la rama?"). Inside an agent choice the term is a noun and the question still blocks ("Should I ship the login or the cart fix?"). Decision on "¿Hago el pago hoy o mañana?": the first-person "hago" makes the payment the agent's act, so it blocks; the operator's payment is phrased "¿Haces el pago hoy o mañana?" and passes. A verbless "¿Pago hoy o mañana?" carries no detectable Agent_Action (the gate cannot tell the noun "pago" from the verb) and passes as the operator's step.
- **Config**: `registry/no-menu-question.yaml`, a two-level YAML subset (`key:` then `  - item`) with the keys `openers`, `permission_patterns`, `selection_patterns`, `info_interrogatives`, `choice_verbs`, `info_markers`, `filler`, `irreducible`, `object_followers`, `info_verbs`, `agent_action_patterns`, `selection_openers`, `statement_menu_patterns`, `solicit_patterns`, `operator_action_patterns` and `diagnostic_patterns`, parsed by the Menu_Gate itself.
- **Hatch**: the literal `menu-ok` on a line of the reply.
- **Rule_Registry**: `registry/rules.yaml` with fixtures under `registry/fixtures/COMMS.no-menu-question/`.
- **Rule_Text**: the `CLAUDE.md` paragraph with anchor "No menu questions".
- **Doctor**: `scripts/brain_doctor.py`.

## Functional Requirements

### FR-01: What fires

The Menu_Gate blocks when the Closing_Sentence is a Choice_Question and names no Irreducible_Step. The block reason names `/choice`, the irreducible-step exception and the Hatch, and carries the signature `SIN-MENÚ` for the friction ledger.

### FR-02: What does not fire

A quoted question, a question inside a code block or a blockquote, a question followed by a decision, an information question without alternatives or an opener, a Diagnostic_Question, a question whose Irreducible_Step the operator performs, a line carrying the Hatch, and an empty reply all pass.

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

- R-01: A menu phrased without `?` is seen only through `statement_menu_patterns` and `solicit_patterns`; a bullet list of options ending in a plain period, or a request phrased outside those patterns, is not. Widening the net would block every information question.
- R-02: The Spanish `o` as a whole word can appear inside a non-menu question ("¿Está bien el nombre A o B del archivo?"); the Hatch covers it.
- R-03: Like every Stop gate, the harness cap on consecutive continuations and the parallel run with the other Stop gates apply (see `docs/architecture/v11-reply-panel.md` R-02, R-04).
- R-04: The Diagnostic_Question test reads verbs from a lexicon plus preterite endings; a state verb outside `info_verbs` in a bare `o`/`or` question still blocks, and a verbless agent menu with an `info_verbs` word in it passes. Every regex is linear; a 20k-character near-miss runs in under 0.2 s.
- R-05: `diagnostic_patterns` reads verbs from a lexicon and a clitic shape; a second-person state verb outside the lexicon still blocks, and a near-preference such as "¿Te sirve el CSV o el Excel?" passes as a fact about the operator's need. The Preference_Line is a word list, not a parse.
