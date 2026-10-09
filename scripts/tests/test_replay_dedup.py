#!/usr/bin/env python3
"""Two follow-ups of the stateful Stop-gate replay, on the synthetic corpus of
test_replay_stateful (kept in its own file so that module stays untouched):

  - a forked or resumed session file copies its parent's records, uuids
    included, so the same Stop sits in two captured files; the stateful
    session counts take it once;
  - `replay` prints how many cases each method decided (stateful,
    isolated-fallback, isolated), in the text and in the --json output.

All transcript content is synthetic. Timing is never asserted.
"""
from __future__ import annotations

import argparse
import io
import json
import shutil
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent))
sys.path.insert(0, str(TESTS))

import replay_harness as rh  # noqa: E402
import test_replay_stateful as base  # noqa: E402


class TestStatefulDedup(unittest.TestCase):
    setUp = base.TestStatefulReplay.setUp
    tearDown = base.TestStatefulReplay.tearDown

    def _capture(self):
        with redirect_stdout(io.StringIO()):
            rh.capture_sessions(self.cdir, self.root, "2026-09-01", "2026-10-01", gates=(base.TOY,))

    def test_a_stop_copied_into_a_forked_session_file_counts_once(self):
        self._capture()
        sdir = self.cdir / "sessions"
        src = sdir / f"{rh._case_id('session', base.SID_A)}.json.gz"
        shutil.copy(src, sdir / "zz-fork-of-a.json.gz")    # same records, same uuids
        stats = {}
        rh.replay_all(self.cdir, 2, scripts=self.scripts, session_stats=stats)
        want = {"sessions": 3, "stops": 6, "historical_deny": 1, "replay_deny": 1,
                "hist_deny_reproduced": 1}
        # Only these keys: other per-Stop counters may ride in the same dict.
        self.assertEqual({k: stats[base.TOY].get(k) for k in want}, want)

    def test_replay_prints_the_count_of_each_method(self):
        self._capture()
        res = rh.replay_all(self.cdir, 2, scripts=self.scripts)
        bl = self.tmp / "baseline.json"
        bl.write_text(json.dumps({"generated": "t", "cases": {
            cid: {"g": base.TOY, "e": "Stop", "h": "allow", "d": r["d"], "c": r["c"], "l": "-"}
            for cid, r in res.items()}}), encoding="utf-8")
        args = argparse.Namespace(corpus=str(self.cdir), baseline=str(bl), jobs=2, gate="",
                                  isolated=False, json=True, allow_unlabelled_loss=True)
        real = rh.replay_all
        rh.replay_all = lambda *a, **k: real(*a, **dict(k, scripts=self.scripts))
        try:
            out = io.StringIO()
            with redirect_stdout(out):
                rh.cmd_replay(args)
            self.assertEqual(json.loads(out.getvalue())["methods"],
                             {"stateful": 2, "isolated-fallback": 0, "isolated": 0})
            args.json = False
            out = io.StringIO()
            with redirect_stdout(out):
                rh.cmd_replay(args)
            self.assertIn("method: stateful 2, isolated-fallback 0, isolated 0", out.getvalue())
        finally:
            rh.replay_all = real


if __name__ == "__main__":
    unittest.main()
