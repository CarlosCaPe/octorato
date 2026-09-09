#!/usr/bin/env python3
"""Anchors for the v8 Phase 2 ISOLATION gates (one writer per tree and per lane).

The fixture selftests prove the two gates block and allow end to end. These pin
the decisions underneath them, one at a time, so a regression says WHICH rule
moved: how a lane is claimed and matched, when a holder stops holding, that a
parent has no more license than a sibling, that a verb quoted inside an argument
is text and not a command, where a redirect writes, that `--release` never
belongs to an agent, and that a brain with no arms config denies no cross-arm
write it cannot define.

Timing is never asserted (v8-kernel.md section 3).
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import kernel_proc  # noqa: E402

WRITE_GATE = SCRIPTS / "g__pretool-write__tree-owner.py"
BASH_GATE = SCRIPTS / "g__pretool-bash__tree-owner.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class IsolationCase(unittest.TestCase):
    """A throwaway HOME with a worktree, a parent and two children. Journals are
    written through the real library, so liveness is the real liveness."""

    def setUp(self):
        self._saved = (os.environ.get("HOME"), os.environ.get("USERPROFILE"))
        self.home = tempfile.mkdtemp(prefix="iso-test-")
        os.environ["HOME"] = self.home
        os.environ["USERPROFILE"] = self.home
        self.tree = os.path.join(self.home, "work", "tree")
        os.makedirs(os.path.join(self.tree, ".git"))
        os.makedirs(os.path.join(self.tree, "pkg"))
        self.a_py = os.path.join(self.tree, "pkg", "a.py")
        open(self.a_py, "w").close()
        kernel_proc.register("sess-parent", {"type": "main loop", "worktree": self.tree})
        for child in ("agent-a", "agent-b"):
            kernel_proc.register(child, {"ppid": "sess-parent", "type": "builder",
                                         "worktree": self.tree})
        # EACH ONE HAS RUN A TOOL, which is what "these processes are running"
        # means everywhere below. Registered-and-never-worked was the state the
        # setup actually built, and cycle 5 C3 made the difference load-bearing:
        # `live_journal_pids` now ignores a journal that carries only `start`
        # lines, because a registration in flight holds no lane (`claim_lane`
        # creates the row and runs off a tool call), and counting one made two
        # SessionStart hooks on a table-less machine fault each other forever.
        # A lane holder that has never journaled a tool call is not a state a
        # real machine sits in; it was a shortcut in the fixture.
        for pid in ("sess-parent", "agent-a", "agent-b"):
            kernel_proc.append(pid, {"kind": "tool", "tool_name": "Read",
                                     "tool_use_id": f"toolu_{pid}"})

    def tearDown(self):
        for key, value in zip(("HOME", "USERPROFILE"), self._saved):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.home, ignore_errors=True)

    # ── helpers ────────────────────────────────────────────────────────────
    def run_gate(self, gate: Path, payload: dict):
        env = dict(os.environ)
        env["HOME"] = self.home
        env["USERPROFILE"] = self.home
        env.pop("OCTO_LANE_OVERRIDE", None)
        cp = subprocess.run([sys.executable, str(gate)], input=json.dumps(payload),
                            capture_output=True, text=True, cwd=self.home, env=env,
                            timeout=30)
        return cp.returncode, cp.stdout

    def age_journal(self, pid, age_seconds):
        """Backdate the WHOLE journal, mtime and every record, re-chained.
        `os.utime` alone is the cycle 5 C4 ATTACK, not an expiry, and
        `test_c4_*` asserts it stays denied; backdating only the LAST record is
        cycle 6 C-A's forgery signature (the tail contradicts line 0 and the
        line before it), so it stopped meaning "expired" too."""
        kernel_proc.backdate_journal(kernel_proc.journal_path(pid), age_seconds)

    def denied(self, out: str) -> bool:
        try:
            obj = json.loads(out or "{}")
        except ValueError:
            return False
        return (obj.get("hookSpecificOutput") or {}).get("permissionDecision") == "deny"

    def write_payload(self, pid, path, cwd=None):
        return {"session_id": "sess-parent", "agent_id": pid, "tool_name": "Write",
                "tool_input": {"file_path": path, "content": "x"},
                "cwd": cwd or self.tree}

    def bash_payload(self, pid, command, cwd=None):
        p = {"session_id": "sess-parent", "tool_name": "Bash",
             "tool_input": {"command": command}, "cwd": cwd or self.tree}
        if pid != "sess-parent":
            p["agent_id"] = pid
        return p


class LaneClaim(IsolationCase):

    def test_first_write_claims_the_lane_and_the_tree(self):
        rc, out = self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))
        self.assertEqual(rc, 0)
        self.assertFalse(self.denied(out))
        row = kernel_proc.read_ptable()["processes"]["agent-a"]
        self.assertIn(kernel_proc.norm_path(self.a_py), row["lanes"])
        self.assertEqual(row["tree"], kernel_proc.norm_path(self.tree))

    def test_a_claimed_lane_is_not_reclaimed(self):
        """The hot-path contract: a repeat write to a path this process already
        owns must not take the ptable lock again."""
        self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))
        before = os.stat(kernel_proc.ptable_path()).st_mtime_ns
        time.sleep(0.01)
        self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))
        self.assertEqual(os.stat(kernel_proc.ptable_path()).st_mtime_ns, before)

    def test_second_writer_on_one_lane_is_denied(self):
        self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))
        rc, out = self.run_gate(WRITE_GATE, self.write_payload("agent-b", self.a_py))
        self.assertTrue(self.denied(out))
        self.assertIn("agent-a", out)

    def test_the_deny_is_journaled(self):
        self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))
        self.run_gate(WRITE_GATE, self.write_payload("agent-b", self.a_py))
        kinds = [l.get("kind") for l in kernel_proc.read_journal("agent-b") if l]
        self.assertIn("deny", kinds)


class PrefixMatch(IsolationCase):

    def test_removing_the_directory_of_someone_elses_lane_is_denied(self):
        self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))
        rc, out = self.run_gate(
            BASH_GATE, self.bash_payload("agent-b", f"rm -rf {self.tree}/pkg"))
        self.assertTrue(self.denied(out))
        self.assertIn("agent-a", out)

    def test_a_sibling_directory_is_not_a_prefix(self):
        self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))
        os.makedirs(os.path.join(self.tree, "pkg-docs"))
        rc, out = self.run_gate(
            BASH_GATE, self.bash_payload("agent-b", f"rm -rf {self.tree}/pkg-docs"))
        self.assertFalse(self.denied(out))


class ExpiredHolder(IsolationCase):

    def test_a_holder_past_the_ttl_holds_nothing(self):
        self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))
        self.age_journal("agent-a", kernel_proc.TTL + 300)
        rc, out = self.run_gate(
            BASH_GATE, self.bash_payload("agent-b", "git checkout -- pkg/a.py"))
        self.assertFalse(self.denied(out))

    def test_an_exited_holder_holds_nothing(self):
        """CYCLE 8 CHANGED THE SETUP, not the assertion. The ending used to be
        one appended journal line, which QA then used as an attack: it freed
        this very lane with 15 bytes and no other edit. An ending is both writes
        the exit hook makes, so the test makes both; the forged half alone is
        asserted to DENY in
        `EndingNeedsBothHalvesTest.test_c8_a_well_formed_exit_line_alone_...`."""
        self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))
        kernel_proc.append("agent-a", {"kind": "exit", "status": "ok"})
        self.assertTrue(kernel_proc.update_row("agent-a", {"exited": True}))
        rc, out = self.run_gate(WRITE_GATE, self.write_payload("agent-b", self.a_py))
        self.assertFalse(self.denied(out))


class ParentVsSibling(IsolationCase):

    def test_the_parent_gets_no_license_over_a_childs_lane(self):
        self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))
        payload = self.write_payload("sess-parent", self.a_py)
        payload.pop("agent_id")
        rc, out = self.run_gate(WRITE_GATE, payload)
        self.assertTrue(self.denied(out))
        self.assertIn("agent-a", out)

    def test_a_whole_tree_verb_is_denied_while_a_child_holds_a_lane(self):
        self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))
        rc, out = self.run_gate(
            BASH_GATE, self.bash_payload("sess-parent", "git reset --hard HEAD"))
        self.assertTrue(self.denied(out))
        self.assertIn("agent-a", out)

    def test_the_owner_may_touch_its_own_lane(self):
        self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))
        rc, out = self.run_gate(
            BASH_GATE, self.bash_payload("agent-a", "git checkout -- pkg/a.py"))
        self.assertFalse(self.denied(out))


class QuotedMention(IsolationCase):

    def test_a_verb_inside_a_quoted_argument_is_text(self):
        self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))
        for command in ('git commit -m "revert the git checkout"',
                        'echo "rm -rf pkg"',
                        "git commit -m 'git reset --hard was wrong'"):
            rc, out = self.run_gate(BASH_GATE, self.bash_payload("agent-b", command))
            self.assertFalse(self.denied(out), command)

    def test_stash_list_and_show_are_not_whole_tree_verbs(self):
        self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))
        for command in ("git stash list", "git stash show"):
            rc, out = self.run_gate(BASH_GATE, self.bash_payload("agent-b", command))
            self.assertFalse(self.denied(out), command)
        rc, out = self.run_gate(BASH_GATE, self.bash_payload("agent-b", "git stash"))
        self.assertTrue(self.denied(out))


class RedirectTargets(IsolationCase):

    def test_a_redirect_onto_someone_elses_lane_is_denied(self):
        self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))
        for command in ("echo bad > pkg/a.py", "echo bad >> pkg/a.py",
                        f"echo bad >{self.a_py}"):
            rc, out = self.run_gate(BASH_GATE, self.bash_payload("agent-b", command))
            self.assertTrue(self.denied(out), command)

    def test_a_descriptor_redirect_names_no_file(self):
        self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))
        rc, out = self.run_gate(
            BASH_GATE, self.bash_payload("agent-b", "pytest -q 2>&1 | tail -5"))
        self.assertFalse(self.denied(out))

    def test_cd_moves_the_base_a_relative_target_resolves_against(self):
        self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))
        rc, out = self.run_gate(
            BASH_GATE,
            self.bash_payload("agent-b", f"cd {self.tree}/pkg && rm a.py",
                              cwd=self.home))
        self.assertTrue(self.denied(out))


class BroadStaging(IsolationCase):
    """The half the dimension gate cannot see: two SUBAGENTS of one session are
    one dimension to it, so B's `git add -A` over A's uncommitted files was never
    denied. Here the lane is keyed by process, so it is."""

    def test_broad_add_is_denied_while_a_sibling_holds_a_lane(self):
        self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))
        for command in ("git add -A", "git add --all", "git add .",
                        'git commit -am "wip"', "git commit --all"):
            rc, out = self.run_gate(BASH_GATE, self.bash_payload("agent-b", command))
            self.assertTrue(self.denied(out), command)
            self.assertIn("agent-a", out)

    def test_explicit_pathspec_staging_passes(self):
        self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))
        rc, out = self.run_gate(BASH_GATE, self.bash_payload("agent-b", "git add b.py"))
        self.assertFalse(self.denied(out))

    def test_broad_add_with_no_other_lane_passes(self):
        solo = os.path.join(self.home, "work", "solo")
        os.makedirs(os.path.join(solo, ".git"))
        self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))
        rc, out = self.run_gate(BASH_GATE, self.bash_payload("agent-b", "git add -A", cwd=solo))
        self.assertFalse(self.denied(out))

    def test_the_repo_flag_moves_the_staged_root(self):
        self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))
        rc, out = self.run_gate(
            BASH_GATE, self.bash_payload("agent-b", f"git -C {self.tree} add -A",
                                         cwd=self.home))
        self.assertTrue(self.denied(out))


class ShellCBodies(IsolationCase):
    """A `-c` body is a command, not a string."""

    def test_a_shell_c_body_is_rescanned(self):
        self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))
        for command in (f'bash -c "rm -rf {self.tree}/pkg"',
                        f"sh -c 'git checkout -- {self.a_py}'",
                        f'env -u HOME bash -c "rm -rf {self.tree}/pkg"',
                        f'bash -c "bash -c \'rm -rf {self.tree}/pkg\'"'):
            rc, out = self.run_gate(BASH_GATE, self.bash_payload("agent-b", command))
            self.assertTrue(self.denied(out), command)

    def test_a_python_c_body_gets_a_best_effort_pass(self):
        self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))
        rc, out = self.run_gate(
            BASH_GATE,
            self.bash_payload("agent-b", f'python3 -c "rm -rf {self.tree}/pkg"'))
        self.assertTrue(self.denied(out))

    def test_a_mention_that_is_not_a_c_body_stays_text(self):
        self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))
        for command in ('git commit -m "run bash -c rm -rf pkg next time"',
                        f'echo "bash -c \'rm -rf {self.tree}/pkg\'"'):
            rc, out = self.run_gate(BASH_GATE, self.bash_payload("agent-b", command))
            self.assertFalse(self.denied(out), command)

    def test_recursion_is_bounded(self):
        """A body nested past the depth limit must not hang or crash; the gate
        stops looking and allows, it never fails closed on a parse limit."""
        deep = "rm -rf " + self.tree + "/pkg"
        for _ in range(6):
            deep = 'bash -c "' + deep.replace('"', '\\"') + '"'
        rc, out = self.run_gate(BASH_GATE, self.bash_payload("agent-b", deep))
        self.assertEqual(rc, 0)


class ReleaseIsTheOperators(IsolationCase):

    def test_release_from_bash_is_denied_in_every_shape(self):
        for command in ("octo ps --release agent-a",
                        "python3 ~/.claude/scripts/octo.py ps --release agent-a",
                        "env -u CLAUDE_SESSION_ID octo ps --release=agent-a",
                        "ls && octo ps --release agent-a"):
            rc, out = self.run_gate(BASH_GATE, self.bash_payload("agent-b", command))
            self.assertTrue(self.denied(out), command)
            self.assertIn("--release", out)

    def test_the_word_release_alone_does_not_fire(self):
        for command in ("gh release list", 'git commit -m "octo --release notes"'):
            rc, out = self.run_gate(BASH_GATE, self.bash_payload("agent-b", command))
            self.assertFalse(self.denied(out), command)


class ArmsBoundary(IsolationCase):

    def _arms(self, mapping: dict):
        cfg = os.path.join(self.home, ".claude", "company", "config")
        os.makedirs(cfg, exist_ok=True)
        with open(os.path.join(cfg, "arms-paths.json"), "w", encoding="utf-8") as fh:
            json.dump(mapping, fh)

    def _two_arms(self):
        for name in ("alpha", "beta"):
            os.makedirs(os.path.join(self.home, "arms", name, ".git"), exist_ok=True)
        return (os.path.join(self.home, "arms", "alpha"),
                os.path.join(self.home, "arms", "beta"))

    def test_a_cross_arm_write_is_denied(self):
        alpha, beta = self._two_arms()
        self._arms({"alpha": "arms/alpha", "beta": "arms/beta"})
        rc, out = self.run_gate(
            WRITE_GATE, self.write_payload("agent-a", os.path.join(beta, "x.py"),
                                           cwd=alpha))
        self.assertTrue(self.denied(out))
        self.assertIn("beta", out)

    def test_a_write_inside_the_processes_own_arm_passes(self):
        alpha, _beta = self._two_arms()
        self._arms({"alpha": "arms/alpha", "beta": "arms/beta"})
        rc, out = self.run_gate(
            WRITE_GATE, self.write_payload("agent-a", os.path.join(alpha, "x.py"),
                                           cwd=alpha))
        self.assertFalse(self.denied(out))

    def test_no_arms_config_denies_nothing(self):
        """A public adopter declares no arms. A gate that invents a boundary
        nobody configured is noise, so the check fails open."""
        alpha, beta = self._two_arms()
        self.assertFalse(os.path.exists(
            os.path.join(self.home, ".claude", "company", "config", "arms-paths.json")))
        rc, out = self.run_gate(
            WRITE_GATE, self.write_payload("agent-a", os.path.join(beta, "x.py"),
                                           cwd=alpha))
        self.assertFalse(self.denied(out))

    def test_candidate_arrays_are_all_boundaries(self):
        """arms-paths values may be candidate arrays. Every candidate counts: a
        boundary that moves when a directory is missing is not a boundary."""
        alpha, beta = self._two_arms()
        self._arms({"alpha": ["nowhere/alpha", "arms/alpha"],
                    "beta": ["arms/beta", "nowhere/beta"]})
        rc, out = self.run_gate(
            WRITE_GATE, self.write_payload("agent-a", os.path.join(beta, "x.py"),
                                           cwd=alpha))
        self.assertTrue(self.denied(out))


class ForeignPayloads(IsolationCase):

    def test_each_gate_ignores_the_other_gates_tool(self):
        self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))
        rc, out = self.run_gate(BASH_GATE, self.write_payload("agent-b", self.a_py))
        self.assertFalse(self.denied(out))
        rc, out = self.run_gate(
            WRITE_GATE, self.bash_payload("agent-b", "rm -rf pkg"))
        self.assertFalse(self.denied(out))

    def test_a_read_only_command_reads_no_process_table(self):
        """Hot path: a command with nothing to collide with must not even open
        the table (the parse comes first, by construction)."""
        self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))
        before = os.stat(kernel_proc.ptable_path()).st_mtime_ns
        rc, out = self.run_gate(BASH_GATE, self.bash_payload("agent-b", "ls -la"))
        self.assertFalse(self.denied(out))
        self.assertEqual(os.stat(kernel_proc.ptable_path()).st_mtime_ns, before)


class QaCycle1(IsolationCase):
    """One test per defect QA cycle 1 raised, named by its number so a
    regression says which decision moved."""

    def hold(self):
        self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))

    def test_d1_every_deny_line_carries_its_rule_id(self):
        self.hold()
        self.run_gate(WRITE_GATE, self.write_payload("agent-b", self.a_py))
        self.run_gate(BASH_GATE, self.bash_payload("agent-b", "git reset --hard"))
        denies = [l for l in kernel_proc.read_journal("agent-b")
                  if l and l.get("kind") == "deny"]
        self.assertTrue(denies)
        for line in denies:
            self.assertEqual(line.get("rule"), "ARCHITECTURE.kernel-isolation")

    def test_d2_no_git_root_means_no_tree_to_own(self):
        """Outside a repo the fallback root was the cwd, which prefix-matched
        every lane under it: `git stash` from $HOME denied everything."""
        self.hold()
        for command in ("git stash", "git add -A", "git reset --hard"):
            rc, out = self.run_gate(
                BASH_GATE, self.bash_payload("agent-b", command, cwd=self.home))
            self.assertFalse(self.denied(out), command)

    def test_d3_a_valued_git_global_does_not_hide_the_verb(self):
        self.hold()
        for command in ("git -c commit.gpgsign=false checkout -- pkg/a.py",
                        "git --namespace ns checkout -- pkg/a.py",
                        "git -c a.b=c add -A",
                        "git --exec-path=/usr/lib/git-core checkout -- pkg/a.py"):
            rc, out = self.run_gate(BASH_GATE, self.bash_payload("agent-b", command))
            self.assertTrue(self.denied(out), command)

    def test_d4_wrapper_options_are_per_wrapper(self):
        self.hold()
        # -i is a FLAG for env and sudo: the command behind it must still be read
        for command in (f"env -i rm -rf {self.tree}/pkg",
                        f"sudo -i rm -rf {self.tree}/pkg",
                        f"env -u HOME -i rm -rf {self.tree}/pkg"):
            rc, out = self.run_gate(BASH_GATE, self.bash_payload("agent-b", command))
            self.assertTrue(self.denied(out), command)

    def test_d4_env_chdir_moves_the_base(self):
        self.hold()
        for command in (f"env -C {self.tree}/pkg rm a.py",
                        f"env --chdir={self.tree}/pkg rm a.py"):
            rc, out = self.run_gate(
                BASH_GATE, self.bash_payload("agent-b", command, cwd=self.home))
            self.assertTrue(self.denied(out), command)

    def test_d5_more_wrappers_and_grouping(self):
        self.hold()
        for command in (f"exec rm -rf {self.tree}/pkg",
                        f"timeout 5 rm -rf {self.tree}/pkg",
                        f"timeout -k 1 5 rm -rf {self.tree}/pkg",
                        f"nice -n 10 rm -rf {self.tree}/pkg",
                        f"time rm -rf {self.tree}/pkg",
                        f"(rm -rf {self.tree}/pkg)",
                        f"{{ rm -rf {self.tree}/pkg ; }}"):
            rc, out = self.run_gate(BASH_GATE, self.bash_payload("agent-b", command))
            self.assertTrue(self.denied(out), command)

    def test_d5_pushd_moves_the_base(self):
        self.hold()
        rc, out = self.run_gate(
            BASH_GATE, self.bash_payload("agent-b", f"pushd {self.tree}/pkg && rm a.py",
                                         cwd=self.home))
        self.assertTrue(self.denied(out))

    def test_d6_a_glob_reduces_to_its_literal_directory(self):
        self.hold()
        for command in ("git checkout -- pkg/*.py", "rm -rf pkg/*",
                        "git checkout -- :/", "git checkout -- ':(top)'"):
            rc, out = self.run_gate(BASH_GATE, self.bash_payload("agent-b", command))
            self.assertTrue(self.denied(out), command)

    def test_d6_a_glob_in_a_sibling_directory_still_passes(self):
        self.hold()
        os.makedirs(os.path.join(self.tree, "docs"))
        rc, out = self.run_gate(BASH_GATE, self.bash_payload("agent-b", "rm -rf docs/*.md"))
        self.assertFalse(self.denied(out))

    def test_d7_a_bare_checkout_changes_nothing(self):
        self.hold()
        rc, out = self.run_gate(BASH_GATE, self.bash_payload("agent-b", "git checkout"))
        self.assertFalse(self.denied(out))

    def test_d8_the_deny_names_the_unlock_as_phase_1b(self):
        self.hold()
        rc, out = self.run_gate(WRITE_GATE, self.write_payload("agent-b", self.a_py))
        self.assertIn("octo ps --release", out)
        self.assertIn("Phase 1b", out)

    def test_d9_delegating_releases_the_delegators_lanes(self):
        payload = self.write_payload("sess-parent", self.a_py)
        payload.pop("agent_id")
        self.run_gate(WRITE_GATE, payload)
        self.assertTrue(kernel_proc.read_ptable()["processes"]["sess-parent"]["lanes"])
        rc, out = self.run_gate(WRITE_GATE, {
            "session_id": "sess-parent", "tool_name": "Agent",
            "tool_input": {"prompt": "build", "subagent_type": "Backend Architect"},
            "cwd": self.tree})
        self.assertFalse(self.denied(out))
        self.assertEqual(kernel_proc.read_ptable()["processes"]["sess-parent"]["lanes"], [])
        released = [l for l in kernel_proc.read_journal("sess-parent")
                    if l and l.get("kind") == "release"]
        self.assertEqual(released[-1].get("reason"), "delegate")
        # the child may now write what the parent wrote before spawning it
        rc, out = self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))
        self.assertFalse(self.denied(out))

    def test_d9_the_sibling_rule_survives_the_release(self):
        self.hold()
        self.run_gate(WRITE_GATE, {"session_id": "sess-parent", "agent_id": "agent-a",
                                   "tool_name": "Agent", "tool_input": {"prompt": "x"},
                                   "cwd": self.tree})
        # agent-a released ITS lanes; agent-b's are untouched
        self.run_gate(WRITE_GATE, self.write_payload("agent-b", os.path.join(self.tree, "b.py")))
        rc, out = self.run_gate(
            WRITE_GATE, self.write_payload("agent-a", os.path.join(self.tree, "b.py")))
        self.assertTrue(self.denied(out))
        self.assertIn("agent-b", out)

    def test_d9_a_parent_lane_claimed_after_the_spawn_still_binds(self):
        rc, out = self.run_gate(WRITE_GATE, {
            "session_id": "sess-parent", "tool_name": "Agent",
            "tool_input": {"prompt": "build"}, "cwd": self.tree})
        payload = self.write_payload("sess-parent", self.a_py)
        payload.pop("agent_id")
        self.run_gate(WRITE_GATE, payload)
        rc, out = self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))
        self.assertTrue(self.denied(out))
        self.assertIn("sess-parent", out)

    def test_d10_no_ptable_on_disk_claims_nothing(self):
        """Still claims nothing, and since QA cycle 3 F3 it also DENIES, because
        the journals of the three registered processes are sitting right there:
        a table that is gone beside live journals is a machine whose record was
        removed, not a machine with nothing on it. The half this test was
        written for is unchanged and is what is asserted last: a read must never
        materialise the file.
        """
        os.unlink(kernel_proc.ptable_path())
        rc, out = self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))
        self.assertTrue(self.denied(out))
        self.assertFalse(os.path.exists(kernel_proc.ptable_path()))

    def test_residual_the_kernels_own_state_is_a_floor(self):
        kdir = kernel_proc.kernel_dir()
        rc, out = self.run_gate(
            WRITE_GATE, self.write_payload("agent-b", os.path.join(kdir, "ptable.json")))
        self.assertTrue(self.denied(out))
        for command in (f"rm -rf {kdir}", f"echo x > {kdir}/ptable.json",
                        f"sed -i s/a/b/ {kdir}/journal/agent-a.jsonl"):
            rc, out = self.run_gate(BASH_GATE, self.bash_payload("agent-b", command))
            self.assertTrue(self.denied(out), command)

    def test_the_added_deny_set(self):
        self.hold()
        for command in ("git rm -f pkg/a.py", "git mv pkg/a.py pkg/c.py",
                        "git add -u", "git add ./",
                        f"unlink {self.a_py}", f"truncate -s 0 {self.a_py}",
                        f"find {self.tree}/pkg -name '*.py' -delete",
                        f"find {self.tree}/pkg -exec rm {{}} ;",
                        f"xargs rm -f {self.a_py}"):
            rc, out = self.run_gate(BASH_GATE, self.bash_payload("agent-b", command))
            self.assertTrue(self.denied(out), command)

    def test_named_residuals_are_honestly_uncovered(self):
        """These evade by design (a distinct verb table or an evaluator), and
        the report says so. Pinned so the claim stays true instead of drifting
        into a silent regression either way."""
        self.hold()
        deep = f"rm -rf {self.tree}/pkg"
        for _ in range(4):
            deep = 'bash -c "' + deep.replace('"', '\\"') + '"'
        for command in (
                # separate verb tables
                f"rsync -a --delete /tmp/x/ {self.tree}/pkg/",
                f"shred -u {self.a_py}",
                # `ln -sf /dev/null <lane>` USED TO SIT HERE and no longer
                # does: QA cycle 10 put `ln` in the mutator table, so the
                # destination of a link is a write like any other. It is
                # pinned as DENIED in
                # `QaCycle10.test_f4_the_destination_of_a_link_is_a_write`.
                f"perl -pi -e s/a/b/ {self.a_py}",
                # an evaluator: the body is Python, not shell. AIMED AT A LANE,
                # which is what is still uncovered. The same evaluators aimed at
                # the KERNEL DIRECTORY moved to
                # `test_the_kernel_floor_is_an_effect_not_a_verb` in QA cycle 9,
                # because they now deny.
                f'python3 -c "import shutil; shutil.rmtree(\'{self.tree}/pkg\')"',
                # git verbs that rewrite the tree through a different door
                "git apply /tmp/p.diff", "git rebase main", "git merge main",
                "git pull", "git cherry-pick HEAD~1", "git revert HEAD",
                # the shell would expand these; this gate does not run the shell
                f"DIR={self.tree}/pkg && rm -rf $DIR",
                # brace expansion is the shell's job too
                f"rm -rf {self.tree}/{{pkg,x}}",
                # xargs fed from stdin: the target never appears in the command
                f"echo {self.tree}/pkg | xargs rm -rf",
                f"xargs rm -f < /tmp/list",
                f"cat /tmp/list | xargs rm -f",
                # a -c body nested deeper than the scan limit
                deep):
            rc, out = self.run_gate(BASH_GATE, self.bash_payload("agent-b", command))
            self.assertFalse(self.denied(out),
                             command + " is now covered: move it out of the residual list "
                             "in the gate docstring and the PR comment")


class QaCycle2(IsolationCase):
    """The four false denies and the three residual gaps the cycle-1 widening
    introduced. A gate that denies work nobody owns is not stricter, it is
    broken; these pin the line where the widening stops."""

    def hold(self):
        self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))

    def test_f1_a_glob_that_reaches_no_lane_passes(self):
        self.hold()
        for command in ("rm -f *.log", "git checkout -- *.md", "rm -rf zz*",
                        "git checkout -- x*.py"):
            rc, out = self.run_gate(BASH_GATE, self.bash_payload("agent-b", command))
            self.assertFalse(self.denied(out), command)

    def test_f1_a_glob_that_does_reach_a_lane_is_denied(self):
        self.hold()
        for command in ("rm -f *.py", "git checkout -- a*"):
            rc, out = self.run_gate(BASH_GATE, self.bash_payload(
                "agent-b", command, cwd=os.path.join(self.tree, "pkg")))
            self.assertTrue(self.denied(out), command)
        # a glob one level up still reaches the lane through its directory
        rc, out = self.run_gate(BASH_GATE, self.bash_payload("agent-b", "rm -rf pk*"))
        self.assertTrue(self.denied(out))

    def test_f1_the_specs_that_mean_everything_keep_the_root(self):
        self.hold()
        for command in ("rm -rf *", "git checkout -- :/", "git checkout -- ':(top)'",
                        "git checkout -- ."):
            rc, out = self.run_gate(BASH_GATE, self.bash_payload("agent-b", command))
            self.assertTrue(self.denied(out), command)

    def test_f2_a_find_name_filter_is_the_target_not_the_root(self):
        self.hold()
        for command in ("find . -name '*.pyc' -delete",
                        f"find {self.tree} -name '*.log' -delete",
                        "find . -iname '*.tmp' -delete"):
            rc, out = self.run_gate(BASH_GATE, self.bash_payload("agent-b", command))
            self.assertFalse(self.denied(out), command)
        rc, out = self.run_gate(
            BASH_GATE, self.bash_payload("agent-b", "find . -name '*.py' -delete"))
        self.assertTrue(self.denied(out))

    def test_g1_iname_and_ipath_match_case_insensitively(self):
        self.hold()
        for command in ("find . -iname 'A.PY' -delete", "find . -ipath '*PKG/A.PY' -delete"):
            rc, out = self.run_gate(BASH_GATE, self.bash_payload("agent-b", command))
            self.assertTrue(self.denied(out), command)
        # -name stays case-SENSITIVE, which is what find does
        rc, out = self.run_gate(
            BASH_GATE, self.bash_payload("agent-b", "find . -name 'A.PY' -delete"))
        self.assertFalse(self.denied(out))

    def test_f3_only_the_token_after_exec_is_the_program(self):
        self.hold()
        for command in ("find pkg -exec grep rm {} ;", "find pkg -name rm -print"):
            rc, out = self.run_gate(BASH_GATE, self.bash_payload("agent-b", command))
            self.assertFalse(self.denied(out), command)
        rc, out = self.run_gate(
            BASH_GATE, self.bash_payload("agent-b", "find pkg -exec rm {} ;"))
        self.assertTrue(self.denied(out))

    def test_f4_a_flag_is_not_a_branch_name(self):
        self.hold()
        for command in ("git checkout -q", "git checkout --quiet", "git checkout -q -f"):
            rc, out = self.run_gate(BASH_GATE, self.bash_payload("agent-b", command))
            self.assertFalse(self.denied(out), command)
        rc, out = self.run_gate(BASH_GATE, self.bash_payload("agent-b", "git checkout -q main"))
        self.assertTrue(self.denied(out))

    def test_r2_the_floor_reads_the_state_verbs(self):
        kdir = kernel_proc.kernel_dir()
        for command in (f"touch {kdir}/ptable.json", f"chmod 777 {kdir}/ptable.json",
                        f"chattr +i {kdir}/ptable.json", f"dd if=/dev/zero of={kdir}/ptable.json"):
            rc, out = self.run_gate(BASH_GATE, self.bash_payload("agent-b", command))
            self.assertTrue(self.denied(out), command)

    def test_r2_the_state_verbs_are_floor_only(self):
        """`touch` on a sibling's file is not the collision this rule is about,
        so the state verbs never become lane denies."""
        self.hold()
        for command in (f"touch {self.a_py}", f"chmod 644 {self.a_py}"):
            rc, out = self.run_gate(BASH_GATE, self.bash_payload("agent-b", command))
            self.assertFalse(self.denied(out), command)

    def test_n2_the_floor_covers_the_ledgers_ancestors(self):
        for path in (os.path.dirname(kernel_proc.kernel_dir()),
                     os.path.join(self.home, ".claude"), self.home):
            rc, out = self.run_gate(BASH_GATE, self.bash_payload("agent-b", f"rm -rf {path}"))
            self.assertTrue(self.denied(out), path)

    def test_n1_every_deny_names_the_unlock(self):
        self.hold()
        for gate, payload in (
                (BASH_GATE, self.bash_payload("agent-b", "git reset --hard")),   # tree
                (BASH_GATE, self.bash_payload("agent-b", "git add -A")),          # stage
                (BASH_GATE, self.bash_payload("agent-b", "rm -rf pkg")),          # lane
                (WRITE_GATE, self.write_payload("agent-b", self.a_py))):
            rc, out = self.run_gate(gate, payload)
            self.assertTrue(self.denied(out))
            self.assertIn("octo ps --release", out)
            self.assertIn("Phase 1b", out)


class UnreadableTableFailsClosed(IsolationCase):
    """QA cycle 1, F1. The serious one: a `processes` that is not an object was
    a silent TOTAL loss, and the gate then let the intruder through.

    Measured on the tip before this change. A healthy table where `owner` holds
    a lane: the gate denies the second writer and names the holder. The same
    rows rewritten as an ARRAY: the same call produced empty output, which the
    harness reads as allowed, and the write that followed republished a one-row
    table in which the INTRUDER held the lane. `sane_table` returns an empty
    table for that shape, an empty table says nobody owns anything, and the gate
    whose whole job is to deny the second writer had nothing left to deny with.

    One writer per tree is fail-closed, so the state where ownership is
    unknowable is a deny. Not a compromise: the state is unreachable from the
    kernel's own writers, so reaching it means a writer that is not the kernel
    touched the file, which is the last moment to keep working blind.
    """

    def list_shaped(self):
        """The same rows, as an array. Nothing is missing from the FILE."""
        with open(kernel_proc.ptable_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        data["processes"] = list(data["processes"].values())
        with open(kernel_proc.ptable_path(), "w", encoding="utf-8") as fh:
            json.dump(data, fh)

    def reason(self, out: str) -> str:
        obj = json.loads(out or "{}")
        return (obj.get("hookSpecificOutput") or {}).get("permissionDecisionReason") or ""

    def setUp(self):
        super().setUp()
        # the healthy half of the reproduction, first: agent-a owns a.py
        rc, out = self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))
        self.assertFalse(self.denied(out), "the owner claims its own lane")
        self.assertIn("agent-a", kernel_proc.read_ptable()["processes"])

    def test_the_write_gate_denies_instead_of_going_blind(self):
        rc, out = self.run_gate(WRITE_GATE, self.write_payload("agent-b", self.a_py))
        self.assertTrue(self.denied(out), "the healthy table denies the second writer")
        self.assertIn("agent-a", self.reason(out))

        self.list_shaped()
        with open(kernel_proc.ptable_path(), "rb") as fh:
            before = fh.read()
        rc, out = self.run_gate(WRITE_GATE, self.write_payload("agent-b", self.a_py))
        self.assertEqual(rc, 0)
        self.assertTrue(self.denied(out), "an unknowable owner is denied, never allowed")
        reason = self.reason(out)
        self.assertIn("process table is unreadable", reason)
        self.assertIn("array of 3 value(s)", reason, "the fault names what it found")
        self.assertIn(self.a_py, reason, "and the path it could not decide")

        with open(kernel_proc.ptable_path(), "rb") as fh:
            self.assertEqual(fh.read(), before,
                             "and the denied write took no lane: the file is untouched, "
                             "so agent-a's lane is still in it")

    def register_hook(self, payload):
        """The REAL SessionStart reflex, in its own process. Nothing here may be
        simulated: the finding is about what that hook publishes."""
        env = dict(os.environ)
        env["HOME"] = self.home
        env["USERPROFILE"] = self.home
        cp = subprocess.run([sys.executable, str(SCRIPTS / "r__session__proc-register.py")],
                            input=json.dumps(payload), capture_output=True,
                            text=True, env=env, cwd=self.home, timeout=60)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        return cp

    def test_a_routine_session_start_does_not_reopen_the_gate(self):
        """QA cycle 2, F1. The gate failed closed and then stopped, because the
        very next `register` published `fresh_table()` plus its own row and the
        fault went with it. Measured on the tip before this change, this exact
        sequence: denied while faulted, register hook rc=0, rows on disk
        `['newsess']`, fault `''`, the same intruder ALLOWED, and `agent-b`
        holding the lane `agent-a` had claimed.

        SessionStart fires on startup, resume, clear and compact, so the
        protection lasted minutes. The row is still published; what does not
        come with it any more is an empty base.
        """
        self.list_shaped()
        rc, out = self.run_gate(WRITE_GATE, self.write_payload("agent-b", self.a_py))
        self.assertTrue(self.denied(out), "denied while faulted, as before")

        self.register_hook({"session_id": "newsess", "source": "startup",
                            "cwd": self.home})
        with open(kernel_proc.ptable_path(), encoding="utf-8") as fh:
            disk = json.load(fh)
        self.assertIn("newsess", disk["processes"], "the hook wrote its row")
        self.assertIn(kernel_proc.FAULT_KEY, disk, "and carried the fault with it")

        rc, out = self.run_gate(WRITE_GATE, self.write_payload("agent-b", self.a_py))
        self.assertTrue(self.denied(out),
                        "a registration is not a repair: the owner of that lane "
                        "is still unknown")
        reason = self.reason(out)
        self.assertIn("process table is unreadable", reason)
        self.assertIn("array of 3 value(s)", reason, "the original fault, not a new one")
        self.assertNotIn("lanes", json.dumps(disk["processes"]),
                         "and no lane was transferred to the intruder")

    def test_the_deny_says_how_to_get_out_of_it(self):
        """A gate that denies every hooked write with no way out is a brick.
        There is no subcommand and no env hatch by design (an agent clearing
        this would be clearing its own gate), so the deny carries the file
        operation the operator runs in a terminal where no hook fires."""
        self.list_shaped()
        rc, out = self.run_gate(WRITE_GATE, self.write_payload("agent-b", self.a_py))
        reason = self.reason(out)
        self.assertIn(f"rm {kernel_proc.ptable_path()}", reason)
        self.assertIn(kernel_proc.FAULT_KEY, reason)
        self.assertIn("CARRIES THE FAULT FORWARD", reason,
                      "so nobody waits for a restart to fix it")

    def test_the_bash_gate_denies_instead_of_going_blind(self):
        """The twin. Both gates read the same table through the same seam, so a
        fix in one of them and not the other is half a gate."""
        cmd = f"rm -f {self.a_py}"
        rc, out = self.run_gate(BASH_GATE, self.bash_payload("agent-b", cmd))
        self.assertTrue(self.denied(out), "the healthy table denies the second writer")

        self.list_shaped()
        rc, out = self.run_gate(BASH_GATE, self.bash_payload("agent-b", cmd))
        self.assertEqual(rc, 0)
        self.assertTrue(self.denied(out))
        reason = self.reason(out)
        self.assertIn("process table is unreadable", reason)
        self.assertIn(self.a_py, reason)


class DeletedTableFailsClosed(IsolationCase):
    """QA cycle 3, F3. Corrupting the table was the loud attack and it was
    guarded; DELETING it was the cheap one and it was not, and both reach the
    file through the same door (`rm` is denied here, `python3 -c` and `ln -sf`
    are not, which `QaCycle1.test_named_residuals_are_honestly_uncovered`
    already pins).

    Measured: the healthy table denies the intruder, one `os.unlink` of the
    ptable and the same call is ALLOWED, with no fault, no quarantine copy and
    no doctor FAIL. Corruption bought a deny-all the attacker also suffers;
    deletion bought a silent allow-everything machine. Failing closed on one
    and open on the other pays the outage against the move nobody would make.
    """

    def hold(self):
        rc, out = self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))
        self.assertFalse(self.denied(out))
        self.assertIn("agent-a", kernel_proc.read_ptable()["processes"])

    def reason(self, out: str) -> str:
        obj = json.loads(out or "{}")
        return (obj.get("hookSpecificOutput") or {}).get("permissionDecisionReason") or ""

    def test_deleting_the_table_does_not_open_the_gate(self):
        self.hold()
        rc, out = self.run_gate(WRITE_GATE, self.write_payload("agent-b", self.a_py))
        self.assertTrue(self.denied(out), "the healthy table denies the intruder")

        os.unlink(kernel_proc.ptable_path())
        rc, out = self.run_gate(WRITE_GATE, self.write_payload("agent-b", self.a_py))
        self.assertTrue(self.denied(out), "and so does a table that was removed")
        self.assertIn("absent", self.reason(out))
        self.assertFalse(os.path.exists(kernel_proc.ptable_path()),
                         "a denied write still materialises nothing")

    def test_the_bash_twin_denies_it_too(self):
        self.hold()
        os.unlink(kernel_proc.ptable_path())
        rc, out = self.run_gate(BASH_GATE,
                                self.bash_payload("agent-b", f"rm -f {self.a_py}"))
        self.assertTrue(self.denied(out))
        self.assertIn("absent", self.reason(out))

    def test_a_machine_with_nothing_running_is_still_a_fresh_install(self):
        """The half that keeps this from being "deny always". A quiet machine
        still has its journals, it just has old ones, and both gates have to
        allow: a rule that cannot tell a fresh install from a loss is a broken
        laptop, not a stricter gate.

        The journals used to be DELETED here to build "quiet", and cycle 5 M1
        made that a different state with a different answer: an empty journal
        directory on a machine that has run hooks is a sweep, not an idle
        laptop, and the kernel cannot produce it (`register` writes its own
        journal before it takes the lock). The test below is that half.
        """
        os.unlink(kernel_proc.ptable_path())
        for name in os.listdir(kernel_proc.journal_dir()):
            if name.endswith(".jsonl"):
                self.age_journal(name[:-len(".jsonl")], kernel_proc.TTL + 300)
        rc, out = self.run_gate(WRITE_GATE, self.write_payload("agent-b", self.a_py))
        self.assertFalse(self.denied(out))
        rc, out = self.run_gate(BASH_GATE,
                                self.bash_payload("agent-b", f"rm -f {self.a_py}"))
        self.assertFalse(self.denied(out))

    def test_the_table_and_the_journals_swept_together_is_denied(self):
        """Cycle 5 M1 state 1, and the one edit from the test above: `rm
        ptable.json journal/*.jsonl`. The directory stays, so the deletion guard
        reads it as usable, and no journal reads live because there are none.
        Two deletions, every history marker intact, and both gates allowed."""
        self.hold()
        os.unlink(kernel_proc.ptable_path())
        for name in os.listdir(kernel_proc.journal_dir()):
            os.unlink(os.path.join(kernel_proc.journal_dir(), name))
        rc, out = self.run_gate(WRITE_GATE, self.write_payload("agent-b", self.a_py))
        self.assertTrue(self.denied(out))
        self.assertIn("journal directory", self.reason(out))

    def test_an_expired_holder_does_not_hold_the_machine_faulted(self):
        """Liveness is the existing definition, not a file count: journals past
        the TTL are dead, and a table deleted beside only dead journals is a
        machine that really has nothing running."""
        self.hold()
        os.unlink(kernel_proc.ptable_path())
        for name in os.listdir(kernel_proc.journal_dir()):
            if name.endswith(".jsonl"):
                self.age_journal(name[:-len(".jsonl")], kernel_proc.TTL + 300)
        rc, out = self.run_gate(WRITE_GATE, self.write_payload("agent-b", self.a_py))
        self.assertFalse(self.denied(out))


class SymlinkLoopFailsClosed(IsolationCase):
    """QA cycle 3, F1, from the gate. `read_ptable_detail` had two `except
    OSError` legs and only one of them carried the fault forward. The tested
    shape (a directory at the ptable path) failed at `open` and hit the carrying
    leg; an ELOOP symlink fails one line earlier at the stat and hit the other,
    so through it the cycle-4 loss reproduced verbatim: denied, one SessionStart,
    fault gone, the same intruder allowed.

    Which leg an unreadable table lands on is chosen by whoever made it
    unreadable. A fail-closed rule that holds for one syscall and not the other
    is not fail-closed.
    """

    def loop(self):
        path = kernel_proc.ptable_path()
        os.unlink(path)
        os.symlink(path, path)

    def reason(self, out: str) -> str:
        obj = json.loads(out or "{}")
        return (obj.get("hookSpecificOutput") or {}).get("permissionDecisionReason") or ""

    def register_hook(self, payload):
        env = dict(os.environ)
        env["HOME"] = self.home
        env["USERPROFILE"] = self.home
        cp = subprocess.run([sys.executable, str(SCRIPTS / "r__session__proc-register.py")],
                            input=json.dumps(payload), capture_output=True,
                            text=True, env=env, cwd=self.home, timeout=60)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        return cp

    def test_the_fault_survives_the_session_start_on_this_leg_too(self):
        rc, out = self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))
        self.assertFalse(self.denied(out), "the owner claims its lane first")

        self.loop()
        rc, out = self.run_gate(WRITE_GATE, self.write_payload("agent-b", self.a_py))
        self.assertTrue(self.denied(out), "denied while the table cannot be read")
        self.assertIn("could not be read", self.reason(out))

        self.register_hook({"session_id": "newsess", "source": "startup",
                            "cwd": self.home})
        with open(kernel_proc.ptable_path(), encoding="utf-8") as fh:
            disk = json.load(fh)
        self.assertIn("newsess", disk["processes"], "the hook wrote its row")
        self.assertIn(kernel_proc.FAULT_KEY, disk, "and carried the fault with it")

        rc, out = self.run_gate(WRITE_GATE, self.write_payload("agent-b", self.a_py))
        self.assertTrue(self.denied(out),
                        "a registration is not a repair, on this leg either")
        self.assertNotIn("lanes", json.dumps(disk["processes"]),
                         "and no lane was transferred to the intruder")


class FaultDenyMessageIsAboutTheRightThing(IsolationCase):
    """QA cycle 3, F6. During a fault the Bash gate denies `git stash` in the
    process's OWN tree, which is right (that verb rewrites every file under the
    root, including files held by processes the gate can no longer see) and the
    message was wrong about why: it said "cannot tell whether another process
    holds <root>" about a path nobody was contesting. The verdict stays, the
    sentence has to say what is actually unknown.
    """

    def reason(self, out: str) -> str:
        obj = json.loads(out or "{}")
        return (obj.get("hookSpecificOutput") or {}).get("permissionDecisionReason") or ""

    def test_a_whole_tree_verb_in_your_own_tree_is_denied_for_the_stated_reason(self):
        rc, out = self.run_gate(BASH_GATE, self.bash_payload("agent-b", "git stash"))
        self.assertFalse(self.denied(out), "healthy: your own tree is yours")

        with open(kernel_proc.ptable_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        data["processes"] = list(data["processes"].values())
        with open(kernel_proc.ptable_path(), "w", encoding="utf-8") as fh:
            json.dump(data, fh)

        rc, out = self.run_gate(BASH_GATE, self.bash_payload("agent-b", "git stash"))
        self.assertTrue(self.denied(out), "fail closed, as designed")
        reason = self.reason(out)
        self.assertIn("any OTHER process is writing in", reason)
        self.assertIn("git stash", reason, "and it names the verb that takes the tree")
        self.assertNotIn(f"holds {self.tree}", reason,
                         "nobody was contesting that path; that was the wrong claim")

    def test_a_path_verb_still_says_holds(self):
        """The other branch, so the fix is a discrimination and not a blanket
        rewording: a target that really is one path keeps the sentence it had."""
        with open(kernel_proc.ptable_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        data["processes"] = list(data["processes"].values())
        with open(kernel_proc.ptable_path(), "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        rc, out = self.run_gate(BASH_GATE,
                                self.bash_payload("agent-b", f"rm -f {self.a_py}"))
        self.assertTrue(self.denied(out))
        self.assertIn(f"holds {self.a_py}", self.reason(out))


class DenyNamesWhatIsKnown(IsolationCase):
    """QA cycle 2, C: `describe()` inferred `main loop` from a missing `ppid`.

    For the row `claim_lane` creates when a register hook loses its race with
    the process's first write, that inference is simply wrong: the row carries
    neither `type` nor `ppid`, and the deny told the reader a subagent was a
    main loop. These strings are read by a human while blocked, so a guess
    printed as a fact there is expensive.
    """

    def racer(self, pid="racer"):
        """The row the race actually leaves: a lane, no type, no parent."""
        kernel_proc.append(pid, {"kind": "tool", "tool_name": "Write"})
        kernel_proc.claim_lane(pid, self.a_py, tree=self.tree)
        row = kernel_proc.read_ptable()["processes"][pid]
        self.assertNotIn("type", row)
        self.assertNotIn("ppid", row)
        return row

    def test_a_lane_claimed_by_a_racing_process_is_not_called_a_main_loop(self):
        self.racer()
        for gate, payload in ((WRITE_GATE, self.write_payload("agent-a", self.a_py)),
                              (BASH_GATE, self.bash_payload("agent-a",
                                                            f"rm -rf {self.a_py}"))):
            rc, out = self.run_gate(gate, payload)
            self.assertTrue(self.denied(out))
            self.assertNotIn("main loop", out, "the kernel never learned this type")
            self.assertIn(f"pid racer (type {kernel_proc.UNKNOWN_TYPE}", out)

    def test_a_registered_holder_still_reads_its_real_type(self):
        """The `?` is a statement about knowledge, not a blanket: a row that
        carries a type still prints it, so the deny stays as informative as it
        ever was for the common case."""
        self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))
        rc, out = self.run_gate(WRITE_GATE, self.write_payload("agent-b", self.a_py))
        self.assertTrue(self.denied(out))
        self.assertIn("pid agent-a (builder,", out)
        self.assertNotIn(kernel_proc.UNKNOWN_TYPE, out)

    def test_both_gates_describe_a_process_with_the_same_words(self):
        """One vocabulary across the two gates, and the same one the readers
        use. A parent link still proves `subagent`; its absence proves nothing."""
        for gate, name in ((WRITE_GATE, "wg"), (BASH_GATE, "bg")):
            mod = _load(gate, name)
            self.assertIn("subagent", mod.describe("x", {"ppid": "p"}))
            self.assertIn(f"type {kernel_proc.UNKNOWN_TYPE}", mod.describe("x", {}))
            self.assertIn(f"type {kernel_proc.UNKNOWN_TYPE}", mod.describe("x", None))
            self.assertIn("builder", mod.describe("x", {"type": "builder"}))


class TheAgentProofClaimIsMeasured(IsolationCase):
    """QA cycle 3. `kernel_proc.recovery` explains why the way out is a file
    operation and not a subcommand, and it used to explain it with a claim the
    mechanism does not support: "a command an agent could run would be a
    command that clears its own gate". QA verified it for `rm`, `mv` and `>`
    and DEFEATED it with `python3 -c` and `ln -sf`.

    The docstring lists exactly which verbs are denied at the kernel directory.
    A list in prose drifts, so it is measured here: every verb it names as
    denied must deny. QA cycle 9 replaced the second half of that contract: the
    two paths it used to name as OPEN are closed, the floor is a named-path test
    rather than a verb list, and what is measured now is that the closed ones
    deny AND that reading kernel state through the read-only list still does
    not. When either half stops being true, the honest move is to update the
    docstring, not these tests.
    """

    def decide(self, command):
        rc, out = self.run_gate(BASH_GATE, self.bash_payload("agent-b", command))
        return "deny" if self.denied(out) else "allow"

    def test_every_verb_the_docstring_names_behaves_as_it_says(self):
        tbl = kernel_proc.ptable_path()
        denied = {
            "rm": f"rm -f {tbl}", "mv": f"mv {tbl} /tmp/x", "cp": f"cp /tmp/x {tbl}",
            "sed": f"sed -i s/a/b/ {tbl}", "tee": f"echo x | tee {tbl}",
            "unlink": f"unlink {tbl}", "truncate": f"truncate -s 0 {tbl}",
            "redirect": f"echo x > {tbl}", "touch": f"touch {tbl}",
            "chmod": f"chmod 000 {tbl}", "chattr": f"chattr +i {tbl}",
            "dd": f"dd of={tbl}",
        }
        doc = kernel_proc.recovery.__doc__
        for label, command in denied.items():
            self.assertEqual(self.decide(command), "deny", command)
            self.assertIn(f"`{label}`" if label not in ("redirect",) else "`>`", doc,
                          f"{label} is denied but the docstring does not name it")

    def test_the_kernel_floor_is_an_effect_not_a_verb(self):
        """QA cycle 9 F1, AND IT IS THE INVERSION OF THE TEST THAT USED TO SIT
        HERE. That test pinned two paths as OPEN (`ln -sf` and a `python3 -c`
        body aimed at the ptable) on the stated grounds that closing them was
        "a real expansion of the gate's verb detection with its own
        false-positive risk". What it was actually pinning was a way to DISABLE
        both gates: `mkfifo` (or `ln -sf` at a fifo) on a HOLDER'S JOURNAL wedges
        every gate that reads it inside `open()` until the harness kills it at
        `timeout: 5`, and a killed hook writes no stdout, emits no
        `permissionDecision`, and every matrix in this PR reads that as ALLOW.
        Measured over 20 s on both gates before the fix.

        So the floor is a NAMED-PATH test now, and this pins the direction it
        was inverted in: an allowlist of VERBS loses to the next verb, and the
        verbs below are the ones QA reached for after `rm` was denied. What this
        test STOPPED covering is the old "these two are open" claim, which was
        true and is now false; the interpreter aimed at a LANE is still open and
        is still pinned, one class up, in
        `QaCycle1.test_named_residuals_are_honestly_uncovered`.
        """
        tbl = kernel_proc.ptable_path()
        jnl = kernel_proc.journal_path("agent-a")
        for command in (f"ln -sf /dev/null {tbl}",
                        f"mkfifo {jnl}",
                        f"mknod {jnl} p",
                        f"shred -u {jnl}",
                        f"install -m 644 /dev/null {jnl}",
                        f"busybox rm -f {jnl}",
                        f'python3 -c "import os; os.unlink(\'{tbl}\')"',
                        f'python3 -c "open(\'{jnl}\',\'a\').write(\'x\')"',
                        f'python3 -c "import os;os.utime(\'{jnl}\',(1,1))"',
                        f'perl -e "open(F,\'>>\',\'{jnl}\')"',
                        f"cd {os.path.dirname(jnl)} && mkfifo agent-a.jsonl",
                        f"K={kernel_proc.kernel_dir()} && mkfifo $K/journal/x.jsonl"):
            self.assertEqual(self.decide(command), "deny", command)
        doc = kernel_proc.recovery.__doc__
        self.assertNotIn("INTERPRETER PATH IS OPEN", doc)
        self.assertIn("mkfifo", doc)

    def test_the_invocation_budget_bounds_the_whole_call_not_one_fan_out(self):
        """QA cycle 9 F2, at the gate, with the harness's own number as the
        assertion. `SCAN_BUDGET` bounded a fan-out and the Bash gate opens one
        per TARGET, so N targets bought N budgets: 8 targets over one stale row
        with an 8000-line journal measured 6.65 s, past `timeout: 5`, and a
        killed hook emits no `permissionDecision` at all, which every matrix in
        this PR reads as ALLOW.

        `timeout=5` here IS the harness. If a correct gate cannot answer inside
        it, neither can the real one, so this is the true property and not a
        wall-clock guess dressed up as one.

        THE VERDICT IS PINNED WITH A LIVE HOLDER RATHER THAN WITH THE CLOCK, and
        the first version of this test got that wrong in a way worth recording:
        it asserted DENY over sixteen STALE rows, which is the verdict only when
        the budget runs out before they are all read. That passed on a loaded
        box and failed on an idle one, where the gate has time to read every row
        and correctly FREES them. A test whose expected answer depends on how
        busy the machine is measures the machine. So `agent-a`'s real lane is
        one of the targets: the answer is DENY under both outcomes (it is found
        live if the scan reaches it, and UNKNOWN reads live if the budget is
        spent first), and what the clock decides is only how the gate got there.
        """
        import hashlib as _h
        self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))
        table = kernel_proc.read_ptable()
        start = time.time() - kernel_proc.TTL * 10
        targets = []
        for k in range(16):
            d = os.path.join(self.tree, "dead%d" % k)
            os.makedirs(d, exist_ok=True)
            f = os.path.join(d, "f.py")
            with open(f, "w") as fh:
                fh.write("x\n")
            targets.append(f)
            pid = "stale-%d" % k
            table["processes"][pid] = {
                "pid": pid, "type": "main", "worktree": self.tree,
                "registered_ts": start, "lanes": [f]}
            out, prev = [], None
            for i in range(8000):
                rec = {"seq": i, "ts": round(start + i * 1e-3, 6),
                       "start_ts": start, "pid": pid, "kind": "tool",
                       "prev": prev}
                raw = json.dumps(rec, separators=(",", ":"),
                                 sort_keys=True).encode()
                out.append(raw)
                prev = _h.sha256(raw).hexdigest()
            jp = kernel_proc.journal_path(pid)
            with open(jp, "wb") as fh:
                fh.write(b"\n".join(out) + b"\n")
            old = time.time() - kernel_proc.TTL * 5
            os.utime(jp, (old, old))
        with open(kernel_proc.ptable_path(), "w", encoding="utf-8") as fh:
            json.dump(table, fh)

        # the live holder's own lane, last, so every stale row is walked first
        targets.append(self.a_py)
        command = " && ".join("rm -f %s" % t for t in targets)
        env = dict(os.environ)
        env["HOME"] = self.home
        env["USERPROFILE"] = self.home
        env.pop("OCTO_LANE_OVERRIDE", None)
        try:
            cp = subprocess.run(
                [sys.executable, str(BASH_GATE)],
                input=json.dumps(self.bash_payload("agent-b", command)),
                capture_output=True, text=True, cwd=self.home, env=env,
                timeout=5)
        except subprocess.TimeoutExpired:
            self.fail("no verdict inside the harness timeout: the gate would "
                      "be killed with no decision, which reads as ALLOW")
        self.assertTrue(self.denied(cp.stdout),
                        "and the answer it gets there is a DENY, because one of "
                        "those targets is a LIVE holder's lane")
        # NAMING A HOLDER IS THE PROPERTY; naming `agent-a` SPECIFICALLY is not.
        # This line used to assert the second one and it is the very defect the
        # docstring above warns about one paragraph earlier: it pins WHICH
        # BRANCH RAN, and which branch runs is decided by the clock. Reproduced
        # on 2026-09-08 with six busy cores, three runs each, on THIS build and
        # on HEAD alike: the gate spends its journal budget before it reaches
        # `agent-a`'s lane, correctly denies on an unread `stale-N` row instead,
        # and says so in the deny. That is the fail-closed answer, not a miss.
        # So what is asserted is what the mechanism guarantees under both
        # outcomes: a holder is named, and when it is not the live one the deny
        # says the budget is why.
        named = [pid for pid in ["agent-a"] + ["stale-%d" % k for k in range(16)]
                 if pid in cp.stdout]
        self.assertTrue(named,
                        "naming the holder, which is the whole point of failing "
                        "closed rather than just failing")
        if named != ["agent-a"]:
            self.assertIn("budget", cp.stdout,
                          "a holder that was not confirmed live has to say so")

    def test_the_exclusion_reading_kernel_state_is_not_denied(self):
        """The over-fire half, and it is the price of inverting the floor: a
        READ through a tool that is not on the read-only list is denied too. So
        the list has to actually work, or the gate stops being a floor and
        becomes a wall. One edit from each violation above: the same path, a
        program that cannot write it."""
        tbl = kernel_proc.ptable_path()
        jdir = kernel_proc.journal_dir()
        for command in (f"cat {tbl}", f"ls {jdir}", f"wc -l {tbl}",
                        f"grep -c pid {tbl}", f"stat {tbl}",
                        f"find {jdir} -name '*.jsonl'",
                        "mkfifo /tmp/qa9-not-kernel", "ln -sf /tmp/a /tmp/b",
                        'python3 -c "print(1)"', "echo kernel", "git status"):
            self.assertEqual(self.decide(command), "allow", command)


class QaCycle4(IsolationCase):
    """The same class of bug as the corrupt table, reached seven cheaper ways.

    Every assertion here lands on the GATE, which is the last hop and the one
    that decides. The library-level twins in test_kernel_proc.py pin the
    reader's answer; these pin what a second writer is actually allowed to do
    with it, because "the reader reports a fault" and "the intruder is denied"
    were two different measurements in every earlier cycle of this PR.
    """

    def setUp(self):
        super().setUp()
        rc, out = self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))
        self.assertFalse(self.denied(out), "the owner claims its own lane")
        self.assertIn(kernel_proc.norm_path(self.a_py),
                      kernel_proc.read_ptable()["processes"]["agent-a"]["lanes"])

    # ── helpers ────────────────────────────────────────────────────────────
    def reason(self, out: str) -> str:
        obj = json.loads(out or "{}")
        return (obj.get("hookSpecificOutput") or {}).get("permissionDecisionReason") or ""

    def on_disk(self) -> dict:
        """The file, parsed WITHOUT the seam under test."""
        with open(kernel_proc.ptable_path(), encoding="utf-8") as fh:
            return json.load(fh)

    def write_table(self, data) -> None:
        with open(kernel_proc.ptable_path(), "w", encoding="utf-8") as fh:
            json.dump(data, fh)

    def both_deny(self, needle, why="", setup=None):
        """The intruder's write and the intruder's `rm`, on both gates.

        `setup` is re-applied before the SECOND gate, and cycle 5 is why it had
        to exist. The first gate's own `journal_deny` calls `append`, which
        creates the journal directory, so a test that removed that directory
        measured the second gate against a machine where it was back: the fault
        changed from journal-evidence to zero-rows and the assertion passed
        anyway, because the needle was sitting in the generic `recovery()` text
        appended to every deny. Per-kind recovery took that boilerplate away and
        exposed it. Each gate is measured in the state the test built.
        """
        if setup:
            setup()
        rc, out = self.run_gate(WRITE_GATE, self.write_payload("agent-b", self.a_py))
        self.assertEqual(rc, 0)
        self.assertTrue(self.denied(out), f"the write gate allowed it {why}")
        self.assertIn(needle, self.reason(out))
        if setup:
            setup()
        rc, out = self.run_gate(BASH_GATE,
                                self.bash_payload("agent-b", f"rm -f {self.a_py}"))
        self.assertEqual(rc, 0)
        self.assertTrue(self.denied(out), f"the bash gate allowed it {why}")
        self.assertIn(needle, self.reason(out))

    def both_allow(self, why=""):
        rc, out = self.run_gate(WRITE_GATE, self.write_payload("agent-b", self.a_py))
        self.assertFalse(self.denied(out), f"the write gate denied it {why}")
        rc, out = self.run_gate(BASH_GATE,
                                self.bash_payload("agent-b", f"rm -f {self.a_py}"))
        self.assertFalse(self.denied(out), f"the bash gate denied it {why}")

    def register_hook(self, pid="newsess"):
        """The REAL SessionStart reflex, in its own process."""
        env = dict(os.environ)
        env["HOME"] = self.home
        env["USERPROFILE"] = self.home
        cp = subprocess.run([sys.executable, str(SCRIPTS / "r__session__proc-register.py")],
                            input=json.dumps({"session_id": pid, "source": "startup",
                                              "cwd": self.home}),
                            capture_output=True, text=True, env=env, cwd=self.home,
                            timeout=60)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        return cp

    # ── F1a: a table that exists and carries no row ────────────────────────
    def test_f1a_a_table_written_empty_is_a_loss_not_a_fresh_install(self):
        """The cheapest of the seven, and cheaper than the `rm` this PR closed:
        one write of `{"version":1,"processes":{}}`. The guard keyed on
        `FileNotFoundError`, so this walked straight past it with `dropped=[]`
        and `fault=''`, and both gates allowed the intruder onto agent-a's lane.
        The decision is on the RESULT now, zero rows, never on which syscall
        produced it."""
        self.write_table({"version": 1, "processes": {}})
        self.both_deny("carries no row", "over an empty table")

    def test_f1a_an_empty_table_on_a_quiet_machine_still_allows(self):
        """The half that keeps this from being "deny always", and the one edit
        that separates it from the test above: the same empty table, with
        nothing running beside it. A rule that cannot tell a fresh install from
        a loss is a broken laptop, not a stricter gate."""
        self.write_table({"version": 1, "processes": {}})
        for name in os.listdir(kernel_proc.journal_dir()):
            if name.endswith(".jsonl"):
                self.age_journal(name[:-len(".jsonl")], kernel_proc.TTL + 300)
        self.both_allow("on a machine with nothing running")

    # ── F1b/F1c: rows that could not be read ───────────────────────────────
    def test_f1b_a_table_whose_every_row_is_junk_is_the_same_loss(self):
        """Zero rows reached by DROPPING rather than by writing. `dropped` named
        the pid and `fault` was empty, and both gates read the empty result as
        an empty machine."""
        self.write_table({"version": 1, "processes": {"agent-a": "x"}})
        self.both_deny("every row in the ptable was unreadable")

    def test_f1c_corrupting_only_the_holders_row_is_denied(self):
        """The most surgical version of the whole attack: ONE row edited, every
        other row intact, so the table is not empty and the zero-rows rule above
        never fires. Measured before the fix: `dropped=['agent-a']`, `fault=''`,
        both gates ALLOW. The lanes of a row that could not be read are exactly
        as unknowable as the lanes of a table that could not be read."""
        data = self.on_disk()
        data["processes"]["agent-a"] = "x"
        self.write_table(data)
        self.assertTrue(data["processes"].get("agent-b"),
                        "other rows survive, so this is not the zero-rows case")
        self.both_deny("could not be read", "with one row corrupted")

    def test_f1c_a_session_start_does_not_free_the_lane_it_lost(self):
        """The half that made one row edit enough. `register` republishes what
        it read, so the repair DELETED the holder's row: measured `lane_owner`
        returning `agent-a` before the registration and `None` after it, with
        nothing on any surface. The drop is carried forward now, so the gate
        keeps denying and the doctor keeps failing until a human looks."""
        data = self.on_disk()
        data["processes"]["agent-a"] = "x"
        self.write_table(data)
        self.register_hook()

        disk = self.on_disk()
        self.assertNotIn("agent-a", disk["processes"], "the repair really removed it")
        self.assertIn("newsess", disk["processes"], "and the hook still wrote its row")
        self.assertIn(kernel_proc.FAULT_KEY, disk,
                      "so the loss has to travel with the table")
        self.both_deny("process table is unreadable", "after a routine SessionStart")
        self.assertTrue(kernel_proc.quarantines(),
                        "and the row as it was is preserved beside the file")

    # ── F2: a parser that fails in a way nobody caught ─────────────────────
    def nested(self, depth=9998):
        """20 KB of `[`: valid JSON, far under the byte ceiling, and `json.load`
        raises RecursionError, which is a RuntimeError."""
        with open(kernel_proc.ptable_path(), "w", encoding="utf-8") as fh:
            fh.write("[" * depth + "]" * depth)
        self.assertLess(os.path.getsize(kernel_proc.ptable_path()),
                        kernel_proc.MAX_PTABLE_BYTES,
                        "the ceiling is not what stops this one")

    def test_f2_a_parser_failure_is_a_deny_and_not_a_silent_exit_zero(self):
        """RecursionError is neither ValueError nor OSError, so it escaped every
        fault leg in the reader and left through the gates' outer
        `except Exception: sys.exit(0)`. Measured rc=0, empty stdout, empty
        stderr: no deny, no journal line, no quarantine, no doctor FAIL, which
        is strictly quieter than the deletion this PR had just closed."""
        self.nested()
        self.both_deny("could not be parsed")
        rc, out = self.run_gate(WRITE_GATE, self.write_payload("agent-b", self.a_py))
        self.assertIn("RecursionError", self.reason(out),
                      "and it says which failure it was")

    def test_f2_the_refusal_is_journaled_like_every_other_one(self):
        """The finding was not only "allowed", it was "allowed leaving no
        trace". A deny that writes no journal line is a deny nobody can audit,
        so the line is asserted separately from the verdict."""
        self.nested()
        self.run_gate(WRITE_GATE, self.write_payload("agent-b", self.a_py))
        denies = [l for l in kernel_proc.read_journal("agent-b")
                  if isinstance(l, dict) and l.get("kind") == "deny"]
        self.assertTrue(denies, "the refusal left no record at all")
        self.assertIn(denies[-1].get("why"), ("ptable-unreadable", "ptable-read-raised"))

    def test_f2_the_gates_stay_fail_open_for_everything_that_is_not_this(self):
        """The scope of the change, asserted rather than promised. Denying on
        ANY exception would wedge the harness on a bug in path matching or the
        arms config, where allowing the call is the right failure, so only the
        ptable read is wrapped. A payload that is not even a dict still exits 0
        with no output."""
        for gate in (WRITE_GATE, BASH_GATE):
            rc, out = self.run_gate(gate, ["not", "a", "dict"])
            self.assertEqual(rc, 0)
            self.assertEqual(out.strip(), "")

    # ── F3: the deletion guard's own evidence ──────────────────────────────
    def test_f3_deleting_the_journal_directory_with_the_table_is_denied(self):
        """`live_journal_pids` returned `[]` on any OSError, so the evidence the
        deletion guard reads was removable by the same move it guards: measured
        ALLOW on both gates for `rm ptable.json && rm -rf journal/`. The kernel
        directory still shows it has run hooks, which is what tells this apart
        from a machine that never did."""
        def wipe():
            if os.path.exists(kernel_proc.ptable_path()):
                os.unlink(kernel_proc.ptable_path())
            shutil.rmtree(kernel_proc.journal_dir(), ignore_errors=True)
        self.both_deny("journal directory", "with the journals gone too", wipe)

    def test_f3_an_unreadable_journal_directory_is_denied(self):
        """The same move without the deletion. This one needs no history check:
        a directory that exists and cannot be walked is a state the kernel
        cannot produce."""
        def lock_out():
            if os.path.exists(kernel_proc.ptable_path()):
                os.unlink(kernel_proc.ptable_path())
            os.makedirs(kernel_proc.journal_dir(), exist_ok=True)
            os.chmod(kernel_proc.journal_dir(), 0o000)
        try:
            self.both_deny("cannot be read", "with the journals unreadable",
                           lock_out)
        finally:
            os.chmod(kernel_proc.journal_dir(), 0o755)

    def test_f3_a_file_where_the_journal_directory_belongs_is_denied(self):
        def replace_with_file():
            if os.path.exists(kernel_proc.ptable_path()):
                os.unlink(kernel_proc.ptable_path())
            if os.path.isdir(kernel_proc.journal_dir()):
                shutil.rmtree(kernel_proc.journal_dir())
            with open(kernel_proc.journal_dir(), "w", encoding="utf-8") as fh:
                fh.write("not a directory\n")
        self.both_deny("cannot be read", "with a file where the journals were",
                       replace_with_file)

    def test_f3_the_residual_is_a_home_that_shows_no_history_at_all(self):
        """Stated, measured and allowed, the way `recovery()` states the
        interpreter path. Removing the table, the journals AND everything else
        the kernel left behind produces a HOME that is byte for byte a wiped
        cache, and no reader can tell those apart from inside. It is a strictly
        larger move than the one closed above, and the honest answer is to allow
        it and say so, not to deny every fresh install."""
        os.unlink(kernel_proc.ptable_path())
        shutil.rmtree(kernel_proc.journal_dir())
        for name in os.listdir(kernel_proc.kernel_dir()):
            os.unlink(os.path.join(kernel_proc.kernel_dir(), name))
        self.assertFalse(kernel_proc._kernel_has_history())
        self.both_allow("on a HOME with no kernel state left")

    # ── F4: a holder's journal is not its life ─────────────────────────────
    def test_f4_deleting_the_holders_journal_does_not_free_its_lane(self):
        """`_mtime` returns None for a deleted journal, `_own_fresh` reads that
        as False and `is_live` reads dead, so `rm journal/agent-a.jsonl` freed
        the lane with the table fully intact and both gates allowed the
        intruder. A missing liveness RECORD selecting the permissive branch is
        the exact inference this PR rejects for the process table."""
        os.unlink(kernel_proc.journal_path("agent-a"))
        self.both_deny("agent-a", "with the holder's journal deleted")

    def test_f4_a_session_start_does_not_free_it_either(self):
        """The second move, which is what made the first one worth making.
        `prune` treated a row with no journal as dead once its `registered_ts`
        aged past the TTL, so one SessionStart 15 minutes later removed the row
        and the lane went with it. That row is kept and the table is faulted
        instead, bounded by PRUNE_AFTER so it still expires on its own."""
        os.unlink(kernel_proc.journal_path("agent-a"))
        data = self.on_disk()
        data["processes"]["agent-a"]["registered_ts"] = time.time() - (kernel_proc.TTL + 60)
        self.write_table(data)
        self.register_hook()

        disk = self.on_disk()
        self.assertIn("agent-a", disk["processes"], "the row is not pruned away")
        self.assertIn(kernel_proc.FAULT_KEY, disk, "and the loss is on the table")
        self.both_deny("hold lanes with no journal", "after a SessionStart")

    def test_f4_a_row_that_holds_nothing_still_ages_out_normally(self):
        """The bound, and the one edit that separates it from the test above: a
        row whose journal is gone and which holds NO lane is an ordinary dead
        row, so it prunes and nothing faults. Without this the rule would be
        "any missing journal denies the machine", which is the broken-laptop
        version of the same idea."""
        kernel_proc.register("idle", {"ppid": "sess-parent", "type": "builder"})
        os.unlink(kernel_proc.journal_path("idle"))
        data = self.on_disk()
        data["processes"]["idle"]["registered_ts"] = time.time() - (kernel_proc.TTL + 60)
        self.write_table(data)
        self.register_hook()

        disk = self.on_disk()
        self.assertNotIn("idle", disk["processes"], "it prunes like any dead row")
        self.assertNotIn(kernel_proc.FAULT_KEY, disk, "and nothing is faulted")

    # ── F5: a read that never returns ──────────────────────────────────────
    def test_f5_a_fifo_at_the_ptable_path_denies_instead_of_hanging(self):
        """`os.path.getsize` SUCCEEDS on a fifo and `open` then blocks forever
        with no writer: both gates were still running at 60 s. A PreToolUse hook
        that never returns is neither fail-closed nor fail-open, it is a hung
        session, so the stat comes first and a path that is not a regular file
        is never opened.

        The TIMEOUT is the assertion here: `run_gate` waits 30 s and raises
        `subprocess.TimeoutExpired` on a hang, which is the failure this test
        exists to catch. The deny text is the second half.
        """
        os.unlink(kernel_proc.ptable_path())
        os.mkfifo(kernel_proc.ptable_path())
        self.both_deny("not a regular file", "with a fifo at the ptable path")

    # ── F6: lanes that are not lanes ───────────────────────────────────────
    def test_f6_a_lanes_field_that_is_not_a_list_of_paths_drops_the_row(self):
        """Three shapes on an OTHERWISE PERFECT row, all measured ALLOW:
        `lanes` as the path string itself, as null, and as a list of numbers.
        `lanes_of` coerced every one to `[]` and `norm_path` swallowed the
        elements, so the row kept its pid, its type and its worktree, appeared
        healthy in every listing, and silently forfeited the path it held. A row
        whose lanes cannot be read is a row whose ownership cannot be read."""
        for bad in (kernel_proc.norm_path(self.a_py), None, [12345], {}, [""]):
            with self.subTest(lanes=bad):
                data = self.on_disk()
                data["processes"]["agent-a"]["lanes"] = bad
                self.write_table(data)
                self.assertEqual(
                    sorted(kernel_proc.read_ptable_detail()[1]), ["agent-a"],
                    "the row is dropped, which is what puts it on the surfaces")
                self.both_deny("could not be read", f"with lanes={bad!r}")

    def test_f6_a_row_with_no_lanes_key_at_all_is_still_healthy(self):
        """The one edit that keeps the rule from being "any row without a lane
        list is corrupt": an ABSENT `lanes` is the shape of every row between
        `register` and its first write, and it must stay readable. `null` is not
        the same thing and is covered above."""
        data = self.on_disk()
        data["processes"]["agent-b"].pop("lanes", None)
        self.write_table(data)
        self.assertEqual(kernel_proc.read_ptable_detail()[1], [])
        rc, out = self.run_gate(WRITE_GATE,
                                self.write_payload("agent-b", os.path.join(self.tree, "b.py")))
        self.assertFalse(self.denied(out))


class QaCycle10(IsolationCase):
    """Four holes adversarial QA found in the SHARED command parser rather than
    in any one gate, which is why they are pinned here: `scan()` and its verb
    tables are imported by every gate that peels a command, so all of them were
    open at once.

    Every one of the four is the SAME defect wearing four costumes. The kernel
    floor stopped being a verb list in cycle 9 (`_KSTATE_READONLY` names the
    programs that provably cannot write, and everything else is denied at the
    kernel directory), and these four are the places where the LANE test is
    still a verb list and lost to the next verb, the next wrapper, the next
    spelling of a path, and the next way of naming an inode.

    Each test below fails with its own fix reverted. That was measured, not
    asserted: the failing test is named in the PR report next to the line that
    was put back.
    """

    def hold(self):
        self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))

    def decide(self, command, pid="agent-b"):
        rc, out = self.run_gate(BASH_GATE, self.bash_payload(pid, command))
        return "deny" if self.denied(out) else "allow"

    # ── F1 `install` is `cp` ────────────────────────────────────────────────
    def test_f1_install_writes_its_destination_exactly_as_cp_does(self):
        """`install /dev/null <lane>` truncates and rewrites the file byte for
        byte the way `cp /dev/null <lane>` does. Measured at HEAD: the `cp` was
        denied and the `install` was allowed, and the only difference between
        them was which words a table happened to contain."""
        self.hold()
        for command in (f"install /dev/null {self.a_py}",
                        f"install -m 644 /dev/null {self.a_py}",
                        f"install -m 755 -o me -g me /dev/null {self.a_py}",
                        f"install -t {self.tree}/pkg /dev/null",
                        f"install -d {self.tree}/pkg"):
            self.assertEqual(self.decide(command), "deny", command)
        self.assertEqual(self.decide(f"cp /dev/null {self.a_py}"), "deny",
                         "the control that was already right")

    def test_f1_install_into_a_path_nobody_holds_still_passes(self):
        """`install` has real work to do. A build that installs its own output
        must not become collateral: one edit from each violation above, the
        same verb aimed somewhere nobody owns."""
        self.hold()
        os.makedirs(os.path.join(self.tree, "dist"), exist_ok=True)
        for command in (f"install /dev/null {self.tree}/dist/tool",
                        f"install -m 755 /dev/null {self.tree}/dist/tool",
                        f"install -d {self.tree}/dist/sub",
                        f"install -t {self.tree}/dist /dev/null",
                        f"install /dev/null {self.tree}/pkg/z.py",
                        "install --help"):
            self.assertEqual(self.decide(command), "allow", command)

    # ── F2 a multi-call binary is a wrapper ─────────────────────────────────
    def test_f2_a_multicall_binary_is_a_wrapper_not_a_program(self):
        """`busybox rm -f <lane>` runs busybox's own rm and the file is exactly
        as gone. It is the shape `env`, `nohup` and `command` were already
        peeled for; busybox was simply never named, so the parser read
        `busybox` as the program and stopped."""
        self.hold()
        for command in (f"busybox rm -f {self.a_py}",
                        f"busybox mv {self.a_py} /tmp/qa10-x",
                        f"toybox rm -f {self.a_py}",
                        f"env -u HOME busybox rm -f {self.a_py}",
                        f"busybox sh -c \"rm -rf {self.tree}/pkg\""):
            self.assertEqual(self.decide(command), "deny", command)

    def test_f2_busybox_is_peeled_not_blanket_denied(self):
        """The peel has to leave a READ readable. One edit from the violation:
        the same wrapper, an applet that writes nothing, and the same applet
        aimed at a path nobody holds."""
        self.hold()
        for command in (f"busybox ls {self.tree}/pkg",
                        f"busybox cat {self.a_py}",
                        f"busybox rm -f {self.tree}/pkg/z.py",
                        "busybox"):
            self.assertEqual(self.decide(command), "allow", command)

    # ── F3 HOME is a value this process holds, not a guess ──────────────────
    def test_f3_home_is_expanded_because_this_process_knows_its_own(self):
        """A ONE-TOKEN BYPASS OF EVERY PATH RULE IN THE GATE, kernel floor
        included: `rm "$HOME/.claude/settings.json"` passed while the same
        command spelled absolutely was denied. Expanding `$HOME` is not the
        variable expansion the residual list refuses; that one needs a shell
        this gate never runs, and this one reads a value the gate already
        holds."""
        self.hold()
        for command in ('rm -rf "$HOME/work/tree/pkg"',
                        "rm -rf ${HOME}/work/tree/pkg",
                        "rm -rf $HOME/work/tree/pkg",
                        'rm -f "$HOME/.claude/.cache/kernel/ptable.json"'):
            self.assertEqual(self.decide(command), "deny", command)

    def test_f3_only_home_is_expanded_and_the_rest_stays_a_residual(self):
        """Where the expansion stops, and why it stops there. `$HOMEBREW` is
        not `$HOME` with a suffix, and `$DIR` is a value that lives in a shell
        nobody ran: inventing one would deny work nobody owns."""
        self.hold()
        os.makedirs(os.path.join(self.home, "work", "solo"), exist_ok=True)
        for command in ('rm -rf "$HOME/work/solo"',
                        'rm -rf "$HOMEBREW/x"',
                        'rm -rf "$HOME_DIR/x"',
                        f"DIR={self.tree}/pkg && rm -rf $DIR"):
            self.assertEqual(self.decide(command), "allow", command)

    # ── F4 a hardlink is a second name for one inode ────────────────────────
    def test_f4_a_hardlink_is_a_second_name_for_the_same_inode(self):
        """`realpath` does not resolve a hardlink, so once the alias exists no
        gate can connect the new name back to the protected one and the write
        through it is invisible BY CONSTRUCTION. The act of aliasing is the
        last moment anything is decidable, so that is where the deny lands."""
        self.hold()
        os.makedirs(os.path.join(self.tree, "dist"), exist_ok=True)
        alias = os.path.join(self.tree, "alias.py")
        for command in (f"ln {self.a_py} {alias}",
                        f"ln -f {self.a_py} {alias}",
                        f"cp -l {self.a_py} {alias}",
                        f"cp --link {self.a_py} {alias}",
                        f"ln -t {self.tree}/dist {self.a_py}",
                        f"ln {self.a_py}"):
            self.assertEqual(self.decide(command), "deny", command)

    def test_f4_the_source_rule_is_not_the_destination_rule_wearing_a_hat(self):
        """THE MASKED-BY-A-NEIGHBOUR CHECK, run rather than reasoned. `ln` also
        writes its DESTINATION, and a violation whose destination is a lane
        would deny for that reason and prove nothing about the source rule. So
        the destination here is a path nobody holds, and the only rule that can
        produce this deny is the hardlink one: flip the SOURCE to an unowned
        file and the same command allows."""
        self.hold()
        alias = os.path.join(self.tree, "alias.py")
        self.assertEqual(self.decide(f"ln {self.a_py} {alias}"), "deny")
        self.assertEqual(self.decide(f"ln {self.tree}/b.py {alias}"), "allow")

    def test_f4_a_symlink_of_a_lane_is_not_an_alias_of_its_inode(self):
        """One edit from the violation, and the edit is the whole rule: `-s`
        stores a PATH, not an inode, so a write through the link resolves back
        to the lane where the ordinary test still runs. Denying it would be
        denying a legitimate `ln -s` in a worktree, which is the shape this
        repo uses every day."""
        self.hold()
        for command in (f"ln -s {self.a_py} {self.tree}/alias.py",
                        f"ln -sf {self.a_py} {self.tree}/alias.py",
                        "ln -s pkg/a.py alias.py",
                        f"ln {self.tree}/b.py {self.tree}/c.py",
                        f"cp {self.a_py} {self.tree}/c.py"):
            self.assertEqual(self.decide(command), "allow", command)

    def test_the_four_fixes_compose(self):
        """THE ONLY TEST HERE THAT IS ALLOWED TO FAIL ON MORE THAN ONE REVERT,
        and it is here so the four above do not have to be. Each of those pins
        exactly one rule, using no shape that depends on another, so a
        regression says WHICH rule moved. This one pins that they still stack:
        the wrapper peel has to hand the real verb to the mutator table, and
        the expansion has to happen before either looks at a path. Measured
        with all four reverted one at a time: the four single-rule tests fail
        one each, and this one fails on every revert, by design."""
        self.hold()
        for command in (f"busybox install /dev/null {self.a_py}",
                        'install /dev/null "$HOME/work/tree/pkg/a.py"',
                        'ln "$HOME/work/tree/pkg/a.py" alias.py',
                        'busybox rm -rf "$HOME/work/tree/pkg"'):
            self.assertEqual(self.decide(command), "deny", command)

    def test_f4_the_destination_of_a_link_is_a_write(self):
        """`ln -sf /dev/null <lane>` was a NAMED RESIDUAL until `ln` joined the
        mutator table. It is not one now, so it is pinned here and removed from
        `test_named_residuals_are_honestly_uncovered` rather than left in a
        list that has stopped being true."""
        self.hold()
        for command in (f"ln -sf /dev/null {self.a_py}",
                        f"ln -f /dev/null {self.a_py}"):
            self.assertEqual(self.decide(command), "deny", command)


class QaCycle11(IsolationCase):
    """The channel the floor never looked at, measured on the machine's own
    traffic rather than on the vocabulary the gate names.

    Cycle 9 made the kernel floor a NAMED-PATH test and cycle 10 reported it
    closed. It was closed for `-c`. Of 16350 distinct real Bash commands in the
    harness transcripts, 3186 carry a HEREDOC and 3601 carry a `-c`, and the
    heredoc form of the identical write passed: with `python3 - <<EOF` the
    program arrives on stdin, there is no flag whose argument is the program,
    and the raw-text test was handed an opening line that names nothing.

    The same reading closes an over-fire that was already live in the other
    direction. A heredoc body is DATA unless the command it feeds runs stdin as
    its program, and until now every body was split into segments and read as
    commands, so a note whose prose said `rm -rf pkg/` was a deletion.

    Each test below fails with its own fix reverted, measured one at a time and
    named in the PR report.
    """

    def hold(self):
        self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))

    def decide(self, command, pid="agent-b"):
        rc, out = self.run_gate(BASH_GATE, self.bash_payload(pid, command))
        return "deny" if self.denied(out) else "allow"

    def kfile(self):
        return os.path.join(kernel_proc.kernel_dir(), "journal", "agent-a.jsonl")

    # ── F1 the heredoc is a command channel with no flag ────────────────────
    def test_f1_a_heredoc_body_is_a_program_when_its_receiver_runs_stdin(self):
        """The dominant idiom, and the floor was open through all of it. Every
        command here writes the same journal line as the `-c` control, which is
        pinned last so a green here can never be a green that stopped testing
        the kernel floor at all."""
        k = self.kfile()
        for command in (
                f"python3 - <<'EOF'\nopen('{k}','a').write('x')\nEOF",
                f"python3 <<'EOF'\nopen('{k}','a').write('x')\nEOF",
                f"python3 <<EOF\nopen('{k}','a').write('x')\nEOF",
                f"cat <<'EOF' | python3 -\nopen('{k}','a').write('x')\nEOF",
                f"bash -s <<'EOF'\nrm -f {k}\nEOF",
                f"bash <<-EOF\n\trm -f {k}\nEOF"):
            self.assertEqual(self.decide(command), "deny", command)
        self.assertEqual(
            self.decide(f"""python3 -c "open('{k}','a').write('x')" """), "deny",
            "the control that was already right")

    def test_f1_a_heredoc_body_nobody_runs_stays_data(self):
        """ONE EDIT FROM THE VIOLATION, and the edit is the whole rule: the same
        body, handed to a program that does not execute stdin. A gate that
        denies the dominant idiom gets turned off, which is worse than the hole,
        so the receiver decides and not the presence of a path."""
        self.hold()
        k = self.kfile()
        notes = os.path.join(self.tree, "notes.md")
        for command in (
                f"cat > {notes} <<'EOF'\nthe journals live in {k}\nEOF",
                f"cat <<'EOF'\nthe journals live in {k}\nEOF",
                f"python3 tool.py <<'EOF'\n{k}\nEOF",
                f"grep -c x <<'EOF'\n{k}\nEOF"):
            self.assertEqual(self.decide(command), "allow", command)

    def test_f1_a_data_heredoc_is_no_longer_read_as_a_deletion(self):
        """The over-fire this reading removes, measured at HEAD before the fix:
        the body was split into segments, so a note ABOUT a command was read as
        the command. Held lane, prose that names it, and nothing is executed."""
        self.hold()
        notes = os.path.join(self.tree, "notes.md")
        for command in (
                f"cat > {notes} <<'EOF'\nto reset it: rm -rf {self.tree}/pkg\nEOF",
                f"cat > {notes} <<'EOF'\nrun `git checkout -- {self.a_py}` to undo\nEOF",
                f"tee {notes} <<'EOF'\nrm -f {self.a_py}\nEOF"):
            self.assertEqual(self.decide(command), "allow", command)

    def test_f1_a_shell_that_does_run_the_body_is_still_scanned(self):
        """The other half of the same rule, so the fix above cannot be a
        blanket amnesty for heredocs: when the receiver IS a shell, the body is
        a command list and the lane test runs on it exactly as before."""
        self.hold()
        for command in (f"bash <<'EOF'\nrm -rf {self.tree}/pkg\nEOF",
                        f"sh -s <<'EOF'\ngit checkout -- {self.a_py}\nEOF",
                        f"cd {self.tree}/pkg && bash <<'EOF'\nrm -f a.py\nEOF"):
            self.assertEqual(self.decide(command), "deny", command)

    # ── F2 a versioned interpreter is the same interpreter ──────────────────
    def test_f2_a_versioned_interpreter_is_the_same_interpreter(self):
        """`python3.12` is the only versioned binary on this host and it was
        the one name the host match could not make: stripping trailing digits
        from `python3.12` leaves `python3.`, dot included, which matches
        nothing. Adversarial QA found the identical defect in the merge gate,
        so it is one bug in shared logic rather than two."""
        k = self.kfile()
        for command in (
                f"""python3.12 -c "open('{k}','a').write('x')" """,
                f"""python3.13 -c "open('{k}','a').write('x')" """,
                f"""perl5.36 -e "open(F,'>>','{k}')" """):
            self.assertEqual(self.decide(command), "deny", command)

    def test_f2_a_version_strip_does_not_widen_anything_else(self):
        """Where the strip stops. It widens the INTERPRETER tables and nothing
        else: `base64` normalizes to `base`, so a read-only program would lose
        its place in `_KSTATE_READONLY` if the same strip ran there, and a
        versioned interpreter aimed at a path nobody owns still has work to
        do."""
        self.hold()
        k = self.kfile()
        for command in (f"base64 {k}",
                        f"""python3.12 -c "print('hello')" """,
                        f"python3.12 {self.tree}/tool.py",
                        f"python3.12 - <<'EOF'\nprint('hello')\nEOF"):
            self.assertEqual(self.decide(command), "allow", command)

    # ── F3 the channels that are not a heredoc ──────────────────────────────
    def test_f3_a_here_string_and_a_process_substitution_are_channels_too(self):
        """Lifted from the merge gate's `_stdin_channel_texts`, which found the
        same hole from the other side. A here-string reaches a shell the way a
        heredoc does; a process substitution runs its body whatever the outer
        program is, which is why it needs no receiver test at all."""
        self.hold()
        k = self.kfile()
        for command in (f'bash <<< "rm -f {k}"',
                        f'bash <<<"rm -rf {self.tree}/pkg"',
                        f'cat <(rm -rf {self.tree}/pkg)',
                        f'diff <(rm -f {self.a_py}) /dev/null'):
            self.assertEqual(self.decide(command), "deny", command)

    def test_f3_a_here_string_of_data_is_data(self):
        """One edit from each violation above: the same syntax carrying text
        nobody executes, and a process substitution that only reads."""
        self.hold()
        k = self.kfile()
        for command in ('grep -c x <<< "some line"',
                        f'grep -c x <<< "{k}"',
                        f'diff <(cat {k}) /dev/null',
                        f'diff <(git show HEAD:pkg/a.py) {self.a_py}'):
            self.assertEqual(self.decide(command), "allow", command)

    def test_the_splitter_claims_what_a_shell_would_claim(self):
        """The three claims `split_heredocs` makes about where a body starts and
        ends, each of which the shell also makes. A `<<` with no terminator line
        is not a heredoc at all, so it can never swallow the commands after it;
        a body ends at the FIRST line equal to its terminator, so what follows
        is an ordinary command again; and a line that opens two heredocs pairs
        them with its terminators in order, so the second body goes to the
        command that runs it and not to the one that only prints it."""
        k = self.kfile()
        for command in (
                f"cat <<'A' | python3 - <<'B'\njust data\nA\nopen('{k}','a')\nB",
                f"python3 - <<'PY'\nx = 1 << 3\nopen('{k}','a').write('x')\nPY"):
            self.assertEqual(self.decide(command), "deny", command)
        self.hold()
        for command in ("echo 'a << b' && rm -f /tmp/qa11-nothing",
                        f"python3 - <<'PY'\nprint('done')\nPY\nstat {k}/ptable.json"):
            self.assertEqual(self.decide(command), "allow", command)

    def test_the_cycle_11_fixes_compose(self):
        """THE ONLY TEST HERE ALLOWED TO FAIL ON MORE THAN ONE REVERT, and it
        is here so the others do not have to be. Measured with each fix
        reverted alone: the version strip has to run before the channel test
        can recognise the receiver, and the channel has to exist before the
        version matters to it."""
        k = self.kfile()
        for command in (
                f"python3.12 - <<'EOF'\nopen('{k}','a').write('x')\nEOF",
                f"cat <<'EOF' | python3.12 -\nopen('{k}','a').write('x')\nEOF"):
            self.assertEqual(self.decide(command), "deny", command)

    def test_the_cycle_11_residual_was_a_closed_list_and_is_now_covered(self):
        """`python3 -W ignore <<EOF` was cycle 11's ONE named residual, and QA
        cycle 12 C7 measured four more of the same shape (`bash -o pipefail`,
        `bash -s foo`, `bash -s -- foo`, `python3 -X utf8`). One example was
        pinned; the CLASS was not, which is the failure this PR chain keeps
        repeating. The per-host option tables cover it now and the surviving
        residual is pinned in `QaCycle12.test_named_residuals_of_cycle_12`.

        The cwd half of the cycle-11 list did NOT survive being measured, which
        is why it was never in it: a first draft resolved every body against the
        cwd the COMMAND started in, and `cd pkg && bash <<EOF … rm -f a.py …
        EOF` went from denied at HEAD to allowed. A body is claimed by the
        sub-command that opens it instead, so it keeps that line's cwd, and the
        case is pinned as DENIED in
        `test_f1_a_shell_that_does_run_the_body_is_still_scanned`."""
        self.hold()
        k = self.kfile()
        self.assertEqual(
            self.decide(f"python3 -W ignore <<'EOF'\nopen('{k}','a').write('x')\nEOF"),
            "deny")



class QaCycle12(IsolationCase):
    """Cycle 11 closed ONE spelling of the heredoc and the matrix read the rest
    of the class as closed with it. Nine findings, measured with a passing
    positive control (`python3 - <<'EOF'` still denies), and four of them live
    INSIDE the channel cycle 11 had just claimed.

    The finding that is bigger than the heredoc is C1: `$(...)` and backticks
    were never parsed as commands anywhere in this file. They were caught only
    incidentally, when a literal kernel path survived tokenization as a bare
    token AND the outer verb was not read-only, which is why
    `x=$(rm -f <kdir>/ptable.json)` denied while `echo $(python3 -c "…")` and
    any interpreter that COMPUTES the path sailed through.

    Each test below fails with its own fix reverted, measured one at a time and
    named in the PR report.
    """

    def hold(self):
        self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))

    def decide(self, command, pid="agent-b"):
        rc, out = self.run_gate(BASH_GATE, self.bash_payload(pid, command))
        return "deny" if self.denied(out) else "allow"

    def kfile(self):
        return os.path.join(kernel_proc.kernel_dir(), "journal", "agent-a.jsonl")

    # ── C1 a command substitution is a command ──────────────────────────────
    def test_c1_a_substitution_runs_a_command_wherever_it_sits(self):
        """Every WORD POSITION a substitution can occupy, because a
        substitution is a word construct and the position is the whole class:
        an argument to a read-only verb, an assignment RHS, a redirect TARGET,
        inside double quotes, nested, and inside a `-c` body one level down.
        The redirect case is the one that needs the marker rather than the
        recursion: the destination is computed by a command this gate does not
        run, so the body's TEXT answers instead of the token."""
        k = self.kfile()
        kdir = kernel_proc.kernel_dir()
        for command in (
                f'echo $(python3 -c "open(\'{k}\',\'a\').write(\'x\')")',
                f"true $(rm -f {k})",
                f"echo `rm -f {k}`",
                f"echo $(echo $(rm -f {k}))",
                f'echo "$(rm -f {k})"',
                f"echo `cd /tmp; rm -f {k}`",
                f"echo hi > $(echo {kdir})/ptable.json",
                f'bash -c "rm -f $(echo {kdir})/ptable.json"'):
            self.assertEqual(self.decide(command), "deny", command)

    def test_c1_a_substitution_that_only_reads_is_still_a_read(self):
        """One edit from each violation above. A substitution is scanned as the
        command it is, so a read stays a read and single-quoted text stays
        literal: bash expands nothing inside `'…'`, and neither does this."""
        self.hold()
        k = self.kfile()
        for command in (f"echo $(cat {k})",
                        f"echo 'x $(rm -f {k})'",
                        "echo $((1 << 3)) && echo done"):
            self.assertEqual(self.decide(command), "allow", command)

    def test_c1_a_verb_that_comes_from_an_expansion_stays_opaque(self):
        """The deliberate behaviour cycle 12 must NOT regress. `$(echo rm)` is
        a program name this gate cannot know, so the marker it leaves is not a
        read-only program either and the token scan still runs over the
        segment."""
        self.assertEqual(self.decide(f"$(echo rm) -f {self.kfile()}"), "deny")

    # ── C2 an unquoted terminator makes the body a command channel ───────────
    def test_c2_an_unquoted_terminator_expands_the_body(self):
        """`cat` is not a stdin-program host, so cycle 11 read this body as
        data. Bash reads it as a command channel anyway: with an UNQUOTED
        terminator it expands `$(...)` and backticks in the body before `cat`
        ever sees it."""
        k = self.kfile()
        for command in (f"cat <<EOF\n$(rm -f {k})\nEOF",
                        f"cat <<EOF\n`rm -f {k}`\nEOF"):
            self.assertEqual(self.decide(command), "deny", command)

    def test_c2_a_quoted_terminator_keeps_the_body_literal(self):
        """One edit from each violation above: the quotes. A quoted delimiter
        is bash's own way of saying the body is data, and it stays data."""
        self.hold()
        k = self.kfile()
        for command in (f"cat <<'EOF'\n$(rm -f {k})\nEOF",
                        f'cat <<"EOF"\n`rm -f {k}`\nEOF'):
            self.assertEqual(self.decide(command), "allow", command)

    # ── C3 the terminator is matched the way bash matches it ────────────────
    def test_c3_a_whitespace_decoy_does_not_close_the_body(self):
        """`.strip()` let a line of `"  EOF"` close the parse here while bash
        kept the body open, so everything after the decoy was read as data.
        Bash wants the line to EQUAL the delimiter; only `<<-` strips, and only
        leading TABS."""
        k = self.kfile()
        for command in (f"python3 - <<'EOF'\n  EOF\nopen('{k}','a')\nEOF",
                        f"python3 - <<-EOF\n\topen('{k}','a')\n\tEOF"):
            self.assertEqual(self.decide(command), "deny", command)

    def test_c3_a_real_terminator_still_ends_the_body(self):
        """One edit from the decoy: the same line without its leading spaces.
        The body ends there and what follows is an ordinary command again."""
        self.hold()
        k = self.kfile()
        self.assertEqual(
            self.decide(f"python3 - <<'EOF'\nprint(1)\nEOF\nstat {k}"), "allow")

    # ── C4 the delimiter charset was a closed list too ──────────────────────
    def test_c4_every_spelling_of_a_delimiter_is_a_delimiter(self):
        """THE CLASS, not one member. A heredoc delimiter is any WORD: bare,
        single-quoted, double-quoted, backslash-escaped or PARTIALLY quoted,
        with optional blanks after the operator. The old pattern was
        `['\"]? [A-Za-z_] [\\w.-]*`, so a delimiter that started with a digit, was
        escaped rather than quoted, or held a `!` was not a heredoc at all."""
        k = self.kfile()
        for command in (f"python3 - <<\\EOF\nopen('{k}','a')\nEOF",
                        f"python3 - <<'1EOF'\nopen('{k}','a')\n1EOF",
                        f"python3 - <<'E!'\nopen('{k}','a')\nE!",
                        f'python3 - <<"EOF"\nopen(\'{k}\',\'a\')\nEOF',
                        f"python3 - <<E'OF'\nopen('{k}','a')\nEOF",
                        f"python3 - << EOF\nopen('{k}','a')\nEOF"):
            self.assertEqual(self.decide(command), "deny", command)

    def test_c4_a_shift_operator_is_not_a_delimiter(self):
        """One edit away from the widening being too wide. `<<` with no
        terminator line is not a heredoc, which is what keeps the wider charset
        from swallowing the rest of a command."""
        self.hold()
        self.assertEqual(self.decide("echo 'a << b' && echo ok"), "allow")

    # ── C5 a grouping opener is not the receiver ────────────────────────────
    def test_c5_a_group_opener_is_not_the_program(self):
        """`shlex.split('( python3 - <<EOF')[0]` is `(`, so the host came back
        empty and the body was discarded on its way out of the drain."""
        k = self.kfile()
        for command in (f"( python3 - <<'EOF'\nopen('{k}','a')\nEOF\n)",
                        f"{{ python3 - <<'EOF'\nopen('{k}','a')\nEOF\n}}"):
            self.assertEqual(self.decide(command), "deny", command)

    # ── C6 the two closed lists ─────────────────────────────────────────────
    def test_c6_stdin_is_every_name_procfs_gives_it(self):
        """`/dev/fd/0` was in the list and `/proc/self/fd/0` was not, which is
        a list rather than a rule. The set is closed by PROCFS: `/dev/stdin`,
        `/dev/fd/N`, `/proc/self/fd/N`, `/proc/thread-self/fd/N` and
        `/proc/<pid>/fd/N` are the names the kernel provides, and nothing
        else names this process's stdin."""
        k = self.kfile()
        for operand in ("-", "/dev/stdin", "/dev/fd/0", "/proc/self/fd/0",
                        "/proc/thread-self/fd/0", "/proc/1234/fd/0"):
            command = f"python3 {operand} <<'EOF'\nopen('{k}','a')\nEOF"
            self.assertEqual(self.decide(command), "deny", command)

    def test_c6_a_project_runner_is_a_wrapper_by_shape(self):
        """`uv run python - <<EOF` and `poetry run python - <<EOF` both passed
        and both binaries are installed on this box. The fix is the SHAPE, not
        another tool list: `<tool> run|exec|x … <program>` is a wrapper when the
        first non-flag token after the verb is a program this file already has a
        table for, so the tool name never has to be enumerated."""
        k = self.kfile()
        for command in (f"uv run python - <<'EOF'\nopen('{k}','a')\nEOF",
                        f"poetry run python - <<'EOF'\nopen('{k}','a')\nEOF",
                        f"pipenv run python3 - <<'EOF'\nopen('{k}','a')\nEOF",
                        f"mise exec -- python3 - <<'EOF'\nopen('{k}','a')\nEOF"):
            self.assertEqual(self.decide(command), "deny", command)

    def test_c6_a_run_verb_whose_operand_is_not_a_program_is_not_peeled(self):
        """One edit from the violations above, and the reason the shape is safe
        to invert: `npm run build` names a SCRIPT, not a program, so nothing is
        peeled and the heredoc after it stays data.

        `docker run python3 -` is the second edit, and it is deliberate rather
        than missed: the body runs in the CONTAINER's filesystem, where
        `~/.claude/.cache/kernel` is not this host's, so peeling it would turn
        the header's stated ssh / container-exec under-fire into a false deny.
        `_REMOTE_RUNNERS` keeps those runners out of the shape."""
        self.hold()
        k = self.kfile()
        self.assertEqual(
            self.decide("npm run build <<'EOF'\nsome data\nEOF"), "allow")
        self.assertEqual(
            self.decide(f"docker run python3 - <<'EOF'\nopen('{k}','a')\nEOF"),
            "allow")

    # ── C7 a valued option must not hide the operand ────────────────────────
    def test_c7_a_valued_option_does_not_turn_a_program_into_data(self):
        """Five spellings, one defect and four residuals of the same shape. The
        value of an option this parser did not know landed where an operand
        would be, `stdin_is_program` read it as a script name and the body
        became data. `bash -s` is the straight defect in the set: it is not an
        unknown option, it MEANS read the program from stdin, and its operands
        are `$0` and the positional parameters."""
        k = self.kfile()
        for command in (f"bash -o pipefail <<EOF\nrm -f {k}\nEOF",
                        f"bash -s foo <<EOF\nrm -f {k}\nEOF",
                        f"bash -s -- foo <<EOF\nrm -f {k}\nEOF",
                        f"python3 -X utf8 <<EOF\nopen('{k}','a')\nEOF",
                        f"python3 -W ignore - <<EOF\nopen('{k}','a')\nEOF"):
            self.assertEqual(self.decide(command), "deny", command)

    def test_c7_a_script_operand_still_means_the_body_is_input(self):
        """One edit from each violation above: a real script name after the
        option. There the program is the file and the body is its stdin, which
        is data, and reading data as a command is the over-fire cycle 11
        removed."""
        self.hold()
        k = self.kfile()
        for command in (f"python3 -W ignore run.py <<EOF\nopen('{k}','a')\nEOF",
                        f"bash -o pipefail run.sh <<EOF\nrm -f {k}\nEOF"):
            self.assertEqual(self.decide(command), "allow", command)

    # ── C8 the parse is bounded, and the bound denies ───────────────────────
    def test_c8_a_parse_that_cannot_finish_denies_instead_of_being_killed(self):
        """The cliff was a silent bypass. `scan()` cost ~250 us per SEGMENT and
        the harness kills this hook at `timeout: 5`, so past roughly 20000
        sub-commands the gate produced NO verdict, and no verdict is read as
        ALLOW by every matrix in this PR. The budget is on segments because the
        cost is per segment: a 20000-line DATA heredoc costs 30 ms because its
        body is split off and never tokenized."""
        self.assertEqual(self.decide("\n".join(["echo rm"] * 2100)), "deny")

    def test_c8_a_command_under_the_budget_is_untouched(self):
        """One edit from the violation: 200 fewer sub-commands. And the shape
        the budget must never punish, a large file written through a data
        heredoc, whose body is not parsed at all."""
        self.hold()
        self.assertEqual(self.decide("\n".join(["echo rm"] * 1900)), "allow")
        body = "\n".join("line %d rm git" % i for i in range(9000))
        self.assertEqual(self.decide(f"cat > notes.md <<'EOF'\n{body}\nEOF"),
                         "allow")

    # ── the residuals this cycle leaves, stated rather than discovered ──────
    def test_named_residuals_of_cycle_12(self):
        """Pinned so the claim stays true, and each one is a MEASURED allow.

        1. a runner whose SUBCOMMAND sits where an operand would (`deno run -`,
           `bun run -`): the head is a CODE HOST, so nothing is peeled in front
           of it, and `run` lands where an operand would;
        2. `${ cmd; }` / `${| cmd; }`, ksh93's value substitution, which bash
           gained in 5.3 and this host (bash 5.2.21) rejects outright.

        Both fail toward ALLOW, which is the right failure for a rule whose
        cost is denying the dominant idiom.

        CYCLE 12'S RESIDUAL 2 IS GONE, and its removal is the measurement that
        matters here: `uv run --with rich python -` allowed because the peel
        stopped at the first valued flag, and cycle 13 inverted the wrapper
        away from the tool name entirely, so `--with`, `rich` and `uv` are all
        just tokens the search walks past on its way to `python`. It is pinned
        as a DENY in `test_c13_the_wrapper_is_a_shape_not_a_table` instead."""
        self.hold()
        k = self.kfile()
        for command in (
                f"deno run --allow-read - <<'EOF'\nopen('{k}','a')\nEOF",
                f"echo ${{ rm -f {k}; }}"):
            self.assertEqual(self.decide(command), "allow",
                             command + " is now covered: move it out of the "
                             "residual list and out of the PR report")



