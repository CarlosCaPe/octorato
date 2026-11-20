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
import random
import re
import subprocess
import sys
import tempfile
import time
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

    def test_a_spec_does_not_leave_the_gate_by_moving(self):
        # One level deeper or outside the spec homes a feature.md is not a spec the
        # gate reads; moved there with its header kept, the flip passed unseen.
        for name in ("violation_spec_moved_one_level_deeper_with_flip",
                     "violation_spec_moved_one_level_deeper_without_header",
                     "violation_spec_moved_outside_the_spec_homes_with_flip"):
            found = spec_lint._push_selftest_case(PUSH_FIXTURES / name)
            self.assertTrue(any("outside a spec directory" in f for f in found), found)
        # the same file added while the spec stays where it is: a copy, not a move
        copied = spec_lint._push_selftest_case(
            PUSH_FIXTURES / "benign_feature_copied_outside_the_spec_homes_while_the_spec_stays")
        self.assertEqual(copied, [])

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


RUN_FIXTURES = ROOT / "registry" / "fixtures" / "FLOW.build-loop-excellence"


class RunEvidenceTest(unittest.TestCase):
    """FLOW.build-loop-excellence: a spec converges only with a run receipt, and the
    receipts live in run-evidence.txt, a plain-text file with one reading."""

    LINE = "RUN-01 [AC-01] `tool --flag`: exit 0, wrote out.csv"

    def _red_without(self, message: str) -> None:
        """Drop one kind of finding from the reader and require the ladder to go red."""
        real = spec_lint.run_evidence

        def blind(data, criteria=None):
            receipts, findings = real(data, criteria)
            return receipts, [f for f in findings if message not in f[1]]
        with mock.patch.object(spec_lint, "run_evidence", blind):
            self.assertEqual(_quiet(spec_lint.selftest, RUN_FIXTURES), 1, message)

    def test_run_fixture_ladder_passes(self):
        self.assertEqual(_quiet(spec_lint.selftest, RUN_FIXTURES), 0)

    def test_selftest_goes_red_when_any_spec_counts_as_run(self):
        # Break the thing the gate guards: every flip reads as carrying a receipt.
        with mock.patch.object(spec_lint, "run_receipts", lambda data, criteria=None: ["RUN-01"]):
            self.assertEqual(_quiet(spec_lint.selftest, RUN_FIXTURES), 1)

    def test_selftest_goes_red_when_a_missing_file_is_let_through(self):
        with mock.patch.object(spec_lint, "_show_bytes", lambda repo, rev, path: b"RUN-01 [AC-01] `x y`: ok\n"):
            self.assertEqual(_quiet(spec_lint.selftest, RUN_FIXTURES), 1)

    def test_selftest_goes_red_when_a_converged_spec_may_drop_its_receipts(self):
        with mock.patch.object(spec_lint, "_needs_evidence", lambda flip, had, has: flip):
            self.assertEqual(_quiet(spec_lint.selftest, RUN_FIXTURES), 1)

    def test_selftest_goes_red_when_the_file_is_not_linted(self):
        with mock.patch.object(spec_lint, "_lint_run_evidence", lambda *a, **k: None):
            self.assertEqual(_quiet(spec_lint.selftest, RUN_FIXTURES), 1)

    def test_selftest_goes_red_when_a_file_with_a_finding_still_counts(self):
        # "No receipt counts while the file has one finding."
        def lenient(data, criteria=None):
            return [rid for _i, rid, _acs in spec_lint.run_evidence(data, criteria)[0]]
        with mock.patch.object(spec_lint, "run_receipts", lenient):
            self.assertEqual(_quiet(spec_lint.selftest, RUN_FIXTURES), 1)

    def test_selftest_goes_red_when_one_kind_of_finding_is_dropped(self):
        for message in ("line is neither blank, a `#` comment nor a run receipt",
                        "run receipt does not follow",
                        "is an unfilled template",
                        "holds the character",
                        "not valid UTF-8",
                        "references unknown criterion",
                        "duplicates line"):
            with self.subTest(message):
                self._red_without(message)

    def test_selftest_goes_red_when_a_change_to_the_file_alone_is_not_gated(self):
        with mock.patch.object(spec_lint, "SPEC_FILES", ("feature.md", "plan.md")):
            self.assertEqual(_quiet(spec_lint.selftest, RUN_FIXTURES), 1)

    def test_selftest_goes_red_when_a_markdown_section_is_tolerated(self):
        with mock.patch.object(spec_lint, "_names_run_evidence", lambda line: False):
            self.assertEqual(_quiet(spec_lint.selftest, RUN_FIXTURES), 1)

    def test_selftest_goes_red_when_unsafe_characters_are_let_through(self):
        with mock.patch.object(spec_lint, "_UNSAFE", re.compile(r"(?!)")):
            self.assertEqual(_quiet(spec_lint.selftest, RUN_FIXTURES), 1)

    def test_selftest_goes_red_when_ids_take_any_unicode_digit(self):
        # `\d` also matches the digits of other scripts: two ids that look alike
        # would be two ids, and a criterion could be named in digits nobody can type.
        with mock.patch.object(spec_lint, "_RUN_ID", re.compile(r"(RUN-\d{2,}) \[")):
            self.assertEqual(_quiet(spec_lint.selftest, RUN_FIXTURES), 1)
        with mock.patch.object(spec_lint, "_AC_REF", re.compile(r"AC-\d+")):
            self.assertEqual(_quiet(spec_lint.selftest, RUN_FIXTURES), 1)

    def test_selftest_goes_red_when_a_placeholder_counts_as_a_receipt(self):
        # The grammar the gate prints must not satisfy the gate.
        with mock.patch.object(spec_lint, "_is_placeholder", lambda value: False):
            self.assertEqual(_quiet(spec_lint.selftest, RUN_FIXTURES), 1)

    def test_selftest_goes_red_when_a_placeholder_is_matched_by_its_first_word(self):
        # Convergence 2, T19: `todo add milk` is a command, not a template.
        real = spec_lint._is_placeholder
        words = ("todo", "tbd", "fixme", "pending", "placeholder")

        def by_prefix(value):
            return real(value) or value.strip().casefold().startswith(words)
        with mock.patch.object(spec_lint, "_is_placeholder", by_prefix):
            self.assertEqual(_quiet(spec_lint.selftest, RUN_FIXTURES), 1)

    def test_selftest_goes_red_when_wrapping_is_not_stripped(self):
        # Convergence 2, T20: `TODO.`, `[TODO]`, `<what was executed>.`
        with mock.patch.object(spec_lint, "_WRAPPING", " "):
            self.assertEqual(_quiet(spec_lint.selftest, RUN_FIXTURES), 1)

    def test_what_counts_as_a_receipt(self):
        line = self.LINE
        two = line.replace("RUN-01", "RUN-02")
        cases = {
            "one receipt": (line + "\n", ["RUN-01"]),
            "no final line feed": (line, ["RUN-01"]),
            "two receipts, blank lines between": (f"{line}\n\n\n{two}\n", ["RUN-01", "RUN-02"]),
            "comment lines": (f"# runs\n#\n## looks like a heading\n{line}\n# end\n", ["RUN-01"]),
            "trailing spaces": (f"{line}   \n", ["RUN-01"]),
            "a line of spaces": (f"   \n{line}\n", ["RUN-01"]),
            "crlf line ends": (f"# runs\r\n{line}\r\n{two}\r\n", ["RUN-01", "RUN-02"]),
            "angle-bracket argument": ("RUN-01 [AC-01] `tool --repo <tmp>`: exit 0\n", ["RUN-01"]),
            "markup that means nothing here": ("RUN-01 [AC-01] `tool`: prints <!-- <script> ``` and exits 0\n", ["RUN-01"]),
            "non-ASCII observation": ("RUN-01 [AC-01] `tool`: escribió 3 filas, 日本語\n", ["RUN-01"]),
            "no-break space in an observation": ("RUN-01 [AC-01] `tool`: 3\u00a0rows\n", ["RUN-01"]),
            "long id": (line.replace("RUN-01", "RUN-0123"), ["RUN-0123"]),
            # everything below is refused, and one refused line empties the file
            "empty file": ("", []),
            "comments only": ("# nothing yet\n", []),
            "prose line": (f"{line}\nRan on a clean checkout.\n", []),
            "markdown bullet": ("- " + line, []),
            "starred bullet": ("* " + line, []),
            "numbered": ("1. " + line, []),
            "checkbox": ("- [x] " + line, []),
            "quoted": ("> " + line, []),
            "indented receipt": ("  " + line, []),
            "indented comment": (f" # runs\n{line}\n", []),
            "fence line": (f"```\n{line}\n```\n", []),
            "html comment line": (f"<!-- note -->\n{line}\n", []),
            "lower-case id": (line.replace("RUN", "run"), []),
            "one-digit id": (line.replace("RUN-01", "RUN-1"), []),
            "arabic-indic digits in the id": (line.replace("RUN-01", "RUN-\u0660\u0661"), []),
            "fullwidth digits in the id": (line.replace("RUN-01", "RUN-\uff10\uff11"), []),
            "arabic-indic digits in a criterion": (line.replace("AC-01", "AC-\u0660\u0661"), []),
            "no-break space after the id": (line.replace("RUN-01 ", "RUN-01\u00a0"), []),
            "two spaces after the id": (line.replace("RUN-01 ", "RUN-01  "), []),
            "criteria joined by a bare comma": (line.replace("[AC-01]", "[AC-01,AC-02]"), []),
            "empty criteria": (line.replace("[AC-01]", "[]"), []),
            "no observation": ("RUN-01 [AC-01] `tool`: ", []),
            "no command": ("RUN-01 [AC-01] ``: exit 0", []),
            "no code span": ("RUN-01 [AC-01] tool: exit 0", []),
            "observation on the next line": ("RUN-01 [AC-01] `tool`:\nexit 0\n", []),
            "duplicate id": (f"{line}\n{line}\n", []),
            "template": ("RUN-01 [AC-01] `<what was executed>`: <what was observed>", []),
            "tab in a command": (line.replace("tool --flag", "tool\t--flag"), []),
            "tab-indented receipt": ("\t" + line, []),
            "form feed line break": (f"x\x0c{line}\n", []),
            "form feed in a comment": (f"# a\x0cb\n{line}\n", []),
            "vertical tab": (f"{line}\n\x0b\n", []),
            "file separator": (f"{line}\x1c{two}\n", []),
            "group separator": (f"{line}\x1d{two}\n", []),
            "record separator": (f"{line}\x1e{two}\n", []),
            "unit separator": (f"{line}\x1f\n", []),
            "next line character": (f"{line}\u0085{two}\n", []),
            "line separator": (f"{line}\u2028{two}\n", []),
            "paragraph separator": (f"{line}\u2029{two}\n", []),
            "nul": (f"{line}\x00\n", []),
            "escape": (f"{line}\x1b[2K\n", []),
            "delete": (f"{line}\x7f\n", []),
            "lone carriage return": (f"# hidden\r{line}\n", []),
            "two carriage returns before the line feed": (f"{line}\r\r\n", []),
            "zero-width space": (line.replace("RUN-01", "RUN-\u200b01"), []),
            "zero-width joiner in an observation": (f"{line}\u200d\n", []),
            "soft hyphen": (f"{line}\u00ad\n", []),
            "right-to-left override": (f"{line}\u202e\n", []),
            "isolate": (f"{line}\u2066\n", []),
            "byte-order mark": (f"\ufeff{line}\n", []),
            "tag character": (f"{line}\U000e0041\n", []),
            "no file": (None, []),
        }
        for name, (text, want) in cases.items():
            with self.subTest(name):
                data = None if text is None else text.encode("utf-8")
                self.assertEqual(spec_lint.run_receipts(data), want)
        for name, data in {"latin-1 byte": self.LINE.encode() + b"\n# caf\xe9\n",
                           "utf-16": ("\ufeff" + self.LINE).encode("utf-16"),
                           "lone surrogate": self.LINE.encode() + b"\n# \xed\xa0\x80\n",
                           "overlong slash": self.LINE.encode() + b"\n# \xc0\xaf\n"}.items():
            with self.subTest(name):
                self.assertEqual(spec_lint.run_receipts(data), [])
                self.assertEqual(spec_lint.run_evidence(data)[1][0][1], "not valid UTF-8")

    def test_lines_break_at_line_feeds_only(self):
        # str.splitlines() also breaks at eleven other characters; the reader must not.
        for ch in "\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029\r":
            with self.subTest(f"U+{ord(ch):04X}"):
                data = f"# a{ch}{self.LINE}\n".encode("utf-8")
                receipts, findings = spec_lint.run_evidence(data)
                self.assertEqual(receipts, [])  # never a new line that holds a receipt
                self.assertEqual([i for i, _m in findings], [1])
                self.assertIn(f"U+{ord(ch):04X}", findings[0][1])
        # a carriage return is dropped only right before the line feed
        self.assertEqual(spec_lint.run_evidence(f"{self.LINE}\r\n".encode()), ([(1, "RUN-01", ["AC-01"])], []))

    def test_criteria_must_exist_when_they_are_known(self):
        data = (self.LINE + "\n").encode()
        self.assertEqual(spec_lint.run_receipts(data, {"AC-01"}), ["RUN-01"])
        self.assertEqual(spec_lint.run_receipts(data, {"AC-02"}), [])
        self.assertEqual(spec_lint.run_receipts(data, set()), [])
        self.assertIn("references unknown criterion AC-01", spec_lint.run_evidence(data, set())[1][0][1])

    def test_a_placeholder_is_the_whole_value(self):
        wraps = ("{}", "{}.", "[{}]", "({})", "<{}>", "**{}**", "_{}_", '"{}"', "{}...", "  {} ", "{}!")
        for word in sorted(spec_lint.PLACEHOLDERS - {""}):
            for wrap in wraps:
                for value in (wrap.format(word), wrap.format(word.upper()), wrap.format(word.title())):
                    with self.subTest(value):
                        self.assertTrue(spec_lint._is_placeholder(value))
        for value in ("", " ", "_", "**", "``", "...", "…", "---", "???", "xx", "XXX", "xxxx.",
                      "<>", "<cmd>", "<cmd> <args>", "<what was executed>.", "what was executed.",
                      "< a > < b >.", "[ ]", "()"):
            with self.subTest(value):
                self.assertTrue(spec_lint._is_placeholder(value))
        # A value that merely STARTS with a placeholder word, or holds one, is real.
        honest = ["todo add milk", "tbd-cli sync", "fixme-scan src/", "pending-jobs --count",
                  "placeholder-gen --out x", "pending migrations 0, exit 0", "none of the 3 rows changed",
                  "n/a for 2 of 5 rows, exit 0", "command not found, exit 127", "x", "0", "ok",
                  "exit 0", "tool --repo <tmp>", "xargs -n1 echo", "xxd file", "TODO list printed"]
        for value in honest:
            with self.subTest(value):
                self.assertFalse(spec_lint._is_placeholder(value))
        for word in ("todo", "tbd", "fixme", "pending", "placeholder", "none", "n/a"):
            with self.subTest(f"{word} + more"):
                self.assertFalse(spec_lint._is_placeholder(f"{word} and 3 rows written"))

    FEATURE = ("# Feature\n\n> **Status:** draft\n> **Spec-Format:** ears-1\n\n"
               "## Glossary\n\n- **Exporter**: writes.\n\n## Acceptance Criteria\n\n"
               "- [ ] AC-01: THE Exporter SHALL write UTF-8.\n")

    def _findings(self, evidence=None, feature_tail: str = "") -> str:
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "feature.md").write_text(self.FEATURE + feature_tail, encoding="utf-8", newline="")
            if evidence is not None:
                data = evidence if isinstance(evidence, bytes) else evidence.encode("utf-8")
                (Path(d) / "run-evidence.txt").write_bytes(data)
            return "\n".join(spec_lint.lint(Path(d)).findings)

    def test_lint_names_each_refused_line(self):
        good = self.LINE + "\n"
        self.assertEqual(self._findings(), "")  # the file is optional until the flip
        self.assertEqual(self._findings("# runs\n\n" + good), "")
        only = "run-evidence.txt:2: line is neither blank, a `#` comment nor a run receipt"
        shape = "run-evidence.txt:2: run receipt does not follow `RUN-## [AC-##] `<what was executed>`: <what was observed>`"
        for name, second, want in (
            ("prose", "Ran on a clean checkout.", only),
            ("fence", "```", only),
            ("indented comment", " # note", only),
            ("markdown bullet", "- RUN-02 [AC-01] `tool`: ok", shape),
            ("numbered", "1. RUN-02 [AC-01] `tool`: ok", shape),
            ("lower case id", "run-02 [AC-01] `tool`: ok", shape),
            ("one digit", "RUN-2 [AC-01] `tool`: ok", shape),
            ("non-ASCII digits", "RUN-\u0660\u0662 [AC-01] `tool`: ok", shape),
            ("template", "RUN-02 [AC-01] `<what was executed>`: <what was observed>",
             "run-evidence.txt:2: RUN-02 is an unfilled template"),
            ("template with a full stop", "RUN-02 [AC-01] `what was executed.`: what was observed.",
             "run-evidence.txt:2: RUN-02 is an unfilled template"),
            ("duplicate id", good.rstrip(), "run-evidence.txt:2: RUN-01 duplicates line 1"),
            ("unknown criterion", "RUN-02 [AC-77] `tool`: ran",
             "run-evidence.txt:2: RUN-02 references unknown criterion AC-77"),
            ("form feed", "RUN-02 [AC-01] `tool`: ok\x0c", "run-evidence.txt:2: holds the character U+000C"),
            ("line separator", "RUN-02 [AC-01] `tool`: ok\u2028x", "run-evidence.txt:2: holds the character U+2028"),
            ("tab", "RUN-02 [AC-01] `a\tb`: ok", "run-evidence.txt:2: holds the character U+0009"),
        ):
            with self.subTest(name):
                self.assertIn(want, self._findings(good + second + "\n"))
        self.assertIn("run-evidence.txt:2: not valid UTF-8", self._findings(good.encode() + b"\xff\n"))
        moved = "run evidence lives in `run-evidence.txt`"
        for name, tail in (("the old section", "\n## Run evidence\n\n- " + good),
                           ("miscased", "\n## RUN EVIDENCE\n"), ("deeper", "\n### Run evidence\n"),
                           ("a tail", "\n## Run evidence (final)\n"), ("indented", "\n ## Run evidence\n"),
                           ("setext", "\nRun evidence\n============\n"), ("bold", "\n**Run evidence**\n")):
            with self.subTest(name):
                self.assertIn(moved, self._findings(good, feature_tail=tail))
        # A sentence that mentions the words, and a heading quoted in a fence, are not headings.
        self.assertEqual(self._findings(good, feature_tail="\n## Notes\n\nThe run evidence is in the text file.\n"), "")
        self.assertEqual(self._findings(good, feature_tail="\n## Notes\n\n```\n## Run evidence\n```\n"), "")

    def test_a_directory_in_place_of_the_file_is_a_finding(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "feature.md").write_text(self.FEATURE, encoding="utf-8")
            (Path(d) / "run-evidence.txt").mkdir()
            self.assertIn("cannot be read", "\n".join(spec_lint.lint(Path(d)).findings))

    def test_a_long_line_costs_linear_time(self):
        # 200,000 characters per line, every shape that made an earlier pattern crawl.
        n = 200_000
        good = self.LINE + "\n"
        lines = {
            "hash then spaces": "#" + " " * n + "x",
            "spaces": " " * n + "x",
            "stars": "*" * n + "x",
            "quote marks": "> " * (n // 2) + "x",
            "dashes": "- " * (n // 2) + "x",
            "underscores": "_" * n + "x",
            "status then spaces": "status" + " " * n + "x",
            "status colon then spaces": "status:" + " " * n + "x",
            "spec-format then stars": "spec-format" + "*" * n + "x",
            "receipt with an open backtick": "RUN-01 [AC-01] `" + " " * n,
            "receipt with spaces before the colon": "RUN-01 [AC-01] `tool`" + " " * n + ":",
            "receipt of angle brackets": "RUN-01 [AC-01] `" + "<" * n + "`: ok",
            "receipt with a long criteria list": "RUN-01 [" + "AC-1, " * (n // 6),
            "receipt with a long id": "RUN-" + "0" * n,
            "backticks": "`" * n,
            "run ids": "RUN-" * (n // 4),
            "unclosed markers": "[NEEDS CLARIFICATION:" * (n // 21),
            "marker then spaces": "[NEEDS" + " " * n,
            "brackets": "[" * n,
            "run evidence then spaces": "## Run evidence" + " " * n + "x",
            "non-ASCII": "é" * n,
        }
        for name, line in lines.items():
            for where in ("in the evidence file", "in feature.md"):
                with self.subTest(f"{name}, {where}"):
                    began = time.perf_counter()
                    if where == "in the evidence file":
                        self._findings(good + line + "\n")
                        spec_lint.run_receipts((good + line + "\n").encode("utf-8"))
                    else:
                        self._findings(good, feature_tail="\n## Notes\n\n" + line + "\n")
                    self.assertLess(time.perf_counter() - began, 1.0)

    def test_linear_patterns_read_what_the_old_ones_read(self):
        # The three patterns rewritten for linear time, checked against their old form.
        old_format = re.compile(
            r"^\s*(?:[>*+|-]\s*)*[*_]*\s*spec[-_ ]?format\s*[*_]*\s*[:|]\s*[*_]*\s*ears-1\b", re.IGNORECASE)
        old_status = re.compile(
            r"^\s*(?:[>*+|-]\s*)*[*_]*\s*status\s*[*_]*\s*[:|]\s*[*_]*\s*(?:draft|approved|converged)\b",
            re.IGNORECASE)
        old_marker = re.compile(r"\[\s*NEEDS\s+CLARIFICATION\s*(?::[^\]]*)?\]", re.IGNORECASE)
        corpus = []
        for path in list(ROOT.glob("docs/specs*/*/*.md")) + list(ROOT.glob("registry/fixtures/FLOW.*/*/*.md")):
            corpus += path.read_text(encoding="utf-8").splitlines()
        rng = random.Random(20261120)
        header_bits = ["> ", "- ", "* ", "| ", "+ ", "**", "_", " ", "\t", "status", "Status", "spec-format",
                       "Spec_Format", ":", "|", "draft", "converged", "approved", "ears-1", "ears-2", "x"]
        marker_bits = ["[", "]", ":", " ", "\n", "NEEDS", "needs", "CLARIFICATION", "clarification", "x", "\t",
                       "[NEEDS CLARIFICATION", "[ needs\n clarification ", "[NEEDS CLARIFICATION]",
                       "[NEEDS CLARIFICATION: which?]", "NEEDS CLARIFICATION"]
        for _ in range(4000):
            corpus.append("".join(rng.choice(header_bits) for _ in range(rng.randint(1, 9))))
        self.assertGreater(sum(1 for line in corpus if old_status.match(line)), 20)
        for line in corpus:
            # a superset: every header the old pattern saw, the new one sees
            if old_format.match(line):
                self.assertTrue(spec_lint._LOOSE_FORMAT.match(line), line)
            if old_status.match(line):
                self.assertTrue(spec_lint._LOOSE_STATUS.match(line), line)
        texts = ["\n".join(corpus[:4000])]
        texts += ["".join(rng.choice(marker_bits) for _ in range(rng.randint(1, 40))) for _ in range(6000)]
        seen = 0
        for text in texts:
            want = [m.span() for m in old_marker.finditer(text)]
            seen += len(want)
            self.assertEqual(spec_lint._marker_spans(text), want, repr(text))
            self.assertEqual(spec_lint._without_markers(text), old_marker.sub("", text), repr(text))
        self.assertGreater(seen, 1000)

    def test_the_cli_refuses_a_flip_until_a_receipt_is_committed(self):
        # A real run of the shipped command against a throwaway repository.
        case = RUN_FIXTURES / "violation_flip_without_run_evidence"
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as home:
            env["HOME"] = env["USERPROFILE"] = home  # an empty receipt ledger

            def git(*a):
                return subprocess.run(["git", "-C", repo, *a], check=True, env=env,
                                      capture_output=True, text=True).stdout.strip()

            def gate(base):
                return subprocess.run([sys.executable, str(ROOT / "scripts" / "spec_lint.py"),
                                       "--repo", repo, "--push-range", base, "HEAD"],
                                      env=env, capture_output=True, text=True)
            sd = Path(repo) / "docs" / "specs" / "202611200000-toy"
            sd.mkdir(parents=True)
            for name in ("feature.md", "plan.md"):
                (sd / name).write_text((case / name).read_text(encoding="utf-8"), encoding="utf-8")
            git("init", "-q")
            git("add", "-A")
            git("commit", "-qm", "base")
            base = git("rev-parse", "HEAD")
            feature = sd / "feature.md"
            feature.write_text(feature.read_text(encoding="utf-8").replace(
                "> **Status:** approved", "> **Status:** converged"), encoding="utf-8")
            git("commit", "-qam", "flip")
            first = gate(base)
            self.assertEqual(first.returncode, 1)
            self.assertIn("has no run receipt under `## Run evidence`", first.stdout)
            with feature.open("a", encoding="utf-8") as fh:
                fh.write("\n## Run evidence\n\n- RUN-01 [AC-01] `<what was executed>`: <what was observed>\n")
            git("commit", "-qam", "template")
            template = gate(base)
            self.assertIn("has no run receipt under `## Run evidence`", template.stdout)
            self.assertIn("RUN-01 is an unfilled template", template.stdout)
            feature.write_text(feature.read_text(encoding="utf-8").replace(
                "`<what was executed>`: <what was observed>",
                "`python3 app.py`: exit 0, the report is written in UTF-8"), encoding="utf-8")
            git("commit", "-qam", "receipt")
            filled = gate(base)
            self.assertNotIn("run receipt", filled.stdout)
            self.assertNotIn("unfilled template", filled.stdout)
            self.assertIn("holds no converge receipt", filled.stdout)  # the other half still asks
            feature.write_text(feature.read_text(encoding="utf-8").replace(
                "`python3 app.py`: exit 0, the report is written in UTF-8",
                "`todo add milk`: pending migrations 0, exit 0"), encoding="utf-8")
            git("commit", "-qam", "a real command that starts with a placeholder word")
            honest = gate(base)
            self.assertNotIn("run receipt", honest.stdout)
            self.assertNotIn("unfilled template", honest.stdout)

    def test_the_cli_refuses_a_flip_until_a_receipt_is_committed(self):
        # A real run of the shipped command against a throwaway repository.
        case = RUN_FIXTURES / "violation_flip_without_the_evidence_file"
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as home:
            env["HOME"] = env["USERPROFILE"] = home  # an empty receipt ledger

            def git(*a):
                return subprocess.run(["git", "-C", repo, *a], check=True, env=env,
                                      capture_output=True, text=True).stdout.strip()

            def gate(base):
                return subprocess.run([sys.executable, str(ROOT / "scripts" / "spec_lint.py"),
                                       "--repo", repo, "--push-range", base, "HEAD"],
                                      env=env, capture_output=True, text=True)
            sd = Path(repo) / "docs" / "specs" / "202611200000-toy"
            sd.mkdir(parents=True)
            for name in ("feature.md", "plan.md"):
                (sd / name).write_text((case / name).read_text(encoding="utf-8"), encoding="utf-8")
            git("init", "-q")
            git("config", "core.autocrlf", "false")
            git("add", "-A")
            git("commit", "-qm", "base")
            base = git("rev-parse", "HEAD")
            feature = sd / "feature.md"
            evidence = sd / "run-evidence.txt"

            def commit(msg, data: bytes):
                evidence.write_bytes(data)
                git("add", "-A")
                git("commit", "-qm", msg)
                return gate(base)
            feature.write_text(feature.read_text(encoding="utf-8").replace(
                "> **Status:** approved", "> **Status:** converged"), encoding="utf-8")
            git("commit", "-qam", "flip")
            first = gate(base)
            self.assertEqual(first.returncode, 1)
            self.assertIn("has no `run-evidence.txt`", first.stdout)
            template = commit("template", b"RUN-01 [AC-01] `<what was executed>`: <what was observed>\n")
            self.assertIn("holds no run receipt that counts", template.stdout)
            self.assertIn("run-evidence.txt:1: RUN-01 is an unfilled template", template.stdout)
            hidden = commit("a receipt behind a form feed", b"# runs\x0cRUN-01 [AC-01] `python3 app.py`: exit 0\n")
            self.assertIn("holds no run receipt that counts", hidden.stdout)
            self.assertIn("holds the character U+000C", hidden.stdout)
            lone = commit("a receipt behind a lone carriage return", b"# runs\rRUN-01 [AC-01] `python3 app.py`: exit 0\n")
            self.assertIn("holds the character U+000D", lone.stdout)
            binary = commit("not text", b"RUN-01 [AC-01] `python3 app.py`: exit 0\n\xff\xfe\n")
            self.assertEqual(binary.returncode, 1)
            self.assertIn("run-evidence.txt:2: not valid UTF-8", binary.stdout)
            filled = commit("receipt", b"# one run\r\nRUN-01 [AC-01] `python3 app.py`: exit 0, the report is written in UTF-8\r\n")
            self.assertNotIn("run-evidence", filled.stdout)
            self.assertNotIn("unfilled template", filled.stdout)
            self.assertIn("holds no converge receipt", filled.stdout)  # the other half still asks
            honest = commit("a real command that starts with a placeholder word",
                            b"RUN-01 [AC-01] `todo add milk`: pending migrations 0, exit 0\n")
            self.assertNotIn("run-evidence", honest.stdout)
            self.assertNotIn("unfilled template", honest.stdout)


if __name__ == "__main__":
    unittest.main()
