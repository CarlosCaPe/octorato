#!/usr/bin/env python3
"""ai_sync pull ends with the FAST doctor profile, push keeps the full gates.

The full doctor took ~220 s on a populated machine, most of it the checks that
execute every gate selftest, and pull is a read path the operator waits on. So
pull runs `brain_doctor.py --fast` and prints where the full profile runs. The
push side is pinned too: .githooks/pre-push must still call --registry and
--gate-receipt, or the fast pull would be the only doctor a change ever meets.

Every step of pull that touches git, hooks or arms is stubbed; the test reads
which arguments reach script_step and never runs a real script or git command.
"""
from __future__ import annotations

import argparse
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import ai_sync  # noqa: E402


class PullDoctorProfile(unittest.TestCase):
    def _run_pull(self):
        calls = []

        def fake_step(rel, *args, fatal=False, label=""):
            calls.append((rel, args))
            return True

        ns = argparse.Namespace(arms=[], status=False)
        out = io.StringIO()
        with mock.patch.object(ai_sync, "_is_repo", return_value=False), \
                mock.patch.object(ai_sync, "script_step", side_effect=fake_step), \
                mock.patch.object(ai_sync, "ensure_hooks_path"), \
                mock.patch.object(ai_sync, "connectome_stale", return_value=False), \
                mock.patch.object(ai_sync, "memory_map_stale", return_value=False), \
                mock.patch.object(ai_sync, "sync", return_value=0), \
                redirect_stdout(out):
            rc = ai_sync.pull(ns)
        return rc, calls, out.getvalue()

    def test_pull_runs_doctor_fast(self):
        rc, calls, _ = self._run_pull()
        self.assertEqual(rc, 0)
        doctor = [args for rel, args in calls if rel == "scripts/brain_doctor.py"]
        self.assertEqual(doctor, [("--fast",)])

    def test_pull_names_where_the_full_profile_runs(self):
        _, _, out = self._run_pull()
        self.assertIn("pre-push", out)
        self.assertIn("python3 scripts/brain_doctor.py", out)

    def test_pre_push_keeps_full_gate_checks(self):
        text = (ROOT / ".githooks" / "pre-push").read_text(encoding="utf-8")
        self.assertIn("brain_doctor.py\" --registry", text)
        self.assertIn("brain_doctor.py\" --gate-receipt", text)
        self.assertNotIn("brain_doctor.py\" --fast", text)


if __name__ == "__main__":
    unittest.main()
