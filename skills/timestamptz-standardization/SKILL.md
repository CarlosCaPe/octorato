---
name: timestamptz-standardization
description: "Timestamp Standardization (timestamptz)"
metadata:
  short-description: "Timestamp Standardization (timestamptz)"
  original-index: 26
---

# Timestamp Standardization (timestamptz)

> Source: [PostgreSQL Best Practices](../DOCUMENTS/PostgreSQL_BestPractices_Azure.md)
> -- "Use timestamptz (UTC). Avoid timezone-naive types."

## What

Converting all `timestamp without time zone` columns to `timestamptz`
(timestamp with time zone) and ensuring UTC semantics across the schema.

## Why

`timestamp without time zone` stores a bare datetime with **no timezone
information**. PostgreSQL interprets it differently depending on the session's
`TimeZone` setting. This causes:
- Ambiguous time values across servers, clients, and time zones
- Wrong results in scheduled jobs that cross DST boundaries
- Incorrect ordering/filtering when Azure servers default to UTC but
  clients assume local time
- Silent data corruption when aggregating timestamps from multiple zones

`timestamptz` stores the value in UTC internally and converts for display
based on the session timezone. This eliminates all ambiguity.

**Official PG 16 specification** (datatype-datetime.html):
- Both `timestamp` and `timestamptz` use **8 bytes**, microsecond precision
- `timestamptz` is stored internally as UTC
- On output, the value is converted from UTC to the session's `TimeZone`
- The SQL standard requires plain `timestamp` to mean `timestamp without
  time zone` -- always spell out `timestamptz` explicitly

## How

### Step 1: Assess scope
```sql
-- Find all timestamp columns that are NOT timestamptz
SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public'
  AND data_type = 'timestamp without time zone'
ORDER BY table_name, ordinal_position;
```

### Step 2: Convert with explicit UTC reinterpretation
```sql
ALTER TABLE public."MyTable"
    ALTER COLUMN "CreatedDate" TYPE timestamptz
    USING "CreatedDate" AT TIME ZONE 'UTC';
```

The `AT TIME ZONE 'UTC'` clause tells PostgreSQL: "these existing values
were meant to be UTC -- store them as UTC timestamptz."

### Step 3: Handle dependent views
Views that SELECT timestamp columns will break if the underlying type
changes. Drop and recreate them:
```sql
-- Save view definition
SELECT pg_get_viewdef('public."MyView"'::regclass, true);

-- Drop view
DROP VIEW IF EXISTS public."MyView";

-- Alter column type
ALTER TABLE public."MyTable"
    ALTER COLUMN "CreatedDate" TYPE timestamptz
    USING "CreatedDate" AT TIME ZONE 'UTC';

-- Recreate view
CREATE VIEW public."MyView" AS ...;
```

### Step 4: Set default for new rows
```sql
ALTER TABLE public."MyTable"
    ALTER COLUMN "CreatedDate" SET DEFAULT now();
    -- now() returns timestamptz, not timestamp
```

## Decision Matrix

| Scenario | Use |
|----------|-----|
| Any new column storing "when something happened" | `timestamptz NOT NULL DEFAULT now()` |
| Columns storing a user-entered date only (no time) | `date` |
| Columns storing a duration or interval | `interval` |
| Legacy column with `timestamp without time zone` | Convert to `timestamptz` |

## Key PostgreSQL Behavior

```sql
-- Session timezone affects display, NOT storage
SET timezone = 'America/Los_Angeles';
SELECT now();  -- displays in Pacific time
SELECT now() AT TIME ZONE 'UTC';  -- displays in UTC

-- timestamptz stores in UTC regardless of session
INSERT INTO t (ts) VALUES ('2026-03-04 10:00:00-05');
-- Stored as: 2026-03-04 15:00:00+00 (UTC)
```

## When to Use

- Every table audit that finds `timestamp without time zone` columns
- Every new table definition (always use `timestamptz`)
- After audit findings flag timestamp type inconsistencies

## Where We Used It

- ****: Converted ALL Scribe tables to timestamptz (original ticket)
- ****: Standardized AuditLog/ErrorLog timestamps
- ****: Migrated 15 Feature Flag columns to timestamptz
- ****: Converted 65 myapp columns to timestamptz
- **scheduling Audit**: Finding #2 flagged 28 columns across 12 tables

## Related Skills

- **Skill #07** (Backward Compatibility) -- app code may assume naive timestamps
- **Skill #04** (Idempotent Design) -- check column type before converting

## References

- [PostgreSQL Best Practices](../DOCUMENTS/PostgreSQL_BestPractices_Azure.md)
  -- "Schema design and data types" and Backlog #2
- [scheduling Audit TDD](../DOCUMENTS/scheduling_DB_Audit_TDD.md)
  -- Finding #2

## Gotchas

- `ALTER COLUMN TYPE timestamptz` rewrites the table -- locks it briefly;
  on very large tables, plan for downtime or use a staged approach
- Views that reference the column must be dropped first and recreated after
- If the server timezone is NOT UTC, `AT TIME ZONE 'UTC'` is critical --
  without it, PostgreSQL assumes the session timezone
- Application code that formats timestamps without timezone info may display
  differently after conversion
- `created_at` defaults should use `now()` (returns timestamptz), not
  `CURRENT_TIMESTAMP` (same, but `now()` is more portable in PL/pgSQL)

---

*Category: DDL | Origin: , , , *
