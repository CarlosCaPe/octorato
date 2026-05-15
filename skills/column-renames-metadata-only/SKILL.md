---
name: column-renames-metadata-only
description: "Column Renames (Metadata-Only)"
metadata:
  short-description: "Column Renames (Metadata-Only)"
  original-index: 05
---

# Column Renames (Metadata-Only)

## What

PostgreSQL's `ALTER TABLE RENAME COLUMN` is a **metadata-only** operation. It
changes the column name in the system catalogs (`pg_attribute`) without touching
the actual table data. It's instant regardless of table size.

## Why

This matters because renaming a column on a 100-million-row table takes the
same time as renaming one on a 10-row table: effectively zero. No table rewrite,
no data movement, no downtime.

## How

```sql
ALTER TABLE public."Applicant"
    RENAME COLUMN "SpeialtyRequirement" TO "SpecialtyRequirement";
```

What happens internally:
1. PostgreSQL acquires an `ACCESS EXCLUSIVE` lock on the table (very briefly)
   -- this is the strictest lock mode but the hold time is sub-millisecond
   since only catalog metadata is updated (PG 16 docs: sql-altertable.html)
2. Updates `pg_attribute.attname` for that column's OID
3. Releases the lock

Total time: typically < 1ms.

## What It Does NOT Do

- Does NOT update stored procedures that reference the old column name
- Does NOT update views that reference the old column name
- Does NOT update application code
- Does NOT update indexes (indexes reference column attnum, not name)
- Does NOT change parameter names in function signatures

This is why  had to separately update 4 stored procedures -- the column
rename alone would have left them broken with `"column does not exist"` errors.

## When to Use

- Fixing typos in column names
- Standardizing naming conventions
- Any rename where you can also update all dependent objects

## Where We Used It

- ****: Renamed 4 misspelled columns in `public."Applicant"`
  - `SpeialtyRequirement` -> `SpecialtyRequirement`
  - `AddionalCommentsAuthToWork` -> `AdditionalCommentsAuthToWork`
  - `AdditinalCpmmentsUnderAge` -> `AdditionalCommentsUnderAge`
  - `VertirnaryTechOrAssistant` -> `the clientTechOrAssistant`

## Related Skills

- **Skill #06** (pg_get_functiondef) -- update procedures after column renames
- **Skill #08** (Deep Grep) -- verify all references found
- **Skill #14** (Research Checklist) -- find all affected objects before renaming
- **Skill #19** (Multi-Object Rename) -- when the rename includes the table itself

## Gotchas

- **Stored procedures break** if they use quoted column names (`"OldName"`)
- **Views break** if they reference the old column name
- **Application code breaks** if it uses the old column name in queries
- Always search for ALL dependent objects before renaming

---

*Category: DDL | Origin: *
