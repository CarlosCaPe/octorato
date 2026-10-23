---
name: schema-as-code-three-layer-sync
description: "Keeps the three layers of a schema-as-code project in sync: ER diagram, data dictionary and the declarative SQL. Defines the chain of truth and the diff flow when they drift."
---

# Schema-as-Code Three-Layer Sync

A schema-as-code project has three layers that document the same thing
from different angles. When they disagree, you have a problem. This
skill is the discipline for keeping them aligned.

## The three layers

| Layer | What it is | Common tools |
|---|---|---|
| **ER** (Entity-Relationship) | Visual canonical model. Drives architectural conversations. | Miro, dbdiagram.io, drawio, Lucidchart, plantUML, ERwin |
| **DD** (Data Dictionary) | Human-readable narrative of each table + column with semantics, history, open questions. Lives where humans read docs. | Confluence, Notion, Markdown wiki, Sphinx, mkdocs |
| **Code** (Schema-as-Code) | What the database actually IS. Source-controlled. | Atlas (declarative), Flyway (versioned), Liquibase, sqitch, Prisma, drizzle-kit, alembic |

## The cardinal rule: define your source-of-truth chain

**Before any sync work, the project must have a written chain.** Without
it, when layers disagree you get circular arguments instead of clean
decisions.

Recommended default chain when no other policy exists:

```
ER  >  DD  >  Code
```

Meaning: when ER and code disagree, ER wins; when DD and code disagree,
DD wins; when ER and DD disagree, ER wins.

Why ER first? It's the visual, architectural model. When a stakeholder
draws on the board during a meeting, that decision should propagate
forward.

Some projects invert this (e.g., code-first projects where ORM
migrations are the source-of-truth). Either is valid; the rule is to
**pick one and write it down**.

When a project's chain is unwritten, surface this as the first decision
to settle before starting any sync work.

## The sync workflow when layers diverge

```
1. Detect drift          which layer changed and which lagged
2. Confirm direction     does the change propagate forward in the chain
3. Author the gap        draft the changes to the lagging layer(s)
4. Validate locally      run the declarative loop (see below)
5. Push + open PR        with a clear delta description
6. Wait for review       reviewers see the intent, not just the diff
7. Merge                 with confidence the chain is consistent again
```

The **Confirm direction** step matters most. If the ER author updated the
ER to match a misunderstanding, propagating that to DD + code amplifies
the mistake. Always check that the upstream change reflects real intent
before propagating.

## Local-first validation loop (declarative migration tools)

When the code layer uses a declarative tool (Atlas, Liquibase
managed-source, etc.), the validation loop is:

```sh
# 1. Spin up a fresh local DB
docker compose up -d postgres                     # or whatever the project uses

# 2. Apply current desired state to the fresh DB
<tool> schema apply --env local --auto-approve     # Atlas
# or
<tool> migrate --schema=...                        # equivalent in other tools

# 3. Confirm idempotency — the second apply must be a no-op
<tool> schema apply --env local --dry-run
# Expected output: "Schema is synced, no changes to be made" or equivalent
```

**If step 3 reports changes, the schema is non-idempotent.** Common
causes:
- DML (INSERT/UPDATE) in source files that the tool re-runs every time
- Generated DEFAULTs that produce different values per apply
- Functions, views, or triggers with subtle non-deterministic body

Non-idempotency is a bug. Fix before pushing.

## Greenfield vs production: the destructive-change decision tree

When the code change requires a type that can't be auto-cast (Postgres
42804: `cannot be cast automatically`), you have three options:

```
                         Does production carry data?
                         ┌──────────┴───────────┐
                        NO                     YES
                         │                      │
                  GREENFIELD path         PRODUCTION path
                         │                      │
                         ▼                      ▼
         Drop+recreate on fresh DB.    Versioned migration with
         Declarative tool computes      explicit backfill / cutover.
         the DROP TABLE + CREATE        Multi-phase deploy.
         TABLE in one apply.            Possibly: dual-write window.
                         │                      │
                         ▼                      ▼
                   Time: ~minutes          Time: days to weeks
```

### NEVER take the third option

**Never** add a one-off pre-apply hack to the pipeline yaml (a `docker
run psql ... DROP CONSTRAINT ... DROP COLUMN ...` block, or equivalent).
These hacks:
- Carry forward forever as tech debt
- Reviewers identify them as "AI did this"
- Surprise the next person who edits the pipeline
- Cannot be reproduced in local development
- Bypass the declarative model the project committed to

If you find yourself drafting one, either the project is greenfield
(use option 1) or it's production (use option 2). The pipeline-hack
option is always wrong.

