---
name: research-checklist-discipline
description: "Research Checklist Discipline"
metadata:
  short-description: "Research Checklist Discipline"
  original-index: 14
---

# Research Checklist Discipline

> **Scope**: This skill is the **pre-build** step — run BEFORE writing SQL.
> Skill #08 (Deep Grep Code Review) is the verification step run DURING
> code review to confirm this checklist was done correctly.

## What

A mandatory pre-build verification process that ensures ALL affected database
objects have been identified before writing a single line of SQL.

## Why

Assumptions and ticket descriptions are unreliable. The only trustworthy source
is the database itself (via DDL snapshots and catalog queries). This checklist
forces the author to mechanically verify scope before building, not after.
When this step was skipped in DA-102, a 4th procedure (`GetNewApplicants`) was
missed and only caught later during code review (Skill #08).

## How

### Before building any DDL script:

**1. List ALL related procedures** -- not just the ones with obvious names:
```powershell
Get-ChildItem -Recurse -Filter "*.sql" -Path database/postgresql/**/Procedures/ |
    Select-String -Pattern 'Applicant' |
    Select-Object -Property Filename -Unique
```

**2. Search with QUOTED column names** -- catches actual SQL references:
```powershell
Get-ChildItem -Recurse -Filter "*.sql" -Path database/postgresql/**/Procedures/ |
    Select-String -Pattern '"VertirnaryTechOrAssistant"'
```

**3. Count and verify** -- if you expect N procedures, verify you found N:
```
Expected: 3 procedures (from Jira)
Found:    4 procedures (from grep)
Action:   Investigate the extra one!
```

**4. Cross-check environments** -- DEV and QA should have the same procedures:
```powershell
# List procedure files in both environments
$dev = Get-ChildItem database/postgresql/dev/**/Procedures/*.sql | Select-Object Name
$qa  = Get-ChildItem database/postgresql/qa/**/Procedures/*.sql | Select-Object Name
Compare-Object $dev $qa -Property Name
```

**5. Document the full list** in the script header:
```sql
/*
 * Affected procedures:
 *   - AddApplicant       (INSERT column list)
 *   - GetApplicant       (SELECT lists, 4 branches)
 *   - GetAllApplicants   (SELECT via CTE)
 *   - GetNewApplicants   (SELECT via CTE)   <-- found in deep grep
 */
```

## The Root Cause

| Search Pattern | What It Catches | What It Misses |
|---|---|---|
| `VertirnaryTechOrAssistant` (unquoted) | Everything, including parameter names | May truncate in noisy output |
| `"VertirnaryTechOrAssistant"` (quoted) | Only SQL column references | Nothing -- this is the correct pattern |

## When to Use

- **Every** DDL change that affects columns, tables, or types
- Before every script build, not after
- Even when the Jira ticket specifies the scope -- verify independently

## Where We Used It

- **DA-102**: Added Research Checklist section to README after the
  `GetNewApplicants` miss was caught in Round 2 code review

## Lesson

> Trust grep, not memory. Trust quoted patterns, not unquoted ones.
> Trust your count, not the ticket description.

---

*Category: Process | Origin: DA-102*
