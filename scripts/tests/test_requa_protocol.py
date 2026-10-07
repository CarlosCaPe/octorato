#!/usr/bin/env python3
"""Pins the Base_Update_Verifier (spec v10, AC-12) that `/requa` runs.

`commands/requa.md` calls scripts/requa.py for the parent check, the
master-membership status and the normalized patch compare. These tests drive
it over a throwaway fixture repo with the remote answers injected, so no test
touches the network or a local master ref:

  - a pure update merge (master merged into the PR, nothing else) is IDENTICAL;
  - a merge commit that also edits a PR file DIFFERS;
  - the PR's change moved to another function with identical context lines
    DIFFERS, because the function-context text survives normalization;
  - parent shapes other than two parents with the reviewed head among them
    are NEEDS-WORK, and a prefix of the reviewed head never matches it.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import requa  # noqa: E402

HELPER = ROOT / "scripts" / "requa.py"

BODY = ["    p = 0", "    q = 0", "    r = 0", "    x = 1", "    y = 2", "    z = 3",
        "    s = 0", "    t = 0", "    u = 0"]


HEADER = "".join(f"# master header line {i}\n" for i in range(5))


def module(a_y: str = "2", b_y: str = "2", extra: str = "", header: str = "") -> str:
    """Two functions whose bodies are line-for-line identical, so a hunk in
    either one carries the same context lines and differs only in the
    function-context text git writes after the second @@."""
    a = [ln.replace("y = 2", f"y = {a_y}") for ln in BODY]
    b = [ln.replace("y = 2", f"y = {b_y}") for ln in BODY]
    return header + "\n".join(["def a():", *a, "", "", "def b():", *b, extra]) + "\n"


class Fixture:
    """master M0 -> M1, PR branch OLD off M0 (edits a()).

    M1 edits notes.txt and also prepends a header to f.py, far from the PR's
    hunk, so a clean merge shifts the hunk's line numbers and changes the blob
    hashes on the `index` line: exactly what normalization has to absorb."""

    def __init__(self, path: Path, pr_blob: bytes | None = None):
        self.path = str(path)
        self.git("init", "-q", "-b", "master")
        self.write("f.py", module())
        self.write("notes.txt", "one\n")
        self.m0 = self.commit("base")
        self.git("checkout", "-q", "-b", "pr")
        self.write("f.py", module(a_y="20"))
        if pr_blob is not None:
            self.write("blob.bin", pr_blob)
        self.old = self.commit("pr: change a()")
        self.git("checkout", "-q", "master")
        self.write("notes.txt", "one\ntwo\n")
        self.write("f.py", module(header=HEADER))
        self.m1 = self.commit("master moves")

    def git(self, *args: str) -> str:
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e",
                   GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        cp = subprocess.run(["git", "-C", self.path, *args], capture_output=True,
                            text=True, env=env, check=True)
        return cp.stdout.strip()

    def write(self, name: str, text: str | bytes) -> None:
        if isinstance(text, bytes):
            Path(self.path, name).write_bytes(text)
        else:
            Path(self.path, name).write_text(text, encoding="utf-8", newline="")

    def commit(self, msg: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg)
        return self.git("rev-parse", "HEAD")

    def merge_commit(self, f_py: str | None = None, files: dict | None = None) -> str:
        """A merge of master (M1) into the PR head (OLD), parents [OLD, M1],
        whose tree is the clean merge unless f_py overrides f.py, which is how
        a conflict resolution or an extra edit rides inside a merge commit."""
        self.git("checkout", "-q", "pr")
        self.git("merge", "-q", "--no-ff", "--no-edit", "master")
        files = dict(files or {})
        if f_py is not None:
            files["f.py"] = f_py
        if not files:
            return self.git("rev-parse", "HEAD")
        for name, data in files.items():
            self.write(name, data)
        self.git("add", *files)
        self.git("commit", "-q", "--amend", "--no-edit")
        return self.git("rev-parse", "HEAD")


class RequaCompareTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.fx = Fixture(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def run_compare(self, new: str) -> tuple[bool, str]:
        # The merge bases are what `gh api repos/R/compare/MASTER...HEAD` returns;
        # here they are known by construction and injected.
        fx = self.fx
        self.assertEqual(fx.git("merge-base", fx.m1, fx.old), fx.m0)
        self.assertEqual(fx.git("merge-base", fx.m1, new), fx.m1)
        return requa.compare(fx.path, fx.m0, fx.old, fx.m1, new)

    def test_pure_update_merge_is_identical(self):
        new = self.fx.merge_commit()
        self.assertEqual(Path(self.fx.path, "f.py").read_text(), module(a_y="20", header=HEADER))
        raw_old = requa.git_patch(self.fx.path, self.fx.m0, self.fx.old)
        raw_new = requa.git_patch(self.fx.path, self.fx.m1, new)
        self.assertNotEqual(raw_old, raw_new, "the fixture must move line numbers and blob hashes")
        same, diff = self.run_compare(new)
        self.assertTrue(same, diff)
        cp = subprocess.run([sys.executable, str(HELPER), "compare", "--repo", self.fx.path,
                             self.fx.m0, self.fx.old, self.fx.m1, new],
                            capture_output=True, text=True)
        self.assertEqual((cp.returncode, cp.stdout.strip()), (0, "IDENTICAL"))

    def test_merge_that_also_edits_a_pr_file_differs(self):
        new = self.fx.merge_commit(f_py=module(a_y="20", extra="# added in the merge", header=HEADER))
        same, diff = self.run_compare(new)
        self.assertFalse(same)
        self.assertIn(b"+# added in the merge", diff)

    def test_change_moved_to_another_function_with_identical_context_differs(self):
        new = self.fx.merge_commit(f_py=module(b_y="20", header=HEADER))
        same, diff = self.run_compare(new)
        self.assertFalse(same, "a hunk that moved from a() to b() must not read as identical")
        self.assertIn(b"@@ def a():", diff)
        self.assertIn(b"@@ def b():", diff)
        cp = subprocess.run([sys.executable, str(HELPER), "compare", "--repo", self.fx.path,
                             self.fx.m0, self.fx.old, self.fx.m1, new],
                            capture_output=True, text=True)
        self.assertEqual(cp.returncode, 1)
        self.assertEqual(cp.stdout.strip().splitlines()[-1], "DIFFERS")

    def test_cr_only_edit_on_the_pr_hunk_differs(self):
        # The merge ends the PR's changed line with \r\n instead of \n. Decoding
        # the patch as text folds the \r away and reads IDENTICAL (QA, a4525d3).
        f_py = module(a_y="20", header=HEADER).replace("y = 20\n", "y = 20\r\n")
        new = self.fx.merge_commit(f_py=f_py)
        same, diff = self.run_compare(new)
        self.assertFalse(same, "a CR-only edit on the PR's hunk must not read as identical")
        self.assertIn(b"y = 20\r\n", diff)

    def test_a_ref_name_is_refused_before_git_runs(self):
        new = self.fx.merge_commit()
        for ref in ("master", "HEAD", "origin/master", self.fx.m1[:12]):
            with self.assertRaises(ValueError):
                requa.compare(self.fx.path, self.fx.m0, self.fx.old, ref, new)


BLOB = bytes(range(256)) * 4


class RequaBinaryTest(unittest.TestCase):
    """The PR adds a binary file. Without --binary git prints only "Binary
    files ... differ", and dropping the index line erased the one carrier of
    its identity, so a swapped binary read IDENTICAL (QA, a4525d3)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.fx = Fixture(Path(self._tmp.name), pr_blob=BLOB)

    def tearDown(self):
        self._tmp.cleanup()

    def test_pure_update_with_a_pr_binary_is_identical(self):
        new = self.fx.merge_commit()
        same, diff = requa.compare(self.fx.path, self.fx.m0, self.fx.old, self.fx.m1, new)
        self.assertTrue(same, diff)

    def test_merge_that_swaps_the_pr_binary_differs(self):
        new = self.fx.merge_commit(files={"blob.bin": bytes(reversed(BLOB))})
        same, diff = requa.compare(self.fx.path, self.fx.m0, self.fx.old, self.fx.m1, new)
        self.assertFalse(same, "a swapped binary must not read as identical")


