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
        """Backdate BOTH halves of a journal's liveness: its mtime AND the `ts`
        of its last chained record. `os.utime` alone is the cycle 5 C4 ATTACK,
        not an expiry, and `test_c4_*` asserts it stays denied."""
        path = kernel_proc.journal_path(pid)
        when = time.time() - age_seconds
        with open(path, encoding="utf-8") as fh:
            lines = [ln for ln in fh.read().split("\n") if ln.strip()]
        if lines:
            rec = json.loads(lines[-1])
            rec["ts"] = when
            lines[-1] = json.dumps(rec, separators=(",", ":"))
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
        os.utime(path, (when, when))

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

    The docstring now lists exactly which verbs are denied at the kernel
    directory and says the interpreter path is open. A list in prose drifts, so
    it is measured here: every verb it names as denied must deny, and the two
    it names as open must still be allowed. When that second half stops being
    true, the honest move is to update the docstring, not this test.
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

    def test_the_two_open_paths_are_still_open_and_still_labelled(self):
        """Not a wish: this is the residual, and the PR says so instead of
        closing it here. Expanding the gate's verb detection to cover an
        interpreter body is a change with its own false-positive risk."""
        tbl = kernel_proc.ptable_path()
        self.assertEqual(self.decide(f"ln -sf /dev/null {tbl}"), "allow")
        self.assertEqual(
            self.decide(f'python3 -c "import os; os.unlink(\'{tbl}\')"'), "allow")
        doc = kernel_proc.recovery.__doc__
        self.assertIn("INTERPRETER PATH IS OPEN", doc)
        self.assertIn("ln -sf", doc)


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
