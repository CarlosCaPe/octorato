---
name: data-retention-policy-lifecycle
description: "Data Retention Policy Lifecycle"
metadata:
  short-description: "Data Retention Policy Lifecycle"
  original-index: 21
---

# Data Retention Policy Lifecycle

## What

A five-phase approach to implementing data retention policies in PostgreSQL:
size analysis, rule definition, maintenance procedure, scheduled execution,
and validation with rollback.

## Why

Tables like audit logs, error logs, and shift history grow unbounded. Without
a retention policy, they consume storage, slow backups, and degrade query
performance. A proper retention lifecycle ensures data is purged safely,
automatically, and with full audit trail.

## How

### Phase 1: Size analysis
```sql
-- How big is the table? How fast is it growing?
SELECT
    pg_size_pretty(pg_total_relation_size('"ShiftAuditLog"')) AS total_size,
    (SELECT COUNT(*) FROM public."ShiftAuditLog") AS row_count,
    MIN("CreatedDate") AS oldest_row,
    MAX("CreatedDate") AS newest_row
FROM public."ShiftAuditLog";
```

### Phase 2: Rule definition
Document the retention rule with business justification:
```markdown
| Table | Retention | Justification |
|-------|-----------|---------------|
| ShiftAuditLog | 90 days | Audit requirement: 90-day lookback |
| ErrorLog | 30 days | Debugging window: 30 days max |
| RefreshTokens | 7 days past expiry | Expired tokens have no value |
```

### Phase 3: Maintenance procedure
```sql
CREATE OR REPLACE PROCEDURE maintenance.purge_shift_audit_log(
    p_retention_days int DEFAULT 90
)
LANGUAGE plpgsql AS $$
DECLARE
    v_cutoff timestamptz;
    v_deleted bigint;
BEGIN
    v_cutoff := now() - (p_retention_days || ' days')::interval;

    DELETE FROM public."ShiftAuditLog"
    WHERE "CreatedDate" < v_cutoff;

    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RAISE NOTICE 'Purged % rows older than %', v_deleted, v_cutoff;
END;
$$;
```

### Phase 4: Schedule via pg_cron (see Skill #16 for full pg_cron patterns)
```sql
SELECT cron.schedule(
    'purge-shift-audit-log',
    '0 3 * * 0',  -- weekly, Sunday 3 AM
    $$CALL maintenance.purge_shift_audit_log(90)$$
);
```

### Phase 5: Validate + rollback plan
```sql
-- Validate: check job ran and purged rows
SELECT * FROM cron.job_run_details
WHERE jobid = (SELECT jobid FROM cron.job WHERE jobname = 'purge-shift-audit-log')
ORDER BY start_time DESC LIMIT 5;

-- Rollback: disable if needed
SELECT cron.unschedule('purge-shift-audit-log');
```

## Supporting indexes
Always ensure the retention column is indexed (Skill #10):
```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_shiftauditlog_createddate
    ON public."ShiftAuditLog" ("CreatedDate");
```

Without this index, the DELETE does a sequential scan of the entire table.

## When to Use

- Any table that grows unbounded (audit logs, error logs, session data)
- After audit findings flag tables with no retention strategy
- When storage costs or backup times become a concern

## Where We Used It

- ****: Full 5-phase retention lifecycle for ShiftAuditLog (90-day retention)
- ****: Retention policy indexes for logging tables
- ****: Token purge via pg_cron (simplified retention)

## Related Skills

- **Skill #16** (pg_cron Scheduled Maintenance) -- scheduling engine for Phase 4
- **Skill #10** (Index CONCURRENTLY) -- supporting indexes on retention columns
- **Skill #20** (Procedure Hardening) -- error handling in the purge procedure

## References

- [PostgreSQL Best Practices](../DOCUMENTS/PostgreSQL_BestPractices_Azure.md)
  -- see Backlog #13 (Log rotation without partitioning) and
  "Maintenance, vacuum, and bloat" section

## Gotchas

- **Test the DELETE query first** with `SELECT COUNT(*)` before running the purge
- Large deletes can bloat the table (dead tuples) -- schedule `VACUUM` after
- Consider batched deletes for very large tables (delete 10K rows at a time)
- Always index the retention column BEFORE scheduling the purge job
- Document the retention rule in the ticket README -- future engineers need
  to know WHY 90 days was chosen

---

*Category: Process | Origin: , , *
