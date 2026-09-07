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
        # TWO roles, deliberately in different places. The CHECKOUT is where the
        # git history lives; the HARNESS HOME is where transcripts are written. The
        # bug was reading the second from the first, and a sandbox that puts both in
        # one directory cannot tell the two resolutions apart, which is exactly how
        # the first version of this test passed on the broken code (QA cycle 2).
        self.brain = self.tmp / "checkout"
        (self.brain / "scripts").mkdir(parents=True)
        self.harness = self.tmp / "harness-home"
        (self.harness / "projects" / "slug" / "sess").mkdir(parents=True)
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
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.harness)
        self.addCleanup(_restore_env, saved_env)

    def write_refusal(self, kind: str, when: float) -> None:
        """One transcript record in the harness's own shape."""
        from datetime import datetime, timezone
        stamp = datetime.fromtimestamp(when, timezone.utc).isoformat().replace("+00:00", "Z")
        path = self.harness / "projects" / "slug" / "sess" / "transcript.jsonl"
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
        armed, seen, _, _ = doctor._harness_refusals_since_hook(time.time() - 7 * 86400)
        self.assertIsNotNone(armed)
        self.write_refusal("automode-blocked", armed - 3600)
        _, seen_after, _, _ = doctor._harness_refusals_since_hook(time.time() - 7 * 86400)
        self.assertEqual(seen_after, 0)

    def test_an_old_record_in_a_live_file_is_still_excluded(self):
        """The per-record timestamp guard had no test that dies without it: the
        sibling above back-dates the FILE's mtime along with the record, so the mtime
        prefilter alone carried it. In production the two are not equivalent. A
        long-running session file gets its mtime bumped by every new line, so a
        pre-arm record inside a still-active transcript is excluded only by the
        record's own timestamp (QA cycle 3)."""
        armed, _, _, _ = doctor._harness_refusals_since_hook(time.time() - 7 * 86400)
        self.write_refusal("automode-blocked", armed - 3600)
        # the file is LIVE: a later line just landed, so its mtime is now
        path = self.harness / "projects" / "slug" / "sess" / "transcript.jsonl"
        os.utime(path, None)
        self.assertGreater(path.stat().st_mtime, armed,
                           "the mtime prefilter must NOT be what excludes it")
        _, seen, _, _ = doctor._harness_refusals_since_hook(time.time() - 7 * 86400)
        self.assertEqual(seen, 0, "the record's own timestamp is what excludes it")

    def test_the_window_is_clamped_to_the_cutoff(self):
        """Claimed in a commit message before it existed, which is the failure this
        PR is about moved into the permanent record: QA reverted the clamp and all
        228 tests stayed green. Without it the harness window widens to the hook's
        commit date while the journal window stays seven days, so the two sides count
        over different spans and the failure is manufactured out of the mismatch."""
        armed_early, _, _, _ = doctor._harness_refusals_since_hook(0)
        self.assertIsNotNone(armed_early)
        self.assertLess(armed_early, 4_000_000_000.0)
        armed_clamped, _, _, _ = doctor._harness_refusals_since_hook(4_000_000_000.0)
        self.assertEqual(armed_clamped, 4_000_000_000.0,
                         "the cutoff wins whenever it is later than the add commit")

    def test_the_arm_date_takes_the_earlier_of_the_two_git_dates(self):
        """%ct is reset forward by any rebase, squash or filter-repo, and %at
        survives a rebase but not a squash. Both fail toward NOW, which narrows the
        window, which is quiet on a broken brain: the shallow-clone shape by another
        road. The earlier of the two errs wide, which can only make the check
        louder (QA cycle 5)."""
        # The two dates MUST differ here or the test is blind: in an ordinary commit
        # %at and %ct are the same instant, so min and max are the same number and
        # the mutation is invisible. My first version of this test did exactly that
        # and survived the revert, which the control caught before it shipped. A
        # rebase is what makes them diverge, so the sandbox reproduces one: an old
        # author date carried onto a fresh committer date.
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env["GIT_AUTHOR_DATE"] = "2020-01-01T00:00:00Z"
        env["GIT_COMMITTER_DATE"] = "2030-01-01T00:00:00Z"
        hook = self.brain / "scripts" / "r__permission-denied__journal.py"
        hook.write_text("# re-added after a rewrite\n", encoding="utf-8")
        for args in (["rm", "-q", "--cached", "scripts/r__permission-denied__journal.py"],
                     ["commit", "-q", "-m", "drop it"],
                     ["add", "scripts/r__permission-denied__journal.py"],
                     ["commit", "-q", "-m", "re-add it, author date older"]):
            subprocess.run(["git", "-C", str(self.brain)] + args, check=True,
                           capture_output=True, env=env)
        out = subprocess.run(["git", "log", "--diff-filter=A", "--follow", "-1",
                              "--format=%at %ct", "--",
                              "scripts/r__permission-denied__journal.py"],
                             cwd=str(self.brain), capture_output=True, text=True,
                             env=env).stdout.split()
        self.assertEqual(len(out), 2, "both dates are asked for")
        self.assertNotEqual(out[0], out[1],
                            "the fixture must make the two dates diverge, or a test "
                            "of `earlier of the two` cannot fail")
        armed, _, _, _ = doctor._harness_refusals_since_hook(0)
        self.assertEqual(armed, min(float(out[0]), float(out[1])),
                         "the EARLIER date wins, which errs wide")
        self.assertNotEqual(armed, max(float(out[0]), float(out[1])))

    def test_the_earlier_date_wins_in_the_other_direction_too(self):
        """The sibling above only ever produces %at < %ct, so `min` and "take %at"
        are the same function on its fixture and a mutation to either survives it.
        A rebase makes the author date the older one; a cherry-pick from a host whose
        clock runs fast makes the COMMITTER date the older one, and only that second
        shape can tell the two apart. QA cycle 6 measured the gap: the property the
        docstring claims was pinned in one direction and asserted in two."""
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env["GIT_AUTHOR_DATE"] = "2030-01-01T00:00:00Z"
        env["GIT_COMMITTER_DATE"] = "2020-01-01T00:00:00Z"
        hook = self.brain / "scripts" / "r__permission-denied__journal.py"
        hook.write_text("# re-added by a cherry-pick from a fast clock\n", encoding="utf-8")
        for args in (["rm", "-q", "--cached", "scripts/r__permission-denied__journal.py"],
                     ["commit", "-q", "-m", "drop it"],
                     ["add", "scripts/r__permission-denied__journal.py"],
                     ["commit", "-q", "-m", "re-add it, committer date older"]):
            subprocess.run(["git", "-C", str(self.brain)] + args, check=True,
                           capture_output=True, env=env)
        out = subprocess.run(["git", "log", "--diff-filter=A", "--follow", "-1",
                              "--format=%at %ct", "--",
                              "scripts/r__permission-denied__journal.py"],
                             cwd=str(self.brain), capture_output=True, text=True,
                             env=env).stdout.split()
        self.assertEqual(len(out), 2)
        self.assertGreater(float(out[0]), float(out[1]),
                           "this fixture is the MIRROR of the sibling: %ct must be "
                           "the earlier one here, or the pair proves nothing new")
        armed, _, _, _ = doctor._harness_refusals_since_hook(0)
        self.assertEqual(armed, float(out[1]), "the committer date is the earlier one")
        self.assertNotEqual(armed, float(out[0]))

    def test_a_refusal_after_the_hook_went_live_is_counted(self):
        armed, _, _, _ = doctor._harness_refusals_since_hook(time.time() - 7 * 86400)
        self.write_refusal("automode-blocked", armed + 60)
        _, seen, _, _ = doctor._harness_refusals_since_hook(time.time() - 7 * 86400)
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
        armed, seen, _, _ = doctor._harness_refusals_since_hook(time.time() - 7 * 86400)
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
        armed, seen, other, _ = doctor._harness_refusals_since_hook(time.time() - 7 * 86400)
        self.assertIsNone(armed, "a grafted history cannot say when the hook arrived")
        self.assertEqual((seen, other), (0, 0))

    def test_a_later_edit_to_the_hook_does_not_move_the_window(self):
        """`git log -1` with a pathspec answers with the LAST commit that touched the
        file, so the day anyone fixes a typo in the hook the window would collapse to
        that moment and the check would go quiet for good. The question is when the
        reflex could FIRST have fired."""
        armed_before, _, _, _ = doctor._harness_refusals_since_hook(0)
        hook = self.brain / "scripts" / "r__permission-denied__journal.py"
        hook.write_text("# a typo fix, months later\n", encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env["GIT_COMMITTER_DATE"] = env["GIT_AUTHOR_DATE"] = "2099-01-01T00:00:00Z"
        for args in (["add", "-A"], ["commit", "-q", "-m", "fix a typo"]):
            subprocess.run(["git", "-C", str(self.brain)] + args, check=True,
                           capture_output=True, env=env)
        armed_after, _, _, _ = doctor._harness_refusals_since_hook(0)
        self.assertEqual(armed_before, armed_after,
                         "maintaining the hook must not silence the check")


class TestTheEvidenceIsWhereTheHarnessWritesIt(DenyCoverageCase):
    def test_the_scan_follows_the_harness_home_not_the_checkout(self):
        """The finding that made the whole check a no-op: the projects dir was
        resolved from the checkout this file lives in, so from a worktree it pointed
        at a directory that does not exist, the scan read nothing, and the healthy
        sentence printed anyway. This brain's own rule puts every parallel session in
        a worktree, so that was the normal case."""
        armed, _, _, _ = doctor._harness_refusals_since_hook(time.time() - 7 * 86400)
        self.write_refusal("automode-blocked", armed + 60)
        # THE control that makes this test discriminate: the checkout has no
        # projects/ at all, which is the worktree shape, so the old resolution finds
        # nothing while the new one finds the transcript. The first version of this
        # test pointed both at one directory and therefore passed on the bug.
        self.assertFalse((self.brain / "projects").exists(),
                         "the checkout must NOT carry transcripts, or the two "
                         "resolutions cannot be told apart")
        _, seen, _, _ = doctor._harness_refusals_since_hook(time.time() - 7 * 86400)
        self.assertEqual(seen, 1, "the transcripts are found by the harness home")

    def test_no_projects_dir_at_all_claims_nothing(self):
        """Absent evidence is not evidence of absence. Reporting zero here would be
        the check's own disease: a reassuring sentence produced by reading nothing."""
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.tmp / "nowhere")
        armed, seen, other, _ = doctor._harness_refusals_since_hook(time.time() - 7 * 86400)
        self.assertIsNone(armed)
        self.assertEqual((seen, other), (0, 0))

    def test_an_unreadable_subdirectory_claims_nothing_either(self):
        """The probe guarded the ROOT and glob swallowed the PermissionError one
        level down, so the silent zero came straight back inside a session folder.
        Same blind spot, same remedy, as the tree walk in the packages work the same
        day: a call that fails without raising is its own class (QA cycle 3)."""
        armed, _, _, _ = doctor._harness_refusals_since_hook(time.time() - 7 * 86400)
        self.write_refusal("automode-blocked", armed + 60)
        inner = self.harness / "projects" / "slug"
        os.chmod(inner, 0o000)
        self.addCleanup(lambda: os.chmod(inner, 0o755))
        if os.access(inner, os.R_OK):
            self.skipTest("running as root, EACCES is not enforceable")
        armed2, seen, other, _ = doctor._harness_refusals_since_hook(time.time() - 7 * 86400)
        self.assertIsNone(armed2, "a subtree it cannot walk is not evidence of zero")
        self.assertEqual((seen, other), (0, 0))

    def test_an_unreadable_projects_dir_claims_nothing(self):
        """The ROOT case of the subtree test above, kept because it is the shape
        found first. What protects it is the ERROR-AWARE WALK, not the listing probe
        cycle 2 added: that probe was deleted once the walk covered the root too, and
        this test stayed green through its deletion, which is how it was found
        pointing at a guard that no longer existed (QA cycle 4 and 5). A docstring
        that credits a deleted guard tells the next reader to stop looking."""
        projects = self.harness / "projects"
        os.chmod(projects, 0o000)
        self.addCleanup(lambda: os.chmod(projects, 0o755))
        if os.access(projects, os.R_OK):
            self.skipTest("running as root, EACCES is not enforceable")
        armed, seen, other, _ = doctor._harness_refusals_since_hook(time.time() - 7 * 86400)
        self.assertIsNone(armed, "a directory it cannot list is not evidence of zero")
        self.assertEqual((seen, other), (0, 0))

    def test_a_corrupt_transcript_is_skipped_not_crashed(self):
        """The doctor must not crash on a transcript nobody in this brain wrote."""
        armed, _, _, _ = doctor._harness_refusals_since_hook(time.time() - 7 * 86400)
        path = self.harness / "projects" / "slug" / "sess" / "junk.jsonl"
        deep = "[" * 200000 + "]" * 200000
        path.write_text('"toolDenialKind automode- not an object"\n'
                        + '{"toolDenialKind": "automode-blocked"\n'
                        + deep + ' toolDenialKind automode-\n', encoding="utf-8")
        os.utime(path, (armed + 60, armed + 60))
        _, seen, _, _ = doctor._harness_refusals_since_hook(time.time() - 7 * 86400)
        self.assertEqual(seen, 0, "no valid record, and no crash")


