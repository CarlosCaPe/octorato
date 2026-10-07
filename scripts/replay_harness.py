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

ISOLATION. Every case runs under a fresh temp HOME, with an ALLOWLIST
environment (PATH, LANG, LC_*, PYTHON*, TMPDIR; no token, no OCTO_* override)
and `CLAUDE_SESSION_ID=__selftest__`, the session seam `gate_selftest.py` gives
a fixture leg (and the same seam the
outward-send gate uses to accept a seeded gate receipt, so the receipt check
does not mask the checks behind it). What the replay therefore CANNOT see, and
what makes a replayed decision differ from the historical one: receipts and
ledgers that lived in the real HOME (panel, QA, delegation ledger, kernel
process table, block-once sentinels), the operator's private config under
`company/config/`, the live state of the cwd the call ran in, and anything the
window cut. The baseline records both decisions, so the agreement rate per gate
is printed rather than assumed.

STATEFUL STOP GATES. A gate that keeps per-session state on disk across turns
(goal-anchor pins a root goal under ~/.claude/.cache/goal-anchor/) cannot be
replayed one case at a time: its block on turn N depends on what it saw on
turns 1..N-1. For those gates (STATEFUL_STOP_GATES) the corpus also holds, per
session that carries one of their cases, the session transcript (records the
gates read, slimmed like a window) and the list of its Stops: where each one
cut the transcript, whether it ran with stop_hook_active (the Stop before it
was blocked by any Stop hook and no operator prompt came between), which gates
blocked it historically, and which corpus case it is. The stateful replay runs
EVERY Stop of the session in order through ONE sandbox HOME, appending the
transcript up to each cut before calling the gate, so the gate's own state
carries across turns exactly as it did live. A case of a stateful Stop gate whose
session was not captured falls back to the isolated replay and is counted.
Residual, measured on goal-anchor: even replayed in order with the gate that
produced history, most historical blocks do not reproduce, and the replay
blocks on Stops history let through. The recorded transcript is not what the
live gate read at its Stop: there are live blocks on a turn whose recorded
final reply carries no closure claim, right after allows on turns whose final
replies do, which fits a hook reading the file before the turn's last records
were written. That write timing is in no record, so it cannot be rebuilt, and
the gate stays LOW-FIDELITY until a Stop payload carries what the gate read.

FIDELITY REVISION. History was produced by the gate as it was deployed then,
not by this checkout. `baseline --fidelity-rev GATE=REV` replays that gate's
cases a second time with `scripts/` taken from git at REV and stores that
decision per case (`p`); deny/allow fidelity is then measured from `p` against
history, and `before_after` reports blocks at REV against blocks now on the
same cases. Without `p` fidelity is measured from `d`, as before.

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
# Stop gates whose decision depends on state THEY wrote on earlier turns of the
# same session. Not here, because their missing state is not their own:
# d__stop__wa-guardia.py reads the live messaging-bridge store and the process
# table, g__stop__delegation-audit.py reads a ledger a PostToolUse reflex
# writes. Replaying the Stops in order gives neither of them that input.
STATEFUL_STOP_GATES = ("g__stop__goal-anchor.py",)
# Transcript record types a Stop gate reads. The rest is harness bookkeeping
# (queue operations, titles, mode latches, file-history snapshots) and is
# dropped from a captured session to keep it small.
SESSION_TYPES = {"user", "assistant", "system", "attachment"}


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
    capture_sessions(cdir, root, args.since, args.until)
    apply_labels(cdir)
    if args.no_baseline:
        return 0
    return write_baseline(cdir, args.jobs, _parse_revs(getattr(args, "fidelity_rev", None)))


# ── build: sessions of stateful Stop gates ──────────────────────────────────

