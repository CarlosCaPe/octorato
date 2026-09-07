#!/usr/bin/env python3
"""A deny count of zero is two different states, and only one of them is healthy.

`kernel-replay` used to print `0 deny(s) in 7 days` whether the harness had refused
nothing since the PermissionDenied hook went live, or had refused plenty and the
reflex had recorded none of it. The first is an unexercised mechanism, the second is
a dead one, and a check that renders them identically is a check that cannot fail
when it matters.

The other side of the comparison is the harness's own record: it stamps a refused
tool call with `toolDenialKind` in the session transcript. No hook writes that, which
is what makes it evidence rather than a second opinion from the same source.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

BRAIN = Path(__file__).resolve().parent.parent.parent
DOCTOR = BRAIN / "scripts" / "brain_doctor.py"


def _load():
    spec = importlib.util.spec_from_file_location("brain_doctor_dc", DOCTOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


doctor = _load()


def _restore_env(saved: dict) -> None:
    """Put CLAUDE_CONFIG_DIR back exactly as it was, unset included. os.environ is
    process-wide, and a leak here would follow every later test module."""
    for k in ("CLAUDE_CONFIG_DIR",):
        if k in saved:
            os.environ[k] = saved[k]
        else:
            os.environ.pop(k, None)


class DenyCoverageCase(unittest.TestCase):
    """A throwaway brain with a real git history, so the hook's arm date is read the
    way the check reads it in production: off the commit, not off a mtime a test
    could set to anything."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="deny-cov-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.brain = self.tmp / ".claude"
        (self.brain / "scripts").mkdir(parents=True)
        (self.brain / "projects" / "slug" / "sess").mkdir(parents=True)
        hook = self.brain / "scripts" / "r__permission-denied__journal.py"
        hook.write_text("# stand-in for the reflex\n", encoding="utf-8")
        env = dict(os.environ)
        # git exports these to its hooks, and a `git -C` does NOT clear them, so a
        # commit made from inside one lands in the LIVE repo. Scrubbed for the same
        # reason brain_doctor.scrubbed_env exists.
        for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_PREFIX",
                  "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY", "GIT_NAMESPACE"):
            env.pop(k, None)
        for args in (["init", "-q"],
                     ["config", "user.email", "t@example.invalid"],
                     ["config", "user.name", "t"],
                     ["add", "scripts/r__permission-denied__journal.py"],
                     ["commit", "-q", "-m", "add the reflex"]):
            subprocess.run(["git", "-C", str(self.brain)] + args, check=True,
                           capture_output=True, env=env)
        self._saved_dir = doctor.CLAUDE_DIR
        doctor.CLAUDE_DIR = self.brain
        self.addCleanup(lambda: setattr(doctor, "CLAUDE_DIR", self._saved_dir))
        # The transcripts resolve from the HARNESS home, not from the checkout,
        # which is the finding this sandbox now has to model: pointing only
        # CLAUDE_DIR at a fixture used to leave the scan reading the real brain.
        saved_env = dict(os.environ)
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.brain)
        self.addCleanup(_restore_env, saved_env)

    def write_refusal(self, kind: str, when: float) -> None:
        """One transcript record in the harness's own shape."""
        from datetime import datetime, timezone
        stamp = datetime.fromtimestamp(when, timezone.utc).isoformat().replace("+00:00", "Z")
        path = self.brain / "projects" / "slug" / "sess" / "transcript.jsonl"
        rec = {"type": "user", "timestamp": stamp,
               "message": {"content": [{"type": "tool_result", "is_error": True,
                                        "toolDenialKind": kind}]}}
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
        os.utime(path, (when + 5, when + 5))


