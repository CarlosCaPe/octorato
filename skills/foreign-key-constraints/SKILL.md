---
name: foreign-key-constraints
description: "Foreign Key Constraints"
metadata:
  short-description: "Foreign Key Constraints"
  original-index: 09
---

# Foreign Key Constraints

## What

`ALTER TABLE ADD CONSTRAINT ... FOREIGN KEY` enforces referential integrity
between tables. The FK guarantees that every value in the child column exists
in the parent table's referenced column.

## Why

Without FKs, orphaned records accumulate silently. A `HospitalId` in an
appointments table might reference a hospital that no longer exists. FKs
catch this at INSERT/UPDATE time, preventing data corruption.

## How

### Standard FK pattern (NOT VALID + VALIDATE)
```sql
-- Step 1: Add the constraint without scanning existing rows (instant)
ALTER TABLE public."AppointmentInfo"
    ADD CONSTRAINT fk_appointmentinfo_hospitalid
    FOREIGN KEY ("HospitalId")
    REFERENCES public."Hospital"("HospitalId")
    NOT VALID;

-- Step 2: Validate existing rows (non-blocking, allows concurrent reads)
ALTER TABLE public."AppointmentInfo"
    VALIDATE CONSTRAINT fk_appointmentinfo_hospitalid;
```

Why NOT VALID + VALIDATE?
- `ADD FOREIGN KEY` acquires `SHARE ROW EXCLUSIVE` lock on both the
  child table AND the referenced (parent) table -- lighter than the
  `ACCESS EXCLUSIVE` used by most ALTER TABLE forms
  (PG 16 docs: sql-altertable.html)
- `NOT VALID` skips scanning existing rows -- constraint creation is fast
- New inserts/updates ARE validated immediately against the FK
- `VALIDATE CONSTRAINT` scans existing rows with an even weaker lock
  (`SHARE UPDATE EXCLUSIVE`) that allows concurrent reads AND writes;
  it also acquires only `ROW SHARE` on the referenced table
  (PG 16 docs: sql-altertable.html)
- This is the recommended pattern in our
  [Best Practices](../DOCUMENTS/PostgreSQL_BestPractices_Azure.md)

### FK with explicit actions
```sql
ALTER TABLE public."ChildTable"
    ADD CONSTRAINT fk_child_parent
    FOREIGN KEY ("ParentId")
    REFERENCES public."ParentTable"("Id")
    ON DELETE CASCADE
    ON UPDATE CASCADE
    NOT VALID;

ALTER TABLE public."ChildTable"
    VALIDATE CONSTRAINT fk_child_parent;
```

### Idempotent pattern
```sql
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'fk_appointmentinfo_hospitalid'
          AND table_schema = 'public'
    ) THEN
        ALTER TABLE public."AppointmentInfo"
            ADD CONSTRAINT fk_appointmentinfo_hospitalid
            FOREIGN KEY ("HospitalId")
            REFERENCES public."Hospital"("HospitalId");
        RAISE NOTICE 'Created FK: fk_appointmentinfo_hospitalid';
    ELSE
        RAISE NOTICE 'Skipped: fk_appointmentinfo_hospitalid (already exists)';
    END IF;
END $$;
```

## Pre-Requisites

Before adding a FK, verify:
1. **No orphans exist** -- see **Skill #24** (Orphan Detection & FK Rollout)
   for the full scan + remediation workflow
2. **Parent column has a unique index** (usually PK or UNIQUE constraint)
3. **Data types match** between child and parent columns

## When to Use

- Any column that references another table's primary key
- After database audits identify missing referential integrity
- As part of schema hardening / best practices enforcement

## Where We Used It

- ****: FK on `AppointmentInfo.HospitalId` -> `Hospital.HospitalId`
- ****: FK on `AppointmentInfo.ProviderId` -> `Provider.ProviderId`

## Related Skills

- **Skill #24** (Orphan Detection & FK Rollout) -- orphan scan + data cleanup
  before FK creation
- **Skill #10** (Index CONCURRENTLY) -- supporting indexes for FK columns
- **Skill #20** (Procedure Hardening) -- FK-aware delete ordering in procedures

## References

- [PostgreSQL Best Practices](../DOCUMENTS/PostgreSQL_BestPractices_Azure.md)
  -- see "Foreign keys and constraints" in Design & Modeling

## Gotchas

- Always use `NOT VALID` + `VALIDATE CONSTRAINT` (see main example above)
- `ADD FOREIGN KEY` locks BOTH the child AND the parent table with
  `SHARE ROW EXCLUSIVE` -- coordinate with teams owning the parent table
- FKs create implicit dependencies -- `DROP TABLE parent` will fail
- FKs can slow down INSERT/UPDATE/DELETE on the child table (each operation
  checks the parent)
- Always create a supporting index on the FK column (Skill #10) --
  PostgreSQL does NOT auto-create indexes on FK columns
- On partitioned tables, FKs cannot be declared `NOT VALID`
  (PG 16 limitation -- see Skill #34)

---

*Category: DDL | Origin: , *
