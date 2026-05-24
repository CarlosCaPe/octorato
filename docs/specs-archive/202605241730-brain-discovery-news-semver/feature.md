# Feature: Daily Brain Discovery Loop + News-to-FB Pipeline + Site Semver

> **Status:** DRAFT v2 · awaiting operator sign-off
> **Spec author:** Octorato (Claude Opus 4.7) · 2026-05-24
> **Scope:** Three coupled deliverables — F1 (Trending Curation), F2 (News→FB), F3 (Semver). All-in-one because each feeds the others.
> **Brain-root rule:** this file lives in `~/.claude/docs/specs-in-progress/`, archives to `docs/specs-archive/` at close.

---

## 0. Why all 3 in one spec

| Feature | Depends on | Used by |
|---|---|---|
| F1 — GH/HN/PH trending curation → digest | (nothing) | F2 (auto-news), F3 (auto-PATCH) |
| F2 — News → FB Page bridge | F3 (semver as part of news front-matter) | F1 (auto-publish path) |
| F3 — Semver model for site/news | (nothing) | F1 (PATCH on AI-auto news), F2 (version stamped on each FB post for traceability) |

Splitting would require F1 to ship a half-baked auto-publish + F2 to bolt on later = double rework. One spec, three sections.

---

# F1 · GitHub Trending Daily Curation

## F1.1 Problem
Brain grows by reaction. New MCP servers / agent frameworks / CLI tools ship on GitHub-trending daily and never reach the brain because the operator doesn't read /trending. Recent miss-then-add cases: `claude-mem-persistent-memory` and `floci-local-aws` were both added manually 2-3 days after they trended.

## F1.2 Goal
Daily, automated curation pipeline that:
1. Pulls top-100 from `github.com/trending` (scrape) + top-30 HN front-page (Firebase API) + Product Hunt today launches (GraphQL or scrape) in parallel.
2. Heuristic filter drops noise (already covered by existing skill, irrelevant domain, no README).
3. Classifies survivors into 4 brain-fit buckets: **skill-candidate / mcp-candidate / pattern-reference / paid-alternative**.
4. LLM QA gate (Groq `llama-3.3-70b-versatile`, uses existing `GROQ_API_KEY`) — final ~20-30 calls/day to drop "doesn't beat what we have".
5. Writes to two destinations:
   - **Notion page** "GH Trending — `<YYYY-MM-DD>`" under parent Curation page (mobile-readable, search)
   - **Markdown archive** `~/.claude/knowledge/github-trending/<YYYY-MM-DD>.md` (cold storage, grep-able)
6. `/trending-promote <date> <repo>` scaffolds a real `~/.claude/skills/<name>/SKILL.md` AND triggers F2 (auto-news to FB).

## F1.3 Scheduling
- Workflow `brain-trending-digest` added to `~/dataqbs-local-cron/runner.py`
- `Daily(hour=7, minute=30)` UTC (≈01:30 CST), runs in <2min
- Failure logs to journal + state.sqlite; never crashes supervisor

## F1.4 Brain-fit classification rules
| Bucket | Heuristic trigger |
|---|---|
| `skill-candidate` | Description has action verbs + topic overlap with brain vocab (ai, cli, devtools, automation, observability, db, security) |
| `mcp-candidate` | Name/topics contains `mcp` OR description mentions "Model Context Protocol" / "MCP server" |
| `pattern-reference` | Architectural keywords (durable objects, vector db, sandbox, RAG, eval, agent framework) AND no wrap surface |
| `paid-alternative` | README contains "alternative to <SaaS>" OR description claims OSS replacement for paid (Postman/ElevenLabs/Datadog/Linear/etc.) |
| `SKIP` | None of the above match OR `query_connectome.py` similarity >0.4 with existing skill AND repo not 2× more stars |

