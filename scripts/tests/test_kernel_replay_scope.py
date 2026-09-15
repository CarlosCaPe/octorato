#!/usr/bin/env python3
"""Anchors for the SCOPE of the kernel-replay orphan assertion (brain_doctor.py).

The kernel journal is machine-wide by design: `lane_owner` and `process_age`
(kernel_proc.py:634, 760) probe processes living in other worktrees, so
one-writer-per-tree only holds while every dimension appends to the same
directory. `registry/rules.yaml` is NOT machine-wide; it travels per branch.
The two met on 2026-09-15: a gate on an open branch journaled denies into the
shared journal and the doctor on master, which does not carry that row yet,
called a registered rule an orphan and blocked the push.

A deny is now judged against the checkout that FIRED it, which the journal's
own `start` line records, read at that checkout's COMMITTED HEAD. Both halves
are load-bearing and both are pinned here, because the first version of this
fix widened the lookup to every checkout on the machine and a QA pass showed
two ways to launder a rule id through it:

  * committed in the firing checkout passes (revert the scope resolution and
    this one goes red, which is what makes the anchor an anchor);
  * an UNCOMMITTED edit in that checkout does not vouch, or a sibling would be
    held to a lower bar than the checkout being pushed, whose own uncommitted
    edit voids the gate receipt;
  * a plain directory sitting at a path `git worktree list` still remembers
    does not vouch either;
  * a deny whose journal names no checkout is judged here, with no benefit of
    the doubt;
  * a rule declared by NOBODY still FAILs, so none of this turned RULE #1 off.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
ROOT = SCRIPTS.parent

HEAD = "version: 1\nrules:\n"


def _rule(rule_id: str) -> str:
    return (
        f"- id: {rule_id}\n"
        f"  title: 'fixture rule {rule_id}'\n"
        "  category: FLOW\n"
        "  source:\n"
        "    file: docs/architecture/v8-kernel.md\n"
        "    anchor: 'fixture'\n"
        "  strength: REFLEX\n"
        "  firing_mode:\n"
        "  - hook\n"
        "  mechanism:\n"
        "  - kind: Reflex\n"
        "    canonical_name: fixture.py\n"
        "    firing_event: PostToolUse\n"
    )


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    """git with every inherited GIT_* scrubbed: these tests are run from a repo
    whose own hooks export GIT_DIR, and a leaked one commits in the live brain."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({
        "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        "HOME": str(cwd),
    })
    return subprocess.run(["git", *args], cwd=str(cwd), env=env,
                          capture_output=True, text=True)


