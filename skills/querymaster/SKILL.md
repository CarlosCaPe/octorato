# QueryMaster — Multi-Engine Database Agent (Master Skill)

> Trigger: user asks to query a database, run SQL, inspect schema, execute KQL,
> or mentions any supported engine by name (postgres, snowflake, sql server, adx, sqlite, databricks).

## Overview

QueryMaster is a master router that receives natural-language prompts, identifies the
target database engine, generates the appropriate query (SQL, KQL, etc.), and optionally
executes it with dry-run safety. Each engine is a child skill with embedded best practices.

## Supported Engines

| Engine | Child Skill | Driver (Python) | Driver (Node.js) |
|--------|------------|-----------------|-------------------|
| PostgreSQL | `querymaster-postgresql` | `psycopg2` / `psycopg` | `pg` (node-postgres) |
| Snowflake | `querymaster-snowflake` | `snowflake-connector-python` | N/A |
| SQL Server / Azure | `querymaster-sqlserver` | `pyodbc` | `tedious` / `mssql` |
| Azure Data Explorer | `querymaster-adx` | `azure-kusto-data` | N/A |
| SQLite | `querymaster-sqlite` | `sqlite3` (stdlib) | `better-sqlite3` |
| Databricks | `querymaster-databricks` | `databricks-sql-connector` | N/A |

## Architecture

```
User Prompt
    │
    ▼
┌──────────────┐
│  QueryMaster │  ← this skill (router)
│   (master)   │
└──────┬───────┘
       │ detects engine from:
       │  1. explicit --engine flag
       │  2. connection name in connections.json
       │  3. context clues in prompt (KQL syntax, Snowflake functions, etc.)
       │
       ▼
┌──────────────────────┐
│  Engine Child Skill   │  ← querymaster-{engine}
│  (best practices +    │
│   query generation)   │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│  CLI Executor         │  ← ~/.local/bin/querymaster/
│  (connect, execute,   │
│   format, log)        │
└──────────────────────┘
```

## CLI Usage

```bash
# Basic: prompt + engine + connection name
querymaster --engine postgres --conn prod_client "tablas con más de 1M filas"

# Dry-run (DEFAULT): generates query, shows it, asks for confirmation
querymaster --engine snowflake --conn snowflake_client "schemas disponibles"

# Execute immediately (skip confirmation)
querymaster --engine sqlite --conn local_db "count trials" --execute

# Read-only mode (restricts to SELECT/SHOW/DESCRIBE/EXPLAIN)
querymaster --engine sqlserver --conn sql_azure_dev "list tables" --readonly

# JSON output for piping
querymaster --engine postgres --conn prod_client "table sizes" --json --execute

# History
querymaster --history                    # list past queries
querymaster --replay <id>               # re-execute a past query
querymaster --history --compress         # force compression of old results
```

## Connection Configuration

### connections.json (~/.config/querymaster/connections.json)

Central registry of connection profiles. **Never contains passwords** — only references
to environment variables. Each project's `.env` holds the actual secrets.

```json
{
  "prod_client": {
    "engine": "postgresql",
    "env_prefix": "DB",
    "env_file": "~/path/to/client-a/.env",
    "defaults": { "port": 5432, "sslmode": "require" }
  },
  "snowflake_client": {
    "engine": "snowflake",
    "auth": "browser_sso",
    "env_file": "~/path/to/client-b/.env",
    "env_prefix": "CONN_LIB_SNOWFLAKE"
  }
}
```

### .env per project (secrets)

```bash
# client-a/.env
DB_HOST=my-server.postgres.database.azure.com
DB_PORT=5432
DB_USER=admin
DB_PASSWORD=secret
DB_NAME=mydb
```

## Execution Flow

