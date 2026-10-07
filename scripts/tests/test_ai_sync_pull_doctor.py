#!/usr/bin/env python3
"""ai_sync pull ends with the FAST doctor profile and keeps the gate receipt valid.

The full doctor took ~220 s on a populated machine, most of it the checks that
execute every gate selftest, and pull is a read path the operator waits on. So
pull runs `brain_doctor.py --fast`. The fast profile skips gate-liveness, the
only writer of the gate receipt every send needs, so pull then runs
`--gate-receipt`, but only when no receipt covers the current gate tree: most
pulls leave scripts/, registry/ and hooks.json alone, and re-proving an
unchanged tree costs ~150 s for nothing. The push side is pinned too:
.githooks/pre-push must still call --registry and --gate-receipt.

The pull cases stub every step that touches git, hooks or arms and read which
arguments reach script_step. The receipt cases build a throwaway brain repo and
a throwaway HOME, so the real ledger is never read or written.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import ai_sync  # noqa: E402
import receipt_ledger  # noqa: E402


class PullDoctorProfile(unittest.TestCase):
    def _run_pull(self, receipt_valid: bool):
        calls = []

        def fake_step(rel, *args, fatal=False, label=""):
            calls.append((rel, args))
            return True

        ns = argparse.Namespace(arms=[], status=False)
        out = io.StringIO()
        current = "a" * 40 if receipt_valid else ""
        with mock.patch.object(ai_sync, "_is_repo", return_value=False), \
                mock.patch.object(ai_sync, "script_step", side_effect=fake_step), \
                mock.patch.object(ai_sync, "gate_receipt_current", return_value=current), \
                mock.patch.object(ai_sync, "ensure_hooks_path"), \
                mock.patch.object(ai_sync, "connectome_stale", return_value=False), \
                mock.patch.object(ai_sync, "memory_map_stale", return_value=False), \
                mock.patch.object(ai_sync, "sync", return_value=0), \
                redirect_stdout(out):
            rc = ai_sync.pull(ns)
        doctor = [args for rel, args in calls if rel == "scripts/brain_doctor.py"]
        return rc, doctor, out.getvalue()

    def test_invalid_receipt_runs_fast_then_gate_receipt(self):
        rc, doctor, out = self._run_pull(receipt_valid=False)
        self.assertEqual(rc, 0)
        self.assertEqual(doctor, [("--fast",), ("--gate-receipt",)])
        self.assertIn("gate surfaces changed, re-proving", out)

    def test_valid_receipt_skips_gate_receipt(self):
        rc, doctor, out = self._run_pull(receipt_valid=True)
        self.assertEqual(rc, 0)
        self.assertEqual(doctor, [("--fast",)])
        self.assertIn("gate receipt still valid for tree " + "a" * 12 + ", skipped", out)

    def test_pull_names_where_the_full_profile_runs(self):
        _, _, out = self._run_pull(receipt_valid=True)
        self.assertIn("pre-push", out)
        self.assertIn("--gate-receipt", out)
        self.assertIn("python3 scripts/brain_doctor.py", out)

    def test_pre_push_keeps_full_gate_checks(self):
        text = (ROOT / ".githooks" / "pre-push").read_text(encoding="utf-8")
        self.assertIn("brain_doctor.py\" --registry", text)
        self.assertIn("brain_doctor.py\" --gate-receipt", text)
        self.assertNotIn("brain_doctor.py\" --fast", text)


class GateReceiptCurrent(unittest.TestCase):
    """gate_receipt_current against a real git tree and a real ledger file."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.home = base / "home"
        self.brain = base / "brain"
        (self.brain / "scripts").mkdir(parents=True)
        (self.brain / "registry").mkdir()
        (self.brain / "scripts" / "g.py").write_text("print('gate')\n")
        (self.brain / "registry" / "rules.yaml").write_text("rules: []\n")
        (self.brain / "hooks.json").write_text("{}\n")
        git = ["git", "-C", str(self.brain), "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(git[:3] + ["init", "-q"], check=True)
        subprocess.run(git + ["add", "scripts", "registry", "hooks.json"], check=True)
        subprocess.run(git + ["commit", "-q", "-m", "base"], check=True)
        self.env = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        self.env.start()
        self.claude = mock.patch.object(ai_sync, "CLAUDE", self.brain)
        self.claude.start()

    def tearDown(self):
        self.claude.stop()
        self.env.stop()
        self.tmp.cleanup()

    def _write_receipt(self, gates: str):
        path = receipt_ledger.global_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as fh:
            fh.write(json.dumps({"kind": "gate-liveness", "ok": True, "gates": gates}) + "\n")

    def test_no_receipt_means_reprove(self):
        self.assertEqual(ai_sync.gate_receipt_current(), "")

    def test_receipt_for_this_tree_is_reused(self):
        gates = receipt_ledger.gate_tree_hash(self.brain)
        self.assertTrue(gates)
        self._write_receipt(gates)
        self.assertEqual(ai_sync.gate_receipt_current(), gates)

    def test_receipt_for_another_tree_means_reprove(self):
        self._write_receipt("0" * 40 + ":" + "1" * 40 + ":" + "2" * 40)
        self.assertEqual(ai_sync.gate_receipt_current(), "")

    def test_dirty_gate_surface_means_reprove(self):
        self._write_receipt(receipt_ledger.gate_tree_hash(self.brain))
        (self.brain / "scripts" / "g.py").write_text("print('edited')\n")
        self.assertEqual(ai_sync.gate_receipt_current(), "")


if __name__ == "__main__":
    unittest.main()
