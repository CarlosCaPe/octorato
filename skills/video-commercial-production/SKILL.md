---
name: video-commercial-production
description: "Produces HD 9:16 video commercials from GSAP-animated HTML pages, capturing with Playwright and encoding with ffmpeg. Output works on WhatsApp, Instagram and TikTok. Triggers on 'video', 'comercial', 'MP4', 'Reel', 'video desde HTML', 'record animation'."
---

# Video Commercial Production

> Produce HD 9:16 portrait video commercials from GSAP-animated HTML pages using Playwright screen capture + ffmpeg encoding. Outputs are WhatsApp/Instagram/TikTok compatible.

## Triggers

Use this skill when: `video`, `commercial`, `comercial`, `record video`, `MP4`, `screen capture animation`, `GSAP video`, `produce video`, `WhatsApp video`, `Instagram Reel`, `TikTok video`, `video from HTML`, `record animation`.

## Stack

| Tool | Purpose |
|------|---------|
| **GSAP** | Timeline animation engine (scenes, transitions, text reveals) |
| **HTML/CSS** | Self-contained single-file commercial with `?record=true` mode |
| **Playwright** | Headless Chromium screen capture → WebM |
| **ffmpeg** | WebM → MP4 (H.264 Main + silent AAC) |
| **Python** | Orchestration script (`record_mp4.py`) |

## Architecture

```
HTML (GSAP animation + record mode CSS)
  ↓ Playwright (Chromium headless, viewport 1080×1920, DPR=1)
  ↓ WebM (raw screen capture)
  ↓ ffmpeg (H.264 Main L4.0, CRF 18, 30fps, silent AAC, faststart)
  ↓ MP4 (1080×1920, ~3-4 MB per 30s video)
```

## Critical Pattern: CSS transform:scale(3) for HD Video

**Problem**: Playwright's `device_scale_factor` (DPR) works for screenshots but NOT for video recording. Video recorder captures CSS-pixel layout inside the full canvas, resulting in tiny content in the corner of the frame.

**Solution**: Use `transform: scale(3)` on the viewport element instead of DPR scaling.

```css
/* Record mode: layout at 360×640, scale 3× to fill 1080×1920 */
body.record-mode #viewport {
  width: 33.3333%;   /* 1080 / 3 = 360px CSS layout */
  height: 33.3333%;  /* 1920 / 3 = 640px CSS layout */
  transform: scale(3);
  transform-origin: top left;
}
```

```python
# Playwright context — NO DPR, full HD viewport
context = browser.new_context(
    viewport={"width": 1080, "height": 1920},
    device_scale_factor=1,  # NOT 3
    record_video_dir=str(output_dir),
    record_video_size={"width": 1080, "height": 1920},
)
```

**Why this works**: CSS lays out content at 360×640 (mobile-sized), then the browser scales it 3× via CSS transform to fill the full 1080×1920 video frame. The video recorder captures the post-transform result.

**Anti-pattern (DO NOT)**:
- `device_scale_factor=3` + viewport 360×640 → video shows tiny content in corner
- Per-element CSS overrides (font-size, padding) → fragile, partial coverage
- `transform: scale()` on inner content elements → breaks GSAP animations

## ffmpeg Encoding (WhatsApp Compatible)

```bash
ffmpeg -y \
  -i raw.webm \
  -f lavfi -i anullsrc=r=44100:cl=stereo \  # REQUIRED: silent AAC track
  -c:v libx264 \
  -profile:v main \
  -level 4.0 \
  -preset medium \
  -crf 18 \
  -r 30 \
  -pix_fmt yuv420p \
  -c:a aac \
  -b:a 64k \
  -t 30 \
  -movflags +faststart \
  output.mp4
```

### Why silent AAC is mandatory

WhatsApp requires an audio track or it shows a **black screen** on some devices. The `anullsrc` lavfi filter generates a silent audio stream that satisfies this requirement.

### Encoding parameters explained

