#!/usr/bin/env python3
r"""PreToolUse Bash hook — QA gate (FAIL-CLOSED for merge actions).

NOTE on security boundary: the command-matching below IDENTIFIES the action; the
AGENT-PROOF env channel (OCTO_MERGE_APPROVE, which an inline env cannot pass to
the harness-run hook) AUTHORIZES it. The two fail differently, and conflating
them is how this gate was bypassed: the env channel is immune to FORGERY, not to
EVASION. Authorization is only consulted AFTER the command is identified as a
merge, so a command shape the matcher does not identify never reaches the env
check at all — an evasion is a total bypass, not a degraded authorization.
Detection is command-boundary-anchored: the string is split on UNQUOTED shell
separators (; && || | & newline), heredoc BODIES are removed (they are data on
stdin, not command lines), and each sub-command is matched at EVERY command-head
position it contains, on DECODED tokens. Decoding is what makes `gh "pr" merge`,
`gh pr $'\x6derge'` and `gh pr $"merge"` the same command as `gh pr merge` — all
four spellings of quoting (`'…'`, `"…"`, ANSI-C `$'…'`, locale `$"…"`, plus the
backslash) are resolved by the SHELL before the program runs, so they are
resolved here too. Decoding also TRUNCATES where bash truncates: a bash word is
a C string, so `$'pr\x00xx'` is the word `pr` (measured, bash 5.2.21), and
keeping the bytes past that NUL let four spellings walk in cycle 8.
It cannot manufacture a verb out of a quoted MENTION
(`git commit -m "gh pr merge 96"`), because a whole-token quote is ONE token and
one token can never supply the two words a verb needs after a head.
Between the head and the verb, an ENUMERATED set of the tool's own GLOBAL
options is skipped, on TOKENS, each with its value consumed the way that tool
consumes it: `-R`/`--repo` for gh, attached, `=`-joined or in the next word,
before the `pr` group and before the verb (every one of those positions measured
accepted by the installed gh 2.88.1, which returns `{"number":288}` for
`gh pr -R CarlosCaPe/octorato view 288 --json number`), and git's documented
globals (`_git_globals_end`, `_gh_globals_end`). "EVERY position" means
every position in that enumeration, never "any word starting with a dash" — a
general dash-skip would hand the verb a place to hide behind a crafted flag.
ON TOKENS is the cycle-8 correction. The skip used to be a REGEX whose value was
`\S+`, matched against a form flattened by joining decoded tokens with spaces, so
a value that CONTAINS a space became two words and the verb vanished behind them
(`git -c 'core.pager=less -F' push origin main` measured pushing for real), and
the same regex accepted only `-R x` and `-R=x` while pflag also glues the value
on (`gh -Rowner/repo pr merge 288`, measured).
Cycle 7 measured eight spellings walking the old adjacency requirement,
`gh pr -R X merge N` (the spelling in gh's own docs) among them; cycle 8 measured
six more walking the enumeration's own grammar.
A head whose STRING ARGUMENT is itself a command (`bash -c`, `sh -lc`, `eval`,
`ssh host`, `script -qc`, a shell reading a heredoc) has that argument
re-identified; a head that does not re-parse (`git commit`, `echo`, `cat`,
`python3 -`) does not. That property, not the presence of quotes, is the line —
and since QA cycle 5 it is decided by the HEAD rather than by a list of channels
(`_INERT_ARG_HEADS`), because a list of channels loses to the next channel.
Three CHANNELS run a span of the line as a line of its own no matter what the
head is, so they are read before the head is even consulted: a command
substitution `$(…)` or `` `…` `` (`_command_substitution_texts`), a process
substitution `<(…)`/`>(…)`, and a `|` into something that executes its stdin
(`_runs_its_stdin`).

RESIDUAL — ELEVEN, each one MEASURED against this file on 2026-09-08 by feeding
the payload on stdin (deny = exit 2). This list is what remains, not what is
convenient — an earlier one omitted five reachable families. It is the CANONICAL
count: `skills/agent-proof-approval-gate`, `skills/command-boundary-hook-matching`
and `docs/architecture/v7-nothing-ships-unverified.md` summarize this list and
used to read 4, 3 and 5 against a header that said 7, which is how a residual
stops being tracked. One number, four surfaces, reconciled 2026-09-08.

  1. The VERB supplied by an expansion instead of by literal text:
     ``X="pr merge"; gh $X 291``, ``$(echo "gh pr merge 291")``,
     ``C="gh pr merge 291"; eval "$C"``. All measured ALLOW. The opaque-HEAD
     case is closed (``$(echo gh) pr merge 291``, ``${PATH:0:0}gh``, ``$'gh'``,
     ``G=gh; $G pr merge 291`` all deny) because the remainder still carries the
     verb. CORRECTED in cycle 7: `$'gh'` is listed there as closed and it was
     closed only at the HEAD position, for that same reason. In every OTHER
     position ANSI-C quoting walked — `gh pr $'merge' 288`,
     `gh pr $'\x6derge' 288`, `git push origin $'main'` and nine more, all
     measured executing a fake binary on PATH. None of them is an expansion:
     `$'…'` and `$"…"` are QUOTING, so they are decoded in the tokenizer and
     leave this residual entirely. What remains here is the case where a
     VARIABLE supplies the verb.
     Substituting same-line assignments everywhere would close this and
     would also deny ``docs='gh pr merge'; echo $docs``, a legitimate command in
     the over-fire corpus, so it is left open and named rather than traded for a
     false positive.
  2. A merge that lives in a FILE this hook never sees: ``./deploy.sh``,
     ``printf ... > /tmp/x.sh; bash /tmp/x.sh``, a Makefile target, a git hook.
     Measured ALLOW. The gate reads the command string, not the filesystem.
  3. A merge through a NON-SHELL runtime: ``python3 -c "...requests.put(...)"``,
     node, or any HTTP client that is not curl. Measured ALLOW. Only `gh api`
     and `curl` are recognized API tools. It also covers a runtime that SHELLS
     OUT, which is the same hole with a shorter spelling:
     ``awk 'BEGIN{system("gh pr merge 291")}'`` — measured ALLOW and measured
     EXECUTING a fake `gh` on PATH (QA cycle 5). Identifying a merge inside one
     of these means writing an interpreter for that language: the argument is a
     PROGRAM, not a command line, and `perl -e`, `ruby -e`, `node -e`,
     `php -r`, `lua -e` and `sed -e 'e …'` are all the same shape. They are in
     `_INERT_ARG_HEADS` for exactly that reason, so the cost is stated here
     rather than paid as an over-fire on every awk one-liner.
  4. `gh repo set-default`, which records a resolved base repo in the cwd repo's
     own git config; the cwd repo here resolves by its remote `url`. Measured
     ALLOW as a command; its EFFECT on a later `gh pr merge` is not measured (no
     such config exists to test against), so it is stated, not claimed fixed.
  5. A REPO-LOCAL git alias: `_git_aliases` reads only the user-global config,
     because the target repo is not resolved until after identification. The
     DEFINITION is gated on any line that writes one (`git config alias.x`,
     `git -c alias.x=`), so this is reachable only across two separate tool
     calls into a repo that already carried the alias.
  6. GH_REPO/GH_HOST/GH_CONFIG_DIR set in a way this hook cannot see. All three
     channels that ARE reachable are read (see _line_env): the inline prefix, a
     same-line export, and the harness process env. A Bash tool call does not
     keep exports for the next call — measured — so there is no fourth today.
  7. The v7 boundary itself: the receipt files live under $HOME and the model can
     append to them. Only the harness env (OCTO_MERGE_APPROVE) is a real
     boundary. See docs/architecture/v7-nothing-ships-unverified.md.
  8. The ALLOW-side enumerations. There are TWO of them now and they nest:
     `_NON_SHELL_C_HEADS` ⊂ `_INERT_ARG_HEADS`. Cycle 5 made the choice
     deliberate rather than accidental — see `_INERT_ARG_HEADS` — so this file
     carries its enumeration on the HEAD dimension (the programs whose arguments
     are text: finite, famous, and failing LOUD as an over-fire) instead of on
     the CHANNEL dimension (open-ended: five new members arrived in one cycle).
     The cost of the outer set is the same shape as the inner one described
     below: a head listed there whose argument really IS a command walks. A
     program
     whose `-c` means COUNT or QUERY is exempt from the unnamed-wrapper `-c`
     reading, which is what ended the `grep -c` / `grep -rc` / `psql -c`
     over-fire class. Two edges, both measured, both stated rather than traded:
     a wrapper deliberately NAMED for a counter escapes that reading
     (``./grep -c "gh pr merge 291"`` — ALLOW), and an unlisted counter reached
     through ANOTHER program can still over-fire (``xargs grep -c "…"`` — DENY).
     The ``find . -exec grep -c "…" {} ';'`` half of that sentence was STALE:
     re-measured in cycle 7 it is ALLOW, in both the quoted `';'` and the
     backslash spelling. The direction is harmless — an over-fire that is not
     there — but an unmeasured claim is exactly what this file keeps catching in
     other people's code. The exemption is anchored on the HEAD
     word ALONE, because any other anchor re-opens the path-argument bypass this
     cycle just closed: ``flock /var/lock/grep -c "gh pr merge 291"`` and
     ``flock /var/lock/psql -c "…"`` both still DENY, and that is the trade.
     The DENY-side enumeration is the same shape on the same dimension, and it
     is named here because cycle 8 measured its cost. The global-option sets
     (`_GIT_GLOBAL_BOOL` and its three valued siblings, `_GH_GLOBAL_LONG_VALUE`
     and its shorthand pair) decide which words may sit between a head and its
     verb, and a member nobody listed is a MISS, not the loud over-fire the
     allow-side sets fail with. What cycle 8 replaced was not the lists but the
     GRAMMAR they were applied with, so what remains exposed is a global option
     that EXISTS and is unlisted, never another spelling of one that is listed:
     the three whitespace-in-value spellings and the two attached-shorthand ones
     it measured were all members of lists that already named their option.
  9. Parse TIME. `hooks.json` gives this gate 5 s; a hook killed at its budget
     writes no stdout, and the harness reads that as ALLOW, so a slow parse is a
     bypass with a stopwatch. Four superlinear paths were fixed this cycle, all
     measured whole-parse unless noted:
       - `_peel_candidates` built and joined a tail LIST per token, head or not:
         20000 benign words 39.7 s -> 0.43 s.
       - `_api_write_action` ran a 1.7 ms regex per synthesized `curl` candidate,
         and an opaque head synthesizes one per token: 8000 `$a` 52.2 s -> 0.7 s.
       - `_alias_definition_form` ran two lazy `[^|&;]*?` regexes per candidate:
         0.004 s vs 1.282 s for 200 calls on a 36 KB sub-command.
       - `_split_heredocs` scanned every remaining line per `<<WORD`: 9.2 s ->
         0.03 s at 8000 openers, measured on the function.
     THREE shapes stay superlinear and are BOUNDED rather than eliminated, all
     re-measured as the min of 3 runs on 2026-09-08 after the cycle-5 fixes. A
     crafted line alternating an opaque token with a write-marker flag
     (``git $a -f $a -f …``) sits at 2.90 s at 2500 pairs and 4.99 s at 3500, so
     3500 pairs is the edge of the budget. A 6000-LINE pasted script costs
     1.20 s of CPU for an unrelated reason — every line is its own sub-command
     and each one is normalized. The 3.38 s WALL figure this paragraph used to
     carry, and the "inside the budget up to about 10000 lines" that followed
     from it, were taken on a quiet box and stated without their load: cycle 7
     measured the same 6000 lines at 5.40 s of wall at load 18.8, which is OVER
     the 5 s budget. CPU is the load-free number and is the one quoted here now;
     the wall figure is a range, not a constant, and the 10000-line headroom
     only exists on an idle box. NEW in
     cycle 5, the price of reading command substitutions: a line of N distinct
     `$(…)` whose contents name a head runs each one through the recursion —
     0.56 s at 1000, 1.48 s at 2000, 3.05 s at 4000, so roughly 6000 reaches the
     budget. Two costs the recursion exposed were paid down rather than
     accepted: `_line_env_chain` walked the whole process environment per cache
     miss and now reads three keys (4.98 s of a 9.34 s parse, profiled), and both
     new scans carry a `_may_publish` pre-filter (20000 benign words 5.10 s ->
     1.01 s, which is BETTER than the 1.33 s this shape cost before the cycle).
     It was called "sound by construction" and it is sound only for the ALPHABET
     its flatten table knows, which cycle 7 walked: the hex row
     `$'\x6d\x65\x72\x67\x65'` flattens to `$x6dx65x72x67x65`, carries none
     of the five probe words, and a substitution holding it was dropped before
     the recursion could look at it. The probe now decodes ANSI-C and locale
     quoting first, with the same reader the tokenizer uses; the decode only
     ever ADDS text, so it can widen the filter and never narrow it.
     What is FENCED and what is only MEASURED are different lists, and
     CORRECTED in cycle 7 the fenced list is not uniform either: "each leg
     asserted against the 5 s budget itself" is true of the WHOLE-PARSE legs
     only. Two fences are function-level and assert their own line, because the
     whole-parse budget could not tell the fix from the revert — `_split_heredocs`
     at 1.0 s on 8000 openers and `_alias_definition_form` at 0.2 s for 200
     calls — and the alias one appeared in neither list below. A third, added in
     cycle 7, asserts CPU rather than wall (see the failability note at the end
     of this residual). Cycle 6 caught this paragraph conflating fenced with
     measured: it said
     the substitution shape was "pinned by TestTheParseFitsTheHookBudget" when
     no leg in that class carried a `$(` at all — the one cost this cycle
     introduced was the one cost with no regression fence. FENCED against the
     5 s budget itself rather than against a ratio, because the budget is the
     contract: 20000 benign words, 5000 opaque tokens, 2000 `<<` openers, 1500
     opaque-token/write-marker pairs, and 3500 `$(…)` substitutions naming a
     head. FENCED on a FUNCTION and against its own line, because the whole
     parse could not tell: `_split_heredocs` (1.0 s on 8000 openers) and
     `_alias_definition_form` (0.2 s for 200 calls). FENCED on CPU and against
     2.5 s, because wall clock straddles: the 3500-substitution parse in a
     ~900-variable child. MEASURED and NOT fenced: the edges themselves (3500
     pairs, ~6000 substitutions, the script-line edge, which is load-dependent
     and NOT ~10000 on a busy box) and the crossover curves above. A fence sits BELOW its shape's edge on purpose: at the edge,
     3500 pairs measures 4.07 s at load 17, a margin of 1.2x that is red the
     first busy day, and a fence that goes red under normal agent load is
     deleted, which is worse than no fence. Sizes are picked against a BUSY box
     (loads 8 to 20 on 4 cores, five sibling agents) and the two bounded legs
     take the min of five runs: worst of eight rounds is 0.84 s at 1500 pairs
     and 1.86 s at 3500 substitutions. Where the two pressures met, failability
     won: 2000 and 2500 substitutions are quieter (1.09 s worst at 2500) and
     both leave the regression below GREEN, so the leg sits at 3500 and spends
     the headroom down to 2.7x — a fence that cannot fail is not a fence, and
     2.7x is still three times the margin a fence at the edge would have. That
     failability was RUN, not claimed, and the runs that stayed green are
     reported too: with `_line_env_chain` reverted to the whole-process walk in
     a copy of the tree, the leg fails at 5.44 s of the 5 s budget on a
     491-variable environment against 1.33 s for the fix, and on the same revert
     it also came back green twice, at 4.04 s and 4.6 s, when the box was
     quieter. That straddle is the honest limit of a wall-clock budget
     assertion: the revert costs a steady 4x-6x, but this box swings about 3x in
     throughput between load 8 and load 20, so a fixed 5 s line lands inside the
     regression's range rather than below it. The leg catches this regression at
     the loads where it crosses 5 s, which is what the contract says, and it is
     not a detector for every constant-factor cost — on a 91-variable
     environment the same revert is 2.33 s against 1.34 s and stays green, and
     that env-size dependence is exactly what the three-key read removes.
     FAILABILITY, and a REASON that was wrong. Cycle 6 declined a sensitivity
     fence on the ground that it "needs `os.environ` mutation" and this brain
     carries a lesson about that leaking across modules. The lesson is about
     IN-PROCESS writes to `os.environ`; `subprocess.run(env=…)` writes nothing
     in the test process, and it is also how the hook actually runs — the
     harness spawns it with an environment rather than importing it. Wall clock
     is not the only clock either: `time.process_time()` removes the load axis
     the straddle above lives on, because CPU stays within 1.1x-1.3x on this box
     while wall swings 3x-5x. So the straddle is now fenced rather than only
     described. `test_the_env_read_is_flat_in_a_fat_environment` spawns one
     interpreter with ~900 padded variables and asserts the CPU of the
     3500-substitution parse under 2.5 s: measured 0.52 / 0.53 / 0.62 s with the
     three-key read and 4.62 / 4.80 / 5.60 s with it reverted to the
     whole-process walk. The first size tried, ~450 variables, was rejected for
     being red by only 1.02x (2.55 / 2.92 / 2.68 s) — red on this box is not red
     on a quieter one. The wall-clock leg stays the BUDGET contract; this one is
     the REGRESSION contract, and they measure different things on purpose.
     A cross-product shape QA built in cycle 7 (100 substitutions against 200
     opaque/`-f` pairs, 121 KB) measured 11.29 s of wall at load 18 and 2.36 s
     of CPU — residual 9's known quadratic rearranged rather than a new class,
     and inside the budget on a quiet box. On how a payload REACHES this gate:
     it arrives as JSON on stdin, not as argv, so no ARG_MAX bound applies to
     the gate at all; and the harness runs Bash tool calls in a PERSISTENT shell
     (measured — a `cd` in one call is still in effect in the next), so the
     command is written to that shell rather than passed as one `bash -c`
     argument. The ~128 KB single-argument limit bounds neither path.
     Cycle 8 walked into this residual rather than only reading it: moving the
     option grammar onto tokens made the git ALIAS expansion tokenize its own
     candidate, and a candidate is a per-token SUFFIX, so 800 opaque tokens went
     from 0.09 s to 14.4 s and 5000 from 1.0 s to 324 s — caught by the 5000-token
     leg below, which is what that leg is for. The fix is the same one this
     residual keeps making: the peel already holds the tokens, so it hands them
     to every reader instead of letting each one rebuild them.
     One fixture backs the opaque-argument shape
     (benign_long_opaque_argument_list.json): the selftest harness kills a leg
     at 30 s, which is what turns time into a verdict a fixture can assert. The
     heredoc scan has no fixture — proving it
     needs a 240 KB payload — and is unit-anchored only.
 10. bash 5.3's funsub spellings of command substitution, ``${ cmd; }`` and
     ``${| cmd; }``. NOT reachable on the installed bash (5.2.21): measured
     `noexec`, a syntax error, so there is no way to run a fixture pair for them
     here and wiring them would be a claim rather than a mechanism. They are
     listed as a residual and not as a bypass because all four spellings measured
     DENY today anyway — `${` carries a `$`, so the opaque-head reading takes the
     remainder and finds the verb. That is a coincidence of the opaque path, not
     coverage of the channel: on bash 5.3 the honest fix is two more openers in
     `_command_substitution_texts`, with the fixture pair that box can run.
 11. A pipe whose consumer executes stdin only after ANOTHER hop:
     ``echo "gh pr merge 291" | ssh host bash`` (ssh forwards the stream to a
     remote shell) and ``echo "…" | tee /tmp/x.sh; bash /tmp/x.sh`` (which is
     residual 2 wearing a pipe). Measured ALLOW. `_runs_its_stdin` reads the
     stage on the right of the `|`, and in both of these that stage executes
     nothing itself.

KNOWN COST, not a hole: a gh-merge line whose PR number the RAW parse cannot
read (`gh "pr" merge 291`, `gh pr $'merge' 291`, an unclosed quote) is identified
as a merge and falls to the 'unknown' sentinel, which no approval can name — so
that spelling denies forever, even for the operator. The number is read off the
raw form on purpose: flattening the quoting there would read a flag VALUE as the
PR (`-t $'x 280' 281` merges 281). The GLOBAL-OPTION spellings closed in cycle 7
are NOT in this class and were checked for it: `gh pr -R owner/repo merge 288`
and its five siblings all still read 288, because the option is skipped inside
the same anchor that finds the verb, so the remainder the number is read from
starts where it always did. Cycle 8's spellings were checked the same way and
are not in this class either: `gh -Rowner/repo pr merge 288` reads 288, and so
does `git -c 'core.pager=less -F' push origin main` for its branch. The class is
decided by a token's SPELLING, not by its position — `_gh_merge_pr_num` reads the
number only when the head and both verb words occupy exactly their own decoded
length, which is what a quote or an escape breaks.

When a Bash command is detected as a merge action, this hook BLOCKS execution
unless the operator's AGENT-PROOF env approval is present for EVERY merge
sub-command in the line.
Detected forms: `gh pr merge` (including through a gh ALIAS, resolved from gh's
own config, and the alias DEFINITION that would arm one); `git push` directly to
main/master; and the gh api / curl API equivalents (a write call to REST
`/pulls/<N>/merge`, a GraphQL `mergePullRequest` / `enablePullRequestAutoMerge` /
`mergeBranch` mutation, `POST /repos/.../merges` into main/master, or a
`PATCH`/`DELETE` of `/git/refs/heads/(main|master)`). API reads pass; only a
write method or body flag qualifies. The one channel, plus its receipt waiver:

  1. OCTO_MERGE_APPROVE=<pr_number>  — env var, PR-scoped, AGENT-PROOF (preferred).
     A PreToolUse hook runs in the HARNESS process and does NOT inherit env vars
     the agent sets inline (e.g. `OCTO_MERGE_APPROVE=96 gh pr merge 96` does NOT
     reach this hook).  Only the operator, who exports the var in their shell
     before invoking Claude Code, can set it — making it a true operator signal.

  2. OCTO_QA_OK=1: an explicit waiver of the QA RECEIPT for the PR named in
     OCTO_MERGE_APPROVE. It is not a channel and authorizes nothing on its own:
     without a matching OCTO_MERGE_APPROVE=<same pr> the merge is still denied.
     Scope, precisely: per COMMAND, not per session-lifetime "once" — nothing
     consumes it, so every merge of that same PR while the shell keeps the var
     exported is waived. DISCOURAGED; unset it after the merge it was for.

The file channel (~/.claude/connectome/merge-approvals.json, written by
octo-dim.py approve-merge) is NO LONGER an authorizer: an agent owns its own
process env, so it can strip the agent-shell markers (`env -u CLAUDECODE ...`)
or pass --i-am-the-operator and forge that file, which made it a self-approval
route. Only the harness env, which the agent's command-scoped env never reaches,
is a real boundary. octo-dim approve-merge is kept as an operator audit log
(listed by `approvals`), not a gate pass.

v7 (2026-09-05): approval is necessary, not sufficient. A merge also needs a QA
receipt for the PR in the receipt ledger (~/.claude/.cache/receipts/global.jsonl),
written by the SubagentStop hook from a QA subagent's QA-VERDICT/QA-SCOPE lines
and re-read from that agent's transcript. OCTO_QA_OK=1 is the explicit bypass of
that receipt only, and only for the PR named in OCTO_MERGE_APPROVE.
Fail-closed ONLY for positively-identified merge commands.
Any parsing error on a non-merge command → exit 0 (fail-open).
Design mirrors grafo-gate.py: same I/O protocol, same stdin JSON shape.

Operator directive 2026-06-01: NO deploy without QA agent approval.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
# Force UTF-8 on stdout/stderr so the ✓ / ✗ / em-dash glyphs in reports
# survive on Windows shells defaulting to cp1252. Without this, a script
# can do its work correctly and still crash with UnicodeEncodeError when
# printing success. Applied repo-wide by _apply-utf8-reconfigure.py.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


# ---------------------------------------------------------------------------
# Anchored publish patterns — applied to the START of each sub-command token.
# Using ^\s* because after splitting we still want to tolerate leading spaces.
# ---------------------------------------------------------------------------

# GLOBAL-OPTION GRAMMAR — where a global option's VALUE ends.
# ADJACENCY IS NOT THE COMMAND. `gh -R owner/repo pr merge 288`,
# `gh --repo=owner/repo pr merge 288` and `gh pr -R owner/repo merge 288` all run
# the same merge — the last of those is the spelling in gh's own `pr merge`
# docs — and all three walked this anchor until cycle 7 measured them. So a run
# of the tool's own global options is skipped between the head and the verb,
# each one with its value consumed AS a value: a general "skip any word starting
# with a dash" would let a crafted flag hide the verb behind it.
# Cycle 7 wrote that skip as a REGEX whose value was `\S+`, matched against a
# form built by joining decoded tokens with single spaces, and cycle 8 measured
# what that costs. A value that CONTAINS whitespace is one shell word, the
# flattening turns it into two, and the anchor loses the verb behind it:
# `git -c 'core.pager=less -F' push origin main`, `git -c "user.name=Q A" push
# origin main`, `git -C "/p/sp ace" push origin main` and the `--git-dir` /
# `--work-tree` pair over the same path all pushed for real to a local bare
# remote while this gate returned 0. `git -c user.name=QA push origin main` — the
# same shape with no space in the value — denied, which is what isolated the
# cause to the whitespace rather than to the option. `-c 'core.pager=less -F'` is
# a spelling people type by hand.
# The same regex missed gh's ATTACHED shorthand value: pflag accepts `-Rvalue`
# glued together and `_GH_GLOBAL_OPT` accepted only `-R x` and `-R=x`, so
# `gh -RCarlosCaPe/octorato pr merge 288` and `gh pr -RCarlosCaPe/octorato merge
# 288` both walked (gh 2.88.1 measured accepting the glued form on `pr view`,
# returning 288, and `pr merge 999999` measured reaching GitHub's
# `repository.pullRequest` lookup, so the flag parsed and the verb ran).
# So the skip below runs on TOKENS, and each tool gets the attach grammar it
# actually implements. Both are FINITE and documented, which is why they are
# written down once here instead of pattern-matched:
#   git — hand-rolled in git.c, measured against the installed git 2.43.0: the
#     two shorthands `-C`/`-c` read the NEXT argv and REJECT both `-cx` and
#     `-c=x`; every long option takes `--opt=value` or `--opt value`;
#     `--exec-path` is `=`-attached only, because bare `--exec-path` prints the
#     path and runs no subcommand at all.
#   gh — pflag, measured against the installed gh 2.88.1: a shorthand takes its
#     value ATTACHED (`-Rowner/repo`), `=`-joined (`-R=owner/repo`) or as the
#     next word (`-R owner/repo`); in a cluster the FIRST value-taking shorthand
#     ends the token and swallows the rest of it as its value. The cluster rule
#     is written as grammar rather than as spellings, and `_GH_GLOBAL_SHORT_BOOL`
#     is EMPTY today because gh registers no boolean global shorthand (`gh --help`
#     lists only `--help` and `--version`), so a future one is a set entry rather
#     than a new parser.
# An option omitted from either enumeration can only cost a MISS, never an
# over-fire, so both err toward listing — see residual 8 on what that costs.
_GIT_GLOBAL_SHORT_VALUE = frozenset({"-C", "-c"})
_GIT_GLOBAL_LONG_VALUE = frozenset({
    "--git-dir", "--work-tree", "--namespace", "--super-prefix",
    "--attr-source", "--config-env",
})
_GIT_GLOBAL_ATTACHED_VALUE = frozenset({"--exec-path"})
_GIT_GLOBAL_BOOL = frozenset({
    "-p", "-P", "--paginate", "--no-pager", "--no-replace-objects",
    "--no-lazy-fetch", "--no-optional-locks", "--no-advice", "--bare",
    "--literal-pathspecs", "--glob-pathspecs", "--noglob-pathspecs",
    "--icase-pathspecs",
})
# `--no-lazy-fetch`, `--no-advice` and `--super-prefix` are rejected by the
# installed git 2.43.0 before a subcommand. They stay listed on purpose: a newer
# git accepts them, and an option the local git refuses can only cost a deny on a
# line that was never going to run.

_GH_GLOBAL_LONG_VALUE = frozenset({"--repo"})
_GH_GLOBAL_LONG_BOOL = frozenset({"--help", "--version"})
_GH_GLOBAL_SHORT_VALUE = frozenset("R")
_GH_GLOBAL_SHORT_BOOL = frozenset()


def _git_global_step(toks: list[str], i: int) -> int:
    """Index after the ONE git global option at *i*, or *i* when it is not one."""
    t = toks[i]
    if t in _GIT_GLOBAL_BOOL:
        return i + 1
    if t in _GIT_GLOBAL_SHORT_VALUE or t in _GIT_GLOBAL_LONG_VALUE:
        return i + 2                       # git.c reads the next argv, always
    name, sep, _v = t.partition("=")
    if sep and (name in _GIT_GLOBAL_LONG_VALUE
                or name in _GIT_GLOBAL_ATTACHED_VALUE):
        return i + 1
    return i


def _git_globals_end(toks: list[str], i: int) -> int:
    """Index of the first token after git's global options, starting at *i*."""
    n = len(toks)
    while i < n:
        j = _git_global_step(toks, i)
        if j == i:
            break
        i = j
    return i


