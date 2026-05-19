---
name: cron-bridge-daily-publisher
description: End-to-end architectural pattern for "daily auto-publish N curated items from D1 → social platform (FB Page, IG Business, LinkedIn Page, etc.) via the existing Multi-Reach scheduler worker". Includes fair-rotation selector, content-hash idempotency, sentinel-keyed daily dedup, R2 image mirror via serve endpoint, D1 audit trail, and a companion retract sweep for platform ToS SLA (e.g. EasyBroker 24h). Reusable across white-label / franchise / multi-tenant scenarios.
when_to_use: When a client wants "post N things per day to one or more social platforms, picked from a catalog, without duplicates within a cycle". Especially when there's an upstream feed (REST API, scraping target, manual catalog) → D1 → social. Examples — real-estate listings, e-commerce products, restaurant menus, event calendars.
triggers: ["daily social publisher", "fair rotation", "auto-post N per day", "multireach bridge", "EB-to-FB", "catalog to social"]
---

# Cron Bridge — Daily Auto-Publisher

## When this skill fires

Client asks for a variant of: "I want my <catalog of N items> to auto-post to <social Page/Account>, M items per day, no repeats until we've cycled through all N, and respect any ToS removal SLAs". This skill is the architectural recipe.

Pre-flight check: confirm the target platform allows API publishing for the surface you're targeting (Page yes, Group no — see `tos-safe-social-share-helper` for the no-API case).

## Architecture overview

```
┌──────────────────┐  cron */30  ┌──────────────────┐
│ Upstream feed    │ ────────►   │ ingest worker    │ ──┐
│ (REST API)       │             │ → D1 catalog     │   │ idempotent UPSERT
└──────────────────┘             │ → R2 images      │   │ + tombstone sweep
                                 │ → audit rows     │ ◄─┘
                                 └────────┬─────────┘
                                          │
              ┌─────────────────────────────────────────┐
              │                                         │
              ▼ cron 1×/day @ 14:00 UTC                 ▼ cron */1 (publisher worker)
┌──────────────────┐                          ┌──────────────────┐
│ bridge endpoint  │                          │ multireach       │
│ /api/.../bridge  │ ── INSERT KV Posts ──►   │ scheduler worker │
│ + sentinel       │ ── INSERT D1 audit ──►   │ → Graph API      │
│ + fair rotation  │                          │ → updates KV     │
└──────────────────┘                          └──────────────────┘
                                                       │
                                                       ▼
                                              ┌──────────────────┐
                                              │ Social platform  │
                                              │ Page / Account   │
                                              └──────────────────┘
                                                       ▲
              ┌────────────────────────────────────────┘
              │ cron 1×/hour
              ▼
┌──────────────────┐
│ retract endpoint │ ── DELETE on tombstoned items
│ /api/.../retract │    (24h ToS SLA compliance)
└──────────────────┘
```

## The 6 components (build in this order)

### 1. Schema — content + tracking

Three D1 tables (skip any you already have):

```sql
-- The catalog item (whatever you're publishing)
CREATE TABLE catalog_items (
  id              INTEGER PRIMARY KEY,
  source          TEXT NOT NULL CHECK (source IN ('upstream','own')),
  external_id     TEXT,                       -- id from upstream feed
  slug            TEXT NOT NULL,
  -- ... domain-specific fields ...
  content_hash    TEXT,                       -- sha256(canonical_json(record))
  last_seen_at    TEXT,                       -- stamped each ingest run
  deleted_at      TEXT,                       -- tombstone (soft delete)
  UNIQUE (source, external_id)
);
CREATE INDEX ix_catalog_active ON catalog_items(deleted_at) WHERE deleted_at IS NULL;

-- Per-publication tracking (rotation memory + retract bookkeeping)
CREATE TABLE social_posts (
  id                   INTEGER PRIMARY KEY,
  item_id              INTEGER NOT NULL REFERENCES catalog_items(id),
  target_platform_id   TEXT NOT NULL,         -- e.g. FB Page Graph ID
  multireach_post_id   TEXT,                  -- KV id from publisher
  platform_post_id     TEXT,                  -- set by worker after publish
  status               TEXT NOT NULL DEFAULT 'scheduled'
                       CHECK (status IN ('scheduled','posted','failed','retracted','retract_failed')),
  scheduled_at         TEXT NOT NULL,
  posted_at            TEXT,
  retracted_at         TEXT,
  last_error           TEXT
);
-- Daily idempotency: at most ONE post per (item, target) per UTC date
CREATE UNIQUE INDEX ux_social_posts_daily
  ON social_posts (item_id, target_platform_id, substr(scheduled_at, 1, 10));
CREATE INDEX ix_social_posts_rotation
  ON social_posts (item_id, target_platform_id, scheduled_at);
```

### 2. Fair-rotation selector (the heart of the cycle)

The query MUST: NULLS-first (never-posted wins), then oldest-scheduled-at, with RANDOM() tiebreak.

```sql
SELECT c.*, (SELECT r2_key FROM catalog_images WHERE item_id = c.id LIMIT 1) AS cover_r2_key
FROM catalog_items c
LEFT JOIN social_posts p
  ON p.item_id = c.id
  AND p.target_platform_id = ?
  AND p.status IN ('scheduled', 'posted')
WHERE c.deleted_at IS NULL AND c.source = 'upstream'
GROUP BY c.id
ORDER BY MAX(p.scheduled_at) IS NOT NULL,   -- 0 = nulls first
         MAX(p.scheduled_at) ASC,             -- oldest next
         RANDOM()                              -- tiebreak
LIMIT ?
```

