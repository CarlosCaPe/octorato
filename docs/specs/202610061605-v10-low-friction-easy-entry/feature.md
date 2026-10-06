# Feature: v10, Low Friction and Easy Entry

> **Status:** draft
> **Spec-Format:** ears-1
> **Date:** 2026-10-06
> **Classification:** LARGE (score 13: 10+ files, new feature, architectural decision, multiple modules)

v7 made an unverified send impossible. v8 made a run a process. v9 made "done" a verdict. v10 keeps every one of those guarantees and makes them cheap: a gate that blocks legitimate work is a bug with a measured rate, a newcomer reaches a first spec in minutes, and the state the gates guard is something you can look at.

## Summary

Three gaps were measured on 2026-10-06 against GitHub Spec Kit and the Kiro documentation.

**Friction.** Over 30 days of transcripts (1,059 files, 2026-09-06 to 2026-10-06), the send-ask check of the outward-send gate denied 64 times with an estimated 71% false-positive rate (10 of 14 sampled), and cost about 186 minutes of the operator retyping a send token; 8 denied turns already carried an explicit ask. `budget-check.py` blocked nothing and added a median 7.2 s to every subagent spawn (247 timeouts at 10 s). The goal-anchor Stop gate fired 100 times at an estimated 92% false-positive rate because it anchors short tokens such as "dale" or "send-ok" as the session goal. 280 Stop blocks sent 239 of 2,229 turns (10.7%) back for a rewrite. Master requires an up-to-date branch, and updating a branch moves its head and voids the QA pin, so none of the 17 open pull requests can merge without a second QA pass. No gate writes its own deny log, so none of these numbers existed before this census.

**Entry.** The README promises a 3-command quickstart while the wiki walks 5 steps and about 12 commands. `quickstart.py` never runs `merge-hooks.py`, so on a fresh clone the hooks are most likely not wired until the first `ai-pull` (read from the code paths, not yet reproduced on a clean clone). The constitution costs about 24k tokens per session, three of its sections are in Spanish against the English-only rule, a newcomer meets 9 glossary concepts before any value against about 4 in Spec Kit, and `brain_doctor` did not finish in 180 s on a populated machine while quickstart waits on it.

**Visual.** Octorato has no status line, no dashboard and no rendered view of its specs, receipts, gates or processes. Kiro shows specs, live task state and hooks in its own editor. The data to render already exists: `brain_doctor --json`, `spec_lint.py`, the receipt ledger, the kernel process table and journals.

Working notes behind every number: the friction census, the entry and UI census and the pull request triage, kept in the session scratchpad of 2026-10-06; the friction census ships with its extraction scripts so the baseline can be recomputed.

## Glossary

Every acceptance criterion names one of these components as its subject.

- **Friction_Ledger**: a new append-only, gitignored JSONL file under `~/.claude/.cache/friction/`, one line per gate deny or Stop block, with gate name, session, tool, a reason code and a truncated input digest.
- **Friction_Report**: a new `octo friction` subcommand that reads the Friction_Ledger and the replay corpus and prints denies, sampled false-positive rate and latency per gate.
- **Replay_Harness**: a new script that replays a frozen corpus of real tool calls and prompts through a gate and reports allow/deny changes against a stored baseline.
- **Send_Gate**: `scripts/g__pretool-mcp__outward-send.py`.
- **Goal_Anchor**: `scripts/g__stop__goal-anchor.py`.
- **Budget_Check**: `scripts/budget-check.py`.
- **Merge_Gate**: `scripts/qa-merge-gate.py`.
- **Receipt_Ledger**: `scripts/receipt_ledger.py`.
- **Quickstart**: `scripts/quickstart.py` and the README install section.
- **Doctor**: `scripts/brain_doctor.py`.
- **Constitution**: the tracked `CLAUDE.md` at the brain root.
- **Dashboard**: a new `octo dash` subcommand that writes one self-contained HTML page from local state.
- **Status_Line**: a new status line script registered for Claude Code.
- **Fresh_Clone_Test**: a new CI job that installs the brain from a clean clone in a container and times it.

