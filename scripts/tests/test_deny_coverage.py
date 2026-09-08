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
import io
import json
import os
import re
import shutil
import sys
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


def run_main(checks, argv=("brain_doctor.py",)):
    """Run the REAL `main` with `checks` in place of CHECKS, over a REAL byte stream.

    Every earlier attempt at this pinned one path at whatever hop had just been
    fixed, and the next mutation moved one hop past it. Ten instances in, the answer
    is not another single-path test: it is one wire that carries everything a reader
    gets (status, message, hint, name, exit code, encoding) for a FAIL and a WARN and
    a PASS at once.

    Bytes, not StringIO. `redirect_stdout(io.StringIO())` swallows the
    `AttributeError` from `sys.stdout.reconfigure` and never encodes, so deleting the
    encoding hop in `main` was invisible while `PYTHONIOENCODING=ascii python3
    scripts/brain_doctor.py` died on the brain emoji before printing a single result
    (QA cycle 9). An ascii TextIOWrapper reproduces exactly that: `reconfigure` is
    real on a TextIOWrapper, so the hop is what keeps the glyphs encodable and
    dropping it raises here.
    """
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="ascii", errors="strict")
    real_checks, real_argv = doctor.CHECKS, sys.argv
    real_out, real_err = sys.stdout, sys.stderr
    doctor.CHECKS = list(checks)
    sys.argv = list(argv)
    sys.stdout = stream
    sys.stderr = io.TextIOWrapper(io.BytesIO(), encoding="ascii", errors="strict")
    try:
        rc = doctor.main()
    finally:
        try:
            stream.flush()
        except Exception:
            pass
        doctor.CHECKS, sys.argv = real_checks, real_argv
        sys.stdout, sys.stderr = real_out, real_err
    return rc, raw.getvalue().decode("utf-8")


def stub_checks(results):
    """CHECKS entries that hand back exactly these Results, one per check."""
    return [(r.key, (lambda r: (lambda fix: r))(r)) for r in results]


_ROW = re.compile(r"^\s*\[(PASS|WARN|FAIL)\]\s+\S\s+(\S+)\s\s+(.*)$")
_HINT = re.compile(r"^\s*↳ fix:\s(.*)$")


_SUMMARY = re.compile(r"^\s+(\d+) passed, (\d+) warn, (\d+) fail\s*$")


def parse_summary(out: str) -> dict:
    """The `N passed, N warn, N fail` footer, as a dict.

    Kept OUT of `parse_human`'s row namespace on purpose: putting it there made
    three sibling tests fail on an unexpected key, and a row dict that carries one
    entry which is not a row is a trap for every later caller. Separate reader,
    explicit assertion.

    It was the last thing the printer emits with nothing watching it. Swapping the
    warn and fail counts, zeroing them, or deleting the line all stayed green,
    while the JSON twin was asserted whole in the same class under a comment
    saying the counts are not interchangeable (QA cycle 11). A variant, not a hop,
    which is why every earlier sweep walked past it.
    """
    # La ULTIMA, no la primera. El pie va al final y un mensaje puede traer un
    # salto de linea con una linea con forma de resumen: `check crashed: {e}`
    # incrusta texto de excepcion arbitrario, y la salida de un subproceso llega
    # a los mensajes. Leyendo la primera, ese texto tapa el pie real y la
    # asercion que descansa en este lector mide el mensaje, no el resumen
    # (QA ciclo 12).
    for line in reversed(out.splitlines()):
        m = _SUMMARY.match(line)
        if m:
            return {"passed": int(m.group(1)), "warn": int(m.group(2)),
                    "fail": int(m.group(3))}
    return {}