OLD = "a" * 40
X = "b" * 40
Y = "c" * 40


class RequaParentsTest(unittest.TestCase):
    def test_needs_work_shapes(self):
        # OLD[:39] + "d" is a full SHA sharing 39 digits with OLD: equality, never prefix.
        for parents in ([OLD], [Y, X], [OLD, X, Y], [OLD[:12], X], [OLD[:39] + "d", X],
                        [OLD, OLD], []):
            ok, second, why = requa.check_parents(OLD, parents)
            self.assertFalse(ok, f"{parents} must be NEEDS-WORK")
            self.assertEqual(second, "")

    def test_ok_shapes_return_the_other_parent(self):
        for parents in ([OLD, X], [X, OLD]):
            ok, second, why = requa.check_parents(OLD, parents)
            self.assertTrue(ok, f"{parents}: {why}")
            self.assertEqual(second, X)

    def test_cli_parents(self):
        cp = subprocess.run([sys.executable, str(HELPER), "parents", "--old", OLD, X, OLD],
                            capture_output=True, text=True)
        self.assertEqual((cp.returncode, cp.stdout.strip()), (0, X))
        cp = subprocess.run([sys.executable, str(HELPER), "parents", "--old", OLD, OLD, X, Y],
                            capture_output=True, text=True)
        self.assertEqual(cp.returncode, 1)
        self.assertTrue(cp.stdout.startswith("NEEDS-WORK"))

    def test_second_parent_must_be_on_master(self):
        self.assertTrue(requa.on_master("identical"))
        self.assertTrue(requa.on_master("ahead"))
        for status in ("behind", "diverged", "", "IDENTICAL"):
            self.assertFalse(requa.on_master(status), status)


class RequaCommandTest(unittest.TestCase):
    """The protocol text keeps its guarantees and calls this helper."""

    def test_command_calls_the_helper_and_reads_master_through_gh(self):
        text = (ROOT / "commands" / "requa.md").read_text(encoding="utf-8")
        for verb in ('"$REQUA" parents', '"$REQUA" on-master', '"$REQUA" compare',
                     'REQUA="$HOME/.claude/scripts/requa.py"'):
            self.assertIn(verb, text)
        self.assertIn('gh api "repos/$R/commits/master"', text)
        self.assertIn("never sets or exports `OCTO_MERGE_APPROVE`", text)
        self.assertIn("never merges", text)
        self.assertIn("never edits `scripts/qa-merge-gate.py`", text)


if __name__ == "__main__":
    unittest.main()