## F1.5 Acceptance criteria
- AC-F1-1: Digest file exists at `~/.claude/knowledge/github-trending/<today>.md` by 07:35 UTC
- AC-F1-2: Notion page "GH Trending — <today>" exists under parent Curation page
- AC-F1-3: Both contain identical content (same buckets, same survivors)
- AC-F1-4: Re-running same day = idempotent (overwrite, no dupes)
- AC-F1-5: 0 survivors → both destinations get "no signal today" placeholder (not empty)
- AC-F1-6: Selector breakage on github.com/trending → exit 1, supervisor records FAIL
- AC-F1-7: LLM gate skipped gracefully if `GROQ_API_KEY` missing; digest still emitted (heuristic-only)
- AC-F1-8: `/trending-promote <date> <repo>` scaffolds skill + invokes F2 pipeline; full chain logs in `~/dataqbs-local-cron/logs/trending-promote.log`

---

# F2 · News → FB Page Bridge (Generalized)

## F2.1 Problem
The blog→FB pipeline works (`/api/multireach/internal/blog-bridge` + `fb-publish-{en,es}` crons). News articles, which are a separate Astro content collection, **don't** flow to FB Page. So when `/dataqbs-news <slug>` publishes a skill announcement, it lives only on the site — nobody sees it on the FB feed.

Operator's instruction: "esas news se ben enviar tamien el page de facebook" — apply same FB publish pattern to ALL news, not just trending-derived.

