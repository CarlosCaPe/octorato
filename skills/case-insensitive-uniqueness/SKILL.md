---
name: case-insensitive-uniqueness
description: "Case-Insensitive Uniqueness (Functional Indexes)"
metadata:
  short-description: "Case-Insensitive Uniqueness (Functional Indexes)"
  original-index: 31
---

# Case-Insensitive Uniqueness (Functional Indexes)

> Source: [PostgreSQL Best Practices](../DOCUMENTS/PostgreSQL_BestPractices_Azure.md)
> -- Audit Finding #6 and Backlog #3

## What

Creating a case-insensitive unique constraint on text columns (typically email)
using a **functional B-tree index** on `lower(column)` instead of the `citext`
extension.

## Why

Email addresses `Alice@Example.com` and `alice@example.com` are the same
mailbox but different PostgreSQL text values. Without case-insensitive
uniqueness:
- Duplicate accounts can be created with different casing
- Login lookups may fail (searching for `alice@` when stored as `Alice@`)
- Data quality degrades silently

The decision to use `lower()` instead of `citext`:
- `citext` requires an extension (`CREATE EXTENSION citext`) -- adds surface area
- `lower()` + B-tree is native, lightweight, and requires no extension
- Both approaches are equally effective for ASCII email
- Our Best Practices recommend `lower()` until `citext` is justified

## How

### Create the functional unique index
```sql
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_users__email_lower
    ON public."Users" (lower("Email"));
```

### Query using the same expression
```sql
-- MUST use lower() in the query for the index to be used
SELECT "UserId", "Email"
FROM public."Users"
WHERE lower("Email") = lower('Alice@Example.com');
```

### Idempotent pattern for scripts
```sql
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE schemaname = 'public'
          AND indexname = 'uq_users__email_lower'
    ) THEN
        -- Must be outside DO block (CONCURRENTLY restriction)
        RAISE NOTICE '[--] Index uq_users__email_lower needs creation';
    ELSE
        RAISE NOTICE '[OK] Index uq_users__email_lower already exists';
    END IF;
END $$;

-- Outside DO block:
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_users__email_lower
    ON public."Users" (lower("Email"));
```

### Check for existing duplicates BEFORE creating the unique index
```sql
-- This will fail if duplicates exist
SELECT lower("Email"), COUNT(*)
FROM public."Users"
GROUP BY lower("Email")
HAVING COUNT(*) > 1;
```

If duplicates are found, resolve them before creating the unique index.

## lower() vs citext Comparison

| Aspect | `lower()` + B-tree | `citext` |
|--------|-------------------|----------|
| Extension needed | No | Yes (`CREATE EXTENSION citext`) |
| Column type change | No | Yes (`ALTER COLUMN TYPE citext`) |
| Query requirement | Must use `lower()` in WHERE | Transparent (implicit) |
| Index type | Functional B-tree | Standard B-tree |
| Collation awareness | ASCII only | Full locale support |
| Maintenance | Low | Low |

**Our standard**: Use `lower()` unless multiple tables need case-insensitive
behavior AND the `lower()` pattern creates significant code repetition.

## When to Use

- Email columns that must be unique (case-insensitive)
- Username columns with uniqueness requirements
- Any text column where case variants should be treated as equal

## Where We Used It

- ****: Case-insensitive unique index on `Users.Email` (Scribe DB)
- ****: Case-insensitive unique index on `Users.Email` (Feature Flags DB)

## Related Skills

- **Skill #10** (Index CONCURRENTLY) -- creation technique
- **Skill #24** (Orphan Detection) -- check for duplicates before creating unique index
- **Skill #27** (Naming Conventions) -- `uq_<table>__<column>_lower` pattern

## References

- [PostgreSQL Best Practices](../DOCUMENTS/PostgreSQL_BestPractices_Azure.md)
  -- Audit Finding #6 and Backlog #3
- [Feature Flags Audit TDD](../DOCUMENTS/feature_flags_DB_Audit_TDD.md)
  -- "Prevent case-variant duplicates in email identifiers"

## Gotchas

- The query WHERE clause **must** use `lower()` for the index to be selected
  by the planner -- `WHERE "Email" = 'alice@...'` will NOT use the index
- If duplicates exist in the data, `CREATE UNIQUE INDEX` will fail with a
  duplicate key error -- always scan for duplicates first
- `lower()` is ASCII-only collation. For Unicode case folding (e.g., German
  eszett `ss` vs `SS`), consider `citext` or ICU collation
- Application code must consistently apply `lower()` when inserting --
  otherwise different-case values can be stored even though lookups match
- `CONCURRENTLY` is required to avoid locking the table during index build

---

*Category: DDL | Origin: , *
