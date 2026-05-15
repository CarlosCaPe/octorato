---
name: production-bug-fix-stored-functions
description: "Production Bug Fix in Stored Functions"
metadata:
  short-description: "Production Bug Fix in Stored Functions"
  original-index: 25
---

# Production Bug Fix in Stored Functions

## What

A disciplined approach to finding, fixing, and validating logic bugs in stored
functions/procedures -- wrong filters, missing predicates, incorrect joins,
or flawed business logic.

## Why

A bug in a stored function is worse than a bug in application code because:
- It affects ALL callers (every app, every service, every query)
- It's invisible to application-level testing
- It may have been silently returning wrong results for months
- The fix must be deployed without downtime (`CREATE OR REPLACE`)

## How

### Step 1: Root-cause analysis
```sql
-- Get the current function definition
SELECT pg_get_functiondef(oid)
FROM pg_proc
WHERE proname = 'get_feature_flag_value_or_list'
  AND pronamespace = 'feature_flags'::regnamespace;
```

Read the logic line by line. Common bug patterns:
- Missing `WHERE` predicate (returns all rows instead of filtered)
- Wrong column in JOIN condition
- `AND` vs `OR` logic error
- Missing `NULL` handling (`COALESCE`, `IS NOT NULL`)
- Implicit type coercion causing wrong matches

### Step 2: Write a test query that proves the bug
```sql
-- Before fix: returns inactive flags (bug)
SELECT * FROM feature_flags.get_feature_flag_value_or_list('MyFlag');
-- Returns rows where Active = false (should not!)

-- Expected: only active flags
SELECT * FROM feature_flags."FeatureFlags"
WHERE "FlagName" = 'MyFlag' AND "Active" = true;
```

### Step 3: Fix with CREATE OR REPLACE
```sql
CREATE OR REPLACE FUNCTION feature_flags.get_feature_flag_value_or_list(
    p_flag_name text
)
RETURNS TABLE(...) AS $$
BEGIN
    RETURN QUERY
    SELECT ...
    FROM feature_flags."FeatureFlags" f
    WHERE f."FlagName" = p_flag_name
      AND f."Active" = true;  -- THE FIX: was missing
END;
$$ LANGUAGE plpgsql;
```

### Step 4: Validate the fix
```sql
-- After fix: only active flags returned
SELECT * FROM feature_flags.get_feature_flag_value_or_list('MyFlag');
-- Should return 0 rows for inactive flags

-- Regression check: existing behavior preserved for active flags
SELECT * FROM feature_flags.get_feature_flag_value_or_list('ActiveFlag');
-- Should still return expected rows
```

### Step 5: Document in CLOSURE_NOTE
```markdown
## Bug Details
- **Function**: feature_flags.get_feature_flag_value_or_list
- **Bug**: Missing `AND "Active" = true` predicate
- **Impact**: Returned inactive feature flags to all callers
- **Fix**: Added `Active` filter to WHERE clause
- **Root cause**: Original function copied from a different context
  where all records were assumed active
```

## When to Use

- When audit or QA discovers a stored function returning wrong results
- When application team reports unexpected behavior from a DB function
- When code review (Skill #08) finds logic errors in procedure bodies

## Where We Used It

- ****: Fixed `get_feature_flag_value_or_list` -- was not filtering
  by `Active` column, returning inactive feature flags to all callers

## Related Skills

- **Skill #06** (pg_get_functiondef) -- extract current definition for analysis
- **Skill #08** (Deep Grep Code Review) -- verify no other functions have same bug
- **Skill #20** (Procedure Hardening) -- systematic hardening beyond the one fix

## Gotchas

- `CREATE OR REPLACE` preserves ownership and permissions -- no need to
  re-grant after the fix (PG 16 docs: sql-createfunction.html).
  Note: you cannot change the return type with OR REPLACE -- you must
  DROP and recreate the function in that case
- The fix is **instant** -- the next call to the function uses the new code
- Always write a regression test query that proves both:
  1. The bug is fixed (negative case)
  2. Existing behavior is preserved (positive case)
- If the function has overloads, ensure you're fixing the right signature
- Consider whether the bug has caused data corruption that also needs cleanup

---

*Category: Reliability | Origin: *
