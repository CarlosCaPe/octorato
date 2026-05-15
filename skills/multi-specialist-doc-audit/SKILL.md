---
name: multi-specialist-doc-audit
description: "Audit a long technical document for hallucinations and uncited claims by dispatching N specialist agents in parallel, each scoped to a domain. Each returns a severity-tiered table; the orchestrator consolidates and decides surgical-fix vs full-rebuild."
metadata:
  short-description: "Parallel N-specialist audit with severity tiers"
---

# Multi-Specialist Doc Audit

## What

A workflow for auditing a long technical document (proposal, RFC, evaluation, RAG output) for hallucinations and unsourced claims. Instead of one agent re-reading the whole thing, dispatch N specialist agents in parallel — each scoped to its domain — and consolidate their findings into one severity-tiered audit report.

## Why

A single-agent audit on a 1000+ line document either:
- runs out of attention (skims, misses domain-specific errors), or
- spends most of its time re-reading content outside its specialty.

A multi-specialist parallel audit:
- catches more domain-specific errors (a Compliance Auditor flags BAA wording a generalist would miss; a Security Engineer flags an OAuth scope name that doesn't exist; a Market Research Analyst catches an outdated vendor pricing claim)
- runs in parallel — the wall-clock cost is one agent's time, not N agents in series
- produces consistent severity tiers across all reviewers, so the consolidator can prioritize fixes
- defaults to "find the issues" rather than "approve the doc" — every specialist enters with a "NEEDS WORK" prior

## When to Use

- Doc length ≥ 500 lines AND mixes author opinion with vendor / regulatory / technical claims
- Doc is going to an external audience (client, regulator, leadership) where credibility cost is high
- Doc claims metrics, vendor capabilities, regulatory references, or auth/security details that can be objectively checked

Do NOT use for:
- Internal scratchpad docs
- Doc < 200 lines (one agent is fine)
- Doc that is purely subjective (e.g., a vision statement)

## Workflow

### 1. Map domains to specialists

Identify the 3–6 distinct claim domains in the doc. Common pattern:

| Domain in the doc | Specialist agent (from the brain registry) |
|---|---|
| Cross-domain / overall narrative / metrics | Reality Checker (default-to-finding-issues) |
| Compliance, regulatory, BAA, encryption | Compliance Auditor |
| Vendor pricing, capabilities, market position | Market Research Analyst |
| OAuth, scopes, Conditional Access, infra security | Security Engineer |
| AI / ML / database / vector store / embedding claims | AI Engineer |
| Code architecture / technical correctness | Code Reviewer or Backend Architect |

Do not dispatch a specialist for a domain the doc doesn't actually cover. One unnecessary agent dilutes the consolidated report.

### 2. Brief each specialist with three things

Each agent gets:
1. **Scope** — exactly which sections / claim types they own (and which they should NOT verify)
2. **Sources of truth** — list of `[KB]` paths, `[vendor:URL]`s, captured artifacts, git log, etc.
3. **Output format** — the severity table (below)

Keep prompts under ~600 words each. Specialists do better with focus than with context.

### 3. Severity tier table (mandatory output format)

Every specialist returns a table:

| Section | Claim | Source verification | Severity | Recommended fix |
|---|---|---|---|---|

Severity values are exactly four:

| Tier | Meaning |
|---|---|
| **HALLUCINATION** | Claim contradicts known truth or has zero source. Must fix. |
| **UNCITED** | Claim plausible but no evidence in any source. Must cite or remove. |
| **ASSUMPTION** | Claim explicitly hedged but presented confidently. Label or hedge. |
| **VERIFIED** | Claim fully backed by a citable source. No fix needed. |

Add `NARRATIVE` for retrospective/framing sections that aren't falsifiable but acceptable as labeled narrative.

### 4. Dispatch in parallel

Make all specialist calls in a single tool-use round so they run concurrently. The wall-clock cost is one agent's time, not N agents serialized.

### 5. Consolidate

The orchestrator receives N reports and produces:

1. A unified severity table (worst first), grouped by tier
2. A count: `X HALLUCINATION / Y UNCITED / Z ASSUMPTION / W VERIFIED`
3. A recommendation:
   - **Surgical fix** if HALLUCINATION count is small (≤5 over a 1000-line doc)
   - **Tier 2 fix** if UNCITED count is large but no HALLUCINATIONS — label assumptions, cite the rest
   - **Full rebuild** if HALLUCINATION count is high or specialists disagree on basic facts

### 6. Present and confirm

Show the consolidated table to the user. Recommend a path. Wait for user confirmation before applying fixes.

## Anti-patterns

| Anti-pattern | Why it fails |
|---|---|
| One agent for the whole doc | Misses domain-specific defects; runs out of attention |
| All specialists with identical prompts | Defeats the parallelization — same issues found N times, missing issues found 0 times |
| Skipping the severity tiers | Without HALLUCINATION/UNCITED/ASSUMPTION/VERIFIED, "issues" become unprioritized |
| Defaulting to "approve" | Specialists must enter with a NEEDS-WORK prior or they rubber-stamp the doc |
| Letting specialists silently skip uncertain claims | Specialists should mark "could not verify, flag for human review" rather than omit |
| Consolidating without showing the user | The orchestrator's job is to surface findings, not bury them in a fix |

## Composability

- `source-citation-tagging` — pre-tagging makes the audit cheaper; specialists can grep tags and verify each
- `peer-review-lifecycle` (existing) — multi-specialist audit feeds the peer-review v1.0 → v2.0 cycle
- `document-code-review` (existing) — adds 9 mechanical defect dimensions; runs in addition to the multi-specialist audit, not instead
- `gap-analysis-pattern` (existing) — useful for the "what's missing" complement to "what's wrong"

## Lessons Learned

- Five specialists in parallel on a 1500-line proposal doc found 15 HALLUCINATIONs in ~10 minutes wall-clock. A single Reality Checker would have taken longer and missed at least 5 of them (the ones in domains it doesn't specialize in).
- Specialist briefs that say "do NOT verify X (other agent has that)" are critical. Without scope boundaries, two specialists waste tokens on the same claim and miss their actual scope.
- The HALLUCINATION/UNCITED/ASSUMPTION distinction is what makes the report actionable. "Issues found: 23" is useless. "5 HALLUCINATIONs, 8 UNCITED, 10 ASSUMPTIONS" tells you exactly what to fix and in what order.
- Always recommend `surgical / tier-2 / full-rebuild` as the THREE options, then let the user pick. Don't auto-rebuild on a small number of HALLUCINATIONs.
