---
name: "kdp-coloring-book"
description: "Turns an operator-supplied original story or theme into a print-ready coloring book for Amazon KDP paperback: page plan, original line art via imagegen, interior PDF with bleed and margins, wrap cover with spine, and a pre-upload checklist. Never traces or derives from another book's artwork."
---

# KDP Coloring Book

Builds a coloring book from **original** input (a story, characters, or a theme the operator supplies) and packages it to Amazon KDP paperback specs. It composes two existing skills: `imagegen` (line art) and `pdf` (interior and cover assembly, render check).

## Hard rule: original art only

- Never use a screenshot, scan, or page of another coloring book (or any third-party artwork) as an input, reference image, or "style sample". A popular shortcut is to screenshot a best-seller's page and ask an image model for "more like this". That produces a derivative of a protected work and puts the KDP account at risk.
- Style may be described in words (genre conventions are not protected): "thick uniform outlines", "cozy everyday scene", "cute rounded animal characters", "large open areas". The drawing itself must be generated fresh from the operator's story.
- Characters, names and plot come from the operator. If the operator has not supplied them, ask; do not invent a story and present it as theirs.

## Inputs (ask for any that are missing)

| Input | Example | Default |
|---|---|---|
| Story or theme | operator's text, one scene per page | none, required |
| Audience | adults/teens, or kids with an age band | none, required |
| Language of title and captions | es, en, de, fr | operator's language |
| Trim size | 8.5x8.5 in (square, common for "bold and easy"), 8.5x11 in | 8.5x8.5 in |
| Page count (coloring pages) | 40-50 | 40 |
| Caption per page | short line from the story under the drawing | on for story books, off for theme books |

## Style by audience

| Audience | Line weight | Detail | Notes |
|---|---|---|---|
| Kids 1-4 | very thick, one closed shape per object | minimal, no small regions | one subject per page, large shapes |
| Kids 5-10 | thick | moderate, a simple background | characters plus a scene |
| Adults/teens "bold and easy" / cozy | thick, uniform | moderate, rounded cute characters, cozy everyday scenes | the dominant best-selling adult style in the market sample below |
| Adults detailed (mandala, landscapes) | thin to medium | high | relaxation and "antiestrés" positioning |

Market sample (Amazon.es books search, sorted by Best Sellers, 2026-11-06): the adult query was led by cute-animal and cozy daily-life titles with simple thick-line designs, followed by large mixed collections (landscapes, mandalas) and color-by-number; the kids query was led by low-price publisher activity books and "my first coloring book" titles for ages 1-4. Re-measure before relying on it; rankings move.

## Workflow

1. **Intake.** Collect the inputs table. Confirm the story is the operator's own.
2. **Page plan.** Write `plan.md`: one row per page with page number, scene description (from the story), caption, and complexity level. Coloring pages are printed single-sided: every coloring page is followed by a back page that is either blank or carries a light pattern; KDP lists "excessive blank pages" as a rejection cause, so prefer a light back-page element (a small caption, a "this page belongs to" line, or a test-color swatch) over fully empty pages. Add front matter: title page, "this book belongs to", optional color test page.
3. **Line art.** For each page, call `imagegen` with a prompt built from the plan row plus the fixed style block:
   `black and white coloring page line art, pure white background, clean closed outlines, uniform <thick|medium> line weight, no shading, no gray fills, no text, no border, <scene from plan>`.
   Keep a character sheet (one reference image per character, generated first, from the operator's descriptions) and reuse it as the reference input for consistency. Generate at least 2550x2550 px for 8.5x8.5 in or 2550x3300 px for 8.5x11 in (300 DPI at trim).
4. **Clean.** Convert each image to pure black on white (threshold, remove gray), check that line weight is at least 0.75 pt (0.01 in) at print size, and reject pages with tiny closed regions for the kids tiers.
5. **Interior PDF.** Use `pdf` (reportlab). Single-page PDF, no spreads. Page size = trim plus bleed when any art reaches the edge; otherwise trim size without bleed. Respect margins (table below). Embed every font. No crop marks, annotations or metadata objects.
6. **Cover.** Wrap cover as one PDF: bleed + back + spine + front + bleed. Spine width from the page count (table below). Spine text only from 80 pages. Leave the barcode area on the lower right of the back cover clear. 300 DPI.
7. **Render check.** Render every interior page and the cover to PNG (Poppler) and look at them before declaring done. Count pages and confirm the total is even and within the trim's limits.
8. **Checklist** (below), then hand the files to the operator. Upload and the AI-content disclosure in KDP are the operator's step.

## KDP paperback specs (black ink, white paper)

Source: KDP help G201834180, GVBQ3CMEQW3W2VL6, G201857950, G201953020, G202169030, G202145450, read 2026-11-06. Re-check before each release; KDP changes these pages.

| Spec | Value |
|---|---|
| Page count | 24 minimum; 8.5x11 and 8.5x8.5 up to 590; 8x10 up to 828; total rounded up to even |
| Bleed | 0.125 in on top, bottom and outside; page = trim width + 0.125 in, trim height + 0.25 in (8.5x8.5 -> 8.625x8.75 in; 8.5x11 -> 8.625x11.25 in) |
| Outside margins | at least 0.25 in without bleed, 0.375 in with bleed |
| Inside (gutter) margin | 24-150 pages 0.375 in; 151-300 0.5 in; 301-500 0.625 in; 501-700 0.75 in |
| Image resolution | 300 DPI minimum; under 200 DPI is "low resolution" |
| Line weight | at least 0.75 pt (0.01 in) |
| Gray fill | at least 10% if used (coloring pages should use none) |
| Fonts | embedded, 7 pt minimum |
| Interior file | single PDF, single pages, up to 650 MB |
| Spine width | page count x 0.002252 in (white paper) |
| Spine text | only from 80 pages |
| Cover | one PDF, back + spine + front with 0.125 in bleed each side, 300 DPI, text 0.125 in inside trim |
| Cover calculator | https://kdp.amazon.com/cover-calculator |

Royalty note for pricing: KDP paperback royalty is 60% of list price at 9.99 or above (50% below), minus the printing cost (G201834330).

## Pre-upload checklist

- [ ] Every drawing generated from the operator's story; no third-party image used as input
- [ ] Interior PDF opens, page count even, within trim limits, every page rendered and viewed
- [ ] All art pure black on white, line weight at or above 0.75 pt at print size
- [ ] Margins and bleed match the table for this trim and page count
- [ ] Fonts embedded
- [ ] Cover width = 2 x 0.125 + 2 x trim width + spine; spine text only if 80+ pages
- [ ] Operator told that KDP requires disclosing AI-generated images (cover and interior) when publishing (G200672390)
- [ ] Coloring books are generally not "low-content" under KDP's definition (GGE5T76TWKA85DJM); do not tick the low-content box by default

## Open gaps

- KDP gives no numeric limit for blank pages; the back-page element in step 2 is a mitigation, not a documented threshold.
- No KDP rule was found for 1-bit vs grayscale line-art images; the clean step outputs grayscale-safe pure black on white.
