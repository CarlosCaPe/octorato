---
name: idempotent-sql-design
description: "Idempotent SQL Design"
metadata:
  short-description: "Idempotent SQL Design"
  original-index: 04
---

# Idempotent SQL Design

## What

Scripts that check the current state before acting, so they can be safely
re-run without causing errors or duplicate changes. Running the script once
or ten times produces the same final state.

## Why

Deployments fail. Networks drop. Operators re-run scripts "just to be sure."
An idempotent script handles all of these gracefully -- it skips work that's
already done and only applies what's missing.

## How

### Column renames
```sql
-- Check before acting
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'Applicant'
      AND column_name = 'SpeialtyRequirement'  -- old name
) THEN
    ALTER TABLE public."Applicant"
        RENAME COLUMN "SpeialtyRequirement" TO "SpecialtyRequirement";
    RAISE NOTICE 'Renamed: SpeialtyRequirement -> SpecialtyRequirement';
ELSE
    RAISE NOTICE 'Skipped: SpeialtyRequirement (already renamed)';
END IF;
```

### Index creation
```sql
-- Only create if missing
IF NOT EXISTS (
    SELECT 1 FROM pg_indexes
    WHERE schemaname = 'public'
      AND indexname = 'ix_my_index'
) THEN
    CREATE INDEX ix_my_index ON public."MyTable" ("MyColumn");
END IF;
```

### FK constraints
```sql
-- Only add if missing
IF NOT EXISTS (
    SELECT 1 FROM information_schema.table_constraints
    WHERE constraint_name = 'fk_my_constraint'
) THEN
    ALTER TABLE public."MyTable"
        ADD CONSTRAINT fk_my_constraint
        FOREIGN KEY ("MyColumn") REFERENCES public."OtherTable"("Id");
END IF;
```

## Key Principle

The pattern is always:
1. **Query current state** (does the old column exist? does the index exist?)
2. **Act only if needed** (IF EXISTS / IF NOT EXISTS)
3. **Report what happened** (RAISE NOTICE with [OK] or [--] prefix)

## When to Use

- Every DDL script. Always.
- Especially critical for scripts deployed to multiple environments where
  some may already have partial changes applied

## Where We Used It

- ****: Column renames + procedure updates (check old/new state first)
- **/**: FK constraint creation (check constraint existence)
- **/**: Index creation (check index existence)

---

*Category: Reliability | Origin: *
