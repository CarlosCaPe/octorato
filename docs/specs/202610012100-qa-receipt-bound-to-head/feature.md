# Feature: A QA verdict is bound to the commit it reviewed

> **Status:** approved
> **Spec-Format:** ears-1
> **Date:** 2026-10-01
> **Classification:** LARGE (score 7: 4-10 files, an architecture decision on the merge gate, multiple modules)

A QA PASS approves a pull request today, whatever the pull request holds when it is merged. It should approve the commit the reviewer read, and nothing pushed after it.

## Summary

`qa-merge-gate.py` lets a `gh pr merge` through when the operator's `OCTO_MERGE_APPROVE` names the pull request and the receipt ledger holds an anchored QA PASS whose scope names the same pull request number (`scripts/receipt_ledger.py`, `qa_pass_for`). The receipt carries no commit. Two holes follow, both seen on 2026-10-01 while v9 shipped:

- Commits pushed after a PASS ride on it. On #347 a PASS covered f8caa23. Every commit added afterwards would have merged on that PASS without a new review, as long as no one asked for one.
- A later verdict does not revoke an earlier PASS. `qa_pass_for` returns the most recent PASS and skips every FAIL and NEEDS-WORK, so a PASS followed by a NEEDS-WORK on the same pull request still opens the gate.

The fix keeps the gate free of network calls. It runs under a 5 second hook timeout (`hooks.json`), and a killed hook writes nothing, which the harness reads as allow. So the gate never asks GitHub for the pull request head. It requires the merge command to pin a commit and compares that commit against the one the QA reviewer declared with a third protocol line, `QA-HEAD: <sha>`. The newest anchored verdict for that pull request and that commit decides.

GitHub enforces the pin on a direct merge, measured on 2026-10-01 against primary sources:
- `gh pr merge --match-head-commit SHA` becomes `expectedHeadOid` on the `mergePullRequest` GraphQL input (cli/cli `pkg/cmd/pr/merge/http.go`), whose schema reads "OID that the pull request head ref must match to allow merge".
- The REST `PUT /repos/{owner}/{repo}/pulls/{n}/merge` endpoint takes `sha`, "SHA that pull request head must match to allow merge", and answers 409 when it differs.

That proof does not cover auto-merge. With `--auto`, gh sends the pin to `enablePullRequestAutoMerge`, whose field is documented only as "the expected head OID", and GitHub disables an armed auto-merge only when someone without write access pushes. Whether GitHub re-checks the pin when it performs the auto-merge is not established, so an approved merge must be a direct one.

## Glossary

Every acceptance criterion names one of these components as its subject.

- **QA_Reviewer**: an independent QA subagent whose agent type the receipt ledger accepts as a verifier persona.
- **QA_Reflex**: `scripts/r__subagent-stop__qa-receipt.py`, the SubagentStop hook that records QA and converge receipts.
- **Receipt_Ledger**: `scripts/receipt_ledger.py`.
- **Merge_Gate**: `scripts/qa-merge-gate.py`, the PreToolUse hook on Bash.
- **Rule_Text**: every place that teaches the QA protocol or the gated merge command: the QA receipt paragraph of `CLAUDE.md`, the v7 contract document `docs/architecture/v7-nothing-ships-unverified.md`, the `qa-merge-gate` and `r__subagent-stop__qa-receipt` rows of `docs/ANATOMY.md`, the `pre-merge-qa-gate` skill, and the Merge_Gate's own block messages.

## User Stories

- As the operator, I want a PASS to approve exactly the commit the reviewer read, so that a commit pushed afterwards needs its own review.
- As the operator, I want the newest verdict on a commit to decide, so that a NEEDS-WORK cannot be outvoted by an older PASS.
- As the operator, I want the merge command I paste to carry the commit it merges, so that GitHub refuses the merge when the branch moved after review.

## Functional Requirements

### FR-01: The reviewer names the commit

The QA protocol gains a third line, `QA-HEAD: <sha>`, the full 40 hexadecimal digit commit the reviewer checked out and judged. The reflex records it in the receipt, and every consumer re-reads it from the agent transcript, as it already does for the verdict and the scope.

### FR-02: The merge names the commit, and is direct