def stop_points(recs: list) -> list:
    """Every main-loop Stop of one transcript, in order.

    A Stop is identified by where it cut the transcript (`end`: just after the
    last assistant record before it, the same cut `_payload` uses) and carries
    the keys the corpus derives case ids from: the uuid of each blocking-error
    attachment (with the gate it names) and the uuid of its stop_hook_summary.
    `active` is the stop_hook_active the harness passed: the Stop before was
    blocked by any Stop hook and no operator prompt came between.
    """
    by_end, order = {}, []

    def at(i: int) -> dict:
        end = i
        while end > 0 and recs[end - 1].get("type") != "assistant":
            end -= 1
        if end not in by_end:
            by_end[end] = {"end": end, "ts": "", "sid": "", "cwd": "", "blocks": [], "summary": None}
            order.append(end)
        return by_end[end]

    for i, d in enumerate(recs):
        a = d.get("attachment") or {}
        if a.get("type") == "hook_blocking_error" and (a.get("hookEvent") or "Stop") == "Stop":
            be = a.get("blockingError") or {}
            gate, _ = friction_ledger.attribute_block(be.get("command") or "", be.get("blockingError") or "")
            s = at(i)
            s["blocks"].append([gate, d.get("uuid")])
            s["ts"] = s["ts"] or d.get("timestamp") or ""
            s["sid"] = s["sid"] or d.get("sessionId") or ""
            s["cwd"] = s["cwd"] or d.get("cwd") or ""
        elif d.get("subtype") == "stop_hook_summary":
            s = at(i)
            s["summary"] = {"key": d.get("uuid"),
                            "clean": not d.get("preventedContinuation") and not d.get("hookErrors")}
            s["ts"] = d.get("timestamp") or s["ts"]
            s["sid"] = d.get("sessionId") or s["sid"]
            s["cwd"] = d.get("cwd") or s["cwd"]
    order.sort()
    out, prev = [], None
    for end in order:
        s = by_end[end]
        prompt_between = prev is not None and any(_is_prompt(r) for r in recs[prev["end"]:end])
        s["active"] = bool(prev and prev["blocks"] and not prompt_between)
        out.append(s)
        prev = s
    return out


def _load_sized(path: str) -> tuple[list, list]:
    """Like _load, plus each parsed line's byte length (newline included)."""
    recs, sizes = [], []
    try:
        with open(path, "rb") as fh:
            for raw in fh:
                try:
                    recs.append(json.loads(raw.decode("utf-8", errors="replace")))
                except ValueError:
                    continue
                sizes.append(len(raw))
    except OSError:
        pass
    return recs, sizes


def _session_file(root: Path, sid: str) -> str:
    hits = sorted(glob.glob(str(root / "*" / f"{glob.escape(sid)}.jsonl")))
    return hits[0] if hits else ""


def capture_sessions(cdir: Path, root: Path, since: str, until: str,
                     gates: tuple = STATEFUL_STOP_GATES) -> dict:
    """Freeze, under cdir/sessions/, the transcript and the Stops of every
    session that holds a case of a stateful Stop gate. Private like the cases.
    Returns {"sessions": n, "cases_mapped": n, "cases_unmapped": n}."""
    rows = [r for r in _index(cdir) if r["gate"] in gates and r["event"] == "Stop"] \
        if (cdir / "index.jsonl").exists() else []
    want = {r["id"] for r in rows}
    sids = {}
    for r in rows:
        sid = (_read_case(cdir, r["id"]).get("payload") or {}).get("session_id") or ""
        if sid:
            sids.setdefault(sid, set()).add(r["id"])
    sdir = cdir / "sessions"
    shutil.rmtree(sdir, ignore_errors=True)
    mapped = set()
    n = 0
    for sid in sorted(sids):
        path = _session_file(root, sid)
        if not path:
            continue
        recs, sizes = _load_sized(path)
        stops = []
        for s in stop_points(recs):
            if s["sid"] and s["sid"] != sid:
                continue
            cases = {}
            for g in gates:
                for bg, key in s["blocks"]:
                    if bg == g and _case_id(g, key) in want:
                        cases[g] = _case_id(g, key)
                if s["summary"] and _case_id(g, s["summary"]["key"]) in want:
                    cases[g] = _case_id(g, s["summary"]["key"])
            mapped.update(cases.values())
            stops.append({"end": s["end"], "ts": s["ts"], "cwd": s["cwd"], "active": s["active"],
                          "in_window": bool(since <= (s["ts"] or "")[:10] < until),
                          "hist": sorted({g for g, _ in s["blocks"]}), "cases": cases})
        # Every record up to the last Stop: the ones a gate reads slimmed, the
        # harness bookkeeping reduced to its type. `sizes` keeps each line's
        # original byte length so the replay can pad it back: gates read only
        # the last 256 KB of the transcript, and which turns fall inside that
        # tail decides what a gate with no saved state rebuilds.
        last = stops[-1]["end"] if stops else 0
        keep = [_slim(d) if d.get("type") in SESSION_TYPES else {"type": d.get("type")}
                for d in recs[:last]]
        sdir.mkdir(parents=True, exist_ok=True)
        with gzip.open(sdir / f"{_case_id('session', sid)}.json.gz", "wt", encoding="utf-8") as fh:
            json.dump({"sid": sid, "records": keep, "sizes": sizes[:last], "stops": stops}, fh,
                      ensure_ascii=False)
        n += 1
    out = {"sessions": n, "cases_mapped": len(mapped), "cases_unmapped": len(want - mapped)}
    print(json.dumps(out))
    return out


