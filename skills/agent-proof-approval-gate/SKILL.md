---
name: agent-proof-approval-gate
description: Build a fail-closed PreToolUse gate for merge/deploy/destructive actions that the AI agent provably cannot self-bypass. Use when you need human-only override for a consequential action the agent orchestrates.
metadata:
  type: lesson-learned
  status: draft
  captured: 2026-06-02
  origin: session-learn-extractor (manual /learn)
---

# Agent-Proof Approval Gate

## Problem

A PreToolUse hook that blocks a destructive action (merge, deploy, delete) needs a human-only override. Naively you might check for an env var or a flag — but the agent can set those itself with an inline prefix (`APPROVE=1 gh pr merge 96`) or by writing a file. The gate must be unforgeable by the entity it constrains.

## Key Insight — Inline Env Never Reaches the Hook

A PreToolUse hook runs in the **harness process**, not in the shell that executes the agent's command. When the agent writes `VAR=1 cmd`, that assignment is scoped to the child shell that runs `cmd`; the hook fires before `cmd` even starts, in a separate environment. Therefore:

> **An env var set in the agent's command prefix is invisible to the hook.**

Only a human who runs `export OCTO_MERGE_APPROVE=96` in the real terminal session can set the hook's env. The agent cannot reach it.

## Design

### Primary channel — scoped env var (agent-proof)

```bash
# Human grants approval for a specific PR
export OCTO_MERGE_APPROVE=96      # must match the exact PR number being merged
```

The hook validates:
1. `OCTO_MERGE_APPROVE` is set.
2. Its value **equals** the PR number extracted from the command being intercepted (not `startswith`, not `in` — exact equality).
3. Optionally, a TTL: compare against the file-mtime of a stamp written when the var was set.

```python
import os, re, sys

def check_approval(pr_number: str) -> bool:
    approved = os.environ.get("OCTO_MERGE_APPROVE", "").strip()
    return approved == pr_number          # "96" != "95", "96x", " 96"

# In the hook body:
if not check_approval(detected_pr):
    print(f"[gate] BLOCKED — set OCTO_MERGE_APPROVE={detected_pr} to authorize.")
    sys.exit(1)   # non-zero exit blocks the tool call
```

### There is no safe secondary file channel (lesson, 2026-09-01)

An earlier design offered a TTL'd approval file (`octo-dim approve-merge 96`) as a convenience channel the gate honored on freshness. It was removed as a gate authorizer: a file the agent can write is a self-approval route. The agent owns its own process env, so it defeats any write-time agent-shell refusal two ways, `env -u CLAUDECODE python3 octo-dim approve-merge 96` (strip the markers) or an explicit `--i-am-the-operator` escape flag. No check inside a command the agent executes can prove the writer was the operator.

Only the harness env is a real boundary, because the agent's command-scoped env never becomes the hook's env. So the env channel is not merely "preferred", it is the ONLY authorizer. `octo-dim approve-merge` still writes a record, but as an operator audit log listed by `approvals`, never as a gate pass. When you are tempted to add a "convenient" file/flag/env-inside-the-agent channel to a gate the agent orchestrates, stop: if the agent can execute it, the agent can forge it.

## Scoping Rule — Never Blanket, Always Specific

The approved value must encode the **exact action**:

| Bad (blanket) | Good (scoped) |
|---|---|
| `OCTO_MERGE_APPROVE=yes` | `OCTO_MERGE_APPROVE=96` |
| `APPROVE_ALL=1` | `OCTO_DEPLOY_APPROVE=prod-2026-06-02` |

A stale `OCTO_MERGE_APPROVE=95` cannot authorize PR 96. This prevents approval replay.

## Identification and authorization fail differently

The env channel is immune to **forgery**, not to **evasion**, and conflating the two is how this gate got bypassed. Authorization is only consulted *after* the command has been identified as a merge, so a command shape the matcher never identifies never reaches the env check at all. An evasion is a total bypass, not a degraded authorization. Two jobs, two failure modes:

- Env channel for **authorization** (unforgeable: the agent's command-scoped env never becomes the hook's env).
- Command parsing for **identification** (best-effort; every ambiguity fails closed).

