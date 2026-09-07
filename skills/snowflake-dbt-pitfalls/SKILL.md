---
name: snowflake-dbt-pitfalls
description: "Snowflake and dbt traps that fail silently or destroy data: CREATE OR REPLACE, Dynamic Tables, PIVOT, sources.yml freshness, versioned models. Each one with its prevention."
---

# Snowflake and dbt pitfalls (silent / destructive)

Five non-obvious footguns distilled from real engineering sessions. Each is something the docs underplay and that a future task can trigger on. Generic only.

## 1. `CREATE OR REPLACE TABLE` resets the new object's Time Travel lineage
`CREATE OR REPLACE TABLE` drops the old table and creates a **new object with fresh lineage**. What this breaks:
- The new object's Time Travel window starts at creation. `SELECT ... AT/BEFORE` on the new table cannot reach the OLD table's history. Anything keyed to the old lineage (streams, downstream Time Travel queries) is severed.
- The old data is NOT gone, though: the dropped version is retained in Time Travel for its retention window and is recoverable with `UNDROP TABLE`. The catch is `UNDROP` restores to the original name, so if the new same-named table already exists you must rename it out of the way first, then `UNDROP`, then reconcile.

So the real risk is silent lineage loss and a clumsy recovery, not permanent data loss. Engineers misread it because `CREATE OR REPLACE` is idiomatic for views/procs/stages. **Prevention: CLONE first** for a clean, immediately queryable backup with intact history:
```sql
CREATE OR REPLACE TABLE my_table_backup CLONE my_table;
CREATE OR REPLACE TABLE my_table AS SELECT ...;
```

## 2. Snowflake Dynamic Table (DT) constraints
- **`CURRENT_TIMESTAMP` is allowed in filters but not in the SELECT list under incremental refresh.** Since the GA in May 2025, `CURRENT_TIMESTAMP`/`CURRENT_DATE`/`CURRENT_TIME` work in `WHERE`/`HAVING`/`QUALIFY` (the immutable-window pattern, e.g. `WHERE event_time < CURRENT_TIMESTAMP()`). Putting `CURRENT_TIMESTAMP()` in the SELECT list forces FULL refresh; use `METADATA$ROW_LAST_COMMIT_TIME` instead when you need a per-row refresh timestamp. Still restricted for incremental: session-context functions (`CURRENT_USER`/`CURRENT_ROLE`/`CURRENT_WAREHOUSE`) and sequences.
- **Account limit is 50,000 DTs** (as of 2025; verify in your account limits, it has moved over releases). Not a small number, but design DT-heavy pipelines with it in mind.
- If a table is **fully reloaded every cycle** anyway, a scheduled-Task `TRUNCATE + INSERT` can be cheaper and simpler than a DT. The DT change-tracking overhead buys little when there is no incremental benefit.

## 3. Snowflake `PIVOT` with dotted column values (two compounding bugs)
- **`IN(...)` takes quoted string literals that match the source column's VALUES**, and each becomes a generated column header. If a value contains a dot (e.g. `'c2_tag.avg'`), the auto-generated column header is an invalid/dotted identifier that fails downstream when you reference it unquoted in the outer `SELECT`. The fix is NOT to unquote the `IN` list (it must stay quoted), it is to **normalize the dots in the source values first** so the generated headers are clean identifiers.
```sql
WITH normalized AS (
  SELECT REPLACE(tag_id, '.', '_') AS tag_id_clean, value FROM source_table
)
SELECT *
FROM normalized
PIVOT(MAX(value) FOR tag_id_clean IN ('c2_tag_avg', 'c3_tag_sum'));
-- IN values stay quoted literals; headers come back as 'c2_tag_avg' etc.
-- add  AS p (grp, c2_tag_avg, c3_tag_sum)  if you need bare SELECTable identifiers
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
