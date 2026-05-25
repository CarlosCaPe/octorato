#!/usr/bin/env python3
"""
GitHub Trending Daily Curation — feeds the brain.

Pulls top trending from 3 sources (GH/HN/PH), classifies into 4 brain-fit
buckets via heuristics + optional Groq LLM QA gate, writes the digest to
Markdown (~/.claude/knowledge/github-trending/<date>.md) and (when token
present) a daily Notion page.

Stdlib only + the `gh` CLI for GitHub REST metadata enrichment.

Usage:
    python3 github_trending_digest.py                  # today
    python3 github_trending_digest.py --date 2026-05-23
    python3 github_trending_digest.py --dry-run        # print, don't write
    python3 github_trending_digest.py --no-llm         # skip Groq QA gate

Env vars consumed (auto-loaded from supervisor + project .env files):
    GROQ_API_KEY                       (optional, enables LLM QA gate)
    NOTION_TOKEN                       (optional, enables Notion writer)
    NOTION_CURATION_PARENT_PAGE_ID     (required if NOTION_TOKEN set)
    PRODUCTHUNT_TOKEN                  (optional, falls back to scrape)

Exit codes:
     0  digest written successfully (may be empty "no signal")
     1  at least one source failed AND no survivors emitted
     2  config error (missing required env, bad --date format)
     3  unexpected fatal error (caught at top-level)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from html.parser import HTMLParser
from typing import Optional

# ──────────────────────────────────────────────────────────────────────────
# Paths & constants
# ──────────────────────────────────────────────────────────────────────────

ROOT = pathlib.Path.home() / ".claude"
KNOWLEDGE_DIR = ROOT / "knowledge" / "github-trending"
SKILLS_DIR = ROOT / "skills"
CONNECTOME_QUERY = ROOT / "scripts" / "query_connectome.py"

BRAIN_TOPIC_VOCAB = {
    "ai", "ml", "llm", "agent", "rag", "embedding", "transformer",
    "cli", "tui", "devtools", "developer-tools",
    "automation", "orchestration", "workflow",
    "observability", "monitoring", "tracing", "metrics", "logging",
    "database", "db", "sql", "vector", "postgres", "sqlite", "duckdb",
    "security", "auth", "secrets", "encryption",
    "cloudflare", "workers", "edge", "serverless",
    "mcp", "model-context-protocol",
}
MCP_KEYWORDS = re.compile(r"\b(mcp|model[- ]context[- ]protocol)\b", re.I)
PATTERN_KEYWORDS = re.compile(
    r"\b(durable object|vector db|sandbox|agent framework|"
    r"retrieval-augmented|RAG|eval framework|evaluation harness)\b",
    re.I,
)
PAID_ALT_KEYWORDS = re.compile(
    r"\b(alternative to|open[- ]source replacement|free alternative)\b", re.I
)
ACTION_VERBS = re.compile(
    r"\b(cli (for|that)|tool (for|that)|automate|generate|extract|sync|"
    r"convert|deploy|publish|monitor|scrape|index|search|analyze)\b", re.I
)

# ──────────────────────────────────────────────────────────────────────────
# Logging (stdlib only, structured)
# ──────────────────────────────────────────────────────────────────────────


def log(level: str, msg: str, **kv) -> None:
    ts = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    extras = " ".join(f"{k}={v!r}" for k, v in kv.items())
    print(f"{ts} [{level}] {msg} {extras}", file=sys.stderr, flush=True)


# ──────────────────────────────────────────────────────────────────────────
# Env loading (mirror supervisor's auto-discover so we work standalone too)
# ──────────────────────────────────────────────────────────────────────────


def _parse_dotenv(p: pathlib.Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not p.is_file():
        return out
    for raw in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.strip().strip('"').strip("'")
        if k.strip() and v:
            out[k.strip()] = v
    return out


def load_env() -> dict[str, str]:
    env = dict(os.environ)
    home = pathlib.Path.home()
    # Site repo path: set BRAIN_SITE_REPO to your local checkout (generic default below).
    repo = pathlib.Path(
        os.environ.get("BRAIN_SITE_REPO", str(home / "Documents" / "github" / "dataqbs_site"))
    )
    for f in [
        repo / "projects" / "real_estate" / ".env",
        repo / "projects" / "dataqbs_site" / ".dev.vars",
        repo / "projects" / "dataqbs_site" / ".env",
        home / "dataqbs-local-cron" / ".env",
    ]:
        for k, v in _parse_dotenv(f).items():
            env.setdefault(k, v)
    return env


# ──────────────────────────────────────────────────────────────────────────
# Data model
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class Candidate:
    source: str                  # "github" | "hn" | "ph" | "tiktok"
    name: str                    # owner/repo or "HN: title" or "PH: name"
    url: str
    description: str
    language: str = ""
    topics: list[str] = field(default_factory=list)
    stars_today: int = 0
    stars_total: int = 0
    last_commit: str = ""
    score_hints: dict = field(default_factory=dict)
    bucket: str = ""             # set by classifier
    # Harmonization action — the OPERATOR INSTRUCTION for this candidate.
    # ADD            — net-new skill, no brain overlap
    # MERGE-WITH:<n> — append section/notes to existing skill <n>
    # REPLACE:<n>    — incumbent <n> deprecated, new one supersedes it
    # EXTEND:<n>     — create subskill under <n> umbrella
    # SKIP           — incumbent covers it, candidate isn't materially better
    action: str = "SKIP"
    best_brain_match: str = "none"
    similarity: float = 0.0
    why_might_beat: str = ""
    llm_verdict: str = ""        # set by LLM gate ("keep" | "drop" | "")


# ──────────────────────────────────────────────────────────────────────────
# Source 1: GitHub trending (HTML scrape)
# ──────────────────────────────────────────────────────────────────────────


class GHTrendingParser(HTMLParser):
    """Parser for github.com/trending. Resilient to minor markup changes."""

    def __init__(self):
        super().__init__()
        self.repos: list[dict] = []
        self._cur: Optional[dict] = None
        self._capture = ""  # text accumulator
        self._capture_target = ""  # which field we're filling

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "article" and "Box-row" in a.get("class", ""):
            self._cur = {"name": "", "description": "", "language": "",
                         "stars_today": 0, "stars_total": 0}
        if self._cur is None:
            return
        if tag == "h2" and "h3" in a.get("class", ""):
            self._capture_target = "name"
            self._capture = ""
        elif tag == "p" and "color-fg-muted" in a.get("class", ""):
            self._capture_target = "description"
            self._capture = ""
        elif tag == "span" and a.get("itemprop") == "programmingLanguage":
            self._capture_target = "language"
            self._capture = ""
        elif tag == "span" and "d-inline-block" in a.get("class", "") and "float-sm-right" in a.get("class", ""):
            self._capture_target = "stars_today"
            self._capture = ""

    def handle_endtag(self, tag):
        if self._cur is None:
            return
        if self._capture_target == "name" and tag == "h2":
            name = re.sub(r"\s+", "", self._capture)
            self._cur["name"] = name
            self._capture_target = ""
        elif self._capture_target == "description" and tag == "p":
            self._cur["description"] = self._capture.strip()
            self._capture_target = ""
        elif self._capture_target == "language" and tag == "span":
            self._cur["language"] = self._capture.strip()
            self._capture_target = ""
        elif self._capture_target == "stars_today" and tag == "span":
            m = re.search(r"([\d,]+)", self._capture)
            if m:
                self._cur["stars_today"] = int(m.group(1).replace(",", ""))
            self._capture_target = ""
        if tag == "article" and self._cur:
            if self._cur.get("name"):
                self.repos.append(self._cur)
            self._cur = None
            self._capture_target = ""

    def handle_data(self, data):
        if self._cur is None or not self._capture_target:
            return
        self._capture += data


def fetch_github_trending(period: str = "daily", top_n: int = 100) -> list[Candidate]:
    """Scrape github.com/trending. Regex-based, resilient to markup changes.

    Strategy: find every repo via the canonical `data-hovercard-type="repository"`
    attribute (stable across UI redesigns), then for each, slice the surrounding
    HTML window to extract description, language, stars-today. Far more robust
    than HTMLParser state-machine which broke on the last UI update."""
    url = f"https://github.com/trending?since={period}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (brain-curation/1.0)",
            "Accept": "text/html",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError) as exc:
        log("ERROR", "github trending fetch failed", err=str(exc))
        return []

    # GitHub removed data-hovercard-type="repository" (verified 2026-05-24).
    # Stable anchor: <article class="Box-row"> blocks. Each contains one repo.
    blocks = re.split(r'<article\s+class="Box-row"', html)[1:]
    if not blocks:
        log("WARN", "github trending: zero <article class=\"Box-row\"> matches — selectors shifted")
        return []

    out: list[Candidate] = []
    seen = set()
    for block in blocks:
        # First /owner/repo href within the block is the repo link.
        m = re.search(r'href="/([a-zA-Z0-9_.-]+/[a-zA-Z0-9._-]+)"', block)
        if not m:
            continue
        name = m.group(1)
        # Reject sub-paths and dotfile noise
        if name.count("/") > 1 or name.endswith(".") or name in seen:
            continue
        seen.add(name)
        window = block[:3000]

        desc = ""
        m = re.search(r'<p[^>]*>(.*?)</p>', window, re.S)
        if m:
            desc = re.sub(r"<[^>]+>", "", m.group(1)).strip()

        lang = ""
        m = re.search(
            r'<span[^>]*itemprop="programmingLanguage"[^>]*>([^<]+)</span>',
            window,
        )
        if m:
            lang = m.group(1).strip()

        stars_today = 0
        # GitHub puts "N stars today/week/month" in a span with class color-fg-muted near a star icon
        m = re.search(r'([\d,]+)\s*stars?\s+(?:today|this week|this month)', window, re.I)
        if m:
            stars_today = int(m.group(1).replace(",", ""))

        out.append(
            Candidate(
                source="github",
                name=name,
                url=f"https://github.com/{name}",
                description=desc,
                language=lang,
                stars_today=stars_today,
            )
        )
    return out


def enrich_github(c: Candidate) -> Candidate:
    """Use `gh api repos/<name>` to fill topics, total stars, last commit."""
    try:
        result = subprocess.run(
            ["gh", "api", f"repos/{c.name}"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return c
        meta = json.loads(result.stdout)
        c.stars_total = int(meta.get("stargazers_count", 0))
        c.topics = list(meta.get("topics") or [])
        c.last_commit = meta.get("pushed_at", "")
        if not c.description and meta.get("description"):
            c.description = meta["description"]
        if not c.language and meta.get("language"):
            c.language = meta["language"]
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        log("WARN", "gh api enrichment failed", repo=c.name, err=str(exc))
    return c


# ──────────────────────────────────────────────────────────────────────────
# Source 2: Hacker News (Firebase API)
# ──────────────────────────────────────────────────────────────────────────


def fetch_hn(top_n: int = 30) -> list[Candidate]:
    base = "https://hacker-news.firebaseio.com/v0"
    try:
        with urllib.request.urlopen(f"{base}/topstories.json", timeout=10) as r:
            ids = json.loads(r.read())[:top_n]
    except (urllib.error.URLError, OSError) as exc:
        log("ERROR", "hn topstories fetch failed", err=str(exc))
        return []

    out: list[Candidate] = []
    for sid in ids:
        try:
            with urllib.request.urlopen(f"{base}/item/{sid}.json", timeout=8) as r:
                item = json.loads(r.read())
        except Exception:
            continue
        title = item.get("title") or ""
        u = item.get("url") or f"https://news.ycombinator.com/item?id={sid}"
        out.append(
            Candidate(
                source="hn",
                name=f"HN: {title[:80]}",
                url=u,
                description=title,
                score_hints={"hn_score": item.get("score", 0), "hn_comments": item.get("descendants", 0)},
            )
        )
    return out


# ──────────────────────────────────────────────────────────────────────────
# Source 3: Product Hunt (page scrape, GraphQL TODO if token set)
# ──────────────────────────────────────────────────────────────────────────


def fetch_producthunt(top_n: int = 20) -> list[Candidate]:
    """Best-effort scrape of producthunt.com homepage. Graceful empty if blocked."""
    url = "https://www.producthunt.com/"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (brain-curation/1.0)",
            "Accept": "text/html",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError) as exc:
        log("INFO", "producthunt fetch skipped (often gated)", err=str(exc))
        return []

    # PH is a JS-heavy app; the homepage embeds initial state in __NEXT_DATA__.
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except Exception:
        return []

    out: list[Candidate] = []
    # Extract any post-like dicts shallowly — PH structure changes frequently.
    def walk(node, depth=0):
        if depth > 6 or len(out) >= top_n:
            return
        if isinstance(node, dict):
            if node.get("__typename") == "Post" and node.get("slug"):
                out.append(
                    Candidate(
                        source="ph",
                        name=f"PH: {node.get('name','')[:80]}",
                        url=f"https://www.producthunt.com/posts/{node['slug']}",
                        description=node.get("tagline") or "",
                        score_hints={"ph_votes": node.get("votesCount", 0)},
                    )
                )
            for v in node.values():
                walk(v, depth + 1)
        elif isinstance(node, list):
            for v in node:
                walk(v, depth + 1)

    walk(data)
    return out


# ──────────────────────────────────────────────────────────────────────────
# Source 4: TikTok tech-curator hashtags (lightweight metadata via yt-dlp)
# ──────────────────────────────────────────────────────────────────────────


TIKTOK_HASHTAGS = ["devtools", "opensource", "ai", "cli", "developer"]


def fetch_tiktok(hashtags: list[str] = None, per_tag: int = 5) -> list[Candidate]:
    """Pull recent top videos from configured TikTok hashtags via yt-dlp metadata.

    Lightweight v1: only metadata (title, description, uploader). No video
    download, no frame extraction. If yt-dlp is missing or TikTok blocks the
    request, returns empty silently (TikTok is a flaky surface).
    """
    hashtags = hashtags or TIKTOK_HASHTAGS
    out: list[Candidate] = []
    if not subprocess.run(["which", "yt-dlp"], capture_output=True).returncode == 0:
        log("INFO", "yt-dlp not present — skipping TikTok source")
        return out
    for tag in hashtags:
        url = f"https://www.tiktok.com/tag/{tag}"
        try:
            res = subprocess.run(
                [
                    "yt-dlp", "--flat-playlist", "--skip-download",
                    "--no-warnings", "--quiet",
                    "--print", "%(title)s ||| %(description)s ||| %(uploader)s ||| %(webpage_url)s",
                    "--playlist-end", str(per_tag),
                    url,
                ],
                capture_output=True, text=True, timeout=30,
            )
        except subprocess.TimeoutExpired:
            log("WARN", "tiktok yt-dlp timeout", tag=tag)
            continue
        if res.returncode != 0:
            log("INFO", "tiktok yt-dlp returned non-zero", tag=tag, code=res.returncode)
            continue
        for line in res.stdout.splitlines():
            parts = line.split(" ||| ")
            if len(parts) < 4:
                continue
            title, desc, uploader, video_url = parts[0], parts[1], parts[2], parts[3]
            # TikTok descriptions often pack value: project name + URL + hashtags.
            # Keep both title and description as the candidate's text body.
            text = f"{title} — {desc}".strip(" —")
            out.append(
                Candidate(
                    source="tiktok",
                    name=f"TT[{tag}] @{uploader}: {title[:60]}",
                    url=video_url,
                    description=text[:300],
                    topics=[tag],
                    score_hints={"hashtag": tag, "uploader": uploader},
                )
            )
    return out


# ──────────────────────────────────────────────────────────────────────────
# Classifier (heuristics)
# ──────────────────────────────────────────────────────────────────────────


def query_connectome(text: str) -> tuple[str, float]:
    """Returns (best_skill_name, similarity_score) via existing brain script."""
    if not CONNECTOME_QUERY.is_file():
        return ("none", 0.0)
    try:
        result = subprocess.run(
            ["python3", str(CONNECTOME_QUERY), "query", text[:500]],
            capture_output=True, text=True, timeout=10,
        )
    except subprocess.TimeoutExpired:
        return ("none", 0.0)
    if result.returncode != 0:
        return ("none", 0.0)
    # Parse first SKILLS row: "    skill-name — score: X.Y, connections: N"
    for line in result.stdout.splitlines():
        m = re.match(r"\s+(\S[^—]*)— score: ([\d.]+)", line)
        if m and "SKILLS" not in line:
            return (m.group(1).strip(), float(m.group(2)))
    return ("none", 0.0)


def classify(
    c: Candidate,
    similarity_threshold_low: float = 0.25,
    similarity_threshold_high: float = 0.55,
    beat_factor_stars: float = 2.0,
) -> Candidate:
    """Assign bucket + harmonization action. Mutates c.

    Action decision tree (this is the brain integration model, per
    operator instruction: "no sólo agregar, armonizar/homologar/integrar"):

    similarity < 0.25       → ADD               (no overlap, net-new)
    0.25 <= sim < 0.55      → EXTEND or MERGE-WITH
                              (real overlap but candidate brings new angle)
    sim >= 0.55             → REPLACE (if stars × beat_factor > incumbent)
                              or SKIP (incumbent good enough)
    """
    text = f"{c.name} {c.description} {' '.join(c.topics)}"
    best, score = query_connectome(c.description or c.name)
    c.best_brain_match, c.similarity = best, score

    # Bucket (taxonomy of what KIND of thing this is)
    if MCP_KEYWORDS.search(text):
        c.bucket = "mcp-candidate"
    elif PAID_ALT_KEYWORDS.search(c.description):
        c.bucket = "paid-alternative"
    elif PATTERN_KEYWORDS.search(text):
        c.bucket = "pattern-reference"
    elif ACTION_VERBS.search(c.description) and any(
        t in BRAIN_TOPIC_VOCAB for t in c.topics + [c.language.lower()]
    ):
        c.bucket = "skill-candidate"
    else:
        c.bucket = "SKIP"
        c.action = "SKIP"
        c.why_might_beat = "no brain-fit signal (no MCP/paid-alt/pattern/skill markers)"
        return c

    # Action (operator instruction — HOW to integrate)
    if score < similarity_threshold_low:
        c.action = "ADD"
        c.why_might_beat = f"net-new capability (closest brain match `{best}` at score={score:.2f}, below 0.25 floor)"
    elif score < similarity_threshold_high:
        # Real overlap but not a duplicate. Heuristic: pattern-reference
        # extends; skill/mcp/paid-alt merges. Operator can override.
        if c.bucket == "pattern-reference":
            c.action = f"EXTEND:{best}"
            c.why_might_beat = f"adjacent pattern to `{best}` (score={score:.2f}) — extends, doesn't replace"
        else:
            c.action = f"MERGE-WITH:{best}"
            c.why_might_beat = f"overlaps `{best}` (score={score:.2f}) — merge to consolidate; don't fragment"
    else:
        # Strong overlap. Replace only if clearly better; otherwise skip.
        incumbent_proxy_stars = 100
        if c.stars_total >= beat_factor_stars * incumbent_proxy_stars:
            c.action = f"REPLACE:{best}"
            c.why_might_beat = (
                f"strong overlap with `{best}` (score={score:.2f}), "
                f"but {c.stars_total:,} stars suggest the candidate is more mature; "
                "consider deprecating incumbent"
            )
        else:
            c.action = "SKIP"
            c.bucket = "SKIP"
            c.why_might_beat = f"covered by `{best}` (score={score:.2f}); candidate not materially better"
    return c


# ──────────────────────────────────────────────────────────────────────────
# LLM QA gate (Groq)
# ──────────────────────────────────────────────────────────────────────────


def llm_qa_gate(candidates: list[Candidate], groq_key: str) -> list[Candidate]:
    """Final pass: ask Groq llama-3.3-70b-versatile to drop low-value entries."""
    survivors = [c for c in candidates if c.bucket != "SKIP"]
    if not survivors:
        return candidates

    # Batch the call: one prompt with all survivors as a numbered list.
    items = "\n".join(
        f"{i+1}. [{c.bucket}] {c.name} — {c.description[:120]}"
        for i, c in enumerate(survivors)
    )
    prompt = (
        "You are a curator for an AI agent's brain (a personal skill/MCP "
        "registry). Decide for each item whether it should pass the gate "
        "and reach the operator's morning digest, or be dropped as noise.\n\n"
        "Criteria for KEEP: actually new capability, well-described, not a "
        "demo/tutorial, looks production-grade.\n"
        "Criteria for DROP: vague description, joke/gag repo, obvious clone, "
        "tutorial/learning material with no reusable artifact.\n\n"
        f"Items:\n{items}\n\n"
        "Respond with exactly N lines (where N = number of items), each line "
        "either 'KEEP <reason>' or 'DROP <reason>'. Use the same item order. "
        "Keep reasons to <= 12 words."
    )

    body = json.dumps({
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": "You are a terse curation gate. Respond exactly N lines, KEEP or DROP per item."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "max_tokens": 1500,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {groq_key}",
            "Content-Type": "application/json",
            # Groq's API sits behind Cloudflare, which 403s the default
            # `Python-urllib/x.y` UA with "error code: 1010" (browser-signature
            # ban). A browser-like UA gets through. Verified 2026-05-24.
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) brain-curation/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, OSError) as exc:
        log("WARN", "groq llm gate failed; surfacing heuristic survivors as-is", err=str(exc))
        return candidates

    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    verdicts = [line.strip() for line in content.splitlines() if line.strip()]
    for i, v in enumerate(verdicts[: len(survivors)]):
        up = v.upper()
        if up.startswith("DROP"):
            survivors[i].bucket = "SKIP"
            survivors[i].llm_verdict = v
        elif up.startswith("KEEP"):
            survivors[i].llm_verdict = v
    return candidates


# ──────────────────────────────────────────────────────────────────────────
# Markdown writer
# ──────────────────────────────────────────────────────────────────────────


BUCKET_ORDER = ["skill-candidate", "mcp-candidate", "pattern-reference", "paid-alternative"]
BUCKET_LABELS = {
    "skill-candidate": "Skill candidates",
    "mcp-candidate": "MCP candidates",
    "pattern-reference": "Pattern references",
    "paid-alternative": "Paid-tool alternatives",
}


def render_markdown(date: str, candidates: list[Candidate]) -> str:
    survivors = [c for c in candidates if c.bucket != "SKIP"]
    by_bucket: dict[str, list[Candidate]] = {b: [] for b in BUCKET_ORDER}
    for c in survivors:
        by_bucket.setdefault(c.bucket, []).append(c)

    counts = {b: len(by_bucket.get(b, [])) for b in BUCKET_ORDER}
    counts_line = ", ".join(f"{b}={counts[b]}" for b in BUCKET_ORDER)

    lines = [
        f"# GitHub Trending Curation — {date}",
        "",
        f"**Scanned:** {len(candidates)}  ·  **Surfaced:** {len(survivors)}  ·  **{counts_line}**",
        "**Sources:** github.com/trending (daily) + HN top-30 + Product Hunt today",
        "",
        "---",
        "",
    ]
    if not survivors:
        lines.append("_No signal today — every trending repo was either covered by an existing brain skill or didn't pass the value gate._")
        lines.append("")
        return "\n".join(lines)

    for b in BUCKET_ORDER:
        items = by_bucket.get(b, [])
        if not items:
            continue
        lines.append(f"## {BUCKET_LABELS[b]} ({len(items)})")
        lines.append("")
        for i, c in enumerate(items, 1):
            star = f"★ +{c.stars_today}" if c.source == "github" and c.stars_today else ""
            total = f"({c.stars_total:,} total)" if c.stars_total else ""
            lines.append(f"### {i}. `{c.name}` {star} {total}".rstrip())
            lines.append(f"- **Source:** {c.source.upper()}  ·  **Language:** {c.language or '?'}  ·  **Topics:** {', '.join(c.topics) or '—'}")
            if c.description:
                lines.append(f"- **Description:** {c.description}")
            lines.append(f"- **URL:** {c.url}")
            lines.append(f"- **Best brain match:** {c.best_brain_match} (similarity={c.similarity:.2f})")
            lines.append(f"- **Action:** `{c.action}`")
            lines.append(f"- **Rationale:** {c.why_might_beat}")
            if c.llm_verdict:
                lines.append(f"- **LLM verdict:** {c.llm_verdict}")
            lines.append("")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("**Next step:** review entries, then `/trending-promote <date> <repo>` for each keeper.")
    lines.append("")
    return "\n".join(lines)


def write_markdown(date: str, body: str, dry_run: bool = False) -> pathlib.Path:
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    out = KNOWLEDGE_DIR / f"{date}.md"
    if dry_run:
        log("INFO", "dry-run: skipping markdown write", path=str(out))
        return out
    out.write_text(body, encoding="utf-8")
    log("INFO", "markdown written", path=str(out), bytes=len(body))
    return out


# ──────────────────────────────────────────────────────────────────────────
# Notion writer
# ──────────────────────────────────────────────────────────────────────────


def write_notion(date: str, body: str, env: dict[str, str], dry_run: bool = False) -> bool:
    token = env.get("NOTION_TOKEN")
    parent = env.get("NOTION_CURATION_PARENT_PAGE_ID")
    if not token:
        log("INFO", "NOTION_TOKEN not set — skipping Notion writer")
        return False
    if not parent:
        log("WARN", "NOTION_TOKEN set but NOTION_CURATION_PARENT_PAGE_ID missing — skipping Notion writer")
        return False
    if dry_run:
        log("INFO", "dry-run: skipping notion write")
        return True

    # Notion API: create a child page under parent. Use plain text blocks; Markdown
    # rendering isn't supported, so we ship the body as a `code` block (mono font,
    # preserves Markdown for the operator to copy/paste anywhere).
    payload = {
        "parent": {"page_id": parent},
        "properties": {
            "title": [{"text": {"content": f"GH Trending — {date}"}}]
        },
        "children": [
            {
                "object": "block",
                "type": "code",
                "code": {
                    "rich_text": [{"type": "text", "text": {"content": body[:2000]}}],
                    "language": "markdown",
                },
            }
        ],
    }
    # Notion code blocks cap at 2000 chars per rich_text; chunk if longer.
    chunks = [body[i : i + 1900] for i in range(0, len(body), 1900)]
    payload["children"] = [
        {
            "object": "block",
            "type": "code",
            "code": {
                "rich_text": [{"type": "text", "text": {"content": chunk}}],
                "language": "markdown",
            },
        }
        for chunk in chunks
    ]
    req = urllib.request.Request(
        "https://api.notion.com/v1/pages",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
        log("INFO", "notion page created", id=data.get("id", "?"))
        return True
    except (urllib.error.URLError, OSError, urllib.error.HTTPError) as exc:
        log("ERROR", "notion write failed", err=str(exc))
        return False


# ──────────────────────────────────────────────────────────────────────────
# Main orchestration
# ──────────────────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat(),
                    help="ISO date YYYY-MM-DD (default today)")
    ap.add_argument("--dry-run", action="store_true",
                    help="don't write outputs, just print")
    ap.add_argument("--no-llm", action="store_true",
                    help="skip Groq QA gate (heuristic-only)")
    args = ap.parse_args()

    try:
        dt.date.fromisoformat(args.date)
    except ValueError:
        log("ERROR", "bad --date format, expected YYYY-MM-DD")
        return 2

    env = load_env()

    # Parallel fetch (4 sources)
    sources = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(fetch_github_trending, "daily", 100): "github",
            pool.submit(fetch_hn, 30): "hn",
            pool.submit(fetch_producthunt, 20): "ph",
            pool.submit(fetch_tiktok): "tiktok",
        }
        for fut in as_completed(futures, timeout=120):
            name = futures[fut]
            try:
                items = fut.result()
                log("INFO", f"{name} fetched", count=len(items))
                sources.extend(items)
            except Exception as exc:
                log("WARN", f"{name} source failed", err=str(exc))

    if not sources:
        log("ERROR", "all sources empty; aborting")
        body = render_markdown(args.date, [])
        write_markdown(args.date, body, args.dry_run)
        return 1

    # Enrich GH entries (gh api) — sequential to avoid rate spikes
    enriched: list[Candidate] = []
    for c in sources:
        if c.source == "github":
            c = enrich_github(c)
        enriched.append(c)

    # Classify
    for c in enriched:
        classify(c)

    log("INFO", "post-heuristic counts", **{
        b: sum(1 for c in enriched if c.bucket == b) for b in BUCKET_ORDER + ["SKIP"]
    })

    # LLM gate
    if not args.no_llm and env.get("GROQ_API_KEY"):
        enriched = llm_qa_gate(enriched, env["GROQ_API_KEY"])
        log("INFO", "post-LLM counts", **{
            b: sum(1 for c in enriched if c.bucket == b) for b in BUCKET_ORDER + ["SKIP"]
        })

    # Render + write
    body = render_markdown(args.date, enriched)
    write_markdown(args.date, body, args.dry_run)
    write_notion(args.date, body, env, args.dry_run)

    # Machine-readable sidecar — ALL candidates (incl SKIP + reasons) so the
    # autopromote step can build the cumulative HISTORY.md audit ledger and
    # the operator can later ask "why did you ignore X?".
    if not args.dry_run:
        sidecar = KNOWLEDGE_DIR / f"{args.date}.json"
        try:
            sidecar.write_text(json.dumps({
                "date": args.date,
                "scanned": len(enriched),
                "candidates": [asdict(c) for c in enriched],
            }, ensure_ascii=False, indent=0), encoding="utf-8")
            log("INFO", "sidecar written", path=str(sidecar))
        except Exception as exc:
            log("WARN", "sidecar write failed", err=str(exc))

    if args.dry_run:
        print(body)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log("FATAL", "unhandled exception", err=str(exc))
        sys.exit(3)
