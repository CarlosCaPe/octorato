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

For every pushed ref, `spec_lint.py --push-range <base> <head>` reads the specs the range touches. A spec is a `feature.md` in its own directory directly under `docs/specs/` or `docs/specs-archive/`, at any depth of the repository; a `feature.md` nested deeper (`docs/specs/<name>/v2/feature.md`), test fixtures and templates are not specs and are never read, because violation fixtures are malformed on purpose. A `docs` directory, a spec home, a spec directory or a spec file must be a plain file or directory in the git tree, at any depth: no symlink, no submodule, and no other tree mode. The gate reads the tree, and a link or a submodule would hide specs that a filesystem walk (the doctor, an editor, a person) still sees on disk. A link or submodule with any other name hides nothing the gate reads, because a spec in the tree sits at its real path. The rule is broad on purpose: a vendored symlink named `docs`, or a convenience link inside a spec home or a spec directory, is refused too. Spec paths are matched without regard to case, and any spelling other than the lower-case `docs/specs/<name>/feature.md` (or `plan.md`, or `docs/specs-archive`) is refused, because on a case-insensitive filesystem (Windows, macOS by default) another spelling lands on the same file. A spec file may not be a Git LFS pointer, which would hide the spec the same way. Deleting a spec is allowed. For each spec it:

1. lints, at the pushed head, every ears-1 spec whose `feature.md` or `plan.md` the range changes (AC-15). The headers are part of the lint: every header-shaped `Status` or `Spec-Format` line, in any markup, must be the canonical `> **Status:** draft|approved|converged` and `> **Spec-Format:** ears-1`, exactly once, in the first 30 lines. The gate reads only the canonical form, so any other form is a finding, never an unseen flip;
2. refuses a spec that stops being ears-1 in the range (its Spec-Format header removed or broken), and a spec directory under `docs/specs/` not named `<yyyymmddHHMM>-<lowercase-slug>`;
3. refuses a spec that says `converged` without a `plan.md`, flip or not;
4. for every ears-1 spec whose `Status` becomes `converged` in the range, requires the latest anchored converge receipt for that exact spec directory to say `CONVERGED` (a later `GAPS` makes an earlier `CONVERGED` stale) and to be newer than the newest code commit on the branch (AC-14).

