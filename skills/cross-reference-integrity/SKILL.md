---
name: cross-reference-integrity
description: "Cross-Reference Integrity"
metadata:
  short-description: "Cross-Reference Integrity"
  original-index: 39
---

# Cross-Reference Integrity

## What

A systematic approach to managing internal document references (section numbers, finding numbers, evidence numbers, line numbers) that prevents reference rot and orphan links as documents evolve.

## Why

Cross-references are the **hyperlinks of technical documents**. When they break:
- Readers lose trust in the document's accuracy
- Critical connections between evidence and conclusions become invisible
- Reviewers waste time hunting for referenced content
- Wrong decisions get made based on mislinked data

Reference rot accelerates as documents grow. A 500-line document might have 20 cross-references. A 3,000-line document might have 200+. Manual tracking becomes impossible.

## Reference Types and Vulnerabilities

| Reference Type | Pattern | Vulnerability | Example |
|----------------|---------|---------------|---------|
| Section reference | `§X.Y`, `Section X.Y` | Breaks when sections renumbered | "See §2.4.2 for details" |
| Finding reference | `Finding #N`, `#N` | Breaks when findings reordered | "Confirmed by Finding #35" |
| Evidence reference | `Evidence #N` | Breaks when evidence list changes | "Source: Evidence #12" |
| Line reference | `line N`, `lines N-M` | Breaks on any edit above that line | "See line 450" |
| Named anchor | `Appendix A Q7` | Stable if naming consistent | "Answered in Appendix A Q7" |

**Stability ranking** (most to least stable):
1. Named anchors (survive most edits)
2. Finding/Evidence numbers (survive structural changes)
3. Section numbers (break on outline changes)
4. Line numbers (break on any edit)

## How

### Reference Inventory

Before major edits, inventory all references:

```bash
# Extract all section references
grep -oE '§[0-9]+(\.[0-9]+)*' document.md | sort | uniq -c

# Extract all finding references  
grep -oE 'Finding #[0-9]+|#[0-9]+' document.md | sort | uniq -c

# Extract all evidence references
grep -oE 'Evidence #[0-9]+' document.md | sort | uniq -c

# Extract potential line references
grep -oE 'line[s]? [0-9]+' document.md
```

### Validation Matrix

Create a validation matrix for critical documents:

```markdown
| Reference | Target Exists? | Target Content Matches? | Used In |
|-----------|----------------|------------------------|---------|
| §2.5.2 | ✅ | ✅ SP inventory table | §6.4, Exec Summary |
| Finding #35 | ✅ | ✅ Hospital pipeline failures | §6.3, Charter row 5 |
| Evidence #12 | ✅ | ✅ Lincoln's charter PDF | Charter Traceability |
```

### Structural Change Protocol

When renumbering sections or reordering content:

1. **Before change**: Export all references to a temp file
2. **Make change**: Perform the structural modification
3. **After change**: Search-and-replace all affected references
4. **Verify**: Re-run reference inventory, compare to original

```bash
# Example: Section 2.4 becomes 2.5
sed -i 's/§2\.4/§2.5/g; s/§2\.5/§2.6/g; s/§2\.6/§2.7/g' document.md
# WARNING: Order matters! Work backwards to avoid collisions
```

### Bidirectional Reference Tracking

For critical references, track both directions:

```markdown
## §6.4 Domain Migration Roadmap

**Referenced by:** Charter Traceability row 6, Executive Summary, §3.6.3
**References:** §2.5.2 (SP counts), §3.1 (criteria matrix), §3.4 (risk), Finding #28 (cross-DB)
```

This makes it visible which sections need updating when either end changes.

## Reference Patterns by Document Type

| Document Type | Primary Reference Style | Rationale |
|---------------|------------------------|-----------|
| TDD / RFC | Section numbers + Finding numbers | Formal structure, evidence-backed |
| Runbook | Named anchors + step numbers | Execution sequence matters |
| API Docs | Named anchors + code refs | Stability across versions |
| Audit Report | Finding numbers + Evidence numbers | Traceability chain critical |

## When to Use

- **Always** when document exceeds 500 lines
- **Always** when document has >20 cross-references
- **Always** before finalizing a decision document
- **Always** after merging branches that touch same document
- **Critical** when references link evidence to conclusions

## Anti-Patterns

| Anti-Pattern | Problem | Solution |
|--------------|---------|----------|
| Line number references | Break on any edit | Use section/finding numbers instead |
| Implicit references | "See above" — where exactly? | Use explicit section numbers |
| Stale reference comments | `// See §4.2 (MOVED TO §5.1)` | Update the reference, remove comment |
| Reference-free claims | "As confirmed earlier..." — where? | Add explicit Finding # or § reference |
| Copy-paste references | Same §2.4.2 appears 15 times, section renamed | Search-replace systematically |

## Automation Helpers

### Node.js Reference Validator

```javascript
const fs = require('fs');
const doc = fs.readFileSync('document.md', 'utf8');

// Extract all section references
const sectionRefs = doc.match(/§\d+(\.\d+)*/g) || [];

// Extract all section headers
const sectionHeaders = doc.match(/^#{1,6}\s+\d+(\.\d+)*\s/gm) || [];
const definedSections = sectionHeaders.map(h => h.match(/\d+(\.\d+)*/)[0]);

// Find orphan references
const orphans = sectionRefs.filter(ref => {
  const num = ref.replace('§', '');
  return !definedSections.some(s => s.startsWith(num));
});

console.log('Potentially orphaned references:', [...new Set(orphans)]);
```

### Grep-Based Quick Check

```bash
# Find all unique section references
grep -oE '§[0-9.]+' doc.md | sort -u > refs.txt

# Find all section headers
grep -oE '^#{1,4} [0-9.]+' doc.md | sed 's/^#* /§/' | sort -u > headers.txt

# Show references without matching headers
comm -23 refs.txt headers.txt
```

## Real-World Example

From the Acme Corp TDD session:

**Scenario:** Added new §6 Charter Deliverables section (366 lines) between existing content.

**Reference Impact:**
- Charter Traceability table needed 7 references updated (§6.1–§6.6)
- Closing note needed update to mention "all 8 deliverables"
- No section renumbering required (§6 was empty, Part Two remained Part Two)

**Verification:** Node.js script checked all 8 traceability rows showed ✅ with valid §6.x references.

## Related Skills

- `38_document_semantic_coherence.md` — Overall coherence discipline
- `14_research_checklist_discipline.md` — Verification before claiming done
- `11_gap_analysis_pattern.md` — Finding what's missing before acting
