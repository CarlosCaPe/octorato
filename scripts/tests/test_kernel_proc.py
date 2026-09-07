#!/usr/bin/env python3
"""Anchors for the v8 kernel PROCESS + JOURNAL library (scripts/kernel_proc.py).

What is pinned here is what the rest of v8 leans on: the hash chain survives
concurrent writers and detects an unlocked one, a huge payload is truncated
instead of splitting a line, liveness follows the single definition in
v8-kernel.md section 2 (a waiting parent stays live, an expired or exited child
does not), and open mode journals what it let through.

Timing is never asserted (v8-kernel.md section 3): these tests prove the hot
path runs and journals, never how fast.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

import kernel_proc  # noqa: E402


class SandboxHome(unittest.TestCase):
    """Every test runs against a throwaway HOME: kernel_proc resolves its paths
    lazily for exactly this reason, so the real ~/.claude/.cache is never read
    or written by a test."""

    def setUp(self):
        self._saved = (os.environ.get("HOME"), os.environ.get("USERPROFILE"))
        self.home = tempfile.mkdtemp(prefix="kernel-test-")
        os.environ["HOME"] = self.home
        os.environ["USERPROFILE"] = self.home

    def tearDown(self):
        import shutil
        for key, value in zip(("HOME", "USERPROFILE"), self._saved):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.home, ignore_errors=True)

    def touch_journal(self, pid, age_seconds=0.0):
        """Make <pid>'s journal exist with an mtime `age_seconds` in the past."""
        kernel_proc.append(pid, {"kind": "start"})
        when = time.time() - age_seconds
        os.utime(kernel_proc.journal_path(pid), (when, when))


class ChainTest(SandboxHome):
    def test_four_concurrent_writers_keep_one_chain(self):
        """200 lines each from 4 processes, one journal, chain intact.

        The failure this guards is silent: without the flock two appends read
        the same tail, both claim the same seq and prev, and the journal still
        looks fine until a replay tries to verify it.
        """
        pid = "concurrent"
        code = (
            "import os,sys;"
            f"sys.path.insert(0, {str(SCRIPTS)!r});"
            "import kernel_proc;"
            "[kernel_proc.append(sys.argv[1], {'kind':'tool','tool_name':'W'+sys.argv[2],"
            "'tool_use_id':'t%d'%i}) for i in range(200)]"
        )
        env = dict(os.environ)
        env["HOME"] = self.home
        env["USERPROFILE"] = self.home
        procs = [subprocess.Popen([sys.executable, "-c", code, pid, str(n)], env=env)
                 for n in range(4)]
        for p in procs:
            self.assertEqual(p.wait(timeout=120), 0)

        lines = kernel_proc.read_journal(pid)
        self.assertEqual(len(lines), 800, "every append must land exactly once")
        code_, why = kernel_proc.verify_detail(pid)
        self.assertEqual(code_, 0, why)
        self.assertEqual([l["seq"] for l in lines], list(range(800)))

    def test_an_unlocked_writer_breaks_the_chain(self):
        pid = "tampered"
        kernel_proc.append(pid, {"kind": "start"})
        kernel_proc.append(pid, {"kind": "tool", "tool_name": "Read"})
        self.assertEqual(kernel_proc.verify(pid), 0)
        # a writer that skipped the lock and guessed seq/prev
        with open(kernel_proc.journal_path(pid), "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"seq": 2, "ts": time.time(), "start_ts": 1.0,
                                 "pid": pid, "kind": "tool", "prev": "0" * 64}) + "\n")
        code, why = kernel_proc.verify_detail(pid)
        self.assertEqual(code, 1)
        self.assertIn("prev", why)

    def test_an_edited_byte_breaks_the_chain(self):
        pid = "edited"
        for _ in range(3):
            kernel_proc.append(pid, {"kind": "tool", "tool_name": "Bash"})
        raw = Path(kernel_proc.journal_path(pid)).read_bytes()
        Path(kernel_proc.journal_path(pid)).write_bytes(raw.replace(b"Bash", b"Basi", 1))
        self.assertEqual(kernel_proc.verify(pid), 1)

    def test_start_ts_is_copied_forward(self):
        pid = "start-ts"
        kernel_proc.append(pid, {"kind": "start"})
        time.sleep(0.01)
        kernel_proc.append(pid, {"kind": "tool"})
        lines = kernel_proc.read_journal(pid)
        self.assertEqual(lines[0]["start_ts"], lines[1]["start_ts"])
        self.assertGreater(lines[1]["ts"], lines[0]["ts"] - 1)