def parse_human(out: str) -> dict:
    """What `render_human` printed, as {key: {status, message, hint}}.

    BY KEY, never "is this string somewhere in the blob". Presence-anywhere
    assertions stay green when the FAIL and WARN markers are swapped onto each
    other's rows, and when every row prints its NEIGHBOUR's hint: the reader is told
    the wrong thing about the right check and every `assertIn` is satisfied (QA
    cycle 10). Parsing the rows is what makes association assertable at all.
    """
    rows, last = {}, None
    for line in out.splitlines():
        m = _ROW.match(line)
        if m:
            last = m.group(2)
            rows[last] = {"status": m.group(1), "message": m.group(3).rstrip(), "hint": ""}
            continue
        m = _HINT.match(line)
        if m and last is not None:
            rows[last]["hint"] = m.group(1).rstrip()

    return rows


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
        # each road to its own discriminator.
        #
        # Presence alone is not enough either. Give all four roads the same
        # four-cause boilerplate and every `assertIn` passes while the reader gets a
        # MENU instead of a cause, which is this check's own disease (QA cycle 8). So
        # each road must also NOT carry the other three tokens.
        #
        # The tokens name the CONDITION, never the adjective: "shallow" alone made a
        # correct rewording to "a depth-limited clone, whose grafted history..." turn
        # the test red, so the binding was pinning the word and not the meaning.
        tokens = {"unreadable subtree": "could not read",
                  "no projects dir": "no projects directory",
                  "shallow clone": "grafted history",
                  "no such commit": "no commit adding"}
        for road, token in tokens.items():
            self.assertIn(token, causes[road],
                          f"the {road} road is telling the reader it was something else: "
                          f"{causes[road]!r}")
            for other, other_token in tokens.items():
                if other == road:
                    continue
                self.assertNotIn(other_token, causes[road],
                                 f"the {road} road also offers the reader the "
                                 f"{other} cause, which is a menu, not an answer: "
                                 f"{causes[road]!r}")


class TestTheFourOutcomesReadDifferently(unittest.TestCase):
    """The whole point: states that used to print one sentence now print four, and
    exactly one of them fails. Pure inputs, so every branch is reachable here rather
    than only the one this machine happens to be in."""

    def own_the_deny_count(self):
        """Point the journal scan at an EMPTY directory, so `denies` is 0 by
        construction instead of by luck.

        Any test here that calls `check_kernel_replay` was reading the live
        `~/.claude/.cache/kernel/journal/`, and the WARN branch needs `denies == 0`.
        The brain recorded its first deny inside the 7-day window mid-session and the
        suite went red at an untouched HEAD, deterministically, on any machine that
        has refused one call in a week (QA cycle 8). A test whose inputs it does not
        own is a test that will be deleted the first time the world moves.

        The first version of this pointed the scan at an EMPTY directory, and the
        commit message called what it stopped measuring "a count that was never the
        subject". That was wrong, and measured wrong: the check's second and third
        assertions (the newest real journals replay and verify, and every deny line
        names a registered rule) ran over 448 journals before and over zero after.
        Incidental, machine-dependent coverage is still coverage, and taking it to
        zero everywhere is a regression (QA cycle 9).

        So the directory holds the tracked golden journal instead, with a fresh
        mtime: the replay and chain verification execute for real, deterministically
        and on every machine, while the deny count stays 0 because that journal's own
        timestamps are years outside the 7-day window.

        HALF of that claim was false, and the false half is the one it was written to
        fix. Instrumented, the replay loop does enter with `journals=1` and fires
        three times, so assertion 2 executes. Assertion 3 does NOT: the `ts < cutoff`
        guard sits before `denies += 1`, so the golden journal's three deny lines are
        seen and none is counted, and the comparison against the registry that used
        to run over 46 real deny lines now runs over zero. Deny counting and the
        orphan check are not entangled by accident, they are entangled by one `if`.
        Unentangling them is not a matter of choosing a better journal for THIS
        helper, whose WARN branch needs `denies == 0` by construction: the orphan
        branch gets journals of its own, with fresh timestamps, in
        `TestTheJournalScanActuallyRuns` (QA cycle 10).

        The redirection is HOME, not a monkeypatch, because `octo replay --verify`
        runs in a SUBPROCESS: an in-process stub of `kernel_proc.journal_dir` cannot
        reach it, and the child went on reading the live directory. HOME is restored
        unconditionally, since a leaked one is what broke every later test module in
        PR #282.
        """
        import tempfile
        sandbox = Path(tempfile.mkdtemp(prefix="deny-cov-home-"))
        self.addCleanup(shutil.rmtree, sandbox, ignore_errors=True)
        jdir = sandbox / ".claude" / ".cache" / "kernel" / "journal"
        jdir.mkdir(parents=True)
        golden = (doctor.CLAUDE_DIR / "registry" / "fixtures"
                  / "ARCHITECTURE.kernel-process" / "replay" / "journal.jsonl")
        self.assertTrue(golden.is_file(), "the golden journal fixture must exist")
        seeded = jdir / "kernel-golden-agent.jsonl"
        shutil.copyfile(golden, seeded)
        os.utime(seeded, None)
        saved = os.environ.get("HOME")
        os.environ["HOME"] = str(sandbox)
        self.addCleanup(lambda: os.environ.__setitem__("HOME", saved)
                        if saved is not None else os.environ.pop("HOME", None))
        return jdir

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
        self.own_the_deny_count()
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
        self.own_the_deny_count()
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

    def test_the_cause_travels_from_the_check_to_stdout_through_main(self):
        """The NINTH instance, and it names the pattern: every fix moves the
        assertion one hop downstream and leaves the new last hop unpinned. #1 was
        the pure function vs its caller. #8 was the caller vs the printer. This is
        the printer vs the caller of the printer.

        `test_a_pass_message_survives_the_printer` hands `render_human` a Result it
        built itself, so the producer end and the printer end are each pinned and
        the WIRE between them is not. QA proved it: in `main`, filtering the PASS
        results out of the `render_human` call restores the cycle-6 invisibility one
        hop up, and all 235 tests stay green while the reader sees nothing at all,
        not even the check's name (QA cycle 8).

        So this one runs the real `check_kernel_replay` through the real `main` and
        reads stdout. Nothing is hand-built except the road.
        """
        import io, contextlib
        self.own_the_deny_count()
        road = "a shallow clone, whose grafted history cannot say when the hook arrived"
        real = doctor._harness_refusals_since_hook
        doctor._harness_refusals_since_hook = lambda cutoff: (None, 0, 0, road)
        self.addCleanup(lambda: setattr(doctor, "_harness_refusals_since_hook", real))
        real_checks = doctor.CHECKS
        doctor.CHECKS = [("kernel-replay", doctor.check_kernel_replay)]
        self.addCleanup(lambda: setattr(doctor, "CHECKS", real_checks))
        real_argv = sys.argv
        sys.argv = ["brain_doctor.py"]
        self.addCleanup(lambda: setattr(sys, "argv", real_argv))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = doctor.main()
        out = buf.getvalue()
        self.assertEqual(rc, 0, "no window is not a failure")
        self.assertIn(road, out,
                      "the cause has to survive every hop from the check to the "
                      "terminal, and main is the last one")
        self.assertIn("kernel-replay", out, "so does the name of the check saying it")

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


