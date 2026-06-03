# Concurrent Sessions — Isolation Guide

## The problem

`~/.claude/` is a git working tree. When two Claude Code sessions run in the
same directory they share one index, one HEAD, and one set of uncommitted files.
This causes real data-churn collisions:

1. Session A creates files (new skill, edits to `CLAUDE.md`) but hasn't committed
   yet — the files sit uncommitted in the shared tree.
2. Session B runs its own commit flow with a broad `git add`. That stage captures
   **everything** dirty, including A's files.
3. B commits. A's work is now inside B's commit under B's unrelated message.
4. B resets and re-commits. A's changeset is now fragmented across the index,
   on a branch A never chose, none of it pushed.

Nothing is permanently lost, but the changeset is shredded and the shared HEAD is
unstable while B iterates. The root cause is no isolation boundary plus broad
staging plus two live writers on one index.

The awareness hook in `scripts/dimension-awareness-hook.py` **warns** when other
live sessions share the main tree, but it is fail-open — it never blocks a write.
**Warning alone is not isolation.** True isolation requires each session to run
in its own git worktree from the moment it launches.

## The fix: launch every session in its own dimension

Before opening a second (or third) terminal with `claude`, provision a worktree:

```bash
python3 ~/.claude/scripts/octo-dim.py start [--session-id <name>]
```

The command:
- resolves a session id (`CLAUDE_SESSION_ID` env → `--session-id` arg → `hostname-pid`)
- idempotently creates a git worktree at `~/.octorato/dim/<first-8-chars>/` on branch `dim/<first-8-chars>`
- registers the session in the blackboard (`connectome/sessions.json`)
- warns if other live sessions still share the main tree
- prints the exact command to start the session in that directory

Then follow the printed instruction:

```bash
cd ~/.octorato/dim/<short-id> && claude
```

**The agent cannot re-root itself.** Hooks are subprocesses; `chdir` inside a
subprocess does not affect the parent process's working directory. That is why
the operator must `cd` and launch `claude` from the worktree directory — before
the session starts, not after.

## Workflow summary

```
# Terminal 1 (already running — this is the main tree)
# Nothing changes here.

# Terminal 2 — before opening claude:
python3 ~/.claude/scripts/octo-dim.py start --session-id feat-x
#  → prints: cd ~/.octorato/dim/feat-x00 && claude
cd ~/.octorato/dim/feat-x00 && claude

# Work in T2 independently. Commit by explicit pathspec only (see rules below).
# When done, push the dim branch and open a PR back to master as usual.

# Cleanup after merge:
git -C ~/.claude worktree remove ~/.octorato/dim/feat-x00
git -C ~/.claude branch -d dim/feat-x00
python3 ~/.claude/scripts/octo-dim.py unregister --session-id feat-x
```

## Hard rules until everyone is isolated

Even with the worktree in place, follow these rules to avoid index collisions
with sessions that haven't isolated yet:

| Rule | Reason |
|------|--------|
| **Commit only by explicit pathspec** — never `git add -A` or `git add .` | A broad add in one session swallows the other session's uncommitted files |
| **`git pull --ff-only`** to catch up with master | Merge commits on a shared dim branch create noise |
| **Treat unexpected files in `git status` as another dimension's work** — don't stage them | They belong to a neighbor session's uncommitted changeset |
| **Land via PR, not direct push to master** | Keeps the main branch stable while dimensions iterate |
| **`git worktree remove` after merge** | Stale checkouts accumulate and confuse `git worktree list` |

## Reconciling back to master

Work in a dimension is a normal feature branch. When ready:

```bash
# Inside the dimension worktree:
git push -u origin dim/<short-id>
gh pr create --base master --title "..."
# Operator approves; auto-merge or squash as usual.
```

The awareness hook warns about the other session's dimension — that is expected
and correct. The warnings stop once all sessions have isolated worktrees.

## Related

- `skills/session-isolation/SKILL.md` — the full collision narrative, octopus
  morphology framing, and recovery steps if a collision already happened.
- `scripts/octo-dim.py` — the dimension registry CLI (`start`, `list`, `prune`,
  `unregister`, `worktree-init`, `approve-merge`, …).
- `scripts/dimension-awareness-hook.py` — the warn-only hook that fires on every
  write when other live sessions share the main tree.
- Anthropic native: `claude --worktree <name>` (same pattern, built into the CLI).
