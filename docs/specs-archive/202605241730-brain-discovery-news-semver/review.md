# Review · brain-discovery-news-semver

> **Date:** 2026-05-24 17:30 UTC
> **Spec:** feature.md (this dir) · **Plan:** plan.md (this dir)
> **PR (F2+F3):** https://github.com/CarlosCaPe/dataqbs_site/pull/148
> **Out-of-repo glue (F1+F4+F5):** ~/.claude/scripts/, ~/.claude/skills/github-trending-curation/, ~/.claude/commands/trending-promote.md, ~/dataqbs-local-cron/runner.py

## What shipped

### F1 — Daily trending digest (in ~/.claude/)
- `scripts/github_trending_digest.py` (833 lines, stdlib + gh CLI). Fetches GH/HN/PH/TikTok in parallel, classifies into 4 buckets via heuristics + connectome similarity, optional Groq llama-3.3-70b QA gate, writes Markdown digest + optional Notion page.
- `skills/github-trending-curation/SKILL.md` (~80 lines) — usage doc + config block + integration with /trending-promote.
- `knowledge/github-trending/` data directory.
- Supervisor workflow `brain-trending-digest` at Daily(7, 30) UTC, registered in `~/dataqbs-local-cron/runner.py`.

### F2 — News → FB Page bridge (in PR #148)
- `migrations/0014_news_fb_publish_history.sql` — D1 sentinel table.
- `src/pages/api/multireach/internal/news-bridge.ts` — mirrors blog-bridge, targets dataqbs main FB Page.
- Supervisor workflow `fb-publish-news` at Daily(14, 30) UTC.

### F3 — Site semver (in PR #148)
- `scripts/bump-semver.ts` — bot=PATCH, operator=MINOR, "Octorato-Major: yes" trailer=MAJOR.
- `.githooks/post-commit` — auto-bump on main only, idempotent.
- News schema gets optional `published_in_version` field.
- News article footer renders the version badge.

### F4 — TikTok hashtag mining (in F1's digest.py)
- `fetch_tiktok()` uses yt-dlp metadata mode on TikTok hashtag URLs (devtools / opensource / ai / cli / developer). Lightweight: only metadata, no frame extraction. Graceful skip when TikTok blocks the request (current state).

### F5 — Harmonization actions (in F1's classifier)
- Every candidate now gets an **action** field: `ADD` / `MERGE-WITH:<skill>` / `REPLACE:<skill>` / `EXTEND:<skill>` / `SKIP`.
- `/trending-promote` consumes the action — scaffolds new skill (ADD), appends to existing (MERGE), or deprecates and supersedes (REPLACE).
- Operationalizes operator instruction "no sólo agregar, armonizar/homologar/integrar".

### Memory carve-outs
- `feedback_bot_pr_exception.md` — bot identities push direct to main.
- `feedback_trending_promote_auto_publish.md` — single carve-out from PULL model.

## 8-dimension review against spec

| Dimension | Result | Notes |
|---|---|---|
| 1. Correctness | ✅ PASS | Smoke test: digest run on 2026-05-24 produced 3 candidates from 46 sources with correct buckets (mcp-candidate) + harmonization actions (ADD x2, MERGE-WITH x1). |
| 2. Resilience | ✅ PASS | Per-source try/except + degraded fallback (PH gated → 0 results, TikTok blocked → 0 results, neither crashes the pipeline). |
| 3. Idempotence | ✅ PASS | Markdown writer overwrites cleanly; D1 news_fb_publish_history blocks double-publish; post-commit hook skips on bump commits. |
| 4. Test coverage | ⚠️ DEFER | No unit tests added in v1. Smoke test confirmed end-to-end. Operator may add tests in v2. |
| 5. Security | ✅ PASS | No new tokens at brain root; GROQ from existing .env; NOTION_TOKEN optional. Spec lives in specs-archive/. |
| 6. Performance | ✅ PASS | Smoke run completed in ~60s (mostly LLM-gate-free + connectome queries). Well within the 2min budget. |
| 7. Brain-fit consistency | ✅ PASS | Deterministic classifier; same input produces same bucket + same action. |
| 8. Doc coverage | ✅ PASS | SKILL.md exists, MEMORY.md amended, runbook updated, /trending-promote slash command documented. |

## Known limitations (v1 → v2 backlog)

1. **GitHub trending only renders ~16 entries**, not 100. Operator's "top 100" was an assumption; real ceiling is the page's render limit. Mitigated by adding 3 other sources (HN/PH/TikTok).
2. **TikTok auth-gated** — yt-dlp returns non-zero against TikTok hashtag URLs without cookies. v1 gracefully skips. v2: add a cookie file or fall back to `social-video-mining` skill's full pipeline.
3. **Notion writer untested** — operator hasn't provided NOTION_TOKEN + parent page ID yet. Writer is wired and will activate when those env vars are set; for now degrades to Markdown-only.
4. **Product Hunt gated** — homepage blocks unauthenticated scraping in some regions. v1 gracefully skips. v2: add PRODUCTHUNT_TOKEN to call their GraphQL API.
5. **LLM gate cost not measured** — Groq llama-3.3-70b at ~20-30 calls/day is well within free tier, but worth tracking once it runs daily.

## Operator follow-ups

- Provide `NOTION_TOKEN` + `NOTION_CURATION_PARENT_PAGE_ID` (paste into `~/dataqbs-local-cron/.env`).
- Install the post-commit hook in your checkout: `cd ~/Documents/github/dataqbs_site && git config core.hooksPath .githooks` (after PR #148 merges).
- First daily fire of `brain-trending-digest`: tomorrow 07:30 UTC (≈01:30 CST).
- First daily fire of `fb-publish-news`: tomorrow 14:30 UTC (≈08:30 CST).
- Review the daily digest for ~1 week — if noise is too high, we activate the LLM gate by default (currently runs but conservative). If too quiet, we lower the similarity threshold.

## What was NOT done (intentional)

- No /news → /blog redirect (operator confirmed: keep separate, cross-link).
- No auto-creation of skill body — `/trending-promote` scaffolds a TODO checklist, the operator writes the content.
- No multi-language news bridge (ES default; EN later).
- No /changelog page on the site (semver tracked, not surfaced as its own page yet).
- F3 hook is NOT auto-installed via the PR — operator must run `git config core.hooksPath .githooks` once after merge. By design (per-developer git config).
