---
description: Promote an article from the daily AI-news digest to a real brain skill, then publish a news article + push to dataqbs FB Page. News-feed sibling of /trending-promote.
argument-hint: <YYYY-MM-DD> "<title-substring>"
allowed-tools: Bash, Read, Edit, Write, WebFetch
---

# /news-promote: News article to Skill in one shot

**Args:** `$ARGUMENTS` (expected: `<YYYY-MM-DD> "<title-substring>"`)

This is the promote half of `[[news-article-curation]]`. It mirrors `/trending-promote` exactly, with three differences: the digest source, the candidate lookup, and a mandatory deep-read (the digest only holds the feed summary, not the full article).

## Pre-flight

1. Parse arguments: first token is the digest date (YYYY-MM-DD); the rest is a title substring identifying the article (quote it).
2. Read the JSON sidecar `~/.claude/knowledge/news-articles/<date>.json`. If missing, abort and point the operator at the daily cron (`news_article_digest.py`).
3. Find the candidate whose `name` contains the title substring (case-insensitive). If 0 match, abort. If >1 match, list them and ask which. Extract: `action`, `bucket`, `best_brain_match`, `similarity`, `url`, `description`, `source`.
4. If `action == SKIP`, abort with "classified as SKIP; promote anyway? rerun with --force". Never silently bypass the harmonization decision.
5. **Deep-read (mandatory):** `WebFetch` the article `url` and read the real piece. The feed summary is not enough to write a substantive skill. Pull the actual technique, the concrete steps, the numbers, the gotcha. If the article is paywalled or thin and yields no reusable artifact, abort and tell the operator to SKIP it.

## Behavior per action

Identical to `/trending-promote` (`ADD` / `MERGE-WITH:<skill>` / `EXTEND:<skill>` / `REPLACE:<skill>`). See that command for the per-action file mechanics. The only change: `metadata.source` is the article URL and `metadata.discovered_on` is the digest date, and the skill body is grounded in the deep-read, not a tagline.

For `ADD`, also add a single reference entry to `~/.claude/MEMORY.md`: `- [<title>](<file>): one-line hook`.

## Quality bar (NON-NEGOTIABLE)

Same bar as `/trending-promote`. A news-derived skill must teach the technique, not summarize the headline. Structure: `## ¿Qué es?` / `## ¿Cuándo conviene usarlo?` (3-5 scenarios) / `## Quickstart` (runnable where applicable) / `## Por qué nos importa` (the technical take: how a dataqbs/octorato operator uses it, what it replaces, the cost or risk it removes). No angle, no publish. No doubled periods, no verbatim feed blurb.

## Cross-cutting: publish news + post to FB

Identical to `/trending-promote` steps 1-5 (bot-worktree reset, author the article to the quality bar via `scripts/news/skill-to-news-article.ts <skill-name-kebab>` then enrich, bot-identity commit with `--no-verify`, push to main, POST to the `news-bridge` with the slug + `X-Scheduler-Secret`). Cite the original article URL as the source in the published piece (attribution, per the always-on legal/copyright rule).

## Issue-resolution scan

Same as `/trending-promote`: after promotion, scan open octorato issues with the strict 3-rule filter (semantic match, no third-party PR, dry-run before close).

## Output

```
✅ Promoted "<title>" (source=<feed>) with action=<ACTION>
   Brain:    ~/.claude/skills/<name>/SKILL.md
   News:     <site>/news/<date>-<slug>
   FB Page:  multireach post <post-id> queued
   Source:   <article-url>
```

## Failure modes

- Sidecar missing → fail loud, point at the cron.
- Title substring matches 0 or many → abort / disambiguate.
- Action = SKIP → require `--force`.
- Deep-read yields no reusable technique → abort, recommend SKIP (do not publish a hollow piece).
- FB bridge HTTP ≠ 200/201 → log + continue (news is committed; retriable).
