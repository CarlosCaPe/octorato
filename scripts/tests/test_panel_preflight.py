#!/usr/bin/env python3
"""Tests for panel_preflight.py and panel_digest.py --preflight (FLOW.panel-before-reply).

Pins: every Stop hook in hooks.json is run or skipped with a reason; a draft a
Stop gate would block makes --preflight exit 1 and --panel-request --to
operator print no block; a clean draft passes and its block carries the
draft's own digest; the source class and quorum are printed; the session
transcript is copied, never written; the gates get no session_id.

Stdlib only:

    python3 -m unittest scripts.tests.test_panel_preflight
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
ROOT = SCRIPTS.parent
DIGEST = SCRIPTS / "panel_digest.py"
sys.path.insert(0, str(SCRIPTS))

import panel_digest  # noqa: E402
import panel_preflight  # noqa: E402

CLEAN = "The tests pass on the branch.\n\nProvenance: Basis: git log origin/master · Engine: main loop\n"
CLEAN_SELF = "The tests pass on the branch.\n\nProvenance: Basis: own reasoning\n"
NO_FOOTER = "The tests pass on the branch.\n"
EM_DASH = "The tests pass — all of them.\n\nProvenance: Basis: git log\n"


def _env() -> dict:
    env = dict(os.environ)
    for k in ("CLAUDE_SESSION_ID", "CLAUDE_CODE_SESSION_ID"):
        env.pop(k, None)
    return env


class _Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pf-test-"))
        self.transcript = self.tmp / "session.jsonl"
        self.transcript.write_text(json.dumps({
            "type": "user", "uuid": "u1", "timestamp": "2026-10-16T08:00:00.000Z",
            "message": {"role": "user", "content": "Do the tests pass?"}, "origin": {"kind": "human"},
        }) + "\n", encoding="utf-8")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def body(self, text: str) -> Path:
        p = self.tmp / "body.md"
        p.write_text(text, encoding="utf-8")
        return p

    def cli(self, text: str, *args):
        return subprocess.run([sys.executable, str(DIGEST), "--body-file", str(self.body(text)),
                               "--transcript", str(self.transcript), *args],
                              capture_output=True, text=True, encoding="utf-8", env=_env(),
                              cwd=str(self.tmp), timeout=120)


class HookCoverageTests(unittest.TestCase):
    def test_every_stop_hook_is_run_or_skipped(self):
        hooks = panel_preflight.stop_hooks(ROOT / "hooks.json")
        names = {h[0] for h in hooks}
        self.assertTrue(names, "no Stop hooks read from hooks.json")
        for name in panel_preflight.SKIP:
            self.assertIn(name, names, f"SKIP lists {name}, which is not a Stop hook")
        run = names - set(panel_preflight.SKIP)
        for gate in ("cadence-stop-hook.py", "source-attribution-check.py", "claim-verify-stop.py",
                     "g__stop__no-menu-question.py", "g__stop__defer-today.py",
                     "g__stop__draft-promise.py", "g__stop__paste-ready-raw.py",
                     "g__stop__unsourced-attribute.py", "g__stop__unsourced-absence.py"):
            self.assertIn(gate, run)
        for name in run:
            self.assertTrue((SCRIPTS / name).is_file(), f"{name} missing in scripts/")


class PreflightCliTests(_Tmp):
    def test_clean_draft_passes_with_class_and_quorum(self):
        cp = self.cli(CLEAN, "--to", "operator", "--preflight")
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        self.assertIn("PREFLIGHT verdict: PASS", cp.stdout)
        self.assertIn("source class: SOURCED, reply panel quorum: 1", cp.stdout)
        self.assertIn("PREFLIGHT cadence-stop-hook.py: PASS", cp.stdout)

    def test_self_draft_prints_quorum_three(self):
        cp = self.cli(CLEAN_SELF, "--to", "operator", "--preflight")
        self.assertIn("source class: SELF, reply panel quorum: 3", cp.stdout)

    def test_missing_footer_blocks(self):
        cp = self.cli(NO_FOOTER, "--to", "operator", "--preflight")
        self.assertEqual(cp.returncode, 1, cp.stdout + cp.stderr)
        self.assertIn("PREFLIGHT source-attribution-check.py: BLOCK", cp.stdout)

    def test_em_dash_blocks(self):
        cp = self.cli(EM_DASH, "--to", "operator", "--preflight")
        self.assertEqual(cp.returncode, 1, cp.stdout + cp.stderr)
        self.assertIn("PREFLIGHT cadence-stop-hook.py: BLOCK", cp.stdout)

    def test_preflight_needs_operator_only(self):
        cp = self.cli(CLEAN, "--to", "someone@example.com", "--preflight")
        self.assertEqual(cp.returncode, 2)

    def test_transcript_is_not_written(self):
        before = self.transcript.read_bytes()
        self.cli(CLEAN, "--to", "operator", "--preflight")
        self.assertEqual(self.transcript.read_bytes(), before)


class PanelRequestTests(_Tmp):
    def test_blocked_draft_gets_no_panel_block(self):
        cp = self.cli(NO_FOOTER, "--to", "operator", "--panel-request")
        self.assertEqual(cp.returncode, 1)
        self.assertNotIn("PANEL-SHA256", cp.stdout)
        self.assertIn("no panel request", cp.stderr)

    def test_clean_draft_gets_its_own_digest(self):
        cp = self.cli(CLEAN, "--to", "operator", "--panel-request")
        self.assertEqual(cp.returncode, 0, cp.stderr)
        want = panel_digest.digest(CLEAN, recipients=["operator"])
        self.assertIn(f"PANEL-SHA256: {want}", cp.stdout)
        self.assertIn("PREFLIGHT: PASS, source class SOURCED", cp.stderr)

    def test_no_preflight_flag_emits_block(self):
        cp = self.cli(NO_FOOTER, "--to", "operator", "--panel-request", "--no-preflight")
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertIn("PANEL-SHA256", cp.stdout)

    def test_outward_panel_request_runs_no_preflight(self):
        cp = self.cli(NO_FOOTER, "--to", "someone@example.com", "--panel-request")
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertNotIn("PREFLIGHT", cp.stderr)
        self.assertIn("PANEL-SHA256", cp.stdout)


class PayloadTests(_Tmp):
    def test_gates_get_no_session_id_and_first_stop(self):
        seen = []
        orig = panel_preflight._run_one

        def spy(script, tail, timeout, payload, cwd):
            seen.append(payload)
            return {"gate": script, "verdict": "PASS", "reason": ""}

        panel_preflight._run_one = spy
        try:
            res = panel_preflight.run(CLEAN, str(self.transcript))
        finally:
            panel_preflight._run_one = orig
        self.assertTrue(seen)
        for p in seen:
            self.assertNotIn("session_id", p)
            self.assertIs(p["stop_hook_active"], False)
            self.assertEqual(p["last_assistant_message"], CLEAN)
        self.assertEqual(res["blocked"], [])

    def test_child_env_drops_session_ids(self):
        os.environ["CLAUDE_CODE_SESSION_ID"] = "x"
        try:
            self.assertNotIn("CLAUDE_CODE_SESSION_ID", panel_preflight._child_env())
        finally:
            os.environ.pop("CLAUDE_CODE_SESSION_ID", None)


if __name__ == "__main__":
    unittest.main()