## User Stories

- As the operator, I want a gate that blocks my legitimate work to show up as a number with its cause, so that friction gets fixed instead of tolerated.
- As the operator, I want my explicit "send it" to count the first time, in Spanish or English, so that I never retype a token to release a message I already asked for.
- As a newcomer, I want one install command and a first spec within minutes, so that I see value before I learn the architecture.
- As the operator, I want to see specs, tasks, receipts, gates and running processes on one page, so that I do not read terminal scrollback to know where things stand.

## Functional Requirements

### FR-01: Friction is measured by the system, not by a census

Every fail-closed gate and every Stop block appends one line to the Friction_Ledger. `octo friction` reports per gate. A frozen replay corpus, built from the 30-day census, becomes the regression set: a gate change ships with its before/after deny count on that corpus.

### FR-02: The send ask is read the way the operator writes it

The Send_Gate recognises an explicit send ask in Spanish and English, reads the operator's last genuine prompt even when the current turn was started by a task notification, and treats a read of the support script (help, cat, grep) as a read, not a send. Every other Send_Gate check (panel receipt, absence, attribute, promise, thread) is unchanged.

### FR-03: Stop gates stop crying wolf

The Goal_Anchor never anchors a prompt that is only a short acknowledgement or a hatch token, and re-anchors when the work changes. The WhatsApp guard Stop gate fires only on a turn that itself sent a message. The remaining top-10 sources from the census are tuned with a replay result each.

### FR-04: Latency has a budget

A hook on the hot path finishes within a stated budget. Budget_Check answers from a cache refreshed out of band instead of recomputing on every spawn.

### FR-05: A rebase does not void a review

When a pull request's head changes only because its base moved, and its patch is identical to the reviewed one, the earlier QA verdict carries over. Any change to the patch itself still voids it.

### FR-06: One install path that wires everything

Quickstart wires hooks and the git hooks path, runs a fast Doctor profile, and ends by creating a first spec. README and wiki describe the same path. A CI job proves it on a clean clone.

### FR-07: A lighter constitution

The Constitution keeps the rules every session needs and moves the long mechanism narratives (residuals, measurements, history) into the architecture docs they already summarise, loaded on demand. It is English-only.

### FR-08: A visible brain

`octo dash` renders specs with task and converge state, open pull requests with QA receipts, the gate receipt, live kernel processes and the friction report into one HTML page, offline and from local data. A Status_Line shows the gate receipt, live process count and the active spec.

## Acceptance Criteria

