---
name: fillfactor-storage-tuning
description: "Fillfactor & Storage Parameter Tuning"
metadata:
  short-description: "Fillfactor & Storage Parameter Tuning"
  original-index: 23
---

# Fillfactor & Storage Parameter Tuning

## What

Adjusting the `fillfactor` storage parameter on tables and indexes to optimize
for workload patterns. Fillfactor controls how much of each 8KB page PostgreSQL
fills during INSERT/COPY, leaving the rest for in-page HOT updates.

## Why

Default fillfactor differs by object type (PG 16 docs):
- **Tables**: 100 (complete packing) -- `sql-createtable.html`
- **B-tree indexes**: 90 (10% reserved for page splits) -- `sql-createindex.html`

For tables with frequent UPDATEs, fillfactor 100 forces every update to
create a new tuple on a different page, causing:
- Table bloat (dead tuples accumulate)
- Index bloat (new index entries for each tuple version)
- More I/O (random reads across pages)
- More frequent VACUUM cycles

Lowering fillfactor to 90 leaves 10% free space per page, enabling
**Heap-Only Tuples (HOT)** updates that reuse space in-place.

## How

### Analyze the workload first
```sql
-- Check update frequency vs insert frequency
SELECT
    relname,
    n_tup_ins AS inserts,
    n_tup_upd AS updates,
    n_tup_del AS deletes,
    ROUND(100.0 * n_tup_upd / NULLIF(n_tup_ins + n_tup_upd + n_tup_del, 0), 1)
        AS update_pct
FROM pg_stat_user_tables
WHERE schemaname = 'public'
ORDER BY n_tup_upd DESC;
```

### Decision matrix

| Update % | Fillfactor | Rationale |
|----------|------------|-----------|
| < 10% | 100 (default) | Mostly INSERT-only, maximize density |
| 10-50% | 90 | Balance between density and HOT updates |
| > 50% | 80-85 | Heavy UPDATE workload, maximize HOT success |
| Append-only (logs) | 100 | Never updated, maximize density |

### Apply fillfactor
```sql
-- On the table (affects future INSERTs and rewrites)
ALTER TABLE public."AppointmentInfo"
    SET (fillfactor = 90);

-- On a BTREE index
ALTER INDEX public."PK_AppointmentInfo"
    SET (fillfactor = 90);

-- IMPORTANT: fillfactor only applies to NEW pages.
-- To apply to existing data, REINDEX or VACUUM FULL:
REINDEX INDEX CONCURRENTLY public."PK_AppointmentInfo";
```

### Validate HOT update effectiveness
```sql
SELECT
    relname,
    n_tup_hot_upd,
    n_tup_upd,
    ROUND(100.0 * n_tup_hot_upd / NULLIF(n_tup_upd, 0), 1) AS hot_pct
FROM pg_stat_user_tables
WHERE n_tup_upd > 0
ORDER BY n_tup_upd DESC;
```

Target: HOT update percentage > 90% for update-heavy tables.

## When to Use

- After audit findings identify high-churn tables with bloat
- When `pg_stat_user_tables` shows low HOT update percentages
- For PK indexes on frequently-updated tables
- During initial schema optimization

## Where We Used It

- ****: Set fillfactor=90 on high-churn PK indexes
- ****: Reviewed and validated fillfactor settings across all indexes

## References

- [PostgreSQL Best Practices](../DOCUMENTS/PostgreSQL_BestPractices_Azure.md)
  -- see "Maintenance, vacuum, and bloat" section

## Gotchas

- Fillfactor changes only affect **new** pages -- existing pages need
  `REINDEX CONCURRENTLY` or `VACUUM FULL` to reorganize
- Don't set fillfactor too low on large tables -- wastes disk space
- `VACUUM FULL` rewrites the entire table and holds `AccessExclusiveLock`
  -- use `REINDEX CONCURRENTLY` instead for indexes
- Append-only tables (logs, audit trails) should keep fillfactor=100
- `ALTER TABLE SET (fillfactor = N)` acquires `SHARE UPDATE EXCLUSIVE`
  lock -- lightweight, does not block reads or writes
  (PG 16 docs: sql-altertable.html)
- B-tree index default fillfactor is **90**, not 100 -- only lower it
  further for heavily-updated indexes
- Monitor `pg_stat_user_tables.n_tup_hot_upd` after changes to verify impact

---

*Category: Strategy | Origin: , *