class QaCycle13(IsolationCase):
    """Cycle 12 enumerated three classes and the ENUMERATION became the new
    place to be wrong. Every test below is measured against a REAL HELD LANE
    with `rm -f <lane>` as the passing positive control, because cycle 12's
    wrapper measurement was taken against the kernel directory, where the
    named-path floor catches any verb and hid three holes.

    Each test fails with its own fix reverted, measured one at a time and named
    in the PR report.
    """

    def hold(self):
        self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))

    def decide(self, command, pid="agent-b"):
        rc, out = self.run_gate(BASH_GATE, self.bash_payload(pid, command))
        return "deny" if self.denied(out) else "allow"

    def kfile(self):
        return os.path.join(kernel_proc.kernel_dir(), "journal", "agent-a.jsonl")

    def test_the_positive_control_denies(self):
        """The measurement every other test in this class depends on. Cycle 12
        measured the wrapper class against the KERNEL directory, where the
        named-path floor denies whatever verb arrives, so a wrapper that was
        never peeled still produced a deny and the hole stayed invisible. A
        lane has no such floor: only the verb rule reaches it."""
        self.hold()
        self.assertEqual(self.decide(f"rm -f {self.a_py}"), "deny")

    # ── C13-1 arithmetic is a word context, not a sealed span ───────────────
    def test_c13_a_substitution_inside_arithmetic_is_still_a_command(self):
        """The enumeration said `$((expr))` is "ARITHMETIC, not a command, left
        verbatim on purpose". That is a false statement about bash. Measured on
        bash 5.2.21, each of these removes the file:

            echo $(( $(rm -f a; echo 1) ))     x=$((`rm -f b; echo 2`))
            (( $(rm -f c; echo 3) ))           echo $[ $(rm -f d; echo 1) ]

        Arithmetic is evaluated AFTER expansion, so it is an ordinary word
        context and the scan has to continue inside it."""
        self.hold()
        k, lane = self.kfile(), self.a_py
        for command in (f"echo $(( $(rm -f {k}) ))",
                        f"x=$(( $(rm -f {k}) ))",
                        f"echo $(( 1 + $(rm -f {k}) ))",
                        f"echo $[ $(rm -f {k}) ]",
                        f"echo $(( $(rm -f {lane}) ))"):
            self.assertEqual(self.decide(command), "deny", command)

    def test_c13_arithmetic_that_computes_is_still_arithmetic(self):
        """One edit from each violation above. The `$((` is copied through, so
        an expression with no command in it runs no command and nothing is
        denied; a substitution that only READS stays a read."""
        self.hold()
        k = self.kfile()
        for command in (f"echo $((1 << 3))",
                        f"echo $(( 2 * 3 )) && echo done",
                        f"echo $(( $(cat {k} | wc -l) ))"):
            self.assertEqual(self.decide(command), "allow", command)

    # ── C13-2 the wrapper is a SHAPE, not a table ───────────────────────────
    def test_c13_the_wrapper_is_a_shape_not_a_table(self):
        """Every one of these was measured ALLOWING against a held lane at
        cycle 12's tip, and every binary is installed on this host. `setsid -w`
        is the one that matters most: it is mandated by the hard rules of every
        brief this repo is built under, so it stood in front of nearly every
        command an agent here runs.

        The last two are cycle 12's own residual and its `run`-verb shape,
        closed by the same inversion: `uv` and `--with rich` are just tokens the
        forward search walks past."""
        self.hold()
        lane = self.a_py
        for command in (f"setsid -w rm -f {lane}",
                        f"flock /tmp/octo-c13.lock rm -f {lane}",
                        f"ionice -c 3 rm -f {lane}",
                        f"taskset -c 0 rm -f {lane}",
                        f"unshare -r rm -f {lane}",
                        f"strace -o /dev/null rm -f {lane}",
                        f"systemd-run --user rm -f {lane}",
                        f"watch -x rm -f {lane}",
                        f"uv run --with rich python3 -c \"import os\"" 
                        f" && rm -f {lane}",
                        f"uvx some-tool rm -f {lane}"):
            self.assertEqual(self.decide(command), "deny", command)

    def test_c13_what_the_inversion_must_not_peel(self):
        """The four bounds, one edit from the violations above. A SCRIPT
        runner's `run` names a package.json script or a crate, not a program on
        PATH — both of these were measured DENYING at cycle 12's tip and both
        are over-fires. A REMOTE runner acts on another file system. A package
        manager's `install` is not `/usr/bin/install`. And a cloud CLI's `cp`
        writes an object store, not this disk."""
        self.hold()
        lane = self.a_py
        # QA cycle 14 blocker 4: `apt-get install -y curl wget` and
        # `pip install requests` were green with the `install` bound reverted,
        # because neither names a lane and neither could have denied either way.
        # Every input below now puts the LANE in the position the bound decides,
        # so removing the bound flips the verdict.
        for command in (f"npm run rm -- {lane}",
                        f"cargo run rm {lane}",
                        f"docker run --rm alpine rm -f {lane}",
                        f"ssh buildhost rm -f {lane}",
                        f"apt-get install -y {lane}",
                        f"pip install -t {os.path.dirname(lane)} pkg",
                        f"aws s3 cp {lane} s3://bucket/a.py"):
            self.assertEqual(self.decide(command), "allow", command)

    def test_c13_a_reserved_word_head_is_not_an_unknown_program(self):
        """The over-fire the inversion had before it was bounded, measured over
        19191 real Bash commands from this machine's transcripts: a python
        heredoc body carrying `for ln in mem.read_text().splitlines():` peeled
        at `ln`, a real mutator in a real table, on a line that is not a shell
        command at all. And `case … pend) ;; *) break;; esac` arrives as ONE
        segment from the borrowed splitter, so a search with no stop walked
        past `;;`, `esac` and `done` into the next command entirely."""
        self.hold()
        lane = self.a_py
        # QA cycle 14 blocker 4: both inputs were lane-free, so the reserved
        # word and the scan stop could be deleted with the test still green.
        # The lane is now in the position each bound protects: after the
        # reserved-word head, and past a `;;` the walk must not cross.
        # The loop variable is `ln`, a real mutator, and the word after it is
        # the LANE: without the reserved-word guard the head `for` is read as an
        # unknown program, the search peels at `ln`, and `_copy_targets` reads
        # `in <lane>` as a hardlink onto the lane. With the guard it is a `for`
        # loop. Anything less than a lane in that position and the revert stays
        # green, which is what QA cycle 14 blocker 4 measured.
        for command in (f"for ln in {lane}; do echo $ln; done",
                        f"case x in pend) ;; *) break;; esac\nls {lane}"):
            self.assertEqual(self.decide(command), "allow", command)

    def test_c13_the_walk_stops_where_the_command_does(self):
        """The scan stop, separated from the reserved-word head because the two
        were covering each other: `case …` is a reserved word, so the head guard
        blocked the peel before the stop was ever consulted and deleting the
        stop left the test green (QA cycle 14 blocker 4).

        The head here is a program this file models nothing about, so the guard
        does not fire, and the reserved word sits WHERE THE WALK REACHES IT. It
        is the shape the corpus produced: `case "$ST" in … pend) ;; *) break;;
        esac / done / aws s3 cp …` arrives as one segment from the borrowed
        splitter, and a walk with no stop crosses `;;`, `esac` and `done` into
        the next command."""
        self.hold()
        lane = self.a_py
        # `;;` is NOT in this list on purpose: the borrowed splitter breaks a
        # segment on `;`, so `mytool arg ;; rm -f <lane>` really is two commands
        # and the second one really does delete the lane. It denies, correctly,
        # and asserting otherwise would pin a bug.
        for command in (f"mytool arg done rm -f {lane}",
                        f"mytool arg esac rm -f {lane}"):
            self.assertEqual(self.decide(command), "allow", command)

    # ── C13-3 the `-c` channel in every spelling that eats the next word ────
    def test_c13_a_bundle_ending_in_c_is_minus_c(self):
        """`_shell_c` and the wrapped fallback both looked for the token `-c`,
        exactly, so a short-option bundle walked. On an UNMODELED head the rule
        is the merge gate's inversion rather than a wrapper table: when no
        program this file knows comes first, a `-c`-shaped flag is a re-parse
        whatever the wrapper is called."""
        self.hold()
        lane = self.a_py
        for command in (f"bash -ec 'rm -f {lane}'",
                        f"sh -euc 'rm -f {lane}'",
                        f"script -qc 'rm -f {lane}' /dev/null",
                        f"flock /tmp/octo-c13b.lock -c 'rm -f {lane}'"):
            self.assertEqual(self.decide(command), "deny", command)

    def test_c13_a_c_that_is_not_a_command_flag_is_left_alone(self):
        """The bounds on the inversion above, and the reason it is safe. The
        first three heads are programs this file MODELS as read-only, so the
        unmodeled-head rule never reaches them and `-c` keeps meaning count.
        `git -c` is a config setting on a head this file models. And a REMOTE
        runner is excluded for the same reason it is excluded from the peel:
        `docker run alpine sh -c '…'` runs in the container's file system, and
        `ssh -c` is a cipher, not a command."""
        self.hold()
        lane = self.a_py
        for command in (f"grep -rc rm {lane}",
                        f"wc -lc {lane}",
                        f"sort -uc {lane}",
                        f"git -c user.name=x status",
                        f"docker run --rm alpine sh -c 'rm -f {lane}'",
                        f"ssh -c aes256-ctr buildhost uptime",
                        f"ffmpeg -i a.mp4 -c copy b.mp4"):
            self.assertEqual(self.decide(command), "allow", command)

    # ── C13-4 eval ─────────────────────────────────────────────────────────
    def test_c13_eval_reparses_its_arguments_joined(self):
        """The one member of the class with no flag at all: every argument
        `eval` takes, joined, is a command line."""
        self.hold()
        self.assertEqual(self.decide(f"eval 'rm -f {self.a_py}'"), "deny")
        self.assertEqual(self.decide(f"eval rm -f {self.a_py}"), "deny")

    def test_c13_eval_of_a_read_is_a_read(self):
        self.hold()
        self.assertEqual(self.decide(f"eval 'cat {self.a_py}'"), "allow")

    # ── C13-5 a heredoc feeds a DESCRIPTOR ─────────────────────────────────
    def test_c13_a_heredoc_is_paired_with_the_operand_by_number(self):
        """`is_stdin_operand` accepted base 0 while `_heredoc_ops` accepted
        `3<<`, so `python3 /dev/fd/3 3<<'EOF'` executed and allowed. The path
        forms are the same defect one `/` wide: `//dev/stdin` and `/dev//fd/0`
        are the same files to the kernel and were different strings to the
        table."""
        self.hold()
        k = self.kfile()
        for command in (f"python3 /dev/fd/3 3<<'EOF'\nopen('{k}','a')\nEOF",
                        f"python3 /proc/self/fd/4 4<<'EOF'\nopen('{k}','a')\nEOF",
                        f"python3 //dev/stdin <<'EOF'\nopen('{k}','a')\nEOF",
                        f"python3 /dev//fd/0 <<'EOF'\nopen('{k}','a')\nEOF"):
            self.assertEqual(self.decide(command), "deny", command)

    def test_c13_a_descriptor_nothing_feeds_is_still_data(self):
        """One edit: the operand names fd 3 and the heredoc feeds fd 0, so the
        body is the SCRIPT's input and not its program."""
        self.hold()
        k = self.kfile()
        self.assertEqual(
            self.decide(f"python3 /dev/fd/3 <<'EOF'\nopen('{k}','a')\nEOF"),
            "allow")

    # ── C13-6 a missing terminator is still a heredoc ──────────────────────
    def test_c13_a_heredoc_with_no_terminator_still_runs_its_body(self):
        """Bash warns ("here-document delimited by end-of-file") and runs the
        body anyway. `split_heredocs` said "not a heredoc" and handed the body
        to the command splitter, so a body destined for an interpreter was read
        as a list of shell words instead of the program it is. One byte cheaper
        than the decoy closed in cycle 12 C3, and in the opposite direction."""
        self.hold()
        k, lane = self.kfile(), self.a_py
        self.assertEqual(self.decide(f"bash -s <<EOF\nrm -f {lane}"), "deny")
        self.assertEqual(self.decide(f"python3 - <<EOF\nopen('{k}','a')"), "deny")

    def test_c13_a_data_body_with_no_terminator_is_still_data(self):
        """One edit: `cat > notes` is not a stdin-program host, so the body is
        data whether it is closed or not, and the rest of the input belongs to
        it exactly as bash says it does."""
        self.hold()
        self.assertEqual(
            self.decide(f"cat > notes.txt <<'EOF'\nrm -f {self.a_py}"), "allow")

    # ── C13-7 a heredoc opened inside a WORD ───────────────────────────────
    def test_c13_a_heredoc_opened_inside_a_substitution_has_a_host(self):
        """`result=$(python3 - <<EOF …)` is the common idiom. The body was
        split off first, the opener was masked to a marker, the recursion saw
        no body, and the orphan drained against a line whose head is `x=` —
        which `peel_env` removes, leaving no host at all."""
        self.hold()
        k, lane = self.kfile(), self.a_py
        for command in (f"x=$(bash -s <<'EOF'\nrm -f {lane}\nEOF\n)",
                        f"x=$(python3 - <<'EOF'\nopen('{k}','a')\nEOF\n)",
                        f"x=`python3 - <<'EOF'\nopen('{k}','a')\nEOF\n`"):
            self.assertEqual(self.decide(command), "deny", command)

    def test_c13_a_data_heredoc_inside_a_substitution_is_still_data(self):
        self.hold()
        self.assertEqual(
            self.decide(f"x=$(cat <<'EOF'\nrm -f {self.a_py}\nEOF\n)"), "allow")

    # ── C13-8 one rule, one scope ──────────────────────────────────────────
    def test_c13_a_computed_write_target_reaches_a_lane_too(self):
        """`subst_names_kernel_state` applied the raw-text test to the KERNEL
        directory and to nothing else, so one rule had two scopes: a computed
        target that spelled the kernel directory denied while the same shape
        aimed at another process's lane walked."""
        self.hold()
        pkg = os.path.dirname(self.a_py)
        self.assertEqual(self.decide(f"echo hi > $(echo {pkg})/a.py"), "deny")
        self.assertEqual(self.decide(f"echo hi > $(dirname {self.a_py})/a.py"),
                         "deny")

    def test_c13_a_computed_target_is_the_token_not_the_word(self):
        """The bound, and it is what keeps the rule from denying a whole tree:
        the word from the body is substituted INTO the token, so
        `> $(echo <pkg>)/notes.txt` names `<pkg>/notes.txt` and not `<pkg>`.
        Returning the bare word put a hit on the directory, which prefix-matches
        every lane under it."""
        self.hold()
        pkg = os.path.dirname(self.a_py)
        self.assertEqual(self.decide(f"echo hi > $(echo {pkg})/notes.txt"),
                         "allow")

    def test_c13_a_separator_only_word_names_no_path(self):
        """Measured over the real corpus: `> $T/g_$(echo $ref | tr '/' '_').py`
        put a hit on `/` on 14 commands, out of the `'/'` argument of `tr`."""
        # QA cycle 14 blocker 4, and the correction matters more than the
        # anchor. Cycle 13 justified this guard by saying the bare word
        # "resolves to the filesystem ROOT, which prefix-matches every lane
        # there is". That is FALSE: `kernel_proc.paths_conflict("/", <lane>)`
        # is False by design, so a `/` hit can never change a verdict and no
        # behavioural test could ever anchor this. What the guard actually buys
        # is a junk hit removed, which costs an ownership lookup and puts a
        # meaningless target in the deny report. So it is asserted on the HITS,
        # the same way the null-sink filter is.
        gate = _load(BASH_GATE, "bash_gate_separator_word")
        self.assertEqual(
            gate.scan("echo hi > $(echo x | tr 'q' '/')", self.tree),
            [("path", kernel_proc.norm_path(os.path.join(self.tree, "__OCTOSUBST0__")),
              ">")])

    # ── C13-9 characters are charged where they are WALKED ─────────────────
    def test_c13_the_opener_walk_is_charged_before_it_runs(self):
        """M10. The cap was a TEST taken after `split_heredocs` had already
        char-walked every line carrying `<<`, so that walk was free: QA measured
        13.3 s and 11.8 s on multi-megabyte shapes and, under a 5 s emulated
        kill, rc 124 with zero bytes on stdout — twice — which is the
        no-verdict-reads-as-allow path this budget exists to close."""
        gate = _load(BASH_GATE, "bash_gate_opener_charge")
        pad = "a" * (gate._MAX_PARSE_CHARS + 4096)
        # `split_heredocs` is called DIRECTLY, because the whole claim is about
        # ORDER: `scan` charges the parsed text too, one line later, and a test
        # that only asks "was it denied" cannot tell the two charges apart. This
        # one asks the earlier of the two, and goes green only while the walk
        # itself is what refuses.
        budget = [gate._MAX_SEGMENTS, gate._MAX_PARSE_CHARS]
        with self.assertRaises(gate.ParseTooLarge):
            gate.split_heredocs("cat <<EOF " + pad + "\nbody\nEOF", budget)

    def test_c13_an_unquoted_body_is_charged_before_it_is_scanned(self):
        """The second uncharged walk: a heredoc body is exempt from the parse
        cap by design, and then the substitution scanner reads every character
        of an UNQUOTED one in a pure-Python loop."""
        gate = _load(BASH_GATE, "bash_gate_body_charge")
        pad = "a" * (gate._MAX_PARSE_CHARS + 4096)
        with self.assertRaises(gate.ParseTooLarge):
            gate.scan("cat <<EOF\n" + pad + "\nrm -f x\nEOF", self.tree)

    def test_c13_a_quoted_body_is_not_charged_because_it_is_not_walked(self):
        """The control that keeps the charge honest, and the reason the cap can
        be this low: a QUOTED body runs nothing, is never scanned for
        substitutions, and a large file written through `cat > f <<'EOF'` stays
        exactly as cheap and as allowed as it is today."""
        gate = _load(BASH_GATE, "bash_gate_quoted_body")
        pad = "a" * (gate._MAX_PARSE_CHARS * 4)
        hits = gate.scan("cat > f.txt <<'EOF'\n" + pad + "\nEOF", self.tree)
        self.assertEqual(hits, [("path",
                                 kernel_proc.norm_path(
                                     os.path.join(self.tree, "f.txt")), ">")])

    def test_c13_the_substitution_count_is_charged(self):
        """M8. Each masked substitution is a COMMAND and spends a segment; the
        charge is taken up front because the masking has already happened and
        the count is exact.

        QA cycle 14 blocker 4: the first spelling of this test used `$(rm)`
        bodies, and reverting the up-front charge left it GREEN because each
        body was then scanned as its own segment and charged there — two
        mechanisms covering each other, which is the shape that makes a revert
        look anchored when it is not. The bodies here are EMPTY, so a
        recursion into them charges nothing (`scan` fast-outs on a command with
        no trigger before it spends a segment) and the up-front count is the
        only thing that can raise."""
        gate = _load(BASH_GATE, "bash_gate_subst_charge")
        empty = "echo rm " + "$()" * (gate._MAX_SEGMENTS + 50)
        with self.assertRaises(gate.ParseTooLarge):
            gate.scan(empty, self.tree)

    def test_c14_the_caps_are_pinned_to_their_measurement(self):
        """QA cycle 14 blocker 3 and 4: a `CAP_256K` mutant stayed green, so
        nothing in the suite defended the number and it could drift back to a
        value that fails open by clock. The numbers are asserted here with the
        measurement that produced them, taken END TO END through the real hook
        against a real held lane, which is what faces the harness `timeout: 5`:

            95 KiB one long word        1.74 s sequential
            95 KiB `rm -f x x x …`      6.63 s sequential, 9.85 s x3 concurrent
            8192 tokens                 2.22 s sequential, 2.87 s x3 concurrent
            47 KiB one long word        2.31 s sequential, 2.03 s x3 concurrent

        Timing is never ASSERTED (v8-kernel.md section 3) because a clock under
        load is not a fact about the code. The CONSTANTS are, and they are what
        a mutant moves."""
        gate = _load(BASH_GATE, "bash_gate_caps")
        self.assertLessEqual(gate._MAX_PARSE_CHARS, 48 * 1024)
        self.assertLessEqual(gate._MAX_PARSE_TOKENS, 8192)
        self.assertLessEqual(gate._MAX_SEGMENTS, 2000)

    def test_c13_the_parse_cap_is_a_spend_not_a_test(self):
        """M9. The cap is cumulative across FRAMES, so text a recursion re-reads
        is charged for both readings — the cap bounds the WALKING, not the
        command. A `bash -c` body is walked twice, so it costs twice."""
        self.hold()
        gate = _load(BASH_GATE, "bash_gate_parse_cap")
        half = "a" * int(gate._MAX_PARSE_CHARS * 0.6)
        with self.assertRaises(gate.ParseTooLarge):
            gate.scan("bash -c 'rm -f x " + half + "'", self.tree)
        self.assertEqual(
            self.decide("bash -c 'echo " + "a" * 4096 + "'"), "allow")

    # ── the three mutants cycle 12 left unpinned ───────────────────────────
    def test_c13_m5_a_tab_decoy_does_not_close_a_plain_heredoc(self):
        """`<<-` strips leading TABS from the terminator line and a plain `<<`
        strips nothing, so a `\tEOF` line does not close a `<<EOF`. Cycle 12 C3
        has a fixture for the SPACE decoy only, and the mutant that drops the
        tabstrip test flipped this to allow with nothing failing."""
        self.hold()
        k = self.kfile()
        # The decoy has to sit BEFORE the dangerous line, or both readings deny
        # and the test measures nothing: with the tabstrip test dropped, `\tEOF`
        # closes the body at line 1 and `open('<kdir>/…')` becomes a top-level
        # segment whose token is not a path, so the mutant ALLOWS.
        self.assertEqual(
            self.decide(f"python3 - <<EOF\nimport os\n\tEOF\n"
                        f"open('{k}','a')\nEOF"), "deny")
        # and the operator that DOES strip tabs still strips them: `<<-EOF`
        # closes on `\tEOF`, so the line after it is a command and not a body
        self.assertEqual(
            self.decide(f"python3 - <<-EOF\nimport os\n\tEOF\nrm -f {self.a_py}"),
            "deny")

    def test_c13_m17_an_apostrophe_inside_double_quotes_is_not_a_quote(self):
        """M17. Inside double quotes a `'` is an ordinary character, so the
        single-quote state must not toggle on it. No test had an apostrophe
        before a substitution, and the mutant that stops tracking `in_dq`
        flipped this to allow."""
        self.hold()
        k = self.kfile()
        self.assertEqual(self.decide(f'echo "it\'s $(rm -f {k})"'), "deny")

    def test_c13_m18_a_substitution_marker_travels_into_a_recursion(self):
        """M18. The end-of-scan drain is the only thing covering a substitution
        whose marker is masked at one frame and handed to a recursion that never
        saw it. Both spellings were unpinned."""
        self.hold()
        lane = self.a_py
        self.assertEqual(self.decide(f'bash -c "echo $(rm -f {lane})"'), "deny")
        self.assertEqual(self.decide(f"( echo $(rm -f {lane}) )"), "deny")

    # ── the residuals this cycle leaves, stated rather than discovered ──────
    def test_named_residuals_of_cycle_13(self):
        """Each one a MEASURED allow, pinned so the claim stays true.

        1. a wrapper whose PROGRAM is computed (`setsid $(echo rm) -f x`): the
           peel target is a marker, not a program, so the segment falls back to
           the token scan — the behaviour a computed verb has had since cycle 12;
        2. a python heredoc body that deletes a LANE (`os.remove('<lane>')`):
           an interpreter body is tested against the kernel floor as RAW TEXT
           and re-scanned as commands only for a shell, so a lane path inside
           python is not a shell target.

        CYCLE 13'S RESIDUAL 2 IS GONE and its removal is the point: it said a
        wrapper could hide its program "past `_PEEL_SCAN` tokens", and QA cycle
        14 measured real traffic putting the program past that number, so the
        cap was deleted rather than re-chosen and the shape is now covered.
        This test is what noticed: it went RED on the deletion instead of
        letting a stale residual survive in the report."""
        self.hold()
        lane = self.a_py
        for command in (f"setsid $(echo rm) -f {lane}",
                        f"python3 - <<'EOF'\nimport os\nos.remove('{lane}')\nEOF"):
            self.assertEqual(self.decide(command), "allow",
                             command + " is now covered: move it out of the "
                             "residual list and out of the PR report")


