---
name: 4d-spec
description: >
  Orchestrator that merges the 4D Paradigm with Spec-Driven Development (SDD).
  Classifies task complexity and activates SDD phases only when warranted.
  Use at the START of any implementation task to determine the right workflow depth.
triggers:
  - new feature
  - implementation task
  - build feature
  - spec driven
  - 4d+s
  - complex change
---

# 4D+S: Spec-Driven 4D Orchestrator

Merges the Octopus 4D Paradigm with SDD (Spec-Driven Development) to get the best of both worlds.

## When to Activate

This skill activates at the START of any task that involves writing or modifying code.
It classifies complexity and routes to the appropriate workflow depth.

## Complexity Classifier

Assess the task against these criteria:

| Signal | Points |
|--------|--------|
| Touches 1-3 files | 0 |
| Touches 4-10 files | +2 |
| Touches 10+ files | +4 |
| New feature (not a fix) | +2 |
| Architectural decision required | +3 |
| Multiple modules/services affected | +2 |
| User explicitly requests spec | +5 |
| Database schema changes | +1 |
| New API endpoints | +1 |

**Score → Workflow:**

| Score | Level | Workflow |
|-------|-------|---------|
| 0-2 | TRIVIAL | 4D only (Describe → Gate → Execute → Diligent → Disclose) |
| 3-5 | MEDIUM | 4D + `plan.md` (task checklist before Gate) |
| 6+ | LARGE | 4D + full SDD (`feature.md` + `plan.md` + analyze + implement ⇄ converge + `review.md` + archive) |

## Workflow by Level

### TRIVIAL (score 0-2)

Standard 4D: no SDD artifacts needed:
1. **1D Describe**: state what and why (1-3 sentences)
2. **2D Delegate**: run delegate-check
3. **4D Gate**: Change Manifest table
4. **Execute**
5. **3D Diligent**: build/lint/test
6. **4D Disclose**: impact + side effects

### MEDIUM (score 3-5)

4D + task checklist:
1. **1D Describe**: state what and why
2. **2D Delegate**: run delegate-check
3. **2S Plan**: generate `plan.md` with numbered tasks (cap: 20 tasks max)
   - Use `/sdd-plan` format but lighter: no AC mapping table needed
   - Plan lives in working directory, deleted after completion
4. **4D Gate**: Change Manifest + plan.md summary
5. **Execute**: follow plan tasks in order, mark done
6. **3D Diligent**: build/lint/test
7. **4D Disclose**: impact + side effects
8. Clean up: delete plan.md (git tracks the actual changes)

### LARGE (score 6+)

Full 4D+SDD. "Done" is a verdict computed against the spec by a pass that did not write
the code, never a claim by the builder:
1. **1D Describe + Spec**: `/sdd-feature` produces an ears-1 `feature.md` (EARS criteria,
   Glossary, at most 3 open markers)
   - Resolve markers with `/sdd-refine`, one question at a time
2. **2D Delegate**: run delegate-check (loads relevant agents/skills)
3. **2S Plan**: `/sdd-plan` refuses while markers remain, then writes `plan.md` in the task
   grammar `T## [AC-##] <path>: <action>`
4. **2S Analyze**: `/sdd-analyze` as an independent verifier subagent. `FIX-FIRST` sends you
   back to step 1 or 3
5. **4D Gate**: Change Manifest + spec summary + plan summary + analyze verdict
6. **Execute**: `/sdd-implement` (follows plan, verifies each layer, grades nothing)
7. **3D Converge**: `/sdd-converge` as an independent verifier subagent. `GAPS` appends a
   Convergence section to `plan.md`; go back to step 6. Loop until `CONVERGED`
8. **3D Review**: `/sdd-review` (7 quality dimensions, reads the converge verdict)
9. **4D Disclose**: impact radius + converge and review verdicts
10. **Archive**: `/sdd-archive` requires `CONVERGED`, then moves to `docs/specs-archive/`

## Integration with Existing 4D

| 4D Phase | SDD Enhancement | When |
|----------|----------------|------|
| 1D Describe | Becomes `feature.md` with ACs and edge cases | LARGE only |
| 2D Delegate | No change: delegate-check still runs | Always |
| 4D Gate | Manifest now INCLUDES plan.md task list | MEDIUM+ |
| 3D Diligent | Adds the converge loop (done = verdict) + 7-dimension quality review | LARGE only |
| 4D Disclose | Adds archive for institutional memory | LARGE only |

## Key Adaptations for Solo Operator

- **Max 20 planned tasks** in any plan.md (tasks above the first `## Convergence` section): if SDD generates more, consolidate
- **No docs/project.md required**: we already have `.claude/CLAUDE.md` per arm
- **feature.md lives in project root** during work, archived after
- **review.md is optional for MEDIUM**: only mandatory for LARGE
- **`/sdd-yolo`** maps to our "hazlo directo" exception: full pipeline with single gate

## Output Format

At task start, always report:

```
4D+S Classification: [TRIVIAL/MEDIUM/LARGE] (score: N)
  Signals: [list matched signals]
  Workflow: [which phases activate]
  SDD skills: [which /sdd-* commands will be used, or "none"]
```

## Quick Reference

| Want to... | Command |
|------------|---------|
| Classify a task | Read this skill's classifier |
| Write a spec | `/sdd-feature` |
| Refine a spec | `/sdd-refine` |
| Generate plan | `/sdd-plan` |
| Check spec against plan | `/sdd-analyze` |
| Implement from plan | `/sdd-implement` |
| Decide whether it is done | `/sdd-converge` |
| Review code quality | `/sdd-review` |
| Archive completed work | `/sdd-archive` |
| Full pipeline (one gate) | `/sdd-yolo` |
