#!/usr/bin/env python3
"""`g__wrap__export-guard.py --bench` (v11 T17, AC-14), on the stub upstream.

Few runs per event: these tests pin the record's shape, its coverage of every
upstream event and the refusals, never a latency number (that depends on the
host's load and is recorded, not asserted). No network beyond 127.0.0.1.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BRAIN = Path(__file__).resolve().parent.parent.parent
GUARD = BRAIN / "scripts" / "g__wrap__export-guard.py"
OCTO_PKG = BRAIN / "scripts" / "octo_pkg.py"
UPSTREAM = BRAIN / "registry" / "fixtures" / "META.kernel-package" / "plugin-upstream"


class TestBench(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="guard-bench-")).resolve()
        cls.wrapper = cls.tmp / "wrapper"
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        cp = subprocess.run([sys.executable, str(OCTO_PKG), "wrap-plugin", str(UPSTREAM),
                             "--out", str(cls.wrapper)], env=env, capture_output=True,
                            stdin=subprocess.DEVNULL, timeout=120)
        assert cp.returncode == 0, cp.stderr

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def bench(self, plugin: Path, *extra):
        out = self.tmp / "record.json"
        cp = subprocess.run([sys.executable, str(GUARD), "--bench", str(plugin),
                             "--events", "2", "--out", str(out), *extra],
                            capture_output=True, stdin=subprocess.DEVNULL, timeout=600)
        return cp, out

    def test_record_covers_every_upstream_event(self):
        cp, out = self.bench(self.wrapper)
        self.assertIn(cp.returncode, (0, 1), cp.stderr)
        rec = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(rec, json.loads(cp.stdout))
        up = json.loads((UPSTREAM / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        self.assertEqual(set(rec["events"]), set(up["hooks"]))
        self.assertEqual(rec["upstream"], {"name": "langsmith-tracing", "version": "0.0.0-stub"})
        self.assertEqual(rec["wrapped_runs_not_finished"], 0,
                         "a wrapped run must exit 0 with no stdout whatever the upstream does")
        for ev in rec["events"].values():
            for k in ("without", "with_allow", "with_deny"):
                self.assertGreater(ev[k]["median_ms"], 0)
            self.assertEqual(ev["runs"], 2)
        self.assertIn("not measured", rec["endpoint"]["nonroutable_address"])
        self.assertNotIn(os.path.expanduser("~"), out.read_text(encoding="utf-8"))
        self.assertEqual(cp.returncode, 0 if rec["within_bound"] else 1)

    def test_mismatched_event_sets_are_refused(self):
        bad = self.tmp / "bad"
        shutil.copytree(self.wrapper, bad)
        hf = bad / "hooks" / "hooks.json"
        h = json.loads(hf.read_text(encoding="utf-8"))
        del h["hooks"]["Stop"]
        hf.write_text(json.dumps(h), encoding="utf-8")
        cp, _ = self.bench(bad)
        self.assertEqual(cp.returncode, 2)

    def test_not_a_wrapper_is_refused(self):
        cp, _ = self.bench(UPSTREAM)
        self.assertEqual(cp.returncode, 2)

    def test_quantile_is_nearest_rank(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("guard_q", GUARD)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(mod._quantile(list(range(1, 101)), 0.95), 95)
        self.assertEqual(mod._quantile([5.0], 0.95), 5.0)


if __name__ == "__main__":
    unittest.main()
