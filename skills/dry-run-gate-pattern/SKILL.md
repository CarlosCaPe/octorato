---
name: dry-run-gate-pattern
description: "Dry-Run Gate Pattern"
metadata:
  short-description: "Dry-Run Gate Pattern"
  original-index: 02
---

# Dry-Run Gate Pattern

## What

A boolean flag that defaults to `true`, preventing any modifications unless the
caller explicitly opts in. The script runs all analysis and reporting but aborts
before making changes.

## Why

Prevents accidental execution. Every script is **read-only by default**. The DBA
must consciously pass `--execute 1` to apply changes. This is critical when the
same script targets DEV, QA, and PROD.

## How

```sql
DO $$
DECLARE
    dry_run boolean := COALESCE(
        NULLIF(current_setting('da.execute', true), ''),
        '0'
    ) <> '1';
BEGIN
    -- ... gap analysis, reporting ...

    IF dry_run THEN
        RAISE NOTICE 'DRY-RUN COMPLETE -- no changes applied';
        RAISE NOTICE 'To execute, run with --execute 1';
        RAISE EXCEPTION 'DRY-RUN complete -- no changes applied.';
    END IF;
END $$;
```

The runner (`scripts/run_sql_file.js`) sets `da.execute` via:
```sql
SET da.execute = '1';
```

The `COALESCE(NULLIF(...), '0')` expression handles three edge cases:
- Setting not set at all (`current_setting` returns NULL with `true` flag)
  (PG 16 docs: functions-admin.html -- "returns NULL if missing_ok is true")
- Setting set to empty string
- Setting set to '0'

All three default to dry-run mode.

## When to Use

- Every DDL script that modifies schema or data
- Scripts that will be run by humans (not just automated pipelines)

## Where We Used It

- **DA-102**: Phase 1 dry-run gate before column renames
- **DA-126/DA-127**: Before FK constraint creation
- **DA-134/DA-139**: Before index creation

## Gotchas

- `RAISE EXCEPTION` aborts the current DO block AND prevents subsequent
  statements from running -- this is the desired behavior for dry-run
- The `true` parameter in `current_setting('da.execute', true)` means
  "return NULL if setting doesn't exist" instead of throwing an error

---

*Category: Safety | Origin: DA-102*
