#!/usr/bin/env python3
"""g__wrap__export-guard.py: the Export_Guard of v11 AC-09, AC-10 and AC-11.

The selftest drives every fixture of registry/fixtures/SECURITY.export-guard
with a stub upstream and asserts whether it was spawned. These cases pin, by
name, what a reader of the selftest line would otherwise have to trust: the
selftest passes, a deny is silent at the real command line, and an allow arm
gets the upstream with the payload bytes unchanged. Every leg runs under a
temporary HOME; nothing reads the operator's brain or arms.
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
GUARD = SCRIPTS / "g__wrap__export-guard.py"
_spec = importlib.util.spec_from_file_location("export_guard", GUARD)
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)

STUB = "import sys\nopen(sys.argv[1], 'wb').write(sys.stdin.buffer.read())\n"


class ExportGuard(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = os.path.realpath(self._tmp.name)
        os.makedirs(os.path.join(self.home, ".claude", "company", "config"))
        self.stub = os.path.join(self.home, "stub.py")
        Path(self.stub).write_text(STUB, encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _arm(self, name, manifest):
        root = os.path.join(self.home, "arms", name)
        os.makedirs(root, exist_ok=True)
        if manifest is not None:
            Path(root, "arm.json").write_text(json.dumps(manifest), encoding="utf-8")
        cfg = Path(self.home, ".claude", guard.ARMS_REL)
        reg = json.loads(cfg.read_text(encoding="utf-8")) if cfg.exists() else {}
        reg[name] = f"arms/{name}"
        cfg.write_text(json.dumps(reg), encoding="utf-8")
        return root

    def _cli(self, cwd, *, project_dir=None):
        marker = os.path.join(self.home, "spawned.bin")
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
        env.update(HOME=self.home, USERPROFILE=self.home)
        if project_dir:
            env["CLAUDE_PROJECT_DIR"] = project_dir
        raw = json.dumps({"cwd": cwd, "hook_event_name": "PostToolUse"}).encode("utf-8")
        cp = subprocess.run([sys.executable, str(GUARD), "--", sys.executable, self.stub, marker],
                            input=raw, capture_output=True, env=env, timeout=60)
        got = Path(marker).read_bytes() if os.path.exists(marker) else None
        return cp, raw, got

    def test_selftest_passes(self):
        cp = subprocess.run([sys.executable, str(GUARD), "--selftest"],
                            capture_output=True, text=True, timeout=300)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertIn("selftest PASS", cp.stdout)

    def test_absent_field_is_silent_and_spawns_nothing(self):
        root = self._arm("plain", {"kind": "arm", "name": "plain"})
        cp, _raw, got = self._cli(root)
        self.assertEqual((cp.returncode, cp.stdout, cp.stderr, got), (0, b"", b"", None))

    def test_allow_arm_gets_the_payload_bytes(self):
        root = self._arm("open", {"kind": "arm", "telemetry": {"export": "allow"}})
        cp, raw, got = self._cli(root)
        self.assertEqual(cp.returncode, 0)
        self.assertEqual(got, raw)

    def test_project_dir_in_a_deny_arm_closes_an_allow_cwd(self):
        open_root = self._arm("open", {"kind": "arm", "telemetry": {"export": "allow"}})
        closed = self._arm("closed", {"kind": "arm", "telemetry": {"export": "deny"}})
        cp, _raw, got = self._cli(open_root, project_dir=closed)
        self.assertEqual((cp.returncode, cp.stdout, got), (0, b"", None))

    def test_unregistered_deny_arm_inside_an_allow_arm(self):
        # QA probe: a client repo cloned into an allow arm's tree before it is
        # registered carries its own deny. Red without the walk to the root.
        root = self._arm("open", {"kind": "arm", "telemetry": {"export": "allow"}})
        inner = os.path.join(root, "vendor", "client")
        os.makedirs(inner)
        Path(inner, "arm.json").write_text(
            json.dumps({"kind": "arm", "telemetry": {"export": "deny"}}), encoding="utf-8")
        with self.assertRaises(guard.Deny):
            guard.decide(json.dumps({"cwd": inner}).encode(), home=self.home, project_dir=None)
        cp, _raw, got = self._cli(os.path.join(inner))
        self.assertEqual((cp.returncode, cp.stdout, got), (0, b"", None))

    def test_no_arms_config_is_deny(self):
        with self.assertRaises(guard.Deny):
            guard.decide(json.dumps({"cwd": self.home}).encode(), home=self.home,
                         project_dir=None)


if __name__ == "__main__":
    unittest.main()
