---
description: Weekly ritual — review the week's accumulated changes on the `test` integration branch and promote them to `master` (the curated, public canonical).
argument-hint: (no args) — runs the review + promotion flow
allowed-tools: Bash, Read
---

# /promote-test — weekly test → master promotion

Octorato uses a **staged-promotion** workflow:

- **`test`** = the integration / contribution branch. Contributors open PRs
  against it; bot-authored skills and the operator's mid-week work land here.
  Anyone can critique and iterate freely on `test`.
- **`master`** = the curated, public canonical. **Only updated by this weekly
  promotion.** Protected (status checks + linear history).
- **Content** (blog / news / metrics on `dataqbs_IA`) is the exception — it
  ships to its own `master` daily for SEO freshness. This command is about the
  **brain** (`octorato`): skills, agents, rules, docs.

## What this does

1. **Sync local brain → `test`.** Push any uncommitted/local skill additions
   from `~/.claude` (the operator's working copy) onto the `test` branch via the
   `~/dataqbs-local-cron/brain-test-worktree`, so the week's work is staged.
2. **Show the diff** `master…test` — every skill / agent / rule / doc that would
   be promoted. Group by type so the operator can scan in ~1 min.
3. **Run the gates** on `test`: `check-generic.py` (no client leaks),
   `brain-stats.py` + `check-stats-drift.py` (floors truthful), connectome
   rebuild clean.
4. **Open a PR** `test → master` titled `promote: week of <date>` with the diff
   summary as the body. The operator reviews + merges (or it auto-merges once
   the protected-branch checks are green).

## Steps (run these)

```bash
# 1. Refresh the test worktree + pull any contributor PRs already merged to test
cd ~/dataqbs-local-cron/brain-test-worktree
git fetch origin --quiet && git reset --hard origin/test --quiet

# 2. Sync the operator's local brain skills/agents/docs onto test
#    (copy new/changed skill dirs from ~/.claude that aren't yet on test)
rsync -a --exclude='.git' --exclude='knowledge/github-trending/20*' \
  ~/.claude/skills/ ./skills/
rsync -a --exclude='.git' ~/.claude/agents/ ./agents/
cp ~/.claude/README.md ~/.claude/MEMORY.md ./ 2>/dev/null || true
git add -A
if [ -n "$(git status --porcelain)" ]; then
  git -c user.name="Carlos Carrillo" -c user.email="carlos.carrillo@dataqbs.com" \
    commit -m "stage: week of $(date -u +%F) — local brain work onto test"
  git push origin HEAD:test
fi

# 3. Show what would be promoted
echo "=== master…test diff (what promotion publishes) ==="
git fetch origin master --quiet
git log origin/master..origin/test --oneline | cat
git diff --stat origin/master..origin/test | tail -30

# 4. Gates
python3 ~/.claude/scripts/check-generic.py --staged --quiet && echo "✓ generic clean"
python3 ~/.claude/scripts/check-stats-drift.py

# 5. Open the promotion PR (operator reviews + merges)
gh pr create --repo CarlosCaPe/octorato --base master --head test \
  --title "promote: week of $(date -u +%F)" \
  --body "Weekly test→master promotion. Diff above. Gates: generic ✓, stats-drift ✓." \
  2>&1 | tail -2 || echo "(PR may already exist — check: gh pr list --repo CarlosCaPe/octorato --base master)"
```

## Notes

- **Contributors:** open PRs against `test`. See CONTRIBUTING.md.
- **Cadence:** weekly is the default. Run ad-hoc whenever `test` has reviewed,
  ready work worth publishing.
- **Rollback:** if a promotion shipped something wrong, revert the merge commit
  on `master` and re-promote a fixed `test`.
- This keeps the daily discovery loop's output **staged + reviewable** instead
  of hitting the public canonical unreviewed — fewer master updates, each one
  deliberate.
