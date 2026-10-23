---
name: querymaster-snowflake
description: "Child skill of querymaster for Snowflake: connection via Browser SSO, OAuth and service user/password, REST SQL API and warehouse best practices. Activates when the resolved engine is Snowflake."
---

# QueryMaster — Snowflake Engine Skill

> Child skill of `querymaster`. Activated when engine is Snowflake.
> Covers: Snowflake (Python connector, REST SQL API, Browser SSO, OAuth).

## Connection Patterns

### Python (snowflake-connector-python) — Browser SSO
```python
import snowflake.connector
conn = snowflake.connector.connect(
    account=env["CONN_LIB_SNOWFLAKE_ACCOUNT"],
    authenticator="externalbrowser",
    role=env.get("CONN_LIB_SNOWFLAKE_ROLE", "PUBLIC"),
    warehouse=env.get("CONN_LIB_SNOWFLAKE_WAREHOUSE"),
    database=env.get("CONN_LIB_SNOWFLAKE_DATABASE"),
)
```

### Python — User/Password (service accounts)
```python
conn = snowflake.connector.connect(
    account=env["SNOWFLAKE_ACCOUNT"],
    user=env["SNOWFLAKE_USER"],
    password=env["SNOWFLAKE_PASSWORD"],
    role=env.get("SNOWFLAKE_ROLE"),
    warehouse=env.get("SNOWFLAKE_WAREHOUSE"),
    database=env.get("SNOWFLAKE_DATABASE"),
    schema=env.get("SNOWFLAKE_SCHEMA"),
)
```

### REST SQL API (Azure Functions / OAuth)
```python
from azure.identity import ClientSecretCredential
credential = ClientSecretCredential(tenant_id, client_id, client_secret)
token = credential.get_token(f"https://{account}.snowflakecomputing.com/.default")
# POST https://{account}.snowflakecomputing.com/api/v2/statements
headers = {"Authorization": f"Bearer {token.token}", "Content-Type": "application/json"}
body = {"statement": sql, "warehouse": warehouse, "database": database, "schema": schema}
```

### connections.json entry
```json
{
  "snowflake_client": {
    "engine": "snowflake",
    "auth": "browser_sso",
    "env_file": "~/path/to/client-b/.env",
    "env_prefix": "CONN_LIB_SNOWFLAKE"
  },
  "snowflake_svc": {
    "engine": "snowflake",
    "auth": "password",
    "env_file": "~/path/to/client-b/.env",
    "env_prefix": "SNOWFLAKE"
  }
}
```

## Best Practices

### Query Generation Rules

1. **Qualify with database and schema** — `DATABASE.SCHEMA.TABLE`
2. **Uppercase SQL keywords** — Snowflake convention: `SELECT`, `FROM`, `WHERE`
3. **Double-quote identifiers only when mixed-case** — Snowflake folds to UPPERCASE by default
4. **Use VARIANT/OBJECT/ARRAY correctly** — Semi-structured access: `col:key::type`
5. **Warehouse awareness** — Queries consume credits; always consider warehouse size
6. **Result caching** — Identical queries within 24h return cached results (no credits)
7. **LIMIT always** — Default `LIMIT 1000` to prevent massive result sets

### Schema Discovery Queries

```sql
-- List all databases
SHOW DATABASES;

-- List schemas in current database
SHOW SCHEMAS IN DATABASE identifier($database);

-- List tables with row counts
SELECT
    TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME,
    ROW_COUNT, BYTES,
    ROUND(BYTES / 1024 / 1024, 2) AS SIZE_MB,
    CREATED, LAST_ALTERED
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA NOT IN ('INFORMATION_SCHEMA')
    AND TABLE_TYPE = 'BASE TABLE'
ORDER BY ROW_COUNT DESC NULLS LAST;

-- Column details
SELECT
    TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME,
    DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT,
    CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_NAME = $1
ORDER BY ORDINAL_POSITION;

-- Warehouse usage (credits)
SELECT
    WAREHOUSE_NAME, START_TIME, END_TIME,
    CREDITS_USED, CREDITS_USED_COMPUTE,
    CREDITS_USED_CLOUD_SERVICES
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
WHERE START_TIME >= DATEADD('day', -7, CURRENT_TIMESTAMP())
ORDER BY START_TIME DESC;

-- Query history (slow queries)
SELECT
    QUERY_ID, QUERY_TEXT, DATABASE_NAME,
    WAREHOUSE_NAME, EXECUTION_STATUS,
    TOTAL_ELAPSED_TIME / 1000 AS ELAPSED_SECONDS,
    ROWS_PRODUCED, BYTES_SCANNED
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE TOTAL_ELAPSED_TIME > 30000  -- > 30s
    AND START_TIME >= DATEADD('day', -1, CURRENT_TIMESTAMP())
ORDER BY TOTAL_ELAPSED_TIME DESC
LIMIT 20;

-- Storage usage
SELECT
    TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME,
    ACTIVE_BYTES, TIME_TRAVEL_BYTES, FAILSAFE_BYTES,
    ROUND((ACTIVE_BYTES + TIME_TRAVEL_BYTES + FAILSAFE_BYTES) / 1024 / 1024, 2) AS TOTAL_MB
FROM SNOWFLAKE.ACCOUNT_USAGE.TABLE_STORAGE_METRICS
WHERE TABLE_CATALOG = CURRENT_DATABASE()
    AND ACTIVE_BYTES > 0
ORDER BY TOTAL_MB DESC
LIMIT 50;
```

