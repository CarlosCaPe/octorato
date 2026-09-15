#!/usr/bin/env python3
"""Anchors for the SCOPE of the kernel-replay orphan assertion (brain_doctor.py).

The kernel journal is machine-wide by design: `lane_owner` and `process_age`
(kernel_proc.py:634, 760) probe processes living in other worktrees, so
one-writer-per-tree only holds while every dimension appends to the same
directory. `registry/rules.yaml` is NOT machine-wide; it travels per branch.
The two met on 2026-09-15: a gate on an open branch journaled 1,586 denies into
the shared journal and the doctor on master, which does not carry that row yet,
called a registered rule an orphan and blocked the push.

What is pinned here is the correction AND its limit, in both directions:

  * a deny naming a rule declared by a SIBLING checkout passes (revert the fix
    and this one fails, which is the whole point of the anchor);
  * a deny naming a rule declared by NO checkout still FAILS, so the widening
    did not quietly turn RULE #1 off;
  * the helper never counts the checkout it is run from, or every id would
    look declared-elsewhere.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
ROOT = SCRIPTS.parent
DOCTOR = SCRIPTS / "brain_doctor.py"

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
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({
        "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        "HOME": str(cwd),
    })
    return subprocess.run(["git", *args], cwd=str(cwd), env=env,
                          capture_output=True, text=True)


def _load_doctor():
    spec = importlib.util.spec_from_file_location("bd_under_test", DOCTOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class SiblingCheckoutIds(unittest.TestCase):
    """The helper reads the OTHER checkouts of the same repo, never its own."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="replay-scope-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = self.tmp / "brain"
        (self.repo / "registry").mkdir(parents=True)
        (self.repo / "registry" / "rules.yaml").write_text(
            HEAD + _rule("TEST.here-only"), encoding="utf-8")
        self.assertEqual(_git(self.repo, "init", "-q", "-b", "main").returncode, 0)
        _git(self.repo, "add", "-A")
        self.assertEqual(_git(self.repo, "commit", "-qm", "base").returncode, 0)

    def _helper_ids(self):
        bd = _load_doctor()
        bd.CLAUDE_DIR = self.repo
        return bd._sibling_checkout_rule_ids()

    def test_own_checkout_is_never_counted(self):
        ids, paths = self._helper_ids()
        self.assertNotIn("TEST.here-only", ids,
                         "the checkout under test must not vouch for itself")
        self.assertEqual(paths, [])

    def test_sibling_worktree_ids_are_found(self):
        sib = self.tmp / "sib"
        self.assertEqual(
            _git(self.repo, "worktree", "add", "-q", str(sib), "-b", "feat").returncode, 0)
        (sib / "registry" / "rules.yaml").write_text(
            HEAD + _rule("TEST.here-only") + _rule("TEST.sibling-only"), encoding="utf-8")
        _git(sib, "add", "-A")
        self.assertEqual(_git(sib, "commit", "-qm", "declare").returncode, 0)

        ids, paths = self._helper_ids()
        self.assertIn("TEST.sibling-only", ids)
        self.assertEqual([str(sib)], [str(Path(p)) for p in paths])

    def test_unreadable_sibling_is_skipped_not_fatal(self):
        sib = self.tmp / "broken"
        self.assertEqual(
            _git(self.repo, "worktree", "add", "-q", str(sib), "-b", "broken").returncode, 0)
        (sib / "registry" / "rules.yaml").write_text("{ not: [valid", encoding="utf-8")
        ids, paths = self._helper_ids()
        self.assertEqual(paths, [], "a checkout mid-rebase is not this check's business")


class OrphanJudgementScope(unittest.TestCase):
    """The seam: which registry a deny line is judged against.

    Runs the REAL check against a sandbox brain (its own scripts/, registry/
    and HOME), because the defect lived in the meeting of a global journal with
    a per-branch registry and neither half is observable from a unit test.
    """

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

    def _home_with_deny(self, rule_id: str) -> Path:
        """A sandbox HOME whose kernel journal holds one chained deny line."""
        home = Path(tempfile.mkdtemp(prefix="replay-home-", dir=self.tmp))
        (home / ".claude" / ".cache" / "kernel" / "journal").mkdir(parents=True)
        driver = (
            "import os, sys\n"
            f"sys.path.insert(0, {str(self.brain / 'scripts')!r})\n"
            "import kernel_proc\n"
            "kernel_proc.append('fixture-pid', {'kind': 'start'})\n"
            f"kernel_proc.append('fixture-pid', {{'kind': 'deny', 'rule': {rule_id!r}}})\n"
        )
        env = dict(os.environ, HOME=str(home))
        cp = subprocess.run([sys.executable, "-c", driver], env=env,
                            capture_output=True, text=True)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        return home

    def _run_check(self, home: Path):
        driver = (
            "import importlib.util, json, sys\n"
            f"spec = importlib.util.spec_from_file_location('bd', {str(self.brain / 'scripts' / 'brain_doctor.py')!r})\n"
            "bd = importlib.util.module_from_spec(spec); spec.loader.exec_module(bd)\n"
            "r = bd.check_kernel_replay(False)\n"
            "print(json.dumps({'status': r.status, 'message': r.message}))\n"
        )
        env = dict(os.environ, HOME=str(home))
        cp = subprocess.run([sys.executable, "-c", driver], env=env,
                            capture_output=True, text=True, cwd=str(self.brain))
        self.assertEqual(cp.returncode, 0, cp.stderr)
        import json
        return json.loads(cp.stdout.strip().splitlines()[-1])

    def test_rule_declared_nowhere_still_fails(self):
        """The widening must not have turned RULE #1 off."""
        home = self._home_with_deny("TEST.declared-nowhere")
        out = self._run_check(home)
        self.assertEqual(out["status"], "FAIL", out["message"])
        self.assertIn("TEST.declared-nowhere", out["message"])

    def test_rule_declared_only_in_a_sibling_checkout_passes(self):
        """Revert the scope fix and this is the test that goes red."""
        sib = self.tmp / "sibling-branch"
        self.assertEqual(
            _git(self.brain, "worktree", "add", "-q", str(sib), "-b", "feat-gate").returncode, 0)
        rules = sib / "registry" / "rules.yaml"
        rules.write_text(rules.read_text(encoding="utf-8")
                         + _rule("TEST.declared-in-sibling"), encoding="utf-8")
        _git(sib, "add", "-A")
        self.assertEqual(_git(sib, "commit", "-qm", "declare gate").returncode, 0)
        self.addCleanup(lambda: _git(self.brain, "worktree", "remove", "--force", str(sib)))

        home = self._home_with_deny("TEST.declared-in-sibling")
        out = self._run_check(home)
        self.assertEqual(out["status"], "PASS", out["message"])
        self.assertIn("TEST.declared-in-sibling", out["message"])


if __name__ == "__main__":
    unittest.main()