## F2.2 Goal
Add a generalized news→FB Page bridge that mirrors the existing blog→FB flow:
1. New endpoint `src/pages/api/multireach/internal/news-bridge.ts` — mirrors `blog-bridge.ts` but reads from `content/news/`.
2. New supervisor workflow `fb-publish-news` — daily at e.g. 14:30 UTC (offset from existing 13:00 EN / 15:00 ES blog crons so we don't slam the worker concurrently). Picks today's most recent news article that hasn't been FB-published yet (idempotency via D1 sentinel table `news_fb_publish_history`).
3. `/trending-promote` invokes the same bridge endpoint directly after committing the news article — instant publish, no wait for cron.
4. Target: dataqbs main FB Page (technical/AI audience, distinct from Séptimo Piso which is RE-only per memory `Real Estate · Séptimo Piso fachada`).

## F2.3 Idempotency
- D1 migration `0012_news_fb_publish_history.sql`: table `news_fb_publish_history(news_slug TEXT PRIMARY KEY, published_at TEXT, multireach_post_id TEXT)`.
- Bridge endpoint checks the table before queueing — returns `{status: "already-bridged"}` on retries (mirrors blog-bridge's day-keyed pattern).
- Cron is safe to invoke from multiple paths (cron + promote + manual `gh workflow run`).

## F2.4 Acceptance criteria
- AC-F2-1: New endpoint returns 201 + multireach_post_id when called for a fresh news slug, 200 "already-bridged" on retry
- AC-F2-2: Workflow `fb-publish-news` registered in runner.py with `Daily(hour=14, minute=30)`
- AC-F2-3: Manual `/dataqbs-news <slug>` (existing) does NOT auto-FB-publish — keeps PULL model for manual path; only `/trending-promote` (F1) auto-bridges
- AC-F2-4: D1 sentinel table prevents double-publish even if cron fires twice
- AC-F2-5: FB post body contains: news title + 1-line summary + dataqbs.com/news/<slug> link + relevant emoji per bucket type
- AC-F2-6: No realestate cross-contamination: bridge hardcodes the dataqbs page channel, rejects RE-tagged news (defense-in-depth, even though news collection doesn't have RE tags)

---

# F3 · Semver Model for Site & News

## F3.1 Problem
`projects/dataqbs_site/package.json` version is stuck at `1.0.0` since forever. With 11+ bot commits per branch + operator's manual changes, no way to tell at a glance "how much has changed since I last looked".

## F3.2 Goal
Apply semver to the dataqbs site (in `projects/dataqbs_site/package.json`) with the operator's specific scheme:
| Bump | Trigger |
|---|---|
| PATCH (`1.0.X`) | AI-auto commits — bot identities (blog-bot, dataqbs-bot, dataqbs-traffic-bot, octorato-bot). Each auto-news, each metrics snapshot, each AI-generated blog post = PATCH bump. |
| MINOR (`1.X.0`) | Operator's manual commits (carlos.carrillo@dataqbs.com or Carlos Carrillo identity). Each PR you merge to main = MINOR bump. |
| MAJOR (`X.0.0`) | AI-proposed major-suggestion commits — explicit opt-in via commit trailer `Octorato-Major: yes`. Used when Claude proposes a structural/breaking change (new content category, schema migration, framework upgrade) that the operator accepts. Defense: only auto-bumps with the trailer, so accidental "AI big change" doesn't trigger MAJOR. |

## F3.3 Implementation
- New script `projects/dataqbs_site/scripts/bump-semver.ts` — reads HEAD commit, detects identity + trailer, bumps `package.json` version, commits "chore: bump version to X.Y.Z" with `--no-verify`.
- Wired as a **git post-commit hook** (in `.githooks/post-commit`) so every commit on main auto-bumps. Skip on non-main branches.
- Or as **post-merge hook on main** to avoid per-commit overhead during feature branch work — bumps once per merge based on the set of squashed commits' identities.
- Each news article front-matter gets a new field `published_in_version: "X.Y.Z"` — the version snapshot at publish time. Helps build "changelog" view later.
- News pages render the version badge somewhere visible (footer / corner) for the operator's audit eye.

## F3.4 Acceptance criteria
- AC-F3-1: After an AI bot commit to main, `projects/dataqbs_site/package.json` version bumps PATCH (X.Y.N → X.Y.N+1)
- AC-F3-2: After an operator merge to main (PR squashed), version bumps MINOR (X.Y.N → X.Y+1.0)
- AC-F3-3: Commit with `Octorato-Major: yes` trailer in body bumps MAJOR (X.Y.N → X+1.0.0)
- AC-F3-4: Non-main commits don't trigger bumps
- AC-F3-5: Bump script is idempotent (running twice on same commit = no-op)
- AC-F3-6: News front-matter has `published_in_version` for all NEW articles (existing articles untouched)
- AC-F3-7: Version visible on dataqbs.com/news pages (small footer badge)

---

## Shared sections

### Architecture (cross-feature)

```
                 ~/dataqbs-local-cron/runner.py  (existing supervisor)
                              │
        ┌─────────────────────┼─────────────────────────────┐
        │                     │                             │
   Daily 07:30 UTC      Daily 14:30 UTC               Daily 18:00 UTC
   brain-trending       fb-publish-news               dataqbs-traffic-watch
   -digest (F1)         (F2)                          (existing)
        │                     │
        ▼                     ▼
   github_trending      POST /api/multireach/
   _digest.py           internal/news-bridge
        │                     │
        ├─ Markdown            ▼
        │  archive          MULTIREACH_STORE (KV)
        │                     │
        ├─ Notion             ▼
        │  page             multireach-scheduler worker
        │                  (CF cron * * * * *)
        ▼                     │
   ~/.claude/                 ▼
   knowledge/             FB Page (dataqbs main)
   github-trending/

User flow: digest review → /trending-promote <date> <repo>
   ↓ scaffolds ~/.claude/skills/<name>/SKILL.md
   ↓ cd ~/dataqbs-local-cron/bot-worktree
   ↓ runs skill-to-news-article.ts → writes content/news/<date>-<slug>.md
   ↓ post-commit hook bumps PATCH (F3)
   ↓ commits + pushes to main
   ↓ POSTs to /api/multireach/internal/news-bridge directly (F2, instant)
   ↓ → FB Page
```

### Non-functional requirements

- **No secrets at brain root** (memory `No SDD artifacts at brain root`) — spec & plan live in `~/.claude/docs/specs-in-progress/`, archive on close.
- **Brain stays generic** (memory `The Brain Stays Generic`) — digest content has no client tokens. Only metadata flows public.
- **Bot-worktree pollution-free** (today's fix) — F1/F2 auto-commits go via `~/dataqbs-local-cron/bot-worktree` on main, never operator's feature branch.
- **PR-first rule exception**: AI-auto commits (news from trending, version bumps, traffic snapshots) push directly to main. Operator-approved in this session; memory `Prefer PR over direct main` gets a carve-out amendment.
- **PULL model exception for trending-only**: `/dataqbs-news` (manual) keeps current PULL flow. Only `/trending-promote` auto-publishes. Memory `dataqbs.news curation rule` amended to carve out trending path.
- **GROQ_API_KEY** is the only new "credential" footprint — already in `projects/dataqbs_site/.dev.vars`, read by runner via existing auto-discover.
- **Notion** access: requires Notion integration token in `~/dataqbs-local-cron/.env` as `NOTION_TOKEN`. Skill degrades to Markdown-only if missing.

### Acceptance criteria (8 dimensions, master checklist)

1. **Correctness** — All F1/F2/F3 ACs above pass (1+2+3 ACs total).
2. **Resilience** — Any of: trending scraper fails, LLM down, Notion 401, FB 5xx, bridge 503 → loud failure, log entry, exit non-zero. No silent skip.
3. **Idempotence** — Every cron + every promotion is safe to re-fire any time (date-keyed sentinels + version bump no-op).
4. **Test coverage** — Unit tests for: classifier rules (golden inputs), semver bump logic (commit→version transition table), news-bridge sentinel.
5. **Security** — No new secrets at brain root. `gh` CLI for GH API. `GROQ_API_KEY` from existing .env. Notion token in supervisor .env (gitignored). FB tokens unchanged (already in MULTIREACH_STORE KV).
6. **Performance** — F1 pipeline <2min. F2 bridge <500ms p95. F3 hook <100ms (must not slow operator commits).
7. **Brain-fit consistency** — Deterministic classifier (same input = same bucket).
8. **Doc coverage** — `~/.claude/skills/github-trending-curation/SKILL.md` + amendments to `MEMORY.md` (carve-outs) + runbook update at `~/Documents/github/dataqbs_site/docs/ops/local-cron-supervisor.md` (new workflows table rows).

### Impact radius (new + modified files)

**Brain (`~/.claude/`):**
- NEW: `scripts/github_trending_digest.py`
- NEW: `skills/github-trending-curation/SKILL.md`
- NEW: `commands/trending-promote.md`
- NEW: `knowledge/github-trending/` (dir)
- MOD: `MEMORY.md` (carve-out lines for PR/PULL rules)

**Dataqbs site (`~/Documents/github/dataqbs_site/`):**
- NEW: `projects/dataqbs_site/src/pages/api/multireach/internal/news-bridge.ts`
- NEW: `projects/dataqbs_site/scripts/bump-semver.ts`
- NEW: `projects/dataqbs_site/migrations/0012_news_fb_publish_history.sql`
- NEW: `.githooks/post-commit` (or post-merge)
- MOD: `projects/dataqbs_site/package.json` (initial version bump from 1.0.0)
- MOD: `projects/dataqbs_site/src/content/config.ts` (add `published_in_version` to news schema)
- MOD: `projects/dataqbs_site/src/pages/news/[...slug].astro` (render version badge)
- MOD: `docs/ops/local-cron-supervisor.md` (runbook table +2 rows)

**Supervisor (`~/dataqbs-local-cron/`):**
- MOD: `runner.py` (+2 workflows: `brain-trending-digest`, `fb-publish-news`)
- MOD: `.env` (add `NOTION_TOKEN`, optional)

### Out of scope (v1)

- Multi-language news (F2 only handles ES news first; EN news bridge later)
- Visual changelog page on the site (semver tracked but not surfaced as a /changelog page yet — v2)
- Trending sources beyond GH/HN/PH (Twitter, Reddit, arXiv, etc.)
- Auto-creation of skill SKILL.md body (the scaffold from /trending-promote is a TODO checklist; operator fills the actual content)
- Vector-similarity beyond TF-IDF (current `query_connectome.py` is enough for v1)

### Open questions

- **Q1: Notion parent page ID for Curation?** A: ask operator at implementation start; create one if missing.
- **Q2: FB Page channel ID for dataqbs main?** A: derive from `multireach_post_id` of an existing blog-published post (search `wrangler tail multireach-scheduler` logs).
- **Q3: Should the post-commit hook live in dataqbs_site `.githooks/` or globally?** A: project-local — `.githooks/` in the repo, installed via `git config core.hooksPath .githooks`.

---

## Ready for `/sdd-plan`

Spec covers all 3 features. Estimated plan size: 18-20 tasks (within the 20-task cap). Sign off below and we generate the plan.
