# Octorato v9: Done Is a Verdict

> v7 made a send without receipts impossible. v8 made a run a process. v9 makes "done" a verdict computed against a spec by a pass that did not write the code, never a claim typed by the agent that did.

Spec and plan: `docs/specs/202609301321-v9-done-is-a-verdict/`.

## The problem

Before v9 the SDD flow let the builder grade itself. `sdd-implement` wrote `impl-summary.md` with `[x] AC-01: Passed`, and `sdd-review` ticked the acceptance criteria in `feature.md`. Both were completion claims made by the process that wrote the code, and nothing could check them, because acceptance criteria were free prose.

## The contract

A LARGE task is done when, and only when, an independent verifier on the judgment tier has judged every acceptance criterion against the code and tests and returned `CONVERGE-VERDICT: CONVERGED` for that spec directory, and nothing outside the spec directory has changed since.

Three layers carry it.

| Layer | Mechanism | What it makes true |
|---|---|---|
| A spec a script can read | `Spec-Format: ears-1`: EARS criteria with a Glossary subject, at most 3 open markers, tasks as `T## [AC-##] <path>: <action>`. Checked by `scripts/spec_lint.py`, stdlib only | Coverage is computed, not judged. Rule `FLOW.spec-contract` |
| Verdict skills | `sdd-analyze` (spec against plan, read-only, before code) and `sdd-converge` (code against criteria, append-only, after code), both independent verifier subagents | The builder never grades its own work |
| Receipt and gate | The SubagentStop reflex `r__subagent-stop__qa-receipt.py` records `CONVERGE-VERDICT` and `CONVERGE-SCOPE` as a `converge` receipt; `.githooks/pre-push` runs `spec_lint.py --push-range` per pushed ref | A spec cannot reach `Status: converged` in a push without a fresh CONVERGED receipt. Rule `FLOW.done-is-a-verdict` |

### The spec home

Every ears-1 spec is created in `docs/specs/<yyyymmddHHMM>-<feature-name>/` and never moves. That path is the key of the converge scope, the receipt and the push gate. A spec that moved at archive time gave them three different paths, so no receipt could ever match (operator decision, 2026-09-30).

### What the push gate checks

For every pushed ref, `spec_lint.py --push-range <base> <head>`:

1. lints, at the pushed head, every ears-1 spec whose `feature.md` or `plan.md` the range changes (AC-15);
2. for every ears-1 spec whose `Status:` becomes `converged` in the range, requires the latest anchored converge receipt for that exact spec directory to say `CONVERGED` (a later `GAPS` makes an earlier `CONVERGED` stale) and to be newer than the last commit in the range that touches a path outside the spec directory (AC-14).

A receipt is anchored the same way a QA receipt is: written by the harness-side reflex, pointing at a harness-written agent transcript under the projects directory whose last report re-parses to the same verdict and scope, from a verifier persona. A scope must equal the spec directory exactly; a prefix never matches.

### What the doctor checks

`brain_doctor` check `spec-contract` lints every ears-1 spec on disk and confirms the pre-push stanza. It warns, never fails, for a spec that says `converged` with no CONVERGED receipt on this machine. The two gate rules prove their fixtures through `gate-liveness`.

## Residuals, measured

| Residual | Measurement | Bound |
|---|---|---|
| The push stanza can be skipped from a worktree | Fed to `g__pretool__arming-surface.py` on 2026-09-30: `git push --no-verify` and `git -c core.hooksPath=/dev/null push` are **allowed** with a worktree as cwd and **denied** with the live root as cwd | The branch still reaches master only through `gh pr merge`, which needs the operator's `OCTO_MERGE_APPROVE` and a QA receipt. A merge through the GitHub web UI runs no local hook at all. The doctor's WARN makes a converged spec without a receipt visible afterwards |
| Receipts are local to one machine | The ledger is `~/.claude/.cache/receipts/global.jsonl`, gitignored | The machine that ran the converge pass pushes the status change. A second machine pulling a converged spec sees a WARN, not a FAIL |
| A transcript can be forged under `$HOME` | Same residual v7 states: agent transcripts are files the model can append to | A forged receipt needs the harness fields, the right session directory and the right agent id, and it stays visible in the transcript and the ledger. Visible and recorded, not impossible |
| Freshness is computed from commit dates | Committer dates are set by whoever commits | A backdated code commit could make a stale receipt look fresh. It needs a deliberate `GIT_COMMITTER_DATE` and it shows in `git log --format=%cI` |
| A status-only push accepts any CONVERGED receipt | When the range touches nothing outside the spec directory there is no newer code commit to compare against, by the definition in AC-14 | The code shipped in an earlier push, and that push carried its own history; the receipt still has to be the latest verdict for the directory |

## Phases

| Phase | Tasks | Shipped in |
|---|---|---|
| 1. A spec a script can read | T01-T06 | #327 |
| 2. The verdict skills and the flow | T07-T12 | #333 |
| 3. The receipt, the push gate and the wiring | T13-T18 | this document's PR |
| 4. Release | T19-T20 | converge on this spec, then the operator cuts v9.0.0 |