class TestArmDate(DenyCoverageCase):
    def test_a_refusal_from_before_the_hook_existed_is_not_counted(self):
        """Refusals that predate the reflex are nobody's fault. Counting them would
        make every brain fail its first doctor run after wiring the hook."""
        armed, seen, _ = doctor._harness_refusals_since_hook(time.time() - 7 * 86400)
        self.assertIsNotNone(armed)
        self.write_refusal("automode-blocked", armed - 3600)
        _, seen_after, _ = doctor._harness_refusals_since_hook(time.time() - 7 * 86400)
        self.assertEqual(seen_after, 0)

    def test_a_refusal_after_the_hook_went_live_is_counted(self):
        armed, _, _ = doctor._harness_refusals_since_hook(time.time() - 7 * 86400)
        self.write_refusal("automode-blocked", armed + 60)
        _, seen, _ = doctor._harness_refusals_since_hook(time.time() - 7 * 86400)
        self.assertEqual(seen, 1)

    def test_a_brain_with_no_such_commit_reports_no_window(self):
        """A fresh or shallow clone has no commit for the hook. The honest answer is
        None, so the caller prints the count without a verdict it cannot support."""
        subprocess.run(["git", "-C", str(self.brain), "rm", "-q", "--cached",
                        "scripts/r__permission-denied__journal.py"],
                       check=True, capture_output=True)
        other = self.tmp / "empty"
        (other / "scripts").mkdir(parents=True)
        subprocess.run(["git", "-C", str(other), "init", "-q"], check=True, capture_output=True)
        doctor.CLAUDE_DIR = other
        armed, seen, _ = doctor._harness_refusals_since_hook(time.time() - 7 * 86400)
        self.assertIsNone(armed)
        self.assertEqual(seen, 0)


    def test_a_shallow_clone_reports_no_window_rather_than_a_wrong_one(self):
        """The commit message claimed a shallow clone "claims nothing". It did the
        opposite: git treats the grafted tip as introducing every file, so `log -1`
        always answers, always with the newest possible date, which is the narrowest
        possible window. Quiet on broken (QA cycle 1)."""
        shallow = self.tmp / "shallow"
        subprocess.run(["git", "clone", "-q", "--depth", "1", "file://" + str(self.brain),
                        str(shallow)], check=True, capture_output=True)
        doctor.CLAUDE_DIR = shallow
        armed, seen, other = doctor._harness_refusals_since_hook(time.time() - 7 * 86400)
        self.assertIsNone(armed, "a grafted history cannot say when the hook arrived")
        self.assertEqual((seen, other), (0, 0))

    def test_a_later_edit_to_the_hook_does_not_move_the_window(self):
        """`git log -1` with a pathspec answers with the LAST commit that touched the
        file, so the day anyone fixes a typo in the hook the window would collapse to
        that moment and the check would go quiet for good. The question is when the
        reflex could FIRST have fired."""
        armed_before, _, _ = doctor._harness_refusals_since_hook(0)
        hook = self.brain / "scripts" / "r__permission-denied__journal.py"
        hook.write_text("# a typo fix, months later\n", encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env["GIT_COMMITTER_DATE"] = env["GIT_AUTHOR_DATE"] = "2099-01-01T00:00:00Z"
        for args in (["add", "-A"], ["commit", "-q", "-m", "fix a typo"]):
            subprocess.run(["git", "-C", str(self.brain)] + args, check=True,
                           capture_output=True, env=env)
        armed_after, _, _ = doctor._harness_refusals_since_hook(0)
        self.assertEqual(armed_before, armed_after,
                         "maintaining the hook must not silence the check")


class TestTheEvidenceIsWhereTheHarnessWritesIt(DenyCoverageCase):
    def test_the_scan_follows_the_harness_home_not_the_checkout(self):
        """The finding that made the whole check a no-op: the projects dir was
        resolved from the checkout this file lives in, so from a worktree it pointed
        at a directory that does not exist, the scan read nothing, and the healthy
        sentence printed anyway. This brain's own rule puts every parallel session in
        a worktree, so that was the normal case."""
        armed, _, _ = doctor._harness_refusals_since_hook(time.time() - 7 * 86400)
        self.write_refusal("automode-blocked", armed + 60)
        # CLAUDE_DIR moved somewhere with no projects/ at all, the worktree shape
        elsewhere = self.tmp / "worktree"
        (elsewhere / "scripts").mkdir(parents=True)
        doctor.CLAUDE_DIR = self.brain          # the git history still resolves
        self.assertFalse((elsewhere / "projects").exists())
        _, seen, _ = doctor._harness_refusals_since_hook(time.time() - 7 * 86400)
        self.assertEqual(seen, 1, "the transcripts are found by the harness home")

    def test_no_projects_dir_at_all_claims_nothing(self):
        """Absent evidence is not evidence of absence. Reporting zero here would be
        the check's own disease: a reassuring sentence produced by reading nothing."""
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.tmp / "nowhere")
        armed, seen, other = doctor._harness_refusals_since_hook(time.time() - 7 * 86400)
        self.assertIsNone(armed)
        self.assertEqual((seen, other), (0, 0))

    def test_a_corrupt_transcript_is_skipped_not_crashed(self):
        """The doctor must not crash on a transcript nobody in this brain wrote."""
        armed, _, _ = doctor._harness_refusals_since_hook(time.time() - 7 * 86400)
        path = self.brain / "projects" / "slug" / "sess" / "junk.jsonl"
        deep = "[" * 200000 + "]" * 200000
        path.write_text('"toolDenialKind automode- not an object"\n'
                        + '{"toolDenialKind": "automode-blocked"\n'
                        + deep + ' toolDenialKind automode-\n', encoding="utf-8")
        os.utime(path, (armed + 60, armed + 60))
        _, seen, _ = doctor._harness_refusals_since_hook(time.time() - 7 * 86400)
        self.assertEqual(seen, 0, "no valid record, and no crash")