A pull request merge through the gate carries the commit it merges, read from the command's own arguments the way gh reads them. gh's flag parser gives a flag that takes a value the next token even when that token looks like a flag: in `gh pr merge 96 -t --match-head-commit=<sha>` the string `--match-head-commit=<sha>` is the merge subject, gh sends no pin, and GitHub merges any head (measured with `gh pr list --search --limit=3`, where `--limit=3` became the search text). So the gate walks the arguments with gh's value-flag table, and a token that is the value of another flag is never a pin. Short flags cluster: in `-st` (squash, then subject) the `t` takes the next token, so in a token `-xyz` each letter is read in turn and the first value flag takes the rest of the token, or the next token when nothing is left (measured with `gh api ... -iq --silent`, where `-q` inside `-iq` took `--silent` as its program):
- `gh pr merge <n>`: `--match-head-commit <commit>` or `--match-head-commit=<commit>`. The value flags are `-t`/`--subject`, `-b`/`--body`, `-F`/`--body-file`, `-A`/`--author-email`, `-R`/`--repo` and the pin flag itself, in their spaced, `=` and attached short forms. When the pin repeats, the last one counts, as in gh.
- `gh api` on the REST merge endpoint: the value of a `-f`, `-F`, `--field` or `--raw-field` argument reading `sha=<commit>`, read with gh api's value-flag table (`-f`, `-F`, `--field`, `--raw-field`, `-H`, `--header`, `-X`, `--method`, `--input`, `-q`, `--jq`, `-t`, `--template`, `-p`, `--preview`, `--hostname`, `--cache`). A body passed any other way (`--input`, `curl -d`, a JSON string) cannot be read, so the merge is blocked and the message names the readable form.

`--auto` is refused on an approved merge, because GitHub's re-check of the pin on auto-merge is not established. GitHub refuses a direct merge whose head differs from the pin, so the pinned commit is the merged commit. The repository's auto-merges are the bot's CHANGELOG pull requests, armed by `.github/workflows/version-bump.yml` in GitHub Actions, where no hook runs (measured over the last 15 merges on 2026-10-01). The refusal binds merges an agent runs through this gate. A merge the operator types in an unhooked terminal is not gated at all, and the merge command handed to the operator carries the pin so that GitHub enforces it there too.

### FR-03: The newest verdict on that commit decides

Each receipt is anchored to the report entry it was recorded from, not to its agent's last report. A reviewer can be resumed: re-read on 2026-10-01, 70 of the ledger's 310 qa rows no longer matched their agent's last report, every one of them a resumed agent, and some NEEDS-WORK and FAIL rows now re-read as "no verdict" because a later reply ended in plain prose or a harness error ("You've hit your session limit", "Login expired"). Re-read against the last report, one SendMessage to a reviewer that said NEEDS-WORK erased its revocation. So the reflex records the harness `uuid` and `timestamp` of the entry it parsed, and a consumer re-reads that exact entry, which must still carry the same verdict, scope and commit. A resumed reviewer's later report is a receipt of its own.

For the pull request and the pinned commit, the newest anchored receipt decides, newest by the harness-written timestamp of the entry that carries its report, never by the order of ledger lines, which anyone can re-append. Receipts from every session on this machine count, the same reach as the converge receipt. That is no weakening: a 40-digit commit names one commit, so a PASS from another session cannot match a different commit, and a NEEDS-WORK from any session now revokes. A PASS opens the gate, any other verdict keeps it closed, and receipts for other commits are ignored.

The lookup stays inside the gate's 5 second budget. Ledger lines are first narrowed to qa rows whose own scope names the pull request, and only those transcripts are opened; the commit and the verdict are then read from each transcript, which decides. Narrowing on the ledger's own commit would let a row whose ledger commit differs from its transcript hide a real NEEDS-WORK, so the ledger narrows by pull request only. Only regular files are opened, so a pipe or a device placed where a transcript belongs cannot hold the read open. Measured on 2026-10-01, re-reading every anchored qa receipt took 0.88 s for 307 rows and extrapolates past 5 s for the ledger's 1 MB window. The lookup runs in a daemon thread that the gate waits on for at most 3 seconds; when the wait ends first, the gate blocks and exits, and the thread dies with the process, whatever read it is stuck in.

### FR-04: What does not change

