#!/usr/bin/env python3
"""Anchors for the stateful Stop-gate replay (v10 T16, AC-10).

A Stop gate that keeps per-session state under HOME blocks on turn 3 because
of something it saw on turn 1. Pinned here, on a synthetic two-session corpus
and a toy gate: the corpus builder captures each session's transcript and
Stops (with the historical stop_hook_active), the isolated replay misses the
block, the stateful replay reproduces it, and the second session (same gate,
no arming turn) is not contaminated by the first, which proves one sandbox
HOME per session. Also pinned: fidelity is measured from `p` when present.

All transcript content is synthetic. Timing is never asserted.
"""
from __future__ import annotations

import gzip
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import replay_harness as rh  # noqa: E402

TOY = "g__stop__toy-stateful.py"

# Arms on a prompt starting with ARM; blocks a reply carrying "done" once armed.
# The arming flag is GLOBAL under HOME (not keyed by session) on purpose: if two
# sessions shared a sandbox, the second one would block too.
TOY_GATE = r'''
import json, sys
from pathlib import Path
d = json.load(sys.stdin)
if d.get("stop_hook_active"):
    sys.exit(0)
rows = [json.loads(l) for l in open(d["transcript_path"], encoding="utf-8") if l.strip()]
def text(e):
    c = (e.get("message") or {}).get("content")
    return c if isinstance(c, str) else " ".join(x.get("text", "") for x in c or [] if isinstance(x, dict))
users = [text(e) for e in rows if e.get("type") == "user"]
replies = [text(e) for e in rows if e.get("type") == "assistant"]
flag = Path.home() / ".claude" / ".cache" / "toy" / "armed"
if users and users[-1].startswith("ARM"):
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text("1")
if replies and "done" in replies[-1] and flag.exists():
    print(json.dumps({"decision": "block", "reason": "toy: armed two turns ago"}))
'''


def _session(sid: str, prompts: list, replies: list, blocked_turn: int | None) -> list:
    """user, assistant, [blocking attachment], stop summary, per turn."""
    recs, n = [], 0

    def rec(**kw):
        nonlocal n
        n += 1
        kw.setdefault("uuid", f"{sid[:4]}-{n}")
        kw.setdefault("sessionId", sid)
        kw.setdefault("timestamp", f"2026-09-10T10:{n:02d}:00.000Z")
        recs.append(kw)

    for t, (p, r) in enumerate(zip(prompts, replies), start=1):
        rec(type="user", origin={"kind": "human"}, message={"role": "user", "content": p})
        rec(type="assistant", message={"role": "assistant", "content": [{"type": "text", "text": r}]})
        if t == blocked_turn:
            rec(type="attachment", attachment={
                "type": "hook_blocking_error", "hookEvent": "Stop",
                "blockingError": {"command": f"python3 ~/.claude/scripts/{TOY}",
                                  "blockingError": "toy: armed two turns ago"}})
        rec(type="system", subtype="stop_hook_summary", preventedContinuation=False,
            hookErrors=["x"] if t == blocked_turn else [])
    return recs


SID_A = "aaaaaaaa-0000-4000-8000-000000000001"
SID_B = "bbbbbbbb-0000-4000-8000-000000000002"


