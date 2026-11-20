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
- **Fresh_Entry**: the newest Ledger_File entry of the session whose `ts` is strictly newer than the operator prompt's timestamp, as `prompt_read` of `g__stop__reply-panel.py` finds it.
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

The Source_Attribution_Gate passes a reply that has a Footer_Line marker, or, when it has none, a Fresh_Entry with a non-empty Basis. The session is the payload's `session_id`, else `OCTO_PROVENANCE_SESSION`. A ledger lookup error counts as no entry.

### FR-03: Same classification rules

The Reply_Panel's sources are every Footer_Line plus the Fresh_Entry. No source is SELF; any SELF source is SELF (the Fresh_Entry Basis is judged with `_empty_basis` and `_self_basis`, the helpers a Footer_Line Basis goes through); otherwise SOURCED. INPUT stays as before, and a SELF Fresh_Entry Basis cancels it like a SELF footer does. The digest is unchanged: `digest(reply, recipients=["operator"])` over the displayed text. An unreadable Ledger_File is a GateError (fail closed).

### FR-04: Preflight judges as Stop will

The Preflight classifies the draft with the Fresh_Entry of the current session against the copied transcript, and hands the session to the spawned gates in `OCTO_PROVENANCE_SESSION`; the synthetic payload still carries no `session_id`.

### FR-05: Instruction flips

The Reminder tells the agent to record the provenance and the 2D verdict with the CLI and not print them, and to print the footer only when the operator asks. Brain_Docs say the same: recorded always, hidden on screen by default, shown on request.

### FR-06: Closure

`provenance_ledger.py` is a run-time import of two gates, so it joins the Arming_Closure next to `stop_block.py`.

## Acceptance Criteria

- [ ] AC-01: WHEN `record` runs with a session, THE Provenance_Ledger SHALL append one entry to the Ledger_File with that session id and a UTC timestamp.
- [ ] AC-02: IF no session id is available, THEN THE Provenance_Ledger SHALL write nothing and exit 2.
- [ ] AC-03: WHEN a reply has no Footer_Line and the session holds a Fresh_Entry with a non-empty Basis, THE Source_Attribution_Gate SHALL allow the stop.
- [ ] AC-04: IF a reply has no Footer_Line and the session has no Fresh_Entry, THEN THE Source_Attribution_Gate SHALL block once.
- [ ] AC-05: IF the only entry of the session is not newer than the operator prompt, THEN THE Source_Attribution_Gate SHALL block once.
- [ ] AC-06: IF the Fresh_Entry Basis is empty, THEN THE Source_Attribution_Gate SHALL block once.
- [ ] AC-07: WHEN a reply has no Footer_Line and the Fresh_Entry Basis names a source, THE Reply_Panel SHALL classify the reply SOURCED and require one reviewer.
- [ ] AC-08: IF the Fresh_Entry Basis is empty, none or names self or own reasoning, THEN THE Reply_Panel SHALL classify the reply SELF and require three reviewers.
- [ ] AC-09: IF the session has no Fresh_Entry and the reply has no Footer_Line, THEN THE Reply_Panel SHALL classify the reply SELF.
- [ ] AC-10: IF a Footer_Line and the Fresh_Entry disagree, THEN THE Reply_Panel SHALL apply the SELF reading.
- [ ] AC-11: THE Reply_Panel SHALL compute the digest over the exact displayed reply text, unchanged by any ledger entry.
- [ ] AC-12: WHEN a draft has no Footer_Line and the session holds a Fresh_Entry, THE Preflight SHALL print the class the Reply_Panel will compute and SHALL not report a Source_Attribution_Gate block.
- [ ] AC-13: THE Reminder SHALL instruct recording with `provenance_ledger.py record` and printing the footer only when the operator asks.
- [ ] AC-14: THE Brain_Docs SHALL state that provenance and the 2D verdict are recorded every turn, hidden on the operator's screen by default and shown on request.
- [ ] AC-15: THE Arming_Closure SHALL include `provenance_ledger.py`.
- [ ] AC-16: THE Source_Attribution_Gate SHALL keep accepting a Footer_Line and keep the `no provenance footer` substring in its shown line.

## Residuals

- R-01: The Ledger_File is model-written. It carries the same trust as the footer text it replaces, no more: a model that records a false Basis gets the same quorum a false footer would. Neither is a harness receipt.
- R-02: A subagent's Bash sees the parent's `CLAUDE_CODE_SESSION_ID`, so a `record` run inside a subagent counts for the parent's current turn.
- R-03: The cost of one extra Bash call per turn is accepted; it replaces a footer line in the displayed text.
- R-04: Other docs that describe the footer as printed (README.md, WHITEPAPER.md, docs/wiki/Glossary.md, docs/ANATOMY.md, docs/architecture/hook-orchestration.md, skills/human-cadence/SKILL.md) are not rewritten here; they stay accurate for the back-compat path and are left for a docs pass.
- R-05: `CLAUDE.md` sits at the `claude-md-budget` ceiling (12,000 by the doctor's bound on master), so its edits are token-neutral (11,999 after): the rule lives in the Diagram-first paragraph, and the Reply panel line keeps "any Provenance Basis" without naming the ledger; the full contract is in `skills/4d-paradigm-protocol/SKILL.md`.