class TruncationTest(SandboxHome):
    def test_a_huge_payload_is_truncated_not_split(self):
        pid = "huge"
        kernel_proc.append(pid, {"kind": "tool", "tool_name": "Bash",
                                 "cwd": "x" * 20000, "tool_use_id": "toolu_1"})
        raw = Path(kernel_proc.journal_path(pid)).read_bytes()
        self.assertEqual(raw.count(b"\n"), 1, "one record is always one line")
        self.assertLessEqual(len(raw), kernel_proc.MAX_LINE)
        rec = json.loads(raw)
        self.assertTrue(rec["trunc"])
        for key in ("seq", "ts", "start_ts", "pid", "kind", "prev"):
            self.assertIn(key, rec, "core identity fields survive truncation")
        self.assertEqual(kernel_proc.verify(pid), 0)

    def test_many_huge_fields_still_fit(self):
        pid = "huge-many"
        record = {"kind": "tool"}
        for i in range(12):
            record[f"f{i}"] = "y" * 5000
        kernel_proc.append(pid, record)
        raw = Path(kernel_proc.journal_path(pid)).read_bytes().rstrip(b"\n")
        self.assertLessEqual(len(raw), kernel_proc.MAX_LINE - 1)
        self.assertTrue(json.loads(raw)["trunc"])


class LivenessTest(SandboxHome):
    def table(self):
        return kernel_proc.read_ptable()

    def test_parent_waiting_on_a_long_child_reads_live(self):
        kernel_proc.register("parent", {"kind": "main"})
        kernel_proc.register("child", {"kind": "subagent", "ppid": "parent"})
        # the parent has not written in 20 minutes; the child just did
        old = time.time() - 1200
        os.utime(kernel_proc.journal_path("parent"), (old, old))
        table = self.table()
        self.assertTrue(kernel_proc.is_live("parent", table),
                        "a parent blocked on a child is not dead")
        self.assertTrue(kernel_proc.is_live("child", table))

    def test_an_expired_child_is_not_live(self):
        kernel_proc.register("parent", {"kind": "main"})
        kernel_proc.register("child", {"kind": "subagent", "ppid": "parent"})
        old = time.time() - (kernel_proc.TTL + 60)
        os.utime(kernel_proc.journal_path("child"), (old, old))
        table = self.table()
        self.assertFalse(kernel_proc.is_live("child", table),
                         "a hung child releases what it holds after the TTL")
        self.assertTrue(kernel_proc.is_live("parent", table))

    def test_a_child_with_an_exit_line_is_not_live(self):
        kernel_proc.register("parent", {"kind": "main"})
        kernel_proc.register("child", {"kind": "subagent", "ppid": "parent"})
        kernel_proc.append("child", {"kind": "exit", "status": "ok"})
        self.assertFalse(kernel_proc.is_live("child", self.table()))

    def test_a_child_of_a_dead_parent_is_not_live(self):
        kernel_proc.register("parent", {"kind": "main"})
        kernel_proc.register("child", {"kind": "subagent", "ppid": "parent"})
        old = time.time() - (kernel_proc.TTL + 60)
        for pid in ("parent", "child"):
            os.utime(kernel_proc.journal_path(pid), (old, old))
        self.assertFalse(kernel_proc.is_live("child", self.table()))
        self.assertFalse(kernel_proc.is_live("parent", self.table()))

    def test_a_future_mtime_is_skew_not_liveness(self):
        kernel_proc.register("skewed", {"kind": "main"})
        ahead = time.time() + kernel_proc.FUTURE_SKEW + 600
        os.utime(kernel_proc.journal_path("skewed"), (ahead, ahead))
        self.assertFalse(kernel_proc.is_live("skewed", self.table()))

    def test_an_unknown_pid_is_read_as_a_main_process(self):
        self.touch_journal("stranger", age_seconds=5)
        self.assertTrue(kernel_proc.is_live("stranger", self.table()))


