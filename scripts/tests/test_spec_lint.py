#!/usr/bin/env python3
"""Unit tests for scripts/spec_lint.py, the deterministic reader of a v9 spec.

The fixture ladder (every violation blocks for its own reason, every benign
allows) lives in `spec_lint.py --selftest registry/fixtures/FLOW.spec-contract`.
These tests cover what the ladder cannot: that the selftest itself goes red when
the linter is broken, the CLI exit codes, and the live v9 spec staying clean.
"""
from __future__ import annotations

import importlib.util
import io
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES = ROOT / "registry" / "fixtures" / "FLOW.spec-contract"

_spec = importlib.util.spec_from_file_location("spec_lint", ROOT / "scripts" / "spec_lint.py")
spec_lint = importlib.util.module_from_spec(_spec)
sys.modules["spec_lint"] = spec_lint  # dataclasses resolve the module by name
_spec.loader.exec_module(spec_lint)


def _quiet(fn, *a, **kw):
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        return fn(*a, **kw)


class SelftestTest(unittest.TestCase):
    def test_fixture_ladder_passes(self):
        self.assertEqual(_quiet(spec_lint.selftest, FIXTURES), 0)

    def test_selftest_goes_red_when_ears_check_is_disabled(self):
        # Break the thing the check guards: accept any sentence as EARS.
        with mock.patch.object(spec_lint, "_EARS", [("any", re.compile(r"^(?:.*?)(\w+)"))]):
            self.assertEqual(_quiet(spec_lint.selftest, FIXTURES), 1)

    def test_selftest_goes_red_when_coverage_check_is_disabled(self):
        with mock.patch.object(spec_lint, "lint_plan", lambda *a, **k: None):
            self.assertEqual(_quiet(spec_lint.selftest, FIXTURES), 1)

    def test_selftest_goes_red_when_marker_cap_is_raised(self):
        with mock.patch.object(spec_lint, "MAX_MARKERS", 99):
            self.assertEqual(_quiet(spec_lint.selftest, FIXTURES), 1)

    def test_selftest_goes_red_when_prose_in_criteria_is_tolerated(self):
        # A criterion demoted to prose must not silently leave coverage.
        real = spec_lint._AC_ITEM
        loose = re.compile(r"^(?:- \[[ xX]\] )?(AC-\d+): (.*)$")
        with mock.patch.object(spec_lint, "_AC_ITEM", loose):
            self.assertIsNot(spec_lint._AC_ITEM, real)
            self.assertEqual(_quiet(spec_lint.selftest, FIXTURES), 1)

    def test_selftest_refuses_an_empty_fixture_dir(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(_quiet(spec_lint.selftest, Path(d)), 1)


class EarsTest(unittest.TestCase):
    def test_each_pattern_yields_its_subject(self):
        cases = {
            "THE Exporter SHALL write UTF-8.": "Exporter",
            "WHEN a job ends, THE Exporter SHALL write.": "Exporter",
            "WHILE a job runs, THE Scheduler SHALL wait.": "Scheduler",
            "WHERE retries are on, THE Scheduler SHALL retry.": "Scheduler",
            "IF the disk is full, THEN THE Exporter SHALL NOT truncate.": "Exporter",
            "THE Report-Exporter SHALL write UTF-8.": "Report-Exporter",
        }
        for sentence, subject in cases.items():
            self.assertEqual(spec_lint._ears_subject(sentence), subject, sentence)

    def test_prose_and_lowercase_keywords_are_rejected(self):
        for sentence in ("The exporter must write UTF-8.",
                         "when a job ends, the Exporter shall write.",
                         "IF the disk is full, THE Exporter SHALL stop."):
            self.assertIsNone(spec_lint._ears_subject(sentence), sentence)


class CliTest(unittest.TestCase):
    def test_exit_codes(self):
        self.assertEqual(_quiet(spec_lint.main, [str(FIXTURES / "benign_all_patterns")]), 0)
        self.assertEqual(_quiet(spec_lint.main, [str(FIXTURES / "violation_not_ears")]), 1)
        self.assertEqual(_quiet(spec_lint.main, []), 2)

    def test_ready_flag_turns_a_marker_into_a_finding(self):
        target = str(FIXTURES / "benign_three_markers")
        self.assertEqual(_quiet(spec_lint.main, [target]), 0)
        self.assertEqual(_quiet(spec_lint.main, ["--ready", target]), 1)

    def test_missing_feature_is_a_finding(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(_quiet(spec_lint.main, [d]), 1)


class LiveSpecTest(unittest.TestCase):
    def test_every_ears_spec_in_the_repo_is_clean(self):
        checked = 0
        features = sorted((ROOT / "docs" / "specs").glob("*/feature.md")) + \
            sorted((ROOT / "docs" / "specs-archive").glob("*/feature.md"))
        for feature in features:
            rep = spec_lint.lint(feature.parent)
            if rep.skipped:
                continue
            checked += 1
            self.assertEqual(rep.findings, [], feature)
        self.assertGreaterEqual(checked, 1, "no ears-1 spec found in docs/specs or docs/specs-archive")


if __name__ == "__main__":
    unittest.main()
