#!/usr/bin/env python3
"""gate_selftest.run_scripts must behave like `subprocess.run` on a fresh
interpreter, which is what a hook leg used to be.

On Linux a leg is a fork of the selftest process. Each case below is a place
where a fork can quietly differ from a spawn: a timeout that a gate can
disarm, output from a thread that `os._exit` throws away, a grandchild still
holding the pipe, an import path the leg's HOME would not give, a status
stolen from another child, or an exit code mapped differently. Parity cases
run the same leg through both paths and compare.

Stdlib only:  python3 -m unittest scripts.tests.test_gate_selftest_runner
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import gate_selftest  # noqa: E402

DENY = ('{"hookSpecificOutput": {"hookEventName": "PreToolUse", '
        '"permissionDecision": "deny", "permissionDecisionReason": "x"}}')
LINUX = sys.platform.startswith("linux") and hasattr(os, "fork")


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="runner-test-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def gate(self, body: str) -> str:
        path = os.path.join(self.tmp, "gate.py")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(textwrap.dedent(body))
        return path

    def leg(self, script: str, timeout: float = 30, env: dict = None) -> dict:
        return {"script": script, "input": '{"tool_name": "Bash"}',
                "cwd": self.tmp, "env": env or dict(os.environ),
                "timeout": timeout}

    def both(self, script: str, **kw):
        """(rc, stdout) through the fork path and through subprocess.run."""
        out = []
        saved = gate_selftest._FORK_OK
        try:
            for fork in (True, False):
                gate_selftest._FORK_OK = fork and saved
                r = gate_selftest.run_scripts([self.leg(script, **kw)])[0]
                out.append((r.returncode, r.stdout))
        finally:
            gate_selftest._FORK_OK = saved
        return out


@unittest.skipUnless(LINUX, "the fork path exists on Linux only")
class Deadline(_Base):
    """The deadline belongs to the PARENT: a gate cannot disarm it."""

    def _assert_times_out(self, script, limit=1):
        t = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            gate_selftest.run_scripts([self.leg(script, timeout=limit)])
        self.assertLess(time.monotonic() - t, limit + 4)

    def test_hang_with_its_own_sigalrm_handler(self):
        self._assert_times_out(self.gate("""
            import signal, time
            signal.signal(signal.SIGALRM, lambda *a: None)
            time.sleep(8)
        """))

    def test_hang_after_alarm_zero(self):
        self._assert_times_out(self.gate("""
            import signal, time
            signal.alarm(0)
            time.sleep(8)
        """))

    def test_grandchild_holding_stdout(self):
        # subprocess.run reads to EOF, so a grandchild that keeps the write
        # end open is a leg still running, and it times out.
        script = self.gate("""
            import os, time
            if os.fork() == 0:
                time.sleep(6)
                os._exit(0)
            print("done")
        """)
        self._assert_times_out(script)

    def test_grandchild_in_the_group_with_stdout_closed(self):
        # Stricter than subprocess.run on purpose: a leg is finished only
        # when nothing it started is still alive.
        script = self.gate("""
            import os, sys, time
            if os.fork() == 0:
                os.close(1); os.close(2)
                time.sleep(6)
                os._exit(0)
        """)
        self._assert_times_out(script)


@unittest.skipUnless(LINUX, "the fork path exists on Linux only")
class Parity(_Base):
    def assertParity(self, body, want_rc=None):
        fork, spawn = self.both(self.gate(body))
        self.assertEqual(fork, spawn)
        if want_rc is not None:
            self.assertEqual(fork[0], want_rc)
        return fork

    def test_deny_printed_from_a_non_daemon_thread(self):
        rc, out = self.assertParity("""
            import threading, time
            def late():
                time.sleep(0.2)
                print(%r)
            threading.Thread(target=late).start()
        """ % DENY, want_rc=0)
        self.assertTrue(gate_selftest.emits_block(rc, out))

    def test_exit_minus_one_is_255(self):
        self.assertParity("import sys\nsys.exit(-1)\n", want_rc=255)

    def test_keyboard_interrupt_is_killed_by_sigint(self):
        self.assertParity("raise KeyboardInterrupt\n", want_rc=-2)

    def test_deny_then_stdout_close(self):
        rc, out = self.assertParity("""
            import sys
            print(%r)
            sys.stdout.close()
        """ % DENY, want_rc=0)
        self.assertTrue(gate_selftest.emits_block(rc, out))

    def test_uncaught_exception_is_one(self):
        self.assertParity("raise RuntimeError('x')\n", want_rc=1)

    def test_real_gate_fixture_legs(self):
        # Regression guard rather than a reproduction: the real arming-surface
        # gate on one violation and one benign fixture, through both paths.
        gate = str(SCRIPTS / "g__pretool__arming-surface.py")
        import importlib.util
        spec = importlib.util.spec_from_file_location("arming_for_test", gate)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        fdir = SCRIPTS.parent / "registry" / "fixtures" / "ARCHITECTURE.arming-surface"
        for name, blocks in (("violation_settings_write.json", True),
                             ("benign_settings_write.json", False)):
            path = fdir / name
            payload = json.loads(path.read_text(encoding="utf-8"))
            setup = payload.pop("_setup", {}) or {}
            seen = []
            saved = gate_selftest._FORK_OK
            try:
                for fork in (True, False):
                    gate_selftest._FORK_OK = fork
                    sb = tempfile.mkdtemp(prefix="arming-selftest-")
                    try:
                        mod._build_sandbox(sb, setup)
                        r = gate_selftest.run_scripts([{
                            "script": gate, "input": mod._leg_body(payload, setup, sb),
                            "cwd": sb, "env": mod._leg_env(sb), "timeout": 30}])[0]
                        seen.append((r.returncode, r.stdout.replace(sb, "<SB>")))
                    finally:
                        shutil.rmtree(sb, ignore_errors=True)
            finally:
                gate_selftest._FORK_OK = saved
            self.assertEqual(seen[0], seen[1], name)
            self.assertEqual(gate_selftest.emits_block(*seen[0]), blocks, name)


@unittest.skipUnless(LINUX, "the fork path exists on Linux only")
class OwnChildrenOnly(_Base):
    def test_does_not_reap_another_popen(self):
        other = subprocess.Popen([sys.executable, "-c",
                                  "import sys, time; time.sleep(0.3); sys.exit(7)"])
        try:
            gate_selftest.run_scripts([self.leg(self.gate(
                "import time\ntime.sleep(1.0)\n"))])
        finally:
            rc = other.wait(timeout=10)
        self.assertEqual(rc, 7)


_USER_SITE_DRIVER = r"""
import json, os, site, sys
sys.path.insert(0, sys.argv[1])
import gate_selftest
try:
    import onlyuser_pkg_for_test  # proves THIS process sees its user site
