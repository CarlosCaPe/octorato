---
name: backward-compatible-schema-changes
description: "Backward-Compatible Schema Changes"
metadata:
  short-description: "Backward-Compatible Schema Changes"
  original-index: 07
---

# Backward-Compatible Schema Changes

## What

Making database schema changes that don't break existing application code.
The application continues working without any code changes, even though the
database structure has been modified.

## Why

In production systems, you can't deploy database changes and application
changes at the exact same millisecond. There's always a window where the
old app code runs against the new schema (or vice versa). Backward-compatible
changes eliminate this risk.

## How

### Column renames with preserved parameter names

```sql
-- The procedure parameter keeps the OLD name
CREATE OR REPLACE PROCEDURE public."AddApplicant"(
    ...
    "p_vertirnarytechorassistant" boolean,  -- old spelling preserved
    ...
)
AS $$
BEGIN
    INSERT INTO public."Applicant" (
        ...
        "the clientTechOrAssistant",  -- new spelling in column ref
        ...
    ) VALUES (
        ...
        p_vertirnarytechorassistant,  -- old spelling in param ref (no quotes)
        ...
    );
END;
$$ LANGUAGE plpgsql;
```

The application calls:
```sql
CALL public."AddApplicant"(
    p_vertirnarytechorassistant => true  -- still works!
);
```

### The principle

| Layer | What Changed | What Stayed |
|-------|-------------|-------------|
| Table column name | `"VertirnaryTechOrAssistant"` -> `"the clientTechOrAssistant"` | Data, type, constraints |
| Procedure body | Quoted column refs updated | Everything else |
| Procedure signature | Nothing | Parameter names, types, order |
| Application code | Nothing | Call syntax, parameter binding |

## When to Use

- Any schema change on a system with active callers
- When you can't coordinate simultaneous DB + app deployments
- As a two-phase approach: rename columns now, rename parameters later

## Where We Used It

- ****: Renamed 4 columns and updated procedure bodies while preserving
  all `p_` parameter names. Application code continues working unchanged.
  Parameter name cleanup deferred to a future ticket after app coordination.

## Gotchas

- Document the "debt" -- old parameter names should eventually be cleaned up
- Test with the actual application, not just SQL queries
- Named parameter binding (`p_name => value`) is sensitive to parameter names;
  positional binding is not

---

*Category: Strategy | Origin: *