class QaCycle14(IsolationCase):
    """Cycle 13 inverted the wrapper and corrected one false row of cycle 12's
    enumeration. Cycle 14 measured what was left and found the pattern had moved
    again: the ALLOW-LISTS that stand in FRONT of the model. A read-only list
    that could write, a trigger list that never let a modelled program run, and
    a scan depth chosen against a shape real traffic exceeds.

    Every test is measured against a REAL HELD LANE with `rm -f <lane>` as the
    positive control, and each fails with its own fix reverted.
    """

    def hold(self):
        self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))

    def decide(self, command, pid="agent-b"):
        rc, out = self.run_gate(BASH_GATE, self.bash_payload(pid, command))
        return "deny" if self.denied(out) else "allow"

    def kdir(self):
        return kernel_proc.kernel_dir()

    def test_the_positive_control_denies(self):
        self.hold()
        self.assertEqual(self.decide(f"rm -f {self.a_py}"), "deny")

    # ── B1 the read-only list was the hole ─────────────────────────────────
    def test_c14_a_read_only_program_can_still_write(self):
        """`_KSTATE_READONLY` carried `sort`, `uniq` and `less`, and the header
        called it "the set of programs that provably cannot create, replace or
        unlink a path". Measured on this host: `sort -o /tmp/f /etc/hostname`
        and `uniq /etc/hostname /tmp/f` each wrote 11 bytes. The floor worked
        for every program NOT on the list, so the list was the hole."""
        self.hold()
        k = self.kdir()
        for command in (f"sort -o {k}/ptable.json /etc/hostname",
                        f"uniq /etc/hostname {k}/ptable.json",
                        f"cat /etc/hostname | less --log-file={k}/ptable.json",
                        f"curl -so{k}/ptable.json http://x"):
            self.assertEqual(self.decide(command), "deny", command)

    def test_c14_a_read_only_operand_is_still_a_read(self):
        """The bound, one edit away: the list exempts a program's OPERANDS, and
        reading kernel state is how anyone debugs this machine. What it never
        exempted, and now does not, is a path handed to a FLAG."""
        self.hold()
        k = self.kdir()
        for command in (f"cat {k}/ptable.json",
                        f"grep -c x {k}/ptable.json",
                        f"head -n 5 {k}/ptable.json",
                        f"wc -l {k}/ptable.json"):
            self.assertEqual(self.decide(command), "allow", command)

    def test_c14_no_readonly_member_takes_an_output_file(self):
        """The screen that found `sort` and `less`, re-run so a member added
        later without it fails. AND THE SCREEN CANNOT PROVE THE NEGATIVE: it
        reads FLAGS out of `--help`, and `uniq`'s write is a POSITIONAL, which
        is exactly the member it missed and a human found by running it. That
        is why the header no longer claims the list is closed."""
        gate = _load(BASH_GATE, "bash_gate_readonly_screen")
        # flags whose name looks like output but whose value is not a file
        # Each entry is a flag whose name looks like output and whose value is
        # not a file: `ls -o` is a long format, `grep -o` (and its `egrep` /
        # `fgrep` aliases) is only-matching, `od -o` is an octal format,
        # `strings -o` is an offset, and the two `--output-*` are separators.
        benign = {("ls", "-o"), ("grep", "-o"), ("egrep", "-o"),
                  ("fgrep", "-o"), ("cut", "--output-delimiter"),
                  ("od", "-o"), ("od", "--output-duplicates"),
                  ("strings", "-o"), ("strings", "--output-separator")}
        offenders = []
        for prog in gate._KSTATE_READONLY:
            try:
                cp = subprocess.run([prog, "--help"], capture_output=True,
                                    text=True, timeout=5)
            except (OSError, subprocess.SubprocessError):
                continue
            text = cp.stdout + cp.stderr
            for flag in ("-o", "-O", "--output", "--output-file", "--log-file"):
                if re.search(r"(^|[\s,])" + re.escape(flag) + r"([\s,=]|$)",
                             text, re.M) and (prog, flag) not in benign:
                    offenders.append((prog, flag))
        self.assertEqual(offenders, [], "a read-only member takes an output "
                         "file: either prove it cannot write or drop it")

    # ── B2 a wrapper chain ─────────────────────────────────────────────────
    def test_c14_a_wrapper_hands_off_to_the_wrapper_table(self):
        """`_peel_target` excluded `_WRAPPERS`, so an unmodeled head could not
        hand off to the table, and an `env -u` chain then pushed the real
        program past the scan depth. Every one of these was measured ALLOWING
        against a held lane at e00fad7, and the first is the shape the hard
        rules of every brief here mandate."""
        self.hold()
        lane = self.a_py
        for command in (
                f"setsid -w env -u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE"
                f" -u GIT_PREFIX rm -f {lane}",
                f"setsid -w nice -n 10 ionice -c 3 taskset -c 0 rm -f {lane}",
                f"setsid -w env A=1 B=2 C=3 D=4 E=5 F=6 G=7 H=8 rm -f {lane}",
                f"setsid -w env -u A -u B -u C -u D python3 - <<'EOF'\n"
                f"open('{self.kdir()}/ptable.json','w')\nEOF"):
            self.assertEqual(self.decide(command), "deny", command)

    def test_c14_the_handoff_carries_the_working_directory(self):
        """What the handoff is FOR, and the revert that showed the first
        version of this claim was not anchored: with the scan unbounded, a flat
        search reaches `rm` through an `env -u` chain either way, so the lane
        denied with or without `_WRAPPERS` as a peel target. The difference is
        the CWD. `env -C <dir>` moves the directory a relative target resolves
        against, and only the wrapper TABLE knows that; a flat jump to `rm`
        resolves `a.py` against the wrong directory and misses the lane."""
        self.hold()
        pkg = os.path.dirname(self.a_py)
        self.assertEqual(self.decide(f"setsid -w env -C {pkg} rm -f a.py"), "deny")

    def test_c14_a_read_only_head_still_has_its_flags_read(self):
        """The other branch a revert found unanchored. Today no member of the
        list takes an output file, so the read-only branch's flag test is
        unreachable through a real program and a behavioural test cannot see
        it. It is defence for the member added tomorrow, so it is asserted on
        the FUNCTION: a path handed to a flag is a hit whatever the head is."""
        gate = _load(BASH_GATE, "bash_gate_readonly_flags")
        k = kernel_proc.kernel_dir()
        self.assertEqual(
            gate.flag_values_naming_kernel_state(
                ["grep", "--output=%s/ptable.json" % k], self.tree, k),
            [kernel_proc.norm_path(k + "/ptable.json")])
        self.assertEqual(
            gate.flag_values_naming_kernel_state(
                ["grep", "--output=/tmp/elsewhere"], self.tree, k), [])
        # and the CALL SITE, which a revert showed the assertion above cannot
        # reach: with today's list no member takes an output file, so the
        # read-only branch is unreachable through a real program. Putting a
        # writer ON the list is the only way to exercise it, and that is
        # exactly the future this branch is defence against.
        gate._KSTATE_READONLY = gate._KSTATE_READONLY + ("curl",)
        try:
            hits = gate.scan("curl --output=%s/ptable.json http://x" % k, self.tree)
        finally:
            gate._KSTATE_READONLY = tuple(
                x for x in gate._KSTATE_READONLY if x != "curl")
        self.assertTrue(any(kind == "state" for kind, _t, _v in hits), hits)

    def test_c14_the_order_that_already_worked_still_works(self):
        """The control that named the cause: with the wrapper FIRST the table
        peeled it and the chain denied, so the difference was the handoff and
        not the chain."""
        self.hold()
        self.assertEqual(
            self.decide(f"env -u GIT_DIR -u GIT_WORK_TREE setsid -w rm -f {self.a_py}"),
            "deny")

    # ── B5 members past the stated end ─────────────────────────────────────
    def test_c14_a_pipe_into_a_shell_is_a_stdin_channel(self):
        """The header listed heredoc, here-string and process substitution as
        "the same channel in other syntax" and left out the PIPE, which is the
        common one: 61 real commands on this machine pipe into a shell."""
        self.hold()
        lane = self.a_py
        for command in (f'echo "rm -f {lane}" | bash',
                        f"printf 'rm -f %s\\n' {lane} | sh",
                        f'. <(echo "rm -f {lane}")'):
            self.assertEqual(self.decide(command), "deny", command)

    def test_c14_a_pipe_that_is_not_a_program_is_not_one(self):
        """One edit: the same pipe into a program that does not run stdin as
        its program is ordinary data, and text that no shell receives stays
        text."""
        self.hold()
        lane = self.a_py
        for command in (f'echo "rm -f {lane}" | wc -l',
                        f'echo "rm -f {lane}" > /tmp/notes.txt'):
            self.assertEqual(self.decide(command), "allow", command)

    def test_c14_an_output_flag_is_a_write(self):
        """595 real commands on this machine carry `-o`/`-O`. A lane has no
        floor to catch them, so the only thing separating `curl -o <lane>` from
        `grep -f <lane>` is knowing what the flag means. Enumerated, and the
        source says it is an enumeration with an end."""
        self.hold()
        lane = self.a_py
        for command in (f"curl -so {lane} http://x",
                        f"wget -qO {lane} http://x",
                        f"sort -o {lane} /etc/hostname",
                        f"uniq /etc/hostname {lane}"):
            self.assertEqual(self.decide(command), "deny", command)

    def test_c14_a_program_that_consumes_its_input_is_a_write(self):
        """`gzip <lane>` leaves `<lane>.gz` and no `<lane>`; `zip -qm` and
        `tar --remove-files` delete what they packed. Measured deleting a real
        file on this host."""
        self.hold()
        lane = self.a_py
        for command in (f"gzip {lane}",
                        f"tar -cf /tmp/x.tar --remove-files {lane}",
                        f"zip -qm /tmp/x.zip {lane}"):
            self.assertEqual(self.decide(command), "deny", command)

    def test_c14_keeping_the_input_is_not_a_write(self):
        """One edit from the violation above: the flag that turns the removal
        off is read, so `gzip -k` is a copy and not a delete."""
        self.hold()
        self.assertEqual(self.decide(f"gzip -k {self.a_py}"), "allow")

    def test_c14_a_command_string_argument_is_a_command(self):
        """`env -S` is the sharpest: `-S` was already in env's VALUED option
        table, so the command WAS the value and the peel dropped it whole.
        `watch` takes its command as one string, and `--` does not hide the
        operand a flag already claimed."""
        self.hold()
        lane = self.a_py
        for command in (f'env -S "rm -f {lane}"',
                        f'watch -n 0.1 "rm -f {lane}"',
                        f'bash -c -- "rm -f {lane}"',
                        f'env -u GIT_DIR bash -c -- "rm -f {lane}"',
                        f'bash -ce "rm -f {lane}"',
                        f"git -c alias.zap='!rm -f' zap {lane}"):
            self.assertEqual(self.decide(command), "deny", command)

    def test_c14_a_bundle_on_an_unmodeled_head_must_still_end_in_c(self):
        """The bound on the widened bundle rule, and it is a regression this
        cycle caused and caught: reading `c` ANYWHERE in a cluster is right for
        a shell and wrong for everything else, because `tar -cf a.tar dir` and
        `ps -ef` are not shells. Widening it unscoped stopped
        `tar --remove-files` from reaching its own rule."""
        self.hold()
        lane = self.a_py
        self.assertEqual(self.decide(f"tar -cf /tmp/x.tar --remove-files {lane}"),
                         "deny")
        self.assertEqual(self.decide(f"tar -cf /tmp/x.tar {os.path.dirname(lane)}"),
                         "allow")

    def test_c14_find_ok_runs_what_find_exec_runs(self):
        """`-ok`/`-okdir` differ from `-exec`/`-execdir` by a confirmation
        prompt, and a prompt is not a gate."""
        self.hold()
        pkg = os.path.dirname(self.a_py)
        for command in (f"find {pkg} -name a.py -ok rm {{}} ;",
                        f"find {pkg} -name a.py -okdir rm {{}} ;"):
            self.assertEqual(self.decide(command), "deny", command)

    def test_c14_a_substitution_that_runs_later_is_still_a_command(self):
        """`x="a[\\$(rm -f <lane>; echo 0)]"; echo $((x))` deletes under bash.
        The escape makes the substitution literal at assignment time and the
        arithmetic runs it later. The residual this would fall into says
        "unknowable without running the shell", and that is not true here: the
        path is spelled out. So the rule is on the DEFERRING CONSTRUCT."""
        self.hold()
        lane = self.a_py
        self.assertEqual(
            self.decide(f'x="a[\\$(rm -f {lane}; echo 0)]"; echo $((x))'), "deny")

    def test_c14_quoted_prose_without_an_evaluator_stays_prose(self):
        """The bound: without a deferred evaluator in the command the same text
        runs nothing, which is what keeps a quoted mention allowed."""
        self.hold()
        self.assertEqual(self.decide(f"echo 'x $(rm -f {self.a_py})'"), "allow")

    def test_c14_a_null_device_is_not_a_target(self):
        """`curl -o /dev/null` is the standard way to measure an HTTP status
        and it produced 796 hits over 19403 real commands once output flags
        were read. It accepts a write and stores nothing, so it is not a
        target: the hit could never be anyone's lane and each one costs an
        ownership lookup. Asserted on the HITS rather than the verdict, because
        a `/dev/null` hit never changes a verdict and a behavioural test could
        not tell the filter from its absence."""
        gate = _load(BASH_GATE, "bash_gate_null_sink")
        self.assertEqual(
            gate.scan('curl -s -o /dev/null -w "%{http_code}" http://x', self.tree),
            [])
        self.assertEqual(
            gate.scan("rm -f /dev/null", self.tree), [])
        self.assertNotEqual(
            gate.scan("curl -s -o /tmp/real.txt http://x", self.tree), [])

    # ── the trigger was the last verb allow-list ───────────────────────────
    def test_c14_every_dispatch_table_is_a_trigger(self):
        """The fast path in front of the model was a hand-written verb list and
        it had drifted: `curl -so <lane>` and `gzip <lane>` were parsed
        correctly by their own helpers and `scan` returned [] before calling
        either. It is derived now, and this asserts the derivation so a table
        added later without it fails."""
        gate = _load(BASH_GATE, "bash_gate_triggers")
        for table in (gate._MUTATORS, gate._STATE_VERBS, gate._OUTPUT_FLAGS,
                      gate._CONSUMING, gate._POSITIONAL_OUTPUT,
                      gate._COMMAND_STRING):
            for name in table:
                self.assertIn(name, gate._TRIGGERS, name)

    # ── the caps, and what the program answers above them ──────────────────
    def test_c14_the_token_cost_is_charged_where_it_is_spent(self):
        """Blocker 3. Cycle 13 measured one long word, which is
        `shlex`-quadratic and looked like the ceiling. MANY SHORT TOKENS is
        worse, because every token is resolved and every hit costs an ownership
        lookup: 95 KiB of `rm -f x x x …` cost 6.63 s sequentially and 9.85 s
        with three concurrent, against a `timeout: 5` whose kill writes nothing
        and reads as ALLOW."""
        gate = _load(BASH_GATE, "bash_gate_token_charge")
        over = "rm -f " + " ".join(["x"] * (gate._MAX_PARSE_TOKENS + 200))
        with self.assertRaises(gate.ParseTooLarge):
            gate.scan(over, self.tree)

    def test_c14_a_command_under_the_token_cap_is_untouched(self):
        """The control: the cap must never punish a real command. The largest
        of 19403 distinct real commands on this machine is 4429 tokens, and the
        p999 is 1206."""
        gate = _load(BASH_GATE, "bash_gate_token_control")
        under = "rm -f " + " ".join(["x"] * 4429)
        self.assertEqual(len(gate.scan(under, self.tree)), 4429)


