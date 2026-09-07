---
name: querymaster-sqlserver
description: "Child skill of querymaster for SQL Server and Azure SQL (Database, Managed Instance, on-prem): pyodbc connection with an Azure AD token and T-SQL best practices. Activates when the resolved engine is SQL Server."
---

# QueryMaster — SQL Server / Azure SQL Engine Skill

> Child skill of `querymaster`. Activated when engine is SQL Server or Azure SQL.
> Covers: Azure SQL Database, Azure SQL Managed Instance, SQL Server on-prem.

## Connection Patterns

### Python (pyodbc) — Azure AD Interactive Browser
```python
import pyodbc
from azure.identity import InteractiveBrowserCredential
import struct

credential = InteractiveBrowserCredential()
token = credential.get_token("https://database.windows.net/.default")
token_bytes = token.token.encode("utf-16-le")
token_struct = struct.pack(f"<I{len(token_bytes)}s", len(token_bytes), token_bytes)

conn_str = (
    f"Driver={{ODBC Driver 17 for SQL Server}};"
    f"Server={env['SQL_SERVER']};"
    f"Database={env['SQL_DATABASE']};"
)
conn = pyodbc.connect(conn_str, attrs_before={1256: token_struct})
```

### Python (pyodbc) — SQL Authentication
```python
conn_str = (
    f"Driver={{ODBC Driver 17 for SQL Server}};"
    f"Server={env['SQL_SERVER']};"
    f"Database={env['SQL_DATABASE']};"
    f"UID={env['SQL_USER']};"
    f"PWD={env['SQL_PASSWORD']};"
    "Encrypt=yes;TrustServerCertificate=no;"
)
conn = pyodbc.connect(conn_str)
```

### Python (aioodbc) — Async for Azure Functions
```python
import aioodbc
conn = await aioodbc.connect(dsn=conn_str)
```

### Node.js (mssql)
```javascript
const sql = require('mssql');
const config = {
    server: process.env.SQL_SERVER,
    database: process.env.SQL_DATABASE,
    authentication: { type: 'azure-active-directory-default' },
    options: { encrypt: true, trustServerCertificate: false }
};
const pool = await sql.connect(config);
```

### connections.json entry
```json
{
  "sql_azure_dev": {
    "engine": "sqlserver",
    "auth": "azure_ad",
    "env_file": "~/path/to/client-b/.env",
    "env_vars": { "server": "SQL_SERVER_DEV", "database": "SQL_DATABASE_DEV" }
  },
  "sql_azure_prod": {
    "engine": "sqlserver",
    "auth": "azure_ad",
    "env_file": "~/path/to/client-b/.env",
    "env_vars": { "server": "SQL_SERVER_PROD", "database": "SQL_DATABASE_PROD" }
  }
}
```

## Best Practices

### Query Generation Rules

