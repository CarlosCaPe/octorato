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
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
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
        stale = time.time() - (kernel_proc.TTL + 300)
        os.utime(kernel_proc.journal_path("agent-a"), (stale, stale))
        rc, out = self.run_gate(
            BASH_GATE, self.bash_payload("agent-b", "git checkout -- pkg/a.py"))
        self.assertFalse(self.denied(out))

    def test_an_exited_holder_holds_nothing(self):
        self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))
        kernel_proc.append("agent-a", {"kind": "exit", "status": "ok"})
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
        os.unlink(kernel_proc.ptable_path())
        rc, out = self.run_gate(WRITE_GATE, self.write_payload("agent-a", self.a_py))
        self.assertFalse(self.denied(out))
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
        kdir = kernel_proc.kernel_dir()
        deep = f"rm -rf {self.tree}/pkg"
        for _ in range(4):
            deep = 'bash -c "' + deep.replace('"', '\\"') + '"'
        for command in (
                # separate verb tables
                f"rsync -a --delete /tmp/x/ {self.tree}/pkg/",
                f"shred -u {self.a_py}",
                f"ln -sf /dev/null {self.a_py}",
                f"perl -pi -e s/a/b/ {self.a_py}",
                # an evaluator: the body is Python, not shell
                f'python3 -c "import shutil; shutil.rmtree(\'{self.tree}/pkg\')"',
                f'python3 -c "open(\'{kdir}/ptable.json\',\'w\').write(\'{{}}\')"',
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


class Selftests(unittest.TestCase):

    def test_both_gates_prove_themselves(self):
        fixtures = "registry/fixtures/ARCHITECTURE.kernel-isolation"
        for gate in (WRITE_GATE, BASH_GATE):
            cp = subprocess.run([sys.executable, str(gate), "--selftest", fixtures],
                                capture_output=True, text=True,
                                cwd=str(SCRIPTS.parent), timeout=180)
            self.assertEqual(cp.returncode, 0, cp.stderr or cp.stdout)


if __name__ == "__main__":
    unittest.main()
