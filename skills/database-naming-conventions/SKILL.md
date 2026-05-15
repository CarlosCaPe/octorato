---
name: database-naming-conventions
description: "Database Naming Conventions"
metadata:
  short-description: "Database Naming Conventions"
  original-index: 27
---

# Database Naming Conventions

> Source: [PostgreSQL Best Practices](../DOCUMENTS/PostgreSQL_BestPractices_Azure.md)
> -- "Database naming conventions" section

## What

A complete reference for naming database objects. This skill exists so the
agent never has to guess or hallucinate naming patterns -- the rules are here.

## Why

Inconsistent naming causes:
- Quoted identifier hell (PascalCase forces `"MyTable"` everywhere)
- Ambiguous FK/index names that don't self-document their purpose
- Merge conflicts when two engineers pick different conventions
- ORM scaffolding confusion

Our legacy schemas use PascalCase (e.g., `"AppointmentInfo"`, `"HospitalId"`).
New schemas should use snake_case. Both conventions coexist, and this skill
documents the rules for each.

## Conventions

### Legacy Schemas (PascalCase -- existing objects)

These schemas already exist with PascalCase identifiers. When modifying
existing objects, **follow the existing convention** for consistency:

| Object | Pattern | Example |
|--------|---------|---------|
| Table | PascalCase, singular | `"AppointmentInfo"`, `"Recording"` |
| Column | PascalCase | `"HospitalId"`, `"CreatedDate"` |
| PK constraint | `PK_<Table>` | `"PK_AppointmentInfo"` |
| FK constraint | `fk_<child>_<column>` | `fk_appointmentinfo_hospitalid` |
| Index | `ix_<table>_<columns>` | `ix_appointmentinfo_hospitalid` |
| Unique index | `uq_<table>__<columns>` | `uq_users__email_lower` |

### New Schemas (snake_case -- recommended standard)

All new schemas, tables, and columns should use lowercase snake_case:

| Object | Pattern | Example |
|--------|---------|---------|
| Schema | lowercase, bounded context | `billing`, `scribe`, `feature_flags` |
| Table | plural snake_case | `users`, `order_items` |
| Column | snake_case | `hospital_id`, `created_at` |
| PK column | `id` or `<table>_id` | `id`, `user_id` |
| FK column | `<referenced_table>_id` | `user_id`, `hospital_id` |
| Timestamps | `created_at`, `updated_at` | `timestamptz NOT NULL DEFAULT now()` |
| PK constraint | `pk_<table>` | `pk_users` |
| FK constraint | `fk_<table>__<column>` | `fk_orders__user_id` |
| Unique | `uq_<table>__<columns>` | `uq_users__email` |
| Check | `ck_<table>__<description>` | `ck_orders__total_nonnegative` |
| B-tree index | `ix_<table>__<columns>` | `ix_orders__status_created` |
| Partial index | `ix_<table>__<columns>_<predicate>` | `ix_orders__status_open` |
| Sequence | `<table>_<column>_seq` | `users_id_seq` |
| Function | `<schema>.<verb_noun>` | `billing.calculate_invoice_total` |

### Double-Underscore Rule

Use `__` (double underscore) between the table name and column names in
constraint/index names. This distinguishes the table part from the column part:
- `fk_orders__user_id` -- FK on `orders.user_id`
- `uq_users__email` -- unique on `users.email`
- `ix_products__status_created` -- composite index

### Naming Things to Avoid

| Avoid | Why | Instead |
|-------|-----|---------|
| Abbreviations | `usr`, `appt`, `cfg` are ambiguous | `users`, `appointment`, `config` |
| Team/org names in object names | Coupling to org structure | Use domain names |
| Quoted identifiers in new objects | Forces quoting everywhere | Use snake_case |
| Reserved words as names | `user`, `order`, `group` need quoting | `users`, `orders`, `groups` |
| Redundant prefixes | `tbl_users`, `sp_GetUser` | `users`, `get_user` |

## When to Use

- Every time you name a new object (table, column, index, constraint, function)
- When renaming objects during convergence (Skill #19)
- During code review -- verify names follow convention

## Where We Used It

- **All tickets**: FK constraint naming (`fk_<child>_<column>`)
- **All tickets**: Index naming (`ix_<table>_<columns>`)
- **/**: Table rename `Scribe` -> `Recording` followed naming rules
- ****: Schema naming (`partitions`, `maintenance`)

## Related Skills

- **Skill #05** (Column Renames) -- rename to match convention
- **Skill #19** (Multi-Object Rename) -- cascade naming through dependents

## References

- [PostgreSQL Best Practices](../DOCUMENTS/PostgreSQL_BestPractices_Azure.md)
  -- "Database naming conventions" and "the client naming and Git conventions"

## Gotchas

- PostgreSQL folds unquoted identifiers to lowercase -- `CREATE TABLE Users`
  is actually `create table users`. Only quoted identifiers preserve case.
- When working in legacy PascalCase schemas, stay PascalCase for consistency
- In mixed environments, document which convention each schema uses
- The `__` double-underscore is a the client convention, not a PostgreSQL standard
- Function/procedure names should use snake_case verbs: `get_user`, not `GetUser`

---

*Category: Strategy | Origin: PostgreSQL Best Practices*