def _gh_globals_end(toks: list[str], i: int) -> int:
    """Index of the first token after gh's global options, starting at *i*."""
    n = len(toks)
    while i < n:
        t = toks[i]
        if t.startswith("--"):
            name, sep, _v = t.partition("=")
            if sep and name in _GH_GLOBAL_LONG_VALUE:
                i += 1
            elif t in _GH_GLOBAL_LONG_VALUE:
                i += 2
            elif t in _GH_GLOBAL_LONG_BOOL:
                i += 1
            else:
                break
            continue
        if len(t) > 1 and t[0] == "-":
            j, takes_next = 1, False
            while j < len(t):
                c = t[j]
                if c in _GH_GLOBAL_SHORT_VALUE:
                    takes_next = j + 1 == len(t)   # nothing attached: next word
                    j = len(t)                     # the rest of the token IS it
                    break
                if c in _GH_GLOBAL_SHORT_BOOL:
                    j += 1
                    continue
                break                              # unknown shorthand: not ours
            if j < len(t):
                break
            i += 2 if takes_next else 1
            continue
        break
    return i


def _gh_merge_anchor(toks: list[str], base: int):
    """(index of `pr`, index of `merge`) in `gh [globals] pr [globals] merge`.

    None when *toks* from *base* is not that. Token EQUALITY, not a regex over a
    joined string: both verbs are whole words to the shell, and a joined form
    cannot tell one word containing a space from two words.
    """
    i = _gh_globals_end(toks, base)
    if i >= len(toks) or toks[i] != "pr":
        return None
    pr_i = i
    i = _gh_globals_end(toks, i + 1)
    if i >= len(toks) or toks[i] != "merge":
        return None
    return pr_i, i


def _git_push_anchor(toks: list[str], base: int):
    """Index of the first ARGUMENT of `git [globals] push`, else None."""
    i = _git_globals_end(toks, base)
    if i >= len(toks) or toks[i] != "push":
        return None
    return i + 1


# git [-C <path>] [-c key=val] push [opts] <remote> <ref>
# Catches: git push origin main  /  git push origin "main"  /
#          git push origin +main  /  git push -u origin master  /
#          git -C /x push origin main  /  git push origin HEAD:main
# Does NOT catch: main-feature / feature/main-redesign / my-main /
#                 git push-mirror / git push-all (hyphenated, not a subcommand) /
#                 "push" appearing only inside a quoted arg of a different subcommand.
# `push` is the git SUBCOMMAND, matched as a whole token, so `push-mirror` is a
# different word and is rejected.
# NOTE on the trailing lookahead: `:` is deliberately NOT there. In a refspec
# `<src>:<dst>` the branch that gets written is the DESTINATION, so
# `git push origin main:refs/heads/feature-x` pushes local main INTO feature-x
# and is not a publish to main; matching the `main` before the colon denied a
# legitimate command (over-fire measured 2026-09-08). Every real push to main
# still matches, because the destination spelling always leaves `main` at the
# end of its token: `origin main`, `HEAD:main`, `:main`, `feature:refs/heads/main`,
# `main:main` (the second one), `+main`.
_PAT_GIT_PUSH_TAIL = re.compile(
    r"^[^|&;]*?(?:[\s:/\'\"+])(?:HEAD:)?\+?(main|master)(?=$|\s|[\'\"])")


def _git_push_branch(toks: list[str], start: int) -> str | None:
    """'main' / 'master' when the push arguments from *start* publish to it.

    The ARGUMENTS are still read as one joined string, because the refspec rules
    above are about the shape of a token's tail, not about where tokens end. The
    join is reached only once the token-level anchor above has already agreed
    that this is a `git push`, so the whitespace-in-a-global-value class cannot
    reach it.
    """
    m = _PAT_GIT_PUSH_TAIL.match(" " + " ".join(toks[start:]))
    return m.group(1) if m else None


def _gh_repo_option(toks: list[str], start: int = 1) -> str | None:
    """The `-R`/`--repo` value of a gh line, read in FLAG position only.

    A WRONG read here costs an ALLOW — it names the repository the merge is
    scoped against — so the walk is positional and follows pflag's cluster rule
    rather than searching for the letter. Two ways to get it wrong, both closed:
    a `-R` sitting inside another flag's VALUE (`gh pr merge -t "-R x" 288`) is a
    value, and in a cluster the FIRST value-taking shorthand swallows the rest of
    the token, so the `R` of `-tR` belongs to `-t` and is not a flag at all.
    """
    i, flags_done = start, False
    while i < len(toks):
        tok = toks[i]
        i += 1
        if not flags_done and tok == "--":
            flags_done = True
            continue
        if flags_done or not tok.startswith("-") or len(tok) == 1:
            continue
        if tok.startswith("--"):
            name, sep, val = tok.partition("=")
            if name == "--repo":
                return val if sep else (toks[i] if i < len(toks) else None)
            if not sep and name in _GH_VALUE_FLAGS:
                i += 1                           # consume the value token
            continue
        k = 1
        while k < len(tok) and tok[k] not in _GH_VALUE_SHORTS:
            k += 1
        if k >= len(tok):
            continue                             # a cluster of booleans
        letter, rest = tok[k], tok[k + 1:]
        if rest.startswith("="):
            rest = rest[1:]
        if rest:
            value = rest
        else:
            value = toks[i] if i < len(toks) else None
            i += 1
        if letter == "R":
            return value
    return None


def _git_c_option(toks: list[str]) -> str | None:
    """The value of git's `-C` global, walked with git's own option grammar.

    Stops at the first word that is not a global, so a `-C` appearing later as a
    SUBCOMMAND's own flag (`git log -C`) is never read as the repository.
    """
    i, n = 1, len(toks)
    while i < n:
        if toks[i] == "-C":
            return toks[i + 1] if i + 1 < n else None
        j = _git_global_step(toks, i)
        if j == i:
            return None
        i = j
    return None


# Extracts the PR number from `gh pr merge [flags] <N> [flags]`. The number is NOT
# always the first argument: `gh pr merge -R owner/repo 280` and the --repo spelling
# are documented forms, and reading only the first token yielded "unknown",
# which denied a correctly approved PR. So: take the first BARE all-digit token.
# A flag and its value are skipped because neither is all digits.
_BARE_NUM = re.compile(r"^\d+$")

# Flags of `gh pr merge` that CONSUME the next token (verbatim from `gh help pr
# merge`, FLAGS + INHERITED FLAGS). Their value must never be read as the PR:
# `gh pr merge -t 280 281` merges 281, and taking 280 approved the wrong PR.
# Every other flag there is boolean. A flag wrongly listed here can only cost an
# extra deny (the number becomes unseen, and an unseen number is a sentinel);
# one wrongly omitted would allow the wrong merge, so the list errs long.
_GH_VALUE_FLAGS = frozenset({
    "-A", "--author-email", "-b", "--body", "-F", "--body-file",
    "--match-head-commit", "-t", "--subject", "-R", "--repo",
})
# short letters of the above, for a bundle like `-dt 280 281`
_GH_VALUE_SHORTS = frozenset("AbFtR")


_ARG_TOKENS_CACHE: dict[str, list[str] | None] = {}


