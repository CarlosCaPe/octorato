---
name: unicode-symbol-compatibility
description: "Unicode Symbol Compatibility in Markdown Documents"
metadata:
  short-description: "Unicode Symbol Compatibility in Markdown Documents"
  original-index: 45
---

# Unicode Symbol Compatibility in Markdown Documents

## What

A discipline for choosing Unicode characters and emoji that render correctly across all target environments — GitHub, VS Code, PDF export, browser, and older systems — rather than characters that work only in modern Unicode 12.0+ renderers.

## Why

Unicode characters introduced after version 6.0 (2010) are not guaranteed to render on all systems. In a professional technical document:

- A broken symbol `□` destroys credibility as much as a typo
- A redundant symbol `4️⃣ 4` signals copy-paste sloppiness
- The `§` sign in a link label `[§2.6.1.9]` may render as a box in some markdown viewers
- Keycap emoji like `4️⃣` (U+0034 + U+FE0F + U+20E3) look garbled when paired redundantly with the digit they represent

These are **silent bugs** — they look fine in the editor but break for readers.

## Problem Catalog

### 1. Unicode 12.0 Colored Circles (2019) — High Risk

| Character | Codepoint | Unicode Ver | Problem | Safe Replacement |
|-----------|-----------|-------------|---------|-----------------|
| 🟢 | U+1F7E2 | 12.0 (2019) | Box on older systems | ✅ (U+2705, v6.0) |
| 🟡 | U+1F7E1 | 12.0 (2019) | Box on older systems | ⚠️ (U+26A0, v4.0) |
| 🟠 | U+1F7E0 | 12.0 (2019) | Box on older systems | 🔶 (U+1F536, v6.0) |
| 🔴 | U+1F534 | 6.0 (2010)  | ✅ Safe — keep as-is | — |

**Rule:** Never use 🟢🟡🟠 in documents. They were introduced in Unicode 12.0 and are not universally supported. Use ✅⚠️🔶 instead.

### 2. Section Sign `§` in Link Labels — Medium Risk

**Problem:**
```markdown
| Evidence |
| [§2.6.1.9](#2619-sql-mi-sku-compute-allocation) |  ← § may render as box
```

**Rule:** In markdown link display text, always use `Section X.X.X` (spelled out):
```markdown
| Evidence |
| [Section 2.6.1.9](#2619-sql-mi-sku-compute-allocation) |  ← always readable
```

**Exception:** `§` is acceptable in:
- Skills and instructional files as shorthand (readers are technical)
- Prose sentence-internal use: "see §3.4 for details" — acceptable
- Status log entries and internal notes

### 3. Keycap Emoji Redundancy — Low Risk, High Sloppiness

**Problem:**
```markdown
| 4️⃣ 4 | **Item** |   ← "4" appears twice: once as keycap, once as digit
```

The keycap `4️⃣` (digit + variation selector + combining enclosing keycap) IS the number 4. Writing `4️⃣ 4` is redundant — like writing "4 4".

**Rule:** Never pair a keycap emoji with its own digit. Either:
```markdown
| 4️⃣ | **Item** |   ← keycap alone (acceptable)
| 4   | **Item** |   ← plain digit (preferred for tables)
| 4.  | **Item** |   ← numbered with period (preferred for headings)
```

For headings, prefer plain numbers over keycap emoji for anchor stability:
```markdown
#### 4. Stabilize ADF Pipeline   ← stable anchor: #4-stabilize-adf-pipeline
#### 4️⃣ Stabilize ADF Pipeline  ← same anchor, but more fragile visually
```

## Detection Checklist

Run before any document publish:

```bash
# Unicode 12.0 colored circles (must be zero)
node -e "const c=require('fs').readFileSync('doc.md','utf8'); ['🟢','🟡','🟠'].forEach(e=>{ const n=(c.match(new RegExp(e,'g'))||[]).length; if(n) console.log(e+': '+n+' occurrences — replace!'); });"

# § in link labels (must be zero in TDD/deliverable docs)
grep -n '\[§' document.md

# Keycap + digit redundancy (e.g., 1️⃣ 1, 4️⃣ 4)
node -e "const c=require('fs').readFileSync('doc.md','utf8'); const lines=c.split('\n'); lines.forEach((l,i)=>{ if(/[0-9]️⃣ [0-9]/.test(l)) console.log('L'+(i+1)+': '+l.substring(0,80)); });"
```

## Safe Emoji Reference Table

| Purpose | Safe (v6.0 or earlier) | Avoid (v12.0+) |
|---------|------------------------|----------------|
| Success / OK / Green | ✅ | 🟢 |
| Warning / Caution / Yellow | ⚠️ | 🟡 |
| Medium / Orange | 🔶 | 🟠 |
| Critical / Red | 🔴 ✅ Safe | — |
| Info / Blue | 🔷 | 🔵 (v6.0, OK) |
| Priority 1 | 🥇 (v9.0, widely supported) | — |
| Priority 2 | 🥈 (v9.0, widely supported) | — |
| Priority 3 | 🥉 (v9.0, widely supported) | — |
| Priority 4+ | `4.` (plain text) | 4️⃣ (avoid in combination) |

