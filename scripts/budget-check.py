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

Residual (cache poisoning): a hand-written ~/.claude/.cache/budget/spend.json hides spend for up to 15 minutes, the same class as budgets.yaml itself being writable.

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


_LOAD_WARNINGS: list[str] = []   # why a config that exists was read as {}


def _load_budgets() -> dict:
    """Returns the parsed budgets dict, or {} if no config exists.

    {} = no budget caps configured = nothing to enforce. A file that exists but
    cannot be read also yields {}; the reason is kept in _LOAD_WARNINGS so the
    verdict names it instead of reading as a silent allow.
    """
    _LOAD_WARNINGS.clear()
    if BUDGETS_YAML.exists():
        try:
            import yaml  # type: ignore[import-not-found]
            return yaml.safe_load(BUDGETS_YAML.read_text(encoding="utf-8")) or {}
        except ImportError:
            msg = (f"{BUDGETS_YAML} exists but PyYAML is not installed — "
                   f"create {BUDGETS_JSON} as a JSON fallback.")
            sys.stderr.write(f"⚠ {msg}\n")
            _LOAD_WARNINGS.append(msg)
            return {}
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"⚠ Failed to parse {BUDGETS_YAML}: {e}\n")
            _LOAD_WARNINGS.append(f"failed to parse {BUDGETS_YAML}: {e}")
            return {}
    if BUDGETS_JSON.exists():
        try:
            return json.loads(BUDGETS_JSON.read_text(encoding="utf-8")) or {}
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"⚠ Failed to parse {BUDGETS_JSON}: {e}\n")
            _LOAD_WARNINGS.append(f"failed to parse {BUDGETS_JSON}: {e}")
            return {}
    return {}


# Top-level keys this script reads. Anything else is ignored by evaluate(), so
# a config written in another shape (an `arms:` map, say) enforced nothing with
# no word said. It is now named, never guessed at: no cap is invented and the
# decision is unchanged.
KNOWN_KEYS = ("budgets", "default", "spend_json")
CONFIG_FIX = "convert to the budgets: list documented in budget-check.py"


def config_problems(cfg) -> list[str]:
    """What in a loaded config this script cannot read. [] when it reads all."""
    if cfg in (None, {}):
        return []
    if not isinstance(cfg, dict):
        return [f"top level is a {type(cfg).__name__}, not a mapping; nothing is enforced"]
    out = []
    unknown = sorted(str(k) for k in cfg if k not in KNOWN_KEYS)
    if unknown:
        out.append("unrecognised top-level key(s) ignored: " + ", ".join(unknown))
    if "budgets" not in cfg and "default" not in cfg:
        out.append("neither budgets: nor default: is present; no cap is enforced")
    if "budgets" in cfg and not isinstance(cfg.get("budgets") or [], list):
        out.append("budgets: is not a list; its entries are ignored")
    if "default" in cfg and not isinstance(cfg.get("default") or {}, dict):
        out.append("default: is not a mapping; it is ignored")
    return out


def _warnings(cfg) -> list[str]:
    return list(_LOAD_WARNINGS) + config_problems(cfg)


