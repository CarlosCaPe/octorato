# Review: v11, No Reply Unreviewed

> **Date:** 2026-10-14
> **Spec:** feature.md (this dir) · **Plan:** plan.md (this dir)
> **Branch:** feat/v11-reply-panel (worktree, not pushed)

Builder's record of what shipped and what was run. It is not a verdict: `sdd-converge` grades this work, not the builder.

## What shipped

| Task | Files |
|---|---|
| T01-T04 | `scripts/g__stop__reply-panel.py` (new), `scripts/panel_fixture_seed.py` (`seed_reply_receipt`) |
| T05 | `registry/fixtures/FLOW.panel-before-reply/` (36 cases: 23 `violation_*`, 13 `benign_*`, each with its transcript) |
| T06 | `registry/rules.yaml` (`FLOW.panel-before-reply`) |
| T07 | `hooks.json` (Stop, timeout 20), `docs/CAPABILITIES.md` (regenerated) |
| T08 | `scripts/brain_doctor.py` (`reply-panel-arm-env`) |
| T09 | `CLAUDE.md` ("Reply panel" bullet), `docs/architecture/v11-reply-panel.md` (new) |
| T10 | this file, plan.md task boxes |

T08 finding: the generic checks already cover the rule (`registry-wiring` for the Stop registration, `registry-anchors` for the anchor, `gate-liveness` for the selftest), so the only doctor addition is the AC-16 warning.

## Acceptance criteria and their proof

| AC | Covered by |
|---|---|
| AC-01 | selftest unit check (digest of reflowed text equal, one changed word differs); `benign_ac01_whitespace_reflow` (receipt seeded on the reflowed text) |
| AC-02 | `benign_ac02_pass_receipt`, `benign_ac02_pass_stop_feedback_last` (isMeta Stop feedback is the newest entry) |
| AC-03 | `violation_ac03_no_receipt` asserts stderr holds the digest, `panel_digest.py --panel-request --to operator`, the reviewer types, and lacks `panel-skip` |
| AC-04 | `violation_ac04_receipt_older_than_prompt`, `violation_ac12_notification_opened_receipt_before_prompt` |
| AC-05 | `violation_ac05_needs_work_newer_than_pass`; control `benign_ac05_needs_work_then_newer_pass` |
| AC-06 | `violation_ac06_text_changed_after_panel` |
| AC-07 | `benign_ac07_skip_in_prompt`, `benign_ac07_skip_after_stop_feedback`; `violation_ac07_skip_in_assistant_text`, `violation_ac07_skip_in_tool_result`, `violation_ac07_skip_in_ismeta` |
| AC-08 | `violation_ac08_stop_active_no_receipt`, `benign_ac08_stop_active_with_receipt` |
| AC-09 | `violation_ac09_transcript_unreadable`, `violation_ac09_ledger_unreadable` (stderr names the error), `violation_ac09_receipts_dir_missing_is_no_receipt` (normal message, no "cannot decide") |
| AC-10 | `benign_ac10_off_switch` (with no transcript at all), `benign_ac10_empty_message`; every case runs with `CLAUDE_CODE_CHILD_SESSION=1`, `violation_ac10_child_session_ignored` names it |
| AC-11 | `benign_ac11_pending_status_line` (asserts the id is recorded as spent), `benign_ac11_spent_still_exempts_while_stop_active`; violations: status over cap, not a panel reviewer, no panel block, block not to operator, completed by notification, completed by tool_result, already spent, panel before the operator prompt, spent ledger unreadable, spent ledger unwritable |
| AC-12 | `benign_ac12_notification_opened_turn`, `benign_ac12_handback_opened_turn` |
| AC-13 | registry proof `scripts/g__stop__reply-panel.py --selftest registry/fixtures/FLOW.panel-before-reply`, output below; run with `OCTO_REPLY_PANEL=off` exported, still PASS |
| AC-14 | doctor negatives below: gate removed from hooks.json, anchor removed, selftest failing |
| AC-15 | `docs/architecture/v11-reply-panel.md`, Residuals table R-01 to R-12 with a source column |
| AC-16 | `check_reply_panel_arm_env` run on a temp HOME, output below |
| AC-17 | selftest unit check (in-process and on a copy of the gate whose send gate lacks `_origin`); tree-copy negative below |

## Validation, verbatim

