#!/usr/bin/env python3
"""v10 T07 (AC-11, AC-22): budget-check answers from a spend cache.

The PreToolUse check reads a cache that SessionStart and each finished spawn
refresh. A cache older than 15 minutes, from another month, stamped in the
future or unreadable is never used: the check recomputes synchronously and the
hard_stop decision is unchanged.

Stdlib only:  python3 -m unittest scripts.tests.test_budget_cache
"""
from __future__ import annotations

import datetime as _dt
import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("budget_check", SCRIPTS / "budget-check.py")
bc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bc)


class BudgetCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="budget-cache-")
        self.env = mock.patch.dict(os.environ, {"HOME": self.tmp, "USERPROFILE": self.tmp})
        self.env.start()
        cfg = Path(self.tmp) / "budgets.json"
        cfg.write_text(json.dumps({"budgets": [{"arm": "hot", "monthly_usd_cap": 10.0,
                                                "action_on_breach": "hard_stop", "grace_pct": 100}]}))
        self.paths = [mock.patch.object(bc, "BUDGETS_YAML", Path(self.tmp) / "none.yaml"),
                      mock.patch.object(bc, "BUDGETS_JSON", cfg)]
        for p in self.paths:
            p.start()
        self.runs = 0

    def tearDown(self):
        for p in self.paths:
            p.stop()
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def profiler(self, spend):
        def fake():
            self.runs += 1
            return spend
        return mock.patch.object(bc, "_profiler_spend", fake)

    def write(self, spend, age_s=0, month=None):
        now = _dt.datetime.now().timestamp()
        bc._write_cache(spend, now - age_s)
        if month:
            data = json.loads(bc.cache_path().read_text())
            data["month"] = month
            bc.cache_path().write_text(json.dumps(data))

    def test_a_fresh_cache_answers_without_the_profiler(self):
        self.write({"hot": 50.0}, age_s=60)
        with self.profiler({"hot": 0.0}):
            v = bc.evaluate()
        self.assertEqual((v["status"], self.runs), ("HARD_STOP", 0))

    def test_a_cache_older_than_15_minutes_is_recomputed_synchronously(self):
        self.write({"hot": 0.0}, age_s=bc.CACHE_MAX_AGE_S + 5)
        with self.profiler({"hot": 50.0}):
            v = bc.evaluate()
        self.assertEqual((v["status"], self.runs), ("HARD_STOP", 1))
        self.assertEqual(bc._read_cache(), {"hot": 50.0})       # rewritten

    def test_a_future_or_other_month_or_torn_cache_is_not_trusted(self):
        for setup in (lambda: self.write({"hot": 0.0}, age_s=-3600),
                      lambda: self.write({"hot": 0.0}, month="1999-01"),
                      lambda: bc.cache_path().write_text("{not json")):
            setup()
            self.runs = 0
            with self.profiler({"hot": 50.0}):
                self.assertEqual(bc.evaluate()["status"], "HARD_STOP")
            self.assertEqual(self.runs, 1)

    def test_no_applicable_cap_skips_the_spend_entirely(self):
        bc.BUDGETS_JSON.write_text(json.dumps({"arms": [{"name": "x"}],
                                               "budgets": [{"arm": "a", "monthly_usd_cap": 0}]}))
        with self.profiler({"a": 1e9}):
            self.assertEqual(bc.evaluate()["status"], "OK")
            self.assertEqual(bc._refresh_main(False), 0)
        self.assertEqual(self.runs, 0)
        bc.BUDGETS_JSON.write_text(json.dumps({"default": {"monthly_usd_cap": 1.0,
                                                           "action_on_breach": "hard_stop", "grace_pct": 100}}))
        with self.profiler({"anyarm": 5.0}):
            self.assertEqual(bc.evaluate()["status"], "HARD_STOP")   # the default cap still applies
        self.assertEqual(self.runs, 1)

    def test_a_failed_profiler_run_is_not_cached(self):
        with self.profiler(None):
            self.assertEqual(bc.evaluate()["status"], "OK")       # unchanged fail-open on no data
        self.assertFalse(bc.cache_path().exists())

    def test_refresh_is_skipped_when_spend_comes_from_a_file(self):
        bc.BUDGETS_JSON.write_text(json.dumps({"spend_json": "~/s.json", "budgets": []}))
        with self.profiler({"hot": 1.0}):
            self.assertEqual(bc._refresh_main(False), 0)
        self.assertEqual(self.runs, 0)

    def test_refresh_writes_the_cache_and_background_detaches(self):
        with self.profiler({"hot": 3.0}):
            self.assertEqual(bc._refresh_main(False), 0)
        self.assertEqual(bc._read_cache(), {"hot": 3.0})
        with mock.patch.object(bc.subprocess, "Popen") as popen:
            self.assertEqual(bc._refresh_main(True), 0)
        args, kwargs = popen.call_args
        self.assertIn("--refresh", args[0])
        self.assertNotIn("--background", args[0])
        self.assertTrue(kwargs.get("start_new_session"))


if __name__ == "__main__":
    unittest.main()