The identification half is therefore where the work is. Peel by **allowlist** and the wrapper you did not name is a total bypass: `env` and `command` were peeled, and `time gh pr merge 291`, `nice`, `nohup`, `timeout 30`, `stdbuf -o0`, `setsid`, `sudo -u x`, `exec`, `eval`, `xargs` and a leading `\gh` all walked through, each one actually invoking gh (measured 2026-09-08). Invert the default instead: drop leading tokens until one of them IS a command head you know how to read. An unrecognized leading token is suspicious, not trusted, and a wrapper's own value-taking options (`timeout N`, `nice -n 5`) need no special case because they are just more unrecognized tokens.

Identification also has to cover the API call *behind* each CLI verb, not only the verb. `gh pr merge --auto` was denied while `gh api graphql -f query='mutation{enablePullRequestAutoMerge(...)}'`, the exact call it makes, was allowed. And the target has to be resolved the way the tool resolves it: `gh` reads `-R`, then `GH_REPO`, then the cwd repo, so a gate that reads only `-R` and cwd ungates `GH_REPO=<protected> gh pr merge <n>` fired from an unrelated directory.

Match the verb words on **decoded** tokens, not on the raw string. One quote pair defeats a raw matcher completely: `gh "pr" merge 291`, `gh pr "merge" 291`, `git "push" origin main`, `git push origin ma"in"` and `gh api -X PUT .../pulls/291/me"rge"` all invoked the real tool while the anchor saw nothing (measured 2026-09-08). Decoding costs no over-fire, because a whole-token quoted *mention* is ONE token and one token can never supply the two words a verb needs after a head. Keep the raw form for reading argument VALUES (a PR number off `gh pr merge -t "x 280" 281` must still be 281) — the two needs are separable, and conflating them is what made the raw string look load-bearing.

Try the anchor at **every** command-head position in a sub-command, not the first. A benign head in front otherwise swallows the merge behind it (`git status & gh pr merge 291`). And treat `&` as a separator: it backgrounds what precedes it and starts a new command.

## The "forced trade" is not forced

A gate that stops at string matching concludes it must choose between catching `bash -c "gh pr merge 96"` and not re-matching `git commit -m "gh pr merge 96"`. That is false, and the distinguishing property is not quoting. It is whether the head **re-parses its string argument as a command**:

| Head | Re-parses? | Verdict |
|---|---|---|
| `bash -c`, `sh -lc`, `zsh -c`, `eval`, `ssh host`, `script -qc`, a shell reading a heredoc | yes | recurse into the argument, identify |
| `git commit -m`, `echo`, `cat > f <<EOF`, `python3 -` | no | the argument is data, leave it alone |

Recurse on the first set, never on the second, and you get both halves. The same rule fixes heredocs in the other direction: a heredoc BODY is data on stdin, so `cat > notes.md <<EOF ... EOF` must not match what the note SAYS, while `bash <<EOF ... EOF` must.

## Residual Risk

**ELEVEN residuals**, the canonical list; `scripts/qa-merge-gate.py`'s own header carries it in full and this is the summary. Each was measured on 2026-09-08 by feeding the payload on stdin (deny = exit 2). Counting matters: three separate surfaces used to quote three different numbers, which is how a residual stops being tracked.

