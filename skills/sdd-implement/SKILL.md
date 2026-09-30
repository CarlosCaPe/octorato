---
name: sdd-implement
description: >
  SDD step 4. Read plan.md and implement the feature task by task, running the
  build and tests after each layer. Whether the feature is done is decided by /sdd-converge,
  not here.
  Use after /sdd-plan has produced plan.md.
---

# SDD: Implementation

You are a senior software engineer executing the implementation plan precisely.

## Pre-conditions
Verify these files exist:
- `plan.md`: the implementation plan
- `feature.md`: the feature spec (for acceptance criteria)
- `docs/project.md`: project context

## Process

### 1. Read Everything
Read `plan.md`, `feature.md`, and `docs/project.md` before writing a single line of code.

### 2. Execute Steps in Order
Work through each step in `plan.md` sequentially. For each step:
- Announce which step you're starting
- Create or modify the specified files
- Follow the architectural patterns from `docs/project.md` strictly
- Do not skip steps or reorder without explaining why
- **As soon as a step is complete and verified, mark it done in `plan.md`** by changing `- [ ]` to `- [x]` on that step's line (or prepending `✅` if the plan does not use checkboxes)

### 3. Code Quality Rules
- Follow the conventions already present in the codebase (read existing similar files first)
- Write clean, idiomatic code for the tech stack
- Add documentation to public APIs
- Do not introduce new dependencies without flagging it to the user

### 4. Run Verification After Each Layer
After completing each step, run the relevant build/test command from `docs/project.md`:
- After schema changes: check migration applies cleanly
- After each new source file: compile (use the project's compile command)
- After tests are written: run them (use the project's test command)
- Fix any failures before proceeding to the next step

### 5. Do Not Grade Your Own Work
Do not declare acceptance criteria met, and never tick or annotate them in `feature.md` or
anywhere else. The process that wrote the code is the worst judge of whether it satisfies
the spec. Run the full test suite once at the end and report its result; `/sdd-converge`
decides completion.

If the plan carries a `## Convergence <n>` section with open tasks, work through those tasks
the same way as the original ones.

### 6. Summary Report
Write a file named `impl-summary.md` in the project root with the following content:

```markdown
## Implementation Complete

### Files Created
- ...

### Files Modified
- ...

### Test Suite
<command run> → <result, one line>

### Notes
Any deviations from the plan and why.
```

Keep each entry a single concise bullet: this file is a quick reference, not prose.

After writing the file, tell the user: "`impl-summary.md` created." For a LARGE task, prompt them to run `/sdd-converge` as an independent subagent; for smaller tasks, `/sdd-review`.