```
$ python3 scripts/g__stop__reply-panel.py --selftest registry/fixtures/FLOW.panel-before-reply
selftest PASS: 23 block + 13 allow + 2 unit checks (g__stop__reply-panel.py vs FLOW.panel-before-reply)
exit=0

$ OCTO_REPLY_PANEL=off CLAUDE_CODE_CHILD_SESSION=1 python3 scripts/g__stop__reply-panel.py --selftest registry/fixtures/FLOW.panel-before-reply
selftest PASS: 23 block + 13 allow + 2 unit checks (g__stop__reply-panel.py vs FLOW.panel-before-reply)
exit=0

$ python3 scripts/g__pretool-mcp__outward-send.py --selftest registry/fixtures/FLOW.panel-before-send
selftest PASS: 96 block + 34 allow (g__pretool-mcp__outward-send.py vs FLOW.panel-before-send)
exit=0

$ python3 scripts/spec_lint.py docs/specs/202610141340-v11-reply-panel
ok docs\specs\202610141340-v11-reply-panel\feature.md
exit=0

$ python3 scripts/cadence-lint.py --file <CLAUDE.md "Reply panel" line, extracted>
✓ cadence clean [para.md]
exit=0
$ python3 scripts/cadence-lint.py --file docs/architecture/v11-reply-panel.md
✓ cadence clean [docs\architecture\v11-reply-panel.md]
exit=0

$ python3 scripts/check-generic.py        (run before each commit, on the staged files)
✓ check-generic: clean — scanned 72 staged file(s) (loaded 26 tokens from <company>/brain-blocklist.txt)
✓ check-generic: clean — scanned 4 staged file(s) ...
✓ check-generic: clean — scanned 1 staged file(s) ...
✓ check-generic: clean — scanned 1 staged file(s) ...

$ python3 scripts/brain_doctor.py --registry
  [PASS] ✓ registry-wiring             all 92 rules wired (disk + hooks.json)
  [PASS] ✓ registry-anchors            all rule anchors present in their source file
  [PASS] ✓ registry-coverage           Coverage 100% of CLAUDE.md anchors (43/43); 0 prose anchors unwired
  [PASS] ✓ registry-naming             26 grandfathered; new hook scripts follow the canonical scheme
  [PASS] ✓ registry-orphans            all 52 live hooks claimed by a registry rule
  [PASS] ✓ claude-md-budget            11,702 tokens (per-piece bound, ceiling 12,000); every section reads as English
  11 passed, 0 warn, 0 fail
```

`brain_doctor.py --fast` (exit 1), the lines that are not PASS:

```
  [WARN] ! incident-fixture-coverage      memory layer absent on this machine, skipped
  [WARN] ! reflex-triage                  memory layer absent on this machine, skipped
  [FAIL] ✗ hooks-merge-fresh              1 hooks.json command(s) reference missing file(s): <HOME>\.claude\scripts\g__stop__reply-panel.py
  [WARN] ! cursor-hooks-sync              ~/.cursor/hooks.json drifted from hooks.json
  [FAIL] ✗ connectome-fresh               neural_map.json missing
  [WARN] ! arms-config                    company/config/arms-paths.json absent (gitignored/optional)
  [WARN] ! sync-targets                   arms-paths.json absent — skipping sync-target verification
  [WARN] ! blocklist                      company/brain-blocklist.txt absent — generic-check soft-fails open
  [WARN] ! finops-enforcement             budgets.yaml absent — per-arm budget caps are NOT enforced (FinOps off)
  [WARN] ! spec-contract                  3 spec(s) say converged with no CONVERGED receipt on this machine: ...
  30 passed, 8 warn, 2 fail
```

Both FAILs belong to running the doctor inside a worktree, not to this change. `connectome-fresh` failed the same way on the untouched branch before T01 (baseline run: 30 passed, 8 warn, 1 fail). `hooks-merge-fresh` resolves `~/.claude/scripts/...` against the live copy, which does not have the new script until the branch is merged and synced; the worktree has it. `reply-panel-arm-env` reads PASS here because the worktree has no `company/` directory.

## Negative tests

The selftest fails when one fixture's expected code is flipped, in each direction, and passes again once restored:

