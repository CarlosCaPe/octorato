#!/usr/bin/env python3
"""Analyze images using GPT-4o vision via GitHub Models API or OpenAI API.

Usage:
    python3 analyze_image.py <path_or_glob> [--prompt "custom prompt"] [--json] [--model MODEL]
    python3 analyze_image.py image1.jpg image2.png  # multiple files
    python3 analyze_image.py "photos/*.jpeg"         # glob pattern
    python3 analyze_image.py photo.jpg --prompt "What room is this? Answer in one word"
    python3 analyze_image.py *.jpeg --json            # structured JSON output per image
    python3 analyze_image.py dir/                     # all images in directory

Auth priority: OPENAI_API_KEY > GITHUB_TOKEN > `gh auth token`
"""

import argparse
import base64
import glob
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif"}

DEFAULT_PROMPT = (
    "Describe this image in detail. Include:\n"
    "1. What room or space is shown (bedroom, kitchen, backyard, laundry, bathroom, etc.)\n"
    "2. Key objects and furniture visible\n"
    "3. Style and condition (modern, traditional, good condition, etc.)\n"
    "4. Any notable features\n"
    "Keep the response concise (3-5 sentences)."
)

CLASSIFY_PROMPT = (
    "Classify this image into exactly ONE category from this list:\n"
    "FACHADA, COCHERA, SALA, SALA_COMEDOR, COMEDOR, COCINA, RECAMARA, "
    "BAÑO, VESTIDOR, AREA_SOCIAL, ESCALERAS, TERRAZA, JARDIN, PATIO, "
    "AREA_LAVADO, CUARTO_SERVICIO, OFICINA, PANELES_SOLARES, PASILLO, "
    "FUENTE, ALBERCA, AMENIDADES, BODEGA, OTRO\n\n"
    "Also provide a short title (max 8 words) describing the image.\n\n"
    "Respond ONLY with valid JSON: {\"category\": \"...\", \"title\": \"...\", \"description\": \"...\"}"
)

BATCH_CLASSIFY_PROMPT = (
    "You are analyzing a set of property images. For each image, classify it into "
    "exactly ONE category from: FACHADA, COCHERA, SALA, SALA_COMEDOR, COMEDOR, "
    "COCINA, RECAMARA, BAÑO, VESTIDOR, AREA_SOCIAL, ESCALERAS, TERRAZA, JARDIN, "
    "PATIO, AREA_LAVADO, CUARTO_SERVICIO, OFICINA, PANELES_SOLARES, PASILLO, "
    "FUENTE, ALBERCA, AMENIDADES, BODEGA, OTRO.\n\n"
    "For each image provide a short title (max 8 words).\n\n"
    "Respond ONLY with a JSON array, one object per image in order:\n"
    '[{"image_index": 0, "category": "...", "title": "...", "description": "..."}]'
)


def get_token_and_endpoint():
    """Return (token, base_url) using auth priority."""
    # 1. OPENAI_API_KEY
    key = os.environ.get("OPENAI_API_KEY")
    if key:
        return key, "https://api.openai.com/v1/chat/completions"

    # 2. GITHUB_TOKEN
    key = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if key:
        return key, "https://models.inference.ai.azure.com/chat/completions"

    # 3. gh auth token
    gh_paths = [
        os.path.expanduser("~/.local/bin/gh"),
        "/usr/local/bin/gh",
        "/usr/bin/gh",
    ]
    for gh in gh_paths:
        if os.path.isfile(gh):
            try:
                result = subprocess.run(
                    [gh, "auth", "token"], capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip(), "https://models.inference.ai.azure.com/chat/completions"
            except Exception:
                pass

    # Also try gh on PATH
    try:
        result = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip(), "https://models.inference.ai.azure.com/chat/completions"
    except Exception:
        pass

    print("ERROR: No API key found. Set OPENAI_API_KEY, GITHUB_TOKEN, or authenticate with `gh auth login`.", file=sys.stderr)
    sys.exit(1)


def encode_image(path: str) -> tuple[str, str]:
    """Return (base64_data, media_type) for an image file."""
    ext = Path(path).suffix.lower()
    media_map = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".gif": "image/gif",
        ".webp": "image/webp", ".bmp": "image/bmp",
        ".tiff": "image/tiff", ".tif": "image/tiff",
    }
    media_type = media_map.get(ext, "image/jpeg")
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")
    return data, media_type


