---
name: schema-row-counts
description: Get exact row counts per table in a given schema — PostgreSQL primary, with notes for other engines. Two-column result: table_name, row_count.
metadata:
  type: skill
---

# schema-row-counts

Returns a two-column table (`table_name`, `row_count`) for every BASE TABLE in a schema.

## PostgreSQL — exact count (any schema)

```sql
SELECT
    table_name,
    (xpath('/row/cnt/text()',
           query_to_xml(format('SELECT COUNT(*) AS cnt FROM %I.%I', table_schema, table_name),
                        false, true, ''))
    )[1]::text::int AS row_count
FROM information_schema.tables
WHERE table_schema = '<schema>'        -- replace with target schema
  AND table_type   = 'BASE TABLE'
ORDER BY row_count DESC, table_name;
```

**Replace `<schema>`** with the target schema name (e.g., `payer`, `eligibility`, `public`).

## PostgreSQL — fast approximate (uses pg_stat, no full scan)

Use when tables are large and exact counts are not required (e.g., dashboards, health checks):

```sql
SELECT
    relname          AS table_name,
    n_live_tup       AS row_count
FROM pg_stat_user_tables
WHERE schemaname = '<schema>'
ORDER BY n_live_tup DESC, relname;
```

Stats lag behind until `ANALYZE` runs. Good for ballpark; not for audits.

## How to run (local Docker setup — newum_db pattern)

```powershell
# One-liner: replace payer with target schema
docker compose exec postgres psql -U $env:NEWUM_LOCAL_USER -d newum -c `
  "SELECT table_name, (xpath('/row/cnt/text()', query_to_xml(format('SELECT COUNT(*) AS cnt FROM payer.%I', table_name), false, true, '')))[1]::text::int AS row_count FROM information_schema.tables WHERE table_schema = 'payer' AND table_type = 'BASE TABLE' ORDER BY row_count DESC, table_name;"
```

## How to run (via QueryMaster)

```bash
qm -e postgresql -c <conn> "SELECT table_name, ... WHERE table_schema = '<schema>' ..." --execute
```

## MS-SQL equivalent

```sql
SELECT
    t.name            AS table_name,
    p.rows            AS row_count
FROM sys.tables t
JOIN sys.partitions p ON p.object_id = t.object_id
                     AND p.index_id IN (0, 1)
WHERE SCHEMA_NAME(t.schema_id) = '<schema>'
ORDER BY p.rows DESC, t.name;
```

## Databricks / Spark SQL equivalent

```sql
SHOW TABLES IN <schema>;
-- then per table:
SELECT COUNT(*) FROM <schema>.<table>;
-- or loop via notebook:
-- %python
-- for t in spark.catalog.listTables("<schema>"):
--     print(t.name, spark.table(f"<schema>.{t.name}").count())
```

## Lessons Learned

- 2026-05-15 (newUM/OncoHealth): Applied to `payer` schema post-seed validation. 30 rows in `payer`, 0 in all others (benefit_package, business_grain, business_grouping, employer_group, payer_organization_link). Confirmed seed ran clean.
- The `xpath/query_to_xml` trick is the canonical PostgreSQL pattern for dynamic per-table counts without PL/pgSQL or superuser permissions.
- `pg_stat_user_tables` is faster but requires a recent `ANALYZE` — safe for monitoring, not for audit assertions.
