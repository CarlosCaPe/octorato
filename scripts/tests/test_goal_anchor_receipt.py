#!/usr/bin/env python3
"""Anchors for the goal-anchor read receipt (v10 T19, AC-10).

The live goal-anchor gate can read the transcript before a turn's last records
land, so a replay that cuts every Stop at the end of the recorded turn judges a
reply the live gate never saw. T19 makes the gate write, at every Stop, a
receipt of what it read, and teaches the stateful replay to cut there. Pinned:

  * a synthetic session whose live read stopped one record early: the receipt
    cut differs from the end cut, the replay from the receipt reproduces the
    recorded block, the end cut does not;
  * the receipt holds ids, sizes, digests and codes, never text;
  * a receipt that cannot be written changes nothing about the decision;
  * `_pass_code` names `fire` exactly when `_should_fire` is True;
  * the friction ledger carries the receipt's last uuid on the block line.

All transcript content is synthetic. Timing is never asserted.
"""
from __future__ import annotations

import gzip
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from io import StringIO
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent
REPO = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

import friction_ledger  # noqa: E402
import replay_harness as rh  # noqa: E402

GATE = SCRIPTS / "g__stop__goal-anchor.py"
GATE_NAME = GATE.name
FIXTURES = REPO / "registry" / "fixtures" / "FLOW.root-goal-anchor"
SID = "cccccccc-0000-4000-8000-000000000003"

ROOT = "objetivo: migrar el esquema de facturacion al ledger nuevo"
OBSTACLES = ["no me deja entrar al servidor", "sigue fallando el acceso",
             "otra vez sale AccessDenied", "no conecta la consola",
             "sigue sin abrir el panel"]
# Words that appear in the prompts and replies above and below; none may reach a receipt.
SECRET_WORDS = ["facturacion", "ledger", "servidor", "AccessDenied", "consola", "Reviso", "resuelto",
                "Pregunta"]


def _load_gate():
    spec = importlib.util.spec_from_file_location("goal_anchor_under_test", GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _now_ts() -> str:
    t = time.time()
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + f".{int(t * 1000) % 1000:03d}Z"


def _run_gate(payload: dict, home: Path, extra_env: dict | None = None) -> tuple[int, str]:
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG") or k.startswith(("LC_", "PYTHON"))}
    env.update(HOME=str(home), USERPROFILE=str(home), **(extra_env or {}))
    cp = subprocess.run([sys.executable, str(GATE)], input=json.dumps(payload), capture_output=True,
                        text=True, env=env, timeout=60)
    return cp.returncode, cp.stdout


class LiveSession:
    """Writes a session the way the harness does and runs the real gate at each
    Stop, against what was on disk at that moment. On the last turn the gate
    reads BEFORE the turn's final assistant record lands."""

    def __init__(self, tmp: Path):
        self.home = tmp / "livehome"
        self.home.mkdir()
        (tmp / "projects" / "proj").mkdir(parents=True)
        self.path = tmp / "projects" / "proj" / f"{SID}.jsonl"
        self.path.write_text("", encoding="utf-8")
        self.recs: list = []
        self.n = 0
        self.decisions: list = []

    def rec(self, **kw) -> dict:
        self.n += 1
        kw.setdefault("uuid", f"live-{self.n:03d}")
        kw.setdefault("sessionId", SID)
        kw.setdefault("timestamp", _now_ts())
        self.recs.append(kw)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(kw) + "\n")
        return kw

    def stop(self) -> bool:
        time.sleep(0.005)  # receipts and records are ordered by millisecond timestamps
        rc, out = _run_gate({"session_id": SID, "transcript_path": str(self.path),
                             "stop_hook_active": False, "cwd": "/tmp"}, self.home)
        blocked = '"block"' in out
        time.sleep(0.005)
        return blocked

    def turn(self, prompt: str, replies: list, late: list | None = None) -> None:
        self.rec(type="user", origin={"kind": "human"}, message={"role": "user", "content": prompt})
        for r in replies:
            self.rec(type="assistant", message={"role": "assistant", "content": [{"type": "text", "text": r}]})
        blocked = self.stop()
        for r in late or []:  # records the harness wrote after the hook had read
            self.rec(type="assistant", message={"role": "assistant", "content": [{"type": "text", "text": r}]})
        if blocked:
            self.rec(type="attachment", attachment={
                "type": "hook_blocking_error", "hookEvent": "Stop",
                "blockingError": {"command": f"python3 ~/.claude/scripts/{GATE_NAME}",
                                  "blockingError": "ANCLA: declaraste cierre sin nombrar el objetivo raiz"}})
        self.rec(type="system", subtype="stop_hook_summary", preventedContinuation=False,
                 hookErrors=["x"] if blocked else [])
        self.decisions.append(blocked)


