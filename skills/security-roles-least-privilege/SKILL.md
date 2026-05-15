---
name: security-roles-least-privilege
description: "Security Roles & Least-Privilege Grants"
metadata:
  short-description: "Security Roles & Least-Privilege Grants"
  original-index: 35
---

# Security Roles & Least-Privilege Grants

> Source: [PostgreSQL Best Practices](../DOCUMENTS/PostgreSQL_BestPractices_Azure.md)
> -- "Security essentials", "Roles & grants"

## What

Implementing role-based access control with three standard roles
(`app_owner`, `app_user`, `app_readonly`) and schema-level GRANT/REVOKE
to enforce least-privilege access. This ensures applications and users
can only perform the operations they need.

## Why

By default, PostgreSQL grants generous permissions:
- `PUBLIC` role can `CREATE` objects in the `public` schema
- Any authenticated user can read `pg_catalog` and `information_schema`
- The superuser (`psqladmin` on Azure) owns everything

Without role separation:
- Application connections run as the database owner (full DDL access)
- A compromised app can `DROP TABLE` or `ALTER` schema
- Read-only dashboards can accidentally write data
- Audit trails cannot distinguish who did what

The Best Practices mandate three roles:

| Role | Purpose | Permissions |
|------|---------|-------------|
| `app_owner` | Schema management, migrations | `ALL` on schema + objects |
| `app_user` | Application runtime | `SELECT, INSERT, UPDATE, DELETE` on tables |
| `app_readonly` | Dashboards, reporting | `SELECT` only |

## How

### Create the three standard roles

```sql
-- Roles are cluster-wide (not per-database)
CREATE ROLE app_owner NOLOGIN;
CREATE ROLE app_user NOLOGIN;
CREATE ROLE app_readonly NOLOGIN;

-- Grant hierarchy: app_owner > app_user > app_readonly
GRANT app_readonly TO app_user;
GRANT app_user TO app_owner;
```

### Grant schema-level permissions

```sql
-- Revoke default PUBLIC access
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- app_owner: full control
GRANT ALL ON SCHEMA public TO app_owner;
GRANT ALL ON ALL TABLES IN SCHEMA public TO app_owner;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO app_owner;
GRANT ALL ON ALL FUNCTIONS IN SCHEMA public TO app_owner;

-- app_user: DML only
GRANT USAGE ON SCHEMA public TO app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO app_user;

-- app_readonly: read only
GRANT USAGE ON SCHEMA public TO app_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO app_readonly;
```

### Set default privileges for future objects

```sql
-- When app_owner creates new tables, app_user and app_readonly
-- automatically get the right permissions
ALTER DEFAULT PRIVILEGES FOR ROLE app_owner IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_user;

ALTER DEFAULT PRIVILEGES FOR ROLE app_owner IN SCHEMA public
    GRANT SELECT ON TABLES TO app_readonly;

ALTER DEFAULT PRIVILEGES FOR ROLE app_owner IN SCHEMA public
    GRANT USAGE ON SEQUENCES TO app_user;
```

### Create login users assigned to roles

```sql
-- Migration runner (uses app_owner)
CREATE USER migration_user WITH PASSWORD '***' IN ROLE app_owner;

-- Application service account (uses app_user)
CREATE USER appservice_user WITH PASSWORD '***' IN ROLE app_user;

-- Reporting/dashboard account (uses app_readonly)
CREATE USER report_user WITH PASSWORD '***' IN ROLE app_readonly;
```

### Audit current permissions

```sql
-- Check table-level grants
SELECT
    grantee,
    table_schema,
    table_name,
    privilege_type
FROM information_schema.table_privileges
WHERE table_schema = 'public'
ORDER BY grantee, table_name, privilege_type;
```

