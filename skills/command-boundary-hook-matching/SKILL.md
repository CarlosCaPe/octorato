---
name: command-boundary-hook-matching
description: Pattern-match what a Bash command actually does in a PreToolUse hook without false-firing on mentions inside quoted args, commit messages, or echo strings. Use when building any hook that decides based on command semantics.
metadata:
  type: lesson-learned
  status: draft
  captured: 2026-06-02
  origin: session-learn-extractor (manual /learn)
---

# Command-Boundary Hook Matching

## Problem

A naive `"gh pr merge" in command` check fires on:

```bash
git commit -m "do not run gh pr merge 96 yet"   # mention in commit message
echo "about to run gh pr merge"                  # echo
for pr in 95 96; do gh pr merge $pr; done        # loop — fires twice, wrong context
```

None of these are the real invocation you want to intercept. The hook either over-fires (false positives trigger unnecessary blocks) or under-fires (quoted indirection evades detection).

## Fix — Quote-Aware Sub-Command Splitter

Split the raw command string on **unquoted** shell separators only, then anchor the pattern at the **start** of each sub-command.

### Step 1 — Join continuations

```python
command = command.replace("\\\n", " ")
```

### Step 2 — Quote-aware split on unquoted separators

Separators: `;` `&&` `||` `|` `\n` and grouping `(` `)` `{` `}`.

```python
import re

def _split_subcmds(cmd: str) -> list[str]:
    parts, buf, depth, in_sq, in_dq = [], [], 0, False, False
    i = 0
    while i < len(cmd):
        c = cmd[i]
        if in_sq:
            buf.append(c)
            if c == "'":
                in_sq = False
        elif in_dq:
            buf.append(c)
            if c == '"' and (i == 0 or cmd[i-1] != '\\'):
                in_dq = False
        elif c == "'":
            in_sq = True; buf.append(c)
        elif c == '"':
            in_dq = True; buf.append(c)
        elif c in '({':
            depth += 1; buf.append(c)
        elif c in ')}':
            depth -= 1; buf.append(c)
        elif depth == 0 and c in ';\n|':
            # handle && and ||
            if c == '|' and i + 1 < len(cmd) and cmd[i+1] == '|':
                parts.append(''.join(buf).strip()); buf = []; i += 1
            elif c == '|':
                # check for && look-ahead not needed; single | is also a separator
                parts.append(''.join(buf).strip()); buf = []
            else:
                parts.append(''.join(buf).strip()); buf = []
        elif depth == 0 and cmd[i:i+2] == '&&':
            parts.append(''.join(buf).strip()); buf = []; i += 1
        else:
            buf.append(c)
        i += 1
    if buf:
        parts.append(''.join(buf).strip())
    return [p for p in parts if p]
```

### Step 3 — Strip leading env assignments and redirections

```python
_STRIP = re.compile(
    r'^(?:'
    r'[A-Z_][A-Z0-9_]*=[^\s]*\s+'   # VAR=val
    r'|>[^\s]+\s+'                    # >file
    r'|2>[^\s]+\s+'                   # 2>file
    r')*'
)

def _strip_prefix(sub: str) -> str:
    return _STRIP.sub('', sub)
```

### Step 4 — Anchored pattern match

```python
_PAT_MERGE = re.compile(r'^\s*gh\s+pr\s+merge\b')

def is_merge_command(command: str) -> tuple[bool, str | None]:
    for sub in _split_subcmds(command):
        clean = _strip_prefix(sub)
        if _PAT_MERGE.match(clean):
            # extract PR number
            m = re.search(r'\bgh\s+pr\s+merge\s+(\d+)', clean)
            return True, m.group(1) if m else None
    return False, None
```

`^\s*gh\s+pr\s+merge\b` anchored at the sub-command start ensures it cannot match mid-string inside a quoted arg.

## Fail-Open vs Fail-Closed

| Hook type | On parse error / ambiguity |
|---|---|
| **Context-injection** (informational) | FAIL-OPEN — skip, never block |
| **Gate/block** (authorization) | FAIL-CLOSED — treat ambiguous = not authorized, block |

If shell indirection makes the real command opaque, a fail-closed gate correctly blocks until a human grants the env-var approval (see [[agent-proof-approval-gate]]).