def _arg_tokens(s: str):
    """Argument tokens of *s* (quoting honoured), or None when it does not parse.

    Replaces `shlex.split(posix=True)`, which was called TWICE over the same
    string (the help walk and the PR-number walk) and whose character state
    machine cost 4.1 s of an 8.4 s run on an 80 KB `-b` body — against a hook
    timeout of 5 s (QA cycle 3, bypass 6). This file's own tokenizer does the
    same job in milliseconds, and it keeps `$(...)` and `<(...)` as ONE opaque
    word where shlex splits them into fragments a PR number could hide in.
    Memoized because the two walks ask the identical question.
    """
    if s in _ARG_TOKENS_CACHE:
        return _ARG_TOKENS_CACHE[s]
    toks = _tokens_with_offsets(s)
    out = None if toks is None else [t for t, _s, _e in toks]
    if len(_ARG_TOKENS_CACHE) > 256:
        _ARG_TOKENS_CACHE.clear()
    _ARG_TOKENS_CACHE[s] = out
    return out


def _gh_merge_pr_num(sub: str) -> str | None:
    """First bare numeric ARGUMENT of a gh-pr-merge sub-command, else None.

    Flag values are skipped, so only a positional token can be the PR. `--flag=value`
    carries its value inside the token; a bare `--` ends flag parsing.

    Read off the RAW sub-command, where a quoted flag value is still ONE token
    (`-t "x 280" 281` merges 281, and flattening it approved 280). The tokens are
    decoded, so a global option whose value contains a space stays one word and
    the walk finds the verb behind it — which is what keeps the spellings closed
    in cycles 7 and 8 OUT of the KNOWN COST class described at the top of this
    file, the same check cycle 7 made for its own six.
    """
    toks = _tokens_with_offsets(sub)
    if toks is None:
        return None                          # unclosed quote: sentinel, denies
    parts = [t for t, _s, _e in toks]
    if not parts or os.path.basename(parts[0].strip("\"'")) != "gh":
        return None
    pos = _gh_merge_anchor(parts, 1)
    if pos is None:
        return None
    # KNOWN COST, kept deliberately rather than inherited by accident: the
    # number is read only when the head and both verb words are spelled
    # LITERALLY. A token whose source span is longer than its decoded text was
    # quoted or escaped, which is exactly `gh "pr" merge 291` and
    # `gh pr $'merge' 291` — identified as merges off the DECODED form and left
    # on the unapprovable 'unknown' sentinel, as the header documents.
    for k in (0,) + pos:
        text, start, end = toks[k]
        if end - start != len(text):
            return None
    i, flags_done = pos[1] + 1, False
    while i < len(parts):
        tok = parts[i].strip("\"'")
        i += 1
        if not flags_done and tok == "--":
            flags_done = True
            continue
        if not flags_done and tok.startswith("-") and len(tok) > 1:
            if "=" in tok:                       # --body=x: value is inside
                continue
            if tok in _GH_VALUE_FLAGS or (
                not tok.startswith("--") and tok[-1] in _GH_VALUE_SHORTS
            ):
                i += 1                           # consume the value token
            continue
        if _BARE_NUM.match(tok):
            return tok
    return None


def _gh_merge_is_help(toks: list[str], start: int) -> bool:
    """True when a gh-pr-merge line only ASKS FOR HELP and merges nothing.

    `gh pr merge --help` prints usage and exits; denying it was a false positive
    that cost QA two read-only tool calls this session. It walks the ARGUMENT
    tokens from *start* — the index the anchor left just past `merge` — with the
    same value-flag rules as _gh_merge_pr_num rather than searching a string,
    because `gh pr merge -t "-h" 291` is a real merge whose `-h` is a flag
    VALUE, and a substring search there would turn a merge into an allow.
    """
    i, flags_done = start, False
    while i < len(toks):
        tok = toks[i]
        i += 1
        if not flags_done and tok == "--":
            flags_done = True
            continue
        if flags_done or not tok.startswith("-") or len(tok) == 1:
            continue
        if tok in ("-h", "--help"):
            return True
        if "=" in tok:
            continue
        if tok in _GH_VALUE_FLAGS or (
            not tok.startswith("--") and tok[-1] in _GH_VALUE_SHORTS
        ):
            i += 1                               # consume the value token
    return False


# git-push flags that CONSUME the next token, so a `-n` sitting in a flag VALUE
# is never read as `--dry-run`. Erring long here can only cost an extra deny.
_GIT_PUSH_VALUE_FLAGS = frozenset({
    "-o", "--push-option", "--repo", "--receive-pack", "--exec",
})


def _git_push_is_dry_run(toks: list[str], start: int) -> bool:
    """True when a git-push line only REHEARSES the push and writes nothing.

    `git push --dry-run origin main` denied (measured 2026-09-08) — an over-fire
    on a command whose whole point is that it does not publish, and the kind that
    teaches people to route around the gate. Walked as TOKENS from *start*, the
    index the anchor left just past `push`, not searched as a substring, for the
    same reason `_gh_merge_is_help` is: a `--dry-run` sitting inside a quoted flag
    VALUE (`git push -o "--dry-run" origin main`) is a value, not a flag, and a
    substring search there would turn a real push into an allow.
    """
    i, flags_done = start, False
    while i < len(toks):
        tok = toks[i]
        i += 1
        if not flags_done and tok == "--":
            flags_done = True
            continue
        if flags_done or not tok.startswith("-") or len(tok) == 1:
            continue
        if tok in ("--dry-run", "-n"):
            return True
        if "=" in tok:
            continue
        if tok in _GIT_PUSH_VALUE_FLAGS:
            i += 1                               # consume the value token
    return False


# API-form publish — the command-shape bypass of `gh pr merge` / `git push`.
# Intent over mechanism (agent-proof-approval-gate skill, OpenBot lesson #2):
# a REST or GraphQL call that merges a PR, merges a branch INTO main/master, or
# force-updates the main/master ref has the same effect as the CLI forms, so it
# gets the same gate. Covers `gh api` and `curl`. Only WRITE calls gate: a plain
# GET to any of these paths is a read and passes (else the gate over-fires and
# gets switched off). A real write must carry a mutating method or a body flag,
# and that is exactly the token the agent cannot omit and still write.
_PAT_API_TOOL = re.compile(r"^\s*(?:gh\s+api|curl)\b")
_API_WRITE = re.compile(
    r"(?:--method|--request|-X)\s*=?\s*(?:PUT|POST|PATCH|DELETE)\b"
    r"|(?:^|\s)(?:-f|-F|--field|--raw-field|--input|-d|--data|--data-raw|--data-binary)(?=[=\s]|$)",
    re.IGNORECASE,
)
_API_PR_NUM_RE = re.compile(r"/pulls/(\d+)/merge\b")
# GraphQL mutations that merge. `enablePullRequestAutoMerge` is the mutation
# `gh pr merge --auto` itself makes: the CLI spelling was gated while the exact
# API call behind it was not, so `gh api graphql -f query='mutation{
# enablePullRequestAutoMerge(...)}'` armed a merge that lands the moment checks
# go green. `mergeBranch` is the GraphQL twin of POST /repos/../merges.
_API_GRAPHQL_MERGE = re.compile(
    r"\b(?:mergePullRequest|enablePullRequestAutoMerge|mergeBranch)\b")
_API_MERGES_RE = re.compile(r"repos/[\w.-]+/[\w.-]+/merges\b")
_API_REFS_RE = re.compile(r"git/refs\b")
_API_MASTER_BRANCH_RE = re.compile(r"heads/(main|master)\b")
# owner/repo out of any of the three REST paths, to protect-check the TARGET
# repo (not cwd: the agent can fire the call from anywhere). No path repo
# (e.g. GraphQL) → unresolvable → gate, fail-closed.
_API_REPO_ANY_RE = re.compile(
    r"repos/([\w.-]+/[\w.-]+?)/(?:pulls/\d+/merge|merges|git/refs)\b"
)
# owner/repo out of a github remote URL given as an ARGUMENT (git push accepts a
# URL where a remote name goes).
_URL_SLUG_RE = re.compile(r"github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?(?=$|[\s/])")
# base branch of a POST /merges, so only a merge INTO main/master gates.
_API_BASE_RE = re.compile(
    r'(?:(?:-f|-F|--field|--raw-field)\s*=?\s*base=|"base"\s*:\s*"|(?:^|\s)base=)([\w./-]+)',
    re.IGNORECASE,
)


def _api_write_action(sub: str) -> str | None:
    """If *sub* (already leading-stripped) is an API WRITE that merges a PR,
    merges a branch into main/master, or updates the main/master ref, return a
    scope token for approval matching (the PR number, or 'main'/'master').
    Otherwise None. Only write methods qualify, so API reads pass."""
    if not _PAT_API_TOOL.match(sub) or not _API_WRITE.search(sub):
        return None
    m = _API_PR_NUM_RE.search(sub)          # PR merge, REST
    if m:
        return m.group(1)
    if _API_GRAPHQL_MERGE.search(sub):      # PR merge, GraphQL mutation
        return "unknown"
    if _API_REFS_RE.search(sub):            # ref write to a head
        bm = _API_MASTER_BRANCH_RE.search(sub)
        return bm.group(1) if bm else None
    if _API_MERGES_RE.search(sub):          # branch merge into base
        bm = _API_BASE_RE.search(sub)
        base = bm.group(1).lower() if bm else None
        if base is None or base in ("main", "master"):
            return base or "master"         # unparseable base → fail-closed
        return None                         # merge into a non-default branch
    return None

# Set True by main() the moment a publish/merge sub-command is positively
# identified. The __main__ crash handler keys fail-open vs fail-closed off it.
_PUBLISH_IDENTIFIED = False
# The stdin payload of THIS invocation, kept so the crash handler can journal
# its refusal: a fail-closed crash used to print and exit 2 with no journal
# line, so `octo replay` showed nothing for the one refusal nobody can re-run.
_LAST_PAYLOAD: dict | None = None

# ---------------------------------------------------------------------------
# Repo scoping (root-cause fix, 2026-06-04). The gate guards PROTECTED repos:
# the brain (~/.claude, including its linked worktrees) plus any repo listed in
# the operator-owned, gitignored company/config/protected-repos.json
# ({"protected": ["~/Documents/github/<deploy-arm>", ...]}). A push to main of
# an ordinary working repo is daily flow, not a guarded merge; gating every
# repo's main produced constant false blocks. Resolution is DETERMINISTIC
# (paths and git-config file reads only — the agent classifies nothing) and
# the direction stays fail-closed: unresolvable target → still gated. Only a
# positively-identified NON-protected target is ungated.
# ---------------------------------------------------------------------------

_BRAIN = Path.home() / ".claude"
_PROTECTED_CFG = _BRAIN / "company" / "config" / "protected-repos.json"


def _protected_roots() -> list[Path]:
    roots = [_BRAIN]
    try:
        data = json.loads(_PROTECTED_CFG.read_text(encoding="utf-8"))
        for item in data.get("protected", []):
            roots.append(Path(os.path.expanduser(str(item))))
    except Exception:
        pass  # config absent → only the brain is protected
    out: list[Path] = []
    for r in roots:
        try:
            out.append(r.resolve())
        except Exception:
            continue
    return out


def _remote_slug(repo_root: Path) -> str | None:
    """owner/repo (lowercase) parsed from <root>/.git/config; file reads only."""
    try:
        cfg = (repo_root / ".git" / "config").read_text(encoding="utf-8")
        m = re.search(r"url\s*=\s*\S*github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?\s*$",
                      cfg, re.MULTILINE)
        return m.group(1).lower() if m else None
    except Exception:
        return None


def _canon_slug(s: str) -> str | None:
    """Canonical owner/repo (lowercase) from any -R form: bare slug, https URL,
    ssh host:owner/repo, with or without trailing .git or slash. The INPUT side
    must pass through the same canonicalizer as the known side, else '.git' and
    ssh variants of the brain's own slug classify as ungated (QA finding 1)."""
    s = s.strip().strip("'\"")
    m = re.search(r"(?:github\.com[:/])?([\w.-]+/[\w.-]+?)(?:\.git)?/?$", s)
    return m.group(1).lower() if m else None


def _repo_root_and_gitdir(start: str):
    """Walk up from *start* to the first .git entry. Returns (worktree_root,
    resolved_gitdir_or_None). A linked worktree's .git FILE points into the
    main repo's .git dir — that is how a brain worktree is recognized."""
    try:
        p = Path(start).resolve()
    except Exception:
        return None, None
    while True:
        g = p / ".git"
        if g.is_dir():
            return p, g
        if g.is_file():
            try:
                m = re.search(r"gitdir:\s*(.+)", g.read_text(encoding="utf-8"))
                if m:
                    gd = Path(m.group(1).strip())
                    gd = gd if gd.is_absolute() else (p / gd)
                    return p, gd.resolve()
            except OSError:
                pass
            return p, None
        if p.parent == p:
            return None, None
        p = p.parent


def _effective_cwd(cmd: str, matched_sub: str, session_cwd: str) -> str:
    """Session cwd adjusted by any `cd` sub-commands BEFORE the matched one.
    Only plain `cd <path>` is parsed; `cd -`, `pushd`, subshells are ignored,
    which leaves cwd unadjusted and can only OVER-gate, never under-gate."""
    cwd = session_cwd or os.getcwd()
    for raw in _line_parts(cmd):
        if raw == matched_sub:
            break
        s = _unwrap_sub(raw).strip()
        m = re.match(r"^cd\s+(\S+)", s)
        if m:
            p = os.path.expanduser(m.group(1).strip("'\""))
            cwd = p if os.path.isabs(p) else os.path.join(cwd, p)
    return cwd


def _is_protected_target(cmd: str, matched_sub: str, session_cwd: str):
    """True = protected, False = positively NOT protected, None = unresolvable
    (treated as protected: the gate stays fail-closed when unsure)."""
    # `sub` (raw, quoting intact) is read for VALUES; `dec` (decoded) is read to
    # decide WHICH form this is. Deciding the form on the raw string meant
    # `gh "pr" merge 291` fell past the gh branch into the cwd branch and could
    # resolve to a repo it does not target.
    cfg_dir = _cfg_dir_for(cmd, matched_sub)
    sub, dec, view = _normalize_full(matched_sub, cfg_dir)

    # An alias DEFINITION has no repo: gh's config is per-user, so an alias that
    # expands to a merge arms every repo the agent can reach, protected ones
    # included. Unresolvable by construction → gate.
    if _alias_definition_form(dec):
        return None

    # gh api / curl write (PR merge, branch merge into main/master, or a
    # main/master ref update): the target repo is in the REST path, NOT the cwd
    # (the agent can fire the API call from anywhere, so cwd-based resolution
    # would under-gate). Resolve owner/repo from the path and compare against
    # the protected slugs. GraphQL / any form with no path repo is unresolvable
    # → None (gate, fail-closed).
    if _api_write_action(dec) is not None:
        m = _API_REPO_ANY_RE.search(dec)
        if not m:
            return None
        slug = _canon_slug(m.group(1))
        known = {s for s in (_remote_slug(r) for r in _protected_roots()) if s}
        if not known or slug is None:
            return None
        return slug in known

    # gh pr merge: the target is -R/--repo if given, else GH_REPO, else the cwd
    # repo — the same order gh itself resolves in. Reading only -R and the cwd
    # let `GH_REPO=<protected slug> gh pr merge <n>`, fired from an unrelated
    # repo, resolve to that unrelated repo and UNGATE a merge of the protected
    # one. GH_HOST moves the whole request to another server, which this gate
    # cannot check against, so a non-github.com host is unresolvable, not safe.
    if _gh_merge_form(view):
        line_env = _line_env(cmd, matched_sub)
        host = (line_env.get("GH_HOST") or "").strip().strip("\"'").lower()
        if host and host not in ("github.com", "api.github.com"):
            return None
        opt = _gh_repo_option(_cmd_tokens(sub))
        raw = opt if opt else (line_env.get("GH_REPO") or "").strip()
        if raw:
            slug = _canon_slug(raw)
            known = [s for s in (_remote_slug(r) for r in _protected_roots()) if s]
            if not known or slug is None:
                return None  # unparseable either side → gate
            return slug in known  # exact canonical match, no suffix tricks

    # A push can name its target as a URL instead of a remote name, and then the
    # cwd repo is not the repo being written: `git push https://github.com/<brain>
    # main`, fired from an unrelated repo, resolved to that unrelated repo and
    # ungated (measured 2026-09-08 — it only denied from a non-repo cwd, by luck).
    # Positive check only: a URL that names a protected repo gates; anything else
    # falls through, because `git push otherremote main` inside the brain is still
    # a push to the brain.
    if _git_push_form(view):
        known = {s for s in (_remote_slug(r) for r in _protected_roots()) if s}
        for m in _URL_SLUG_RE.finditer(dec):
            if (_canon_slug(m.group(1)) or "") in known:
                return True

    # Resolve the repo the command operates on: git -C wins, else effective cwd.
    # A relative -C is joined against the effective SESSION cwd, never the
    # hook's own cwd (QA finding 3: right answer, deterministic reason).
    target = None
    gtoks = _cmd_tokens(sub)
    if _head_of(gtoks) == "git":
        # Read with git's own grammar, not with `\S+`: `git -C "/p/sp ace" push
        # origin main` resolved to `/p/sp`, which is a different directory and a
        # different verdict about whether the target is protected.
        cpath = _git_c_option(gtoks)
        if cpath is not None:
            raw = os.path.expanduser(cpath.strip("'\""))
            base = _effective_cwd(cmd, matched_sub, session_cwd)
            target = raw if os.path.isabs(raw) else os.path.join(base, raw)
    if target is None:
        target = _effective_cwd(cmd, matched_sub, session_cwd)

    root, gitdir = _repo_root_and_gitdir(target)
    if root is None:
        return None
    candidates = [root] + ([gitdir] if gitdir is not None else [])
    for cand in candidates:
        for prot in _protected_roots():
            if cand == prot or prot in cand.parents:
                return True
    # A CLONE of a protected repo living anywhere is still protected: compare
    # the target's own remote slug against the protected slugs (QA finding 2).
    tgt_slug = _remote_slug(root)
    if tgt_slug:
        known = {s for s in (_remote_slug(r) for r in _protected_roots()) if s}
        if tgt_slug in known:
            return True
    return False


# FIX 5: join backslash-newline continuations before any splitting so that
# `gh pr \<newline>merge 96` is treated as a single token.
def _join_continuations(cmd: str) -> str:
    """Replace backslash-newline pairs with a single space."""
    return re.sub(r"\\\n", " ", cmd)


