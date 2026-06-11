---
name: social-video-mining
description: Extract structured insights from short-form social video (TikTok, YouTube Shorts, Instagram Reels, Bilibili, Douyin) WITHOUT paid speech-to-text — uses yt-dlp for video acquisition, ffmpeg for frame extraction, native multimodal vision (Read on JPGs) for on-screen text/logo identification, and WebFetch for source verification. Use when curating OSS tools from a creator channel, when mining tech-curator content for skill candidates, when transcripts are unavailable / blocked / too expensive, or when on-screen overlays carry the actual signal (project names, URLs, stats, logos).
---

# Social Video Mining — Frames Over Audio

Technique skill, not a tool wrapper. Documents the workflow we used to mine OSS-replacement gems from a daily-tech-tip TikTok creator without burning OpenAI Whisper credits. The key insight: **tech short-form video puts the signal on screen, not in the audio** — project names, URLs, GitHub stats, license badges all appear as overlay text and screen recordings.

## When to use

- Curating skill candidates from a tech-creator channel (TikTok, YouTube Shorts, Reels, Douyin, Bilibili)
- Verifying product claims from video reviews without watching dozens of videos
- Building reference material from conference talks where transcripts are unavailable
- Any "video → structured knowledge" task where audio transcription is blocked, expensive, or just not the highest-signal channel

## When NOT to use

- Audio IS the signal (interviews, podcasts, lectures) — use `transcribe` skill instead
- Long-form video where the project name only appears once — frame sampling will miss it; consider audio transcription
- Live streams or videos behind paywalls

## Workflow

```
1. List      → yt-dlp --flat-playlist --dump-json --playlist-end N <channel-url>
                Extract: title, description, view_count, upload_date per video
2. Triage    → filter titles/descriptions for the signal you want
                Sort by view_count (popularity = social validation)
3. Download  → yt-dlp -q -o "/tmp/<prefix>_%(id)s.%(ext)s" <video-url>
4. Frames    → ffmpeg -ss <sec> -i <video> -frames:v 1 -q:v 4 <frame>.jpg
                Extract 2-3 frames per video at strategic timestamps:
                  - t=2-5s : intro / project name often appears
                  - t=15-25s : middle / detailed view of the tool
                  - t=35-40s : outro / CTA + URL often appears
5. Vision    → Read each JPG — native multimodal sees:
                  - Project names (top-left logos, browser tabs)
                  - GitHub repo URLs (README banners, browser URL bar)
                  - License badges (MIT / Apache / AGPL)
                  - Star counts, version numbers
                  - On-screen overlay text (Spanish captions, hashtags)
6. Verify    → WebFetch or `gh search repos "<name>"` to confirm canonical URL exists
                and license / stars match what was on screen
7. Cleanup   → rm -rf /tmp/<prefix>_*  to release ~5MB per video
```

## Strategic timestamp picks

Most tech-tip short-form videos follow this structure:

| Timestamp | Typical content |
|---|---|
| 0-3s | Hook + caption with project pitch ("AWS en local y gratis") |
| 3-10s | Project logo + landing page hero ("Local AWS. Zero cost.") |
| 10-25s | Demo / detail screen recording with on-screen features |
| 25-35s | Stats / license / GitHub repo screenshot |
| 35-45s | Outro CTA with URL + hashtags |

Sample frames at t=5, t=20, t=40 and you'll capture name, demo, and source URL in 90% of cases. Add t=12, t=32 for hard cases.

## Cost profile (vs alternatives)

| Approach | Tokens / 1 video | API cost / 1 video | Speed |
|---|---|---|---|
| WebFetch on TikTok URL | ~500 (bot-walled) | $0 | Fast, useless |
| Browser scrape via agent-browser | ~5,000-10,000 | $0 | Slow, login-walled |
| yt-dlp + OpenAI Whisper transcription | ~3,000 | ~$0.01 | Medium, needs API key |
| **This skill (yt-dlp + frames + native vision)** | ~2,000 (3 frames × ~600 each) | **$0** | Fast, no API key |

Native vision dominates for project-identification tasks. Transcription only wins when audio is the signal (which short-form tech video rarely is).

## Permissions / install prerequisites

- `~/.local/bin/yt-dlp` — install via standalone GitHub release (no PEP 668 conflict). Settings allowlist needs:
  - `Bash(curl -fsSL https://github.com/yt-dlp/yt-dlp/releases/*)`
  - `Bash(chmod +x /home/<user>/.local/bin/yt-dlp)`
  - `Bash(~/.local/bin/yt-dlp:*)`
- `ffmpeg` — already present on most systems at `~/.local/bin/ffmpeg` or via `which ffmpeg`
- `jq` — for parsing yt-dlp's JSON dumps
- No external API keys required

## Cleanup discipline

Always `rm -rf /tmp/<prefix>_*` at the end of a mining run. Each video is ~5MB; a 10-video session = 50MB. Don't leave artifacts.

## Limits / when this fails

- **Channel doesn't permit unauthenticated metadata access** — yt-dlp may need cookies; falls back to agent-browser
- **Creator uses CapCut / Premiere with minimal on-screen text** — name only spoken, never shown. Then audio transcription wins
- **Branded text obscured by stylized fonts / shaders** — vision misreads; use 2 frames to cross-check
- **Project name is generic ("API client")** — vision identifies the screenshot but not the brand; WebFetch search step is essential

## TikTok gotcha: do NOT add curl_cffi, and don't blindly upgrade yt-dlp

Verified 2026-06-11 against a live TikTok pull. Two traps, both counter-intuitive:

1. **curl_cffi impersonation BREAKS the TikTok extractor.** yt-dlp warns "no impersonation target available" on TikTok, which looks like the thing to fix. It is not. Inject `curl_cffi` and TikTok serves a challenge page with no rehydration JSON, so extraction dies with `ERROR: Unable to extract universal data for rehydration`. Plain urllib (no curl_cffi) gets the normal page and works. Leave that warning alone for TikTok.
2. **yt-dlp versions after 2026.03.17 regressed TikTok** with the same rehydration error (2026.6.9 and master both fail, even without curl_cffi). Pin to a known-working build (`pipx runpip yt-dlp install "yt-dlp==2026.3.17"`) and only upgrade once an upstream TikTok fix lands. Test the actual target video after any yt-dlp change, never assume newer is safer.

Recognition signal: `Unable to extract universal data for rehydration` on a TikTok URL = one of these two, not a network blip.

## Anti-fabrication discipline (CRITICAL per CLAUDE.md)

Vision can hallucinate text it didn't actually see. **Every project name extracted by vision MUST be verified** via WebFetch or `gh search` before writing it into a brain skill or a client recommendation. The verification step is not optional. Workflow step 6 exists specifically to enforce this.

If verification fails (no repo found, name doesn't match search results), do NOT invent a URL or guess. Report "vision saw X but no canonical repo found — manual verification needed" and stop.

## Related brain assets

- `transcribe` — when audio IS the signal (interviews, lectures, podcasts)
- `image-analyzer`, `gemini-vision` — for richer per-image analysis when frames need deeper interpretation
- `agent-browser` — fallback when yt-dlp is blocked
- `knowledge-corpus` — to organize what's mined into a queryable brain layer
- Trend Researcher agent — natural consumer of mined social-video gems
- Sister technique: the broader "mine creator channels for OSS gems" pattern that produced this skill, `claude-mem-persistent-memory`, `bruno-postman-alternative`, `coolify-self-hosted-paas`, `spacetimedb-backend-as-database`, and `vibevoice-elevenlabs-alternative` in a single research session