class TestWhichClassesCount(DenyCoverageCase):
    def test_only_the_automode_family_counts(self):
        """Measured on this harness: PermissionDenied fires for the auto-mode
        classifier only. A `permission-rule` or `user-rejected` refusal never reaches
        the hook, so counting it would manufacture a failure out of a refusal the
        reflex was never offered."""
        armed, _, _ = doctor._harness_refusals_since_hook(time.time() - 7 * 86400)
        for kind in ("permission-rule", "user-rejected"):
            self.write_refusal(kind, armed + 60)
        _, seen, _ = doctor._harness_refusals_since_hook(time.time() - 7 * 86400)
        self.assertEqual(seen, 0, "a refusal the hook never sees is not its failure")
        for kind in ("automode-blocked", "automode-unavailable", "automode-parsing-error"):
            self.write_refusal(kind, armed + 60)
        _, seen, _ = doctor._harness_refusals_since_hook(time.time() - 7 * 86400)
        self.assertEqual(seen, 3)

    def test_the_key_is_found_wherever_it_sits(self):
        """Walked, not path-indexed. A fixed path would stop matching the day the
        harness moves the field, which is exactly the silence this check exists to
        break."""
        deep = {"a": [{"b": {"c": {"toolDenialKind": "automode-blocked"}}}]}
        self.assertTrue(doctor._carries_automode_denial(deep))
        self.assertFalse(doctor._carries_automode_denial({"toolDenialKind": "permission-rule"}))
        self.assertFalse(doctor._carries_automode_denial({"toolDenialKind": 42}))
        self.assertFalse(doctor._carries_automode_denial([]))


class TestTheFourOutcomesReadDifferently(unittest.TestCase):
    """The whole point: states that used to print one sentence now print four, and
    exactly one of them fails. Pure inputs, so every branch is reachable here rather
    than only the one this machine happens to be in."""

    def test_no_refusals_since_the_hook_is_unexercised_not_proven(self):
        status, text, _ = doctor.deny_coverage(0, 1_700_000_000.0, 0)
        self.assertEqual(status, doctor.PASS)
        self.assertIn("unexercised rather than proven", text)
        self.assertNotIn("against", text)

    def test_refusals_and_an_empty_journal_is_the_only_failure(self):
        """The state the old message could not distinguish: wired and dead."""
        status, text, hint = doctor.deny_coverage(0, 1_700_000_000.0, 12)
        self.assertEqual(status, doctor.FAIL)
        self.assertIn("refused 12", text)
        self.assertIn("recorded none", text)
        self.assertIn("--selftest", hint, "a failure carries the command that checks it")

    def test_refusals_and_a_journal_that_has_them_passes_with_both_counts(self):
        status, text, _ = doctor.deny_coverage(9, 1_700_000_000.0, 12)
        self.assertEqual(status, doctor.PASS)
        self.assertIn("9 deny(s)", text)
        self.assertIn("12 harness refusal(s)", text)

    def test_a_brain_with_no_arm_date_claims_nothing(self):
        """No commit for the hook means no window, and no window means no verdict.
        Reading `no history` as `no refusals` would be an invented pass."""
        status, text, _ = doctor.deny_coverage(0, None, 0)
        self.assertEqual(status, doctor.PASS)
        self.assertNotIn("unexercised", text)
        self.assertNotIn("harness", text)

    def test_the_failure_cannot_be_reached_without_a_real_refusal(self):
        """The control. If any input shape produced FAIL, the check would fire on a
        healthy brain and be turned off by the next person who saw it."""
        for denies, armed, harness in ((0, None, 0), (0, 1.0, 0), (5, 1.0, 0),
                                       (5, 1.0, 5), (1, 1.0, 99)):
            with self.subTest(denies=denies, armed=armed, harness=harness):
                self.assertEqual(doctor.deny_coverage(denies, armed, harness)[0],
                                 doctor.PASS)


if __name__ == "__main__":
    unittest.main()