class TestTheJournalScanActuallyRuns(unittest.TestCase):
    """Assertions 2 and 3 of `check_kernel_replay`, each with a journal of its own.

    Both live one function away from the silent zero this PR exists to abolish, and
    both were reading whatever the machine happened to have. The helper that made the
    surrounding class deterministic seeds the tracked golden journal, whose `ts`
    values are years old, which is exactly what keeps the deny count at 0 for the
    WARN branch and exactly what stops assertion 3 from counting anything: the
    `ts < cutoff` guard sits before `denies += 1`. So the orphan branch gets its own
    journals here, with FRESH timestamps, and stops depending on a fixture chosen for
    the opposite property.

    Every test in this class also pins the SCAN itself. The journals are seeded under
    a sandbox HOME, which is where `kernel_proc.journal_dir()` reads; resolving it
    from CLAUDE_DIR instead (a `.cache/kernel/journal` that does not exist in a
    worktree, which under this brain's own isolation rule is the normal shape) or
    skipping every `.jsonl` name turns all four red.
    """

    def sandbox(self) -> Path:
        home = Path(tempfile.mkdtemp(prefix="deny-cov-journal-"))
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        jdir = home / ".claude" / ".cache" / "kernel" / "journal"
        jdir.mkdir(parents=True)
        saved = os.environ.get("HOME")
        os.environ["HOME"] = str(home)
        self.addCleanup(lambda: os.environ.__setitem__("HOME", saved)
                        if saved is not None else os.environ.pop("HOME", None))
        # HOME, not a monkeypatch: `octo replay --verify` runs in a SUBPROCESS and
        # inherits the environment, so an in-process stub of `journal_dir` would
        # leave the child reading the live directory. The paths in kernel_proc are
        # lazy for this reason, so importing it before or after the rebind is the
        # same thing.
        sys.path.insert(0, str(BRAIN / "scripts"))
        import kernel_proc
        self.kernel_proc = kernel_proc
        return jdir

    def seed(self, jdir: Path, pid: str, records) -> Path:
        """A REAL chained journal, written by the writer under test's own library.
        Hand-rolling the `prev` hashes would test my arithmetic, not the chain."""
        for rec in records:
            self.kernel_proc.append(pid, rec)
        return jdir / f"{pid}.jsonl"

    def start(self, ts: float) -> dict:
        return {"kind": "start", "ts": ts, "start_ts": ts, "type": "Reality Checker"}

    def break_chain(self, path: Path) -> None:
        """Rewrite line 0 so line 1's `prev` no longer matches its bytes. Tampering
        with the LAST line proves nothing: no later line points at it."""
        lines = path.read_text(encoding="utf-8").splitlines()
        first = json.loads(lines[0])
        first["type"] = "Rewritten After The Fact"
        lines[0] = json.dumps(first, separators=(",", ":"))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def no_harness_refusals(self) -> None:
        """Pin the OTHER half of the check, so a PASS here is about the journal."""
        real = doctor._harness_refusals_since_hook
        doctor._harness_refusals_since_hook = lambda cutoff: (1_700_000_000.0, 0, 0, "")
        self.addCleanup(lambda: setattr(doctor, "_harness_refusals_since_hook", real))

    def test_a_deny_naming_an_unregistered_rule_fails_the_check(self):
        """Assertion 3, which had stopped executing entirely. This is RULE #1 pointed
        at the journal: a refusal attributed to a rule the registry does not carry is
        a gate refusing work under a name nobody can look up."""
        jdir = self.sandbox()
        now = time.time()
        self.seed(jdir, "orphan-agent",
                  [self.start(now),
                   {"kind": "deny", "ts": now, "rule": "NOWHERE.no-such-rule",
                    "reason": "seeded"}])
        result = doctor.check_kernel_replay(False)
        self.assertEqual(result.status, doctor.FAIL, result.message)
        self.assertIn("NOWHERE.no-such-rule", result.message,
                      "the orphan rule id has to reach the reader by name")
        self.assertIn("in no registry row", result.message)

    def test_a_deny_naming_a_registered_rule_is_counted_and_passes(self):
        """The sibling that makes the one above a discriminator rather than a
        tripwire, and the assertion that the COUNT is real: a deny inside the window
        has to reach `denies`, so the sentence says two rather than zero. This is
        what dies the moment the `ts` guard swallows the count again."""
        jdir = self.sandbox()
        self.no_harness_refusals()
        rule = sorted(r.id for r in doctor.Registry.load(doctor.REGISTRY_PATH).rules)[0]
        now = time.time()
        self.seed(jdir, "registered-agent",
                  [self.start(now),
                   {"kind": "deny", "ts": now, "rule": rule, "reason": "seeded"},
                   {"kind": "deny", "ts": now, "rule": rule, "reason": "seeded again"}])
        result = doctor.check_kernel_replay(False)
        self.assertEqual(result.status, doctor.PASS, result.message)
        self.assertIn("2 deny(s) in 7 days, all naming a registered rule", result.message)

    def test_a_journal_whose_chain_is_broken_fails_by_pid(self):
        """Assertion 2 had no assertion. `for _, pid in journals[:5]:` replaced by
        `for _, pid in []:` was invisible to all 238 tests, and the loop had been
        "proved" to run by planting a `raise` inside it, which is a diagnostic, not a
        test: nothing that survives in the suite asserted it."""
        jdir = self.sandbox()
        now = time.time()
        path = self.seed(jdir, "tampered-agent",
                         [self.start(now),
                          {"kind": "tool", "ts": now, "tool_name": "Read",
                           "tool_use_id": "t1"}])
        self.break_chain(path)
        self.assertEqual(self.kernel_proc.verify_detail("tampered-agent")[0], 1,
                         "the fixture has to be a chain that actually breaks, or the "
                         "test passes on a check that never looked")
        result = doctor.check_kernel_replay(False)
        self.assertEqual(result.status, doctor.FAIL, result.message)
        # The whole sentence, not `assertIn("tampered-agent", ...)`. Measured: with
        # the `.jsonl` filter inverted, the scan picks up the sibling `.lock` file and
        # reports `pid tampered-agent.json`, which satisfies both of the substring
        # assertions this replaced while naming a journal that does not exist.
        self.assertEqual(result.message, "replay --verify failed for pid tampered-agent")

    def test_the_newest_five_journals_are_the_ones_replayed(self):
        """`journals.sort(reverse=True)` and then `[:5]`. Sorting the other way makes
        the check inspect the five OLDEST of hundreds, which on a real brain is the
        same silent zero by another road and survives any single-journal test."""
        jdir = self.sandbox()
        self.no_harness_refusals()
        now = time.time()
        for i in range(6):
            path = self.seed(jdir, f"chain-{i}",
                             [self.start(now),
                              {"kind": "tool", "ts": now, "tool_name": "Read",
                               "tool_use_id": "t1"}])
            if i == 0:
                self.break_chain(path)
            stamp = now - (6 - i) * 60
            os.utime(path, (stamp, stamp))
        result = doctor.check_kernel_replay(False)
        self.assertEqual(result.status, doctor.PASS,
                         "the broken chain is the OLDEST of six, outside the newest "
                         f"five: {result.message}")
        self.assertIn("5 real journal(s) replay", result.message)
        # the same journal, now the newest: one more line would do it in production
        os.utime(jdir / "chain-0.jsonl", None)
        result = doctor.check_kernel_replay(False)
        self.assertEqual(result.status, doctor.FAIL, result.message)
        self.assertIn("chain-0", result.message)