class TestStatefulReplay(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="replay-stateful-test-"))
        self.scripts = self.tmp / "scripts"
        self.scripts.mkdir()
        (self.scripts / TOY).write_text(TOY_GATE, encoding="utf-8")
        self.root = self.tmp / "projects"
        (self.root / "proj").mkdir(parents=True)
        self.cdir = self.tmp / "corpus"
        (self.cdir / "cases").mkdir(parents=True)
        sessions = {
            # A: armed on turn 1, nothing on turn 2, blocked on turn 3.
            SID_A: _session(SID_A, ["ARM the example", "next step", "wrap it up"],
                            ["ok", "working", "all done"], blocked_turn=3),
            # B: same closing turn, never armed: allowed historically.
            SID_B: _session(SID_B, ["plain example", "next step", "wrap it up"],
                            ["ok", "working", "all done"], blocked_turn=None),
        }
        index = []
        for sid, recs in sessions.items():
            with open(self.root / "proj" / f"{sid}.jsonl", "w", encoding="utf-8") as fh:
                for r in recs:
                    fh.write(json.dumps(r) + "\n")
            last = len(recs) - 1                      # the turn-3 stop summary
            blocked = [i for i, r in enumerate(recs) if r.get("type") == "attachment"]
            i = blocked[0] if blocked else last
            hist = "deny" if blocked else "allow"
            cid = rh._case_id(TOY, recs[i]["uuid"])
            payload, win = rh._payload(recs, {"i": i}, "Stop")
            case = {"id": cid, "gate": TOY, "event": "Stop", "kind": hist, "hist": hist,
                    "hist_code": "", "sub": False, "ts": recs[i]["timestamp"], "payload": payload,
                    "window": win, "reason": "", "prompt": "", "blocked": ""}
            with gzip.open(self.cdir / "cases" / f"{cid}.json.gz", "wt", encoding="utf-8") as fh:
                json.dump(case, fh)
            index.append({k: case[k] for k in ("id", "gate", "event", "kind", "hist", "hist_code", "sub", "ts")})
            setattr(self, "case_" + sid[0], cid)
        with open(self.cdir / "index.jsonl", "w", encoding="utf-8") as fh:
            for r in index:
                fh.write(json.dumps(r) + "\n")
        self.patch = mock.patch.object(rh, "STATEFUL_STOP_GATES", (TOY,))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_stop_points_carry_cut_active_and_history(self):
        recs = rh._load(str(self.root / "proj" / f"{SID_A}.jsonl"))
        stops = rh.stop_points(recs)
        self.assertEqual(len(stops), 3)
        self.assertEqual([s["active"] for s in stops], [False, False, False])
        self.assertEqual(stops[2]["blocks"][0][0], TOY)
        for s in stops:                              # each cut ends on the turn's reply
            self.assertEqual(recs[s["end"] - 1]["type"], "assistant")

    def test_capture_maps_every_case_to_a_stop(self):
        with redirect_stdout(io.StringIO()):
            out = rh.capture_sessions(self.cdir, self.root, "2026-09-01", "2026-10-01", gates=(TOY,))
        self.assertEqual(out, {"sessions": 2, "cases_mapped": 2, "cases_unmapped": 0})

    def test_isolated_misses_and_stateful_catches_the_block(self):
        with redirect_stdout(io.StringIO()):
            rh.capture_sessions(self.cdir, self.root, "2026-09-01", "2026-10-01", gates=(TOY,))
        iso = rh.replay_all(self.cdir, 2, scripts=self.scripts, stateful=False)
        self.assertEqual(iso[self.case_a]["d"], "allow")           # turn-1 state is gone
        stats = {}
        st = rh.replay_all(self.cdir, 2, scripts=self.scripts, session_stats=stats)
        self.assertEqual(st[self.case_a]["d"], "deny")
        self.assertEqual(st[self.case_a]["m"], "stateful")
        self.assertEqual(st[self.case_b]["d"], "allow")            # one HOME per session
        self.assertEqual(stats[TOY], {"sessions": 2, "stops": 6, "historical_deny": 1,
                                      "replay_deny": 1, "hist_deny_reproduced": 1})

    def test_uncaptured_session_falls_back_to_isolated(self):
        st = rh.replay_all(self.cdir, 2, scripts=self.scripts)    # no sessions/ captured
        self.assertEqual(st[self.case_a]["m"], "isolated-fallback")
        self.assertEqual(st[self.case_a]["d"], "allow")

    def test_fidelity_is_measured_from_the_history_revision(self):
        cases = {"x1": {"g": TOY, "e": "Stop", "h": "deny", "d": "allow", "p": "deny", "c": "", "l": "FP"},
                 "x2": {"g": TOY, "e": "Stop", "h": "allow", "d": "allow", "p": "allow", "c": "", "l": "-"}}
        g = rh.gate_stats(cases, {TOY: "abc1234"})[TOY]
        self.assertEqual(g["deny_fidelity"], 1.0)
        self.assertFalse(g["low_fidelity"])
        self.assertEqual(g["before_after"], {"rev": "abc1234", "before": 1, "after": 0})
        del cases["x1"]["p"], cases["x2"]["p"]
        self.assertTrue(rh.gate_stats(cases)[TOY]["low_fidelity"])


if __name__ == "__main__":
    unittest.main()
