#!/usr/bin/env python3
"""Gemini Vision Analyzer — 'Nano Banana' image analysis via Gemini Flash.

Analyzes images using Google Gemini Flash (vision) model.
Supports single files, multiple files, directories, and VS Code chat images.

Usage:
    python3 gemini_vision.py <image_path> [--prompt "..."] [--model gemini-2.0-flash]
    python3 gemini_vision.py <dir>/ [--batch]
    python3 gemini_vision.py --vscode-latest [--prompt "..."]

Auth:
    GEMINI_API_KEY env var (or loaded from ~/.env)

Examples:
    # Describe an image
    python3 gemini_vision.py photo.jpg

    # Custom prompt
    python3 gemini_vision.py screenshot.png --prompt "Is the blue line overlapping the text?"

    # Analyze latest VS Code chat image
    python3 gemini_vision.py --vscode-latest --prompt "What do you see?"

    # Batch analyze directory
    python3 gemini_vision.py photos/ --batch

    # Use specific model
    python3 gemini_vision.py img.png --model gemini-2.5-flash
"""

import argparse
import base64
import glob
import json
import os
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Auth: load GEMINI_API_KEY from env or ~/.env
# ---------------------------------------------------------------------------
def _load_api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key
    # Try ~/.env
    env_file = Path.home() / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("GEMINI_API_KEY=") and not line.startswith("#"):
                key = line.split("=", 1)[1].strip().strip("'\"")
                if key:
                    os.environ["GEMINI_API_KEY"] = key
                    return key
    print("ERROR: GEMINI_API_KEY not found. Set it in env or ~/.env", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# VS Code chat image discovery
# ---------------------------------------------------------------------------
VSCODE_CHAT_IMAGES = Path.home() / ".var/app/com.visualstudio.code/config/Code/User/workspaceStorage/vscode-chat-images"

def find_vscode_latest() -> Path | None:
    """Find the most recent image dragged into VS Code chat."""
    if not VSCODE_CHAT_IMAGES.is_dir():
        return None
    images = sorted(VSCODE_CHAT_IMAGES.glob("image-*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    return images[0] if images else None


# ---------------------------------------------------------------------------
# Image collection
# ---------------------------------------------------------------------------
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif"}

def collect_images(paths: list[str], batch: bool = False) -> list[Path]:
    """Resolve paths to image files."""
    result = []
    for p in paths:
        path = Path(p)
        if path.is_dir():
            for ext in IMAGE_EXTS:
                result.extend(sorted(path.glob(f"*{ext}")))
                if not batch:
                    result.extend(sorted(path.glob(f"**/*{ext}")))
        elif path.is_file() and path.suffix.lower() in IMAGE_EXTS:
            result.append(path)
        else:
            # Try glob
            matches = glob.glob(p)
            for m in matches:
                mp = Path(m)
                if mp.is_file() and mp.suffix.lower() in IMAGE_EXTS:
                    result.append(mp)
    return result


# ---------------------------------------------------------------------------
# GitHub Models fallback (GPT-4o via GitHub Token — free)
# ---------------------------------------------------------------------------
def _get_github_token() -> str | None:
    """Get GitHub token from env or gh CLI."""
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        return token
    gh_paths = [
        os.path.expanduser("~/.local/bin/gh"),
        "/usr/local/bin/gh", "/usr/bin/gh",
    ]
    for gh in gh_paths:
        if os.path.isfile(gh):
            try:
                result = subprocess.run(
                    [gh, "auth", "token"], capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip()
            except Exception:
                pass
    return None


def _analyze_github_models(image_path: Path, prompt: str) -> str:
    """Fallback: analyze image via GitHub Models API (GPT-4o, free)."""
    import urllib.request

    token = _get_github_token()
    if not token:
        raise RuntimeError("No GitHub token available for fallback")

    image_data = image_path.read_bytes()
    b64 = base64.b64encode(image_data).decode("utf-8")
    suffix = image_path.suffix.lower()
    mime_map = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".webp": "image/webp",
    }
    mime_type = mime_map.get(suffix, "image/png")

    payload = json.dumps({
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64}"}}
        ]}],
        "max_tokens": 1024,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://models.inference.ai.azure.com/chat/completions",
        data=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# Vision API call — Gemini primary, GitHub Models fallback
# ---------------------------------------------------------------------------
def analyze_image(image_path: Path, prompt: str, model: str = "gemini-2.0-flash") -> str:
    """Send image to Gemini for vision analysis; fallback to GitHub Models."""
    # Try Gemini first
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_key:
        # Try loading from ~/.env
        env_file = Path.home() / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.strip().startswith("GEMINI_API_KEY=") and not line.strip().startswith("#"):
                    gemini_key = line.strip().split("=", 1)[1].strip().strip("'\"")
                    break

    if gemini_key:
        try:
            # Add site-packages to path if needed
            sp = "/var/data/python/lib/python3.13/site-packages"
            if sp not in sys.path:
                sys.path.insert(0, sp)
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=gemini_key)
            image_data = image_path.read_bytes()
            suffix = image_path.suffix.lower()
            mime_map = {
                ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
                ".tiff": "image/tiff", ".tif": "image/tiff",
            }
            mime_type = mime_map.get(suffix, "image/png")
            image_part = types.Part.from_bytes(data=image_data, mime_type=mime_type)
            response = client.models.generate_content(model=model, contents=[prompt, image_part])
            return response.text
        except Exception as e:
            print(f"  Gemini failed ({e}), falling back to GitHub Models (GPT-4o)...", file=sys.stderr)

    # Fallback to GitHub Models (free)
    print("  Using GitHub Models (GPT-4o) — free via gh auth", file=sys.stderr)
    return _analyze_github_models(image_path, prompt)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Gemini Vision Analyzer — 'Nano Banana' image analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument("images", nargs="*", help="Image file(s), directory, or glob pattern")
    parser.add_argument("--prompt", "-p", default="Describe what you see in this image in detail. Be specific about layout, text, colors, spatial relationships, and any issues you notice.",
                        help="Custom prompt for the analysis")
    parser.add_argument("--model", "-m", default="gemini-2.0-flash",
                        help="Gemini model to use (default: gemini-2.0-flash)")
    parser.add_argument("--vscode-latest", action="store_true",
                        help="Analyze the latest image from VS Code chat")
    parser.add_argument("--batch", action="store_true",
                        help="Batch mode for directories")
    parser.add_argument("--json", action="store_true",
                        help="Output results as JSON")

    args = parser.parse_args()

    # Collect images
    image_paths = []
    if args.vscode_latest:
        latest = find_vscode_latest()
        if latest:
            image_paths.append(latest)
        else:
            print("ERROR: No VS Code chat images found.", file=sys.stderr)
            sys.exit(1)

    if args.images:
        image_paths.extend(collect_images(args.images, args.batch))

    if not image_paths:
        parser.print_help()
        sys.exit(1)

    # Deduplicate
    image_paths = list(dict.fromkeys(image_paths))

    print(f"Analyzing {len(image_paths)} image(s) with {args.model}...", file=sys.stderr)

    results = []
    for img_path in image_paths:
        print(f"\n  Processing: {img_path.name}", file=sys.stderr)
        try:
            result = analyze_image(img_path, args.prompt, args.model)
            results.append({"file": str(img_path), "result": result, "status": "ok"})
            if not args.json:
                print(f"\n{'='*60}")
                print(f"  {img_path.name}")
                print(f"{'='*60}")
                print(result)
        except Exception as e:
            results.append({"file": str(img_path), "error": str(e), "status": "error"})
            if not args.json:
                print(f"\nERROR analyzing {img_path.name}: {e}", file=sys.stderr)

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))

    # Summary
    ok = sum(1 for r in results if r["status"] == "ok")
    err = sum(1 for r in results if r["status"] == "error")
    if len(results) > 1:
        print(f"\n--- {ok} ok, {err} errors ---", file=sys.stderr)


if __name__ == "__main__":
    main()
