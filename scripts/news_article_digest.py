#!/usr/bin/env python3
"""
AI News & Blogs Daily Curation — feeds the brain (sibling of github_trending_digest).

Pulls recent items from a watchlist of AI news/blog RSS+Atom feeds, classifies
each into brain-fit buckets via heuristics + optional Groq LLM QA gate, and writes
the digest to Markdown + a JSON sidecar under
`~/.claude/knowledge/news-articles/<date>.{md,json}`.

This is the INBOUND half of the loop: blog feeds (things we COULD learn) get
distilled into skill candidates the operator can promote. The OUTBOUND half
(brain skill -> published news article) already exists in the dataqbs arm.
Promote a keeper with `/news-promote <date> "<title-substring>"`.

Stdlib only. No feedparser dependency (RSS + Atom parsed with xml.etree) so the
script runs on any machine without `pip install`.

Usage:
    python3 news_article_digest.py                 # today
    python3 news_article_digest.py --date 2026-06-08
    python3 news_article_digest.py --dry-run       # print, don't write
    python3 news_article_digest.py --no-llm        # skip Groq QA gate

Env vars consumed (auto-loaded from project .env files, same as trending):
    GROQ_API_KEY    (optional, enables LLM QA gate)

Exit codes:
     0  digest written (may be "no signal")
     1  every feed failed AND no survivors
     2  config error (bad --date)
     3  unexpected fatal error
"""
from __future__ import annotations

import argparse
import datetime as dt
import html as htmlmod
import json
import os
import pathlib
import re
import subprocess
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from email.utils import parsedate_to_datetime
from typing import Optional

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# ──────────────────────────────────────────────────────────────────────────
# Paths & constants
# ──────────────────────────────────────────────────────────────────────────

ROOT = pathlib.Path.home() / ".claude"
KNOWLEDGE_DIR = ROOT / "knowledge" / "news-articles"
SKILL_DIR = ROOT / "skills" / "news-article-curation"
CONNECTOME_QUERY = ROOT / "scripts" / "query_connectome.py"

# Seed list — mirrors the dataqbs blog `sources.json`. The brain fetches these
# itself; it does NOT reach into the arm (brain stays independent of any arm).
DEFAULT_FEEDS = [
    {"id": "simonwillison", "name": "Simon Willison", "url": "https://simonwillison.net/atom/everything/"},
    {"id": "openai", "name": "OpenAI Blog", "url": "https://openai.com/blog/rss.xml"},
    {"id": "deepmind", "name": "Google DeepMind", "url": "https://deepmind.google/blog/rss.xml"},
    {"id": "googleai", "name": "Google AI Blog", "url": "https://blog.google/innovation-and-ai/technology/ai/rss/"},
    {"id": "latentspace", "name": "Latent Space", "url": "https://www.latent.space/feed"},
    {"id": "mittr", "name": "MIT Technology Review", "url": "https://www.technologyreview.com/feed/"},
    {"id": "techcrunch", "name": "TechCrunch AI", "url": "https://techcrunch.com/category/artificial-intelligence/feed/"},
    {"id": "arstechnica", "name": "Ars Technica AI", "url": "https://arstechnica.com/ai/feed/"},
    {"id": "theverge", "name": "The Verge AI", "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"},
    {"id": "arxiv", "name": "arXiv cs.AI", "url": "http://arxiv.org/rss/cs.AI"},
]

# Brain-fit vocabulary — overlap signal that an article is on-topic for us.
BRAIN_TOPIC_VOCAB = {
    "ai", "ml", "llm", "agent", "agentic", "rag", "embedding", "transformer",
    "prompt", "inference", "fine-tuning", "fine tuning", "eval", "evaluation",
    "cli", "tui", "devtools", "developer tools",
    "automation", "orchestration", "workflow",
    "observability", "monitoring", "tracing", "metrics", "logging",
    "database", "sql", "vector", "postgres", "sqlite", "duckdb",
    "security", "auth", "secrets", "encryption",
    "cloudflare", "workers", "edge", "serverless",
    "mcp", "model context protocol",
    "cost", "token", "finops", "budget", "pricing",
}
MCP_KEYWORDS = re.compile(r"\b(mcp|model[- ]context[- ]protocol)\b", re.I)
PATTERN_KEYWORDS = re.compile(
    r"\b(durable object|vector db|sandbox|agent framework|"
    r"retrieval-augmented|RAG|eval framework|evaluation harness|architecture|"
    r"design pattern|scaling|distributed)\b",
    re.I,
)
PAID_ALT_KEYWORDS = re.compile(
    r"\b(alternative to|open[- ]source replacement|free alternative)\b", re.I
)
LESSON_KEYWORDS = re.compile(
    r"\b(how (to|we)|guide|lessons?|deep[- ]dive|post[- ]?mortem|we built|"
    r"building|benchmark|optimi[sz]|gotcha|pitfall|best practices|playbook|"
    r"case study|under the hood|debugging|teardown|breakdown)\b",
    re.I,
)
TOOL_KEYWORDS = re.compile(
    r"\b(introducing|announc|launch|releas|open[- ]sourc|now available|"
    r"ships?|unveil|we['’]re releasing)\b",
    re.I,
)

