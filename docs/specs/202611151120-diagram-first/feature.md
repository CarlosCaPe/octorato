# Feature: Diagram-First Replies

> **Status:** draft
> **Spec-Format:** ears-1
> **Date:** 2026-11-15
> **Classification:** LARGE (score 9: 10+ files, new feature, multiple modules)

A reply that explains a flow, a before/after, the status of several items or a structure in paragraphs makes the reader rebuild the picture in their head. The operator's rule is that such a reply opens with an ASCII diagram in a code block, and prose covers only what the diagram does not say. The rule has lived as memory and is broken under load, so this feature wires it as a Stop gate in the class of `g__stop__no-menu-question.py` and `g__stop__paste-ready-raw.py`.

## Summary

The gate reads the last assistant reply and the last operator prompt. It strips the Provenance footer, the Disclose one-liners, fenced code, inline code, blockquotes and quoted spans, and counts the words left. Above the Word_Floor, when the stripped prose has an Explanatory_Shape and the reply does not open with an Opening_Diagram, it blocks once and says which shape it saw. Short replies, paste-ready messages, `input-needed:` replies and lines carrying the Hatch pass.

## Glossary

- **Diagram_Gate**: `scripts/g__stop__diagram-first.py`, a Stop hook.
- **Prose**: the reply after removing fenced code blocks (closed or trailing open), inline code spans, lines starting with `>`, spans inside double, curly or guillemet quotes, the Provenance footer line (`Provenance:`, `Procedencia:`, `Herkunft:`), lines starting with the Disclose markers (`💡 Unlock-suggestion`, `☠ Prune-suggestion`) and lines carrying the Hatch.
- **Word_Floor**: 80 words of Prose, a word being a whitespace-separated token (`str.split()`, as `scripts/g__stop__reply-panel.py` counts) that holds at least one letter or digit, so arrows, glyphs and list markers do not count. A reply below it is short and exempt. A status line while a subagent runs (at most 30 words, `docs/architecture/v11-reply-panel.md`) and an `input-needed:` reply (at most 60 words, `scripts/g__stop__reply-panel.py` INPUT_CAP) both sit below it.
- **Explanatory_Shape**: any of Flow_Shape, Before_After_Shape, Status_Shape or Structure_Shape, read from the Prose.
- **Flow_Shape**: two or more arrow tokens (`->`, `-->`, `=>`, `→`, `⟶`, `─►`) in the Prose, or three or more consecutive numbered list items (`1.` or `1)`).
- **Before_After_Shape**: a line opening with a before label (`Before:`, `Antes:`, `Previously:`) and a later line opening with an after label (`After:`, `Now:`, `Después:`, `Ahora:`), each label optionally wrapped in bullet, heading or bold markers.
- **Status_Shape**: three or more list items or table body rows that each carry a state marker: a glyph (`✓`, `✗`, `✅`, `❌`, `⚠`) or a whole state word (done, pending, blocked, open, merged, failing, passing, green, red, listo, pendiente, bloqueado, hecho, abierto, cerrado), matched case- and accent-folded.
- **Structure_Shape**: a bullet list with items at two or more indentation levels and four or more items in total.
- **Opening_Diagram**: a fenced block that is the first non-blank element of the reply, or that follows a single Lead_Line, whose info string is empty, `text`, `txt` or `ascii`, and whose body holds a diagram glyph (`─►`, `►`, `├─`, `└─`, `│`, `▼`, `→`, `->`).
- **Lead_Line**: one non-blank line of at most 20 words before the fence, not itself a list item.
- **Paste_Ask**: the last operator prompt matches the paste-ready ask pattern `_ASK_PASTE` of `scripts/g__stop__paste-ready-raw.py`, loaded by file path.
- **Input_Line**: the last non-blank Prose line, when it opens with the `input-needed:` label, the INPUT class of the reply panel.
- **Exemption**: a Paste_Ask, an Input_Line or a Hatch line in the reply.
- **Blocking_Condition**: the Prose reaches the Word_Floor, carries an Explanatory_Shape, no Exemption applies, and the reply has no Opening_Diagram.
- **Friction_Map**: `registry/friction-signatures.json`.
- **Preflight**: `scripts/panel_preflight.py`, which `scripts/panel_digest.py --panel-request --to operator` runs and which derives its gate list from the Stop hooks in `hooks.json`.
- **Lineage**: `connectome/lineage.yaml`.
- **Hatch**: the literal `diagram-ok` on a line of the reply.
- **Rule_Registry**: `registry/rules.yaml` with fixtures under `registry/fixtures/COMMS.diagram-first/`.
- **Rule_Text**: the `CLAUDE.md` paragraph with anchor "Diagram-first".
- **Cadence_Skill**: `skills/human-cadence/SKILL.md`, which carries the HOW.
- **Doctor**: `scripts/brain_doctor.py`.

## Functional Requirements

### FR-01: What fires

The Diagram_Gate blocks when the Prose reaches the Word_Floor, carries an Explanatory_Shape, and the reply has no Opening_Diagram. The reason names the shape it saw, the grammar (`──►`, `├─` / `└─`, ✓ / ? / ✗, `1°` / `2°`), the Hatch, and carries the signature `DIAGRAM-FIRST` for the friction ledger.

### FR-02: What does not fire

