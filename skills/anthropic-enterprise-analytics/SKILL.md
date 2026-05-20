---
name: anthropic-enterprise-analytics
description: "Pull Anthropic's Admin API usage_report into ~/.claude/analytics/ so brain-digest can reconcile estimated cost (from session JSONL list-price math) against actual billed cost (from Anthropic). Closes the estimated-vs-billed gap that any operator running on Pro/Max/Enterprise has."
metadata:
  short-description: "Vendor-side cost truth — pulls per-user / per-key actuals from the Anthropic Admin API and reconciles them with the brain's own estimate"
---

# Anthropic Enterprise Analytics — ingestion

## What this skill is

The fourth and final block of the FinOps pipeline. The first three
(per-arm rollup, cost-spike watchdog, budget caps) all run on the
brain's *estimated* USD — list-price math applied to token counts read
from native Claude Code session JSONLs.

The estimate is good enough for budget caps and spike detection, but it
is **not** what Anthropic actually bills the operator. The Admin API
exposes the truth: per-user, per-API-key, per-day cost figures with
Anthropic's actual rate card applied (including any enterprise
discounts).

This skill closes the gap. It pulls the Admin API daily, writes the
data to a private directory, and brain-digest renders a reconciliation
row alongside the per-arm estimate.

## When to use

- You are on **Anthropic Enterprise / Team** with admin scope on the
  organization (the regular per-user API key won't work).
- You want the brain digest to surface "estimated $X, billed $Y, delta
  Z%" so you catch any drift between the brain's list-price math and
  Anthropic's actual invoice — usually drift indicates either a model
  pricing change you haven't picked up in `_pricing.py` or a cache-read
  classification mismatch.
- You want to bill clients against *actual* spend, not estimated.

If you are on Pro/Max only, this skill is dormant — the script exits
cleanly with "not configured" and the rest of the FinOps pipeline keeps
running on estimates.

## How to set up

### 1. Mint an Admin API key

In the Anthropic Console → **Settings → API keys → Admin keys**. Create
one with scope sufficient to read `usage_report`. Store it locally:

```bash
echo 'export ANTHROPIC_ADMIN_API_KEY="sk-ant-admin-..."' >> ~/.profile
# (or your shell's equivalent — never commit this to any repo)
```

If your account spans multiple organizations, also set
`ANTHROPIC_ORG_ID`.

### 2. Run it once manually to verify

```bash
python3 ~/.claude/scripts/anthropic-analytics-pull.py --dry-run
# Confirms env vars + the URL it would hit.

python3 ~/.claude/scripts/anthropic-analytics-pull.py --days 7
# Writes ~/.claude/analytics/anthropic-<today>.jsonl with 7 days of rows.
```

### 3. Schedule the daily pull

Add to your crontab (next to the brain-digest cron):

```cron
# Anthropic Admin Analytics — daily reconciliation pull at 09:30 MX local
30 15 * * * /usr/bin/python3 ~/.claude/scripts/anthropic-analytics-pull.py \
  >> ~/.claude/analytics/cron.log 2>&1
```

The cron runs *after* brain-digest (which fires at 15:00 UTC), so the
reconciliation lands on the next morning's digest.

### 4. Brain-digest reconciliation

`brain-digest.py` automatically reads the latest
`analytics/anthropic-*.jsonl` file (if present) and adds a row to the
Cost section showing **Estimated (Octorato) vs Billed (Anthropic)** and
the delta percentage. If the delta is >20% for two consecutive days, a
note flags it for operator review (drift likely indicates a stale
pricing dict in `_pricing.py`).

## What goes in analytics/

Each pull writes one JSONL line per usage row returned by the Admin
API. The exact schema is whatever Anthropic returns — we pass it
through verbatim so the operator doesn't lose information when
Anthropic adds fields. Typical fields per Anthropic's docs:

- `date` or `time_bucket`
- `model`
- `tokens.input`, `tokens.output`, `tokens.cache_creation`,
  `tokens.cache_read`
- `usd_amount` or `usd_cost`
- `api_key_id` (anonymized)

The directory is **gitignored** (`/analytics/` rule in `~/.claude/.gitignore`)
because it contains vendor billing data — never enters the public brain
repo.

## Anti-patterns

- **Committing the admin key.** It grants org-wide usage visibility.
  Anthropic publishes an audit trail of admin-key reads; rotate
  immediately on accidental commit.
- **Skipping the dry-run.** The Admin API endpoint has changed once
  already (early 2026); a dry-run catches a stale base URL before the
  cron is firing daily.
- **Relying on this for active enforcement.** The Admin API is an
  *after-the-fact* report — a runaway agent burning $5000 in an hour
  shows up on tomorrow's pull, not in time to stop. That's what
  `budget-check.py` (Feature 3) is for; this skill is the truth-table,
  not the brake pedal.

## Lessons Learned

<!-- Append as the operator runs reconciliations and discovers drift
patterns or schema changes in the Anthropic Admin API. -->