# ──────────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────────


def log(level: str, msg: str, **kv) -> None:
    ts = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    extras = " ".join(f"{k}={v!r}" for k, v in kv.items())
    print(f"{ts} [{level}] {msg} {extras}", file=sys.stderr, flush=True)


# ──────────────────────────────────────────────────────────────────────────
# Env loading (mirror trending digest so we work standalone)
# ──────────────────────────────────────────────────────────────────────────


def _parse_dotenv(p: pathlib.Path) -> dict:
    out: dict = {}
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


def load_env() -> dict:
    env = dict(os.environ)
    home = pathlib.Path.home()
    repo = pathlib.Path(
        os.environ.get("BRAIN_SITE_REPO", str(home / "Documents" / "github" / "dataqbs_site"))
    )
    for f in [
        repo / "projects" / "dataqbs_site" / ".dev.vars",
        repo / "projects" / "dataqbs_site" / ".env",
        home / "dataqbs-local-cron" / ".env",
    ]:
        for k, v in _parse_dotenv(f).items():
            env.setdefault(k, v)
    return env


# ──────────────────────────────────────────────────────────────────────────
# Data model (identical schema to trending so /news-promote can consume it)
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class Candidate:
    source: str
    name: str
    url: str
    description: str
    language: str = ""
    topics: list = field(default_factory=list)
    stars_today: int = 0
    stars_total: int = 0
    last_commit: str = ""          # reused as published date for articles
    score_hints: dict = field(default_factory=dict)
    bucket: str = ""
    action: str = "SKIP"
    best_brain_match: str = "none"
    similarity: float = 0.0
    why_might_beat: str = ""
    llm_verdict: str = ""


# ──────────────────────────────────────────────────────────────────────────
# Feed fetch + parse (RSS + Atom, namespace-agnostic, stdlib only)
# ──────────────────────────────────────────────────────────────────────────


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _strip_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s or "")
    return htmlmod.unescape(s).strip()


def _parse_date(s: str) -> Optional[dt.datetime]:
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)
        if d is not None:
            return d
    except (TypeError, ValueError, IndexError):
        pass
    try:
        return dt.datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def fetch_feed(feed: dict, per_feed: int = 8, recency_days: int = 4) -> list:
    url = feed["url"]
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) brain-curation/1.0",
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
    except (urllib.error.URLError, OSError) as exc:
        log("WARN", "feed fetch failed", feed=feed["id"], err=str(exc))
        return []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        log("WARN", "feed parse failed", feed=feed["id"], err=str(exc))
        return []

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=recency_days)
    nodes = [e for e in root.iter() if _localname(e.tag) in ("item", "entry")]
    items: list = []
    for node in nodes:
        title = link = summary = pub = ""
        for ch in list(node):
            ln = _localname(ch.tag)
            if ln == "title" and not title:
                title = (ch.text or "").strip()
            elif ln == "link":
                href = ch.get("href")
                rel = ch.get("rel", "alternate")
                if href:
                    if rel in ("alternate", "") and not link:
                        link = href
                elif ch.text and not link:
                    link = ch.text.strip()
            elif ln in ("summary", "description", "content") and not summary:
                summary = _strip_html(ch.text or "")
            elif ln in ("pubDate", "published", "updated", "date") and not pub:
                pub = (ch.text or "").strip()
        if not title and not link:
            continue
        d = _parse_date(pub)
        if d is not None:
            if d.tzinfo is None:
                d = d.replace(tzinfo=dt.timezone.utc)
            if d < cutoff:
                continue
        items.append((
            d,
            Candidate(
                source=feed["id"],
                name=(title[:140] or link),
                url=(link or url),
                description=summary[:400],
                last_commit=pub,
            ),
        ))
    _floor = dt.datetime.min.replace(tzinfo=dt.timezone.utc)
    items.sort(key=lambda t: (t[0] is not None, t[0] or _floor), reverse=True)
    return [c for _, c in items[:per_feed]]


