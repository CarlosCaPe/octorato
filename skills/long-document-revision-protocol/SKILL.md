---
name: long-document-revision-protocol
description: "Long Document Revision Protocol"
metadata:
  short-description: "Long Document Revision Protocol"
  original-index: 44
---

# Long Document Revision Protocol

## What

A comprehensive checklist and workflow for revising technical documents exceeding 1,000 lines, integrating all document quality skills into a single actionable process.

## Why

Long documents (1,000+ lines) have unique failure modes:
- **Invisible drift**: Changes in one section contradict another section 500 lines away
- **Reference rot**: Cross-references break as structure evolves
- **Status decay**: Markers become stale as content changes
- **Voice fragmentation**: Different sections read like different authors
- **Structural erosion**: Hierarchy breaks down over multiple edit sessions

No single skill addresses all these risks. This protocol orchestrates all document quality skills into a coherent revision workflow.

## The Protocol

### Phase 1: Pre-Revision Assessment (5 minutes)

Before making changes, understand the document state:

```markdown
## Pre-Revision Checklist

1. Document Statistics
   - [ ] Total line count: ___
   - [ ] Number of sections (## headers): ___
   - [ ] Number of cross-references (§, Finding #, Evidence #): ___
   - [ ] Number of status markers (✅⚠️🔴⏳): ___

2. Change Impact Assessment
   - [ ] Which sections will I modify?
   - [ ] Which sections reference those sections?
   - [ ] Are there status markers in affected areas?
   - [ ] Will structure (section numbers) change?

3. Backup
   - [ ] Git commit before changes? (recommended)
   - [ ] Or: copy to _backup.md
```

### Phase 2: Make Changes

Apply your edits with awareness:

```markdown
## During Editing

- [ ] For each fact added: Is this fact stated elsewhere? (→ reference, don't duplicate)
- [ ] For each status change: Update the marker (✅⚠️🔴⏳)
- [ ] For each structural change: Note affected cross-references
- [ ] For each new section: Match voice/tense of surrounding content
```

### Phase 3: Post-Revision Verification (10-15 minutes)

After completing edits, run the full coherence suite:

```markdown
## Post-Revision Audit

### 3.1 Semantic Coherence (Skill #38)
- [ ] No contradictions between edited and unedited sections
- [ ] Summary sections align with detail sections
- [ ] Conclusions still supported by evidence

### 3.2 Cross-Reference Integrity (Skill #39)
- [ ] All §X.Y references resolve to existing sections
- [ ] All Finding #N references exist in findings register
- [ ] All Evidence #N references exist in evidence register
- [ ] No orphan references from deleted content

### 3.3 Status Marker Hygiene (Skill #40)
- [ ] No ✅ on incomplete items
- [ ] No ⏳ on completed items
- [ ] No ⚠️ on resolved issues
- [ ] No stale "TBD" or "pending" text near ✅ markers

### 3.4 Content Deduplication (Skill #41)
- [ ] No verbatim paragraphs in multiple locations
- [ ] Key facts have single authoritative source
- [ ] Other occurrences reference the source

### 3.5 Voice Consistency (Skill #42)
- [ ] Tense consistent (present for facts, future for plans)
- [ ] Person consistent (we/MVH/passive)
- [ ] Tone consistent (formal-neutral throughout)
- [ ] No jarring style shifts at edit boundaries

### 3.6 Structural Completeness (Skill #43)
- [ ] No empty sections (header without content)
- [ ] No orphan headers (### without parent ##)
- [ ] Section numbering sequential
- [ ] All promised content delivered
```

### Phase 4: Final Validation

Quick automated checks:

```bash
# Status marker count
echo "✅: $(grep -c '✅' doc.md)"
echo "⚠️: $(grep -c '⚠️' doc.md)"
echo "🔴: $(grep -c '🔴' doc.md)"
echo "⏳: $(grep -c '⏳' doc.md)"

# Stale marker search
grep -n "TBD\|PENDING\|deferred\|~~" doc.md

# Reference inventory
grep -oE '§[0-9.]+' doc.md | sort | uniq -c | sort -rn | head -20

# Empty section detection
grep -n '^##' doc.md | while read line; do
  linenum=$(echo $line | cut -d: -f1)
  nextline=$((linenum + 1))
  sed -n "${nextline}p" doc.md | grep -q '^#' && echo "Empty section at line $linenum"
done
```

## Quick Reference Card

For routine edits, use this abbreviated checklist:

```
□ Contradictions? (search antonyms near edit)
□ References valid? (§, Finding #, Evidence #)
□ Markers accurate? (✅⚠️🔴⏳)
□ Duplicates? (search key phrases)
□ Voice match? (tense, person, tone)
□ Structure intact? (headers have content)
```

## When to Use Full Protocol

| Situation | Protocol Level |
|-----------|---------------|
| Fix a typo | None needed |
| Update a number | Quick reference card |
| Add a paragraph | Quick reference card |
| Add a section | Phases 2-4 |
| Merge documents | Full protocol |
| Major restructure | Full protocol |
| Pre-publish review | Full protocol |

## Integration with Git Workflow

```bash
# Before major revision
git add -A && git commit -m "checkpoint before revision"

# After revision passes protocol
git add -A && git commit -m "revision complete - coherence verified"

# If issues found
git diff  # see what changed
git checkout -- document.md  # revert if needed
```

## Real-World Example

From the Acme Corp TDD revision session:

**Revision scope:** Add 366 lines (§6 Charter Deliverables) + update 7 table rows

**Protocol execution:**
1. **Pre-revision**: 2,701 lines, 55 findings, 8 deliverables with 6 at ⚠️
2. **Changes**: Inserted §6.1–§6.6, updated Charter Traceability table
3. **Post-revision**:
   - Coherence: New sections reference existing findings (no contradictions)
   - References: §6.1–§6.6 all resolve, Finding #refs valid
   - Markers: All 8 rows now ✅, closing note updated
   - Deduplication: Key facts reference §2.5.2, §3.2 (not duplicated)
   - Voice: Matched existing formal-neutral, evidence-backed style
   - Structure: §6 hierarchy clean, no empty sections
4. **Validation**: Node.js script confirmed 8 GREEN rows, 0 stale markers

**Result:** 3,067 lines, fully coherent, all deliverables addressed.

## Related Skills

- `38_document_semantic_coherence.md` — Contradiction prevention
- `39_cross_reference_integrity.md` — Reference management
- `40_status_marker_hygiene.md` — Marker accuracy
- `41_content_deduplication_discipline.md` — Single source of truth
- `42_voice_and_cadence_consistency.md` — Writing style
- `43_structural_completeness_verification.md` — Document structure
