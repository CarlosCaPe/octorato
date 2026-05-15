---
name: atomic-3phase-ddl-scripts
description: "Atomic 3-Phase DDL Scripts"
metadata:
  short-description: "Atomic 3-Phase DDL Scripts"
  original-index: 01
---

# Atomic 3-Phase DDL Scripts

## What

A script architecture that separates database modifications into three
distinct phases within a single SQL file:

| Phase | Purpose | Behavior on Failure |
|-------|---------|---------------------|
| Phase 1 | Pre-check, gap analysis, dry-run gate | RAISE EXCEPTION stops all |
| Phase 2 | Execute changes (single DO block) | Rolls back atomically |
| Phase 3 | Post-check, verify final state | Reports pass/fail counts |

## Why

Separating concerns makes scripts **auditable**, **safe**, and **debuggable**.
Phase 1 tells you what *will* happen before anything changes. Phase 2 does the
work atomically. Phase 3 proves it worked.

## How

```sql
-- Phase 1: Pre-check
DO $$
BEGIN
    -- gap analysis: what needs doing?
    -- dry-run gate: RAISE EXCEPTION if dry_run = true
END $$;

-- Phase 2: Execute (atomic DO block)
DO $$
BEGIN
    -- all modifications inside ONE block
    -- if any fails, everything rolls back
END $$;

-- Phase 3: Post-check
DO $$
BEGIN
    -- verify every expected outcome
    -- report confirmed/failed counts
END $$;
```

The key insight is that Phase 2 is a **single DO block**. If any statement inside
it fails, PostgreSQL rolls back the entire block -- you never get a half-applied
state.

## When to Use

- Any DDL change that touches multiple objects (columns + procedures)
- Changes that need auditable before/after evidence
- Scripts that will be deployed across environments (DEV, QA, PROD)

## Where We Used It

- ****: 4 column renames + 4 procedure updates in one atomic Phase 2
- **/**: FK constraints + indexes in atomic blocks
- **/**: Index creation with pre/post verification

## Gotchas

- `CREATE INDEX CONCURRENTLY` cannot run inside a transaction block -- it needs
  its own phase outside a DO block
- Each DO block is its own transaction when autocommit is on (default in psql
  and our Node.js runner). If wrapped in explicit BEGIN/COMMIT, multiple DO
  blocks share one transaction -- avoid this for 3-Phase scripts
- `RAISE EXCEPTION` inside a DO block aborts that block's transaction and
  prevents subsequent statements from running (PG 16 docs:
  plpgsql-errors-and-messages.html)

---

*Category: Architecture | Origin: *
