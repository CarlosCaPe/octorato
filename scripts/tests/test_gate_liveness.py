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

# brain_doctor imports its siblings (receipt_ledger) by bare name. Run alone, this
# module left scripts/ off sys.path, so check_gate_liveness raised ImportError and
# returned FAIL from its receipt branch: the broken-gate assertion below was green
# for a reason that had nothing to do with a broken gate. Under `unittest discover`
# a sibling module happened to insert this path first, so the same test measured a
# different thing depending on what ran before it. Pin it here.
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_working_gate(d: Path) -> Path:
    """The benign twin of the broken gate, derived from it by ONE edit: the deny is
    conditional on the violation payload instead of unconditional. It blocks the
    violation fixture and allows the benign one, so its selftest exits 0."""
    return _write_gate(d, deny_when="'rm -rf' in cmd")


def _write_block_everything_gate(d: Path) -> Path:
    """A gate that denies EVERY payload: it blocks the violation fixture but ALSO
    blocks the benign one, so its selftest must fail the benign leg."""
    return _write_gate(d, deny_when="True")


def _write_gate(d: Path, deny_when: str) -> Path:
    """Write a gate whose --selftest is wired to the real harness. `deny_when` is the
    python expression over `cmd` that decides whether to emit a PreToolUse deny."""
    script = d / "broken_gate.py"
    script.write_text(
        "import sys, json\n"
        f"sys.path.insert(0, {str(SCRIPTS)!r})\n"
        "def main():\n"
        "    payload = json.loads(sys.stdin.read() or '{}')\n"
        "    cmd = (payload.get('tool_input') or {}).get('command', '')\n"
        f"    if {deny_when}:\n"
        "        print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse',\n"
        "            'permissionDecision': 'deny', 'permissionDecisionReason': 'denied'}}))\n"
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

    def test_evaluate_proofs_judges_the_rule_set_it_is_handed(self):
        """The general proof executor must judge the caller's rules, never re-read the
        brain's own registry behind its back. Re-reading is precisely what hid a dead
        gate: check_gate_liveness loaded a registry holding one broken gate and the
        executor answered about 41 healthy proofs out of a different file."""
        doctor = _load_module("brain_doctor_rules_arg", SCRIPTS / "brain_doctor.py")
        rules = [{"id": "TEST.handed-in",
                  "proof": [{"method": "FILE_EXISTS",
                             "locator": "no_such_file_in_this_brain.xyz",
                             "expect": "present"}]}]
        failures, evaluated, _na = doctor.evaluate_proofs(
            CLAUDE_DIR, methods=("FILE_EXISTS",), rules=rules)
        self.assertEqual(evaluated, 1,
                         f"executor must evaluate the 1 handed-in proof, evaluated {evaluated}")
        self.assertTrue(any("TEST.handed-in" in f for f in failures),
                        f"handed-in failing proof must be reported, got {failures}")

    def _run_doctor_over(self, d: Path, script: Path):
        """Point brain_doctor's registry at a one-rule registry naming `script`'s
        selftest, and return check_gate_liveness's verdict."""
        doctor = _load_module("brain_doctor_under_test", SCRIPTS / "brain_doctor.py")
        registry = d / "rules.yaml"
        registry.write_text(
            "version: 1\n"
            "rules:\n"
            "  - id: TEST.broken-gate\n"
            "    title: gate under test for the liveness harness self-test\n"
            "    category: FLOW\n"
            "    source: { file: CLAUDE.md, anchor: \"RULE #1\" }\n"
            "    strength: GATE\n"
            "    gateable: true\n"
            "    enforcement: fail-closed\n"
            "    firing_mode: [hook]\n"
            "    mechanism:\n"
            "      - { kind: Gate, canonical_name: broken_gate.py, firing_event: PreToolUse, firing_matcher: \"Bash\" }\n"
            "    proof:\n"
            # Single-quoted YAML scalar: inside DOUBLE quotes a backslash
            # opens an escape sequence, so a Windows locator makes the whole
            # registry unparseable and the doctor reports "cannot load
            # registry" (WARN) instead of failing the broken gate this test
            # is about. Single quotes take the path literally.
            f"      - {{ method: EXIT_CODE, locator: '{script} --selftest {d/'fixtures'}', expect: 0 }}\n"
            "    liveness_required: FIRES\n",
            encoding="utf-8",
        )
        orig = doctor.REGISTRY_PATH
        try:
            doctor.REGISTRY_PATH = registry
            return doctor, doctor.check_gate_liveness(False)
        finally:
            doctor.REGISTRY_PATH = orig

    def test_doctor_gate_liveness_fails_on_broken_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            doctor, result = self._run_doctor_over(d, _write_block_everything_gate(d))
        self.assertEqual(result.status, doctor.FAIL,
                         f"doctor must FAIL a broken gate, got {result.status}: {result.message}")
        # Any FAIL is not enough. The check has other FAIL branches (an unresolvable
        # HEAD, a receipt that cannot be written), and this test was once green from
        # one of them while the liveness sweep was gone. Demand the verdict name the
        # broken gate and the leg it failed.
        self.assertIn("block+allow", result.message,
                      f"FAIL must come from the liveness sweep, got: {result.message}")
        self.assertIn("TEST.broken-gate", result.message,
                      f"FAIL must name the dead gate, got: {result.message}")

    def test_doctor_gate_liveness_does_not_fail_on_a_working_gate(self):
        """The other direction, one edit away: the same registry, the same fixtures,
        a gate that denies the violation and allows the benign payload. A check that
        reddens on everything proves as little as one that reddens on nothing."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            doctor, result = self._run_doctor_over(d, _write_working_gate(d))
        self.assertNotIn("block+allow", result.message,
                         f"a working gate must not fail the liveness sweep: {result.message}")
        # PASS on a clean tree; WARN when gate surfaces differ from HEAD (the receipt
        # branch deliberately refuses to vouch for uncommitted gates). Never FAIL.
        self.assertIn(result.status, (doctor.PASS, doctor.WARN),
                      f"working gate must not FAIL, got {result.status}: {result.message}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