```bash
# 1  the VERB comes from an expansion, not from text
X="pr merge"; gh $X 291 ; $(echo "gh pr merge 291") ; C="gh pr merge 291"; eval "$C"
#    cycle 7: ANSI-C and locale QUOTING left this residual. `$'gh'` used to be
#    listed here as closed and was closed only at the HEAD position; in every
#    other position `gh pr $'merge' 288`, `gh pr $'\x6derge' 288` and
#    `git push origin $'main'` walked. They are quoting, not expansion, and are
#    decoded in the tokenizer now.
# 2  the merge lives in a file the hook never reads
./deploy.sh
# 3  a non-shell runtime does the API call, or shells out from inside one
python3 -c "...requests.put(...)"
awk 'BEGIN{system("gh pr merge 291")}'      # measured executing; the argument is
                                            # a PROGRAM, not a command line
# 4  gh repo set-default, whose EFFECT on a later merge is unmeasured
# 5  a REPO-LOCAL git alias (only the user-global config is read)
# 6  GH_REPO / GH_HOST / GH_CONFIG_DIR arriving on a channel the hook cannot see
# 7  the v7 boundary: receipt files live under $HOME and the model can append
# 8  the two nested ALLOW-side enumerations, _NON_SHELL_C_HEADS < _INERT_ARG_HEADS:
#    a program NAMED grep/psql/gcc/echo/awk on the HEAD is exempt from the
#    unnamed-wrapper argument reading, and an unlisted counter reached through
#    `xargs` still over-fires. Cycle 8 named the DENY-side twin here: the
#    global-option sets decide which words may sit between a head and its verb,
#    and an option nobody listed is a MISS, not a loud over-fire
grep -c "gh pr merge 292" notes.md          # allowed, correctly
xargs grep -c "gh pr merge 292"             # denies: over-fire, head-anchored
find . -exec grep -c "…" {} \;               # cycle 7: re-measured ALLOW. This
                                            # line used to claim a deny; the
                                            # claim was stale, harmless in
                                            # direction, and untrue.
# 9  parse TIME: a crafted ~25 KB line of `$a -f` noise approaches the 5 s hook
#    budget, and a killed hook writes no stdout, which the harness reads as ALLOW
# 10 bash 5.3 funsubs ${ cmd; } / ${| cmd; }: unreachable on the installed bash
#    5.2, so no fixture pair can run them here (they deny today only as a
#    coincidence of the opaque-head reading, which is not coverage)
# 11 a pipe whose consumer executes stdin only after ANOTHER hop
echo "gh pr merge 291" | ssh host bash      # ssh itself executes nothing
```

Cycle 5 closed three classes and added residuals 10 and 11. Class A: `$(…)` and backticks are the SAME channel as the `<(…)` cycle 3 closed, and their contents were never re-matched — `cat <(gh pr merge 291)` denied while `echo $(gh pr merge 291)` allowed, both executing. Class B: the cycle-4 option walk skipped an option but not its VALUE, so `bash -c -o pipefail "…"` returned `pipefail` as the command. Class C is the architectural one: deny-by-default had been applied to bare-head peeling only, and the quoted-command path went back to an ENUMERATION OF CHANNELS, which lost to five new ones in a single cycle (`env -S`, `--split-string=`, `watch`, a bare `| bash`, `git -c core.sshCommand=`). The fence moved onto the HEAD — on a head that is neither a command head nor one whose arguments are DATA, every argument that parses as a whole publish command line is a command that wrapper runs — measured at 0 new denials on a 74-command read-only corpus and 0 on 400 real commands taken from this repo's own docs.

Cycle 7 returned FAIL with 22 spellings that pass the gate and execute a real merge against a fake binary on PATH, in two classes plus one regression this branch had introduced itself. The regression: `1f0ca89` moved verb matching onto decoded tokens to close `gh "pr" merge`, its decoder turned `$'main'` into `$main`, and `git push origin $'main'` went DENY on the commit before it and ALLOW on it — one spelling closed and another opened in the same change. Class 1 is that family: `$'…'` and `$"…"` are QUOTING, resolved by the shell before the program runs, so twelve spellings of the verb, the head, the branch and the API path walked (`gh pr $'\x6derge' 288`, the all-hex `$'\x67\x68' $'\x70\x72' $'\x6d\x65\x72\x67\x65' 288`, `curl -X $'PUT' …`). The hex row also defeated `_may_publish`, whose "sound by construction" held only for the alphabet its flatten table knew. Class 2 is ADJACENCY: the gh anchor required `gh pr merge` with nothing between the words and the git one admitted only `-C`/`-c`, so `gh pr -R owner/repo merge 288` — the spelling in gh's own docs — and `git --no-pager push origin main` walked. Both are closed by decoding quoting in the tokenizer and by skipping an ENUMERATED set of each tool's own global options with their values, never "any word starting with a dash".