class TestTheWireCarriesEveryRow(unittest.TestCase):
    """`run_all` and both printers, exercised through the real `main`.

    Stubbing CHECKS is what made the wire deterministic, and it is also what took
    `run_all` itself back out of it: the `fix` flag, the per-check crash handler and
    the list-returning check were all unmeasured one hop further out, and a read-only
    doctor run that silently performed repairs (`git remote set-url`, `pip install
    --user`, writing `~/.cursor/hooks.json`, setting `core.hooksPath`, regenerating
    `neural_map.json`) is a real safety property of this tool. Stubbing an input to
    make a test deterministic deletes coverage silently; the stubs stay, and now they
    RECORD what `run_all` did to them (QA cycle 10).
    """

    def wire(self):
        """Two FAILs, a WARN and a PASS.

        The PASS is not padding. The fixture that carried only a FAIL and a WARN let
        `render_human` drop the `[PASS]` marker and let `main` drop PASS rows from the
        JSON `checks` array, both invisible, which is the eleventh instance of this
        session's pattern inside the test written to end it. A PASS is a VARIANT, not
        a hop, and every hop of it was covered while none of the variants was.

        The SECOND fail is not padding either, and it is my own miss caught by the
        control: with one WARN and one FAIL, swapping the `warn` and `fail` counts in
        the JSON summary produces the identical object, so the assertion that was
        written to catch that mutation could not. Asymmetric counts are what make the
        two positions distinguishable at all.
        """
        return [doctor.Result("stub-fail", doctor.FAIL, "the stub failed",
                              "fix the stub that failed"),
                doctor.Result("stub-fail-two", doctor.FAIL, "the other stub failed",
                              "fix the other stub too"),
                doctor.Result("stub-warn", doctor.WARN, "the stub warned",
                              "look at the stub that warned"),
                doctor.Result("stub-pass", doctor.PASS, "the stub passed", ""),
                # TRES pases, no uno. Con 2 FAIL / 1 WARN / 1 PASS los conteos eran
                # passed == warn == 1, asi que intercambiar esas dos posiciones daba una
                # linea BYTE POR BYTE identica, y dos mutaciones sobrevivian bajo una
                # asercion que dice "los conteos no son intercambiables". El segundo FAIL
                # se habia agregado por esta misma razon para romper el empate warn/fail:
                # tres posiciones son tres pares, y solo uno estaba roto. Con {3,1,2} las
                # seis permutaciones se distinguen (QA ciclo 12).
                doctor.Result("stub-pass-two", doctor.PASS, "another stub passed", ""),
                doctor.Result("stub-pass-three", doctor.PASS, "a third passed", "")]

    def test_every_verdict_survives_the_whole_wire_to_a_real_byte_stream(self):
        """Kills the six mutations 236 tests missed in cycle 9 (deleting the WARN line
        from the printer, deleting the hint block, `return 0` instead of `1 if fails`,
        truncating the results list, dropping the encoding hop, printing the icon
        without the status) and the three cycle 10 added one hop out: suppressing the
        `[PASS]` marker, swapping the FAIL and WARN labels onto each other's rows, and
        printing every row's neighbour's hint. The last two are why this asserts BY
        KEY: both keep every marker and every hint present in the blob."""
        results = self.wire()
        rc, out = run_main(stub_checks(results))
        self.assertEqual(rc, 1, "a FAIL has to leave a non-zero exit; ai-sync reads it")
        rows = parse_human(out)
        self.assertEqual(set(rows), {r.key for r in results},
                         f"every check's name reaches the reader: {out!r}")
        for r in results:
            got = rows[r.key]
            self.assertEqual(got["status"], r.status,
                             "the status belongs to THIS row, not to a neighbour")
            self.assertEqual(got["message"], r.message)
            self.assertEqual(got["hint"], r.hint,
                             "a FAIL or WARN hint is not decoration, and a PASS has "
                             "none to print")
        self.assertEqual(parse_summary(out), {"passed": 3, "warn": 1, "fail": 2},
                         "the footer is the line a hurried reader trusts, and it was "
                         "the last thing the printer emits with nothing watching it")

    def test_a_warn_only_run_exits_zero(self):
        """`rc == 1` on the fixture above is also satisfied by counting WARN as a
        failure, which contradicts the module docstring's "WARN never fails the run"
        and would block every push on a check that only asked a human to look."""
        results = [doctor.Result("stub-warn", doctor.WARN, "the stub warned", "look"),
                   doctor.Result("stub-pass", doctor.PASS, "the stub passed", "")]
        rc, out = run_main(stub_checks(results))
        self.assertEqual(rc, 0, "a WARN is not a failure")
        rows = parse_human(out)
        self.assertEqual(rows["stub-warn"]["status"], doctor.WARN)
        self.assertEqual(rows["stub-pass"]["status"], doctor.PASS)

    def test_the_json_surface_carries_the_whole_row_and_the_summary(self):
        """The machine-readable side, asserted whole. Key/status/message alone left
        `hint` droppable from `to_dict` and the `warn`/`fail` summary counts
        swappable, both silent.

        The expected row is written out LITERALLY rather than compared against
        `r.to_dict()`. Comparing the output of the function under test against that
        same function is not an assertion: dropping `hint` from `to_dict` changes
        both sides and the equality holds. The control caught this one in the test
        written to kill it, which is the same shape as everything else in this file.
        """
        results = self.wire()
        rc, out = run_main(stub_checks(results), argv=("brain_doctor.py", "--json"))
        self.assertEqual(rc, 1)
        doc = json.loads(out)
        got = {c["key"]: c for c in doc["checks"]}
        self.assertEqual(set(got), {r.key for r in results},
                         "every check reaches the JSON consumer too, PASS included")
        for r in results:
            self.assertEqual(got[r.key],
                             {"key": r.key, "status": r.status, "message": r.message,
                              "hint": r.hint},
                             "the whole row, hint included")
        self.assertEqual(doc["summary"], {"passed": 3, "warn": 1, "fail": 2},
                         "the summary counts are not interchangeable")

    def test_run_all_forwards_the_fix_flag_it_was_given(self):
        """`out = fn(True)` inside `run_all` survived every test in this file. A
        read-only doctor run would then perform repairs nobody asked for, which is
        this tool's whole contract with the operator: `--fix` is opt-in."""
        seen = []

        def recorder(fix):
            seen.append(fix)
            return doctor.Result("stub-fix", doctor.PASS, f"called with fix={fix}", "")

        rc, out = run_main([("stub-fix", recorder)])
        self.assertEqual(seen, [False], "a bare run must never repair anything")
        self.assertEqual(rc, 0)
        self.assertIn("fix=False", parse_human(out)["stub-fix"]["message"])
        rc, out = run_main([("stub-fix", recorder)], argv=("brain_doctor.py", "--fix"))
        self.assertEqual(seen, [False, True], "and --fix has to actually arrive")
        self.assertIn("fix=True", parse_human(out)["stub-fix"]["message"])

    def test_a_check_that_raises_becomes_a_fail_row(self):
        """`run_all`'s per-check crash handler was unpinned: reporting PASS for a
        check that raised would turn every crash into a green run, which is the
        loudest possible version of the silence this whole PR is about."""
        def boom(fix):
            raise RuntimeError("the stub exploded")

        rc, out = run_main([("stub-boom", boom),
                            ("stub-pass", lambda fix: doctor.Result(
                                "stub-pass", doctor.PASS, "the stub passed", ""))])
        self.assertEqual(rc, 1, "a crashed check fails the run")
        rows = parse_human(out)
        self.assertEqual(rows["stub-boom"]["status"], doctor.FAIL)
        self.assertIn("the stub exploded", rows["stub-boom"]["message"],
                      "the exception text is what a reader debugs from")
        self.assertEqual(rows["stub-pass"]["status"], doctor.PASS,
                         "one bad check never takes the rest of the run with it")

    def test_a_check_returning_two_results_yields_both(self):
        """Four checks in CHECKS return lists. Keeping only the first Result of one
        would silently halve `sync-targets` or the RULE #1 registry rows."""
        pair = [doctor.Result("stub-one", doctor.PASS, "the first row", ""),
                doctor.Result("stub-two", doctor.FAIL, "the second row", "fix the second")]
        rc, out = run_main([("stub-list", lambda fix: list(pair))])
        self.assertEqual(rc, 1, "the FAIL is in the SECOND Result of the list")
        rows = parse_human(out)
        self.assertEqual(set(rows), {"stub-one", "stub-two"})
        self.assertEqual(rows["stub-two"]["hint"], "fix the second")

    def test_the_gate_receipt_surface_runs_the_real_gate_check(self):
        """`--gate-receipt` is what `.githooks/pre-push` runs, and it is its only
        other reader. Returning a hardcoded PASS without calling
        `check_gate_liveness` survived: no test ran this surface at all. The receipt
        is written inside that function, so calling it is the invariant here."""
        calls = []

        def stub(fix):
            calls.append(fix)
            return doctor.Result("gate-liveness", doctor.FAIL,
                                 "the stub gate check ran", "look at the gates")

        real = doctor.check_gate_liveness
        doctor.check_gate_liveness = stub
        self.addCleanup(lambda: setattr(doctor, "check_gate_liveness", real))
        rc, out = run_main(stub_checks(self.wire()),
                           argv=("brain_doctor.py", "--gate-receipt"))
        self.assertEqual(calls, [False], "the real gate check has to be the one that ran")
        rows = parse_human(out)
        self.assertEqual(set(rows), {"gate-liveness"},
                         "--gate-receipt runs ONLY the gate check, never the rest")
        self.assertEqual(rows["gate-liveness"]["status"], doctor.FAIL)
        self.assertEqual(rc, 1, "pre-push has to be able to block on it")

    def test_the_registry_surface_runs_all_three_registry_checks(self):
        """`--registry` is the other pre-push surface. Dropping
        `check_orphan_hooks` from it survived, and an orphan hook is a mechanism
        RULE #1 says cannot exist."""
        for name, key in (("check_registry", "reg-stub"),
                          ("check_naming", "naming-stub"),
                          ("check_orphan_hooks", "orphan-stub")):
            real = getattr(doctor, name)
            setattr(doctor, name,
                    (lambda k: (lambda fix: [doctor.Result(k, doctor.PASS,
                                                           f"{k} ran", "")]))(key))
            self.addCleanup(lambda n=name, r=real: setattr(doctor, n, r))
        rc, out = run_main(stub_checks(self.wire()), argv=("brain_doctor.py", "--registry"))
        self.assertEqual(rc, 0)
        rows = parse_human(out)
        self.assertEqual(set(rows),
                         {"reg-stub", "naming-stub", "orphan-stub"},
                         "all three, and nothing from CHECKS")

    def test_the_registry_surface_can_still_block_a_push(self):
        """Running the three checks is not the invariant. `.githooks/pre-push:251`
        reads this surface by EXIT CODE alone, so forcing every registry row to
        PASS makes it silently stop blocking, and that survived all 248 tests
        (QA cycle 11). Its sibling above asserted the checks ran and stopped one
        step short of what the only consumer reads.
        """
        for name, key in (("check_registry", "reg-stub"),
                          ("check_naming", "naming-stub"),
                          ("check_orphan_hooks", "orphan-stub")):
            status = doctor.FAIL if key == "orphan-stub" else doctor.PASS
            real = getattr(doctor, name)
            setattr(doctor, name,
                    (lambda k, st: (lambda fix: [doctor.Result(k, st, f"{k} ran", "fix it")]))(key, status))
            self.addCleanup(lambda n=name, r=real: setattr(doctor, n, r))
        rc, out = run_main(stub_checks(self.wire()), argv=("brain_doctor.py", "--registry"))
        self.assertEqual(rc, 1, "a registry FAIL has to reach pre-push as a non-zero exit")
        self.assertEqual(parse_human(out)["orphan-stub"]["status"], doctor.FAIL)


if __name__ == "__main__":
    unittest.main()
