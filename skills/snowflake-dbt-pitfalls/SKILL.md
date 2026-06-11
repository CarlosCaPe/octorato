---
name: snowflake-dbt-pitfalls
description: Non-obvious Snowflake and dbt footguns that fail silently or destroy data. Load when writing or reviewing Snowflake DDL (CREATE OR REPLACE, Dynamic Tables, PIVOT) or dbt config (sources.yml freshness, versioned models). Each pitfall has a concrete prevention. Triggers - "CREATE OR REPLACE TABLE", Snowflake Time Travel / UNDROP, Dynamic Table refresh errors, PIVOT returning literals/nulls, dbt source freshness passing when it should not, dbt versioned-model YAML parse error that survives typo fixes.
---

# Snowflake and dbt pitfalls (silent / destructive)

Five non-obvious footguns distilled from real engineering sessions. Each is something the docs underplay and that a future task can trigger on. Generic only.

## 1. `CREATE OR REPLACE TABLE` permanently destroys Time Travel (the worst one)
`CREATE OR REPLACE TABLE` drops and recreates the object in one atomic step that **bypasses the recycle bin**:
- `UNDROP` does NOT recover it (UNDROP only works after an explicit `DROP`).
- Time Travel coverage restarts from zero at recreation; old snapshots are gone.
- The old data is permanently, irrecoverably lost. No workaround after the fact.

It is dangerous precisely because `CREATE OR REPLACE` is idiomatic for views/procs/stages, so engineers assume "replace" is recoverable. **Prevention: CLONE first.**
```sql
CREATE OR REPLACE TABLE my_table_backup CLONE my_table;
CREATE OR REPLACE TABLE my_table AS SELECT ...;
```

## 2. Snowflake Dynamic Table (DT) constraints
- **`CURRENT_TIMESTAMP()` (and other non-deterministic functions) are forbidden inside a DT query.** DTs use deterministic change-tracking for incremental refresh; non-determinism breaks it (create fails or results are wrong). Use `METADATA$ACTION_TIMESTAMP`, or pass the timestamp as a parameter via a Task.
- **Default hard limit of 250 DTs per account** (raisable by support). Easy to hit when DTs are treated as cheap views.
- If a table is **fully reloaded every cycle** anyway, a scheduled-Task `TRUNCATE + INSERT` is cheaper and simpler than a DT. The DT change-tracking overhead buys nothing when there is no incremental benefit.

## 3. Snowflake `PIVOT` with dotted column values (two compounding bugs)
- **Single-quoted values in `IN(...)` are string literals, not column refs.** `PIVOT(MAX(value) FOR tag IN ('c2.avg'))` makes the header AND cell the literal string, not aggregated data. Use **unquoted identifiers** in both `IN(...)` and the outer `SELECT`.
- **Dots in identifiers** like `c2_tag.avg` parse as a two-part identifier `c2_tag.avg` and fail compilation. Normalize dots first.
```sql
WITH normalized AS (
  SELECT REPLACE(tag_id, '.', '_') AS tag_id_clean, value FROM source_table
)
SELECT c2_tag_avg, c3_tag_sum
FROM normalized
PIVOT(MAX(value) FOR tag_id_clean IN (c2_tag_avg, c3_tag_sum));
```
Symptom that points here: PIVOT returns the column-name strings or nulls instead of values.

## 4. dbt `sources.yml` freshness has two underused keys
- **`filter:`** accepts a WHERE expression evaluated before the freshness check. Without it, freshness checks `max(loaded_at)` across ALL rows including stale/rejected ones. Scope it, e.g. `filter: "status = 'LOADED'"`, so freshness reflects meaningful rows.
- **`identifier:`** maps the logical source name to a different physical table name. Without it dbt assumes node name = table name; after a rename the freshness check silently hits the wrong table or errors. The fix is one `identifier:` key, not a schema change.
Symptom: a freshness check passing when it should fail (or vice versa).

## 5. dbt versioned-model `include/exclude` placement
In versioned models (`versions:` in `schema.yml`), an `include: all` / `exclude: [col]` block nested **inside** the `columns:` list is structurally invalid and throws a YAML parse error that survives typo fixes (the error is structural, not textual). It belongs at the **version level**, a sibling of `defined_in:`/`config:`:
```yaml
versions:
  - v: 1
    include: all
    exclude: [deprecated_col]
    # NOT under columns:
```
Symptom: a dbt YAML parse error pointing at the wrong line that persists after every typo fix.

## Provenance
Distilled from real Snowflake/dbt debugging sessions, stripped of any project data. Complements `querymaster-snowflake` (query authoring) and the DDL-safety skills; this one is specifically the silent/destructive gotcha set.
