#!/usr/bin/env python3
"""
budget-check.py — FinOps Feature 3 (budget caps + halt mechanism).

Reads ~/.claude/budgets.yaml (gitignored — private operator config),
computes the current-month spend per arm from skill-cost-profiler's
--json output, and emits:

  OK       — exit 0, every arm under its cap (or no cap configured)
  WARN     — exit 0, an arm is between cap and (cap * grace_pct/100)
             — prints a warning line, doesn't block
  HARD_STOP — exit 2, an arm is at or above (cap * grace_pct/100) AND
             its action_on_breach == 'hard_stop'
             — caller (PreToolUse hook) must refuse the tool invocation

Stdlib + optional PyYAML (falls back to JSON at ~/.claude/budgets.json).
Designed to be cheap (<200ms) so it can run on every tool invocation.

Schema (~/.claude/budgets.yaml — gitignored):

    budgets:
      - arm: client-x
        monthly_usd_cap: 200.00
        action_on_breach: hard_stop    # alert | warn | hard_stop
        grace_pct: 110                 # allow 10% overage before hard_stop fires

    # Optional global default for any arm not listed above:
    default:
      monthly_usd_cap: 100.00
      action_on_breach: warn
      grace_pct: 120

CLI usage:
  python3 budget-check.py                  # default: print status, exit code
  python3 budget-check.py --json           # JSON output (for hooks)
  python3 budget-check.py --arm <name>     # check only one arm
  python3 budget-check.py --tool <name>    # context for which tool is being checked

Exit codes:
  0 — OK (or WARN — caller may still proceed)
  1 — config error (malformed yaml, etc.)
  2 — HARD_STOP — caller MUST refuse the tool invocation
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import subprocess
import sys
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


BUDGETS_YAML = Path.home() / ".claude" / "budgets.yaml"
BUDGETS_JSON = Path.home() / ".claude" / "budgets.json"
COST_PROFILER = Path(__file__).parent / "skill-cost-profiler.py"

VALID_ACTIONS = {"alert", "warn", "hard_stop"}
DEFAULT_GRACE_PCT = 110


def _load_budgets() -> dict:
    """Returns the parsed budgets dict, or {} if no config exists.

    {} = no budget caps configured = nothing to enforce.
    """
    if BUDGETS_YAML.exists():
        try:
            import yaml  # type: ignore[import-not-found]
            return yaml.safe_load(BUDGETS_YAML.read_text(encoding="utf-8")) or {}
        except ImportError:
            sys.stderr.write(
                f"⚠ {BUDGETS_YAML} exists but PyYAML is not installed — "
                f"create {BUDGETS_JSON} as a JSON fallback.\n"
            )
            return {}
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"⚠ Failed to parse {BUDGETS_YAML}: {e}\n")
            return {}
    if BUDGETS_JSON.exists():
        try:
            return json.loads(BUDGETS_JSON.read_text(encoding="utf-8")) or {}
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"⚠ Failed to parse {BUDGETS_JSON}: {e}\n")
            return {}
    return {}


def _month_to_date_usd_by_arm() -> dict[str, float]:
    """Run skill-cost-profiler --days N --json with N = days since 1st of month.

    Returns {arm: usd_estimate}. Empty dict if profiler unavailable.
    """
    if not COST_PROFILER.exists():
        return {}
    today = _dt.date.today()
    day_of_month = today.day  # 1..31; we measure month-to-date
    try:
        result = subprocess.run(
            [sys.executable, str(COST_PROFILER), "--days", str(day_of_month), "--json"],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            return {}
        data = json.loads(result.stdout)
        arms_list = data.get("by_arm", []) if isinstance(data, dict) else []
        return {r["arm"]: float(r.get("usd_estimate", 0.0)) for r in arms_list}
    except (subprocess.SubprocessError, OSError, json.JSONDecodeError):
        return {}


def evaluate(arm_filter: str | None = None, cwd: str | None = None) -> dict:
    """Returns a structured verdict consumable by both human + hook.

    Shape:
      {
        "status": "OK" | "WARN" | "HARD_STOP",
        "arms": [
          {"arm": str, "spent_usd": float, "cap_usd": float,
           "grace_usd": float, "action_on_breach": str, "verdict": str}
        ],
        "halt_reason": str | None,    # populated only if status == HARD_STOP
      }
    """
    cfg = _load_budgets()
    if not cfg:
        return {"status": "OK", "arms": [], "halt_reason": None,
                "note": "no budgets configured"}

    # Spend source: the profiler by default, or a JSON file {arm: usd} named by
    # `spend_json` (an external FinOps export, or a fixture). Config-first.
    spend_json = cfg.get("spend_json")
    if spend_json:
        try:
            spend = {k: float(v) for k, v in json.loads(
                Path(os.path.expanduser(str(spend_json))).read_text(encoding="utf-8")).items()}
        except Exception:
            spend = {}
    else:
        spend = _month_to_date_usd_by_arm()
    default = cfg.get("default") or {}
    arms_cfg = cfg.get("budgets", []) or []
    # Path scoping (v7): an arm entry may carry `path`; then its cap applies only
    # when the tool call's cwd is under that path. Entries without `path` keep
    # the historical global behaviour. A breached client arm halts work IN that
    # arm, not every arm on the machine.
    if cwd:
        scoped = []
        for b in arms_cfg:
            pth = (b or {}).get("path") if isinstance(b, dict) else None
            if pth and not str(cwd).startswith(os.path.expanduser(str(pth)).rstrip("/") ):
                continue
            scoped.append(b)
        arms_cfg = scoped

    # Index per-arm overrides
    overrides = {b["arm"]: b for b in arms_cfg if isinstance(b, dict) and "arm" in b}

    # Build the set of arms we care about: every configured arm + any arm
    # observed with spend (so default budget can apply).
    interesting = set(overrides.keys()) | set(spend.keys())
    if arm_filter:
        interesting = {arm_filter}

    rows: list[dict] = []
    overall = "OK"
    halt_reason: str | None = None
    for arm in interesting:
        ovr = overrides.get(arm, {})
        cap = float(ovr.get("monthly_usd_cap", default.get("monthly_usd_cap", 0)) or 0)
        if cap <= 0:
            continue  # no cap configured = nothing to enforce
        action = ovr.get("action_on_breach", default.get("action_on_breach", "alert"))
        grace_pct = int(ovr.get("grace_pct", default.get("grace_pct", DEFAULT_GRACE_PCT)))
        grace_usd = cap * (grace_pct / 100.0)
        spent = float(spend.get(arm, 0.0))

        if spent >= grace_usd and action == "hard_stop":
            verdict = "HARD_STOP"
            overall = "HARD_STOP"
            if not halt_reason:
                halt_reason = (
                    f"arm '{arm}' burned ${spent:.2f} "
                    f"(grace ${grace_usd:.2f} = cap ${cap:.2f} × {grace_pct}%) — refusing tool."
                )
        elif spent >= cap:
            verdict = "WARN"
            if overall == "OK":
                overall = "WARN"
        else:
            verdict = "OK"

        rows.append({
            "arm": arm,
            "spent_usd": round(spent, 2),
            "cap_usd": round(cap, 2),
            "grace_usd": round(grace_usd, 2),
            "action_on_breach": action,
            "verdict": verdict,
        })

    return {"status": overall, "arms": rows, "halt_reason": halt_reason}


def _print_human(verdict: dict) -> None:
    status = verdict["status"]
    print(f"Budget check: {status}")
    if verdict.get("note"):
        print(f"  {verdict['note']}")
    for r in verdict["arms"]:
        marker = {"OK": "✓", "WARN": "⚠", "HARD_STOP": "🛑"}.get(r["verdict"], "?")
        print(
            f"  {marker} {r['arm']:24}  spent ${r['spent_usd']:>8,.2f}  "
            f"cap ${r['cap_usd']:>8,.2f}  ({r['action_on_breach']})"
        )
    if verdict.get("halt_reason"):
        print()
        print(f"HALT REASON: {verdict['halt_reason']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="FinOps budget cap checker (Feature 3 of the brain FinOps pipeline).",
    )
    parser.add_argument("--arm", default=None, help="Restrict the check to one arm.")
    parser.add_argument("--tool", default=None, help="Name of the tool being checked (logged only).")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of human text.")
    if "--selftest" in (argv if argv is not None else sys.argv[1:]):
        return _selftest()
    args = parser.parse_args(argv)

    # As a PreToolUse hook the harness passes the payload on stdin; only `cwd`
    # is read from it (for path-scoped caps). Never blocks on a missing stdin.
    cwd = None
    try:
        if not sys.stdin.isatty():
            raw = sys.stdin.read()
            if raw.strip():
                cwd = (json.loads(raw) or {}).get("cwd")
    except Exception:
        cwd = None

    verdict = evaluate(arm_filter=args.arm, cwd=cwd)
    if args.tool:
        verdict["tool"] = args.tool

    if args.json:
        json.dump(verdict, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        _print_human(verdict)

    if verdict["status"] == "HARD_STOP":
        return 2
    return 0


def _selftest() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import gate_selftest
    argv = sys.argv
    fixture = argv[argv.index("--selftest") + 1] if len(argv) > argv.index("--selftest") + 1 \
        else "registry/fixtures/FLOW.budget-halt"
    return gate_selftest.run_gate_selftest(__file__, fixture)


if __name__ == "__main__":
    sys.exit(main())
