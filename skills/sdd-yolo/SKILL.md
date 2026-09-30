---
name: sdd-yolo
description: >
  SDD fast path. Runs the full pipeline (spec, plan, analyze, implement and converge until
  done, review, archive) with a single confirmation gate before implementation begins.
  Stops automatically if analyze says FIX-FIRST, converge cannot close, or review finds
  Critical or Major issues.
  Use when you want to ship a well-understood feature with minimal interruptions.
argument-hint: <feature description>
---

# SDD: YOLO Full Pipeline

You are running the full SDD workflow end-to-end with minimal interruptions.
The pipeline is: **spec → plan → analyze → implement ⇄ converge → review → archive**.

There is exactly **one confirmation gate**: after the spec and plan are produced,
before implementation begins. Everything else runs automatically.

## Required Inputs

Before starting, collect these inputs. If any are missing, ask for them now: do not proceed without them.

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

## Phase 1: Spec

Follow the full `sdd-feature` process:

1. Read `docs/project.md`.
2. Analyse the request: **`feature_description`** (collected in Step 0).
3. Create the spec directory `docs/specs/<yyyymmddHHMM>-<feature-name>/` and write `feature.md`
   in it, in the ears-1 format of `sdd-feature`: `Spec-Format: ears-1` header,
   Glossary, EARS acceptance criteria. Anything you cannot decide becomes an inline
   `[NEEDS CLARIFICATION: ...]` marker (at most 3).
4. If markers remain, resolve them with the user one question at a time, each with a
   recommended answer, as `sdd-refine` does. The pipeline does not continue with open markers.
5. Run `python3 ~/.claude/scripts/spec_lint.py --ready <spec-directory>` and fix every finding.
6. Print a compact summary of the spec (3 to 5 bullet points, not the full file).

---

## Phase 2: Plan

Follow the full `sdd-plan` process immediately after Phase 1:

1. Read `feature.md` and `docs/project.md`.
2. Write `plan.md` in the task grammar `- [ ] T## [AC-##] <path>: <action>`, at most 20 tasks.
3. Run the linter again: every criterion must be covered by a task.
4. Run `/sdd-analyze` as an independent verifier subagent. On `FIX-FIRST`, fix the spec or
   the plan and re-run it; do not reach the gate with a `FIX-FIRST` verdict.
5. Print a compact summary of the plan (task names only, not full detail) and the analyze verdict.

---

## Confirmation Gate

Present the following prompt and **wait for the user's response** before continuing:

```
## Ready to implement

Spec: feature.md ✓
Plan: plan.md ✓

[Compact spec summary: 3–5 bullets]
[Plan steps: numbered list of step names]

Type PROCEED to start implementation, or describe any changes you want first.
```

- If the user types **PROCEED** (or equivalent confirmation): continue to Phase 3.
- If the user requests changes: apply them to `feature.md` and/or `plan.md`, show what changed, then re-present the gate.
- If the user aborts: stop and leave `feature.md` and `plan.md` in place for manual continuation.

---

## Phase 3: Implement

Follow the full `sdd-implement` process:

1. Read `plan.md`, `feature.md`, and `docs/project.md`.
2. Execute each step in `plan.md` in order.
3. Compile and run tests after each layer. Fix failures before moving on: never carry failures forward.
4. Do not introduce new dependencies without flagging them to the user.
5. After all tasks, run the full test suite once and print the completion summary (files
   created and modified, test result). Do not grade the criteria yourself.

### Converge loop

6. Run `/sdd-converge` as an independent verifier subagent.
7. On `GAPS`, implement the tasks it appended under `## Convergence <n>`, then run it again.
8. Stop the pipeline if the same criterion stays unmet after 3 converge passes. Continue only
   on `CONVERGED`. When you stop, print:

```
## YOLO Pipeline Stopped: converge did not close

Feature: <Feature Name>
Unmet after 3 passes: <AC ids, with the converge evidence for each>

feature.md and plan.md stay in place. Decide whether the criterion or the code is wrong:
/sdd-refine for the criterion, /sdd-implement for the code, then /sdd-converge.
```

---

## Phase 4: Review

Follow the full `sdd-review` process immediately after Phase 3:

1. Run `git diff main...HEAD --name-only` to determine changed files.
2. Review across the 7 quality dimensions (language and framework practices, security,
   duplication, design, performance, test quality, observability), quoting the converge verdict.
3. Produce the full structured review report.

---

## Phase 5: Archive or Stop

Evaluate the review verdict:

### If verdict is ✅ Ready to merge OR 🟡 Merge after minor fixes

Proceed automatically to archive:

1. Follow the full `sdd-archive` process.
2. Update `docs/project.md` (features list, architecture decisions, API surface, env config).
3. Show the proposed `project.md` changes and ask for confirmation before writing.
4. The spec directory `docs/specs/<yyyymmddHHMM>-<feature-name>/` stays where it is.
5. Create `README.md` in it.

Then print the final pipeline summary:

```
## YOLO Pipeline Complete ✓

Feature: <Feature Name>
Spec directory: docs/specs/<yyyymmddHHMM>-<feature-name>/

Phase results:
  Spec        ✓
  Plan        ✓  (analyze: READY)
  Implement   ✓  (N files created, M files modified)
  Converge    ✓  (CONVERGED after <k> pass(es))
  Review      ✓  (<verdict>)
  Archive     ✓

Next: commit the spec directory and docs/project.md to version control.
```

### If verdict is 🟠 Requires fixes and re-review OR 🔴 Do not merge

**Stop. Do not archive.**

Print:

```
## YOLO Pipeline Stopped: Review issues require attention

Feature: <Feature Name>

Phase results:
  Spec        ✓
  Plan        ✓
  Implement   ✓
  Converge    ✓
  Review      ✗  (<verdict>)
  Archive     skipped

Critical/Major findings must be resolved before archiving.
Fix the issues above, then run /sdd-review to re-review, and /sdd-archive when clean.
```

Leave the spec directory as it is so the user can continue manually.
