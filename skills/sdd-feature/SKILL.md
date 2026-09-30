---
name: sdd-feature
description: >
  SDD step 1. Analyse a feature request and produce a detailed feature.md spec.
  Use when the user describes a new feature they want to build.
  Asks for missing details before writing the spec.
argument-hint: <feature description or title>
---

# SDD: Feature Analysis

You are acting as a senior software architect and requirements analyst.

## Required Inputs

Before starting, collect these inputs. If any are missing, ask for them now: do not proceed without them.

| Input                 | Description           | Example                                             |
|-----------------------|-----------------------|-----------------------------------------------------|
| `feature_description` | What feature to build | "Add JWT authentication with refresh token support" |

## Steps

### Step 0: Validate Inputs (ALWAYS DO THIS FIRST)

Check the conversation for `feature_description`.
- If present → proceed to Step 1.
- If missing → ask: "What feature would you like to build?" Do NOT proceed until the user provides it.

---

## Your Goal
Produce a thorough `feature.md` file that leaves no ambiguity for the implementation step.

### 1. Read Project Context
Always start by reading `docs/project.md` to understand:
- The tech stack in use
- Architecture patterns and constraints
- Any existing conventions

### 2. Analyse the Request
The feature request is: **`feature_description`** (collected in Step 0).

Identify any missing or ambiguous information across these dimensions:
- **Functional requirements**: what exactly should the feature do?
- **User stories**: who benefits and how?
- **Acceptance criteria**: how do we know it's done?
- **Edge cases**: what could go wrong?
- **Integration points**: which existing modules/services are involved?
- **Non-functional requirements**: performance, security, scalability concerns?
- **Out of scope**: what are we explicitly NOT building?

### 3. Mark What You Cannot Decide
Do not stop to ask a batch of questions. Write the spec with what is known, and put each open
decision inline, exactly where it matters, as a marker: `[NEEDS CLARIFICATION: <question>]`.

- At most **3** markers. If more than 3 things are unknown, keep the 3 that change scope,
  security or user experience most, in that order, and make a reasonable, stated assumption for the rest.
- Markers are resolved by `/sdd-refine`, one question at a time. `/sdd-plan` refuses to run while any remain.
- If the description is too thin to write even one requirement, ask the user one question and wait.

### 4. Write feature.md
Once you have enough information, create `feature.md` in the project root with this structure:

```markdown
# Feature: <Feature Name>

> **Status:** draft
> **Spec-Format:** ears-1

## Summary
One-paragraph description of the feature and its purpose.

## Glossary
Name every component an acceptance criterion can talk about. Each criterion's subject must be one of these names.
- **<ComponentName>**: <what it is, one line>

## User Stories
- As a <role>, I want to <action> so that <benefit>.

## Functional Requirements
### FR-01: <Requirement Name>
Description...

### FR-02: ...

## Acceptance Criteria
- [ ] AC-01: THE <Component> SHALL <response>.
- [ ] AC-02: WHEN <trigger>, THE <Component> SHALL <response>.
- [ ] AC-03: WHILE <state>, THE <Component> SHALL <response>.
- [ ] AC-04: WHERE <optional feature is present>, THE <Component> SHALL <response>.
- [ ] AC-05: IF <unwanted condition>, THEN THE <Component> SHALL <response>.

## Technical Scope
### Affected Modules
- List of modules/packages/services involved

### New Components Required
- List of new classes, endpoints, tables, etc.

### Integration Points
- Existing services or systems this interacts with

## Non-Functional Requirements
- Performance: ...
- Security: ...
- Scalability: ...

## Out of Scope
- Explicitly list what is NOT included

## Revision History

| Date | Change Summary |
|------|----------------|
| <date> | Initial spec |
```

### 5. Acceptance Criteria Are EARS Sentences
Every criterion is ONE sentence in one of the five EARS patterns above, with the keywords in
capitals exactly as shown and a Glossary name as its subject. `SHALL NOT` is allowed. One
behaviour per criterion; a criterion that needs "and" to describe two outcomes is two criteria.
Criteria are never ticked by the author, the implementer or the reviewer.

### 6. Lint the Spec
Run the deterministic linter on the spec directory and fix every finding before handing it over:

```bash
python3 ~/.claude/scripts/spec_lint.py <spec-directory>
```

It checks the EARS shape, the Glossary subjects, unique ids and the marker cap. It makes no model call.

After the linter is clean, summarize what you wrote, list the open markers, and point the user to `/sdd-refine` (to resolve markers) or `/sdd-plan` (when none remain).
