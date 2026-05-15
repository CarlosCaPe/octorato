---
name: image-analyzer
description: "Analyze, describe, and classify images using GPT-4o vision via GitHub Models API or OpenAI API. MANDATORY TRIGGER: Use this skill whenever the user says 'imagen', 'mira la imagen', 'revisa la imagen', 'screenshot', 'foto', 'captura', 'mira esto', 'que ves', 'what do you see', 'look at this', or drags/pastes an image into the chat. Also use when you need to 'see' image contents (rooms, objects, style) to make decisions. Trigger on: image classification, photo identification, visual comparison, property photo analysis, 'what is in this image', bulk image labeling, duplicate detection."
metadata:
  short-description: Analyze images with GPT-4o vision
---

# Image Analyzer

Analyze images using GPT-4o vision via GitHub Models API or OpenAI API. Supports single files, globs, directories, and batch mode.

## MANDATORY: When User References an Image

**ALWAYS do this when the user mentions an image, screenshot, photo, or pastes one:**

1. **Check for VS Code chat images** (drag-and-drop into chat):
   ```bash
   ls -lt ~/.var/app/com.visualstudio.code/config/Code/User/workspaceStorage/vscode-chat-images/ 2>/dev/null | head -5
   ```
   Pick the most recent file matching the conversation timestamp.

2. **Check for explicit file path** in the user message.

3. **Check common screenshot locations**:
   ```bash
   ls -lt ~/Pictures/Screenshots/ ~/Desktop/ 2>/dev/null | head -5
   ```

4. **Run the analyzer** on the found image:
   ```bash
   python3 ~/.claude/skills/image-analyzer/scripts/analyze_image.py /path/to/image.png --prompt "Describe what you see in detail"
   ```

**NEVER say "I can't see images" — you CAN, via this script. Use it.**

## VS Code Chat Image Path Pattern

When users drag images into VS Code Copilot Chat, they land at:
```
~/.var/app/com.visualstudio.code/config/Code/User/workspaceStorage/vscode-chat-images/image-<timestamp>.png
```

To find the latest one:
```bash
ls -t ~/.var/app/com.visualstudio.code/config/Code/User/workspaceStorage/vscode-chat-images/ | head -1
```

## Auth Priority

1. `OPENAI_API_KEY` → OpenAI API
2. `GITHUB_TOKEN` / `GH_TOKEN` → GitHub Models API
3. `gh auth token` → GitHub Models API

## Quick Reference

```bash
SCRIPT=~/.claude/skills/image-analyzer/scripts/analyze_image.py

# Describe one image
python3 "$SCRIPT" photo.jpg

# Analyze VS Code chat image (latest)
LATEST=$(ls -t ~/.var/app/com.visualstudio.code/config/Code/User/workspaceStorage/vscode-chat-images/ | head -1)
python3 "$SCRIPT" ~/.var/app/com.visualstudio.code/config/Code/User/workspaceStorage/vscode-chat-images/"$LATEST" --prompt "Describe what you see"

# Classify into real-estate categories (JSON output)
python3 "$SCRIPT" photo.jpg --classify

# Batch classify all images in a directory (single API call, faster)
python3 "$SCRIPT" photos/ --classify --batch

# Custom prompt
python3 "$SCRIPT" photo.jpg --prompt "What room is this? One word."

# Detect duplicates in a gallery screenshot
python3 "$SCRIPT" screenshot.png --prompt "Identify any duplicate or very similar photos in this gallery"

# Multiple files with JSON output
python3 "$SCRIPT" img1.jpg img2.jpg --json

# Glob pattern
python3 "$SCRIPT" "photos/*.jpeg" --classify --batch
```

## Real-Estate Categories

The `--classify` flag maps images to: FACHADA, COCHERA, SALA, SALA_COMEDOR, COMEDOR, COCINA, RECAMARA, BAÑO, VESTIDOR, AREA_SOCIAL, ESCALERAS, TERRAZA, JARDIN, PATIO, AREA_LAVADO, CUARTO_SERVICIO, OFICINA, PANELES_SOLARES, PASILLO, FUENTE, ALBERCA, AMENIDADES, BODEGA, OTRO.

Output: `{"category": "...", "title": "...", "description": "...", "file": "..."}`

## Workflow: Classify New Property Photos

1. Run: `python3 "$SCRIPT" /path/to/new/photos/ --classify --batch`
2. Parse JSON output to get category + title per image
3. Rename files: `CATEGORY_NN.jpeg`
4. Copy to `public/realestate/<property>/`
5. Update `ficha_tecnica.json` with new entries

## Options

| Flag | Purpose |
|------|---------|
| `--classify` | Real-estate category classification (JSON) |
| `--batch` | All images in one API call (faster) |
| `--json` | Force JSON output |
| `--prompt "..."` | Custom prompt |
| `--model MODEL` | Model name (default: gpt-4o) |
| `--max-tokens N` | Max response tokens (default: 1024) |

## Rate Limits (GitHub Models API)

- 10 requests per 60 seconds
- Batch mode maxes at ~8000 tokens (8-10 images)
- For large batches: process in groups of 5 with 12s pauses
