---
name: news-article-curation
description: Daily brain learning loop for AI news and blogs. Reads a watchlist of RSS/Atom feeds (Simon Willison, OpenAI, DeepMind, Latent Space, arXiv cs.AI and more), classifies each recent article into brain-fit buckets via heuristics + an optional Groq LLM gate, and surfaces only the ones that teach something the brain doesn't already know. Output lands in `~/.claude/knowledge/news-articles/<date>.{md,json}`. Promote a keeper to a real skill with `/news-promote <date> "<title-substring>"`. Sibling of github-trending-curation; this is the INBOUND half (blog feeds we can learn from), the news section on the site is the OUTBOUND half (skills we already learned).
metadata:
  type: brain-routine
  schedule: daily 06:45 UTC
  runner: ~/dataqbs-local-cron/runner.py → workflow brain-news-digest
---

# AI News & Blogs Daily Curation

## The loop this closes

The dataqbs arm already runs `blog-daily`: it ingests 10 AI RSS feeds, summarizes them, and PUBLISHES posts. That is content going out. It never fed the brain anything. The site's `news/` section is the opposite end: skills the brain already learned, published outward via `/trending-promote`.

This skill is the missing middle. It reads the SAME class of feeds, but instead of publishing summaries it distills each recent article into a skill candidate the operator can promote. Blog = things we could learn. News = things we already learned. This connects them.

It does NOT touch the arm's live blog pipeline, and the brain fetches the feeds itself, so the brain never depends on an arm.

## Trigger

```bash
python3 ~/.claude/scripts/news_article_digest.py                 # today
python3 ~/.claude/scripts/news_article_digest.py --date 2026-06-08   # backfill
python3 ~/.claude/scripts/news_article_digest.py --dry-run        # print, don't write
python3 ~/.claude/scripts/news_article_digest.py --no-llm         # heuristic only
```

Scheduled daily at 06:45 UTC via the local cron supervisor (a quarter hour before GitHub trending, so both digests are ready by the morning skim).

## What it does

1. **Loads feeds** from `feeds.yaml` (falls back to a built-in seed list if missing).
2. **Fetches** every feed in parallel (RSS + Atom, parsed with stdlib `xml.etree`, no `feedparser` dependency). Keeps only items from the last 4 days, capped per feed.
3. **Classifier** assigns each article a bucket:
   - `lesson-candidate`: teaches a technique/pattern/gotcha/benchmark, on a brain topic
   - `tool-mention`: announces or reviews a tool that could become a skill or MCP
   - `pattern-reference`: an architectural concept worth a reference
   - `paid-alternative`: open-source replacement for a paid SaaS
   - `mcp-candidate`: mentions Model Context Protocol
   - `SKIP`: pure news/opinion with no reusable artifact, OR an existing skill already covers it (TF-IDF via `query_connectome.py`)
4. **Harmonization action** per survivor, same model as trending: `ADD` (net-new), `MERGE-WITH:<skill>` / `EXTEND:<skill>` (real overlap), or `SKIP` (covered). Harmonize, don't accrete.
5. **LLM QA gate**: Groq `llama-3.3-70b-versatile` (`GROQ_API_KEY` from `projects/dataqbs_site/.dev.vars`). Drops announcements with no "how". Graceful skip if the key is missing.
6. **Writes** `~/.claude/knowledge/news-articles/<date>.md` (human digest) + `<date>.json` (machine sidecar, ALL items incl. SKIP + reasons).

## Operator daily workflow

1. `cat ~/.claude/knowledge/news-articles/$(date +%F).md` (or read it alongside the trending digest).
2. Usually 0-5 survivors. For each real keeper: `/news-promote <date> "<title-substring>"`.
3. That scaffolds the skill (ADD/MERGE/EXTEND per the action) and reuses the existing news + FB publish path.

## Config

Edit `feeds.yaml` to add or remove sources. Per-feed knobs and recency/cap live in the script (`per_feed`, `recency_days`). Set `--no-llm` to run heuristic-only.

## Integration with existing brain

- Reuses `query_connectome.py` for skill-overlap dedup (identical call to trending).
- Reuses `GROQ_API_KEY` already in the project `.dev.vars`.
- Emits the SAME JSON schema as `github-trending-curation`, so `/news-promote` mirrors `/trending-promote`.
- Brain-independent: fetches public feeds directly, no arm dependency.

## Out of scope (v1)

- Full-text article fetch (uses feed summary only; deep-read happens at promote time).
- Auto-promotion (human gate is mandatory, same as every brain learning routine).
- Twitter / Reddit / YouTube sources.

## Lessons / history

Initialized 2026-06-08. Built after discovering the loop was half-open: the arm published blog content from these feeds but nothing distilled them back into brain skills. See `[[harmonization-over-accretion]]` for why the action field matters.