# Strip leading wrapper tokens from an already-split sub-command before pattern
# matching. Applied PER sub-command so it never crosses a real separator boundary.
#
# SECURITY (measured against the live gate, 2026-09-08): the publish patterns are
# anchored at the START of the sub-command, so ANY leading token that is not the
# verb defeats the anchor. `env A=1 gh pr merge` and `command gh pr merge` were
# peeled by name — and `time`, `nohup`, `nice`, `timeout 30`, `stdbuf -o0`,
# `setsid`, `sudo`, `exec`, `eval`, `xargs` and a leading `\gh` all walked
# straight through, each one actually invoking gh.
#
# DESIGN CHOICE — deny-by-default over an allowlist. Naming wrappers is a list
# that has to grow every time someone finds another one, and the one you have not
# named is a total bypass. So the default is inverted: leading tokens are DROPPED
# until one of them IS a command head this gate knows how to read. An
# unrecognized leading token is suspicious, not trusted, and no wrapper needs to
# be named — including the ones whose own options consume a following token
# (`timeout N`, `nice -n 5`, `stdbuf -o0`, `sudo -u x`), because those options and
# their values are just more unrecognized tokens on the way to the head.
#
# The cost, MEASURED 2026-09-08 rather than guessed: a command that passes an
# unquoted merge command as arguments (`echo gh pr merge 280`, `grep -rn gh pr
# merge scripts/`) is identified as a merge, so it denies from inside a PROTECTED
# repo and ungates elsewhere like any other merge. Quoting it — how anyone writes
# that line anyway — makes it a non-match. A QUOTED mention
# (`git commit -m "gh pr merge 96"`) is never a match: the tokenizer keeps a
# quoted argument as ONE token and a head only counts as a whole bare token.
# That is the fail-closed side of the trade, and it is loud, not silent.
_W_GROUP = re.compile(r"^[({]\s*")
_W_GROUP_END = re.compile(r"[\s;)}]+$")
_CMD_HEADS = frozenset({"gh", "git", "curl", "cd"})


# Characters that end a bulk run in `_tokenize`. Inside double quotes only these
# four are special; outside quotes, add whitespace, both quote marks and `<`.
_DQ_STOP = re.compile(r"[\"\\$`]")
_PLAIN_RUN = re.compile(r"[^\s'\"\\$`<]+")

# ANSI-C quoting, `$'…'`, and locale quoting, `$"…"`. Both are QUOTING, not
# expansion: bash decodes them at parse time and the word that reaches the
# program is the decoded text, so `gh pr $'\x6derge' 288` and `gh pr merge 288`
# are the SAME command line. Cycle 7 measured 12 spellings of this walking the
# gate, and one of them is a regression this branch introduced in 1f0ca89: that
# commit moved verb matching onto decoded tokens, the decoder turned `$'main'`
# into `$main`, and `git push origin $'main'` went from DENY on 2ceb87c to ALLOW
# — one spelling closed and another opened in the same change. Residual 1 says
# an expansion supplies the verb and is out of scope; `$'…'` never was an
# expansion, so nothing here reads a variable.
_ANSI_C_SIMPLE = {
    "a": "\a", "b": "\b", "e": "\x1b", "E": "\x1b", "f": "\f", "n": "\n",
    "r": "\r", "t": "\t", "v": "\v", "\\": "\\", "'": "'", '"': '"', "?": "?",
}
_HEXDIGITS = frozenset("0123456789abcdefABCDEF")
_OCTDIGITS = frozenset("01234567")


def _ansi_c_body(s: str, i: int, nul_truncates: bool = True) -> tuple[str, int, bool]:
    r"""(decoded text, index past the closing quote, closed?) for the ANSI-C
    string opening at ``s[i:i+2] == "$'"``.

    Faithful to bash on the escape that is NOT recognized: `$'\z'` is `\z`, the
    backslash retained, so this can never manufacture a verb bash would not
    produce. That claim is TRUE and cycle 8 tested its CONVERSE, which nobody
    had: a word bash TRUNCATES and this decoder did not. A bash word is a C
    string, so an embedded NUL ends the body — measured on bash 5.2.21,
    `$'pr\x00xx'` prints `[pr]` and `$'main\x00zz'` prints `[main]` — while this
    reader kept the bytes after it, so the decoded word was `pr\x00xx`, which is
    not the word any anchor is looking for. `gh $'pr\x00xx' merge 288`,
    `$'gh\x00zz' pr merge 288`, `git $'push\x00x' origin main` and
    `git push origin $'main\x00zz'` all walked this gate, and the last two pushed
    for real to a local bare remote. Truncation is of the BODY only, not of the
    word: `x$'a\x00b'y` measures `[xay]`, so the concatenation continues after
    the closing quote.

    *nul_truncates* is False for one caller, `_ansi_c_expand`, which only ever
    WIDENS a pre-filter: truncating there could drop the very word the filter
    exists to find.

    An unclosed opener is a shell syntax error and reports closed=False,
    which the tokenizer treats exactly as it treats any other unclosed quote.
    """
    out: list[str] = []
    j, n = i + 2, len(s)
    while j < n and s[j] != "'":
        ch = s[j]
        if ch != "\\" or j + 1 >= n:
            out.append(ch)
            j += 1
            continue
        esc = s[j + 1]
        if esc in _ANSI_C_SIMPLE:
            out.append(_ANSI_C_SIMPLE[esc])
            j += 2
        elif esc == "x":
            k, digits = j + 2, ""
            while k < n and len(digits) < 2 and s[k] in _HEXDIGITS:
                digits += s[k]
                k += 1
            if digits:
                out.append(chr(int(digits, 16)))
                j = k
            else:
                out.append("\\" + esc)
                j += 2
        elif esc in ("u", "U"):
            width = 4 if esc == "u" else 8
            k, digits = j + 2, ""
            while k < n and len(digits) < width and s[k] in _HEXDIGITS:
                digits += s[k]
                k += 1
            if digits:
                try:
                    out.append(chr(int(digits, 16)))
                except ValueError:
                    pass
                j = k
            else:
                out.append("\\" + esc)
                j += 2
        elif esc in _OCTDIGITS:
            k, digits = j + 1, ""
            while k < n and len(digits) < 3 and s[k] in _OCTDIGITS:
                digits += s[k]
                k += 1
            out.append(chr(int(digits, 8) & 0xFF))
            j = k
        elif esc == "c" and j + 2 < n:
            out.append(chr(ord(s[j + 2].upper()) ^ 0x40))
            j += 3
        else:
            out.append("\\" + esc)
            j += 2
    body = "".join(out)
    if nul_truncates:
        zero = body.find("\x00")
        if zero >= 0:
            body = body[:zero]
    if j < n and s[j] == "'":
        return body, j + 1, True
    return body, n, False


def _ansi_c_expand(text: str) -> str:
    """*text* with every `$'…'` replaced by its decoding and the `$` of every
    `$"…"` dropped. QUOTE-BLIND on purpose: it is only ever used to widen a
    pre-filter, where reading a `$'…'` that bash would have taken literally can
    make the filter say YES too often and never NO too often."""
    if "$'" not in text and '$"' not in text:
        return text
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        if text[i] == "$" and i + 1 < n and text[i + 1] == "'":
            body, i, _closed = _ansi_c_body(text, i, nul_truncates=False)
            out.append(body.replace("\x00", ""))
        elif text[i] == "$" and i + 1 < n and text[i + 1] == '"':
            i += 1
        else:
            out.append(text[i])
            i += 1
    return "".join(out)

_TOKENS_CACHE: dict[str, list | None] = {}


def _tokens_with_offsets(s: str):
    """Memoized `_tokenize`. The peel, the env walk, the PR-number walk and the
    help walk all ask the identical question about the identical string, and the
    answer depends on nothing else — an 80 KB `-b` body was tokenized FIVE times
    per invocation, 1.9 s of a run against a 5 s hook timeout. Callers only read
    the tuples, so one list is safe to share."""
    if s in _TOKENS_CACHE:
        return _TOKENS_CACHE[s]
    out = _tokenize(s)
    if len(_TOKENS_CACHE) > 256:
        _TOKENS_CACHE.clear()
    _TOKENS_CACHE[s] = out
    return out


def _tokenize(s: str):
    """[(decoded_token, start, end)] for *s*, split on UNQUOTED whitespace.

    Quotes and backslash escapes are honored, so a quoted argument stays one
    token (that is what keeps a quoted mention from looking like a merge) and
    `\\gh` decodes to `gh`. Offsets are into the ORIGINAL string, so slicing
    from `end` preserves the rest of the command verbatim — flattening the
    quoting there would let a quoted flag value be re-read as the PR number.
    Returns None when the string does not tokenize (unclosed quote).
    """
    toks: list[tuple[str, int, int]] = []
    buf: list[str] = []
    start = -1
    in_single = in_double = False
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if ch == "\\" and not in_single and i + 1 < n:
            if start < 0:
                start = i
            # Inside DOUBLE quotes bash escapes only ``$ ` " \\`` and a newline;
            # before anything else the backslash is LITERAL. Eating it there was
            # not cosmetic: `echo "gh pr $'\\x6derge' 291" | bash` handed the
            # stdin channel `$'x6derge'`, the hex escapes stripped of the
            # backslashes that made them escapes, and the re-parse then decoded
            # a word that is not the verb. Measured ALLOW before this line.
            if in_double and s[i + 1] not in "$`\"\\\n":
                buf.append(ch)
                i += 1
            else:
                buf.append(s[i + 1])
                i += 2
            continue
        # A command substitution is ONE word to the shell no matter how many
        # spaces it contains, so it has to be one token here too. Without this,
        # `$(echo gh) pr merge 96` tokenized as `$(echo` + `gh)` and the opaque
        # head below could never see it. Nothing is executed: the group is
        # consumed as opaque text.
        if ch == "$" and not in_single and i + 1 < n and s[i + 1] == "(":
            if start < 0:
                start = i
            depth, j = 0, i + 1
            while j < n:
                if s[j] == "(":
                    depth += 1
                elif s[j] == ")":
                    depth -= 1
                    if depth == 0:
                        j += 1
                        break
                j += 1
            buf.append(s[i:j])
            i = j
            continue
        # Process substitution is ONE word to the shell too, and unlike `$(...)`
        # it is a CHANNEL: `bash <(echo "gh pr merge 292")` hands the shell a
        # file whose contents are that command line. Splitting it into `<(echo`
        # and `gh pr merge 292)` is how the channel disappeared entirely (QA
        # cycle 3, bypass 4 — measured executing the real gh). It is not a
        # substitution inside double quotes, so both quote states matter here.
        if (ch == "<" and not in_single and not in_double
                and i + 1 < n and s[i + 1] == "("):
            if start < 0:
                start = i
            depth, j = 0, i + 1
            while j < n:
                if s[j] == "(":
                    depth += 1
                elif s[j] == ")":
                    depth -= 1
                    if depth == 0:
                        j += 1
                        break
                j += 1
            buf.append(s[i:j])
            i = j
            continue
        # ANSI-C and locale quoting. Both are decided by the SHELL before the
        # program ever runs, so they belong in the decoder next to `\\` and `"`,
        # not in the opaque-head reading: `$'merge'` is the word `merge`, and it
        # is not an expansion of anything. Neither is special inside quotes, so
        # both quote states are read here (`"$'x'"` really is a literal `$'x'`).
        if (ch == "$" and not in_single and not in_double
                and i + 1 < n and s[i + 1] == "'"):
            if start < 0:
                start = i
            text_ac, j, closed = _ansi_c_body(s, i)
            if not closed:
                return None            # unclosed quote: a shell syntax error
            buf.append(text_ac)
            i = j
            continue
        if (ch == "$" and not in_single and not in_double
                and i + 1 < n and s[i + 1] == '"'):
            if start < 0:
                start = i
            in_double = True           # `$"…"` is `"…"` with a translation pass
            i += 2
            continue
        if ch == "`" and not in_single:
            if start < 0:
                start = i
            j = s.find("`", i + 1)
            j = n if j < 0 else j + 1
            buf.append(s[i:j])
            i = j
            continue
        if ch == "'" and not in_double:
            if start < 0:
                start = i
            in_single = not in_single
            i += 1
            continue
        if ch == '"' and not in_single:
            if start < 0:
                start = i
            in_double = not in_double
            i += 1
            continue
        if ch.isspace() and not in_single and not in_double:
            if start >= 0:
                toks.append(("".join(buf), start, i))
                buf, start = [], -1
            i += 1
            continue
        if start < 0:
            start = i
        # Bulk-take the run of characters none of the branches above can claim,
        # instead of stepping one at a time. EXACT, not an approximation: every
        # stop character below is a character one of those branches handles in
        # this state, and every other character reached this line to be appended
        # verbatim anyway. It is what keeps a padded argument from starving the
        # hook: a 500 KB `-b` body ran 4.9 s against a 5 s timeout, and a gate the
        # harness kills is a gate that never says no (QA cycle 3, bypass 6).
        if in_single:
            j = s.find("'", i)          # in single quotes NOTHING else is special
            if j < 0:
                j = n
        elif in_double:
            m2 = _DQ_STOP.search(s, i)
            j = n if m2 is None else m2.start()
        else:
            m2 = _PLAIN_RUN.match(s, i)
            j = m2.end() if m2 else i
        if j <= i:
            buf.append(ch)              # no run here: guarantee forward progress
            i += 1
        else:
            buf.append(s[i:j])
            i = j
    if in_single or in_double:
        return None
    if start >= 0:
        toks.append(("".join(buf), start, n))
    return toks


def _ws_tokens(s: str):
    """Quote-blind whitespace tokens, used ONLY when the string does not
    tokenize. An unclosed quote is a shell syntax error, so nothing runs; the
    fallback exists so the gate still IDENTIFIES the merge instead of losing the
    anchor and falling open."""
    return [(m.group(0), m.start(), m.end()) for m in re.finditer(r"\S+", s)]


# A head the SHELL will resolve and this tokenizer cannot: `$(echo gh)`,
# `` `echo gh` ``, `${PATH:0:0}gh`, `$'gh'`, `$G`. It is not decidable without
# executing something, so it is treated the deny-by-default way: the remainder
# is tried against every head this gate knows, and if the remainder is a merge
# verb the line is a merge whoever the head turns out to be.
_OPAQUE_HEAD = re.compile(r"[$`]")


def _peel_candidates(s: str) -> list[tuple[str, str, tuple | None]]:
    """[(raw_form, decoded_form, view)] for EVERY command-head position in *s*.

    raw_form     = the DECODED head plus the ORIGINAL remainder, quoting intact.
                   PR-number extraction reads this one, because a quoted flag
                   value must stay ONE token there (`-t "x 280" 281` merges 281).
    decoded_form = the decoded head plus every following token DECODED and joined
                   by single spaces. It is a RENDERING, not a parse: a token
                   that contains whitespace is two words in it, which is why the
                   view below and not this string is what verb matching reads.
                   `_api_write_action` and `_alias_definition_form` do read it,
                   and neither has an option grammar to lose.
                   VERB matching reads the view, because `gh "pr" merge 1`,
                   `gh pr me\\rge 1` and `git "push" origin main` are the same
                   command to the shell and were three total bypasses while the
                   matcher looked at the raw remainder (QA cycle 4, A1).
                   Decoding cannot manufacture a verb out of a quoted MENTION: a
                   whole-token quote (`git commit -m "gh pr merge 96"`) is ONE
                   token, and one token can never supply the two words a verb
                   needs after a head.
    view         = (head, decoded tokens, base index, offset tuples, source) for
                   every caller that reads the command's SHAPE: the verb anchors,
                   the option readers and the alias expansion. The tokens already
                   exist here, so handing them over costs a tuple, while
                   re-deriving them per candidate is the O(tokens²) shape
                   residual 9 keeps paying down — an alias expansion that
                   re-tokenized its own candidate measured 14.4 s on 800 opaque
                   tokens against a 5 s budget. None on the no-head fallback,
                   which is one candidate for the whole string.

    EVERY position, not just the first (A2): the old peel stopped at the first
    head it recognized, so a benign head in front swallowed the merge behind it
    (`git status & gh pr merge 291` allowed). The patterns stay anchored — the
    anchor just gets tried at each head, which is also what keeps a merge inside
    a loop body (`do gh pr merge 1`) identified.
    """
    s = s.lstrip()
    m = _W_GROUP.match(s)
    while m:
        s = s[m.end():]
        m = _W_GROUP.match(s)
    # ...and the closer, so a subshell's `)` is not glued to the last argument
    # (`(gh pr merge 291)` yielded the PR token `291)`, which is not a number,
    # which is the unapprovable sentinel — fail-closed but unmergeable forever).
    s = _W_GROUP_END.sub("", s)
    toks = _tokens_with_offsets(s)
    if toks is None:
        toks = _ws_tokens(s)
    # The decoded remainder of position i is a SUFFIX of the decoded whole, so
    # it is built once and sliced, never re-joined per token. The old code built
    # `toks[i + 1:]` and joined it for EVERY token, head or not: O(tokens²) on a
    # line that contains no head at all. 20000 benign words took 20.3 s against a
    # 5 s `hooks.json` budget, and a hook that is killed writes no stdout, which
    # the harness reads as ALLOW — a timeout is a bypass with a stopwatch.
    flat_parts = [t for t, _s2, _e2 in toks]
    flat = " ".join(flat_parts)
    dec_at: list[int] = []          # offset of token i inside `flat`
    pos = 0
    for t in flat_parts:
        dec_at.append(pos)
        pos += len(t) + 1
    # A synthesized `curl` reaches exactly ONE pattern, `_api_write_action`, and
    # that needs an `_API_WRITE` marker somewhere in the candidate's remainder.
    # Every remainder is a SUFFIX of `flat`, so the LAST marker in `flat` bounds
    # all of them at once: past it a `curl` candidate can match nothing, and
    # synthesizing it anyway cost a 1.7 ms regex per opaque token — 9.6 s on a
    # 5000-token line, against a 5 s `hooks.json` budget. Exact, not a heuristic:
    # a match lying wholly inside a suffix that starts after the last match would
    # itself be a later match in `flat`.
    last_write = -1
    if "-" in flat:
        for _m in _API_WRITE.finditer(flat):
            last_write = _m.start()
    out: list[tuple[str, str, tuple | None]] = []
    for i, (text, _start, end) in enumerate(toks):
        bare = text.strip("\"'")
        head = os.path.basename(bare)
        is_cmd = head in _CMD_HEADS
        if not is_cmd and not _OPAQUE_HEAD.search(bare):
            continue
        at = dec_at[i + 1] if i + 1 < len(flat_parts) else len(flat)
        rest_dec = flat[at:] if i + 1 < len(flat_parts) else ""
        suffix = (" " + rest_dec) if rest_dec else ""
        if is_cmd:
            out.append((head + s[end:], head + suffix,
                        (head, flat_parts, i + 1, toks, s)))
        else:
            heads = ("gh", "git", "curl") if at <= last_write else ("gh", "git")
            for h in heads:
                out.append((h + s[end:], h + suffix,
                            (h, flat_parts, i + 1, toks, s)))
    if not out:
        out.append((s, flat if toks else s, ("", flat_parts, len(flat_parts), toks, s)))
    return out


