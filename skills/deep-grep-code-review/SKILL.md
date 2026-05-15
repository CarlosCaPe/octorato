---
name: deep-grep-code-review
description: "Deep Grep Code Review"
metadata:
  short-description: "Deep Grep Code Review"
  original-index: 08
---

# Deep Grep Code Review

> **Scope**: This skill is the **verification** step — used DURING code review
> to confirm that Skill #14 (Research Checklist) was done correctly.
> Skill #14 runs BEFORE building SQL; this one runs AFTER.

## What

A code review technique that uses exhaustive text searches across database
DDL snapshots to verify that ALL affected objects have been identified and
fixed. Not a cursory glance -- a systematic, grep-based audit.

## Why

Even with a research checklist (Skill #14), the original author can miss
objects. The deep grep is an independent, mechanical verification by the
**reviewer** (not the author). In DA-102, the initial research found 3
procedures, but the deep grep during code review found a 4th
(`GetNewApplicants`) that was missed.

## How

### Step 1: Search with QUOTED column names
```powershell
# This catches actual SQL column references (the dangerous ones)
grep -r '"VertirnaryTechOrAssistant"' database/postgresql/**/Procedures/
```

### Step 2: Search ALL related object files (not just obvious names)
```powershell
# Don't just search "Applicant" procedures -- search everything
Get-ChildItem -Recurse -Filter "*.sql" database/postgresql/dev/**/Procedures/ |
    Select-String -Pattern '"VertirnaryTechOrAssistant"'
```

### Step 3: Cross-check the count
If your research says "3 procedures" but grep says 4, **investigate the 4th**.
Don't assume the grep is wrong.

### Step 4: Verify negative space
Also search procedures that you expect to be clean:
```powershell
# These Applicant-related procs should NOT have the column refs
# Verify they truly don't
grep -l "VertirnaryTechOrAssistant" UpdateApplicant*.sql GetApplicants*.sql
# Expected: no output
```

## The Checklist

1. List ALL procedures that touch the affected table
2. Search for QUOTED column references (catches actual SQL usage)
3. Search for UNQUOTED references (catches comments, aliases)
4. Verify count matches expectations
5. Cross-check DEV and QA snapshots
6. Document the full procedure list in the script header

## When to Use

- Before finalizing any DDL script that modifies columns or table structure
- During code review of any schema change ticket
- Whenever the original research was done by someone else (or by you last week)

## Where We Used It

- **DA-102 Round 2 code review**: Found `GetNewApplicants` was missed.
  The initial grep used unquoted patterns which truncated results.
  The deep grep with quoted patterns found all 4 affected procedures.

## Lesson Learned

> The grep pattern matters. `grep VertirnaryTechOrAssistant` matches parameter
> names AND column refs. `grep '"VertirnaryTechOrAssistant"'` matches only
> quoted column references in SQL -- the ones that actually break.

---

*Category: Process | Origin: DA-102*