### Semi-Structured Data Patterns

```sql
-- Access VARIANT column fields
SELECT
    col:name::STRING AS name,
    col:age::INT AS age,
    col:address.city::STRING AS city
FROM my_table;

-- Flatten arrays
SELECT
    t.id,
    f.value::STRING AS tag
FROM my_table t,
    LATERAL FLATTEN(input => t.tags) f;

-- Parse JSON in stage files
SELECT
    $1:timestamp::TIMESTAMP_NTZ AS ts,
    $1:value::FLOAT AS val
FROM @my_stage/data.json.gz (FILE_FORMAT => 'json_format');
```

### Safety Guards

- **Never generate** `DROP DATABASE` or `DROP SCHEMA` — require explicit double confirmation
- **Warehouse cost warning** — Warn when queries target large tables without filters
- **Time travel awareness** — Warn that `DELETE`/`UPDATE` can be undone with `AT(TIMESTAMP => ...)`
- **Role check** — `SELECT CURRENT_ROLE()` before destructive operations
- **Clone suggestion** — For testing destructive ops, suggest `CREATE TABLE ... CLONE ...`

### Common Prompt → SQL Mappings

| User says | Generated SQL |
|-----------|--------------|
| "table sizes" | INFORMATION_SCHEMA.TABLES with ROW_COUNT, BYTES |
| "slow queries" | ACCOUNT_USAGE.QUERY_HISTORY ordered by elapsed time |
| "credit usage" | ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY |
| "schemas" | SHOW SCHEMAS |
| "warehouses" | SHOW WAREHOUSES |
| "who's running queries" | INFORMATION_SCHEMA.QUERY_HISTORY where IS_RUNNING |
| "stored procedures" | SHOW PROCEDURES IN SCHEMA |
| "views" | SHOW VIEWS IN SCHEMA |
| "stages" | SHOW STAGES |
| "file format" | SHOW FILE FORMATS |

---

## Search Optimization Service (SOS)

Enable point-lookup acceleration on large tables (billions of rows).

### Enable SOS on specific columns
```sql
ALTER TABLE PROD_DATALAKE.FCTS.SENSOR_READING_SAM_B
    ADD SEARCH OPTIMIZATION ON EQUALITY(SITE_CODE, SENSOR_ID);
```

### Clone + SOS pattern (sandbox testing)
```sql
-- Clone prod table to sandbox (zero-copy, instant)
CREATE OR REPLACE TRANSIENT TABLE SANDBOX_DATA_ENGINEER.CCARRILL2.FCTS_SENSOR_READING_SAM_B
    CLONE PROD_DATALAKE.FCTS.SENSOR_READING_SAM_B;

-- Enable SOS on clone for testing
ALTER TABLE SANDBOX_DATA_ENGINEER.CCARRILL2.FCTS_SENSOR_READING_SAM_B
    ADD SEARCH OPTIMIZATION ON EQUALITY(SITE_CODE, SENSOR_ID);
```

### When to use SOS

| Scenario | SOS? |
|----------|------|
| Point lookups on billion-row tables | Yes |
| Full table scans / analytics | No (clustering better) |
| Multi-column equality filters | Yes |
| Range scans on timestamps | No (clustering better) |

---

## Clustering & Copy-and-Swap

Re-cluster large tables for query performance using transient copy-and-swap.

### Check clustering stats
```sql
SELECT SYSTEM$CLUSTERING_INFORMATION('DB.SCHEMA.TABLE', '(SITE_CODE, SENSOR_ID, VALUE_UTC_TS)');
```

### Transient copy-and-swap (re-cluster)
```sql
-- 1. Build new clustered copy (expensive, use large warehouse)
CREATE OR REPLACE TRANSIENT TABLE DB.SCHEMA.TABLE__CLUST_TMP
    CLUSTER BY (SITE_CODE, SENSOR_ID, VALUE_UTC_TS)
AS SELECT * FROM DB.SCHEMA.TABLE;

-- 2. Atomic swap (rename)
ALTER TABLE DB.SCHEMA.TABLE RENAME TO DB.SCHEMA.TABLE__OLD;
ALTER TABLE DB.SCHEMA.TABLE__CLUST_TMP RENAME TO DB.SCHEMA.TABLE;

-- 3. Cleanup
DROP TABLE DB.SCHEMA.TABLE__OLD;
```

**Gotcha**: CTAS on multi-TB tables is very expensive. Always use `--confirm` flag pattern (dry-run default).

---

## Streams & Tasks (Incremental ETL)

Replace truncate+reload with change data capture.

