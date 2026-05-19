---
name: tos-safe-social-share-helper
description: Architectural pattern for cases where a client wants to "auto-publish to social platform X" but the platform's ToS forbids API automation for that surface (FB Groups post-2024, IG personal accounts, LinkedIn personal feeds, etc.). Build a 1-click manual flow with clipboard-prefill + deep-link + tracking, not a bot. Saves the client's account from ban, gives them legal velocity, and produces telemetry the bot couldn't.
when_to_use: When client asks "automate posting to <social-surface>" AND that surface's Graph/REST API for posting was deprecated/restricted OR requires the user to be admin (and they're not). Common cases as of 2025-now — FB Groups (deprecated April 2024), IG Stories from personal accounts, TikTok video uploads, X Spaces, LinkedIn newsfeeds from personal profiles.
triggers: ["facebook groups automate", "publish_to_groups", "share to multiple groups", "tos-safe automation", "share helper"]
---

# ToS-Safe Social Share Helper

## When this skill fires

Client says some variant of: "auto-publish to FB Groups", "post to N groups", "share to my followers/communities automatically". Before building a bot, run the constraints check below.

**Constraints check (5 min):**

1. Is there an OFFICIAL API for posting to this surface? Check the platform's current Graph API / REST docs (not Stack Overflow circa 2019).
2. If yes — is the required permission/scope available to third-party apps right now? (Many got deprecated.)
3. If yes — does the user have the platform role required (admin, moderator, business account)? Members are usually NOT enough.

If any answer is NO, the API path is dead. Don't write the bot. Build this share-helper instead.

## Three paths and their honest tradeoffs

| Path | Legal | Account risk | UX cost | Build cost |
|------|-------|--------------|---------|------------|
| **A. Share helper (this skill)** | ✅ 100% ToS-compliant | Cero | Manual ~5-15s per (post,target) cell | ~4h |
| **B. Browser automation as the user** (Playwright + session persist) | ⚠️ Violates ToS | High — banhammer the user's account | Full auto | ~12h + maintenance |
| **C. Paid boost / promoted post** | ✅ Pago | Cero | Auto but $$ | ~2h + ongoing budget |

Default to A. Only consider B if the client explicitly accepts the account-loss risk in writing AND uses a dedicated account (never the personal one).

## The pattern (4 pieces)

### 1. Schema — targets list + share tracking

Two D1 tables:

```sql
CREATE TABLE IF NOT EXISTS <feature>_share_targets (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  external_id     TEXT    NOT NULL UNIQUE,    -- e.g. FB group id, IG handle
  name            TEXT    NOT NULL,            -- human label for UI
  url             TEXT    NOT NULL,            -- direct deep-link to compose
  role            TEXT    NOT NULL DEFAULT 'member' CHECK (role IN ('member','admin','mod')),
  enabled         INTEGER NOT NULL DEFAULT 1  CHECK (enabled IN (0,1)),
  display_order   INTEGER NOT NULL DEFAULT 0,
  added_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS <feature>_shares (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  source_post_id  INTEGER NOT NULL REFERENCES <feature>_posts(id) ON DELETE CASCADE,
  target_id       INTEGER NOT NULL REFERENCES <feature>_share_targets(id) ON DELETE CASCADE,
  shared_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  shared_by_user  TEXT,
  status          TEXT    NOT NULL DEFAULT 'shared' CHECK (status IN ('shared','skipped','removed','failed'))
);
CREATE UNIQUE INDEX ux_<feature>_shares_post_target ON <feature>_shares(source_post_id, target_id);
```

### 2. Two API endpoints (gated by your session/auth)

- `POST /api/<feature>/share-recorded` — idempotent UPSERT into `<feature>_shares` (per-cell click record).
- `GET/POST/DELETE /api/<feature>/share-targets` — CRUD for the targets list.

Auth pattern: cookie session (reuse existing auth — don't roll your own).

### 3. The helper page

SSR page that renders, per (post × target) cell, a button that:

1. Copies the post caption to the user's clipboard (`navigator.clipboard.writeText`)
2. Opens the target's compose URL in a new tab (`window.open(url, '_blank', 'noopener')`)
3. Marks the share as `shared` optimistically (UI flips green); on API error rollback.

A secondary OK/✕ button toggles the shared status manually (mistakes, removals, replays).

Key client-side detail: use **event delegation** on a single `document.click` listener — DON'T attach handlers to each button. With 12 posts × 10 targets = 120 buttons, you avoid 120 listeners.

### 4. Optional: humanized share-now reminder

If the user wants to be "reminded" to do today's shares: cron at posting times sends them a notification (email / WhatsApp / Slack) with deep-link to the helper page. Don't auto-share — just nudge.

## Anti-patterns to refuse

- **Don't** wrap a bot inside an "extension/CLI" thinking it's safer. The platform's bot-detection looks at request fingerprint + timing patterns, not where the request came from.
- **Don't** "humanize" timing on a bot (random 30-180s) and call it ToS-compliant. It's still automation; ToS doesn't mention timing.
- **Don't** use the client's personal account for any bot. If they insist, write the risk in plain language and have them sign off. Then strongly prefer a dedicated account they accept losing.
- **Don't** skip the share tracking table. Without it you can't tell which manual actions actually happened, can't generate reports, can't dedupe.

## Telemetry the bot couldn't give you

Because every share is a recorded click, you get:

- Per-target engagement: which groups/audiences convert the most (and lose value the fastest)
- Per-user effort: how much manual time is the helper actually saving vs costing
- Per-post optimization: which posts get shared to fewer targets (signal of low confidence in the post)
- Drop-off patterns: weekday/weekend rhythm of when the manual share actually happens

## Concrete cost calibration

- 12 posts × 10 targets × 8s/cell = **16 min/day** of user manual time
- 24 posts × 10 targets × 8s/cell = **32 min/day** — usually the breaking point. Above this, reduce post count or drop targets, don't add a bot.

## Related skills / patterns

- `cron-bridge-daily-publisher` — the OTHER half of the pipeline (the platform-native auto-publish that this helper extends with manual amplification)
- Memory: `lesson-meta-deprecated-groups-publishing` — the canonical case study for "API for X got killed, what now"
