---
name: tsql-to-plpgsql-conversion
description: "AI-Assisted T-SQL to PL/pgSQL Stored Procedure Conversion"
metadata:
  short-description: "Convert T-SQL stored procedures to PL/pgSQL with AI assistance"
  original-index: 39
---

# T-SQL → PL/pgSQL Stored Procedure Conversion

## What

A systematic, AI-accelerated approach to converting Microsoft T-SQL stored procedures
to PostgreSQL PL/pgSQL. Covers syntax translation, semantic validation, and regression
test generation.

## Why

Manual SP conversion takes 4–8 hours per procedure. AI-assisted conversion reduces this
to ~1–2 hours average (human review included) — a ~75% reduction. For 1,727 SPs, this
is the difference between $690K–$1.4M and $173K–$345K.

## Conversion Rules — T-SQL → PL/pgSQL

### Phase 1: Mechanical Syntax Translation (AI handles 100%)

```
T-SQL                              PL/pgSQL
──────────────────────────────────  ──────────────────────────────────
DECLARE @var INT = 5               DECLARE var INT := 5;
SET @var = 10                      var := 10;
SELECT TOP(@n) ...                 SELECT ... LIMIT n
ISNULL(a, b)                       COALESCE(a, b)
GETDATE()                          NOW()
DATEADD(day, 5, @d)                d + INTERVAL '5 days'
DATEDIFF(day, @a, @b)              EXTRACT(DAY FROM (b - a))
'a' + 'b'                          'a' || 'b'
BEGIN TRY...END TRY                BEGIN...EXCEPTION WHEN...THEN...END
BEGIN CATCH...END CATCH            (inside EXCEPTION block)
ERROR_MESSAGE()                    SQLERRM
@@ROWCOUNT                         GET DIAGNOSTICS v_cnt = ROW_COUNT
@@IDENTITY / SCOPE_IDENTITY()      RETURNING id INTO v_id
IDENTITY(1,1)                      GENERATED ALWAYS AS IDENTITY
#temp_table                        CREATE TEMP TABLE temp_table(...)
@table_variable TABLE(...)         CREATE TEMP TABLE (session-scoped)
PRINT @msg                         RAISE NOTICE '%', msg;
RAISERROR(msg, 16, 1)              RAISE EXCEPTION '%', msg;
NOLOCK hint                        (remove — MVCC handles this)
WITH (ROWLOCK)                     (remove — PG row-level locking default)
EXEC sp_name @p1, @p2              CALL sp_name(p1, p2);
INSERT INTO @t EXEC sp             (use temp table + CALL, or refactor to function)
OUTPUT inserted.*                  RETURNING *
MERGE...WHEN MATCHED               INSERT...ON CONFLICT DO UPDATE
CROSS APPLY fn(...)                LATERAL JOIN fn(...)
OPTION (MAXDOP n)                  SET max_parallel_workers_per_gather = n
```

### Phase 2: JSON Operations (AI handles ~90%, human validates edge cases)

```
T-SQL                              PL/pgSQL
──────────────────────────────────  ──────────────────────────────────
OPENJSON(@json)                    jsonb_array_elements(@json::jsonb)
OPENJSON(@json) WITH (...)         jsonb_to_recordset(@json::jsonb) AS t(...)
FOR JSON PATH                      json_agg(json_build_object(...))
FOR JSON AUTO                      row_to_json(t) aggregated
JSON_VALUE(doc, '$.key')           doc->>'key'
JSON_QUERY(doc, '$.obj')           doc->'obj'
ISJSON(@val)                       (validate with jsonb cast in TRY block)
JSON_MODIFY(doc, '$.key', val)     jsonb_set(doc, '{key}', to_jsonb(val))
```

### Phase 3: Architecture Changes (AI proposes, human decides)

| Pattern | T-SQL | PL/pgSQL Alternative | Decision Needed |
|---------|-------|---------------------|-----------------|
| Cross-DB query | `db.schema.table` | `postgres_fdw` or consolidate | Architecture |
| Table variables | `DECLARE @t TABLE(...)` | `CREATE TEMP TABLE` or CTE | Performance |
| CDC columns | `__$start_lsn` | Logical replication / pgoutput | Infrastructure |
| sp_replcmds | Replication reader | `pg_logical` | Infrastructure |
| SQL Agent jobs | `sp_start_job` | `pg_cron` or Azure Automation | Operations |
| Extended Events | `dm_xe_sessions` | `pg_stat_statements` | Monitoring |

## SP Complexity Classification

