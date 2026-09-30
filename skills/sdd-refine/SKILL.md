---
name: sdd-refine
description: >
  SDD step 2 (optional, repeatable). Read an existing feature.md and refine it by updating or
  enhancing requirements based on user input. Use when requirements have changed,
  new edge cases are discovered, or the spec needs clarification before planning
  or re-planning. Run before /sdd-plan if plan.md already exists.
argument-hint: <what to change or enhance (optional)>
---

# SDD: Refine Feature Spec

You are a senior software architect refining an existing feature specification.

## Inputs

| Input                | Required | Description                       | Example                                               |
|----------------------|----------|-----------------------------------|-------------------------------------------------------|
| `refinement_request` | Optional | What to change or add to the spec | "Add rate limiting: max 5 login attempts per minute" |

## Steps

### Step 0: Validate Inputs (ALWAYS DO THIS FIRST)

Check the conversation for `refinement_request` and for `feature.md` in the project root.

- If `feature.md` does not exist → stop and tell the user to run `/sdd-feature` first.
- If `refinement_request` is present → proceed to Step 1.
- If `refinement_request` is missing → ask:
  > "What would you like to change or add to the spec? Is this a scope change, a clarification, or new edge cases?"
  Do NOT proceed until the user provides it.

---

## Pre-conditions
Verify `feature.md` exists in the project root.
If it does not exist, tell the user to run `/sdd-feature` first.

### 1. Read Current State
Read these files before doing anything:
- `feature.md`: the existing spec to be refined
- `docs/project.md`: project context and constraints
- `plan.md`: if it exists, note which parts of the plan may be invalidated by changes

### 2. Understand the Refinement Request
The refinement input is: **`refinement_request`** (collected in Step 0).

Analyse `refinement_request` against the current `feature.md` and identify:
- What sections are affected
- Whether the change expands scope, reduces scope, or clarifies existing scope
- Any knock-on effects (e.g., changing a requirement may invalidate other ACs)

### 3. Clarify One Question at a Time
Open `[NEEDS CLARIFICATION: ...]` markers in `feature.md` come first, then any ambiguity in the
refinement request itself. Work through them one by one:

1. Ask **one** question. Offer 2 to 4 concrete options and mark one as recommended, with the
   reason in one line (impact, scope, risk).
2. Wait for the answer.
3. Apply it immediately to the section it affects, and delete the marker it resolves.
4. Only then ask the next question. Stop after 5 questions in one session; anything left stays
   as a marker.

### 4. Show a Diff Summary Before Editing
Before modifying the file, present a brief plan of changes:

```
## Proposed Changes to feature.md

### Additions
- FR-04: <new requirement>
- AC-05: <new acceptance criterion>

### Modifications
- FR-02: Updated to clarify that X also applies to Y
- AC-02: Strengthened: must complete within 200ms, not 500ms

### Removals
- FR-03: Removed: out of scope per user confirmation

### No Change
- All other sections remain as-is
```

Ask the user to confirm before applying.

### 5. Apply the Refinements
Update `feature.md` in place. Preserve:
- Existing section structure and numbering where possible
- The checkbox state of every criterion exactly as found; never tick or untick one
- The `Spec-Format` header, the Glossary, and EARS form for every criterion (new criteria
  follow the patterns in `/sdd-feature`, with a Glossary name as subject)
- Open markers you did not resolve; add a new one only if the refinement raises a question
  you cannot answer, and never exceed 3 in total

Increment requirement IDs sequentially (do not reuse deleted IDs).

### 6. Impact Assessment
After updating `feature.md`, check if `plan.md` exists.
If it does, analyse the impact:

```
## Impact on plan.md

plan.md exists and may be partially invalidated. Here is what needs revisiting:

- Step 2 (Domain Layer): FR-04 adds a new value object not currently planned
- Step 6 (Tests): 2 new ACs require additional test cases
- Step 3 is unaffected

Recommendation: Run /sdd-plan again to regenerate the plan before implementing.
```

If `plan.md` does not exist, simply confirm the spec is updated and prompt the user to run `/sdd-plan`.

### 7. Changelog Entry
Append a refinement record at the bottom of `feature.md`:

```markdown
---

## Revision History

| Date | Change Summary |
|------|----------------|
| <date> | Initial spec |
| <date> | <One-line summary of this refinement> |
```

If a revision history table already exists, append a new row; do not recreate the table.
The row names the questions answered in this session. This table is the only clarification log.

### 8. Lint
Run `python3 ~/.claude/scripts/spec_lint.py <spec-directory>` and fix every finding.
