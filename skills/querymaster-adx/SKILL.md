# QueryMaster — Azure Data Explorer (ADX) / KQL Engine Skill

> Child skill of `querymaster`. Activated when engine is Azure Data Explorer.
> Covers: ADX clusters, KQL (Kusto Query Language), real-time sensor/telemetry data.
> **Important:** ADX uses KQL, NOT SQL. Never generate SQL syntax for ADX.

## Connection Patterns

### Python (azure-kusto-data) — Browser SSO
```python
from azure.kusto.data import KustoClient, KustoConnectionStringBuilder
from azure.identity import InteractiveBrowserCredential

credential = InteractiveBrowserCredential()
kcsb = KustoConnectionStringBuilder.with_azure_token_credential(
    connection_string=env["ADX_CLUSTER_URL"],  # https://cluster.region.kusto.windows.net
    credential=credential
)
client = KustoClient(kcsb)
response = client.execute(database=env["ADX_DATABASE"], query=kql_query)
```

### Python — Managed Identity (Azure Functions)
```python
from azure.identity import DefaultAzureCredential
credential = DefaultAzureCredential()
kcsb = KustoConnectionStringBuilder.with_azure_token_credential(cluster_url, credential)
client = KustoClient(kcsb)
```

### connections.json entry
```json
{
  "adx_prod": {
    "engine": "adx",
    "auth": "browser_sso",
    "env_file": "~/path/to/client-b/.env",
    "env_vars": {
      "cluster": "ADX_CLUSTER_URL",
      "database": "ADX_DATABASE"
    }
  }
}
```

## KQL vs SQL — Critical Differences

| Concept | SQL | KQL |
|---------|-----|-----|
| Filter rows | `WHERE col = 'x'` | `| where col == "x"` |
| Select columns | `SELECT a, b` | `| project a, b` |
| Aliases | `SELECT a AS alias` | `| project alias = a` |
| Ordering | `ORDER BY col DESC` | `| sort by col desc` |
| Limit | `LIMIT 100` | `| take 100` |
| Group by | `GROUP BY col` | `| summarize ... by col` |
| Aggregation | `COUNT(*)` | `count()` |
| String contains | `LIKE '%x%'` | `has "x"` or `contains "x"` |
| Time filter | `WHERE ts > '2026-01-01'` | `| where ts > datetime(2026-01-01)` |
| Computed column | `SELECT col + 1 AS new` | `| extend new = col + 1` |

**Rule:** NEVER generate SQL for ADX queries. Always use KQL syntax.

## Best Practices

### Query Generation Rules

1. **Pipe syntax** — KQL is pipe-based: `Table | where ... | summarize ... | project ...`
2. **Table name first** — Query always starts with the table name
3. **Time filter early** — Put time filters (`where Timestamp > ago(1h)`) as early as possible
4. **Use `has` over `contains`** — `has` is term-based (indexed, fast), `contains` is substring (slow)
5. **Limit results** — Always add `| take 1000` unless user needs all data
6. **Use `summarize` for aggregation** — Not `GROUP BY`
7. **Time-series operators** — Use `make-series`, `render timechart` for temporal data
8. **`bin()` for time buckets** — `summarize count() by bin(Timestamp, 1h)`
9. **Dynamic/JSON access** — `| extend val = toreal(Properties.temperature)`

### Schema Discovery Queries

```kql
// List all databases in cluster
.show databases

// List tables in database
.show tables

// Table schema (columns and types)
.show table TableName schema as json

// Table row count estimate
.show table TableName details
| project TableName, TotalRowCount, TotalExtentSize

// All tables with sizes
.show tables details
| project TableName, TotalRowCount,
    SizeMB = TotalExtentSize / 1024 / 1024
| order by TotalRowCount desc

// Functions (stored queries)
.show functions

// Materialized views
.show materialized-views

// Ingestion failures (last 24h)
.show ingestion failures
| where FailedOn > ago(24h)
| summarize count() by Table, ErrorCode
```

### Common Sensor/Telemetry Patterns (mining/industrial context)

```kql
// Latest readings for a tag
FCTSCURRENT
| where TagName == "TAG_001"
| take 1

// Historical time-series (last 24h, 5min buckets)
FCTS
| where Timestamp > ago(24h)
| where TagName == "TAG_001"
| summarize avg(Value) by bin(Timestamp, 5m)
| render timechart

// Multi-tag comparison
FCTS
| where Timestamp > ago(1h)
| where TagName in ("TAG_001", "TAG_002", "TAG_003")
| summarize avg(Value) by bin(Timestamp, 1m), TagName
| render timechart

// Anomaly detection (values outside 3 sigma)
FCTS
| where Timestamp > ago(7d)
| where TagName == "TAG_001"
| summarize avg_val = avg(Value), stdev_val = stdev(Value) by bin(Timestamp, 1h)
| extend upper = avg_val + 3 * stdev_val, lower = avg_val - 3 * stdev_val
| where avg_val > upper or avg_val < lower

// Registry lookup (tag metadata)
Global
| TagRegistry
| where TagName has "temperature"
| project TagName, Description, Site, Unit, EngineeringMin, EngineeringMax

// Site-specific queries (BAG, SAM, MOR, CMX, SIE, NMO, CVE)
// Each site has its own database in the ADX cluster
```