A gated action with no pull request number (`git push` to `main` or `master`, a REST `merges` or ref write) keeps today's rule, with no commit pin. `OCTO_QA_OK=1` stays the operator's explicit bypass, and it lifts the receipt check, the pin and the `--auto` refusal together, as it does today without approval. In this spec an approved merge is one where `OCTO_MERGE_APPROVE` names the pull request and `OCTO_QA_OK` is not `1`.

## Acceptance Criteria

- [ ] AC-01: WHEN a QA_Reviewer's final report carries `QA-HEAD: <sha>` with 40 hexadecimal digits, THE QA_Reflex SHALL record that commit in lower case in the qa receipt.
- [ ] AC-02: THE Receipt_Ledger SHALL re-read the verdict, the scope and the reviewed commit of a qa receipt from the exact transcript entry the receipt names by its harness `uuid`, and SHALL skip a receipt whose ledger fields differ from the re-read ones or whose entry is gone.
- [ ] AC-03: IF `OCTO_MERGE_APPROVE` names a pull request and its `gh pr merge` carries no `--match-head-commit` argument with 40 hexadecimal digits, THEN THE Merge_Gate SHALL block it and name the flag in its message.
- [ ] AC-04: IF `OCTO_MERGE_APPROVE` names a pull request and its REST merge carries no `-f`, `-F`, `--field` or `--raw-field` argument `sha=<40 hexadecimal digits>`, THEN THE Merge_Gate SHALL block it and name that form in its message.
- [ ] AC-05: IF the pin is found only inside the text of another argument, or as the value of another flag in its spaced, `=`, attached or clustered short form, THEN THE Merge_Gate SHALL treat the merge as unpinned.
- [ ] AC-06: IF an approved `gh pr merge` carries `--auto`, THEN THE Merge_Gate SHALL block it.
- [ ] AC-07: IF no anchored qa receipt names both the pull request and the pinned commit, THEN THE Merge_Gate SHALL block the merge.
- [ ] AC-08: IF the anchored qa receipt with the newest transcript timestamp for the pull request and the pinned commit is not a PASS, THEN THE Merge_Gate SHALL block the merge, even when a ledger line for an older PASS was appended after it.
- [ ] AC-09: WHEN `OCTO_MERGE_APPROVE` names the pull request and the anchored qa receipt with the newest transcript timestamp for it and the pinned commit is a PASS, THE Merge_Gate SHALL allow the merge.
- [ ] AC-10: THE Merge_Gate SHALL decide without a network call.
- [ ] AC-11: WHERE the operator sets `OCTO_QA_OK=1`, THE Merge_Gate SHALL skip the receipt check, the commit pin and the `--auto` refusal, as the explicit bypass it is today.
- [ ] AC-12: WHILE a gated action carries no pull request number, THE Merge_Gate SHALL apply today's rule without a commit pin.
- [ ] AC-13: THE Rule_Text SHALL state the three protocol lines, the pinned and direct merge command, and the rule that the newest verdict on a commit decides.
- [ ] AC-14: THE Receipt_Ledger SHALL open only regular-file transcripts of qa ledger rows whose own scope names the pull request.
- [ ] AC-15: IF the receipt lookup does not finish within 3 seconds, including a read that blocks, THEN THE Merge_Gate SHALL block the merge.
- [ ] AC-16: WHEN a QA_Reviewer that recorded a verdict is resumed and replies again, THE Receipt_Ledger SHALL keep reading the earlier receipt from its own entry, whatever the later reply says.
- [ ] AC-17: WHEN the QA_Reflex records a qa receipt, THE QA_Reflex SHALL store the harness `uuid` and `timestamp` of the transcript entry it parsed the report from.
- [ ] AC-18: IF the anchored qa receipt with the newest transcript timestamp for the pull request is a FAIL or NEEDS-WORK whose report carries no valid `QA-HEAD`, THEN THE Merge_Gate SHALL treat it as the verdict for every commit of that pull request.
- [ ] AC-19: WHEN one Bash command carries several publish sub-commands, THE Merge_Gate SHALL decide each one and allow the command only when every one is allowed, and SHALL read a pin only from the arguments bash passes, so an unquoted `#` comment ends them.
- [ ] AC-20: IF the operator's approval is exported and a command mentions a merge or a push to main inside syntax the Merge_Gate does not parse (a backslash, a heredoc, ANSI-C quoting, a substitution, `sh -c`, `eval`), THEN THE Merge_Gate SHALL block the whole command and name the plain command form.