class SharedParserConvergence(unittest.TestCase):
    """One rule, one authority, and an alarm when the copies drift.

    `qa-merge-gate.py` is this brain's PROVIDER of the command-boundary parser:
    `receipt_ledger._qa_gate_helpers()` borrows `_split_subcmds` and
    `_strip_leading` from it, and cycle 11 borrowed `_stdin_channel_texts` from
    it for the heredoc work. `_command_substitution_texts` is the authority on
    what a command substitution IS. The Bash gate needs the same rule expressed
    as SPANS rather than texts, because it has to keep the outer command
    tokenizing and has to recognise a computed write target as opaque, so it
    carries `split_command_substitutions` — whose body half is one call away
    from the provider's whole contract.

    This test is what keeps that from becoming a third drifting copy. It skips
    with a named reason on a base whose merge gate does not carry the function
    yet, and it arms itself the moment that branch lands.
    """

    CORPUS = (
        "echo $(rm -f /x)",
        "echo `rm -f /x`",
        "echo $((1 << 3))",
        # QA cycle 13: the corpus that AVOIDS the divergence is the same shape
        # as a fixture set that avoids the bug. Bash expands `$(cmd)` and
        # backticks INSIDE `$(( ))` — measured, `bash -c 'echo $(( $(rm -f a;
        # echo 1) ))'` removes the file — so arithmetic is an ordinary word
        # context and these four were a live disagreement the old corpus could
        # not see: this gate returned [] and the provider returned the inner
        # command.
        "echo $(( $(c) ))",
        "echo $(( $(rm -f /x) ))",
        "x=$((`b`))",
        "echo $(( 1 + $(a) ))",
        "echo 'x $(rm -f /x)'",
        'echo "$(a) $(b)"',
        "x=$(echo $(y))",
        "echo hi > $(echo /d)/f",
        'git commit -m "$(date)"',
        "echo $(cd /tmp; rm -f a)",
        'bash -c "rm -f $(echo /k)/p"',
        "cat <<EOF\n$(rm -f /k)\nEOF",
        "echo no substitution here",
        "echo \\$(not a sub)",
        "echo $(a `b` c)",
    )

    def test_the_substitution_rule_has_one_authority(self):
        merge_gate = SCRIPTS / "qa-merge-gate.py"
        if not merge_gate.exists():
            self.skipTest("no qa-merge-gate.py on this base")
        theirs = getattr(_load(merge_gate, "qa_merge_gate_convergence"),
                         "_command_substitution_texts", None)
        if theirs is None:
            self.skipTest(
                "qa-merge-gate.py on this base carries no "
                "`_command_substitution_texts`; it lands with "
                "fix/qa-gate-blanket-override (e0f9444) and this test arms "
                "itself the moment it does")
        mine = _load(BASH_GATE, "bash_gate_convergence")
        for text in self.CORPUS:
            self.assertEqual(
                list(mine.split_command_substitutions(text)[1].values()),
                theirs(text),
                "the two spellings of the substitution rule disagree on "
                + repr(text) + ": converge them instead of keeping both")