def _profiler_spend() -> dict[str, float] | None:
    """Run skill-cost-profiler --days N --json with N = days since 1st of month.

    Returns {arm: usd_estimate}, or None when the profiler is missing or fails
    (so a failure is never cached as "no spend").
    """
    if not COST_PROFILER.exists():
        return None
    today = _dt.date.today()
    day_of_month = today.day  # 1..31; we measure month-to-date
    try:
        result = subprocess.run(
            [sys.executable, str(COST_PROFILER), "--days", str(day_of_month), "--json"],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        arms_list = data.get("by_arm", []) if isinstance(data, dict) else []
        return {r["arm"]: float(r.get("usd_estimate", 0.0)) for r in arms_list}
    except (subprocess.SubprocessError, OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def _month_to_date_usd_by_arm() -> dict[str, float]:
    """The profiler's month-to-date spend, {} when it is unavailable."""
    return _profiler_spend() or {}


# -- spend cache (v10 T07, AC-11 + AC-22) -------------------------------------
# The profiler walks every session transcript of the month: a measured 7.2 s
# median per call, with timeouts at the hook's 10 s, on every subagent spawn.
# The PreToolUse check now answers from a cache that SessionStart and each
# finished spawn refresh in the background. A cache up to 15 minutes old is
# fresh. A stale one, older than 15 minutes but from this month and at most 24
# hours old, still answers at once and starts one background refresh (AC-22 as
# amended 2026-10-09): recomputing synchronously cost a 10 s timeout on the
# first spawn after an idle spell, which broke AC-11's 1 s p95. A cache from
# another month, stamped in the future, unreadable or older than 24 hours is
# never used: the check recomputes synchronously. The hard_stop decision is
# taken on whatever spend the check answers from. Residual, stated: after an
# idle spell the decision can rest on a number up to 24 hours old, so spend
# made since then is caught by the first call after the background refresh
# finishes (a profiler run, about 8 s measured); a failed profiler run is not
# cached; the cache is a file under $HOME, as writable as budgets.yaml itself,
# so this is a FinOps cap, not an agent-proof boundary.
CACHE_MAX_AGE_S = 15 * 60
CACHE_STALE_MAX_S = 24 * 60 * 60
REFRESH_STALE_S = 180  # the profiler call times out at 120 s


def cache_path() -> Path:
    return Path(os.path.expanduser("~")) / ".claude" / ".cache" / "budget" / "spend.json"


def _read_cache_aged(now: float | None = None) -> tuple[dict[str, float], float] | None:
    """(spend, age in seconds) for a usable cache: this month, not stamped in
    the future, at most CACHE_STALE_MAX_S old. None otherwise."""
    now = _dt.datetime.now().timestamp() if now is None else now
    try:
        data = json.loads(cache_path().read_text(encoding="utf-8"))
        age = now - float(data["computed_at"])
        if not (0 <= age <= CACHE_STALE_MAX_S):
            return None
        if data.get("month") != _dt.date.fromtimestamp(now).strftime("%Y-%m"):
            return None
        return {str(k): float(v) for k, v in dict(data["spend"]).items()}, age
    except Exception:  # missing, torn or malformed: recompute
        return None


def _read_cache(now: float | None = None) -> dict[str, float] | None:
    """The cache only when it is fresh (at most CACHE_MAX_AGE_S old)."""
    got = _read_cache_aged(now)
    if got is None or got[1] > CACHE_MAX_AGE_S:
        return None
    return got[0]


def _write_cache(spend: dict[str, float], now: float | None = None) -> None:
    now = _dt.datetime.now().timestamp() if now is None else now
    try:
        p = cache_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"computed_at": now,
                                   "month": _dt.date.fromtimestamp(now).strftime("%Y-%m"),
                                   "spend": spend}), encoding="utf-8")
        os.replace(tmp, p)
    except OSError:
        pass  # an unwritable cache only costs speed


def refresh_cache() -> dict[str, float] | None:
    """Recompute the month-to-date spend and store it. None on profiler failure."""
    spend = _profiler_spend()
    if spend is not None:
        _write_cache(spend)
    return spend


def _cached_spend() -> dict[str, float]:
    """Fresh cache; a stale one of this month (at most 24 h) plus one
    background refresh; else a synchronous recompute (AC-22, amended)."""
    got = _read_cache_aged()
    if got is not None:
        spend, age = got
        if age > CACHE_MAX_AGE_S:
            _refresh_main(background=True)  # fail-open, never waits
        return spend
    return refresh_cache() or {}


def _cap_of(entry: dict, default: dict) -> float:
    return float(entry.get("monthly_usd_cap", default.get("monthly_usd_cap", 0)) or 0)