> **Note on 🥇🥈🥉:** These are Unicode 9.0 (2016). They are widely supported in modern environments. If targeting very old systems, replace with plain `1.` `2.` `3.`.

## When to Apply

- **Every new table with colored status indicators**: Use ✅⚠️🔶🔴 only
- **Every section Evidence column**: Use `Section X.X.X` not `§X.X.X`
- **Every priority/rank column**: Use plain numbers or `X.` for values > 3
- **Before any document publish or commit**: Run detection checklist above

## Anti-Patterns

| Anti-Pattern | Example | Fix |
|---|---|---|
| Unicode 12.0 circles | `🟢 OK` in table | `✅ OK` |
| § in link labels | `[§2.6.5](#anchor)` | `[Section 2.6.5](#anchor)` |
| Keycap + digit | `4️⃣ 4` | `4` |
| Inconsistent priority icons | `🥇 🥈 🥉 4️⃣` | `🥇 🥈 🥉 4.` |
| **CRLF in markdown** | `\r\n` line endings (Windows) | Always write with `\n` (LF only). CRLF causes invisible `\r` to appear as `^M` or `?` in some renderers, breaking heading detection. |
| **Italic/annotation inside heading** | `### tablename *(NEW — added 2026-05-04)*` | Move annotation below heading as plain text or blockquote. Asterisks inside `#` headings break MD parsers. Pattern: `### tablename` + next line `> *Added 2026-05-04*` |

## Real-World Example

**Session 2026-03-07 — Acme Corp TDD:**

1. `🟢` appeared 17 times, `🟡` 7 times, `🟠` 4 times — all Unicode 12.0
   - Detection: User reported seeing broken `□` boxes in rendered document
   - Fix: Global replace across 9 .md files (54 occurrences)

2. `§` appeared in 4 Evidence-column link labels `[§2.6.1.9](#...)` and 5 footnote refs `(§SQL Server Agent)`
   - Detection: User reported `[§]` rendering as a broken box
   - Fix: Link labels → `[Section X.X.X]`; footnotes → `(→ Topic)`

3. `4️⃣ 4` appeared in Priority table row and heading
   - Detection: User flagged "4️⃣ 4" as redundant/broken-looking
   - Fix: `4️⃣ 4` → `4` in table; `4️⃣ Heading` → `4. Heading`

**Root cause:** These symbols were introduced incrementally during drafting. No pre-publish Unicode compatibility scan existed. This skill documents the scan as a required gate.

## Markdown Heading Safety Rules

Apply these before writing or generating any `#` heading:

1. **No CRLF** — always open/write files with `newline='\n'` in Python, or normalize with `.replace('\r\n', '\n')` before write.
2. **No inline italic/bold inside headings** — `### title *(note)*` breaks. Move annotation to the line below as `> *note*` or plain text.
3. **No em dash in heading unless title-level** — OK in `# Document Title — Subtitle` (H1 only). Avoid in `###` table/section headings.
4. **No special chars between `#` and text** — only a single ASCII space. No NBSP, zero-width space, soft hyphen.

```python
# Fix script — normalize any generated MD file before writing
import re

def normalize_md(text: str) -> str:
    # 1. LF only
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    # 2. Remove italic/bold annotations from headings
    def clean_heading(m):
        hashes, title = m.group(1), m.group(2).strip()
        title = re.sub(r'\s*\*\([^)]+\)\*\s*$', '', title)
        title = re.sub(r'\s*\*(NEW[^*]*)\*\s*$', '', title)
        return hashes + ' ' + title
    text = re.sub(r'^(#{1,6}) (.+)$', clean_heading, text, flags=re.MULTILINE)
    return text
```

## Lessons Learned

**2026-05-04 — Client Data Dictionaries (3 DD files):**

- Agent-generated Data Dictionaries had `*(NEW — added 2026-05-04)*` appended to `###` table headings. Caused MD heading detection failures in VS Code, Confluence, and GitHub preview.
- The Eligibility DD was written with CRLF line endings (598 `\r\n` pairs) while the other two used LF. Root cause: Python `open()` without `newline='\n'` on Windows defaults to CRLF.
- Fix: `normalize_md()` function above — strip CRLF + clean heading annotations. Applied retroactively to 3 files.
- **Rule added to anti-patterns:** Never put `*(annotation)*` inside heading lines. Put it on the next line as a blockquote.

**Rule: always publish AFTER fix, never before.** The correct sequence is: (1) fix the file, (2) verify with `python -c "..."`, (3) THEN publish to Confluence. Publishing before fixing means the Confluence page gets the broken content, and the fix commit doesn't automatically update the live page. If a fix was committed after a Confluence publish in the same session, always re-run `node shared/update-confluence-page.js` for the affected pages before declaring done.

## Related Skills

- `40_status_marker_hygiene.md` — Status markers ✅⚠️🔴⏳ semantics and lifecycle
- `44_long_document_revision_protocol.md` — Pre-publish checklist (add Unicode scan)
- `37_technical_document_craftsmanship.md` — Professional quality standards
