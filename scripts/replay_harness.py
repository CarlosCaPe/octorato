#!/usr/bin/env python3
"""replay_harness.py: replay real tool calls and Stop turns through the gates (v10 FR-01, AC-03, AC-04).

A gate change that loosens something is invisible to a fixture pair: the pair
proves the gate still blocks ONE violation, not that it still blocks the real
traffic it blocked last month. This harness keeps that traffic as a frozen,
private corpus and replays every case through the gate script it belongs to,
exactly as the harness would call it (the hook payload as JSON on stdin, the
decision read from the exit code and stdout), then diffs the result against a
stored baseline.

    build     scan the transcripts of a date window, freeze the corpus, label it,
              replay it once and write the baseline
    replay    replay the corpus against the gates in THIS checkout and print
              allow->deny and deny->allow against the baseline; exit 1 when a
              case labelled TP that the baseline denied is no longer denied
    baseline  replay and rewrite the baseline (an intended change, reviewed)
    label     re-apply the private label rules to the corpus and the baseline

PRIVATE vs TRACKED. The corpus holds real prompts, commands and message text,
so it lives in the gitignored `company/friction-corpus/` (or `--corpus`,
`OCTO_FRICTION_CORPUS`) and never leaves the machine. The tracked
`registry/friction-baseline.json` holds only counts and, per case, a 16-hex id
(sha256 of gate and harness uuid), the gate, the replayed decision, a reason
code from `registry/friction-signatures.json`, the historical decision and the
label. Nothing in it reconstructs a prompt, a command or a body.

A case is one gate and one event:
  * a real deny or Stop block of that gate (historical decision `deny`), and
  * a sample of real calls and turns the same gate let through (`allow`),
    drawn per gate with a fixed seed from the calls its hooks.json matcher
    covers, so allow->deny regressions are visible too.
Each case carries the hook payload and a WINDOW of the transcript that ends at
the event: the records since the 10th operator prompt back (at most 1,500),
every earlier operator prompt as text, tool_result bodies and earlier tool_use
inputs cut to 2,000 characters, assistant and operator text whole. The gate
reads that window as its
transcript_path.

ISOLATION. Every case runs under a fresh temp HOME, with the operator-override
env vars stripped and `CLAUDE_SESSION_ID=__selftest__`, which is the same
isolation `gate_selftest.py` gives a fixture leg (and the same seam the
outward-send gate uses to accept a seeded gate receipt, so the receipt check
does not mask the checks behind it). What the replay therefore CANNOT see, and
what makes a replayed decision differ from the historical one: receipts and
ledgers that lived in the real HOME (panel, QA, delegation ledger, kernel
process table, block-once sentinels), the operator's private config under
`company/config/`, the live state of the cwd the call ran in, and anything the
window cut. The baseline records both decisions, so the agreement rate per gate
is printed rather than assumed.

LABELS. `company/friction-corpus/label-rules.json` (private) holds ordered
rules: {gate, code?, hist?, sub?, field: input|prompt|reason|blocked,
pattern, label: TP|FP}. The first rule that matches a case labels it; every
other case is unlabelled. They encode the census's classification and are
reviewed before they become the regression set.

Fresh clone: no corpus, so `replay` prints SKIP and exits 0.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import glob
import gzip
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))

import friction_ledger  # noqa: E402
import gate_selftest  # noqa: E402

BASELINE = REPO / "registry" / "friction-baseline.json"
HOOKS_JSON = REPO / "hooks.json"
BLOCKING = ("deny", "ask")

WINDOW_PROMPTS = 10
WINDOW_RECORDS = 1500
RESULT_CUT = 2000
INPUT_CUT_HISTORY = 2000
ATTACH_CUT = 1000
STRING_CUT = 20000
CASE_TIMEOUT = 30
# Gates that are never replayed: budget-check costs a median 7 s per call and
# blocked nothing in the census window; reflexes and tracers decide nothing.
SKIP_GATES = {"budget-check.py", "trace-hook.py"}
SELFTEST_SESSION = "__selftest__"


# ── locations ───────────────────────────────────────────────────────────────

def corpus_dir(arg: str = "") -> Path:
    if arg:
        return Path(arg)
    env = os.environ.get("OCTO_FRICTION_CORPUS")
    if env:
        return Path(env)
    return REPO / "company" / "friction-corpus"


def gate_path(gate: str) -> Path:
    return HERE / gate


# ── hooks.json: which gates run on which event and tool ─────────────────────

def gate_table() -> list:
    """[(event, matcher_regex, script)] for PreToolUse and Stop hooks."""
    out = []
    try:
        h = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return out
    h = h.get("hooks", h)
    for ev in ("PreToolUse", "Stop"):
        for grp in h.get(ev, []) or []:
            if not isinstance(grp, dict):
                continue
            m = grp.get("matcher") or "*"
            for x in grp.get("hooks", []):
                s = friction_ledger.script_of(x.get("command", ""))
                if not s or s in SKIP_GATES or s.startswith("r__"):
                    continue
                out.append((ev, m, s))
    return out


def matcher_hits(matcher: str, tool: str) -> bool:
    if matcher in ("*", ""):
        return True
    try:
        return re.fullmatch(matcher, tool or "") is not None
    except re.error:
        return matcher == tool


# ── transcript helpers ──────────────────────────────────────────────────────

def _load(path: str) -> list:
    recs = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    recs.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return recs


def _is_prompt(d: dict) -> bool:
    if d.get("type") != "user" or d.get("isMeta") or d.get("isCompactSummary"):
        return False
    c = (d.get("message") or {}).get("content")
    if isinstance(c, list) and any(isinstance(x, dict) and x.get("type") == "tool_result" for x in c):
        return False
    t = friction_ledger._text_of(c)
    return bool(t.strip()) and not t.startswith("Stop hook feedback") \
        and not t.startswith("<system-reminder>")


def _cut(o, n=STRING_CUT):
    if isinstance(o, str):
        return o[:n]
    if isinstance(o, list):
        return [_cut(x, n) for x in o]
    if isinstance(o, dict):
        return {k: _cut(v, n) for k, v in o.items()}
    return o


def _slim(d: dict) -> dict:
    """A window record a gate can still read, at a fraction of the bytes.

    Assistant and operator TEXT is kept whole: Stop gates judge the end of a
    reply (a footer, a closing promise), so cutting it would manufacture denies.
    What is cut is what no gate judges in history: tool_result bodies, tool_use
    inputs of earlier calls, attachment payloads, and the harness's duplicate
    `toolUseResult` copy.
    """
    d = {k: v for k, v in d.items() if k != "toolUseResult"}
    if d.get("type") == "attachment":
        return _cut(d, ATTACH_CUT)
    msg = d.get("message")
    c = (msg or {}).get("content") if isinstance(msg, dict) else None
    if isinstance(c, list):
        new = []
        for x in c:
            if isinstance(x, dict) and x.get("type") == "tool_result":
                x = dict(x, content=_cut(x.get("content"), RESULT_CUT))
            elif isinstance(x, dict) and x.get("type") == "tool_use":
                x = dict(x, input=_cut(x.get("input"), INPUT_CUT_HISTORY))
            new.append(x)
        d["message"] = dict(msg, content=new)
    return d


def window(recs: list, end: int) -> list:
    """recs[start:end] with start set by the prompt and record caps."""
    seen, start = 0, end
    while start > 0 and end - start < WINDOW_RECORDS:
        start -= 1
        if _is_prompt(recs[start]):
            seen += 1
            if seen >= WINDOW_PROMPTS:
                break
    # Every earlier operator prompt rides along, text only: a gate that anchors
    # on the session's first goal (goal-anchor) must see it, and prompts are a
    # few hundred bytes each.
    prefix = [_slim(r) for r in recs[:start] if _is_prompt(r)]
    return prefix + [_slim(r) for r in recs[start:end]]


def _last_prompt(win: list) -> str:
    for d in reversed(win):
        if _is_prompt(d):
            return friction_ledger._text_of((d.get("message") or {}).get("content"))
    return ""


def _last_assistant(win: list) -> str:
    for d in reversed(win):
        if d.get("type") == "assistant":
            t = friction_ledger._text_of((d.get("message") or {}).get("content"))
            if t:
                return t
    return ""


# ── build: scan ─────────────────────────────────────────────────────────────

def _files(root: Path, since: str) -> list:
    t0 = time.mktime(time.strptime(since, "%Y-%m-%d")) if since else 0
    out = []
    for pat in (str(root / "*" / "*.jsonl"), str(root / "*" / "*" / "subagents" / "**" / "*.jsonl")):
        for f in glob.glob(pat, recursive=True):
            try:
                if os.path.getmtime(f) >= t0:
                    out.append(f)
            except OSError:
                pass
    return sorted(out)


def scan_file(path: str, since: str, until: str, table: list) -> dict:
    """Deny events and allow candidates of one transcript (no windows yet)."""
    recs = _load(path)
    sub = "/subagents/" in path
    uses, denied = {}, set()
    out = {"deny": [], "pre_allow": [], "stop_allow": []}
    for i, d in enumerate(recs):
        if d.get("type") == "assistant":
            for c in (d.get("message") or {}).get("content") or []:
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    uses[c.get("id")] = (i, c.get("name"), c.get("input"))
    for i, d in enumerate(recs):
        ts = d.get("timestamp") or ""
        if not (since <= ts[:10] < until):
            continue
        a = d.get("attachment") or {}
        if a.get("type") == "hook_blocking_error":
            be = a.get("blockingError") or {}
            gate, code = friction_ledger.attribute_block(be.get("command") or "", be.get("blockingError") or "")
            out["deny"].append({"key": d.get("uuid"), "gate": gate, "code": code, "event": a.get("hookEvent") or "Stop",
                                "i": i, "tid": None, "reason": be.get("blockingError") or "", "sub": sub})
            continue
        if d.get("subtype") == "stop_hook_summary" and not sub:
            if not d.get("preventedContinuation") and not d.get("hookErrors"):
                out["stop_allow"].append({"key": d.get("uuid"), "i": i, "sub": sub})
            continue
        if d.get("type") != "user":
            continue
        cont = (d.get("message") or {}).get("content")
        if not isinstance(cont, list):
            continue
        for x in cont:
            if not (isinstance(x, dict) and x.get("type") == "tool_result"):
                continue
            tid = x.get("tool_use_id")
            rt = friction_ledger._text_of(x.get("content"))
            m = friction_ledger._PRE_RE.match(rt)
            if m:
                gate, code = friction_ledger.attribute_pretool(m.group(2), m.group(1))
                denied.add(tid)
                if tid in uses:
                    out["deny"].append({"key": f"{d.get('uuid')}:{tid}", "gate": gate, "code": code,
                                        "event": "PreToolUse", "i": uses[tid][0], "tid": tid,
                                        "reason": m.group(2), "sub": sub})
            elif tid in uses and not x.get("is_error"):
                out["pre_allow"].append({"key": f"{d.get('uuid')}:{tid}", "i": uses[tid][0], "tid": tid,
                                         "tool": uses[tid][1], "sub": sub})
    return out


def _case_id(gate: str, key: str) -> str:
    return hashlib.sha256(f"{gate}|{key}".encode()).hexdigest()[:16]


def _payload(recs: list, ev: dict, event: str) -> tuple[dict, list]:
    i = ev["i"]
    d = recs[i]
    sid = d.get("sessionId") or ""
    if event == "PreToolUse":
        win = window(recs, i + 1)
        tool = inp = None
        for c in (d.get("message") or {}).get("content") or []:
            if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("id") == ev["tid"]:
                tool, inp = c.get("name"), c.get("input")
        p = {"session_id": sid, "hook_event_name": "PreToolUse", "tool_name": tool,
             "tool_input": inp, "tool_use_id": ev["tid"], "cwd": d.get("cwd") or ""}
    else:
        end = i
        while end > 0 and recs[end - 1].get("type") != "assistant":
            end -= 1
        win = window(recs, end)
        p = {"session_id": sid, "hook_event_name": event, "stop_hook_active": False,
             "cwd": d.get("cwd") or ""}
    if d.get("agentId"):
        p["agent_id"] = d["agentId"]
    return p, win


def build(args) -> int:
    cdir = corpus_dir(args.corpus)
    root = Path(args.root) if args.root else friction_ledger.projects_dir()
    table = [t for t in gate_table() if gate_path(t[2]).exists()]
    pre_gates = sorted({(m, s) for ev, m, s in table if ev == "PreToolUse"})
    stop_gates = sorted({s for ev, m, s in table if ev == "Stop"})
    files = _files(root, args.since)
    t0 = time.monotonic()
    denies, pre_cand, stop_cand = [], [], []
    seen = set()
    for f in files:
        r = scan_file(f, args.since, args.until, table)
        for e in r["deny"]:
            if e["key"] in seen or e["gate"].startswith("harness:") or not gate_path(e["gate"]).exists():
                continue
            seen.add(e["key"])
            denies.append((f, e))
        pre_cand += [(f, e) for e in r["pre_allow"]]
        stop_cand += [(f, e) for e in r["stop_allow"]]
    rng = random.Random(args.seed)
    picks = [(f, dict(e, kind="deny", hist="deny")) for f, e in denies]
    for m, s in pre_gates:
        cands = [(f, e) for f, e in pre_cand if matcher_hits(m, e["tool"])]
        for f, e in rng.sample(cands, min(args.allow_per_gate, len(cands))):
            picks.append((f, dict(e, gate=s, code="", event="PreToolUse", kind="allow", hist="allow", reason="")))
    for s in stop_gates:
        for f, e in rng.sample(stop_cand, min(args.allow_per_gate, len(stop_cand))):
            picks.append((f, dict(e, gate=s, code="", event="Stop", tid=None, kind="allow", hist="allow",
                                  reason="")))
    # windows: one parse per file that holds a pick
    byfile = {}
    for f, e in picks:
        byfile.setdefault(f, []).append(e)
    if args.fresh:  # the cases and what derives from them; never the operator's label rules
        shutil.rmtree(cdir / "cases", ignore_errors=True)
        for name in ("index.jsonl", "labels.json", "meta.json"):
            (cdir / name).unlink(missing_ok=True)
    (cdir / "cases").mkdir(parents=True, exist_ok=True)
    index, ids = [], set()
    for f, evs in byfile.items():
        recs = _load(f)
        for e in evs:
            cid = _case_id(e["gate"], e["key"])
            if cid in ids:
                continue
            ids.add(cid)
            payload, win = _payload(recs, e, e["event"])
            case = {"id": cid, "gate": e["gate"], "event": e["event"], "kind": e["kind"],
                    "hist": e["hist"], "hist_code": e.get("code") or "", "sub": e["sub"],
                    "ts": recs[e["i"]].get("timestamp") or "", "payload": payload, "window": win,
                    "reason": e.get("reason") or "", "prompt": _last_prompt(win)[:2000],
                    "blocked": _last_assistant(win)[-2000:] if e["event"] != "PreToolUse" else ""}
            with gzip.open(cdir / "cases" / f"{cid}.json.gz", "wt", encoding="utf-8") as fh:
                json.dump(case, fh, ensure_ascii=False)
            index.append({k: case[k] for k in ("id", "gate", "event", "kind", "hist", "hist_code", "sub", "ts")})
    index.sort(key=lambda r: (r["gate"], r["id"]))
    with open(cdir / "index.jsonl", "w", encoding="utf-8") as fh:
        for r in index:
            fh.write(json.dumps(r) + "\n")
    meta = {"since": args.since, "until": args.until, "files": len(files), "cases": len(index),
            "denies": sum(1 for r in index if r["kind"] == "deny"), "seed": args.seed,
            "allow_per_gate": args.allow_per_gate, "built": _now(),
            "scan_seconds": round(time.monotonic() - t0, 1)}
    (cdir / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(json.dumps(meta))
    apply_labels(cdir)
    if args.no_baseline:
        return 0
    return write_baseline(cdir, args.jobs)


# ── labels ──────────────────────────────────────────────────────────────────

def _read_case(cdir: Path, cid: str) -> dict:
    with gzip.open(cdir / "cases" / f"{cid}.json.gz", "rt", encoding="utf-8") as fh:
        return json.load(fh)


def _index(cdir: Path) -> list:
    rows = []
    with open(cdir / "index.jsonl", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def label_of(case: dict, rules: list) -> str:
    fields = {"input": json.dumps((case.get("payload") or {}).get("tool_input"), ensure_ascii=False),
              "prompt": case.get("prompt") or "", "reason": case.get("reason") or "",
              "blocked": case.get("blocked") or ""}
    for r in rules:
        if r.get("gate") and r["gate"] != case["gate"]:
            continue
        if r.get("code") and r["code"] != case.get("hist_code"):
            continue
        if r.get("hist") and r["hist"] != case.get("hist"):
            continue
        if "sub" in r and bool(r["sub"]) != bool(case.get("sub")):
            continue
        if re.search(r["pattern"], fields.get(r.get("field", "input"), ""), re.S | re.I):
            return r["label"]
    return ""


def apply_labels(cdir: Path) -> dict:
    """Write labels.json (case id -> TP|FP) from the private rules. Returns counts."""
    rf = cdir / "label-rules.json"
    try:
        rules = json.loads(rf.read_text(encoding="utf-8")).get("rules", [])
    except (OSError, ValueError):
        rules = []
    labels = {}
    for r in _index(cdir):
        lab = label_of(_read_case(cdir, r["id"]), rules) if rules else ""
        if lab:
            labels[r["id"]] = lab
    (cdir / "labels.json").write_text(json.dumps(labels, indent=0, sort_keys=True), encoding="utf-8")
    counts = {"TP": sum(1 for v in labels.values() if v == "TP"),
              "FP": sum(1 for v in labels.values() if v == "FP")}
    print(json.dumps({"labels": counts, "rules": len(rules)}))
    return counts


def _labels(cdir: Path) -> dict:
    try:
        return json.loads((cdir / "labels.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# ── replay ──────────────────────────────────────────────────────────────────

def decide(rc: int, out: str, err: str) -> tuple[str, str]:
    """(decision, reason text) the way the harness reads a hook's answer."""
    if rc == 2:
        return "deny", err or out
    if rc not in (0, None):
        return "error", err[-300:]
    s = (out or "").strip()
    if s.startswith("{"):
        try:
            o = json.loads(s)
        except ValueError:
            o = {}
        if isinstance(o, dict):
            hso = o.get("hookSpecificOutput") or {}
            if isinstance(hso, dict) and hso.get("permissionDecision") in ("deny", "ask"):
                return hso["permissionDecision"], str(hso.get("permissionDecisionReason") or "")
            if o.get("decision") == "block":
                return "deny", str(o.get("reason") or "")
    return "allow", ""


