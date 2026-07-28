---
name: querymaster-databricks
description: "Skill hijo de querymaster para Databricks. PLACEHOLDER: aun no hay workspace ni cluster provisionado, solo la plantilla de conexion con databricks-sql-connector. Se completa cuando exista acceso."
---

# QueryMaster — Databricks Engine Skill (Placeholder)

> Child skill of `querymaster`. Activated when engine is Databricks.
> **Status: PLACEHOLDER** — No active workspace/cluster available yet.
> This skill will be completed when Databricks access is provisioned.

## Connection Patterns (Template)

### Python (databricks-sql-connector)
```python
from databricks import sql

conn = sql.connect(
    server_hostname=env["DATABRICKS_HOST"],       # adb-xxxx.azuredatabricks.net
    http_path=env["DATABRICKS_HTTP_PATH"],         # /sql/1.0/warehouses/xxxx
    access_token=env["DATABRICKS_TOKEN"],          # PAT or OAuth token
)
cursor = conn.cursor()
cursor.execute("SELECT 1")
```

### Python — OAuth (Azure AD)
```python
from azure.identity import DefaultAzureCredential
credential = DefaultAzureCredential()
token = credential.get_token("2ff814a6-3304-4ab8-85cb-cd0e6f879c1d/.default")  # Databricks resource ID

conn = sql.connect(
    server_hostname=env["DATABRICKS_HOST"],
    http_path=env["DATABRICKS_HTTP_PATH"],
    credentials_provider=lambda: {"Authorization": f"Bearer {token.token}"},
)
```

### connections.json entry (template)
```json
{
  "databricks_dev": {
    "engine": "databricks",
    "auth": "pat",
    "env_file": "~/Documents/github/PROJECT/.env",
    "env_vars": {
      "host": "DATABRICKS_HOST",
      "http_path": "DATABRICKS_HTTP_PATH",
      "token": "DATABRICKS_TOKEN"
    }
  }
}
```

### .env template
```bash
DATABRICKS_HOST=adb-1234567890.azuredatabricks.net
DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/abcdef1234567890
DATABRICKS_TOKEN=dapi<YOUR_PERSONAL_ACCESS_TOKEN_HERE>
```

## Key Concepts

### Compute Types
- **SQL Warehouse** — Serverless/classic, for SQL analytics. Use `http_path=/sql/1.0/warehouses/...`
- **All-Purpose Cluster** — For notebooks/jobs. Use `http_path=/sql/protocolv1/o/.../...`
- **Jobs Cluster** — Ephemeral, for scheduled jobs. Not queryable interactively.

### Unity Catalog Hierarchy
```
Catalog → Schema (Database) → Table/View/Function
```
- **3-level namespace**: `catalog.schema.table`
- Default catalog: set per workspace or `USE CATALOG name;`

### Delta Lake
- Default table format on Databricks
- ACID transactions, time travel, schema evolution
- `DESCRIBE HISTORY table` — view all versions
- `SELECT * FROM table VERSION AS OF 5` — query specific version
- `OPTIMIZE table` — compact small files
- `VACUUM table RETAIN 168 HOURS` — clean old versions

## Schema Discovery Queries (Template)

```sql
-- List catalogs
SHOW CATALOGS;

-- List schemas in catalog
SHOW SCHEMAS IN catalog_name;

-- List tables in schema
SHOW TABLES IN catalog_name.schema_name;

-- Table details
DESCRIBE TABLE EXTENDED catalog.schema.table;

-- Column details
DESCRIBE catalog.schema.table;

-- Table history (Delta)
DESCRIBE HISTORY catalog.schema.table;

-- Table properties
SHOW TBLPROPERTIES catalog.schema.table;

-- Compute resources
-- (not queryable via SQL — use REST API or CLI)
```

## Safety Guards

- **Unity Catalog permissions** — Verify catalog/schema access before queries
- **Warehouse cost** — SQL Warehouses cost DBUs; warn for large scans
- **VACUUM warning** — Cannot undo; respects retention period
- **DROP protection** — Double confirmation for `DROP TABLE`, `DROP SCHEMA`, `DROP CATALOG`
- **PAT security** — Personal Access Tokens expire; rotate regularly

## TODO When Access Is Available

- [ ] Test connection with real workspace
- [ ] Discover available catalogs and schemas
- [ ] Add project-specific query patterns
- [ ] Benchmark query execution times
- [ ] Add Spark SQL-specific optimizations (partitioning, caching)
- [ ] Document DBU cost model for common query patterns