# gh aliases (B4). `gh mrg 291` reached GitHub: an alias expands inside gh, so
# the verb anchor never sees `pr merge`. Aliases live in gh's own config file, so
# resolving them is a deterministic file read of the same shape as _remote_slug.
# A6: gh honours BOTH YAML spellings of the block, so both are read. The
# block-style `aliases:` on its own line was the only one recognized, and
# `aliases: {mrg: pr merge}` — verified honoured by the installed gh 2.88.1 —
# resolved to nothing, which put the alias back outside the anchor.
_ALIAS_BLOCK_RE = re.compile(r"^aliases:\s*$")
_ALIAS_FLOW_RE = re.compile(r"^aliases:\s*\{(.*)\}\s*$")
_ALIAS_ENTRY_RE = re.compile(r"^\s+([\w.-]+):\s*(.+?)\s*$")
_ALIAS_FLOW_ENTRY_RE = re.compile(r"^\s*([\w.-]+)\s*:\s*(.+?)\s*$")
_GH_FIRST_WORD_RE = re.compile(r"^gh\s+([A-Za-z][\w.-]*)(?=\s|$)")
_aliases_cache: dict = {}


def _gh_config_dir(cfg_dir: str | None = None) -> Path:
    """gh's config directory, GH_CONFIG_DIR first — from the COMMAND LINE when
    the caller could see one (A6: `GH_CONFIG_DIR=/tmp/x gh mrg 291` set it for
    gh and not for this hook, so alias resolution read the wrong file and the
    merge walked), else from this process's env, else the default."""
    d = cfg_dir if cfg_dir else os.environ.get("GH_CONFIG_DIR")
    return Path(os.path.expanduser(d)) if d else Path.home() / ".config" / "gh"


def _gh_aliases(cfg_dir: str | None = None) -> dict:
    """{alias: expansion} read off gh's config.yml. Empty on any error."""
    path = _gh_config_dir(cfg_dir) / "config.yml"
    key = str(path)
    cached = _aliases_cache.get(key)
    if cached is not None:
        return cached
    found: dict = {}
    _aliases_cache[key] = found
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return found
    in_block = False
    for line in text.splitlines():
        if not in_block:
            flow = _ALIAS_FLOW_RE.match(line)
            if flow:
                for part in flow.group(1).split(","):
                    m = _ALIAS_FLOW_ENTRY_RE.match(part)
                    if m:
                        found[m.group(1)] = m.group(2).strip().strip("\"'")
                continue
            in_block = bool(_ALIAS_BLOCK_RE.match(line))
            continue
        if line.strip() and not line[:1].isspace():
            break  # dedent: the aliases block ended
        m = _ALIAS_ENTRY_RE.match(line)
        if m:
            found[m.group(1)] = m.group(2).strip().strip("\"'")
    return found


def _expand_gh_alias(sub: str, cfg_dir: str | None = None) -> str:
    """`gh <alias> args` rewritten to what gh will actually run."""
    m = _GH_FIRST_WORD_RE.match(sub)
    if not m:
        return sub
    exp = _gh_aliases(cfg_dir).get(m.group(1))
    if not exp:
        return sub
    rest = sub[m.end(1):]
    if exp.startswith("!"):          # shell alias: the expansion IS the line
        return exp[1:].lstrip() + rest
    return "gh " + exp + rest


# A5: git aliases got none of the treatment gh's got. `git pm` runs whatever
# `alias.pm` says, so the `push` anchor never sees it, and `git -c alias.p=...`
# needs no config file at all — which is why RESOLUTION alone could never be
# the fix and the DEFINITION is gated as well (see _alias_definition_form).
_GIT_ALIAS_WORD_RE = re.compile(r"^[A-Za-z][\w.-]*$")
_GIT_C_ALIAS_RE = re.compile(r"-c\s+alias\.([\w.-]+)=(\S+|'[^']*'|\"[^\"]*\")")
_GIT_ALIAS_SECTION_RE = re.compile(r"^\s*\[\s*alias\s*\]\s*$", re.IGNORECASE)
_GIT_SECTION_RE = re.compile(r"^\s*\[")
_GIT_ALIAS_ENTRY_RE = re.compile(r"^\s*([\w.-]+)\s*=\s*(.+?)\s*$")
_git_aliases_cache: dict = {}


def _git_aliases() -> dict:
    """{alias: expansion} from the user's global git config. File reads only.

    Global scope only, deliberately: the repo-local config lives in the TARGET
    repo, which is not resolved until after identification. A repo-local alias
    is therefore residual, and it is stated as such rather than claimed closed.
    """
    p = os.environ.get("GIT_CONFIG_GLOBAL") or str(Path.home() / ".gitconfig")
    cached = _git_aliases_cache.get(p)
    if cached is not None:
        return cached
    found: dict = {}
    _git_aliases_cache[p] = found
    try:
        text = Path(p).read_text(encoding="utf-8")
    except Exception:
        return found
    in_block = False
    for line in text.splitlines():
        if _GIT_SECTION_RE.match(line):
            in_block = bool(_GIT_ALIAS_SECTION_RE.match(line))
            continue
        if not in_block:
            continue
        m = _GIT_ALIAS_ENTRY_RE.match(line)
        if m:
            found[m.group(1)] = m.group(2).strip().strip("\"'")
    return found


def _expand_git_alias(sub: str, view: tuple | None = None) -> str:
    """`git [globals] <alias> args` rewritten to what git will actually run.

    A same-line `-c alias.<n>=<body>` wins over the config file, exactly as git
    resolves it — and that is the spelling that needs no config file at all.

    The globals are walked with `_git_globals_end`, the same grammar the push
    anchor uses. The regex it replaced stopped its value at the first space, so
    `git -c 'core.pager=less -F' pm` never found `pm`; the note below used to
    call that "defeats the push anchor" and worked around it by dropping the
    option instead of by reading it.
    """
    if view is None:                       # direct call: parse what we were given
        toks = _tokens_with_offsets(sub)
        if toks is None:
            return sub
        parts = [t for t, _s, _e in toks]
        head, base, src = _head_of(parts), 1, sub
    else:
        head, parts, base, toks, src = view
    if head != "git" or base < 1 or base > len(toks):
        return sub
    i = _git_globals_end(parts, base)
    if i >= len(parts) or not _GIT_ALIAS_WORD_RE.match(parts[i]):
        return sub
    globals_text = src[toks[base - 1][2]:toks[i][1]]
    inline = {k: v.strip("'\"") for k, v in _GIT_C_ALIAS_RE.findall(globals_text)}
    exp = inline.get(parts[i]) or _git_aliases().get(parts[i])
    if not exp:
        return sub
    rest = src[toks[i][2]:]
    if exp.startswith("!"):          # shell alias: the expansion IS the line
        return exp[1:].lstrip() + rest
    # `-C <path>` is kept (it names the repo the command operates on), the
    # `-c alias.*` entry is dropped: it is the DEFINITION, not a selector.
    kept = _GIT_C_ALIAS_RE.sub("", globals_text).strip()
    return "git " + (kept + " " if kept else "") + exp + rest


def _expand_alias(sub: str, cfg_dir: str | None = None, view: tuple | None = None) -> str:
    """Either alias vocabulary, whichever the head belongs to."""
    out = _expand_gh_alias(sub, cfg_dir)
    return out if out != sub else _expand_git_alias(sub, view)


# Defining an alias is one ungated command away from an ungated merge, and it
# beats alias RESOLUTION on a single line: `gh alias set m 'pr merge' && gh m 291`
# fires this hook once, before the config file the resolver reads has been
# written. So the definition is gated too. `alias import` reads definitions from
# a file this hook cannot see, so it is unresolvable and always gates.
_PAT_GH_ALIAS_SET = re.compile(r"^\s*gh\s+alias\s+set\b")
_PAT_GH_ALIAS_IMPORT = re.compile(r"^\s*gh\s+alias\s+import\b")
_ALIAS_MERGE_BODY = re.compile(
    r"pr\s+merge\b|/merge\b|mergePullRequest|enablePullRequestAutoMerge|mergeBranch")
# A5: the git half. `git config alias.pm '...'` writes the file AFTER this hook
# read it, and `git -c alias.p='push origin main' p` never writes one at all, so
# resolution could not be the fix for either — the DEFINITION is what gets gated,
# exactly as `gh alias set` is. A git alias body can also be a push to main, which
# no gh alias body ever is, so it gets its own body pattern.
_PAT_GIT_CONFIG_ALIAS = re.compile(
    r"^\s*git\s+[^|&;]*?\bconfig\b[^|&;]*?\balias\.[\w.-]+")
_PAT_GIT_C_ALIAS_DEF = re.compile(r"^\s*git\s+[^|&;]*?-c\s+alias\.[\w.-]+=")
_ALIAS_PUSH_BODY = re.compile(
    r"push\b[^|&;]*?(?:[\s:/\'\"+])(?:HEAD:)?\+?(?:main|master)(?=$|\s|[\'\"])")


def _alias_definition_form(sub: str) -> bool:
    """True when *sub* defines a gh or git alias that could expand to a merge."""
    # `_PAT_GIT_CONFIG_ALIAS` and `_PAT_GIT_C_ALIAS_DEF` both carry `[^|&;]*?`,
    # a lazy run that backtracks across the WHOLE sub-command, and `_normalize`
    # asks this question once per candidate head. 5000 `$a` tokens (three
    # candidates each, all opaque) spent 14 s inside these two. The word `alias`
    # is required by both patterns, so a C-level substring test decides it first
    # and the regexes only run on a line that could actually match.
    if "alias" not in sub:
        return False
    if _PAT_GH_ALIAS_IMPORT.match(sub):
        return True
    if _PAT_GH_ALIAS_SET.match(sub) and _ALIAS_MERGE_BODY.search(sub):
        return True
    if (_PAT_GIT_CONFIG_ALIAS.match(sub) or _PAT_GIT_C_ALIAS_DEF.match(sub)) and (
            _ALIAS_MERGE_BODY.search(sub) or _ALIAS_PUSH_BODY.search(sub)):
        return True
    return False


def _cmd_tokens(s: str) -> list[str]:
    """The decoded words of *s*, with the quote-blind fallback the peel uses."""
    toks = _tokens_with_offsets(s)
    if toks is None:
        toks = _ws_tokens(s)
    return [t for t, _s, _e in toks]


def _head_of(toks: list[str]) -> str:
    """The command word of *toks*: basename, quoting stripped, or ''."""
    return os.path.basename(toks[0].strip("\"'")) if toks else ""


def _gh_merge_form(view: tuple) -> bool:
    """True when the candidate *view* is a `gh pr merge`."""
    head, parts, base = view[0], view[1], view[2]
    return head == "gh" and _gh_merge_anchor(parts, base) is not None


def _git_push_form(view: tuple) -> str | None:
    """'main'/'master' when the candidate *view* pushes there, else None."""
    head, parts, base = view[0], view[1], view[2]
    if head != "git":
        return None
    start = _git_push_anchor(parts, base)
    return None if start is None else _git_push_branch(parts, start)


def _is_publish_form(dec: str, view: tuple):
    """Which publish pattern the normalized sub-command matches.

    One place, so candidate selection in _normalize_full and the form label in
    _find_publish_subcmds can never disagree about what a merge is.

    The VERB forms read *view* — (head, decoded tokens, base index, offsets,
    source) as `_peel_candidates` built it — because the token boundaries are
    the thing an option grammar needs and the decoded rendering does not carry
    them. *dec* is what the two REGEX forms read, and neither of those has an
    option grammar to lose. The view is required rather than optional so no
    caller can quietly fall back to re-reading the rendering.
    """
    head, parts, base = view[0], view[1], view[2]
    if head == "gh":
        pos = _gh_merge_anchor(parts, base)
        if pos is not None:
            return None if _gh_merge_is_help(parts, pos[1] + 1) else "gh"
    elif head == "git":
        start = _git_push_anchor(parts, base)
        if start is not None and _git_push_branch(parts, start):
            return None if _git_push_is_dry_run(parts, start) else "push"
    if _api_write_action(dec) is not None:
        return "api"
    if _alias_definition_form(dec):
        return "alias"
    return None


def _normalize_full(s: str, cfg_dir: str | None = None) -> tuple[str, str, tuple]:
    """(raw_form, decoded_form, view) of *s*: wrappers peeled, aliases expanded.

    Of the candidate head positions, the one that IS a publish form wins; else
    the first. Expansion is repeated because a shell alias can expand back into
    a wrapper (`!time gh pr merge`), and bounded so it cannot loop.

    The view travels with the two forms so the caller that asks for the form
    label again does not have to re-derive the tokens the peel already built.
    """
    cur = s
    # A view, never None: `_is_publish_form` indexes it, the peel always returns
    # one, and a crash BEFORE identification fails open — which is the one
    # direction this file never gets to fail in.
    fallback = (s, s, ("", [], 0, [], s))
    for _ in range(5):
        cands = _peel_candidates(cur)
        fallback = cands[0]
        for raw, dec, view in cands:
            if _is_publish_form(dec, view):
                return raw, dec, view
        nxt = None
        for raw, _dec, view in cands:
            expanded = _expand_alias(raw, cfg_dir, view)
            if expanded != raw:
                nxt = expanded
                break
        if nxt is None:
            break
        cur = nxt
    return fallback


def _normalize(s: str, cfg_dir: str | None = None) -> tuple[str, str]:
    """(raw_form, decoded_form) of *s* — `_normalize_full` without the view."""
    return _normalize_full(s, cfg_dir)[:2]


def _unwrap_sub(s: str, cfg_dir: str | None = None) -> str:
    """The RAW normalized form — quoting of the arguments preserved. Read by PR
    extraction, where a quoted flag value must stay one token."""
    return _normalize(s, cfg_dir)[0]


def _prefix_env(sub: str) -> dict:
    """VAR=val assignments in the wrapper prefix of *sub* (before the head).

    `GH_REPO=o/r gh pr merge 291` and `env GH_REPO=o/r gh pr merge 291` both put
    the variable here, and the peel above drops it — so it has to be read before
    it is dropped, not after.
    """
    toks = _tokens_with_offsets(sub)
    if toks is None:
        toks = _ws_tokens(sub)
    out = {}
    for text, _s, _e in toks:
        if os.path.basename(text.strip("\"'")) in _CMD_HEADS:
            break                    # the head: the prefix ends here
        k, sep, v = text.partition("=")
        if sep and re.fullmatch(r"[A-Za-z_]\w*", k):
            out[k] = v.strip("\"'")
    return out


def _line_env(cmd: str, matched_sub: str) -> dict:
    """Env the matched sub-command will actually see, from what is VISIBLE.

    Three reachable channels, all of them visible to a PreToolUse hook:
      * the wrapper prefix of the sub-command itself (see _prefix_env);
      * an `export VAR=val` or a bare assignment in an EARLIER sub-command of the
        same line. Measured 2026-09-08: an `export` in one Bash tool call does
        NOT survive into the next call, and the hook process never sees it, so
        same-line is the only way an agent can set a variable for a merge;
      * the hook's own process env, which is what an operator export before
        launching the harness looks like.
    Later channels lose to earlier ones, the way the shell resolves them.
    """
    parts = _line_parts(cmd)
    chain = _line_env_chain(cmd)
    try:
        idx = parts.index(matched_sub)
    except ValueError:
        idx = len(parts)          # not a part of this line: every assignment applies
    out = dict(chain[idx])
    out.update(_prefix_env(matched_sub))
    return out


_ENV_CHAIN_CACHE: dict[str, list[dict]] = {}


def _line_env_chain(cmd: str) -> list[dict]:
    """chain[i] = the env sub-command i of *cmd* sees, computed ONCE per line.

    This used to be O(n²) and it was a real hole, not a nuisance:
    `_cfg_dir_for` called `_line_env` once PER sub-command, and each call
    re-split and re-tokenized the WHOLE command. 500 `;`-joined no-ops plus a
    merge took 9.7 s (measured 2026-09-08) against this gate's `hooks.json`
    timeout of 5 s, and 2000 took 132 s. The gate still returned 2; it just
    never got to say so. A fail-closed contract that depends on the process
    surviving is not fail-closed, so the fix is the complexity, not the
    timeout. One extra entry at the end: the env after every part, which is
    what a sub-command that is not in this list should see.
    """
    # The process env is part of the answer, so it is part of the key: caching on
    # the command string alone would hand a stale chain to the next caller after
    # an export (and to the next test that patches os.environ).
    key = (cmd, os.environ.get("GH_REPO"), os.environ.get("GH_HOST"),
           os.environ.get("GH_CONFIG_DIR"))
    chain = _ENV_CHAIN_CACHE.get(key)
    if chain is not None:
        return chain
    # Three lookups, not a walk of the whole environment. Identical result; the
    # walk cost ~92 decodes per cache MISS, and the Class A recursion turned one
    # miss per line into one per command substitution (2000 of them: 4.98 s of a
    # 9.3 s parse, profiled 2026-09-08).
    acc = {k: os.environ[k] for k in ("GH_REPO", "GH_HOST", "GH_CONFIG_DIR")
           if k in os.environ}
    chain = []
    for raw in _line_parts(cmd):
        chain.append(dict(acc))
        toks = _tokens_with_offsets(raw)
        if toks is None:
            toks = _ws_tokens(raw)
        words = [t for t, _s, _e in toks]
        if words and os.path.basename(words[0]) == "export":
            words = words[1:]
        for text in words:
            k, sep, v = text.partition("=")
            if sep and re.fullmatch(r"[A-Za-z_]\w*", k):
                acc[k] = v.strip("\"'")
            else:
                break
    chain.append(dict(acc))
    if len(_ENV_CHAIN_CACHE) > 64:
        _ENV_CHAIN_CACHE.clear()
    _ENV_CHAIN_CACHE[key] = chain
    return chain


