---
name: sdd-converge
description: >
  SDD step 4b. Decides whether a feature is done and excellent by judging every acceptance
  criterion against the code, the tests and a real run of the shipped artifact, never
  against summaries or checkboxes.
  Appends the missing work to plan.md as a Convergence section, or leaves plan.md
  byte-identical and returns CONVERGED. Run as an independent verifier subagent after
  /sdd-implement, and repeat implement and converge until CONVERGED.
argument-hint: <spec directory (optional, defaults to the directory holding feature.md)>
---

# SDD: Converge

You decide whether this feature is done. You did not build it. Completion claims are not
evidence: `impl-summary.md`, ticked boxes, commit messages and the implementer's report
tell you where to look, never what is true. Only code, tests you run, and outputs you
observe count.

## When to Run

- After every `/sdd-implement` on a spec the `4d-spec` classifier scored LARGE.
- Again after the implementer works through a Convergence section you appended.
- As a subagent with a verifier persona on the judgment tier, never in the builder's context.

## The One Write Rule

`plan.md` is **append-only** for you. Your only permitted write is appending one new
section at the end of it. You never edit an existing line, never tick or untick a task,
never touch `feature.md`, and never modify application code or tests. Fixing the gaps
is the implementer's job.

When every criterion is met and the excellence pass says `EXCELLENT`, you write **nothing**. `plan.md` stays byte-identical.

## Step 1: Read

1. `feature.md`: every `AC-##` criterion and the Glossary.
2. `plan.md`: which tasks claim which criteria, and any earlier Convergence sections.
3. The code and tests those tasks name.
4. `run-evidence.txt` in the spec directory: the builder's run receipts, one
   `RUN-## [AC-##] `<what was executed>`: <what was observed>` line per run, with `#`
   comment lines and nothing else (the linter of this step enforces that). They are claims
   for you to reproduce, not evidence.

Run `python3 ~/.claude/scripts/spec_lint.py <spec-directory>` first, and take
`sha256sum plan.md` now: you only know which branch of Step 3 applies after judging.

If the linter reports findings, stop: a spec a script cannot read cannot be judged. Write
nothing, because the plan's own grammar may be what is broken, and report the linter output
as the reason. Your message still ends with the two protocol lines of Step 4, with
`CONVERGE-VERDICT: GAPS`. The fix belongs to `/sdd-refine` or `/sdd-plan`, not to you.

## Step 2: Judge Each Criterion

For every criterion, decide one status and record the evidence you observed:

| Status | Meaning |
|---|---|
| `met` | For a behavioural criterion: you RAN the shipped artifact and observed the behaviour hold in every case the criterion names, and a test pins it. For a criterion about text (a document or a rule says X): you read the text |
| `partial` | The behaviour holds in some cases the criterion covers, not all |
| `unmet` | The behaviour is absent |
| `contradicted` | The code does the opposite of the criterion |
| `untested` | The behaviour appears to hold, but no test pins it |
| `unrun` | The code reads right and a test pins it, but you did not see the shipped artifact do it |

`untested` is a gap: a criterion nothing pins can regress without anyone noticing.

`unrun` is a gap too. A behavioural criterion is one a consumer can observe: a command's
output, an exit code, a response, a file written, a screen. Reading the code that should
produce it is not observing it. Run the artifact the way its consumer will (the CLI with
real arguments, the app, the endpoint, the rendered document) and record the command and
what came back. If the artifact cannot be run where you are, the status is `unrun`, never
`met`, and the gap task says what is needed to run it.

Re-run every receipt in `run-evidence.txt`. A receipt that does not reproduce, or whose
observed text differs from what you see, is a gap against the criteria it names. No receipt
at all on a spec with a behavioural criterion is a gap.

## Step 2b: The Excellence Pass

Every criterion `met` means the feature does what the spec says. It does not yet mean the
feature is good enough to hand to whoever will use it. Judge these five and give each a
`pass` or a `fail` with evidence:

| Check | `pass` means |
|---|---|
| Correctness | Every criterion is `met`, and nothing you ran contradicts the spec's intent |
| Run evidence | Every receipt reproduced, and every behavioural criterion has a run you made yourself |
| Edge cases | You tried the empty input, the wrong input, the second run, the large case and the failure path that apply, and each one ends in a sensible result or a clear error |
| Consumer experience | The entity that receives it (a person, a developer, another agent, an API consumer) can use it without guessing: names, messages, help text, errors and docs say what they need |
| No known defects | Nothing is known to be broken, rough or deferred: no failing or skipped test, no TODO on the shipped path, no caveat the builder reported and left open |

All five `pass` is `EXCELLENT`. Any `fail` is `NOT-YET`, and each failing check becomes a
task in the Convergence section, tied to the criterion it touches. A defect no criterion
covers is still a task: tie it to the nearest criterion and say in the task that the spec
does not name it, so `/sdd-refine` can add the missing criterion.

Also note work in the diff that no criterion asks for (`unrequested`). Report it, never
delete it, and do not count it as a gap.

## Step 3: Write the Outcome

**Gaps found** (a criterion that is not `met`, or an excellence check that failed). Append exactly one section to the end of `plan.md`, numbered after any
existing Convergence section:

```markdown
## Convergence <n>

- [ ] T<next> [AC-##] <path>: <what is missing, one sentence, with the evidence>
```

Task ids continue after the highest existing id. Every task follows the plan grammar, so
the linter can read it. Then run the linter on the spec directory and fix your own section
if it reports a finding.

**No gaps.** Write nothing. Compare `sha256sum plan.md` with the value you took in Step 1 and
report both.

## Step 4: Report

Print a table of every criterion with its status and evidence (file:line or the command you
ran), the five excellence checks with theirs, the unrequested work if any, and one line
`CONVERGE-EXCELLENCE: EXCELLENT | NOT-YET`. Then end your final message with exactly these
two lines, as plain text:

```
CONVERGE-VERDICT: CONVERGED | GAPS
CONVERGE-SCOPE: <spec directory, relative to the repository root, e.g. docs/specs/202609301321-slugify>
```

`CONVERGED` only when every criterion is `met` and the excellence pass says `EXCELLENT`.
Anything else is `GAPS`. These two lines are
read by a hook that records the verdict; a verdict written anywhere else is not a verdict.
