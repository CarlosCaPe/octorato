---
name: structural-completeness-verification
description: "Structural Completeness Verification"
metadata:
  short-description: "Structural Completeness Verification"
  original-index: 43
---

# Structural Completeness Verification

## What

A systematic approach to ensuring technical documents have complete structural integrity — no orphan headers, no missing sections, no broken hierarchies, and no promised content that doesn't exist.

## Why

Structural incompleteness manifests as:
- **Orphan headers**: `### 4.3 Analysis` with no content below
- **Missing sections**: TOC promises §5 but document jumps from §4 to §6
- **Broken hierarchy**: `#### 2.1.1` appears under `## 3` (wrong parent)
- **Dangling references**: "See Section 7" when Section 7 doesn't exist
- **Promised deliverables**: "Part Three will contain..." but Part Three is empty

These defects signal incomplete work and erode reader confidence.

## Structural Integrity Rules

| Rule | Description | Violation Example |
|------|-------------|-------------------|
| **Header-content pairing** | Every header has content below it | `### Analysis` followed immediately by `### Results` |
| **Sequential numbering** | Sections numbered without gaps | §1, §2, §4 (missing §3) |
| **Hierarchy consistency** | Child sections under correct parent | `#### 2.1.1` under `## 3` instead of `## 2` |
| **TOC-body alignment** | Every TOC entry exists in body | TOC shows "5. Recommendations" but §5 missing |
| **Promise fulfillment** | Every "will contain" / "see below" delivers | "Details below" with no details |

## How

### Header Hierarchy Extraction

```bash
# Extract all headers with line numbers
grep -n '^#' document.md

# Expected output shows clean hierarchy:
# 10:# Title
# 25:## 1. Introduction
# 45:### 1.1 Background
# 60:### 1.2 Scope
# 80:## 2. Analysis
# ...
```

### Structural Validation Script

```javascript
const fs = require('fs');
const doc = fs.readFileSync('document.md', 'utf8');
const lines = doc.split('\n');

let issues = [];
let lastHeaderLine = -1;
let lastHeaderLevel = 0;
let lastHeaderText = '';

lines.forEach((line, i) => {
  const headerMatch = line.match(/^(#{1,6})\s+(.+)/);
  
  if (headerMatch) {
    const level = headerMatch[1].length;
    const text = headerMatch[2];
    
    // Check for empty section (header immediately followed by header)
    if (lastHeaderLine === i - 1) {
      issues.push(`Line ${lastHeaderLine + 1}: Empty section "${lastHeaderText}"`);
    }
    
    // Check for hierarchy skip (e.g., ## followed by ####)
    if (level > lastHeaderLevel + 1) {
      issues.push(`Line ${i + 1}: Hierarchy skip - "${text}" (level ${level}) under level ${lastHeaderLevel}`);
    }
    
    lastHeaderLine = i;
    lastHeaderLevel = level;
    lastHeaderText = text;
  }
});

// Check if document ends with empty section
if (lastHeaderLine === lines.length - 1 || lastHeaderLine === lines.length - 2) {
  issues.push(`Line ${lastHeaderLine + 1}: Document ends with empty section "${lastHeaderText}"`);
}

issues.forEach(issue => console.log(issue));
console.log(`\nTotal issues: ${issues.length}`);
```

### Section Numbering Audit

```bash
# Extract section numbers
grep -oE '^#{1,4}\s+[0-9]+(\.[0-9]+)*' document.md | \
  sed 's/^#* //' | \
  sort -t. -k1,1n -k2,2n -k3,3n

# Look for:
# - Missing numbers (1, 2, 4 — where's 3?)
# - Duplicate numbers (two §2.3 sections)
# - Out-of-order numbers (3.2 before 3.1)
```

### Promise Tracking

Search for forward references and verify they resolve:

```bash
# Find forward references
grep -n "below\|following\|next section\|will contain\|see §\|Part.*will" document.md

# For each, verify the promised content exists
```

## Structural Completeness Checklist

```markdown
## Before Publishing: Structure Audit

### Header Integrity
- [ ] No empty sections (header with no content)
- [ ] No orphan headers (### without parent ##)
- [ ] Consistent numbering scheme throughout
- [ ] No duplicate section numbers

### TOC Alignment (if TOC exists)
- [ ] Every TOC entry has matching section
- [ ] Every major section appears in TOC
- [ ] TOC page numbers / links are accurate

### Promise Fulfillment
- [ ] Every "see below" has content below
- [ ] Every "Part X will contain" has content in Part X
- [ ] Every "to be completed" is either complete or explicitly marked ⏳

### Reference Resolution
- [ ] Every §X.Y reference points to existing section
- [ ] Every "Appendix X" reference has matching appendix
- [ ] Every "Table N" reference has matching table
```

## Common Structural Failures

| Failure | Cause | Prevention |
|---------|-------|------------|
| Empty sections | Outline created, content never added | Write content immediately after header |
| Missing sections | Content deleted, header orphaned | Delete header with content |
| Number gaps | Section removed, others not renumbered | Renumber after deletions |
| Hierarchy breaks | Copy-paste from different document | Adjust header levels after paste |
| Promise decay | "Will add later" → forgotten | Track promises, resolve before publish |

## When to Use

- **After outlining**: Verify skeleton is valid before adding content
- **After major edits**: Structural changes cascade
- **Before publishing**: Full structural audit
- **After merging**: Combined documents may have structural conflicts

## Real-World Example

From the Acme Corp TDD:

**Structural challenge:** Inserting new §6 (366 lines) between existing §5 and Part Two.

**Verification performed:**
1. New §6 has proper hierarchy: `### 6` → `#### 6.1` → `##### 6.1.1`
2. No empty sections — every header has content
3. Part Two remained "Part Two" (not renumbered to "Part Three")
4. Charter Traceability table references §6.1–§6.6 all resolve

**Result:** Script confirmed all 8 deliverable rows showed valid section references, no orphan headers in new content.

## Related Skills

- `38_document_semantic_coherence.md` — Structure is a coherence dimension
- `39_cross_reference_integrity.md` — References depend on structure
- `11_gap_analysis_pattern.md` — Find what's missing
