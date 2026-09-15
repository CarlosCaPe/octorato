#!/usr/bin/env python3
"""Anchors for the wrapper peel in `qa-merge-gate.py`.

Measured on 2026-09-15, and it was not a theory: the gate anchors every publish
pattern at the START of a sub-command, and `_strip_leading` peeled grouping,
env-assignments, redirections, `env` and `command` but nothing else. So:

    gh pr merge 307 --squash --delete-branch             rc=2, BLOCKED
    timeout 300 gh pr merge 307 --squash --delete-branch rc=0, ALLOWED

and the second form merged the PR without the operator's env approval. Six
characters of prefix turned the brain's fail-closed merge gate into a
decorative one.

Two things are pinned here, because the fixture corpus proves the behaviour
while these prove the two properties a corpus cannot:

  * the local `_WRAPPER_ARGC` COVERS the shared parser's `_WRAPPERS`, so the
    gate that runs on every Bash call can keep its own cheap table without the
    two drifting apart. Covering more is allowed, covering less is not: more
    peeling can only over-gate, and under-gating is the defect above;
  * the peel is basename-aware and flag-aware, which is what stops the next
    spelling of the same trick.
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GATE = _load("qa_merge_gate_under_test", SCRIPTS / "qa-merge-gate.py")
PARSER = _load("tree_owner_under_test", SCRIPTS / "g__pretool-bash__tree-owner.py")


class WrapperTableDoesNotDrift(unittest.TestCase):
    def test_every_shared_wrapper_is_peeled_here_too(self):
        shared = set(PARSER._WRAPPERS)
        mine = set(GATE._WRAPPER_ARGC) | {"env", "command"}   # those two predate this table
        missing = sorted(shared - mine)
        self.assertEqual(missing, [],
                         "the shared parser peels these and the merge gate does not, "
                         "which is exactly how a prefix gets to disarm the gate")

    def test_timeout_and_flock_eat_their_positional(self):
        """`timeout 300 cmd` and `flock /tmp/x cmd` take an argument before the
        command; the rest do not. Getting this wrong eats the command itself."""
        self.assertEqual(GATE._WRAPPER_ARGC["timeout"], 1)
        self.assertEqual(GATE._WRAPPER_ARGC["flock"], 1)
        self.assertEqual(GATE._WRAPPER_ARGC["sudo"], 0)
        self.assertEqual(GATE._WRAPPER_ARGC["nohup"], 0)


class ThePeelReachesTheCommand(unittest.TestCase):
    def _bare(self, command: str) -> str:
        return GATE._strip_leading(command).strip()

    def test_the_measured_hole(self):
        self.assertTrue(self._bare("timeout 300 gh pr merge 307 --squash")
                        .startswith("gh pr merge"))

    def test_flags_and_their_values_are_not_mistaken_for_the_command(self):
        for spelling in ("timeout -k 5 300 gh pr merge 307",
                         "timeout --kill-after=5 300 gh pr merge 307",
                         "sudo -u carlos gh pr merge 307",
                         "nice -n 10 gh pr merge 307",
                         "stdbuf -o0 gh pr merge 307"):
            with self.subTest(spelling=spelling):
                self.assertTrue(self._bare(spelling).startswith("gh pr merge"), spelling)

    def test_an_absolute_path_peels_like_its_basename(self):
        self.assertTrue(self._bare("/usr/bin/timeout 300 gh pr merge 307")
                        .startswith("gh pr merge"))

    def test_wrappers_nest(self):
        self.assertTrue(self._bare("env A=1 sudo nohup timeout 300 gh pr merge 307")
                        .startswith("gh pr merge"))

    def test_a_wrapper_in_front_of_ordinary_work_is_left_alone(self):
        """The peel must not invent a publish where there is none."""
        self.assertEqual(self._bare("timeout 300 ls -la"), "ls -la")
        self.assertEqual(self._bare("sudo apt update"), "apt update")

    def test_a_command_that_is_not_wrapped_is_untouched(self):
        self.assertEqual(self._bare("gh pr merge 307 --squash"), "gh pr merge 307 --squash")


if __name__ == "__main__":
    unittest.main()
