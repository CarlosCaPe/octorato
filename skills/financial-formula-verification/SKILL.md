---
name: financial-formula-verification
description: "Financial Formula Verification for Cloud Cost Documents"
metadata:
  short-description: "Financial Formula Verification for Cloud Cost Documents"
  original-index: 49
---

# Financial Formula Verification for Cloud Cost Documents

## What

A mechanical verification process for financial calculations in cloud migration
documents, cost analyses, and technology evaluations. Treats every dollar figure
as a testable assertion that must be independently re-derived from its inputs.

## Why

Financial discrepancies in technical documents destroy credibility with leadership
and finance teams. A single wrong number in an executive summary casts doubt on
every other number in the document. These errors are common because:

- Authors copy formulas from one section and update some but not all references
- Cloud pricing changes or the wrong tier's pricing is used
- "Used" vs "provisioned" storage creates different totals
- Discount percentages (AHB, Reserved Instances, etc.) are estimated instead of verified

## Verification Protocol

### Step 1 - Extract All Financial Assertions

Grep every dollar amount, percentage, and timeline from the document:

```bash
# All dollar amounts
grep -oP '\$[\d,.]+[KMB]?\b' document.md | sort | uniq -c | sort -rn

# All percentage values
grep -oP '\d+(\.\d+)?%' document.md | sort | uniq -c | sort -rn

# Break-even or timeline references
grep -oiP '\d+(\.\d+)?\s*(year|month|yr|mo)\b' document.md | sort -u
```

### Step 2 - Identify the Canonical Source

Every financial figure should trace back to ONE authoritative calculation.
Find that calculation (usually in a "Cost Methodology" or "Financial Summary" section)
and treat it as the source of truth.

**The document should have a single section where:**
- Unit costs are stated with source links
- Quantities are stated with evidence references
- Arithmetic is shown: unit * quantity = result

### Step 3 - Re-derive Every Total

For each stated total, independently multiply:

| Verify | How |
|--------|-----|
| Compute cost | vCores * $/vCore/month = stated total |
| Storage cost | TB * 1024 * $/GB/month = stated total |
| Backup cost | TB * $/GB/month = stated total |
| Grand total | Sum of components = stated total |
| AHB/discount | Compute * (1 - discount%) = stated discounted total |
| Annual savings | (Platform A - Platform B) * 12 = stated annual savings |
| Break-even | Migration cost / annual savings = stated timeline |

### Step 4 - Verify Unit Costs Against Official Sources

| Cloud Provider | Where to Verify |
|---------------|-----------------|
| Azure SQL MI | https://azure.microsoft.com/en-us/pricing/details/azure-sql-managed-instance/single/ |
| Azure PG Flex | https://azure.microsoft.com/en-us/pricing/details/postgresql/flexible-server/ |
| Azure Hybrid Benefit | https://learn.microsoft.com/en-us/azure/azure-sql/azure-hybrid-benefit |
| Azure Storage | Pricing page for the specific service (MI storage, PG storage, backup) |

**Common pricing traps:**
- General Purpose vs Business Critical tier (very different $/vCore)
- Per-4-vCore pricing that must be divided by 4 for per-vCore rate
- Storage: used vs provisioned (billing is on provisioned, not used)
- AHB: actual discount is ~30-33%, not 55-60% (common misconception)
- Backup pricing differs from data storage pricing

### Step 5 - Cross-Section Consistency Check

The same financial metric must show the same value in every section where it appears.
Common locations to cross-check:

| Section | What to Check |
|---------|--------------|
| Executive Summary / "The Question" | List price, AHB price, annual savings range |
| Financial Summary table | All cost components, totals, savings |
| Cost Calculation Methodology | Detailed arithmetic per component |
| Verdict / Recommendation | ROI, break-even, migration cost |
| Quick Reference / Navigation tables | Summary figures must match source sections |

### Step 6 - Document Corrections

When a discrepancy is found:

1. Identify the correct value (from official pricing or correct arithmetic)
2. List ALL locations where the incorrect value appears
3. Fix all locations in a single pass (prevent partial fixes)
4. Add the correction to the revision history
5. Note: "No technical findings, verdicts, or evidence were modified" if applicable

## Checklist - Financial Verification Gate

- [ ] All dollar amounts extracted and grouped by meaning
- [ ] Unit costs verified against official pricing pages
- [ ] Every total independently re-derived from inputs
- [ ] Component subtotals sum to stated grand totals
- [ ] Discount percentages match vendor documentation
- [ ] Storage calculations use provisioned (not used) volumes
- [ ] Same metric shows same value in all document sections
- [ ] Break-even timeline = migration cost / annual savings
- [ ] Corrections tracked in revision history

## Anti-Patterns

| Don't | Do |
|-------|-----|
| Trust a $/vCore/hr rate without verifying the tier | Look up the exact SKU on the pricing page |
| Assume "60% AHB discount" because someone said so | Read the Microsoft AHB documentation |
| Use storage "used" for cost calculations | Use storage "provisioned" (that's what gets billed) |
| Fix a number in one section but not others | Grep for the old value and fix every occurrence |
| Round intermediate calculations | Keep precision, round only the final displayed value |
