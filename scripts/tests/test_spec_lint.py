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
import subprocess
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
            far = "2999-01-01T00:00:00+00:00"
            return dict(r, ts=far, verdict_ts=far) if r else r
        with mock.patch.object(receipt_ledger, "converge_latest_for", aged):
            self.assertEqual(_quiet(spec_lint.selftest, PUSH_FIXTURES), 1)

    def test_push_selftest_goes_red_when_only_the_current_lfs_url_matches(self):
        # A legacy pointer (hawser, git-media) hides a spec the same way.
        current = "version https://git-lfs.github.com/spec/"
        with mock.patch.object(spec_lint, "_is_lfs_pointer",
                               lambda b: bool(b) and b.startswith(current)):
            self.assertEqual(_quiet(spec_lint.selftest, PUSH_FIXTURES), 1)

    def test_push_selftest_goes_red_when_paths_match_by_lower_not_casefold(self):
        def by_lower(parts, i):
            pair = "/".join(parts[i:i + 2]).lower()
            return pair if pair in spec_lint.SPEC_HOMES else ""
        with mock.patch.object(spec_lint, "_home_at", by_lower):
            self.assertEqual(_quiet(spec_lint.selftest, PUSH_FIXTURES), 1)

    def test_push_selftest_goes_red_when_merge_commits_are_not_read(self):
        # The old reader: one `git diff-tree` per commit, which prints nothing for a merge.
        def per_commit(repo, before, head):
            out = set()
            revs = spec_lint._git(repo, "rev-list", f"{before}..{head}").split()
            for c in revs:
                out.update(q for q in spec_lint._git(
                    repo, "-c", "core.quotePath=false", "diff-tree", "--no-commit-id",
                    "--name-only", "-r", "-z", "--root", c).split("\0") if q)
            return out
        with mock.patch.object(spec_lint, "_changed_paths", per_commit):
            self.assertEqual(_quiet(spec_lint.selftest, PUSH_FIXTURES), 1)

    def test_push_selftest_goes_red_when_before_follows_commit_dates(self):
        # The old "before": the first parent of the last commit `git rev-list` prints.
        def by_date(repo, base, head):
            last = spec_lint._git(repo, "rev-list", f"{base}..{head}").split()[-1]
            return spec_lint._git(repo, "rev-list", "--parents", "-n", "1", last).split()[1]
        with mock.patch.object(spec_lint, "_before_rev", by_date):
            self.assertEqual(_quiet(spec_lint.selftest, PUSH_FIXTURES), 1)

    def test_push_selftest_goes_red_when_before_is_the_remote_refs_own_tip(self):
        # Against the ref's tip a spec converged on the default branch reads as this
        # branch's flip, and code pushed after a pushed flip is never checked.
        with mock.patch.object(spec_lint, "_before_rev", lambda repo, base, head: base):
            self.assertEqual(_quiet(spec_lint.selftest, PUSH_FIXTURES), 1)

    def test_push_selftest_goes_red_when_submodule_changes_can_be_ignored(self):
        def porcelain(repo, before, head):
            out = subprocess.run(["git", "-C", str(repo), "-c", "core.quotePath=false", "diff",
                                  "--name-only", "--no-renames", "-z", before, head],
                                 capture_output=True, check=True).stdout
            return {q for q in out.decode().split("\0") if q}
        with mock.patch.object(spec_lint, "_changed_paths", porcelain):
            self.assertEqual(_quiet(spec_lint.selftest, PUSH_FIXTURES), 1)

    def test_a_spec_does_not_leave_ears_by_moving(self):
        for name in ("violation_renamed_spec_leaves_ears_with_flip",
                     "violation_renamed_spec_changes_format_version_with_flip"):
            found = spec_lint._push_selftest_case(PUSH_FIXTURES / name)
            self.assertTrue(any("does not leave ears-1 by moving" in f for f in found), found)
        # the same move with the header kept is an ordinary flip at the new path
        kept = spec_lint._push_selftest_case(
            PUSH_FIXTURES / "benign_renamed_spec_flip_with_receipt_for_the_new_path")
        self.assertEqual(kept, [])

    def test_a_new_ref_is_compared_with_the_default_remote_branch(self):
        case = PUSH_FIXTURES / "violation_flip_no_receipt"
        sd = "docs/specs/202609300000-toy"
        with tempfile.TemporaryDirectory() as tmp:
            repo, home = Path(tmp) / "repo", Path(tmp) / "home"
            home.mkdir()
            env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                       GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")

            def git(*a):
                return subprocess.run(["git", "-C", str(repo), *a], check=True, env=env,
                                      capture_output=True, text=True).stdout.strip()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            (repo / sd).mkdir(parents=True)
            feature = (case / "feature.md").read_text()
            (repo / sd / "feature.md").write_text(feature)
            (repo / sd / "plan.md").write_text((case / "plan.md").read_text())
            git("add", "-A"); git("commit", "-qm", "base")
            base = git("rev-parse", "HEAD")
            (repo / sd / "feature.md").write_text(
                feature.replace("> **Status:** approved", "> **Status:** converged"))
            git("add", "-A"); git("commit", "-qm", "flip")
            head = git("rev-parse", "HEAD")
            with mock.patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home)}):
                # no remote-tracking ref at all: every file is new, the flip is seen
                self.assertTrue(spec_lint.push_findings(repo, spec_lint.ZERO_SHA, head))
                git("update-ref", "refs/remotes/origin/master", base)
                found = spec_lint.push_findings(repo, spec_lint.ZERO_SHA, head)
                self.assertTrue(any("holds no converge receipt" in f for f in found), found)
                # the remote already holds this head: nothing to check
                git("update-ref", "refs/remotes/origin/master", head)
                self.assertEqual(spec_lint.push_findings(repo, spec_lint.ZERO_SHA, head), [])

    def test_a_miscased_spec_blocks_while_present_and_may_be_deleted(self):
        present = spec_lint._push_selftest_case(PUSH_FIXTURES / "violation_spec_path_miscased")
        self.assertTrue(any("in lower case" in f for f in present), present)
        gone = spec_lint._push_selftest_case(PUSH_FIXTURES / "benign_miscased_spec_deleted_in_push")
        self.assertEqual(gone, [])

    def test_lfs_pointer_shapes(self):
        oid = "oid sha256:" + "0" * 64 + "\nsize 12\n"
        for url in ("https://git-lfs.github.com/spec/v1", "https://hawser.github.com/spec/v1",
                    "http://git-media.io/v/2"):
            self.assertTrue(spec_lint._is_lfs_pointer(f"version {url}\n{oid}"), url)
        self.assertTrue(spec_lint._is_lfs_pointer(
            "version https://git-lfs.github.com/spec/v1\next-0-foo sha256:" + "1" * 64 + "\n" + oid))
        for not_pointer in (None, "", "# Feature: x\n\n> **Status:** draft\n",
                            "version 2 of this spec\n\noid sha256: see below\n"):
            self.assertFalse(spec_lint._is_lfs_pointer(not_pointer), not_pointer)


