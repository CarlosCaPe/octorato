# Feature: Quiet Provenance

> **Status:** draft
> **Spec-Format:** ears-1
> **Date:** 2026-11-20
> **Classification:** LARGE (score 9: 10+ files, new feature, behavior change of live gates)

The Provenance footer (Basis · Engine · Touched · Verified · Graph) and the 2D verdict line help the agent: they make it name its sources and its route every turn. On the operator's screen they are logs that get in the way of reading the answer. Operator directive (2026-11-20): keep producing them every turn, hide them on his screen by default, show them when he asks, and use diagrams instead of text walls.

Today the footer has to sit in the reply text, because three Stop-time consumers read it from there: `source-attribution-check.py` (blocks a reply with no provenance marker), `g__stop__reply-panel.py` (SOURCED vs SELF from the footer's Basis, quorum 1 vs 3) and `panel_preflight.py` (prints the same class before the panel). This feature gives the provenance a second, off-screen home and teaches those consumers to read it.

## Summary

A small CLI, `scripts/provenance_ledger.py`, appends the turn's provenance (and the 2D verdict) as one JSON line keyed by session id to a gitignored ledger. Every consumer accepts either the visible footer line (back-compat) or a ledger entry of this session strictly newer than the operator's prompt, using the reply panel's own prompt walk as the anchor. The reply panel classifies the ledger Basis with the same helpers it applies to a footer Basis. The digest stays over the exact displayed reply text. `4d-reminder.py`, `CLAUDE.md` and `skills/4d-paradigm-protocol/SKILL.md` switch the instruction from "print it" to "record it, print it only on request".

`g__stop__diagram-first.py` and `claim-verify-stop.py` only EXEMPT footer lines from their counts; with no footer printed there is nothing to exempt, and a printed one is still exempt, so they need no change.

## Glossary

- **Provenance_Ledger**: `scripts/provenance_ledger.py`, CLI `record` / `show` / `--selftest` and library `record`, `entries`, `fresh`, `footer_line`, `prompt_ts`, `fresh_for_transcript`.
- **Ledger_File**: `~/.claude/.cache/provenance/provenance.jsonl`, gitignored by `.cache/`, one `{"kind": "provenance", "session_id", "ts", "basis", "engine", "touched", "verified", "graph", "verdict"}` line per record. Kept out of `.cache/receipts/`, whose files are hook-written.
- **Fresh_Entries**: every Ledger_File entry of the session whose `ts` is strictly newer than the Reply_Anchor and not later than now plus `FUTURE_SKEW_S` (120 s), oldest first (`provenance_ledger.fresh_all`).
- **Reply_Anchor**: the operator prompt's timestamp (as `prompt_read` of `g__stop__reply-panel.py` finds it), moved forward to the newest earlier assistant reply of the same turn that has at least 31 words, differs from the current reply and is followed by a user-side entry, i.e. a reply that already ended a stop (`provenance_ledger.reply_anchor`). Status lines (30 words or fewer) do not move it.
- **Bound_Text**: the text the operator-reply digest is computed over (`bound_reply_text`): the reply itself when it shows a Footer_Line or no Fresh_Entries exist, else the reply plus one rendered footer line (`provenance_ledger.footer_line`) per Fresh_Entry, joined by newlines.
- **Panel_Request**: `scripts/panel_digest.py --panel-request --to operator` (and the digest-only `--to operator` form).
- **Footer_Line**: a `Provenance` / `Procedencia` / `Herkunft` line in the reply text.
- **Reply_Panel**: `scripts/g__stop__reply-panel.py` (rule `FLOW.panel-before-reply`).
- **Source_Attribution_Gate**: `scripts/source-attribution-check.py` (rule `CODE.cite-sources`).
- **Preflight**: `scripts/panel_preflight.py`, run by `panel_digest.py --preflight` and `--panel-request --to operator`.
- **Reminder**: `scripts/4d-reminder.py` (UserPromptSubmit).
- **Brain_Docs**: `CLAUDE.md` and `skills/4d-paradigm-protocol/SKILL.md`.
- **Arming_Closure**: `_SCRIPT_PATTERNS` in `scripts/g__pretool__arming-surface.py`.

## Functional Requirements

### FR-01: Record off-screen

`provenance_ledger.py record --basis ... [--engine] [--touched] [--verified] [--graph] [--verdict]` appends one entry for the session named by `--session`, else `CLAUDE_SESSION_ID`, else `CLAUDE_CODE_SESSION_ID`. With no session it writes nothing and exits 2. `show` prints the latest entry as a one-line footer, for the operator on request.

### FR-02: Either path satisfies the presence check

The Source_Attribution_Gate passes a reply that has a Footer_Line marker, or, when it has none, a Fresh_Entries member with a non-empty Basis. The session is the payload's `session_id`, else `OCTO_PROVENANCE_SESSION`. A ledger lookup error counts as no entry.

### FR-03: Same classification rules

The Reply_Panel's sources are every Footer_Line plus every Fresh_Entries member. No source is SELF; any SELF source is SELF, in any order (each entry Basis is judged with `_empty_basis` and `_self_basis`, the helpers a Footer_Line Basis goes through); otherwise SOURCED. INPUT stays as before, and a SELF entry Basis cancels it like a SELF footer does. An unreadable Ledger_File is a GateError (fail closed).

### FR-03b: The Basis is bound to the receipt

The digest is `digest(Bound_Text, recipients=["operator"])`. The Panel_Request prints the Bound_Text in the reviewed block and digests it, so the reviewer judges the Basis that sets the quorum and PANEL-SHA256 covers it. A record made after the review changes the Bound_Text, so the old PASS no longer matches. A reply with a visible Footer_Line keeps today's digest.

### FR-04: Preflight judges as Stop will

The Preflight classifies the draft with the Fresh_Entries of the current session against the copied transcript, and hands the session to the spawned gates in `OCTO_PROVENANCE_SESSION`; the synthetic payload still carries no `session_id`. A ledger read error is a FAIL line that blocks the panel request, as the Stop gate fails closed on it. The session comes from `provenance_ledger.current_session` (CLAUDE_SESSION_ID, then CLAUDE_CODE_SESSION_ID) in every reader.

### FR-05: Instruction flips

The Reminder tells the agent to record the provenance and the 2D verdict with the CLI and not print them, and to print the footer only when the operator asks. Brain_Docs say the same: recorded always, hidden on screen by default, shown on request.

### FR-06: Closure

`provenance_ledger.py` is a run-time import of two gates, so it joins the Arming_Closure next to `stop_block.py`.

## Acceptance Criteria

- [ ] AC-01: WHEN `record` runs with a session, THE Provenance_Ledger SHALL append one entry to the Ledger_File with that session id and a UTC timestamp.
- [ ] AC-02: IF no session id is available, THEN THE Provenance_Ledger SHALL write nothing and exit 2.
- [ ] AC-03: WHEN a reply has no Footer_Line and the session holds Fresh_Entries with a non-empty Basis, THE Source_Attribution_Gate SHALL allow the stop.
- [ ] AC-04: IF a reply has no Footer_Line and the session has no Fresh_Entries, THEN THE Source_Attribution_Gate SHALL block once.
- [ ] AC-05: IF the only entry of the session is not newer than the Reply_Anchor, THEN THE Source_Attribution_Gate SHALL block once.
- [ ] AC-06: IF every Fresh_Entries Basis is empty, THEN THE Source_Attribution_Gate SHALL block once.
- [ ] AC-07: WHEN a reply has no Footer_Line and every Fresh_Entries Basis names a source, THE Reply_Panel SHALL classify the reply SOURCED and require one reviewer.
- [ ] AC-08: IF any Fresh_Entries Basis is empty, none or names self or own reasoning, THEN THE Reply_Panel SHALL classify the reply SELF and require three reviewers, whatever entries follow it.
- [ ] AC-09: IF the session has no Fresh_Entries and the reply has no Footer_Line, THEN THE Reply_Panel SHALL classify the reply SELF.
- [ ] AC-10: IF a Footer_Line and a Fresh_Entries member disagree, THEN THE Reply_Panel SHALL apply the SELF reading.
- [ ] AC-11: WHEN a reply has no Footer_Line and Fresh_Entries exist, THE Reply_Panel SHALL compute the digest over the Bound_Text, and WHEN the reply has a Footer_Line THE Reply_Panel SHALL compute it over the displayed text alone.
- [ ] AC-12: WHEN a draft has no Footer_Line and the session holds Fresh_Entries, THE Preflight SHALL print the class the Reply_Panel will compute and SHALL not report a Source_Attribution_Gate block.
- [ ] AC-17: WHEN the Panel_Request runs on a reply with no Footer_Line, THE Panel_Request SHALL print and digest the Bound_Text, so the reviewed block carries every Fresh_Entries footer line.
- [ ] AC-18: IF an entry is recorded after the PASS was given, THEN THE Reply_Panel SHALL find no PASS for the new Bound_Text and block.
- [ ] AC-19: IF an entry is older than an earlier reply of the same turn that already ended a stop, THEN THE Reply_Panel SHALL not count it.
- [ ] AC-20: IF an entry is stamped more than 120 seconds after now, THEN THE Provenance_Ledger SHALL leave it out of Fresh_Entries.
- [ ] AC-21: IF the Ledger_File cannot be read, THEN THE Preflight SHALL print a FAIL line and block the Panel_Request.
- [ ] AC-13: THE Reminder SHALL instruct recording with `provenance_ledger.py record` and printing the footer only when the operator asks.
- [ ] AC-14: THE Brain_Docs SHALL state that provenance and the 2D verdict are recorded every turn, hidden on the operator's screen by default and shown on request.
- [ ] AC-15: THE Arming_Closure SHALL include `provenance_ledger.py`, with an arming-surface fixture pair that names it.
- [ ] AC-16: THE Source_Attribution_Gate SHALL keep accepting a Footer_Line and keep the `no provenance footer` substring in its shown line.

## Residuals

- R-01: The Ledger_File is model-written, so it carries the same trust as the footer text it replaces. It is not a harness receipt. What closes the gap is the binding (FR-03b): the Basis that sets the quorum is in the reviewed block and under PANEL-SHA256, so the reviewer judges it as it would judge a printed footer, and no entry can be added or changed after the review without voiding the PASS. A false Basis that a reviewer accepts is the same residual a false footer has.
- R-02: A subagent's Bash sees the parent's `CLAUDE_CODE_SESSION_ID`, so a `record` run inside a subagent lands in the parent's Fresh_Entries. With FR-03b, that changes the Bound_Text: it voids the parent's PASS (a re-review) and can lower the class to SELF, but it cannot lift it.
- R-06: Reply_Anchor counts assistant text of 31 or more words followed by a user-side entry as a reply that ended a stop. Long mid-turn narration before a tool call also moves the anchor, so the agent records after it. A reply split across several assistant entries is compared entry by entry against the current reply; an earlier entry of the same reply that is long and followed by a tool result moves the anchor.
- R-03: The cost of one extra Bash call per turn is accepted; it replaces a footer line in the displayed text.
- R-04: Other docs that describe the footer as printed (README.md, WHITEPAPER.md, docs/wiki/Glossary.md, docs/ANATOMY.md, docs/architecture/hook-orchestration.md, skills/human-cadence/SKILL.md) are not rewritten here; they stay accurate for the back-compat path and are left for a docs pass.
- R-05: `CLAUDE.md` sits at the `claude-md-budget` ceiling (12,000 by the doctor's bound on master), so its edits are token-neutral (11,999 after): the rule lives in the Diagram-first paragraph, and the Reply panel line keeps "any Provenance Basis" without naming the ledger; the full contract is in `skills/4d-paradigm-protocol/SKILL.md`.