def run_case(cdir: Path, cid: str) -> dict:
    case = _read_case(cdir, cid)
    script = gate_path(case["gate"])
    if not script.exists():
        return {"id": cid, "d": "missing", "c": "", "ms": 0}
    sandbox = Path(tempfile.mkdtemp(prefix="friction-replay-"))
    try:
        claude = sandbox / ".claude"
        rec = claude / ".cache" / "receipts"
        rec.mkdir(parents=True)
        (rec / "global.jsonl").write_text(json.dumps(
            {"kind": "gate-liveness", "ok": True, "head": "SELFTEST", "gates": "SELFTEST",
             "ts": "2026-01-01T00:00:00+00:00"}) + "\n", encoding="utf-8")
        tdir = claude / "projects" / "replay"
        tdir.mkdir(parents=True)
        payload = dict(case["payload"])
        sid = payload.get("session_id") or "replay"
        tp = tdir / f"{sid}.jsonl"
        with open(tp, "w", encoding="utf-8") as fh:
            for r in case["window"]:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        payload["transcript_path"] = str(tp)
        env = dict(os.environ)
        for k in gate_selftest._OVERRIDE_ENV:
            env.pop(k, None)
        for k in list(env):
            if k.startswith("GIT_") or k in ("OCTO_FRICTION_DIR",):
                env.pop(k, None)
        env.update(HOME=str(sandbox), USERPROFILE=str(sandbox), CLAUDE_SESSION_ID=SELFTEST_SESSION)
        t0 = time.monotonic()
        try:
            cp = subprocess.run([sys.executable, str(script)], input=json.dumps(payload),
                                capture_output=True, text=True, encoding="utf-8", errors="replace",
                                cwd=str(sandbox), env=env, timeout=CASE_TIMEOUT)
            d, why = decide(cp.returncode, cp.stdout, cp.stderr)
        except subprocess.TimeoutExpired:
            d, why = "timeout", ""
        ms = int((time.monotonic() - t0) * 1000)
        code = ""
        if d in BLOCKING:
            g, code = friction_ledger.classify(why, payload.get("tool_name"))
            if g != case["gate"]:
                code = "block"
        return {"id": cid, "d": d, "c": code, "ms": ms}
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