## Technical Scope

### Affected Modules

| File | Change |
|---|---|
| `scripts/receipt_ledger.py` | `parse_qa_head()`; a lookup keyed on pull request and commit that returns the newest anchored receipt |
| `scripts/r__subagent-stop__qa-receipt.py` | record `head` on qa receipts |
| `scripts/qa-merge-gate.py` | read the commit pin from the command's arguments, refuse `--auto` on an approved merge, decide on the newest receipt for that commit, and teach the new protocol in its block messages |
| `scripts/tests/test_receipt_ledger.py`, `scripts/tests/test_qa_merge_gate_head.py` | the criteria as tests |
| `CLAUDE.md`, `docs/architecture/v7-nothing-ships-unverified.md`, `docs/ANATOMY.md`, `skills/pre-merge-qa-gate/SKILL.md` | the protocol, the pinned direct merge, the newest-verdict rule |

### Integration Points

The merge gate already reads the pull request number from the command (`_extract_pr_id`) and the REST path (`_api_write_action`). The commit pin is read from the same command string. The receipt ledger already anchors a receipt to a harness-written agent transcript and a verifier persona; the commit is one more field re-read from the same report.

## Non-Functional Requirements

- The gate keeps its 5 second budget: no network, no git call.
- A receipt recorded before this change carries no commit, so it opens nothing. A pull request reviewed under the old protocol needs one more QA pass. That is the intended cost.

## Out of Scope

- A merge queue. GitHub enqueues a `gh pr merge` when the base branch requires one, and the pin's meaning there is the same open question as auto-merge. `master` has no merge queue (GraphQL `mergeQueue` is null on 2026-10-01); a repository that adds one needs this decision again.
- The converge receipt's consumer. `converge_latest_for` re-reads its agent's last report and has the same exposure to a resumed converge pass (measured: 3 of 7 converge rows mismatch). The reflex records the entry anchor for converge receipts too, so the follow-up is a consumer change in the push gate with its own fixtures, outside this spec.
- A ledger line deleted. The ledger is a file under `$HOME`, so removing a NEEDS-WORK line removes the revocation. The same residual v7 states for the transcripts: visible and recorded, not impossible.
- Generic skills that print a plain `gh pr merge` for any repository (`pr-first-on-auto-deploy-main`, `stacked-pr-squash-delete-gotcha`). On a protected repository the gate blocks those commands and its message names the pin.
- A GraphQL `mergePullRequest` call. The gate cannot read a pull request number from it and already blocks it unless the operator sets `OCTO_QA_OK=1`.
- Pushes straight to `main` or `master`. They have no pull request and no QA receipt, and keep today's rule.
- The gate reading `gh pr merge --help` as a merge. A separate false positive, seen while writing this spec.
- Deliberate shell obfuscation that hides the merge or the pin from a plain reading, when no rule above catches it: a variable or a function that names the command (`G=gh; $G pr merge`), an alias, `gh alias`, or any indirection the gate does not evaluate. The gate's command matching is a speed-bump for honest mistakes; the boundary is the operator's exported approval, as the gate's header states. An honest merge is one plain, pinned command, and every form an honest command line uses in front of gh is read.


## Revision History

