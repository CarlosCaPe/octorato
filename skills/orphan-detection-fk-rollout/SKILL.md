---
name: orphan-detection-fk-rollout
description: "Orphan Data Detection & FK Rollout"
metadata:
  short-description: "Orphan Data Detection & FK Rollout"
  original-index: 24
---

# Orphan Data Detection & FK Rollout

## What

A systematic process for detecting orphan records (child rows referencing
non-existent parent rows) and safely rolling out FK constraints on tables
with existing data. Goes beyond Skill #09 (basic FK creation) into data
quality remediation.

## Why

You can't just `ADD CONSTRAINT ... FOREIGN KEY` on a table with orphan rows --
PostgreSQL will reject it. The rollout process must:
1. Find all orphans
2. Decide what to do with them (delete, null-out, create missing parents)
3. Clean the data
4. Add the FK with `NOT VALID` (skip validation, instant)
5. `VALIDATE CONSTRAINT` (verify remaining data, allows concurrent reads)

## How

### Step 1: Detect orphans
```sql
SELECT c."HospitalId", COUNT(*) AS orphan_count
FROM public."AppointmentInfo" c
LEFT JOIN public."Hospital" p ON p."HospitalId" = c."HospitalId"
WHERE p."HospitalId" IS NULL
  AND c."HospitalId" IS NOT NULL
GROUP BY c."HospitalId"
ORDER BY orphan_count DESC;
```

### Step 2: Decide remediation strategy

| Strategy | When to Use | SQL |
|----------|-------------|-----|
| Delete orphans | Child records have no value without parent | `DELETE FROM child WHERE parent_id NOT IN (SELECT id FROM parent)` |
| NULL out FK | Child records are valuable, FK is optional | `UPDATE child SET parent_id = NULL WHERE parent_id NOT IN (...)` |
| Create missing parents | Parent should exist but was accidentally deleted | `INSERT INTO parent (id) SELECT DISTINCT parent_id FROM child WHERE ...` |
| Skip FK | Orphans are too numerous or business-critical to modify | Document and revisit |

### Step 3: Clean the data
```sql
-- Example: NULL out orphaned references
UPDATE public."AppointmentInfo"
SET "HospitalId" = NULL
WHERE "HospitalId" NOT IN (
    SELECT "HospitalId" FROM public."Hospital"
);
```

### Step 4: Add FK with NOT VALID
```sql
ALTER TABLE public."AppointmentInfo"
    ADD CONSTRAINT fk_appointmentinfo_hospitalid
    FOREIGN KEY ("HospitalId")
    REFERENCES public."Hospital"("HospitalId")
    NOT VALID;  -- instant, no scan
```

### Step 5: Validate (non-blocking)
```sql
ALTER TABLE public."AppointmentInfo"
    VALIDATE CONSTRAINT fk_appointmentinfo_hospitalid;
    -- scans table but allows concurrent reads/writes
```

### Corrupted data scenario
Sometimes orphans exist because of corrupted records that block deletes:
```sql
-- Find records that can't be deleted because of FK violations
DELETE FROM feature_flags."FeatureFlags" WHERE "FlagId" = 42;
-- ERROR: update or delete on table "FeatureFlags" violates FK constraint

-- Root cause: corrupted child records referencing non-existent parents
-- Fix: clean corrupted children first, then retry parent delete
DELETE FROM feature_flags."FeatureFlagValues"
WHERE "FlagId" NOT IN (SELECT "FlagId" FROM feature_flags."FeatureFlags");
```

## When to Use

- Before adding FK constraints to tables with existing data
- When audit findings reveal missing referential integrity
- When DELETE operations fail due to FK violations on corrupted data
- As Phase 2 in any FK rollout script (between gap analysis and FK creation)

## Where We Used It

- ****: Orphan scan across 14 FK relationships before adding constraints
- ****: Validate and add FKs to EmailConfig, RoleMapping, UsersGroup
- ****: Cleaned corrupted feature flag records blocking FK-constrained deletes
- ****: Added missing FKs to Hospitals->Region, UsersRole->Roles

## Related Skills

- **Skill #09** (Foreign Key Constraints) -- FK syntax and NOT VALID pattern
- **Skill #10** (Index CONCURRENTLY) -- supporting indexes for FK columns
- **Skill #20** (Procedure Hardening) -- FK-aware delete ordering

## Gotchas

- Always scan for orphans BEFORE attempting `ADD CONSTRAINT`
- `ADD FOREIGN KEY ... NOT VALID` acquires `SHARE ROW EXCLUSIVE` lock on
  both child and parent tables -- lighter than `ACCESS EXCLUSIVE` but still
  blocks concurrent DDL on those tables (PG 16 docs: sql-altertable.html)
- `NOT VALID` skips scanning existing rows but new inserts/updates ARE
  validated immediately -- only pre-existing orphans are tolerated
- `VALIDATE CONSTRAINT` acquires the even lighter `SHARE UPDATE EXCLUSIVE`
  lock (allows concurrent reads AND writes); acquires only `ROW SHARE` on
  the referenced table (PG 16 docs: sql-altertable.html)
- Document the orphan count and remediation strategy in the CLOSURE_NOTE
- If orphan count is high (>1000), investigate root cause before cleaning

---

*Category: DDL | Origin: , , , *