```
$ mv benign_ac02_pass_receipt.json violation_ac02_pass_receipt.json   # expected code flipped from 0 to 2
$ python3 scripts/g__stop__reply-panel.py --selftest registry/fixtures/FLOW.panel-before-reply
selftest FAIL: 24 block + 12 allow (g__stop__reply-panel.py vs FLOW.panel-before-reply): violation_ac02_pass_receipt.json: exit 0, want 2 (); violation_ac02_pass_receipt.json: blocked but nothing journaled under FLOW.panel-before-reply
exit=1
$ mv back; python3 scripts/g__stop__reply-panel.py --selftest registry/fixtures/FLOW.panel-before-reply
selftest PASS: 23 block + 13 allow + 2 unit checks (g__stop__reply-panel.py vs FLOW.panel-before-reply)
exit=0
$ git status --short registry/fixtures/FLOW.panel-before-reply
(empty = restored)
$ mv violation_ac07_skip_in_ismeta.json benign_ac07_skip_in_ismeta.json   # expected code flipped from 2 to 0
selftest FAIL: 22 block + 14 allow (g__stop__reply-panel.py vs FLOW.panel-before-reply): benign_ac07_skip_in_ismeta.json: exit 2, want 0 (REPLY PANEL (FLOW.panel-before-reply): this reply has no PASS panel receipt for its exact text, newer than the operator's prompt. Digest: e02164c77a22413446c755)
exit=1
(empty = restored)
```

AC-17, on a temp copy of `scripts/` and `registry/` whose send gate has `def _origin(` renamed:

```
$ python3 <copy>/scripts/g__stop__reply-panel.py --selftest registry/fixtures/FLOW.panel-before-reply
selftest FAIL: 23 block + 13 allow (g__stop__reply-panel.py vs FLOW.panel-before-reply): live send gate: send gate helper missing: _origin (in scripts/g__pretool-mcp__outward-send.py); violation_ac03_no_receipt.json: stderr lacks 'e02164c77a22413446c75573a9a3e1e328c5541a18235d27c5e3221d4e8c243b'; ...
exit=1
$ echo <Stop payload> | python3 <copy>/scripts/g__stop__reply-panel.py
REPLY PANEL (FLOW.panel-before-reply) cannot decide: send gate helper missing: _origin (in scripts/g__pretool-mcp__outward-send.py)
exit=2
```

AC-14, each condition broken in the worktree, checked, then restored with `git checkout` or `mv`:

```
## (a) gate removed from hooks.json Stop list
  [FAIL] ✗ registry-wiring             FLOW.panel-before-reply: g__stop__reply-panel.py not in hooks.json at Stop|*
## (b) "Reply panel" anchor removed from CLAUDE.md
  [FAIL] ✗ registry-anchors            FLOW.panel-before-reply: anchor 'Reply panel' absent in CLAUDE.md
## (c) selftest failing (one fixture flipped), run through the doctor gate-liveness runner
gate-liveness proof FLOW.panel-before-reply: scripts/g__stop__reply-panel.py --selftest registry/fixtures/FLOW.panel-before-reply -> exit 1: selftest FAIL: 24 block + 12 allow ...
exit=1
## restored: all three
  [PASS] ✓ registry-wiring             all 92 rules wired (disk + hooks.json)
  [PASS] ✓ registry-anchors            all rule anchors present in their source file
gate-liveness proof FLOW.panel-before-reply: scripts/g__stop__reply-panel.py --selftest registry/fixtures/FLOW.panel-before-reply -> exit 0: selftest PASS: 23 block + 13 allow + 2 unit checks (g__stop__reply-panel.py vs FLOW.panel-before-reply)
exit=0
(empty = restored)
```

The full `gate-liveness` check was not run: it writes the gate receipt into the live ledger under `~/.claude/.cache/receipts`. The runner above is the same `_run_selftest_locator` it calls.

AC-16, `check_reply_panel_arm_env` against a temp HOME with three settings files (`arm-a` sets the switch, `arm-b` does not, `not-an-arm` sets it but is not listed):

```
with hit: WARN 1 arm settings file(s) set OCTO_REPLY_PANEL in env: <tmp-home>\arm-a\.claude\settings.local.json
no hit:   PASS no arm settings file sets OCTO_REPLY_PANEL (1 scanned)
absent:   PASS arms-paths.json absent; no arm settings scanned
AC-16 PASS
exit=0
```

## Panel latency (R-06)

One measured run, 2026-10-14: a Reality Checker subagent (background) reviewing a 26-word reply to the operator with three checkable claims, block from `panel_digest.py --panel-request --to operator` (exit 0, digest `8870b3c2...4077`). Harness task notification: `duration_ms` 72969 (73 s), 5 tool uses, 84,736 subagent tokens; verdict `PANEL-VERDICT: PASS` for that digest. One sample, not a distribution; a reply whose claims need no command runs would cost less.

## Not done here

- No push, no PR, no merge (out of the builder's scope). The live copy does not run the gate until the branch is merged and `ai-pull` syncs it.
- The Stop-hook behaviour inside a real Claude Code session was not exercised: the gate is proven on fixtures shaped from the measured transcript fields, not on a live stop.
