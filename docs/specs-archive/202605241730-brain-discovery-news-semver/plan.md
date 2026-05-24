# Plan: F1 + F2 + F3 (Brain Discovery / News→FB / Site Semver)

> **Generated:** 2026-05-24 from `feature.md` v2 · **Cap:** 20 tasks
> **Order:** dependencies respected (F3 hook before F1/F2 use it; bridge endpoint before /trending-promote uses it).

## Task list (20)

| # | ID | Subject | Maps to AC | Blocks |
|---|---|---|---|---|
| 1 | F1-T1 | Create skill SKILL.md (`~/.claude/skills/github-trending-curation/SKILL.md`) with config block + how-to + triggers | AC-F1-8, doc | T2 |
| 2 | F1-T2 | Write `~/.claude/scripts/github_trending_digest.py` skeleton: 3-source fetchers (GH scrape, HN Firebase, PH page) | AC-F1-1, AC-F1-6 | T3 |
| 3 | F1-T3 | Implement heuristic classifier (4 buckets + SKIP) with `query_connectome.py` integration | AC-F1-1, AC-F1-3 | T4 |
| 4 | F1-T4 | Implement Groq LLM QA gate (graceful skip if `GROQ_API_KEY` missing) | AC-F1-7 | T5 |
| 5 | F1-T5 | Implement Markdown writer to `~/.claude/knowledge/github-trending/<date>.md` (idempotent) | AC-F1-1, AC-F1-4, AC-F1-5 | T6 |
| 6 | F1-T6 | Implement Notion writer (parent page lookup + daily page creation; degrades if `NOTION_TOKEN` missing) | AC-F1-2, AC-F1-3 | T7 |
| 7 | F1-T7 | Register `brain-trending-digest` workflow in `~/dataqbs-local-cron/runner.py` at `Daily(7, 30)` UTC | AC-F1-1, AC-F1-6 | T8, T18 |
| 8 | F2-T1 | D1 migration `0012_news_fb_publish_history.sql` + apply to prod | AC-F2-4 | T9 |
| 9 | F2-T2 | New endpoint `projects/dataqbs_site/src/pages/api/multireach/internal/news-bridge.ts` (mirror blog-bridge) | AC-F2-1, AC-F2-4, AC-F2-5, AC-F2-6 | T10, T13 |
| 10 | F2-T3 | Register `fb-publish-news` workflow in runner.py at `Daily(14, 30)` UTC | AC-F2-2 | T18 |
| 11 | F3-T1 | Write `projects/dataqbs_site/scripts/bump-semver.ts` (commit identity + trailer parser → package.json bump) | AC-F3-1, AC-F3-2, AC-F3-3, AC-F3-4, AC-F3-5 | T12 |
| 12 | F3-T2 | Add `.githooks/post-commit` hook + install instructions in CLAUDE.md / arm-onboarding skill | AC-F3-1, AC-F3-2 | T13 |
| 13 | F3-T3 | Add `published_in_version` to news schema (`src/content/config.ts`) | AC-F3-6 | T14 |
| 14 | F3-T4 | Render version badge on `src/pages/news/[...slug].astro` (footer/corner) | AC-F3-7 | T19 |
| 15 | F1-T8 | Create `/trending-promote` slash command (`~/.claude/commands/trending-promote.md`): scaffold skill + invoke F2 bridge + commit via bot-worktree | AC-F1-8, AC-F2-1 | T19 |
| 16 | SH-T1 | Update `~/.claude/MEMORY.md` with two carve-outs: PR-first exception for AI bots, PULL-model exception for `/trending-promote` | NFR-doc | T19 |
| 17 | SH-T2 | Update `~/Documents/github/dataqbs_site/docs/ops/local-cron-supervisor.md` runbook (+2 rows) | NFR-doc | T19 |
| 18 | SH-T3 | First end-to-end smoke test: manual `python3 github_trending_digest.py` → verify Markdown + Notion outputs | AC-F1-1 to AC-F1-5 | T19 |
| 19 | SH-T4 | End-to-end smoke: pick a fake repo from today's digest → `/trending-promote` → verify SKILL.md scaffolded + news article committed + FB POST 201 (or dry-run if FB token rotation pending) | AC-F1-8, AC-F2-1, AC-F3-1 | T20 |
| 20 | SH-T5 | Archive: move spec + plan + add review.md to `~/.claude/docs/specs-archive/202605241500-brain-discovery-news-semver/` | NFR-doc, lifecycle | (end) |

## Notes on ordering

- F3 hook (T12) lands BEFORE T19 so the first auto-publish triggers PATCH bump (proves the loop).
- F2 endpoint (T9) lands BEFORE T15 so `/trending-promote` has something to POST to.
- T18 is the smoke test for F1 in isolation; T19 is the full E2E smoke (F1+F2+F3).
- T20 archives only after T19 passes — if T19 fails, spec stays in `specs-in-progress/`.

## Risks (per-task callout)

- **T2:** GitHub trending HTML changes occasionally. Use 2-3 fallback selectors + log clearly. PH may need GraphQL token; degrade to scrape if missing.
- **T4:** Groq rate limits — if >30 calls/min, throttle.
- **T6:** Notion API token may not exist yet — task includes prompting operator.
- **T9:** D1 migration must apply on prod (CF API). Has `IF NOT EXISTS` for safety.
- **T12:** post-commit hooks fire on every commit. Must be fast (<100ms). Skip non-main.
- **T15:** `/trending-promote` does git operations — must use bot-worktree (today's fix), not operator's checkout.
