---
name: querymaster-sqlite
description: "Child skill of querymaster for SQLite: local file databases, Optuna storage, analytical sweeps and embedded use, with WAL and foreign_keys PRAGMA. Activates when the resolved engine is SQLite."
---

# QueryMaster — SQLite Engine Skill

> Child skill of `querymaster`. Activated when engine is SQLite.
> Covers: local file-based DBs, Optuna storage, analytical sweeps, embedded use.

## Connection Patterns

### Python (sqlite3 — stdlib)
```python
import sqlite3
conn = sqlite3.connect(
    database=db_path,       # file path or ":memory:"
    timeout=30,
    isolation_level=None,   # autocommit; or "DEFERRED" for transactions
)
conn.row_factory = sqlite3.Row  # dict-like access
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA synchronous=NORMAL")
conn.execute("PRAGMA foreign_keys=ON")
```

### connections.json entry
```json
{
  "local_analytics": {
    "engine": "sqlite",
    "path": "~/path/to/your-arm/analytics/hpo.db",
    "pragmas": ["journal_mode=WAL", "synchronous=NORMAL"]
  },
  "sweep_db": {
    "engine": "sqlite",
    "path": "~/path/to/your-arm/analytics/sweep_results.db"
  }
}
```

## Best Practices

### Query Generation Rules

1. **No schemas** — SQLite has no schema concept (only `main` and `temp`)
2. **Use `sqlite_master`** — System table for schema introspection (not `information_schema`)
3. **PRAGMA for config** — Runtime settings via PRAGMA, not SET
4. **Type affinity** — SQLite is dynamically typed; columns have affinity not strict types
5. **No ALTER DROP COLUMN** — Before 3.35.0; use recreate pattern if needed
6. **UPSERT** — `INSERT ... ON CONFLICT DO UPDATE SET ...` (since 3.24.0)
7. **Window functions** — Supported since 3.25.0
8. **JSON** — `json_extract()`, `json_each()` since 3.38.0
9. **Concurrent reads OK** — WAL mode allows concurrent reads, single writer

### Schema Discovery Queries

```sql
-- List all tables
SELECT name, type FROM sqlite_master
WHERE type IN ('table', 'view')
    AND name NOT LIKE 'sqlite_%'
ORDER BY type, name;

-- Table structure
PRAGMA table_info('table_name');

-- Table with row counts
SELECT
    m.name AS table_name,
    (SELECT COUNT(*) FROM [table_name]) AS row_count
FROM sqlite_master m
WHERE m.type = 'table' AND m.name NOT LIKE 'sqlite_%';

-- Indexes
PRAGMA index_list('table_name');

-- Index columns
PRAGMA index_info('index_name');

-- Database file size
SELECT page_count * page_size AS size_bytes
FROM pragma_page_count(), pragma_page_size();

-- Integrity check
PRAGMA integrity_check;

-- WAL status
PRAGMA journal_mode;
PRAGMA wal_checkpoint(PASSIVE);

-- Foreign key check
PRAGMA foreign_key_check;

-- Table DDL (creation SQL)
SELECT sql FROM sqlite_master WHERE name = 'table_name';
```

### Optuna-Specific Queries (HPO context)

```sql
-- Count total trials
SELECT COUNT(*) AS total_trials FROM trials;

-- Best trials by value
SELECT trial_id, value, datetime(datetime_start, 'localtime') AS started,
    datetime(datetime_complete, 'localtime') AS completed,
    state
FROM trials
WHERE state = 'COMPLETE'
ORDER BY value ASC  -- or DESC depending on direction
LIMIT 20;

-- Trial parameters
SELECT
    t.trial_id, t.value,
    tp.param_name, tp.param_value
FROM trials t
JOIN trial_params tp ON t.trial_id = tp.trial_id
WHERE t.trial_id IN (SELECT trial_id FROM trials ORDER BY value ASC LIMIT 5);

-- Study summary
SELECT
    study_id, study_name, direction
FROM studies;

-- Trial distribution over time
SELECT
    date(datetime_start) AS day,
    COUNT(*) AS trials,
    MIN(value) AS best_value,
    AVG(value) AS avg_value
FROM trials
WHERE state = 'COMPLETE'
GROUP BY date(datetime_start)
ORDER BY day;

-- Study directions (objective direction per study)
-- IMPORTANT: 'direction' column is in study_directions, NOT in studies
SELECT s.study_id, s.study_name, sd.direction, sd.objective
FROM studies s
JOIN study_directions sd ON s.study_id = sd.study_id;

-- Top trials with their parameter values
SELECT t.trial_id, t.value, tp.param_name, tp.param_value
FROM trials t
JOIN trial_params tp ON t.trial_id = tp.trial_id
WHERE t.state = 'COMPLETE'
ORDER BY t.value DESC LIMIT 10;
```

