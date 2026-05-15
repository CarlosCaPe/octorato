---
name: peer-review-lifecycle
description: "Peer Review Lifecycle for Technical Documents"
metadata:
  short-description: "Peer Review Lifecycle for Technical Documents"
  original-index: 47
---

# Peer Review Lifecycle for Technical Documents

## What

A structured protocol for what happens when a technical document enters peer review - covering version control, revision history tracking, reviewer attribution, acceptance criteria for feedback, and the professional workflow from "draft submitted" to "review incorporated, version bumped."

## Why

Peer review is the single highest-value quality gate for long-form technical documents. But without a disciplined lifecycle:

- Feedback gets lost in Slack threads or verbal conversations
- Version numbers stay at 1.0 forever, making it impossible to tell which draft was reviewed
- The same reviewer sees the same issues twice because changes weren't tracked
- There's no audit trail showing what changed, when, and why

A professional document - especially one going to an Architecture Review Board - needs the same change-tracking rigor as production code.

## The Peer Review Lifecycle

```
Draft Complete --> Submit for Review --> Reviewer Reads --> Feedback Received
                                                                  |
                   v2.0 Final <-- Evaluate Each Point <-----------+
```

## Phase 1 - Prepare the Document for Review

Before handing the document to a reviewer:

1. **Run the Code Review pass** (see document-code-review skill) - fix all mechanical defects first
2. **Set the version to X.0** (e.g., 1.0) - this is the "submitted for review" baseline
3. **Ensure the Revision History table exists** - if not, add one

### Revision History Table Format

Place this section after the document metadata (contributors, ticket, date) and before the Table of Contents:

```markdown
## Document Revision History

| Version | Date       | Author(s)        | Change Description                         |
|---------|------------|------------------|---------------------------------------------|
| 1.0     | YYYY-MM-DD | Author Name      | Initial draft - complete evaluation         |
```

**Rules:**
- Version uses semantic format: `Major.Minor` (1.0, 1.1, 2.0)
- Date is ISO 8601: `YYYY-MM-DD`
- Author column lists the person who made the changes, not the reviewer
- Change description is concise but specific - not "updates" but "Incorporated peer review: standardized financial numbers, added residual risks section"

## Phase 2 - Reviewer Evaluates the Document

The reviewer provides feedback as a **numbered list of specific, actionable points**. Each point should:

| Attribute | Good Example | Bad Example |
|-----------|-------------|-------------|
| Specific | "Section 3.6.3 says $1.2M but Executive Summary says $1.3M" | "Numbers seem off" |
| Actionable | "Add a Residual Risks section before the appendices" | "Maybe mention risks?" |
| Located | "In the HA/DR section, paragraph 3" | "Somewhere in the middle" |
| Scoped | "Soften 'Evidence proves...' to 'Evidence indicates...'" | "Tone could be better" |

### The 5-Point Review Pattern

| # | Category | What the Reviewer Checks |
|---|----------|--------------------------|
| 1 | Numerical Consistency | Same dollar amounts, percentages, timelines across all sections |
| 2 | Structural Completeness | Missing sections, orphaned references, gaps in logic flow |
| 3 | Tone & Confidence Calibration | Overclaiming ("100% evidence-based"), hedging language |
| 4 | Guardrails & Caveats | Missing disclaimers, environmental assumptions stated as facts |
| 5 | Risk Visibility | Residual risks, unknowns, and assumptions not called out explicitly |

## Phase 3 - Evaluate and Incorporate Feedback

For each reviewer point, the author must make one of three decisions:

| Decision | When | Action |
|----------|------|--------|
| **Accept** | The point is valid and improves the document | Apply the change |
| **Accept with modification** | The spirit is right but the specific suggestion needs adjustment | Apply a variation |
| **Decline with rationale** | The point conflicts with evidence or scope | Document why in the revision notes |

**Rule:** Never silently ignore a review point. Every point gets a decision.

### Applying Changes

For each accepted point:

1. Make the edit in the document
2. Verify the change doesn't break internal links or TOC entries
3. If the change affects financial numbers, re-run the cross-section consistency check
4. If the change adds a new section, add the corresponding TOC entry

## Phase 4 - Bump Version and Update Revision History

### Version Bump Rules

| Change Scope | Version Bump | Example |
|-------------|--------------|---------|
| Typos, formatting, minor wording | Minor: 1.0 -> 1.1 | Fixed table alignment, corrected date |
| New sections, restructured content, numerical corrections | Major: 1.0 -> 2.0 | Incorporated peer review with 5 structural changes |
| Post-ARB revisions based on board feedback | Major: 2.0 -> 3.0 | Updated verdict based on ARB discussion |

### Update the Revision History

```markdown
| 2.0 | 2026-03-10 | Author | Peer review: standardized financial ranges, corrected prompt count, calibrated confidence language, added environment vs. platform guardrail, added Residual Risks section |
```

**Rule:** The change description should reference the reviewer by name and summarize what categories of changes were made.

### Update the Document Metadata

- **Last Updated** date -> current date
- **Document Contributors** -> add reviewer name if not already listed
- **Version** -> new version number

## Phase 5 - Post-Review Verification

1. Re-run the Document Code Review (document-code-review skill) - especially dimensions 1, 2, 5, and 6
2. Regenerate HTML/PDF output
3. Commit with a descriptive message referencing the review

## Checklist - Peer Review Lifecycle Gate

- [ ] Document version set before submitting for review
- [ ] Revision History table exists in the document
- [ ] All reviewer points evaluated (accept / accept-modified / decline)
- [ ] No review point silently ignored
- [ ] Financial numbers re-verified after changes
- [ ] TOC updated if new sections were added
- [ ] Internal links re-validated after any heading changes
- [ ] Version bumped appropriately (minor vs major)
- [ ] Revision History row added with reviewer name and change summary
- [ ] Document metadata updated (date, contributors)
- [ ] HTML/PDF regenerated from updated source
- [ ] Commit message references the review and lists changes
