#!/usr/bin/env python3
"""
cost-vs-change.py — "is the new thing making me cheaper or more expensive?"

Correlates the daily Claude cost curve (reused from usage_report — single
source of truth for pricing) with the brain's own git log: which skills /
scripts / agents landed on which day. For every day a NEW capability was
merged, it compares the average daily cost in the window before vs after, so
you can see the *marginal cost of each new thing* — not just total spend.

Honest scope: list-price estimate; correlation ≠ causation (daily cost is
driven mostly by how much you worked that day, not only by new capabilities).
Use it to spot signals worth investigating, not as proof.

Usage:
  cost-vs-change.py [--days N] [--window W]
    --days   lookback for the timeline (default 30)
    --window days each side for the marginal before/after average (default 3)
"""
import sys
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

CLAUDE_DIR = Path(__file__).resolve().parent.parent
PROJECTS = CLAUDE_DIR / "projects"

sys.path.insert(0, str(CLAUDE_DIR / "skills" / "claude-usage-report" / "scripts"))
try:
    from usage_report import aggregate  # reuse the canonical parser + pricing
except Exception:
    aggregate = None

CAP_NEW = ("skills/", "scripts/", "agents/")          # an ADDED file here = new capability
CAP_TOUCH = ("skills/", "scripts/", "agents/", "hooks", "CLAUDE.md")


def daily_cost():
    if not aggregate:
        return {}
    data = aggregate(PROJECTS)
    return {d: b["cost"] for d, b in data.get("by_day", {}).items()}


def git_changes(days: int):
    """Map date -> list of {subject, new_caps:[paths], touched:bool}."""
    try:
        out = subprocess.run(
            ["git", "-C", str(CLAUDE_DIR), "log", f"--since={days} days ago",
             "--date=short", "--pretty=format:C\t%ad\t%s", "--name-status"],
            capture_output=True, text=True, timeout=30, check=False,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return {}
    by_date = defaultdict(list)
    cur = None
    for line in out.splitlines():
        if line.startswith("C\t"):
            _, date, subj = line.split("\t", 2)
            cur = {"date": date, "subject": subj, "new_caps": [], "touched": False}
            by_date[date].append(cur)
        elif cur and "\t" in line:
            status, path = line.split("\t", 1)
            path = path.strip()
            if any(path.startswith(p) for p in CAP_TOUCH):
                cur["touched"] = True
            if status.startswith("A") and (
                (path.startswith("skills/") and path.endswith("SKILL.md"))
                or (path.startswith("scripts/") and path.endswith(".py"))
                or (path.startswith("agents/") and path.endswith(".md"))
            ):
                cur["new_caps"].append(path)
    return by_date


def cap_label(path: str) -> str:
    if path.startswith("skills/"):
        return path.split("/")[1]
    return path.split("/")[-1]


def main():
    ap = argparse.ArgumentParser(description="Correlate daily cost with brain changes")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--window", type=int, default=3)
    args = ap.parse_args()

    costs = daily_cost()
    changes = git_changes(args.days)
    if not costs:
        print("No cost data (usage_report unavailable or no logs).")
        return

    today = datetime.now().date()
    start = today - timedelta(days=args.days)
    days = [start + timedelta(days=i) for i in range(args.days + 1)]
    dstr = [d.strftime("%Y-%m-%d") for d in days]

    print("=" * 72)
    print(f"  Cost vs Change — last {args.days} days  (list-price estimate)")
    print("=" * 72)
    print(f"  {'date':<12} {'$ est':>9} {'Δ%':>6}   capabilities landed")
    prev = None
    cap_days = []
    for ds in dstr:
        c = costs.get(ds, 0.0)
        delta = ""
        if prev is not None and prev > 0:
            delta = f"{(c - prev) / prev * 100:+.0f}%"
        caps = []
        for cm in changes.get(ds, []):
            for p in cm["new_caps"]:
                caps.append("🆕 " + cap_label(p))
        if caps:
            cap_days.append(ds)
        # only print rows with cost or a capability (skip empty days)
        if c > 0 or caps:
            print(f"  {ds:<12} {c:>8.2f} {delta:>6}   {'; '.join(caps)}")
        prev = c

    # Marginal signal: avg daily cost W days before vs W days after each cap-day
    print("\n  Marginal cost signal (avg $/day, ±{}d around each new capability):".format(args.window))
    if not cap_days:
        print("    no new capabilities merged in window.")
    for cd in cap_days:
        idx = dstr.index(cd)
        before = [costs.get(dstr[j], 0.0) for j in range(max(0, idx - args.window), idx)]
        after = [costs.get(dstr[j], 0.0) for j in range(idx + 1, min(len(dstr), idx + 1 + args.window))]
        ba = sum(before) / len(before) if before else 0.0
        aa = sum(after) / len(after) if after else 0.0
        arrow = "↑ pricier" if aa > ba else ("↓ cheaper" if aa < ba else "≈ flat")
        caps = "; ".join(cap_label(p) for cm in changes.get(cd, []) for p in cm["new_caps"])
        print(f"    {cd}  before ${ba:.2f}/d → after ${aa:.2f}/d   {arrow}   [{caps[:50]}]")
    print("\n  ⚠ correlation ≠ causation — daily cost tracks how much you worked, "
          "not only new capabilities. Signals to investigate, not proof.")
    print("=" * 72)


if __name__ == "__main__":
    main()
