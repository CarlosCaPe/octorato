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
import os
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


PUSH_FIXTURES = ROOT / "registry" / "fixtures" / "FLOW.done-is-a-verdict"


class PushGateTest(unittest.TestCase):
    def test_push_fixture_ladder_passes(self):
        self.assertEqual(_quiet(spec_lint.selftest, PUSH_FIXTURES), 0)

    def test_push_selftest_goes_red_when_any_receipt_is_accepted(self):
        # Break the thing the gate guards: every spec reads as freshly converged.
        sys.path.insert(0, str(ROOT / "scripts"))
        import receipt_ledger
        fake = {"verdict": "CONVERGED", "ts": "2999-01-01T00:00:00+00:00"}
        with mock.patch.object(receipt_ledger, "converge_latest_for", lambda *a, **k: fake):
            self.assertEqual(_quiet(spec_lint.selftest, PUSH_FIXTURES), 1)

    def test_push_selftest_goes_red_when_freshness_is_ignored(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import receipt_ledger
        real = receipt_ledger.converge_latest_for
        def aged(*a, **k):
            r = real(*a, **k)
            return dict(r, ts="2999-01-01T00:00:00+00:00") if r else r
        with mock.patch.object(receipt_ledger, "converge_latest_for", aged):
            self.assertEqual(_quiet(spec_lint.selftest, PUSH_FIXTURES), 1)


class DoctorCheckTest(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import brain_doctor
        self.bd = brain_doctor

    def test_passes_on_this_tree(self):
        self.assertEqual(self.bd.check_spec_contract(False).status, "PASS")

    def test_fails_without_the_pre_push_stanza(self):
        with mock.patch.object(self.bd, "_rt", lambda p: "#!/bin/sh\nexit 0\n"):
            self.assertEqual(self.bd.check_spec_contract(False).status, "FAIL")

    def test_fails_on_a_broken_spec_in_the_tree(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "scripts").mkdir()
            (root / ".githooks").mkdir()
            (root / "scripts" / "spec_lint.py").write_text((ROOT / "scripts" / "spec_lint.py").read_text())
            (root / ".githooks" / "pre-push").write_text((ROOT / ".githooks" / "pre-push").read_text())
            bad = root / "docs" / "specs" / "202609300000-bad"
            bad.mkdir(parents=True)
            (bad / "feature.md").write_text((FIXTURES / "violation_not_ears" / "feature.md").read_text())
            with mock.patch.object(self.bd, "CLAUDE_DIR", root):
                self.assertEqual(self.bd.check_spec_contract(False).status, "FAIL")


class DoctorConvergedWithoutReceiptTest(unittest.TestCase):
    def test_warns_when_a_spec_says_converged_without_a_receipt(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import brain_doctor as bd
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "scripts").mkdir()
            (root / ".githooks").mkdir()
            for f in ("spec_lint.py", "receipt_ledger.py"):
                (root / "scripts" / f).write_text((ROOT / "scripts" / f).read_text())
            (root / ".githooks" / "pre-push").write_text((ROOT / ".githooks" / "pre-push").read_text())
            spec = root / "docs" / "specs" / "202609300000-done"
            spec.mkdir(parents=True)
            text = (FIXTURES / "benign_all_patterns" / "feature.md").read_text()
            (spec / "feature.md").write_text(text.replace("> **Status:** draft", "> **Status:** converged"))
            (spec / "plan.md").write_text((FIXTURES / "benign_all_patterns" / "plan.md").read_text())
            home = root / "home"
            with mock.patch.object(bd, "CLAUDE_DIR", root), \
                    mock.patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home)}):
                r = bd.check_spec_contract(False)
            self.assertEqual(r.status, "WARN", r.message)
            self.assertIn("202609300000-done", r.message)


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
