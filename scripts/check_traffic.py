#!/usr/bin/env python3
"""
Octorato traffic watcher — runs daily in GitHub Actions.

Pulls clone/view/star/fork stats from the GitHub Traffic API, compares
against the prior snapshot stored in .metrics/traffic_history.json, and
opens a GitHub Issue when a spike is detected.

Spike definition (the OR of):
  - today's clones >= max(5, 2× the 7-day avg)
  - today's views  >= max(10, 2× the 7-day avg)
  - new star (vs last snapshot)
  - new fork (vs last snapshot)

The script is intentionally dependency-free — only the stdlib + the
GITHUB_TOKEN exported by the workflow. It uses `urllib` instead of
`requests` so we don't need a pip install step in CI.

Env required:
  GITHUB_TOKEN — provided by the workflow (default token has traffic scope
                 when the workflow lives in the same repo it's watching)
  GITHUB_REPOSITORY — provided by Actions (owner/name)
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = os.environ.get("GITHUB_REPOSITORY", "CarlosCaPe/octorato")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
API = "https://api.github.com"
STATE_PATH = Path(__file__).resolve().parent.parent / ".metrics" / "traffic_history.json"
MAX_HISTORY = 90  # keep ~3 months of snapshots

# Spike thresholds — tunable. Set conservatively so we don't alert on noise.
MIN_CLONES_SPIKE = 5
MIN_VIEWS_SPIKE = 10
MULTIPLIER = 2.0   # vs 7-day average


def gh(path: str) -> dict:
    """GET a GitHub API endpoint as the workflow token. Returns parsed JSON."""
    req = urllib.request.Request(
        f"{API}{path}",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "octorato-traffic-watcher",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def gh_post(path: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{API}{path}",
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "octorato-traffic-watcher",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def load_history() -> list[dict]:
    if not STATE_PATH.exists():
        return []
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return []


def save_history(history: list[dict]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Keep tail only, sorted oldest→newest
    trimmed = sorted(history, key=lambda x: x["date"])[-MAX_HISTORY:]
    STATE_PATH.write_text(json.dumps(trimmed, indent=2) + "\n")


def today_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def main() -> int:
    if not TOKEN:
        print("::error::GITHUB_TOKEN not set", file=sys.stderr)
        return 2

    # 1. Pull current state from GitHub
    clones = gh(f"/repos/{REPO}/traffic/clones")
    views  = gh(f"/repos/{REPO}/traffic/views")
    repo   = gh(f"/repos/{REPO}")
    stargazers = gh(f"/repos/{REPO}/stargazers")
    forks_info = gh(f"/repos/{REPO}/forks?per_page=100")
    referrers  = gh(f"/repos/{REPO}/traffic/popular/referrers")
    paths      = gh(f"/repos/{REPO}/traffic/popular/paths")

    # Pick today's per-day numbers if present, else 0.
    today = today_utc_iso()
    daily_clones = next(
        (d for d in clones.get("clones", []) if d["timestamp"].startswith(today)),
        {"count": 0, "uniques": 0},
    )
    daily_views = next(
        (d for d in views.get("views", []) if d["timestamp"].startswith(today)),
        {"count": 0, "uniques": 0},
    )

    snapshot = {
        "date": today,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "today_clones": daily_clones.get("count", 0),
        "today_unique_cloners": daily_clones.get("uniques", 0),
        "today_views": daily_views.get("count", 0),
        "today_unique_viewers": daily_views.get("uniques", 0),
        "stars": repo.get("stargazers_count", 0),
        "forks": repo.get("forks_count", 0),
        "watchers": repo.get("subscribers_count", 0),
        "stargazer_logins": sorted([u["login"] for u in stargazers]),
        "fork_owners": sorted([f["owner"]["login"] for f in forks_info]),
        "top_referrer": referrers[0] if referrers else None,
        "top_path": paths[0] if paths else None,
    }

    # 2. Load history + figure out 7-day averages and prior snapshot
    history = load_history()
    last_7 = history[-7:]
    avg_clones = sum(s["today_clones"] for s in last_7) / 7 if last_7 else 0
    avg_views  = sum(s["today_views"]  for s in last_7) / 7 if last_7 else 0
    prior = history[-1] if history else None

    # 3. Detect spike conditions
    reasons: list[str] = []
    kinds: set[str] = set()  # which categories fired → drives an accurate title
    clones_threshold = max(MIN_CLONES_SPIKE, MULTIPLIER * avg_clones)
    views_threshold  = max(MIN_VIEWS_SPIKE,  MULTIPLIER * avg_views)

    if snapshot["today_clones"] >= clones_threshold and snapshot["today_clones"] > 0:
        kinds.add("traffic")
        reasons.append(
            f"📈 **{snapshot['today_clones']} clones today** "
            f"({snapshot['today_unique_cloners']} unique) — "
            f"threshold was {clones_threshold:.1f} (7d avg = {avg_clones:.1f})"
        )
    if snapshot["today_views"] >= views_threshold and snapshot["today_views"] > 0:
        kinds.add("traffic")
        reasons.append(
            f"👀 **{snapshot['today_views']} views today** "
            f"({snapshot['today_unique_viewers']} unique) — "
            f"threshold was {views_threshold:.1f} (7d avg = {avg_views:.1f})"
        )
    if prior:
        # Social events (new stars/forks) are recorded in the snapshot/history but
        # no longer open issues — they were vanity noise on the public tracker that
        # newcomers see. Only a genuine traffic spike (clones/views) warrants an issue.
        new_stars = set(snapshot["stargazer_logins"]) - set(prior.get("stargazer_logins", []))
        new_forks = set(snapshot["fork_owners"]) - set(prior.get("fork_owners", []))
        if new_stars:
            print(f"[traffic-watch] new stargazer(s): {', '.join(sorted(new_stars))} — logged, no issue")
        if new_forks:
            print(f"[traffic-watch] new fork(s): {', '.join(sorted(new_forks))} — logged, no issue")

    # 4. Always save snapshot (so the next run has fresh data)
    if not history or history[-1]["date"] != today:
        history.append(snapshot)
    else:
        history[-1] = snapshot  # same-day re-run overwrites
    save_history(history)

    # 5. If there's anything to alert on, open an issue
    if not reasons:
        print(f"[traffic-watch] no spike today ({snapshot['today_clones']} clones, "
              f"{snapshot['today_views']} views). State saved.")
        return 0

    body_parts = [
        f"_Snapshot taken {snapshot['checked_at']}_",
        "",
        "## What triggered this",
        *[f"- {r}" for r in reasons],
        "",
        "## Today",
        f"- Clones: **{snapshot['today_clones']}** ({snapshot['today_unique_cloners']} unique)",
        f"- Views: **{snapshot['today_views']}** ({snapshot['today_unique_viewers']} unique)",
        f"- Stars total: **{snapshot['stars']}** · Forks: **{snapshot['forks']}** · Watchers: **{snapshot['watchers']}**",
        "",
        "## Top referrer + path",
        f"- Referrer: `{(snapshot['top_referrer'] or {}).get('referrer', 'n/a')}` "
        f"({(snapshot['top_referrer'] or {}).get('count', 0)} views)",
        f"- Path: `{(snapshot['top_path'] or {}).get('path', 'n/a')}` "
        f"({(snapshot['top_path'] or {}).get('count', 0)} views)",
        "",
        "## Trailing window",
        f"- 7-day avg clones/day: {avg_clones:.1f}",
        f"- 7-day avg views/day: {avg_views:.1f}",
        "",
        "---",
        "_Generated by `.github/workflows/traffic-watch.yml` — close this issue once acknowledged._",
    ]
    # Title reflects the ACTUAL trigger — never call a star/fork a "traffic
    # spike" (issue #9 was "📈 Traffic spike: 0 clones, 0 views", a contradiction).
    if "traffic" in kinds:
        title = (f"📈 Traffic spike on {today}: "
                 f"{snapshot['today_clones']} clones, {snapshot['today_views']} views")
    else:
        social = []
        if "stars" in kinds:
            social.append("⭐ new star")
        if "forks" in kinds:
            social.append("🍴 new fork")
        title = f"{' + '.join(social)} on {today}" if social else f"Repo activity on {today}"

    issue = gh_post(
        f"/repos/{REPO}/issues",
        {"title": title, "body": "\n".join(body_parts), "labels": ["traffic"]},
    )
    print(f"[traffic-watch] opened issue #{issue.get('number')}: {issue.get('html_url')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
