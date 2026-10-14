# Review: v11, No Reply Unreviewed

> **Date:** 2026-10-14
> **Spec:** feature.md (this dir) · **Plan:** plan.md (this dir)
> **Branch:** feat/v11-reply-panel (worktree, not pushed)

Builder's record of what shipped and what was run. It is not a verdict: `sdd-converge` grades this work, not the builder.

## What shipped

| Task | Files |
|---|---|
| T01-T04 | `scripts/g__stop__reply-panel.py` (new), `scripts/panel_fixture_seed.py` (`seed_reply_receipt`) |
| T05 | `registry/fixtures/FLOW.panel-before-reply/` (75 cases: 57 `violation_*`, 18 `benign_*`, each with its transcript; 6 added by Convergence 1, 12 by FR-06, 11 by Convergence 2, 10 by Convergence 3) |
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

## Convergence 1 (T11 to T13 and the operator decisions)

| Item | Change | Proof |
|---|---|---|
| T11 [AC-07] | none in the gate; new fixture | `violation_ac07_skip_only_in_reply`; mutation `skip_also_in_msg` killed |
| T12 [AC-09] | `_fixture` receipts take `corrupt_report`, which makes `receipt_ledger.report_at` raise TypeError past the readability check | `violation_ac09_ledger_raises` asserts stderr `receipt ledger raised: TypeError`; mutation `ledger_raise_swallowed` killed |
| T13 [AC-16] | `scripts/tests/test_reply_panel_arm_env.py` (3 tests, temp HOME, `brain_doctor.HOME` patched) | unittest output below |
| (a) absent reply key | exit 2, "payload has no last_assistant_message"; empty string still exits 0; a non-string value also exits 2 | `violation_ac10_payload_without_message`, `benign_ac10_empty_message`; mutation `absent_is_empty` killed |
| (b) unknown origin kind | ends the walk with no prompt (exit 2) | `violation_ac12_unknown_origin_ends_walk`; mutation `unknown_origin_skipped` killed |
| (c) strictly newer | receipt `verdict_ts` equal to the prompt's exits 2 | `violation_ac04_receipt_equal_to_prompt`; mutation `receipt_time_ge` killed |
| extra | a mutation run by the converge (`operator_opener_any`, accept any human-kind entry) survived; new fixture with the skip word in a human entry missing its `uuid` | `violation_ac07_skip_in_forged_human_entry`; mutation killed |
| R-11 | feature.md and the architecture doc add that a spent id re-exempts a second status stop in the same operator turn while `stop_hook_active` is true | text |

```
$ python3 scripts/g__stop__reply-panel.py --selftest registry/fixtures/FLOW.panel-before-reply
selftest PASS: 29 block + 13 allow + 2 unit checks (g__stop__reply-panel.py vs FLOW.panel-before-reply)
exit=0

$ python3 scripts/g__pretool-mcp__outward-send.py --selftest registry/fixtures/FLOW.panel-before-send
selftest PASS: 96 block + 34 allow (g__pretool-mcp__outward-send.py vs FLOW.panel-before-send)
exit=0

$ python3 scripts/brain_doctor.py --registry
  [PASS] ✓ registry-bootstrap          rules.yaml loads (92 rules); pre-push gate present
  [PASS] ✓ registry-schema             rules.yaml valid vs schema
  [PASS] ✓ registry-wiring             all 92 rules wired (disk + hooks.json)
  [PASS] ✓ registry-anchors            all rule anchors present in their source file
  [PASS] ✓ registry-coverage           Coverage 100% of CLAUDE.md anchors (43/43); 0 prose anchors unwired
  [PASS] ✓ registry-anchor-ambiguity   every registered anchor maps to exactly one anchor line, unshadowed
  [PASS] ✓ registry-failclosed         every gateable rule is fail-closed (zero left at model discretion)
  [PASS] ✓ registry-gateable-coverage  every gate-shaped rule carries an explicit gateable flag
  [PASS] ✓ registry-naming             26 grandfathered; new hook scripts follow the canonical scheme
  [PASS] ✓ registry-orphans            all 52 live hooks claimed by a registry rule
  [PASS] ✓ claude-md-budget            11,702 tokens (per-piece bound, ceiling 12,000); every section reads as English
  11 passed, 0 warn, 0 fail
exit=0

$ python3 scripts/spec_lint.py docs/specs/202610141340-v11-reply-panel
ok docs\specs\202610141340-v11-reply-panel\feature.md
exit=0

$ python3 -m unittest scripts/tests/test_reply_panel_arm_env.py -v
test_listed_arm_that_sets_the_switch_is_named ... ok
test_no_arms_file_scans_nothing ... ok
test_unlisted_directory_is_not_scanned ... ok

----------------------------------------------------------------------
Ran 3 tests in 0.046s

OK
exit=0

$ python3 scripts/cadence-lint.py --file docs/architecture/v11-reply-panel.md
✓ cadence clean [docs\architecture\v11-reply-panel.md]
exit=0
```

