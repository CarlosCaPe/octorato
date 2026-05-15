---
name: document-code-review
description: "Document Code Review - Full QA Pass"
metadata:
  short-description: "Document Code Review - Full QA Pass"
  original-index: 46
---

# Document Code Review - Full QA Pass

## What

A systematic quality assurance process for long-form technical documents (TDDs, evaluations, RFCs) that treats the document as code - validating internal links, TOC accuracy, table formatting, financial consistency, and structural integrity before marking a version as final.

## Why

A 4,000+ line technical document has the same surface area for defects as a mid-size codebase. Broken internal links, mismatched financial numbers across sections, orphaned TOC entries, and malformed tables are **silent credibility killers** - the reader discovers them before the author does.

A code review pass catches these defects mechanically, the same way a linter catches syntax errors.

## The Nine Review Dimensions

| # | Dimension | What It Catches | Tool / Technique |
|---|-----------|-----------------|------------------|
| 1 | TOC Integrity | Missing entries, orphaned headings, wrong nesting | Heading extraction vs TOC diff |
| 2 | Internal Links | Broken `#anchor` references, typos in slugs | Regex extraction + slug validation |
| 3 | External Links | Dead URLs, moved pages, timeouts | HTTP HEAD requests (spot-check) |
| 4 | Table Formatting | Trailing pipes, missing columns, alignment drift | Line-by-line pipe count |
| 5 | Cross-Section Consistency | Financial numbers differ across sections, contradicting verdicts | Grep for key values, compare |
| 6 | Mathematical Verification | Arithmetic errors, subtotals that don't sum, misapplied rates | Independent recalculation |
| 7 | Stale Assumption Detection | Statements true in earlier versions that became outdated when new scenarios, figures, or findings were added | Grep for superseded claims, compare with latest version context |
| 8 | Cross-Format Consistency | MD source and rendered outputs (HTML, PDF, DOCX) have different content — edits applied to one format but not regenerated in others | Pattern-count comparison between source and rendered files |
| 9 | Layout Arithmetic Verification | Parallel columns/cells in generated PDFs have misaligned elements — signature lines at different heights, unbalanced tables, spacer math errors | Programmatic flowable measurement with `.wrap()` + height arithmetic |

## Execution Protocol

### Step 1 - TOC vs Heading Inventory

Extract all headings from the document and compare against the TOC entries:

```bash
# Extract all headings from the markdown
grep -n "^#" document.md | head -80

# Count TOC entries
grep -c "^\s*[-\d]" document.md   # approximate TOC line count
```

**What to verify:**
- Every `##` and `###` heading has a corresponding TOC entry
- TOC nesting depth matches heading depth
- No duplicate anchors (headings with identical slugs)
- Appendix entries appear at correct level

### Step 2 - Internal Link Audit

Extract every `[text](#anchor)` reference and validate the anchor exists as a heading:

```javascript
// Extract all internal links
const links = [...md.matchAll(/\[([^\]]+)\]\(#([^)]+)\)/g)];
console.log(`Found ${links.length} internal links`);

// Extract all heading slugs
const headings = [...md.matchAll(/^#{1,6}\s+(.+)$/gm)]
  .map(m => slugify(m[1]));

// Find broken links
const broken = links.filter(l => !headings.includes(l[2]));
```

**Acceptable result:** Zero broken links. Any broken link is a blocker.

### Step 3 - External URL Spot-Check

For documents with external references (Azure docs, GitHub, vendor pages):

```bash
# Extract all external URLs
grep -oP 'https?://[^\s\)]+' document.md | sort -u | head -20

# Spot-check top 10
curl -sI "https://example.com" | head -1
```

**Not required:** Full crawl of every URL. Spot-check the top 10-20 most referenced domains.

### Step 4 - Table Formatting Scan

```bash
# Find tables with inconsistent column counts
grep -n "^|" document.md | awk -F'|' '{print NR, NF-1, $0}' | head -20
```

**Common defects:**
- Trailing empty column: `| data | data | |` (extra pipe at end)
- Missing space before inline links: `|[link](#anchor)` vs `| [link](#anchor)`
- Separator row column count doesn't match header row

### Step 5 - Financial Number Consistency

For documents containing cost estimates, savings projections, or ROI calculations:

```bash
# Find all dollar amounts
grep -oP '\$[\d,.]+[KMB]?(?:/yr)?' document.md | sort -u

# Find all percentage values
grep -oP '\d+(\.\d+)?%' document.md | sort -u

# Find all timeline references
grep -oP '\d+(\.\d+)?\s*(year|month|yr)' document.md | sort -u
```