def _cfg_dir_for(cmd: str, sub: str) -> str | None:
    """GH_CONFIG_DIR as the sub-command will see it. A6: reading it only from the
    hook's own env made `GH_CONFIG_DIR=/tmp/x gh mrg 291` resolve aliases out of
    the wrong file, so the alias resolver could not see the alias that ran."""
    try:
        return _line_env(cmd, sub).get("GH_CONFIG_DIR") or None
    except Exception:
        return None


def _split_subcmds(cmd: str) -> list[str]:
    """The sub-commands of *cmd*, separators dropped. See `_split_subcmds_sep`.

    Kept as its own name because `receipt_ledger._qa_gate_helpers()` imports it
    (see `_strip_leading`), and a consumer's `except Exception` turns a renamed
    helper into a silent no-op rather than a failure.
    """
    return [p for p, _sep in _split_subcmds_sep(cmd)]


_SPLIT_CACHE: dict[str, list[tuple[str, str]]] = {}


def _split_subcmds_sep(cmd: str) -> list[tuple[str, str]]:
    """Split *cmd* on unquoted shell separators (;  &&  ||  |  &  newline).

    Returns [(sub_command, separator_that_ENDED_it)], "" for the last one. The
    separator is kept because `|` is not just a boundary, it is a CHANNEL: the
    text one stage prints is the SCRIPT the next stage runs when that stage is a
    shell reading stdin. `printf 'gh pr merge 291' | bash` and
    `echo "gh pr merge 291" | xargs -I{} bash -c "{}"` were both measured
    executing a fake `gh` on PATH while this gate ALLOWED them (QA cycle 5,
    Class C), because each half is innocent and only the pipe joins them.

    `&` is a separator (A2): it BACKGROUNDS the command before it and starts a
    new one, so `git status & gh pr merge 291` is two commands, and omitting it
    made the whole tail one sub-command whose head was `git status`. `&&` is
    matched first, so it is unaffected; a `&` inside `2>&1` or `|&` splits into
    fragments that are not commands and match nothing.

    Tracks single-quote and double-quote state so that separators inside
    quoted strings are treated as literal characters and do NOT cause a split.
    Returns a list of raw sub-command strings (may be empty after stripping).
    """
    cached = _SPLIT_CACHE.get(cmd)
    if cached is not None:
        return cached
    parts: list[tuple[str, str]] = []
    buf: list[str] = []
    in_single = False
    in_double = False
    i = 0
    n = len(cmd)
    while i < n:
        ch = cmd[i]
        if ch == "'" and not in_double:
            in_single = not in_single
            buf.append(ch)
            i += 1
        elif ch == '"' and not in_single:
            in_double = not in_double
            buf.append(ch)
            i += 1
        elif not in_single and not in_double:
            # A `#` that STARTS a word opens a shell comment: everything to the
            # end of the line is text the shell never runs. Keeping it made the
            # peel try a head position inside a comment, so
            # `git status # gh pr merge 292` DENIED — an over-fire measured
            # 2026-09-08 on a command that publishes nothing. A `#` in the
            # middle of a word is not a comment (`curl https://x#frag`), which
            # is why the preceding character has to be whitespace or nothing.
            if ch == "#" and (i == 0 or cmd[i - 1].isspace()):
                j = cmd.find("\n", i)
                i = n if j < 0 else j
                continue
            # Check for two-char separators first
            two = cmd[i:i + 2]
            if two in ("&&", "||"):
                parts.append(("".join(buf), two))
                buf = []
                i += 2
            elif ch in (";", "|", "\n", "&"):
                parts.append(("".join(buf), ch))
                buf = []
                i += 1
            else:
                buf.append(ch)
                i += 1
        else:
            buf.append(ch)
            i += 1
    parts.append(("".join(buf), ""))
    if len(_SPLIT_CACHE) > 256:
        _SPLIT_CACHE.clear()
    _SPLIT_CACHE[cmd] = parts
    return parts


_HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][\w.-]*)\1")
# Heads that RE-PARSE a string argument (or stdin) as a command. This set, not
# the presence of quotes, is what separates a quoted MENTION from a quoted
# COMMAND (A4).
_REPARSE_HEADS = frozenset({"bash", "sh", "zsh", "dash", "ksh", "ssh", "script",
                            "eval"})
_STDIN_REPARSE_HEADS = frozenset({"bash", "sh", "zsh", "dash", "ksh", "ssh"})
# Single-letter options that may legitimately share a bundle with `c` on a shell
# or a shell-like wrapper (`bash -lc`, `sh -ic`, `script -qc`). A bundle carrying
# any letter outside this set is not a command flag, which is what stops the old
# substring test from reading `--norc` as one.
_SHELL_OPT_LETTERS = frozenset("abcefhiklmnopqrstuvxBCDEHIPT")
# Recursion bound. It is a COST bound, not a security one: at the cap a remaining
# re-parsing head is treated as a merge and DENIED, because "I stopped looking"
# is not "there is nothing there". Failing OPEN here meant depth 3 denied and
# depth 4 allowed — four nested `bash -c` executed the real gh (QA cycle 3,
# bypass 2). Raised from 3 to 5 so the deny lands past any nesting a real command
# uses, and the cost stays bounded because each level parses a shorter string.
_MAX_REPARSE_DEPTH = 5


