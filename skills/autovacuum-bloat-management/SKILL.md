---
name: autovacuum-bloat-management
description: "Autovacuum & Table Bloat Management"
metadata:
  short-description: "Autovacuum & Table Bloat Management"
  original-index: 30
---

# Autovacuum & Table Bloat Management

> Source: [PostgreSQL Best Practices](../DOCUMENTS/PostgreSQL_BestPractices_Azure.md)
> -- "Maintenance, vacuum, and bloat" section

## What

Monitoring and tuning PostgreSQL's autovacuum system to prevent table and
index bloat. Includes per-table autovacuum parameter tuning for high-churn
tables.

## Why

PostgreSQL uses MVCC (Multi-Version Concurrency Control). Every UPDATE creates
a new row version; DELETE marks the old version as dead. These dead tuples
accumulate as **bloat** until VACUUM reclaims the space.

If autovacuum can't keep up:
- Table size grows beyond the live data size
- Index entries point to dead tuples (index bloat)
- Sequential scans become slower (scanning dead rows)
- `HOT` updates fail more often (no free space on the page)
- Storage costs increase on Azure

## How

### Monitor dead tuples and vacuum activity
```sql
SELECT
    schemaname,
    relname,
    n_live_tup,
    n_dead_tup,
    ROUND(100.0 * n_dead_tup / NULLIF(n_live_tup + n_dead_tup, 0), 1)
        AS dead_pct,
    last_vacuum,
    last_autovacuum,
    last_analyze,
    last_autoanalyze
FROM pg_stat_user_tables
WHERE n_dead_tup > 1000
ORDER BY n_dead_tup DESC;
```

### Check table bloat estimate
```sql
SELECT
    schemaname || '.' || relname AS table_name,
    pg_size_pretty(pg_total_relation_size(relid)) AS total_size,
    pg_size_pretty(pg_relation_size(relid)) AS table_size,
    pg_size_pretty(pg_indexes_size(relid)) AS index_size,
    n_live_tup,
    n_dead_tup
FROM pg_stat_user_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(relid) DESC;
```

### Tune autovacuum for hot tables
```sql
-- High-churn table: vacuum more aggressively
ALTER TABLE public."AuditLog" SET (
    autovacuum_vacuum_scale_factor = 0.05,   -- vacuum at 5% dead (default 20%)
    autovacuum_analyze_scale_factor = 0.02   -- analyze at 2% changes (default 10%)
);

-- Verify settings
SELECT relname, reloptions
FROM pg_class
WHERE relname = 'AuditLog';
```

### Default autovacuum thresholds (PG 16 docs: runtime-config-autovacuum.html)

| Parameter | Default | Meaning |
|-----------|---------|---------||
| `autovacuum_vacuum_threshold` | 50 | Minimum dead tuples before vacuum |
| `autovacuum_vacuum_scale_factor` | 0.20 | Fraction of table that must be dead |
| `autovacuum_vacuum_insert_threshold` | 1000 | Inserts before insert-triggered vacuum (PG 13+) |
| `autovacuum_vacuum_insert_scale_factor` | 0.20 | Fraction of table size for insert-triggered vacuum |
| `autovacuum_analyze_threshold` | 50 | Minimum changes before analyze |
| `autovacuum_analyze_scale_factor` | 0.10 | Fraction of table that must change |

**Trigger formula**: Vacuum runs when
`dead_tuples > threshold + scale_factor * n_live_tup`

For a 1M-row table with defaults: vacuum at 50 + 0.20 * 1,000,000 = **200,050 dead tuples**.
With tuned 0.05: vacuum at 50 + 0.05 * 1,000,000 = **50,050 dead tuples**.

### Manual vacuum (when needed)
```sql
-- Standard vacuum (non-blocking, reclaims dead tuples)
VACUUM (VERBOSE) public."AuditLog";

-- Vacuum + analyze (update planner statistics too)
VACUUM (VERBOSE, ANALYZE) public."AuditLog";

-- VACUUM FULL (rewrites table, reclaims disk space, but LOCKS table)
-- Use only for extreme bloat; prefer REINDEX CONCURRENTLY for indexes
VACUUM FULL public."AuditLog";
```

### Reindex for index bloat
```sql
-- Non-blocking index rebuild
REINDEX INDEX CONCURRENTLY public."ix_auditlog_createddate";

-- Check for invalid indexes (failed concurrent operations)
SELECT indexrelid::regclass, indisvalid
FROM pg_index
WHERE NOT indisvalid;
```

## Decision Matrix

| Scenario | Action |
|----------|--------|
| Dead tuple % < 10% | Normal -- autovacuum handling it |
| Dead tuple % 10-30% | Consider lowering scale_factor |
| Dead tuple % > 30% | Immediate: manual VACUUM; then tune autovacuum |
| Table size >> expected for row count | Possible bloat; check dead_pct |
| After bulk DELETE/UPDATE | Run `VACUUM ANALYZE` manually |
| After index creation | Run `ANALYZE` to update stats |

## When to Use

- During database audits (check bloat across all tables)
- After implementing retention policies (Skill #21) -- large DELETEs cause bloat
- After bulk data operations (imports, migrations, purges)
- When queries suddenly slow down (possible stale stats)

## Where We Used It

- **/**: Fillfactor tuning (related to HOT update optimization)
- **Audit TDDs**: All three audits include autovacuum monitoring recommendations
- ****: After retention DELETE, vacuum needed for ShiftAuditLog

## Related Skills

- **Skill #23** (Fillfactor Tuning) -- fillfactor + autovacuum work together
- **Skill #21** (Data Retention) -- large DELETEs need vacuum follow-up
- **Skill #29** (EXPLAIN ANALYZE) -- verify stats are fresh before trusting plans

## References

- [PostgreSQL Best Practices](../DOCUMENTS/PostgreSQL_BestPractices_Azure.md)
  -- "Maintenance, vacuum, and bloat" section and Backlog #9

## Gotchas

- **Never disable autovacuum** -- the table will bloat and eventually
  approach transaction ID wraparound (catastrophic)
- `VACUUM FULL` acquires `AccessExclusiveLock` -- blocks all access;
  use only as a last resort during maintenance windows
- `VACUUM` reclaims space for reuse but does NOT return it to the OS --
  the table file stays the same size. Only `VACUUM FULL` shrinks the file.
- After large bulk DELETEs, run `VACUUM ANALYZE` to both reclaim space
  and update planner statistics
- On Azure Flexible Server, autovacuum settings can be adjusted via
  Server Parameters in the Azure Portal (server-wide) or per-table via ALTER

---

*Category: Tooling | Origin: Audit TDDs, PostgreSQL Best Practices*