Mutations, each applied to a temp copy of `scripts/` and `registry/`, never to the worktree:

```
$ python3 <scratch>/mutate_c1.py <worktree>   # each mutation on a temp copy of scripts/ + registry/
skip_also_in_msg: selftest exit 1 -> KILLED :: violation_ac07_skip_only_in_reply.json: exit 0, want 2 ()
ledger_raise_swallowed: selftest exit 1 -> KILLED :: violation_ac09_ledger_raises.json: stderr lacks 'receipt ledger raised: TypeError'
receipt_time_ge: selftest exit 1 -> KILLED :: violation_ac04_receipt_equal_to_prompt.json: exit 0, want 2 ()
absent_is_empty: selftest exit 1 -> KILLED :: violation_ac10_payload_without_message.json: exit 0, want 2 ()
unknown_origin_skipped: selftest exit 1 -> KILLED :: violation_ac12_unknown_origin_ends_walk.json: exit 0, want 2 ()
operator_opener_any: selftest exit 1 -> KILLED :: violation_ac07_skip_in_forged_human_entry.json: exit 0, want 2 ()
6/6 mutations killed
exit=0
```

## FR-06

| Task | Change | Proof |
|---|---|---|
| T14 | `receipt_ledger.panel_receipts_for` holds the per-receipt validation and returns every validated receipt, deciding first; `panel_latest_for` returns its first entry. The gate reads the Source_Class from the last Provenance / Procedencia / Herkunft line and counts distinct PASS reviewer agent ids newer than the prompt, with a PASS deciding. stderr names the class and "it has N of Q". | send gate selftest unchanged at 96 block + 34 allow |
| T15 | 12 fixtures; the 42 earlier cases now carry a sourced footer (`Basis: migration.log, row_counts.csv`), since they test other criteria. | see the AC table below |
| T16 | Architecture doc: the quorum rule, how the class is read, R-13. CLAUDE.md "Reply panel" bullet names the quorum; claude-md-budget 11,724 of 12,000. | cadence-lint and doctor below |

| AC | Fixtures |
|---|---|
| AC-18 | `violation_ac18_self_one_reviewer`, `violation_ac18_self_two_reviewers`, `violation_ac18_self_one_reviewer_recorded_three_times` (one reviewer, three ledger rows), `violation_ac18_self_es_razonamiento_propio`, `violation_ac18_self_de_eigene_ueberlegung`; stderr asserts "is SELF (source class)", "from 3 distinct reviewer(s)", "it has N of 3", and lacks `panel-skip` |
| AC-19 | `benign_ac19_self_three_reviewers`; `violation_ac19_self_three_but_needs_work_decides` (a NEEDS-WORK newer than the three PASS) |
| AC-20 | `benign_ac20_sourced_one_reviewer`, `benign_ac20_sourced_bold_label_one_reviewer` |
| AC-21 | `violation_ac21_no_footer_is_self`, `violation_ac21_no_basis_field_is_self`; `benign_ac21_no_footer_three_reviewers` |

