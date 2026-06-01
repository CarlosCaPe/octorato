#!/usr/bin/env python3
"""
brain-digest.py — observability surface 5. Daily aggregator.

Combines the data produced by Phase A (trace) and Phase B (cost profiler,
watchdog, SLOs) into a single markdown digest under
~/.claude/digests/brain-YYYY-MM-DD.md. The folder is already gitignored.

Sections (per spec):
  - Skill activity (24h): top 10 most-fired + bottom 10 stale
  - Agent activity (24h): top 5 most-activated
  - SLOs status
  - Watchdog anomalies
  - Cost (24h)

Stdlib only. Talks to sibling scripts via subprocess when they expose
--json output, otherwise reimplements the small aggregation inline.

Usage:
  python3 ~/.claude/scripts/brain-digest.py            # writes today's digest
  python3 ~/.claude/scripts/brain-digest.py --stdout   # also prints to stdout
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from _brain_obs import iter_trace_records, parse_record_ts

DIGESTS_DIR = Path.home() / ".claude" / "digests"
SCRIPTS_DIR = Path.home() / ".claude" / "scripts"
SLO_REPORT = Path.home() / ".claude" / "SLO_REPORT.md"


# Trace ingestion + ts parsing — imported from _brain_obs.
_parse_ts = parse_record_ts
_iter_records = iter_trace_records


# ── Section: skill + agent activity (24h) ──────────────


def section_activity(now: datetime) -> dict:
    since = now - timedelta(hours=24)
    skill_counter: Counter[str] = Counter()
    agent_counter: Counter[str] = Counter()
    error_counter: Counter[str] = Counter()

    for rec in _iter_records(since):
        ev = rec.get("event")
        name = rec.get("name") or "(unknown)"
        status = rec.get("status")
        if ev == "skill_fire":
            skill_counter[name] += 1
            if status == "error":
                error_counter[f"skill::{name}"] += 1
        elif ev == "agent_activate":
            agent_counter[name] += 1
            if status == "error":
                error_counter[f"agent::{name}"] += 1

    # Bottom 10 stale: skills present in trace history > 7d ago but NOT in last 24h
    stale_since = now - timedelta(days=30)
    seen_in_history: set[str] = set()
    for rec in _iter_records(stale_since):
        if rec.get("event") == "skill_fire":
            seen_in_history.add(rec.get("name") or "(unknown)")
    stale = sorted(seen_in_history - set(skill_counter.keys()))[:10]

    return {
        "skills_top10": skill_counter.most_common(10),
        "skills_stale": stale,
        "agents_top5": agent_counter.most_common(5),
        "errors_24h": error_counter.most_common(10),
    }


# ── Section: SLOs ──────────────────────────────────────


def section_slos() -> dict:
    """Reads SLO_REPORT.md if it exists; otherwise runs slos.py and parses output."""
    slos_script = SCRIPTS_DIR / "slos.py"
    if not slos_script.exists():
        return {"available": False}
    try:
        result = subprocess.run(
            ["python3", str(slos_script), "--write-report"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            return {"available": False, "error": result.stderr.strip()[:200]}
        return {"available": True, "report_excerpt": result.stdout.strip()}
    except (subprocess.SubprocessError, OSError) as e:
        return {"available": False, "error": str(e)}


# ── Section: Watchdog ──────────────────────────────────


def section_watchdog() -> dict:
    watchdog_script = SCRIPTS_DIR / "watchdog.py"
    if not watchdog_script.exists():
        return {"available": False}
    try:
        result = subprocess.run(
            ["python3", str(watchdog_script)],  # dry-run by default
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            return {"available": False, "error": result.stderr.strip()[:200]}
        # Parse the count line from the output
        return {"available": True, "report": result.stdout.strip()}
    except (subprocess.SubprocessError, OSError) as e:
        return {"available": False, "error": str(e)}


# ── Section: Anthropic billed-vs-estimated (FinOps Feature 4) ──


def section_anthropic_reconciliation() -> dict:
    """Read the most recent ~/.claude/analytics/anthropic-*.jsonl file (if
    any) and total the billed USD. Returns {available: bool, billed_usd_24h: float}.
    """
    analytics_dir = Path.home() / ".claude" / "analytics"
    if not analytics_dir.exists():
        return {"available": False}
    files = sorted(analytics_dir.glob("anthropic-*.jsonl"))
    if not files:
        return {"available": False}
    latest = files[-1]
    billed = 0.0
    row_count = 0
    try:
        for line in latest.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Anthropic schema variants: usd_amount | usd_cost | cost_usd | amount_usd
            for k in ("usd_amount", "usd_cost", "cost_usd", "amount_usd"):
                if k in row and isinstance(row[k], (int, float)):
                    billed += float(row[k])
                    break
            row_count += 1
    except OSError as e:
        return {"available": False, "error": str(e)}
    return {
        "available": True,
        "billed_usd": round(billed, 2),
        "file": str(latest.name),
        "rows": row_count,
    }


# ── Section: Budget burn (FinOps Feature 3) ────────────


def section_budget_burn() -> dict:
    """Run budget-check.py --json to surface month-to-date budget posture."""
    script = SCRIPTS_DIR / "budget-check.py"
    if not script.exists():
        return {"available": False}
    try:
        result = subprocess.run(
            ["python3", str(script), "--json"],
            capture_output=True, text=True, timeout=120,
        )
        # exit code 2 = HARD_STOP — still want the data
        if result.returncode not in (0, 2):
            return {"available": False, "error": result.stderr.strip()[:200]}
        data = json.loads(result.stdout)
        return {"available": True, **data}
    except (subprocess.SubprocessError, OSError, json.JSONDecodeError) as e:
        return {"available": False, "error": str(e)}


# ── Section: Cost (24h) ────────────────────────────────


def section_cost_24h() -> dict:
    """Use skill-cost-profiler with --days 1 to get 24h cost."""
    cost_script = SCRIPTS_DIR / "skill-cost-profiler.py"
    if not cost_script.exists():
        return {"available": False}
    try:
        result = subprocess.run(
            ["python3", str(cost_script), "--days", "1", "--json"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            return {"available": False, "error": result.stderr.strip()[:200]}
        data = json.loads(result.stdout)
        # Schema changed in FinOps Feature 1: top-level dict with by_skill +
        # by_arm sublists. Fall back to flat list for backward compat.
        if isinstance(data, dict) and "by_skill" in data:
            skills = data.get("by_skill", [])
            arms = data.get("by_arm", [])
        else:
            skills = data
            arms = []
        total_tokens = sum(r["total_tokens"] for r in skills)
        total_usd = sum(r.get("usd_estimate", 0.0) for r in arms) or sum(
            r.get("usd_estimate", 0.0) for r in skills
        )
        # Top 5 cost-heaviest skills, EXCLUDING __conversation__ which dominates by design
        skills_only = [r for r in skills if r["skill"] != "__conversation__"][:5]
        return {
            "available": True,
            "total_tokens_24h": total_tokens,
            "total_usd_24h": total_usd,
            "top5_skills": skills_only,
            "by_arm": arms,
            "conversation_tokens": next(
                (r["total_tokens"] for r in skills if r["skill"] == "__conversation__"), 0
            ),
        }
    except (subprocess.SubprocessError, OSError, json.JSONDecodeError) as e:
        return {"available": False, "error": str(e)}


def section_finops_routing(days: int = 7) -> dict:
    """Routing KPI + per-arm spend via finops-digest.py (reuses canonical pricing)."""
    script = SCRIPTS_DIR / "finops-digest.py"
    if not script.exists():
        return {"available": False}
    try:
        result = subprocess.run(
            ["python3", str(script), "--days", str(days), "--json"],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            return {"available": False, "error": result.stderr.strip()[:200]}
        data = json.loads(result.stdout)
        data["available"] = True
        data["days"] = days
        return data
    except (subprocess.SubprocessError, OSError, json.JSONDecodeError) as e:
        return {"available": False, "error": str(e)}


# ── Rendering ──────────────────────────────────────────


def render_digest(now: datetime, activity: dict, slos: dict, watchdog: dict,
                  cost: dict, budget: dict | None = None,
                  reconciliation: dict | None = None,
                  finops: dict | None = None) -> str:
    lines: list[str] = []
    today = now.strftime("%Y-%m-%d")
    lines.append(f"# Brain Daily — {today}")
    lines.append("")
    lines.append(f"_Generated {now.strftime('%Y-%m-%d %H:%M:%S UTC')} by brain-digest.py._")
    lines.append("")

    # Skill activity
    lines.append("## Skill activity (24h)")
    if activity["skills_top10"]:
        lines.append("")
        lines.append("**Top 10 most-fired**")
        lines.append("")
        lines.append("| # | Skill | Fires |")
        lines.append("|---|---|---:|")
        for i, (name, n) in enumerate(activity["skills_top10"], 1):
            lines.append(f"| {i} | `{name}` | {n:,} |")
    else:
        lines.append("_No skill_fire events in the last 24h._")
    lines.append("")

    if activity["skills_stale"]:
        lines.append(f"**Stale skills** (fired within 30d but NOT in last 24h, top {len(activity['skills_stale'])})")
        lines.append("")
        lines.append(", ".join(f"`{s}`" for s in activity["skills_stale"]))
        lines.append("")

    # Agent activity
    lines.append("## Agent activity (24h)")
    if activity["agents_top5"]:
        lines.append("")
        lines.append("| # | Agent | Activations |")
        lines.append("|---|---|---:|")
        for i, (name, n) in enumerate(activity["agents_top5"], 1):
            lines.append(f"| {i} | `{name}` | {n:,} |")
    else:
        lines.append("_No agent_activate events in the last 24h._")
    lines.append("")

    # Errors (combined)
    if activity["errors_24h"]:
        lines.append("## Errors (24h)")
        lines.append("")
        lines.append("| # | Class::Name | Errors |")
        lines.append("|---|---|---:|")
        for i, (key, n) in enumerate(activity["errors_24h"], 1):
            lines.append(f"| {i} | `{key}` | {n} |")
        lines.append("")

    # SLOs
    lines.append("## SLOs status")
    if not slos.get("available"):
        msg = slos.get("error", "SLO script unavailable.")
        lines.append(f"_{msg}_")
    else:
        excerpt = slos.get("report_excerpt", "").strip()
        # Take the table portion (lines starting with `|` or `#`)
        kept = [ln for ln in excerpt.splitlines() if ln.strip().startswith(("|", "**", "_"))]
        if kept:
            lines.extend(kept)
        else:
            lines.append("_No SLOs configured. Create `~/.claude/slos.yaml` to start tracking._")
    lines.append("")

    # Watchdog
    lines.append("## Watchdog anomalies")
    if not watchdog.get("available"):
        msg = watchdog.get("error", "Watchdog script unavailable.")
        lines.append(f"_{msg}_")
    else:
        excerpt = watchdog.get("report", "")
        # Try to find anomalies count line
        anomaly_line = next(
            (ln for ln in excerpt.splitlines() if "Anomalies detected" in ln),
            "_(parse error)_",
        )
        lines.append(anomaly_line)
        # If there are tables, include them
        in_table = False
        for ln in excerpt.splitlines():
            if ln.strip().startswith(("### Cliff", "### Quality")):
                in_table = True
                lines.append("")
                lines.append(ln)
                continue
            if in_table:
                if not ln.strip() or ln.startswith("("):
                    in_table = False
                    continue
                lines.append(ln)
    lines.append("")

    # Cost
    lines.append("## Cost (24h)")
    if not cost.get("available"):
        msg = cost.get("error", "Cost profiler unavailable.")
        lines.append(f"_{msg}_")
    else:
        total = cost.get("total_tokens_24h", 0)
        conv = cost.get("conversation_tokens", 0)
        total_usd = cost.get("total_usd_24h", 0.0)
        skill_total = total - conv
        lines.append("")
        lines.append(f"- **Total tokens (24h)**: {total:,}")
        lines.append(f"- **Total USD (24h, list price)**: ${total_usd:,.2f}")
        lines.append(f"- Conversation thinking: {conv:,} ({conv / total * 100 if total else 0:.1f}%)")
        lines.append(f"- Skill-attributed: {skill_total:,} ({skill_total / total * 100 if total else 0:.1f}%)")

        # FinOps Feature 1: per-arm cost rollup. Lands the "I can bill
        # Client A $X for May" claim from the roadmap.
        arms = cost.get("by_arm", [])
        if arms:
            lines.append("")
            lines.append("**Cost by arm / client (24h)**")
            lines.append("")
            lines.append("| Arm | Sessions | Turns | Total tokens | USD (list price) |")
            lines.append("|---|---:|---:|---:|---:|")
            for r in arms:
                lines.append(
                    f"| `{r['arm']}` | {r.get('sessions', 0):,} | {r.get('turns', 0):,} "
                    f"| {r['in_tokens'] + r['out_tokens']:,} | ${r.get('usd_estimate', 0.0):,.2f} |"
                )

        top5 = cost.get("top5_skills", [])
        if top5:
            lines.append("")
            lines.append("**Top 5 cost-heaviest skills (24h, excluding __conversation__)**")
            lines.append("")
            lines.append("| # | Skill | Invocations | Total tokens | USD |")
            lines.append("|---|---|---:|---:|---:|")
            for i, r in enumerate(top5, 1):
                usd = r.get("usd_estimate", 0.0)
                lines.append(
                    f"| {i} | `{r['skill']}` | {r['invocations']:,} | {r['total_tokens']:,} | ${usd:,.2f} |"
                )
    lines.append("")

    # ── Anthropic billed-vs-estimated reconciliation (FinOps Feature 4) ──
    if reconciliation and reconciliation.get("available"):
        est = cost.get("total_usd_24h", 0.0) if cost.get("available") else 0.0
        billed = reconciliation.get("billed_usd", 0.0)
        delta_pct = ((billed - est) / est * 100) if est > 0 else None
        lines.append("**Anthropic billed (vendor truth)** vs **Estimated (Octorato)** — 24h")
        lines.append("")
        lines.append(f"- Estimated (list-price math): ${est:,.2f}")
        lines.append(f"- Billed (Anthropic Admin API): ${billed:,.2f}")
        if delta_pct is not None:
            sign = "+" if delta_pct >= 0 else ""
            note = " ⚠ drift > 20%" if abs(delta_pct) > 20 else ""
            lines.append(f"- Delta: {sign}{delta_pct:.1f}%{note}")
        lines.append(f"- Source: `analytics/{reconciliation.get('file')}` ({reconciliation.get('rows', 0)} rows)")
        lines.append("")

    # ── Budget burn (FinOps Feature 3) ─────────────────────
    if budget and budget.get("available"):
        lines.append("## Budget burn (month-to-date)")
        status = budget.get("status", "OK")
        rows = budget.get("arms", [])
        if not rows:
            lines.append(f"_{budget.get('note', 'no budgets configured')}_")
        else:
            badge = {"OK": "✓ all clear", "WARN": "⚠ at-or-near cap on ≥1 arm",
                     "HARD_STOP": "🛑 hard-stop active on ≥1 arm"}.get(status, status)
            lines.append(f"**Overall:** {badge}")
            lines.append("")
            lines.append("| Arm | Spent (MTD) | Cap | Grace | Action | Verdict |")
            lines.append("|---|---:|---:|---:|---|---|")
            for r in rows:
                marker = {"OK": "✓", "WARN": "⚠", "HARD_STOP": "🛑"}.get(r["verdict"], "")
                lines.append(
                    f"| `{r['arm']}` | ${r['spent_usd']:,.2f} | ${r['cap_usd']:,.2f} "
                    f"| ${r['grace_usd']:,.2f} | {r['action_on_breach']} | {marker} {r['verdict']} |"
                )
            if budget.get("halt_reason"):
                lines.append("")
                lines.append(f"**HALT REASON:** {budget['halt_reason']}")
        lines.append("")

    if finops and finops.get("available") and finops.get("all_opus_baseline_usd"):
        days = finops.get("days", 7)
        by_tier = finops.get("by_tier", {})
        total = finops.get("total_estimated_usd", 0.0) or 0.0
        saved = finops.get("saved_usd", 0.0)
        base = finops.get("all_opus_baseline_usd", 0.0)
        pct_saved = (saved / base * 100) if base else 0.0
        lines.append(f"## FinOps routing ({days}d, list-price estimate)")
        for t in ("opus", "sonnet", "haiku", "other"):
            if t in by_tier:
                c = by_tier[t]
                pct = (c / total * 100) if total else 0.0
                lines.append(f"- **{t}**: ${c:,.2f} ({pct:.1f}% of spend)")
        lines.append(f"- _all-Opus baseline ${base:,.2f} → routing saved ${saved:,.2f} ({pct_saved:.0f}%)_")
        billed = finops.get("billed_usd")
        if billed is None:
            lines.append("- _est-vs-billed: run anthropic-analytics-pull to reconcile_")
        else:
            lines.append(f"- _estimated ${total:,.2f} vs billed ${billed:,.2f}_")
        arms = finops.get("arms", {})
        if arms:
            top = sorted(arms.items(), key=lambda kv: -kv[1])[:3]
            lines.append("- top arms: " + ", ".join(f"`{a}` ${v:,.2f}" for a, v in top))
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("_Generated by observability surface 5._")
    return "\n".join(lines) + "\n"


# ── Entry point ────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Brain Daily Digest — Phase C Port 5.")
    parser.add_argument("--stdout", action="store_true", help="Also print the digest to stdout.")
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Override the digest date (YYYY-MM-DD). Default: today UTC.",
    )
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc)
    if args.date:
        try:
            d = datetime.strptime(args.date, "%Y-%m-%d")
            now = d.replace(tzinfo=timezone.utc, hour=now.hour, minute=now.minute)
        except ValueError:
            sys.stderr.write(f"Bad --date '{args.date}', using today UTC.\n")

    activity = section_activity(now)
    slos = section_slos()
    watchdog = section_watchdog()
    cost = section_cost_24h()
    budget = section_budget_burn()
    reconciliation = section_anthropic_reconciliation()
    finops = section_finops_routing()

    digest = render_digest(now, activity, slos, watchdog, cost, budget, reconciliation, finops)

    DIGESTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DIGESTS_DIR / f"brain-{now.strftime('%Y-%m-%d')}.md"
    out_path.write_text(digest, encoding="utf-8")
    print(f"✓ Wrote {out_path}")

    if args.stdout:
        print()
        print(digest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
