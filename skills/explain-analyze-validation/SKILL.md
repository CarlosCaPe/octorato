---
name: explain-analyze-validation
description: "EXPLAIN ANALYZE Query Validation"
metadata:
  short-description: "EXPLAIN ANALYZE Query Validation"
  original-index: 29
---

# EXPLAIN ANALYZE Query Validation

> Source: [PostgreSQL Best Practices](../DOCUMENTS/PostgreSQL_BestPractices_Azure.md)
> -- "Use EXPLAIN (ANALYZE, BUFFERS) to understand plans and I/O"

## What

Using `EXPLAIN (ANALYZE, BUFFERS)` to validate that queries use the intended
indexes and access paths. This is the evidence-based way to confirm that index
changes, schema changes, or query rewrites actually improve performance.

## Why

"I added an index" does not mean "the query uses the index." PostgreSQL's
query planner makes autonomous decisions based on statistics, table size,
and cost estimates. `EXPLAIN ANALYZE` shows the **actual** execution plan
with real timing and I/O counts -- not guesses.

Without this skill, we're guessing about performance and may:
- Add indexes that are never used (write overhead for no read benefit)
- Miss sequential scans on large tables
- Fail to detect that an index scan is actually slower than a seq scan
- Ignore buffer cache misses that cause I/O spikes

## How

### Basic EXPLAIN ANALYZE
```sql
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT "HospitalId", COUNT(*)
FROM public."AppointmentInfo"
WHERE "StatusId" = 1
GROUP BY "HospitalId";
```

### Reading the output
```
Seq Scan on "AppointmentInfo"  (cost=0.00..15234.00 rows=5000 width=12)
                               (actual time=0.015..45.230 rows=4892 loops=1)
  Filter: ("StatusId" = 1)
  Rows Removed by Filter: 95108
  Buffers: shared hit=8234 read=1200
Planning Time: 0.145 ms
Execution Time: 45.890 ms
```

### Key metrics to watch

| Metric | What It Means | Red Flag |
|--------|---------------|----------|
| `Seq Scan` | Full table scan | On tables > 10K rows with a WHERE clause |
| `Index Scan` | Using an index | Good -- verify it's the right index |
| `Index Only Scan` | Satisfied entirely from index | Best case -- no table lookup |
| `Bitmap Index Scan` | Combines multiple indexes | OK for complex predicates |
| `shared hit` | Pages found in cache | High = good |
| `shared read` | Pages read from disk | High = possible I/O problem |
| `Rows Removed by Filter` | Rows scanned but not returned | High = wrong index or missing index |
| `actual rows` vs `rows` | Actual vs estimated row count | Large mismatch = stale stats, run ANALYZE |

### Before/after comparison pattern
```sql
-- Before adding index
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM public."Recording" WHERE "HospitalId" = 42;
-- Seq Scan, 45ms, 8234 buffers

-- After adding index
CREATE INDEX CONCURRENTLY ix_recording_hospitalid
    ON public."Recording" ("HospitalId");

EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM public."Recording" WHERE "HospitalId" = 42;
-- Index Scan using ix_recording_hospitalid, 0.8ms, 12 buffers
```

### Validate index is used
```sql
-- Check if an index is being used at all
SELECT indexrelname, idx_scan, idx_tup_read, idx_tup_fetch
FROM pg_stat_user_indexes
WHERE schemaname = 'public'
  AND relname = 'Recording'
ORDER BY idx_scan DESC;
```

### Covering index validation
```sql
-- If you expect an Index Only Scan, ANALYZE first
ANALYZE public."Recording";

EXPLAIN (ANALYZE, BUFFERS)
SELECT "HospitalId", "CreatedDate"
FROM public."Recording"
WHERE "HospitalId" = 42;
-- Should show "Index Only Scan" if covering index includes both columns
```

## Common Plan Problems

| Problem | Symptom | Fix |
|---------|---------|-----|
| Seq Scan on filtered large table | `Rows Removed by Filter` >> `actual rows` | Add index on WHERE column |
| Index exists but not used | `Seq Scan` despite index | Run `ANALYZE`; check data distribution |
| Bitmap scan on single-column query | Multiple index ops | Consider composite index |
| Nested Loop with high loops count | `loops=100000` | Check JOIN order; add index on inner table |
| Sort on disk | `Sort Method: external merge` | Increase `work_mem` or add ORDER-matching index |

## When to Use

- After adding or dropping any index (validate it's used/unused)
- Before and after schema changes (prove no regression)
- During audit TDD validation (evidence for index recommendations)
- When a query is reported as slow

## Where We Used It

- **Audit TDDs**: All three (feature_flags, user_mgmt, scheduling)
  recommend EXPLAIN validation before implementing index recommendations
- ****: Used EXPLAIN to validate composite index replacement
- ****: Validated supporting indexes improve FK join paths

## Related Skills

- **Skill #10** (Index CONCURRENTLY) -- create the indexes
- **Skill #15** (Post-Check Verification) -- EXPLAIN as post-check evidence
- **Skill #33** (pg_stat_statements) -- find which queries to EXPLAIN

## References

- [PostgreSQL Best Practices](../DOCUMENTS/PostgreSQL_BestPractices_Azure.md)
  -- "Query performance and troubleshooting" section
- [PostgreSQL EXPLAIN docs](https://www.postgresql.org/docs/current/sql-explain.html)

## Gotchas

- `EXPLAIN ANALYZE` **actually runs the query** -- use with care on
  destructive statements (wrap in `BEGIN; EXPLAIN ANALYZE DELETE ...; ROLLBACK;`)
- Always `ANALYZE` the table before EXPLAIN if you've recently loaded data
  -- stale stats cause the planner to make bad estimates
- `BUFFERS` output requires `track_io_timing = on` for accurate I/O times
- Plans can differ between DEV and QA/PROD due to different data volumes
  and statistics -- always validate in the target environment
- Don't optimize queries until you see the plan -- intuition is often wrong

---

*Category: Process | Origin: Audit TDDs, PostgreSQL Best Practices*
