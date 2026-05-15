---
name: stored-procedure-logic-hardening
description: "Stored Procedure Logic Hardening"
metadata:
  short-description: "Stored Procedure Logic Hardening"
  original-index: 20
---

# Stored Procedure Logic Hardening

## What

Rewriting stored procedure **logic** for safety, determinism, and correctness --
beyond just rebuilding the definition (Skill #06). This includes:
- Validating FK delete ordering to prevent orphans
- Adding explicit error handling with meaningful messages
- Ensuring deterministic behavior (no implicit ordering assumptions)
- Adding audit logging for destructive operations

## Why

Database procedures that do DELETE, UPDATE, or data migration are the most
dangerous code in the system. A procedure without proper error handling can
silently delete wrong records. A procedure without FK-aware delete ordering
can fail mid-execution, leaving partial results.

## How

### FK-aware delete ordering
```sql
-- BAD: delete parent before children -> FK violation
DELETE FROM public."Users" WHERE "UserId" = p_user_id;
DELETE FROM public."UserRoles" WHERE "UserId" = p_user_id;  -- too late!

-- GOOD: delete children first, then parent
DELETE FROM public."UserRoles" WHERE "UserId" = p_user_id;
DELETE FROM public."UserSessions" WHERE "UserId" = p_user_id;
DELETE FROM public."Users" WHERE "UserId" = p_user_id;  -- safe now
```

### Explicit error handling
```sql
-- BAD: silent failure
DELETE FROM public."Users" WHERE "UserId" = p_user_id;

-- GOOD: validate and report
IF NOT EXISTS (SELECT 1 FROM public."Users" WHERE "UserId" = p_user_id) THEN
    RAISE EXCEPTION 'User % not found -- cannot delete', p_user_id;
END IF;

DELETE FROM public."Users" WHERE "UserId" = p_user_id;
GET DIAGNOSTICS v_count = ROW_COUNT;

IF v_count <> 1 THEN
    RAISE EXCEPTION 'Expected to delete 1 user, deleted % -- rolling back', v_count;
END IF;
```

### Deterministic behavior
```sql
-- BAD: implicit ordering, non-deterministic
SELECT * FROM public."Hospitals" WHERE "RegionId" = p_region_id;

-- GOOD: explicit ordering, deterministic
SELECT * FROM public."Hospitals"
WHERE "RegionId" = p_region_id
ORDER BY "HospitalId";
```

### Audit logging
```sql
-- Log destructive operations
INSERT INTO audit."OperationLog" ("Operation", "TableName", "AffectedId", "Timestamp")
VALUES ('HARD_DELETE', 'Users', p_user_id, now());
```

## When to Use

- Any procedure that does DELETE or bulk UPDATE
- Procedures that merge/consolidate records (hospital merge, user merge)
- Procedures called by automated systems (no human to catch errors)
- After audit findings flag unsafe procedure logic

## Where We Used It

- ****: Hardened user hard-delete routine -- added FK delete ordering,
  explicit row-count validation, and audit logging
- ****: Validated and hardened hospital merge procedure -- ensured
  deterministic column selection and FK-safe update ordering

## Related Skills

- **Skill #06** (pg_get_functiondef) -- technique for modifying procedure code
- **Skill #09** (Foreign Key Constraints) -- FK coverage used by delete ordering
- **Skill #25** (Production Bug Fix) -- when hardening reveals a logic bug

## Gotchas

- Adding error handling can change procedure behavior for callers that
  expected silent failures -- coordinate with the app team
- `GET DIAGNOSTICS` must be called immediately after the DML statement
- `RAISE EXCEPTION` inside a procedure rolls back the entire transaction
  (unlike `RAISE NOTICE` which just logs)
- Always test with edge cases: NULL input, non-existent ID, duplicate records

---

*Category: Reliability | Origin: , *