A reply below the Word_Floor, a reply to a Paste_Ask, a reply with an Input_Line, a reply with a line carrying the Hatch, a reply whose only shape lives inside code, a blockquote or a quoted span, a long reply with no Explanatory_Shape, and a reply that opens with an Opening_Diagram all pass.

### FR-03: Block once, fail open

The Diagram_Gate returns silently when `stop_hook_active` is true, and exits 0 with no output on any internal error, the contract of its sibling Stop gates. A block is mirrored into the kernel journal through `scripts/kernel_proc.py`, fail-open, as the siblings do.

### FR-04: Wiring

The rule `COMMS.diagram-first` is registered in the Rule_Registry with strength GATE, enforcement fail-closed, an `IN_HOOKS_JSON` proof and a `--selftest` proof over its fixtures, and `liveness_required: FIRES`; the Diagram_Gate is registered on Stop in `hooks.json`, which also puts it in the `panel_preflight.py` run that `panel_digest.py --panel-request` triggers; the Rule_Text holds the anchor; `registry/friction-signatures.json` maps the block text to the gate.

## Acceptance Criteria

- [ ] AC-01: WHEN the Blocking_Condition holds with a Flow_Shape, THE Diagram_Gate SHALL print a block decision whose reason carries `DIAGRAM-FIRST` and names the flow shape.
- [ ] AC-02: WHEN the Blocking_Condition holds with a Before_After_Shape, a Status_Shape or a Structure_Shape in English or Spanish, THE Diagram_Gate SHALL print a block decision naming that shape.
- [ ] AC-03: WHEN the Blocking_Condition holds and the reply carries a diagram fence that is not an Opening_Diagram, THE Diagram_Gate SHALL print a block decision whose reason says to move the diagram to the top.
- [ ] AC-04: WHEN the reply opens with an Opening_Diagram, with or without one Lead_Line, THE Diagram_Gate SHALL print nothing.
- [ ] AC-05: WHEN the Prose is below the Word_Floor, THE Diagram_Gate SHALL print nothing.
- [ ] AC-06: WHEN an Exemption applies, THE Diagram_Gate SHALL print nothing.
- [ ] AC-07: WHEN the only Explanatory_Shape sits inside fenced code, inline code, a blockquote or a quoted span, THE Diagram_Gate SHALL print nothing.
- [ ] AC-08: WHILE `stop_hook_active` is true, THE Diagram_Gate SHALL print nothing.
- [ ] AC-09: IF the Diagram_Gate cannot parse its stdin or read its transcript, THEN THE Diagram_Gate SHALL exit 0 with no output.
- [ ] AC-10: THE Rule_Registry SHALL hold `COMMS.diagram-first` with a `--selftest` proof whose fixtures carry a violation and a benign twin for the flow, numbered, before/after, Spanish, status, structure and late-diagram cases, plus benign fixtures for the short, paste-ready, input-needed, status-line, hatch, code, blockquote and plain-prose cases.
- [ ] AC-11: THE Doctor SHALL report the rule wired only when the Diagram_Gate is registered on Stop, its selftest passes, the Rule_Registry entry carries `liveness_required: FIRES` and the Rule_Text holds the anchor, with `CLAUDE.md` still inside its 12,000-token ceiling.
- [ ] AC-13: THE Friction_Map SHALL map the pattern `DIAGRAM-FIRST` to the Diagram_Gate, and that pattern SHALL appear in the Diagram_Gate's block reason.
- [ ] AC-14: THE Preflight SHALL include the Diagram_Gate in the Stop gates it runs.
- [ ] AC-15: THE Lineage SHALL hold a node whose surfaces name the Diagram_Gate, the Rule_Registry entry, its fixtures, `hooks.json`, the Rule_Text and the Cadence_Skill.
- [ ] AC-12: THE Cadence_Skill SHALL carry the grammar, when the rule applies, the exemptions, the Hatch and one worked example.

## Residuals

- R-01: The shapes are surface patterns, not a parse. A flow told in plain sentences with no arrows and no numbered list ("first the hook runs, then the ledger records it") is not seen. Widening the net to words like "then" would block ordinary prose.
- R-02: "Prose covers only what the diagram does not say" is not measured. The gate checks that the diagram comes first; whether the prose repeats it is left to the reviewer panel.
- R-03: A Lead_Line longer than 20 words before the diagram blocks; the Hatch covers a deliberate long lead.
- R-04: The Paste_Ask exemption depends on `scripts/g__stop__paste-ready-raw.py` staying loadable by path. If that load fails, the exemption is off and a paste-ready reply over the Word_Floor with a shape can block once; the Hatch covers it.
- R-05: Like every Stop gate, the harness cap on consecutive continuations and the parallel run with the other Stop gates apply (`docs/architecture/v11-reply-panel.md` R-02, R-04).
- R-06: `CLAUDE.md` measured 11,954 of its 12,000-token ceiling before this change (doctor check `claude-md-budget`), so the Rule_Text is one short paragraph and the HOW lives in the Cadence_Skill. To fit it, the Do-it-today paragraph loses its sentence restating the do-it-right reconciliation; the same reconciliation stays verbatim in the ULTRA RULE "Do it right, not fast" bullet.
- R-07: The Input_Line exemption reads only the last Prose line, so a long reply that ends on an `input-needed:` question passes at any length. The reply panel caps an INPUT reply at 60 words; this gate does not repeat that cap, because the panel already enforces it.