```sql
-- Check schema-level grants
SELECT
    nspname AS schema,
    pg_catalog.has_schema_privilege(r.rolname, n.nspname, 'CREATE') AS can_create,
    pg_catalog.has_schema_privilege(r.rolname, n.nspname, 'USAGE')  AS can_use
FROM pg_namespace n
CROSS JOIN pg_roles r
WHERE nspname = 'public'
  AND r.rolname IN ('app_owner', 'app_user', 'app_readonly')
ORDER BY r.rolname;
```

### Revoke dangerous defaults

```sql
-- Prevent PUBLIC from creating objects in public schema
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- Prevent PUBLIC from connecting to sensitive databases (optional)
REVOKE CONNECT ON DATABASE "myapp" FROM PUBLIC;
GRANT CONNECT ON DATABASE "myapp" TO app_owner, app_user, app_readonly;
```

## Schema Isolation Pattern

For databases with multiple schemas (e.g., `operations`, `staging`):

```sql
-- Create isolated schema
CREATE SCHEMA operations AUTHORIZATION app_owner;

-- Grant per-schema access
GRANT USAGE ON SCHEMA operations TO app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA operations TO app_user;

-- Readonly sees public but not operations
GRANT USAGE ON SCHEMA public TO app_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO app_readonly;
-- (no grant on operations schema for app_readonly)
```

## Azure Flexible Server Notes

- The admin user (`psqladmin`) has `azure_pg_admin` role, NOT true superuser
- `psqladmin` can create roles and grant permissions
- `psqladmin` cannot modify `shared_preload_libraries` directly (use Azure Portal)
- Password rotation should use Azure Key Vault references in connection strings
- Managed Identity (Entra ID) authentication is available but requires
  `azure_ad_admin` configuration

## When to Use

- When setting up a new database (greenfield)
- When hardening an existing database (brownfield audit finding)
- Before deploying application service accounts
- When creating read-only access for dashboards or reporting tools

## Where We Applied It

- **Best Practices**: Documented as mandatory security pattern
- **Audit TDDs**: Role separation listed as a finding in all three audits

## Related Skills

- **Skill #18** (Schema Separation) -- schema-level isolation for multi-tenant
- **Skill #27** (Naming Conventions) -- role naming follows snake_case
- **Skill #04** (Idempotent Migrations) -- role creation scripts must be idempotent

## References

- [PostgreSQL Best Practices](../DOCUMENTS/PostgreSQL_BestPractices_Azure.md)
  -- "Security essentials" and "Roles & grants" sections
- [User Management Audit TDD](../DOCUMENTS/user_mgmt_DB_Audit_TDD.md)
  -- Permission audit findings

## Gotchas

- `GRANT ALL` on a **schema** gives `CREATE` + `USAGE` -- it does NOT grant
  permissions on tables within the schema (those are separate)
- `ALTER DEFAULT PRIVILEGES` only applies to objects created **after** the
  command runs -- existing tables need explicit GRANT
- `ALTER DEFAULT PRIVILEGES` is scoped to the **creating role** -- if
  `psqladmin` creates a table, `app_owner`'s default privileges do not apply
- Per-schema `ALTER DEFAULT PRIVILEGES ... REVOKE` can only reverse a
  previous per-schema GRANT -- it cannot revoke global defaults
  (PG 16 docs: sql-alterdefaultprivileges.html)
- **Sequence permissions are separate from table permissions** -- granting
  on a table does NOT extend to sequences used by that table. Always grant
  `USAGE ON ALL SEQUENCES` explicitly for roles that INSERT
  (PG 16 docs: sql-grant.html)
- `REVOKE CREATE ON SCHEMA public FROM PUBLIC` may break extensions that
  create objects in public -- test after revoking
- On Azure, you cannot `CREATE ROLE ... SUPERUSER` -- use `azure_pg_admin`
  for administrative tasks
- Role membership is inherited by default (`INHERIT`). Use `NOINHERIT` if
  you want explicit `SET ROLE` activation
- `DROP OWNED BY <role>` drops ALL objects owned by that role -- use with
  extreme caution during role cleanup

---

*Category: Safety | Origin: Best Practices*
