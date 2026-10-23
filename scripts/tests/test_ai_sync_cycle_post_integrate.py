#!/usr/bin/env python3
"""ai_sync cycle re-projects hooks after an integrate that moved HEAD.

Measured failure: `ai-sync` pulled two commits that added a Stop hook to
hooks.json, exited 0, and never ran merge-hooks.py, so the harness kept the old
hook set and the doctor failed hooks-runtime-sync. `pull` always ran the
post-integrate steps; `cycle` skipped them. Both now share post_integrate().

These cases stub git, push and every script so nothing touches the real brain,
and read which scripts reach script_step and in what order relative to push().
"""
from __future__ import annotations

import argparse
import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import ai_sync  # noqa: E402


class CyclePostIntegrate(unittest.TestCase):
    def _run_cycle(self, head_moves: bool, drift: bool = False, branch: str = "master"):
        events = []
        heads = iter(["a" * 40, ("b" if head_moves else "a") * 40])

        def fake_git(*args, check=False, quiet=False):
            if args == ("rev-parse", "HEAD"):
                return 0, next(heads), ""
            if args == ("rev-parse", "--abbrev-ref", "HEAD"):
                return 0, branch, ""
            if args[:2] == ("rev-parse", "--absolute-git-dir") or \
                    args[-1:] == ("--git-common-dir",):
                return 0, "/brain/.git", ""
            if args[:1] == ("pull",):
                events.append(("git", args))
                return 0, "", ""
            if args == ("rev-list", "--count", "@{u}..HEAD"):
                return 0, "0", ""
            return 0, "", ""

        def fake_step(rel, *args, fatal=False, label=""):
            if rel == "scripts/check-hooks-drift.py":
                events.append(("drift-check", fatal))
                return not drift
            events.append(("step", rel, args))
            return True

        def fake_push(args):
            events.append(("push",))
            return 0

        def fake_sync(names=None):
            events.append(("sync", names))
            return 0

        ns = argparse.Namespace(message=[])
        with mock.patch.object(ai_sync, "_is_repo", return_value=True), \
                mock.patch.object(ai_sync, "git", side_effect=fake_git), \
                mock.patch.object(ai_sync, "self_heal_origin"), \
                mock.patch.object(ai_sync, "ensure_hooks_path"), \
                mock.patch.object(ai_sync, "_cotenants_on_tree", return_value=[]), \
                mock.patch.object(ai_sync, "script_step", side_effect=fake_step), \
                mock.patch.object(ai_sync, "push", side_effect=fake_push), \
                mock.patch.object(ai_sync, "sync", side_effect=fake_sync), \
                mock.patch.object(ai_sync, "connectome_stale", return_value=False), \
                mock.patch.object(ai_sync, "memory_map_stale", return_value=False), \
                mock.patch.object(ai_sync, "gate_receipt_current", return_value="c" * 40), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            rc = ai_sync.cycle(ns)
        return rc, events

    @staticmethod
    def _index(events, pred):
        for i, ev in enumerate(events):
            if pred(ev):
                return i
        return -1

    def test_live_root_off_trunk_is_refused_before_the_integrate(self):
        # A main checkout parked on a feature branch rebases onto the trunk and
        # then pushes to its own remote branch, which can never fast-forward.
        rc, events = self._run_cycle(head_moves=True, branch="chore/stray")
        self.assertEqual(rc, 1)
        self.assertEqual(events, [])

    def test_moved_head_runs_merge_hooks_before_push(self):
        rc, events = self._run_cycle(head_moves=True)
        self.assertEqual(rc, 0)
        hooks = self._index(events, lambda e: e[:2] == ("step", "scripts/merge-hooks.py"))
        cursor = self._index(events, lambda e: e[:2] == ("step", "scripts/merge-hooks-cursor.py"))
        pkgs = self._index(events, lambda e: e[:2] == ("step", "scripts/octo_pkg.py"))
        push = self._index(events, lambda e: e == ("push",))
        self.assertGreaterEqual(hooks, 0, events)
        self.assertGreaterEqual(cursor, 0, events)
        self.assertGreaterEqual(pkgs, 0, events)
        # Before push: push()'s FATAL hooks-drift guard must not see the drift
        # the integrate itself created.
        self.assertLess(hooks, push)
        self.assertLess(cursor, push)

    def test_moved_head_runs_fast_doctor_after_push(self):
        _, events = self._run_cycle(head_moves=True)
        doctor = self._index(events, lambda e: e[:2] == ("step", "scripts/brain_doctor.py"))
        push = self._index(events, lambda e: e == ("push",))
        self.assertGreater(doctor, push, events)
        self.assertEqual(events[doctor][2], ("--fast",))

    def test_moved_head_leaves_arm_sync_to_push(self):
        _, events = self._run_cycle(head_moves=True)
        self.assertNotIn("sync", [e[0] for e in events])

    def test_unmoved_head_skips_post_integrate(self):
        rc, events = self._run_cycle(head_moves=False)
        self.assertEqual(rc, 0)
        self.assertEqual([e for e in events if e[0] == "step"], [])
        self.assertIn(("push",), events)

    def test_drift_check_runs_before_the_integrate(self):
        _, events = self._run_cycle(head_moves=True)
        check = self._index(events, lambda e: e[0] == "drift-check")
        pull = self._index(events, lambda e: e[0] == "git" and e[1][:1] == ("pull",))
        self.assertGreaterEqual(check, 0, events)
        self.assertLess(check, pull)
        self.assertEqual(events[check], ("drift-check", True))

    def test_unadopted_settings_hook_aborts_before_merge_hooks(self):
        rc, events = self._run_cycle(head_moves=True, drift=True)
        self.assertNotEqual(rc, 0)
        self.assertNotIn(("step", "scripts/merge-hooks.py", ()), events)
        self.assertNotIn(("push",), events)
        self.assertFalse([e for e in events if e[0] == "git"], events)


if __name__ == "__main__":
    unittest.main()
