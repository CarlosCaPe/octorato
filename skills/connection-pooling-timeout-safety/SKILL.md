---
name: connection-pooling-timeout-safety
description: "Connection Pooling & Timeout Safety"
metadata:
  short-description: "Connection Pooling & Timeout Safety"
  original-index: 32
---

# Connection Pooling & Timeout Safety

> Source: [PostgreSQL Best Practices](../DOCUMENTS/PostgreSQL_BestPractices_Azure.md)
> -- "Connection management and pooling", "Server configuration"

## What

Configuring connection pool sizing, statement timeouts, and idle transaction
timeouts to prevent resource exhaustion and runaway queries on Azure
Flexible Server.

## Why

PostgreSQL forks a process per connection. Without pooling and timeout
guardrails:
- Burst traffic can exceed `max_connections` (default 100 on small tiers)
- A single unoptimized query can run for hours, holding locks
- Idle transactions hold row-level locks and block autovacuum
- Connection storms during deployments can crash the server

These are infrastructure-level settings, but Data Engineers must understand
them because:
- Migration scripts can trigger long-running DDL
- Bulk INSERT/UPDATE can exceed `statement_timeout`
- DO blocks run as a single statement -- timeout applies to the whole block

## How

### Server Parameters (Azure Portal or CLI)

```text
-- Query timeout (milliseconds). 0 = no limit.
statement_timeout = 30000          -- 30 seconds for app queries
-- Long migrations may need temporary increase:
-- SET LOCAL statement_timeout = '5min';

-- Kill idle-in-transaction sessions (milliseconds)
idle_in_transaction_session_timeout = 60000   -- 60 seconds

-- Slow query logging threshold (milliseconds)
log_min_duration_statement = 250              -- log queries > 250ms
```

### Application Pool Sizing (Node.js / knex)

```js
// knexfile.js -- recommended pool configuration
pool: {
    min: 2,
    max: 10,
    acquireTimeoutMillis: 10000,   // fail fast if pool exhausted
    idleTimeoutMillis: 30000,      // release idle connections
    reapIntervalMillis: 1000       // check for idle connections
}
```

**Pool sizing rule of thumb** from Best Practices:
```
max_pool_size = (core_count * 2) + effective_spindle_count
```
For Azure B1ms (1 vCPU, no spindles): `max = (1 * 2) + 1 = 3`
For Azure D2s_v3 (2 vCPU): `max = (2 * 2) + 1 = 5`

### Temporary timeout override for migrations

```sql
-- Inside a migration transaction
BEGIN;
    SET LOCAL statement_timeout = '5min';

    -- Long-running DDL (e.g., adding column with default)
    ALTER TABLE public."LargeTable"
        ADD COLUMN "IsActive" boolean NOT NULL DEFAULT true;

COMMIT;
-- statement_timeout reverts to server default after COMMIT
```

### Check current settings

```sql
SHOW statement_timeout;
SHOW idle_in_transaction_session_timeout;
SHOW max_connections;

-- Active connections by state
SELECT state, COUNT(*)
FROM pg_stat_activity
GROUP BY state
ORDER BY COUNT(*) DESC;
```

### Monitor connection usage

```sql
SELECT
    usename,
    application_name,
    state,
    query_start,
    NOW() - query_start AS duration,
    LEFT(query, 80) AS query_preview
FROM pg_stat_activity
WHERE state <> 'idle'
ORDER BY duration DESC;
```

## Decision Matrix

| Scenario | statement_timeout | idle_in_transaction |
|----------|------------------|---------------------|
| Web API queries | 30s | 60s |
| Migration scripts | 5min (SET LOCAL) | 60s |
| Bulk data loads | 10min (SET LOCAL) | 60s |
| One-off admin queries | Session-level SET | Not critical |
| pg_cron jobs | Default (30s) | Default (60s) |

## When to Use

- Every application connecting to PostgreSQL (pool sizing)
- Every Azure Flexible Server (timeout configuration)
- Before running migration scripts that may take > 30 seconds

## Where We Applied It

- **knexfile.js**: Pool configuration for audit/migration runner
- **Best Practices**: Documented as mandatory server configuration
- **, **: Timeout considerations during bulk operations

## Related Skills

- **Skill #16** (pg_cron Scheduling) -- scheduled jobs inherit server timeouts
- **Skill #30** (Autovacuum & Bloat) -- idle transactions block autovacuum
- **Skill #33** (pg_stat_statements) -- slow queries identified via observability

## References

- [PostgreSQL Best Practices](../DOCUMENTS/PostgreSQL_BestPractices_Azure.md)
  -- "Connection management and pooling" section
- [PostgreSQL Best Practices](../DOCUMENTS/PostgreSQL_BestPractices_Azure.md)
  -- "Server configuration" section

## Gotchas

- `statement_timeout` applies to the entire DO block, not individual
  statements within it -- a DO block with 10 ALTERs is ONE statement
- `SET LOCAL` only works inside a transaction (`BEGIN...COMMIT`); without
  a transaction, it is equivalent to `SET` (session-level)
- Azure Flexible Server has its own `max_connections` ceiling per tier --
  you cannot SET it beyond the tier limit
- Connection poolers (PgBouncer) may require `transaction` mode, which
  breaks `SET` and prepared statements -- use `SET LOCAL` instead
- `idle_in_transaction_session_timeout` kills the entire session, not just
  the transaction -- the application must handle reconnection

---

*Category: Strategy | Origin: Best Practices*
