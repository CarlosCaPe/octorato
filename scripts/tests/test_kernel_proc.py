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


class TornWriteTest(SandboxHome):
    """QA cycle 1, D2. `os.write` may write fewer bytes than asked, and a killed
    process leaves a file that does not end on a newline. Both used to glue the
    next record onto the fragment: one unreadable line, a reused seq, a chain
    that never verified again."""

    def test_a_torn_fragment_is_terminated_and_named_by_index(self):
        pid = "torn"
        kernel_proc.append(pid, {"kind": "start"})
        path = Path(kernel_proc.journal_path(pid))
        path.write_bytes(path.read_bytes() + b'{"seq":1,"ts":1.0,"start_')  # half a line
        kernel_proc.append(pid, {"kind": "tool", "tool_name": "Bash"})

        raws = [r for r in path.read_bytes().split(b"\n") if r]
        self.assertEqual(len(raws), 3, "the fragment became its own line, not a prefix")
        self.assertEqual(json.loads(raws[2])["seq"], 2, "seq is not reused")
        code, why = kernel_proc.verify_detail(pid)
        self.assertEqual(code, 1)
        self.assertIn("line 1 does not parse", why)
        self.assertIn("1 break(s)", why, "damage is one named line, not everything after it")
        # the chain continues from the torn line's bytes
        import hashlib as _h
        self.assertEqual(json.loads(raws[2])["prev"], _h.sha256(raws[1]).hexdigest())

    def test_a_complete_line_without_a_newline_recovers_clean(self):
        pid = "unterminated"
        kernel_proc.append(pid, {"kind": "start"})
        path = Path(kernel_proc.journal_path(pid))
        path.write_bytes(path.read_bytes().rstrip(b"\n"))  # the newline never landed
        kernel_proc.append(pid, {"kind": "tool"})
        self.assertEqual(kernel_proc.verify(pid), 0, "no data was lost, so nothing is broken")
        self.assertEqual([l["seq"] for l in kernel_proc.read_journal(pid)], [0, 1])

    def test_a_short_write_is_retried_until_every_byte_lands(self):
        import unittest.mock as mock
        real = os.write
        state = {"split": True}

        def half(fd, data):
            if state["split"] and len(data) > 4:
                state["split"] = False
                return real(fd, data[:4])   # the kernel accepted only 4 bytes
            return real(fd, data)

        pid = "short"
        with mock.patch("os.write", side_effect=half):
            kernel_proc.append(pid, {"kind": "start"})
        raw = Path(kernel_proc.journal_path(pid)).read_bytes()
        self.assertTrue(raw.endswith(b"\n"), "the loop finished the line")
        self.assertEqual(kernel_proc.verify(pid), 0)

    def test_a_write_that_makes_no_progress_raises(self):
        import unittest.mock as mock
        with mock.patch("os.write", return_value=0):
            with self.assertRaises(OSError):
                kernel_proc.append("stuck", {"kind": "start"})


class RegisterRaceTest(SandboxHome):
    """QA cycle 1, D1. Ten SessionStart hooks fire at once; every one of them
    must keep its row."""

    def test_ten_parallel_registers_keep_ten_rows(self):
        code = (
            "import sys;"
            f"sys.path.insert(0, {str(SCRIPTS)!r});"
            "import kernel_proc;"
            "kernel_proc.register(sys.argv[1], {'kind':'main','worktree':'/w'})"
        )
        env = dict(os.environ)
        env["HOME"] = self.home
        env["USERPROFILE"] = self.home
        procs = [subprocess.Popen([sys.executable, "-c", code, f"p{n}"], env=env)
                 for n in range(10)]
        for p in procs:
            self.assertEqual(p.wait(timeout=120), 0)
        rows = kernel_proc.read_ptable()["processes"]
        self.assertEqual(sorted(rows), [f"p{n}" for n in range(10)])

    def test_the_journal_exists_before_the_row_is_published(self):
        seen = {}
        real_write = kernel_proc._write_ptable

        def spy(data):
            seen["journal_first"] = os.path.exists(kernel_proc.journal_path("order"))
            return real_write(data)

        kernel_proc._write_ptable = spy
        try:
            kernel_proc.register("order", {"kind": "main"})
        finally:
            kernel_proc._write_ptable = real_write
        self.assertTrue(seen["journal_first"],
                        "a row published before its journal can be pruned by a sibling")

    def test_prune_keeps_a_young_row_whose_journal_is_missing(self):
        kernel_proc.register("young", {"kind": "main"})
        os.unlink(kernel_proc.journal_path("young"))
        table = kernel_proc.read_ptable()
        self.assertEqual(kernel_proc.prune(table), 0)
        self.assertIn("young", table["processes"])

        table["processes"]["young"]["registered_ts"] = time.time() - kernel_proc.TTL - 60
        self.assertEqual(kernel_proc.prune(table), 1, "past the TTL it is gone for good")
        self.assertNotIn("young", table["processes"])


