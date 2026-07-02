#!/usr/bin/env python3
"""Tests for the v6 gate-liveness harness. Proves the prover.

Two anti-fake guarantees are asserted here:

  1. gate_selftest's BENIGN leg is real: a gate that blocks EVERYTHING FAILS its
     selftest, so gaming the harness by denying all is impossible.
  2. brain_doctor's gate-liveness check FAILs when a registered gate's --selftest
     does not pass, i.e. a labeled-but-dead gate is caught.

Stdlib only, no network/services:

    python3 -m unittest scripts.tests.test_gate_liveness
    python3 scripts/tests/test_gate_liveness.py
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
CLAUDE_DIR = SCRIPTS.parent


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_block_everything_gate(d: Path) -> Path:
    """A gate that denies EVERY payload, with a --selftest wired to the real harness."""
    script = d / "broken_gate.py"
    script.write_text(
        "import sys, json\n"
        f"sys.path.insert(0, {str(SCRIPTS)!r})\n"
        "def main():\n"
        "    json.loads(sys.stdin.read() or '{}')\n"
        "    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse',\n"
        "        'permissionDecision': 'deny', 'permissionDecisionReason': 'blocks everything'}}))\n"
        "    return 0\n"
        "if __name__ == '__main__':\n"
        "    if '--selftest' in sys.argv:\n"
        "        import gate_selftest\n"
        "        i = sys.argv.index('--selftest')\n"
        "        sys.exit(gate_selftest.run_gate_selftest(__file__, sys.argv[i+1]))\n"
        "    sys.exit(main())\n",
        encoding="utf-8",
    )
    fx = d / "fixtures"
    fx.mkdir()
    (fx / "violation.json").write_text(json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}), encoding="utf-8")
    (fx / "benign.json").write_text(json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": "ls"}}), encoding="utf-8")
    return script


class GateLivenessHarnessTest(unittest.TestCase):
    def test_benign_leg_fails_a_block_everything_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            script = _write_block_everything_gate(d)
            cp = subprocess.run(
                [sys.executable, str(script), "--selftest", str(d / "fixtures")],
                capture_output=True, text=True,
            )
            # block-everything blocks the benign fixture, so the selftest must FAIL
            self.assertNotEqual(cp.returncode, 0,
                                "block-everything gate must FAIL the benign leg")

    def test_doctor_gate_liveness_fails_on_broken_gate(self):
        doctor = _load_module("brain_doctor_under_test", SCRIPTS / "brain_doctor.py")
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            script = _write_block_everything_gate(d)
            registry = d / "rules.yaml"
            registry.write_text(
                "version: 1\n"
                "rules:\n"
                "  - id: TEST.broken-gate\n"
                "    title: deliberately broken gate for the harness self-test\n"
                "    category: FLOW\n"
                "    source: { file: CLAUDE.md, anchor: \"RULE #1\" }\n"
                "    strength: GATE\n"
                "    gateable: true\n"
                "    enforcement: fail-closed\n"
                "    firing_mode: [hook]\n"
                "    mechanism:\n"
                "      - { kind: Gate, canonical_name: broken_gate.py, firing_event: PreToolUse, firing_matcher: \"Bash\" }\n"
                "    proof:\n"
                f"      - {{ method: EXIT_CODE, locator: \"{script} --selftest {d/'fixtures'}\", expect: 0 }}\n"
                "    liveness_required: FIRES\n",
                encoding="utf-8",
            )
            orig = doctor.REGISTRY_PATH
            try:
                doctor.REGISTRY_PATH = registry
                result = doctor.check_gate_liveness(False)
            finally:
                doctor.REGISTRY_PATH = orig
            self.assertEqual(result.status, doctor.FAIL,
                             f"doctor must FAIL a broken gate, got {result.status}: {result.message}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
