---
name: orchestrated-planning
description: "Create and execute phased implementation plans with documentation discovery and subagent delegation. Use when asked to plan a feature, execute a multi-step task, or when 2D Delegate determines the task needs structured planning before execution."
metadata:
  source: "Adapted from claude-mem make-plan + do skills (thedotmack/claude-mem)"
  version: "1.0.0"
  adopted: "2026-04-13"
---

# Orchestrated Planning & Execution

> Two-mode skill: **Plan** (create phased plan) and **Execute** (run plan with subagents).
> Integrates with the 4D Paradigm: enhances 2D Delegate with structured research
> and 3D Diligent with per-phase verification.

## Triggers

- "plan this feature", "create a plan", "break this down"
- "execute the plan", "run the plan", "do the plan"
- Complex multi-file changes spanning 3+ files
- When delegate-check recommends structured planning
- Unfamiliar APIs, frameworks, or codebases

## Mode 1: Plan (make-plan)

You are an ORCHESTRATOR. Create an LLM-friendly plan in phases that can be
executed consecutively -- each phase self-contained with its own context.

### Delegation Model

Use subagents for *fact gathering and extraction* (docs, examples, signatures,
grep results). Keep *synthesis and plan authoring* with the orchestrator
(phase boundaries, task framing, final wording).

### Subagent Reporting Contract (MANDATORY)

Each subagent response must include:
1. **Sources consulted** -- files/URLs read, with line numbers
2. **Concrete findings** -- exact API names, signatures, file paths
3. **Copy-ready snippets** -- example code locations to reference
4. **Confidence note** -- known gaps, what might be missing

**Reject and redeploy** the subagent if it reports conclusions without sources.

### Phase 0: Documentation Discovery (ALWAYS FIRST)

Before planning implementation, deploy subagents to:
1. Search for relevant docs, examples, and existing patterns in the codebase
2. Identify actual APIs, methods, and signatures (not assumed)
3. Create an **Allowed APIs** list citing specific documentation
4. Note anti-patterns -- methods that DON'T exist, deprecated parameters

### Each Implementation Phase Must Include

1. **What to implement** -- frame tasks to COPY from docs, not transform
   - Good: "Copy the pattern from src/utils/auth.ts:45-60"
   - Bad: "Migrate the existing code to the new approach"
2. **Documentation references** -- cite specific files/lines
3. **Verification checklist** -- how to prove this phase worked
4. **Anti-pattern guards** -- what NOT to do

### Final Phase: Verification

1. Verify all implementations match documentation
2. Grep for known bad patterns
3. Run tests to confirm functionality

## Mode 2: Execute (do)

You are an ORCHESTRATOR. Deploy subagents to execute *all* work. Do not do
the work yourself except to coordinate, route context, and verify.

### Execution Rules

- Each phase uses fresh subagents (clean context)
- One clear objective per subagent, require evidence
- Do not advance until the assigned subagent reports completion
  AND the orchestrator confirms it matches the plan

### During Each Phase

Deploy an "Implementation" subagent to:
1. Execute the implementation as specified in the plan
2. COPY patterns from documentation, don't invent
3. Cite documentation sources in code comments for unfamiliar APIs
4. If an API seems missing, **STOP and verify** -- don't assume it exists

### After Each Phase

Deploy verification subagents:
1. **Verification** -- run the phase's verification checklist
2. **Anti-pattern check** -- grep for known bad patterns from the plan
3. **Quality review** -- review changes for correctness
4. **Commit only if verified** -- no commit until verification passes

### Between Phases

- Push to working branch after each verified phase
- Prepare next phase handoff with plan context

## Integration with 4D Paradigm

| 4D Phase | How This Skill Enhances It |
|----------|---------------------------|
| 1D Describe | Plan output IS the description (phases, scope, files) |
| 2D Delegate | Phase 0 Doc Discovery = structured 2D research |
| 3D Diligent | Per-phase verification checklists = systematic 3D |
| 4D Disclose | Plan manifest = pre-flight disclosure of all changes |

## Anti-Patterns to Prevent

- Inventing API methods that "should" exist
- Adding parameters not in documentation
- Skipping Phase 0 (doc discovery)
- Skipping verification steps between phases
- Assuming structure without checking examples
- Doing work yourself instead of deploying subagents

## When NOT to Use

- Single-file edits under 50 lines (just do it directly)
- Well-understood patterns already in the codebase
- When delegate-check says SELF (no specialist needed)

## Lessons Learned

1. **Documentation Availability != Usage** -- explicitly require reading docs
2. **Task Framing Matters** -- direct agents to docs, not just outcomes
3. **Verify > Assume** -- require proof, not assumptions about APIs
4. **Session Boundaries** -- each phase must be self-contained with own doc refs
5. **Reject incomplete reports** -- subagents must cite sources or be redeployed
