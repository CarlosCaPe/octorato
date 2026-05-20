---
name: sentinel-blocks-rerun
description: "Diagnose daily-idempotent endpoints that silently no-op because an earlier same-day run set a 'already-done' sentinel"
metadata:
  short-description: "Daily-idempotent sentinel left over from off-hour run blocks the scheduled cron"
---

# Sentinel Blocks Re-Run

## What

Many daily ingest / publish / fan-out endpoints use a **sentinel** record (KV key,
DB row, file marker) to make themselves idempotent — "did I already run for
`YYYY-MM-DD`?" If yes, return early with `status: "already-done"`.

This is correct behavior, but it has a sharp failure mode: if **any** caller
fires the endpoint for date `T` (a manual test from yesterday's late evening, a
restart-induced retry, a one-off curl), the sentinel for `T` lands. Then the
**actual scheduled cron** for date `T` shows up at its normal time, sees the
sentinel, and skips — producing zero work output for that day, silently.

## When to suspect this

- Daily pipeline reports "ran successfully" (`HTTP 200`, `ok: true`) but **no
  downstream artifacts appeared** (no new posts, no new rows, no new files).
- The response body says `"already-done"` / `"already-bridged"` /
  `"no-candidates"` / `"already-processed"` instead of the expected
  `"scheduled" / "created N items"`.
- Job logs from the day in question show ZERO new records, but the previous
  day's records exist normally.
- Manual re-trigger of the workflow returns the same "already done" response.

## Diagnosis (5-minute playbook)

1. **Read the response body**, not just the HTTP code. A 200 + `"already-done"`
   is a no-op disguised as success.
2. **Find the sentinel key/row**. Search the endpoint code for the
   idempotency check (`if (await get(sentinelKey))`, `SELECT 1 FROM runs WHERE
   day = ?`, file-exists guard, etc.).
3. **Inspect the sentinel timestamp**. If it was created at an unexpected hour
   (e.g., 01:30 instead of the scheduled 14:00), an out-of-band caller wrote it.
4. **Delete the sentinel** for the affected date.
5. **Re-trigger** the workflow / endpoint. It should now respond
   `"scheduled" / "created"` and emit the expected artifacts.
6. **Verify** new artifacts land.

## Fix patterns

### Operational (right now)

```bash
# Delete the offending sentinel
kv delete "<sentinel-key-for-today>"
# Re-fire the scheduled workflow
trigger-workflow daily-job.yml
# Confirm response carries created-count, not already-done
```

### Code-level (prevent recurrence)

Defense in depth — pick the one that fits the system:

| Strategy | Tradeoff |
|---|---|
| Sentinel key includes the **triggering source** (cron-id / manual-id) | Manual triggers no longer block cron, but two crons same day still no-op (usually fine) |
| Sentinel records **what was produced** (count, sample IDs); endpoint returns those on `already-done` | Operator sees that previous run delivered N items; can decide to delete + re-fire |
| Sentinel has a **TTL shorter than the cron interval** (e.g., 6h for a daily cron) | Re-runs within 6h still no-op (correct), runs after 6h treat the day as fresh |
| Endpoint accepts `?force=true` query param that bypasses the sentinel guard | Explicit operator escape hatch with audit |

## Anti-patterns

- **Trusting `HTTP 200` alone**. Always inspect the response body — many idempotent
  endpoints use 200 + status enum, not 200/201 split.
- **Deleting the sentinel without checking what produced it.** If the previous
  run actually did succeed and emit downstream artifacts, deleting + re-running
  produces duplicates.
- **Adding `?force=true` and never logging who used it.** The escape hatch needs
  an audit trail or it becomes the new normal.

## Lessons Learned

<!-- Append new cases as encountered. Include: date, what the sentinel was
keyed on, what triggered the off-hour run, how the duplicate-detection played
out after the fix. -->
