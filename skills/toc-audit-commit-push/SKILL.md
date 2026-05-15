---
name: toc-audit-commit-push
description: "TOC Audit, Commit & Push Workflow"
metadata:
  short-description: "TOC Audit, Commit & Push Workflow"
  original-index: 48
---

# TOC Audit, Commit & Push Workflow

## What

A repeatable workflow for validating a markdown Table of Contents against actual document headings, fixing discrepancies, regenerating output artifacts (HTML/PDF), and committing the result with professional, traceable commit messages.

## Why

The Table of Contents is the **navigation contract** of a long document. When a heading is added, renamed, or moved but the TOC isn't updated:

- Readers click a TOC link and land on the wrong section (or nowhere)
- The TOC omits entire sections, making them invisible
- The TOC lists sections that no longer exist (orphaned entries)
- PDF/HTML output inherits the broken TOC, and the defect reaches the audience

## The TOC Audit Process

### Step 1 - Extract All Headings

Pull every heading from the markdown, excluding the TOC section itself:

```bash
grep -n "^#" document.md

grep -c "^## " document.md    # H2 count
grep -c "^### " document.md   # H3 count
```

**For large documents (1000+ lines):** Use a script that generates slugs:

```javascript
const headings = [...md.matchAll(/^(#{1,6})\s+(.+)$/gm)].map(m => ({
  level: m[1].length,
  text: m[2],
  slug: m[2].toLowerCase()
    .replace(/[^\w\s-]/g, '')
    .replace(/\s/g, '-')
    .replace(/^-+|-+$/g, '')
}));
```

### Step 2 - Extract All TOC Entries

```javascript
const tocLinks = [...tocSection.matchAll(/\[([^\]]+)\]\(#([^)]+)\)/g)].map(m => ({
  text: m[1],
  anchor: m[2]
}));
```

### Step 3 - Diff Headings vs TOC

| Check | What It Finds |
|-------|---------------|
| Heading exists but no TOC entry | **Missing TOC entry** - section invisible in navigation |
| TOC entry exists but no matching heading | **Orphaned TOC entry** - link goes nowhere |
| TOC anchor doesn't match heading slug | **Broken link** - click leads to wrong place |
| TOC nesting depth doesn't match heading level | **Wrong hierarchy** - H3 shown as top-level |

### Step 4 - Fix Discrepancies

| Issue | Fix |
|-------|-----|
| Missing TOC entry | Add the entry at the correct nesting level |
| Orphaned TOC entry | Remove the dead entry |
| Broken anchor | Regenerate the slug from the heading text |
| Wrong nesting | Adjust indentation to match heading level |

### Step 5 - Validate Anchor Slugs

GitHub-style anchor slug generation rules:

| Input | Slug |
|-------|------|
| `## Executive Summary` | `#executive-summary` |
| `## 3.6 Post-Discovery Assessment` | `#36-post-discovery-assessment` |
| `## HA/DR & Failover` | `#hadr--failover` |
| `## Cost: $96K-$144K/Year` | `#cost-96k144kyear` |

**Rules:**
- Lowercase everything
- Replace spaces with hyphens
- Strip all non-word characters except hyphens
- Consecutive hyphens from stripped characters remain as `--`
- Emoji are stripped (become empty), leaving a leading hyphen

## The Commit & Push Workflow

### Commit Message Format

```
TICKET-ID: Version X.Y - concise description of changes

Detailed list of what changed:
- Added/Updated/Removed [specific section]
- Fixed [specific issue]
- Regenerated HTML/PDF output

Triggered by: [peer review / self-review / section addition]
```

### The Push Sequence

```bash
# 1. Stage all changes
git add -A

# 2. Review what's staged
git status
git diff --cached --stat

# 3. Commit with descriptive message
git commit -m "TICKET: description"

# 4. Pull before push (rebase to avoid merge commits)
git pull --rebase origin main

# 5. Push
git push origin main

# 6. Verify
git log --oneline -3
```

**Rule:** Always `pull --rebase` before pushing. If the remote has new commits, a plain `git push` will fail. Rebasing keeps the history linear.

## Regenerating Output Artifacts

After any document change, regenerate all output formats before committing:

```bash
# HTML generation (custom converter)
node scripts/misc/simple_md_to_html.js

# PDF generation (md-to-pdf with local stylesheet)
cd DOCUMENTS
npx md-to-pdf --config-file md-to-pdf.config.json --stylesheet pdf-styles.css document.md
```

**Rule:** The HTML/PDF in the repository must always reflect the current markdown source.

## Checklist - TOC Audit & Commit Gate

- [ ] All headings (H2, H3, H4) have corresponding TOC entries
- [ ] No orphaned TOC entries pointing to deleted/renamed headings
- [ ] Anchor slugs match heading text (GitHub slug rules)
- [ ] TOC nesting depth matches heading hierarchy
- [ ] Internal links from TOC are clickable in the generated HTML
- [ ] HTML/PDF regenerated from current markdown source