Critical: in the JS wrapper, ALSO filter out items already scheduled today (a separate query). Without it, edge cases at UTC rollover can double-schedule.

### 3. Bridge endpoint (the daily trigger)

`POST /api/<feature>/internal/bridge`, called by GH Actions cron at e.g. 14:00 UTC:

```
1. Auth via X-Scheduler-Secret shared header
2. Resolve target channel (e.g. FB Page) by platformId from the existing Multi-Reach KV
3. Idempotency: sentinel key = `<feature>:bridge:<utcDate>:<targetId>`, TTL 7d
   - If exists → return 200 already-bridged
4. Run fair-rotation selector → N candidates
5. For each candidate:
   a. Mirror image from source R2 to multireach-media R2 (idempotent on bytes-hash key)
   b. saveMedia → get mediaId
   c. Build caption (template, include required attribution like "Ref. EB: <id>")
   d. createPost in multireach KV with text + mediaIds + targets + schedule={type:'once', startDate}
      Stagger: scheduledAt = now + 60s + i * 60min
   e. INSERT into social_posts (D1 tracking row)
6. Set sentinel
7. Return 201 with summary
```

### 4. Retract endpoint (the ToS compliance loop)

`POST /api/<feature>/internal/retract`, called hourly:

```
1. SELECT social_posts WHERE status IN ('scheduled','posted')
   AND linked catalog item has deleted_at IS NOT NULL
2. For each row:
   - If platform_post_id is null (not yet published) → disable the KV Post (worker skips it)
   - Else → look up platform_post_id from KV (D1 may be stale — back-fill opportunistically)
   - Call platform's DELETE endpoint (e.g. Graph API DELETE /<post-id>)
   - Mark row status='retracted'
```

Treat platform 404 as success (already deleted). Bound work per run (e.g. LIMIT 30).

### 5. GH Actions workflows

Three crons:

```yaml
# Daily publisher
on: { schedule: [{ cron: "0 14 * * *" }] }   # 14:00 UTC = 8 AM CDMX
permissions: { contents: read }
concurrency: { group: <feature>-publish, cancel-in-progress: false }
# → curl POST /api/<feature>/internal/bridge with X-Scheduler-Secret

# Hourly retract (24h SLA compliance)
on: { schedule: [{ cron: "5 * * * *" }] }
# → curl POST /api/<feature>/internal/retract

# Hourly watchdog (alert if ingest gets stale)
on: { schedule: [{ cron: "15 * * * *" }] }
# → query D1 audit table, FAIL if max(started_at) older than threshold
```

### 6. R2 media serve endpoint (gotcha trap)

If the publisher worker uploads images via Graph API by URL (most platforms), the URL must be publicly fetchable. Options:

- **A. R2 public bucket** (`pub-<hash>.r2.dev`) — simplest, but ALL objects become public. Verify the bucket holds only items you want public.
- **B. Serving proxy** (Astro/Workers endpoint that pulls from private R2 and serves with `Access-Control-Allow-Origin: *`) — more secure, but careful with the allowlist. **Always whitelist by prefix** — `key.startsWith('uploads/')` rejected my legitimate `realestate/` prefix; lost 30 min of "Meta API 400: Missing or invalid image file" before I traced it.

## Idempotency invariants — must NEVER break

1. **Catalog upsert**: ON CONFLICT (source, external_id) DO UPDATE. Re-runs with same upstream data → zero net changes.
2. **Tombstone sweep**: filtered by `source='upstream'` ONLY. Mass-tombstoning your own items (`source='own'`) is the most common load-bearing bug. Add a defensive test.
3. **Bridge sentinel**: keyed by (user, feature, UTC date, target). One sentinel per "day cycle" per target.
4. **Daily UPSERT in tracking**: UNIQUE index on `(item_id, target_id, substr(scheduled_at, 1, 10))`. Prevents accidental double-posting on the same UTC date.

## Calibration numbers (empirical, real-estate domain)

- 84 items in catalog, posting 12/day → full cycle in 7 days
- ~30s wall-clock per bridge call for 12 items (R2 mirror + KV write + D1 insert + 5 retries on CF rate limits)
- ~3.5 min wall-clock end-to-end for the GH Actions workflow
- ~0.16% R2 fetch error rate from upstream CDNs (jittery sources) — retry exp backoff is sufficient
- 99 → 199 D1 calls per bridge run; stay under 1000/sec D1 limit easily

## Anti-patterns to refuse

- **Don't** trigger publish from the ingest cron. Separate them. Ingest is "data fresh"; publish is "content marketing cadence". Coupling them creates "you posted on Sunday at 3am because EB pushed an update" surprises.
- **Don't** write a UI for picking which N items to publish. Let fair rotation do its job. Adding curation here is where the project starts to scope-creep.
- **Don't** mix prime/curated items and feed items in the same rotation pool by default. Use a `tier` column (low number = priority) so curated stuff floats to the top of the daily picks.

## Related skills / patterns

- `tos-safe-social-share-helper` — companion pattern when you ALSO want to fan-out posts to surfaces with no API (FB Groups, etc.)
- `idempotent-sql-design` — for the catalog UPSERT semantics
- `dry-run-gate-pattern` — for safely testing the bridge before the cron goes live
- Memory: `lesson-fb-pages-dual-id` — gotcha when wiring the bridge to a FB Page target