## "No AI artifacts" — the canonical rule for schema work

When generating SQL for a schema-as-code project, **omit all AI
fingerprints**. Reviewers should not be able to tell whether the SQL
was hand-written or generated. Specifically:

| Avoid | Why |
|---|---|
| `-- Generated by tool.py` headers | Marks the file as machine-output |
| `-- Advisory cross-schema FKs (NOT enforced):` blocks | Not the project's convention |
| `-- DD did not specify a PK; added surrogate` | Reveals indecision |
| `-- TODO`, `-- HACK`, `-- FIXME` | Decision punted, code committed |
| `-- Generated YYYY-MM-DD` | Timestamps decay; version control is authoritative |
| `15_` prefixes when the repo uses `10_/20_/30_` | New numbering layer introduced unnecessarily |
| Renamed files like `*_v2.sql`, `*_old.sql` | Git history is the version history |
| Stub files (`-- TODO: implement`) | Empty placeholder is worse than missing |

The replacement pattern: **match the repo's existing style exactly**.
Look at the most recent commit in the schema directory and mimic
indentation, keyword case, alignment, comment density, naming
conventions. If the human author writes 2-space indent without
comments, do the same — even if 4-space with comments is more
"correct" academically.

## Cross-source-of-truth diff workflow

When you suspect drift but aren't sure where it lives, generate the
diff in this order:

```
1. Re-export the ER (fresh capture from the diagram tool)
2. Parse it into structured tables/columns
3. Read the current DD storage from the wiki API (fresh, not local cache)
4. Read the current code from the repo at the current default branch HEAD
5. Build three pairwise diffs:
   - ER vs DD
   - DD vs Code
   - ER vs Code
6. Confirm consistency: if all three diffs are non-empty, expect the
   transitive (ER vs Code should approximately equal ER vs DD plus
   DD vs Code).
```

The transitive consistency check catches parsing bugs. If it fails,
re-examine the parser before drafting changes.

## When to use this skill

- The project has explicit ER, DD, and code layers (or the discussion
  references them by other names).
- A stakeholder requests "sync the schema" or "align with the diagram"
  or "update the data dictionary."
- A schema PR has been red on CI for type-cast reasons (42804 or similar
  in Postgres; analogous errors in other engines).
- A new layer drift is discovered (e.g., during a code review).

## When NOT to use this skill

- The project is code-first with no separate ER or DD — there's nothing
  to align.
- The schema change is a single column add with no type-cast risk —
  just write the migration directly.
- The disagreement is semantic (what the column MEANS) rather than
  structural (whether the column exists) — that's a stakeholder
  conversation, not a sync exercise.

## Anti-patterns

- ❌ Editing the DD to match a code mistake (corrupts the source-of-truth
  chain backwards).
- ❌ Splitting a sync into multiple PRs along arbitrary lines (ownership,
  scope, etc.) when one atomic PR would convey "the layers are now
  aligned" more clearly. Split only when ownership genuinely differs.
- ❌ Applying the ER blindly when it disagrees with stakeholder intent —
  always confirm the ER update was intentional.
- ❌ Validating only on CI, not locally — local docker apply catches 90%
  of issues in minutes instead of CI-cycle-time.
- ❌ Carrying pre-apply pipeline hacks "temporarily" — they become
  permanent.

## Related skills

- `idempotent-sql-design` — what makes a `.sql` file safe to re-run
- `atomic-3phase-ddl-scripts` — when destructive changes need staging
- `backward-compatible-schema-changes` — production-path pattern
- `investigate-before-asking` — applied to sync work: read the layers
  before asking which won
- `do-not-ask-to-pause` — keep moving through the workflow once
  direction is clear
- `4d-paradigm-protocol` — Change Manifest format applies to schema PRs

## Lessons learned (real incidents)

- A pre-apply docker hack added to a pipeline template "to unblock CI"
  carried forward through two PRs before being explicitly removed. Cost:
  one extra cleanup PR and several rounds of "what is this?" review
  comments.
- A schema sync where ER said one direction and a recent code commit
  said the opposite — without explicit source-of-truth chain, the
  reviewer arguments cycled for hours. The fix was retroactively
  declaring "ER > DD > Code" and applying it.
- A 25-table schema generated by a script left visible artifacts:
  `-- Generated by gen-cases.py` headers, `_old.sql` rename suggestions,
  `-- TODO: implement` stubs. Reviewer reaction: "this was done with
  AI." The remediation was to regenerate without artifacts, matching
  the repo's existing hand-written style.