def call_vision_api(token, base_url, model, messages, max_tokens=1024):
    """Call the chat completions API with vision content."""
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
    }).encode("utf-8")

    req = urllib.request.Request(
        base_url,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"API error {e.code}: {body}", file=sys.stderr)
        sys.exit(1)


def resolve_paths(args_paths):
    """Resolve file paths, globs, and directories into a list of image files."""
    files = []
    for p in args_paths:
        path = Path(p)
        if path.is_dir():
            for f in sorted(path.iterdir()):
                if f.suffix.lower() in IMAGE_EXTENSIONS:
                    files.append(str(f))
        elif "*" in p or "?" in p:
            for f in sorted(glob.glob(p)):
                if Path(f).suffix.lower() in IMAGE_EXTENSIONS:
                    files.append(f)
        elif path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            files.append(str(path))
        else:
            print(f"WARNING: Skipping {p} (not an image or not found)", file=sys.stderr)
    return files


def analyze_single(token, base_url, model, image_path, prompt):
    """Analyze a single image."""
    b64, media = encode_image(image_path)
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{media};base64,{b64}"},
                },
            ],
        }
    ]
    return call_vision_api(token, base_url, model, messages)


def analyze_batch(token, base_url, model, image_paths, prompt):
    """Analyze multiple images in a single API call (more efficient)."""
    content = [{"type": "text", "text": prompt}]
    for path in image_paths:
        b64, media = encode_image(path)
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{media};base64,{b64}"},
        })
    messages = [{"role": "user", "content": content}]
    return call_vision_api(token, base_url, model, messages, max_tokens=2048)


def main():
    parser = argparse.ArgumentParser(
        description="Analyze images using GPT-4o vision (GitHub Models or OpenAI)"
    )
    parser.add_argument("paths", nargs="+", help="Image files, glob patterns, or directories")
    parser.add_argument("--prompt", default=None, help="Custom prompt (default: detailed description)")
    parser.add_argument("--classify", action="store_true", help="Classify into real-estate categories (JSON output)")
    parser.add_argument("--batch", action="store_true", help="Send all images in one API call (faster, cheaper)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--model", default="gpt-4o", help="Model name (default: gpt-4o)")
    parser.add_argument("--max-tokens", type=int, default=1024, help="Max response tokens")
    args = parser.parse_args()

    files = resolve_paths(args.paths)
    if not files:
        print("ERROR: No valid image files found.", file=sys.stderr)
        sys.exit(1)

    token, base_url = get_token_and_endpoint()

    # Determine prompt
    if args.prompt:
        prompt = args.prompt
    elif args.classify:
        prompt = CLASSIFY_PROMPT if not args.batch else BATCH_CLASSIFY_PROMPT
    else:
        prompt = DEFAULT_PROMPT

    print(f"Analyzing {len(files)} image(s) with {args.model}...", file=sys.stderr)
    if "azure" in base_url:
        print("Using: GitHub Models API", file=sys.stderr)
    else:
        print("Using: OpenAI API", file=sys.stderr)

    results = []

    if args.batch and len(files) > 1:
        # Batch mode: all images in one call
        response = analyze_batch(token, base_url, args.model, files, prompt)
        if args.json or args.classify:
            # Try to parse JSON response
            try:
                parsed = json.loads(response.strip().removeprefix("```json").removesuffix("```").strip())
                if isinstance(parsed, list):
                    for i, item in enumerate(parsed):
                        item["file"] = files[i] if i < len(files) else "unknown"
                    results = parsed
                else:
                    parsed["file"] = files[0]
                    results = [parsed]
            except json.JSONDecodeError:
                for i, f in enumerate(files):
                    results.append({"file": f, "raw_response": response})
        else:
            print(f"\n{'='*60}")
            for f in files:
                print(f"  {Path(f).name}")
            print(f"{'='*60}\n")
            print(response)
    else:
        # Individual mode: one call per image
        for img_path in files:
            name = Path(img_path).name
            print(f"\n  Processing: {name}", file=sys.stderr)
            response = analyze_single(token, base_url, args.model, img_path, prompt)

            if args.json or args.classify:
                try:
                    parsed = json.loads(response.strip().removeprefix("```json").removesuffix("```").strip())
                    parsed["file"] = name
                    results.append(parsed)
                except json.JSONDecodeError:
                    results.append({"file": name, "raw_response": response})
            else:
                print(f"\n{'='*60}")
                print(f"  {name}")
                print(f"{'='*60}")
                print(response)

    if results:
        print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