def cmd_sessions(args) -> int:
    cdir = corpus_dir(args.corpus)
    if not (cdir / "index.jsonl").exists():
        print(f"SKIP: private replay corpus not found at {cdir}.")
        return 0
    meta = {}
    try:
        meta = json.loads((cdir / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    root = Path(args.root) if args.root else friction_ledger.projects_dir()
    capture_sessions(cdir, root, meta.get("since") or "", meta.get("until") or "9999")
    return 0


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


_ENV_KEEP = ("PATH", "LANG", "TMPDIR", "SYSTEMROOT", "PATHEXT", "COMSPEC")
_ENV_KEEP_PREFIX = ("LC_", "PYTHON")


def replay_env(sandbox: Path) -> dict:
    """An ALLOWLIST environment for a replayed gate.

    Copying os.environ and stripping a denylist let every credential of the
    shell that ran the harness (a GitHub token, the harness messaging token and
    socket) reach real gate code fed real traffic. Only what a Python gate
    needs to start is kept; HOME and the session id are the sandbox's own. The
    operator overrides (OCTO_*) are therefore gone by construction.
    """
    env = {k: v for k, v in os.environ.items()
           if k in _ENV_KEEP or k.startswith(_ENV_KEEP_PREFIX)}
    env.update(HOME=str(sandbox), USERPROFILE=str(sandbox), CLAUDE_SESSION_ID=SELFTEST_SESSION)
    return env


def _sandbox() -> Path:
    """A fresh HOME holding only the seeded gate receipt."""
    sandbox = Path(tempfile.mkdtemp(prefix="friction-replay-"))
    rec = sandbox / ".claude" / ".cache" / "receipts"
    rec.mkdir(parents=True)
    (rec / "global.jsonl").write_text(json.dumps(
        {"kind": "gate-liveness", "ok": True, "head": "SELFTEST", "gates": "SELFTEST",
         "ts": "2026-01-01T00:00:00+00:00"}) + "\n", encoding="utf-8")
    (sandbox / ".claude" / "projects" / "replay").mkdir(parents=True)
    return sandbox


def _run_gate(script: Path, payload: dict, sandbox: Path, gate: str) -> dict:
    """One hook call, read the way the harness reads it."""
    env = replay_env(sandbox)
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
        if g != gate:
            code = "block"
    return {"d": d, "c": code, "ms": ms}


def run_case(cdir: Path, cid: str, scripts: Path | None = None) -> dict:
    """Isolated replay: one case, one fresh HOME, the case's own window."""
    case = _read_case(cdir, cid)
    script = (scripts or HERE) / case["gate"]
    if not script.exists():
        return {"id": cid, "d": "missing", "c": "", "ms": 0}
    sandbox = _sandbox()
    try:
        payload = dict(case["payload"])
        sid = payload.get("session_id") or "replay"
        tp = sandbox / ".claude" / "projects" / "replay" / f"{sid}.jsonl"
        with open(tp, "w", encoding="utf-8") as fh:
            for r in case["window"]:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        payload["transcript_path"] = str(tp)
        return dict(_run_gate(script, payload, sandbox, case["gate"]), id=cid)
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


def _read_session(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def run_session(sess: dict, gates: tuple, scripts: Path | None = None) -> dict:
    """Stateful replay of one session: every Stop in order through ONE HOME.

    The transcript file grows to each Stop's cut before the gates run, so each
    call sees the transcript as it was at that turn, and whatever a gate saved
    under HOME on an earlier turn is still there. Returns
    {"cases": {case_id: result}, "stops": [{gate: decision}]}.
    """
    sandbox = _sandbox()
    try:
        sid = sess.get("sid") or "replay"
        tp = sandbox / ".claude" / "projects" / "replay" / f"{sid}.jsonl"
        recs = sess.get("records") or []
        sizes = sess.get("sizes") or []
        written = 0
        cases, per_stop = {}, []
        with open(tp, "wb") as fh:
            for s in sess.get("stops") or []:
                end = max(written, int(s.get("end") or 0))
                for i in range(written, min(end, len(recs))):
                    line = json.dumps(recs[i], ensure_ascii=False).encode("utf-8")
                    pad = (sizes[i] if i < len(sizes) else 0) - len(line) - 1
                    fh.write(line + b" " * max(0, pad) + b"\n")
                fh.flush()
                written = end
                row = {}
                for g in gates:
                    script = (scripts or HERE) / g
                    if not script.exists():
                        res = {"d": "missing", "c": "", "ms": 0}
                    else:
                        payload = {"session_id": sid, "hook_event_name": "Stop",
                                   "stop_hook_active": bool(s.get("active")),
                                   "cwd": s.get("cwd") or "", "transcript_path": str(tp)}
                        res = _run_gate(script, payload, sandbox, g)
                    row[g] = res["d"]
                    cid = (s.get("cases") or {}).get(g)
                    if cid:
                        cases[cid] = dict(res, id=cid, m="stateful")
                per_stop.append(row)
        return {"cases": cases, "stops": per_stop}
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


def _stop_key(sess: dict, s: dict) -> str:
    """The uuid of the assistant record a Stop cut after. A forked or resumed
    session file copies its parent's records, uuids included, so the same Stop
    can sit in two captured files; this key counts it once."""
    recs, end = sess.get("records") or [], int(s.get("end") or 0)
    return (recs[end - 1].get("uuid") or "") if 0 < end <= len(recs) else ""


def _sessions(cdir: Path) -> list:
    return sorted((cdir / "sessions").glob("*.json.gz")) if (cdir / "sessions").is_dir() else []


def replay_all(cdir: Path, jobs: int, gate: str = "", scripts: Path | None = None,
               stateful: bool = True, session_stats: dict | None = None) -> dict:
    """Replay every case (or one gate's). Cases of a stateful Stop gate are
    decided by the stateful session replay when their session was captured,
    and by the isolated replay otherwise. `session_stats`, when given, is
    filled per stateful gate with counts over every in-window Stop of the
    captured sessions (historical blocks, replayed blocks, reproduced)."""
    rows = [r for r in _index(cdir) if not gate or r["gate"] == gate]
    out = {}
    sgates = tuple(g for g in STATEFUL_STOP_GATES if not gate or g == gate) if stateful else ()
    if sgates and any(r["gate"] in sgates for r in rows):
        files = _sessions(cdir)

        def one(p):
            sess = _read_session(p)
            return sess, run_session(sess, sgates, scripts)

        seen = set()
        with cf.ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
            for sess, res in ex.map(one, files):
                out.update(res["cases"])
                if session_stats is None:
                    continue
                for g in sgates:
                    st = session_stats.setdefault(g, {"sessions": 0, "stops": 0, "historical_deny": 0,
                                                      "replay_deny": 0, "hist_deny_reproduced": 0})
                    st["sessions"] += 1
                    for s, row in zip(sess.get("stops") or [], res["stops"]):
                        if not s.get("in_window"):
                            continue
                        k = _stop_key(sess, s)
                        if k and (g, k) in seen:
                            continue
                        seen.add((g, k))
                        hd, rd = g in (s.get("hist") or []), row.get(g) in BLOCKING
                        st["stops"] += 1
                        st["historical_deny"] += hd
                        st["replay_deny"] += rd
                        st["hist_deny_reproduced"] += hd and rd
    rest = [r for r in rows if r["id"] not in out]
    fallback = {r["id"] for r in rest if r["gate"] in sgates}
    with cf.ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        for res in ex.map(lambda r: run_case(cdir, r["id"], scripts), rest):
            if res["id"] in fallback:
                res["m"] = "isolated-fallback"
            out[res["id"]] = res
    return out


class scripts_at:
    """`scripts/` as it was at a git revision, extracted to a temp dir.

        with scripts_at("d8a3f51^") as sdir: replay_all(..., scripts=sdir)
    """

    def __init__(self, rev: str):
        self.rev = rev
        self.tmp = None

    def __enter__(self) -> Path:
        self.tmp = Path(tempfile.mkdtemp(prefix="friction-rev-"))
        arc = subprocess.run(["git", "-C", str(REPO), "archive", "--format=tar", self.rev, "scripts"],
                             capture_output=True)
        if arc.returncode != 0:
            shutil.rmtree(self.tmp, ignore_errors=True)
            raise SystemExit(f"git archive {self.rev} failed: {arc.stderr.decode(errors='replace')[:200]}")
        subprocess.run(["tar", "-x", "-C", str(self.tmp)], input=arc.stdout, check=True)
        return self.tmp / "scripts"

    def __exit__(self, *exc):
        shutil.rmtree(self.tmp, ignore_errors=True)
        return False


def _rev_sha(rev: str) -> str:
    cp = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--verify", f"{rev}^{{commit}}"],
                        capture_output=True, text=True)
    return cp.stdout.strip() if cp.returncode == 0 else rev


def _parse_revs(items) -> dict:
    out = {}
    for it in items or []:
        g, _, rev = it.partition("=")
        if g and rev:
            out[g] = rev
    return out


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


LOW_FIDELITY = 0.5


def gate_stats(cases: dict, revs: dict | None = None) -> dict:
    """Per gate, from the baseline cases: how far a replay can be trusted.

    `agree` counts cases whose replayed decision matches history. Fidelity is
    measured on each side separately, because the two failure modes differ: a
    gate whose block depends on real-HOME state replays its historical denies
    as allows (goal-anchor), and a gate whose allow depends on a block-once
    sentinel replays its historical allows as denies (chat-context). Either
    side under 50% marks the gate LOW-FIDELITY, and a before/after claim on it
    is flagged wherever it is printed.

    When a gate's cases carry `p` (the decision of the gate revision that
    produced history, see FIDELITY REVISION), fidelity is measured from `p`,
    because the gate in this checkout may block less on purpose, and
    `before_after` counts blocks at that revision against blocks now.
    """
    out = {}
    with_p = {c["g"] for c in cases.values() if "p" in c}
    for c in cases.values():
        g = out.setdefault(c["g"], {"cases": 0, "historical_deny": 0, "replay_deny": 0, "agree": 0,
                                    "hist_deny_reproduced": 0, "hist_allow_reproduced": 0,
                                    "TP": 0, "FP": 0, "TP_FP_of_denies": [0, 0],
                                    "labelled_denies": 0})
        hd = c["h"] == "deny"
        rd = c["d"] in BLOCKING
        fd = (c.get("p") in BLOCKING) if c["g"] in with_p else rd
        g["cases"] += 1
        g["historical_deny"] += hd
        g["replay_deny"] += rd
        g["agree"] += (hd == rd)
        g["hist_deny_reproduced"] += hd and fd
        g["hist_allow_reproduced"] += (not hd) and (not fd)
        if c["g"] in with_p:
            ba = g.setdefault("before_after", {"rev": (revs or {}).get(c["g"], ""), "before": 0, "after": 0})
            ba["before"] += fd
            ba["after"] += rd
        if c["l"] in ("TP", "FP"):
            g[c["l"]] += 1
            if hd:
                g["TP_FP_of_denies"][0 if c["l"] == "TP" else 1] += 1
                g["labelled_denies"] += 1
    for g in out.values():
        hd, ha = g["historical_deny"], g["cases"] - g["historical_deny"]
        dr = g["hist_deny_reproduced"] / hd if hd else None
        ar = g["hist_allow_reproduced"] / ha if ha else None
        g["deny_fidelity"] = None if dr is None else round(dr, 3)
        g["allow_fidelity"] = None if ar is None else round(ar, 3)
        g["low_fidelity"] = any(x is not None and x < LOW_FIDELITY for x in (dr, ar))
    return dict(sorted(out.items()))


def fidelity_label(g: dict) -> str:
    """'agree a/n, deny r/h' plus the LOW-FIDELITY mark."""
    if not g:
        return "no baseline stats"
    txt = (f"agree {g['agree']}/{g['cases']}, deny {g['replay_deny']}/{g['historical_deny']} "
           f"(historical denies reproduced {g['hist_deny_reproduced']}/{g['historical_deny']})")
    ba = g.get("before_after")
    if ba:
        txt += f", measured at {str(ba.get('rev') or '?')[:7]}"
    return txt + (" LOW-FIDELITY" if g.get("low_fidelity") else "")


def write_baseline(cdir: Path, jobs: int, revs: dict | None = None, gate: str = "") -> int:
    """Replay and write the baseline. `revs` maps a gate to the git revision
    that produced its history (stored as `p` per case). With `gate`, only that
    gate is replayed and merged into the existing baseline."""
    rows = [r for r in _index(cdir) if not gate or r["gate"] == gate]
    labels = _labels(cdir)
    prior = load_baseline() if gate else {}
    revs = dict(prior.get("fidelity_revs") or {}, **(revs or {}))
    t0 = time.monotonic()
    sstats = {}
    res = replay_all(cdir, jobs, gate, session_stats=sstats)
    pres = {}
    for g, rev in sorted(revs.items()):
        if gate and g != gate:
            continue
        sha = _rev_sha(rev)
        revs[g] = sha
        pstats = {}
        with scripts_at(sha) as sdir:
            pres.update(replay_all(cdir, jobs, g, scripts=sdir, session_stats=pstats))
        if g in sstats and g in pstats:
            sstats[g]["rev_replay_deny"] = pstats[g]["replay_deny"]
            sstats[g]["rev_hist_deny_reproduced"] = pstats[g]["hist_deny_reproduced"]
    secs = round(time.monotonic() - t0, 1)
    cases = dict(prior.get("cases") or {})
    for r in rows:
        x = res.get(r["id"]) or {"d": "missing", "c": ""}
        # A one-gate merge keeps the reviewed labels already in the baseline;
        # relabelling is `label`'s job.
        lab = ((prior.get("cases") or {}).get(r["id"]) or {}).get("l") or labels.get(r["id"], "-")
        cases[r["id"]] = {"g": r["gate"], "e": r["event"], "h": r["hist"], "d": x["d"], "c": x["c"],
                          "l": lab}
        if r["gate"] in revs and r["id"] in pres:
            cases[r["id"]]["p"] = pres[r["id"]]["d"]
    gates = gate_stats(cases, revs)
    meta = {}
    try:
        meta = json.loads((cdir / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    stateful = dict(prior.get("stateful_sessions") or {}, **sstats)
    doc = {
        "_comment": "v10 Replay_Harness baseline. Counts and per-case ids only: the corpus it was "
                    "replayed from is private (company/friction-corpus/). Case fields: g gate, e event, "
                    "h historical decision, d replayed decision, c reason code, l label (TP, FP, - unlabelled), "
                    "p decision of the gate revision in fidelity_revs (fidelity is measured from it). "
                    "Stateful Stop gates are replayed session by session (stateful_sessions: counts over "
                    "every in-window Stop of those sessions). "
                    "Regenerate with `python3 scripts/replay_harness.py baseline` after an intended change.",
        "version": 1,
        "generated": _now(),
        "window": {"since": meta.get("since"), "until": meta.get("until")},
        "corpus_cases": len(_index(cdir)),
        "replay_seconds": secs,
        "fidelity_revs": dict(sorted(revs.items())),
        "stateful_sessions": dict(sorted(stateful.items())),
        "gates": gates,
        "cases": dict(sorted(cases.items())),
    }
    BASELINE.write_text(json.dumps(doc, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    agree = sum(g["agree"] for g in gates.values())
    print(json.dumps({"baseline": str(BASELINE.relative_to(REPO)), "cases": len(rows),
                      "agree_with_history": agree, "replay_seconds": secs,
                      "low_fidelity": [k for k, g in gates.items() if g["low_fidelity"]]}))
    return 0


def load_baseline(path: Path = BASELINE) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def compare(base: dict, res: dict) -> dict:
    """allow->deny, deny->allow, lost TPs, lost unlabelled historical denies and
    gates that stopped denying altogether, against the baseline."""
    a2d, d2a, lost, lost_unlab, code_moves = [], [], [], [], []
    now_deny, base_deny = {}, {}
    for cid, now in res.items():
        b = (base.get("cases") or {}).get(cid)
        if not b:
            continue
        was, isn = b["d"] in BLOCKING, now["d"] in BLOCKING
        base_deny[b["g"]] = base_deny.get(b["g"], 0) + was
        now_deny[b["g"]] = now_deny.get(b["g"], 0) + isn
        row = {"id": cid, "gate": b["g"], "label": b["l"], "was": b["d"], "now": now["d"],
               "code_was": b["c"], "code_now": now["c"], "hist": b["h"]}
        if was and not isn:
            d2a.append(row)
            if b["l"] == "TP":
                lost.append(row)
            elif b["l"] == "-" and b["h"] == "deny":
                lost_unlab.append(row)
        elif isn and not was:
            a2d.append(row)
        elif was and isn and b["c"] != now["c"]:
            code_moves.append(row)
    silenced = sorted(g for g, n in base_deny.items() if n and not now_deny.get(g))
    return {"allow_to_deny": a2d, "deny_to_allow": d2a, "lost_tp": lost,
            "lost_unlabelled_deny": lost_unlab, "silenced_gates": silenced, "code_moves": code_moves}


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
    res = replay_all(cdir, args.jobs, args.gate, stateful=not getattr(args, "isolated", False))
    secs = round(time.monotonic() - t0, 1)
    missing = sorted(set(base["cases"]) - set(res)) if not args.gate else []
    diff = compare(base, res)
    stats = gate_stats(base["cases"], base.get("fidelity_revs"))
    methods = {"stateful": 0, "isolated-fallback": 0, "isolated": 0}
    for r in res.values():
        methods[r.get("m") or "isolated"] += 1
    if args.json:
        print(json.dumps({"cases": len(res), "seconds": secs, "methods": methods, **diff,
                          "low_fidelity": [g for g, v in stats.items() if v["low_fidelity"]],
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
        print("method: " + ", ".join(f"{k} {v}" for k, v in methods.items()))
        print(f"{'gate':40s} {'cases':>5s} {'deny before':>11s} {'deny now':>8s}  fidelity vs history")
        for g, (n, b, a) in sorted(per.items()):
            print(f"{g:40s} {n:5d} {b:11d} {a:8d}  {fidelity_label(stats.get(g) or {})}")
        for name in ("allow_to_deny", "deny_to_allow", "code_moves"):
            rows = diff[name]
            print(f"{name.replace('_', ' ')}: {len(rows)}")
            for r in rows[:40]:
                flag = " [LOW-FIDELITY gate: not evidence]" if \
                    (stats.get(r["gate"]) or {}).get("low_fidelity") else ""
                print(f"  {r['id']} {r['gate']} label={r['label']} hist={r['hist']} "
                      f"{r['was']}({r['code_was']}) -> {r['now']}({r['code_now']}){flag}")
        low = sorted({r["gate"] for k in ("allow_to_deny", "deny_to_allow", "code_moves") for r in diff[k]
                      if (stats.get(r["gate"]) or {}).get("low_fidelity")})
        if low:
            print("WARNING: before/after on LOW-FIDELITY gate(s); the replay does not reproduce their "
                  "history, so these counts prove nothing about them: " + ", ".join(low))
        if missing:
            print(f"baseline cases absent from this corpus: {len(missing)} (corpus rebuilt or pruned)")
    rc = 0
    if diff["lost_tp"]:
        print(f"FAIL: {len(diff['lost_tp'])} labelled true positive(s) no longer blocked: "
              + ", ".join(f"{r['gate']}:{r['id']}" for r in diff["lost_tp"][:10]), file=sys.stderr)
        rc = 1
    if diff["silenced_gates"]:
        print("FAIL: gate(s) that denied in the baseline deny nothing now: "
              + ", ".join(diff["silenced_gates"]), file=sys.stderr)
        rc = 1
    if diff["lost_unlabelled_deny"]:
        n = len(diff["lost_unlabelled_deny"])
        if getattr(args, "allow_unlabelled_loss", False):
            print(f"note: {n} unlabelled historical deny(s) now allow, accepted by "
                  "--allow-unlabelled-loss", file=sys.stderr)
        else:
            print(f"FAIL: {n} unlabelled historical deny(s) now allow (label them, or pass "
                  "--allow-unlabelled-loss for an intended loosening): "
                  + ", ".join(f"{r['gate']}:{r['id']}" for r in diff["lost_unlabelled_deny"][:10]),
                  file=sys.stderr)
            rc = 1
    return rc


def cmd_baseline(args) -> int:
    cdir = corpus_dir(args.corpus)
    if not (cdir / "index.jsonl").exists():
        print(f"SKIP: private replay corpus not found at {cdir}.")
        return 0
    return write_baseline(cdir, args.jobs, _parse_revs(args.fidelity_rev), args.gate)


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
        base["gates"] = gate_stats(base["cases"], base.get("fidelity_revs"))
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
    b.add_argument("--fidelity-rev", action="append", default=[], metavar="GATE=REV",
                   help="measure GATE's fidelity with scripts/ at git REV (the version that produced history)")
    r = sub.add_parser("replay", help="replay against the baseline; exit 1 on a lost TP")
    r.add_argument("--gate", default="", help="only this gate script")
    r.add_argument("--baseline", default="")
    r.add_argument("--json", action="store_true")
    r.add_argument("--isolated", action="store_true",
                   help="replay stateful Stop gates case by case too (the pre-session mode)")
    r.add_argument("--allow-unlabelled-loss", action="store_true",
                   help="accept unlabelled historical denies that now allow (an intended loosening)")
    bl = sub.add_parser("baseline", help="replay and rewrite registry/friction-baseline.json")
    bl.add_argument("--gate", default="", help="only this gate, merged into the existing baseline")
    bl.add_argument("--fidelity-rev", action="append", default=[], metavar="GATE=REV",
                    help="measure GATE's fidelity with scripts/ at git REV (the version that produced history)")
    se = sub.add_parser("sessions", help="capture the sessions of stateful Stop gates into the corpus")
    se.add_argument("--root", default="", help="projects dir (default ~/.claude/projects)")
    sub.add_parser("label", help="re-apply the private label rules")
    a = ap.parse_args(argv)
    if a.cmd == "build":
        return build(a)
    if a.cmd == "replay":
        return cmd_replay(a)
    if a.cmd == "baseline":
        return cmd_baseline(a)
    if a.cmd == "sessions":
        return cmd_sessions(a)
    if a.cmd == "label":
        return cmd_label(a)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