Two rules keep the anchor honest once you have it:

- Match the verb on **decoded** tokens. `gh "pr" merge 291` is the same command as `gh pr merge 291`, and a raw-string matcher sees neither. Decoding does not re-match a quoted mention: a whole-token quote stays ONE token.
- Recurse into a head that **re-parses** its string argument (`bash -c`, `sh -lc`, `eval`, `ssh host`, `script -qc`, a shell reading a heredoc); never into one that does not (`git commit -m`, `echo`, `cat <<EOF`). Quoting is not the discriminator; re-parsing is.
- Decide re-parsing by the **head**, never by a list of channels. `-c`, `--command`, stdin, `-o RemoteCommand=` is an enumeration, and an enumeration of channels loses to the next channel the same way an enumeration of verbs loses to the next verb: `env -S`, `--split-string=`, `watch`, a bare `| bash` and `git -c core.sshCommand=` all arrived in ONE review cycle. Invert it — on a head that is neither a command head nor one whose arguments are DATA, every argument that parses as a whole command line is a command that wrapper runs — and carry the enumeration on the head dimension instead, where the members are finite, famous, and fail as a loud over-fire rather than a silent allow.
- Three CHANNELS execute a span of the line regardless of the head, so read them before you look at the head at all: `$(…)` and backticks, `<(…)`/`>(…)`, and a `|` into a stage that executes its stdin. When you close one member of that class, enumerate the others in the same commit — closing `<(…)` and leaving `$(…)` open for two cycles is what this rule is made of.
- QUOTING has FOUR spellings and a decoder that knows three of them is a matcher with a hole: `'…'`, `"…"`, `\x`, and the two `$`-prefixed forms `$'…'` (ANSI-C, where `$'\x6derge'` is the word `merge`) and `$"…"` (locale). All four are resolved by the shell before the program runs, so all four belong in the decoder. Cycle 7 measured twelve spellings of the last two walking a gate that handled the first three — including the one the fix that added decoding had introduced itself, `git push origin $'main'`, where the decoder turned `$'main'` into `$main` and the verb path read it as an expansion it had declared out of scope. A decoder that half-decodes can OPEN a spelling while closing another.
- ADJACENCY is not the command. `gh pr merge` and `git push` are verbs, not fixed positions: every real CLI accepts its own global options between the head and the verb, and the tool's docs are the enumeration (`gh pr -R owner/repo merge 288` is gh's own documented spelling; `git --no-pager push origin main` runs). Skip those options WITH their values, from an enumerated list, and never "any word starting with a dash" — a general dash-skip hands the verb a place to hide behind a crafted flag.
- Skip the option on TOKENS, with the tool's own attach grammar. Cycle 8's three bypasses all came from reading the parser's RULE and noticing it is not the tool's rule, never from inventing a spelling. A `\S+` value matched against a form flattened by joining decoded tokens with spaces cannot survive a value that CONTAINS whitespace: `git -c 'core.pager=less -F' push origin main` pushed for real while `git -c user.name=QA push origin main` denied, and the difference was the space. The same regex knew `-R x` and `-R=x` but not pflag's glued `-Rvalue`, which the tool accepts. Write each tool's grammar down once — git's two shorthands read the next argv and reject an attached value, pflag glues, `=`-joins or takes the next word and lets the first value-taking letter of a cluster swallow the rest — instead of matching a shape and hoping the values end where whitespace does. The same `\S+` reading usually also decides SCOPE somewhere (which repo, which directory), and there a misread costs an ALLOW rather than a miss.
- Model the SUBCOMMAND LOOKUP, not the global options. Every enumeration answers a question, and the question has to be "which words can appear before the verb and still let the verb dispatch", not "which globals exist". cobra strips flags to find a subcommand, and at the parent level it does not know the child's flags, so those get stripped there too: `gh pr --squash=true merge 999999` reaches the PR lookup on gh 2.88.1, which means the merge verb ran, while `gh pr --squash merge 999999` does not, because the bare flag ate `merge` as its value. `gh pr --body x merge 999999` DOES run, because the word it ate was `x`. A model that enumerates only globals is accurate about everything it lists and blind to the class next door. The rule is short enough to write down instead: a token carrying its own value (`--name=value`, `-xvalue`, `-x=value`) consumes nothing, a bare one consumes the next word, and the verb is the first positional left. Keep BOTH outcomes when you cannot know which, so no plausible parse hides the verb; the cost is a deny on a line the tool refuses to run anyway.
- A word-level decoder must be measured against the shell at the BYTE level, per escape, not spot-checked. `\c` folds with `x & 0x1f` and a plausible-looking `toupper(x) ^ 0x40` agrees on every LETTER, so a letter-only check passes both and the difference only shows on punctuation and digits. It mattered because `x & 0x1f` reaches NUL for four characters and the wrong formula reaches it for one, so `$'pr\c xx'` was the word `pr` to the shell and something else to the gate. When you close a truncation class, enumerate the CHARACTERS that reach the truncating value, not the escape FORMS that can spell them.
- Test the CONVERSE of a decoder claim that is true. "This cannot manufacture a word the shell would not produce" was true and never implied the other direction: a word the shell TRUNCATES and the decoder does not. A shell word is a C string, so `$'pr\x00xx'` is the word `pr` and four spellings walked a gate whose decoder kept the bytes after the NUL — through the hex, octal, control and unicode escapes alike, which is why the fix truncates the body rather than the one escape that was measured.

