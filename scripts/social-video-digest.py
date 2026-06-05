#!/usr/bin/env python3
"""
social-video-digest — daily triage of social-video creators for brain-worthy gems.

What this DOES (cheap, runs in cron):
  - Reads watchlist from ~/.claude/config/social-video-digest.json
  - For each creator, dumps latest N video metadata via yt-dlp (no downloads)
  - Filters to: new since last run AND matches keyword rules
  - Ranks by view count, caps to top N candidates
  - Writes a daily digest markdown to ~/.claude/digests/YYYY-MM-DD.md
  - Updates state at ~/.claude/state/social-video-digest.json

What this does NOT do (delegated to the agent during interactive review):
  - Video downloads, frame extraction, vision analysis — that's the
    `social-video-mining` skill's job, invoked on-demand when an operator
    opens the digest and decides to deep-dive a candidate.

Usage:
  python3 ~/.claude/scripts/social-video-digest.py             # run
  python3 ~/.claude/scripts/social-video-digest.py --dry-run   # no state write
  python3 ~/.claude/scripts/social-video-digest.py --reset     # forget state

Cron (suggested, daily 06:00 UTC):
  0 6 * * * /usr/bin/python3 $HOME/.claude/scripts/social-video-digest.py >> $HOME/.claude/digests/.cron.log 2>&1
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
# Force UTF-8 on stdout/stderr so the ✓ / ✗ / em-dash glyphs in reports
# survive on Windows shells defaulting to cp1252. Without this, a script
# can do its work correctly and still crash with UnicodeEncodeError when
# printing success. Applied repo-wide by _apply-utf8-reconfigure.py.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


CLAUDE_ROOT = Path.home() / ".claude"
CONFIG_FILE = CLAUDE_ROOT / "config" / "social-video-digest.json"


def expand(p: str) -> Path:
    return Path(os.path.expanduser(p))


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        sys.exit(f"ERROR: config not found at {CONFIG_FILE}")
    return json.loads(CONFIG_FILE.read_text())


def load_state(state_path: Path) -> dict:
    if state_path.exists():
        return json.loads(state_path.read_text())
    return {"version": 1, "creators": {}}


def save_state(state_path: Path, state: dict) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2) + "\n")


def channel_url(handle: str, platform: str) -> str:
    p = platform.lower()
    if p == "tiktok":
        return f"https://www.tiktok.com/@{handle}"
    if p in ("youtube", "youtube-shorts", "yt"):
        return f"https://www.youtube.com/@{handle}"
    if p == "instagram":
        return f"https://www.instagram.com/{handle}/"
    if p in ("bilibili", "b站"):
        return f"https://space.bilibili.com/{handle}"
    # Fallback — operator can put a full URL in handle for unknown platforms
    return handle if handle.startswith("http") else f"https://{p}.com/@{handle}"


def dump_videos(yt_dlp: Path, url: str, n: int) -> list[dict]:
    try:
        result = subprocess.run(
            [str(yt_dlp), "--flat-playlist", "--dump-json", "--no-warnings",
             "--playlist-end", str(n), url],
            capture_output=True, text=True, timeout=180,
        )
    except subprocess.TimeoutExpired:
        return []
    except FileNotFoundError:
        sys.exit(f"ERROR: yt-dlp not found at {yt_dlp}. Install or fix runtime.yt_dlp_path.")
    videos = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        try:
            videos.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return videos


def filter_new(videos: list[dict], last_seen_id: str | None, filters: dict) -> list[dict]:
    """Return videos that are NEW (newer than last_seen) AND pass keyword rules.
    Annotates each with `_matched` (keywords hit)."""
    must = [k.lower() for k in filters.get("must_match_any", [])]
    excl = [k.lower() for k in filters.get("exclude_if_matches", [])]

    out: list[dict] = []
    for v in videos:
        if v.get("id") == last_seen_id:
            break  # yt-dlp returns newest first; stop at last seen
        text = ((v.get("title") or "") + " " + (v.get("description") or "")).lower()

        if any(k in text for k in excl):
            continue
        if must:
            hits = [k for k in must if k in text]
            if not hits:
                continue
            v["_matched"] = hits
        else:
            v["_matched"] = []
        out.append(v)
    return out


def fmt_date(yyyymmdd: str) -> str:
    if yyyymmdd and len(yyyymmdd) == 8:
        return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"
    return yyyymmdd or ""


def video_url(handle: str, platform: str, vid: str) -> str:
    if platform.lower() == "tiktok":
        return f"https://www.tiktok.com/@{handle}/video/{vid}"
    if platform.lower() in ("youtube", "youtube-shorts", "yt"):
        return f"https://www.youtube.com/watch?v={vid}"
    return ""


def render_digest(date_str: str, results: dict, config: dict) -> str:
    total_new = sum(len(r["new"]) for r in results.values())
    total_cand = sum(len(r["candidates"]) for r in results.values())

    lines = [
        f"# Social Video Digest — {date_str}",
        "",
        "## Summary",
        f"- Creators scanned: **{len(results)}**",
        f"- New videos since last run: **{total_new}**",
        f"- High-signal candidates: **{total_cand}**",
        "",
    ]

    if total_cand == 0 and total_new == 0:
        lines += ["_Nothing new today. Brain growth: pass._", ""]

    for handle, r in results.items():
        lines.append(f"## @{handle}")
        lines.append(f"_Platform: `{r['platform']}` · Language: `{r['language']}`_")
        lines.append("")

        if not r["new"]:
            lines.append("No new videos since last run.")
            lines.append("")
            continue

        if r["candidates"]:
            lines.append(f"### Candidates — {len(r['candidates'])} high-signal of {len(r['new'])} new")
            lines.append("")
            lines.append("| Date | Title | Views | Matched | Link |")
            lines.append("|------|-------|-------|---------|------|")
            for v in r["candidates"]:
                date = fmt_date(v.get("upload_date") or "")
                title = (v.get("title") or "")[:70].replace("|", "\\|")
                views = v.get("view_count") or 0
                matched = ", ".join(v.get("_matched") or []) or "—"
                url = video_url(handle, r["platform"], v.get("id") or "")
                link = f"[deep-dive]({url})" if url else "—"
                lines.append(f"| {date} | {title} | {views:,} | {matched} | {link} |")
            lines.append("")

        unmatched = [v for v in r["new"] if v not in r["candidates"]]
        if unmatched:
            lines.append(f"_({len(unmatched)} other new videos filtered out by view threshold or keyword rules)_")
            lines.append("")

    lines += [
        "---",
        "",
        "**Next step**: open a candidate link, then invoke the `social-video-mining` skill in a Claude Code session to extract project name + verify the GitHub repo. If it's a brain-worthy gem, propose a skill via the 4D Gate.",
        "",
        f"**Re-run manually**: `python3 ~/.claude/scripts/social-video-digest.py`",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="Don't write state or digest, just print summary")
    parser.add_argument("--reset", action="store_true", help="Clear state (forces full re-scan next run)")
    args = parser.parse_args()

    config = load_config()
    runtime = config.get("runtime", {})
    state_path = expand(runtime.get("state_file", "~/.claude/state/social-video-digest.json"))
    digest_dir = expand(runtime.get("digest_dir", "~/.claude/digests"))
    n_videos = int(runtime.get("videos_per_creator", 20))
    max_cand = int(runtime.get("max_candidates_per_creator", 5))
    yt_dlp = expand(runtime.get("yt_dlp_path", "~/.local/bin/yt-dlp"))

    if args.reset and state_path.exists():
        state_path.unlink()
        print(f"✓ Reset: removed {state_path}")

    state = load_state(state_path)
    filters = config.get("filters", {})

    results: dict[str, dict] = {}

    for creator in config.get("creators", []):
        handle = creator["handle"]
        platform = creator.get("platform", "tiktok")
        language = creator.get("language", "es")
        min_views = int(creator.get("min_views_for_candidate", 0))

        url = channel_url(handle, platform)
        videos = dump_videos(yt_dlp, url, n_videos)

        creator_state = state["creators"].get(handle, {})
        last_seen = creator_state.get("last_seen_id")

        # First run: don't flood — record newest and emit nothing
        first_run = last_seen is None
        if first_run and videos:
            results[handle] = {
                "platform": platform, "language": language,
                "new": [], "candidates": [],
                "_note": f"First run — baseline set at video {videos[0].get('id')}. New videos will appear from tomorrow.",
            }
        else:
            new = filter_new(videos, last_seen, filters)
            candidates = sorted(
                [v for v in new if (v.get("view_count") or 0) >= min_views],
                key=lambda v: v.get("view_count") or 0,
                reverse=True,
            )[:max_cand]
            results[handle] = {
                "platform": platform, "language": language,
                "new": new, "candidates": candidates,
            }

        if videos and not args.dry_run:
            state["creators"][handle] = {
                "last_seen_id": videos[0].get("id"),
                "last_run_at": datetime.now(timezone.utc).isoformat(),
                "new_since_last": len(results[handle]["new"]),
            }

    if not args.dry_run:
        save_state(state_path, state)

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    digest_md = render_digest(date_str, results, config)

    if args.dry_run:
        print(digest_md)
    else:
        digest_dir.mkdir(parents=True, exist_ok=True)
        digest_path = digest_dir / f"{date_str}.md"
        digest_path.write_text(digest_md)
        total_new = sum(len(r["new"]) for r in results.values())
        total_cand = sum(len(r["candidates"]) for r in results.values())
        print(f"✓ Digest written: {digest_path}")
        print(f"  Creators: {len(results)} | New: {total_new} | Candidates: {total_cand}")


if __name__ == "__main__":
    main()