class TestWhichClassesCount(DenyCoverageCase):
    def test_only_the_automode_family_counts(self):
        """Measured on this harness: PermissionDenied fires for the auto-mode
        classifier only. A `permission-rule` or `user-rejected` refusal never reaches
        the hook, so counting it would manufacture a failure out of a refusal the
        reflex was never offered."""
        armed, _, _, _ = doctor._harness_refusals_since_hook(time.time() - 7 * 86400)
        for kind in ("permission-rule", "user-rejected"):
            self.write_refusal(kind, armed + 60)
        _, seen, _, _ = doctor._harness_refusals_since_hook(time.time() - 7 * 86400)
        self.assertEqual(seen, 0, "a refusal the hook never sees is not its failure")
        for kind in ("automode-blocked", "automode-unavailable", "automode-parsing-error"):
            self.write_refusal(kind, armed + 60)
        _, seen, _, _ = doctor._harness_refusals_since_hook(time.time() - 7 * 86400)
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


class TestEachNoWindowRoadNamesItself(DenyCoverageCase):
    """Four roads end at "no window" and they are not the same news. A shallow clone
    is permanent for that checkout, a missing projects dir is a config mismatch, an
    unreadable subtree is transient or hostile, and a checkout with no such commit is
    a fresh one. Rendering them as one non-event is the collapse this whole check
    exists to undo, reappearing one level up (QA cycle 6)."""

    def _why(self):
        armed, _, _, why = doctor._harness_refusals_since_hook(time.time() - 7 * 86400)
        # Asserted at COLLECTION time, not after: a road that quietly stopped being a
        # no-window road would otherwise donate a stale cause to the distinctness
        # check and the set would still look healthy.
        self.assertIsNone(armed, "this road must actually reach the no-window return")
        self.assertTrue(why, "and it must name itself on the way")
        return why

    def test_the_four_roads_give_four_different_causes(self):
        causes = {}
        inner = self.harness / "projects" / "slug"
        os.chmod(inner, 0o000)
        if os.access(inner, os.R_OK):
            os.chmod(inner, 0o755)
            self.skipTest("running as root, EACCES is not enforceable")
        try:
            causes["unreadable subtree"] = self._why()
        finally:
            os.chmod(inner, 0o755)

        saved_cfg = os.environ["CLAUDE_CONFIG_DIR"]
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.tmp / "nowhere")
        try:
            causes["no projects dir"] = self._why()
        finally:
            os.environ["CLAUDE_CONFIG_DIR"] = saved_cfg

        shallow = self.tmp / "shallow"
        subprocess.run(["git", "clone", "-q", "--depth", "1",
                        "file://" + str(self.brain), str(shallow)],
                       check=True, capture_output=True)
        doctor.CLAUDE_DIR = shallow
        causes["shallow clone"] = self._why()

        empty = self.tmp / "empty"
        (empty / "scripts").mkdir(parents=True)
        subprocess.run(["git", "-C", str(empty), "init", "-q"], check=True,
                       capture_output=True)
        doctor.CLAUDE_DIR = empty
        causes["no such commit"] = self._why()

        self.assertEqual(len(set(causes.values())), 4,
                         f"each road has to be distinguishable in the sentence: {causes}")
        # Distinct is not enough: swapping two roads' strings keeps the set at four
        # while the doctor tells a reader "shallow clone" over a missing projects
        # directory, which is a WRONG cause, worse than none (QA cycle 7). So bind
        # each road to its own discriminator. Substrings, not the whole sentence:
        # this must survive a reworded message and die on a swapped one.
        for road, token in (("unreadable subtree", "could not read"),
                            ("no projects dir", "no projects directory"),
                            ("shallow clone", "shallow"),
                            ("no such commit", "no commit adding")):
            self.assertIn(token, causes[road],
                          f"the {road} road is telling the reader it was something else: "
                          f"{causes[road]!r}")


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

    def test_a_brain_with_no_arm_date_says_it_did_not_compare(self):
        """No window means no verdict, and it also has to mean no SILENCE. This
        assertion was inverted: it REQUIRED the line to say nothing about the
        harness, so `never compared` and `compared and clean` rendered the same
        PASS. That is this check's own thesis failing inside the function that
        fixed it, and three roads now reach it, one of them a directory that
        vanishes mid-walk with nobody attacking anything (QA cycle 4)."""
        status, text, _ = doctor.deny_coverage(0, None, 0)
        self.assertEqual(status, doctor.PASS, "it still claims no verdict")
        self.assertIn("window could not be established", text)
        self.assertNotIn("unexercised", text, "that is the OTHER state's sentence")
        _, clean_text, _ = doctor.deny_coverage(0, 1_700_000_000.0, 0)
        self.assertNotEqual(text, clean_text,
                            "a reader must be able to tell the two apart")

    def test_the_warn_survives_the_pure_function(self):
        status, text, hint = doctor.deny_coverage(0, 1_700_000_000.0, 0, 7)
        self.assertEqual(status, doctor.WARN)
        self.assertIn("7 refusal(s) of other classes", text)
        self.assertIn("toolDenialKind", hint, "a WARN has to say what to confirm")

    def test_the_warn_reaches_the_caller_that_was_dropping_it(self):
        """The test above is NOT this test, and mistaking one for the other is the
        finding. The pure function already returned WARN before the fix; the caller
        collapsed it into its PASS line and threw the hint away. Asserting on the
        function proved nothing about the caller, and QA showed it by putting the
        bug back and watching all 216 tests stay green.

        So this one calls `check_kernel_replay` itself, with only the counter
        stubbed, and asserts on the Result a reader actually sees. It fails on every
        version of this file before the caller was fixed.
        """
        real = doctor._harness_refusals_since_hook
        doctor._harness_refusals_since_hook = lambda cutoff: (1_700_000_000.0, 0, 7, "")
        self.addCleanup(lambda: setattr(doctor, "_harness_refusals_since_hook", real))
        # This class does not move CLAUDE_DIR, so the replay half of the check runs
        # against the real checkout, which is what makes the Result a real one.
        result = doctor.check_kernel_replay(False)
        self.assertEqual(result.status, doctor.WARN,
                         "a status the caller does not carry does not exist")
        self.assertIn("refusal(s) of other classes", result.message)
        self.assertIn("toolDenialKind", result.hint or "",
                      "the hint has to survive the trip through the caller")

    def test_the_cause_reaches_the_reader_through_the_caller(self):
        """The literal recurrence of the WARN finding, one word over. The cause of a
        no-window PASS lived in the HINT for one cycle, and a hint on a PASS is dead
        twice: `check_kernel_replay` forwards one only for FAIL and WARN, and
        `render_human` prints one only for FAIL and WARN. So the commit message could
        claim "the reader still learns which road it was" while no reader could.

        This asserts on the Result a reader actually gets, not on the pure function,
        and it dies on any version that puts the cause anywhere but the sentence
        (QA cycle 6)."""
        road = "a shallow clone, whose grafted history cannot say when the hook arrived"
        real = doctor._harness_refusals_since_hook
        doctor._harness_refusals_since_hook = lambda cutoff: (None, 0, 0, road)
        self.addCleanup(lambda: setattr(doctor, "_harness_refusals_since_hook", real))
        result = doctor.check_kernel_replay(False)
        self.assertEqual(result.status, doctor.PASS,
                         "no window is not a failure, it is an uncompared reflex")
        self.assertIn(road, result.message,
                      "a cause the reader cannot see is a cause that does not exist")
        self.assertIn("NOT compared", result.message)

    def test_a_pass_message_survives_the_printer(self):
        """The eighth instance of this session's recurring failure, and the sibling
        of the first. Instance #1 asserted on the pure function when the bug was in
        the caller; this one asserted on the caller when the claim was about the
        PRINTER. My own docstring named both hops ("`check_kernel_replay` forwards
        one only for FAIL and WARN, AND `render_human` prints one only for FAIL and
        WARN") and the test crossed one of them. QA proved it by restoring the exact
        cycle-6 invisibility inside `render_human` and watching all 234 stay green
        (QA cycle 7).

        `render_human` is the last hop before a human, so the invariant the source
        states, "a cause the reader cannot see is a cause that does not exist", is
        only closed here.
        """
        import io, contextlib
        cause = "a shallow clone, whose grafted history cannot say when the hook arrived"
        r = doctor.Result("kernel-replay", doctor.PASS,
                          f"0 deny(s) in 7 days; the comparison window could not be "
                          f"established ({cause}), so the reflex was NOT compared "
                          f"against the harness record", "")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            doctor.render_human([r])
        out = buf.getvalue()
        self.assertIn(cause, out,
                      "a PASS message must reach stdout; the printer is where the "
                      "cause was invisible the second time")
        self.assertIn("kernel-replay", out)

    def test_the_warn_needs_an_empty_journal_not_just_other_classes(self):
        """The other one claimed and missing. Dropping the second half of the
        condition fires the WARN on a healthy brain that HAS journal denies, which is
        the noisy direction and the one an operator learns to scroll past."""
        status, _, _ = doctor.deny_coverage(4, 1_700_000_000.0, 0, 7)
        self.assertEqual(status, doctor.PASS,
                         "denies in the journal mean the reflex is demonstrably alive")
        status, _, _ = doctor.deny_coverage(0, 1_700_000_000.0, 0, 7)
        self.assertEqual(status, doctor.WARN, "an empty journal is what makes it a WARN")

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