1. **Use square brackets** for identifiers: `[schema].[table].[column]`
2. **TOP instead of LIMIT**: `SELECT TOP 1000 ...` (T-SQL syntax)
3. **Schema-qualify** — Always `dbo.table_name` or `schema.table_name`
4. **NOLOCK hint sparingly** — `WITH (NOLOCK)` only for non-critical reads
5. **Prefer SET NOCOUNT ON** — Reduce network chatter in procedures
6. **Date functions** — `GETDATE()` / `GETUTCDATE()`, `DATEADD`, `DATEDIFF`, `FORMAT`
7. **String concat** — Use `CONCAT()` or `+`, never `||` (that's PostgreSQL)
8. **NULL handling** — `ISNULL()` or `COALESCE()`, not `IFNULL()`
9. **EXISTS over IN** — For subqueries, `EXISTS` is generally faster

### Schema Discovery Queries

```sql
-- List all schemas
SELECT name AS schema_name
FROM sys.schemas
WHERE name NOT IN ('guest', 'INFORMATION_SCHEMA', 'sys')
ORDER BY name;

-- Tables with row counts and sizes
SELECT
    s.name AS schema_name,
    t.name AS table_name,
    p.rows AS row_count,
    CAST(ROUND(SUM(a.total_pages) * 8.0 / 1024, 2) AS DECIMAL(18,2)) AS size_mb,
    t.create_date, t.modify_date
FROM sys.tables t
JOIN sys.schemas s ON t.schema_id = s.schema_id
JOIN sys.indexes i ON t.object_id = i.object_id
JOIN sys.partitions p ON i.object_id = p.object_id AND i.index_id = p.index_id
JOIN sys.allocation_units a ON p.partition_id = a.container_id
WHERE i.index_id <= 1
GROUP BY s.name, t.name, p.rows, t.create_date, t.modify_date
ORDER BY p.rows DESC;

-- Missing indexes (DMVs)
SELECT TOP 20
    d.statement AS table_name,
    d.equality_columns,
    d.inequality_columns,
    d.included_columns,
    s.avg_user_impact,
    s.user_seeks + s.user_scans AS total_usage
FROM sys.dm_db_missing_index_details d
JOIN sys.dm_db_missing_index_groups g ON d.index_handle = g.index_handle
JOIN sys.dm_db_missing_index_group_stats s ON g.index_group_handle = s.group_handle
ORDER BY s.avg_user_impact * (s.user_seeks + s.user_scans) DESC;

-- Index usage stats
SELECT
    OBJECT_SCHEMA_NAME(i.object_id) AS schema_name,
    OBJECT_NAME(i.object_id) AS table_name,
    i.name AS index_name,
    i.type_desc,
    s.user_seeks, s.user_scans, s.user_lookups, s.user_updates,
    CAST(ROUND(ps.used_page_count * 8.0 / 1024, 2) AS DECIMAL(18,2)) AS size_mb
FROM sys.indexes i
LEFT JOIN sys.dm_db_index_usage_stats s
    ON i.object_id = s.object_id AND i.index_id = s.index_id
JOIN sys.dm_db_partition_stats ps
    ON i.object_id = ps.object_id AND i.index_id = ps.index_id
WHERE OBJECTPROPERTY(i.object_id, 'IsUserTable') = 1
    AND i.name IS NOT NULL
ORDER BY s.user_seeks + s.user_scans + s.user_lookups ASC;

-- Active sessions / blocking
SELECT
    r.session_id, r.blocking_session_id,
    r.status, r.command, r.wait_type,
    r.total_elapsed_time / 1000 AS elapsed_sec,
    SUBSTRING(qt.text, r.statement_start_offset/2 + 1,
        (CASE WHEN r.statement_end_offset = -1
            THEN LEN(CONVERT(NVARCHAR(MAX), qt.text)) * 2
            ELSE r.statement_end_offset END - r.statement_start_offset) / 2 + 1
    ) AS query_text
FROM sys.dm_exec_requests r
CROSS APPLY sys.dm_exec_sql_text(r.sql_handle) qt
WHERE r.session_id != @@SPID
ORDER BY r.total_elapsed_time DESC;

-- Stored procedures list
SELECT
    s.name AS schema_name,
    p.name AS procedure_name,
    p.create_date, p.modify_date
FROM sys.procedures p
JOIN sys.schemas s ON p.schema_id = s.schema_id
ORDER BY s.name, p.name;

-- Table structure
SELECT
    c.name AS column_name,
    t.name AS data_type,
    c.max_length, c.precision, c.scale,
    c.is_nullable, c.is_identity,
    dc.definition AS default_value
FROM sys.columns c
JOIN sys.types t ON c.user_type_id = t.user_type_id
LEFT JOIN sys.default_constraints dc ON c.default_object_id = dc.object_id
WHERE c.object_id = OBJECT_ID('schema.table_name')
ORDER BY c.column_id;
```

### MERGE Pattern (Upsert)

```sql
MERGE INTO target_table AS tgt
USING source_table AS src
ON tgt.id = src.id
WHEN MATCHED THEN
    UPDATE SET tgt.col1 = src.col1, tgt.col2 = src.col2
WHEN NOT MATCHED BY TARGET THEN
    INSERT (id, col1, col2)
    VALUES (src.id, src.col1, src.col2);
```

---

## Memory-Optimized Tables (In-Memory OLTP)

### Check memory-optimized status
```sql
SELECT t.name AS table_name, t.is_memory_optimized
FROM sys.tables t
WHERE t.name IN ('DRILL_CYCLE', 'LOAD_HAUL__LH_BUCKET')
ORDER BY t.name;
```

### Memory-optimized Table Types (for TVPs)
```sql
SELECT tt.name AS type_name, tt.is_memory_optimized
FROM sys.table_types tt
WHERE tt.name LIKE '%IMO%'
ORDER BY tt.name;
```

**Key pattern**: DEV environments typically have `is_memory_optimized=OFF`; PROD has `ON`. Always verify before deploying procedures that expect in-memory types.

---

## Dynamic MERGE Procedure Generation

Generate MERGE procedures dynamically from table type metadata:

```sql
-- Get columns from a Table Type
SELECT c.name
FROM sys.columns c
JOIN sys.table_types tt ON c.object_id = tt.type_table_object_id
WHERE tt.name = 'LOAD_HAUL__LH_BUCKET_IMO'
ORDER BY c.column_id;

-- Generate MERGE proc
CREATE OR ALTER PROCEDURE [dbo].[usp_Merge_LH_BUCKET]
    @Data [dbo].[LOAD_HAUL__LH_BUCKET_IMO] READONLY
AS
BEGIN
    SET NOCOUNT ON;
    MERGE [dbo].[LOAD_HAUL__LH_BUCKET] AS target
    USING @Data AS source
    ON target.[BUCKET_ID] = source.[BUCKET_ID]
    WHEN MATCHED THEN UPDATE SET ...
    WHEN NOT MATCHED THEN INSERT (...) VALUES (...);
    SELECT @@ROWCOUNT AS RowsAffected;
END
```

---

## Schema Extraction (Multi-Environment)

### Azure AD token authentication
```python
from azure.identity import InteractiveBrowserCredential
import struct, pyodbc

credential = InteractiveBrowserCredential()
token = credential.get_token("https://database.windows.net/.default")
token_bytes = token.token.encode("UTF-16-LE")
token_struct = struct.pack(f'<I{len(token_bytes)}s', len(token_bytes), token_bytes)

SQL_COPT_SS_ACCESS_TOKEN = 1256
conn = pyodbc.connect(conn_str, attrs_before={SQL_COPT_SS_ACCESS_TOKEN: token_struct})
```

### Extract all object types
```sql
-- Tables
SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = @schema AND TABLE_TYPE = 'BASE TABLE';

-- Views
SELECT TABLE_NAME FROM INFORMATION_SCHEMA.VIEWS WHERE TABLE_SCHEMA = @schema;

-- Stored procedures
SELECT ROUTINE_NAME FROM INFORMATION_SCHEMA.ROUTINES WHERE ROUTINE_SCHEMA = @schema AND ROUTINE_TYPE = 'PROCEDURE';

-- Functions
SELECT ROUTINE_NAME FROM INFORMATION_SCHEMA.ROUTINES WHERE ROUTINE_SCHEMA = @schema AND ROUTINE_TYPE = 'FUNCTION';

-- Table Types (user-defined)
SELECT tt.name FROM sys.table_types tt ORDER BY tt.name;

-- Triggers
SELECT name, OBJECT_NAME(parent_id) AS table_name FROM sys.triggers;
```

### Multi-environment deployment (DEV → TEST → PROD)
Pattern: Extract DDL from one env, diff against target, generate migration scripts.

---

### Safety Guards

- **Never generate** `DROP TABLE` without `IF OBJECT_ID('...') IS NOT NULL`
- **Never generate** `DELETE` without `WHERE` — require explicit user request
- **Transaction wrapping** — Suggest `BEGIN TRAN; ... ROLLBACK;` for testing destructive ops
- **Azure-specific** — Warn about DTU/vCore limits, elastic pool constraints
- **ODBC driver check** — Verify ODBC Driver 17/18 is installed before execution

### Common Prompt → SQL Mappings

| User says | Generated SQL |
|-----------|--------------|
| "table sizes" | sys.tables + sys.allocation_units |
| "missing indexes" | sys.dm_db_missing_index_details |
| "slow queries" | sys.dm_exec_query_stats + sys.dm_exec_sql_text |
| "blocking" | sys.dm_exec_requests with blocking_session_id |
| "stored procedures" | sys.procedures |
| "who is connected" | sys.dm_exec_sessions |
| "database size" | sys.database_files |
| "fragmentation" | sys.dm_db_index_physical_stats |
| "memory-optimized" | sys.tables WHERE is_memory_optimized = 1 |
| "table types" | sys.table_types |

### Error Handling

| Error | Cause | Action |
|-------|-------|--------|
| `Login failed for user` | Wrong credentials or no access | Check .env, verify Azure AD permissions |
| `Cannot open database` | DB doesn't exist or no access | Verify SQL_DATABASE value |
| `ODBC Driver not found` | Driver not installed | Install `msodbcsql17` or `msodbcsql18` |
| `Token expired` | Azure AD token timed out | Re-authenticate with browser |
| `timeout expired` | Query too slow | Increase --timeout, check query plan |
| `Table type is_memory_optimized mismatch` | DEV vs PROD config difference | Verify env-specific table type definitions |

---

## Lessons Learned

> Auto-populated when queries fail.

| Date | Error Pattern | Root Cause | Fix |
|------|--------------|-----------|-----|
<!-- New lessons appended here -->
