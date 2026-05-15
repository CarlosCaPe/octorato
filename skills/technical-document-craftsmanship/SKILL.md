---
name: technical-document-craftsmanship
description: "Skill #37 — Technical Document Craftsmanship"
metadata:
  short-description: "Skill #37 — Technical Document Craftsmanship"
  original-index: 37
---

# Skill #37 — Technical Document Craftsmanship

## Category: Process

## Origin

PROJ-100 — Acme Corp Migration Evaluation TDD

## Principle

> **The reader sees the final document, not the git history.**

A technical document must read as a coherent, intentional artifact — not as a series of patches. Every section, term, and framing choice must be deliberate and consistent. If the document says "migrate" in one section and "consolidate" in another, the reader loses trust in the author's precision.

## Why This Matters

- **ARB members, leadership, and cross-team stakeholders** read the document once. They don't see our commits, our iterations, or our corrections.
- **Inconsistent terminology** signals sloppy thinking. If we can't be precise about words, can we be precise about migration cost estimates?
- **Draft vs. final is invisible** — the first version we share IS the final version in the reader's eyes. There are no "first drafts" once the document leaves our hands.

## The Rules

### 1. Terminology Consistency

Pick one term and use it everywhere. If the action is "migrate," never write "consolidate," "move," "transition," or "convert" as synonyms unless each has a distinct, defined meaning in the glossary.

**Example — PROJ-100:**

| Wrong (inconsistent) | Right (consistent) |
|---|---|
| "Can we consolidate?" (§1) + "Can we migrate?" (§2.3.5) | "Can we migrate?" everywhere — because that's the action being evaluated |

### 2. Scope Alignment

Every statement must align with the document's declared scope. If the scope says "Migration Feasibility Study," don't frame questions as "consolidation" — that's a strategic decision above our scope.

| Term | Who Owns It | Our Role |
|---|---|---|
| **Migrate** | Engineering (us) | Evaluate feasibility, cost, risk |
| **Consolidate** | Leadership / ARB | Strategic decision based on our evaluation |

### 3. Section Independence

Each section should be readable in isolation. If someone jumps to §3.5.4 (Concurrency Model), they shouldn't need to read §1 to understand the framing. Don't rely on "we fixed this in a later section" — every section must stand on its own.

### 4. No Visible Iteration Artifacts

- No "UPDATED:" or "FIXED:" markers in the document body
- No "this was previously incorrect" — just write the correct thing
- No change logs inside the document — that's what git is for
- Headers like "The Question We Must Answer" appear exactly once, in the right place

### 5. Glossary as Contract

If a term appears in the document, it must be in the glossary. If it's in the glossary, it must be used consistently. The glossary is not a reference appendix — it's a **contract** with the reader about what words mean.

## Checklist

| # | Check | When |
|---|-------|------|
| 1 | Is every key term used consistently across all sections? | Before sharing |
| 2 | Does each section align with the declared scope? | Before sharing |
| 3 | Can each section be read independently without confusion? | Before sharing |
| 4 | Are there any iteration artifacts visible to the reader? | Before sharing |
| 5 | Is every term in the glossary used consistently in the body? | Before sharing |
| 6 | Would someone reading this for the first time see a coherent document? | Before sharing |

## Anti-Patterns

| Anti-Pattern | Why It's Wrong | Fix |
|---|---|---|
| Using "consolidate" and "migrate" interchangeably | They mean different things and signal different ownership | Pick one; define it in glossary |
| Duplicate headers in different sections | Reader sees two "Questions We Must Answer" and doesn't know which is authoritative | One canonical location per heading |
| Leaving placeholder text from iterations | "TBD — will be updated" in a shared document undermines credibility | Either fill it or remove the section |
| Framing our work beyond our scope | "We recommend consolidation" when our scope is migration feasibility | Stay in lane — evaluate, don't prescribe strategy |

## Relationship to Other Skills

| Skill | Relationship |
|-------|-------------|
| #08 — Deep Grep Code Review | Grep the document for inconsistent terms before sharing |
| #11 — Gap Analysis Pattern | Same [OK]/[--]/[!!] discipline applies to document sections |
| #14 — Research Checklist Discipline | Research the correct terminology before writing |
| #36 — GitHub Copilot Usage Policy | AI-generated text must meet the same craftsmanship standard |

---

*Origin: PROJ-100 — Discovered when "consolidate" and "migrate" were used interchangeably in the Acme Corp TDD. The reader would have seen two different framings of the same question.*
