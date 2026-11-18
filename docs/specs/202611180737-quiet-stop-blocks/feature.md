# Feature: Quiet Stop Blocks

> **Status:** draft
> **Spec-Format:** ears-1
> **Date:** 2026-11-18
> **Classification:** LARGE (score 8: 10+ files, behavior change of live gates)

Release v12 moved advisory `systemMessage` text off the operator's screen. What still floods the terminal are Stop hook block reasons: Claude Code prints the full reason of every Stop hook that blocks, and some reasons run past 150 words (the reply panel's `REPLY PANEL (FLOW.panel-before-reply)` message). The operator should see one short line per block; the model must still get the full instructions.

## Step 0 finding (native channel)

Source: https://code.claude.com/docs/en/hooks, section "Stop decision control" (read 2026-11-18, Claude Code 2.1.327 installed). On Stop, `decision: "block"` needs `reason`, which "Tells Claude why it should continue"; exit 2 routes stderr the same way. `hookSpecificOutput.additionalContext` keeps the conversation going too, but "it is shown in the transcript as hook feedback rather than a hook error". `systemMessage` is a "Warning message shown to the user" and `suppressOutput` "Has no effect". No documented field reaches the model on Stop while staying off the screen, so the split is built with a detail ledger file.

## Summary

Every blocking Stop gate prints its reason through one library. The library writes the gate's full text to a per-session Detail_File and returns one Shown_Line that names it. When the write fails, the library returns the full text, so a block never loses its instructions. Decision logic is untouched.

## Glossary

- **Stop_Block_Lib**: `scripts/stop_block.py`, function `shown(gate, short, full, payload, rule)`.
- **Blocking_Gates**: the Stop hooks in `hooks.json` that can block: `cadence-stop-hook.py`, `g__stop__draft-promise.py`, `g__stop__unsourced-attribute.py`, `g__stop__unsourced-absence.py`, `g__stop__paste-ready-raw.py`, `g__stop__defer-today.py`, `g__stop__no-menu-question.py`, `g__stop__diagram-first.py`, `source-attribution-check.py`, `claim-verify-stop.py`, `g__stop__delegation-audit.py`, `d__stop__wa-guardia.py`, `g__stop__goal-anchor.py` (JSON block) and `g__stop__reply-panel.py` (exit 2 + stderr).
- **Non_Blocking_Stop_Hooks**: `trace-hook.py`, `no-pause-suggestion.py`, `grafo-ledger-check.py`, `r__stop__friction-ledger.py`.
- **Full_Reason**: the reason text a gate printed before this change, unchanged.
- **Shown_Line**: the reason the gate prints: the gate tag plus the measured fact, then ` · detail: <absolute path>`, one line of at most `WORD_CAP` (25) whitespace-split words.
- **Detail_Ledger**: `~/.claude/.cache/stop-blocks/<session>/` (gitignored by `.cache/`), `OCTO_STOP_BLOCK_DIR` overrides the root for tests.
- **Detail_File**: `<Detail_Ledger>/<gate>.txt`, a header (gate, rule, session, ts) and the Full_Reason; plus one `blocks.jsonl` row per block.
- **Friction_Signatures**: `registry/friction-signatures.json`, the patterns that attribute a block to a reason code.
- **Split_Test**: `scripts/tests/test_stop_block.py`.

## Functional Requirements

### FR-01: One line on screen

Each Blocking_Gate prints a Shown_Line in place of its Full_Reason.

### FR-02: Full text for the model

Before the Shown_Line is returned, the Full_Reason is written to the Detail_File and read back.

### FR-03: Never weaker

A failed write or read-back returns the Full_Reason. Decision logic, block-once behavior, fail-open and fail-closed paths and kernel journaling stay as they were.

### FR-04: Attribution survives

Each Shown_Line keeps the substring its Friction_Signatures row matches (`CADENCE on your reply`, `SIN-MENÚ`, `DIAGRAM-FIRST`, `⚓ ANCLA`, `GUARDIA SIN ARMAR`, `no provenance footer`, `claimed verified/done`, `TOTAL coverage`, `ATRIBUTO-SIN-FUENTE`, `AUSENCIA-SIN-BÚSQUEDA`, `HOY-NO-MAÑANA`, `bulk-fetch-delegation`).

## Acceptance Criteria

- [ ] AC-01: WHEN a Blocking_Gate blocks, THE Blocking_Gates SHALL print a Shown_Line of one line and at most 25 words.
- [ ] AC-02: WHEN a Blocking_Gate blocks, THE Detail_File SHALL hold the Full_Reason byte for byte at the path the Shown_Line names.
- [ ] AC-03: IF the Detail_Ledger cannot be written or read back, THEN THE Stop_Block_Lib SHALL return the Full_Reason.
- [ ] AC-04: THE Blocking_Gates SHALL keep every block and allow verdict of their `--selftest` fixtures.
- [ ] AC-05: WHEN the reply panel blocks on missing receipts, THE Shown_Line SHALL read `REPLY PANEL <have>/<need> (<class>)` followed by the detail path.
- [ ] AC-06: THE Stop_Block_Lib SHALL map a session id to a directory name of letters, digits, `_`, `.` and `-` only, so no payload escapes the Detail_Ledger root.
- [ ] AC-07: THE Split_Test SHALL fail when a Stop hook in `hooks.json` is neither a Blocking_Gate nor a Non_Blocking_Stop_Hook.
- [ ] AC-08: THE Blocking_Gates SHALL keep the Friction_Signatures substring of FR-04 in their Shown_Line.

## Supersedes

- `docs/specs/202611172031-diagram-always/` AC-08: the phrase "flow first; text short and in bullets; ..." now lives in the Detail_File; the Shown_Line carries `DIAGRAM-FIRST` and the measured fact.
- `docs/specs/202610141340-v11-reply-panel/`: the reply panel's stderr text assertions (`stderr_has` / `stderr_lacks` in its fixtures) now run on the Detail_File; the shown stderr is held to one line.

## Residuals

- R-01: The model must open the Detail_File to get the instructions. A model that acts on the Shown_Line alone gets the tag, the fact and the path, not the full how-to.
- R-02: `panel_preflight.py` runs the Stop gates on drafts with no session id, so its blocks land in `<Detail_Ledger>/adhoc/` and overwrite each other's latest file there; `blocks.jsonl` keeps every row.
- R-03: The display behavior of a block reason is not measured in the TUI here; the change rests on the operator's report that full reasons reach his screen and on the docs cited in Step 0.
- R-04: The Detail_File of a gate holds only its latest block per session; earlier ones stay in `blocks.jsonl`, which grows until its session directory is pruned after 7 days.
