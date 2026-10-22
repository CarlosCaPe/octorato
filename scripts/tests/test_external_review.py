#!/usr/bin/env python3
"""Tests for receipted reviews on other engines (v11 spec 202610141000, phase 4, T19).

  - the Accepted_Review_Call parser: accepted shapes, refused shapes (AC-20),
    the requested model (AC-22), and the prompt digest against the argv Bash
    itself passes (AC-23)
  - the hook pair end to end: a pinned call leaves one complete receipt that
    the ledger returns as a reviewer whose id is its tool_use_id (AC-18,
    AC-19, AC-24); a tampered output copy, a call missing from the session
    transcript or a deny arm make it count for nothing (AC-24, AC-27)
  - panel_pass_for never returns an external PASS (AC-26)
  - the QA_Receipt_Reflex adds `external_reviewers` (AC-28)
  - the Doctor keeps runtime status census-only next to an `allowed`
    reviewer (AC-29) and fails an `allowed` pair or a machine path in the
    Reviewer_Registry
  - the three selftests the registry runs (AC-21, AC-38)

Stdlib plus PyYAML (as test_runtime_registry):
    python3 -m unittest scripts.tests.test_external_review
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent
ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import brain_doctor  # noqa: E402
import external_review as er  # noqa: E402
import panel_digest as pd  # noqa: E402
import panel_fixture_seed as seed  # noqa: E402
import receipt_ledger as rl  # noqa: E402

N = "/opt/n/bin/node"
CJS = "/opt/n/lib/node_modules/@openai/codex/bin/codex.js"
GJS = "/opt/n/lib/node_modules/@google/gemini-cli/bundle/gemini.js"
ENGINES = {"codex": (N, CJS), "gemini": (N, GJS)}
T = dt.datetime(2026, 10, 14, 10, 0, 0, tzinfo=dt.timezone.utc)


def iso(t):
    return t.isoformat().replace("+00:00", ".000Z")


class HomeCase(unittest.TestCase):
    """A throwaway HOME for every test, restored after."""

    def setUp(self):
        self.home = Path(os.path.realpath(tempfile.mkdtemp(prefix="ext-review-test-")))
        # os.path.expanduser reads USERPROFILE on Windows and ignores HOME; both
        # point at the throwaway HOME, or the code under test writes the real one.
        self.env_home = mock.patch.dict(os.environ, {"HOME": str(self.home),
                                                     "USERPROFILE": str(self.home)})
        self.env_home.start()

    def tearDown(self):
        self.env_home.stop()
        shutil.rmtree(self.home, ignore_errors=True)


class Parser(unittest.TestCase):
    def ok(self, cmd):
        call, why = er.parse_call(cmd, ENGINES)
        self.assertIsNotNone(call, f"{cmd!r} refused: {why}")
        return call

    def no(self, cmd):
        call, _ = er.parse_call(cmd, ENGINES)
        self.assertIsNone(call, f"{cmd!r} was accepted")

    def test_accepted_shapes(self):
        c = self.ok(f"{N} {CJS} exec --skip-git-repo-check -m m1 'review this'")
        self.assertEqual((c["engine"], c["prompt"], c["prompt_index"]), ("codex", "review this", 6))
        g = self.ok(f"{N} {GJS} --model m2 --prompt 'review this'")
        self.assertEqual((g["engine"], g["requested_model"]), ("gemini", "m2"))

    def test_ac20_refused_shapes(self):
        for cmd in (
            f"codex(){{ {N} {CJS} \"$@\"; }}; codex exec 'p'",
            f"alias codex='{N} {CJS}' && codex exec 'p'",
            "PATH=/tmp/fake:$PATH codex exec 'p'",
            f"FOO=1 {N} {CJS} exec 'p'",
            f"env {N} {CJS} exec 'p'",
            "codex exec 'p'",
            f"{CJS} exec 'p'",
            f"{N} {CJS} exec 'p' && true",
            f"{N} {CJS} exec 'p' | cat",
            f"{N} {CJS} exec 'p'; true",
            f"{N} {CJS} exec -c x=1 'p'",
            f"{N} {CJS} exec --config x=1 'p'",
            f"{N} {CJS} exec --oss 'p'",
            f"{N} {CJS} exec -p prof 'p'",
            f"{N} {CJS} exec 'p' < /tmp/x",
            f"{N} {CJS} exec 'p' > /tmp/x",
            f"{N} {CJS} exec - <<< 'p'",
            f"{N} {CJS} exec - <<EOF\np\nEOF",
            f"{N} {CJS} exec\n'p'",
            f"{N} {CJS} exec $P",
            f"{N} {CJS} exec \"$(cat p)\"",
            f"{N} {CJS} exec `cat p`",
            f"{N} {CJS} exec p*",
            f"{N} {CJS} exec ~/p",
            f"{N} {CJS} exec 'a' 'b'",
            f"{N} {CJS} exec",
            f"{N} {CJS} 'p'",
            f"{N} {GJS} -p 'p' --yolo",
            f"{N} {GJS} 'p'",
            f"{N} {GJS} -m a -m b -p 'p'",
            f"{N} {CJS} exec 'unterminated",
        ):
            self.no(cmd)

    def test_single_quotes_hide_metacharacters_double_quotes_do_not(self):
        self.ok(f"{N} {CJS} exec 'a; b | c > d $e `f` (g) {{h}}\nnext line'")
        self.no(f"{N} {CJS} exec \"a $e\"")
        self.no(f"{N} {CJS} exec \"it's $HOME\"")

    def test_ac22_requested_model(self):
        self.assertEqual(self.ok(f"{N} {CJS} exec -m gpt-x 'p'")["requested_model"], "gpt-x")
        self.assertEqual(self.ok(f"{N} {CJS} exec --model gpt-x 'p'")["requested_model"], "gpt-x")
        self.assertEqual(self.ok(f"{N} {CJS} exec 'p'")["requested_model"], "unknown")
        self.assertEqual(self.ok(f"{N} {GJS} -p 'p'")["requested_model"], "unknown")

    def test_ac23_digest_is_the_single_prompt_argument(self):
        c = self.ok(f"{N} {CJS} exec 'it'\"'\"'s' ")
        self.assertEqual(c["prompt"], "it's")
        self.assertEqual(c["prompt_sha256"], er.sha256_bytes("it's".encode()))

    @unittest.skipUnless(shutil.which("bash"), "needs bash")
    def test_ac23_digest_equals_bash_argv(self):
        self.assertEqual(er._digest_checks([]), [])


def _write_session(home, session, tid, command, ts, agent=None):
    rel = Path(".claude") / "projects" / "fx" / f"{session}.jsonl"
    tp = home / rel
    if agent:
        tp = home / ".claude" / "projects" / "fx" / session / "subagents" / f"agent-{agent}.jsonl"
    tp.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": command}}]},
         "uuid": "u-" + tid, "parentUuid": None, "sessionId": session,
         "timestamp": iso(ts - dt.timedelta(seconds=30))},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tid, "content": "ok"}]},
         "uuid": "r-" + tid, "parentUuid": "u-" + tid, "sessionId": session, "timestamp": iso(ts)},
    ]
    with tp.open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return home / rel


class HookPairSeam(HomeCase):
    """The rows the real hooks write are the rows the ledger accepts."""

    def setUp(self):
        super().setUp()
        self.p = er._sandbox_layout(str(self.home))
        er._write_pins(str(self.home), self.p)
        seed.seed_reviewer_pair(self.home, "codex", "m1", "allowed")
        self.session, self.tid = "sess-seam", "toolu_seam_1"
        self.msg = pd.Message("The fix is in.", [], ["operator"])
        self.cmd = er._expand_cmd("{{NODE}} {{CODEX}} exec -m m1 'Review the block.'", self.p)
        self.env = {k: v for k, v in os.environ.items()
                    if k not in er.POISON_ENV}
        self.env["CLAUDE_PROJECT_DIR"] = str(self.home / ".claude")
        self.now = T + dt.timedelta(minutes=10)

    def run_pair(self, verdict="PASS", cwd=None, write_session=True, mutate=None):
        tp = self.home / ".claude" / "projects" / "fx" / f"{self.session}.jsonl"
        if write_session:
            tp = _write_session(self.home, self.session, self.tid, self.cmd, T)
        payload = {"session_id": self.session, "tool_name": "Bash", "tool_use_id": self.tid,
                   "tool_input": {"command": self.cmd}, "cwd": cwd or str(self.home / ".claude"),
                   "transcript_path": str(tp)}
        (self.home / ".claude").mkdir(exist_ok=True)
        pend = er.pre_hook(payload, self.env)
        self.assertIsNotNone(pend)
        self.assertEqual(pend["pre_problems"], [])
        if mutate:
            mutate()
        block = self.msg.panel_block().rsplit("\nPANEL-SHA256:", 1)[0]
        out = f"Reviewed.\n{block}\nPANEL-VERDICT: {verdict}\nPANEL-SHA256: {self.msg.digest}\n"
        return er.post_hook(dict(payload, tool_response={"stdout": out, "stderr": "",
                                                         "interrupted": False}), self.env)

    def test_ac18_ac24_complete_receipt_counts_as_one_reviewer(self):
        rec = self.run_pair()
        self.assertIsNotNone(rec)
        self.assertEqual((rec["state"], rec["exit_code"], rec["requested_model"]),
                         ("complete", 0, "m1"))
        self.assertEqual(rec["prompt_sha256"], er.sha256_bytes(b"Review the block."))
        self.assertTrue((self.home / ".claude/.cache/receipts/external/toolu_seam_1.out").is_file())
        got = rl.panel_receipts_for(self.msg.digest, self.session, self.now)
        self.assertEqual([(r["agent_id"], r["verdict"], r.get("external")) for r in got],
                         [(self.tid, "PASS", True)])
        self.assertIsNone(rl.panel_pass_for(self.msg.digest, self.session, self.now))  # AC-26

    def test_ac19_swap_during_call_leaves_no_receipt(self):
        def swap():
            with open(self.p["vendor"], "ab") as fh:
                fh.write(b"x")
        self.assertIsNone(self.run_pair(mutate=swap))

    def test_ac24_tampered_output_copy_does_not_count(self):
        self.assertIsNotNone(self.run_pair())
        out = self.home / ".claude/.cache/receipts/external/toolu_seam_1.out"
        out.write_text(out.read_text() + "\n", encoding="utf-8")
        self.assertEqual(rl.panel_receipts_for(self.msg.digest, self.session, self.now), [])

    def test_ac24_call_absent_from_session_transcript_does_not_count(self):
        self.assertIsNotNone(self.run_pair(write_session=False))
        self.assertEqual(rl.panel_receipts_for(self.msg.digest, self.session, self.now), [])

    def test_ac24_outside_window_and_not_allowed_do_not_count(self):
        self.assertIsNotNone(self.run_pair())
        late = T + dt.timedelta(minutes=rl.PANEL_WINDOW_MINUTES + 1)
        self.assertEqual(rl.panel_receipts_for(self.msg.digest, self.session, late), [])
        seed.seed_reviewer_pair(self.home, "codex", "m1", "not-allowed")
        self.assertEqual(rl.panel_receipts_for(self.msg.digest, self.session, self.now), [])

    def test_ac27_deny_arm_does_not_count_allow_arm_does(self):
        cwd = seed.seed_arm(self.home, "client", "deny")
        self.env["CLAUDE_PROJECT_DIR"] = os.path.expanduser(cwd)
        self.assertIsNotNone(self.run_pair(cwd=os.path.expanduser(cwd)))
        self.assertEqual(rl.panel_receipts_for(self.msg.digest, self.session, self.now), [])
        (self.home / "arms" / "client" / "arm.json").write_text(
            json.dumps({"telemetry": {"export": "allow"}}), encoding="utf-8")
        self.assertEqual(len(rl.panel_receipts_for(self.msg.digest, self.session, self.now)), 1)


    def test_ac27_cwd_moved_out_of_a_deny_arm_project_does_not_count(self):
        arm = os.path.expanduser(seed.seed_arm(self.home, "client", "deny"))
        (self.home / "elsewhere").mkdir()
        self.env["CLAUDE_PROJECT_DIR"] = arm
        self.assertIsNotNone(self.run_pair(cwd=str(self.home / "elsewhere")))
        self.assertEqual(rl.panel_receipts_for(self.msg.digest, self.session, self.now), [])

    def test_workspace_config_in_cwd_leaves_no_receipt(self):
        work = self.home / "work"
        (work / ".gemini").mkdir(parents=True)
        (work / ".gemini" / "settings.json").write_text("{}", encoding="utf-8")
        self.env["CLAUDE_PROJECT_DIR"] = str(work)
        payload = {"session_id": self.session, "tool_name": "Bash", "tool_use_id": self.tid,
                   "tool_input": {"command": self.cmd}, "cwd": str(work),
                   "transcript_path": str(self.home / "t.jsonl")}
        pend = er.pre_hook(payload, self.env)
        self.assertTrue(any("workspace config" in p for p in pend["pre_problems"]))

    def test_project_dir_absent_and_dotenv_above_it_leave_no_receipt(self):
        env = dict(self.env)
        env.pop("CLAUDE_PROJECT_DIR")
        payload = {"session_id": self.session, "tool_name": "Bash", "tool_use_id": self.tid,
                   "tool_input": {"command": self.cmd}, "cwd": str(self.home / ".claude"),
                   "transcript_path": str(self.home / "t.jsonl")}
        self.assertIn("CLAUDE_PROJECT_DIR is absent from the hook environment",
                      er.pre_hook(payload, env)["pre_problems"])
        (self.home / "w" / "p").mkdir(parents=True)
        (self.home / "w" / ".env").write_text("X=1\n", encoding="utf-8")
        probs = er.workspace_problems(str(self.home / "w" / "p"), str(self.home / "w" / "p"))
        self.assertTrue(any(p.endswith(os.path.join("w", ".env")) for p in probs), probs)

    def test_codex_subcommand_in_prompt_slot_is_refused(self):
        call, why = er.parse_call(f"{N} {CJS} exec resume", ENGINES)
        self.assertIsNone(call)
        self.assertIn("subcommand", why)


class QaReflex(HomeCase):
    """AC-28: a reviewer that names an external receipt gets it recorded."""

    def _reviewer(self, session, agent, report):
        tp = self.home / ".claude" / "projects" / "fx" / session / "subagents" / f"agent-{agent}.jsonl"
        tp.parent.mkdir(parents=True, exist_ok=True)
        rows = [
            {"type": "user", "message": {"role": "user", "content": "Panel."}, "uuid": "p-" + agent,
             "parentUuid": None, "sessionId": session, "timestamp": iso(T)},
            {"type": "assistant", "message": {"role": "assistant", "id": "m-" + agent,
                                              "content": [{"type": "text", "text": report}]},
             "uuid": "a-" + agent, "parentUuid": "p-" + agent, "sessionId": session,
             "timestamp": iso(T + dt.timedelta(minutes=1))},
        ]
        tp.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        return tp

    def _run(self, session, agent, tp):
        env = dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home))
        payload = {"session_id": session, "agent_id": agent, "agent_type": "Reality Checker",
                   "agent_transcript_path": str(tp)}
        subprocess.run([sys.executable, str(SCRIPTS / "r__subagent-stop__qa-receipt.py")],
                       input=json.dumps(payload), capture_output=True, text=True, env=env,
                       timeout=60)
        rows = [json.loads(ln) for ln in
                (self.home / ".claude/.cache/receipts/global.jsonl").read_text().splitlines()]
        return [r for r in rows if r.get("kind") == "panel" and r.get("agent_id") == agent]

    def _case(self, report_verdict):
        session = "sess-qa-ext"
        msg = pd.Message("The fix is in.", [], ["operator"])
        recent = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)
        seed.seed_external_receipt(self.home, session, msg, "PASS", iso(recent), "toolu_qx")
        block = msg.panel_block().rsplit("\nPANEL-SHA256:", 1)[0]
        report = (f"Checked it, and ran a second engine.\nREVIEW-EXTERNAL: toolu_qx\n{block}\n"
                  f"PANEL-VERDICT: {report_verdict}\nPANEL-SHA256: {msg.digest}")
        return self._run(session, "abc123", self._reviewer(session, "abc123", report))

    def test_ac28_matching_verdict_is_recorded(self):
        rows = self._case("PASS")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["agent_type"], "Reality Checker")
        self.assertEqual(rows[0]["external_reviewers"],
                         [{"tool_use_id": "toolu_qx", "engine": "codex",
                           "requested_model": "fx-review-model"}])

    def test_ac28_other_verdict_is_not_recorded(self):
        rows = self._case("NEEDS-WORK")
        self.assertEqual(len(rows), 1)
        self.assertNotIn("external_reviewers", rows[0])


class DoctorAC29(unittest.TestCase):
    """An `allowed` reviewer never changes a runtime status."""

    def setUp(self):
        import test_runtime_registry as trr
        import yaml
        self.trr, self.yaml = trr, yaml
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "census").mkdir()
        for name in ("gemini.json", "codex.json"):
            (self.root / "census" / name).write_text(json.dumps(trr._census(None)), encoding="utf-8")
        self.reg = self.root / "runtimes.yaml"
        self.rev = self.root / "reviewers.yaml"
        for patcher in (mock.patch.object(brain_doctor, "CHECKS",
                                          list(brain_doctor.CHECKS) + trr.FAKE_CHECKS),
                        mock.patch.object(brain_doctor, "EVIDENCE_HARNESSES",
                                          {"claude-code": "fake-ok", "cursor": "fake-ok"}),
                        mock.patch.object(brain_doctor, "REVIEWERS_PATH", self.rev)):
            patcher.start()
            self.addCleanup(patcher.stop)
        getattr(brain_doctor, "_CURRENT_RUN", {}).clear()

    def tearDown(self):
        self._tmp.cleanup()

    def _reviewers(self, pairs, extra=None):
        data = {"schema": 1, "reviewers": {"codex": {"name": "Codex CLI"}}, "pairs": pairs}
        data.update(extra or {})
        self.rev.write_text(self.yaml.safe_dump(data), encoding="utf-8")

    def test_allowed_reviewer_meets_gap_census(self):
        allowed = [{"engine": "codex", "model": "m1", "status": "allowed",
                    "replay_record": "registry/replay/records/codex-m1.json",
                    "baseline_model": "fable"}]
        base = copy.deepcopy(self.trr.BASE)
        self.reg.write_text(self.yaml.safe_dump(base), encoding="utf-8")
        self._reviewers([])
        before = brain_doctor.check_runtime_census_evidence(False, self.reg, self.root)
        self._reviewers(allowed)
        after = brain_doctor.check_runtime_census_evidence(False, self.reg, self.root)
        self.assertEqual((before.status, before.message), (after.status, after.message))
        self.assertEqual(after.status, brain_doctor.PASS, after.message)
        # A `supported` Codex with a gap census fails whatever the reviewer says.
        base["runtimes"]["codex-cli"].update(
            status="supported", evidence="brain_doctor runtime-census-evidence",
            tiers=dict(self.trr.TIERS))
        base["runtimes"]["codex-cli"].pop("classes_not_blocked", None)
        self.reg.write_text(self.yaml.safe_dump(base), encoding="utf-8")
        r = brain_doctor.check_runtime_census_evidence(False, self.reg, self.root)
        self.assertEqual(r.status, brain_doctor.FAIL)
        self.assertIn("codex-cli", r.message)
        # And the reviewer check fails the allowed pair until T20's recompute.
        rr = brain_doctor.check_reviewer_registry(False, self.rev)
        self.assertEqual(rr.status, brain_doctor.FAIL)
        self.assertIn("codex/m1", rr.message)

    def test_reviewer_registry_shape_and_machine_paths(self):
        self._reviewers([])
        self.assertEqual(brain_doctor.check_reviewer_registry(False, self.rev).status,
                         brain_doctor.PASS)
        self._reviewers([], {"reviewers": {"codex": {"script": "/home/someone/codex.js"}}})
        self.assertEqual(brain_doctor.check_reviewer_registry(False, self.rev).status,
                         brain_doctor.FAIL)
        self._reviewers([{"engine": "codex", "model": "m1", "status": "maybe",
                          "replay_record": None, "baseline_model": None}])
        self.assertEqual(brain_doctor.check_reviewer_registry(False, self.rev).status,
                         brain_doctor.FAIL)

    def test_tracked_registry_passes(self):
        r = brain_doctor.check_reviewer_registry(False, ROOT / "registry" / "reviewers.yaml")
        self.assertEqual(r.status, brain_doctor.PASS, r.message)


class Selftests(unittest.TestCase):
    """The commands registry/rules.yaml runs as EXIT_CODE proofs."""

    def _run(self, *argv):
        env = {k: v for k, v in os.environ.items() if k not in er.POISON_ENV}
        cp = subprocess.run([sys.executable, *argv], capture_output=True, text=True, cwd=str(ROOT),
                            env=env, timeout=600)
        self.assertEqual(cp.returncode, 0, cp.stderr[-2000:])

    def test_ac21_external_review_selftest(self):
        self._run(str(SCRIPTS / "external_review.py"), "--selftest",
                  "registry/fixtures/FLOW.external-review-receipt")

    def test_ac38_forged_receipts_selftest(self):
        self._run(str(SCRIPTS / "receipt_ledger.py"), "--selftest-external")


if __name__ == "__main__":
    unittest.main()
