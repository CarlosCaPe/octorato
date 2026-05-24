---
name: github-trending-curation
description: Daily brain discovery loop. Pulls top trending from GitHub + HN + Product Hunt, runs heuristic + LLM filter against existing brain skills, surfaces only candidates that beat what we have. Output lands in `~/.claude/knowledge/github-trending/<date>.md` and a daily Notion page. Promote a candidate to a real skill with `/trending-promote <date> <repo>` — that path also auto-publishes a news article and pushes to the dataqbs FB Page.
metadata:
  type: brain-routine
  schedule: daily 07:30 UTC
  runner: ~/dataqbs-local-cron/runner.py → workflow brain-trending-digest
---

# GitHub Trending Daily Curation

## Trigger

Activates automatically every day at 07:30 UTC via the local cron supervisor (`~/dataqbs-local-cron/runner.py`). Manual ad-hoc / backfill:

```bash
python3 ~/.claude/scripts/github_trending_digest.py                 # today
python3 ~/.claude/scripts/github_trending_digest.py --date 2026-05-23   # backfill
python3 ~/.claude/scripts/github_trending_digest.py --dry-run        # don't write outputs, just print
```

## What it does

1. **Fetches** 3 sources in parallel (60s soft timeout):
   - GitHub trending (daily window, top 100) — HTML scrape
   - Hacker News front-page (top 30) — Firebase API (`hacker-news.firebaseio.com`)
   - Product Hunt today launches — GraphQL if `PRODUCTHUNT_TOKEN` set, else page scrape

2. **Enriches** GitHub entries via `gh api repos/<owner>/<name>` (uses operator's existing `gh` CLI auth).

3. **Heuristic classifier** — every entry gets a bucket:
   - `skill-candidate` — CLI/tool with action verbs + brain-topic overlap (ai, cli, devtools, automation, observability, db, security)
   - `mcp-candidate` — name/topics contains `mcp` OR description mentions Model Context Protocol
   - `pattern-reference` — architectural keywords (durable objects, RAG, vector db, agent framework, sandbox, eval) without wrap surface
   - `paid-alternative` — README contains "alternative to <SaaS>" OR description claims OSS replacement for paid (Postman/ElevenLabs/Datadog/Linear/etc.)
   - `SKIP` — none match, OR an existing brain skill covers the same vocab (via `query_connectome.py` similarity > 0.4) and the trending repo isn't 2× more stars

4. **LLM QA gate** — Groq `llama-3.3-70b-versatile` (`GROQ_API_KEY` from `projects/dataqbs_site/.dev.vars`). Reviews the heuristic survivors with a "does this beat what we already have?" prompt. Drops the ones that don't. ~20-30 calls/day. Graceful skip if key missing.

5. **Output writers** (both run, second is optional):
   - **Markdown archive** (always): `~/.claude/knowledge/github-trending/<YYYY-MM-DD>.md`
   - **Notion page** (when `NOTION_TOKEN` and `NOTION_CURATION_PARENT_PAGE_ID` are set): creates/updates a page titled "GH Trending — <YYYY-MM-DD>" under the configured parent

## Config block

Edit this skill's frontmatter or set env vars to tune behavior:

```yaml
sources:
  github:
    enabled: true
    period: daily          # daily | weekly | monthly
    top_n: 100
  hackernews:
    enabled: true
    top_n: 30
  producthunt:
    enabled: true          # falls back to scrape if PRODUCTHUNT_TOKEN absent
classifier:
  skip_list: []            # regex patterns to SKIP unconditionally (e.g. `^.*-tetris$`)
  llm_gate: true           # set false to disable Groq pass
  similarity_threshold: 0.4
  beat_factor: 2.0         # incumbent skill is beaten if trending repo stars > beat_factor × similar-skill connections
outputs:
  markdown: true
  notion: auto             # true | false | auto (auto = if NOTION_TOKEN set)
```

## How to use (operator daily workflow)

Morning:
1. Coffee ☕
2. Open Notion → today's "GH Trending" page (or `cat ~/.claude/knowledge/github-trending/$(date +%F).md` from terminal)
3. Read the digest. Usually 5-15 survivors. Most days 0-3 are real keepers.
4. For each keeper: `/trending-promote 2026-05-24 owner/repo-name`
5. Done. Trending-promote scaffolds the skill, generates a news article, commits to main, and posts to FB Page in a single shot.

## How it beats just-reading-github.com/trending manually

| Manual | This skill |
|---|---|
| 5-10 min/day scrolling | 30 sec skim |
| Forgets to do it | Hard scheduled |
| Doesn't dedupe vs current brain | TF-IDF skill match |
| Doesn't compare quality | LLM QA gate |
| No history | Markdown archive grep-able |
| Forgets to add good ones | `/trending-promote` is one command |

## Integration with existing brain

- Reuses `~/.claude/scripts/query_connectome.py` for skill-overlap detection.
- Reuses `GROQ_API_KEY` already in `projects/dataqbs_site/.dev.vars`.
- Reuses the `~/dataqbs-local-cron/` supervisor (just adds 2 workflow rows).
- Reuses `~/dataqbs-local-cron/bot-worktree` (created today for the bot-commit pattern).
- Promote path delegates to existing `dataqbs_site/scripts/news/skill-to-news-article.ts`.

## Out of scope (v1)

- Twitter, Reddit, arXiv sources
- LLM-authored skill body (the scaffold is a checklist, operator writes the content)
- Visual changelog page on the site
- Multi-language news (ES default; EN later)

## Lessons / history

Initialized 2026-05-24 in this session. First daily run: 2026-05-25 07:30 UTC.