`scripts/tests/test_panel_receipt.py` (the ledger's own tests) gives 43 tests, 1 failure and 2 errors, all in `BridgeArgs` (bash word splitting and `~` expansion of the support-bridge reader on this Windows host). The same three fail with HEAD's `receipt_ledger.py` and gate restored in a temp copy, so they predate this change and touch no panel reader.

```
$ python3 scripts/g__stop__reply-panel.py --selftest registry/fixtures/FLOW.panel-before-reply
selftest PASS: 37 block + 17 allow + 2 unit checks (g__stop__reply-panel.py vs FLOW.panel-before-reply)
exit=0

$ python3 scripts/g__pretool-mcp__outward-send.py --selftest registry/fixtures/FLOW.panel-before-send
selftest PASS: 96 block + 34 allow (g__pretool-mcp__outward-send.py vs FLOW.panel-before-send)
exit=0

$ python3 scripts/brain_doctor.py --registry
  [PASS] ✓ registry-bootstrap          rules.yaml loads (92 rules); pre-push gate present
  [PASS] ✓ registry-schema             rules.yaml valid vs schema
  [PASS] ✓ registry-wiring             all 92 rules wired (disk + hooks.json)
  [PASS] ✓ registry-anchors            all rule anchors present in their source file
  [PASS] ✓ registry-coverage           Coverage 100% of CLAUDE.md anchors (43/43); 0 prose anchors unwired
  [PASS] ✓ registry-anchor-ambiguity   every registered anchor maps to exactly one anchor line, unshadowed
  [PASS] ✓ registry-failclosed         every gateable rule is fail-closed (zero left at model discretion)
  [PASS] ✓ registry-gateable-coverage  every gate-shaped rule carries an explicit gateable flag
  [PASS] ✓ registry-naming             26 grandfathered; new hook scripts follow the canonical scheme
  [PASS] ✓ registry-orphans            all 52 live hooks claimed by a registry rule
  [PASS] ✓ claude-md-budget            11,724 tokens (per-piece bound, ceiling 12,000); every section reads as English
  11 passed, 0 warn, 0 fail
exit=0

$ python3 scripts/spec_lint.py docs/specs/202610141340-v11-reply-panel
ok docs\specs\202610141340-v11-reply-panel\feature.md
exit=0

$ python3 -m unittest scripts/tests/test_reply_panel_arm_env.py -v
test_listed_arm_that_sets_the_switch_is_named ... ok
test_no_arms_file_scans_nothing ... ok
test_unlisted_directory_is_not_scanned ... ok

----------------------------------------------------------------------
Ran 3 tests in 0.047s

OK
exit=0

$ python3 scripts/cadence-lint.py --file docs/architecture/v11-reply-panel.md
✓ cadence clean [docs\architecture\v11-reply-panel.md]
exit=0
$ python3 scripts/cadence-lint.py --file <CLAUDE.md "Reply panel" line, extracted>
✓ cadence clean [<scratch>/para2.md]
exit=0
```

Mutations, each applied to a temp copy of `scripts/` and `registry/`; the four the coordinator named first, then the Convergence 1 set re-checked on the refactored code:

```
$ python3 <scratch>/mutate_fr06.py <worktree>   # each mutation on a temp copy of scripts/ + registry/
quorum_hardcoded_1: selftest exit 1 -> KILLED :: violation_ac18_self_de_eigene_ueberlegung.json: exit 0, want 2 ()
distinct_id_dropped: selftest exit 1 -> KILLED :: violation_ac18_self_one_reviewer_recorded_three_times.json: exit 0, want 2 ()
sourced_as_self: selftest exit 1 -> KILLED :: benign_ac01_whitespace_reflow.json: exit 2, want 0 (REPLY PANEL (FLOW.panel-before-reply): this reply is SELF (source class) and needs PASS receipts f
missing_footer_as_sourced: selftest exit 1 -> KILLED :: violation_ac21_no_footer_is_self.json: exit 0, want 2 ()
missing_basis_as_sourced: selftest exit 1 -> KILLED :: violation_ac21_no_basis_field_is_self.json: exit 0, want 2 ()
deciding_receipt_ignored: selftest exit 1 -> KILLED :: violation_ac05_needs_work_newer_than_pass.json: exit 0, want 2 ()
skip_also_in_msg: selftest exit 1 -> KILLED :: violation_ac07_skip_only_in_reply.json: exit 0, want 2 ()
ledger_raise_swallowed: selftest exit 1 -> KILLED :: violation_ac09_ledger_raises.json: stderr lacks 'receipt ledger raised: TypeError'
receipt_time_ge: selftest exit 1 -> KILLED :: violation_ac04_receipt_equal_to_prompt.json: exit 0, want 2 ()
absent_is_empty: selftest exit 1 -> KILLED :: violation_ac10_payload_without_message.json: exit 0, want 2 ()
unknown_origin_skipped: selftest exit 1 -> KILLED :: violation_ac12_unknown_origin_ends_walk.json: exit 0, want 2 ()
operator_opener_any: selftest exit 1 -> KILLED :: violation_ac07_skip_in_forged_human_entry.json: exit 0, want 2 ()
12/12 mutations killed
exit=0
```

## Convergence 2

| Task | Change | Proof |
|---|---|---|
| T17 [AC-18] | fixtures only | `violation_ac18_self_three_one_pass_older_than_prompt` and `violation_ac18_self_three_one_older_needs_work`, both "it has 2 of 3"; mutations `newer_filter_dropped` and `pass_filter_dropped` killed |
| T18, T19 [AC-18, AC-21] | `source_class` follows the refined glossary: every provenance line is read and any SELF one wins; `self` is a case-insensitive substring; a Basis of only `none`, `n/a` or `-` is SELF | `violation_ac21_basis_myself`, `_basis_self_evident`, `_basis_path_with_self`, `_self_line_then_sourced_line`, `_sourced_line_in_code_block_after_self_footer`, `_basis_none`, `_basis_na`, `_basis_dash`, each "it has 1 of 3"; `benign_ac20_two_sourced_lines_one_reviewer` keeps two SOURCED lines at quorum 1; mutations `word_bounded_self`, `last_line_only`, `none_basis_sourced` killed |
| T20 [AC-05] | `receipt_ledger.panel_receipts_for`: a PASS whose `_anchor_stands` raises counts as not standing | `test_anchor_check_that_raises_counts_as_not_standing` in `scripts/tests/test_panel_receipt.py`; with the try/except removed on a temp copy it errors with the TypeError it injects; the send gate stays at 96 block + 34 allow and the sent-ledger selftest passes |

Docs: the architecture doc and the CLAUDE.md "Reply panel" bullet describe the safe reading (claude-md-budget 11,724 of 12,000).

```
$ python3 scripts/g__stop__reply-panel.py --selftest registry/fixtures/FLOW.panel-before-reply
selftest PASS: 47 block + 18 allow + 2 unit checks (g__stop__reply-panel.py vs FLOW.panel-before-reply)
exit=0

$ python3 scripts/g__pretool-mcp__outward-send.py --selftest registry/fixtures/FLOW.panel-before-send
selftest PASS: 96 block + 34 allow (g__pretool-mcp__outward-send.py vs FLOW.panel-before-send)
exit=0

$ python3 scripts/r__posttool__sent-ledger.py --selftest registry/fixtures/FLOW.sent-message-ledger
selftest PASS: 4 case(s) (r__posttool__sent-ledger.py vs FLOW.sent-message-ledger)
exit=0

$ python3 scripts/brain_doctor.py --registry
  [PASS] ✓ registry-bootstrap          rules.yaml loads (92 rules); pre-push gate present
  [PASS] ✓ registry-schema             rules.yaml valid vs schema
  [PASS] ✓ registry-wiring             all 92 rules wired (disk + hooks.json)
  [PASS] ✓ registry-anchors            all rule anchors present in their source file
  [PASS] ✓ registry-coverage           Coverage 100% of CLAUDE.md anchors (43/43); 0 prose anchors unwired
  [PASS] ✓ registry-anchor-ambiguity   every registered anchor maps to exactly one anchor line, unshadowed
  [PASS] ✓ registry-failclosed         every gateable rule is fail-closed (zero left at model discretion)
  [PASS] ✓ registry-gateable-coverage  every gate-shaped rule carries an explicit gateable flag
  [PASS] ✓ registry-naming             26 grandfathered; new hook scripts follow the canonical scheme
  [PASS] ✓ registry-orphans            all 52 live hooks claimed by a registry rule
  [PASS] ✓ claude-md-budget            11,724 tokens (per-piece bound, ceiling 12,000); every section reads as English
  11 passed, 0 warn, 0 fail
exit=0

$ python3 scripts/spec_lint.py docs/specs/202610141340-v11-reply-panel
ok docs\specs\202610141340-v11-reply-panel\feature.md
exit=0

$ python3 -m unittest scripts/tests/test_reply_panel_arm_env.py -v
test_listed_arm_that_sets_the_switch_is_named ... ok
test_no_arms_file_scans_nothing ... ok
test_unlisted_directory_is_not_scanned ... ok

----------------------------------------------------------------------
Ran 3 tests in 0.042s

OK
exit=0

$ python3 -m unittest scripts.tests.test_panel_receipt.PanelLedger -v   # T20
test_anchor_check_that_raises_counts_as_not_standing ... ok
test_malformed_digest_records_nothing ... ok
test_newest_decides_and_revokes ... ok
test_other_session_and_stale_never_count ... ok
test_receipt_is_single_use ... ok
test_reflex_records_anchored_panel_row ... ok
test_reflex_refuses_stated_digest_that_does_not_recompute ... ok

----------------------------------------------------------------------
Ran 7 tests in 0.388s

OK
exit=0

$ python3 scripts/cadence-lint.py --file docs/architecture/v11-reply-panel.md
✓ cadence clean [docs\architecture\v11-reply-panel.md]
exit=0
$ python3 scripts/cadence-lint.py --file <CLAUDE.md "Reply panel" line, extracted>
✓ cadence clean [<scratch>/para3.md]
exit=0
```

The whole `scripts/tests/test_panel_receipt.py` now runs 44 tests with the same three pre-existing `BridgeArgs` failures recorded under FR-06 and no new one.

Mutations, each applied to a temp copy of `scripts/` and `registry/` (FR-06, Convergence 2 and Convergence 1 sets together):

```
$ python3 <scratch>/mutate_c2.py <worktree>   # each mutation on a temp copy of scripts/ + registry/
quorum_hardcoded_1: selftest exit 1 -> KILLED :: violation_ac18_self_de_eigene_ueberlegung.json: exit 0, want 2 ()
distinct_id_dropped: selftest exit 1 -> KILLED :: violation_ac18_self_one_reviewer_recorded_three_times.json: exit 0, want 2 ()
sourced_as_self: selftest exit 1 -> KILLED :: benign_ac01_whitespace_reflow.json: exit 2, want 0 (REPLY PANEL (FLOW.panel-before-reply): this reply is SELF (source class) and needs PASS receipts f
missing_footer_as_sourced: selftest exit 1 -> KILLED :: violation_ac21_no_footer_is_self.json: exit 0, want 2 ()
missing_basis_as_sourced: selftest exit 1 -> KILLED :: violation_ac21_no_basis_field_is_self.json: exit 0, want 2 ()
deciding_receipt_ignored: selftest exit 1 -> KILLED :: violation_ac05_needs_work_newer_than_pass.json: exit 0, want 2 ()
newer_filter_dropped: selftest exit 1 -> KILLED :: violation_ac18_self_three_one_pass_older_than_prompt.json: exit 0, want 2 ()
pass_filter_dropped: selftest exit 1 -> KILLED :: violation_ac18_self_three_one_older_needs_work.json: exit 0, want 2 ()
word_bounded_self: selftest exit 1 -> KILLED :: violation_ac21_basis_myself.json: exit 0, want 2 ()
last_line_only: selftest exit 1 -> KILLED :: violation_ac21_self_line_then_sourced_line.json: exit 0, want 2 ()
none_basis_sourced: selftest exit 1 -> KILLED :: violation_ac21_basis_dash.json: exit 0, want 2 ()
skip_also_in_msg: selftest exit 1 -> KILLED :: violation_ac07_skip_only_in_reply.json: exit 0, want 2 ()
ledger_raise_swallowed: selftest exit 1 -> KILLED :: violation_ac09_ledger_raises.json: stderr lacks 'receipt ledger raised: TypeError'
receipt_time_ge: selftest exit 1 -> KILLED :: violation_ac04_receipt_equal_to_prompt.json: exit 0, want 2 ()
absent_is_empty: selftest exit 1 -> KILLED :: violation_ac10_payload_without_message.json: exit 0, want 2 ()
unknown_origin_skipped: selftest exit 1 -> KILLED :: violation_ac12_unknown_origin_ends_walk.json: exit 0, want 2 ()
operator_opener_any: selftest exit 1 -> KILLED :: violation_ac07_skip_in_forged_human_entry.json: exit 0, want 2 ()
17/17 mutations killed
exit=0
```

## Convergence 3

| Task | Change | Proof |
|---|---|---|
| T21 [AC-18, AC-21] | fixtures only; the empty-Basis check now lives in one place (`_empty_basis`), so dropping it is one mutation | `violation_ac21_sourced_line_then_self_line`, `_basis_empty`, `_basis_uppercase_self`, `_quoted_self_line_after_sourced_footer`; mutations `first_line_only`, `empty_basis_dropped`, `ignorecase_dropped`, `quote_tolerance_dropped` killed |
| T22 [AC-21] | `_empty_basis`: after lower-casing and stripping blanks and trailing punctuation, `none`, `nothing`, `n/a`, `na` or a run of hyphens, en dashes or em dashes; `eigene Ueberlegung` joins the self markers | `violation_ac21_basis_none_period`, `_basis_em_dash`, `_basis_double_hyphen`, `_basis_nothing`, `_basis_uppercase_na`, `_basis_eigene_ueberlegung`; mutations `trailing_punct_kept`, `em_dash_dropped`, `hyphen_run_dropped`, `nothing_dropped`, `na_dropped`, `ueberlegung_dropped` killed |

The `NA` fixture is named `basis_uppercase_na`: `basis_NA` and the existing `basis_na` are the same file name on a case-insensitive file system, and the first generation overwrote one with the other (74 instead of 75 cases), caught by the case count.

```
$ python3 scripts/g__stop__reply-panel.py --selftest registry/fixtures/FLOW.panel-before-reply
selftest PASS: 57 block + 18 allow + 2 unit checks (g__stop__reply-panel.py vs FLOW.panel-before-reply)
exit=0

$ python3 scripts/g__pretool-mcp__outward-send.py --selftest registry/fixtures/FLOW.panel-before-send
selftest PASS: 96 block + 34 allow (g__pretool-mcp__outward-send.py vs FLOW.panel-before-send)
exit=0

$ python3 scripts/r__posttool__sent-ledger.py --selftest registry/fixtures/FLOW.sent-message-ledger
selftest PASS: 4 case(s) (r__posttool__sent-ledger.py vs FLOW.sent-message-ledger)
exit=0

$ python3 scripts/brain_doctor.py --registry
  [PASS] ✓ registry-bootstrap          rules.yaml loads (92 rules); pre-push gate present
  [PASS] ✓ registry-schema             rules.yaml valid vs schema
  [PASS] ✓ registry-wiring             all 92 rules wired (disk + hooks.json)
  [PASS] ✓ registry-anchors            all rule anchors present in their source file
  [PASS] ✓ registry-coverage           Coverage 100% of CLAUDE.md anchors (43/43); 0 prose anchors unwired
  [PASS] ✓ registry-anchor-ambiguity   every registered anchor maps to exactly one anchor line, unshadowed
  [PASS] ✓ registry-failclosed         every gateable rule is fail-closed (zero left at model discretion)
  [PASS] ✓ registry-gateable-coverage  every gate-shaped rule carries an explicit gateable flag
  [PASS] ✓ registry-naming             26 grandfathered; new hook scripts follow the canonical scheme
  [PASS] ✓ registry-orphans            all 52 live hooks claimed by a registry rule
  [PASS] ✓ claude-md-budget            11,724 tokens (per-piece bound, ceiling 12,000); every section reads as English
  11 passed, 0 warn, 0 fail
exit=0

$ python3 scripts/spec_lint.py docs/specs/202610141340-v11-reply-panel
ok docs\specs\202610141340-v11-reply-panel\feature.md
exit=0

$ python3 -m unittest scripts/tests/test_reply_panel_arm_env.py -v
test_listed_arm_that_sets_the_switch_is_named ... ok
test_no_arms_file_scans_nothing ... ok
test_unlisted_directory_is_not_scanned ... ok

----------------------------------------------------------------------
Ran 3 tests in 0.054s

OK
exit=0

$ python3 -m unittest scripts.tests.test_panel_receipt.PanelLedger -v
test_anchor_check_that_raises_counts_as_not_standing ... ok
test_malformed_digest_records_nothing ... ok
test_newest_decides_and_revokes ... ok
test_other_session_and_stale_never_count ... ok
test_receipt_is_single_use ... ok
test_reflex_records_anchored_panel_row ... ok
test_reflex_refuses_stated_digest_that_does_not_recompute ... ok

----------------------------------------------------------------------
Ran 7 tests in 0.457s

OK
exit=0

$ python3 scripts/cadence-lint.py --file docs/architecture/v11-reply-panel.md
✓ cadence clean [docs\architecture\v11-reply-panel.md]
exit=0
$ python3 scripts/cadence-lint.py --file <CLAUDE.md "Reply panel" line, extracted>
✓ cadence clean [<scratch>/para4.md]
exit=0
```

The whole `scripts/tests/test_panel_receipt.py`: 44 tests, the same three pre-existing `BridgeArgs` failures, no new one.

Mutations, each applied to a temp copy of `scripts/` and `registry/` (every set so far):

```
$ python3 <scratch>/mutate_c3.py <worktree>   # each mutation on a temp copy of scripts/ + registry/
quorum_hardcoded_1: selftest exit 1 -> KILLED :: violation_ac18_self_de_eigene_ueberlegung.json: exit 0, want 2 ()
distinct_id_dropped: selftest exit 1 -> KILLED :: violation_ac18_self_one_reviewer_recorded_three_times.json: exit 0, want 2 ()
sourced_as_self: selftest exit 1 -> KILLED :: benign_ac01_whitespace_reflow.json: exit 2, want 0 (REPLY PANEL (FLOW.panel-before-reply): this reply is SELF (source class) and needs PASS receipts f
missing_footer_as_sourced: selftest exit 1 -> KILLED :: violation_ac21_no_footer_is_self.json: exit 0, want 2 ()
missing_basis_as_sourced: selftest exit 1 -> KILLED :: violation_ac21_no_basis_field_is_self.json: exit 0, want 2 ()
deciding_receipt_ignored: selftest exit 1 -> KILLED :: violation_ac05_needs_work_newer_than_pass.json: exit 0, want 2 ()
newer_filter_dropped: selftest exit 1 -> KILLED :: violation_ac18_self_three_one_pass_older_than_prompt.json: exit 0, want 2 ()
pass_filter_dropped: selftest exit 1 -> KILLED :: violation_ac18_self_three_one_older_needs_work.json: exit 0, want 2 ()
word_bounded_self: selftest exit 1 -> KILLED :: violation_ac21_basis_myself.json: exit 0, want 2 ()
last_line_only: selftest exit 1 -> KILLED :: violation_ac21_self_line_then_sourced_line.json: exit 0, want 2 ()
none_basis_sourced: selftest exit 1 -> KILLED :: violation_ac21_basis_dash.json: exit 0, want 2 ()
first_line_only: selftest exit 1 -> KILLED :: violation_ac21_quoted_self_line_after_sourced_footer.json: exit 0, want 2 ()
empty_basis_dropped: selftest exit 1 -> KILLED :: violation_ac21_basis_empty.json: exit 0, want 2 ()
ignorecase_dropped: selftest exit 1 -> KILLED :: violation_ac21_basis_uppercase_self.json: exit 0, want 2 ()
quote_tolerance_dropped: selftest exit 1 -> KILLED :: violation_ac21_quoted_self_line_after_sourced_footer.json: exit 0, want 2 ()
trailing_punct_kept: selftest exit 1 -> KILLED :: violation_ac21_basis_none_period.json: exit 0, want 2 ()
em_dash_dropped: selftest exit 1 -> KILLED :: violation_ac21_basis_em_dash.json: exit 0, want 2 ()
hyphen_run_dropped: selftest exit 1 -> KILLED :: violation_ac21_basis_double_hyphen.json: exit 0, want 2 ()
nothing_dropped: selftest exit 1 -> KILLED :: violation_ac21_basis_nothing.json: exit 0, want 2 ()
na_dropped: selftest exit 1 -> KILLED :: violation_ac21_basis_uppercase_na.json: exit 0, want 2 ()
ueberlegung_dropped: selftest exit 1 -> KILLED :: violation_ac21_basis_eigene_ueberlegung.json: exit 0, want 2 ()
skip_also_in_msg: selftest exit 1 -> KILLED :: violation_ac07_skip_only_in_reply.json: exit 0, want 2 ()
ledger_raise_swallowed: selftest exit 1 -> KILLED :: violation_ac09_ledger_raises.json: stderr lacks 'receipt ledger raised: TypeError'
receipt_time_ge: selftest exit 1 -> KILLED :: violation_ac04_receipt_equal_to_prompt.json: exit 0, want 2 ()
absent_is_empty: selftest exit 1 -> KILLED :: violation_ac10_payload_without_message.json: exit 0, want 2 ()
unknown_origin_skipped: selftest exit 1 -> KILLED :: violation_ac12_unknown_origin_ends_walk.json: exit 0, want 2 ()
operator_opener_any: selftest exit 1 -> KILLED :: violation_ac07_skip_in_forged_human_entry.json: exit 0, want 2 ()
27/27 mutations killed
exit=0
```