class PtableTest(SandboxHome):
    def test_register_links_parent_and_child_and_is_idempotent(self):
        kernel_proc.register("p", {"kind": "main", "worktree": "/w"})
        kernel_proc.register("c", {"kind": "subagent", "ppid": "p",
                                   "type": "Reality Checker", "worktree": "/w"})
        procs = kernel_proc.read_ptable()["processes"]
        self.assertEqual(procs["c"]["ppid"], "p")
        self.assertEqual(procs["c"]["type"], "Reality Checker")
        kernel_proc.register("c", {"kind": "subagent", "ppid": "p"})
        self.assertEqual(len(kernel_proc.read_ptable()["processes"]), 2)

    def test_prune_drops_only_long_dead_rows(self):
        kernel_proc.register("fresh", {"kind": "main"})
        kernel_proc.register("ancient", {"kind": "main"})
        old = time.time() - (kernel_proc.PRUNE_AFTER + 3600)
        os.utime(kernel_proc.journal_path("ancient"), (old, old))
        table = kernel_proc.read_ptable()
        self.assertEqual(kernel_proc.prune(table), 1)
        self.assertIn("fresh", table["processes"])
        self.assertNotIn("ancient", table["processes"])

    def test_a_crafted_pid_cannot_escape_the_journal_directory(self):
        pid = "../../../../etc/passwd"
        kernel_proc.append(pid, {"kind": "tool"})
        written = os.path.dirname(os.path.abspath(kernel_proc.journal_path(pid)))
        self.assertEqual(written, os.path.abspath(kernel_proc.journal_dir()))


class HotPathGateTest(SandboxHome):
    """The gate as the harness runs it: stdin payload, stdout verdict, exit 0."""

    def run_gate(self, payload, env_extra=None):
        env = dict(os.environ)
        env["HOME"] = self.home
        env["USERPROFILE"] = self.home
        env.pop("OCTO_KERNEL_OPEN", None)
        env.update(env_extra or {})
        cp = subprocess.run([sys.executable, str(SCRIPTS / "g__pretool__kernel.py")],
                            input=json.dumps(payload), capture_output=True,
                            text=True, env=env, cwd=self.home, timeout=60)
        return cp

    def payload(self, **kw):
        base = {"session_id": "s1", "tool_name": "Bash", "tool_use_id": "toolu_a",
                "tool_input": {"command": "ls"}, "cwd": self.home}
        base.update(kw)
        return base

    def test_a_call_without_a_start_line_is_allowed_and_journaled(self):
        cp = self.run_gate(self.payload())
        self.assertEqual(cp.returncode, 0)
        self.assertEqual(cp.stdout.strip(), "", "a racing register hook is not a violation")
        lines = kernel_proc.read_journal("s1")
        self.assertEqual([l["kind"] for l in lines], ["tool"])
        self.assertEqual(len(lines[0]["input_sha256"]), 64)

    def test_the_agent_id_wins_over_the_session_id(self):
        self.run_gate(self.payload(agent_id="a1"))
        self.assertEqual(len(kernel_proc.read_journal("a1")), 1)
        self.assertEqual(kernel_proc.read_journal("s1"), [])

    def test_an_unwritable_journal_denies_with_the_unlock(self):
        os.makedirs(kernel_proc.journal_path("s1"), exist_ok=True)  # a dir, not a file
        cp = self.run_gate(self.payload())
        self.assertEqual(cp.returncode, 0, "a hook denies in JSON, it does not crash")
        out = json.loads(cp.stdout)
        hso = out["hookSpecificOutput"]
        self.assertEqual(hso["permissionDecision"], "deny")
        self.assertIn("OCTO_KERNEL_OPEN=1", hso["permissionDecisionReason"])

    def test_open_mode_allows_and_backfills_an_open_line(self):
        os.makedirs(kernel_proc.journal_path("s1"), exist_ok=True)
        for _ in range(3):
            cp = self.run_gate(self.payload(), {"OCTO_KERNEL_OPEN": "1"})
            self.assertEqual(cp.stdout.strip(), "", "open mode never denies")
        with open(kernel_proc.pending_path(), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["s1"]["count"], 3)

        os.rmdir(kernel_proc.journal_path("s1"))  # the operator repaired the path
        cp = self.run_gate(self.payload(), {"OCTO_KERNEL_OPEN": "1"})
        self.assertEqual(cp.stdout.strip(), "")
        lines = kernel_proc.read_journal("s1")
        self.assertEqual([l["kind"] for l in lines], ["open", "tool"])
        self.assertEqual(lines[0]["count"], 3, "the doctor can count what ran unjournaled")
        self.assertFalse(os.path.exists(kernel_proc.pending_path()))
        self.assertEqual(kernel_proc.verify("s1"), 0)

    def test_open_mode_is_read_from_the_env_never_the_payload(self):
        os.makedirs(kernel_proc.journal_path("s1"), exist_ok=True)
        cp = self.run_gate(self.payload(OCTO_KERNEL_OPEN="1", octo_kernel_open=True))
        self.assertIn("deny", cp.stdout, "a payload field is not the operator's shell")

    def test_a_payload_without_a_pid_is_ignored(self):
        cp = self.run_gate({"tool_name": "Bash", "tool_input": {}})
        self.assertEqual(cp.returncode, 0)
        self.assertEqual(cp.stdout.strip(), "")

    def test_garbage_on_stdin_never_blocks(self):
        env = dict(os.environ)
        env["HOME"] = self.home
        cp = subprocess.run([sys.executable, str(SCRIPTS / "g__pretool__kernel.py")],
                            input="not json", capture_output=True, text=True,
                            env=env, cwd=self.home, timeout=60)
        self.assertEqual(cp.returncode, 0)
        self.assertEqual(cp.stdout.strip(), "")