1. **Parse** — CLI parses `--engine`, `--conn`, prompt, flags
2. **Load connection** — Read `connections.json` → load `.env` from referenced project
3. **Route** — Master identifies engine → loads child skill context
4. **Generate** — Child skill generates engine-specific query from natural language prompt
5. **Dry-run** (default) — Display generated query → ask `[Execute? y/N]`
6. **Execute** — Connect using loaded credentials → run query
7. **Format** — Display results as rich table (default) or JSON (`--json`)
8. **Log** — Save to `~/.local/share/querymaster/history/YYYY-MM-DD_conn_NNN.json`

## Security Rules (MANDATORY)

These rules are **non-negotiable** and apply to all engines:

1. **Dry-run by default** — Never execute without confirmation unless `--execute` flag
2. **Never log secrets** — Passwords, tokens, API keys never appear in history or output
3. **Read-only mode** — `--readonly` restricts to: SELECT, SHOW, DESCRIBE, EXPLAIN, .show (KQL)
4. **Destructive guard** — DROP, TRUNCATE, DELETE (without WHERE), ALTER DROP require double confirmation:
   ```
   ⚠️  DESTRUCTIVE OPERATION DETECTED
   Query: DROP TABLE users;
   Type 'YES' to confirm (not just 'y'):
   ```
5. **connections.json has no passwords** — Only env var references and non-sensitive defaults
6. **Timeout** — All queries have a default 30s timeout (configurable via `--timeout`)
7. **Row limit** — Default 1000 rows returned (configurable via `--limit`)

## History & Compression Strategy

| Age | Format | Location |
|-----|--------|----------|
| < 30 days | JSON (plain) | `~/.local/share/querymaster/history/` |
| 30–90 days | `.json.gz` (compressed) | same directory |
| > 90 days | deleted | — |

- `history_index.json` — metadata index: timestamp, engine, conn, query, rows, duration, file
- Compression runs automatically on `querymaster --history` or via `querymaster --history --compress`
- Each history entry includes: query text, row count, column names, execution time, engine, connection — but **never credentials**

## When the AI agent is asked to query a database

1. Read this skill first
2. Identify the engine from the user's request
3. Read the corresponding child skill (`querymaster-{engine}`)
4. **4D Paradigm**: Describe what query you'll run and against which connection
5. Use the child skill's best practices to generate the query
6. **Delegate**: For complex queries, verify schema first (check columns exist before referencing)
7. Present the query to the user for confirmation (dry-run)
8. If confirmed, execute via the CLI: `querymaster --engine {engine} --conn {conn} "{prompt}" --execute`
9. **Diligent**: Validate results — check row count, flag unexpected nulls or zero rows
10. **Disclose**: State implications of any destructive operations before executing
11. Format and present results

## Self-Improvement Protocol

After EVERY failed query:
1. Error is logged to history with `error_type` and `error_message` fields
2. Agent checks if similar error exists in engine skill's `## Lessons Learned` section
3. If new error pattern → append to Lessons Learned: date, error pattern, root cause, fix
4. If recurring → flag for human review

### Reviewing errors
```bash
querymaster --review-errors    # Show recent failures grouped by error type
```

### History Schema v2 (error-aware)
```json
{
  "id": 5,
  "timestamp": "2026-03-18T10:30:00",
  "engine": "sqlite",
  "conn_name": "local_hpo",
  "query": "SELECT direction FROM studies",
  "success": false,
  "error_type": "OperationalError",
  "error_message": "no such column: direction",
  "row_count": 0,
  "duration_ms": 0
}
```

## Engine Detection Heuristics

When no `--engine` is specified, detect from context:
- **PostgreSQL**: mentions "postgres", "pg_stat", "psql", "client-a", "client name"
- **Snowflake**: mentions "snowflake", "warehouse", "VARIANT", "client-b", "client name"
- **SQL Server**: mentions "sql server", "azure sql", "mssql", "MERGE", "T-SQL"
- **ADX/KQL**: mentions "kusto", "adx", "kql", "sensor data", "time-series", "FCTS"
- **SQLite**: mentions "sqlite", "local db", "optuna", "sweep"
- **Databricks**: mentions "databricks", "delta lake", "unity catalog", "spark sql"
