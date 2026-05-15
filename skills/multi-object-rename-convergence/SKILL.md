---
name: multi-object-rename-convergence
description: "Multi-Object Rename Convergence"
metadata:
  short-description: "Multi-Object Rename Convergence"
  original-index: 19
---

# Multi-Object Rename Convergence

## What

Renaming a **table** and cascading that rename through all dependent objects:
FK columns across N child tables, views, stored procedures, indexes, and
constraints. A full-stack rename that goes far beyond a single column rename.

## Why

Renaming a table touches every layer of the schema. Unlike a column rename
(Skill #05, metadata-only, no dependents break), a table rename has a blast
radius that includes:
- Foreign key columns in child tables (named after the old table)
- Views that SELECT FROM the old table name
- Stored procedures that reference the old table
- Indexes and constraints named after the old table
- Application code and ORM mappings

## How

### Phase 1: Inventory all dependents
```sql
-- Find all FK references to the old table
SELECT conname, conrelid::regclass AS child_table
FROM pg_constraint
WHERE confrelid = 'public."Scribe"'::regclass;

-- Find all views referencing the old table
SELECT viewname FROM pg_views
WHERE definition LIKE '%"Scribe"%';

-- Find all procedures referencing the old table
SELECT proname FROM pg_proc
WHERE prosrc LIKE '%"Scribe"%';
```

### Phase 2: Rename the table
```sql
ALTER TABLE public."Scribe" RENAME TO "Recording";
```

### Phase 3: Rename FK columns in child tables
```sql
-- In each child table, rename the FK column
ALTER TABLE public."ReportWords"
    RENAME COLUMN "ScribeId" TO "RecordingId";
```

### Phase 4: Rebuild views and procedures
Use `pg_get_functiondef` (Skill #06) for procedures, and `CREATE OR REPLACE VIEW`
for views, replacing all references to the old name.

### Phase 5: Rename indexes and constraints
```sql
ALTER INDEX "IX_Scribe_HospitalId" RENAME TO "IX_Recording_HospitalId";
ALTER TABLE public."Recording"
    RENAME CONSTRAINT "PK_Scribe" TO "PK_Recording";
```

## When to Use

- Correcting misleading table names (Scribe -> Recording)
- Standardizing naming conventions across the schema
- Any rename where the old name propagated into dependent objects

## Where We Used It

- ****: Renamed `Scribe`/`Transcription` table to `Recording` +
  converged FK columns, views, procedures, and indexes
- ****: Follow-up rename of remaining "Scribe" wording in object
  names and definitions

## Related Skills

- **Skill #05** (Column Renames) -- metadata-only column renames within the cascade
- **Skill #06** (pg_get_functiondef) -- rebuild procedures referencing old names
- **Skill #14** (Research Checklist) -- inventory ALL dependents before renaming

## Gotchas

- **Blast radius is large** -- always inventory ALL dependents first (Skill #14)
- Table renames are metadata-only, but view/procedure rebuilds are not trivial
- Application code must be updated simultaneously or use backward-compatible
  views/aliases
- Do in stages: table rename -> column renames -> view rebuilds -> procedure
  rebuilds -> index/constraint renames
- Test with the application between each stage if possible

---

*Category: DDL | Origin: , *