**Rule:** The same metric must show the same value everywhere it appears. If the Executive Summary says "$178K-$382K/yr" then every section referencing annual savings must use that exact range.

### Step 6 - Mathematical Verification

For documents with financial models, verify arithmetic independently:

- Multiply unit costs by quantities and confirm totals match stated figures
- Verify per-unit rates against official pricing sources (Azure pricing pages, vendor quotes)
- Check that percentages (discounts, growth rates) are applied correctly
- Confirm break-even calculations: migration cost / annual savings = stated timeline
- Cross-verify subtotals: compute + storage + backup = stated total

**Common arithmetic defects found in practice:**
- Using a different tier's pricing (e.g., Business Critical rate for General Purpose)
- Mixing "used" vs "provisioned" storage in calculations
- AHB discount percentage not matching Microsoft documentation
- Sub-components not summing to stated total

### Step 7 - Stale Assumption Detection

When a document evolves across versions (e.g., adding an AI-assisted scenario on top of human-only estimates), earlier sections often retain outdated absolute statements. These are **silent credibility killers** — the document contradicts itself.

**How it happens:** Version N adds a new scenario (e.g., AI-assisted migration) in one section. Fifteen other sections still reference only the old scenario (human-only) as if it were the only option. The revision author updated the main analysis but forgot the subsidiary references in verdicts, summaries, charter traceability, findings, and key risk lists.

**Detection technique:**

1. Identify the key change in the latest version from the revision history
2. Extract the "superseded claim" — the statement that was true before the change
3. Grep for all instances of the superseded claim across the entire document
4. For each hit, verify it now includes or acknowledges the new scenario

```bash
# Example: v3.0 added AI-assisted SP conversion. Find all sections
# still claiming "no automated tool" or showing only human-only hours
grep -n 'no automated\|has no.*tool\|6,908.*13,816' document.md

# Filter to lines that do NOT mention the AI alternative
grep -n '6,908.*13,816' document.md | grep -v 'AI-assisted\|human-only'
```

**Common stale patterns:**
- "No automated 1:1 tool exists" (when AI-assisted scenario was added elsewhere)
- Only human-only cost/hours in a summary when AI figures exist in the analysis
- Break-even citing only human-only timeline when AI break-even was computed
- Charter traceability showing old effort estimates without the new scenario
- Verdict justification referencing only the worst-case without the AI alternative
- Findings table frozen at an earlier version's conclusions

**Rule:** After ANY version bump that changes estimates, scenarios, or key findings — grep the ENTIRE document for the old figures and verify every occurrence now includes the updated context.

### Step 8 - Cross-Format Consistency

When a document exists in multiple formats (`.md` source → `.html`, `.pdf`, `.docx` rendered outputs), ALL formats must reflect the same content. The source `.md` is the single source of truth — rendered formats must be regenerated after every edit.

**How drift happens:** Author edits the `.md` file but forgets to regenerate the `.html`. Or worse, edits are applied directly to the HTML without updating the source markdown. Both create a situation where stakeholders reading different formats see different numbers.

**Detection technique:**

Extract all key financial patterns from both files and compare hit counts:

```powershell
# Compare key patterns between MD and HTML
$patterns = @('0\.55M','1\.08M','40.57%','690K','173K','345K',
              '56\.7K','24\.3K','1\.3M','2\.6M','190K','388K')
foreach($p in $patterns) {
  $md = (Select-String -Path doc.md -Pattern $p | Measure-Object).Count
  $html = (Select-String -Path doc.html -Pattern $p | Measure-Object).Count
  $status = if($md -eq $html){'OK'}else{'MISMATCH'}
  Write-Host "$status | MD:$md HTML:$html | $p"
}
```

**Rule:** After ANY `.md` edit, regenerate all rendered formats before committing. Every key financial pattern must return the **same hit count** in both files. Any `MISMATCH` is a blocker.

**Anti-pattern:** Editing the `.html` directly instead of editing the `.md` and regenerating. The `.md` is always the source of truth.

### Step 9 - Layout Arithmetic Verification

When a document is generated programmatically (reportlab, python-docx, PptxGenJS, etc.), the **generator code** is the source of truth — not the rendered output. Layout defects (misaligned columns, unbalanced signature blocks, overlapping elements) are arithmetic bugs in the generator, not rendering bugs.

