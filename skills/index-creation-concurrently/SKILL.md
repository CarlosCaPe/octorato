---
name: index-creation-concurrently
description: "Index Creation (CONCURRENTLY)"
metadata:
  short-description: "Index Creation (CONCURRENTLY)"
  original-index: 10
---

# Index Creation (CONCURRENTLY)

## What

`CREATE INDEX CONCURRENTLY` builds an index without holding an exclusive lock
on the table. Regular `CREATE INDEX` blocks all writes (INSERT/UPDATE/DELETE)
for the duration of the build. The CONCURRENTLY variant allows writes to
continue while the index is being built.

## Why

On production tables with active traffic, a regular index build can cause
downtime. A 100M-row table might take minutes to index, during which all
writes are blocked. `CONCURRENTLY` eliminates this risk at the cost of a
slightly longer build time.

### Lock comparison (PG 16 docs: explicit-locking.html)

| Mode | Lock Acquired | Blocks Writes? | Blocks Reads? |
|------|---------------|----------------|---------------|
| `CREATE INDEX` | `SHARE` | Yes (INSERT/UPDATE/DELETE blocked) | No |
| `CREATE INDEX CONCURRENTLY` | `SHARE UPDATE EXCLUSIVE` | No | No |

## How

### Basic concurrent index
```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_appointmentinfo_hospitalid
    ON public."AppointmentInfo" ("HospitalId");
```

### Covering index (INCLUDE)
```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_vwr_animalid_covering
    ON analytics."events" ("entity_id")
    INCLUDE ("AnimalName", "Species", "Breed");
```

### Important: Cannot run inside a transaction
```sql
-- This FAILS:
BEGIN;
CREATE INDEX CONCURRENTLY ix_test ON public."MyTable" ("MyCol");
COMMIT;

-- This WORKS (outside any transaction block):
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_test
    ON public."MyTable" ("MyCol");
```

## Index Types We Used

| Type | Purpose | Example |
|------|---------|---------|
| B-tree (default) | Equality and range queries | `WHERE "HospitalId" = 123` |
| Covering (INCLUDE) | Avoid table lookups for common queries | Index-only scans |
| Composite | Multi-column lookups | `WHERE "Col1" = x AND "Col2" = y` |

## When to Use

- Any column used in WHERE, JOIN, or ORDER BY clauses
- FK columns (PostgreSQL does NOT auto-create indexes on FK columns)
- High-cardinality columns that filter large result sets

## Where We Used It

- ****: Index on `AppointmentInfo.HospitalId` (supporting FK)
- ****: Index on `AppointmentInfo.ProviderId` (supporting FK)
- ****: 6 high-value indexes on analytics tables (covering indexes)
- ****: Baseline indexes on DINO_EC tables

## References

- [PostgreSQL Best Practices](../DOCUMENTS/PostgreSQL_BestPractices_Azure.md)
  -- see "Indexing strategy (actual usage)" and Backlog #5 (Advanced indexes)
- [Schema Optimization Appendix](../DOCUMENTS/Schema_Optimization_Appendix.md)
  --  and  index decisions

## Gotchas

- `CONCURRENTLY` cannot run inside a DO block or explicit transaction
- If a concurrent build fails, it leaves an INVALID index -- check with:
  ```sql
  SELECT indexrelid::regclass, indisvalid
  FROM pg_index
  WHERE NOT indisvalid;
  ```
- `IF NOT EXISTS` prevents errors on re-run but does NOT rebuild invalid indexes
- Concurrent builds take ~2x longer than regular builds (two table scans)
- Building many indexes concurrently at once can impact performance

---

*Category: DDL | Origin: , *