def _split_heredocs(cmd: str) -> tuple[str, list[tuple[str, str]]]:
    """(*cmd* with heredoc BODIES removed, [(opening_line, body)]).

    A heredoc body is DATA written to a command's stdin, not a command line, and
    treating it as one is where this gate's worst over-fire lived: a note whose
    prose read `To publish: git push origin main` was BLOCKED (measured
    2026-09-08), which is a security failure with extra steps — a gate people
    route around is off. The bodies are returned rather than discarded because a
    SHELL reading its stdin does execute them; see _find_publish_subcmds.

    A `<<WORD` with no matching terminator line is not treated as a heredoc at
    all, so a `<<` inside ordinary text (`echo "a << b"`) can never swallow the
    commands that follow it.
    """
    lines = cmd.split("\n")
    # Where each stripped line CONTENT occurs, built once. The terminator used to
    # be found by scanning every remaining line per `<<WORD`, so a line carrying
    # many openers with no terminator was O(lines²).
    at: dict[str, list[int]] = {}
    for j, ln in enumerate(lines):
        at.setdefault(ln.strip(), []).append(j)
    kept: list[str] = []
    bodies: list[tuple[str, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        kept.append(line)
        i += 1
        for _q, term in _HEREDOC_RE.findall(line):
            end = None
            for j in at.get(term, ()):        # ascending; first one at or past i
                if j >= i:
                    end = j
                    break
            if end is None:
                continue                      # no terminator: not a heredoc
            bodies.append((line, "\n".join(lines[i:end])))
            i = end + 1
    return "\n".join(kept), bodies


# Cross-script contract, restored. `receipt_ledger._qa_gate_helpers()` imports
# `_split_subcmds` AND `_strip_leading` from this file to split a Bash command
# the same way the merge gate does; 2ceb87c replaced the old peel and deleted
# this name, and the consumer's `except Exception` turned that into a SILENT
# fallback in which `receipt_ledger.subcommands()` stopped splitting at all —
# no test failed, and the seek-receipt detection behind the outward-send gate
# quietly degraded. The gate itself uses the richer peel above; this stays as
# the published, prefix-only stripper its consumer asked for.
#
# The PUBLISHED surface of this file, for any gate that needs the same rule
# rather than a second copy of it: `_split_subcmds` / `_split_subcmds_sep`
# (boundaries), `_strip_leading` (prefix noise), `_command_substitution_texts`
# (the `$(…)`, backtick and `>(…)` channels) and `_may_publish` (its sound
# pre-filter). All four are pure string -> string with no intra-file dependency,
# so borrowing one adds nothing to the borrower's hot path.
_STRIP_PREFIX_RE = re.compile(
    r"^(?:[({]\s*)*"               # grouping openers
    r"(?:[A-Za-z_]\w*=\S*\s+)*"    # env assignments  VAR=val
    r"(?:\d*[<>]+\S*\s+)*"         # redirections     >/dev/null  2>&1
)


def _strip_leading(s: str) -> str:
    """*s* with leading env-vars, redirections and grouping chars removed."""
    return _STRIP_PREFIX_RE.sub("", s, count=1)


_PARTS_CACHE: dict[str, list[str]] = {}


def _line_parts(cmd: str) -> list[str]:
    """The sub-commands of *cmd*: continuations joined, heredoc bodies removed,
    split on unquoted separators. One definition, so the matcher, the cwd walk
    and the env walk can never disagree about where a sub-command starts.

    Memoized: it depends on nothing but the string, and the cwd walk, the env
    chain and the matcher all ask for the same line. Re-deriving it per
    sub-command is where 11.8 s of a 14 s parse went (see _line_env_chain).
    """
    parts = _PARTS_CACHE.get(cmd)
    if parts is None:
        parts = _split_subcmds(_split_heredocs(_join_continuations(cmd))[0])
        if len(_PARTS_CACHE) > 64:
            _PARTS_CACHE.clear()
        _PARTS_CACHE[cmd] = parts
    return parts


def _is_command_flag(w: str) -> bool:
    """True when *w* is the flag that says 'the next token is a COMMAND'.

    Matched EXACTLY, or as a shorthand bundle whose letters are ALL known shell
    options and one of them is `c` (`-lc`, `-ic`, `-xc`, `-qc`, `-lic`). The old
    test was a SUBSTRING — `w.startswith("-") and "c" in w.lstrip("-")` — so
    `--norc` looked like a command flag, `_reparse_arg` returned the literal
    `-c` as the command to run, and the caller then skipped the direct match on
    the outer sub-command as well. `bash --norc -c "gh pr merge 292"` allowed
    and executed the real gh (QA cycle 3, bypass 1). A wrong guess must never
    REPLACE the check; here it cannot even be made, and the caller falls through
    to the direct match either way.
    """
    if not w.startswith("-") or w in ("-", "--"):
        return False
    if w.startswith("--"):
        return w == "--command"
    letters = w[1:]
    return "c" in letters and all(ch in _SHELL_OPT_LETTERS for ch in letters)


# Shell option LETTERS whose VALUE is the next word: `-o pipefail` names a set
# -o option, `-O extglob` names a shopt. Both also spell with a leading `+` to
# turn the option off, and `+` is not `-`, which is the whole of Class B below.
_SHELL_VALUE_OPT_LETTERS = frozenset("oO")
# Long shell options that take a separate value word.
_SHELL_VALUE_OPT_LONGS = frozenset({"--rcfile", "--init-file"})


def _opt_consumes_next(w: str) -> bool:
    """True when option word *w* eats the FOLLOWING word as its value.

    Class B, QA cycle 5. `_command_flag_value`'s option walk skipped an option
    but never its VALUE, so the value came back as the command string and the
    real command behind it was never looked at:
    `bash -c -o pipefail "gh pr merge 292"` returned `pipefail` and ALLOWED,
    measured executing a fake `gh` on PATH. The `+` spellings were worse than
    skipped — `+O` does not start with `-`, so the walk read it as the command
    string itself and `bash -c +O extglob "gh pr merge 292"` ALLOWED too.
    An attached value (`-Oextglob`) consumes nothing; a bundle whose LAST letter
    takes a value does (`bash -co pipefail "…"` — measured executing).
    """
    if w.startswith("--"):
        return "=" not in w and w in _SHELL_VALUE_OPT_LONGS
    letters = w[1:]
    for k, ch in enumerate(letters):
        if ch in _SHELL_VALUE_OPT_LETTERS:
            return k == len(letters) - 1
    return False


def _command_flag_value(words: list[str], bundles: bool = True) -> str | None:
    """The token a `-c`-style flag in *words* hands to a shell, else None.

    Four things the old one-liner (`if _is_command_flag(w): return words[i+1]`)
    got wrong, every one of them measured as an ALLOW that executed the real gh
    through a fake `gh` on PATH (QA cycles 4 and 5):

    * bash, sh, dash and ksh keep parsing OPTIONS after `-c`. The command string
      is the first NON-option word, and `--` ends option parsing. Taking
      `words[i + 1]` handed back `--` or `-e`, the recursion found nothing in it,
      and `bash -c -- "gh pr merge 292"`, `bash -c -e "…"` and `sh -c -- "…"`
      all walked.
    * an option that takes a VALUE consumes the next word too, and the `+`
      spellings are options as well. See `_opt_consumes_next` — that half of the
      walk was left undone in the fix above and cost five more ALLOWs.
    * the long flag was only ever matched whole, so `su --command="…"` and
      `flock --command="…" f` allowed while `flock --command "…" f` denied. The
      `=` spelling is the same flag.
    * *bundles*: on the UNNAMED-wrapper path a `-c` inside a letter bundle is a
      non-shell option cluster far more often than a shell's `-lc`, and reading
      it as a command channel DENIED `grep -rc "git push origin main" docs/` and
      `grep -ic "gh pr merge 292" notes.md`. A named shell head keeps the bundle
      reading (`bash -lc` is real); nobody-named gets the exact flag only.
    """
    for i, w in enumerate(words):
        if w.startswith("--") and "=" in w:
            name, _eq, inline = w.partition("=")
            if _is_command_flag(name):
                return inline or None
            continue
        if not _is_command_flag(w):
            continue
        if not bundles and w != "-c" and w != "--command":
            continue
        j = i + 2 if _opt_consumes_next(w) else i + 1
        while j < len(words):
            t = words[j]
            if t == "--":                       # end of options: the next word
                return words[j + 1] if j + 1 < len(words) else None
            if len(t) > 1 and t[0] in "-+":     # another option, keep looking
                j += 2 if _opt_consumes_next(t) else 1
                continue
            return t
        return None
    return None


# The first word of a sub-command, once the shell's own leading noise is gone.
_ENV_WORD_RE = re.compile(r"^[A-Za-z_]\w*=")
_REDIR_WORD_RE = re.compile(r"^\d*[<>]")
_BARE_REDIR_RE = re.compile(r"^\d*[<>]+$")


def _head_index(words: list[str]) -> int:
    """Index of the COMMAND HEAD in *words*: the first word that is not a leading
    env assignment, a redirection or a grouping opener.

    The head POSITION is the point. `_reparse_args` used to test EVERY word ahead
    of the re-parsing head against `_CMD_HEADS` and return "nothing re-parses" on
    a hit, so any wrapper carrying a path or a user name whose basename happened
    to be `gh`, `git`, `curl` or `cd` was a total bypass:
    `flock /var/lock/git -c "gh pr merge 292"` and `sudo -u git bash -c "…"` both
    allowed and both executed the real gh (QA cycle 4, root cause b). `git` is the
    canonical service-account and lock-file name, so that shape is ordinary rather
    than exotic. Anchoring the short-circuit on the head is what makes the
    argument a mere argument again.
    """
    i = 0
    while i < len(words):
        w = words[i]
        if w in ("(", "{"):
            i += 1
            continue
        if _ENV_WORD_RE.match(w):
            i += 1
            continue
        if _BARE_REDIR_RE.match(w):
            i += 2                    # `> file`: the target is not the head
            continue
        if _REDIR_WORD_RE.match(w):
            i += 1                    # `>file`, `2>&1`
            continue
        return i
    return len(words)


# Programs whose `-c` means COUNT or "run this QUERY", not "run this COMMAND".
# The unnamed-wrapper inversion below reads a `-c` as a command channel, which is
# right for `flock`, `su`, `runuser` and every wrapper nobody named, and wrong for
# these: `grep -c "gh pr merge 292" notes.md` counts matching lines and
# `psql -c "insert into log values ('git push origin main')"` runs SQL. Both
# DENIED (QA cycle 4) — over-fire, and a gate people route around is off.
#
# This is an ALLOW-side enumeration, the one shape this file otherwise refuses,
# so it is fenced three ways: it is consulted ONLY on the unnamed path (a real
# `bash`/`sh`/`eval`/`ssh` head is still read as a shell, so `sh -c` inside one of
# these is unaffected), it anchors on the HEAD word alone (a `grep` sitting in a
# wrapper's path argument exempts nothing — that is bypass (b) again), and its
# failure mode is a loud over-fire on an unlisted counter, never a silent allow.
_NON_SHELL_C_HEADS = frozenset({
    "grep", "egrep", "fgrep", "zgrep", "zegrep", "rg", "ag", "ack", "ugrep",
    "uniq", "sort", "nl", "pgrep", "wc", "cut", "comm", "od",
    "psql", "mysql", "mariadb", "sqlite3", "duckdb", "clickhouse-client",
    "redis-cli", "mongosh", "cqlsh", "influx",
    "gcc", "g++", "cc", "clang", "clang++", "as", "ld", "javac",
    "tar", "cpio", "openssl", "objcopy", "objdump", "install",
})

# Heads whose ARGUMENTS ARE DATA. The Class C inversion (`_reparse_args`) reads
# every argument of an unnamed wrapper as a command line it may run, which is
# right for `env -S`, `watch`, `parallel`, `su`, `flock`, `systemd-run` and every
# wrapper nobody has named yet — and wrong for a program whose argument is a
# MESSAGE, a PATTERN, a FILENAME or a program in another language.
#
# The trade, stated plainly: this file refuses allow-side enumerations because an
# enumeration loses to its next member, and this is one. It is the deliberate
# choice of WHICH dimension carries the enumeration. The channel dimension is
# open-ended (five new channels arrived in one QA cycle); the "programs whose
# arguments are text" dimension is finite, its members are famous, and its
# failure mode is a loud OVER-FIRE on an unlisted one, never a silent allow. It
# is the same reasoning, and the same fences, as `_NON_SHELL_C_HEADS` (residual
# 8), which is why that set is folded in whole rather than duplicated.
#
# Interpreters are here on purpose: `awk 'BEGIN{system("gh pr merge 291")}'`,
# `python3 -c "os.system(…)"` and `perl -e 'system …'` all execute, and all three
# are residual 3 (a merge through a NON-SHELL runtime), not a shell channel. The
# argument is a program in another language, and identifying a merge inside one
# means writing an interpreter for that language — see the header.
_INERT_ARG_HEADS = _CMD_HEADS | _NON_SHELL_C_HEADS | frozenset({
    # text out
    "echo", "printf", "cat", "tee", "less", "more", "logger", "notify-send",
    "banner", "figlet", "cowsay", "say", "espeak", "wall", "write", "zenity",
    "yes", "expr", "test", "[", "basename", "dirname", "seq", "readlink",
    # mail and messaging: the argument is a subject or a body
    "mail", "mailx", "sendmail", "msmtp", "mutt", "neomutt",
    # text processing: the argument is a PATTERN or a script in its own language
    "sed", "awk", "gawk", "mawk", "nawk", "tr", "rev", "fold", "fmt", "column",
    "jq", "yq", "xmlstarlet", "csvtool", "miller", "mlr", "datamash",
    # other-language runtimes: residual 3, not a shell channel
    "python", "python2", "python3", "perl", "ruby", "node", "nodejs", "deno",
    "bun", "php", "lua", "tclsh", "Rscript", "julia", "ghc", "runghc", "bc",
    "dc", "osascript",
    # search and archive: the argument is a pattern or a member name
    "find", "locate", "fd", "diff", "cmp", "patch", "zip", "unzip", "gzip",
    # version control that is not git/gh: the argument is a message
    "hg", "svn", "bzr", "jj", "hub", "glab", "tea",
})

# ssh short options that take a VALUE, so the word after them is not the
# destination. `-o` is the one that can carry a whole command line.
_SSH_VALUE_SHORTS = frozenset("BbcDEeFIiJLlmOoPpQRSWw")
_SSH_REMOTE_CMD_RE = re.compile(r"^remotecommand=(.+)$", re.IGNORECASE | re.DOTALL)


def _ssh_commands(rest: list[str]) -> list[str]:
    """Every command line an `ssh` invocation carries, given its arguments.

    Two channels, and the old `rest[1:]` read neither correctly:

    * the words after the DESTINATION. `rest[1:]` assumed the destination was the
      first argument, so one option in front shifted the read a word early.
    * `-o RemoteCommand=…`, which `ssh -G` confirms is honoured as the command to
      run: `ssh -o RemoteCommand='gh pr merge 292' host` ALLOWED (QA cycle 4).
    """
    out: list[str] = []
    i = 0
    dest = None
    while i < len(rest):
        w = rest[i]
        if w == "--":
            i += 1
            continue
        if not (w.startswith("-") and len(w) > 1):
            dest = i
            break
        val = None
        for k, ch in enumerate(w[1:]):
            if ch in _SSH_VALUE_SHORTS:
                val = w[k + 2:]
                if not val and i + 1 < len(rest):
                    i += 1
                    val = rest[i]
                break
        if val:
            m = _SSH_REMOTE_CMD_RE.match(val.strip("\"'"))
            if m:
                out.append(m.group(1))
        i += 1
    if dest is not None and dest + 1 < len(rest):
        out.append(" ".join(rest[dest + 1:]))
    return out


def _publish_carriers(text: str, mentions: bool = True) -> list[str]:
    """The parts of *text* that ARE a publish form, when *text* is content a
    shell will execute. Empty list when it carries none.

    Two readings, because a channel can carry the command either way: as one of
    its own sub-commands (`cd /r && gh pr merge 292` behind a `-c`), or as a
    quoted argument it hands on (`echo "gh pr merge 292"` inside a `<(...)`).
    A single-word token is never a carrier — one token cannot supply the two
    words a verb needs after a head, which is what keeps a mention benign.

    *mentions* selects the second reading. It is a stdin-channel rule, not a
    universal one: `bash <(echo "gh pr merge 292")` really does run the quoted
    argument, but on the unnamed-wrapper `-c` path the same reading turned a
    quoted MENTION inside somebody else's data into a merge —
    `psql -c "insert into log values ('git push origin main')"` DENIED (QA cycle
    4), because the token `('git push origin main')` unwraps to a push. There the
    value has to parse as a whole command LINE, which that SQL statement does not.
    """
    out = [sub for sub in _split_subcmds(text)
           if _is_publish_form(*_normalize_full(sub)[1:])]
    if out or not mentions:
        return out
    toks = _tokens_with_offsets(text)
    if toks is None:
        toks = _ws_tokens(text)
    return [t for t, _s, _e in toks
            if " " in t and _is_publish_form(*_normalize_full(t)[1:])]


def _stdin_channel_texts(raw_sub: str) -> list[str]:
    """Texts *raw_sub* feeds to a command's STDIN through a channel that is not
    a heredoc: a here-string (`<<< "…"`, `<<<"…"`) or a process substitution
    (`<(…)`, which is also how `/dev/stdin` gets its content).

    `_HEREDOC_RE` matches `<<WORD` only, so a here-string never became a body and
    `_reparses_stdin` was never consulted: `bash <<< "gh pr merge 292"` and
    `bash /dev/stdin <<< "…"` both allowed and both executed the real gh (QA
    cycle 3, bypass 3).
    """
    toks = _tokens_with_offsets(raw_sub)
    if toks is None:
        toks = _ws_tokens(raw_sub)
    words = [t for t, _s, _e in toks]
    out: list[str] = []
    for i, w in enumerate(words):
        if w.startswith("<<<"):
            rest = w[3:].strip()
            if rest:
                out.append(rest)
            elif i + 1 < len(words):
                out.append(words[i + 1])
        start = w.find("<(")
        if start >= 0:
            depth, j = 0, start + 1
            while j < len(w):
                if w[j] == "(":
                    depth += 1
                elif w[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            out.append(w[start + 2:j])
    return out


# Every publish pattern in this file needs one of these five substrings to be
# present in the text, after quoting and backslash escapes are flattened:
#   `_gh_merge_anchor` -> "merge"; `_git_push_anchor` -> "push"; the alias-definition
#   forms -> "gh" or "git"; and every `_api_write_action` shape -> "merge"
#   (/pulls/N/merge, /merges, mergePullRequest, enablePullRequestAutoMerge,
#   mergeBranch) or "git" (/git/refs/heads/main). An OPAQUE head synthesizes
#   `gh`/`git`/`curl`, but the REMAINDER still has to carry the verb, so the
#   probe holds there too.
# It is a PRE-FILTER for the two channels this cycle added, never for an
# existing path: at worst it declines to open a new channel, which is the
# behaviour before the channel existed. It exists because both new scans are
# per-WORD and per-SUBSTITUTION, and residual 9 says a gate the harness kills at
# 5 s is a gate that never says no. Measured: 20000 benign words 5.10 s -> 1.43 s.
_MAY_PUBLISH = ("gh", "git", "curl", "merge", "push")
_FLATTEN = str.maketrans("", "", "\\\"'")


def _may_publish(text: str) -> bool:
    """False when *text* provably matches no publish pattern in this file.

    "Sound by construction" is sound only for the ALPHABET the flatten table
    knows, which cycle 7 measured: `$'\\x6d\\x65\\x72\\x67\\x65'` flattens to
    `$x6dx65x72x67x65`, carries none of the five words, and a substitution
    holding it was dropped before the recursion could ever look at it. So the
    probe decodes ANSI-C and locale quoting first, by the same reader the
    tokenizer uses. The decode only ever ADDS text, so the filter can widen and
    never narrow."""
    probe = _ansi_c_expand(text).translate(_FLATTEN).lower()
    return any(w in probe for w in _MAY_PUBLISH)


def _command_substitution_texts(s: str) -> list[str]:
    """The CONTENTS of every command substitution in *s*, outermost first.

    Class A, QA cycle 5, and it is a skipped fix rather than a residual. Cycle 3
    closed `<(…)` by treating it as a channel whose contents are re-matched, and
    the tokenizer learned to swallow `$(…)` as ONE token in the same commit — but
    only so an OPAQUE HEAD could be recognized (`$(echo gh) pr merge 291`). What
    is INSIDE the parens was never looked at, so the more common literal twin of
    the closed channel walked: `cat <(gh pr merge 291)` DENIED while
    `echo $(gh pr merge 291)` ALLOWED, both measured executing a fake `gh` on
    PATH. Same channel, same execution, opposite verdicts.

    Every OTHER member of this class, enumerated so the next reader can check it
    rather than trust it. A member is any syntax that makes the shell execute a
    span of the CURRENT command line as a command line of its own:
      * ``$(…)``           — command substitution.        Closed here.
      * ``` `…` ```        — the archaic spelling of it.  Closed here.
      * ``>(…)``           — process substitution, write side; the contents run.
                             Measured executing (``tee >(gh pr merge 291)``).
                             Closed here.
      * ``<(…)``           — process substitution, read side. Closed in cycle 3;
                             it stays in `_stdin_channel_texts` because a shell
                             may also read the resulting FILE as a script, which
                             is the one place the quoted-mention reading applies.
      * ``$((…))``         — arithmetic, NOT a command. Skipped explicitly, and
                             it has to be skipped explicitly because it opens
                             with the same two characters.
      * ``${ …; }`` / ``${| …; }`` — bash 5.3 funsubs. NOT reachable on the
                             installed bash (5.2: measured `noexec`, a syntax
                             error), so wiring them would be untestable here.
                             Named as residual 10 rather than pretended.
      * a substitution inside SINGLE quotes is not a substitution at all, so the
        scan tracks quote state; `git -c core.pager='gh pr merge 291'` is a
        different class entirely (Class C, the git config channel).

    Contents are returned RAW and re-identified by the caller's recursion, which
    is what makes nesting free: `$(x $(gh pr merge 291))` finds the inner one at
    the next depth. They are NOT run through the quoted-mention reading — a
    `$(…)` is executed as a command LINE, so a quoted string inside it is that
    command's data (`x=$(grep "gh pr merge 291" notes.md)` publishes nothing).

    SHARED ON PURPOSE, in the direction the import graph already flows. This is
    a module-level function over a plain string returning plain strings, with no
    dependency on anything else in this file — deliberately, so the other gates
    borrow it the way `receipt_ledger._qa_gate_helpers()` already borrows
    `_split_subcmds` and `_strip_leading` from here (see `_STRIP_PREFIX_RE`).
    This file is the PROVIDER of the command-boundary parser, not a consumer:
    `g__pretool-bash__tree-owner.py` borrows ITS splitter from
    `dimension-awareness-hook.py`, and `receipt_ledger.py` borrows from here, so
    an import the other way would close a cycle through a module that
    `exec_module`s this one. Three copies of one rule is what this session keeps
    paying for; one copy, borrowed downhill, is the fix.
    """
    out: list[str] = []
    i, n = 0, len(s)
    in_single = in_double = False
    while i < n:
        ch = s[i]
        if ch == "\\" and not in_single and i + 1 < n:
            i += 2
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            i += 1
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            i += 1
            continue
        if in_single:
            i += 1
            continue
        if ch == "`":
            j = s.find("`", i + 1)
            if j < 0:
                break
            out.append(s[i + 1:j])
            i = j + 1
            continue
        opens_sub = (ch == "$" and i + 1 < n and s[i + 1] == "("
                     and not (i + 2 < n and s[i + 2] == "("))
        # `>(…)` is a redirection to a process, not a substitution inside a
        # string, so it is only one outside double quotes — same rule `<(…)`
        # already follows in the tokenizer.
        opens_proc = (ch == ">" and not in_double
                      and i + 1 < n and s[i + 1] == "(")
        if opens_sub or opens_proc:
            depth, j = 0, i + 1
            while j < n:
                if s[j] == "(":
                    depth += 1
                elif s[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            if j >= n:
                break                       # unclosed: nothing runs
            out.append(s[i + 2:j])
            i = j + 1
            continue
        i += 1
    return out


def _reparse_args(raw_sub: str) -> list[str]:
    """Every command STRING *raw_sub* will hand to a shell, in order.

    A4: the property that separates a quoted MENTION from a quoted COMMAND is not
    quoted-vs-unquoted, it is whether the head RE-PARSES its argument. `git commit
    -m "gh pr merge 96"` never does, `echo "…"` never does; `bash -c`, `sh -lc`,
    `eval`, `ssh host`, `script -qc` always do.

    But `_REPARSE_HEADS` is an ALLOWLIST, and the wrapper nobody named is a total
    bypass: `flock /tmp/l -c "gh pr merge 292"` and `su -c "…"` walked straight
    through (QA cycle 3, bypass 5). That is cycle 1's wrapper finding one layer up
    — the deny-by-default peel only inverted identification for BARE head tokens,
    and when the command is a quoted ARGUMENT identification was back on an
    enumeration. So it is inverted here the same way: when no head this gate reads
    comes first, ANY `-c`-style flag or stdin channel whose content PARSES as a
    publish form is a re-parse, whatever the wrapper is called.

    The inversion is bounded FOUR ways, because the first cut of it was measured
    denying three ordinary read-only commands (`grep -c`, `grep -rc`, `psql -c`)
    and over-fire is a security failure with extra steps — a gate people route
    around is off:

      * the HEAD must not be a command head. That test is on the head POSITION
        now, not on every word, which is what closed the `flock /var/lock/git -c`
        and `sudo -u git bash -c` bypasses (see `_head_index`).
      * the flag must be EXACTLY `-c` or `--command`. A letter bundle on a
        wrapper nobody named is an option cluster far more often than a shell's
        `-lc`, and reading `-rc`/`-ic` as a command channel is what denied
        `grep -rc "git push origin main" docs/`.
      * the HEAD must not be a program whose `-c` counts or queries
        (`_NON_SHELL_C_HEADS`). Stated as residual 8 in the header, with both of
        its edges measured.
      * the value must parse as a whole command LINE, not as a quoted MENTION
        inside it (`mentions=False`), which is what stopped a `git push origin
        main` inside a SQL string literal from being read as a push.

    `echo "gh pr merge 96"` carries no command flag and `git commit -m "…"` is a
    command head, so neither ever reaches the inversion. `gcc -c main.c` has the
    flag and no publish form. The residual cost is a command that takes a literal
    `-c "git push origin main"` and does NOT execute it — measured as none on a
    50-command over-fire corpus, and loud rather than silent when it happens.

    CYCLE 5, Class C — the enumeration moved, so it lost again. The inversion
    above was on the WRAPPER, but the CHANNEL went back to a list: `-c`,
    `--command`, stdin, ssh RemoteCommand. Five wrappers arrived in one cycle
    that run their quoted argument through some OTHER channel, every one measured
    executing a fake `gh` on PATH: `env -S "…"`, `env --split-string="…"`,
    `watch "…"`, `parallel "…"`, and `xargs` behind a pipe. An enumeration of
    channels loses to the next channel exactly the way an enumeration of verbs
    lost to the next verb, which is the lesson this whole PR is built on, so it
    is inverted here too and the fence moves entirely onto the HEAD:

        on a head that is neither a command head nor a head whose arguments are
        DATA (`_INERT_ARG_HEADS`), EVERY argument that parses as a whole publish
        command LINE is a command this wrapper runs.

    The `-c` reading is not deleted, it is subsumed: a `-c` value is an argument.
    What the head fence buys is that the over-fire surface is now enumerable and
    finite (the programs whose arguments are text), instead of the channel
    surface, which is not. Measured 2026-09-08, before-vs-after against 8e544c6:
    0 denials on a 74-command read-only corpus, and 0 NEW denials on 400 real
    commands extracted from this repo's own docs (1 pre-existing deny there,
    `git push --force-with-lease origin master`, which is a real push to master).
    The shapes both corpora cover are pinned as unit anchors in
    TestTheQuotedCommandPathIsDenyByDefaultToo, so the measurement is repeatable
    rather than a number in a comment.
    """
    # A command substitution executes NO MATTER WHAT THE HEAD IS, so it is read
    # before the command-head short-circuit below: `git commit -m "$(gh pr merge
    # 291)"` merges, and `git` is a command head.
    out: list[str] = [t for t in _command_substitution_texts(raw_sub)
                      if _may_publish(t)]
    toks = _tokens_with_offsets(raw_sub)
    if toks is None:
        toks = _ws_tokens(raw_sub)
    words = [t for t, _s, _e in toks]
    h = _head_index(words)
    head0 = os.path.basename(words[h].strip("\"'")) if h < len(words) else ""
    if head0 in _CMD_HEADS:
        # The HEAD is a command head, so its own arguments are arguments. One
        # exception, and it is git's own: `git -c KEY=VALUE` where git RUNS the
        # value through a shell. `core.sshCommand` and `sequence.editor` were
        # both measured executing a fake `gh`; `core.pager`, `core.editor` and
        # `diff.external` are the same mechanism with a tty or a diff in the way.
        # Read as an inversion, not as a key list: ANY `-c` value that parses as
        # a publish command line is one, because no benign `git -c` carries a
        # merge on its right-hand side. The alias spelling is gated separately
        # (`_PAT_GIT_C_ALIAS_DEF`), as a DEFINITION rather than a run.
        if head0 == "git":
            for k in range(h + 1, len(words)):
                if words[k] == "-c" and k + 1 < len(words):
                    _key, _eq, val = words[k + 1].partition("=")
                    if _eq:
                        out.extend(_publish_carriers(val, mentions=False))
                elif words[k].startswith("-c") and len(words[k]) > 2:
                    _key, _eq, val = words[k][2:].partition("=")
                    if _eq:
                        out.extend(_publish_carriers(val, mentions=False))
        return out
    named = None
    for i in range(h, len(words)):
        if os.path.basename(words[i].strip("\"'")) in _REPARSE_HEADS:
            named = i
            break
    before_named = len(out)
    if named is not None:
        rest = words[named + 1:]
        head = os.path.basename(words[named].strip("\"'"))
        if head == "eval":
            # eval concatenates ALL its arguments and runs the result. It carries
            # no `-c`, so the flag walk never saw it and `eval "gh pr merge 291"`
            # allowed (measured 2026-09-08) — while UNQUOTED `eval gh pr merge
            # 291` denied through the peel, the tell that the quoting, not the
            # command, was doing the deciding.
            if rest:
                out.append(" ".join(rest))
        elif head == "ssh":
            out.extend(_ssh_commands(rest))
        else:
            v = _command_flag_value(rest)
            if v is not None:
                out.append(v)
    if (named is None and len(out) == before_named
            and head0 not in _INERT_ARG_HEADS):
        rest = words[h + 1:]
        skip = -1
        for k, w in enumerate(rest):
            # A here-string is a STDIN channel and `_stdin_channel_texts` below
            # already reads it. Reading it here too would report the same merge
            # twice, and a doubled target is a doubled approval requirement on
            # one command (`bash <<< "gh pr merge 292"`, measured).
            if w.startswith("<<<"):
                skip = k + 1 if w == "<<<" else -1
                continue
            if k == skip:
                continue
            # A whole command line needs at least a head and a verb, so a word
            # with no whitespace in it can never be one — the same reasoning
            # `_publish_carriers` already applies to a quoted mention. Skipping
            # it is what keeps a 20000-argument line inside the hook budget.
            if not (" " in w or "\t" in w) or not _may_publish(w):
                continue
            out.extend(_publish_carriers(w, mentions=False))
            if w.startswith("--") and "=" in w:
                out.extend(_publish_carriers(w.partition("=")[2], mentions=False))
    for text in _stdin_channel_texts(raw_sub):
        out.extend(_publish_carriers(text))
    return out


def _reparses_stdin(opening_line: str) -> bool:
    """True when the command that opened a heredoc will EXECUTE the body."""
    toks = _tokens_with_offsets(opening_line)
    if toks is None:
        toks = _ws_tokens(opening_line)
    for text, _s, _e in toks:
        head = os.path.basename(text.strip("\"'"))
        if head in _CMD_HEADS:
            return False
        if head in _STDIN_REPARSE_HEADS:
            return True
    return False


def _runs_its_stdin(sub: str) -> bool:
    """True when *sub*, standing on the right of a `|`, EXECUTES what it reads.

    Two shapes, both measured executing a fake `gh` on PATH while the gate
    allowed the whole line (QA cycle 5, Class C):
      * a bare shell — `printf 'gh pr merge 291' | bash`, `… | sh`. A shell with
        no `-c` value and no script FILE operand reads its script from stdin.
      * `xargs` that names a shell — `… | xargs -I{} bash -c "{}"`. The merge
        text is xargs' INPUT and reaches the shell through the placeholder, so
        no argument of either half is ever the command.
    A consumer that merely READS the text (`| grep`, `| wc`, `| tee`, `| mail`)
    executes nothing and is not one of these, which is what keeps a pipeline
    that only inspects a mention benign.
    """
    toks = _tokens_with_offsets(sub)
    if toks is None:
        toks = _ws_tokens(sub)
    words = [t for t, _s, _e in toks]
    h = _head_index(words)
    if h >= len(words):
        return False
    head = os.path.basename(words[h].strip("\"'"))
    rest = words[h + 1:]
    if head == "xargs":
        return any(os.path.basename(w.strip("\"'")) in _STDIN_REPARSE_HEADS
                   for w in rest)
    if head not in _STDIN_REPARSE_HEADS:
        return False
    if _command_flag_value(rest) is not None:
        return False                    # `| bash -c "…"`: the script is the arg
    for w in rest:
        if not w.startswith("-"):
            return False                # a script FILE operand: stdin is data
    return True


def _find_publish_subcmds(cmd: str, _depth: int = 0) -> list[tuple[str, str]]:
    """Return EVERY (raw_sub, form) matching a publish pattern, in order.

    Every one, not just the first: a line chaining two merges is two merges, and
    gating only the head let the second through under the approval granted for
    the first. *form* is "gh", "push", "api" or "alias" and says which pattern
    matched, which is what makes a branch sentinel refusable on the API form
    alone and an alias definition refusable with its own reason.

    Processing order (FIX 5 → split → FIX 3+4 → pattern):
      1. Join backslash-newline continuations (FIX 5) so multi-line commands
         are not split at the wrong boundary.
      2. Split on unquoted shell separators (; && || | newline).
      3. Per sub-command, strip leading env-assignments, redirections, and
         grouping chars (FIX 3+4) — AFTER splitting so we never cross a real
         separator.
      4. Match patterns anchored at the start of the stripped sub-command.

    A publish keyword appearing only inside a quoted argument is NOT matched
    because the split step keeps quoted content intact.
    """
    body_cmd, heredocs = _split_heredocs(_join_continuations(cmd))
    found: list[tuple[str, str]] = []
    staged = _split_subcmds_sep(body_cmd)
    for idx, (raw_sub, _sep) in enumerate(staged):
        inners = _reparse_args(raw_sub)
        # The `|` channel: when THIS stage executes what it reads, the stage
        # feeding it is not printing text, it is writing a script.
        if idx and staged[idx - 1][1] == "|" and _runs_its_stdin(raw_sub):
            inners = inners + _publish_carriers(staged[idx - 1][0])
        before = len(found)
        if _depth < _MAX_REPARSE_DEPTH:
            for inner in inners:
                found.extend(_find_publish_subcmds(inner, _depth + 1))
        elif inners:
            # At the cap. Stopping the walk is a cost decision; ALLOWING what is
            # behind it is not one this gate gets to make, so the unresolved
            # re-parse is itself the finding. `_extract_pr_id` will read no
            # number off it and land on the unapprovable sentinel — deny, and
            # nothing an approval can name.
            found.append((raw_sub, "depth"))
        # FALL THROUGH, not `continue`. A re-parse that produced no finding is a
        # guess that did not pay off, and the old code still skipped the direct
        # match after it: one misread flag (`--norc` read as `-c`, so the command
        # string came back as the literal `-c`) DELETED the check instead of
        # falling back to it, and the merge behind it walked. The direct match now
        # runs whenever the re-parse found nothing, so a wrong guess can only cost
        # a wasted look. It is skipped when the re-parse DID find the merge,
        # because that is the same merge read twice.
        if len(found) > before:
            continue
        _raw_n, dec_n, view_n = _normalize_full(raw_sub, _cfg_dir_for(cmd, raw_sub))
        form = _is_publish_form(dec_n, view_n)
        if form:
            found.append((raw_sub, form))
    for opening, body in heredocs:
        if not _reparses_stdin(opening):
            continue                       # a body nothing executes is data
        if _depth < _MAX_REPARSE_DEPTH:
            found.extend(_find_publish_subcmds(body, _depth + 1))
        else:
            found.append((opening, "depth"))
    return found


def _extract_pr_id(matched_sub: str, cfg_dir: str | None = None) -> str:
    """Return the PR number string, or branch literal 'main'/'master'.

    *matched_sub* is the raw sub-command (pre-strip) returned by
    _find_publish_subcmd.  Strip leading prefixes before matching so that
    `FOO=1 git push origin main` still yields 'main'.

    The two forms are read for two different things, and swapping them is a bug
    either way: the PR NUMBER comes off the RAW form, where a quoted flag value
    is still one token (`-t "x 280" 281` merges 281, and flattening it approved
    280); the branch and API scopes come off the DECODED form, where
    `origin ma"in"` is `origin main`. A gh-merge line whose number the raw parse
    cannot read falls through to the 'unknown' sentinel, which is unapprovable —
    fail-closed, not a guess.
    """
    raw, dec, view = _normalize_full(matched_sub, cfg_dir)
    num = _gh_merge_pr_num(raw)
    if num:
        return num
    branch = _git_push_form(view)
    if branch:
        return branch
    api = _api_write_action(dec)
    if api is not None:
        return api
    return "unknown"


# -- v8 kernel journal (Phase 4, v8-kernel.md) --------------------------------
_KERNEL_RULE = "CODE.qa-merge-gate"


def _journal_deny(reason, payload=None, tool_use_id=None) -> None:
    """Mirror this refusal into the refusing process's journal.

    FAIL-OPEN by contract: every error is swallowed and the verdict this gate
    just reached is unchanged. A journal that cannot be written must never turn
    a deny into an allow. kernel_proc is loaded by PATH through importlib, not
    by name, so nothing on sys.path can shadow it.
    """
    try:
        import importlib.util
        import os as _os
        _path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "kernel_proc.py")
        _spec = importlib.util.spec_from_file_location("_kernel_proc_journal", _path)
        _kp = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_kp)
        _payload = payload if isinstance(payload, dict) else {}
        _kp.journal_deny(_KERNEL_RULE, reason,
                         tool_use_id if tool_use_id is not None else _payload.get("tool_use_id"),
                         _kp.resolve_pid(_payload))
    except Exception:
        pass


def _nudge(text: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": text,
        }
    }))