class DoctorCheckTest(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import brain_doctor
        self.bd = brain_doctor

    def test_never_fails_on_this_tree(self):
        # WARN is legitimate here: once a spec in the tree says converged, a machine
        # that did not run its converge pass holds no receipt for it. Requiring PASS
        # would fail the suite, and so every push, on that machine.
        self.assertNotEqual(self.bd.check_spec_contract(False).status, "FAIL")

    def test_fails_without_the_pre_push_stanza(self):
        with mock.patch.object(self.bd, "_rt", lambda p: "#!/bin/sh\nexit 0\n"):
            self.assertEqual(self.bd.check_spec_contract(False).status, "FAIL")

    def test_fails_when_the_stanza_ignores_the_exit_code(self):
        real = (ROOT / ".githooks" / "pre-push").read_text()
        for broken in (real.replace('>/dev/null 2>&1; then', '>/dev/null 2>&1 || true; then'),
                       real.replace("      echo \"  Fix the spec, or run /sdd-converge", "      :\n      echo \"  Fix the spec, or run /sdd-converge")
                           .replace("    } >&2\n    exit 1\n  fi\ndone", "    } >&2\n  fi\ndone")):
            self.assertNotEqual(broken, real)
            with mock.patch.object(self.bd, "_rt", lambda p, b=broken: b):
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


class HeaderTest(unittest.TestCase):
    def test_every_header_shape_reads_as_a_header(self):
        base = (FIXTURES / "benign_all_patterns" / "feature.md").read_text()
        for line in ("> **Status**: converged", "- **Status:** converged", "_Status:_ converged",
                     "| Status | converged |", "> **STATUS:** CONVERGED"):
            text = base.replace("> **Status:** draft", line)
            self.assertEqual(spec_lint.spec_status(text), "?", line)
        self.assertEqual(spec_lint.spec_status(base.replace("draft", "converged", 1)), "converged")

    def test_only_directories_under_the_spec_homes_are_specs(self):
        for yes in ("docs/specs/202609300000-a", "docs/specs-archive/old",
                    "arm/docs/specs/202609300000-a"):
            self.assertTrue(spec_lint.is_spec_dir(yes), yes)
        for no in ("registry/fixtures/FLOW.spec-contract/violation_not_ears", "docs/specs",
                   "docs/specs/a/b", "templates/spec", "feature"):
            self.assertFalse(spec_lint.is_spec_dir(no), no)

    def test_spec_paths_match_any_case_but_only_lower_case_is_canonical(self):
        for p in ("Docs/specs/202609300000-a", "DOCS/SPECS/202609300000-a", "docs/Specs/202609300000-a"):
            self.assertTrue(spec_lint.is_spec_dir(p), p)
        self.assertTrue(spec_lint.is_canonical_spec_path("docs/specs/202609300000-a/feature.md"))
        for p in ("Docs/specs/202609300000-a/feature.md", "docs/specs/202609300000-a/Feature.md",
                  "docs/SPECS-ARCHIVE/old/plan.md"):
            self.assertFalse(spec_lint.is_canonical_spec_path(p), p)

    def test_spec_paths_match_by_casefold(self):
        # `ſ` (long s) folds to `s`; lower() leaves it, so lower() missed this spelling.
        long_s = "doc\u017f/specs/202609300000-a"
        self.assertTrue(spec_lint.is_spec_dir(long_s))
        self.assertFalse(spec_lint.is_canonical_spec_path(long_s + "/feature.md"))
        self.assertTrue(spec_lint._on_spec_path("doc\u017f"))

    def test_only_ears_1_declares_the_format(self):
        # AC-16: a file that names another version does not declare ears-1 and is skipped.
        for version in ("ears-2", "ears-10", "ears-1a"):
            self.assertFalse(spec_lint.is_ears(f"# F\n\n> **Spec-Format:** {version}\n"), version)
        self.assertTrue(spec_lint.is_ears("# F\n\n> **Spec-Format:** ears-1\n"))
        self.assertTrue(spec_lint.is_ears("# F\n\n**Spec-Format**: EARS-1\n"))

    def test_prose_mention_is_not_a_header(self):
        self.assertFalse(spec_lint.is_ears("# F\n\nThis spec does not use Spec-Format: ears-1 yet.\n"))


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