"Newer" compares the harness-written timestamp of the transcript entry that carries the verdict, never the ledger line's `ts`, against the latest author or committer date among the commits that are on this branch (reachable from the pushed head, not from the default remote branch) and touch a path outside the spec directory. Branch scope closes the two-push split, where code went out in one push and the status flip in the next. Both dates count because each alone is slipped by an everyday command: `git commit --amend` and `git cherry-pick` keep the old author date, and only the committer date shows when the code landed. The cost, accepted: a rebase after the verdict stales it, and so does merging the default branch into the spec's branch (the merge commit is on the branch and master's code entered it unseen by the verifier); the converge pass runs again. That concerns only the push that flips a spec, once per spec. A spec that already says `converged` and has no `plan.md` is refused on any edit, so its first edit restores the plan.

What the gate reads as a header is the header-shaped line at the start of a line. A plain sentence that begins with `Status: converged` at the start of a line is read as a second, non-canonical header and refuses the push; reword it or quote it in backticks. Conversely a status shown only inside an HTML comment, a heading or a later table cell renders for a reader but is not a header, and the gate reads the canonical line.

A receipt is anchored the same way a QA receipt is: written by the harness-side reflex, pointing at a harness-written agent transcript under the projects directory whose last report re-parses to the same verdict and scope, from a verifier persona. A scope must equal the spec directory exactly; a prefix never matches. The gate reads receipts from any session on the machine, because a push runs outside any session.

### What the doctor checks

`brain_doctor` check `spec-contract` lints every ears-1 spec on disk and confirms the pre-push stanza. It confirms the stanza is the condition of an `if !` whose body reaches `exit 1`, and warns, never fails, for a spec that says `converged` with no CONVERGED receipt on this machine. It reads status with the gate's own function. The two gate rules prove their fixtures through `gate-liveness`.

## Residuals, measured

| Residual | Measurement | Bound |
|---|---|---|
| The push stanza can be skipped from a worktree, per push | Fed to `g__pretool__arming-surface.py` on 2026-09-30: `git push --no-verify`, `git -c core.hooksPath=/dev/null push` and the `GIT_CONFIG_KEY_0` spelling are **allowed** with a worktree as cwd and **denied** with the live root as cwd | The branch still reaches master only through `gh pr merge`, which needs the operator's `OCTO_MERGE_APPROVE` and a QA receipt. A merge through the GitHub web UI runs no local hook at all. The doctor's WARN makes a converged spec without a receipt visible afterwards |
| The stanza can be disarmed durably from a worktree | Same probe: `git config core.hooksPath /dev/null` and `chmod -x .githooks/pre-push` are **allowed** with a worktree as cwd. `git config --show-origin core.hooksPath` resolves to `~/.claude/.git/config`, shared by every worktree (no `extensions.worktreeConfig`), so one command disarms every pre-push stanza for every checkout, the live root included | Same bound as above: the merge gate and the doctor. The doctor's `leak-guard` check reports a `core.hooksPath` other than `.githooks` or a pre-push that is not executable on its next run, and `--fix` restores it. This is a v8 arming-surface residual, larger than the per-push skip |
| The gate is installed in this repository only | The stanza lives in this repository's `.githooks/pre-push`. `scripts/ai_sync.py` syncs `CLAUDE.md` and its two mirrors to an arm, and `templates/arm/` ships no hook, so a push from an arm runs no spec gate | The linter, both verdict skills and the receipt reflex work in an arm; only the push-time refusal is missing there. An arm that wants it copies the stanza into its own pre-push |
| Receipts are local to one machine | The ledger is `~/.claude/.cache/receipts/global.jsonl`, gitignored | The machine that ran the converge pass pushes the status change. A second machine pulling a converged spec sees a WARN, not a FAIL |
| The verifier persona is chosen by the main loop | The anchor is the `agent_type` the harness records, and the main loop that built the code picks `subagent_type` and writes its brief | Independence is by convention and by the judgment-tier routing rule, not by mechanism. The brief and the full transcript are on disk for audit |
| A transcript can be forged under `$HOME` | Same residual v7 states: agent transcripts are files the model can append to | A forged receipt needs a harness-shaped entry in the right session directory under the right agent id. Replaying an old genuine verdict with a fresh ledger line no longer works: freshness reads the transcript's own timestamp. Visible and recorded, not impossible |
| Commit dates are set by whoever commits | An amend or a cherry-pick alone no longer slips code under a verdict, since the committer date counts. One rebase flag does: `git rebase --committer-date-is-author-date` after amending new code sets the committer date back to the old author date. A machine whose clock runs behind does the same by accident | It needs a deliberate flag or a wrong clock, and the commit still shows in the branch's history; the verdict's own timestamp comes from the harness, not the commit |
| Code merged to master outside the branch is not counted | Freshness looks at the branch's own commits, so a code change that reached master through another PR before the flip is outside the comparison | That code went through its own PR and QA; the spec's criteria are re-judged the next time its code changes on a branch |
| A first push of a whole history | With no remote-tracking refs (a fresh mirror), the range is every commit and every converged spec reads as a new flip | It blocks rather than allows; push the history with the receipts present, or push the flips separately |

## Phases

| Phase | Tasks | Shipped in |
|---|---|---|
| 1. A spec a script can read | T01-T06 | #327 |
| 2. The verdict skills and the flow | T07-T12 | #333 |
| 3. The receipt, the push gate and the wiring | T13-T18 | #335, #337 |
| 4. Release | T19-T20 | converge on this spec, then the operator cuts v9.0.0 |
