---
name: pg-stat-statements-observability
description: "pg_stat_statements Query Observability"
metadata:
  short-description: "pg_stat_statements Query Observability"
  original-index: 33
---

# pg_stat_statements Query Observability

> Source: [PostgreSQL Best Practices](../DOCUMENTS/PostgreSQL_BestPractices_Azure.md)
> -- "Server configuration", 

## What

Enabling and using the `pg_stat_statements` extension to capture per-query
performance metrics (calls, total time, mean time, rows, shared blocks).
This is the primary tool for identifying slow queries, regression, and
optimization opportunities.

## Why

Without query-level metrics:
- Slow queries hide behind aggregate server metrics (CPU, IOPS)
- Index optimization is guesswork -- you cannot tell which queries dominate
- Performance regressions after deployments go undetected
- Capacity planning has no data foundation

`pg_stat_statements` is lightweight (< 1% overhead), built into PostgreSQL,
and available on Azure Flexible Server as a loadable module.

## How

### Enable the extension (Azure Flexible Server)

1. Azure Portal > Server Parameters:
   ```text
   shared_preload_libraries = pg_stat_statements   -- requires restart
   pg_stat_statements.track = all                  -- track all statements
   pg_stat_statements.max = 5000                   -- max tracked queries
   ```
2. Restart the server (required for `shared_preload_libraries`).
3. Create the extension in each database:
   ```sql
   CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
   ```

### Top 10 queries by total execution time

```sql
SELECT
    calls,
    ROUND(total_exec_time::numeric, 2)       AS total_ms,
    ROUND(mean_exec_time::numeric, 2)        AS mean_ms,
    ROUND(min_exec_time::numeric, 2)         AS min_ms,
    ROUND(max_exec_time::numeric, 2)         AS max_ms,
    rows,
    LEFT(query, 120)                         AS query_preview
FROM pg_stat_statements
ORDER BY total_exec_time DESC
LIMIT 10;
```

### Top 10 queries by mean execution time (slow outliers)

```sql
SELECT
    calls,
    ROUND(mean_exec_time::numeric, 2)        AS mean_ms,
    ROUND(total_exec_time::numeric, 2)       AS total_ms,
    rows,
    LEFT(query, 120)                         AS query_preview
FROM pg_stat_statements
WHERE calls > 10                             -- ignore one-off admin queries
ORDER BY mean_exec_time DESC
LIMIT 10;
```

### Top 10 queries by shared buffer reads (I/O heavy)

```sql
SELECT
    calls,
    shared_blks_read + shared_blks_hit       AS total_blks,
    ROUND(
        100.0 * shared_blks_hit /
        NULLIF(shared_blks_read + shared_blks_hit, 0), 2
    )                                        AS cache_hit_pct,
    ROUND(mean_exec_time::numeric, 2)        AS mean_ms,
    LEFT(query, 120)                         AS query_preview
FROM pg_stat_statements
ORDER BY shared_blks_read DESC
LIMIT 10;
```

### Reset statistics (after optimization to re-baseline)

```sql
-- Reset ALL query stats (use sparingly)
SELECT pg_stat_statements_reset();
```

### Check if extension is active

```sql
SELECT * FROM pg_available_extensions
WHERE name = 'pg_stat_statements';

-- If installed, verify it is tracking
SELECT COUNT(*) AS tracked_queries
FROM pg_stat_statements;
```

### Combine with slow query logging

```text
-- Server parameter (Azure Portal)
log_min_duration_statement = 250    -- log queries > 250ms

-- This gives you two layers:
-- 1. pg_stat_statements: aggregated stats for ALL queries
-- 2. PostgreSQL log: individual slow query events with parameters
```

## Key Metrics to Monitor

| Metric | What It Tells You | Action Threshold |
|--------|------------------|-----------------|
| `total_exec_time` | Cumulative CPU cost | Top query > 50% of total |
| `mean_exec_time` | Per-call latency | > 100ms for OLTP queries |
| `calls` | Query frequency | Top query > 10K calls/hour |
| `rows` | Rows returned per call | > 10K rows (missing pagination?) |
| `shared_blks_read` | Disk I/O | High reads = missing index or seq scan |
| `cache_hit_pct` | Buffer cache effectiveness | < 95% = under-provisioned memory |

## When to Use

- After enabling on a new server  pattern)
- Before and after index changes to measure impact
- During audit investigations to find optimization targets
- Periodically (weekly/monthly) for capacity planning

## Where We Used It

- ****: Enabled `pg_stat_statements` on DEV and QA servers
- **Best Practices**: Listed as mandatory server configuration
- **Audit TDDs**: Query-level observability requirement

## Related Skills

- **Skill #29** (EXPLAIN ANALYZE) -- detailed plan for individual queries
- **Skill #30** (Autovacuum & Bloat) -- bloat causes seq scans, visible here
- **Skill #32** (Connection Pooling) -- slow queries identified here, timeouts set there

## References

- [PostgreSQL Best Practices](../DOCUMENTS/PostgreSQL_BestPractices_Azure.md)
  -- "Server configuration" section
- [User Management Audit TDD](../DOCUMENTS/user_mgmt_DB_Audit_TDD.md)
  -- "Query-level observability" requirement

## Gotchas

- `shared_preload_libraries` change requires a **server restart** on Azure
  Flexible Server -- coordinate with ops
- Statistics persist across connections but are lost on server restart
  unless `pg_stat_statements.save = on` (default on Azure)
- `pg_stat_statements_reset()` clears ALL stats -- there is no per-query
  reset; use it only after a known baseline change
- The `query` column normalizes literal values to `$1, $2, ...` -- you
  cannot see actual parameter values (by design, for security)
- `pg_stat_statements.max = 5000` means the 5001st unique query evicts
  the least-used entry -- increase if your app has many dynamic queries
- On Azure, you may need the `azure_pg_admin` role to create the extension

---

*Category: Tooling | Origin: *