Cycle 8 returned FAIL with three more, none of them a new spelling somebody dreamed up: all three came from reading the RULE the parser implements and noticing it is not the tool's rule. Class 3, the value-consumption grammar: cycle 7's skip was a regex whose value was `\S+`, matched against a form built by joining decoded tokens with spaces, so a value that CONTAINS whitespace became two words and the verb vanished behind them — `git -c 'core.pager=less -F' push origin main`, `git -c "user.name=Q A" push origin main` and the `-C` / `--git-dir` spellings over a spaced path all pushed for real to a local bare remote, while the same shape with no space in the value denied. Class 4, pflag's attached shorthand: `-Rvalue` is glued and the enumeration accepted only `-R x` and `-R=x`, so `gh -RCarlosCaPe/octorato pr merge 288` walked. Class 5, the converse of a claim that was TRUE: the ANSI-C decoder cannot manufacture a word bash would not produce, and nobody had tested a word bash TRUNCATES — a bash word is a C string, `$'pr\x00xx'` is the word `pr`, and keeping the bytes past the NUL let four spellings walk, two of them pushing for real. Fixed as grammar, not as spellings: both tools' global options are walked on TOKENS with the attach rules each one implements (git's two shorthands read the next argv and reject an attached value; pflag glues, `=`-joins or takes the next word, and in a cluster the first value-taking shorthand ends the token), and the decoder truncates its body at the first NUL exactly where bash does. The same `\S+` reading was fixed in the two places it also decided repo SCOPE (`-C` and `-R`) and in the git alias lookup, where a comment had worked around it by dropping the option instead of reading it. The first attempt re-quoted the decoded rendering so it could be read back as tokens and broke the git alias-DEFINITION patterns, which match on that same string: one class closed and another opened, this PR's signature pattern again, caught by the suite and replaced by handing the peel's own token view to every reader.

Cycle 9 returned FAIL with two total bypasses and corrected the framing on one of them. The first was LIVE in production, not a branch regression: cobra parses flags interspersed with positionals, so the `pr merge` subcommand's OWN flags can sit between the head and the verb and still dispatch. `gh pr --squash=true merge 999999` and eight siblings returned 0 from master, from the branch and from the installed hook, and gh 2.88.1 answers them with `GraphQL: Could not resolve to a PullRequest ... (repository.pullRequest)`, which only comes back after the merge verb ran. The model was accurate about everything it enumerated and enumerated the wrong SET: global options, when cobra also admits the subcommand's flags there. A tenth spelling nobody listed fell straight out of modelling the parser instead of extending the list, `gh pr --body x merge 999999`, which dispatches because the word the bare flag ate was `x` and not the verb. The gh side is now cobra's own positional rule with no flag list at all; only git keeps an enumeration, because git's parser is one. The second bypass was called pre-existing because it reproduces at the branch's own earlier tip, and that tip already carried the decoder in question: against MASTER it does not exist. `chr()` raises OverflowError at 0x80000000, the `\u`/`\U` branch caught only ValueError, and the crash landed inside identification, which runs BEFORE the flag `_guarded_main` reads to decide fail-open versus fail-closed. Master denies `gh pr merge 288 $'\U80000000'` with rc 2; the branch allowed it with rc 0 and empty stderr. So it was a regression the branch shipped, and identification now carries its own handler that DENIES with a named cause, because "I could not read this" is not "this is safe". Reading the decoder against bash at the BYTE level, rather than by spot check, then found three more live members of the NUL class cycle 8 had claimed closed: `\c` folds with `x & 0x1f`, not `toupper(x) ^ 0x40`, and the two agree on every letter and disagree everywhere else, so `$'pr\c xx'` is the word `pr` to bash while the decoder produced `pr\x60xx`. Cycle 8 had enumerated the escape FORMS and not the CHARACTERS that fold to NUL.

Residuals 8 and 9 arrived with the cycle-4 fixes, and both are stated rather than traded away. 8 is the price of ending an over-fire class that denied three ordinary read-only commands, and it is fenced to the HEAD word so a wrapper's path argument exempts nothing: `flock /var/lock/grep -c "gh pr merge 291"` still denies. 9 is bounded, not eliminated: the three quadratics measured this cycle went 39.7 s to 0.43 s (20000 benign words), 52.2 s to 0.7 s (8000 opaque tokens) and 9.2 s to 0.03 s (8000 heredoc openers) against a 5 s budget, while two shapes stay superlinear — a line alternating an opaque token with a write-marker flag (`git $a -f …`) sits near 3 s at 2500 pairs, and a 6000-line pasted script sits near 3 s because every line is its own sub-command.

The opaque-HEAD half of that first family IS closable, and closing it costs nothing: when the head is unresolvable (`$(echo gh)`, `${PATH:0:0}gh`, `$'gh'`, `$G`) the REMAINDER still carries the verb, so try the remainder against every head you know and deny if it is a merge whoever the head turns out to be.

Do not buy the rest by substituting same-line assignments everywhere: that also denies `docs='gh pr merge'; echo $docs`, which is a legitimate command. Over-fire is a security failure with extra steps — a gate people route around is off — so measure it against a corpus of real commands before and after every change, and write down what you did not close.

See [[command-boundary-hook-matching]] for the parsing half.

## When to Use

- Merging PRs that auto-deploy to production.
- Running destructive DB migrations.
- Any action where "the agent is doing the work but only the human should pull the trigger."

## Production writes (MANDATORY): no prod write without a per-destination operator approval

A remote production write is the same shape as a merge and gets the same treatment. `aws ssm send-command` carrying a host write, `wrangler deploy` / `secret put` / `kv key put|delete` / `pages deploy`, and the destructive AWS control-plane calls (`ec2 terminate-instances|stop-instances`, `iam put-role-policy|attach-role-policy|delete-*`, `secretsmanager put-secret-value|delete-secret`) are denied fail-closed unless the operator has approved **that specific destination** inside a short window. Orchestrator instructions passed to a builder sub-agent are not an authorization: they live in the agent's own context, so nothing outside the agent can check or record them, and three agents deploying on that basis in one session is exactly what produced the security alerts this rule exists for.

The destination is the instance id, the Worker name, or an agreed token. Approving the Worker never approves the instance, and a morning approval is dead by the afternoon (600 s window: an approval covers one operation, not a day).

Read-only stays untouched by design, and that is a hard requirement rather than a nicety: `describe-*`, `get-*`, `list-*`, an SSM payload that only runs `cat` / `journalctl` / `systemctl is-active|show`, and status `curl`s all pass silently. A gate that cries on a `describe-instances` gets switched off, and then it protects nothing.

Mechanism: `scripts/g__pretool-bash__prod-write.py` (Registry `SEC.prod-write-gate`), approvals via `OCTO_PROD_APPROVE=<destination>` (env, agent-proof) or `octo-dim.py approve-prod <destination>`, which refuses to run when it detects an agent shell.

## Reference Implementation

`~/.claude/scripts/qa-merge-gate.py`: full gate with the agent-proof env channel (`OCTO_MERGE_APPROVE`), the discouraged `OCTO_QA_OK`, which waives the QA receipt only, still requires `OCTO_MERGE_APPROVE` to name the same PR, and is scoped per COMMAND rather than "once" (nothing consumes it, so it keeps waiving while the shell keeps it exported), and command-boundary PR-number extraction. The forgeable file channel was removed (see the lesson above).

`~/.claude/scripts/g__pretool-bash__prod-write.py` is the production-write sibling: per-destination scoping, payload inspection for SSM and ssh, a read-first allowlist that keeps false positives at zero, and a crash path that denies once a prod channel is identified.

## Learned from OpenBot (CopilotKit)

Three transferable rules from the runtime gateway in https://github.com/CopilotKit/OpenBot (`server/src/computer/policy.ts`, `gateway.ts`), the closest public sibling of this gate:

1. **Dry-run before enforce.** Their policy engine ships a `dry-run` mode that decides and records against real traffic while letting everything through, so an operator reads the audit trail before a rule starts refusing anybody's work. Their phrasing: a governance feature nobody dares switch on is not a governance feature. Maps to our fail-open-with-waiver rollout stage; the lesson is to make that stage a first-class mode with its own decision log, not a temporary exception.
2. **Intent over mechanism.** A deny written against one tool name is bypassed by a sibling tool with the same effect: their canonical case is a refused click on Submit that succeeds anyway because the agent presses Enter in the form. Their policy context therefore carries the effect (`activate`, `type`, `read`, opening a page) alongside the tool name. When writing a gate pattern here, ask what other command produces the same effect and cover both.
3. **Resolve the target server-side.** Their gateway resolves what the agent is acting on from a snapshot the server itself fetched, never from the caller's own description; a gate that decides on an attacker-supplied label is decoration. Our equivalent: derive the destination from the command string itself (see [[command-boundary-hook-matching]]), never from what the agent claims in surrounding prose.

## See also

- [[command-boundary-hook-matching]]: parsing the command string safely to extract the action identity
- [[pre-merge-qa-gate]]: QA approval workflow that feeds into this gate
- [[dry-run-gate-pattern]]: sibling pattern for destructive ops (preview before execute)
- OpenBot gateway (https://github.com/CopilotKit/OpenBot): runtime CEL policy with deny-before-allow, audit-row-before-act, and refusals that name the rule
