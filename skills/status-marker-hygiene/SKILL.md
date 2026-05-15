---
name: status-marker-hygiene
description: "Status Marker Hygiene"
metadata:
  short-description: "Status Marker Hygiene"
  original-index: 40
---

# Status Marker Hygiene

## What

A discipline for maintaining accurate status indicators (✅⚠️🔴⏳) throughout a document's lifecycle, ensuring markers always reflect the actual state of their associated content.

## Why

Status markers are **visual contracts with readers**. When a reader sees ✅, they trust that item is complete. When markers lie:

- ✅ on incomplete items → false confidence → missed work
- ⏳ on completed items → unnecessary rework → wasted effort
- ⚠️ on resolved issues → alarm fatigue → real warnings ignored
- 🔴 on cleared blockers → decision paralysis → delays

Status marker decay is insidious because the marker itself looks authoritative while the underlying reality has changed.

## Status Marker Semantics

| Marker | Meaning | Lifecycle |
|--------|---------|-----------|
| ⏳ | Pending / In Progress / TBD | Initial state → resolves to ✅ or 🔴 |
| ⚠️ | Warning / Partial / Needs Attention | Risk flag → resolves to ✅ or 🔴 |
| 🔴 | Blocker / Critical / Failed | Escalation state → resolves to ✅ or remains |
| ✅ | Complete / Confirmed / Passed | Terminal state (should not regress) |

**State transitions:**

```
⏳ TBD ──────┬──→ ✅ Complete
             │
             └──→ ⚠️ Partial ──┬──→ ✅ Resolved
                               │
                               └──→ 🔴 Blocked ──→ ✅ Cleared
```

## How

### Marker Placement Rules

1. **One marker per claim**: Don't stack ✅⚠️ — pick the dominant state
2. **Marker near content**: Place marker within 2 lines of what it describes
3. **Consistent position**: Either leading (✅ Item) or trailing (Item ✅)
4. **Scope clarity**: Make clear if marker covers one item or a group

### Marker Audit Protocol

After any document edit, audit markers in the affected area:

```markdown
## Marker Audit Checklist

For each ✅ in edited area:
- [ ] Is the content actually complete?
- [ ] Are there any remaining "TBD" or "pending" phrases?
- [ ] Do referenced items (§, Finding #) also show ✅?

For each ⏳ in edited area:
- [ ] Is work still genuinely pending?
- [ ] Has the item been completed elsewhere?
- [ ] Should this be promoted to ✅ or escalated to ⚠️?

For each ⚠️ in edited area:
- [ ] Is the warning still valid?
- [ ] Has the issue been resolved?
- [ ] Should this be promoted to ✅ or escalated to 🔴?

For each 🔴 in edited area:
- [ ] Is the blocker still active?
- [ ] Has a workaround been implemented?
- [ ] Should this be demoted to ⚠️ or cleared to ✅?
```

### Bulk Marker Verification

```bash
# Count markers by type
grep -c '✅' document.md && echo "checkmarks"
grep -c '⚠️' document.md && echo "warnings"  
grep -c '🔴' document.md && echo "blockers"
grep -c '⏳' document.md && echo "pending"

# Find ✅ near TBD (contradiction)
grep -n '✅' document.md | while read line; do
  linenum=$(echo $line | cut -d: -f1)
  sed -n "$((linenum-2)),$((linenum+2))p" document.md | grep -q "TBD\|pending\|⏳" && echo "Contradiction at line $linenum"
done
```

### Table Row Status Updates

When updating status tables, follow this pattern:

```markdown
# WRONG: Update marker without updating text
| Task | Status |
| Do the thing | ✅ | ← marker updated
| But the thing isn't done | | ← text still says "isn't done"

# RIGHT: Update marker AND text together
| Task | Status |
| Do the thing | ✅ Complete — verified in testing |
```

## Common Marker Contradictions

| Pattern | Problem | Resolution |
|---------|---------|------------|
| `✅ TBD` | Checkmark on pending item | Remove TBD or change to ⏳ |
| `⚠️ Resolved` | Warning on resolved item | Change to ✅ Resolved |
| `🔴 No longer blocking` | Blocker that isn't blocking | Change to ✅ Cleared or remove |
| `⏳ Complete` | Pending marker on done item | Change to ✅ Complete |
| `✅ deferred to Phase 4` | Complete marker on deferred item | Change to ⏳ or remove deferral |

## When to Use

- **Every edit**: Quick scan of markers in changed area
- **Before publishing**: Full document marker audit
- **After merges**: Markers from different branches may conflict
- **Status meetings**: Verify document markers match verbal updates

## Anti-Patterns

| Anti-Pattern | Problem | Solution |
|--------------|---------|----------|
| Optimistic checkmarks | Mark ✅ when "almost done" | Only ✅ when verifiably complete |
| Warning accumulation | ⚠️ pile up, never resolved | Schedule warning triage |
| Blocker inflation | Everything is 🔴 | Reserve 🔴 for true blockers |
| Marker-free documents | No visual status at all | Add markers to key sections |
| Stale marker inheritance | Copy section, forget to update markers | Reset markers in copied content |

## Real-World Example

From the Acme Corp TDD session:

**Problem:** Charter Traceability table had 6 rows with ⚠️ "deferred to Phase 4" but the content for those deliverables was being written in that same session.

**Detection:** User asked "podemos poner todo esto en verde?" — visual audit revealed the disconnect.

**Resolution:** 
1. Drafted all 6 deliverable sections (§6.1–§6.6)
2. Updated each row: ⚠️ → ✅ with new section references
3. Updated summary note to reflect "all 8 deliverables addressed"

**Verification:** Node.js script confirmed all 8 rows showed [GREEN] status.

## Marker Style Guide

For consistency across documents:

```markdown
## Preferred Formats

✅ **Complete** — task finished, verified
⚠️ **Partial** — some work done, gaps remain  
🔴 **Blocked** — cannot proceed until X resolved
⏳ **Pending** — work not yet started

## Avoid

✔️ (different checkmark, inconsistent)
❌ (ambiguous: failed? removed? not applicable?)
⚠️ (color-only, no semantic meaning)
[x] (markdown checkbox, different rendering)
```

## Related Skills

- `38_document_semantic_coherence.md` — Overall coherence including markers
- `39_cross_reference_integrity.md` — References that markers often accompany
- `14_research_checklist_discipline.md` — Don't claim ✅ without verification
