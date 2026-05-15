---
name: content-deduplication-discipline
description: "Content Deduplication Discipline"
metadata:
  short-description: "Content Deduplication Discipline"
  original-index: 41
---

# Content Deduplication Discipline

## What

A practice for preventing and eliminating duplicate content within technical documents, ensuring each fact has exactly one authoritative location with references pointing to it rather than copies of it.

## Why

Duplicate content creates **maintenance nightmares**:

- Update one copy, forget the others → contradictions
- Reader finds conflicting versions → trust erosion
- Document bloat → harder to navigate
- Search results polluted → wrong instance edited

The **Single Source of Truth (SSOT)** principle applies to documents just as it does to databases: each fact should live in exactly one place.

## Duplication Patterns

| Pattern | Description | Risk Level |
|---------|-------------|------------|
| **Verbatim copy** | Exact same paragraph in 2+ places | 🔴 HIGH — guaranteed to diverge |
| **Paraphrase copy** | Same information, different words | ⚠️ MEDIUM — subtle contradictions |
| **Summary + detail** | Executive summary repeats detail section | ✅ LOW if summary clearly references source |
| **Table + prose** | Same data in table and paragraph form | ⚠️ MEDIUM — update one, forget other |
| **Cross-document** | Same content in multiple files | 🔴 HIGH — no linking mechanism |

## How

### Prevention: Write Once, Reference Elsewhere

```markdown
# WRONG: Duplicate the data
## Section 2.5
There are 1,727 SPs across 22 databases.

## Section 6.4
The 1,727 stored procedures across 22 databases require...

## Executive Summary  
With 1,727 SPs spread across 22 databases...

# RIGHT: Single source with references
## Section 2.5.2 SP Inventory
**Total: 1,727 SPs across 22 databases** (see table below)

## Section 6.4
The SP inventory (§2.5.2: 1,727 SPs across 22 databases) requires...

## Executive Summary
The SP inventory (§2.5.2) drives the migration complexity...
```

### Detection: Find Duplicates

**Paragraph fingerprinting:**

```javascript
const fs = require('fs');
const crypto = require('crypto');

const doc = fs.readFileSync('document.md', 'utf8');
const paragraphs = doc.split(/\n\n+/).filter(p => p.trim().length > 50);

const hashes = {};
paragraphs.forEach((p, i) => {
  // Normalize: lowercase, collapse whitespace, remove punctuation
  const normalized = p.toLowerCase().replace(/\s+/g, ' ').replace(/[^\w\s]/g, '');
  const hash = crypto.createHash('md5').update(normalized).digest('hex').slice(0, 8);
  
  if (hashes[hash]) {
    console.log(`Duplicate found: "${p.slice(0, 60)}..."`);
    console.log(`  First occurrence: paragraph ${hashes[hash]}`);
    console.log(`  This occurrence: paragraph ${i + 1}`);
  } else {
    hashes[hash] = i + 1;
  }
});
```

**Grep for key phrases:**

```bash
# Find repeated key facts
grep -n "1,727 SPs" document.md
grep -n "272 vCores" document.md
grep -n "\$56.5K" document.md

# If count > 1, evaluate: reference or duplicate?
```

### Resolution: Consolidate Duplicates

When duplicates are found:

1. **Identify the authoritative location** — usually the most detailed occurrence
2. **Keep that version** — ensure it's complete and accurate
3. **Replace other occurrences** with references:
   - Full reference: "As documented in §2.5.2, there are 1,727 SPs..."
   - Inline reference: "the SP inventory (§2.5.2)"
   - Parenthetical: "1,727 SPs (§2.5.2)"

### Acceptable Duplication

Some duplication is intentional and acceptable:

| Scenario | Why Acceptable | Safeguard |
|----------|----------------|-----------|
| Executive Summary | Readers may only read summary | Note "Details in §X.Y" |
| Table of Contents | Navigation aid | Auto-generate if possible |
| Glossary definitions | Quick reference | Mark as "canonical definition" |
| Repeated warnings | Safety-critical info | Use consistent boilerplate |

## Deduplication Checklist

```markdown
## Before Publishing: Deduplication Audit

### Key Facts Inventory
List facts that appear in multiple locations:

| Fact | Authoritative Location | Other Occurrences | Action |
|------|----------------------|-------------------|--------|
| SP count: 1,727 | §2.5.2 | §6.4, Exec Summary | Verify refs |
| vCore count: 272 | §2.6.1.9 | §3.2, §6.1 | Verify refs |
| Cost: $56.5K/mo | §2.6.1.9 | Exec Summary | Verify refs |

### Search for Common Duplications
- [ ] Numbers with units ($, GB, K, M)
- [ ] Proper nouns (product names, tech names)
- [ ] Conclusions ("technically feasible", "not recommended")
- [ ] Status claims ("confirmed", "complete", "pending")
```

## When to Use

- **During writing**: Before repeating a fact, check if it exists elsewhere
- **After merging content**: Merged documents often duplicate
- **Before publishing**: Full deduplication audit
- **When document exceeds 1,000 lines**: Duplication becomes invisible

## Anti-Patterns

| Anti-Pattern | Problem | Solution |
|--------------|---------|----------|
| Copy-paste writing | Fastest way to duplicate | Reference instead of copy |
| "Just in case" repetition | "Readers might miss it" | Trust your structure + TOC |
| Template bloat | Same boilerplate in every section | Extract to shared reference |
| Version accumulation | "Old version" kept alongside new | Delete old, keep only current |
| Multi-author overlap | Two people write same section | Coordinate ownership |

## Real-World Example

From the Acme Corp TDD:

**Observation:** The SP count "1,727" appears 20+ times throughout the document.

**Assessment:**
- §2.5.2 is the authoritative source (full table with per-database breakdown)
- Executive Summary references "1,727 SPs" with context
- §6.4 Roadmap references "1,727" when calculating wave sizes
- §3.2 Cost Framework uses "1,727" in effort calculation

**Verdict:** Acceptable duplication — each occurrence either:
- References the source (§2.5.2)
- Uses the number in a calculation specific to that section
- Is in Executive Summary (intentional standalone)

**Key insight:** The number itself isn't the problem; uncontrolled divergence is. "1,727 SPs" is safe because it won't change. "⚠️ Partially covered" duplicated in 6 table rows was a problem because each needed individual updates.

## Related Skills

- `38_document_semantic_coherence.md` — Coherence includes deduplication
- `39_cross_reference_integrity.md` — References replace duplicates
- `04_idempotent_sql_design.md` — Same principle: single source of truth
