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

## Residual Risk

What string matching still cannot see. The canonical list is **nine** residuals, kept in full in `scripts/qa-merge-gate.py`'s header and summarized in [[agent-proof-approval-gate]]. The three lines below are residuals 1 and 2 of that list, the two that are purely a parsing limit.

```bash
X="pr merge"; gh $X 291      # the verb itself comes from an expansion
$(echo "gh pr merge 96")     # the whole command inside one substitution
./deploy.sh                  # the command lives in a file
```

Two more are parsing-layer and were added by the cycle-4 fixes, so they belong here too: a program whose `-c` means COUNT or QUERY (`grep`, `psql`, `gcc`) is exempt from the unnamed-wrapper `-c` reading, anchored on the HEAD word only, so an unlisted counter reached through `find -exec` still over-fires and a wrapper deliberately NAMED `grep` escapes; and parse TIME on an adversarially long line, where a hook killed at its budget writes no stdout and the harness reads that as ALLOW.

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