## Residual Risk

What string matching still cannot see. The canonical list is **eleven** residuals, kept in full in `scripts/qa-merge-gate.py`'s header and summarized in [[agent-proof-approval-gate]]. The three lines below are residuals 1 and 2 of that list, the two that are purely a parsing limit.

```bash
X="pr merge"; gh $X 291      # the verb itself comes from an expansion
$(echo "gh pr merge 96")     # the verb is inside a QUOTED string the sub echoes
./deploy.sh                  # the command lives in a file
```

Read the middle line precisely, because its literal twin is NOT a residual any more: `$(echo gh pr merge 96)` denies, and so do `echo $(gh pr merge 291)`, `x=$(…)` and the backtick spelling. A command substitution is a CHANNEL whose contents are re-matched, exactly like the `<(…)` closed a cycle earlier; what stays open is the verb arriving from an EXPANSION, which is a different thing wearing the same parentheses.

Two more are parsing-layer and were added by the cycle-4 fixes, so they belong here too: a program whose arguments are DATA (`grep`, `psql`, `gcc`, `echo`, `awk`) is exempt from the unnamed-wrapper argument reading, anchored on the HEAD word only, so an unlisted counter reached through `xargs` still over-fires and a wrapper deliberately NAMED `grep` escapes (the `find -exec` half of this sentence was a stale claim, re-measured ALLOW in cycle 7); and parse TIME on an adversarially long line, where a hook killed at its budget writes no stdout and the harness reads that as ALLOW.

Three flag-parsing rules earned the same way, each measured executing the real command through a fake binary on PATH:

- A shell keeps parsing OPTIONS after `-c`. The command string is the first NON-option word, and `--` ends option parsing — `bash -c -- "…"` and `bash -c -e "…"` are not `bash -c "--"`.
- `--command=X` is the same flag as `--command X`. Match the name before the `=`.
- The command HEAD is a POSITION, not "any word in the line". Testing every word against a list of safe heads makes any wrapper carrying a path or a user named `git` a total bypass: `flock /var/lock/git -c "…"`, `sudo -u git bash -c "…"`.

An opaque HEAD is closable (try the remainder against every head you know, and deny if the remainder is the action). An opaque VERB is not, without denying legitimate lines like `docs='gh pr merge'; echo $docs`. The string-matching layer identifies the action; the env-var layer authorizes it, and the env channel is immune to indirection (see [[agent-proof-approval-gate]]).

## When to Use

- Any PreToolUse hook that decides based on what a Bash command does.
- Gates on `git push --force`, `wrangler deploy`, `psql ... DROP`, etc.
- Logging/telemetry hooks that want to capture only real invocations.

## Reference Implementation

`~/.claude/scripts/qa-merge-gate.py` — `_split_subcmds` + `_strip_prefix` + anchored `_PAT_MERGE` / `_PAT_DELETE`.

## See also

- [[agent-proof-approval-gate]] — the authorization layer that complements this parsing layer
- [[dry-run-gate-pattern]] — preview-before-execute for destructive ops
- [[hook-profile-gating]] — profile-based hook activation
