#!/usr/bin/env python3
"""
finops-digest.py — the FinOps lens over Claude Code session logs.

"Lo que no se mide, no crece." Existing tools measure cost by skill
(skill-cost-profiler) and by day/model/project (usage_report). This adds the
three things a multi-client operator actually needs, and reuses the canonical
pricing table from usage_report (single source of truth — never fork the prices):

  1. Per-ARM spend (the client = the repo path = the ledger).
  2. Routing KPI — % of spend on cheap tiers + $ SAVED vs an all-Opus baseline.
     This is the metric that proves model-routing-by-complexity actually works.
  3. Estimated-vs-billed reconciliation (reads ~/.claude/analytics/ produced by
     anthropic-analytics-pull; degrades gracefully if absent).

Estimate, not invoice: cost is list-price math from local JSONL, attributed by
repo path, with a small unattributed remainder — same honest scope as the
per-arm FinOps everywhere else in the brain.

Usage:
  finops-digest.py [--days N] [--json]
"""
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timedelta, timezone
from collections import defaultdict

CLAUDE_DIR = Path(__file__).resolve().parent.parent
PROJECTS = CLAUDE_DIR / "projects"
ANALYTICS = CLAUDE_DIR / "analytics"

# Reuse the canonical pricing + price() — do NOT duplicate the rate table.
sys.path.insert(0, str(CLAUDE_DIR / "skills" / "claude-usage-report" / "scripts"))
try:
    from usage_report import price as _price, PRICING  # noqa: E402
except Exception:  # pragma: no cover - defensive
    _price, PRICING = None, {}

OPUS_REF = "claude-opus-4-7"  # baseline model for the "what if all-Opus" counterfactual


def tier(model: str) -> str:
    b = model.split("[")[0].lower()
    if "opus" in b:
        return "opus"
    if "haiku" in b:
        return "haiku"
    if "sonnet" in b:
        return "sonnet"
    return "other"


def arm_name(project_dir: str) -> str:
    """Strip the $HOME prefix the way usage_report does; the result is the arm."""
    home_prefix = f"-{str(Path.home()).lstrip('/').replace('/', '-')}"
    p = project_dir
    if p.startswith(home_prefix):
        p = p[len(home_prefix):].lstrip("-") or "~"
    return p


def collect(days: int):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    arms = defaultdict(lambda: {"cost": 0.0, "baseline": 0.0, "msgs": 0,
                                "tiers": defaultdict(float)})
    tiers = defaultdict(lambda: {"cost": 0.0, "out": 0, "msgs": 0})
    total = {"cost": 0.0, "baseline": 0.0, "msgs": 0}

    for f in PROJECTS.glob("**/*.jsonl"):
        arm = arm_name(f.parent.name)
        try:
            fh = open(f, "r", encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = rec.get("message", {})
                if not isinstance(msg, dict):
                    continue
                usage = msg.get("usage")
                if not usage:
                    continue
                ts = rec.get("timestamp", "")
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except Exception:
                    continue
                if dt < cutoff:
                    continue
                model = msg.get("model", "unknown")
                cost = _price(model, usage) if _price else 0.0
                baseline = _price(OPUS_REF, usage) if _price else 0.0  # all-Opus counterfactual
                t = tier(model)
                out_t = usage.get("output_tokens", 0)

                a = arms[arm]
                a["cost"] += cost; a["baseline"] += baseline
                a["msgs"] += 1; a["tiers"][t] += cost
                tiers[t]["cost"] += cost; tiers[t]["out"] += out_t; tiers[t]["msgs"] += 1
                total["cost"] += cost; total["baseline"] += baseline; total["msgs"] += 1
    return arms, tiers, total


def billed_total():
    """Best-effort read of billed cost from anthropic-analytics-pull output."""
    if not ANALYTICS.exists():
        return None
    best = None
    for f in sorted(ANALYTICS.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        # Tolerant: look for a top-level cost/total field.
        for k in ("total_cost_usd", "total_cost", "cost_usd", "amount_usd"):
            if isinstance(data, dict) and isinstance(data.get(k), (int, float)):
                best = float(data[k])
    return best


def render(arms, tiers, total, days):
    print("=" * 64)
    print(f"  FinOps Digest — last {days} days  (estimate, list-price)")
    print("=" * 64)
    if not total["msgs"]:
        print("  No usage events in window.")
        return
    print(f"  Total estimated: ${total['cost']:.2f}  over {total['msgs']:,} messages\n")

    # 1. Per-arm ledger
    print("  Per-arm (the client = the ledger)")
    print(f"    {'arm':<34} {'$ est':>9} {'msgs':>7} {'%cheap':>7}")
    for arm, a in sorted(arms.items(), key=lambda kv: -kv[1]["cost"]):
        cheap = a["tiers"].get("haiku", 0) + a["tiers"].get("sonnet", 0)
        pct_cheap = (cheap / a["cost"] * 100) if a["cost"] else 0
        print(f"    {arm[:34]:<34} {a['cost']:>8.2f} {a['msgs']:>7} {pct_cheap:>6.0f}%")
    print()

    # 2. Routing KPI
    print("  Routing KPI (model-routing-by-complexity)")
    for t in ("opus", "sonnet", "haiku", "other"):
        if t in tiers:
            c = tiers[t]["cost"]
            pct = (c / total["cost"] * 100) if total["cost"] else 0
            print(f"    {t:<8} ${c:>8.2f}  {pct:>5.1f}% of spend   ({tiers[t]['msgs']:,} msgs)")
    saved = total["baseline"] - total["cost"]
    pct_saved = (saved / total["baseline"] * 100) if total["baseline"] else 0
    print(f"    → all-Opus baseline would cost ${total['baseline']:.2f}; "
          f"routing SAVED ${saved:.2f} ({pct_saved:.0f}%)")
    print()

    # 3. Estimated vs billed
    billed = billed_total()
    print("  Estimated vs billed")
    if billed is None:
        print("    billed data unavailable — run anthropic-analytics-pull.py "
              "(needs ANTHROPIC_ADMIN_API_KEY) to reconcile.")
    else:
        gap = total["cost"] - billed
        pct = (gap / billed * 100) if billed else 0
        print(f"    estimated ${total['cost']:.2f}  |  billed ${billed:.2f}  "
              f"|  gap ${gap:+.2f} ({pct:+.0f}%)")
    print("=" * 64)


def main():
    ap = argparse.ArgumentParser(description="FinOps digest over Claude Code logs")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    arms, tiers, total = collect(args.days)
    if args.json:
        out = {
            "days": args.days,
            "total_estimated_usd": round(total["cost"], 4),
            "all_opus_baseline_usd": round(total["baseline"], 4),
            "saved_usd": round(total["baseline"] - total["cost"], 4),
            "billed_usd": billed_total(),
            "arms": {a: round(v["cost"], 4) for a, v in arms.items()},
            "by_tier": {t: round(v["cost"], 4) for t, v in tiers.items()},
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        render(arms, tiers, total, args.days)


if __name__ == "__main__":
    main()
