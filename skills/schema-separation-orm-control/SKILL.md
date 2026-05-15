---
name: schema-separation-orm-control
description: "Schema Separation for ORM/Scaffolding Control"
metadata:
  short-description: "Schema Separation for ORM/Scaffolding Control"
  original-index: 18
---

# Schema Separation for ORM/Scaffolding Control

## What

Moving internal database objects (partition children, helper tables, maintenance
artifacts) into a separate schema so that ORM tools (Entity Framework, Npgsql,
Prisma) only scaffold the intended application tables.

## Why

ORMs like Entity Framework discover tables via `information_schema.tables`. If
partition children (e.g., `AppointmentInfo_2024`, `AppointmentInfo_2025`) live in
the `public` schema alongside the parent table, EF will scaffold them as
separate entities -- creating confusion, compilation errors, and bloated models.

Moving them to a `partitions` schema removes them from the ORM's discovery path
while keeping them fully functional (PostgreSQL resolves partition routing
regardless of schema).

## How

### Step 1: Create the target schema
```sql
CREATE SCHEMA IF NOT EXISTS partitions;
```

### Step 2: Move the partition children
```sql
ALTER TABLE public."AppointmentInfo_2024"
    SET SCHEMA partitions;

ALTER TABLE public."AppointmentInfo_2025"
    SET SCHEMA partitions;
```

### Step 3: Verify partition routing still works
```sql
-- Insert should still route to the correct partition
INSERT INTO public."AppointmentInfo" ("CreatedDate", ...)
VALUES ('2025-06-15', ...);

-- Query should still find data across all partitions
SELECT * FROM public."AppointmentInfo"
WHERE "CreatedDate" >= '2025-01-01';
```

### Step 4: Update EF scaffolding command
```bash
# Scaffold only public schema
dotnet ef dbcontext scaffold ... --schema public
```

## Schema Candidates

| Object Type | Move To | Reason |
|---|---|---|
| Partition children | `partitions` | Hide from ORM discovery |
| Maintenance procedures | `maintenance` | Separate ops from app code |
| Monitoring views | `monitoring` | Separate observability layer |
| Audit triggers/functions | `audit` | Clean separation of concerns |

## When to Use

- After implementing table partitioning 
- When ORM scaffolding picks up unwanted objects
- When separating operational concerns from application concerns

## Where We Used It

- ****: Moved partition children from `public` to `partitions` schema
  so EF/Npgsql scaffolding only discovers parent tables

## References

- [PostgreSQL Best Practices](../DOCUMENTS/PostgreSQL_BestPractices_Azure.md)
  -- see Audit Finding #8 (Everything in public schema) and
  "Database naming conventions" (Schemas section)

## Gotchas

- `SET SCHEMA` acquires `AccessExclusiveLock` -- brief but blocking
- Indexes, constraints, and triggers move with the table automatically
- Foreign keys referencing the moved table remain valid (OID-based, not name-based)
- Sequences do NOT automatically move -- check if any need to follow
- Ensure the ORM connection's `search_path` does NOT include the new schema

---

*Category: Strategy | Origin: *
