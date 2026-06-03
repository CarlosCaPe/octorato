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

If shell indirection (`bash -c "..."`, `eval`) makes the real command opaque, a fail-closed gate correctly blocks until a human grants the env-var approval (see [[agent-proof-approval-gate]]).

## Residual Risk

Shell indirection still evades string-based detection:

```bash
bash -c "gh pr merge 96"     # sub-command content is inside a string literal
$(echo gh pr merge 96)       # command substitution
```

This is accepted. The string-matching layer identifies the action; the env-var layer authorizes it. The env channel is immune to indirection (see [[agent-proof-approval-gate]]).

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
