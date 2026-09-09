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
import pty
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

    def write_refusal(self, kind: str, when: float, nested: bool = False) -> None:
        """One transcript record in the harness's own shape.

        TOP LEVEL, next to `type` and `timestamp`. The fixture used to bury
        `toolDenialKind` inside `message.content[0]`, and every real record on this
        machine carries it at the record's root: measured, 226 of 226 in
        ~/.claude/projects, zero nested. `_denial_kind` walks the record so both
        shapes are found and nothing broke, which is exactly why the drift was
        invisible: the shape under test was not the harness's shape, so the coverage
        the suite claimed over the real record was coverage of an invented one
        (QA cycle 13). `nested=True` keeps a case for the walk itself, and it is
        labelled as tolerance rather than evidence, because no record in the
        measurement had that shape.
        """
        from datetime import datetime, timezone
        stamp = datetime.fromtimestamp(when, timezone.utc).isoformat().replace("+00:00", "Z")
        path = self.harness / "projects" / "slug" / "sess" / "transcript.jsonl"
        rec = {"type": "user", "timestamp": stamp,
               "message": {"role": "user",
                           "content": [{"type": "tool_result", "is_error": True,
                                        "content": "denied"}]}}
        if nested:
            rec["message"]["content"][0]["toolDenialKind"] = kind
        else:
            rec["toolDenialKind"] = kind
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

    def test_a_refusal_exactly_at_the_arm_date_is_counted(self):
        """The boundary itself, on the harness side, so the two sides can be asserted
        to agree. `ts < armed_at` skips, which means the instant the hook was armed
        COUNTS. Nothing pinned that: flipping it to `<=` left every test green, and
        the journal side has the mirror hole (see the reflex sibling in
        `TestTheJournalScanActuallyRuns`). A boundary each side reads differently is
        a comparison of two windows that differ by one record."""
        armed, _, _, _ = doctor._harness_refusals_since_hook(time.time() - 7 * 86400)
        self.assertIsNotNone(armed)
        self.write_refusal("automode-blocked", armed)
        _, seen, _, _ = doctor._harness_refusals_since_hook(time.time() - 7 * 86400)
        self.assertEqual(seen, 1, "the arm instant is inside the window, not outside")

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
        _, seen, other, _ = doctor._harness_refusals_since_hook(time.time() - 7 * 86400)
        self.assertEqual(seen, 0, "a refusal the hook never sees is not its failure")
        # `other` had NOTHING asserting it anywhere: deleting `other += 1` from the
        # collector left all 249 tests green while the only new verdict this check
        # introduced lost its entire input, and the WARN became unreachable by data
        # rather than by logic (QA cycle 13). A count that decides a status is not
        # allowed to be the one number nobody reads.
        self.assertEqual(other, 2, "a refusal outside the family is counted, not dropped")
        for kind in ("automode-blocked", "automode-unavailable", "automode-parsing-error"):
            self.write_refusal(kind, armed + 60)
        _, seen, other, _ = doctor._harness_refusals_since_hook(time.time() - 7 * 86400)
        self.assertEqual(seen, 3)
        self.assertEqual(other, 2, "the family the hook fires for does not join `other`")

    def test_a_nested_record_is_still_counted_end_to_end(self):
        """The walk is only worth its comment if the COUNTER sees a nested record
        too, not just the predicate. No record on this machine has that shape, so
        this is the one place the tolerance is exercised at all."""
        armed, _, _, _ = doctor._harness_refusals_since_hook(time.time() - 7 * 86400)
        self.write_refusal("automode-blocked", armed + 60, nested=True)
        _, seen, _, _ = doctor._harness_refusals_since_hook(time.time() - 7 * 86400)
        self.assertEqual(seen, 1)

    def test_the_key_is_found_wherever_it_sits(self):
        """Walked, not path-indexed. A fixed path would stop matching the day the
        harness moves the field, which is exactly the silence this check exists to
        break.

        TOLERANCE, not evidence. Measured in ~/.claude/projects: 226 of 226 records
        carry `toolDenialKind` at the record root and none carries it nested, so this
        pins what the walk BUYS if the harness ever moves the field, and the sandbox
        fixture writes the shape the harness actually writes (QA cycle 13)."""
        flat = {"type": "user", "toolDenialKind": "automode-blocked",
                "message": {"content": [{"type": "tool_result"}]}}
        self.assertTrue(doctor._carries_automode_denial(flat),
                        "the shape every real record on this machine has")
        deep = {"a": [{"b": {"c": {"toolDenialKind": "automode-blocked"}}}]}
        self.assertTrue(doctor._carries_automode_denial(deep))
        self.assertFalse(doctor._carries_automode_denial({"toolDenialKind": "permission-rule"}))
        self.assertFalse(doctor._carries_automode_denial({"toolDenialKind": 42}))
        self.assertFalse(doctor._carries_automode_denial([]))