def main() -> int:
    # The flag is per INVOCATION, not per process. The hook runs one command per
    # process, so this is a no-op in production; it is what lets a test call
    # main() more than once without a previous merge leaving the crash policy
    # armed for a later non-merge command.
    global _PUBLISH_IDENTIFIED, _LAST_PAYLOAD
    _PUBLISH_IDENTIFIED = False
    _LAST_PAYLOAD = None
    # Parse stdin — if this fails we cannot know if it's a merge, so exit 0.
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    _LAST_PAYLOAD = data if isinstance(data, dict) else None

    try:
        tool_input = data.get("tool_input") or {}
        cmd = (tool_input.get("command") or "")
    except Exception:
        return 0

    # Fast path: no sub-command starts with a publish pattern → exit 0 silently.
    matches = _find_publish_subcmds(cmd)
    if not matches:
        return 0
    matched_sub = matches[0][0]

    # Positively identified as a merge action — from here on, a crash must fail
    # CLOSED (_guarded_main reads this flag and exits 2, not 0).
    _PUBLISH_IDENTIFIED = True
    # Fault injection for the crash-handler fixture, and for nothing else. It
    # needs BOTH the harness-only session marker gate_selftest._run_leg sets and
    # an OCTO_ override the fixture declares, so it is reachable only from the
    # selftest harness — and even if it were reachable, its ONLY effect is to
    # make this gate DENY, so it can never be an authorization path.
    if (os.environ.get("CLAUDE_SESSION_ID") == "__selftest__"
            and os.environ.get("OCTO_GATE_CRASH_SELFTEST") == "1"):
        raise RuntimeError("selftest fault injected after merge identification")
    # One entry per merge in the line. A chained line is gated as a whole: every
    # target must carry the same operator approval, so an approval for one PR can
    # never ride a second merge appended after it.
    targets = [(_extract_pr_id(sub_raw, _cfg_dir_for(cmd, sub_raw)), form)
               for sub_raw, form in matches]
    pr_id = targets[0][0]

    # ── Repo scope: only PROTECTED repos are gated ────────────────────────────
    try:
        protected = _is_protected_target(cmd, matched_sub, data.get("cwd") or "")
    except Exception:
        protected = None  # unresolvable → keep gating (fail-closed)
    if protected is False:
        _nudge(
            "✓ QA gate: publish targets a non-protected repo (repo-scope) — ungated. "
            "Protected set: the brain + company/config/protected-repos.json."
        )
        return 0

    # ── Sentinels are not identifiers, so they are not approvable ────────────
    # "unknown" means the parse found no PR number, and on the API forms a bare
    # branch name is whatever the URL happened to carry. Both used to be exportable
    # as OCTO_MERGE_APPROVE (the deny text even told the operator to), which turned
    # one approval into a pass for every URL, branch and GraphQL merge form.
    sentinels = [pid for pid, form in targets
                 if pid == "unknown" or (form == "api" and pid in ("main", "master"))]

    # ── The one channel: env, PR-scoped, agent-proof ─────────────────────────
    env_approve = os.environ.get("OCTO_MERGE_APPROVE", "").strip()
    qa_ok = os.environ.get("OCTO_QA_OK", "").strip() == "1"
    if any(form == "alias" for _pid, form in targets):
        print(
            "✗ QA GATE (fail-closed): this line DEFINES a gh or git alias that expands "
            "to a merge.\n  An alias is per-user, so it arms an ungated merge in every "
            "repo, and defining it\n  in the same line that uses it beats alias "
            "resolution (the config file is read\n  before it is written) — and "
            "`git -c alias.x=...` writes no config file at all.\n  No PR number exists "
            "yet, so no approval can scope it.\n  Operator: run the merge itself with "
            "OCTO_MERGE_APPROVE=<pr> instead of aliasing it.",
            file=sys.stderr,
        )
        _journal_deny("alias definition expanding to a merge blocked", data)
        return 2
    if any(form == "depth" for _pid, form in targets):
        print(
            "✗ QA GATE (fail-closed): this line nests shells deeper than the gate "
            f"re-parses ({_MAX_REPARSE_DEPTH} levels).\n  What runs at the bottom is "
            "unreadable from here, and 'I stopped looking' is not 'there is nothing\n"
            "  there' — allowing it made four nested `bash -c` a total bypass while "
            "three denied.\n  No PR number is readable, so no approval can scope it.\n"
            "  Operator: run the merge itself with OCTO_MERGE_APPROVE=<pr>, not "
            "through nested shells.",
            file=sys.stderr,
        )
        _journal_deny("re-parse depth cap reached with a shell still to read: blocked", data)
        return 2
    if sentinels:
        _journal_deny(f"merge of sentinel {sentinels[0]!r} blocked: not an identifier", data)
        print(
            f"✗ QA GATE (fail-closed): this line merges {sentinels[0]!r}, which is a "
            f"sentinel, not\n  an identifier: no OCTO_MERGE_APPROVE value can approve it "
            f"(setting it to that\n  literal would approve every merge that parses the "
            f"same way).\n  Operator: re-run with an explicit PR number and export "
            f"OCTO_MERGE_APPROVE=<that number>.",
            file=sys.stderr,
        )
        return 2
    mismatched = [pid for pid, _form in targets if pid != env_approve]
    if env_approve and not mismatched:
        # v7 phase 3: the operator's approval is necessary, not sufficient. An
        # independent QA verdict must exist as a HARNESS-written receipt for this
        # PR (r__subagent-stop__qa-receipt.py), re-read from the agent transcript.
        # "QA approved" typed by the main loop is not a receipt. OCTO_QA_OK=1 waives
        # THIS receipt only (bootstrap, or a docs-only PR), never the PR-scoped
        # approval above: it is read only inside this matched-PR branch.
        if not qa_ok:
            try:
                sys.path.insert(0, str(Path(__file__).resolve().parent))
                import receipt_ledger
                qa = receipt_ledger.qa_pass_for(pr_id, str(data.get("session_id") or ""), str(data.get("transcript_path") or ""))
            except Exception:
                qa = None
            if qa is None:
                print(
                    f"✗ QA GATE (fail-closed): PR #{pr_id} is operator-approved but carries NO QA "
                    f"receipt.\n  v7: run an independent QA subagent (judgment tier) on the PR and "
                    f"have it end with\n    QA-VERDICT: PASS\n    QA-SCOPE: PR #{pr_id}\n  The "
                    f"SubagentStop hook records the verdict; the ledger line is re-read from the "
                    f"agent transcript.\n  Explicit operator bypass of the receipt: "
                    f"OCTO_QA_OK=1 (logged), which still needs OCTO_MERGE_APPROVE={pr_id}.",
                    file=sys.stderr,
                )
                _journal_deny(f"merge of PR #{pr_id} blocked: operator-approved but no QA receipt", data)
                return 2
            _nudge(f"✓ QA gate: QA receipt for PR #{pr_id} ({qa.get('agent_type') or 'subagent'}, {qa.get('ts', '')}).")
        else:
            _nudge(
                f"⚠ QA gate: OCTO_QA_OK waived the QA receipt for PR #{pr_id} "
                f"(receipt waiver, discouraged, logged). The PR-scoped "
                f"OCTO_MERGE_APPROVE={pr_id} still authorized this merge."
            )
        _nudge(
            f"✓ QA gate: operator-approved PR #{pr_id} via OCTO_MERGE_APPROVE "
            f"(env, agent-proof); {len(targets)} merge sub-command(s), all on that PR."
        )
        return 0

    # ── (removed) file channel: merge-approvals.json is agent-forgeable, so it
    #    is NOT an authorizer. The agent owns its process env and can strip the
    #    agent-shell markers or pass --i-am-the-operator to write that file, which
    #    made it a self-approval route. Only the harness env below is agent-proof.

    # ── OCTO_QA_OK is NOT an authorizer ───────────────────────────────────────
    # It waives the QA receipt for the PR named in OCTO_MERGE_APPROVE and nothing
    # else. As a blanket it let a merge of 280 through while the operator had
    # approved 279, arming auto-merge on the wrong number.
    if qa_ok:
        scoped = f"OCTO_MERGE_APPROVE={env_approve}" if env_approve else "OCTO_MERGE_APPROVE unset"
        _journal_deny("OCTO_QA_OK waives the QA receipt only; approval missing or "
                      "scoped to another PR", data)
        print(
            f"✗ QA GATE (fail-closed): OCTO_QA_OK=1 waives the QA receipt only, not the\n"
            f"  approval. This command merges {', '.join(pid for pid, _f in targets)}, "
            f"but {scoped}.\n"
            f"  Operator: export OCTO_MERGE_APPROVE={pr_id} in your shell, then re-run.",
            file=sys.stderr,
        )
        return 2

    # ── BLOCK — fail-closed ───────────────────────────────────────────────────
    label = f"PR #{pr_id}" if pr_id not in ("main", "master") else f"branch '{pr_id}'"
    if len(targets) > 1:
        label += f" (+{len(targets) - 1} more merge sub-command(s) in the same line)"
    print(
        f"✗ QA GATE (fail-closed): merge of {label} needs operator approval.\n"
        f"  Operator: export OCTO_MERGE_APPROVE={pr_id} in your shell (env, agent-proof),\n"
        f"  then re-run the merge. The file channel (octo-dim approve-merge) is an audit\n"
        f"  log, not a gate pass: the agent can forge it, so only the harness env counts.\n"
        f"  QA (independent reviewer) must have passed first before granting approval.\n"
        f"  Operator directive 2026-06-01: the gate is the agent's approval, not just green CI.",
        file=sys.stderr,
    )
    _journal_deny(f"merge of {label} blocked: no operator approval in OCTO_MERGE_APPROVE", data)
    return 2


def _selftest() -> int:
    import gate_selftest
    argv = sys.argv
    fixture = argv[argv.index("--selftest") + 1] if len(argv) > argv.index("--selftest") + 1 \
        else "registry/fixtures/CODE.qa-merge-gate"
    return gate_selftest.run_gate_selftest(__file__, fixture)


def _guarded_main() -> int:
    """main() with the crash policy. A FUNCTION, not an inline __main__ block:
    the branch that decides fail-open vs fail-closed on a crash is the one branch
    an agent most benefits from breaking, and code that cannot be called cannot
    be tested — mutating it was invisible to the whole suite.

    Fail-open ONLY while we cannot know this is a merge; once a publish/merge
    sub-command was positively identified, a crash exits 2, because any exception
    after identification would otherwise silently open the gate.
    """
    try:
        return main()
    except Exception:
        if _PUBLISH_IDENTIFIED:
            print(
                "✗ QA GATE (fail-closed): gate crashed AFTER a merge/publish path "
                "was identified — blocking instead of failing open.",
                file=sys.stderr,
            )
            _journal_deny("gate crashed after merge identification: blocked",
                          _LAST_PAYLOAD)
            return 2
        return 0  # fail-open for unexpected crashes on non-merge paths


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    # The guard only covers catastrophic errors; it must NOT swallow a
    # deliberate exit(2) block, which is why main() returns codes rather than
    # raising SystemExit.
    sys.exit(_guarded_main())
