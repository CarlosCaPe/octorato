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
                if name in GATE._PEEL_EXCLUDED:
                    continue  # pinned by test_env_is_left_to_the_env_path
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
        for name in ("sudo", "nohup", "time", "nice"):
            with self.subTest(wrapper=name):
                self.assertEqual(specs[name]["arg"], 0)

    def test_env_is_left_to_the_env_path(self):
        """`env` is not a plain wrapper: the value of `-S`/`--split-string` IS
        the command line, so the shared table (which reads it as a value)
        discarded the merge behind any prefix. The gate leaves env to its own
        `_W_ENV`/`_W_ENVARG` path; this pins that it stays excluded."""
        self.assertEqual(GATE._PEEL_EXCLUDED, frozenset({"env"}))
        self.assertNotIn("env", GATE._wrapper_specs())
        self.assertNotIn("env", GATE._WRAPPER_NAMES)
        self.assertIsNone(GATE._peel_wrapper("env -S " + MERGE))

    def test_env_split_string_behind_a_prefix_is_still_a_publish(self):
        for prefix in ("timeout 5 ", "command ", "nohup ", "sudo -n ", "( ", "! "):
            for env in ("env -S ", "env -iS ", "env --split-string ", "env -iu X "):
                command = prefix + env + MERGE
                with self.subTest(command=command):
                    self.assertTrue(GATE._find_publish_subcmds(command), command)


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


class AWrapperThatMovesTheDirectoryIsNotJudgedByTheSessionCwd(unittest.TestCase):
    """QA measured it on the approved path: with OCTO_MERGE_APPROVE exported
    for another PR and the session in an UNPROTECTED repo, the peel dropped
    `sudo -D <protected>` as an ordinary value, the scope reader judged the
    session cwd, and the merge of the protected repo was allowed. The gate
    before the peel denied it. A wrapper's directory option must make the
    target unreadable, as `env -C` does.

    The gate runs as the hook does, in a subprocess, with HOME pointing at a
    temp dir that holds a protected brain repo and an unprotected one."""

    PUSH = "git push origin " + "main"

    def setUp(self):
        import shutil
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="gate-wrapper-cwd-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.brain = self.tmp / ".claude"
        self.other = self.tmp / "other"
        for repo, slug in ((self.brain, "CarlosCaPe/octorato"), (self.other, "someone/else")):
            (repo / ".git").mkdir(parents=True)
            (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
            (repo / ".git" / "config").write_text(
                f'[remote "origin"]\n\turl = https://github.com/{slug}.git\n')

    def _rc(self, command: str, approve: str = "7") -> int:
        import json
        import os
        import subprocess
        import sys
        env = {k: v for k, v in os.environ.items()
               if k not in ("OCTO_MERGE_APPROVE", "OCTO_QA_OK", "GH_REPO")}
        env.update({"HOME": str(self.tmp), "USERPROFILE": str(self.tmp)})
        if approve:
            env["OCTO_MERGE_APPROVE"] = approve
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command},
                              "cwd": str(self.other)})
        return subprocess.run([sys.executable, str(SCRIPTS / "qa-merge-gate.py")],
                              input=payload, capture_output=True, text=True,
                              env=env, cwd=str(SCRIPTS), timeout=60).returncode

    def test_the_unprotected_cwd_alone_is_allowed(self):
        """The control: the same merge with no directory option is out of
        scope, so the denials below are the directory option's doing."""
        self.assertEqual(self._rc(MERGE + " --squash"), 0)

    def test_sudo_chdir_into_a_protected_repo_is_denied(self):
        b = str(self.brain)
        for command in (f"sudo -D {b} {MERGE} --squash",
                        f"sudo --chdir={b} {self.PUSH}",
                        f"sudo --chdir {b} {MERGE}",
                        f"sudo --chd={b} {MERGE}",
                        f"sudo -nD {b} {self.PUSH}",
                        f"sudo -D{b} {MERGE}",
                        f"sudo -u root -D {b} {MERGE}",
                        f"timeout 5 sudo -D {b} {MERGE}",
                        f"sudo -D {b} gh api -X PUT repos/o/r/pulls/9/merge"):
            with self.subTest(command=command):
                self.assertEqual(self._rc(command), 2, command)

    def test_a_wrapper_that_adds_arguments_or_moves_home_is_unreadable(self):
        """`xargs` appends arguments the gate cannot see (`-R <protected>` from
        stdin), and `sudo -i` starts a login shell in another directory. From
        an unprotected cwd with another PR approved, both must deny, as the
        gate before the peel did."""
        for command in (f"printf -- '-R CarlosCaPe/octorato' | xargs {MERGE}",
                        f"xargs -0n1 {MERGE}",
                        f"timeout 5 xargs {self.PUSH}",
                        f"sudo -i {MERGE}",
                        f"sudo -iu root {MERGE}",
                        f"sudo --login {self.PUSH}"):
            with self.subTest(command=command):
                self.assertEqual(self._rc(command), 2, command)

    def test_a_plain_wrapper_in_an_unprotected_repo_reads_like_the_bare_command(self):
        """The other side: a wrapper that changes nothing about the target is
        judged as the bare command is, so it is not denied for being wrapped."""
        for command in (f"timeout 5 {MERGE}", f"sudo -nu root {MERGE}", f"nice -n 5 {self.PUSH}"):
            with self.subTest(command=command):
                self.assertEqual(self._rc(command), self._rc(MERGE if "merge" in command else self.PUSH))

    def test_a_cd_behind_a_wrapper_does_not_move_the_cwd(self):
        """`sudo cd <dir>` runs nothing in this shell; reading it as a move
        would let `sudo -n cd <unprotected> && <merge>` judge the wrong repo."""
        command = f"cd {self.brain} && sudo -n cd {self.other} && {MERGE}"
        self.assertEqual(self._rc(command), 2)

    def test_chrt_takes_its_scheduling_values(self):
        for command in (f"chrt -T 1000 -f 50 {MERGE}", f"chrt -P 5 -D 3 50 {MERGE}",
                        f"chrt --sched-runtime 1000 -f 50 {MERGE}"):
            with self.subTest(command=command):
                self.assertTrue(GATE._find_publish_subcmds(command), command)


if __name__ == "__main__":
    unittest.main()