| Tier | Lines | T-SQL Features | Human-Only Estimate | AI-Assisted Estimate | AI Confidence |
|------|-------|----------------|--------------------|--------------------|---------------|
| **Simple** | < 50 | Basic CRUD, ISNULL, GETDATE | 2–4 hrs | **15–30 min** | 95%+ |
| **Medium** | 50–200 | JSON ops, temp tables, cursors | 4–6 hrs | **1–2 hrs** | 85–90% |
| **Complex** | 200–500 | MERGE, CROSS APPLY, cross-DB | 6–8 hrs | **2–4 hrs** | 70–80% |
| **Critical** | 500+ | Multi-pattern, business logic | 8–16 hrs | **4–8 hrs** | 50–60% |

## MVH SP Distribution (Estimated from Query Metrics)

Based on Section 2.7.2 (445 active SPs observed in 1 hour):

| Tier | % of 1,727 SPs | Count | Human Hours | AI Hours | AI Cost Savings |
|------|----------------|-------|-------------|----------|-----------------|
| Simple | ~50% | 864 | 2,592 | 432 | 2,160 hrs saved |
| Medium | ~30% | 518 | 2,590 | 777 | 1,813 hrs saved |
| Complex | ~15% | 259 | 1,813 | 777 | 1,036 hrs saved |
| Critical | ~5% | 86 | 1,032 | 516 | 516 hrs saved |
| **Total** | **100%** | **1,727** | **8,027** | **2,502** | **5,525 hrs** |

## Workflow: AI-Assisted SP Conversion

```
┌─────────────────────────────────────────────────────┐
│ STEP 1: EXTRACT (automated)                         │
│ pg_get_functiondef() or read .sql from repo          │
│ Parse: params, return type, body, dependencies       │
└────────────────────┬────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────┐
│ STEP 2: CLASSIFY (AI — Claude Sonnet)               │
│ Tier: Simple | Medium | Complex | Critical          │
│ Features: JSON? MERGE? Cross-DB? Cursors?            │
│ Dependencies: other SPs called, tables referenced    │
└────────────────────┬────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────┐
│ STEP 3: CONVERT (AI — Claude Sonnet)                │
│ Apply mechanical rules (Phase 1)                     │
│ Convert JSON operations (Phase 2)                    │
│ Flag architecture decisions (Phase 3)                │
│ Output: .sql file + conversion_notes.md              │
└────────────────────┬────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────┐
│ STEP 4: VALIDATE (AI + Human)                       │
│ AI: syntax check (dry-run parse)                     │
│ AI: generate regression test (input→output pairs)    │
│ Human: review business logic preservation            │
│ Human: approve architecture decisions                │
└────────────────────┬────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────┐
│ STEP 5: TEST (automated + human)                    │
│ Run regression test against PG                       │
│ Compare output with T-SQL original                   │
│ Performance benchmark (EXPLAIN ANALYZE)              │
└─────────────────────────────────────────────────────┘
```

## AI Model Selection (March 2026)

| Model | Best For | Speed | Cost/SP | Accuracy |
|-------|----------|-------|---------|----------|
| **Claude Sonnet 4** | Batch conversion (Simple/Medium) | Fast | ~$0.10–$0.50 | 85–95% |
| **Claude Opus 4** | Complex/Critical SPs, architecture | Slower | ~$0.50–$2.00 | 90–98% |
| Strategy | Sonnet for 80% volume, Opus for 20% complex | | ~$0.20 avg | |

**Token economics for 1,727 SPs:**
- Average SP: ~200 lines → ~4K input tokens + ~4K output tokens
- Sonnet: ~$0.024/K input, ~$0.08/K output → ~$0.42/SP
- 1,727 × $0.42 = **~$725 total AI cost** (negligible vs human cost)

## Caveats & Risks

1. **AI output MUST be human-reviewed** — AI can introduce subtle semantic bugs
   (e.g., different NULL handling between T-SQL and PL/pgSQL COALESCE chains)
2. **Models evolve rapidly** — these estimates are based on March 2026 capabilities;
   by the time migration executes (2027+), models will likely be more capable
3. **The 75% time reduction is on CONVERSION, not on TESTING** — regression testing
   time remains largely unchanged regardless of AI assistance
4. **Context window limits** — very large SPs (1000+ lines) may need to be split
   for processing; Claude handles ~200K tokens but quality degrades beyond ~50K
5. **Batch parallelism is SP-level, not model-level** — you run one agent per SP,
   not 100 agents simultaneously (API rate limits, cost control, review bottleneck)

## When to Use

- Planning or executing a T-SQL → PL/pgSQL stored procedure migration
- Estimating AI-accelerated migration costs for business cases
- Batch-converting SP files from a source code repository
