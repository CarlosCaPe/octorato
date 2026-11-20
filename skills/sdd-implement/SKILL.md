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

### 5b. Run It for Real
Tests passing is not the artifact working. Before you hand over, execute what you built the
way its consumer will (the CLI with real arguments, the app, the endpoint, the rendered
document) and record each run in `run-evidence.txt`, a plain-text file next to
`feature.md`, one line per run:

```text
# runs made from the repository root
RUN-01 [AC-01, AC-02] `<the exact command or action>`: <exit code and what you observed>
```

Write the exact command, not a description of it: the verifier pastes it. The file is a
machine grammar, not Markdown: a line is blank, a comment that starts with `#` at column 0,
or a receipt in exactly that shape, and the linter reports anything else. No bullets, no
indent, no tabs, one line per receipt, ids in plain digits. A receipt left as the template,
or filled with `TODO` and the like, is refused, and no receipt counts until every line of
the file passes. Receipts never go in `feature.md`: a `## Run evidence` heading there is a
finding.

A receipt is a claim the verifier reproduces, not a grade: it says what you ran and what
came back, never that a criterion is met. Reading the code is not a run. When a run shows a
defect, fix it and run again before recording. The push gate refuses `Status: converged` on
a spec with no receipt (rule `FLOW.build-loop-excellence`).

If the plan carries a `## Convergence <n>` section with open tasks, work through those tasks
the same way as the original ones.

### 6. Summary Report
Write a file named `impl-summary.md` in the spec directory with the following content:

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
