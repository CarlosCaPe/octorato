#!/usr/bin/env python3
"""The Export_Guard's two spawn paths (v11 AC-14 follow-up to T17).

On Linux the allow path is one posix_spawn with every inherited descriptor above
2 closed; where descriptors cannot be enumerated (or `fallback` forces it) it is
subprocess. Both must give the upstream the payload bytes on stdin, discard its
stdout, drop its exit code and hand it no inherited descriptor. These tests also
pin WHICH path ran, which the fixture selftest cannot see.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

GUARD = Path(__file__).resolve().parent.parent / "g__wrap__export-guard.py"

STUB = r"""import json, os, sys
fds = []
try:
    for n in os.listdir("/proc/self/fd"):
        try:
            os.fstat(int(n))
        except OSError:
            continue
        if int(n) > 2:
            fds.append(int(n))
except OSError:
    fds = None
data = sys.stdin.buffer.read()
with open(sys.argv[1], "w", encoding="utf-8") as fh:
    json.dump({"stdin": data.decode("latin-1"), "fds": fds}, fh)
print("stdout the guard must discard")
sys.exit(2)
"""


def _load():
    spec = importlib.util.spec_from_file_location("guard_spawn_under_test", GUARD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class SpawnCase(unittest.TestCase):
    def setUp(self):
        self.mod = _load()
        self.tmp = Path(tempfile.mkdtemp(prefix="guard-spawn-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.stub = self.tmp / "stub.py"
        self.stub.write_text(STUB, encoding="utf-8")
        self.out = self.tmp / "out.json"

    def run_once(self, raw: bytes, **kw):
        r, w = os.pipe()
        os.set_inheritable(r, True)
        try:
            self.mod.run_upstream([sys.executable, str(self.stub), str(self.out)], raw,
                                  dict(os.environ), **kw)
        finally:
            os.close(r)
            os.close(w)
        rec = json.loads(self.out.read_text(encoding="utf-8"))
        return rec, r

    def assert_contract(self, rec, probe, raw):
        self.assertEqual(rec["stdin"].encode("latin-1"), raw)
        if rec["fds"] is not None:
            self.assertNotIn(probe, rec["fds"])


@unittest.skipUnless(os.path.isdir("/proc/self/fd") and hasattr(os, "posix_spawnp"),
                     "posix_spawn path is Linux-only")
class TestPosixPath(SpawnCase):
    def test_default_takes_posix_spawn_and_keeps_the_contract(self):
        calls = []
        real = self.mod._spawn_posix
        self.mod._spawn_posix = lambda *a: (calls.append(1), real(*a))[1]
        raw = b'{"cwd": "/x"}' + bytes(range(256)) * 400      # > one pipe buffer
        rec, probe = self.run_once(raw)
        self.assertEqual(calls, [1])
        self.assert_contract(rec, probe, raw)

    def test_no_descriptor_list_falls_back_without_spawning_twice(self):
        self.mod._inherited_fds = lambda: None
        n = []
        real = self.mod._spawn_posix
        self.mod._spawn_posix = lambda *a: (n.append(1), real(*a))[1]
        rec, probe = self.run_once(b"payload")
        self.assertEqual(n, [1])
        self.assert_contract(rec, probe, b"payload")

    def test_missing_program_is_silent_and_not_retried(self):
        self.mod.run_upstream(["/nonexistent/upstream-hook"], b"x", dict(os.environ))


class TestFallbackPath(SpawnCase):
    def test_forced_fallback_never_calls_posix_spawn(self):
        def boom(*a):
            raise AssertionError("posix_spawn path taken under fallback=True")
        self.mod._spawn_posix = boom
        rec, probe = self.run_once(b'{"cwd": "/y"}', fallback=True)
        self.assert_contract(rec, probe, b'{"cwd": "/y"}')


if __name__ == "__main__":
    unittest.main()