def replay_all(cdir: Path, jobs: int, gate: str = "") -> dict:
    rows = [r for r in _index(cdir) if not gate or r["gate"] == gate]
    out = {}
    with cf.ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        for res in ex.map(lambda r: run_case(cdir, r["id"]), rows):
            out[res["id"]] = res
    return out


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_baseline(cdir: Path, jobs: int) -> int:
    rows = _index(cdir)
    labels = _labels(cdir)
    t0 = time.monotonic()
    res = replay_all(cdir, jobs)
    secs = round(time.monotonic() - t0, 1)
    cases, gates = {}, {}
    for r in rows:
        x = res.get(r["id"]) or {"d": "missing", "c": ""}
        lab = labels.get(r["id"], "-")
        cases[r["id"]] = {"g": r["gate"], "e": r["event"], "h": r["hist"], "d": x["d"], "c": x["c"], "l": lab}
        g = gates.setdefault(r["gate"], {"cases": 0, "historical_deny": 0, "replay_deny": 0,
                                         "agree": 0, "TP": 0, "FP": 0, "TP_FP_of_denies": [0, 0]})
        g["cases"] += 1
        hd = r["hist"] == "deny"
        rd = x["d"] in BLOCKING
        g["historical_deny"] += hd
        g["replay_deny"] += rd
        g["agree"] += (hd == rd)
        if lab in ("TP", "FP"):
            g[lab] += 1
            if hd:
                g["TP_FP_of_denies"][0 if lab == "TP" else 1] += 1
    meta = {}
    try:
        meta = json.loads((cdir / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    doc = {
        "_comment": "v10 Replay_Harness baseline. Counts and per-case ids only: the corpus it was "
                    "replayed from is private (company/friction-corpus/). Case fields: g gate, e event, "
                    "h historical decision, d replayed decision, c reason code, l label (TP, FP, - unlabelled). "
                    "Regenerate with `python3 scripts/replay_harness.py baseline` after an intended change.",
        "version": 1,
        "generated": _now(),
        "window": {"since": meta.get("since"), "until": meta.get("until")},
        "corpus_cases": len(rows),
        "replay_seconds": secs,
        "gates": dict(sorted(gates.items())),
        "cases": dict(sorted(cases.items())),
    }
    BASELINE.write_text(json.dumps(doc, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    agree = sum(g["agree"] for g in gates.values())
    print(json.dumps({"baseline": str(BASELINE.relative_to(REPO)), "cases": len(rows),
                      "agree_with_history": agree, "replay_seconds": secs}))
    return 0


def load_baseline(path: Path = BASELINE) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def compare(base: dict, res: dict) -> dict:
    """allow->deny, deny->allow and lost TPs, per case, against the baseline."""
    a2d, d2a, lost, code_moves = [], [], [], []
    for cid, now in res.items():
        b = (base.get("cases") or {}).get(cid)
        if not b:
            continue
        was, isn = b["d"] in BLOCKING, now["d"] in BLOCKING
        row = {"id": cid, "gate": b["g"], "label": b["l"], "was": b["d"], "now": now["d"],
               "code_was": b["c"], "code_now": now["c"]}
        if was and not isn:
            d2a.append(row)
            if b["l"] == "TP":
                lost.append(row)
        elif isn and not was:
            a2d.append(row)
        elif was and isn and b["c"] != now["c"]:
            code_moves.append(row)
    return {"allow_to_deny": a2d, "deny_to_allow": d2a, "lost_tp": lost, "code_moves": code_moves}


def cmd_replay(args) -> int:
    cdir = corpus_dir(args.corpus)
    if not (cdir / "index.jsonl").exists():
        print(f"SKIP: private replay corpus not found at {cdir} (it is gitignored and built "
              f"per machine with `replay_harness.py build`); nothing to compare.")
        return 0
    base = load_baseline(Path(args.baseline) if args.baseline else BASELINE)
    if not base.get("cases"):
        print("SKIP: no baseline at registry/friction-baseline.json; run `replay_harness.py baseline`.")
        return 0
    t0 = time.monotonic()
    res = replay_all(cdir, args.jobs, args.gate)
    secs = round(time.monotonic() - t0, 1)
    missing = sorted(set(base["cases"]) - set(res)) if not args.gate else []
    diff = compare(base, res)
    if args.json:
        print(json.dumps({"cases": len(res), "seconds": secs, **diff,
                          "not_in_corpus": len(missing)}, indent=1))
    else:
        per = {}
        for cid, now in res.items():
            b = base["cases"].get(cid)
            if not b:
                continue
            p = per.setdefault(b["g"], [0, 0, 0])
            p[0] += 1
            p[1] += b["d"] in BLOCKING
            p[2] += now["d"] in BLOCKING
        print(f"replayed {len(res)} cases in {secs}s against the baseline of {base.get('generated')}")
        print(f"{'gate':44s} {'cases':>6s} {'deny before':>12s} {'deny now':>9s}")
        for g, (n, b, a) in sorted(per.items()):
            print(f"{g:44s} {n:6d} {b:12d} {a:9d}")
        for name in ("allow_to_deny", "deny_to_allow", "code_moves"):
            rows = diff[name]
            print(f"{name.replace('_', ' ')}: {len(rows)}")
            for r in rows[:40]:
                print(f"  {r['id']} {r['gate']} label={r['label']} {r['was']}({r['code_was']}) -> "
                      f"{r['now']}({r['code_now']})")
        if missing:
            print(f"baseline cases absent from this corpus: {len(missing)} (corpus rebuilt or pruned)")
    if diff["lost_tp"]:
        print(f"FAIL: {len(diff['lost_tp'])} labelled true positive(s) no longer blocked: "
              + ", ".join(f"{r['gate']}:{r['id']}" for r in diff["lost_tp"][:10]), file=sys.stderr)
        return 1
    return 0


def cmd_baseline(args) -> int:
    cdir = corpus_dir(args.corpus)
    if not (cdir / "index.jsonl").exists():
        print(f"SKIP: private replay corpus not found at {cdir}.")
        return 0
    return write_baseline(cdir, args.jobs)


def cmd_label(args) -> int:
    cdir = corpus_dir(args.corpus)
    if not (cdir / "index.jsonl").exists():
        print(f"SKIP: private replay corpus not found at {cdir}.")
        return 0
    apply_labels(cdir)
    base = load_baseline()
    if base.get("cases"):
        labels = _labels(cdir)
        for cid, c in base["cases"].items():
            c["l"] = labels.get(cid, "-")
        for g in base.get("gates", {}).values():
            g.update(TP=0, FP=0, TP_FP_of_denies=[0, 0])
        for cid, c in base["cases"].items():
            if c["l"] in ("TP", "FP"):
                g = base["gates"][c["g"]]
                g[c["l"]] += 1
                if c["h"] == "deny":
                    g["TP_FP_of_denies"][0 if c["l"] == "TP" else 1] += 1
        BASELINE.write_text(json.dumps(base, indent=1) + "\n", encoding="utf-8")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="replay_harness", description=__doc__.split("\n")[0])
    ap.add_argument("--corpus", default="", help="corpus dir (default company/friction-corpus)")
    ap.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 2))
    sub = ap.add_subparsers(dest="cmd")
    b = sub.add_parser("build", help="freeze a corpus from the transcripts, label it, write the baseline")
    b.add_argument("--since", default="2026-09-06")
    b.add_argument("--until", default="2026-10-07", help="exclusive, YYYY-MM-DD")
    b.add_argument("--root", default="", help="projects dir (default ~/.claude/projects)")
    b.add_argument("--allow-per-gate", type=int, default=40)
    b.add_argument("--seed", type=int, default=7)
    b.add_argument("--fresh", action="store_true", help="delete the corpus dir first")
    b.add_argument("--no-baseline", action="store_true")
    r = sub.add_parser("replay", help="replay against the baseline; exit 1 on a lost TP")
    r.add_argument("--gate", default="", help="only this gate script")
    r.add_argument("--baseline", default="")
    r.add_argument("--json", action="store_true")
    sub.add_parser("baseline", help="replay and rewrite registry/friction-baseline.json")
    sub.add_parser("label", help="re-apply the private label rules")
    a = ap.parse_args(argv)
    if a.cmd == "build":
        return build(a)
    if a.cmd == "replay":
        return cmd_replay(a)
    if a.cmd == "baseline":
        return cmd_baseline(a)
    if a.cmd == "label":
        return cmd_label(a)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