def _any_cap(default: dict, overrides: dict, arm_filter: str | None = None) -> bool:
    """True when at least one arm could carry a cap > 0 (the same cap lookup
    evaluate() uses per row). The default cap applies to any arm with spend."""
    if arm_filter:
        return _cap_of(overrides.get(arm_filter, {}), default) > 0
    if _cap_of({}, default) > 0:
        return True
    return any(_cap_of(o, default) > 0 for o in overrides.values())


def _needs_profiler(cfg: dict) -> bool:
    """A refresh is worth running only when spend comes from the profiler and
    some cap could apply (path scoping ignored: any cwd may need it)."""
    if not cfg or cfg.get("spend_json"):
        return False
    try:
        default = cfg.get("default") or {}
        arms = {b["arm"]: b for b in (cfg.get("budgets") or [])
                if isinstance(b, dict) and "arm" in b}
        return _any_cap(default, arms)
    except Exception:
        return True  # unreadable caps: keep the cache warm rather than guess


def _refresh_main(background: bool) -> int:
    """`--refresh`: recompute the cache (one runner at a time). With
    `--background`, detach a child that does it and return at once, so a
    SessionStart or PostToolUse hook never waits on the profiler. Fail-open:
    a refresh never blocks anything."""
    try:
        if not _needs_profiler(_load_budgets()):
            return 0  # no caps, or spend from a file: nothing to cache
        if background:
            subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--refresh"],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
            return 0
        lock = cache_path().with_name("refresh.lock")
        lock.parent.mkdir(parents=True, exist_ok=True)
        with open(lock, "a") as fh:
            try:
                import fcntl
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except ImportError:
                # No flock (Windows). Every stale PreToolUse call spawns a
                # refresh, so an exclusive marker file serializes them; one
                # older than the profiler's own timeout is a dead runner's.
                marker = lock.with_name("refresh.running")
                try:
                    os.close(os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                except FileExistsError:
                    try:
                        if _dt.datetime.now().timestamp() - marker.stat().st_mtime > REFRESH_STALE_S:
                            marker.unlink()
                    except OSError:
                        pass
                    return 0  # another refresh is running
                try:
                    _refresh_if_not_fresh()
                finally:
                    try:
                        marker.unlink()
                    except OSError:
                        pass
                return 0
            except OSError:
                return 0  # another refresh is running
            _refresh_if_not_fresh()
    except Exception:
        pass
    return 0


def _refresh_if_not_fresh() -> None:
    """Under the lock: a runner that queued behind one that just finished
    finds a fresh cache and does not profile again."""
    if _read_cache() is None:
        refresh_cache()


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
        "config_warnings": [str],     # present only when the config is not
                                      # fully readable (status is unchanged)
      }
    """
    cfg = _load_budgets()
    # A non-mapping top level crashed evaluate() before (a hook error, which
    # the harness lets through); it now reads as no caps, the same allow, named.
    verdict = _evaluate(cfg if isinstance(cfg, dict) else {}, arm_filter, cwd)
    warnings = _warnings(cfg)
    if warnings:
        verdict["config_warnings"] = warnings
        verdict["config_fix"] = CONFIG_FIX
    return verdict


def _evaluate(cfg, arm_filter: str | None, cwd: str | None) -> dict:
    if not cfg:
        return {"status": "OK", "arms": [], "halt_reason": None,
                "note": "no budgets configured"}

    default = cfg.get("default") or {}
    arms_cfg = cfg.get("budgets", []) or []
    # Path scoping (v7): an arm entry may carry `path`; then its cap applies only
    # when the tool call's cwd is under that path. Entries without `path` keep
    # the historical global behaviour. A breached client arm halts work IN that
    # arm, not every arm on the machine.
    scoped = []
    for b in arms_cfg:
        pth = (b or {}).get("path") if isinstance(b, dict) else None
        if pth:
            if not cwd:
                continue  # scoped cap, no cwd to scope against: not applicable here
            root = os.path.expanduser(str(pth)).rstrip("/")
            c = str(cwd).rstrip("/")
            if not (c == root or c.startswith(root + "/")):
                continue  # directory boundary, not a string prefix (hot vs hotter)
        scoped.append(b)
    arms_cfg = scoped

    # Index per-arm overrides
    overrides = {b["arm"]: b for b in arms_cfg if isinstance(b, dict) and "arm" in b}

    # No cap can apply: every row below would `continue` on cap <= 0, so the
    # verdict is OK whatever the spend. Skip computing it (the profiler is the
    # whole cost of this hook). Same decision, measured: a config with no cap
    # paid the full profiler run on every spawn.
    if not _any_cap(default, overrides, arm_filter):
        return {"status": "OK", "arms": [], "halt_reason": None,
                "note": "no cap applies here"}

    # Spend source: the profiler by default (through the cache), or a JSON file
    # {arm: usd} named by `spend_json` (an external FinOps export, or a
    # fixture). Config-first.
    spend_json = cfg.get("spend_json")
    if spend_json:
        try:
            spend = {k: float(v) for k, v in json.loads(
                Path(os.path.expanduser(str(spend_json))).read_text(encoding="utf-8")).items()}
        except Exception:
            spend = {}
    else:
        spend = _cached_spend()

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
    for w in verdict.get("config_warnings") or []:
        print(f"  WARN config: {w} (fix: {verdict.get('config_fix', CONFIG_FIX)})")
    for r in verdict["arms"]:
        marker = {"OK": "✓", "WARN": "⚠", "HARD_STOP": "🛑"}.get(r["verdict"], "?")
        print(
            f"  {marker} {r['arm']:24}  spent ${r['spent_usd']:>8,.2f}  "
            f"cap ${r['cap_usd']:>8,.2f}  ({r['action_on_breach']})"
        )
    if verdict.get("halt_reason"):
        print()
        print(f"HALT REASON: {verdict['halt_reason']}")


# -- v8 kernel journal (Phase 4, v8-kernel.md) --------------------------------
_KERNEL_RULE = "FLOW.budget-halt"


def _journal_deny(reason, payload=None, tool_use_id=None) -> None:
    """Mirror this refusal into the refusing process's journal.

    FAIL-OPEN by contract: every error is swallowed and the verdict this gate
    just reached is unchanged. A journal that cannot be written must never turn
    a deny into an allow. kernel_proc is loaded by PATH through importlib, not
    by name, so nothing on sys.path can shadow it.
    """
    try:
        import importlib.util
        import os as _os
        _path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "kernel_proc.py")
        _spec = importlib.util.spec_from_file_location("_kernel_proc_journal", _path)
        _kp = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_kp)
        _payload = payload if isinstance(payload, dict) else {}
        _kp.journal_deny(_KERNEL_RULE, reason,
                         tool_use_id if tool_use_id is not None else _payload.get("tool_use_id"),
                         _kp.resolve_pid(_payload))
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="FinOps budget cap checker (Feature 3 of the brain FinOps pipeline).",
    )
    parser.add_argument("--arm", default=None, help="Restrict the check to one arm.")
    parser.add_argument("--tool", default=None, help="Name of the tool being checked (logged only).")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of human text.")
    parser.add_argument("--refresh", action="store_true",
                        help="Recompute the spend cache (SessionStart / PostToolUse[Agent] hooks).")
    parser.add_argument("--background", action="store_true",
                        help="With --refresh: detach the recompute and return at once.")
    if "--selftest" in (argv if argv is not None else sys.argv[1:]):
        return _selftest()
    args = parser.parse_args(argv)
    if args.refresh:
        return _refresh_main(args.background)

    # As a PreToolUse hook the harness passes the payload on stdin; only `cwd`
    # is read from it (for path-scoped caps). Never blocks on a missing stdin.
    cwd = None
    payload: dict = {}
    try:
        if not sys.stdin.isatty():
            raw = sys.stdin.read()
            if raw.strip():
                payload = json.loads(raw) or {}
                cwd = payload.get("cwd")
    except Exception:
        cwd, payload = None, {}

    verdict = evaluate(arm_filter=args.arm, cwd=cwd)
    if args.tool:
        verdict["tool"] = args.tool

    if args.json:
        json.dump(verdict, sys.stdout, indent=2)
        sys.stdout.write("\n")
        for w in verdict.get("config_warnings") or []:
            sys.stderr.write(f"WARN budget-check config: {w} (fix: {CONFIG_FIX})\n")
    else:
        _print_human(verdict)

    if verdict["status"] == "HARD_STOP":
        _journal_deny(verdict.get("halt_reason") or "budget cap breached", payload)
        return 2
    return 0


def _selftest() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import gate_selftest
    argv = sys.argv
    fixture = argv[argv.index("--selftest") + 1] if len(argv) > argv.index("--selftest") + 1 \
        else "registry/fixtures/FLOW.budget-halt"
    rc = gate_selftest.run_gate_selftest(__file__, fixture)
    fdir = Path(fixture)
    if not fdir.is_absolute():
        fdir = Path(__file__).resolve().parent.parent / fdir
    # Named cached-spend, not cache: a generic `cache/` ignore rule would keep
    # the fixture out of git and the leg would silently not run on a clone.
    if rc == 0 and (fdir / "cached-spend").is_dir():
        rc = _cache_selftest(fdir / "cached-spend")
    elif rc == 0 and fdir.name == "FLOW.budget-halt":
        print(f"selftest FAIL: {fdir}/cached-spend is missing; the cache path is unproven",
              file=sys.stderr)
        rc = 1
    return rc


def _cache_selftest(cdir: Path) -> int:
    """The pair above takes spend from `spend_json` and never reads the cache.
    This leg drives the real hook through the cache: a budgets config with no
    `spend_json`, and the cache written FRESH at run time from cache/spend.json
    (a static timestamp would always be stale). violation*.json must block and
    benign*.json must allow. If the cache path broke, the hook would fall back
    to the profiler, which finds no spend in the empty sandbox, and the
    violation would not block."""
    import shutil
    import tempfile
    import gate_selftest
    violations, benigns = sorted(cdir.glob("violation*.json")), sorted(cdir.glob("benign*.json"))
    if not violations or not benigns or not (cdir / "budgets.yaml").is_file() \
            or not (cdir / "spend.json").is_file():
        print(f"selftest FAIL: {cdir} needs budgets.yaml, spend.json, violation*.json, benign*.json",
              file=sys.stderr)
        return 1
    failures = []
    for must_block, files in ((True, violations), (False, benigns)):
        for f in files:
            sandbox = Path(tempfile.mkdtemp(prefix="budget-cache-selftest-"))
            try:
                (sandbox / ".claude").mkdir()
                shutil.copy(cdir / "budgets.yaml", sandbox / ".claude" / "budgets.yaml")
                spend = json.loads((cdir / "spend.json").read_text(encoding="utf-8"))
                now = _dt.datetime.now().timestamp()
                cache = sandbox / ".claude" / ".cache" / "budget" / "spend.json"
                cache.parent.mkdir(parents=True)
                cache.write_text(json.dumps({"computed_at": now,
                                             "month": _dt.date.fromtimestamp(now).strftime("%Y-%m"),
                                             "spend": spend}), encoding="utf-8")
                rc, out = gate_selftest._run_leg(Path(__file__).resolve(),
                                                 gate_selftest._prep_payload(f, cdir, sandbox), sandbox)
            except Exception as exc:  # a leg that cannot be built proves nothing
                failures.append(f"{f.name} could not run: {exc}")
                continue
            finally:
                shutil.rmtree(sandbox, ignore_errors=True)
            if gate_selftest.emits_block(rc, out) != must_block:
                failures.append(f"{f.name} {'did NOT block' if must_block else 'WAS blocked'} (rc={rc})")
    if failures:
        print("selftest FAIL (cache): " + "; ".join(failures), file=sys.stderr)
        return 1
    print(f"selftest PASS (cache): {len(violations)} block + {len(benigns)} allow ({cdir.name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
