# Feature: Diagram-Always Replies

> **Status:** draft
> **Spec-Format:** ears-1
> **Date:** 2026-11-17
> **Classification:** LARGE (score 8: 10+ files, behavior change of a live gate)

The operator decided on 2026-11-17 that 100% of replies to him in the terminal are flows: "quiero 100% de respuestas en flujos, y si es texto, poco con bullets. Si quiero más detalle te lo pido o tú puedes sugerir." The Diagram_Gate of `docs/specs/202611151120-diagram-first/` fired only on four explanatory shapes above an 80-word floor, so most replies passed with no diagram. This spec supersedes that trigger: every reply is checked, and the text after the diagram must be short and in bullets.

## Summary

The gate reads the last assistant reply and the last operator prompt. Unless an Exemption applies, it blocks once when the reply has no Opening_Diagram, or when the Prose runs over the Prose_Cap or holds a Long_Paragraph. The four shape detectors stay only as diagnostic text in the block reason. Two advisory hooks that printed `systemMessage` text on the operator's screen now route that text to the model only.

## Glossary

- **Diagram_Gate**: `scripts/g__stop__diagram-first.py`, a Stop hook.
- **Prose**: as in the superseded spec: the reply minus fenced code, inline code, blockquote lines, quoted spans, the Provenance footer line, the Disclose one-liners and Hatch lines.
- **Opening_Diagram**: a fenced block that is the first non-blank element of the reply (after an optional leading fenced 2D Delegate summary), or follows one Lead_Line (at most 20 words, not a list item), whose info string is empty, `text`, `txt`, `ascii`, `plaintext` or `text-plain`, and whose body holds a diagram glyph: an arrow (`─►`, `►`, `◄`, `→`, `←`, `->`, `<-`, `=>`), a box-drawing glyph (`├─`, `└─`, `┌`, `┐`, `┘`, `│`, `──`, `═`, `║`, `▼`, `▲`), or an ASCII table line (`| a | b |` or `+---+`).
- **Prose_Cap**: `PROSE_MAX_WORDS`, 120 words of Prose.
- **Long_Paragraph**: a run of consecutive non-blank Prose lines that are not list items or table rows (a line indented under a list item continues that item) holding more than `PARAGRAPH_MAX_WORDS`, 40 words.
- **Input_Only**: the last non-blank Prose line opens with `input-needed:` and the rest of the Prose holds at most `INPUT_LEAD_MAX_WORDS`, 30 words.
- **Paste_Ask**: the last operator prompt matches `_ASK_PASTE` of `scripts/g__stop__paste-ready-raw.py`, loaded by file path.
- **Hatch**: the literal `diagram-ok` on a line of the reply.
- **Exemption**: a Paste_Ask, an Input_Only reply or a Hatch line.
- **Detail_Offer**: one closing line offering more detail in verbless form (`¿Más detalle de X?`, `More detail on X?`).
- **Menu_Gate**: `scripts/g__stop__no-menu-question.py`.
- **Status_Exemption**: the reply panel's status line, at most 30 whitespace-split tokens with no outcome word and no digit (`scripts/g__stop__reply-panel.py` STATUS_CAP, status_claim).
- **Advisory_Hooks**: `scripts/impact-radius-hook.py` (PostToolUse) and `scripts/grafo-ledger-check.py` (Stop), with `scripts/grafo-turn-reset.py` (UserPromptSubmit) as the relay.
- **Relay**: `scripts/grafo-turn-reset.py` in its role of handing the Stop advisory to the model.
- **Rule_Fixtures**: `registry/fixtures/COMMS.diagram-first/`.
- **Rule_Text**: the `CLAUDE.md` paragraph with anchor "Diagram-first" and Human Cadence rule 8.
- **Cadence_Skill**: `skills/human-cadence/SKILL.md`.

## Functional Requirements

### FR-01: Every reply is checked

The Diagram_Gate has no word floor. Any reply with no Exemption and no Opening_Diagram blocks, status lines included.

### FR-02: Text after the diagram is short and in bullets

A reply with an Opening_Diagram still blocks when its Prose exceeds the Prose_Cap or holds a Long_Paragraph. The block reason carries `DIAGRAM-FIRST` and the phrase "flow first; text short and in bullets; offer more detail in one line instead of writing it".

### FR-03: Exemptions, block once, fail open

Paste_Ask, Input_Only and Hatch exempt the turn; `stop_hook_active` passes; any error exits 0 with no output.

### FR-04: Rule text

The Rule_Text and the Cadence_Skill state the every-reply rule, the HTML-artifact fallback for content too large for ASCII, the Detail_Offer shape, and the rule-8 exception for terminal replies to the operator (rule 8 still holds for outward drafts).

### FR-05: Advisories stay off the operator's screen

