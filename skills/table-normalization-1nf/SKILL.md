---
name: table-normalization-1nf
description: "Table Normalization (1NF Violations)"
metadata:
  short-description: "Table Normalization (1NF Violations)"
  original-index: 22
---

# Table Normalization (1NF Violations)

## What

Breaking repeating column groups (e.g., `PreferredDate1`, `PreferredDate2`,
`PreferredDate3`) into properly normalized child tables with foreign keys.
This resolves First Normal Form (1NF) violations.

## Why

Repeating columns create:
- **Query complexity**: WHERE clauses need `OR` across N columns
- **Schema rigidity**: adding a 4th preference requires ALTER TABLE
- **NULL proliferation**: most rows only use 1-2 of N slots
- **Index waste**: each column needs its own index for searchability

A normalized child table (`ApplicantPreferredDates`) with one row per preference
eliminates all of these problems.

## How

### Step 1: Identify the repeating group
```sql
-- Columns like: PreferredDate1_Start, PreferredDate1_End,
--               PreferredDate2_Start, PreferredDate2_End, ...
SELECT column_name FROM information_schema.columns
WHERE table_name = 'Applicant'
  AND column_name LIKE 'Preferred%'
ORDER BY ordinal_position;
```

### Step 2: Create the child table
```sql
CREATE TABLE public."ApplicantPreferredDate" (
    "Id"            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    "ApplicantId"   bigint NOT NULL
        REFERENCES public."Applicant"("ApplicantId") ON DELETE CASCADE,
    "Preference"    smallint NOT NULL CHECK ("Preference" BETWEEN 1 AND 3),
    "StartDate"     timestamptz,
    "EndDate"       timestamptz,
    UNIQUE ("ApplicantId", "Preference")
);
```

### Step 3: Migrate existing data
```sql
INSERT INTO public."ApplicantPreferredDate"
    ("ApplicantId", "Preference", "StartDate", "EndDate")
SELECT "ApplicantId", 1, "FirstPreferredSD", "FirstPreferredED"
FROM public."Applicant"
WHERE "FirstPreferredSD" IS NOT NULL

UNION ALL

SELECT "ApplicantId", 2, "SecondPreferredSD", "SecondPreferredED"
FROM public."Applicant"
WHERE "SecondPreferredSD" IS NOT NULL

UNION ALL

SELECT "ApplicantId", 3, "ThirdPreferredSD", "ThirdPreferredED"
FROM public."Applicant"
WHERE "ThirdPreferredSD" IS NOT NULL;
```

### Step 4: Update procedures to use child table
Replace direct column references with JOINs or subqueries against the
child table.

### Step 5: (Later) Drop the old columns
```sql
-- Only after app code is fully migrated
ALTER TABLE public."Applicant"
    DROP COLUMN "FirstPreferredSD",
    DROP COLUMN "FirstPreferredED",
    -- ... etc.
```

## When to Use

- Tables with numbered/suffixed column groups (Date1, Date2, Date3)
- Tables with arrays stored as separate columns
- After audit findings flag 1NF violations

## Where We Used It

- ****: Normalized Applicant preferred dates and preferred locations
  from repeating columns into `ApplicantPreferredDate` and
  `ApplicantPreferredLocation` child tables

## Related Skills

- **Skill #07** (Backward Compatibility) -- keep old columns during transition
- **Skill #09** (Foreign Key Constraints) -- FK from child table to parent
- **Skill #14** (Research Checklist) -- find all procedures referencing old columns

## References

- [PostgreSQL Best Practices](../DOCUMENTS/PostgreSQL_BestPractices_Azure.md)
  -- see "Schema design and data types" section

## Gotchas

- **Data migration is the hard part** -- handle NULLs, duplicates, and edge cases
- Keep old columns during transition (backward compatibility, Skill #07)
- Update ALL procedures that reference the old columns (Skill #14, #08)
- The child table needs proper indexes (FK column, composite lookups)
- Application code must be updated to INSERT into the child table instead
  of the parent's repeating columns

---

*Category: DDL | Origin: *