| Param | Value | Why |
|-------|-------|-----|
| `-profile:v main` | H.264 Main | Universal mobile support |
| `-level 4.0` | Level 4.0 | Supports 1080×1920 @ 30fps |
| `-crf 18` | Quality | High quality, ~3-4 MB for 30s |
| `-r 30` | 30fps | Smooth animation playback |
| `-pix_fmt yuv420p` | 4:2:0 | Required for broad compatibility |
| `-movflags +faststart` | Fast start | Enables streaming playback |

## I18n Video Production

For multi-language sites, produce one video per language:

1. HTML accepts `?lang={code}` URL parameter
2. GSAP timeline uses a translations object `T[lang]` for all text
3. Recording script iterates over languages:

```python
for lang in ["es", "en", "de"]:
    url = f"http://localhost:8765/comercial.html?record=true&lang={lang}"
    # ... record and encode
    # Output: open-garage-{lang}.mp4
```

4. Site serves the correct video based on `$locale`:

```svelte
$: videoSrc = `/videos/open-garage-${$locale}.mp4`;
```

## Record Mode Design Pattern

The HTML commercial has two modes controlled by URL parameters:

### Interactive mode (default)
- Shows play/pause controls, language selector, speed controls
- For previewing and debugging animations

### Record mode (`?record=true`)
- Hides all controls (`display: none`)
- Auto-plays after fonts load + 500ms delay
- Shows subtitles at bottom of screen
- `body.record-mode` CSS class enables the `transform: scale(3)` trick

```javascript
// Auto-detect record mode
const params = new URLSearchParams(window.location.search);
const isRecord = params.get('record') === 'true';
if (isRecord) {
  document.body.classList.add('record-mode');
  // Hide controls, auto-play after delay
  setTimeout(() => tl.play(), 500);
}
```

## Subtitle Engine

Subtitles are synced to the GSAP timeline via `onUpdate` callback:

```javascript
tl.eventCallback('onUpdate', () => {
  const t = tl.time();
  const sub = T[lang].subs.find(s => t >= s.start && t < s.end);
  subtitleEl.textContent = sub ? sub.text : '';
});
```

Subtitle data structure:
```javascript
subs: [
  { start: 0, end: 4, text: "Tu venta de garage digital" },
  { start: 4, end: 8, text: "Abierto, local, justo" },
  // ...
]
```

## Production Workflow

```
1. Edit HTML (GSAP scenes, text, styling)
2. Preview: open comercial.html in browser (interactive mode)
3. Serve locally: python3 -m http.server 8765 --directory video-assets/
4. Record: python3 record_mp4.py [--lang es]
5. Verify: ffprobe open-garage-es.mp4 (check 1080×1920, H.264, AAC)
6. Copy to site: cp results/*.mp4 ../public/videos/
7. Deploy site
```

## Verification Checklist

After recording, verify each MP4:

```bash
ffprobe -v quiet -print_format json -show_streams open-garage-es.mp4
```

Expected:
- Video: 1080×1920, H.264 Main profile, Level 4.0, 30fps
- Audio: AAC, 44100 Hz, stereo
- Duration: ~30s
- File size: 2-5 MB

## Lessons Learned

1. **Playwright DPR ≠ video DPR**: `device_scale_factor` only affects screenshots, NOT video recording. Always use `DPR=1` + CSS `transform: scale(N)` for video.

2. **WhatsApp black screen**: Videos without an audio track show black on WhatsApp (iOS and some Android). Always include a silent AAC track via `anullsrc`.

3. **`tl.seek()` hangs in Playwright**: GSAP's `tl.seek()` can block in headless Chromium. Use `void tl.time(t)` instead for programmatic seeking.

4. **Per-element CSS overrides are fragile**: Don't try to upscale video content by adjusting individual element sizes. The `transform: scale(3)` on the root viewport is the only reliable approach.

5. **Font loading matters**: Wait for fonts to load before starting the animation or text will render in fallback fonts for the first frames.

6. **Content density verification**: Use PIL/Pillow to analyze frame screenshots — count non-background pixels to verify content fills the frame (target >30% density).
