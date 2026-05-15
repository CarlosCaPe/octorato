---
name: ado-refactor-performance-gate
description: "Mandatory performance gate for Azure DevOps SQL refactor tickets. Use when a ticket includes stored procedure refactor/review and you must validate execution plans, index usage, parameter sniffing risk, and query structure optimization opportunities."
metadata:
  short-description: ADO refactor perf gate
  origin: client projects (anonymized pattern)
---

# ADO Refactor Performance Gate

## Purpose
Apply the same performance review standard to every ADO refactor ticket before closure.

## Mandatory Trigger
Run this skill for each refactor ticket in scope, even if the ticket started as "code cleanup" only.

## Required Inputs
- Ticket ID (ADO work item)
- Environment (stg/prod)
- Stored procedure name
- Baseline query/runtime evidence (if available)

## Workflow (Do Not Skip)
1. Confirm ticket metadata
- Capture: status, assignee, links, attachments.
- Check for attached execution plans (`.sqlplan`) or screenshots.

2. Collect execution evidence
- Get estimated and actual execution plans for the procedure's critical statements.
- Capture top expensive operators, key lookups, scans, spills, memory grants, and parallelism decisions.

3. Validate index usage
- Identify missing/unused/inefficient indexes for predicates, joins, and order by clauses.
- Validate whether existing indexes are covering the selected columns.
- Propose concrete index changes only with impact rationale.

4. Check parameter sniffing risk
- Review parameter selectivity variance.
- Compare behavior across representative parameter sets.
- Recommend mitigation only when justified (e.g. `OPTIMIZE FOR`, `RECOMPILE`, split-path logic, or query rewrite).

5. Review query structure
- Remove non-SARGable predicates where possible.
- Detect correlated subqueries/N+1 patterns and redundant `DISTINCT`/sorts.
- Validate join order, filtering order, and unnecessary JSON parsing or scalar UDF hot spots.

6. Produce optimization decision
- Classify each finding by severity: Critical, High, Medium, Low.
- Mark each as: Apply now, Defer, or Reject (with reason).

7. Blocker check (mandatory)
- Report blockers that prevent completion (permissions, missing plans, missing runtime data, VPN/tenant access, token/auth issues).
- Include owner and next action for each blocker.

## Required Deliverable Format (per ticket)

```markdown
## Performance Gate - <TicketId>
- Procedure: <ProcedureName>
- Status: Pass | Pass with risks | Blocked

### Execution Plan Findings
- <Finding 1>
- <Finding 2>

### Index Findings
- <Current index issue>
- <Recommended index change + rationale>

### Parameter Sniffing Assessment
- Risk: None | Low | Medium | High
- Evidence: <short evidence>
- Mitigation: <if required>

### Query Structure Findings
- <SARGability / subquery / join / sort finding>

### Recommended Actions
1. <Action>
2. <Action>

### Blockers
- <Blocker or "None">

### Closure Decision
- <Why this ticket can or cannot be closed>
```

## Definition of Done
A refactor ticket is not "done" until:
- Execution plan evidence reviewed.
- Index usage reviewed.
- Parameter sniffing risk assessed.
- Query structure reviewed for optimization.
- Blockers explicitly documented (or `None`).

## Typical Blockers to Report
- No `SHOWPLAN`/plan capture permissions
- No runtime DMV access
- VPN not connected to private SQL MI endpoint
- Wrong Azure tenant/subscription context
- Missing ADO PAT/API permissions
- Missing representative parameter samples
