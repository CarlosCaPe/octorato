---
name: ddl-export-snapshot-management
description: "DDL Export & Snapshot Management"
metadata:
  short-description: "DDL Export & Snapshot Management"
  original-index: 12
---

# DDL Export & Snapshot Management

## What

A suite of Node.js scripts that export database schemas to local files for
offline analysis, code review, and version control. Three complementary tools
produce different views of the same database.

## Why

You can't grep a live database. By exporting schemas to local files, you can:
- Search across all procedures with grep/ripgrep
- Track schema changes over time via git
- Code review DDL changes before and after deployment
- Work offline when VNET blocks database access

## How

### Three export layers

| Tool | Command | Output | Best For |
|------|---------|--------|----------|
| `export_schema.js` | `node scripts/audit/export_schema.js --env dev --db MyDB` | `schemas/public.sql` (monolithic pg_dump) | Full schema backup |
| `generate_simple_ddl.js` | `node scripts/audit/generate_simple_ddl.js --env dev --db MyDB` | `simple_ddl/public/table_*.sql` (per-table) | Table structure review |
| `generate_templated_ddl.js` | `node scripts/audit/generate_templated_ddl.js --env dev --db MyDB` | `schemas/public/Procedures/*.sql`, `Tables/*.sql` (per-object) | Procedure-level grep |

### Output structure
```
database/postgresql/dev/<server>/<database>/
    schemas/
        public.sql                          # monolithic pg_dump
        public/
            Procedures/
                AddApplicant__ed99d064c842.sql
                GetApplicant__9a46e1f5494b.sql
                ...
            Tables/
                Applicant__<hash>.sql
                ...
            Functions/
            Comments/
            Grants/
    simple_ddl/
        public/
            table_Applicant.sql
            table_Hospital.sql
            ...
```

### Multi-target export
```bash
# Export all targets defined in config/targets.yaml
node scripts/audit/export_all.js
```

### Configuration
Targets are defined in `config/targets.yaml`:
```yaml
targets:
  - name: QA
    host: ${DB_HOST_QA}
    databases: [MyDB_QA, OtherDB_QA]
  - name: DEV
    host: ${DB_HOST_DEV}
    databases: [MyDB_DEV]
```

## Refresh Workflow

Before a code review, always refresh snapshots:
```bash
# 1. Monolithic schema dump
node scripts/audit/export_schema.js --env dev --db myapp_dev

# 2. Per-table DDLs
node scripts/audit/generate_simple_ddl.js --env dev --db myapp_dev

# 3. Per-object split files (Procedures/, Tables/, etc.)
node scripts/audit/generate_templated_ddl.js --env dev --db myapp_dev
```

## When to Use

- Before every code review (refresh from live database)
- After every deployment (capture post-deployment state)
- When onboarding to a new database (initial snapshot)

## Where We Used It

- **DA-102**: Refreshed all 3 layers to verify column renames and procedure
  updates were applied in DEV. Grep of refreshed split files confirmed
  0 old misspelled column references across all 87 procedures.
- **All tickets**: Initial schema discovery and procedure analysis

## Gotchas

- `generate_templated_ddl.js` **deletes** the monolithic `public.sql` if
  `clean_schema_root` is enabled -- run `export_schema.js` again after it
- Simple DDL only exports **table structures** (no procedures, views, etc.)
- File hashes in names (e.g., `__ed99d064c842`) change when the object
  definition changes -- git will show a delete + create, not a rename
- VNET-blocked servers will fail silently or timeout -- always check output

---

*Category: Tooling | Origin: All tickets*
