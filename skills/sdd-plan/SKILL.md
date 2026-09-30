---
name: sdd-plan
description: >
  SDD step 3. Read feature.md and produce a detailed implementation plan.md
  tailored to the project's tech stack and architecture.
  Use after /sdd-feature has produced feature.md.
---

# SDD: Implementation Planning

You are acting as a senior software engineer creating a precise, actionable implementation plan.

## Pre-conditions
Verify both files exist before proceeding:
- `feature.md`: the feature spec (if missing, tell the user to run `/sdd-feature` first)
- `docs/project.md`: project context

## Process

### 0. Refuse an Unready Spec
Run the linter in ready mode on the spec directory:

```bash
python3 ~/.claude/scripts/spec_lint.py --ready <spec-directory>
```

If it exits non-zero, stop. Print the findings (open `[NEEDS CLARIFICATION]` markers or a
malformed criterion) and tell the user to run `/sdd-refine`. Do not write `plan.md`.
A `feature.md` without `Spec-Format: ears-1` is skipped by the linter; plan it as before.

### 1. Read Both Files
Read `feature.md` and `docs/project.md` in full.

### 2. Identify the Tech Stack
From `docs/project.md`, note:
- Primary language and framework
- Build tool and compile/test commands
- Database and data access layer
- Messaging systems
- Testing frameworks
- Any architecture patterns (e.g., Hexagonal, DDD, Layered)

### 3. Produce plan.md

Create `plan.md` in the spec directory, next to `feature.md`, with this structure:

```markdown
# Implementation Plan: <Feature Name>

## Overview
Brief description of the implementation approach.

## Architecture Decisions
- Key design choices and their rationale
- Patterns to follow (aligned with docs/project.md)

## Implementation Steps

Group tasks under headings by layer or phase. Every task is one line in this exact grammar:

- [ ] T01 [AC-01] db/migrations/0042_add_table.sql: create the table
- [ ] T02 [AC-02, AC-03] src/service.py, tests/test_service.py: implement and test the use case

## Risks & Mitigations
- Risk: ... → Mitigation: ...

## Estimated Complexity
Low / Medium / High, with a brief justification
```

### 4. Task Grammar Rules
- `T##` ids are unique and sequential. At most **20** tasks; consolidate if you need more.
- The brackets list every criterion the task serves. Every criterion in `feature.md` appears
  in at least one task, and no task names a criterion that does not exist.
- Paths are separated by a comma and a space; a path itself contains no spaces or commas. They
  name the files the task creates or changes.
- There is no separate mapping table: the brackets are the mapping.
- Sections titled `## Convergence <n>` are appended later by the converge pass and are not
  counted against the cap. Never write one yourself.

### 5. Lint the Plan
Run `python3 ~/.claude/scripts/spec_lint.py <spec-directory>` again. It now also checks the
plan: grammar, the cap, and coverage in both directions. Fix every finding.

After the linter is clean, present a summary of the plan and ask the user to approve before proceeding to `/sdd-implement`.
