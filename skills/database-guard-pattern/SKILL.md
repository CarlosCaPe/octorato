---
name: database-guard-pattern
description: "Database Guard Pattern"
metadata:
  short-description: "Database Guard Pattern"
  original-index: 03
---

# Database Guard Pattern

## What

A safety check at the top of every DDL script that verifies the current
database name matches an expected pattern. If the script connects to the wrong
database, it aborts immediately.

## Why

One misclick in a connection string can point a destructive script at the wrong
database. A database guard is the last line of defense. It costs one line of SQL
and prevents catastrophic mistakes.

## How

```sql
DO $$
DECLARE
    v_db text := current_database();
BEGIN
    IF v_db NOT ILIKE 'myapp%' THEN
        RAISE NOTICE 'SAFETY: This script only runs on myapp databases';
        RAISE NOTICE '  Current database: %', v_db;
        RAISE EXCEPTION 'SAFETY: Wrong database -- aborting all phases';
    END IF;
END $$;
```

Pattern variations:
- Exact match: `v_db <> 'MyDatabase'`
- Prefix match: `v_db NOT ILIKE 'MyApp%'` (covers `_DEV`, `_QA`, `_PROD`)
- Suffix match: `v_db NOT ILIKE '%_appointments'`

## When to Use

- **Every** DDL script. No exceptions.
- Especially important for scripts that run across multiple environments

## Where We Used It

- **Project A**: `myapp%` guard
- **Project B**: `scheduler%` guard
- **Project C**: `analytics%` guard

## Gotchas

- Use `ILIKE` (case-insensitive) because database names can vary in casing
- Place the guard BEFORE any gap analysis -- fail fast
- The guard must use `RAISE EXCEPTION`, not `RETURN` -- `RETURN` only exits
  the current DO block, while `RAISE EXCEPTION` aborts execution

---

*Category: Safety | Origin: *
