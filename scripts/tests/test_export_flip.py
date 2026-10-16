#!/usr/bin/env python3
"""g__pretool__export-flip.py: the Export_Flip_Gate of v11 AC-16.

The selftest runs registry/fixtures/SECURITY.export-flip through
gate_selftest. These cases pin what a JSON fixture cannot carry: stdin that is
not JSON, a symlink whose own name is not arm.json, and the transition rule
(keeping an operator's `allow` is not a flip). Temp dirs only.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
GATE = SCRIPTS / "g__pretool__export-flip.py"
_spec = importlib.util.spec_from_file_location("export_flip", GATE)
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)

DENY_ARM = json.dumps({"kind": "arm", "telemetry": {"export": "deny"}})
ALLOW_ARM = json.dumps({"kind": "arm", "telemetry": {"export": "allow"}})


def run(payload, cwd, raw=None):
    env = dict(os.environ, HOME=cwd, USERPROFILE=cwd)
    data = raw if raw is not None else json.dumps(payload)
    cp = subprocess.run([sys.executable, str(GATE)], input=data, capture_output=True,
                        text=True, encoding="utf-8", cwd=cwd, env=env, timeout=60)
    out = cp.stdout.strip()
    return json.loads(out)["hookSpecificOutput"]["permissionDecision"] if out else "allow"


class ExportFlip(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = os.path.realpath(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_selftest_passes(self):
        cp = subprocess.run([sys.executable, str(GATE), "--selftest"], capture_output=True,
                            text=True, cwd=str(SCRIPTS.parent), timeout=300)
        self.assertEqual(cp.returncode, 0, cp.stderr)

    def test_stdin_not_json_denies(self):
        self.assertEqual(run(None, self.d, raw="{not json"), "deny")

    def test_symlink_alias_of_arm_json(self):
        Path(self.d, "arm.json").write_text(DENY_ARM, encoding="utf-8")
        os.symlink(os.path.join(self.d, "arm.json"), os.path.join(self.d, "notes.json"))
        p = {"tool_name": "Write", "cwd": self.d,
             "tool_input": {"file_path": "notes.json", "content": ALLOW_ARM}}
        self.assertEqual(run(p, self.d), "deny")

    def test_keeping_an_operator_allow_passes(self):
        Path(self.d, "arm.json").write_text(ALLOW_ARM, encoding="utf-8")
        p = {"tool_name": "Edit", "cwd": self.d,
             "tool_input": {"file_path": os.path.join(self.d, "arm.json"),
                            "old_string": '"kind": "arm"', "new_string": '"kind": "arm", "v": 2'}}
        self.assertEqual(run(p, self.d), "allow")

    def test_sets_allow_counts_every_repeated_key(self):
        self.assertTrue(gate.sets_allow('{"telemetry": {"export": "allow", "export": "deny"}}'))
        self.assertTrue(gate.sets_allow('{"telemetry": {}, "telemetry": {"export": "allow"}}'))
        self.assertFalse(gate.sets_allow('{"telemetry": {"export": "Allow"}}'))
        self.assertFalse(gate.sets_allow('{"other": {"export": "allow"}}'))
        self.assertFalse(gate.sets_allow("not json"))

    def test_shell_reads_pass(self):
        for cmd in ("cat arm.json", "jq .telemetry arm.json 2>/dev/null",
                    "git diff -- arm.json", "grep -n export arm.json"):
            self.assertIsNone(gate.decide_bash(cmd), cmd)


if __name__ == "__main__":
    unittest.main()
