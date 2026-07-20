Reconcile the AI brain (~/.claude) with its remote in ONE race-safe command: integrate first (pull --rebase --autostash), then publish (push), retrying if a sibling machine pushed mid-flight. This is the CANONICAL daily sync per CLAUDE.md; prefer it over the manual /ai-pull then /ai-push dance.

## Steps: execute in order using Bash tool

### 1. Daily reflection (linked ritual)

/ai-sync and the `daily-reflection` skill are two halves of one ritual: the sync publishes the day's work, the reflection distils its lesson. If this session did substantive work and no reflection has run yet, run the `daily-reflection` skill FIRST (mistakes-first retro, distil the sharpest lesson to brain memory, then `python3 ~/.claude/scripts/memory_sync.py push`) so the lesson persists in the same beat that publishes the work. Skip only when the session was trivial (pure Q&A, nothing shipped) and say so in the report.

### 2. Run the sync runner

`$ARGUMENTS` is an optional commit message for any local changes the runner commits.

```bash
~/.local/bin/ai-sync "$ARGUMENTS"
```

If the thunk is missing (fresh machine), fall back to the tracked script directly:

```bash
python3 ~/.claude/scripts/ai_sync.py cycle "$ARGUMENTS"
```

The runner handles everything internally: rebase-pull, generic-content gate, secret scan, commit, push with retry on non-fast-forward, connectome regen, arm sync, and a closing brain_doctor pass. Do NOT wrap it with your own git pull/push.

### 3. Dimension safety (multi-session machines)

If another live session shares the ~/.claude working tree, broad staging is gated by the dimension hook. When the runner reports a staging denial, do not force it: commit your session's files by explicit pathspec from your own dimension worktree and re-run the sync. Never `git add -A` on the shared tree.

### 4. Report

Show: what was pulled (commits behind before/after), what was committed and pushed (or "nothing to commit"), arms synced, the brain_doctor verdict, and whether the daily reflection ran (name the memory it wrote) or why it was skipped. If the push was rejected by branch protection (GH006), follow the auto-PR fallback documented in /ai-push step 3b and report the PR URL instead.
