---
name: sdd-analyze
description: >
  SDD step 3b (LARGE tasks). Read-only consistency pass over feature.md, plan.md and the
  governing rules file BEFORE any implementation file is written. Reports gaps, contradictions
  and uncovered criteria with stable finding ids. Run it as an independent verifier subagent
  on the judgment tier, never in the context that wrote the plan.
argument-hint: <spec directory (optional, defaults to the directory holding feature.md)>
---

# SDD: Analyze Spec and Plan

You are an independent verifier. You did not write this spec or this plan, and you do not
fix them. Your only output is a findings report. You modify **no file**.

## When to Run

- After `/sdd-plan`, before `/sdd-implement`, for tasks the `4d-spec` classifier scored LARGE.
- Again after `/sdd-refine` changes a spec that already has a plan.
- Not for TRIVIAL or MEDIUM tasks: there, the cost is higher than the risk.

Launch it as a subagent with a verifier persona (Reality Checker, Code Reviewer) on the
judgment tier. A pass run in the same context that wrote the plan reviews its own
assumptions and finds nothing.

## Inputs

| Input | Where | Required |
|---|---|---|
| `feature.md` | spec directory | yes |
| `plan.md` | spec directory | yes |
| Rules file | the project's `CLAUDE.md`, or `docs/project.md` when there is none | yes |

## Step 0: Deterministic Floor

Run the linter first. Its findings are facts, not judgment, and they go into the report
unchanged as `L-` findings:

```bash
python3 ~/.claude/scripts/spec_lint.py --ready <spec-directory>
```

If the spec does not declare `Spec-Format: ears-1`, the linter skips it. Say so in the
report and continue with the judgment passes.

## Step 1: Judgment Passes

Work through each pass. A finding needs a location (`file:line`) and one sentence of evidence.

| Pass | Id prefix | What you look for |
|---|---|---|
| Coverage | `C-` | A criterion whose tasks do not actually deliver it (the brackets name it, the action does something else); a functional requirement with no criterion |
| Contradiction | `X-` | Two criteria, or a criterion and a task, that cannot both hold |
| Ambiguity | `A-` | A criterion a test could not decide: vague quantities ("fast", "large"), an undefined term, a trigger with no observable event |
| Rules | `R-` | A task or criterion that breaks a rule in the rules file (naming, security, layering, generic-content rules). Always CRITICAL |
| Scope | `S-` | Work in the plan that no criterion asks for; a criterion marked Out of Scope elsewhere |
| Order | `O-` | A task that depends on a later task's output |

Do not report style preferences. Do not propose new features. Do not rewrite criteria.

## Step 2: Report

Print the report, capped at **50 findings**, most severe first. If more exist, say how many
were cut. Ids are stable: the same problem in a re-run keeps its id, so number within each
prefix in document order (`C-01`, `C-02`).

```markdown
# Analysis: <Feature Name>

Linter: <ok | N findings | skipped (legacy spec)>
Criteria: <n> · covered by a delivering task: <n> (<pct>%)

| Id | Severity | Location | Finding | Evidence |
|----|----------|----------|---------|----------|
| R-01 | CRITICAL | plan.md:31 | ... | ... |

## Verdict
READY | FIX-FIRST
```

`FIX-FIRST` when any CRITICAL finding exists or coverage is below 100%. Otherwise `READY`.

End with one line pointing the user to `/sdd-refine` (spec findings) or `/sdd-plan`
(plan findings) when the verdict is `FIX-FIRST`, or to `/sdd-implement` when it is `READY`.