def load_feeds() -> list:
    fpath = SKILL_DIR / "feeds.yaml"
    if fpath.is_file():
        try:
            import yaml
            data = yaml.safe_load(fpath.read_text(encoding="utf-8"))
            feeds = data.get("feeds") if isinstance(data, dict) else data
            out = []
            for f in feeds or []:
                if f.get("enabled", True) and f.get("url"):
                    out.append({"id": f.get("id") or f["url"], "name": f.get("name", ""), "url": f["url"]})
            if out:
                return out
        except Exception as exc:
            log("WARN", "feeds.yaml parse failed; using builtin defaults", err=str(exc))
    return DEFAULT_FEEDS


# ──────────────────────────────────────────────────────────────────────────
# Classifier
# ──────────────────────────────────────────────────────────────────────────


def query_connectome(text: str) -> tuple:
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
    # query_connectome prints the AGENTS block FIRST, then SKILLS. We dedup
    # against existing SKILLS (capabilities), not agent personas, so gate on
    # the SKILLS header before parsing the first "— score:" row.
    in_skills = False
    for line in result.stdout.splitlines():
        if "SKILLS (" in line:
            in_skills = True
            continue
        if not in_skills:
            continue
        m = re.match(r"\s+(\S[^—]*)— score: ([\d.]+)", line)
        if m:
            return (m.group(1).strip(), float(m.group(2)))
    return ("none", 0.0)


def classify(
    c: Candidate,
    similarity_threshold_low: float = 0.25,
    similarity_threshold_high: float = 0.55,
) -> Candidate:
    """Assign bucket + harmonization action (ADD/MERGE/EXTEND/SKIP) for an article."""
    text = f"{c.name} {c.description}"
    low = text.lower()
    best, score = query_connectome(c.description or c.name)
    c.best_brain_match, c.similarity = best, score
    has_topic = any(t in low for t in BRAIN_TOPIC_VOCAB)

    if MCP_KEYWORDS.search(text):
        c.bucket = "mcp-candidate"
    elif PAID_ALT_KEYWORDS.search(text):
        c.bucket = "paid-alternative"
    elif PATTERN_KEYWORDS.search(text) and has_topic:
        c.bucket = "pattern-reference"
    elif LESSON_KEYWORDS.search(text) and has_topic:
        c.bucket = "lesson-candidate"
    elif TOOL_KEYWORDS.search(text) and has_topic:
        c.bucket = "tool-mention"
    else:
        c.bucket = "SKIP"
        c.action = "SKIP"
        c.why_might_beat = "no learning signal (no lesson/tool/pattern/mcp marker, or off-topic)"
        return c

    if score < similarity_threshold_low:
        c.action = "ADD"
        c.why_might_beat = f"net-new learning (closest brain match `{best}` at score={score:.2f}, below 0.25 floor)"
    elif score < similarity_threshold_high:
        if c.bucket == "pattern-reference":
            c.action = f"EXTEND:{best}"
            c.why_might_beat = f"adjacent pattern to `{best}` (score={score:.2f}) — extends, doesn't replace"
        else:
            c.action = f"MERGE-WITH:{best}"
            c.why_might_beat = f"overlaps `{best}` (score={score:.2f}) — merge to consolidate; don't fragment"
    else:
        c.action = "SKIP"
        c.bucket = "SKIP"
        c.why_might_beat = f"covered by `{best}` (score={score:.2f}); article adds no new reusable artifact"
    return c


# ──────────────────────────────────────────────────────────────────────────
# LLM QA gate (Groq) — article-aware prompt
# ──────────────────────────────────────────────────────────────────────────