class CorruptRowTest(SandboxHome):
    """QA cycle 2: one ptable value that is not an object bricked the kernel.

    Measured with `"junk": "not-a-row"` in the table: `octo ps` and `octo top`
    exited 1, `brain_doctor` reported two kernel checks crashed, and both
    register hooks exited 0 having published NOTHING, because `prune()` raised
    inside the ptable lock. A reflex that reports success while writing nothing
    is the worst of those four, so the shape is decided once, at the read, and
    the drop is REPORTED rather than silent.
    """

    def inject(self, *bad):
        """Put `bad` values that are not objects into the table ON DISK.

        Written the way it happens: a healthy table, then a value replaced under
        it (a hand edit, a half-migrated file, a foreign writer). The bad rows
        are NAMED to sort before the healthy one, and the name is the only thing
        that decides it: `_write_ptable` writes with sort_keys, so insertion
        order does not survive the first writer. It matters because `lane_owner`
        returns on its first hit, so a bad row that sorts last is never reached
        and the test would pass for the wrong reason.

        Separate from `corrupt` because a test that wants the corruption to be
        on disk WHILE a reader runs has to set the world up first and inject
        last: any kernel writer in between republishes the table without it
        (QA cycle 3, F2).
        """
        with open(kernel_proc.ptable_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        procs = {f"bad{i}": value for i, value in enumerate(bad or ("not-a-row",))}
        procs.update(data["processes"])
        data["processes"] = procs
        with open(kernel_proc.ptable_path(), "w", encoding="utf-8") as fh:
            json.dump(data, fh)

    def corrupt(self, *bad):
        """One healthy row, then `bad` values that are not objects, on disk."""
        kernel_proc.register("good", {"kind": "main", "type": "main", "worktree": "/w"})
        self.inject(*bad)

    def raw(self) -> bytes:
        """The ptable file's exact bytes. A rewrite that happened to keep the
        same pids would still be a write, so the comparison is on bytes."""
        with open(kernel_proc.ptable_path(), "rb") as fh:
            return fh.read()

    def rows_on_disk(self) -> list:
        """The pid keys the FILE carries right now, parsed without the seam.

        The assertions about what is still on disk have to bypass
        `read_ptable_detail`: reading the table through the thing under test is
        how a test stops being able to see the state it exists to pin.
        """
        with open(kernel_proc.ptable_path(), encoding="utf-8") as fh:
            return sorted(json.load(fh)["processes"])

    def register_hook(self, script, payload):
        env = dict(os.environ)
        env["HOME"] = self.home
        env["USERPROFILE"] = self.home
        return subprocess.run([sys.executable, str(SCRIPTS / script)],
                              input=json.dumps(payload), capture_output=True,
                              text=True, env=env, cwd=self.home, timeout=60)

    def test_a_value_that_is_not_an_object_is_dropped_and_named(self):
        """Dropped, not raised: one unreadable row must not be able to take the
        whole kernel down. Named, not silent: a repair nobody can see is its own
        failure mode."""
        self.corrupt("not-a-row", 7, None, ["lanes"])
        table, dropped, _fault = kernel_proc.read_ptable_detail()
        self.assertEqual(sorted(dropped), ["bad0", "bad1", "bad2", "bad3"])
        self.assertEqual(sorted(table["processes"]), ["good"])
        self.assertEqual(kernel_proc.read_ptable()["processes"], table["processes"])

    def steady_state(self, pid="ancient"):
        """A healthy row plus a row whose journal has been gone longer than the
        grace window: the NORMAL steady state of a machine that has run for a
        while, and the thing that turns `prune_locked` from a no-op into a
        writer. The bad row goes in LAST, because everything above it is a
        writer and a writer republishes the table without it.
        """
        kernel_proc.register("good", {"kind": "main", "type": "main", "worktree": "/w"})
        kernel_proc.register(pid, {"kind": "main"})
        os.unlink(kernel_proc.journal_path(pid))
        table = kernel_proc.read_ptable()
        table["processes"][pid]["registered_ts"] = time.time() - (kernel_proc.TTL + 60)
        kernel_proc._write_ptable(table)
        self.inject()

    def test_the_pure_read_reports_the_drop_and_never_writes_it(self):
        """`read_ptable_detail` repairs in MEMORY only, and this now proves it
        against a table that a writer would have rewritten.

        The claim used to be checked with `prune_locked` on a fixture that had
        nothing prunable, so prune returned 0 and never wrote: the assertion
        held for a reason that had nothing to do with the read (QA cycle 3, F3).
        Here the table carries a prunable row, so a writer handed this same
        fixture WOULD rewrite the file, and the test proves that in its last two
        lines instead of asserting it in prose (QA cycle 4, F6: with the reason
        only stated, making the row non-prunable left the test passing, because
        nothing in it ever called a pruner). The bytes are compared, not the
        parse: a rewrite that happened to keep the same pids would still be a
        write.
        """
        self.steady_state()
        before = self.raw()
        table, dropped, fault = kernel_proc.read_ptable_detail()
        self.assertEqual(dropped, ["bad0"])
        self.assertEqual(fault, "")
        self.assertNotIn("bad0", table["processes"])
        self.assertEqual(self.raw(), before,
                         "the read repaired the table in memory and only there")
        self.assertEqual(kernel_proc.quarantines(), [],
                         "and it left no copy either: a read writes NOTHING")

        self.assertEqual(kernel_proc.prune_locked(), 1,
                         "the fixture IS one a writer rewrites; if this ever "
                         "returns 0 the assertions above prove nothing")
        self.assertNotEqual(self.raw(), before,
                            "so 'the file is untouched' was a fact about the "
                            "read, not about the fixture")

    def test_a_writer_that_erases_the_bad_row_keeps_a_copy_of_what_it_erased(self):
        """QA cycle 3, F3. `octo ps` prunes on read, prune is a writer, and on a
        table carrying one old dead row (the steady state) it republished the
        file without the corrupt row. The drop was then invisible: the read
        afterwards measured `dropped == []`, the footers had nothing to name and
        the doctor had nothing to report. The corruption event left zero trace.

        The trace is the preserved file, taken at the moment the original is
        replaced. It carries the reason and the raw bytes, so the rows a repair
        could not carry forward are readable rather than gone, and
        `brain_doctor` can escalate on how OFTEN this happens instead of on
        whether one bad row happens to still be sitting in the file.
        """
        self.steady_state()
        original = self.raw().decode("utf-8")
        self.assertEqual(kernel_proc.prune_locked(), 1, "prune wrote the table")
        self.assertNotIn("bad0", self.rows_on_disk())

        kept = kernel_proc.quarantines()
        self.assertEqual(len(kept), 1, "one repair, one copy")
        with open(kept[0][1], encoding="utf-8") as fh:
            rec = json.load(fh)
        self.assertEqual(rec["ptable"], original, "the copy is what was overwritten")
        self.assertIn("bad0", rec["reason"], "and it names what could not be read")

    def test_a_read_that_writes_nothing_leaves_no_copy(self):
        """The other half of the same rule: the copy is taken by `_publish`, at
        the write, so a caller that reads a corrupt table and decides not to
        write leaves the evidence exactly where it was and adds no file."""
        self.corrupt()
        kernel_proc.read_ptable_detail()
        self.assertEqual(kernel_proc.prune_locked(), 0, "nothing was prunable")
        self.assertIn("bad0", self.rows_on_disk())
        self.assertEqual(kernel_proc.quarantines(), [])

    def test_prune_survives_a_table_a_caller_assembled_by_hand(self):
        """`prune` mutates under the ptable lock, so a raise there leaves the
        lock holder with an unwritten table and its hook exiting 0 having
        published nothing. It drops the row instead: a value that is not an
        object is not a process."""
        table = {"version": 1, "processes": {"junk": "not-a-row",
                                             "gone": {"registered_ts": 0}}}
        self.assertEqual(kernel_proc.prune(table), 2)
        self.assertEqual(table["processes"], {})

    def test_both_register_hooks_still_publish_their_row(self):
        """The silent half of the defect. Exit 0 is not the assertion; the row
        on disk is.

        The table is corrupted AGAIN between the two hooks, and that is the
        whole difference (QA cycle 3, the second test that passed for the wrong
        reason). `register` republishes what it read, so the first hook wiped
        the bad row and the SUBAGENT hook, the one the method name promises,
        ran against a perfectly clean table: measured `['bad0', 'good']` before
        the first hook and `['good', 'newsess']` before the second. Only one of
        the two was ever tested.
        """
        self.corrupt()
        self.assertIn("bad0", self.rows_on_disk(), "hook 1 faces the bad row")
        cp = self.register_hook("r__session__proc-register.py",
                                {"session_id": "newsess", "source": "startup",
                                 "cwd": self.home})
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertIn("newsess", self.rows_on_disk())

        self.inject()
        self.assertIn("bad0", self.rows_on_disk(), "and now hook 2 faces one too")
        cp = self.register_hook("r__subagent-start__proc-register.py",
                                {"agent_id": "newkid", "session_id": "newsess",
                                 "agent_type": "Reality Checker", "cwd": self.home})
        self.assertEqual(cp.returncode, 0, cp.stderr)
        rows = kernel_proc.read_ptable()["processes"]
        self.assertIn("newsess", rows)
        self.assertIn("newkid", rows)
        self.assertEqual(rows["newkid"]["ppid"], "newsess")
        self.assertNotIn("bad0", self.rows_on_disk())
        self.assertEqual(len(kernel_proc.quarantines()), 2,
                         "one preserved copy per repair, one per hook")

    def test_a_writer_republishes_the_table_without_the_bad_row(self):
        """The drop is not only in memory: every locked writer reads through the
        seam, so the row leaves the FILE on the next write, once."""
        self.corrupt()
        kernel_proc.register("newsess", {"kind": "main", "type": "main"})
        with open(kernel_proc.ptable_path(), encoding="utf-8") as fh:
            procs = json.load(fh)["processes"]
        self.assertNotIn("bad0", procs)
        self.assertEqual(sorted(procs), ["good", "newsess"])

    def test_the_doctor_reports_the_drop_instead_of_crashing(self):
        """`brain_doctor` said `kernel-process-live check crashed: 'str' object
        has no attribute 'get'`. A health check that crashes on the state it
        exists to report is the one that has to be loud about it, so this is a
        WARN naming the row, never a PASS that hides it."""
        import importlib.util
        self.corrupt()
        spec = importlib.util.spec_from_file_location(
            "brain_doctor_ro", str(SCRIPTS / "brain_doctor.py"))
        bd = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bd)
        result = bd.check_kernel_process_live(False)
        self.assertEqual(result.status, bd.WARN, result.message)
        self.assertIn("unreadable ptable row", result.message)
        self.assertIn("bad0", result.message)

    def test_liveness_and_the_lane_lookup_survive_the_bad_row(self):
        """The two functions on the hot path. Both walk every row in the table,
        so both used to raise on the first bad one they reached.

        ORDER IS THE TEST (QA cycle 3, F2). The first version of this corrupted
        the table and then called `claim_lane`, which is a WRITER: it
        republished the table without the bad row, so `is_live` and `lane_owner`
        both ran against a clean file and neither assertion ever saw the state
        named in the method. Measured: `bad0` on disk before the claim, gone
        after it. The world is built first and the corruption injected last, and
        the file is checked on both sides of the two calls, so the bad row is
        provably still there while they run and neither of them is a writer.
        """
        self.corrupt()
        self.touch_journal("good")
        kernel_proc.claim_lane("good", os.path.join(self.home, "pkg"))
        self.inject()                       # the writer is done; corrupt it now
        self.assertIn("bad0", self.rows_on_disk(), "the bad row must be on disk HERE")

        self.assertTrue(kernel_proc.is_live("good"))
        self.assertIn("bad0", self.rows_on_disk(), "is_live is a reader")
        owner, row = kernel_proc.lane_owner(os.path.join(self.home, "pkg", "a.py"),
                                            ignore="other")
        self.assertEqual(owner, "good")
        self.assertEqual(row.get("type"), "main")
        self.assertIn("bad0", self.rows_on_disk(), "lane_owner is a reader")

    def test_a_row_that_is_not_an_object_is_never_a_trace(self):
        """`has_trace`'s row guard, pinned where it can actually be reached.

        QA cycle 4, F5 measured that this guard cannot fire through the live
        path any more: `read_ptable` drops the bad value before `has_trace` sees
        it, so the lookup returns `None` whether the predicate is `isinstance`
        or `is not None`, and the docstring claiming it rejects that row was a
        claim the mechanism no longer supported. Both halves are asserted here.

        The guard is kept as defence in depth (it is the same predicate the read
        applies, at the point of use), so the table is handed in directly, the
        one way a caller could still reach it: a future reader assembling a
        table without going through the seam. `pid in procs` and `is not None`
        both say True for this row, and an ENDING would then create a process.
        """
        from unittest import mock
        self.corrupt()
        self.assertNotIn("bad0", kernel_proc.read_ptable()["processes"],
                         "unreachable through the read: the row is gone first")
        self.assertFalse(kernel_proc.has_trace("bad0"))

        table = {"version": 1, "processes": {"ghost": "not-a-row"}}
        with mock.patch.object(kernel_proc, "read_ptable", return_value=table):
            self.assertIn("ghost", table["processes"], "membership says yes")
            self.assertFalse(kernel_proc.has_trace("ghost"),
                             "a value that is not an object is not a process")
            kernel_proc.append("real", {"kind": "tool", "tool_name": "Bash"})
            self.assertTrue(kernel_proc.has_trace("real"),
                            "and a real trace is still a trace")