except ImportError:
    print(json.dumps({"skip": "no user site in this interpreter"})); sys.exit(0)
env = dict(os.environ); env["HOME"] = sys.argv[3]
leg = {"script": sys.argv[2], "input": "{}", "cwd": sys.argv[3], "env": env,
       "timeout": 30}
out = {}
for fork in (True, False):
    gate_selftest._FORK_OK = fork
    r = gate_selftest.run_scripts([leg])[0]
    out["fork" if fork else "spawn"] = [r.returncode, r.stdout]
print(json.dumps(out))
"""


@unittest.skipUnless(LINUX, "the fork path exists on Linux only")
class UserSite(_Base):
    def test_leg_home_decides_the_user_site(self):
        # The selftest's own HOME has a user site holding a package; the leg's
        # HOME has none. A fresh interpreter under the leg's env cannot import
        # it, so a gate whose deny depends on that import must ALLOW.
        home_a = os.path.join(self.tmp, "home_a")
        home_b = os.path.join(self.tmp, "home_b")
        os.makedirs(home_b)
        ver = "python%d.%d" % sys.version_info[:2]
        site_a = os.path.join(home_a, ".local", "lib", ver, "site-packages")
        os.makedirs(site_a)
        with open(os.path.join(site_a, "onlyuser_pkg_for_test.py"), "w") as fh:
            fh.write("X = 1\n")
        gate = self.gate("""
            try:
                import onlyuser_pkg_for_test
                print(%r)
            except ImportError:
                pass
        """ % DENY)
        driver = os.path.join(self.tmp, "driver.py")
        with open(driver, "w") as fh:
            fh.write(_USER_SITE_DRIVER)
        env = {k: v for k, v in os.environ.items()
               if k not in ("PYTHONUSERBASE", "PYTHONNOUSERSITE", "PYTHONPATH")}
        env["HOME"] = home_a
        cp = subprocess.run([sys.executable, driver, str(SCRIPTS), gate, home_b],
                            capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        got = json.loads(cp.stdout.strip().splitlines()[-1])
        if "skip" in got:
            self.skipTest(got["skip"] + " (a venv disables it)")
        self.assertEqual(got["spawn"], [0, ""])
        self.assertEqual(got["fork"], got["spawn"])


if __name__ == "__main__":
    unittest.main()