**The pattern:** For any parallel layout (side-by-side columns, signature blocks, comparison tables), sum the heights of all flowables in each column independently and verify they match at alignment points.

```python
# reportlab: measure flowable heights before rendering
def measure(flowable, width=230):
    """Return the rendered height of a flowable at a given width."""
    _, h = flowable.wrap(width, 10000)
    return h

# Example: two signature columns must align at the ____ line
# Left:  title(14pt) + spacer(X)
# Right: title(14pt) + spacer(6pt) + image(78pt)
# Solve: X = 6 + 78 = 84pt
left_before_line = measure(title_left) + spacer_left
right_before_line = measure(title_right) + spacer_right + image_height
assert left_before_line == right_before_line, (
    f"Alignment mismatch: left={left_before_line}pt, right={right_before_line}pt"
)
```

**When to apply:**
- Any `Table()` with parallel content that must align horizontally
- Signature blocks (left signer vs right signer)
- Multi-column comparison layouts
- Header/footer elements that must sit at consistent vertical positions

**Detection technique:**
1. Identify all `Table()` or multi-column constructs in the generator code
2. For each column, list every element and its height source (explicit spacer, measured paragraph, image dimensions)
3. Sum heights to each visual alignment point (e.g., the `____` line)
4. Assert column sums are equal — any delta is a bug
5. When an element changes (e.g., image replaced with different dimensions), recalculate all dependent spacers

**Common defects:**
- Image replaced with different aspect ratio but spacer in opposite column not updated
- `Spacer(1, 40)` hardcoded when it should be computed from sibling column content
- `spaceAfter` on `ParagraphStyle` differs between columns, causing cumulative drift
- `VALIGN='TOP'` on Table masks the misalignment visually in some renderers but not in print

**Rule:** Every parallel column in a generated document must have an explicit height budget comment in the code. When any element changes dimensions, the opposite column's spacer must be recalculated.

**Anti-pattern:** Eyeballing the PDF to check alignment. Use `.wrap()` measurement — the eye misses 2-5pt drift that accumulates across pages.

## Checklist - Document Code Review Gate

Before marking any version as `Reviewed`:

- [ ] TOC covers all `##` and `###` headings
- [ ] Zero broken internal links (automated scan)
- [ ] External URLs spot-checked (top 10 domains)
- [ ] Table column counts are consistent per table
- [ ] No trailing empty columns or missing cell separators
- [ ] Financial numbers are identical across all sections
- [ ] Financial arithmetic verified independently (unit * quantity = total)
- [ ] No stale assumptions from earlier versions (grep superseded claims, verify updated context)
- [ ] All rendered formats (HTML, PDF, DOCX) regenerated from source MD and pattern-count verified
- [ ] Layout arithmetic verified for all parallel columns in generated documents (height sums match at alignment points)
- [ ] Verdict language is consistent (same phrasing, same conditions)
- [ ] Revision history updated with current version
- [ ] Code blocks have language tags (`sql`, `json`, `bash`)
- [ ] No orphaned TODO/FIXME markers remain

## When to Run

| Trigger | Scope |
|---------|-------|
| Before peer review handoff | Full 9-dimension pass |
| After incorporating reviewer feedback | Re-run dimensions 1, 2, 5, 6, 7, 8, 9 |
| After any version bump that changes estimates or scenarios | Dimension 7 (stale assumption sweep) is mandatory |
| After any `.md` edit | Dimension 8 (regenerate + cross-format verify) is mandatory |
| Before PDF/HTML generation | Full pass + visual spot-check + dimension 9 for generated docs |
| After any heading rename or section move | Dimensions 1 and 2 only |

## Anti-Patterns

| Don't | Do |
|-------|-----|
| "I'll check the links later" | Run the link audit before every commit |
| Manually counting TOC entries | Script the heading extraction and diff |
| Trusting that financial numbers are consistent because "I wrote them all" | Grep every dollar value and compare mechanically |
| Skipping table formatting because "it looks fine in VS Code" | Pipe counts catch what the eye misses |
| Running the review only once at the end | Run after every major edit pass |
| Trusting arithmetic without re-deriving | Multiply unit costs independently and compare |
| Eyeballing PDF alignment instead of measuring | Use `.wrap()` to measure flowable heights mechanically |
| Hardcoding spacers without documenting the height budget | Add a comment: `# Left: title(14) + spacer(84) = 98pt = Right: title(14) + spacer(6) + img(78)` |