def _build_live(tmp: Path) -> LiveSession:
    live = LiveSession(tmp)
    live.turn(ROOT, ["Empiezo por el inventario del esquema de facturacion y el ledger."])
    for p in OBSTACLES:
        live.turn(p, ["Reviso el acceso."])
    # The live read lands between the closure claim and a trailing question.
    live.turn("sigue fallando el acceso al panel", ["Listo, quedo resuelto."],
              late=["Pregunta: algo mas en el panel?"])
    return live


class TestGoalAnchorReceipt(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="goal-anchor-receipt-test-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _receipts(self, home: Path) -> list:
        return friction_ledger.read_receipts(SID, home / ".claude" / ".cache" / "goal-anchor" / "receipts")

    def _corpus(self, live: LiveSession) -> Path:
        """A one-case corpus whose case is the recorded goal-anchor block."""
        cdir = self.tmp / "corpus"
        (cdir / "cases").mkdir(parents=True)
        att = [r for r in live.recs if r.get("type") == "attachment"]
        self.assertEqual(len(att), 1, "the live gate blocked exactly once")
        cid = rh._case_id(GATE_NAME, att[0]["uuid"])
        case = {"id": cid, "gate": GATE_NAME, "event": "Stop", "kind": "deny", "hist": "deny",
                "hist_code": "", "sub": False, "ts": att[0]["timestamp"],
                "payload": {"session_id": SID}, "window": [], "reason": "", "prompt": "", "blocked": ""}
        with gzip.open(cdir / "cases" / f"{cid}.json.gz", "wt", encoding="utf-8") as fh:
            json.dump(case, fh)
        (cdir / "index.jsonl").write_text(json.dumps(
            {k: case[k] for k in ("id", "gate", "event", "kind", "hist", "hist_code", "sub", "ts")}) + "\n",
            encoding="utf-8")
        self.cid = cid
        return cdir

    def test_receipt_cut_reproduces_the_recorded_block_and_the_end_cut_does_not(self):
        live = _build_live(self.tmp)
        self.assertEqual(live.decisions, [False] * 6 + [True])
        receipts = self._receipts(live.home)
        self.assertEqual(len(receipts), 7)
        self.assertEqual(receipts[-1]["decision"], "block")
        self.assertEqual(receipts[-1]["code"], "fire")

        cdir = self._corpus(live)
        with mock.patch.object(rh, "STATEFUL_STOP_GATES", (GATE_NAME,)), redirect_stdout(StringIO()):
            out = rh.capture_sessions(cdir, self.tmp / "projects", "2000-01-01", "9999",
                                      receipts_root=live.home / ".claude" / ".cache" / "goal-anchor" / "receipts")
        self.assertEqual(out["stops_with_receipt"], 7)
        sess = rh._read_session(next((cdir / "sessions").glob("*.json.gz")))
        last = sess["stops"][-1]
        self.assertEqual(last["rcpt"]["by"], "receipt-uuid")
        self.assertLess(last["rcpt"]["end"], last["end"], "the live read stopped before the end cut")

        with_rc = rh.run_session(sess, (GATE_NAME,), use_receipts=True)
        naive = rh.run_session(sess, (GATE_NAME,), use_receipts=False)
        self.assertEqual(with_rc["methods"], ["receipt-uuid"] * 7)
        self.assertEqual(naive["methods"], ["end-cut"] * 7)
        self.assertEqual(with_rc["cases"][self.cid]["d"], "deny")
        self.assertEqual(with_rc["cases"][self.cid]["m"], "stateful-receipt")
        self.assertEqual(naive["cases"][self.cid]["d"], "allow")
        self.assertEqual([r[GATE_NAME] == "deny" for r in with_rc["stops"]], live.decisions)

        # the replay line counts receipt Stops against the fallback
        st = {}
        with mock.patch.object(rh, "STATEFUL_STOP_GATES", (GATE_NAME,)):
            rh.replay_all(cdir, 1, GATE_NAME, session_stats=st)
        g = st[GATE_NAME]
        self.assertEqual((g["from_receipt"], g["end_cut"], g["receipt_decision_reproduced"]), (7, 0, 7))
        self.assertIn("7 cut from a read receipt, 0 by the fallback end cut", rh.receipt_line(GATE_NAME, g))
        st = {}
        with mock.patch.object(rh, "STATEFUL_STOP_GATES", (GATE_NAME,)):
            rh.replay_all(cdir, 1, GATE_NAME, session_stats=st, use_receipts=False)
        self.assertEqual((st[GATE_NAME]["from_receipt"], st[GATE_NAME]["end_cut"]), (0, 7))

    def test_ledger_block_line_carries_the_last_uuid_the_gate_read(self):
        live = _build_live(self.tmp)
        closure = [r for r in live.recs if r.get("type") == "assistant"][-2]  # the claim, before the late record
        with mock.patch.dict(os.environ, {"HOME": str(live.home),
                                          "OCTO_FRICTION_DIR": str(self.tmp / "friction")}):
            friction_ledger.ingest_paths([str(live.path)], with_latency=False)
            rows = friction_ledger.read_ledger()
        blocks = [r for r in rows if r["gate"] == GATE_NAME]
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["seen_uuid"], closure["uuid"])
        self.assertIsInstance(blocks[0]["seen_bytes"], int)

    def test_receipt_holds_no_text(self):
        live = _build_live(self.tmp)
        raw = (live.home / ".claude" / ".cache" / "goal-anchor" / "receipts" / f"{SID}.jsonl").read_text(
            encoding="utf-8")
        for w in SECRET_WORDS + ROOT.split() + ["Listo", "quedo"]:
            if len(w) >= 4:
                self.assertNotIn(w.lower(), raw.lower(), f"receipt leaked {w!r}")
        allowed = {"v", "ts", "session", "bytes", "tail_lines", "last_uuid", "reply_sha256", "reply_digest",
                   "anchor_id", "turn", "open_turns", "fires_before", "decision", "code"}
        for line in raw.splitlines():
            rec = json.loads(line)
            self.assertLessEqual(set(rec), allowed)
            for k in ("reply_sha256", "reply_digest"):
                self.assertRegex(rec[k] or "0" * 64, r"^[0-9a-f]{64}$")
            self.assertRegex(rec["anchor_id"] or "0" * 16, r"^[0-9a-f]{16}$")

    def test_a_receipt_that_cannot_be_written_changes_nothing(self):
        for leg in ("violation.json", "benign.json"):
            p = json.loads((FIXTURES / leg).read_text(encoding="utf-8"))
            p["transcript_path"] = str(FIXTURES / p["transcript_path"])
            outs = []
            for mode in ("normal", "broken", "off"):
                home = self.tmp / f"{leg}-{mode}"
                home.mkdir()
                env = {}
                if mode == "broken":  # a FILE where the receipts directory must go
                    d = home / ".claude" / ".cache" / "goal-anchor"
                    d.mkdir(parents=True)
                    (d / "receipts").write_text("not a dir", encoding="utf-8")
                if mode == "off":
                    env = {"OCTO_GOAL_ANCHOR_RECEIPTS": "0"}
                outs.append(_run_gate(p, home, env))
                rdir = home / ".claude" / ".cache" / "goal-anchor" / "receipts"
                if mode != "normal":
                    self.assertFalse(rdir.is_dir() and any(rdir.iterdir()), f"{mode}: no receipt expected")
            self.assertEqual(outs[0], outs[1], f"{leg}: write failure changed the decision")
            self.assertEqual(outs[0], outs[2], f"{leg}: disabling receipts changed the decision")
            self.assertEqual(bool(outs[0][1].strip()), leg.startswith("violation"))

    def test_pass_code_names_fire_exactly_when_should_fire(self):
        ga = _load_gate()
        checked = 0
        for tf in sorted(FIXTURES.glob("*_transcript.jsonl")) + [FIXTURES / "violation_transcript.jsonl"]:
            pairs = ga._turn_pairs(tf.read_text(encoding="utf-8").splitlines())
            state = {"history": []}
            for prompt, reply, real in pairs:
                re_ = ga._absorb(state, prompt, reply, real)
                for active in (False, True):
                    self.assertEqual(ga._pass_code(state, reply, re_, active) == "fire",
                                     ga._should_fire(state, reply, re_, active), f"{tf.name}")
                    checked += 1
        self.assertGreater(checked, 20)

    def test_receipt_cut_falls_back_to_bytes_then_to_nothing(self):
        recs = [{"uuid": "a"}, {"uuid": "b"}, {"type": "queue"}, {"uuid": "d"}]
        sizes = [10, 20, 5, 40]
        self.assertEqual(rh.receipt_cut({"last_uuid": "b"}, recs, sizes), (2, "receipt-uuid"))
        self.assertEqual(rh.receipt_cut({"last_uuid": "zz", "bytes": 36}, recs, sizes), (3, "receipt-bytes"))
        self.assertEqual(rh.receipt_cut({"last_uuid": None, "bytes": 0}, recs, sizes), (None, ""))
        self.assertEqual(rh.stop_cut({"end": 4, "active": False}), (4, False, "end-cut"))
        s = {"end": 4, "active": False, "rcpt": {"end": 2, "by": "receipt-uuid", "code": "stop-hook-active"}}
        self.assertEqual(rh.stop_cut(s), (2, True, "receipt-uuid"))
        self.assertEqual(rh.stop_cut(s, use_receipts=False), (4, False, "end-cut"))


if __name__ == "__main__":
    unittest.main()