class SchemaTest(SandboxHome):
    def test_every_emitted_line_validates_against_the_schema(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed")
        schema = json.loads((ROOT / "schemas" / "kernel-journal.schema.json")
                            .read_text(encoding="utf-8"))
        kernel_proc.register("p", {"kind": "main", "worktree": "/w", "cwd": "/w"})
        kernel_proc.register("c", {"kind": "subagent", "ppid": "p", "type": "QA",
                                   "worktree": "/w"})
        kernel_proc.append("c", {"kind": "tool", "tool_name": "Bash",
                                 "tool_use_id": "toolu_x",
                                 "input_sha256": kernel_proc.input_hash({"a": 1})})
        kernel_proc.append("c", {"kind": "open", "count": 2})
        kernel_proc.append("c", {"kind": "exit", "status": "ok", "ok": True})
        for pid in ("p", "c"):
            for line in kernel_proc.read_journal(pid):
                jsonschema.validate(line, schema)

    def test_the_schema_declares_every_kind_the_library_writes(self):
        schema = json.loads((ROOT / "schemas" / "kernel-journal.schema.json")
                            .read_text(encoding="utf-8"))
        self.assertEqual(sorted(schema["properties"]["kind"]["enum"]),
                         sorted(kernel_proc.KINDS))


class SelftestTest(unittest.TestCase):
    """The registered liveness proofs are themselves under test: a selftest that
    silently stops proving anything is how a gate dies quietly."""

    def _run(self, script, fixture):
        cp = subprocess.run([sys.executable, str(SCRIPTS / script), "--selftest",
                             str(ROOT / "registry" / "fixtures" / fixture)],
                            capture_output=True, text=True, cwd=str(ROOT), timeout=180)
        return cp

    def test_process_selftest_passes(self):
        cp = self._run("r__subagent-start__proc-register.py", "ARCHITECTURE.kernel-process")
        self.assertEqual(cp.returncode, 0, cp.stderr)

    def test_journal_gate_selftest_passes(self):
        cp = self._run("g__pretool__kernel.py", "FLOW.kernel-journal")
        self.assertEqual(cp.returncode, 0, cp.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