### Create stream on source
```sql
CREATE OR REPLACE STREAM CDC__DRILL_CYCLE__STRM
    ON VIEW PROD_WG.DRILL_BLAST.DRILL_CYCLE
    SHOW_INITIAL_ROWS = FALSE;
```

### Change detection metadata columns
- `METADATA$ACTION` — INSERT or DELETE (updates = DELETE + INSERT pair)
- `METADATA$ISUPDATE` — TRUE if the row is part of an update
- `METADATA$ROW_ID` — Unique row identifier

### MERGE pattern from stream
```sql
-- Delete pass (apply deletes first)
DELETE FROM CDC__DRILL_CYCLE__CURRENT tgt
USING CDC__DRILL_CYCLE__STRM src
WHERE src.METADATA$ACTION = 'DELETE'
    AND tgt.ORIG_SRC_ID = src.ORIG_SRC_ID
    AND tgt.SITE_CODE = src.SITE_CODE;

-- Upsert pass
MERGE INTO CDC__DRILL_CYCLE__CURRENT tgt
USING (SELECT * FROM CDC__DRILL_CYCLE__STRM WHERE METADATA$ACTION = 'INSERT') src
ON tgt.ORIG_SRC_ID = src.ORIG_SRC_ID AND tgt.SITE_CODE = src.SITE_CODE
WHEN MATCHED THEN UPDATE SET ...
WHEN NOT MATCHED THEN INSERT (...) VALUES (...);
```

### Automate with task
```sql
CREATE OR REPLACE TASK CDC__DRILL_CYCLE__APPLY_TASK
    WAREHOUSE = WH_BATCH_DE
    SCHEDULE = '5 MINUTE'
AS CALL CDC__APPLY_DRILL_CYCLE();

ALTER TASK CDC__DRILL_CYCLE__APPLY_TASK RESUME;
```

**Key insight**: Updates in Snowflake streams surface as DELETE + INSERT pairs (`METADATA$ISUPDATE=TRUE`). Apply deletes first, then upserts.

---

## Role & Warehouse Discovery

### Show current user, role, and role hierarchy
```sql
SELECT CURRENT_USER(), CURRENT_ROLE();
SHOW GRANTS TO USER "username";
SHOW GRANTS OF ROLE "rolename";
```

### List accessible warehouses
```sql
SHOW WAREHOUSES;
```

### Check role grants on an object
```sql
SHOW GRANTS ON TABLE DB.SCHEMA.TABLE;
SHOW GRANTS ON DATABASE DB;
```

---

## Stored Procedure Patterns

### Get procedure DDL
```sql
SELECT GET_DDL('PROCEDURE', 'DB.SCHEMA.PROC_NAME(arg_types)');
```

### Multi-site deployment pattern
When deploying to Snowflake across multiple sites (e.g., mining operations):
1. Deploy to sandbox/dev first with `CREATE OR REPLACE`
2. Validate with site-specific test queries
3. Deploy to prod using the same DDL

---

## Query Refactoring Harness

Production pattern for safe query refactoring:
1. **Baseline**: Save current query + results
2. **Refactor**: Write optimized query
3. **Compare**: Run both, compare row counts + checksums
4. **Validate**: Ensure zero diff before deploying refactored version

```sql
-- Baseline query
CREATE OR REPLACE TABLE SANDBOX.BASELINE_RESULTS AS SELECT * FROM ...;

-- Refactor query
CREATE OR REPLACE TABLE SANDBOX.REFACTOR_RESULTS AS SELECT * FROM ...;

-- Compare
SELECT
    (SELECT COUNT(*) FROM SANDBOX.BASELINE_RESULTS) AS baseline_rows,
    (SELECT COUNT(*) FROM SANDBOX.REFACTOR_RESULTS) AS refactor_rows,
    (SELECT HASH_AGG(*) FROM SANDBOX.BASELINE_RESULTS) AS baseline_hash,
    (SELECT HASH_AGG(*) FROM SANDBOX.REFACTOR_RESULTS) AS refactor_hash;
```

---

### Error Handling

| Error | Cause | Action |
|-------|-------|--------|
| `250001: Could not connect` | Account URL wrong | Verify SNOWFLAKE_ACCOUNT format: `orgname-acctname` |
| `browser_sso timeout` | Browser not opened | Check default browser, try password auth |
| `Warehouse X is suspended` | Warehouse auto-suspended | Will auto-resume on query |
| `Insufficient privileges` | Role lacks permissions | `SHOW GRANTS TO ROLE current_role()` |
| `100035: Object does not exist` | Wrong database/schema context | Fully qualify: `DB.SCHEMA.TABLE` |
| `Stream has been consumed` | Stream data already read | Recreate stream or use append-only |
| `Cannot clone transient table to permanent` | Clone type mismatch | Use `CREATE TRANSIENT TABLE ... CLONE` |

---

## Lessons Learned

> Auto-populated when queries fail.

| Date | Error Pattern | Root Cause | Fix |
|------|--------------|-----------|-----|
<!-- New lessons appended here -->