class OrphanJudgementScope(unittest.TestCase):
    """Runs the REAL check against a sandbox brain with its own scripts/,
    registry/ and HOME, because the defect lived in the meeting of a global
    journal with a per-branch registry and neither half is visible to a unit
    test."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="replay-seam-"))
        cls.brain = cls.tmp / "brain"
        cls.brain.mkdir(parents=True)
        for part in ("scripts", "registry"):
            shutil.copytree(ROOT / part, cls.brain / part,
                            ignore=shutil.ignore_patterns("__pycache__"))
        assert _git(cls.brain, "init", "-q", "-b", "main").returncode == 0
        _git(cls.brain, "add", "-A")
        assert _git(cls.brain, "commit", "-qm", "sandbox brain").returncode == 0

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # ── helpers ─────────────────────────────────────────────────────────────

    def _worktree(self, name: str, rule_id: str, commit: bool) -> Path:
        """A real sibling checkout declaring `rule_id`, committed or not."""
        path = self.tmp / name
        self.assertEqual(
            _git(self.brain, "worktree", "add", "-q", str(path), "-b", name).returncode, 0)
        self.addCleanup(lambda: _git(self.brain, "worktree", "remove", "--force", str(path)))
        rules = path / "registry" / "rules.yaml"
        rules.write_text(rules.read_text(encoding="utf-8") + _rule(rule_id), encoding="utf-8")
        if commit:
            _git(path, "add", "-A")
            self.assertEqual(_git(path, "commit", "-qm", f"declare {rule_id}").returncode, 0)
        return path

    def _home_with_deny(self, rule_id: str, origin: Path = None,
                        start_last: bool = False) -> Path:
        """A sandbox HOME whose kernel journal holds one chained deny line, with
        a `start` line naming `origin` when given. `start_last` writes that line
        AFTER the deny, the way a resumed session does."""
        home = Path(tempfile.mkdtemp(prefix="replay-home-", dir=self.tmp))
        (home / ".claude" / ".cache" / "kernel" / "journal").mkdir(parents=True)
        start = {"kind": "start"}
        if origin is not None:
            start["worktree"] = str(origin)
        if start_last:
            start["source"] = "resume"
        records = [{"kind": "deny", "rule": rule_id}, start] if start_last \
            else [start, {"kind": "deny", "rule": rule_id}]
        driver = (
            "import sys\n"
            f"sys.path.insert(0, {str(self.brain / 'scripts')!r})\n"
            "import kernel_proc\n"
            f"kernel_proc.append('fixture-pid', {records[0]!r})\n"
            f"kernel_proc.append('fixture-pid', {records[1]!r})\n"
        )
        cp = subprocess.run([sys.executable, "-c", driver],
                            env=dict(os.environ, HOME=str(home)),
                            capture_output=True, text=True)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        return home

    def _run_check(self, home: Path) -> dict:
        driver = (
            "import importlib.util, json\n"
            f"spec = importlib.util.spec_from_file_location('bd', {str(self.brain / 'scripts' / 'brain_doctor.py')!r})\n"
            "bd = importlib.util.module_from_spec(spec); spec.loader.exec_module(bd)\n"
            "r = bd.check_kernel_replay(False)\n"
            "print(json.dumps({'status': r.status, 'message': r.message}))\n"
        )
        cp = subprocess.run([sys.executable, "-c", driver],
                            env=dict(os.environ, HOME=str(home)),
                            capture_output=True, text=True, cwd=str(self.brain))
        self.assertEqual(cp.returncode, 0, cp.stderr)
        return json.loads(cp.stdout.strip().splitlines()[-1])

    # ── the assertion still has teeth ───────────────────────────────────────

    def test_rule_declared_nowhere_still_fails(self):
        out = self._run_check(self._home_with_deny("TEST.declared-nowhere"))
        self.assertEqual(out["status"], "FAIL", out["message"])
        self.assertIn("TEST.declared-nowhere", out["message"])

    # ── the seam ────────────────────────────────────────────────────────────

    def test_committed_in_the_firing_checkout_passes(self):
        """Revert the scope resolution and this is the test that goes red."""
        wt = self._worktree("feat-committed", "TEST.committed-there", commit=True)
        out = self._run_check(self._home_with_deny("TEST.committed-there", origin=wt))
        self.assertEqual(out["status"], "PASS", out["message"])
        self.assertIn("TEST.committed-there", out["message"])

    def test_start_line_after_the_deny_still_carries_provenance(self):
        """A resumed session writes `start` late. Measured on the operator's
        machine: 1 journal of 137 has it at seq 14, behind 14 `tool` lines. A
        forward-only scan reads everything before it as provenance-less and
        calls a registered rule an orphan, which is the symptom this check
        exists to remove."""
        wt = self._worktree("feat-resumed", "TEST.resumed-origin", commit=True)
        out = self._run_check(
            self._home_with_deny("TEST.resumed-origin", origin=wt, start_last=True))
        self.assertEqual(out["status"], "PASS", out["message"])

    # ── the two laundering paths a QA pass found in the coarse version ──────

    def test_uncommitted_edit_in_the_firing_checkout_does_not_vouch(self):
        wt = self._worktree("feat-dirty", "TEST.only-on-disk", commit=False)
        out = self._run_check(self._home_with_deny("TEST.only-on-disk", origin=wt))
        self.assertEqual(out["status"], "FAIL", out["message"])
        self.assertIn("TEST.only-on-disk", out["message"])

    def test_plain_directory_at_a_worktree_path_does_not_vouch(self):
        wt = self._worktree("feat-replaced", "TEST.replaced-path", commit=True)
        shutil.rmtree(wt)
        (wt / "registry").mkdir(parents=True)
        (wt / "registry" / "rules.yaml").write_text(
            HEAD + _rule("TEST.replaced-path"), encoding="utf-8")
        out = self._run_check(self._home_with_deny("TEST.replaced-path", origin=wt))
        self.assertEqual(out["status"], "FAIL", out["message"])

    def test_deny_naming_no_checkout_is_judged_here(self):
        """Provenance-less lines get no benefit of the doubt, even when another
        checkout happens to declare the id."""
        self._worktree("feat-unrelated", "TEST.elsewhere-only", commit=True)
        out = self._run_check(self._home_with_deny("TEST.elsewhere-only"))
        self.assertEqual(out["status"], "FAIL", out["message"])


class CommittedRuleIds(unittest.TestCase):
    """The helper reads one checkout, at its committed HEAD, of THIS repo."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="replay-ids-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = self.tmp / "brain"
        (self.repo / "registry").mkdir(parents=True)
        (self.repo / "registry" / "rules.yaml").write_text(
            HEAD + _rule("TEST.here-only"), encoding="utf-8")
        self.assertEqual(_git(self.repo, "init", "-q", "-b", "main").returncode, 0)
        _git(self.repo, "add", "-A")
        self.assertEqual(_git(self.repo, "commit", "-qm", "base").returncode, 0)

    def _ids(self, claude_dir: Path, target: Path):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "bd_ids", SCRIPTS / "brain_doctor.py")
        bd = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bd)
        bd.CLAUDE_DIR = claude_dir
        bd._COMMITTED_IDS_CACHE.clear()
        return bd._committed_rule_ids(str(target))

    def test_an_unrelated_repository_vouches_for_nothing(self):
        other = self.tmp / "other"
        (other / "registry").mkdir(parents=True)
        (other / "registry" / "rules.yaml").write_text(
            HEAD + _rule("TEST.foreign"), encoding="utf-8")
        self.assertEqual(_git(other, "init", "-q", "-b", "main").returncode, 0)
        _git(other, "add", "-A")
        self.assertEqual(_git(other, "commit", "-qm", "base").returncode, 0)
        self.assertEqual(self._ids(self.repo, other), set())

    def test_a_worktree_of_the_same_repo_vouches_for_its_head(self):
        sib = self.tmp / "sib"
        self.assertEqual(
            _git(self.repo, "worktree", "add", "-q", str(sib), "-b", "feat").returncode, 0)
        rules = sib / "registry" / "rules.yaml"
        rules.write_text(rules.read_text(encoding="utf-8") + _rule("TEST.sibling-only"),
                         encoding="utf-8")
        _git(sib, "add", "-A")
        self.assertEqual(_git(sib, "commit", "-qm", "declare").returncode, 0)
        self.assertIn("TEST.sibling-only", self._ids(self.repo, sib))

    def test_a_missing_path_is_empty_not_fatal(self):
        self.assertEqual(self._ids(self.repo, self.tmp / "gone"), set())


if __name__ == "__main__":
    unittest.main()
