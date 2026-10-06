#!/usr/bin/env python3
"""Anchors for the v10 friction measurement (friction_ledger, the Stop reflex,
replay_harness, `octo friction`).

Pinned here: a transcript holding one PreToolUse deny and one Stop block yields
exactly those ledger lines with gate, session, tool, reason code and a digest of
the input cut to 1,200 characters; the ledger never holds the reason text or the
input; re-reading, a resumed copy and a half-written line add nothing; the Stop
reflex never blocks and never prints, even on garbage; every gate the signature
table names exists; the replay harness SKIPs without a corpus, reads a hook's
decision the way the harness does, replays a real gate in a sandbox, and exits
non-zero when a labelled true positive stops being denied; `octo friction`
reports denies, median and p95 latency and the labelled FP rate.

All transcript content is synthetic. Timing is never asserted.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent
ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

import friction_ledger  # noqa: E402
import octo  # noqa: E402
import replay_harness  # noqa: E402

SID = "00000000-0000-4000-8000-000000000001"
DENY_INPUT = {"command": "gh pr merge 7 --squash", "description": "merge"}
STOP_TEXT = "All done, the example task is finished."
SECRET_WORD = "example-reason-text-never-stored"


def _transcript() -> list:
    """One exit-2 deny (named command), one JSON deny (signature only), one
    harness deny, one Stop block, one hook duration and one Stop summary."""
    return [
        {"type": "user", "uuid": "u1", "sessionId": SID, "timestamp": "2026-09-10T10:00:00.000Z",
         "message": {"role": "user", "content": "please do the example task"}},
        {"type": "assistant", "uuid": "a1", "sessionId": SID, "timestamp": "2026-09-10T10:00:01.000Z",
         "message": {"role": "assistant", "content": [
             {"type": "tool_use", "id": "toolu_A", "name": "Bash", "input": DENY_INPUT}]}},
        {"type": "user", "uuid": "r1", "sessionId": SID, "timestamp": "2026-09-10T10:00:02.000Z",
         "message": {"role": "user", "content": [
             {"type": "tool_result", "tool_use_id": "toolu_A", "is_error": True,
              "content": "PreToolUse:Bash hook error: [python3 ~/.claude/scripts/qa-merge-gate.py]: "
                         f"✗ QA GATE (fail-closed): {SECRET_WORD}"}]}},
        {"type": "assistant", "uuid": "a2", "sessionId": SID, "timestamp": "2026-09-10T10:00:03.000Z",
         "message": {"role": "assistant", "content": [
             {"type": "tool_use", "id": "toolu_B", "name": "mcp__gmail__send_email",
              "input": {"to": ["someone@example.com"], "body": "x" * 3000}},
             {"type": "tool_use", "id": "toolu_C", "name": "Bash", "input": {"command": "sleep 60"}}]}},
        {"type": "user", "uuid": "r2", "sessionId": SID, "timestamp": "2026-09-10T10:00:04.000Z",
         "message": {"role": "user", "content": [
             {"type": "tool_result", "tool_use_id": "toolu_B", "is_error": True,
              "content": f"PreToolUse:mcp__gmail__send_email hook error: 📬 ENVÍO SIN PEDIDO: {SECRET_WORD}"},
             {"type": "tool_result", "tool_use_id": "toolu_C", "is_error": True,
              "content": "<tool_use_error>Blocked: sleep 60 is not allowed</tool_use_error>"}]}},
        {"type": "attachment", "uuid": "h1", "sessionId": SID, "timestamp": "2026-09-10T10:00:04.500Z",
         "attachment": {"type": "hook_success", "hookName": "PreToolUse:Bash", "hookEvent": "PreToolUse",
                        "command": "python3 ~/.claude/scripts/delegate-gate.py", "durationMs": 120}},
        {"type": "assistant", "uuid": "a3", "sessionId": SID, "timestamp": "2026-09-10T10:00:05.000Z",
         "message": {"role": "assistant", "content": [{"type": "text", "text": STOP_TEXT}]}},
        {"type": "attachment", "uuid": "b1", "sessionId": SID, "timestamp": "2026-09-10T10:00:06.000Z",
         "attachment": {"type": "hook_blocking_error", "hookName": "Stop", "hookEvent": "Stop",
                        "blockingError": {"blockingError": f"⚓ ANCLA: {SECRET_WORD}",
                                          "command": "python3 ~/.claude/scripts/g__stop__goal-anchor.py"}}},
        {"type": "system", "subtype": "stop_hook_summary", "uuid": "s1", "sessionId": SID,
         "timestamp": "2026-09-10T10:00:06.100Z",
         "hookInfos": [{"command": "python3 ~/.claude/scripts/g__stop__goal-anchor.py", "durationMs": 300},
                       {"command": "python3 ~/.claude/scripts/claim-verify-stop.py", "durationMs": 900}]},
    ]


def _write(path: Path, recs: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in recs:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


class FrictionCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="friction-test-"))
        self.ldir = self.tmp / "ledger"
        self.env = mock.patch.dict(os.environ, {"OCTO_FRICTION_DIR": str(self.ldir)})
        self.env.start()
        self.tp = self.tmp / "projects" / "p" / f"{SID}.jsonl"
        _write(self.tp, _transcript())

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ledger(self) -> list:
        return friction_ledger.read_ledger()


class TestLedger(FrictionCase):
    def test_one_line_per_deny_and_block_with_required_fields(self):
        res = friction_ledger.ingest_paths([self.tp])
        rows = self.ledger()
        self.assertEqual(res["events"], 4)
        by_kind = {}
        for r in rows:
            by_kind.setdefault(r["kind"], []).append(r)
            for k in ("gate", "session", "tool", "code", "input_sha256", "key", "uuid", "ts"):
                self.assertIn(k, r)
            self.assertEqual(r["session"], SID)
        pre = {r["gate"]: r for r in by_kind["pretool-deny"]}
        merge = pre["qa-merge-gate.py"]
        self.assertEqual((merge["tool"], merge["code"]), ("Bash", "merge-approval"))
        want = hashlib.sha256(json.dumps(DENY_INPUT, sort_keys=True,
                                         ensure_ascii=False)[:1200].encode()).hexdigest()
        self.assertEqual(merge["input_sha256"], want)
        send = pre["g__pretool-mcp__outward-send.py"]
        self.assertEqual((send["tool"], send["code"]), ("mcp__gmail__send_email", "send-ask"))
        self.assertGreater(send["input_chars"], 1200)  # digest is of the cut, length of the whole
        stop = by_kind["stop-block"][0]
        self.assertEqual((stop["gate"], stop["code"], stop["event"]),
                         ("g__stop__goal-anchor.py", "root-goal-unnamed", "Stop"))
        self.assertEqual(stop["input_sha256"], hashlib.sha256(STOP_TEXT.encode()).hexdigest())
        self.assertEqual(by_kind["harness-deny"][0]["gate"], "harness:sleep")

    def test_ledger_holds_no_reason_text_and_no_input(self):
        friction_ledger.ingest_paths([self.tp])
        raw = (self.ldir / "ledger.jsonl").read_text(encoding="utf-8")
        for needle in (SECRET_WORD, "gh pr merge", "someone@example.com", STOP_TEXT):
            self.assertNotIn(needle, raw)

    def test_idempotent_rerun_resumed_copy_and_full_reread(self):
        friction_ledger.ingest_paths([self.tp])
        n = len(self.ledger())
        friction_ledger.ingest_paths([self.tp])
        friction_ledger.ingest_paths([self.tp], incremental=False)
        copy = self.tp.with_name("resumed-copy.jsonl")
        shutil.copy(self.tp, copy)
        friction_ledger.ingest_paths([copy])
        self.assertEqual(len(self.ledger()), n)
        lat = friction_ledger.read_latency()
        self.assertEqual(len(lat), 3)
        self.assertEqual(len({x["key"] for x in lat}), 3)

    def test_byte_budget_catches_up_over_several_calls(self):
        friction_ledger.ingest_paths([self.tp])
        whole = sorted(r["key"] for r in self.ledger())
        shutil.rmtree(self.ldir)
        calls = 0
        while True:
            calls += 1
            res = friction_ledger.ingest_paths([self.tp], max_bytes=600)
            if not res["pending"] or calls > 50:
                break
        self.assertGreater(calls, 2)
        self.assertEqual(sorted(r["key"] for r in self.ledger()), whole)

    def test_half_written_line_waits_for_its_newline(self):
        recs = _transcript()
        head = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs[:3])
        tail = json.dumps(recs[7], ensure_ascii=False)
        self.tp.write_text(head + tail[:40], encoding="utf-8")
        friction_ledger.ingest_paths([self.tp])
        self.assertEqual([r["kind"] for r in self.ledger()], ["pretool-deny"])
        self.tp.write_text(head + tail + "\n", encoding="utf-8")
        friction_ledger.ingest_paths([self.tp])
        self.assertEqual(sorted(r["kind"] for r in self.ledger()), ["pretool-deny", "stop-block"])

    def test_subagent_transcripts_are_read_with_their_session(self):
        sub = self.tp.parent / SID / "subagents" / "agent-x.jsonl"
        recs = [dict(r, uuid="sub-" + r["uuid"], agentId="x") for r in _transcript()]
        _write(sub, recs)
        friction_ledger.ingest_paths(friction_ledger.session_paths(str(self.tp), SID))
        agents = {r["agent"] for r in self.ledger()}
        self.assertEqual(agents, {"", "x"})

    def test_unknown_deny_is_kept_as_unattributed(self):
        recs = _transcript()[:2] + [{
            "type": "user", "uuid": "r9", "sessionId": SID, "timestamp": "2026-09-10T10:00:02.000Z",
            "message": {"role": "user", "content": [{
                "type": "tool_result", "tool_use_id": "toolu_A", "is_error": True,
                "content": "PreToolUse:Bash hook error: a refusal no row describes"}]}}]
        _write(self.tp, recs)
        friction_ledger.ingest_paths([self.tp])
        self.assertEqual(self.ledger()[0]["gate"], "unattributed")

    def test_every_gate_in_the_signature_table_exists(self):
        raw = json.loads((ROOT / "registry" / "friction-signatures.json").read_text(encoding="utf-8"))
        for s in raw["signatures"]:
            if s["gate"].startswith("harness:"):
                continue
            self.assertTrue((SCRIPTS / s["gate"]).exists(), s["gate"])


class TestStopReflex(FrictionCase):
    def run_reflex(self, stdin: str):
        env = dict(os.environ, HOME=str(self.tmp))
        return subprocess.run([sys.executable, str(SCRIPTS / "r__stop__friction-ledger.py")],
                              input=stdin, capture_output=True, text=True, env=env, timeout=60)

    def test_records_and_never_blocks(self):
        cp = self.run_reflex(json.dumps({"session_id": SID, "transcript_path": str(self.tp),
                                         "hook_event_name": "Stop"}))
        self.assertEqual((cp.returncode, cp.stdout), (0, ""))
        self.assertEqual(len(self.ledger()), 4)

    def test_fails_open_on_garbage_and_missing_transcript(self):
        for stdin in ("not json", "", json.dumps({"transcript_path": str(self.tmp / "nope.jsonl")})):
            cp = self.run_reflex(stdin)
            self.assertEqual((cp.returncode, cp.stdout), (0, ""))


class TestReplayHarness(FrictionCase):
    def test_skip_without_corpus(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = replay_harness.main(["--corpus", str(self.tmp / "absent"), "replay"])
        self.assertEqual(rc, 0)
        self.assertIn("SKIP", buf.getvalue())

    def test_decide_reads_the_hook_answer_like_the_harness(self):
        d = replay_harness.decide
        self.assertEqual(d(2, "", "why")[0], "deny")
        self.assertEqual(d(0, json.dumps({"hookSpecificOutput": {"permissionDecision": "deny"}}), "")[0], "deny")
        self.assertEqual(d(0, json.dumps({"decision": "block", "reason": "r"}), "")[0], "deny")
        self.assertEqual(d(0, json.dumps({"hookSpecificOutput": {"permissionDecision": "ask"}}), "")[0], "ask")
        self.assertEqual(d(0, json.dumps({"systemMessage": "fyi"}), "")[0], "allow")
        self.assertEqual(d(1, "", "Traceback")[0], "error")

    def _mini_corpus(self) -> Path:
        cdir = self.tmp / "corpus"
        (cdir / "cases").mkdir(parents=True)
        cases = [("c-deny", {"command": "grep -i token .env"}, "deny"),
                 ("c-allow", {"command": "ls -la"}, "allow")]
        with open(cdir / "index.jsonl", "w", encoding="utf-8") as idx:
            for cid, inp, hist in cases:
                case = {"id": cid, "gate": "secrets-grep-guard.py", "event": "PreToolUse",
                        "kind": hist, "hist": hist, "hist_code": "", "sub": False, "ts": "",
                        "payload": {"session_id": SID, "hook_event_name": "PreToolUse",
                                    "tool_name": "Bash", "tool_input": inp, "cwd": ""},
                        "window": _transcript()[:2], "reason": "", "prompt": "", "blocked": ""}
                with gzip.open(cdir / "cases" / f"{cid}.json.gz", "wt", encoding="utf-8") as fh:
                    json.dump(case, fh)
                idx.write(json.dumps({k: case[k] for k in ("id", "gate", "event", "kind", "hist",
                                                           "hist_code", "sub", "ts")}) + "\n")
        return cdir

    def test_real_gate_replays_in_a_sandbox(self):
        cdir = self._mini_corpus()
        res = replay_harness.replay_all(cdir, 2)
        self.assertEqual(res["c-deny"]["d"], "deny")
        self.assertEqual(res["c-deny"]["c"], "secret-read")
        self.assertEqual(res["c-allow"]["d"], "allow")

    def test_lost_true_positive_exits_non_zero(self):
        cdir = self._mini_corpus()
        base = {"generated": "t", "cases": {
            "c-deny": {"g": "secrets-grep-guard.py", "e": "PreToolUse", "h": "deny", "d": "deny",
                       "c": "secret-read", "l": "TP"},
            "c-allow": {"g": "secrets-grep-guard.py", "e": "PreToolUse", "h": "allow", "d": "allow",
                        "c": "", "l": "-"}}}
        bpath = self.tmp / "baseline.json"
        bpath.write_text(json.dumps(base), encoding="utf-8")
        argv = ["--corpus", str(cdir), "replay", "--baseline", str(bpath)]
        with redirect_stdout(io.StringIO()):
            self.assertEqual(replay_harness.main(argv), 0)
        loosened = {"c-deny": {"id": "c-deny", "d": "allow", "c": ""},
                    "c-allow": {"id": "c-allow", "d": "deny", "c": "secret-read"}}
        with mock.patch.object(replay_harness, "replay_all", return_value=loosened), \
                redirect_stdout(io.StringIO()) as out, mock.patch("sys.stderr", new=io.StringIO()):
            self.assertEqual(replay_harness.main(argv), 1)
        self.assertIn("allow to deny: 1", out.getvalue())
        self.assertIn("deny to allow: 1", out.getvalue())

    def test_build_freezes_cases_and_fresh_keeps_label_rules(self):
        cdir = self.tmp / "corpus"
        cdir.mkdir()
        rules = {"rules": [{"gate": "qa-merge-gate.py", "hist": "deny", "field": "input",
                            "pattern": "gh pr merge", "label": "TP"}]}
        (cdir / "label-rules.json").write_text(json.dumps(rules), encoding="utf-8")
        argv = ["--corpus", str(cdir), "build", "--root", str(self.tmp / "projects"),
                "--since", "2026-09-01", "--until", "2026-10-01", "--fresh", "--no-baseline",
                "--allow-per-gate", "2"]
        with redirect_stdout(io.StringIO()):
            self.assertEqual(replay_harness.main(argv), 0)
            self.assertEqual(replay_harness.main(argv), 0)
        self.assertTrue((cdir / "label-rules.json").exists())
        idx = replay_harness._index(cdir)
        denies = {r["gate"] for r in idx if r["kind"] == "deny"}
        self.assertEqual(denies, {"qa-merge-gate.py", "g__pretool-mcp__outward-send.py",
                                  "g__stop__goal-anchor.py"})
        self.assertTrue(any(r["kind"] == "allow" and r["event"] == "Stop" for r in idx))
        labels = json.loads((cdir / "labels.json").read_text(encoding="utf-8"))
        merge_id = next(r["id"] for r in idx if r["gate"] == "qa-merge-gate.py")
        self.assertEqual(labels, {merge_id: "TP"})
        case = replay_harness._read_case(cdir, merge_id)
        self.assertEqual(case["payload"]["tool_input"], DENY_INPUT)
        self.assertEqual(case["window"][-1]["uuid"], "a1")

    def test_unlabelled_flip_is_reported_but_does_not_fail(self):
        base = {"cases": {"x": {"g": "g.py", "e": "Stop", "h": "deny", "d": "deny", "c": "a", "l": "FP"}}}
        diff = replay_harness.compare(base, {"x": {"id": "x", "d": "allow", "c": ""}})
        self.assertEqual((len(diff["deny_to_allow"]), len(diff["lost_tp"])), (1, 0))

    def test_label_rules_first_match_wins(self):
        case = {"gate": "g.py", "hist": "deny", "hist_code": "send-ask", "sub": False,
                "payload": {"tool_input": {"command": "cat notes.txt"}}, "prompt": "send it", "reason": ""}
        rules = [{"gate": "g.py", "code": "send-ask", "field": "prompt", "pattern": "send it", "label": "FP"},
                 {"gate": "g.py", "field": "input", "pattern": "cat", "label": "TP"}]
        self.assertEqual(replay_harness.label_of(case, rules), "FP")
        self.assertEqual(replay_harness.label_of(dict(case, hist_code="x"), rules), "TP")
        self.assertEqual(replay_harness.label_of(dict(case, gate="other.py"), rules), "")


class TestOctoFriction(FrictionCase):
    def test_report_counts_latency_and_window(self):
        friction_ledger.ingest_paths([self.tp])
        now = 1789056000.0  # 2026-09-11T00:00:00Z, one day after the synthetic events
        rep = octo.friction_report(7, now=now)
        g = {r["gate"]: r for r in rep["gates"]}
        self.assertEqual(g["qa-merge-gate.py"]["denies"], 1)
        self.assertEqual(g["g__stop__goal-anchor.py"]["denies"], 1)
        self.assertEqual(g["g__stop__goal-anchor.py"]["latency_p50_ms"], 300)
        self.assertEqual(g["g__stop__goal-anchor.py"]["latency_p95_ms"], 300)
        self.assertIn("harness:sleep", g)
        old = octo.friction_report(7, now=now + 30 * 86400)
        self.assertEqual(old["ledger_rows"], 0)

    def test_percentiles(self):
        vals = list(range(1, 101))
        self.assertEqual(octo._pct(vals, 0.95), 95)
        self.assertEqual(octo._median([1, 2, 3, 4]), 2.5)
        self.assertIsNone(octo._pct([], 0.95))

    def test_cli_prints_empty_hint_and_json(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(octo.main(["friction", "--days", "3"]), 0)
        self.assertIn("ledger is empty", buf.getvalue())
        friction_ledger.ingest_paths([self.tp])
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(octo.main(["friction", "--days", "10000", "--json"]), 0)
        self.assertEqual(json.loads(buf.getvalue())["ledger_rows"], 4)


if __name__ == "__main__":
    unittest.main()
