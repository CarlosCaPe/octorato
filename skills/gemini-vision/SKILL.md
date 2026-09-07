---
name: gemini-vision
description: "MANDATORY TRIGGER: 'analiza imagen', 'nano banana', 'gemini vision', 'que ves en la imagen', or when an image is pasted asking for analysis. Vision with Gemini Flash. Preferred over image-analyzer when GEMINI_API_KEY is set."
metadata:
  short-description: Gemini Flash vision analysis (Nano Banana)
---

# Gemini Vision — "Nano Banana"

Analyze images using Google Gemini Flash (vision model) for detailed visual understanding, layout analysis, text detection, and defect identification.

## When to Use

**ALWAYS use this when:**
- User says "analiza imagen", "nano banana", "qué ves", "describe la imagen"
- User drags/pastes an image into VS Code chat
- You need to "see" an image to make decisions (layout, overlap, colors, etc.)
- Visual verification of generated documents (PDF, DOCX, slides)

**Priority over image-analyzer:** If `GEMINI_API_KEY` is available, prefer this skill over the GPT-4o-based `image-analyzer`. Falls back to `image-analyzer` if no Gemini key.

## Auth

Requires `GEMINI_API_KEY` in env or `~/.env`.
Get one at: https://aistudio.google.com/apikey

## Quick Reference

```bash
SCRIPT=~/.claude/skills/gemini-vision/scripts/gemini_vision.py

# Load API key from ~/.env
export $(grep GEMINI_API_KEY ~/.env | xargs)

# Describe one image
python3 "$SCRIPT" photo.jpg

# Custom prompt for specific analysis
python3 "$SCRIPT" footer.png --prompt "Is the blue line overlapping the date text?"

# Analyze latest VS Code chat image
python3 "$SCRIPT" --vscode-latest --prompt "Describe what you see"

# Batch analyze directory
python3 "$SCRIPT" photos/ --batch

# JSON output
python3 "$SCRIPT" img1.png img2.png --json

# Use specific model (default: gemini-2.0-flash)
python3 "$SCRIPT" img.png --model gemini-2.5-flash
```

## VS Code Chat Images

When users drag images into VS Code Copilot Chat:
```
~/.var/app/com.visualstudio.code/config/Code/User/workspaceStorage/vscode-chat-images/image-<timestamp>.png
```

Use `--vscode-latest` to auto-find the most recent one:
```bash
python3 "$SCRIPT" --vscode-latest --prompt "What do you see?"
```

## Workflow Integration

### 1. Document Verification (PDF/DOCX)
After generating a PDF or DOCX, render to image and verify:
```bash
# Render PDF page to PNG
flatpak-spawn --host pdftoppm -f 1 -l 1 -r 150 -png document.pdf preview
# Analyze with Gemini
python3 "$SCRIPT" preview-1.png --prompt "Check the footer: is the date text overlapping the blue line?"
```

### 2. Before/After Comparison
```bash
python3 "$SCRIPT" before.png after.png --prompt "Compare these two images. What changed? Are there improvements or regressions?"
```

### 3. Architecture Diagram Review
```bash
python3 "$SCRIPT" diagram.svg --prompt "Review this architecture diagram for completeness and accuracy"
```

## Models Available

| Model | Best For | Speed |
|-------|----------|-------|
| `gemini-2.0-flash` | General vision, fast | Fast |
| `gemini-2.5-flash` | Complex analysis | Medium |
| `gemini-2.5-pro` | Highest quality | Slower |

Default: `gemini-2.0-flash` (best speed/quality balance)

## Fallback Chain

1. **Gemini Flash** (this skill) — preferred when `GEMINI_API_KEY` available
2. **GPT-4o** (`image-analyzer` skill) — fallback when `OPENAI_API_KEY` or `GITHUB_TOKEN` available
3. **Pixel analysis** (Pillow) — last resort, programmatic color/position analysis

## Lessons Learned

- Gemini Flash is particularly good at detecting text overlap, layout issues, and spatial relationships in documents
- For PDF footer verification, use specific prompts like "Is the blue line overlapping the date text?" rather than generic "describe"
- VS Code Flatpak stores chat images at a non-standard path — use `--vscode-latest` to handle automatically
- Always `export $(grep GEMINI_API_KEY ~/.env | xargs)` before calling if key isn't in environment
