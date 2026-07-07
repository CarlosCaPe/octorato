Reconcile the AI brain (~/.claude) with its remote in ONE race-safe command: integrate first (pull --rebase --autostash), then publish (push), retrying if a sibling machine pushed mid-flight. This is the CANONICAL daily sync per CLAUDE.md; prefer it over the manual /ai-pull then /ai-push dance.

## Steps: execute in order using Bash tool

### 1. Run the sync runner

`$ARGUMENTS` is an optional commit message for any local changes the runner commits.

```bash
~/.local/bin/ai-sync "$ARGUMENTS"
```

If the thunk is missing (fresh machine), fall back to the tracked script directly:

```bash
python3 ~/.claude/scripts/ai_sync.py cycle "$ARGUMENTS"
```

The runner handles everything internally: rebase-pull, generic-content gate, secret scan, commit, push with retry on non-fast-forward, connectome regen, arm sync, and a closing brain_doctor pass. Do NOT wrap it with your own git pull/push.

### 2. Dimension safety (multi-session machines)

If another live session shares the ~/.claude working tree, broad staging is gated by the dimension hook. When the runner reports a staging denial, do not force it: commit your session's files by explicit pathspec from your own dimension worktree and re-run the sync. Never `git add -A` on the shared tree.

### 3. Report

Show: what was pulled (commits behind before/after), what was committed and pushed (or "nothing to commit"), arms synced, and the brain_doctor verdict. If the push was rejected by branch protection (GH006), follow the auto-PR fallback documented in /ai-push step 3b and report the PR URL instead.