---

## Optuna Table Structure Reference

Optuna's SQLite storage uses these core tables:

| Table | Key Columns | Purpose |
|-------|------------|---------|
| `studies` | `study_id`, `study_name` | Study registry |
| `study_directions` | `study_id`, `direction`, `objective` | Optimization direction (MINIMIZE/MAXIMIZE) |
| `trials` | `trial_id`, `study_id`, `state`, `value`, `datetime_start`, `datetime_complete` | Individual trials |
| `trial_params` | `trial_id`, `param_name`, `param_value`, `distribution_json` | Hyperparameter values |
| `trial_values` | `trial_id`, `objective`, `value` | Multi-objective values |
| `trial_intermediate_values` | `trial_id`, `step`, `intermediate_value` | Pruning checkpoints |
| `trial_user_attributes` | `trial_id`, `key`, `value_json` | Custom metadata |
| `trial_system_attributes` | `trial_id`, `key`, `value_json` | System metadata |

---

## Resumable Sweep Patterns

### Budget sweep with SQLite persistence
```python
# Pattern: persist sweep results so you can stop/resume
import sqlite3, hashlib, json

conn = sqlite3.connect("budget_sweep.db")
conn.execute("PRAGMA journal_mode = WAL")  # enable WAL for concurrent reads

# Create results table with run metadata
conn.execute("""
    CREATE TABLE IF NOT EXISTS sweep_results (
        run_id TEXT, budget REAL, year INT,
        realized_pnl REAL, return_pct REAL,
        PRIMARY KEY (run_id, budget, year)
    )
""")

# Check if already computed (resume support)
existing = conn.execute(
    "SELECT budget FROM sweep_results WHERE run_id = ?", (run_id,)
).fetchall()
```

### WAL mode for concurrent HPO workers
```python
# Enable WAL before multi-process Optuna
conn.execute("PRAGMA journal_mode = WAL")
# This allows multiple readers while one writer (Optuna) inserts trials
```

---

### Safety Guards

- **File existence check** — Verify `.db` file exists before connecting
- **Backup before writes** — `.backup` command or `shutil.copy` before destructive ops
- **WAL cleanup** — `PRAGMA wal_checkpoint(TRUNCATE)` after heavy writes
- **VACUUM** — Suggest after large deletes to reclaim disk space (locks DB)
- **Concurrent writers** — Warn that SQLite supports only ONE writer at a time (WAL allows concurrent reads)

### Common Prompt → SQL Mappings

| User says | Generated SQL |
|-----------|--------------|
| "tables" | `SELECT name FROM sqlite_master WHERE type='table'` |
| "table structure" | `PRAGMA table_info('table')` |
| "db size" | `SELECT page_count * page_size FROM pragma_*` |
| "row counts" | Count per table from sqlite_master |
| "best trials" (Optuna) | `SELECT * FROM trials ORDER BY value LIMIT N` |
| "study directions" | `SELECT s.*, sd.direction FROM studies s JOIN study_directions sd ON s.study_id = sd.study_id` |
| "check integrity" | `PRAGMA integrity_check` |
| "indexes" | `PRAGMA index_list('table')` |
| "trial params" | `trials JOIN trial_params ON trial_id` |

### Error Handling

| Error | Cause | Action |
|-------|-------|--------|
| `database is locked` | Another writer active | Wait + retry, check WAL mode |
| `no such table` | Typo or wrong db file | `SELECT name FROM sqlite_master` |
| `no such column` | Column in different table | Check Optuna table structure above (e.g., `direction` is in `study_directions`) |
| `disk I/O error` | Corrupt file or full disk | `PRAGMA integrity_check`, check disk space |
| `file is not a database` | Wrong file or encrypted | Verify path, check if SQLCipher |
| `attempt to write a readonly database` | File permissions | `chmod` or check mount options |

---

## Lessons Learned

> Auto-populated when queries fail.

| Date | Error Pattern | Root Cause | Fix |
|------|--------------|-----------|-----|
| 2026-03-17 | `no such column: direction` | Column is in `study_directions`, not `studies` | JOIN `study_directions` on `study_id` |
<!-- New lessons appended here -->
