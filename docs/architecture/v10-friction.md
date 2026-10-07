# v10 friction measurement

Spec: `docs/specs/202610061605-v10-low-friction-easy-entry/` (FR-01, AC-01 to AC-04). This page is the source the registry rows `FLOW.friction-ledger` and `FLOW.friction-replay` anchor on.

Before v10 no gate wrote its own deny log, so the cost of a gate that blocks legitimate work existed only as a census someone ran by hand over the transcripts. Phase 1 makes the brain count it itself, and gives every later gate change a regression set built from real traffic.

## Friction ledger

`scripts/friction_ledger.py` reads what the harness already wrote to the session transcript. No gate body changes.

| Transcript record | Becomes |
|---|---|
| `tool_result` with `is_error`, text `PreToolUse:<Tool> hook error: ...` | `pretool-deny` |
| `attachment.type = hook_blocking_error` | `stop-block` |
| auto-mode classifier or sleep refusal | `harness-deny`, gate `harness:*`, never mixed with Octorato gates |

Each event is one line in the gitignored `~/.claude/.cache/friction/ledger.jsonl`: gate, session, agent, tool, reason code, and the sha256 of the input serialised as sorted-key JSON and cut to 1,200 characters. The reason text, the input, a message body or a prompt are never stored. An exit-2 deny names its script in the text; a JSON deny does not, so `registry/friction-signatures.json` maps the reason text to a gate and a reason code. A deny no row matches is kept as `unattributed`.

The digest is unsalted. A short input (`ls`, `git status`) can be recovered by hashing guesses, so the ledger is local and gitignored and never leaves the machine; only the replay baseline, which holds no digest, is tracked.

Idempotent by the harness `uuid` (plus the tool_use id for parallel results). Incremental by a per-file byte offset, whole lines only. Hook durations ride along in monthly `latency-YYYY-MM.jsonl` files (about 70,000 rows a month on the operator's machine). The dedupe sets load lazily: a Stop with nothing new reads no ledger, the small event ledger is deduped in full, and latency is deduped only when a transcript is read from byte 0 (a new file, a reset offset, a resumed copy), against the months that read touches. Past a saved offset every byte is new by construction.

`scripts/r__stop__friction-ledger.py` runs it at every Stop for the session transcript and its subagent transcripts. It never blocks, never prints and exits 0 on any error. A Stop block of the current stop is written by the harness after the hooks return, so it is ledgered at the next Stop, which the block itself causes.

The reflex reads at most 24 MB per Stop, so a session that predates the ledger is caught up over a few Stops. Measured on the operator's laptop, subprocess wall time with interpreter start, on the largest session on the machine (76 MB plus its subagent transcripts): first Stop 0.27 s median of 5 runs (0.45 s max), later Stops 0.13 s median of 20 (0.48 s max while still catching up). Uncapped, the first Stop cost 1.26 s. With a 31-day backfilled ledger (634 events, 71,788 latency rows, 12 MB), a Stop with nothing new costs 0.041 s median of 20 runs (0.049 s max) and a Stop after a 50-line append 0.042 s median of 10; both read no ledger file. What still grows is `offsets.json` (0.2 MB for 1,066 transcripts), read once per Stop.

For the past: `python3 scripts/friction_ledger.py backfill --since YYYY-MM-DD`.

## Replay harness

`scripts/replay_harness.py` freezes real traffic into a private corpus and replays each case through the gate script it belongs to, the way the harness calls it: the hook payload as JSON on stdin, the decision read from exit code 2 or a `deny`/`ask`/`block` JSON answer.

- `build` scans a date window, keeps every real deny and Stop block of a replayable gate plus a fixed-seed sample of calls and turns each gate let through, cuts a transcript window per case (the records since the 10th operator prompt back, at most 1,500, plus every earlier operator prompt; tool results and earlier tool inputs cut to 2,000 characters, reply text whole), applies the private label rules and writes the baseline.
- `replay` prints allow-to-deny, deny-to-allow and reason-code moves against the baseline, with each gate's fidelity next to it. It exits 1 when a case labelled TP that the baseline blocked is no longer blocked, when a gate that denied in the baseline denies nothing, or when an unlabelled historical deny now allows. The last one is waived with `--allow-unlabelled-loss` for an intended loosening; the first two are never waived.
- `baseline` rewrites the baseline after an intended change. `label` re-applies the label rules.

The corpus lives in the gitignored `company/friction-corpus/` because it holds real prompts and commands. The tracked `registry/friction-baseline.json` holds counts and, per case, a 16-hex id, the gate, the historical and replayed decisions, a reason code and the label. On a clone without the corpus, `replay` prints SKIP and exits 0.

What a replay cannot see, so a replayed decision can differ from the historical one: receipts and ledgers of the real HOME (panel, QA, delegation ledger, kernel process table, block-once sentinels), the private `company/config/`, the live state of the directory the call ran in, and whatever the window cut. Every case runs in a fresh temp HOME with an allowlist environment (PATH, LANG, LC_*, PYTHON*, TMPDIR; no token and no override variable reaches real gate code) and `CLAUDE_SESSION_ID=__selftest__`, the session seam of a gate selftest, which also lets the outward-send gate accept a seeded gate receipt so that check does not mask the ones behind it. The baseline stores both decisions, so fidelity is measured per gate: the share of historical denies the replay reproduces and the share of historical allows it reproduces. A gate under 50% on either side is LOW-FIDELITY, and `replay` and `octo friction` flag any before/after on it as not evidence. On the 2026-09-06..10-06 corpus that is goal-anchor (9 of 103 denies), wa-guardia (0 of 38), delegation-audit (0 of 65), all three because their block depends on real-HOME state, and chat-context the other way round (33 replayed denies for 9 historical) because its block-once sentinel never exists in a fresh HOME.

## Report

`octo friction [--days N] [--json]` prints per gate the deny count in the window, the median and p95 hook latency, the replay fidelity (agree over cases, replayed over historical denies, LOW-FIDELITY mark) and the false-positive rate of the labelled denies in the baseline with its coverage ("22 of 103 labelled") and corpus window. The labels encode the census classes, which target known false-positive shapes, so the rate is a rate over the labelled sample, not over all denies. The harness records a duration only for a hook that printed output, and a deny records none, so a missing latency means not recorded.
