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


MERGE = "gh pr " + "merge 9"

GATE = _load("qa_merge_gate_under_test", SCRIPTS / "qa-merge-gate.py")
PARSER = _load("tree_owner_under_test", SCRIPTS / "g__pretool-bash__tree-owner.py")


class WrapperSpecsDoNotDrift(unittest.TestCase):
    """The first cut pinned NAMES only, and QA measured what that misses.

    The shared parser keeps a per-wrapper `valued` tuple, a `cd` tuple and an
    `arg` count. Flattening those into one set made `-E` value-taking for
    `sudo` because `xargs` takes a value for it, so `sudo -E gh pr merge 9` ate
    `gh` and the gate saw `pr merge 9`, which matches nothing. Six spellings
    became bypasses. A name-only pin would have stayed green through all of it,
    so the pin now compares the SPEC.
    """

    def test_every_shared_wrapper_resolves_to_the_shared_spec(self):
        specs = GATE._wrapper_specs()
        for name, shared in PARSER._WRAPPERS.items():
            with self.subTest(wrapper=name):
                self.assertIn(name, specs, f"{name} is peeled by the shared "
                                           f"parser and not by the merge gate")
                self.assertEqual(specs[name], shared,
                                 f"{name} drifted from the shared parser's spec")

    def test_every_peeled_name_is_reachable_from_the_cheap_test(self):
        """`_WRAPPER_NAMES` decides whether the shared table is imported at all,
        so a spec the name set does not carry is a spec that never runs."""
        missing = sorted(set(GATE._wrapper_specs()) - set(GATE._WRAPPER_NAMES))
        self.assertEqual(missing, [])

    def test_every_name_in_the_cheap_test_has_a_spec(self):
        """The reverse gap: a name with no spec peels nothing, silently."""
        specs = GATE._wrapper_specs()
        orphan = sorted(set(GATE._WRAPPER_NAMES) - set(specs))
        self.assertEqual(orphan, [])

    def test_the_positional_eaters_are_the_ones_that_eat(self):
        specs = GATE._wrapper_specs()
        self.assertEqual(specs["timeout"]["arg"], 1)
        self.assertEqual(specs["flock"]["arg"], 1)
        self.assertEqual(specs["chrt"]["arg"], 1)
        for name in ("sudo", "nohup", "env", "time", "nice"):
            with self.subTest(wrapper=name):
                self.assertEqual(specs[name]["arg"], 0)


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

    def test_a_flag_valued_for_one_wrapper_is_not_valued_for_another(self):
        """Every one of these ALLOWED before the per-wrapper split, because a
        flat option set let another wrapper's valued flag eat the command."""
        for spelling in ("sudo -E gh pr merge 9", "sudo -n gh pr merge 9",
                         "sudo -s gh pr merge 9", "sudo -i gh pr merge 9",
                         "sudo -k gh pr merge 9", "sudo -P gh pr merge 9",
                         "time -p gh pr merge 9", "exec -c gh pr merge 9",
                         "ionice -t gh pr merge 9", "xargs -t gh pr merge 9",
                         "flock -n /tmp/x gh pr merge 9",
                         "doas -n gh pr merge 9"):
            with self.subTest(spelling=spelling):
                self.assertTrue(self._bare(spelling).startswith("gh pr merge"), spelling)

    def test_chrt_eats_its_priority(self):
        self.assertTrue(self._bare("chrt 50 gh pr merge 9").startswith("gh pr merge"))
        self.assertTrue(self._bare("chrt --rr 50 gh pr merge 9").startswith("gh pr merge"))

    def test_env_honours_its_own_valued_flags(self):
        """Pre-existing on master, and the reason the old `{env, command}`
        escape hatch was not true: `-u` takes a name and `-C` takes a dir."""
        self.assertTrue(self._bare("env -u FOO gh pr merge 9").startswith("gh pr merge"))
        self.assertTrue(self._bare("env -C /tmp gh pr merge 9").startswith("gh pr merge"))
        self.assertTrue(self._bare("env A=1 B=2 gh pr merge 9").startswith("gh pr merge"))

    def test_a_quoted_value_with_a_space_is_one_token(self):
        """QA measured this as a live bypass of the first cut: `\\S+` split
        `-u "car los"` at the space, the second half stopped the peel, and the
        quoted spelling ALLOWED while the unquoted one denied."""
        for pre in ('sudo -u "car los" ', "sudo -u 'car los' ", 'sudo -p "pw: " ',
                    'time -f "%e s" ', 'flock "/tmp/my lock" ',
                    "flock '/tmp/my lock' ", 'timeout "300" '):
            with self.subTest(prefix=pre):
                self.assertTrue(self._bare(pre + MERGE).startswith("gh pr "), pre)

    def test_a_quoted_value_does_not_invent_a_publish(self):
        self.assertEqual(self._bare('sudo -u "car los" apt update'), "apt update")
        self.assertEqual(self._bare('flock "/tmp/my lock" git status'), "git status")


    def test_a_wrapper_in_front_of_ordinary_work_is_left_alone(self):
        """The peel must not invent a publish where there is none."""
        self.assertEqual(self._bare("timeout 300 ls -la"), "ls -la")
        self.assertEqual(self._bare("sudo apt update"), "apt update")

    def test_a_command_that_is_not_wrapped_is_untouched(self):
        self.assertEqual(self._bare("gh pr merge 307 --squash"), "gh pr merge 307 --squash")


class AMalformedSpecDegradesInsteadOfCrashing(unittest.TestCase):
    """The table comes from another file, so it is untrusted input.

    QA measured the cost of trusting it: a non-mapping entry made the peel
    raise, the exception escaped the finder, and the gate failed OPEN for the
    WHOLE command, so a bare publish in a later sub-command went unseen. A gate
    that crashes open is worse than one that does not peel."""

    def setUp(self):
        self._saved = GATE._WRAPPER_SPECS
        self.addCleanup(lambda: setattr(GATE, "_WRAPPER_SPECS", self._saved))
        GATE._WRAPPER_SPECS = dict(GATE._EXTRA_WRAPPERS)
        GATE._WRAPPER_SPECS["sudo"] = "not-a-dict"

    def test_the_peel_does_not_raise(self):
        self.assertEqual(GATE._strip_leading("sudo -E ls; " + MERGE),
                         "sudo -E ls; " + MERGE)

    def test_the_publish_is_still_found(self):
        self.assertTrue(GATE._find_publish_subcmd("sudo -E ls; " + MERGE))


if __name__ == "__main__":
    unittest.main()