class Selftests(unittest.TestCase):

    FIXTURES = "registry/fixtures/ARCHITECTURE.kernel-isolation"

    def test_both_gates_prove_themselves(self):
        for gate in (WRITE_GATE, BASH_GATE):
            cp = subprocess.run([sys.executable, str(gate), "--selftest", self.FIXTURES],
                                capture_output=True, text=True,
                                cwd=str(SCRIPTS.parent), timeout=180)
            self.assertEqual(cp.returncode, 0, cp.stderr or cp.stdout)

    def test_a_gate_that_never_returns_is_a_named_failure_not_a_traceback(self):
        """The fifo fixture's whole assertion is that the gate RETURNS, and it
        was written as a bare `subprocess.run(timeout=30)`: a hang escaped as
        `TimeoutExpired` and killed the selftest with a stack trace instead of
        saying which fixture hung. A harness that fails by crashing cannot tell
        a hang from a bug in itself."""
        from unittest import mock
        write = _load(WRITE_GATE, "tree_owner_write_hang")
        with mock.patch.object(
                write, "__name__", write.__name__), \
             mock.patch("subprocess.run",
                        side_effect=subprocess.TimeoutExpired("gate", 30)):
            out = io.StringIO()
            err = io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = write.run_isolation_selftest(
                    str(WRITE_GATE), str(SCRIPTS.parent / self.FIXTURES),
                    write.WRITE_TOOLS + ("Agent",), "hang-probe")
        self.assertEqual(rc, 1)
        self.assertIn("HUNG", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())

    def test_the_fault_branch_is_inside_the_mechanism_that_proves_the_gates(self):
        """QA cycle 3, F4, and it is RULE #1 territory. The whole fail-closed
        fault branch could be DELETED from both gates and both selftests still
        passed with identical counts (3+2/29 and 16+13/5), and `brain_doctor`
        still reported that both isolation gates prove themselves. No fixture
        covered it, so no count could move, and a count that did not move looks
        exactly like a count that was checked.

        The mechanism this brain gates its own pushes on has to cover the
        protection the change exists for, so there is a pair per gate per
        cause: an unreadable table that must block, a DELETED table that must
        block, and a genuinely fresh install that must ALLOW. The benign leg is
        what makes the violations mean something: without a table that is empty
        for an honest reason, "denies when it cannot read the table" and
        "denies" are the same measurement.
        """
        fdir = SCRIPTS.parent / self.FIXTURES
        for name in ("violation_ptable_corrupt", "violation_ptable_deleted",
                     "benign_ptable_fresh_install",
                     "violation_write_ptable_corrupt", "violation_write_ptable_deleted",
                     "benign_write_ptable_fresh_install"):
            path = fdir / f"{name}.json"
            self.assertTrue(path.is_file(), path)
            setup = json.loads(path.read_text())["_setup"]
            self.assertIn("ptable", setup, name)

    def test_every_qa_cycle_4_branch_has_a_fixture_on_both_gates(self):
        """Same rule, one cycle later. Seven more ways into the same class of
        bug, so seven more branches the doctor's gate-liveness check has to
        actually exercise: a fixture that does not exist is a count that cannot
        move, and a count that cannot move looks exactly like a count that was
        checked.

        The `_setup` key each one needs is asserted, not just the file, because
        a fixture that lost its override still runs, still passes, and stops
        covering the branch it was written for. The benign legs are listed with
        them: each is ONE `_setup` edit away from its violation, which is what
        makes the violation a measurement of the rule rather than of the gate's
        appetite for denying.
        """
        fdir = SCRIPTS.parent / self.FIXTURES
        wanted = {
            "ptable_empty": "ptable",                       # F1a
            "ptable_row_corrupt": "corrupt_rows",           # F1c
            "ptable_lanes_string": "mangle_lanes",          # F6
            "ptable_nested": "ptable_nest",                 # F2
            "ptable_fifo": "ptable_fifo",                   # F5
            "ptable_deleted_journals_gone": "journal_dir",  # F3
            "ptable_deleted_journals_file": "journal_dir",  # F3
            "journal_of_holder_deleted": "drop_journals",   # F4
        }
        pairs = {
            "ptable_empty_no_journals": "journals",             # the F1a control
            "ptable_deleted_no_history": "journal_dir",         # the F3 residual
            "journal_of_idle_row_deleted": "drop_journals",     # the F4 control
        }
        for stem, key in wanted.items():
            for prefix in ("violation_", "violation_write_"):
                path = fdir / f"{prefix}{stem}.json"
                self.assertTrue(path.is_file(), path)
                self.assertIn(key, json.loads(path.read_text())["_setup"], path.name)
        for stem, key in pairs.items():
            for prefix in ("benign_", "benign_write_"):
                path = fdir / f"{prefix}{stem}.json"
                self.assertTrue(path.is_file(), path)
                self.assertIn(key, json.loads(path.read_text())["_setup"], path.name)

        # Cycle 5 adds four branches to the same manifest, for the same
        # reason: `_readable_row`'s null and empty-string lanes were caught by
        # unit tests and by NEITHER selftest, so the doctor's gate-liveness
        # check could not move on them; M1's sweep and M2's damaged directory
        # beside an intact table had no fixture at all.
        cycle5 = {
            "ptable_lanes_null": "mangle_lanes",              # C1-era row shapes
            "ptable_lanes_empty_string": "mangle_lanes",
            "ptable_deleted_journals_swept": "journals",      # M1 state 1
            "journals_gone_table_intact": "journal_dir",      # M2
        }
        for stem, key in cycle5.items():
            for prefix in ("violation_", "violation_write_"):
                path = fdir / f"{prefix}{stem}.json"
                self.assertTrue(path.is_file(), path)
                self.assertIn(key, json.loads(path.read_text())["_setup"], path.name)
        for prefix in ("benign_", "benign_write_"):
            path = fdir / f"{prefix}journals_gone_no_history.json"
            self.assertTrue(path.is_file(), path)          # M2's one-edit control

        # CYCLE 6 adds three, and all three are the SAME defect the manifest
        # above is a list of: a parse that failed selected the permissive
        # branch. They are here because unit anchors alone were what let cycle 4
        # F6 and cycle 5 M1/M2 reach the doctor's gate-liveness check unmeasured
        # - a branch with no fixture is a count that cannot move, and a count
        # that cannot move looks exactly like a count that was checked.
        cycle6 = {
            "torn_journal_of_holder": "torn_journals",           # C-A
            "journals_truncated_to_start": "truncate_journals",  # C-B
            "fault_carrier_kind_flipped": "fault_carrier",       # M-C
        }
        cycle6_pairs = {
            # C-A's control follows F4's shape: the same tear on a row that
            # holds no lane here, so "any journal I cannot read denies the
            # machine" is not the rule that shipped. Its semantic exclusion is
            # `benign_expired`, where the WHOLE journal says the process went
            # quiet and the lane frees on schedule.
            "torn_journal_of_idle_row": "torn_journals",
            "journals_truncated_to_start": "truncate_journals",
            "fault_carrier_kind_flipped": "fault_carrier",
        }
        for stem, key in cycle6.items():
            for prefix in ("violation_", "violation_write_"):
                path = fdir / f"{prefix}{stem}.json"
                self.assertTrue(path.is_file(), path)
                self.assertIn(key, json.loads(path.read_text())["_setup"], path.name)
        for stem, key in cycle6_pairs.items():
            for prefix in ("benign_", "benign_write_"):
                path = fdir / f"{prefix}{stem}.json"
                self.assertTrue(path.is_file(), path)
                self.assertIn(key, json.loads(path.read_text())["_setup"], path.name)
        # C-B's and M-C's benign legs are ONE VALUE away from their violations,
        # which is what makes each violation a measurement of the rule rather
        # than of the gate's appetite for denying: a start-only journal whose
        # `start_ts` is NOW is C3's real registration race, and a `zero-rows`
        # carrier that names a pid IS re-derivable.
        for prefix in ("", "write_"):
            v = json.loads((fdir / f"violation_{prefix}journals_truncated_to_start.json").read_text())
            b = json.loads((fdir / f"benign_{prefix}journals_truncated_to_start.json").read_text())
            self.assertEqual(set(v["_setup"]["truncate_journals"].values()), {"stale"})
            self.assertEqual(set(b["_setup"]["truncate_journals"].values()), {"fresh"})
            self.assertEqual(v["_setup"]["truncate_journals"].keys(),
                             b["_setup"]["truncate_journals"].keys())
            v = json.loads((fdir / f"violation_{prefix}fault_carrier_kind_flipped.json").read_text())
            b = json.loads((fdir / f"benign_{prefix}fault_carrier_kind_flipped.json").read_text())
            self.assertEqual(v["_setup"]["fault_carrier"]["pids"], [])
            self.assertTrue(b["_setup"]["fault_carrier"]["pids"])
            self.assertEqual({k: x for k, x in v["_setup"]["fault_carrier"].items()
                              if k != "pids"},
                             {k: x for k, x in b["_setup"]["fault_carrier"].items()
                              if k != "pids"},
                             "the benign leg must differ by that value alone")

        # M1's control is the fresh install, and what makes it benign is now
        # STATED in the fixture rather than inherited from a gitignored file
        # that happens not to be in the seed.
        for stem in ("ptable_fresh_install", "ptable_empty_no_journals"):
            for prefix in ("benign_", "benign_write_"):
                setup = json.loads((fdir / f"{prefix}{stem}.json").read_text())["_setup"]
                self.assertEqual(setup.get("kernel_history"), "none", stem)

        # F3's pair is the one whose meaning is a SINGLE key, so it is checked
        # as a pair rather than as two files. It also may not live in the seed:
        # `.ptable.lock` matches the repo's `*.lock` ignore, and a fixture whose
        # meaning depends on an untracked file is a gate armed on one machine
        # and disarmed in every clone.
        for prefix in ("", "write_"):
            v = json.loads((fdir / f"violation_{prefix}ptable_deleted_journals_gone.json").read_text())
            b = json.loads((fdir / f"benign_{prefix}ptable_deleted_no_history.json").read_text())
            self.assertEqual(v["_setup"].get("kernel_history"), "seen")
            self.assertNotIn("kernel_history", b["_setup"])
            self.assertEqual({k: x for k, x in v["_setup"].items()
                              if k not in ("kernel_history", "expect_names")},
                             b["_setup"],
                             "the benign leg must differ by that key alone")
        self.assertFalse((fdir / "home" / ".claude" / ".cache" / "kernel"
                          / ".ptable.lock").exists(),
                         "and it must not be seeded, because *.lock is ignored")


if __name__ == "__main__":
    unittest.main()
