---
name: procedure-rebuild-pg-get-functiondef
description: "Procedure Rebuild via pg_get_functiondef"
metadata:
  short-description: "Procedure Rebuild via pg_get_functiondef"
  original-index: 06
---

# Procedure Rebuild via pg_get_functiondef

## What

A technique for modifying stored procedures by extracting their current
definition from the catalog, performing text replacements on the SQL source,
and re-executing the modified definition -- all within a single DO block.

## Why

Manually rewriting a stored procedure is error-prone and doesn't scale. By
using `pg_get_functiondef`, you get the **exact** current definition from
PostgreSQL's catalog, modify only what you need, and re-create it with
`CREATE OR REPLACE`. This guarantees you don't accidentally change anything
else in the procedure.

## How

```sql
DO $$
DECLARE
    v_def text;
BEGIN
    -- Step 1: Extract current definition
    SELECT pg_get_functiondef(p.oid) INTO v_def
    FROM pg_proc p
    WHERE p.proname = 'MyProcedure'
      AND p.pronamespace = 'public'::regnamespace;

    -- Step 2: Check if replacement is needed
    IF v_def IS NOT NULL
       AND v_def LIKE '%"OldColumnName"%'
    THEN
        -- Step 3: Text replacement (surgical)
        v_def := replace(v_def, '"OldColumnName"', '"NewColumnName"');

        -- Step 4: Re-create the procedure
        EXECUTE v_def;

        RAISE NOTICE 'Updated: MyProcedure';
    ELSE
        RAISE NOTICE 'Skipped: MyProcedure (already correct or not found)';
    END IF;
END $$;
```

## What pg_get_functiondef Returns

It returns a complete `CREATE OR REPLACE FUNCTION/PROCEDURE` statement including:
- Full signature with parameter names and types
- Function body
- Language declaration
- Security attributes
- All options (VOLATILE, COST, ROWS, etc.)

This means `EXECUTE v_def` is equivalent to running the original DDL -- it
replaces the procedure in-place without dropping it.

## When to Use

- Renaming column references inside procedures
- Any bulk search-and-replace across procedure bodies
- When you need to modify procedures atomically alongside other DDL changes

## Where We Used It

- ****: Updated 4 procedures to replace misspelled quoted column names
  with corrected spellings. Each procedure had its definition extracted,
  4 replacements applied, and re-created via EXECUTE.

## Gotchas

- `pg_get_functiondef` returns the definition as PostgreSQL sees it, which may
  differ from the original DDL (formatting, quoting, etc.)
- The `replace()` function is case-sensitive -- match the exact casing
- Parameter names appear in the function signature AND may appear in the body;
  use **quoted** column names in your LIKE/replace to avoid accidentally
  modifying parameter references
- If two procedures have the same name but different signatures (overloads),
  you need to disambiguate by OID or argument types

---

*Category: DDL | Origin: *
