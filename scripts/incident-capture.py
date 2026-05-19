#!/usr/bin/env python3
"""
incident-capture.py — Port 6 (Phase D) helper.

Generates a structured incident markdown file from parsed answers.
Called by the /incident-capture slash command (which collects the
answers interactively from the operator).

Output: ~/.claude/incidents/<YYYY-MM-DD>-<slug>.md (gitignored).

Usage:
  python3 ~/.claude/scripts/incident-capture.py \
    --headline "Redo Multireach fix because cache key collision" \
    --expected "Cache key isolates per channel" \
    --actual "Two channels shared the same key, second overwrote first" \
    --cause "Forgot to include channel_id in cache key derivation" \
    --severity medium \
    --session-id <claude-code-session-uuid>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

INCIDENTS_DIR = Path.home() / ".claude" / "incidents"
TRACES_DIR = Path.home() / ".claude" / "traces"

SEVERITY_LEVELS = ("low", "medium", "high", "critical")


def slugify(text: str, max_len: int = 40) -> str:
    text = text.lower().strip()
    # Drop non-ascii letters: replace accents with bare letter via NFKD
    import unicodedata
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:max_len].rstrip("-")


def task_id_from_session(session_id: str) -> str:
    return hashlib.sha1(session_id.encode("utf-8")).hexdigest()


def trace_excerpt_for(task_id: str, max_lines: int = 30) -> str:
    """Return a small markdown-friendly excerpt of trace records matching this task_id."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    f = TRACES_DIR / f"{today}.jsonl"
    if not f.exists():
        return "_(no trace file for today)_"
    matches: list[dict] = []
    try:
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("task_id") == task_id:
                matches.append(rec)
                if len(matches) >= max_lines:
                    break
    except OSError:
        return "_(could not read trace file)_"
    if not matches:
        return f"_(no trace records matched task_id={task_id})_"
    out = ["```jsonl"]
    out.extend(json.dumps(r, ensure_ascii=False) for r in matches)
    out.append("```")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Write a structured incident markdown.")
    p.add_argument("--headline", required=True, help="One-line incident summary")
    p.add_argument("--expected", required=True, help="What you expected")
    p.add_argument("--actual", required=True, help="What actually happened")
    p.add_argument("--cause", required=True, help="Suspected root cause")
    p.add_argument(
        "--severity",
        choices=SEVERITY_LEVELS,
        default="medium",
        help="Severity level (default: medium)",
    )
    p.add_argument(
        "--trigger",
        choices=("manual", "watchdog", "slo", "diligent"),
        default="manual",
        help="What triggered the capture (default: manual)",
    )
    p.add_argument(
        "--session-id",
        default="",
        help="Claude Code session UUID for trace cross-link",
    )
    p.add_argument(
        "--lessons",
        default="",
        help="Optional 'lessons learned' (also distillable into feedback memory)",
    )
    args = p.parse_args(argv)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    slug = slugify(args.headline)
    if not slug:
        sys.stderr.write("✗ Could not derive slug from headline\n")
        return 2

    incident_id = f"{today}-{slug}"
    task_id = task_id_from_session(args.session_id) if args.session_id else ""
    trace_section = trace_excerpt_for(task_id) if task_id else "_(no session_id provided)_"

    INCIDENTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = INCIDENTS_DIR / f"{incident_id}.md"

    body = f"""---
incident_id: {incident_id}
date: {today}
severity: {args.severity}
trigger: {args.trigger}
task_id: {task_id or "n/a"}
related_traces: traces/{today}.jsonl
status: open
---

# Incident: {args.headline}

## What happened
{args.headline}

## What we expected
{args.expected}

## What actually happened
{args.actual}

## Suspected root cause
{args.cause}

## Trace excerpt
{trace_section}

## Lessons learned
{args.lessons or "_(to be distilled into a feedback memory entry — see follow-up actions)_"}

## Remediation actions
_(captured via TaskCreate by the slash command — list mirrored here for the post-mortem reader)_
"""
    out_path.write_text(body, encoding="utf-8")
    print(f"✓ Wrote {out_path}")
    print(f"  incident_id: {incident_id}")
    print(f"  severity: {args.severity}")
    print(f"  task_id: {task_id or 'n/a'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
