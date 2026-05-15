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
- `feature.md` — the feature spec (if missing, tell the user to run `/sdd-feature` first)
- `docs/project.md` — project context

## Process

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

Create `plan.md` in the project root with this structure:

```markdown
# Implementation Plan: <Feature Name>

## Overview
Brief description of the implementation approach.

## Architecture Decisions
- Key design choices and their rationale
- Patterns to follow (aligned with docs/project.md)

## Implementation Steps

### Step 1: <Database/Schema Changes>
- [ ] Create/alter table: `...`
- [ ] Add migration file: `...`
- Files to create/modify: ...

### Step 2: <Domain Layer>
- [ ] Create entity / model: `...`
- [ ] Create value objects: `...`
- [ ] Define repository / data access interface: `...`
- Files: ...

### Step 3: <Application/Service Layer>
- [ ] Create use case / service: `...`
- [ ] Define request/response objects / command objects: `...`
- Files: ...

### Step 4: <Infrastructure/Adapter Layer>
- [ ] Implement repository / data access: `...`
- [ ] External integrations: `...`
- Files: ...

### Step 5: <API / Presentation Layer>
- [ ] Controller / handler / route: `...`
- [ ] Request/response models: `...`
- [ ] API documentation annotations: `...`
- Files: ...

### Step 6: <Tests>
- [ ] Unit tests: `...`
- [ ] Integration tests: `...`
- [ ] API / end-to-end tests: `...`
- Files: ...

## Acceptance Criteria Mapping
| AC | Verified By |
|----|-------------|
| AC-01: ... | `<TestClass#testMethod>` |
| AC-02: ... | `<TestClass#testMethod>` |

## Risks & Mitigations
- Risk: ... → Mitigation: ...

## Estimated Complexity
Low / Medium / High — brief justification
```

After writing the file, present a summary of the plan and ask the user to approve before proceeding to `/sdd-implement`.
