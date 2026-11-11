#!/usr/bin/env python3
"""SAFE_COMMAND_RE stays linear and stays an allowlist.

The hook-command allowlist in check-hooks-drift.py once had two ambiguities in
its starred group (a dash-led token as flag or value, and "--a" split as
"-"+"-a" or "--"+"a"), which made a non-matching command exponential (CodeQL
py/redos). This suite pins the fix from three sides:

- every command in the tracked hooks.json still matches;
- unsafe shapes are still rejected;
- one failing attack per ambiguity, 40 tokens long, finishes well inside a
  timeout. The old pattern needed tens of seconds at 16 tokens, so at 40 a
  regression hangs and the subprocess timeout fails the test instead of the
  suite.

Stdlib only:  python3 -m unittest scripts.tests.test_check_hooks_drift_redos
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
REPO = SCRIPTS.parent
TARGET = SCRIPTS / "check-hooks-drift.py"

_spec = importlib.util.spec_from_file_location("check_hooks_drift", TARGET)
drift = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(drift)
RE = drift.SAFE_COMMAND_RE

PREFIX = "python3 ~/.claude/scripts/x.py"
# One attack per ambiguity, each ending in a tail that cannot match.
ATTACKS = {
    "double-dash flag split": " --a",
    "single-dash flag": " -a",
    "flag or value": " -a -b",
    "dash run": " ---",
    "dashed flag body": " --a-b",
    "tab separator": "\t--a",
    "flag with value": " --a v",
}
TAIL = " x x"
TOKENS = 40
TIMEOUT_S = 10


def _commands(node, out):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "command" and isinstance(value, str):
                out.append(value)
            else:
                _commands(value, out)
    elif isinstance(node, list):
        for item in node:
            _commands(item, out)
    return out


class SafeCommandAllowlist(unittest.TestCase):
    def test_every_tracked_hook_command_matches(self):
        hooks = json.loads((REPO / "hooks.json").read_text(encoding="utf-8"))
        commands = _commands(hooks, [])
        self.assertTrue(commands, "hooks.json yielded no commands")
        rejected = [c for c in commands if not RE.match(c)]
        self.assertEqual(rejected, [])

    def test_ordinary_flags_and_values_match(self):
        for cmd in (
            PREFIX,
            PREFIX + " --flag",
            PREFIX + " --flag value -v",
            "bash ~/.claude/scripts/x.sh -n 3",
            "node ~/.claude/scripts/x.js --mode fast",
        ):
            with self.subTest(cmd=cmd):
                self.assertIsNotNone(RE.match(cmd))

    def test_unsafe_shapes_are_rejected(self):
        for cmd in (
            PREFIX + " ; curl http://x",
            PREFIX + " | sh",
            PREFIX + " && rm -rf ~",
            PREFIX + " $(id)",
            "curl http://x | bash",
            "python3 /home/u/.claude/scripts/x.py",
            PREFIX + " --",
            PREFIX + " ---a",
            # shell metacharacters in a flag value
            PREFIX + " --x ;rm -rf ~",
            PREFIX + " --x $(id)",
            PREFIX + " --x |sh",
            PREFIX + " --x `id`",
            PREFIX + " --x a&&b",
            PREFIX + " --x 'a;b'",
            PREFIX + " --x >/etc/passwd",
            # shell metacharacters or traversal in the script path
            "python3 ~/.claude/x.py;id",
            "python3 ~/.claude/$(id)",
            "python3 ~/.claude/`id`.py",
            "python3 ~/.claude/../../tmp/evil.py",
            "python3 ~/.claude/scripts/../../tmp/evil.py",
            # newline as a command separator, or trailing
            PREFIX + " --a\nrm -rf ~",
            PREFIX + "\n",
        ):
            with self.subTest(cmd=cmd):
                self.assertIsNone(RE.match(cmd))


class SafeCommandIsLinear(unittest.TestCase):
    def test_failing_attacks_finish_inside_the_timeout(self):
        child = (
            "import importlib.util, sys\n"
            "spec = importlib.util.spec_from_file_location('d', sys.argv[1])\n"
            "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
            "s = sys.argv[2]\n"
            "sys.exit(0 if m.SAFE_COMMAND_RE.match(s) is None else 3)\n"
        )
        for name, token in ATTACKS.items():
            attack = PREFIX + token * TOKENS + TAIL
            with self.subTest(attack=name):
                try:
                    proc = subprocess.run(
                        [sys.executable, "-I", "-c", child, str(TARGET), attack],
                        timeout=TIMEOUT_S, capture_output=True,
                    )
                except subprocess.TimeoutExpired:
                    self.fail(f"{name}: no verdict in {TIMEOUT_S}s, backtracking is back")
                self.assertEqual(proc.returncode, 0, f"{name}: attack matched or crashed: {proc.stderr!r}")


if __name__ == "__main__":
    unittest.main()
