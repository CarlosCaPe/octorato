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
