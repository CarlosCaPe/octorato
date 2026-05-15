---
name: "doc"
description: "Use when the task involves reading, creating, or editing `.docx` documents, especially when formatting or layout fidelity matters; prefer `python-docx` plus the bundled `scripts/render_docx.py` for visual checks."
---


# DOCX Skill

## When to use
- Read or review DOCX content where layout matters (tables, diagrams, pagination).
- Create or edit DOCX files with professional formatting.
- Validate visual layout before delivery.

## Workflow
1. Prefer visual review (layout, tables, diagrams).
   - If `soffice` and `pdftoppm` are available, convert DOCX -> PDF -> PNGs.
   - Or use `scripts/render_docx.py` (requires `pdf2image` and Poppler).
   - If these tools are missing, install them or ask the user to review rendered pages locally.
2. Use `python-docx` for edits and structured creation (headings, styles, tables, lists).
3. After each meaningful change, re-render and inspect the pages.
4. If visual review is not possible, extract text with `python-docx` as a fallback and call out layout risk.
5. Keep intermediate outputs organized and clean up after final approval.

## Temp and output conventions
- Use `tmp/docs/` for intermediate files; delete when done.
- Write final artifacts under `output/doc/` when working in this repo.
- Keep filenames stable and descriptive.

## Dependencies (install if missing)
Prefer `uv` for dependency management.

Python packages:
```
uv pip install python-docx pdf2image
```
If `uv` is unavailable:
```
python3 -m pip install python-docx pdf2image
```
System tools (for rendering):
```
# macOS (Homebrew)
brew install libreoffice poppler

# Ubuntu/Debian
sudo apt-get install -y libreoffice poppler-utils
```

If installation isn't possible in this environment, tell the user which dependency is missing and how to install it locally.

## Environment
No required environment variables.

## Rendering commands
DOCX -> PDF:
```
soffice -env:UserInstallation=file:///tmp/lo_profile_$$ --headless --convert-to pdf --outdir $OUTDIR $INPUT_DOCX
```

PDF -> PNGs:
```
pdftoppm -png $OUTDIR/$BASENAME.pdf $OUTDIR/$BASENAME
```

Bundled helper:
```
python3 scripts/render_docx.py /path/to/file.docx --output_dir /tmp/docx_pages
```

## Quality expectations
- Deliver a client-ready document: consistent typography, spacing, margins, and clear hierarchy.
- Avoid formatting defects: clipped/overlapping text, broken tables, unreadable characters, or default-template styling.
- Charts, tables, and visuals must be legible in rendered pages with correct alignment.
- Use ASCII hyphens only. Avoid U+2011 (non-breaking hyphen) and other Unicode dashes.
- Citations and references must be human-readable; never leave tool tokens or placeholder strings.

## Final checks
- Re-render and inspect every page at 100% zoom before final delivery.
- Fix any spacing, alignment, or pagination issues and repeat the render loop.
- Confirm there are no leftovers (temp files, duplicate renders) unless the user asks to keep them.

## Lessons Learned

### LibreOffice footer rendering limitations (2026-03-27)
**Context:** Generating DOCX with python-docx, rendering to PDF via LibreOffice headless.

1. **PAGE fields created programmatically don't render in footers.**
   - `fldChar` (BEGIN/SEPARATE/END) created by python-docx → LibreOffice ignores them in footer paragraphs.
   - `fldSimple` created by python-docx → same result.
   - **But** PAGE fields that already exist in the template DOCX → render correctly.
   - **Fix:** Preserve the original template text box containing the PAGE field. Don't recreate it.

2. **SDT (Structured Document Tags) block subsequent runs in footer paragraphs.**
   - A `w:sdt` element in a footer paragraph causes LibreOffice to ignore any `w:r` (run) placed after it.
   - **Fix:** Replace the entire SDT with a plain `w:r` run (copy `w:rPr` from SDT for font matching). Never append runs after an SDT in a footer.

3. **Text box vertical alignment requires per-footer-type calibration.**
   - `tIns="0"` on `a:bodyPr` removes internal top padding but is not sufficient alone.
   - `posOffset` (EMU) varies by footer type: regular footers ≠ first-page footers.
   - **Tested values (client project, anonymized):** regular = -36576 EMU, first_page = 18288 EMU.
   - **Fix:** Set `tIns=0` on bodyPr, then calibrate `posOffset` per footer type. Verify with pixel comparison (render page → measure Y coordinates).

4. **Flatpak sandbox file visibility.**
   - `flatpak-spawn --host pdftoppm` writes to the **host** `/tmp/`, not visible from inside the Flatpak sandbox.
   - **Fix:** Render to a path inside the user's home directory (visible to both host and sandbox).