| Date | Change Summary |
|---|---|
| 2026-10-01 | Initial spec |
| 2026-10-01 | Analyze pass 1 (FIX-FIRST): the pin is proven for a direct merge only, so `--auto` is refused; the pin is read from arguments, not raw text; "newest" is the transcript timestamp, across sessions, with ledger and transcript verdicts equal; REST pin forms enumerated; actions without a pull request keep today's rule; Rule_Text covers the gate's messages, ANATOMY and the QA skill. |
| 2026-10-01 | Analyze pass 2 (FIX-FIRST): the pin is read with gh's value-flag table, so a pin that is another flag's value does not count; the lookup is narrowed by ledger rows before any transcript is opened and blocks past 3 seconds (AC-14, AC-15); the bypass lifts the `--auto` refusal too, and "approved" is defined; who uses auto-merge is measured; the gate's own messages are a task. |
| 2026-10-01 | Analyze pass 3 (FIX-FIRST): clustered short flags are walked letter by letter; the ledger narrows by pull request only, so a row whose ledger commit differs from its transcript cannot hide a verdict; only regular files are opened; the deadline is a daemon thread joined for 3 seconds, which pre-empts a blocked read. |
| 2026-10-01 | Analyze pass 4 (FIX-FIRST, plan only): the reflex reads verdict, scope and head from the transcript report consumers re-read, not from the payload, so a quoted line in the payload cannot write a ledger row that hides a revocation. |
| 2026-10-01 | Analyze pass 5 (FIX-FIRST): measured on the real ledger, a resumed reviewer's later reply changed what its earlier receipt re-read as; each receipt is now anchored to the entry it was recorded from (AC-02, AC-16, AC-17); the converge consumer's same exposure is named as a follow-up. |
| 2026-10-01 | Analyze pass 6 (FIX-FIRST, plan only): the anchored entry is read from the whole transcript, not the 256 KB tail, and a uuid on several lines must agree; the converge follow-up is filed as a tracked issue with the pull request. |
| 2026-10-01 | Analyze pass 7: READY, 17 of 17 criteria covered. Whole-transcript reads measured at 0.58 s for the busiest real pull request (47 receipts, 68.5 MB). Status approved. |
| 2026-10-01 | QA cycle 1 (NEEDS-WORK at 8053ec5): an unpinned merge chained after a pinned one (`|| gh pr merge <n>`) and a pin hidden behind a shell comment both passed; a NEEDS-WORK whose head was missing or malformed revoked nothing. Added AC-18 and AC-19. |
| 2026-10-01 | Converge pass 2 and QA cycle 2 (at a3588bb): `&`, `|&` and a comment carrying an apostrophe still chained an unpinned merge; shlex's mid-word comment hid a later pin; ties fell back to ledger order. Covered by T14-T19 under the existing AC-05, AC-08, AC-13 and AC-19. |
| 2026-10-01 | Converge pass 3 (at b1b5022): backslash-newline, heredoc bodies, `$'...'`, an escaped blank, reserved words and quoted command words still misled the hand-written reader. Rather than chase bash shape by shape, AC-20 makes the approved path read only plain commands; the splitter also skips heredoc bodies (bash never runs them) unless fed to a shell. Replayed over 20,858 real commands: 1 new detection (a real `time gh api ... /merge`), 16 dropped (all text inside heredoc bodies), 478 that would block only while an approval is exported. |
| 2026-10-01 | Converge pass 4 (at 7076d54): honest forms still missed (path-qualified gh, `timeout`/`exec`/`nohup`/`time -p`, attached `-R<slug>`, a comment after `)`) are now read; a pin hidden by brace or variable expansion blocks on the approved path; deliberate obfuscation through variables, functions and aliases is named in Out of Scope as the gate's stated residual. |
| 2026-10-01 | QA cycle 4 (at 7076d54): skipping heredoc bodies "unless fed to a shell" was a deny-list that missed `| bash`, `exec`, `env`, `source /dev/stdin` and more, and a `<<` inside arithmetic hid every later line, in both gates. Bodies are read again, line by line; arithmetic shifts are not heredocs; `$'...'` is decoded before the AC-20 mention test; `gh pr -R <slug> merge` is read. The three cycle-3 replay figures above described the skipping design and no longer hold. |
| 2026-10-01 | Converge pass 5 (at d37d0b8): a redirection between a value flag and a pin shifted the pin gh sent; wrappers the gate cannot enumerate (`env -u`, `stdbuf`, `setsid`, `xargs`) ran an unpinned merge under an approval; `{owner}/{repo}` and a subshell's `)` blocked honest pinned merges. Redirections are removed before the pin walk, a brace counts only as an expansion, and while an approval is exported any sub-command that names a merge without being identified as one blocks. |
| 2026-10-01 | QA cycle 5 (at d37d0b8): the bash-shaped reader still diverged from the previous one where bash agrees with the previous one (`$'` inside double quotes, a `#` after NBSP or VT, a continuation or a multi-line quote inside a heredoc body), so both gates missed what master caught. Detection is now the union of both readings; on the approved path a command the two disagree on blocks. Replayed over 20,997 real commands: 0 detections lost in either gate. |
| 2026-10-02 | Converge pass 6 (at c807e0e): pflag's `-<bool>=<value>` cluster end and a named-fd redirection `{x}>` each let the gate check one pin while gh sent another, and a flag before the PR number read as branch `unknown`. Root cause for the first two: the gate chose among several pins. A pin must now occur exactly once in the command, so any misreading of gh's grammar loses it (and blocks) rather than swapping in another commit; both point bugs are fixed too, and the PR is read as the first positional. |
| 2026-10-02 | QA cycle 6 (at c807e0e): the union held for detection, but the repo-scope check took its `cd`s from the bash-shaped reading, so a `cd` inside a heredoc body moved the target out of a protected repo; and the union loosened seek receipts. The target is now judged once per reading and gated when any reading lands in a protected or unresolvable repo; a seek counts only when both readings find it; a named-fd redirection is a redirection. |
| 2026-10-02 | Converge pass 7 (at 0f13554): gh accepts merge's flags between `pr` and `merge` (`gh pr -t x merge 96`), which hid the merge; a carriage return split a word for shlex but not for bash; `GH_REPO`, a PR URL and a repeated `-R` could rule an approved merge out of scope. Flags between `pr` and `merge` are moved after it with gh's value-flag table, words split on bash's blanks only, the last `-R` wins, and the PR number the operator approved is never ruled out of scope. Unapproved repo scope through `GH_REPO` and URLs stays with issue #351. |
| 2026-10-02 | QA cycle 7 (at 0f13554): seek receipts still loosened inside `sh -c`, the autonomous-chat waiver rested on whichever reading named an allowlisted chat first, and an approved API merge took its PR number from the first `/pulls/N/merge` anywhere in the text (a field, a GraphQL body). The reader now reaches every `sh -c` level, the waiver needs every recipient under both readings listed, and an approved `gh api` merge must name the approved PR in its own REST endpoint with one merge path in the text; GraphQL merges are refused on the approved path. |
| 2026-10-02 | Converge pass 8 (at 898e387): gh resolves `<url>/files`, `<url>#comment`, `#96` and `096` to a pull request, which the gate read as `unknown`, so an approved merge from a non-protected directory skipped its receipt. The gate reads every one of those forms, and while an approval is exported scope ungates only a merge whose target is a number it read and that differs from the approved one; an unreadable `gh pr merge` target blocks and asks for the number. |
| 2026-10-02 | QA cycle 8 (at 898e387): reading the LAST `-R` from raw text took a `-R` inside a quoted `--body` or `--subject`, so a protected merge went ungated without an approval where master gated it. Every `-R/--repo` value in the text is now a scope candidate: any protected or unparseable one gates, only all-unprotected ungates. A `sha[` field also counts as a second pin candidate. |
| 2026-10-02 | Converge pass 9 (at 37ffb37): an attached or clustered `-R` (`-RCarlosCaPe/octorato`, `-dR <slug>`, before or after `pr`) was not a scope candidate, so a protected merge from another directory went ungated, as on master. `-R/--repo` candidates are now also read from gh's words in every form gh accepts; the REST path normalises a zero-padded PR number. |
| 2026-10-02 | QA cycle 9 (PASS at 37ffb37, with should-fix items): an exported approval blocked `git push origin main` in every non-protected repo; a repo named only inside a quoted value ungated a merge in a protected directory, as on master; `OCTO_MERGE_APPROVE` was not normalised; `+350` was not read. The approved-scope rule now applies only to an unreadable pull request, never a branch push; real `-R` flags come from gh's words and a quoted-only repo leaves the decision to the directory; the approval is normalised like the PR number; `+n` and `#+n` are read. |
| 2026-10-02 | Converge pass 10 (at 5c215a9): gh's root skips a merge flag placed before `pr` (`gh --subject=x pr merge 96`, `gh -dR<slug> pr merge 96`) and still runs the merge, which the gate did not see, as on master. Flags before the subcommand are now read the way cobra's root `stripFlags` skips them and moved after it, so detection, the pin and the scope candidates see them. |
| 2026-10-02 | QA cycle 10 (FAIL at 5c215a9): reading every word that starts with `-R` as a repo flag took the value of another flag (`--body "-Rother/repo"`, `-t -Rother/repo`), so a merge in the protected directory went ungated without an approval, where master gated it. Real `-R/--repo` values now come from the same pflag walk the pin uses, over the canonical argv, so a word another flag consumes is never a repo. |