- [ ] AC-01: WHEN a fail-closed gate denies a tool call or a Stop hook blocks a turn, THE Friction_Ledger SHALL receive one line carrying the gate name, session id, tool name, reason code and a digest of the input truncated to 1,200 characters.
- [ ] AC-02: THE Friction_Report SHALL print, per gate, the deny count over a requested window, the median and p95 hook latency, and the false-positive rate of the labelled sample when one exists.
- [ ] AC-03: THE Replay_Harness SHALL replay a frozen corpus of at least 1,000 real tool calls and prompts drawn from the 2026-09-06 to 2026-10-06 transcripts, with secrets and message bodies redacted, and SHALL print allow-to-deny and deny-to-allow changes against a stored baseline.
- [ ] AC-04: IF a change to a gate script flips any labelled true-positive case from deny to allow on the Replay_Harness corpus, THEN THE Replay_Harness SHALL exit non-zero.
- [ ] AC-05: WHEN the operator's last genuine prompt carries an explicit, non-negated send ask in Spanish or English, THE Send_Gate SHALL lift the send ask without a separate hatch token.
- [ ] AC-06: WHEN a turn is started by a task notification or a subagent hand-back, THE Send_Gate SHALL evaluate the send ask against the operator's last genuine prompt in the session, not the notification text.
- [ ] AC-07: WHEN a Bash command only reads the support script (help flag, cat, grep, sed -n) and makes no request to a bridge, THE Send_Gate SHALL allow it.
- [ ] AC-08: THE Send_Gate SHALL keep denying a message send that has no PASS panel receipt for its digest, on every labelled true-positive case of the Replay_Harness corpus.
- [ ] AC-09: IF a prompt consists only of an acknowledgement or a hatch token of at most three words, THEN THE Goal_Anchor SHALL keep the previous root goal instead of anchoring the prompt.
- [ ] AC-10: WHEN the Replay_Harness replays the Stop-hook corpus, THE Goal_Anchor SHALL block on at most 25% of the turns it blocked on in the baseline, with every labelled true-positive case still blocked.
- [ ] AC-11: THE Budget_Check SHALL answer a PreToolUse call in at most 300 ms at the median and 1 s at p95, measured over 100 consecutive calls on the operator's machine.
- [ ] AC-12: WHEN a pull request's head changes and `git patch-id --stable` of its diff against the merge base equals the patch-id of the head a QA PASS receipt names, THE Merge_Gate SHALL accept that receipt for the new head.
- [ ] AC-13: IF the patch-id of the new head differs from the reviewed head, THEN THE Merge_Gate SHALL deny the merge exactly as it does today.
- [ ] AC-14: THE Quickstart SHALL, on a clean clone, wire the Claude Code hooks, set `core.hooksPath` to `.githooks` and finish with a first spec directory that `spec_lint.py` accepts, using one command after the clone.
- [ ] AC-15: THE Doctor SHALL offer a fast profile that completes in at most 30 s on the operator's machine, and THE Quickstart SHALL use that profile.
- [ ] AC-16: THE Fresh_Clone_Test SHALL run the Quickstart in a clean container on every pull request that touches the install path and SHALL fail if hooks are not wired or the run exceeds 5 minutes.
- [ ] AC-17: THE Constitution SHALL contain no section written in a language other than English and SHALL load at most 12,000 tokens, measured by the same estimator for the before and after figures.
- [ ] AC-18: WHEN the Constitution moves a mechanism narrative out, THE Doctor SHALL still find every registry rule anchor, so that no rule loses its wiring.
- [ ] AC-19: THE Dashboard SHALL write one self-contained HTML file, with no network fetch, showing specs with task and converge state, open pull requests with their newest QA verdict and pinned head, the gate receipt, live kernel processes and the friction report.
- [ ] AC-20: THE Status_Line SHALL show the gate receipt state, the live process count and the active spec, and SHALL return within 200 ms.

## Technical Scope

- New: `scripts/friction_ledger.py` (append helper imported by gates), `scripts/replay_harness.py`, `registry/fixtures/friction-corpus/` (redacted), `octo friction`, `octo dash`, a status line script, a CI workflow for the clean clone.
- Changed: `g__pretool-mcp__outward-send.py` (send-ask reader), `g__stop__goal-anchor.py`, `d__stop__wa-guardia.py`, `budget-check.py`, `qa-merge-gate.py` and `receipt_ledger.py` (patch-id carry-over), `quickstart.py`, `brain_doctor.py` (fast profile), `README.md`, `docs/wiki/Getting-Started.md`, `CLAUDE.md`.
- The gate edits touch the arming surface, so each is written in a worktree and reaches the live tree only by pull.

## Non-Functional Requirements

- No guarantee from v7, v8 or v9 is weakened: every labelled true positive in the corpus still blocks (AC-04, AC-08, AC-13).
- Every number in a commit or doc carries its measurement mode and source.
- The Friction_Ledger and the corpus never hold a secret or a message body.

## Release Criterion

v10.0.0 ships when every criterion above has a CONVERGED verdict and the Friction_Report over the first 7 days after release shows the send-ask false-positive rate under 15% on its labelled sample.

## Out of Scope

- A VS Code or Cursor extension and a TUI. The Dashboard covers the visual gap first; an editor extension is a v10.x decision made on Dashboard use.
- Removing any gate. Tuning, not removal.
- The auto-mode classifier of Claude Code, which sits outside the brain; its denies are counted in the Friction_Report but not changed.

## Revision History

- 2026-10-06: draft from the friction, entry and UI censuses and the pull request triage.
