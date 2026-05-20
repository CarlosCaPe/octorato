---
name: pr-first-on-auto-deploy-main
description: "On repos where pushing to main auto-deploys to production, default to PR-based workflow even for self-authored changes — PR adds the safety pass that a direct push skips"
metadata:
  short-description: "When main = prod deploy, never push directly — always PR, even for own changes"
---

# PR-First on Auto-Deploy `main`

## What

Some repositories are wired so that **any commit landing on `main` immediately
triggers a production deploy** — Cloudflare Pages, Vercel, Netlify, GitHub
Pages, Render, Railway, Fly.io, and many in-house GH Actions / GitLab CI
pipelines all use this pattern.

In that topology, `git push origin main` is not a version-control action.
**It is a production deploy.** Treat it that way.

## Why default to PR, even for your own changes

| What a PR adds that a direct push skips |
|---|
| A second look at the diff *after* you've stopped typing — the cheapest possible code review |
| Branch protection rules can require CI checks (lint, tests, security scans) to be green before merge |
| Dependabot, CodeQL, Codecov, etc. only post comments on PRs — not on direct pushes |
| The PR title + body becomes the audit trail. `git log` without a PR is "fix things" |
| If something goes wrong, "revert PR #N" is one click. "Revert commit abc123" is git surgery |
| Future-you can find the *why* of a change in the PR description; commit messages decay |

The direct push has exactly one upside: 30 seconds saved. That's a bad
trade against any of the above.

## When direct push to main is OK

- **Docs-only commits** that the operator approved verbatim (typo fix, README
  update). Even then, a 2-line PR is usually better.
- **Hotfixes the operator explicitly marked urgent** ("push directo a main",
  "no PR ahora", "skip review"). Record the directive in the commit message so
  the audit trail isn't blank.
- **Repos without auto-deploy on main**. Personal scratch repos, local-only
  clones, dotfile mirrors.
- **Repos where the operator has explicitly opted out** of PR-first (rare —
  ask first).

If none of the above applies → PR.

## Workflow (copy-paste-ready)

```bash
# 1. Branch off latest main
git fetch origin main
git checkout -b <type>/<short-description>

# 2. Edit + commit normally
git commit -m "type(scope): short description"

# 3. Push branch + open PR with body
git push -u origin <branch>
gh pr create --base main --head <branch> \
  --title "type(scope): short description" \
  --body "$(cat <<'EOF'
## Summary
- What this changes and why.

## Test plan
- [ ] CI green
- [ ] Manual check: ...
EOF
)"

# 4. After review/CI green:
gh pr merge <num> --squash --delete-branch
```

## Auto-mode safety guard

Some agent harnesses have a **classifier that blocks `git push origin main`
directly**, even when the operator authorized it via a click in the UI.
That is intentional: it forces the agent to fall back to the PR path. If the
guard fires, do not work around it. Open a PR.

If the operator types "push directo" in chat (in plain text, not a button
click) — that's the override. The chat-text directive is the audit trail.

## Anti-patterns

- **Force-pushing to main**. Never, regardless of how `main` is wired.
- **`--no-verify` to skip hooks** because "the PR will catch it". Hooks fire
  *locally*; a missed pre-commit hook can leak secrets that even a PR review
  misses.
- **Long-lived branches**. A PR open for >48h drifts from main and the
  re-review cost compounds. Merge or close.
- **Stacking 5 unrelated commits in one PR** because "they're all small".
  Future-you reviewing the revert window will not enjoy this.

## Lessons Learned

<!-- Date · Why the PR path mattered (or didn't) · Outcome -->
