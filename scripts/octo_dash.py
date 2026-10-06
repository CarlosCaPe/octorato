#!/usr/bin/env python3
"""octo_dash.py: one self-contained HTML page of what the brain already knows.

    octo dash              write the page from local state, print its path
    octo dash --refresh    first take a pull request snapshot with `gh`, then write
    octo dash --out PATH   write somewhere else (tests, a second copy)

Every number on the page already exists somewhere on disk; this file only reads
it. Five sections, each read independently so one missing source never blanks
the page:

  specs      docs/specs/*/ : the Status header, the checkbox count of plan.md and
             the newest anchored converge receipt (receipt_ledger.converge_latest_for)
  pulls      ONLY the local snapshot `--refresh` stored. Rendering never touches
             the network, so the page states how old the snapshot is. Per pull
             request: the newest qa receipt in the ledger (by the harness
             timestamp of its entry), the head it pinned, the current head, and
             the anchored verdict that decides the CURRENT head
             (receipt_ledger.qa_latest_for, the same lookup the merge gate uses)
  gate       the v7 gate receipt for this tree: gate_tree_hash + gate_receipt_ok,
             voided by gate_surfaces_dirty, exactly as the outward-send gate reads
             it, without running the slow full doctor
  kernel     live processes, by kernel_proc.is_live (v8-kernel.md section 2)
  friction   the Friction_Ledger read with friction_ledger.py's field names, and
             `octo friction`'s report called in-process (local files only) when
             this brain has it; otherwise "not available" and the page renders

Everything rendered goes through html.escape. Titles, branch names, spec names
and ledger fields are untrusted text; the page carries no script at all, so
there is nothing for an injected string to reach.

The page lives under ~/.claude/.cache/dash/, which .gitignore already excludes
(`.cache/`), so a page that shows PR titles and paths never lands in git.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

PR_FIELDS = "number,title,headRefOid,headRefName,isDraft,updatedAt,url"
_STATUS = re.compile(r"^\s*>?\s*\*\*Status:\*\*\s*([A-Za-z-]+)", re.MULTILINE)
_FORMAT = re.compile(r"^\s*>?\s*\*\*Spec-Format:\*\*\s*(\S+)", re.MULTILINE)
_TASK = re.compile(r"^\s*[-*]\s+\[([ xX])\]", re.MULTILINE)
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
HEAD_LINES = 30


# ── paths ───────────────────────────────────────────────────────────────────

def brain_root() -> Path:
    return _HERE.parent


def cache_dir() -> Path:
    return Path(os.path.expanduser("~")) / ".claude" / ".cache" / "dash"


def snapshot_path() -> Path:
    return cache_dir() / "prs.json"


def friction_ledger_path() -> Path:
    """The Friction_Ledger as friction_ledger.py defines it (OCTO_FRICTION_DIR
    for tests, else the gitignored cache). The fallback mirrors that rule for a
    brain where the module is not installed yet."""
    try:
        import friction_ledger
        return Path(friction_ledger.ledger_dir()) / "ledger.jsonl"
    except Exception:  # noqa: BLE001
        env = os.environ.get("OCTO_FRICTION_DIR")
        base = Path(env) if env else Path(os.path.expanduser("~")) / ".claude" / ".cache" / "friction"
        return base / "ledger.jsonl"


class _NoOptionalLocks:
    """`git status` refreshes the index and takes .git/index.lock while it does,
    so a reader running beside the operator could make their commit fail on
    "index.lock exists". GIT_OPTIONAL_LOCKS=0 tells git to skip that optional
    lock; receipt_ledger builds its git env from os.environ, so it inherits it."""

    def __enter__(self):
        self._old = os.environ.get("GIT_OPTIONAL_LOCKS")
        os.environ["GIT_OPTIONAL_LOCKS"] = "0"
        return self

    def __exit__(self, *exc):
        if self._old is None:
            os.environ.pop("GIT_OPTIONAL_LOCKS", None)
        else:
            os.environ["GIT_OPTIONAL_LOCKS"] = self._old
        return False


def _age(seconds) -> str:
    if seconds is None:
        return "-"
    s = int(max(0, seconds))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    if s < 86400:
        return f"{s // 3600}h{(s % 3600) // 60:02d}m"
    return f"{s // 86400}d{(s % 86400) // 3600:02d}h"


def _e(value) -> str:
    """The one way text reaches the page."""
    return html.escape("" if value is None else str(value), quote=True)


# ── readers (each returns plain data; never raises) ─────────────────────────

def read_specs(root: Path) -> dict:
    base = root / "docs" / "specs"
    out = {"rows": [], "error": None}
    if not base.is_dir():
        out["error"] = "no docs/specs directory"
        return out
    try:
        import receipt_ledger
    except Exception as e:  # noqa: BLE001
        receipt_ledger, out["error"] = None, f"receipt ledger unavailable: {e}"
    for d in sorted((p for p in base.iterdir() if p.is_dir()), reverse=True):
        feature, plan = d / "feature.md", d / "plan.md"
        row = {"name": d.name, "status": "?", "format": "-", "done": 0, "total": 0,
               "converge": None, "converge_ts": None}
        try:
            head = "\n".join(feature.read_text(encoding="utf-8", errors="replace")
                             .splitlines()[:HEAD_LINES])
            m = _STATUS.search(head)
            row["status"] = m.group(1).lower() if m else "?"
            m = _FORMAT.search(head)
            row["format"] = m.group(1) if m else "-"
        except OSError:
            row["status"] = "no feature.md"
        try:
            marks = _TASK.findall(plan.read_text(encoding="utf-8", errors="replace"))
            row["total"] = len(marks)
            row["done"] = sum(1 for x in marks if x in "xX")
        except OSError:
            pass
        if receipt_ledger is not None:
            try:
                r = receipt_ledger.converge_latest_for(f"docs/specs/{d.name}")
                if r:
                    row["converge"] = str(r.get("verdict") or "?")
                    row["converge_ts"] = str(r.get("verdict_ts") or "")
            except Exception:  # noqa: BLE001
                row["converge"] = "unreadable"
        out["rows"].append(row)
    return out


def take_snapshot(root: Path, limit: int = 100) -> dict:
    """The only network call this tool makes, and only under --refresh."""
    cp = subprocess.run(["gh", "pr", "list", "--state", "open", "--limit", str(limit),
                         "--json", PR_FIELDS], cwd=str(root),
                        capture_output=True, text=True, timeout=60)
    if cp.returncode != 0:
        raise RuntimeError((cp.stderr or cp.stdout or "gh pr list failed").strip()[:400])
    prs = json.loads(cp.stdout or "[]")
    snap = {"taken_ts": time.time(), "prs": prs if isinstance(prs, list) else []}
    cache_dir().mkdir(parents=True, exist_ok=True)
    tmp = snapshot_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(snap, indent=1), encoding="utf-8")
    os.replace(tmp, snapshot_path())
    return snap


def _newest_qa_rows(rows: list, number: str) -> dict | None:
    import receipt_ledger
    best, best_key = None, None
    for r in rows:
        if r.get("kind") != "qa" or not receipt_ledger.scope_names(str(r.get("scope") or ""), number):
            continue
        key = str(r.get("entry_ts") or "")
        if best is None or key >= best_key:
            best, best_key = r, key
    return best


def read_pulls(now: float) -> dict:
    out = {"rows": [], "age": None, "error": None}
    try:
        snap = json.loads(snapshot_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        out["error"] = "no snapshot yet: run `octo dash --refresh`"
        return out
    except (OSError, ValueError) as e:
        out["error"] = f"snapshot unreadable: {e}"
        return out
    if not isinstance(snap, dict):
        out["error"] = f"snapshot malformed: top level is {type(snap).__name__}, not an object"
        return out
    try:
        out["age"] = now - float(snap.get("taken_ts"))
    except (TypeError, ValueError):
        out["age"] = None
    prs = snap.get("prs")
    if prs is None:
        prs = []
    if not isinstance(prs, list):
        out["error"] = f"snapshot malformed: prs is {type(prs).__name__}, not a list"
        return out
    skipped = sum(1 for pr in prs if not isinstance(pr, dict))
    if skipped:
        out["error"] = f"snapshot malformed: {skipped} pull request entry(ies) not an object, skipped"
    try:
        import receipt_ledger
        ledger = receipt_ledger.read_global()
    except Exception:  # noqa: BLE001
        receipt_ledger, ledger = None, []
    for pr in prs:
        if not isinstance(pr, dict):
            continue
        num = str(pr.get("number") or "")
        head = str(pr.get("headRefOid") or "").lower()
        row = {"number": num, "title": pr.get("title"), "branch": pr.get("headRefName"),
               "draft": bool(pr.get("isDraft")), "url": pr.get("url"), "head": head,
               "qa": None, "qa_head": None, "decides": None}
        if receipt_ledger is not None and num:
            try:
                newest = _newest_qa_rows(ledger, num)
                if newest:
                    row["qa"] = str(newest.get("verdict") or "?")
                    row["qa_head"] = str(newest.get("head") or "")
                if _SHA40.match(head):
                    dec = receipt_ledger.qa_latest_for(num, head)
                    row["decides"] = str(dec.get("verdict")) if dec else None
            except Exception:  # noqa: BLE001
                row["decides"] = "unreadable"
        out["rows"].append(row)
    return out


def read_gate(root: Path) -> dict:
    """Same three reads the outward-send gate makes, in the same order."""
    try:
        import receipt_ledger
        with _NoOptionalLocks():
            gates = receipt_ledger.gate_tree_hash(root)
            dirty = receipt_ledger.gate_surfaces_dirty(root)
            ok = receipt_ledger.gate_receipt_ok(gates) if gates else False
            head = receipt_ledger.brain_head(root)
    except Exception as e:  # noqa: BLE001
        return {"state": "unknown", "detail": f"unreadable: {e}", "dirty": []}
    if not gates:
        return {"state": "unknown", "detail": "gate tree could not be resolved", "dirty": []}
    if dirty:
        return {"state": "dirty", "detail": f"{len(dirty)} gate surface file(s) differ from HEAD",
                "dirty": dirty[:20], "head": head}
    if ok:
        return {"state": "ok", "detail": "receipt present for this gate tree", "dirty": [], "head": head}
    return {"state": "none", "detail": "no doctor has proven the gates at this tree; "
            "run brain_doctor.py --gate-receipt", "dirty": [], "head": head}


def read_kernel(now: float) -> dict:
    try:
        import kernel_proc
        table = kernel_proc.read_ptable()
    except Exception as e:  # noqa: BLE001
        return {"rows": [], "total": 0, "error": f"kernel unreadable: {e}"}
    procs = table.get("processes", {}) if isinstance(table, dict) else {}
    rows = []
    for pid, row in procs.items():
        try:
            if not kernel_proc.is_live(pid, table, now):
                continue
        except Exception:  # noqa: BLE001
            continue
        started = row.get("registered_ts")
        try:
            age = now - float(started) if started else None
        except (TypeError, ValueError):
            age = None
        rows.append({"pid": pid, "ppid": row.get("ppid") or "-",
                     "type": row.get("type") or kernel_proc.UNKNOWN_TYPE,
                     "age": age, "worktree": row.get("worktree") or "-"})
    rows.sort(key=lambda r: -(r["age"] or 0))
    return {"rows": rows, "total": len(procs), "error": None}


def _ts_of(rec: dict):
    v = rec.get("ts")
    try:
        return float(v)
    except (TypeError, ValueError):
        pass
    try:
        import datetime as _dt
        t = _dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return t.timestamp()
    except (TypeError, ValueError):
        return None


def _octo_friction_report(days: int = 7):
    """`octo friction`'s own report, called in-process. It reads only local
    files (the ledger, latency.jsonl, registry/friction-baseline.json), so it is
    bounded by their size and never touches the network. None when this brain's
    octo.py has no friction report yet."""
    try:
        import octo
        fn = getattr(octo, "friction_report", None)
        return fn(days) if callable(fn) else None
    except Exception as e:  # noqa: BLE001
        return {"error": f"octo friction report failed: {e}"}


def read_friction(now: float) -> dict:
    """Field names are friction_ledger.py's: gate, kind, code, session, ts (ISO).
    A line with no usable `gate` is counted, never shown as `?`."""
    out = {"available": False, "rows": [], "lines": 0, "unrecognised": 0,
           "report": None, "error": None}
    path = friction_ledger_path()
    if path.is_file():
        out["available"] = True
        per = {}
        try:
            with open(path, "rb") as fh:
                for raw in fh:
                    if not raw.strip():
                        continue
                    out["lines"] += 1
                    try:
                        rec = json.loads(raw)
                    except ValueError:
                        rec = None
                    gate = rec.get("gate") if isinstance(rec, dict) else None
                    if not isinstance(gate, str) or not gate.strip():
                        out["unrecognised"] += 1
                        continue
                    slot = per.setdefault(gate, {"gate": gate, "all": 0, "d1": 0, "d7": 0,
                                                 "last": None, "codes": {}})
                    slot["all"] += 1
                    code = rec.get("code")
                    if isinstance(code, str) and code:
                        slot["codes"][code] = slot["codes"].get(code, 0) + 1
                    ts = _ts_of(rec)
                    if ts is not None:
                        if now - ts <= 86400:
                            slot["d1"] += 1
                        if now - ts <= 7 * 86400:
                            slot["d7"] += 1
                        slot["last"] = ts if slot["last"] is None else max(slot["last"], ts)
        except OSError as e:
            out["error"] = f"ledger unreadable: {e}"
        out["rows"] = sorted(per.values(), key=lambda s: (-s["d7"], -s["all"], s["gate"]))
    rep = _octo_friction_report(7)
    if isinstance(rep, dict):
        out["available"] = True
        if rep.get("error"):
            out["error"] = rep["error"]
        else:
            out["report"] = rep
    return out


# ── render ──────────────────────────────────────────────────────────────────

CSS = """
:root{--bg:#f7f7f5;--card:#fff;--fg:#1d1d1b;--muted:#6b6b66;--line:#e3e3de;
--ok:#1f7a3d;--warn:#9a6700;--bad:#b42318;--chip:#efefea}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--card:#1f1f1d;--fg:#ececea;
--muted:#9a9a94;--line:#33332f;--ok:#4cc36f;--warn:#e0a63a;--bad:#ff6b5e;--chip:#2a2a27}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1100px;margin:0 auto;padding:20px 16px 48px}
h1{font-size:22px;margin:0 0 4px}
.sub{color:var(--muted);font-size:13px;margin-bottom:18px;overflow-wrap:anywhere}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:14px 16px;margin:0 0 16px}
h2{font-size:16px;margin:0 0 10px}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600;white-space:nowrap}
td.num{font-variant-numeric:tabular-nums;white-space:nowrap}
code,.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12.5px}
.chip{display:inline-block;padding:1px 8px;border-radius:999px;background:var(--chip);
font-size:12px;white-space:nowrap}
.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}.muted{color:var(--muted)}
.bar{height:6px;background:var(--chip);border-radius:3px;min-width:60px;margin-top:4px}
.bar>span{display:block;height:100%;background:var(--ok);border-radius:3px}
pre{white-space:pre-wrap;word-break:break-word;margin:0;font-size:12.5px}
a{color:inherit}
@media (max-width:600px){th,td{padding:5px 4px}.hide-sm{display:none}}
"""

_VERDICT_CLASS = {"PASS": "ok", "CONVERGED": "ok", "ok": "ok", "FAIL": "bad", "GAPS": "bad",
                  "NEEDS-WORK": "warn", "dirty": "warn", "none": "bad", "unknown": "warn",
                  "converged": "ok", "approved": "warn", "draft": "muted"}


def _chip(text, cls=None) -> str:
    cls = cls or _VERDICT_CLASS.get(str(text), "muted")
    return f'<span class="chip {cls}">{_e(text)}</span>'


def _short(sha) -> str:
    return _e(str(sha or "")[:8] or "-")


def _safe_url(url) -> str | None:
    u = str(url or "")
    return u if re.match(r"^https://github\.com/[\w.\-]+/[\w.\-]+/pull/\d+$", u) else None


def _section(title: str, body: str) -> str:
    return f"<section><h2>{_e(title)}</h2>{body}</section>"


def render(data: dict) -> str:
    now = data["now"]
    parts = []

    sp = data["specs"]
    if sp["rows"]:
        trs = []
        for r in sp["rows"]:
            pct = int(100 * r["done"] / r["total"]) if r["total"] else 0
            conv = (_chip(r["converge"]) + f' <span class="muted mono">{_e(r["converge_ts"] or "")}</span>'
                    if r["converge"] else '<span class="muted">no receipt</span>')
            trs.append(
                f'<tr><td class="mono">{_e(r["name"])}</td><td>{_chip(r["status"])}</td>'
                f'<td class="hide-sm mono">{_e(r["format"])}</td>'
                f'<td class="num">{r["done"]}/{r["total"]}<div class="bar"><span style="width:{pct}%"></span></div></td>'
                f"<td>{conv}</td></tr>")
        body = ('<div class="scroll"><table><tr><th>spec</th><th>status</th><th class="hide-sm">format</th>'
                "<th>tasks</th><th>converge</th></tr>" + "".join(trs) + "</table></div>")
    else:
        body = '<p class="muted">no specs</p>'
    if sp["error"]:
        body += f'<p class="warn">{_e(sp["error"])}</p>'
    parts.append(_section("Specs", body))

    pl = data["pulls"]
    age = f"snapshot age: {_age(pl['age'])}" if pl["age"] is not None else "snapshot age: none"
    body = f'<p class="muted">{_e(age)} (refresh with <code>octo dash --refresh</code>)</p>'
    if pl["error"]:
        body += f'<p class="warn">{_e(pl["error"])}</p>'
    if pl["rows"]:
        trs = []
        for r in pl["rows"]:
            url = _safe_url(r["url"])
            num = (f'<a href="{_e(url)}">#{_e(r["number"])}</a>' if url else f"#{_e(r['number'])}")
            match = ""
            if r["qa_head"]:
                same = r["qa_head"].lower() == r["head"]
                match = _chip("pinned = head" if same else "head moved", "ok" if same else "warn")
            trs.append(
                f"<tr><td class=\"num\">{num}</td><td>{_e(r['title'])}"
                f"{' ' + _chip('draft') if r['draft'] else ''}"
                f'<div class="muted mono">{_e(r["branch"])}</div></td>'
                f"<td>{_chip(r['qa']) if r['qa'] else '<span class=\"muted\">none</span>'}</td>"
                f'<td class="mono">{_short(r["qa_head"])}</td><td class="mono">{_short(r["head"])}</td>'
                f"<td>{match}</td>"
                f"<td>{_chip(r['decides']) if r['decides'] else '<span class=\"muted\">none</span>'}</td></tr>")
        body += ('<div class="scroll"><table><tr><th>PR</th><th>title</th><th>newest QA</th>'
                 "<th>pinned</th><th>head</th><th></th><th>decides head</th></tr>"
                 + "".join(trs) + "</table></div>")
    elif not pl["error"]:
        body += '<p class="muted">no open pull requests in the snapshot</p>'
    parts.append(_section("Pull requests", body))

    g = data["gate"]
    body = f"<p>{_chip(g['state'])} {_e(g['detail'])}</p>"
    if g.get("head"):
        body += f'<p class="muted">HEAD <code>{_short(g["head"])}</code></p>'
    if g.get("dirty"):
        body += "<pre>" + _e("\n".join(g["dirty"])) + "</pre>"
    parts.append(_section("Gate receipt", body))

    k = data["kernel"]
    if k["error"]:
        body = f'<p class="warn">{_e(k["error"])}</p>'
    else:
        body = f'<p class="muted">{len(k["rows"])} live of {k["total"]} registered</p>'
        if k["rows"]:
            trs = [f'<tr><td class="mono">{_e(r["pid"][:12])}</td><td class="mono hide-sm">{_e(str(r["ppid"])[:12])}</td>'
                   f'<td>{_e(r["type"])}</td><td class="num">{_e(_age(r["age"]))}</td>'
                   f'<td class="mono hide-sm">{_e(r["worktree"])}</td></tr>' for r in k["rows"]]
            body += ('<div class="scroll"><table><tr><th>pid</th><th class="hide-sm">ppid</th><th>type</th>'
                     '<th>age</th><th class="hide-sm">worktree</th></tr>' + "".join(trs) + "</table></div>")
    parts.append(_section("Live kernel processes", body))

    f = data["friction"]
    if not f["available"]:
        body = '<p class="muted">not available (no friction ledger and no <code>octo friction</code> on this brain)</p>'
    else:
        body = ""
        if f["lines"]:
            body += f'<p class="muted">{f["lines"]} ledger line(s)'
            if f["unrecognised"]:
                body += f', {f["unrecognised"]} line(s) with no recognised fields'
            body += "</p>"
        if f["rows"]:
            trs = []
            for r in f["rows"]:
                top = max(r["codes"].items(), key=lambda kv: (kv[1], kv[0]))[0] if r["codes"] else "-"
                trs.append(f'<tr><td class="mono">{_e(r["gate"])}</td><td class="num">{r["d1"]}</td>'
                           f'<td class="num">{r["d7"]}</td><td class="num">{r["all"]}</td>'
                           f'<td class="mono hide-sm">{_e(top)}</td>'
                           f'<td class="num">{_e(_age(now - r["last"]) if r["last"] else "-")}</td></tr>')
            body += ('<div class="scroll"><table>'
                     '<tr><th>gate</th><th>24 h</th><th>7 d</th><th>all</th><th class="hide-sm">top code</th>'
                     "<th>last</th></tr>" + "".join(trs) + "</table></div>")
        rep = f["report"]
        if rep and rep.get("gates"):
            trs = []
            for g in rep["gates"]:
                if not isinstance(g, dict):
                    continue
                lab = g.get("labelled") if isinstance(g.get("labelled"), dict) else None
                fp = f'{lab.get("fp_rate", 0):.0%}' if lab else "-"
                p50, p95 = g.get("latency_p50_ms"), g.get("latency_p95_ms")
                p50 = "-" if not isinstance(p50, (int, float)) else f"{p50:.0f}"
                p95 = "-" if not isinstance(p95, (int, float)) else f"{p95:.0f}"
                trs.append(f'<tr><td class="mono">{_e(g.get("gate"))}</td>'
                           f'<td class="num">{_e(g.get("denies"))}</td>'
                           f'<td class="num">{_e(p50)}</td><td class="num">{_e(p95)}</td>'
                           f'<td class="num">{_e(fp)}</td></tr>')
            body += (f'<p class="muted">octo friction, last {_e(rep.get("days"))} day(s): '
                     f'{_e(rep.get("ledger_rows"))} deny/block row(s), '
                     f'{_e(rep.get("latency_rows"))} latency sample(s)</p><div class="scroll"><table>'
                     "<tr><th>gate or hook</th><th>denies</th><th>p50 ms</th><th>p95 ms</th>"
                     "<th>FP rate</th></tr>" + "".join(trs) + "</table></div>")
        if f["error"]:
            body += f'<p class="warn">{_e(f["error"])}</p>'
        if not body:
            body = '<p class="muted">ledger present, no lines yet</p>'
    parts.append(_section("Friction", body))

    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; "
            "style-src 'unsafe-inline'; img-src data:\">"
            f"<title>Octorato dash</title><style>{CSS}</style></head><body><main>"
            f"<h1>Octorato dash</h1><div class=\"sub\">written {_e(stamp)} from local state "
            f"of <code>{_e(data['root'])}</code></div>" + "".join(parts) + "</main></body></html>\n")


def collect(root: Path, now: float = None) -> dict:
    now = time.time() if now is None else now
    return {"now": now, "root": str(root), "specs": read_specs(root), "pulls": read_pulls(now),
            "gate": read_gate(root), "kernel": read_kernel(now), "friction": read_friction(now)}


def write_page(root: Path = None, out: Path = None) -> Path:
    root = root or brain_root()
    out = out or (cache_dir() / "index.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(render(collect(root)), encoding="utf-8")
    os.replace(tmp, out)
    return out


# ── cli ─────────────────────────────────────────────────────────────────────

def run(args) -> int:
    """Exit 2 when --refresh could not take a snapshot. The page is still
    written from the previous one, so the caller gets the page and the signal
    that its PR data is old."""
    root = Path(args.root).resolve() if getattr(args, "root", None) else brain_root()
    rc = 0
    if getattr(args, "refresh", False):
        try:
            snap = take_snapshot(root)
            print(f"snapshot: {len(snap['prs'])} open pull request(s) -> {snapshot_path()}")
        except Exception as e:  # noqa: BLE001
            print(f"snapshot failed, rendering the previous one: {e}", file=sys.stderr)
            rc = 2
    out = write_page(root, Path(args.out) if getattr(args, "out", None) else None)
    print(out)
    return rc


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--refresh", action="store_true",
                   help="take a fresh open-PR snapshot with gh before rendering")
    p.add_argument("--out", metavar="PATH", help="write the page here instead of the cache")
    p.add_argument("--root", metavar="DIR", help="brain checkout to read specs and the gate from")


def selftest() -> int:
    """Hermetic: sandbox HOME, a synthetic spec and snapshot carrying markup.
    Proves the page renders every section and that no injected tag survives."""
    import shutil
    import tempfile
    sandbox = tempfile.mkdtemp(prefix="octo-dash-selftest-")
    saved = os.environ.get("HOME")
    try:
        os.environ["HOME"] = sandbox
        root = Path(sandbox) / "brain"
        spec = root / "docs" / "specs" / "200001010000-synthetic"
        spec.mkdir(parents=True)
        (spec / "feature.md").write_text("# F\n\n> **Spec-Format:** ears-1\n> **Status:** draft\n",
                                         encoding="utf-8")
        (spec / "plan.md").write_text("- [x] T01 a\n- [ ] T02 b\n", encoding="utf-8")
        cache_dir().mkdir(parents=True)
        snapshot_path().write_text(json.dumps({"taken_ts": time.time() - 90, "prs": [
            {"number": 7, "title": "<script>alert(1)</script>", "headRefOid": "a" * 40,
             "headRefName": "x\"><img src=x onerror=1>", "isDraft": False,
             "url": "javascript:alert(1)"}]}), encoding="utf-8")
        page = render(collect(root)).lower()
        bad = [t for t in ("<script", "<img", "javascript:") if t in page]
        need = [t for t in ("specs", "pull requests", "gate receipt", "live kernel processes",
                            "friction", "snapshot age: 1m", "1/2", "not available") if t not in page]
        if bad or need:
            print(f"selftest FAIL: injected={bad} missing={need}", file=sys.stderr)
            return 1
        print("selftest PASS: every section renders, injected markup stays inert")
        return 0
    finally:
        if saved is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = saved
        shutil.rmtree(sandbox, ignore_errors=True)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="octo dash", description=__doc__.split("\n")[0])
    p.add_argument("--selftest", action="store_true")
    add_arguments(p)
    args = p.parse_args(argv)
    if args.selftest:
        return selftest()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
