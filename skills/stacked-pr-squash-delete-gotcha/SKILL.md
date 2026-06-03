---
name: stacked-pr-squash-delete-gotcha
description: Recover from and prevent stacked-PR breakage caused by squash-merge + auto-delete-branch on the base PR. Use when working with stacked branches or any PR whose base branch is another PR's head.
metadata:
  type: lesson-learned
  status: draft
  captured: 2026-06-02
  origin: session-learn-extractor (manual /learn)
---

# Stacked PR + Squash-Merge + Delete-Branch Gotcha

## What breaks and why

Given:

```
main
 └── branch-A  ← PR A (base: main)
      └── branch-B  ← PR B (base: branch-A)
```

When PR A is merged with **squash + delete-branch**:

1. `branch-A` is deleted from the remote.
2. GitHub **auto-closes PR B** because its base branch no longer exists. A closed PR cannot be retargeted.
3. `branch-B` still contains the original (un-squashed) commits from A. When you push `branch-B` against `main` it now conflicts on those commits — they differ from the squash commit that landed.

## Recovery

### Step 1 — Rebase B onto main, dropping A's original commits

```bash
# Identify the tip of branch-A before it was deleted (from reflog or git log on branch-B)
A_TIP=$(git log --format="%H" branch-B | grep -m1 "$(git log --oneline origin/main | head -1 | cut -c1-7)")
# Better: use the commit SHA you noted before the merge, or:
A_TIP=$(git merge-base branch-B origin/main)   # last common ancestor = A's divergence point

git rebase --onto origin/main $A_TIP branch-B
# This replays only B's own commits on top of current main, skipping A's commits.
```

If you know the exact SHA of branch-A's tip before it was squash-merged:

```bash
git rebase --onto origin/main <A-tip-sha> branch-B
```

### Step 2 — Force-push the rebased branch

```bash
git push origin branch-B --force-with-lease
```

### Step 3 — Open a fresh PR

The auto-closed PR cannot be reopened to a different base. Open a new PR:

```bash
gh pr create --base main --head branch-B --title "..." --body "..."
```

Note: the original PR's comments/review history are lost. Link to the old PR in the new description for audit purposes.

## Prevention

| Rule | Why |
|---|---|
| Before merging a base PR, retarget all stacked PRs to `main` first | Prevents auto-close |
| Don't use `--delete-branch` (or auto-delete) when stacked PRs exist | Keeps base branch alive until dependents are merged |
| Use merge commits (not squash) for base PRs with stacked children | Avoids SHA divergence; B's commits still apply cleanly |

### Checklist before merging PR A

```bash
# Find any PRs that target branch-A
gh pr list --base branch-A --state open
# If any: retarget them first
gh pr edit <B-number> --base main
# Then merge A
gh pr merge <A-number> --squash
```

## Squash-merge silent contamination

Even after rebase, verify that A's commit did not ride along into B silently. A `git rebase --onto` replays commits **after** `$A_TIP` — but if `$A_TIP` was wrong (off by one), one of A's commits can sneak in. After rebasing, always check:

```bash
git log origin/main..branch-B --oneline   # should show ONLY B's commits
```

And after merging B, grep the built artifact for any artifact that A introduced, to confirm it came from A's squash commit, not a duplicated commit from B.

## When to Use

- Any workflow with stacked branches (PR B based on PR A's branch, not on main).
- Repos with auto-delete-branch enabled after merge.
- Squash-merge-only repo policies.

## See also

- [[ado-pr-merge-via-api]] — ADO-specific stacked PR and merge sequencing
- [[backward-compatible-schema-changes]] — another pattern where ordering of dependent changes matters
- [[pre-merge-qa-gate]] — QA gate that should catch dependency order before merge