class TableLevelFaultTest(SandboxHome):
    """QA cycle 3, F1. A row that is not an object costs one named row. A
    `processes` that is not an object costs EVERY row, unnamed, and used to be
    the quietest state the kernel had: `sane_table` returned an empty table with
    `dropped == []`, so nothing anywhere reported it and `octo ps` announced
    that the kernel had registered nothing on this machine, which is the
    opposite of the truth.

    It is not reachable from the kernel's own writers (`_write_ptable` publishes
    a complete file with `os.replace`), and that is exactly why it has to be
    loud: a table shaped like this means a writer that is not the kernel touched
    the file.
    """

    def list_shaped(self):
        """The same rows, as an array. Nothing is missing from the FILE; what is
        missing is the kernel's ability to read it."""
        kernel_proc.register("owner", {"kind": "main", "type": "main", "worktree": "/w"})
        kernel_proc.register("other", {"kind": "main", "type": "main", "worktree": "/w"})
        with open(kernel_proc.ptable_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        data["processes"] = list(data["processes"].values())
        with open(kernel_proc.ptable_path(), "w", encoding="utf-8") as fh:
            json.dump(data, fh)

    def test_a_table_level_discard_is_reported_not_silent(self):
        """As loud as a row-level one, and louder about what it cannot say: the
        pids are unrecoverable, so the fault names the SHAPE and the count of
        values that went with it."""
        self.list_shaped()
        table, dropped, fault = kernel_proc.read_ptable_detail()
        self.assertEqual(table["processes"], {})
        self.assertEqual(dropped, [], "no pid survives a value that is not an object")
        self.assertIn("array of 2 value(s)", fault)
        self.assertIn("processes", fault)

    def test_zero_rows_from_a_file_that_exists_is_never_a_fresh_install(self):
        """There is exactly ONE honest empty table: the file is not there. Every
        other way of yielding zero rows is a machine whose table was readable to
        somebody and is not readable to us, and calling that a fresh install is
        what let a total loss pass for a new laptop."""
        self.assertFalse(os.path.exists(kernel_proc.ptable_path()))
        self.assertEqual(kernel_proc.read_ptable_detail(), ({"version": 1, "processes": {}}, [], ""))

        os.makedirs(kernel_proc.kernel_dir(), exist_ok=True)
        for content, expected in (("", "not valid JSON"),
                                  ("[]", "top level is a array"),
                                  ('{"version": 1}', "no `processes` key"),
                                  ('{"processes": "gone"}', "`processes` is a string"),
                                  ('{"processes": null}', "`processes` is a null")):
            with open(kernel_proc.ptable_path(), "w", encoding="utf-8") as fh:
                fh.write(content)
            table, dropped, fault = kernel_proc.read_ptable_detail()
            self.assertEqual(table["processes"], {}, content)
            self.assertTrue(fault, f"{content!r} yielded zero rows and no fault")
            self.assertIn(expected, fault, content)

        # "a file this process cannot open" is on that list and used to be the
        # one leg this test named and never exercised (QA cycle 4, F7). A
        # directory where the file should be is the cheapest real OSError that
        # does not depend on running as a non-root user.
        os.unlink(kernel_proc.ptable_path())
        os.makedirs(kernel_proc.ptable_path())
        table, dropped, fault = kernel_proc.read_ptable_detail()
        self.assertEqual(table["processes"], {})
        self.assertIn("could not be read", fault)
        self.assertEqual(dropped, [])

    def test_a_lane_claim_refuses_a_table_it_could_not_read(self):
        """The write half of the same loss. `claim_lane` republishes what it
        read, so on a faulted table it used to publish a ONE-ROW table: every
        other process's lanes gone, and the claimant holding the path it had
        just been told nobody owned. A claim is the assertion `nobody else holds
        this`, and a table we could not read is no basis for it."""
        self.list_shaped()
        with open(kernel_proc.ptable_path(), "rb") as fh:
            before = fh.read()
        self.assertFalse(kernel_proc.claim_lane("intruder", os.path.join(self.home, "a.py")))
        with open(kernel_proc.ptable_path(), "rb") as fh:
            self.assertEqual(fh.read(), before, "a refused claim writes nothing at all")

    def test_register_publishes_anyway_and_keeps_what_it_overwrites(self):
        """The one writer that MUST write through it. A register hook exiting 0
        with no row on disk is the silent failure the whole seam exists to stop,
        so it publishes; the rows it cannot carry forward are preserved beside
        the file rather than lost."""
        self.list_shaped()
        with open(kernel_proc.ptable_path(), encoding="utf-8") as fh:
            original = fh.read()
        kernel_proc.register("newsess", {"kind": "main", "type": "main"})
        self.assertEqual(kernel_proc.read_ptable()["processes"].get("newsess", {}).get("pid"),
                         "newsess")
        kept = kernel_proc.quarantines()
        self.assertEqual(len(kept), 1)
        with open(kept[0][1], encoding="utf-8") as fh:
            rec = json.load(fh)
        self.assertEqual(rec["ptable"], original, "the two lost rows are still readable")
        self.assertIn("array of 2 value(s)", rec["reason"])

    def test_the_doctor_fails_on_a_fault_where_it_only_warns_on_a_row(self):
        """The severity gap is the finding. A dropped row leaves a working,
        self-repairing kernel (WARN). A fault leaves every reader blind and both
        isolation gates denying every hooked write, which is not a kernel that
        is working."""
        import importlib.util
        self.list_shaped()
        spec = importlib.util.spec_from_file_location(
            "brain_doctor_fault", str(SCRIPTS / "brain_doctor.py"))
        bd = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bd)
        result = bd.check_kernel_process_live(False)
        self.assertEqual(result.status, bd.FAIL, result.message)
        self.assertIn("process table is unreadable", result.message)
        self.assertIn("array of 2 value(s)", result.message)
        self.assertIn("rm ", result.hint, "and it says how to get out of it")

    def test_the_fault_outlives_the_register_that_publishes_over_it(self):
        """QA cycle 4, F1, the serious one. The protection used to last minutes.

        `register` publishes even on a faulted table, which is right: a hook
        exiting 0 with no row on disk is the silent failure the seam exists to
        stop. What was wrong is the BASE it published: `fresh_table()` plus its
        own row, so the fault disappeared with the write, the table read valid
        again, and the gates went straight back to allowing. Measured on the tip
        before this change, with the real SessionStart hook: rows on disk
        `['newsess']`, fault `''`, the intruder allowed, and the lane the other
        process held transferred to it. SessionStart fires on startup, resume,
        clear and compact, so that is minutes, not an edge case.

        The row is published, the empty base is not: the unreadable value is
        carried under `_faulted`, ownership stays unknown, and every reader that
        decides on this table keeps failing closed until a human clears it.
        """
        self.list_shaped()
        kernel_proc.register("newsess", {"kind": "main", "type": "main"})

        table, dropped, fault = kernel_proc.read_ptable_detail()
        self.assertIn("newsess", table["processes"], "the hook still writes its row")
        self.assertTrue(fault, "and the fault it wrote over is still reported")
        self.assertIn("array of 2 value(s)", fault)
        self.assertIn(kernel_proc.FAULT_KEY, fault)

        carrier = table[kernel_proc.FAULT_KEY]
        self.assertEqual(carrier["count"], 2, "it counts what it could not read")
        self.assertEqual(sorted(r["pid"] for r in carrier["rows"]),
                         ["other", "owner"],
                         "and carries the rows, which in the list-shaped case "
                         "are intact and each carry their own pid")
        self.assertFalse(kernel_proc.claim_lane("intruder",
                                                os.path.join(self.home, "a.py")),
                         "so a claim on it is still refused, register or no register")

    def test_the_fault_survives_every_writer_not_just_the_first(self):
        """Sticky is not "one more write": the gates have to stay closed for as
        long as it takes the operator to look. Four registrations and a prune,
        which is the shape of a session that starts, resumes, compacts and
        spawns, and the fault is still there at the end."""
        self.list_shaped()
        for n in range(4):
            kernel_proc.register(f"sess{n}", {"kind": "main", "type": "main"})
        kernel_proc.prune_locked()
        self.assertTrue(kernel_proc.read_ptable_detail()[2])

    def test_repairing_the_shape_by_hand_is_the_way_out_and_it_is_documented(self):
        """The recovery path, asserted rather than described. There is no
        subcommand and no env hatch on purpose: a fault denies every hooked
        write, so a command that clears it is a command the agent can run to
        clear its own gate. That leaves two file operations, and both work."""
        self.list_shaped()
        kernel_proc.register("newsess", {"kind": "main", "type": "main"})
        self.assertIn(kernel_proc.ptable_path(), kernel_proc.recovery())
        self.assertIn(kernel_proc.FAULT_KEY, kernel_proc.recovery())

        with open(kernel_proc.ptable_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        data.pop(kernel_proc.FAULT_KEY)          # the hand repair
        with open(kernel_proc.ptable_path(), "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        table, dropped, fault = kernel_proc.read_ptable_detail()
        self.assertEqual(fault, "", "cleared, and the rows still in the file stay")
        self.assertIn("newsess", table["processes"])

        os.unlink(kernel_proc.ptable_path())     # or the blunt one
        self.assertEqual(kernel_proc.read_ptable_detail(),
                         ({"version": 1, "processes": {}}, [], ""))

    def test_a_file_this_process_cannot_open_faults_instead_of_raising(self):
        """The OSError leg, with its consequence rather than only its text: an
        unreadable file must reach the callers as a fault they fail closed on,
        and it must not reach them as an exception, because the readers that
        take this path run inside hooks that would then exit non-zero."""
        os.makedirs(kernel_proc.kernel_dir(), exist_ok=True)
        os.makedirs(kernel_proc.ptable_path())
        table, dropped, fault = kernel_proc.read_ptable_detail()
        self.assertIn("could not be read", fault)
        self.assertEqual(table["processes"], {})
        self.assertEqual(kernel_proc.read_ptable()["processes"], {})
        self.assertEqual(kernel_proc.lane_owner("/w/a.py"), (None, None))
        self.assertFalse(kernel_proc.is_live("anyone"))

    def test_a_table_past_the_byte_ceiling_is_a_fault_and_is_never_parsed(self):
        """The size of the ptable is chosen by whoever writes it, and every
        locked writer parses it INSIDE the lock: QA measured 245 MB of peak RSS
        and 1.64 s in that window from a 46.1 MB file. The ceiling is checked
        with a stat, before the parse.

        The file here is VALID JSON of a healthy table, padded past the ceiling.
        A reader that parsed it would find two good rows; this one finds a
        fault, which is what proves the parse never ran.
        """
        os.makedirs(kernel_proc.kernel_dir(), exist_ok=True)
        rows = {"a": {"pid": "a"}, "b": {"pid": "b"},
                "pad": {"pid": "pad", "x": "y" * (kernel_proc.MAX_PTABLE_BYTES + 1000)}}
        with open(kernel_proc.ptable_path(), "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "processes": rows}, fh)
        self.assertGreater(os.path.getsize(kernel_proc.ptable_path()),
                           kernel_proc.MAX_PTABLE_BYTES)
        table, dropped, fault = kernel_proc.read_ptable_detail()
        self.assertIn("ceiling", fault)
        self.assertIn("not parsed", fault)
        self.assertEqual(table["processes"], {},
                         "a table nobody parsed grants nobody anything")


class QuarantineLedgerTest(SandboxHome):
    """The repair ledger beside the ptable: what it costs, and who it names.

    QA cycle 4, F2 and F3. The bound was on FILES only, so the size of each one
    was chosen by whoever wrote the corrupt table (46.1 MB in, 47.7 MB copy,
    245 MB peak RSS, 1.64 s of it inside the ptable lock, a 20-file worst case
    near 954 MB), and the record carried `ts`, `reason` and the bytes but never
    said which process had just overwritten every lane on the machine.
    """

    def corrupt_table(self, rows=1, pad=0):
        """A ptable whose `processes` is an array: unreadable, and as big as the
        caller wants, which is the point of the byte bound."""
        os.makedirs(kernel_proc.kernel_dir(), exist_ok=True)
        procs = [{"pid": f"p{i}", "pad": "x" * pad} for i in range(rows)]
        with open(kernel_proc.ptable_path(), "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "processes": procs}, fh)

    def old_copies(self, n, size=0):
        """`n` files already in the ledger, oldest first, each `size` bytes."""
        os.makedirs(kernel_proc.kernel_dir(), exist_ok=True)
        made = []
        for i in range(n):
            path = os.path.join(kernel_proc.kernel_dir(),
                                f"{kernel_proc.QUARANTINE_PREFIX}old{i:03d}.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"ts": 0, "reason": "old", "ptable": "x" * size}, fh)
            when = time.time() - (n - i) * 60
            os.utime(path, (when, when))
            made.append(path)
        return made

    def test_the_ledger_is_bounded_by_a_count(self):
        """The only bound on disk cost the ledger had, and nothing failed when
        it was removed (QA cycle 4, F4)."""
        old = self.old_copies(kernel_proc.MAX_QUARANTINE + 5)
        self.corrupt_table()
        newest = kernel_proc._quarantine("one more repair")
        kept = [p for _, p in kernel_proc.quarantines()]
        self.assertEqual(len(kept), kernel_proc.MAX_QUARANTINE)
        self.assertIn(newest, kept, "the event that just happened is kept")
        self.assertNotIn(old[0], kept, "the oldest is the one that goes")

    def test_the_ledger_is_bounded_by_bytes_as_well(self):
        """A count bounds the number of files and lets the attacker choose the
        multiplicand. Five copies well inside the file bound already blow the
        byte budget, and the trim has to notice."""
        big = kernel_proc.MAX_QUARANTINE_TOTAL // 4
        self.old_copies(5, size=big)
        self.assertLess(5, kernel_proc.MAX_QUARANTINE, "the count bound is NOT what fires here")
        self.corrupt_table()
        newest = kernel_proc._quarantine("one more repair")
        kept = [p for _, p in kernel_proc.quarantines()]
        total = sum(os.path.getsize(p) for p in kept)
        self.assertLessEqual(total, kernel_proc.MAX_QUARANTINE_TOTAL)
        self.assertLess(len(kept), 6)
        self.assertIn(newest, kept)

    def test_one_copy_preserves_a_bounded_slice_and_says_so(self):
        """The per-file half. A 1.2 MB corrupt table used to be copied whole,
        through a slurp and a JSON re-encode, inside the ptable lock. What is
        kept is capped and the truncation is recorded next to the original size,
        so the copy is honest about being partial instead of looking complete."""
        self.corrupt_table(rows=40, pad=40 * 1024)
        size = os.path.getsize(kernel_proc.ptable_path())
        self.assertGreater(size, kernel_proc.MAX_QUARANTINE_BYTES)
        path = kernel_proc._quarantine("too big to keep whole")
        with open(path, encoding="utf-8") as fh:
            rec = json.load(fh)
        self.assertTrue(rec["truncated"])
        self.assertEqual(rec["kept_bytes"], kernel_proc.MAX_QUARANTINE_BYTES)
        self.assertEqual(rec["bytes"], size, "and it says what the original was")
        self.assertLess(os.path.getsize(path), 3 * kernel_proc.MAX_QUARANTINE_BYTES)

    def test_two_repairs_in_the_same_millisecond_are_two_files(self):
        """The collision loop, which nothing failed without (QA cycle 4, F4).
        Its own comment says why it exists: one file for two events undercounts
        exactly the frequency `brain_doctor` escalates on, and the doctor's
        threshold is three in 24 h, so a lost file is a lost escalation."""
        from unittest import mock
        self.corrupt_table()
        with mock.patch("time.time", return_value=1757000000.0):
            first = kernel_proc._quarantine("event one")
            second = kernel_proc._quarantine("event two")
        self.assertNotEqual(first, second)
        self.assertEqual(len(kernel_proc.quarantines()), 2)
        reasons = set()
        for _, path in kernel_proc.quarantines():
            with open(path, encoding="utf-8") as fh:
                reasons.add(json.load(fh)["reason"])
        self.assertEqual(reasons, {"event one", "event two"})

    def test_the_copy_names_the_process_that_overwrote_the_table(self):
        """QA cycle 4, F3. The record carried `ts`, `reason` and the bytes, so
        the process that wiped every lane on the machine left no trace naming
        itself. The kernel pid is the writer's own; `os_pid` and `argv0` are for
        the case that matters most, where the writer is not the kernel."""
        self.corrupt_table(rows=2)
        kernel_proc.register("newsess", {"kind": "main", "type": "main"})
        kept = kernel_proc.quarantines()
        self.assertEqual(len(kept), 1)
        with open(kept[0][1], encoding="utf-8") as fh:
            rec = json.load(fh)
        self.assertEqual(rec["pid"], "newsess")
        self.assertEqual(rec["os_pid"], os.getpid())
        self.assertTrue(rec["argv0"])

    def test_a_carried_fault_is_preserved_once_not_once_per_write(self):
        """The ledger counts EVENTS. A fault is now carried forward, so every
        writer after the first reads a fault too; quarantining on each of them
        would fill the ledger with copies of a table that is no longer the
        corrupt one and would trip the doctor's three-in-24 h escalation off a
        single event. The carrier records the copy it already has."""
        self.corrupt_table(rows=2)
        kernel_proc.register("a", {"kind": "main"})
        kernel_proc.register("b", {"kind": "main"})
        kernel_proc.register("c", {"kind": "main"})
        kept = kernel_proc.quarantines()
        self.assertEqual(len(kept), 1, "one corruption, one copy")
        carrier = kernel_proc.read_ptable()[kernel_proc.FAULT_KEY]
        self.assertEqual(carrier["quarantine"], os.path.basename(kept[0][1]),
                         "and the table points at it")

    def test_the_doctor_escalates_on_three_repairs_in_a_day(self):
        """The headline of the fix that made repairs countable, and nothing
        failed when it was removed (QA cycle 4, F4). One repair is an accident
        and reads as a WARN; three in 24 h is a writer that is not the kernel
        and is still running, which is an operator's problem right now."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "brain_doctor_freq", str(SCRIPTS / "brain_doctor.py"))
        bd = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bd)

        kernel_proc.register("good", {"kind": "main", "type": "main"})
        for n in range(2):
            self.drop_one_row(f"bad{n}")
        self.assertEqual(len(kernel_proc.quarantines()), 2)
        result = bd.check_kernel_process_live(False)
        self.assertEqual(result.status, bd.WARN, result.message)
        self.assertIn("2 repaired ptable(s)", result.message)

        self.drop_one_row("bad2")
        result = bd.check_kernel_process_live(False)
        self.assertEqual(result.status, bd.FAIL, result.message)
        self.assertIn("repaired 3 times", result.message)

    def drop_one_row(self, name):
        """One repair EVENT: a value that is not an object goes in, a writer
        reads it, drops it and preserves what it overwrote."""
        with open(kernel_proc.ptable_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        data["processes"][name] = "not-a-row"
        with open(kernel_proc.ptable_path(), "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        kernel_proc.update_row("good", {"note": name})


class ReRegisterTest(SandboxHome):
    """QA cycle 1, D3. SessionStart fires on startup, resume, clear and compact."""

    def test_each_registration_appends_its_own_start_line_with_its_source(self):
        kernel_proc.register("s", {"kind": "main", "source": "startup"})
        kernel_proc.register("s", {"kind": "main", "source": "resume"})
        lines = kernel_proc.read_journal("s")
        self.assertEqual([l["kind"] for l in lines], ["start", "start"])
        self.assertEqual([l["source"] for l in lines], ["startup", "resume"])
        self.assertEqual(kernel_proc.verify("s"), 0)
        row = kernel_proc.read_ptable()["processes"]["s"]
        self.assertEqual(row["source"], "resume", "the row carries the latest")


class FileCleanupTest(SandboxHome):
    """Journals and locks used to accumulate forever, two files per run."""

    def test_old_files_of_a_dead_pid_are_removed_and_live_ones_are_kept(self):
        for pid in ("gone", "recent", "livepid"):
            kernel_proc.register(pid, {"kind": "main"})
        old = time.time() - (kernel_proc.PRUNE_AFTER + 3600)
        for pid in ("gone",):
            for path in (kernel_proc.journal_path(pid), kernel_proc.lock_path(pid)):
                os.utime(path, (old, old))
        table = kernel_proc.read_ptable()
        self.assertEqual(kernel_proc.prune_files(table), 2, "journal and lock both go")
        self.assertFalse(os.path.exists(kernel_proc.journal_path("gone")))
        self.assertFalse(os.path.exists(kernel_proc.lock_path("gone")))
        self.assertTrue(os.path.exists(kernel_proc.journal_path("recent")))
        self.assertTrue(os.path.exists(kernel_proc.journal_path("livepid")))

    def test_pruning_leaves_no_fresh_lock_behind_when_the_lock_is_seen_first(self):
        """QA nit on Phase 1a. `os.listdir` has no order, so half the time the
        sweep saw `<pid>.jsonl.lock` before `<pid>.jsonl`: it removed the lock,
        then re-created it by taking `lock_path(pid)` again to remove the
        journal, and left a fresh empty `.lock` that no later sweep could
        remove either (its mtime was now young). Forcing that order is the only
        way to pin the fix."""
        from unittest import mock

        kernel_proc.register("dead", {"kind": "main"})
        old = time.time() - (kernel_proc.PRUNE_AFTER + 3600)
        for path in (kernel_proc.journal_path("dead"), kernel_proc.lock_path("dead")):
            os.utime(path, (old, old))
        table = kernel_proc.read_ptable()
        table["processes"].pop("dead", None)  # the row is long gone; the files are not
        forced = ["dead.jsonl.lock", "dead.jsonl"]   # lock FIRST, the bug's order
        with mock.patch.object(kernel_proc.os, "listdir", return_value=forced):
            removed = kernel_proc.prune_files(table)
        self.assertEqual(removed, 2)
        self.assertEqual(sorted(os.listdir(kernel_proc.journal_dir())), [],
                         "a fresh empty .lock is exactly what must NOT be left")

    def test_a_lock_with_no_journal_is_swept_too(self):
        kernel_proc.register("orphan", {"kind": "main"})
        os.unlink(kernel_proc.journal_path("orphan"))
        old = time.time() - (kernel_proc.PRUNE_AFTER + 3600)
        os.utime(kernel_proc.lock_path("orphan"), (old, old))
        self.assertEqual(kernel_proc.prune_files({"processes": {}}), 1)
        self.assertFalse(os.path.exists(kernel_proc.lock_path("orphan")))

    def test_an_orphan_journal_is_kept_until_the_retention_window_then_swept(self):
        """A journal with no ptable row is swept by the SAME retention rule as
        any other, and not one second earlier.

        The sweep enumerates the journal directory, never the ptable, so an
        orphan is already covered: `is_live` reads a pid with no row as a main
        process, and a main process with a stale journal and no children is not
        live. That is the right answer to "should an orphan be pruned sooner":
        no. The journal IS the audit trail, and a shorter window for exactly
        the files that record an anomaly would delete the evidence of it.
        """
        kernel_proc.register("orphaned", {"kind": "main"})
        kernel_proc.append("orphaned", {"kind": "tool", "tool_name": "Bash",
                                        "tool_use_id": "t0"})
        table = kernel_proc.read_ptable()
        table["processes"].pop("orphaned")      # journal on disk, no row: an orphan
        kernel_proc._write_ptable(table)
        table = kernel_proc.read_ptable()

        inside = time.time() - (kernel_proc.PRUNE_AFTER - 3600)
        for path in (kernel_proc.journal_path("orphaned"), kernel_proc.lock_path("orphaned")):
            os.utime(path, (inside, inside))
        self.assertEqual(kernel_proc.prune_files(table), 0,
                         "inside the window the audit trail stays")
        self.assertTrue(os.path.exists(kernel_proc.journal_path("orphaned")))

        past = time.time() - (kernel_proc.PRUNE_AFTER + 3600)
        for path in (kernel_proc.journal_path("orphaned"), kernel_proc.lock_path("orphaned")):
            os.utime(path, (past, past))
        self.assertEqual(kernel_proc.prune_files(table), 2)
        self.assertFalse(os.path.exists(kernel_proc.journal_path("orphaned")))
        self.assertFalse(os.path.exists(kernel_proc.lock_path("orphaned")))

    def test_an_old_file_of_a_LIVE_pid_is_kept(self):
        kernel_proc.register("busy", {"kind": "main"})
        old = time.time() - (kernel_proc.PRUNE_AFTER + 3600)
        os.utime(kernel_proc.lock_path("busy"), (old, old))  # stale lock, fresh journal
        table = kernel_proc.read_ptable()
        self.assertEqual(kernel_proc.prune_files(table), 0)
        self.assertTrue(os.path.exists(kernel_proc.lock_path("busy")))


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


class ExitHookTest(SandboxHome):
    """The SubagentStop reflex as the harness runs it. What is pinned: an ending
    is written once, it carries what the process did, and a child that failed is
    not recorded as ok."""

    def run_stop(self, payload):
        env = dict(os.environ)
        env["HOME"] = self.home
        env["USERPROFILE"] = self.home
        env.pop("OCTO_KERNEL_OPEN", None)
        return subprocess.run([sys.executable, str(SCRIPTS / "r__subagent-stop__proc-exit.py")],
                              input=json.dumps(payload), capture_output=True,
                              text=True, env=env, cwd=self.home, timeout=60)

    def child(self, tools=1):
        kernel_proc.register("s1", {"kind": "main", "worktree": self.home})
        kernel_proc.register("c1", {"kind": "subagent", "ppid": "s1", "type": "QA",
                                    "worktree": self.home})
        for i in range(tools):
            kernel_proc.append("c1", {"kind": "tool", "tool_name": "Bash",
                                      "tool_use_id": f"toolu_{i}"})

    def payload(self, **kw):
        base = {"hook_event_name": "SubagentStop", "session_id": "s1",
                "agent_id": "c1", "agent_type": "QA",
                "last_assistant_message": "Reviewed and shipped."}
        base.update(kw)
        return base

    def exits(self, pid="c1"):
        return [l for l in kernel_proc.read_journal(pid)
                if isinstance(l, dict) and l.get("kind") == "exit"]

    def test_a_normal_exit_is_ok_and_carries_what_the_process_did(self):
        self.child(tools=2)
        cp = self.run_stop(self.payload(agent_transcript_path="/tmp/agent-c1.jsonl"))
        self.assertEqual(cp.returncode, 0)
        self.assertEqual(cp.stdout.strip(), "", "a reflex never speaks to the model")
        (e,) = self.exits()
        self.assertEqual(e["status"], "ok")
        self.assertIs(e["ok"], True)
        self.assertEqual(e["tool_count"], 2)
        self.assertEqual(e["agent_transcript_path"], "/tmp/agent-c1.jsonl")
        self.assertGreaterEqual(e["duration"], 0)
        self.assertEqual(kernel_proc.verify("c1"), 0)
        row = kernel_proc.read_ptable()["processes"]["c1"]
        self.assertTrue(row["exited"])
        self.assertEqual(row["status"], "ok")
        self.assertFalse(kernel_proc.is_live("c1"), "an exited child releases what it held")

    def test_a_child_reporting_an_error_is_not_recorded_as_ok(self):
        self.child()
        self.run_stop(self.payload(last_assistant_message="Error: the build failed."))
        (e,) = self.exits()
        self.assertEqual(e["status"], "error")
        self.assertIs(e["ok"], False)

    def test_a_child_that_said_nothing_is_an_error(self):
        self.child()
        self.run_stop(self.payload(last_assistant_message=""))
        self.assertEqual(self.exits()[0]["status"], "error")

    def test_an_error_named_mid_report_is_a_finding_not_a_crash(self):
        self.child()
        self.run_stop(self.payload(
            last_assistant_message="Found the bug: an error in the retry path. Fixed."))
        self.assertEqual(self.exits()[0]["status"], "ok")

    def test_a_missing_meta_json_is_not_an_error(self):
        self.child()
        self.run_stop(self.payload(
            transcript_path=os.path.join(self.home, "projects", "x", "s1.jsonl")))
        (e,) = self.exits()
        self.assertEqual(e["status"], "ok")
        for absent in ("spawn_depth", "model", "spawn_tool_use_id"):
            self.assertNotIn(absent, e)

    def test_the_meta_json_fields_are_read_when_present(self):
        self.child()
        subs = os.path.join(self.home, "projects", "x", "s1", "subagents")
        os.makedirs(subs)
        atp = os.path.join(subs, "agent-c1.jsonl")
        with open(atp[:-6] + ".meta.json", "w", encoding="utf-8") as fh:
            json.dump({"spawnDepth": 2, "model": "opus", "toolUseId": "toolu_parent"}, fh)
        self.run_stop(self.payload(
            transcript_path=os.path.join(self.home, "projects", "x", "s1.jsonl")))
        (e,) = self.exits()
        self.assertEqual((e["spawn_depth"], e["model"], e["spawn_tool_use_id"]),
                         (2, "opus", "toolu_parent"))

    def test_a_repeated_subagent_stop_writes_no_second_ending(self):
        self.child()
        for _ in range(3):
            self.run_stop(self.payload())
        self.assertEqual(len(self.exits()), 1)
        self.assertEqual(kernel_proc.verify("c1"), 0)

    def test_an_exit_for_a_pid_the_kernel_never_saw_creates_nothing(self):
        """The phantom-exit defect, measured live: 52 journals in one afternoon
        whose first and only line was an `exit` at seq 0, no row, no parent, no
        tool, each naming an agent transcript that did not exist on disk.

        The harness fires SubagentStop for agent ids that never registered and
        never ran a tool, and `append()` creates the journal it writes to, so
        the ending was materialising the process. An exit is an ENDING: it must
        never be the thing that brings a process into being.
        """
        self.child()                       # a real, unrelated process exists
        cp = self.run_stop(self.payload(agent_id="never-existed"))
        self.assertEqual(cp.returncode, 0, "a reflex never blocks")
        self.assertEqual(cp.stdout.strip(), "")
        self.assertFalse(os.path.exists(kernel_proc.journal_path("never-existed")),
                         "an exit alone must not create a journal")
        self.assertFalse(os.path.exists(kernel_proc.lock_path("never-existed")),
                         "nor the lock file that opening one leaves behind")
        self.assertNotIn("never-existed", kernel_proc.read_ptable()["processes"])
        self.assertEqual(self.exits("never-existed"), [])
        self.assertEqual(len(self.exits("c1")), 0, "the real process is untouched")

    def test_a_zero_byte_journal_is_not_a_trace(self):
        """QA cycle 1: an empty file is a name, not work. It is reachable only
        from a crash between the create and the first write, and treating it as
        a trace let an ending write the same phantom shape into it."""
        path = kernel_proc.journal_path("half-open")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "wb").close()
        self.assertEqual(os.path.getsize(path), 0)
        cp = self.run_stop(self.payload(agent_id="half-open"))
        self.assertEqual(cp.returncode, 0)
        self.assertEqual(os.path.getsize(path), 0, "no exit written into an empty journal")
        self.assertEqual(self.exits("half-open"), [])

    def test_a_row_that_is_not_an_object_is_not_a_trace(self):
        """`pid in procs` tests the KEY, so a corrupt table whose value is a
        string or null answered yes and let the ending through. The row has to
        be a row."""
        self.child()                        # so a real table exists to corrupt
        for junk in ("not-a-row", None, 42, ["c1"]):
            with self.subTest(row=junk):
                pid = "junk-%s" % type(junk).__name__
                table = kernel_proc.read_ptable()
                table.setdefault("processes", {})[pid] = junk
                path = kernel_proc.ptable_path()
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(table, fh)
                cp = self.run_stop(self.payload(agent_id=pid))
                self.assertEqual(cp.returncode, 0)
                self.assertFalse(os.path.exists(kernel_proc.journal_path(pid)),
                                 "a malformed row is not evidence the process ran")

    def test_a_journal_opened_by_the_hot_path_gate_still_gets_its_exit(self):
        """The legitimate no-`start` process. Same-event hooks run in parallel,
        so a child's first tool call can beat its own SubagentStart: the gate
        opens the journal on the spot and the first line is a `tool`, never a
        `start`. That process ran, so its ending is recorded like any other.
        This is the case the phantom guard must not weaken."""
        kernel_proc.register("s1", {"kind": "main", "worktree": self.home})
        gate = subprocess.run(
            [sys.executable, str(SCRIPTS / "g__pretool__kernel.py")],
            input=json.dumps({"session_id": "s1", "agent_id": "racer",
                              "tool_name": "Bash", "tool_use_id": "toolu_race",
                              "tool_input": {"command": "true"}, "cwd": self.home}),
            capture_output=True, text=True, env={**os.environ, "HOME": self.home,
                                                 "USERPROFILE": self.home},
            cwd=self.home, timeout=60)
        self.assertEqual(gate.returncode, 0)
        kinds = [l.get("kind") for l in kernel_proc.read_journal("racer")]
        self.assertEqual(kinds, ["tool"], "the gate opens the journal with a tool line")
        self.assertNotIn("racer", kernel_proc.read_ptable()["processes"],
                         "the register hook lost the race, so there is no row")

        self.run_stop(self.payload(agent_id="racer"))
        (e,) = self.exits("racer")
        self.assertEqual(e["status"], "ok")
        self.assertEqual(e["tool_count"], 1)
        self.assertEqual(kernel_proc.verify("racer"), 0)

    def test_a_row_with_no_journal_still_gets_its_exit(self):
        """The other half of the trace test. `register()` writes the journal
        first, so this is rare, but a journal deleted underneath a live process
        must not turn its ending into a no-op."""
        self.child()
        os.unlink(kernel_proc.journal_path("c1"))
        self.assertTrue(kernel_proc.has_trace("c1"), "the ptable row is a trace")
        self.run_stop(self.payload())
        self.assertEqual(len(self.exits("c1")), 1)

    def test_a_payload_without_an_agent_id_is_ignored(self):
        self.child()
        cp = self.run_stop(self.payload(agent_id=""))
        self.assertEqual(cp.returncode, 0)
        self.assertEqual(self.exits(), [])

    def test_garbage_on_stdin_never_blocks(self):
        env = dict(os.environ)
        env["HOME"] = self.home
        cp = subprocess.run([sys.executable, str(SCRIPTS / "r__subagent-stop__proc-exit.py")],
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

    def test_exit_selftest_passes(self):
        cp = self._run("r__subagent-stop__proc-exit.py", "ARCHITECTURE.kernel-process")
        self.assertEqual(cp.returncode, 0, cp.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class ExitStatusWordBoundaryTest(unittest.TestCase):
    def test_error_word_boundary(self):
        import importlib.util, os
        spec = importlib.util.spec_from_file_location(
            "proc_exit", os.path.join(os.path.dirname(__file__), "..", "r__subagent-stop__proc-exit.py"))
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        self.assertEqual(m.status_of("Errors were found and fixed"), "ok")
        self.assertEqual(m.status_of("Exceptionally good result"), "ok")
        self.assertEqual(m.status_of("Error: boom"), "error")
        self.assertEqual(m.status_of("**Fatal** problem"), "error")
        self.assertEqual(m.status_of(""), "error")
        self.assertEqual(m.status_of("QA-VERDICT: FAIL"), "ok")