class TestEachNoWindowRoadNamesItself(DenyCoverageCase):
    """Seven roads end at "no window" and they are not the same news. A shallow clone
    is permanent for that checkout, a missing projects dir is a config mismatch, an
    unreadable subtree or an unreadable FILE is transient or hostile, a checkout with
    no such commit is a fresh one, a git that exits non-zero is a broken environment,
    and an arm date in the future is a clock. Rendering them as one non-event is the
    collapse this whole check exists to undo, reappearing one level up (QA cycle 6).

    Three of the seven were roads that answered under someone else's name, or under
    none. `git rev-parse` answering non-zero (128 for not a repository or for
    dubious ownership; 127 for a git that is not on PATH, which does not exit at
    all and is not 128: subprocess raises and `run` converts it) leaves stdout
    empty, and `!= "false"` read every one of them as a
    grafted history; an unreadable transcript FILE was skipped by a bare `continue`,
    so the count came back confident and unread; a future-dated arm commit skipped
    every record and the row said "unexercised" (QA cycle 13). A wrong cause is worse
    than no cause, which is the argument this PR is built on, so the wrong ones are
    tested exactly like the right ones.
    """

    def _why(self):
        armed, _, _, why = doctor._harness_refusals_since_hook(time.time() - 7 * 86400)
        # Asserted at COLLECTION time, not after: a road that quietly stopped being a
        # no-window road would otherwise donate a stale cause to the distinctness
        # check and the set would still look healthy.
        self.assertIsNone(armed, "this road must actually reach the no-window return")
        self.assertTrue(why, "and it must name itself on the way")
        return why

    def test_an_answer_that_is_neither_true_nor_false_says_so(self):
        """A current `git rev-parse --is-shallow-repository` prints exactly `true` or
        `false`, so this road needs a git that answers something else. It is reachable
        for real, and the reason first written here was measurably wrong: it said a git
        too old to know the flag exits non-zero. It does not. `rev-parse` ECHOES an
        unknown `--` argument back and exits 0, measured on git 2.43 inside a real
        repo:

            $ git rev-parse --is-shallow-repositoryx
            --is-shallow-repositoryx
            rc=0

        So a git predating the flag lands here with the flag itself as the answer,
        which is neither true nor false, and the branch is a real road rather than a
        guard for a hypothetical wrapper. The wrong reason is the same defect class
        this PR is about, in prose instead of code. Stubbed at `doctor.run`, narrowly:
        only the is-shallow call is answered, everything else goes to the real one, or
        the stub would also be answering the `git log` this road never reaches.
        """
        # MEASURED, not asserted in prose. The reason this branch exists was wrong in
        # this very docstring for a cycle, so the claim behind it is checked against
        # the git on this machine rather than restated: an unknown `--` flag comes
        # back on stdout with rc 0, which is what puts a git predating the flag here.
        echoed = doctor.run(["git", "rev-parse", "--is-shallow-repositoryx"],
                            cwd=self.brain)
        self.assertEqual(echoed.returncode, 0,
                         "git exited non-zero on an unknown rev-parse flag, so the "
                         "reason given for this road no longer holds on this git")
        self.assertEqual((echoed.stdout or "").strip(), "--is-shallow-repositoryx",
                         "an unknown flag is echoed back, and that echo is the answer "
                         "that is neither true nor false")

        real_run = doctor.run

        def fake(args, cwd=None):
            if args[:2] == ["git", "rev-parse"]:
                return subprocess.CompletedProcess(args, 0, "maybe\n", "")
            return real_run(args, cwd)

        doctor.run = fake
        self.addCleanup(lambda: setattr(doctor, "run", real_run))
        why = self._why()
        self.assertIn("neither true nor false", why)
        self.assertIn("'maybe'", why, "the reader gets the answer git actually gave")
        self.assertNotIn("grafted history", why,
                         "an unknown answer is not a shallow clone, which is the "
                         "mislabelling this road was split out of")

    def test_the_dubious_ownership_cause_is_the_fatal_line_not_the_remedy(self):
        """The git-failed road named a COMMAND where the cause belongs.

        `because = detail[-1]` took the last stderr line, and git writes the
        diagnosis first and the remedy last. Measured end to end here, with
        `GIT_TEST_ASSUME_DIFFERENT_OWNER=1`, which is how git's own suite forces the
        ownership check without needing a second uid. Before the fix the sentence
        read:

            git itself failed on this checkout (git config --global --add
            safe.directory <path>)

        A remedy printed as a cause is the exact defect this PR argues against, on a
        road this PR added. `test_every_road_gives_its_own_cause` could not see it:
        it reaches this road through a directory that is no repository at all, whose
        stderr is ONE line, so the first and the last are the same and only the road
        token was asserted. Hence a case with a multi-line stderr, asserting the
        CAUSE and refusing the remedy.
        """
        notarepo = self.tmp / "dubious"
        (notarepo / "scripts").mkdir(parents=True)
        env = dict(os.environ)
        for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_PREFIX",
                  "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY", "GIT_NAMESPACE"):
            env.pop(k, None)
        subprocess.run(["git", "-C", str(notarepo), "init", "-q"], check=True,
                       capture_output=True, env=env)
        saved = os.environ.get("GIT_TEST_ASSUME_DIFFERENT_OWNER")
        os.environ["GIT_TEST_ASSUME_DIFFERENT_OWNER"] = "1"
        self.addCleanup(lambda: os.environ.__setitem__(
            "GIT_TEST_ASSUME_DIFFERENT_OWNER", saved) if saved is not None
            else os.environ.pop("GIT_TEST_ASSUME_DIFFERENT_OWNER", None))
        probe = doctor.run(["git", "rev-parse", "--is-shallow-repository"], cwd=notarepo)
        # rc 124 is a HANG, and the skip below would have absorbed it as "this git
        # did not run the ownership check" — a wrong reason for a skip, inside the
        # test against wrong reasons, and the same blindness as a test that only
        # asserts the child came back.
        self.assertNotEqual(probe.returncode, 124,
                            "the probe git never answered; that is a hang, not a "
                            "git that skipped the ownership check")
        if "dubious ownership" not in (probe.stderr or ""):
            # The skip reason names what was MEASURED, not a diagnosis nobody
            # checked. The first one asserted that this git ignores
            # GIT_TEST_ASSUME_DIFFERENT_OWNER, and on a de_DE machine that was
            # false: git honoured it and answered `Schwerwiegend: detected dubious
            # ownership`, so the phrase was missing because it was TRANSLATED, not
            # because the check had not fired. A wrong cause inside the test that
            # guards against wrong causes, skipping on precisely the machine where
            # the defect lives. That road is shut now (`run` pins LC_ALL=C on git,
            # see test_git_answers_in_c_whatever_the_ambient_locale), so what is
            # left here is a git that really did not run the ownership check, and
            # the reader gets git's own words for it either way.
            self.skipTest(
                "no `dubious ownership` diagnosis came back from this git, so the "
                "ownership check did not fire here (a git too old for "
                "GIT_TEST_ASSUME_DIFFERENT_OWNER, or one that already owns the "
                "path). git said: "
                + (repr((probe.stderr or "").strip()[:200]) or "nothing")
                + f" (rc={probe.returncode}). The recorded-stderr sibling still "
                  "covers the selection.")
        doctor.CLAUDE_DIR = notarepo
        why = self._why()
        self.assertIn("git itself failed", why, "still the git-failed road")
        self.assertIn("dubious ownership", why,
                      "the reader gets git's own diagnosis")
        self.assertNotIn("safe.directory", why,
                         "a remedy printed where the cause belongs is the wrong-cause "
                         "defect this whole check is about")

    def test_the_recorded_git_stderr_picks_the_diagnosis_over_the_last_line(self):
        """The same selection, off a RECORDED stderr, so it is asserted on every
        machine including one whose git ignores GIT_TEST_ASSUME_DIFFERENT_OWNER.

        `scripts/tests/fixtures/git-dubious-ownership.stderr` is verbatim git output,
        captured from `git rev-parse --is-shallow-repository` on git 2.43 in a repo
        with that variable set. Not hand-typed: the shape under test has to be the
        shape git writes, which is the drift QA cycle 13 found in the transcript
        fixture one class over.
        """
        recorded = (BRAIN / "scripts" / "tests" / "fixtures"
                    / "git-dubious-ownership.stderr").read_text(encoding="utf-8")
        self.assertGreater(len(recorded.strip().splitlines()), 1,
                           "a one-line stderr cannot tell first from last")
        because = doctor.git_failure_cause(recorded, 128)
        self.assertTrue(because.startswith("fatal:"), because)
        self.assertIn("dubious ownership", because)
        self.assertNotIn("safe.directory", because)

    def test_a_git_that_says_neither_fatal_nor_error_still_names_something(self):
        """The fallback, which is what keeps every road named. A wrapper on PATH, a
        shim, or a localised message this does not recognise gets the last non-empty
        line rather than an empty parenthesis, and a git that said nothing at all
        gets its exit code."""
        self.assertEqual(doctor.git_failure_cause("something odd\nand a last word\n", 3),
                         "and a last word")
        self.assertEqual(doctor.git_failure_cause("", 129), "exit 129")
        self.assertEqual(doctor.git_failure_cause("   \n\n", 129), "exit 129")

    def test_an_error_line_is_a_diagnosis_just_like_a_fatal_one(self):
        """`error:` is half the selection and no fixture opened with it, so deleting
        it from the tuple changed nothing any test could see. git writes `error:` for
        the recoverable half of the same convention (a config file it could not lock,
        a ref it could not update) and then keeps talking, so the last line is as
        wrong a cause there as it is after a `fatal:`."""
        stderr = ("error: could not lock config file .git/config: File exists\n"
                  "Please make sure the file is writable and try again.\n")
        self.assertEqual(doctor.git_failure_cause(stderr, 255),
                         "error: could not lock config file .git/config: File exists")

    def test_a_diagnosis_that_ends_in_a_colon_carries_its_next_line(self):
        """One real git message puts the noun on the LINE AFTER the diagnosis, and
        the cause then arrives without the thing that caused it. Verbatim git 2.43,
        in a repo with `core.repositoryformatversion=1` and an unknown
        `extensions.bogus`:

            fatal: unknown repository extension found:
            <tab>bogus

        `fatal: unknown repository extension found:` names a class of failure and not
        the instance of it, which is a smaller copy of the collapse this check
        undoes. Recorded rather than hand-typed, for the reason the sibling fixture
        states: the shape under test has to be the shape git writes.
        """
        recorded = (BRAIN / "scripts" / "tests" / "fixtures"
                    / "git-unknown-extension.stderr").read_text(encoding="utf-8")
        self.assertTrue(recorded.strip().splitlines()[0].endswith(":"),
                        "this fixture is only interesting while git leaves the "
                        "diagnosis hanging on a colon")
        because = doctor.git_failure_cause(recorded, 128)
        self.assertEqual(because, "fatal: unknown repository extension found: bogus")
        # And the join is scoped to a continuation: the ownership fixture's fatal
        # line ends in a quoted path, so nothing is appended and the remedy two
        # lines below it stays out.
        ownership = (BRAIN / "scripts" / "tests" / "fixtures"
                     / "git-dubious-ownership.stderr").read_text(encoding="utf-8")
        self.assertNotIn("safe.directory", doctor.git_failure_cause(ownership, 128))

    def test_git_answers_in_c_whatever_the_ambient_locale(self):
        """`fatal:` and `error:` are TRANSLATED, so the selection above is sound only
        while git speaks C. It does not by default: git ships message catalogs, and
        its own po files give `Schwerwiegend: ` for de and `fatal : ` (a space before
        the colon) for fr, which match neither prefix. Nothing matches, the fallback
        takes the last line, and the row prints the remedy as the cause again, which
        is the defect this file exists to remove arriving one layer out.

        Asserted on the CHILD's environment rather than on a translated message,
        because a message needs a `.mo` file this distro does not ship and the pin
        has to be provable on every machine, not only where the defect bites. A git
        alias with `!` runs a shell, so this is git handing back what it actually
        got. The localised end-to-end sibling covers the rest of the road.
        """
        saved = {k: os.environ.get(k) for k in ("LC_ALL", "LANG", "LANGUAGE")}

        def restore():
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        self.addCleanup(restore)
        os.environ["LC_ALL"] = "de_DE.UTF-8"
        os.environ["LANG"] = "de_DE.UTF-8"
        os.environ["LANGUAGE"] = "de"

        cp = doctor.run(["git", "-c",
                         'alias.showlocale=!printf "%s\n" "${LC_ALL-unset}"',
                         "showlocale"], cwd=self.brain)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertEqual((cp.stdout or "").strip(), "C",
                         "git ran under the ambient locale, so it is free to "
                         "translate `fatal:` and the cause selection reads the "
                         "remedy again")

        # Scoped to git, and the scope is the point: pinning C on every subprocess
        # would silently change what every other script in this brain prints.
        other = doctor.run([sys.executable, "-c",
                            "import os;print(os.environ.get('LC_ALL'))"])
        self.assertEqual((other.stdout or "").strip(), "de_DE.UTF-8",
                         "the pin reached a non-git command; what is being pinned "
                         "is git's message catalog, not the whole doctor")

        # And keyed on the BASENAME, which nothing said. Replacing the basename
        # test with `args[0] == "git"` passed every assertion above while an
        # absolute path went unpinned, and an absolute path is how a doctor on a
        # machine with two gits would call the one it means.
        gitpath = shutil.which("git")
        self.assertTrue(gitpath, "no git on PATH, so the basename cannot be probed")
        absolute = doctor.run([gitpath, "-c",
                               'alias.showlocale=!printf "%s\n" "${LC_ALL-unset}"',
                               "showlocale"], cwd=self.brain)
        self.assertEqual((absolute.stdout or "").strip(), "C",
                         "git called by its absolute path ran under the ambient "
                         "locale: the pin is testing the whole argv, not the name")

        # The other half of the same guard, and the reason it is a basename and not
        # a path: a wrapper on PATH under ANOTHER name is deliberately NOT pinned,
        # because nothing here calls git under another name and a name-blind pin
        # would land on the helpers this file runs, several of which print Spanish.
        wrapper = self.tmp / "mygit"
        wrapper.write_text("#!/bin/sh\nprintf '%s\\n' \"${LC_ALL-unset}\"\n",
                           encoding="utf-8")
        wrapper.chmod(0o755)
        aliased = doctor.run([str(wrapper)])
        self.assertEqual((aliased.stdout or "").strip(), "de_DE.UTF-8",
                         "a wrapper under another name got the git pin, so the "
                         "guard is not the basename it is documented to be")

    def test_a_localised_git_still_names_the_diagnosis(self):
        """The same pin, end to end, out of the SENTENCE a reader gets.

        Reproduced the way it was found: compile a `de` catalog carrying git's own
        `fatal: ` msgid and point GIT_TEXTDOMAINDIR at it. Before the pin, on this
        machine, the row read

            git itself failed on this checkout (git config --global --add
            safe.directory <path>)

        This one can skip and says exactly what it could not do when it does: it
        needs `msgfmt` and a generated de_DE locale. Its unconditional sibling above
        asserts the same pin off the child's environment, so the anchor does not
        vanish with the skip.
        """
        if not shutil.which("msgfmt"):
            self.skipTest("no msgfmt on PATH, so no catalog can be compiled here; "
                          "test_git_answers_in_c_whatever_the_ambient_locale asserts "
                          "the pin without one")
        locales = subprocess.run(["locale", "-a"], capture_output=True, text=True)
        have_de = any(ln.strip().lower().startswith("de_de.utf8")
                      for ln in (locales.stdout or "").splitlines())
        if not have_de:
            self.skipTest("no de_DE.utf8 locale is generated here, so gettext falls "
                          "back to C and nothing would be translated; "
                          "test_git_answers_in_c_whatever_the_ambient_locale asserts "
                          "the pin without one")
        podir = self.tmp / "locale"
        (podir / "de" / "LC_MESSAGES").mkdir(parents=True)
        po = self.tmp / "git.po"
        po.write_text(
            'msgid ""\nmsgstr ""\n'
            '"MIME-Version: 1.0\\n"\n'
            '"Content-Type: text/plain; charset=UTF-8\\n"\n'
            '"Content-Transfer-Encoding: 8bit\\n"\n\n'
            'msgid "fatal: "\nmsgstr "Schwerwiegend: "\n\n'
            'msgid "error: "\nmsgstr "Fehler: "\n',
            encoding="utf-8")
        built = subprocess.run(
            ["msgfmt", "-o", str(podir / "de" / "LC_MESSAGES" / "git.mo"), str(po)],
            capture_output=True, text=True)
        self.assertEqual(built.returncode, 0, built.stderr)

        notarepo = self.tmp / "dubious-de"
        (notarepo / "scripts").mkdir(parents=True)
        env = dict(os.environ)
        for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_PREFIX",
                  "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY", "GIT_NAMESPACE"):
            env.pop(k, None)
        subprocess.run(["git", "-C", str(notarepo), "init", "-q"], check=True,
                       capture_output=True, env=env)

        saved = {k: os.environ.get(k) for k in
                 ("LC_ALL", "LANG", "GIT_TEXTDOMAINDIR",
                  "GIT_TEST_ASSUME_DIFFERENT_OWNER")}

        def restore():
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        self.addCleanup(restore)
        os.environ["LC_ALL"] = "de_DE.utf8"
        os.environ["LANG"] = "de_DE.utf8"
        os.environ["GIT_TEXTDOMAINDIR"] = str(podir)
        os.environ["GIT_TEST_ASSUME_DIFFERENT_OWNER"] = "1"

        # The catalog has to actually bite, or this test would pass on the broken
        # code by translating nothing. Measured through a raw subprocess, outside
        # `run`, which is the thing under test.
        raw = subprocess.run(["git", "-C", str(notarepo), "rev-parse",
                              "--is-shallow-repository"],
                             capture_output=True, text=True, env=dict(os.environ))
        if "Schwerwiegend:" not in (raw.stderr or ""):
            self.skipTest("the compiled catalog did not translate this git's prefix "
                          f"(git said {(raw.stderr or '').strip()[:120]!r}), so a "
                          "localised git cannot be reproduced here")

        doctor.CLAUDE_DIR = notarepo
        why = self._why()
        self.assertIn("git itself failed", why)
        self.assertIn("fatal:", why,
                      "under a translated git nothing matched and the fallback "
                      "handed back the last line, which is the remedy")
        self.assertNotIn("safe.directory", why)

    def test_a_missing_git_is_a_named_cause_not_a_traceback(self):
        """`run` promises never to raise on non-zero and it keeps that promise, but a
        binary that is not there never exits at all: subprocess raises
        FileNotFoundError before a child exists. Through `run_all` that became

            FAIL check crashed: [Errno 2] No such file or directory: 'git'

        a traceback where a cause belongs, arriving by the one road that never
        reaches the parser. Nobody saw it because another FAIL short-circuited before
        this road ran.
        """
        # Caught rather than left to propagate: an unhandled raise reports as an
        # ERROR with a traceback, which is the very shape under test, and a reader
        # scanning the output cannot tell a broken test from a caught defect. Red
        # with a sentence instead.
        try:
            cp = doctor.run(["git-this-binary-does-not-exist", "--version"])
        except OSError as exc:
            self.fail(f"run raised {type(exc).__name__} ({exc}) instead of "
                      f"answering; a binary that is not there never exits, so the "
                      f"caller gets a traceback where a cause belongs")
        self.assertEqual(cp.returncode, 127,
                         "a missing binary has to be ANSWERED, with the shell's own "
                         "not-found code, not raised past the caller")
        self.assertIn("git-this-binary-does-not-exist", cp.stderr)
        self.assertEqual(cp.stdout, "", "no child ran, so there is no output")

        # And out of the sentence, with git genuinely off PATH. PATH is
        # process-wide, so it is restored the way CLAUDE_CONFIG_DIR is.
        saved_path = os.environ.get("PATH")

        def restore_path():
            if saved_path is None:
                os.environ.pop("PATH", None)
            else:
                os.environ["PATH"] = saved_path
        self.addCleanup(restore_path)
        os.environ["PATH"] = str(self.tmp / "no-binaries-here")
        try:
            why = self._why()
        except OSError as exc:
            self.fail(f"the road raised {type(exc).__name__} ({exc}) instead of "
                      f"naming a cause; through run_all that is `FAIL check crashed`")
        self.assertIn("git itself failed", why, "still the git-failed road")
        self.assertIn("No such file or directory", why,
                      "the reader gets the reason git could not run")
        self.assertNotIn("Traceback", why)

    def test_the_class_of_exec_failures_answers_not_only_three_of_its_members(self):
        """FileNotFoundError, PermissionError and NotADirectoryError were named one
        by one, and naming members leaves the rest of the class raising.

        Measured on this machine, a file with junk bytes and no shebang:

            run(['<that file>'])  ->  OSError, errno 8 (ENOEXEC)

        which is a git wrapper saved without a shebang, or a wrong-arch binary on a
        shared mount, and it still handed the caller the traceback the clause says it
        removes. ELOOP and E2BIG are the same shape. `except OSError` with
        `127 if errno == ENOENT else 126` closes the class and matches what a shell
        returns for each.

        126 had no anchor at all: deleting the branch, or swapping the two codes,
        changed nothing any test could see (mutants M05 and M07). Both codes are
        pinned here, off real files.
        """
        noexec = self.tmp / "not-a-binary"
        noexec.write_bytes(b"\x7fELF\x00 this is not a program\n")
        noexec.chmod(0o755)
        try:
            cp = doctor.run([str(noexec)])
        except OSError as exc:
            self.fail(f"run raised {type(exc).__name__} (errno {exc.errno}) instead "
                      f"of answering; exec failed before a child existed, which is "
                      f"the class the three named members belong to")
        self.assertEqual(cp.returncode, 126,
                         "a file that cannot be exec'd is the shell's 126, not 127: "
                         "it is there, it just will not run")
        self.assertIn("not-a-binary", cp.stderr)
        self.assertNotIn("Traceback", cp.stderr)

        # The other member of the 126 branch, and the discriminator against 127.
        unreadable = self.tmp / "no-permission"
        unreadable.write_text("#!/bin/sh\ntrue\n", encoding="utf-8")
        unreadable.chmod(0o644)
        denied = doctor.run([str(unreadable)])
        self.assertEqual(denied.returncode, 126,
                         "a binary that is there and not executable is 126")
        missing = doctor.run([str(self.tmp / "no-such-binary-at-all")])
        self.assertEqual(missing.returncode, 127,
                         "and only a binary that is NOT THERE is 127; collapsing "
                         "the two tells the reader the wrong thing about a file "
                         "that exists")

    def test_the_name_in_the_sentence_is_the_one_the_os_blamed(self):
        """`args[0]` was printed as the thing that failed, and it is not always the
        thing that failed. Measured:

            run(['git','--version'], cwd='<directory that does not exist>')
              ->  rc=127  stderr='git: No such file or directory'

        The git exists and is fine. The cwd is what is missing, and the exception
        carries that truth in `exc.filename`. A wrong cause inside the fix for wrong
        causes. Reach is nil today, every `cwd=` in this file is CLAUDE_DIR derived
        from `__file__`, and the sentence is wrong anyway, which is the whole
        argument this PR is built on.
        """
        gone = self.tmp / "this-cwd-does-not-exist"
        cp = doctor.run(["git", "--version"], cwd=gone)
        self.assertEqual(cp.returncode, 127)
        self.assertIn(str(gone), cp.stderr,
                      "the reader is told what the OS actually blamed")
        self.assertFalse(cp.stderr.startswith("git:"),
                         "the row blames git, which is installed and fine, for a "
                         "directory that is not there")

    def test_a_call_that_never_answers_is_a_named_cause_too(self):
        """No cause at all is the same reader-facing failure, one step further out.

        Three call sites reach the NETWORK (`ls-remote --tags`, `gh pr list`,
        `ls-remote --heads`). Over ssh with no agent git waits on a passphrase, over
        https on a username, and a host that drops the packets waits on the TCP
        stack: each one hangs the doctor and, through `.githooks/pre-push`, the push
        behind it, with no row and no exit code. Three guards, and each is asserted
        here rather than described.

        Not asserted, because it was measured FALSE and used to be claimed here: a
        repo mid-`git gc` does not wait. git 2.43 with `index.lock` and
        `packed-refs.lock` present answered `ls-remote` in 0.014s rc 0 and failed
        `add` in 9ms with `fatal: Unable to create ...: File exists.`
        """
        saved = doctor.RUN_TIMEOUT
        self.addCleanup(lambda: setattr(doctor, "RUN_TIMEOUT", saved))
        doctor.RUN_TIMEOUT = 1
        try:
            cp = doctor.run([sys.executable, "-c", "import time; time.sleep(30)"])
        except subprocess.TimeoutExpired:
            self.fail("run raised TimeoutExpired instead of answering; through "
                      "run_all a hang becomes `FAIL check crashed`, and before the "
                      "timeout it was not even that, it was a doctor that never "
                      "returned")
        self.assertEqual(cp.returncode, 124,
                         "a call killed for taking too long answers with the "
                         "timeout(1) convention, so it reads like every other rc")
        self.assertIn("no answer in 1s", cp.stderr)
        doctor.RUN_TIMEOUT = saved

        # The cheapest of the four guards, and a PARTIAL one on its own: nothing this
        # doctor spawns inherits fd 0, so it cannot eat the ref list `pre-push`
        # feeds this process. On its own it does NOT close /dev/tty (measured under
        # a pty: `sh -c 'read x </dev/tty'` with stdin=/dev/null blocked the full
        # 3s); `start_new_session` is what closes that, asserted separately below.
        if not Path("/proc/self/fd/0").exists():
            self.skipTest("no /proc on this platform, so fd 0 cannot be named")
        fd0 = doctor.run([sys.executable, "-c",
                          "import os;print(os.readlink('/proc/self/fd/0'))"])
        self.assertEqual(fd0.returncode, 0,
                         "rc 124 here is a hang, and its partial stdout would be "
                         "read as if the probe had answered")
        self.assertEqual((fd0.stdout or "").strip(), "/dev/null",
                         "a child inherited this process's stdin: a git that decides "
                         "to ask for a password will get an answer from whatever is "
                         "on the other end, or wait forever for one")

        # And git is told not to ask in the first place, which turns the wait into a
        # sentence instead of a 300-second silence.
        prompt = doctor.run(["git", "-c",
                             'alias.showprompt=!printf "%s\n" "${GIT_TERMINAL_PROMPT-unset}"',
                             "showprompt"], cwd=self.brain)
        self.assertEqual(prompt.returncode, 0, prompt.stderr)
        self.assertEqual((prompt.stdout or "").strip(), "0", prompt.stderr)

    def test_a_hang_that_had_already_spoken_is_read_not_raised(self):
        """The sibling above passes only because its child prints NOTHING.

        `TimeoutExpired.stdout` and `.stderr` are BYTES on POSIX no matter what
        `encoding=`/`text=` said, because those kwargs configure the decode that
        `communicate()` does on the way out and the timeout path raises before it
        runs. So a helper that printed one line and THEN hung handed `selftest_cause`
        bytes, `line.startswith("FAIL")` raised, and through the real check it came
        back as

            kernel-replay FAIL | check crashed: a bytes-like object is required, not 'str'

        a traceback where a cause belongs, produced by the function written to
        abolish tracebacks, on the COMMON member of the class: a hang that had
        already said something. Reproduced end to end before the fix by replacing
        `r__permission-denied__journal.py` with a print-then-sleep script and running
        the real `check_kernel_replay` with RUN_TIMEOUT=1.

        And the partial STDERR was thrown away entirely, which is the surviving
        mutant M25: the synthesised `no answer in Ns` sentence REPLACED whatever the
        child managed to say. For a git waiting on a passphrase those words are the
        diagnosis, so they are kept and the sentence goes after them.
        """
        saved = doctor.RUN_TIMEOUT
        self.addCleanup(lambda: setattr(doctor, "RUN_TIMEOUT", saved))
        doctor.RUN_TIMEOUT = 1
        speaks_then_hangs = (
            "import sys, time\n"
            "print('selftest FAIL: the violation fixture did not block')\n"
            "sys.stdout.flush()\n"
            "sys.stderr.write('warning: You appear to have cloned an empty repository.\\n')\n"
            "sys.stderr.flush()\n"
            "time.sleep(30)\n"
        )
        cp = doctor.run([sys.executable, "-c", speaks_then_hangs])
        self.assertEqual(cp.returncode, 124)
        self.assertIsInstance(cp.stdout, str,
                              "the partial output comes back as bytes from "
                              "TimeoutExpired; a caller that reads it with str "
                              "methods raises TypeError")
        self.assertIsInstance(cp.stderr, str)

        # The crash itself, at the call site that produced it.
        try:
            cause = doctor.selftest_cause(cp)
        except TypeError as e:  # pragma: no cover - the bug this test exists for
            self.fail(f"selftest_cause raised instead of naming a cause: {e}")
        self.assertEqual(cause, "selftest FAIL: the violation fixture did not block",
                         "a helper that marked its own failure before wedging is "
                         "named by its own verdict, not by the timeout sentence")

        # M25: the partial stderr survives instead of being replaced.
        self.assertIn("warning: You appear to have cloned an empty repository.",
                      cp.stderr,
                      "the only words the child got out before it was killed were "
                      "discarded; for a git waiting on a passphrase that is the "
                      "whole diagnosis")
        self.assertIn("no answer in 1s, killed", cp.stderr)
        self.assertLess(cp.stderr.index("cloned an empty repository"),
                        cp.stderr.index("no answer in 1s"),
                        "the synthesised sentence goes LAST so the `[-1]` fallback "
                        "lands on it only when the child marked nothing")

        # And the silent hang still falls back to the sentence, unchanged.
        quiet = doctor.run([sys.executable, "-c", "import time; time.sleep(30)"])
        self.assertEqual(quiet.returncode, 124)
        self.assertIn("no answer in 1s, killed", doctor.selftest_cause(quiet))

    def test_the_empty_stdin_is_devnull_and_not_an_empty_pipe(self):
        """`input=b""` also hands a child an empty stdin, and it is not the same
        thing.

        They are mutually exclusive in subprocess, so this is a real fork in the
        road and not a style choice, and they differ for a child that WRITES to
        fd 0. Measured: under `input=b""` fd 0 is the read end of a pipe, so
        `os.write(0, b'x')` raises `OSError 9 Bad file descriptor`; under DEVNULL it
        succeeds and the bytes are discarded. Several helpers this doctor runs are
        hooks that were written to talk back on whatever fd they were given, and a
        doctor that made them crash would be manufacturing the failures it reports.
        """
        writer = ("import os\n"
                  "try:\n"
                  "  os.write(0, b'x'); print('wrote')\n"
                  "except OSError as e:\n"
                  "  print('OSError %d' % e.errno)\n")
        started = time.time()
        cp = doctor.run([sys.executable, "-c", writer])
        # rc 0 EXPLICITLY, not "it came back". A child that hangs comes back too,
        # as rc 124 with the output it managed, and an assertion that only reads
        # stdout cannot tell the two apart.
        self.assertEqual(cp.returncode, 0,
                         f"rc {cp.returncode}: 124 here would be a hang wearing a "
                         f"result's clothes")
        self.assertLess(time.time() - started, 30,
                        "the child answered on its own, not because a ceiling fired")
        self.assertEqual((cp.stdout or "").strip(), "wrote",
                         "a child that writes to fd 0 got a pipe read end, not "
                         "/dev/null: under input=b'' this is OSError 9")

        # the other half of the fork, so the assertion above is a discriminator and
        # not a coincidence
        pipe_end = subprocess.run([sys.executable, "-c", writer],
                                  capture_output=True, input=b"")
        self.assertEqual(pipe_end.stdout.decode().strip(), "OSError 9")
        with self.assertRaises(ValueError):
            subprocess.run([sys.executable, "-c", "pass"], capture_output=True,
                           stdin=subprocess.DEVNULL, input=b"")

    def test_a_child_cannot_open_the_operators_terminal(self):
        """The channel `stdin=/dev/null` cannot cover, now covered by the session.

        `start_new_session=True` went in for the group kill, and it closes /dev/tty
        as a second effect worth pinning: a child in a fresh session has no
        controlling terminal, so the open fails outright. Measured under a pty, the
        same `read x </dev/tty` that blocked the full 3s with only stdin on
        /dev/null returned in 0.05s with `cannot open /dev/tty: No such device or
        address`.

        Needs a pty to be meaningful: with no controlling terminal anywhere in the
        picture there is nothing for the child to have opened, and the test would
        pass without proving a thing.
        """
        if not sys.platform.startswith("linux"):
            self.skipTest("controlling-terminal semantics are POSIX-specific here")
        probe = (
            "import importlib.util, sys, time\n"
            f"spec = importlib.util.spec_from_file_location('d', {str(DOCTOR)!r})\n"
            "d = importlib.util.module_from_spec(spec); spec.loader.exec_module(d)\n"
            "d.RUN_TIMEOUT = 3\n"
            "t = time.time()\n"
            "cp = d.run(['sh', '-c', 'read x </dev/tty; echo got'])\n"
            "print('RC=%s ELAPSED=%.2f ERR=%s' % (cp.returncode, time.time()-t, "
            "cp.stderr.strip()))\n"
        )
        pid, fd = pty.fork()
        if pid == 0:                                   # pragma: no cover - child
            os.chdir(str(BRAIN))
            os.execv(sys.executable, [sys.executable, "-c", probe])
        out = b""
        while True:
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            out += chunk
        os.waitpid(pid, 0)
        text = out.decode(errors="replace")
        self.assertIn("RC=", text, f"the pty probe said nothing: {text[:200]!r}")
        self.assertNotIn("RC=124", text,
                         "the child blocked on /dev/tty and only the ceiling ended "
                         "it; that is the wedged pre-push this guard is for")
        elapsed = float(re.search(r"ELAPSED=([\d.]+)", text).group(1))
        self.assertLess(elapsed, 2.0,
                        f"took {elapsed}s: the open did not fail, it waited")
        self.assertIn("cannot open /dev/tty", text,
                      "the child still had a controlling terminal to open")

    def test_the_terminal_prompt_is_ended_by_the_env_not_by_the_empty_stdin(self):
        """The guard that actually ends git's username prompt is the env var.

        An https remote that answers 401 makes git ask on /dev/tty, which stdin on
        /dev/null does not touch. Measured under a pty with GIT_TERMINAL_PROMPT
        unset and stdin=DEVNULL: git printed `Username for 'https://github.com': `
        and hung the full 8s. Through `run`, which sets the variable: rc 128 in
        1.05s with a sentence instead of a wait.

        Network-guarded, because the point is what a REAL remote does. It is the one
        test here that needs one, and it says so rather than passing quietly offline.
        """
        if not shutil.which("git"):
            self.skipTest("no git on PATH")
        url = "https://github.com/CarlosCaPe/octorato-private-probe-does-not-exist.git"
        started = time.time()
        cp = doctor.run(["git", "-c", "credential.helper=", "ls-remote", url],
                        timeout=25)
        elapsed = time.time() - started
        # A timeout is NOT a skip here. rc 124 is the exact failure this guard
        # exists to prevent, so it FAILS loudly; only a genuinely absent network
        # skips, and it has to say so in git's own words.
        # DNS resolving is not the same as the remote being reachable, and the
        # first version of this skip only knew the DNS shape. With a route blocked
        # (`-c http.proxy=http://127.0.0.1:9`) git answers rc 128 with `Failed to
        # connect ... Couldn't connect to server`, which clears both rc asserts and
        # then fails on the prompt string: a captive portal or a corporate firewall
        # turns the suite RED instead of skipping. The skip is the CONNECT-failure
        # class, not one member of it.
        unreachable = ("Could not resolve host", "Temporary failure in name resolution",
                       "Couldn't connect to server", "Failed to connect",
                       "Connection refused", "Connection timed out",
                       "Network is unreachable", "SSL_ERROR", "Proxy CONNECT aborted",
                       "unable to access")
        if any(s in cp.stderr for s in unreachable):
            self.skipTest(f"the remote is not reachable from here: "
                          f"{cp.stderr.strip()[:100]}")
        self.assertNotEqual(cp.returncode, 124,
                            f"git hung for {elapsed:.1f}s and only the ceiling "
                            f"ended it; that is the wedged pre-push this guard is "
                            f"for, not a passing test")
        self.assertLess(elapsed, 20,
                        "git answered only because the ceiling was near, which "
                        "reads the same as answering promptly unless timed")
        self.assertEqual(cp.returncode, 128)
        self.assertIn("terminal prompts disabled", cp.stderr,
                      "git asked instead of answering; without "
                      "GIT_TERMINAL_PROMPT=0 this call hangs on /dev/tty and takes "
                      "the pre-push that spawned it down with it")
        self.assertIn("could not read Username", cp.stderr)

    def test_a_shorter_leash_is_the_callers_to_ask_for(self):
        """`run` grew a `timeout=` because one call site needed a cheaper question
        answered fast, not because 300s was wrong for the rest. The synthesised
        sentence has to name the leash that actually fired, or the reader is told the
        wrong number.

        Timed, not just coded. If `timeout=` were ignored the child would run its
        full 30s and come back rc 0, which the rc assertion catches; if the leash
        fired but at the wrong length the rc would still be 124 and only the clock
        would say so."""
        started = time.time()
        cp = doctor.run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=1)
        elapsed = time.time() - started
        self.assertEqual(cp.returncode, 124)
        self.assertLess(elapsed, 15,
                        f"took {elapsed:.1f}s: the 1s leash was not the one that "
                        f"fired")
        self.assertIn("no answer in 1s, killed", cp.stderr)
        self.assertEqual(doctor.RUN_TIMEOUT, 300,
                         "the default is untouched; a per-call leash is per-call")

        # The discriminator: the same runner with no leash lets the same shape of
        # child finish, so rc 124 above is the leash and not a broken runner.
        quick = doctor.run([sys.executable, "-c", "import time; time.sleep(0.2)"])
        self.assertEqual(quick.returncode, 0)

    def test_no_call_site_bypasses_the_runner(self):
        """`run` is the only place that scrubs `GIT_DIR`, pins LC_ALL=C, disables the
        terminal prompt and closes fd 0, so a call site that goes around it gets none
        of them.

        One did. `check_changelog_freshness` called `subprocess.run` directly for
        `git ls-remote --tags origin`: a NETWORK call, from a process that
        `.githooks/pre-push` invokes with `GIT_DIR` exported, which is the exact
        shape of the 2026-09-05 incident where a child git operated on the live repo
        instead of the intended one.

        Asserted structurally rather than on that one line, because the next bypass
        will be somewhere else: inside `brain_doctor.py`, `subprocess.run(` appears
        only in the body of `run` itself.
        """
        src = DOCTOR.read_text(encoding="utf-8")
        body = src.split("def run(", 1)[1].split("\ndef ", 1)[0]
        # Every way to start a process, not just the one that was there when this
        # test was written: it pinned `subprocess.run(` at a count of 1, and the
        # group-kill rewrite moved the runner to Popen, which would have left the
        # assertion green while naming a primitive the file no longer uses.
        SPAWNS = ("subprocess.run(", "subprocess.Popen(", "subprocess.call(",
                  "subprocess.check_call(", "subprocess.check_output(",
                  "os.system(", "os.popen(", "os.spawn", "os.exec")
        outside = src
        for chunk in (body,):
            outside = outside.replace(chunk, "")
        for spawn in SPAWNS:
            with self.subTest(spawn=spawn):
                self.assertEqual(
                    outside.count(spawn), 0,
                    f"{spawn} appears outside run(): that call site bypasses the "
                    f"env scrub, the locale pin, GIT_TERMINAL_PROMPT=0, "
                    f"stdin=/dev/null, the new session and the group kill. Route "
                    f"it through run(cwd=..., timeout=...) instead")
        self.assertEqual(body.count("subprocess.Popen("), 1,
                         "run() spawns exactly once")

    def test_the_release_probe_keeps_its_own_short_leash(self):
        """Routing the call through `run` and the leash surviving are TWO claims, and
        only the first was defended.

        The structural test next door counts spawn primitives, which proves the
        routing and says nothing about `timeout=10`. A mutation batch changed that
        10 and the suite stayed green: the value the commit body called "the one
        thing worth keeping" was pinned by nothing, because it only matters when a
        child is slow and no child in this suite is slow.

        So this makes one slow on purpose. `run` is wrapped to keep the call site's
        own kwargs and swap the argv for a sleeper, which measures the value the
        call site actually passes rather than the value the source appears to
        contain. Both directions fail: raise the leash to the 300s default and the
        sleeper outlives the assertion window; drop the `timeout=` and the same.
        """
        brain = self.tmp / "leash"
        (brain / "scripts").mkdir(parents=True)
        (brain / "CHANGELOG.md").write_text(
            "# Changelog\n\n## [2026-09-09] — v9.9.9\n\n- probe\n", encoding="utf-8")

        real_run, real_git = doctor.run, doctor.git
        saved_dir = doctor.CLAUDE_DIR
        self.addCleanup(lambda: (setattr(doctor, "run", real_run),
                                 setattr(doctor, "git", real_git),
                                 setattr(doctor, "CLAUDE_DIR", saved_dir)))
        doctor.CLAUDE_DIR = brain
        # no local tags, so the check has to ask the remote
        doctor.git = lambda *a: subprocess.CompletedProcess(["git", *a], 0, "", "")

        seen = {}

        def slow_run(args, cwd=None, timeout=None):
            if args[:4] == ["git", "ls-remote", "--tags", "origin"]:
                seen["timeout"] = timeout
                started = time.time()
                cp = real_run([sys.executable, "-c", "import time; time.sleep(40)"],
                              cwd=cwd, timeout=timeout)
                seen["elapsed"] = time.time() - started
                seen["rc"] = cp.returncode
                return cp
            return real_run(args, cwd=cwd, timeout=timeout)

        doctor.run = slow_run
        doctor.check_release_drift(False)

        self.assertIn("timeout", seen,
                      "the remote probe was never reached; this test asserts "
                      "nothing unless it runs")
        self.assertEqual(seen["timeout"], 10,
                         f"the call site passed timeout={seen['timeout']!r}: the "
                         f"300s default on a network probe is what wedges a "
                         f"pre-push behind an unreachable origin")
        self.assertEqual(seen["rc"], 124,
                         "the leash did not fire on a child that never answers")
        self.assertGreaterEqual(seen["elapsed"], 8,
                                "returned too fast to have been the 10s leash")
        self.assertLess(seen["elapsed"], 25,
                        f"took {seen['elapsed']:.1f}s: a leash longer than 10s is "
                        f"in force at this call site")

    def test_a_remote_that_never_answered_is_not_a_remote_without_the_tag(self):
        """The wrong-cause defect, inside the call this branch rerouted.

        rc 124 (timed out), 127 (no git) and 128 (offline) all fell past the rc
        check into `CHANGELOG declares vX but no git tag vX (local or remote)`, so a
        laptop on a plane was told its release was never cut. The comment one line
        above already separated the three roads while the sentence did not, which is
        the same gap between what the code knows and what the reader is told that
        this whole PR is about.
        """
        brain = self.tmp / "unreached"
        (brain / "scripts").mkdir(parents=True)
        (brain / "CHANGELOG.md").write_text(
            "# Changelog\n\n## [2026-09-09] — v9.9.9\n\n- probe\n", encoding="utf-8")
        real_run, real_git = doctor.run, doctor.git
        saved_dir = doctor.CLAUDE_DIR
        self.addCleanup(lambda: (setattr(doctor, "run", real_run),
                                 setattr(doctor, "git", real_git),
                                 setattr(doctor, "CLAUDE_DIR", saved_dir)))
        doctor.CLAUDE_DIR = brain
        doctor.git = lambda *a: subprocess.CompletedProcess(["git", *a], 0, "", "")

        roads = {
            124: ("git: no answer in 10s, killed (process group reaped)",
                  "no answer in 10s"),
            127: ("git: No such file or directory", "No such file or directory"),
            128: ("fatal: unable to access 'https://origin/': Could not resolve host",
                  "Could not resolve host"),
        }
        for rc, (stderr, needle) in roads.items():
            with self.subTest(rc=rc):
                doctor.run = lambda args, cwd=None, timeout=None, _rc=rc, _e=stderr: (
                    subprocess.CompletedProcess(args, _rc, "", _e)
                    if args[:2] == ["git", "ls-remote"]
                    else real_run(args, cwd=cwd, timeout=timeout))
                res = doctor.check_release_drift(False)
                self.assertEqual(res.status, doctor.WARN)
                self.assertIn("could not be asked", res.message,
                              f"rc {rc} was reported as a remote that answered and "
                              f"did not have the tag")
                self.assertIn(needle, res.message,
                              "the row names which road, not just that one was taken")
                self.assertNotIn("(local or remote)", res.message)

        # And the remote that DID answer without the tag keeps the original verdict,
        # so the new branch is a discriminator and not a blanket excuse.
        doctor.run = lambda args, cwd=None, timeout=None: (
            subprocess.CompletedProcess(args, 0, "", "")
            if args[:2] == ["git", "ls-remote"]
            else real_run(args, cwd=cwd, timeout=timeout))
        answered = doctor.check_release_drift(False)
        self.assertEqual(answered.status, doctor.WARN)
        self.assertIn("(local or remote)", answered.message)
        self.assertIn("never cut", answered.message)

    def test_a_child_killed_by_a_signal_is_named_not_numbered(self):
        """`exit -9` is a code, not a cause, and it was what both selectors printed
        for the one class that reliably arrives with empty streams.

        A negative returncode is POSIX reporting death by signal. Measured through
        `run`: -9 for SIGKILL, -11 for SIGSEGV, nothing on either stream. The two
        that arrive here say something a reader can act on, since SIGKILL is how the
        OOM killer ends a gate selftest on a machine that ran out of memory.
        """
        killed = doctor.run([sys.executable, "-c",
                             "import os, signal; os.kill(os.getpid(), signal.SIGKILL)"])
        self.assertEqual(killed.returncode, -9)
        self.assertEqual(killed.stderr, "", "the premise: nothing to read")
        self.assertEqual(doctor.selftest_cause(killed), "killed by SIGKILL (signal 9)")
        self.assertEqual(doctor.git_failure_cause(killed.stderr, killed.returncode),
                         "killed by SIGKILL (signal 9)")

        segv = doctor.run([sys.executable, "-c", "import ctypes; ctypes.string_at(0)"])
        self.assertEqual(segv.returncode, -11)
        self.assertEqual(doctor.selftest_cause(segv), "killed by SIGSEGV (signal 11)")

        # rc 124 is NOT signal death: `run` synthesises it with a sentence, and a
        # reader who is told "killed by SIGKILL" for a timeout is told the wrong
        # thing about a machine that is merely slow.
        self.assertEqual(doctor._exit_cause(124), "exit 124")
        self.assertEqual(doctor._exit_cause(1), "exit 1")

    def test_stderr_outranks_stdout_when_both_carry_a_marker(self):
        """The stream order is load-bearing and was untested: swapping it survived
        the whole module.

        `gate_selftest.py:212` writes the joined `selftest FAIL: a; b` summary to
        STDERR, and that one printer speaks for 23 of the 33 `--selftest` scripts in
        the registry. Reading stdout first would let a helper's incidental chatter
        outrank the verdict of the majority, which is the same wrong-cause defect as
        the clone warning, arriving from the other side.
        """
        cp = subprocess.CompletedProcess(
            ["helper"], 1,
            "FAIL: a line the helper happened to print first\n",
            "selftest FAIL: the real verdict\n")
        self.assertEqual(doctor.selftest_cause(cp), "selftest FAIL: the real verdict")

        # and stdout is still read when stderr carries no marker at all, which is the
        # base-freshness case this function was written for
        stdout_only = subprocess.CompletedProcess(
            ["helper"], 1,
            "  X violation fixture did NOT warn (stale base undetected)\n",
            "warning: You appear to have cloned an empty repository.\n")
        self.assertEqual(doctor.selftest_cause(stdout_only),
                         "X violation fixture did NOT warn (stale base undetected)")

    def test_every_failure_marker_is_one_the_selector_can_actually_see(self):
        """Presence in a source file is NOT reach, and the first version of this test
        asserted presence.

        It named an emitter per marker and grepped for the glyph. Two of the four
        named emitters cannot reach this selector at all: `capability_manifest.py`
        is read through its RETURN CODE by `check_capability_manifest`, which never
        calls `selftest_cause`; and `✗`'s emitters write the live DENY message,
        which `gate_selftest.run_gate` captures as the CHILD's stdout to decide
        whether the leg blocked, so it never lands on a stream the doctor reads. An
        enumeration replaced by an argument, with the argument unchecked at the
        level where it has to hold, which is the same shape as the prefix tuple next
        door.

        So the fixtures here are RECORDED STREAMS, captured by running the real
        scripts into a forced failure, and each marker is pinned by what
        `selftest_cause` picks out of them.
        """
        fx = BRAIN / "scripts" / "tests" / "fixtures"
        bf_out = (fx / "base-freshness-failed.stdout").read_text(encoding="utf-8")
        bf_err = (fx / "base-freshness-failed.stderr").read_text(encoding="utf-8")
        gs_err = (fx / "gate-selftest-failed.stderr").read_text(encoding="utf-8")

        # "selftest FAIL": stderr, gate_selftest.py:212, speaking for 25 of the 33.
        cp = subprocess.CompletedProcess(["helper"], 1, "", gs_err)
        self.assertTrue(doctor.selftest_cause(cp).startswith("selftest FAIL:"))

        # "X ": stdout, base-freshness with its violation leg forced. The whole
        # reason this function selects by marker: the X line is chosen over the
        # clone warning that the SAME run put on stderr.
        cp = subprocess.CompletedProcess(["helper"], 1, bf_out, bf_err)
        self.assertEqual(doctor.selftest_cause(cp),
                         "X violation fixture did NOT warn (stale base undetected)")

        # "FAIL": the next line of that same real stdout.
        self.assertIn("FAIL base-freshness selftest", bf_out)
        only_fail = subprocess.CompletedProcess(
            ["helper"], 1, "  FAIL base-freshness selftest\n", bf_err)
        self.assertEqual(doctor.selftest_cause(only_fail),
                         "FAIL base-freshness selftest")

        # The fixtures must not drift away from the printers they were captured
        # from, or this test slowly becomes the presence check it replaced.
        bf = (BRAIN / "scripts" / "r__pretool-write__base-freshness.py").read_text(encoding="utf-8")
        self.assertIn("X violation fixture did NOT warn", bf)
        self.assertIn("FAIL base-freshness selftest", bf)
        self.assertIn('print("selftest FAIL: " + "; ".join(failures), file=sys.stderr)',
                      (BRAIN / "scripts" / "gate_selftest.py").read_text(encoding="utf-8"))

        # And the two that cannot reach are gone.
        for gone in ("✗", "✘"):
            self.assertNotIn(gone, doctor.SELFTEST_FAILURE_MARKERS)
        self.assertEqual(set(doctor.SELFTEST_FAILURE_MARKERS),
                         {"selftest FAIL", "FAIL", "X "},
                         "a marker was added without a recorded stream proving the "
                         "selector can see it")

        # The structural reason ✗ cannot reach, asserted rather than remembered: a
        # gate's own output is the child's, and gate_selftest captures it.
        gs = (BRAIN / "scripts" / "gate_selftest.py").read_text(encoding="utf-8")
        self.assertIn("def emits_block(", gs)
        self.assertIn("stdout", gs.split("def emits_block(", 1)[1][:400],
                      "gate_selftest still decides on the CHILD's captured stdout, "
                      "so a gate's ✗ deny text never reaches selftest_cause")

    def test_a_timed_out_child_does_not_leave_its_group_behind(self):
        """`subprocess.run` kills the direct child and nothing else.

        Measured before the fix with a 2s ceiling: `sh -c '<child> & exec <child>'`
        came back rc 124 with a survivor reparented to PID 1, and the stderr said
        `no answer in 2s, killed` with no word about it. Through
        `.githooks/pre-push` that is an ssh left holding the operator's terminal
        after the push has already returned.

        The guard is asserted too, because an unguarded `killpg` kills this test
        runner: without `start_new_session` the child shares our process group
        (measured: child pgid == runner pgid), and the kill would come home.
        """
        if not hasattr(os, "killpg"):
            self.skipTest("no process groups on this platform")
        saved = doctor.RUN_TIMEOUT
        self.addCleanup(lambda: setattr(doctor, "RUN_TIMEOUT", saved))
        doctor.RUN_TIMEOUT = 2
        mark = f"octorato-reap-probe-{os.getpid()}"
        child = f"import time,sys;sys.argv.append({mark!r});time.sleep(300)"
        self.addCleanup(lambda: subprocess.run(["pkill", "-f", mark],
                                               capture_output=True))

        cp = doctor.run(["sh", "-c",
                         f'{sys.executable} -c "{child}" & '
                         f'exec {sys.executable} -c "{child}"'])
        self.assertEqual(cp.returncode, 124)
        time.sleep(0.5)
        alive = subprocess.run(["pgrep", "-f", mark], capture_output=True,
                               text=True).stdout.split()
        self.assertEqual(alive, [],
                         f"{len(alive)} descendant(s) outlived the timeout; before "
                         f"the group kill this one was reparented to PID 1")
        self.assertIn("process group reaped", cp.stderr,
                      "the reader cannot tell a complete kill from a partial one "
                      "unless the sentence says which happened")

        # The guard: we are still here. An unguarded killpg SIGKILLs the runner.
        self.assertTrue(True, "reached, so the reaper did not kill its own group")

        # And the honest limit: a descendant that calls setsid ITSELF has left the
        # group before the kill lands, so the sentence must not claim the tree.
        started = time.time()
        deep = doctor.run(["sh", "-c",
                           f'setsid {sys.executable} -c "{child}" & '
                           f'exec {sys.executable} -c "{child}"'])
        deep_elapsed = time.time() - started
        self.assertEqual(deep.returncode, 124)
        # The escapee inherited the write end of our pipes, so the post-kill drain
        # waits for an EOF that never comes. It is bounded at 5s on purpose: the
        # first version waited 10s and left the process unreaped, which is a hang
        # introduced by the code that removes hangs.
        self.assertLess(deep_elapsed, 20,
                        f"took {deep_elapsed:.1f}s: the drain after the kill is "
                        f"waiting on a pipe a survivor still holds")
        time.sleep(0.5)
        escaped = subprocess.run(["pgrep", "-f", mark], capture_output=True,
                                 text=True).stdout.split()
        self.assertNotEqual(escaped, [],
                            "a setsid descendant is expected to survive; if this "
                            "ever passes, the claim in the docstring is now too "
                            "modest and should be re-measured")
        self.assertNotIn("nothing survived", deep.stderr)

    def test_the_env_scrub_is_a_rule_and_not_a_list(self):
        """`GIT_CONFIG_PARAMETERS` and `GIT_EXEC_PATH` reach a hook and were not in
        the tuple, which is the third time an enumeration on this file was measured
        incomplete.

        Verbatim from a git 2.43 pre-commit hook invoked as
        `git -c user.signingkey=INJECTED -c core.hooksPath=.git/hooks commit`:

            GIT_CONFIG_PARAMETERS='user.signingkey'='INJECTED' 'core.hooksPath'='.git/hooks'

        and a grandchild `git config --get user.signingkey` inside that hook
        answered `INJECTED`. `core.hooksPath` through that route is the same class
        as the GIT_DIR incident.

        The fix cannot be a longer list: `GIT_CONFIG_COUNT` with
        `GIT_CONFIG_KEY_<n>` is an unbounded family of names, so this asserts the
        RULE (drop GIT_*, keep by exception) with a name no list would have had.
        """
        base = {
            "PATH": "/usr/bin", "HOME": "/home/x", "LC_ALL": "es_ES.UTF-8",
            "GIT_DIR": "/live/repo/.git",
            "GIT_CONFIG_PARAMETERS": "'core.hooksPath'='/evil'",
            "GIT_EXEC_PATH": "/usr/lib/git-core",
            "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.hooksPath",
            "GIT_CONFIG_VALUE_0": "/evil",
            "GIT_AUTHOR_NAME": "someone else", "GIT_EDITOR": ":",
            "GIT_SSH_COMMAND": "ssh -i /home/x/.ssh/id_ed25519",
        }
        env = doctor.scrubbed_env(base)
        leaked = sorted(k for k in env if doctor._is_scrubbed_git_var(k))
        self.assertEqual(leaked, [],
                         f"{leaked} survived the scrub; a parent's git config "
                         f"steering a child's git is the GIT_DIR incident again")
        self.assertEqual(env["GIT_SSH_COMMAND"], base["GIT_SSH_COMMAND"],
                         "the access vars are kept, or a machine that reaches "
                         "origin through a custom ssh command stops reaching it")
        self.assertEqual(env["PATH"], "/usr/bin", "non-git env is untouched")
        self.assertEqual(env["LC_ALL"], "es_ES.UTF-8",
                         "scrubbing does not pin the locale; `run` does, and only "
                         "for git")
        # the unbounded family, which is the argument for the rule
        self.assertNotIn("GIT_CONFIG_KEY_0", env)
        self.assertNotIn("GIT_CONFIG_KEY_7", doctor.scrubbed_env(
            dict(base, GIT_CONFIG_KEY_7="core.hooksPath")))

        # The exception is drawn at what git EXPORTS, not at what the tests want.
        # Every name in the measured pre-commit dump is dropped; GIT_TEST_* and
        # GIT_TEXTDOMAINDIR are not in that dump and are the only way to reproduce
        # a dubious-ownership or a translated git without a second uid, so they
        # survive and two live tests keep working.
        for exported in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_PREFIX", "GIT_EDITOR",
                         "GIT_EXEC_PATH", "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL",
                         "GIT_AUTHOR_DATE", "GIT_CONFIG_PARAMETERS"):
            with self.subTest(exported=exported):
                self.assertTrue(doctor._is_scrubbed_git_var(exported))
        for kept in ("GIT_TEST_ASSUME_DIFFERENT_OWNER", "GIT_TEXTDOMAINDIR",
                     "GIT_SSH_COMMAND"):
            with self.subTest(kept=kept):
                self.assertFalse(doctor._is_scrubbed_git_var(kept))

        self.assertNotIn("✘", doctor.SELFTEST_FAILURE_MARKERS)
        # The two files that DISCUSS the deletion are excluded, or this check
        # matches its own explanation and reports a printer that does not exist.
        # (The first draft of this assertion did exactly that: it failed on
        # brain_doctor.py and on this file, both of which only name the glyph.)
        talkers = {DOCTOR.resolve(), Path(__file__).resolve()}
        writers = sorted(
            str(p) for p in (BRAIN / "scripts").rglob("*")
            if p.is_file() and p.suffix in (".py", ".sh", "")
            and "__pycache__" not in p.parts
            and p.resolve() not in talkers
            and "✘" in p.read_text(encoding="utf-8", errors="replace"))
        self.assertEqual(writers, [],
                         "something started writing ✘; give it back its marker "
                         "instead of leaving the failure unmarked")

    def test_the_dispatcher_diagnosis_outlives_its_usage_block(self):
        """git the dispatcher writes diagnoses with NO prefix, and the fallback
        turned one into a usage fragment offered as the reason. Verbatim git 2.43:

            unknown option: --bogus-global
            usage: git [-v | --version] [-h | --help] [-C <path>] [-c <name>=<value>]
                       ...
                       [--config-env=<name>=<envvar>] <command> [<args>]

        and the row read `[--config-env=<name>=<envvar>] <command> [<args>]`.

        The fix is NOT `unknown option:` in the prefix tuple. That closes one member
        and leaves the class open for the next reviewer, which is the habit this
        brain has now measured seven times in a day. What actually broke the row is
        that git's `usage:` block is a REMEDY and it is printed LAST, the same
        remedy-as-cause shape this whole function opens with, so the fallback drops
        it and takes the last line that survives.

        Live git, not a fixture: the point is what git 2.43 actually prints.
        """
        if not shutil.which("git"):
            self.skipTest("no git on PATH")
        cp = doctor.run(["git", "--bogus-global", "status"], cwd=BRAIN)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("usage: git", cp.stderr, "git no longer prints a usage block "
                                               "here; re-measure before trusting this")
        cause = doctor.git_failure_cause(cp.stderr, cp.returncode)
        self.assertEqual(cause, "unknown option: --bogus-global")
        self.assertNotIn("<command>", cause,
                         "a usage fragment where the cause belongs")

        # The prefixed sibling keeps working: a SUBCOMMAND marks its diagnosis, so
        # the marked line wins and the usage block below it is never consulted.
        # 129 is git's usage exit, but OUTSIDE a repository git answers 128 before
        # it parses options at all, so pinning 129 made this test depend on BRAIN
        # being a checkout — true here, false in an exported tree, which is how it
        # was found. What matters either way is that it is not 124.
        sub = doctor.run(["git", "status", "--bogus-sub"], cwd=BRAIN)
        self.assertIn(sub.returncode, (128, 129),
                      "124 would be a hang read as a diagnosis")
        if sub.returncode == 128:
            self.skipTest("not inside a git repository, so git answers before it "
                          "parses the bogus option and there is no usage block")
        self.assertEqual(doctor.git_failure_cause(sub.stderr, sub.returncode),
                         "error: unknown option `bogus-sub'")

        # A stderr that is nothing BUT a usage block has no cause in it, and the exit
        # code is a thin answer that is at least not a wrong one.
        only_usage = "usage: git [-v | --version]\n           [--bare]\n"
        self.assertEqual(doctor.git_failure_cause(only_usage, 129), "exit 129")

    def test_a_subcommand_this_git_does_not_have_names_the_diagnosis(self):
        """Translation was one way for a diagnosis to go unrecognised. It is not the
        only one, and the fallback turned another into the same remedy-as-cause.

        `fatal:`/`error:` is what a SUBCOMMAND writes. git the dispatcher has its own
        prefix, and nothing matched it. Recorded from git 2.43 on this machine:

            git: 'revparse' is not a git command. See 'git --help'.

            The most similar command is
            <tab>rev-parse

        No prefix matched, the fallback took the last line, and the row read
        `rev-parse`: a SUGGESTION offered as the reason, which is exactly the shape
        the dubious-ownership fixture was written to abolish. Reachable the day this
        doctor calls a subcommand newer than the installed git.
        """
        recorded = (BRAIN / "scripts" / "tests" / "fixtures"
                    / "git-not-a-command.stderr").read_text(encoding="utf-8")
        because = doctor.git_failure_cause(recorded, 1)
        self.assertEqual(because,
                         "git: 'revparse' is not a git command. See 'git --help'.")
        self.assertNotIn("most similar", because)
        self.assertNotEqual(because.strip(), "rev-parse",
                            "the row hands the reader the fix and calls it the cause")

        # `BUG:` is git's own internal-assert prefix (usage.c). It is outside the
        # tuple's original two and landed correctly only by the luck of sitting on
        # the first line, which the fallback happens to reach when there is one line.
        bug = ("BUG: refs.c:1234: reference not found in transaction\n"
               "Aborting. Report this to the git mailing list.\n")
        self.assertEqual(doctor.git_failure_cause(bug, 134),
                         "BUG: refs.c:1234: reference not found in transaction")

    def test_the_continuation_is_one_line_and_not_the_whole_list(self):
        """The colon join takes ONE line, and the claim was unpinned: taking all of
        them passed every test (mutant M12). git lists one extension per line and a
        row is a sentence, not a dump, so a repo with TWO unknown extensions is what
        holds the join to its word. Recorded from git 2.43 with
        `core.repositoryformatversion=1` and both `extensions.bogus` and
        `extensions.bogus2` set:

            fatal: unknown repository extensions found:
            <tab>bogus
            <tab>bogus2
        """
        recorded = (BRAIN / "scripts" / "tests" / "fixtures"
                    / "git-unknown-extensions-two.stderr").read_text(encoding="utf-8")
        self.assertEqual(len(recorded.strip().splitlines()), 3,
                         "this fixture is only interesting while git lists two")
        because = doctor.git_failure_cause(recorded, 128)
        self.assertEqual(because, "fatal: unknown repository extensions found: bogus")
        self.assertNotIn("bogus2", because,
                         "the join swallowed the rest of the list, so the row is a "
                         "dump and the next multi-line git message will be a page")

    def test_every_road_gives_its_own_cause(self):
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

        # git EXITS NON-ZERO, which is not a shallow clone and used to be reported
        # as one. A directory that is no repository at all is the cheapest real
        # instance of the class; `git init` answers "false" there, which is why the
        # existing shallow-clone test could never see this road.
        notarepo = self.tmp / "notarepo"
        (notarepo / "scripts").mkdir(parents=True)
        doctor.CLAUDE_DIR = notarepo
        causes["git failed"] = self._why()

        # An arm date AFTER every transcript. Reached by committing the hook with a
        # future author and committer date, which is what a skewed clock or an
        # imported history produces; the check takes the EARLIER of the two, so both
        # have to move or the road is not reached.
        future = self.tmp / "future"
        (future / "scripts").mkdir(parents=True)
        (future / "scripts" / "r__permission-denied__journal.py").write_text("#\n",
                                                                            encoding="utf-8")
        env = dict(os.environ)
        for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_PREFIX",
                  "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY", "GIT_NAMESPACE"):
            env.pop(k, None)
        ahead = time.strftime("%Y-%m-%dT%H:%M:%S",
                              time.gmtime(time.time() + 3 * 86400)) + "+0000"
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = ahead
        for args in (["init", "-q"], ["config", "user.email", "t@example.invalid"],
                     ["config", "user.name", "t"],
                     ["add", "scripts/r__permission-denied__journal.py"],
                     ["commit", "-q", "-m", "add the reflex"]):
            subprocess.run(["git", "-C", str(future)] + args, check=True,
                           capture_output=True, env=env)
        doctor.CLAUDE_DIR = future
        causes["future arm date"] = self._why()

        # A transcript FILE the process cannot open, with its DIRECTORY readable, so
        # the walk succeeds and only the open fails. That is the difference between
        # this road and the unreadable-subtree one, and it is the difference the
        # bare `except OSError: continue` erased.
        doctor.CLAUDE_DIR = self.brain
        armed_now, _, _, _ = doctor._harness_refusals_since_hook(time.time() - 7 * 86400)
        self.assertIsNotNone(armed_now, "the sandbox brain must have a real window")
        self.write_refusal("automode-blocked", armed_now + 60)
        blind = self.harness / "projects" / "slug" / "sess" / "transcript.jsonl"
        os.chmod(blind, 0o000)
        try:
            causes["unreadable file"] = self._why()
        finally:
            os.chmod(blind, 0o644)
            blind.unlink()

        self.assertEqual(len(set(causes.values())), len(causes),
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
        tokens = {"unreadable subtree": "the walk could not read",
                  "no projects dir": "no projects directory",
                  "shallow clone": "grafted history",
                  "no such commit": "no commit adding",
                  "git failed": "git itself failed",
                  "future arm date": "dated in the future",
                  "unreadable file": "transcript file"}
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


class TestTheSelftestCauseIsTheMarkedLine(unittest.TestCase):
    """Six call sites read a failed helper's cause, and the selection was by POSITION.

    `git_failure_cause` exists because `detail[-1]` picked the remedy out of git's
    stderr. Eleven lines above that fix, and five more times through the file, the
    same `detail[-1]` read `cp.stderr or cp.stdout` off a gate selftest, the kernel
    selftests, the isolation gates, the PermissionDenied reflex and changelog-sync.
    Twenty of the thirty-three scripts behind those sites go through
    `gate_selftest.py`, which collapses every failure into one `selftest FAIL: a; b`
    line on stderr, so the last line IS the summary there and `[-1]` looked right.

    It was UNGUARDED, and one printer that does not go through `gate_selftest.py` is
    reachable: `r__pretool-write__base-freshness.py` writes its verdict to stdout
    while the `git clone` its selftest runs lets git's own setup warning onto stderr,
    and `[-1]` on `stderr or stdout` produced a FAIL row naming the clone warning as
    the cause. So the selection is by CONVENTION now, the way the sibling selects on
    `fatal:`: the first MARKED failure line, stderr then stdout. This class is that
    contract, held against the real printers' real streams rather than described.
    """

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="selftest-cause-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_the_gate_printer_summarises_on_one_final_stderr_line(self):
        """Two failures, a noisy gate, one line, and it is last.

        The failure mode `[-1]` would have here is a helper that prints its summary
        first and keeps talking, or one that lets a leg's own stderr through after
        it. So the stub gate writes two lines to stderr and allows both violations,
        which is two failures for the printer to join.
        """
        fdir = self.tmp / "fixtures"
        fdir.mkdir()
        for name in ("violation-one.json", "violation-two.json", "benign.json"):
            (fdir / name).write_text(
                json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                            "tool_input": {"command": "echo hi"}}), encoding="utf-8")
        stub = self.tmp / "g__stub__allows-everything.py"
        stub.write_text("import sys\n"
                        "sys.stdin.read()\n"
                        "sys.stderr.write('leg noise one\\nleg noise two\\n')\n"
                        "sys.exit(0)\n", encoding="utf-8")

        cp = subprocess.run([sys.executable, str(BRAIN / "scripts" / "gate_selftest.py"),
                             str(stub), str(fdir)],
                            capture_output=True, text=True, timeout=120)
        self.assertEqual(cp.returncode, 1, cp.stdout + cp.stderr)
        lines = [ln for ln in (cp.stderr or "").splitlines() if ln.strip()]
        self.assertTrue(lines, "the printer said nothing at all")
        self.assertTrue(lines[-1].startswith("selftest FAIL: "),
                        f"the summary is not the last line: {lines!r}")
        self.assertIn("violation-one.json", lines[-1])
        self.assertIn("violation-two.json", lines[-1],
                      "both failures have to ride the SAME line, or `[-1]` hands "
                      "the reader one of two causes and hides the other")
        self.assertNotIn("leg noise", cp.stderr,
                         "a leg's own stderr reached the parent, so the last line "
                         "is whatever the last leg happened to say")

        # And that is exactly the string the doctor puts in the row.
        self.assertEqual(doctor.selftest_cause(cp), lines[-1])

    def test_the_reflex_printer_summarises_on_one_final_stderr_line(self):
        """The other printer the doctor reads, held to the same contract. A fixture
        directory with no seed is the cheapest real failure it has."""
        empty = self.tmp / "no-fixtures"
        empty.mkdir()
        cp = subprocess.run(
            [sys.executable,
             str(BRAIN / "scripts" / "r__permission-denied__journal.py"),
             "--selftest", str(empty)],
            capture_output=True, text=True, timeout=120)
        self.assertNotEqual(cp.returncode, 0)
        lines = [ln for ln in (cp.stderr or "").splitlines() if ln.strip()]
        self.assertTrue(lines[-1].startswith("selftest FAIL: "),
                        f"the summary is not the last line: {lines!r}")
        self.assertEqual(doctor.selftest_cause(cp), lines[-1])

    def test_a_printer_outside_gate_selftest_still_names_its_own_failure(self):
        """The measured defect, out of a REAL printer's REAL streams.

        `r__pretool-write__base-freshness.py` is the one selftest of the thirty-three
        that neither goes through `gate_selftest.py` nor writes its verdict to
        stderr, and its setup builds a real repo: `git clone` of an empty bare origin
        warns, on stderr, and that warning has nothing to do with why the selftest
        failed. `[-1]` on `stderr or stdout` therefore produced

            GIT.version-control: 'warning: You appear to have cloned an empty
            repository.'

        a FAIL row a reader acts on, naming a setup warning as the cause.

        The failure is forced the way it happens: a `git` wrapper earlier on PATH
        that refuses `fetch`. The selftest's own setup (init, clone, commit, push)
        passes through, `check()` cannot see the remote move ahead, and the violation
        leg legitimately does not warn. Nothing in the script is edited, which is the
        point: the contract is about printers as they are.
        """
        if not shutil.which("git"):
            self.skipTest("no git on PATH")
        bindir = self.tmp / "bin"
        bindir.mkdir()
        real_git = shutil.which("git")
        wrapper = bindir / "git"
        wrapper.write_text(
            "#!/bin/sh\n"
            'for a in "$@"; do [ "$a" = "fetch" ] && exit 1; done\n'
            f'exec {real_git} "$@"\n', encoding="utf-8")
        wrapper.chmod(0o755)

        home = self.tmp / "home"
        home.mkdir()
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env["PATH"] = f"{bindir}:{env.get('PATH', '')}"
        env["HOME"] = str(home)          # keeps the TTL marker out of the real cache
        env.pop("SSH_AUTH_SOCK", None)
        cp = subprocess.run(
            [sys.executable,
             str(BRAIN / "scripts" / "r__pretool-write__base-freshness.py"),
             "--selftest"],
            capture_output=True, text=True, timeout=180, env=env)
        self.assertEqual(cp.returncode, 1,
                         f"the selftest did not fail, so there is no cause to read\n"
                         f"stdout={cp.stdout!r}\nstderr={cp.stderr!r}")
        self.assertIn("You appear to have cloned an empty repository", cp.stderr,
                      "the setup no longer leaks git's warning onto stderr, so this "
                      "anchor is measuring a stream that is no longer there")
        self.assertIn("violation fixture did NOT warn", cp.stdout,
                      "the forced failure did not land where this test expects it")

        because = doctor.selftest_cause(cp)
        self.assertIn("violation fixture did NOT warn", because,
                      "the row is not telling the reader why the selftest failed")
        self.assertNotIn("cloned an empty repository", because,
                         "the row hands the reader a setup warning as the cause, "
                         "which is the defect this whole file is about")

    def test_a_printer_that_lists_its_failures_below_the_marker_names_the_first(self):
        """The smaller member of the same class, also out of a real printer.

        `commit_msg_language_gate.py` writes `selftest FAIL:` and then one item per
        line below it, so `[-1]` gave the reader the LAST item and silently dropped
        the first. The colon continuation the sibling already uses for git answers
        it: the marker line carries its next line, which is the first failure, and a
        row stays a sentence rather than becoming a dump.

        Both legs are forced to fail at once by inverting the fixture pair, which is
        the cheapest way to get a printer to list two.
        """
        fdir = self.tmp / "inverted-fixtures"
        fdir.mkdir()
        # violation.txt must be Spanish for the gate to block it, benign.txt English.
        # Swapped, both assertions fail and the printer has two items to list.
        (fdir / "violation.txt").write_text(
            "add a gate that blocks a non-English commit subject\n", encoding="utf-8")
        (fdir / "benign.txt").write_text(
            "corrige el mensaje del commit porque no está en inglés\n",
            encoding="utf-8")
        cp = subprocess.run(
            [sys.executable,
             str(BRAIN / "scripts" / "commit_msg_language_gate.py"),
             "--selftest", str(fdir)],
            capture_output=True, text=True, timeout=120)
        self.assertEqual(cp.returncode, 1, cp.stdout + cp.stderr)
        lines = [ln.strip() for ln in (cp.stderr or "").splitlines() if ln.strip()]
        self.assertEqual(lines[0], "selftest FAIL:",
                         f"this printer no longer lists below a bare marker: {lines!r}")
        self.assertEqual(len(lines), 3,
                         f"both legs have to fail or there is only one item: {lines!r}")

        because = doctor.selftest_cause(cp)
        self.assertEqual(because, f"selftest FAIL: {lines[1]}")
        self.assertNotIn(lines[2], because,
                         "the row took the whole list; a cause is a sentence")
        self.assertNotEqual(because, "selftest FAIL:",
                            "the row names a class of failure and not one instance "
                            "of it, which is the collapse this file undoes")

    def test_the_helper_prefers_stderr_and_names_a_silent_failure(self):
        """stderr first because that is where both printers write; stdout only when a
        helper puts everything on one stream; and a helper that failed without a word
        still owes the reader something, which is its exit code unless the caller has
        better words."""
        noisy = subprocess.CompletedProcess([], 1, "on stdout\n", "first\nlast\n")
        self.assertEqual(doctor.selftest_cause(noisy), "last")
        stdout_only = subprocess.CompletedProcess([], 1, "only\nthis\n", "")
        self.assertEqual(doctor.selftest_cause(stdout_only), "this")
        silent = subprocess.CompletedProcess([], 3, "", "   \n\n")
        self.assertEqual(doctor.selftest_cause(silent), "exit 3")
        self.assertEqual(doctor.selftest_cause(silent, "no output"), "no output")


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
        healthy brain and be turned off by the next person who saw it.

        The last row is the one that changed meaning. `(1, 1.0, 99)` used to read "a
        journal with one deny of ANY kind covers 99 harness refusals", which is the
        defect: the one deny was the qa-merge-gate's and the reflex had recorded
        nothing. The first argument is now the REFLEX's own count, so one reflex line
        against 99 refusals is a live reflex under-recording, which is a PASS here by
        design (the check asks whether the reflex fires at all, not whether it
        catches every class the harness refuses for). The old reading is now a FAIL,
        and it is pinned end to end where it belongs, on the check rather than on the
        pure function, by `test_another_gates_deny_is_not_coverage_for_the_reflex`.
        """
        for reflex_denies, armed, harness in ((0, None, 0), (0, 1.0, 0), (5, 1.0, 0),
                                              (5, 1.0, 5), (1, 1.0, 99)):
            with self.subTest(reflex_denies=reflex_denies, armed=armed, harness=harness):
                self.assertEqual(doctor.deny_coverage(reflex_denies, armed, harness)[0],
                                 doctor.PASS)

    def test_the_total_is_reported_and_the_reflex_count_is_the_one_that_decides(self):
        """Both numbers reach the reader, and only one of them votes. The live brain
        that produced this PR is the fixture: 571 deny lines in the window, none of
        them the reflex's, nine harness refusals of classes the hook does not fire
        for. The old code took 571 into the comparison and printed PASS."""
        status, text, _ = doctor.deny_coverage(0, 1_700_000_000.0, 0, 9,
                                               total_denies=571)
        self.assertEqual(status, doctor.WARN,
                         "571 refusals by other gates are not this reflex firing")
        self.assertIn("571 deny(s) in 7 days", text, "the total still reaches the reader")
        self.assertIn("9 refusal(s) of other classes", text)
        # And the same total with the reflex alive is not a WARN.
        status, text, _ = doctor.deny_coverage(4, 1_700_000_000.0, 0, 9,
                                               total_denies=571)
        self.assertEqual(status, doctor.PASS)
        self.assertIn("4 of them from the reflex", text)

    def test_refusals_of_other_classes_never_print_that_nothing_was_refused(self):
        """The sentence QA measured as false: with nine other-class refusals on
        record the row said "the harness refused nothing since the hook went live".
        Nine refusals had happened. It survived because the WARN needed an empty
        journal and the journal was never empty, so every live brain landed on this
        line (QA cycle 13)."""
        _, text, _ = doctor.deny_coverage(4, 1_700_000_000.0, 0, 9)
        self.assertNotIn("the harness refused nothing", text)
        self.assertIn("9 refusal(s) of other classes", text)
        # the branch that IS entitled to say it: nothing was refused at all
        _, quiet, _ = doctor.deny_coverage(4, 1_700_000_000.0, 0, 0)
        self.assertIn("the harness refused nothing", quiet)


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
        self.harness_refused(0)

    def harness_refused(self, count: int, armed: float = 1_700_000_000.0) -> None:
        """Pin the harness side to `count` refusals since `armed`."""
        real = doctor._harness_refusals_since_hook
        doctor._harness_refusals_since_hook = lambda cutoff: (armed, count, 0, "")
        self.addCleanup(lambda: setattr(doctor, "_harness_refusals_since_hook", real))

    def other_rule(self) -> str:
        """A registered rule id that is NOT the harness reflex's."""
        ids = sorted(r.id for r in doctor.Registry.load(doctor.REGISTRY_PATH).rules)
        return next(i for i in ids if i != doctor.HARNESS_DENY_RULE)

    def test_another_gates_deny_is_not_coverage_for_the_reflex(self):
        """THE merge blocker of cycle 13, and the one this whole PR turns on.

        `denies` was every journal line with `kind: deny`, and thirteen Octorato
        gates write that kind under their own rule ids. Measured on this brain in a
        7-day window: 571 deny lines, 495 from the qa-merge-gate, 50 from the
        arming-surface gate, 26 from the isolation gate, and ZERO from the reflex
        the coverage claim is about. So `denies == 0` was never reachable on a
        working machine, the FAIL branch was dead, and the row printed PASS while
        the reflex had recorded nothing at all.

        One deny from another gate, twelve harness refusals. The old code counted
        the one, took the final PASS and said "against 12 harness refusal(s)". The
        reflex still recorded none, so this has to FAIL.
        """
        jdir = self.sandbox()
        self.harness_refused(12)
        now = time.time()
        self.seed(jdir, "other-gate-agent",
                  [self.start(now),
                   {"kind": "deny", "ts": now, "rule": self.other_rule(),
                    "reason": "some other gate refused something"}])
        result = doctor.check_kernel_replay(False)
        self.assertEqual(result.status, doctor.FAIL, result.message)
        self.assertIn("refused 12 call(s)", result.message)
        self.assertIn("recorded none", result.message)

    def test_the_reflexs_own_deny_line_is_what_answers_the_harness(self):
        """The discriminator that keeps the test above from being a tripwire: the
        SAME shape, with the rule id the reflex actually stamps, has to pass."""
        jdir = self.sandbox()
        self.harness_refused(12)
        now = time.time()
        self.seed(jdir, "reflex-agent",
                  [self.start(now),
                   {"kind": "deny", "ts": now, "rule": doctor.HARNESS_DENY_RULE,
                    "source": "harness", "reason": "harness denied Bash"},
                   {"kind": "deny", "ts": now, "rule": self.other_rule(),
                    "reason": "a gate, not the harness"}])
        result = doctor.check_kernel_replay(False)
        self.assertEqual(result.status, doctor.PASS, result.message)
        self.assertIn("2 deny(s) in 7 days", result.message)
        self.assertIn("1 of them from the reflex", result.message)
        self.assertIn("12 harness refusal(s)", result.message)

    def test_the_doctors_rule_id_is_the_one_the_reflex_writes(self):
        """Nothing bound `doctor.HARNESS_DENY_RULE` to the reflex's own `RULE_ID`, so
        the two could drift silently, which is precisely what the id choice exists to
        make loud. Imported from the reflex module rather than retyped: a constant
        copied into a test is a third place to drift.

        `source` is bound the same way. It is read off the line the reflex actually
        writes, not off a literal, so renaming the field in the reflex turns this red
        instead of quietly emptying the coverage count.
        """
        sys.path.insert(0, str(BRAIN / "scripts"))
        spec = importlib.util.spec_from_file_location(
            "reflex_permission_denied",
            BRAIN / "scripts" / "r__permission-denied__journal.py")
        reflex = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(reflex)
        self.assertEqual(doctor.HARNESS_DENY_RULE, reflex.RULE_ID,
                         "the doctor counts an id the reflex no longer stamps")
        # the reflex's own `source`, read off a line it produced
        payload = {"session_id": "bind-check", "tool_name": "Bash",
                   "tool_use_id": "toolu_bind", "reason": "denied"}
        self.assertEqual(reflex.denial_fields(payload).get("reason"), "denied")
        jdir = self.sandbox()
        saved_stdin = sys.stdin
        sys.stdin = io.StringIO(json.dumps(payload))
        try:
            reflex.main()
        finally:
            sys.stdin = saved_stdin
        written = [ln for ln in self.kernel_proc.read_journal("bind-check")
                   if isinstance(ln, dict) and ln.get("kind") == "deny"]
        self.assertEqual(len(written), 1, "the reflex has to have written a deny line")
        self.assertEqual(written[0].get("rule"), doctor.HARNESS_DENY_RULE)
        self.assertEqual(written[0].get("source"), doctor.HARNESS_DENY_SOURCE,
                         "the doctor filters on a `source` the reflex does not write")
        self.assertTrue(str(jdir).endswith("journal"))

    def test_the_reflexs_rule_id_from_another_writer_is_not_coverage(self):
        """Rule id AND source, which is where the first draft's argument only held
        half. `rule` alone fails loud on the day the id moves ONLY where automode
        refusals exist after arming, and on this brain that is 0 of 571, so an id
        move presents as the same WARN the row already shows. Requiring `source`
        too costs nothing on live data, since the reflex writes it on every line,
        and closes the hole rule-only leaves: a DIFFERENT writer stamping this id
        would otherwise be counted as coverage for a reflex that recorded nothing.
        """
        jdir = self.sandbox()
        self.harness_refused(4)
        now = time.time()
        self.seed(jdir, "impostor-agent",
                  [self.start(now),
                   {"kind": "deny", "ts": now, "rule": doctor.HARNESS_DENY_RULE,
                    "reason": "some other writer, this reflex's id, no source"}])
        result = doctor.check_kernel_replay(False)
        self.assertEqual(result.status, doctor.FAIL, result.message)
        self.assertIn("recorded none", result.message)

    def test_a_reflex_deny_exactly_at_the_arm_date_is_coverage(self):
        """The journal side of the boundary its sibling pins on the harness side. The
        harness loop skips `ts < armed_at`, so the arm instant counts there; flipping
        this `>=` to `>` left every test green, and the two sides would then disagree
        about one record at the seam. Asserted with the reflex line landing exactly at
        the arm date, which is what a refusal in the same second as the arming commit
        looks like.

        A WHOLE second, deliberately. `kernel_proc.append` stores `round(ts, 6)`, so a
        boundary set at sub-microsecond precision round-trips to a value that can land
        on either side and the test would flake by rounding rather than assert the
        comparison. In production the arm date comes from git's `%at`/`%ct`, which are
        whole seconds, so this is the real shape as well as the stable one.
        """
        jdir = self.sandbox()
        armed = float(int(time.time()) - 120)
        self.harness_refused(1, armed=armed)
        self.seed(jdir, "boundary-agent",
                  [self.start(armed),
                   {"kind": "deny", "ts": armed, "rule": doctor.HARNESS_DENY_RULE,
                    "source": doctor.HARNESS_DENY_SOURCE,
                    "reason": "refused in the same second the hook was armed"}])
        result = doctor.check_kernel_replay(False)
        self.assertEqual(result.status, doctor.PASS, result.message)
        self.assertIn("1 of them from the reflex", result.message)

    def test_a_deny_line_with_no_rule_is_reported_as_unnamed(self):
        """A deny with no `rule`, or an empty one, is in no registry row either, and
        `rule or "(unnamed)"` is what keeps it from printing as an empty name. No test
        reached that branch: every orphan case named a rule. An anonymous refusal is
        the worst orphan of the class, so it has to reach the reader as something."""
        jdir = self.sandbox()
        now = time.time()
        self.seed(jdir, "anonymous-agent",
                  [self.start(now),
                   {"kind": "deny", "ts": now, "reason": "refused, by nothing named"}])
        result = doctor.check_kernel_replay(False)
        self.assertEqual(result.status, doctor.FAIL, result.message)
        self.assertIn("(unnamed)", result.message,
                      "an unnamed refusal has to be visible as unnamed")
        self.assertIn("in no registry row", result.message)

    def test_a_malformed_ts_is_a_named_failure_not_a_traceback(self):
        """`float(line.get("ts"))` on a `ts` that is not a number raised straight out
        of the check, and `run_all` turned it into `FAIL check crashed: could not
        convert string to float`. Fail-closed already, and tamper-only:
        `kernel_proc.append` computes `float(ts)` itself and refuses to write such a
        line, which is why this is seeded past the writer. What was missing was the
        SENTENCE, and a traceback where a cause belongs is this PR's whole subject.

        The tampered journal is the SIXTH, by mtime. `journals[:5]` is what gets
        replayed, and `replay --verify` rejects the edited line first, so a tampered
        journal inside the newest five never reaches this code at all. The deny scan
        walks EVERY journal in the 7-day window, which is wider than the five, and
        that gap is exactly where the crash lived.
        """
        jdir = self.sandbox()
        now = time.time()
        for i in range(5):
            fresh = self.seed(jdir, f"fresh-{i}",
                              [self.start(now),
                               {"kind": "tool", "ts": now, "tool_name": "Read",
                                "tool_use_id": f"t{i}"}])
            os.utime(fresh, (now - i, now - i))
        path = self.seed(jdir, "tampered-agent",
                         [self.start(now),
                          {"kind": "deny", "ts": now, "rule": self.other_rule(),
                           "reason": "seeded"}])
        with self.assertRaises(ValueError):
            self.kernel_proc.append("tampered-agent",
                                    {"kind": "deny", "ts": "not-a-number"})
        lines = path.read_text(encoding="utf-8").splitlines()
        last = json.loads(lines[-1])
        last["ts"] = "yesterday"
        lines[-1] = json.dumps(last, separators=(",", ":"))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        older = now - 600
        os.utime(path, (older, older))
        # Through `run_all`, because that is the hop that rendered the ValueError as
        # "check crashed"; calling the check directly would prove it returns rather
        # than raises and say nothing about the sentence a reader gets. Only this
        # check is in CHECKS for the call, so the assertion is about this row.
        real_checks = doctor.CHECKS
        doctor.CHECKS = [("kernel-replay", doctor.check_kernel_replay)]
        try:
            results = doctor.run_all(False)
        finally:
            doctor.CHECKS = real_checks
        row = next(r for r in results if r.key == "kernel-replay")
        self.assertEqual(row.status, doctor.FAIL, row.message)
        self.assertNotIn("check crashed", row.message,
                         "the reader gets a cause, not a traceback")
        self.assertIn("tampered-agent", row.message, "and the journal by name")
        self.assertIn("not a number", row.message)

    def test_a_reflex_deny_from_before_the_arm_date_is_not_coverage(self):
        """The two counts have to describe the SAME window. The harness side counts
        refusals since the hook was armed; a reflex line from before that instant
        answers a refusal nobody is asking about, and letting it count would put the
        7-day window on one side of the comparison and the arm date on the other."""
        jdir = self.sandbox()
        now = time.time()
        self.harness_refused(3, armed=now - 60)
        self.seed(jdir, "stale-reflex-agent",
                  [self.start(now - 3600),
                   {"kind": "deny", "ts": now - 3600, "rule": doctor.HARNESS_DENY_RULE,
                    "source": "harness", "reason": "before the hook was armed"}])
        result = doctor.check_kernel_replay(False)
        self.assertEqual(result.status, doctor.FAIL, result.message)
        self.assertIn("recorded none", result.message)

    def test_the_sibling_check_counts_the_chains_it_verified(self):
        """The twin of `test_the_newest_five_journals_are_the_ones_replayed`, in the
        function four above it in the same file. `kernel-process-live` printed
        `min(len(journals), 5) newest chain(s) verify`, a bound read off the LIST
        rather than off the loop, so narrowing the slice left the row saying five
        while one had been verified. Same defect, same file, and nothing in the suite
        mentioned that sentence at all: fixing it in one function and leaving the
        twin is the pixelation this brain's Impact Radius rule is about.
        """
        jdir = self.sandbox()
        now = time.time()
        for i in range(6):
            path = self.seed(jdir, f"live-{i}",
                             [self.start(now),
                              {"kind": "tool", "ts": now, "tool_name": "Read",
                               "tool_use_id": "t1"}])
            if i == 0:
                self.break_chain(path)
            stamp = now - (6 - i) * 60
            os.utime(path, (stamp, stamp))
        result = doctor.check_kernel_process_live(False)
        # NOT assertEqual(PASS). This check also benchmarks the hot path and WARNs
        # over a 100 ms median, which a machine running the whole suite crosses: the
        # first version of this test went red on exactly that, timing noise dressed
        # as a chain failure. The check's own comment says timing "is never a FAIL",
        # so FAIL is the assertion that belongs here, and the COUNT is what the test
        # is about.
        self.assertNotEqual(result.status, doctor.FAIL,
                            f"the broken chain is the OLDEST of six: {result.message}")
        self.assertIn("5 newest chain(s) verify", result.message)
        # the same journal, now the newest, so the loop has to reach it
        os.utime(jdir / "live-0.jsonl", None)
        result = doctor.check_kernel_process_live(False)
        self.assertEqual(result.status, doctor.FAIL, result.message)
        self.assertIn("live-0", result.message)

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

    def test_the_footer_is_read_from_the_end_past_a_lookalike_line(self):
        """`parse_summary` reads the LAST summary-shaped line, and until now nothing
        made that matter: no fixture carried a message with one embedded, so
        reverting `reversed(...)` left 41 of 41 green (QA cycle 13). The reader would
        then measure a MESSAGE and call it the footer, and every assertion resting on
        it would be measuring the wrong line while staying green.

        Not a hypothetical shape. `run_all` puts `check crashed: {e}` into a message,
        exception text is arbitrary, and subprocess stderr reaches messages too: the
        `git itself failed` road in this very check pastes git's own last stderr line
        into the sentence. Counts that differ from the real footer in all three
        positions, so reading the wrong line cannot coincide with the right answer.
        """
        results = [doctor.Result("stub-liar", doctor.PASS,
                                 "the stub passed\n  9 passed, 9 warn, 9 fail", ""),
                   doctor.Result("stub-pass", doctor.PASS, "the stub passed", "")]
        rc, out = run_main(stub_checks(results))
        self.assertEqual(rc, 0)
        self.assertIn("9 passed, 9 warn, 9 fail", out,
                      "the decoy has to actually reach stdout, or this proves nothing")
        self.assertEqual(parse_summary(out), {"passed": 2, "warn": 0, "fail": 0},
                         "the footer is the LAST summary-shaped line, not the first")

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