### Time-Series Operators

```kql
// Make-series (fill gaps, regular intervals)
FCTS
| where Timestamp between(ago(7d) .. now())
| where TagName == "TAG_001"
| make-series avg(Value) default=real(null) on Timestamp step 1h

// Moving average
FCTS
| where Timestamp > ago(24h)
| where TagName == "TAG_001"
| sort by Timestamp asc
| extend moving_avg = series_fir(Value, repeat(1, 5), true, true)

// Percentiles
FCTS
| where Timestamp > ago(7d)
| where TagName == "TAG_001"
| summarize percentiles(Value, 5, 50, 95)
```

---

## Multi-Cluster Discovery

### Discover databases in a cluster
```python
from azure.kusto.data import KustoClient, KustoConnectionStringBuilder
from azure.identity import DeviceCodeCredential

credential = DeviceCodeCredential(timeout=900)
kcsb = KustoConnectionStringBuilder.with_azure_token_credential(cluster_uri, credential)
client = KustoClient(kcsb)

# Cluster-level command (requires any database context)
result = client.execute_mgmt("Global", ".show databases")
```

### Discover tables and schema
```kql
-- All tables in a database
.show tables

-- Table schema details
.show table FCTS schema as json

-- All functions
.show functions
```

### Schema snapshot + diff
Export schema metadata periodically for version control:
```python
# Extract metadata as JSON and save to file
result = client.execute_mgmt(database, ".show tables details")
# Save rows as JSON for later comparison
```

---

## Sensor Data Patterns

### Per-site queries (multi-site mining operations)
```kql
SENSOR_READING_SAM_B
| where SITE_CODE == "SAM"
| where VALUE_UTC_TS > ago(1h)
| summarize avg_val = avg(VALUE) by bin(VALUE_UTC_TS, 5m), SENSOR_ID
| order by VALUE_UTC_TS desc
```

### Tag registry lookup
```kql
PI_AF_ATTRIBUTE
| where SITE_CODE == "SAM"
| project SENSOR_ID, TAG_NAME, DESCRIPTION, UNIT
| take 100
```

---

### Safety Guards

- **Never generate** `.drop table` or `.drop database` — require explicit double confirmation
- **Control commands** (start with `.`) vs **queries** (start with table name) — warn user which type
- **Cluster awareness** — Verify correct cluster before executing (prod vs dev)
- **Cost awareness** — Large time ranges on high-ingestion tables are expensive
- **Cross-cluster queries** — `cluster('other').database('db').Table` — warn about performance

### Common Prompt → KQL Mappings

| User says | Generated KQL |
|-----------|--------------|
| "table sizes" | `.show tables details \| project TableName, TotalRowCount, SizeMB` |
| "latest reading" | `FCTSCURRENT \| where TagName == "X" \| take 1` |
| "time series" | `FCTS \| make-series ... on Timestamp step Xm` |
| "anomalies" | `FCTS \| summarize avg/stdev \| extend upper/lower bounds` |
| "tag search" | `TagRegistry \| where TagName has "keyword"` |
| "databases" | `.show databases` |
| "ingestion status" | `.show ingestion failures` |
| "running queries" | `.show running queries` |
| "functions" | `.show functions` |
| "sensor by site" | `SENSOR_READING_{SITE}_B \| where SITE_CODE == ...` |
| "cluster info" | `.show cluster` |

### Error Handling

| Error | Cause | Action |
|-------|-------|--------|
| `Forbidden (403)` | No access to cluster/database | Check Azure AD role assignments |
| `Entity not found` | Wrong table or database name | `.show tables` to verify |
| `Request rate limit exceeded` | Too many concurrent queries | Add delay, reduce frequency |
| `Partial query failure` | Timeout on some extents | Reduce time range, add filters |
| `Semantic error` | KQL syntax mistake | Verify KQL syntax (not SQL!) |
| `Device code timeout` | Auth prompt expired | Re-run, open browser promptly |

---

## Lessons Learned

> Auto-populated when queries fail.

| Date | Error Pattern | Root Cause | Fix |
|------|--------------|-----------|-----|
<!-- New lessons appended here -->
