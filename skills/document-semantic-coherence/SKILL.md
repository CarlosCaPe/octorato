---
name: document-semantic-coherence
description: "Document Semantic Coherence"
metadata:
  short-description: "Document Semantic Coherence"
  original-index: 38
---

# Document Semantic Coherence

## What

A discipline for ensuring technical documents maintain internal logical consistency, structural integrity, and semantic alignment throughout their lifecycle. This skill addresses the **hidden complexity** of long documents where contradictions, orphaned references, and structural decay accumulate invisibly.

## Why

Long technical documents (1,000+ lines) are prone to **semantic drift** — incremental edits that introduce contradictions, orphan references, duplicate content, or broken narrative flow. These defects erode reader trust and can lead to incorrect decisions based on conflicting information within the same document.

Common failure modes:
- **Contradictions**: Section A says "confirmed" while Section B says "pending investigation"
- **Orphaned references**: "See §4.3" when §4.3 was removed or renumbered
- **Duplicate paragraphs**: Same content copy-pasted in multiple locations
- **Lost paragraphs**: Content intended for a section ends up in wrong location
- **Stale markers**: ⏳ TBD markers that were never resolved, crossed-out text never removed
- **Cadence breaks**: Tense shifts, tone changes, or formality inconsistencies mid-document

## The Seven Coherence Dimensions

| # | Dimension | Definition | Detection Method |
|---|-----------|------------|------------------|
| 1 | **Logical Consistency** | No statement contradicts another statement | Search for antonym pairs near same topic keywords |
| 2 | **Reference Integrity** | All cross-references resolve to valid targets | Grep all `§`, `#`, `line`, `Finding`, `Evidence` patterns |
| 3 | **Status Alignment** | Status markers (✅⚠️🔴⏳) match the content they describe | Audit each marker against its surrounding context |
| 4 | **Structural Completeness** | Every promised section exists; no orphan headers | Walk heading hierarchy, verify all TOC entries |
| 5 | **Temporal Consistency** | Dates, timelines, and sequences don't contradict | Extract all dates, verify chronological plausibility |
| 6 | **Voice Uniformity** | Consistent tense, person, and formality level | Spot-check random paragraphs for stylistic drift |
| 7 | **Deduplication** | No content repeated verbatim in multiple locations | Hash paragraph fingerprints, flag duplicates |

## How

### Pre-Edit Coherence Check

Before making significant edits to a long document:

```markdown
1. Identify all sections that reference the content you're changing
2. Note the current status markers (✅⚠️🔴⏳) in affected areas
3. List all cross-references (§, Finding #, Evidence #) pointing to/from the area
4. Check if the content appears elsewhere (search key phrases)
```

### Post-Edit Coherence Verification

After completing edits, run a systematic sweep:

```markdown
## Coherence Checklist

### 1. Contradiction Scan
- [ ] Search for "NOT" / "ZERO" / "confirmed" near edited topics
- [ ] Verify no section now contradicts the changes made
- [ ] Check that summary/conclusion sections align with detail sections

### 2. Reference Integrity
- [ ] All §X.Y references point to existing sections
- [ ] All "Finding #N" references exist in the findings register
- [ ] All "Evidence #N" references exist in the evidence register
- [ ] All line number references (if any) are still valid

### 3. Status Marker Audit
- [ ] No ⏳ TBD where content is now complete
- [ ] No ✅ where content is actually pending
- [ ] No ⚠️ where issue is fully resolved
- [ ] No 🔴 where blocker is removed

### 4. Stale Content Removal
- [ ] No strikethrough (~~) text left in final document
- [ ] No "PENDING DISCOVERY" or similar placeholder text
- [ ] No "deferred to Phase X" where Phase X is now complete
- [ ] No duplicate paragraphs from copy-paste errors

### 5. Structural Integrity
- [ ] All sections in TOC exist in document
- [ ] All major sections have content (no empty headers)
- [ ] Heading hierarchy is consistent (no orphan ### under #)
- [ ] Section numbering is sequential (no gaps)
```

### Automated Detection Patterns

```bash
# Find potential contradictions (antonym patterns)
grep -n "NOT\|ZERO\|confirmed\|complete\|pending\|TBD" doc.md | sort

# Find orphan cross-references
grep -oE '§[0-9]+\.[0-9]+' doc.md | sort | uniq -c | sort -rn

# Find status markers
grep -n "✅\|⚠️\|🔴\|⏳" doc.md

# Find stale markers
grep -n "~~\|PENDING\|TBD\|deferred" doc.md

# Find duplicate content (paragraph hash)
awk 'NF>5 {print NR": "$0}' doc.md | sort -t: -k2 | uniq -d -f1
```

## When to Use

- **Always** after adding >50 lines to a document
- **Always** after merging content from multiple sources
- **Always** before publishing or presenting a document
- **Always** when document has been edited by multiple contributors
- **Critical** for documents that drive decisions (TDDs, RFCs, ADRs)

## Anti-Patterns

| Anti-Pattern | Problem | Solution |
|--------------|---------|----------|
| Edit-and-forget | Change one section, forget to update referencing sections | Use checklist systematically |
| Copy-paste accumulation | Same paragraph appears in 3 places with slight variations | Single source of truth + references |
| Status marker decay | ✅ added when started, never updated when blocked | Audit markers on every edit |
| Reference rot | §4.3 becomes §4.4 after insertion, old refs broken | Search-and-replace all refs after structural changes |
| Revision cruft | ~~old text~~ and "UPDATED:" annotations pile up | Clean document after each revision cycle |

## Real-World Example

From the Acme Corp Migration Evaluation TDD session:

**Problem Found:** §2.4.2 said "🔴 Critical Extrapolation — NOW REPLACED BY ACTUAL DATA" but still contained the old extrapolated content below the label.

**Detection Method:** Contradiction scan — "REPLACED" claims removal, but content still present.

**Resolution:** Removed the entire outdated extrapolation block, kept only the factual content.

**Lesson:** Labels claiming removal don't remove content — verify the actual document state.

## Related Skills

- `14_research_checklist_discipline.md` — Systematic verification before claiming completion
- `37_technical_document_craftsmanship.md` — Overall document quality standards
- `39_cross_reference_integrity.md` — Deep dive on reference management
