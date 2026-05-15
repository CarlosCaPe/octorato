---
name: pg-cron-scheduled-maintenance
description: "pg_cron Scheduled Maintenance"
metadata:
  short-description: "pg_cron Scheduled Maintenance"
  original-index: 16
---

# pg_cron Scheduled Maintenance

## What

Using PostgreSQL's `pg_cron` extension to schedule recurring database maintenance
jobs -- data purges, retention enforcement, statistics refresh -- directly inside
the database engine, without external schedulers.

## Why

External schedulers (cron, Azure Automation, Task Scheduler) add moving parts:
credentials, network access, deployment pipelines. `pg_cron` runs inside PostgreSQL
itself -- no network hops, no external auth, no separate deployment. The job
definition lives alongside the data it maintains.

## How

### Step 1: Enable the extension
```sql
CREATE EXTENSION IF NOT EXISTS pg_cron;
```

### Step 2: Create the maintenance procedure
```sql
CREATE OR REPLACE PROCEDURE maintenance.purge_expired_tokens()
LANGUAGE plpgsql AS $$
DECLARE
    v_deleted bigint;
BEGIN
    DELETE FROM public."RefreshTokens"
    WHERE "ExpiresAt" < now() - interval '7 days';

    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RAISE NOTICE 'Purged % expired tokens', v_deleted;
END;
$$;
```

### Step 3: Schedule the job
```sql
-- Run every hour at minute 0
SELECT cron.schedule(
    'purge-expired-tokens',     -- job name
    '0 * * * *',                -- cron expression
    $$CALL maintenance.purge_expired_tokens()$$
);
```

### Step 4: Validate
```sql
-- Check job is registered
SELECT jobid, jobname, schedule, command
FROM cron.job
WHERE jobname = 'purge-expired-tokens';

-- Check execution history
SELECT jobid, start_time, end_time, status, return_message
FROM cron.job_run_details
ORDER BY start_time DESC
LIMIT 10;
```

### Step 5: Rollback plan
```sql
SELECT cron.unschedule('purge-expired-tokens');
DROP PROCEDURE IF EXISTS maintenance.purge_expired_tokens();
```

## When to Use

- Expired data cleanup (tokens, sessions, logs)
- Retention policy enforcement (delete rows older than N days)
- Statistics refresh (`ANALYZE` on hot tables)
- Any recurring task that only touches data inside the database

## Where We Used It

- ****: Hourly purge of expired refresh tokens
- ****: Retention policy for ShiftAuditLog via scheduled procedure

## Related Skills

- **Skill #21** (Data Retention Lifecycle) -- uses pg_cron for retention scheduling
- **Skill #18** (Schema Separation) -- maintenance procedures in `maintenance` schema

## References

- [PostgreSQL Best Practices](../DOCUMENTS/PostgreSQL_BestPractices_Azure.md)
  -- see Backlog #13 (Log rotation mechanism)

## Gotchas

- `pg_cron` runs jobs in the `postgres` database by default -- use
  `cron.schedule_in_database()` for other databases on Azure Flexible Server
- Jobs run as the `pg_cron` superuser -- ensure procedures have proper
  security context (`SECURITY DEFINER` if needed)
- Azure Flexible Server requires `pg_cron` in `shared_preload_libraries`
  (set via Portal > Server parameters)
- Always include a validation step: check `cron.job_run_details` after first run
- Include a rollback script (`cron.unschedule`) in the ticket

---

*Category: Tooling | Origin: , *
