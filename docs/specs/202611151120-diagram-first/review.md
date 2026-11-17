# Code Review: Diagram-First Replies

## Summary

New Stop gate `scripts/g__stop__diagram-first.py` (rule `COMMS.diagram-first`), its 29 fixtures, 32 unit tests, the registry entry, the Stop registration, the friction signature, the CLAUDE.md paragraph, the HOW in `skills/human-cadence/SKILL.md` and the lineage node. The builder doesn't grade its own work: acceptance is the converge verdict below.

## Findings

### 🔴 Critical

None.

### 🟠 Major

None open. Converge pass 1 found that numbered steps followed by indented sub-bullets were not seen as a flow (T08). Commit 71629fc0 fixed it and pinned it with `violation_numbered_nested` and two tests.

### 🟡 Minor

- The status words (`open`, `red`, `green`) also show up in ordinary list prose. Three items like "- the PR is open" block, and so does Spanish "red" meaning network. The Hatch covers a deliberate case. Spec R-01 records the general surface-pattern limit.
- A one-glyph fence (`->`) at the top counts as an Opening_Diagram. The gate checks that a diagram comes first, not how good it is (spec R-02).
- A `**Provenance**:` footer, with the colon after the closing bold, is not stripped as the footer. The sibling `g__stop__no-menu-question.py` uses the same regex.

### 🔵 Info / Suggestions

- `CLAUDE.md` is at 11,997 of its 12,000-token ceiling. The next rule that needs constitution prose has to cut something first.
- The paste-ready exemption loads `_ASK_PASTE` from the sibling gate by file path, so the two cannot drift (spec R-04).

## Convergence

- Pass 1: GAPS on AC-01. Appended `## Convergence 1` with T08.
- Pass 2: CONVERGED. All 15 criteria met, `plan.md` byte-identical.

## Verdict

PASS