def llm_qa_gate(candidates: list, groq_key: str) -> list:
    survivors = [c for c in candidates if c.bucket != "SKIP"]
    if not survivors:
        return candidates
    items = "\n".join(
        f"{i+1}. [{c.bucket}] {c.name} — {c.description[:140]}"
        for i, c in enumerate(survivors)
    )
    prompt = (
        "You are a curator for an AI agent's brain (a personal skill registry). "
        "Each item is a news/blog ARTICLE. Decide whether it teaches something "
        "reusable worth distilling into a skill, or is just news/opinion.\n\n"
        "KEEP: teaches a concrete technique, pattern, gotcha, benchmark, or a "
        "production-grade tool the operator could turn into a reusable skill.\n"
        "DROP: pure announcement with no how, funding/PR news, opinion piece, "
        "vague, or already obvious.\n\n"
        f"Items:\n{items}\n\n"
        "Respond with exactly N lines (N = number of items), same order, each "
        "either 'KEEP <reason>' or 'DROP <reason>'. Reasons <= 12 words."
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

BUCKET_ORDER = ["lesson-candidate", "tool-mention", "pattern-reference", "paid-alternative", "mcp-candidate"]
BUCKET_LABELS = {
    "lesson-candidate": "Lesson candidates (a technique worth a skill)",
    "tool-mention": "Tool mentions (could become a skill / MCP)",
    "pattern-reference": "Pattern references",
    "paid-alternative": "Paid-tool alternatives",
    "mcp-candidate": "MCP candidates",
}


def render_markdown(date: str, candidates: list, feeds: list) -> str:
    survivors = [c for c in candidates if c.bucket != "SKIP"]
    by_bucket: dict = {b: [] for b in BUCKET_ORDER}
    for c in survivors:
        by_bucket.setdefault(c.bucket, []).append(c)
    counts = {b: len(by_bucket.get(b, [])) for b in BUCKET_ORDER}
    counts_line = ", ".join(f"{b}={counts[b]}" for b in BUCKET_ORDER)

    lines = [
        f"# AI News & Blogs Curation — {date}",
        "",
        f"**Scanned:** {len(candidates)}  ·  **Surfaced:** {len(survivors)}  ·  **{counts_line}**",
        f"**Feeds:** {len(feeds)} ({', '.join(f['id'] for f in feeds)})",
        "",
        "---",
        "",
    ]
    if not survivors:
        lines.append("_No learning signal today — every recent article was either covered by an existing brain skill or carried no reusable technique._")
        lines.append("")
        return "\n".join(lines)

    for b in BUCKET_ORDER:
        bitems = by_bucket.get(b, [])
        if not bitems:
            continue
        lines.append(f"## {BUCKET_LABELS[b]} ({len(bitems)})")
        lines.append("")
        for i, c in enumerate(bitems, 1):
            lines.append(f"### {i}. {c.name}")
            lines.append(f"- **Source:** {c.source}  ·  **Published:** {c.last_commit or '?'}")
            if c.description:
                lines.append(f"- **Summary:** {c.description}")
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
    lines.append('**Next step:** review entries, then `/news-promote ' + date + ' "<title-substring>"` for each keeper. The action field tells you whether to ADD a new skill or MERGE/EXTEND an existing one (harmonize, don\'t accrete).')
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
# Main
# ──────────────────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat(), help="ISO date YYYY-MM-DD")
    ap.add_argument("--dry-run", action="store_true", help="don't write outputs, just print")
    ap.add_argument("--no-llm", action="store_true", help="skip Groq QA gate")
    args = ap.parse_args()

    try:
        dt.date.fromisoformat(args.date)
    except ValueError:
        log("ERROR", "bad --date format, expected YYYY-MM-DD")
        return 2

    env = load_env()
    feeds = load_feeds()
    log("INFO", "feeds loaded", count=len(feeds))

    sources: list = []
    failures = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(fetch_feed, f): f["id"] for f in feeds}
        for fut in as_completed(futures, timeout=120):
            fid = futures[fut]
            try:
                items = fut.result()
                log("INFO", f"{fid} fetched", count=len(items))
                if not items:
                    failures += 1
                sources.extend(items)
            except Exception as exc:
                failures += 1
                log("WARN", f"{fid} feed failed", err=str(exc))

    if not sources:
        log("ERROR", "all feeds empty; aborting")
        body = render_markdown(args.date, [], feeds)
        write_markdown(args.date, body, args.dry_run)
        return 1

    for c in sources:
        classify(c)

    log("INFO", "post-heuristic counts", **{
        b: sum(1 for c in sources if c.bucket == b) for b in BUCKET_ORDER + ["SKIP"]
    })

    if not args.no_llm and env.get("GROQ_API_KEY"):
        sources = llm_qa_gate(sources, env["GROQ_API_KEY"])
        log("INFO", "post-LLM counts", **{
            b: sum(1 for c in sources if c.bucket == b) for b in BUCKET_ORDER + ["SKIP"]
        })

    body = render_markdown(args.date, sources, feeds)
    write_markdown(args.date, body, args.dry_run)

    if not args.dry_run:
        sidecar = KNOWLEDGE_DIR / f"{args.date}.json"
        try:
            sidecar.write_text(json.dumps({
                "date": args.date,
                "scanned": len(sources),
                "candidates": [asdict(c) for c in sources],
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