The Advisory_Hooks emit no `systemMessage`. The PostToolUse hook emits `hookSpecificOutput.additionalContext`; the Stop hook writes its advisory to `~/.claude/.cache/graph-ledger/<sid>.advisory.txt`, which the UserPromptSubmit relay hands to the model as additionalContext and deletes. The file is keyed by the hook payload's `session_id` (env fallback); with no real session id nothing is written or relayed.

## Acceptance Criteria

- [ ] AC-01: WHEN a reply has no Opening_Diagram and no Exemption applies, THE Diagram_Gate SHALL print a block decision, whatever the reply's length.
- [ ] AC-02: WHEN a reply opens with an Opening_Diagram and its Prose is within the Prose_Cap with no Long_Paragraph, THE Diagram_Gate SHALL print nothing.
- [ ] AC-03: WHEN a reply with an Opening_Diagram has Prose over the Prose_Cap or a Long_Paragraph, THE Diagram_Gate SHALL print a block decision whose reason names the cap or the paragraph.
- [ ] AC-04: WHEN an Exemption applies, THE Diagram_Gate SHALL print nothing.
- [ ] AC-05: WHILE `stop_hook_active` is true, THE Diagram_Gate SHALL print nothing.
- [ ] AC-06: IF the Diagram_Gate cannot parse its stdin or read its transcript, THEN THE Diagram_Gate SHALL exit 0 with no output.
- [ ] AC-07: THE Diagram_Gate SHALL accept a plain ASCII table inside a bare or `text` fence as an Opening_Diagram.
- [ ] AC-08: THE Diagram_Gate SHALL put `DIAGRAM-FIRST` and the phrase "flow first; text short and in bullets; offer more detail in one line instead of writing it" in every block reason.
- [ ] AC-09: THE Rule_Fixtures SHALL include a blocking 25-word status line, a passing diagram plus three bullets, a blocking diagram plus a 150-word paragraph and a passing Input_Only reply, and every superseded benign fixture that now blocks SHALL be renamed `violation_flipped_*`.
- [ ] AC-10: WHEN the reply closes on a Detail_Offer in verbless form, THE Menu_Gate SHALL print nothing.
- [ ] AC-11: THE Rule_Text SHALL state FR-04.
- [ ] AC-12: THE Advisory_Hooks SHALL emit no `systemMessage` key, and SHALL keep exit code 0.
- [ ] AC-13: WHEN the Stop advisory fires, THE Relay SHALL emit it once as UserPromptSubmit additionalContext at the next prompt and delete the ledger file.
- [ ] AC-14: THE Cadence_Skill SHALL state FR-04.
- [ ] AC-15: WHEN a reply leads with a fenced 2D Delegate summary followed by an Opening_Diagram, THE Diagram_Gate SHALL print nothing.
- [ ] AC-16: IF the Relay finds no real session id, or an advisory file it cannot decode, THEN THE Relay SHALL print nothing, and SHALL delete an undecodable file.
- [ ] AC-17: WHILE the Stop hook runs for session A, THE Relay SHALL NOT emit A's advisory to any other session.

## Residuals

- R-01: A tiny status diagram must fit the Status_Exemption, which counts every whitespace token (arrows and fences included) and refuses any digit or outcome word anywhere, the diagram included. A status line with `1°` or `✓ done` in its diagram needs a panel. Not a deadlock: `hook ──► reviewer ──► ?` plus a short sentence fits.
- R-02: Quoted spans are removed from the Prose before counting, so a long quoted passage does not count toward the Prose_Cap.
- R-03: The Stop advisory reaches the model one prompt late, and it does not reach it at all when the session ends after that Stop.
- R-04: Whether prose repeats the diagram is still not measured (superseded spec R-02).
- R-05: `CLAUDE.md` measured 11,997 of its 12,000-token ceiling before this change and 12,000 after it (doctor check `claude-md-budget`), so the Rule_Text is a compressed paragraph and the Detail_Offer shapes (`¿Más detalle de X?`, `More detail on X?`) and the reply-panel budget note live in the Cadence_Skill. To fit, the Communication bullet loses its pointer sentence to rule 8, which this change made stale.
- R-06: A paste-ready ask phrased outside `_ASK_PASTE` of `scripts/g__stop__paste-ready-raw.py` is not recognised, so the raw message reply blocks once for a missing diagram. The rewrite (or the Hatch) passes on the next stop; `stop_hook_active` keeps it to one forced rewrite, never a deadlock.
- R-07: Word caps count whitespace-separated tokens. CJK text has no spaces between words, so a long Chinese or Japanese paragraph counts as a few tokens and passes the Prose_Cap and the Long_Paragraph check.
- R-08: The graph advisory relay needs a session-scoped ledger (env `CLAUDE_SESSION_ID` set for the ledger writers). Where the harness does not set it, the ledger is the shared "adhoc" file and the advisory is neither written nor relayed: it is dropped, never leaked across sessions.
