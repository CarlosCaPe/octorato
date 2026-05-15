---
name: sdd-yolo
description: >
  SDD fast path. Runs the full pipeline — analyse → plan → implement → review → archive —
  with a single confirmation gate before implementation begins.
  Stops automatically if Critical or Major issues are found in review.
  Use when you want to ship a well-understood feature with minimal interruptions.
argument-hint: <feature description>
---

# SDD: YOLO Full Pipeline

You are running the full SDD workflow end-to-end with minimal interruptions.
The pipeline is: **analyse → plan → implement → review → archive**.

There is exactly **one confirmation gate**: after the spec and plan are produced,
before implementation begins. Everything else runs automatically.

## Required Inputs

Before starting, collect these inputs. If any are missing, ask for them now — do not proceed without them.

| Input                 | Description                     | Example                                             |
|-----------------------|---------------------------------|-----------------------------------------------------|
| `feature_description` | The feature to build end-to-end | "Add JWT authentication with refresh token support" |

## Steps

### Step 0: Validate Inputs (ALWAYS DO THIS FIRST)

Check the conversation for `feature_description` and for `docs/project.md`.

- If `docs/project.md` does not exist → stop and tell the user to run `/sdd-init` first.
- If `feature_description` is present → proceed to Phase 1.
- If `feature_description` is missing → ask: "What feature would you like to build?" Do NOT proceed until the user provides it.

---

## Phase 1 — Analyse

Follow the full `sdd-feature` process:

1. Read `docs/project.md`.
2. Analyse the request: **`feature_description`** (collected in Step 0).
3. Ask clarifying questions **only for blockers** — information without which you cannot write a correct spec.
   Skip questions about preferences or nice-to-haves. Maximum 3 questions.
4. Write `feature.md` in the project root using the standard structure:

```markdown
# Feature: <Feature Name>

## Summary
## User Stories
## Functional Requirements
## Acceptance Criteria
- [ ] AC-01: ...
## Technical Scope
## Non-Functional Requirements
## Out of Scope
## Open Questions
```

5. Print a compact summary of the spec (3–5 bullet points, not the full file).

---

## Phase 2 — Plan

Follow the full `sdd-plan` process immediately after Phase 1:

1. Read `feature.md` and `docs/project.md`.
2. Write `plan.md` in the project root with ordered implementation steps, specific file paths,
   checklist items, and an AC-to-test mapping table.
3. Print a compact summary of the plan (step names only, not full detail).

---

## Confirmation Gate

Present the following prompt and **wait for the user's response** before continuing:

```
## Ready to implement

Spec: feature.md ✓
Plan: plan.md ✓

[Compact spec summary — 3–5 bullets]
[Plan steps — numbered list of step names]

Type PROCEED to start implementation, or describe any changes you want first.
```

- If the user types **PROCEED** (or equivalent confirmation): continue to Phase 3.
- If the user requests changes: apply them to `feature.md` and/or `plan.md`, show what changed, then re-present the gate.
- If the user aborts: stop and leave `feature.md` and `plan.md` in place for manual continuation.

---

## Phase 3 — Implement

Follow the full `sdd-implement` process:

1. Read `plan.md`, `feature.md`, and `docs/project.md`.
2. Execute each step in `plan.md` in order.
3. Compile and run tests after each layer. Fix failures before moving on — never carry failures forward.
4. Do not introduce new dependencies without flagging them to the user.
5. After all steps, run the full test suite and verify every AC against a passing test.
6. Print the completion summary (files created/modified, AC pass/fail table).

If any AC is failing after implementation, **stop here**. Report what failed and ask the user to fix it before continuing.

---

## Phase 4 — Review

Follow the full `sdd-review` process immediately after Phase 3:

1. Run `git diff main...HEAD --name-only` to determine changed files.
2. Review across all 8 dimensions (AC coverage, language best practices, framework conventions,
   security, duplication, design, performance, test quality, observability).
3. Produce the full structured review report.

---

## Phase 5 — Archive or Stop

Evaluate the review verdict:

### If verdict is ✅ Ready to merge OR 🟡 Merge after minor fixes

Proceed automatically to archive:

1. Follow the full `sdd-archive` process.
2. Update `docs/project.md` (features list, architecture decisions, API surface, env config).
3. Show the proposed `project.md` changes and ask for confirmation before writing.
4. Move `feature.md` and `plan.md` to `docs/specs-archive/<feature-name>/`.
5. Create `docs/specs-archive/<feature-name>/README.md`.

Then print the final pipeline summary:

```
## YOLO Pipeline Complete ✓

Feature: <Feature Name>
Archived to: docs/specs-archive/<feature-name>/

Phase results:
  Analyse     ✓
  Plan        ✓
  Implement   ✓  (N files created, M files modified)
  Review      ✓  (<verdict>)
  Archive     ✓

Next: commit docs/specs-archive/<feature-name>/ and docs/project.md to version control.
```

### If verdict is 🟠 Requires fixes and re-review OR 🔴 Do not merge

**Stop. Do not archive.**

Print:

```
## YOLO Pipeline Stopped — Review issues require attention

Feature: <Feature Name>

Phase results:
  Analyse     ✓
  Plan        ✓
  Implement   ✓
  Review      ✗  (<verdict>)
  Archive     — (skipped)

Critical/Major findings must be resolved before archiving.
Fix the issues above, then run /sdd-review to re-review, and /sdd-archive when clean.
```

Leave `feature.md` and `plan.md` in the project root so the user can continue manually.
