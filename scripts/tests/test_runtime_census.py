#!/usr/bin/env python3
"""Tests for scripts/runtime_census.py (deterministic part only, no model, no network).

    python3 -m unittest scripts.tests.test_runtime_census
"""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
BRAIN = SCRIPTS.parent


def _load():
    spec = importlib.util.spec_from_file_location("runtime_census", SCRIPTS / "runtime_census.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rc = _load()


class TranslationTest(unittest.TestCase):
    def test_every_block_fixture_round_trips_on_both_harnesses(self):
        for harness in rc.HARNESSES:
            classes = rc.census_deterministic(harness)
            for tc in rc.TOOL_CLASSES:
                with self.subTest(harness=harness, tool_class=tc):
                    self.assertTrue(classes[tc]["translatable"], classes[tc])
                    for leg in classes[tc]["legs"]:
                        self.assertEqual(leg["status"], "measured")
                        self.assertTrue(leg["round_trip_lossless"], leg)

    def test_unparseable_payload_is_a_failure_never_an_allow(self):
        for harness in rc.HARNESSES:
            for bad in ("not json at all", "[]", '{"tool_name": 7}', '{"tool_name": "x"}',
                        '{"tool_name": "apply_patch", "tool_input": {"command": "garbage"}}',
                        '{"tool_name": "mcp_gmail_send", "tool_input": {}}'):
                with self.subTest(harness=harness, payload=bad):
                    with self.assertRaises(rc.TranslationError):
                        rc.translate(harness, bad)

    def test_unreadable_fixture_recorded_as_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "X").mkdir()
            (root / "X" / "violation.json").write_text("{not json", encoding="utf-8")
            leg = rc.census_leg("gemini", "shell", "violation", "X/violation.json", root)
            self.assertEqual(leg["status"], "failure")
            self.assertFalse(leg["translatable"])
            self.assertNotIn("round_trip_lossless", leg)

    def test_harness_tool_names_follow_the_documented_maps(self):
        fx = {"tool_name": "mcp__gmail__send_email", "tool_input": {"to": ["a"], "body": "b"},
              "cwd": "/w", "session_id": "s"}
        g = rc.render_gemini(fx)
        self.assertEqual(g["tool_name"], "mcp_gmail_send_email")
        self.assertEqual(g["hook_event_name"], "BeforeTool")
        self.assertEqual(g["mcp_context"], {"server_name": "gmail", "tool_name": "send_email"})
        c = rc.render_codex(fx)
        self.assertEqual(c["tool_name"], "mcp__gmail__send_email")
        self.assertEqual(c["hook_event_name"], "PreToolUse")
        edit = {"tool_name": "Edit", "tool_input": {"file_path": "/p/f.py", "old_string": "a",
                                                    "new_string": "b"}, "cwd": "/w", "session_id": "s"}
        self.assertEqual(rc.render_gemini(edit)["tool_name"], "replace")
        cx = rc.render_codex(edit)
        self.assertEqual(cx["tool_name"], "apply_patch")
        self.assertIn("*** Update File: /p/f.py", cx["tool_input"]["command"])

    def test_mcp_class_records_keys_not_bodies(self):
        for harness in rc.HARNESSES:
            classes = rc.census_deterministic(harness)
            for leg in classes["mcp"]["legs"]:
                payload = json.dumps(leg["rendered_payload"])
                self.assertNotIn("Queja", payload)
                self.assertIn("tool_input_keys", leg)


class RecordTest(unittest.TestCase):
    def test_second_run_is_byte_identical_and_never_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self.assertEqual(rc.main(["--out", str(out)]), 0)
            first = {h: (out / f"{h}.json").read_bytes() for h in rc.HARNESSES}
            self.assertEqual(rc.main(["--out", str(out)]), 0)
            for h in rc.HARNESSES:
                self.assertEqual(first[h], (out / f"{h}.json").read_bytes())
                data = json.loads(first[h])
                self.assertEqual(data["status"], "measured")
                self.assertNotEqual(data["status"], "supported")
                for tc in rc.TOOL_CLASSES:
                    self.assertIsNone(data["tool_classes"][tc]["harness_blocked_violation"])

    def test_deterministic_run_keeps_a_previous_live_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            rc.main(["--out", str(out), "--harness", "codex"])
            path = out / "codex.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["live"] = {"outcome": "failure", "reason": "seeded by test"}
            path.write_text(json.dumps(data), encoding="utf-8")
            rc.main(["--out", str(out), "--harness", "codex"])
            again = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(again["live"]["reason"], "seeded by test")

    def test_records_carry_no_home_path(self):
        home = os.path.expanduser("~")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            rc.main(["--out", str(out)])
            for h in rc.HARNESSES:
                text = (out / f"{h}.json").read_text(encoding="utf-8")
                self.assertNotIn(home, text)
        tracked = BRAIN / "registry" / "census"
        for h in rc.HARNESSES:
            p = tracked / f"{h}.json"
            if p.exists():
                self.assertNotIn(home, p.read_text(encoding="utf-8"))

    def test_scrub_refuses_a_home_path_and_a_secret_shape(self):
        home = os.path.expanduser("~")
        with self.assertRaises(RuntimeError):
            rc._scrub({"x": {"nested": "api_key=ABCDEFGHIJKLMNOPQRSTUV"}})
        # a home path is folded, not refused, when it is the plain home
        self.assertIn('"~/x"', rc._scrub({"p": home + "/x"}))

    def test_live_outcome_classes_503_and_timeout_as_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ)
            r = rc._run([sys.executable, "-c", "print('HTTP 503 Service Unavailable')"], tmp, env)
            self.assertEqual(r["outcome"], "failure")
            r = rc._run([sys.executable, "-c", "print('OCTORATO-CENSUS-OK')"], tmp, env)
            self.assertEqual(r["outcome"], "success")
            r = rc._run([sys.executable, "-c", "print('hello')"], tmp, env)
            self.assertEqual(r["outcome"], "failure")
            old = rc._LIVE_TIMEOUT_S
            rc._LIVE_TIMEOUT_S = 1
            try:
                r = rc._run([sys.executable, "-c", "import time; time.sleep(5)"], tmp, env)
            finally:
                rc._LIVE_TIMEOUT_S = old
            self.assertEqual(r["outcome"], "failure")
            self.assertIn("timeout", r["reason"])


if __name__ == "__main__":
    unittest.main()
