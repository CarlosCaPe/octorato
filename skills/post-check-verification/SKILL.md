---
name: post-check-verification
description: "Post-Check Verification"
metadata:
  short-description: "Post-Check Verification"
  original-index: 15
---

# Post-Check Verification

## What

A dedicated phase at the end of every DDL script that independently verifies
the final state of the database. It checks that every expected change was
applied and reports a confirmed/failed count.

## Why

"The script ran without errors" is not the same as "the script did what we
wanted." Post-checks verify the **outcome**, not just the execution. They
catch subtle issues like:
- A rename that silently did nothing (column didn't exist)
- A procedure update that was skipped (condition was wrong)
- An index that was created INVALID (concurrent build failure)

## How

```sql
-- Phase 3: Post-check
DO $$
DECLARE
    v_confirmed int := 0;
    v_failed    int := 0;
BEGIN
    RAISE NOTICE 'PHASE 3: POST-CHECK';

    -- Verify column exists (new) AND doesn't exist (old)
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'Applicant'
          AND column_name = 'SpecialtyRequirement'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'Applicant'
          AND column_name = 'SpeialtyRequirement'
    ) THEN
        RAISE NOTICE '  [OK] COL 1 SpecialtyRequirement';
        v_confirmed := v_confirmed + 1;
    ELSE
        RAISE NOTICE '  [!!] COL 1 SpecialtyRequirement -- FAILED';
        v_failed := v_failed + 1;
    END IF;

    -- ... repeat for each check ...

    -- Final summary
    RAISE NOTICE '  Checks confirmed: % / %', v_confirmed, v_confirmed + v_failed;

    IF v_confirmed = 8 AND v_failed = 0 THEN
        RAISE NOTICE ' COLUMN RENAME COMPLETE';
    ELSIF v_failed > 0 THEN
        RAISE NOTICE 'PARTIAL -- % check(s) failed', v_failed;
    END IF;
END $$;
```

### What to verify

| Change Type | Positive Check | Negative Check |
|---|---|---|
| Column rename | New name EXISTS | Old name NOT EXISTS |
| Procedure update | New column ref LIKE | Old column ref NOT LIKE |
| Index creation | Index EXISTS in pg_indexes | Index IS VALID |
| FK constraint | Constraint EXISTS | No orphan records |

### The "N / N" pattern

Always report `confirmed / total`:
```
Checks confirmed: 8 / 8    -- all good
Checks confirmed: 6 / 8    -- something wrong
```

This makes log scanning trivial -- search for the number and instantly know
the result.

## When to Use

- Phase 3 of every DDL script
- After every deployment (the log IS the evidence)
- The post-check output goes into the CLOSURE_NOTE as deployment evidence

## Where We Used It

- ****: 8/8 (4 columns + 4 procedures)
- **/**: FK existence + supporting index checks
- **/**: Index existence + validity checks

## Gotchas

- Post-checks must be **independent** of Phase 2 -- they query the database
  directly, not variables from the previous phase
- Each post-check runs in its own DO block so Phase 2 failures don't
  prevent the post-check from reporting the actual state
- Include both positive (new thing exists) AND negative (old thing gone)
  checks -- a false positive from only checking one side can mask bugs

---

*Category: Reliability | Origin: All tickets*
