#!/usr/bin/env python3
"""
anthropic-analytics-pull.py — FinOps Feature 4.

Pulls Anthropic's organization-level usage report (Enterprise / Admin
API) and writes it to ~/.claude/analytics/anthropic-<YYYY-MM-DD>.jsonl
so brain-digest can reconcile *estimated* USD (from session JSONLs +
list-price math) against *actual billed* USD (from Anthropic).

Reads:
  - $ANTHROPIC_ADMIN_API_KEY  (mandatory — Enterprise/Admin scope key,
    distinct from the regular per-user API key)
  - $ANTHROPIC_ORG_ID         (optional — only needed if you have access
    to multiple orgs)

Endpoint:
  GET https://api.anthropic.com/v1/organizations/usage_report
  (Anthropic published this with their May 2026 Enterprise tier;
  see https://docs.anthropic.com/en/api/admin for the canonical
  parameters once you have Enterprise access.)

Failure modes are SOFT — if the admin key is missing, this script
exits 0 with a clear "not configured" message. The rest of the FinOps
pipeline keeps running on estimated cost. The reconciliation is purely
additive.

Cron suggestion: daily at 09:30 MX (15:30 UTC), 30 minutes after the
brain-digest cron, so the reconciliation lands on the *next* day's
digest:

  30 15 * * * /usr/bin/python3 ~/.claude/scripts/anthropic-analytics-pull.py \\
      >> ~/.claude/analytics/cron.log 2>&1

Stdlib only.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ANALYTICS_DIR = Path.home() / ".claude" / "analytics"
ANTHROPIC_API_BASE = "https://api.anthropic.com/v1"
USAGE_ENDPOINT = "/organizations/usage_report"
API_VERSION = "2023-06-01"
TIMEOUT_S = 60


def _today_utc_date() -> str:
    return _dt.datetime.now(_dt.timezone.utc).date().isoformat()


def _output_path(date_str: str) -> Path:
    return ANALYTICS_DIR / f"anthropic-{date_str}.jsonl"


def _fetch_usage(api_key: str, org_id: str | None,
                 starting_at: str, ending_at: str) -> list[dict]:
    """Returns the parsed `data` list from the Anthropic Admin API.

    If the endpoint returns pagination, we paginate via `next_page` until
    exhausted. List shape is determined by Anthropic's response schema;
    we pass it through verbatim into the JSONL file (one row per dict).
    """
    params = {
        "starting_at": starting_at,
        "ending_at": ending_at,
        "limit": "1000",
    }
    if org_id:
        params["organization_id"] = org_id
    out: list[dict] = []
    next_page: str | None = None
    while True:
        if next_page:
            qs = urllib.parse.urlencode({**params, "page": next_page})
        else:
            qs = urllib.parse.urlencode(params)
        url = f"{ANTHROPIC_API_BASE}{USAGE_ENDPOINT}?{qs}"
        req = urllib.request.Request(
            url,
            headers={
                "x-api-key": api_key,
                "anthropic-version": API_VERSION,
                "User-Agent": "octorato-finops/1.0 (brain admin analytics pull)",
            },
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            body = resp.read().decode("utf-8")
        parsed = json.loads(body)
        out.extend(parsed.get("data") or [])
        next_page = parsed.get("next_page") or parsed.get("page_token")
        if not next_page:
            break
    return out


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pull Anthropic Admin API usage_report into ~/.claude/analytics/",
    )
    parser.add_argument("--days", type=int, default=1,
                        help="Window in days ending today (default 1 = last 24h).")
    parser.add_argument("--date", default=None,
                        help="Specific date YYYY-MM-DD (overrides --days for a one-shot pull).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show the URL we'd hit + exit without writing.")
    args = parser.parse_args(argv)

    api_key = os.environ.get("ANTHROPIC_ADMIN_API_KEY")
    org_id = os.environ.get("ANTHROPIC_ORG_ID")

    if args.date:
        d = _dt.datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=_dt.timezone.utc)
        starting_at = d.isoformat()
        ending_at = (d + _dt.timedelta(days=1)).isoformat()
        out_date = args.date
    else:
        now = _dt.datetime.now(_dt.timezone.utc)
        starting_at = (now - _dt.timedelta(days=args.days)).isoformat()
        ending_at = now.isoformat()
        out_date = _today_utc_date()

    if args.dry_run:
        print("Anthropic Admin Analytics pull — dry run")
        print(f"  starting_at: {starting_at}")
        print(f"  ending_at:   {ending_at}")
        print(f"  output:      {_output_path(out_date)}")
        print(f"  api_key set: {bool(api_key)}")
        print(f"  org_id set:  {bool(org_id)}")
        return 0

    if not api_key:
        print(
            "Anthropic Admin Analytics: not configured (ANTHROPIC_ADMIN_API_KEY env "
            "var unset).\n"
            "  Set the Admin scope key (distinct from your regular Anthropic API key)\n"
            "  to enable per-user / per-key cost reconciliation. The rest of the\n"
            "  FinOps pipeline continues to run on estimated cost only."
        )
        return 0

    try:
        rows = _fetch_usage(api_key, org_id, starting_at, ending_at)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:500]
        print(f"::error::Anthropic Admin API returned HTTP {e.code}: {body}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, OSError) as e:
        print(f"::error::Anthropic Admin API unreachable: {e}", file=sys.stderr)
        return 1

    path = _output_path(out_date)
    _write_jsonl(path, rows)
    total_rows = len(rows)
    print(f"✓ Wrote {total_rows} usage rows to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
