---
name: gap-analysis-pattern
description: "Gap Analysis Pattern"
metadata:
  short-description: "Gap Analysis Pattern"
  original-index: 11
---

# Gap Analysis Pattern

## What

A pre-flight check that compares the **desired state** against the **current
state** of the database, reporting exactly what changes are needed before any
modifications are made.

## Why

Gap analysis answers three questions before any work begins:
1. **What needs to be done?** (changes pending)
2. **What's already done?** (idempotent re-runs)
3. **What's unexpected?** (anomalies that need investigation)

This information is logged as NOTICE messages, creating an audit trail of the
database state at the moment the script runs.

## How

```sql
-- Column gap analysis
IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'Applicant'
      AND column_name = 'SpeialtyRequirement'  -- old name
) THEN
    RAISE NOTICE '  [--] COL 1 SpeialtyRequirement -> SpecialtyRequirement -- NEEDS RENAME';
    v_old_found := v_old_found + 1;
ELSIF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'Applicant'
      AND column_name = 'SpecialtyRequirement'  -- new name
) THEN
    RAISE NOTICE '  [OK] COL 1 SpecialtyRequirement -- ALREADY RENAMED';
    v_new_found := v_new_found + 1;
ELSE
    RAISE NOTICE '  [!!] COL 1 Neither old nor new column found -- UNEXPECTED';
END IF;
```

### The three-state pattern

| Marker | Meaning | Action |
|--------|---------|--------|
| `[--]` | Change needed | Will be applied in Phase 2 |
| `[OK]` | Already done | Skip (idempotent) |
| `[!!]` | Unexpected state | Investigate before proceeding |

## When to Use

- Phase 1 of every DDL script
- Before any ALTER TABLE, CREATE INDEX, or procedure modification
- When deploying to environments that may be in different states

## Where We Used It

- ****: 4 column checks + 4 procedure checks in Phase 1
- **/**: FK existence checks + orphan record checks
- **/**: Index existence checks + table row counts

## Gotchas

- Always count your findings (`v_old_found`, `v_new_found`) and report
  the totals -- this makes log review much faster
- The `[!!]` (unexpected) branch should raise attention but not necessarily
  abort -- sometimes the unexpected state is a valid edge case
- Gap analysis runs in Phase 1 (read-only) -- never modify data here

---

*Category: Architecture | Origin: All tickets*
