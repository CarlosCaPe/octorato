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

import hashlib
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

    def age_journal(self, pid, age_seconds):
        """Backdate BOTH halves of a journal's liveness: the file's mtime AND the
        `ts` of its last chained record.

        THE WHOLE FILE MOVES, not just the last line, since cycle 6 C-A. The
        tail is now checked against its own file (`_record_ts`: shape, anchor
        and direction), so a last line backdated on its own contradicts line 0's
        `start_ts` and the line before it, which is the signature of a forged
        record and not of an expiry. `backdate_journal` shifts every line and
        re-chains, so the fixture says one coherent thing.

        `os.utime` alone stopped meaning "this process went quiet" in cycle 5:
        `_own_fresh` re-checks a stale mtime against the record, because one
        `touch` on a live holder's journal used to free its lane with nothing
        deleted, nothing edited and the chain intact. So a test that ages only
        the mtime is now exercising the ATTACK, not the expiry, and every test
        that means "this process is old" has to say it in both places. The one
        test that ages only the mtime does it deliberately and asserts the lane
        stays held.
        """
        path = kernel_proc.journal_path(pid)
        if not kernel_proc.backdate_journal(path, age_seconds):
            when = time.time() - age_seconds
            os.utime(path, (when, when))

    def touch_journal(self, pid, age_seconds=0.0):
        """Make <pid>'s journal exist and read `age_seconds` old."""
        kernel_proc.append(pid, {"kind": "start"})
        self.age_journal(pid, age_seconds)


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
        self.age_journal("parent", 1200)
        table = self.table()
        self.assertTrue(kernel_proc.is_live("parent", table),
                        "a parent blocked on a child is not dead")
        self.assertTrue(kernel_proc.is_live("child", table))

    def test_an_expired_child_is_not_live(self):
        kernel_proc.register("parent", {"kind": "main"})
        kernel_proc.register("child", {"kind": "subagent", "ppid": "parent"})
        self.age_journal("child", kernel_proc.TTL + 60)
        table = self.table()
        self.assertFalse(kernel_proc.is_live("child", table),
                         "a hung child releases what it holds after the TTL")
        self.assertTrue(kernel_proc.is_live("parent", table))

    def test_a_child_that_really_ended_is_not_live(self):
        """RENAMED AND RE-SETUP IN CYCLE 8, and the change is the finding. This
        was `..._with_an_exit_line_...` and it built the ending with `append`
        alone, which is now the ATTACK rather than the state: one appended exit
        line freed a live holder's lane on both gates. A real ending is both
        writes `r__subagent-stop__proc-exit.py` makes, so the setup makes both.

        What stopped being covered is "an exit LINE alone ends a process",
        deliberately, and it is now covered in the opposite direction by
        `EndingNeedsBothHalvesTest.test_c8_a_well_formed_exit_line_alone_is_not
        _an_ending`."""
        kernel_proc.register("parent", {"kind": "main"})
        kernel_proc.register("child", {"kind": "subagent", "ppid": "parent"})
        kernel_proc.append("child", {"kind": "exit", "status": "ok"})
        self.assertTrue(kernel_proc.update_row("child", {"exited": True}))
        self.assertFalse(kernel_proc.is_live("child", self.table()))

    def test_a_child_of_a_dead_parent_is_not_live(self):
        kernel_proc.register("parent", {"kind": "main"})
        kernel_proc.register("child", {"kind": "subagent", "ppid": "parent"})
        for pid in ("parent", "child"):
            self.age_journal(pid, kernel_proc.TTL + 60)
        self.assertFalse(kernel_proc.is_live("child", self.table()))
        self.assertFalse(kernel_proc.is_live("parent", self.table()))

    def test_a_future_mtime_is_skew_not_liveness(self):
        kernel_proc.register("skewed", {"kind": "main"})
        self.age_journal("skewed", -(kernel_proc.FUTURE_SKEW + 600))
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
        self.age_journal("ancient", kernel_proc.PRUNE_AFTER + 3600)
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
        (QA cycle 1, F2).
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
        failure mode.

        NAMED WHERE IT IS USED, which is QA cycle 4 F7. This asserted that the
        pure function returns the pid and stopped there, while the two callers
        that DECIDE on it wrote `table, _dropped, fault = ...` and threw the
        name away: the exact "asserting on the pure function when the caller was
        the bug" shape, and F1c was living in that underscore. So the name is
        followed to each consumer that has to act on it: the writer that carries
        the loss forward, the claim that refuses, and the doctor that reports
        it. The gates are the last hop and they are pinned in
        test_tree_owner.QaCycle4, in their own process, where the deny text is
        what the operator actually reads.
        """
        self.corrupt("not-a-row", 7, None, ["lanes"])
        table, dropped, _fault = kernel_proc.read_ptable_detail()
        self.assertEqual(sorted(dropped), ["bad0", "bad1", "bad2", "bad3"])
        self.assertEqual(sorted(table["processes"]), ["good"])
        self.assertEqual(kernel_proc.read_ptable()["processes"], table["processes"])

        self.assertFalse(kernel_proc.claim_lane("good", os.path.join(self.home, "a.py")),
                         "a claim asserts nobody else holds this, and four rows "
                         "it could not read are no basis for that")
        self.assertIn("bad0", self.rows_on_disk(), "and the refused claim wrote nothing")

        kernel_proc.register("newsess", {"kind": "main", "type": "main"})
        carried = self.raw().decode("utf-8")
        self.assertIn(kernel_proc.FAULT_KEY, carried,
                      "the writer that repairs the table carries the loss with it")
        for pid in ("bad0", "bad1", "bad2", "bad3"):
            self.assertIn(pid, carried, f"and names {pid} in the fault it carries")

        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "brain_doctor_named", str(SCRIPTS / "brain_doctor.py"))
        bd = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bd)
        result = bd.check_kernel_process_live(False)
        self.assertEqual(result.status, bd.FAIL, result.message)
        self.assertIn("bad0", result.message)

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
        held for a reason that had nothing to do with the read (QA cycle 1, F3).
        Here the table carries a prunable row, so a writer handed this same
        fixture WOULD rewrite the file, and the test proves that in its last two
        lines instead of asserting it in prose (QA cycle 2, F6: with the reason
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
        """QA cycle 1, F3. `octo ps` prunes on read, prune is a writer, and on a
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
        whole difference (QA cycle 1, the second test that passed for the wrong
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
        exists to report is the one that has to be loud about it, so it names
        the row and never PASSes over it.

        FAIL, where this used to assert WARN, and QA cycle 4 F1c is the reason
        the severity moved. The WARN rationale was "a row-level drop costs n
        named rows and leaves a working, self-repairing kernel"; it does not
        survive n being all of them, one row at a time, and the self-repair is
        the part that hurts, because the next register republishes the table
        without those rows and their lanes are gone. Both gates deny on a drop
        now, so this machine refuses every hooked write, which is not a working
        kernel. The two things the WARN was protecting are still asserted: the
        check does not crash, and it names the row.
        """
        import importlib.util
        self.corrupt()
        spec = importlib.util.spec_from_file_location(
            "brain_doctor_ro", str(SCRIPTS / "brain_doctor.py"))
        bd = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bd)
        result = bd.check_kernel_process_live(False)
        self.assertEqual(result.status, bd.FAIL, result.message)
        self.assertIn("unreadable ptable row", result.message)
        self.assertIn("bad0", result.message)
        self.assertIn("rm ", result.hint, "and it says how to get out of it")

    def test_liveness_and_the_lane_lookup_survive_the_bad_row(self):
        """The two functions on the hot path. Both walk every row in the table,
        so both used to raise on the first bad one they reached.

        ORDER IS THE TEST (QA cycle 1, F2). The first version of this corrupted
        the table and then called `claim_lane`, which is a WRITER: it
        republished the table without the bad row, so `is_live` and `lane_owner`
        both ran against a clean file and neither assertion ever saw the state
        named in the method. Measured: `bad0` on disk before the claim, gone
        after it. The world is built first and the corruption injected last, and
        the file is checked on both sides of the two calls, so the bad row is
        provably still there while they run and neither of them is a writer.

        The world is now built on a CLEAN table on purpose. Since QA cycle 4 F1c
        `claim_lane` refuses a table with a dropped row (a row it could not read
        is a set of lanes it could not read, so "nobody else holds this" has no
        basis), so building the lane through the corruption would silently claim
        nothing and both assertions below would read None for the wrong reason.
        That refusal is asserted here too, at the end, where it cannot be
        mistaken for the setup.
        """
        kernel_proc.register("good", {"kind": "main", "type": "main", "worktree": "/w"})
        self.touch_journal("good")
        self.assertTrue(kernel_proc.claim_lane("good", os.path.join(self.home, "pkg")),
                        "the lane is claimed on a table that is still readable")
        self.inject()                       # the writer is done; corrupt it now
        self.assertIn("bad0", self.rows_on_disk(), "the bad row must be on disk HERE")

        self.assertTrue(kernel_proc.is_live("good"))
        self.assertIn("bad0", self.rows_on_disk(), "is_live is a reader")
        owner, row = kernel_proc.lane_owner(os.path.join(self.home, "pkg", "a.py"),
                                            ignore="other")
        self.assertEqual(owner, "good")
        self.assertEqual(row.get("type"), "main")
        self.assertIn("bad0", self.rows_on_disk(), "lane_owner is a reader")

        self.assertFalse(
            kernel_proc.claim_lane("other", os.path.join(self.home, "pkg", "b.py")),
            "and a claim on a table carrying an unreadable row is refused (F1c)")
        self.assertIn("bad0", self.rows_on_disk(), "a refused claim writes nothing")

    def test_a_row_that_is_not_an_object_is_never_a_trace(self):
        """`has_trace`'s row guard, pinned where it can actually be reached.

        QA cycle 2, F5 measured that this guard cannot fire through the live
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
    """QA cycle 1, F1. A row that is not an object costs one named row. A
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
        """Zero rows is the truth about this machine in exactly one state, and
        the state is about the MACHINE, not about the file: nothing beside the
        table reads live. Any other way of yielding zero rows is a machine whose
        table was readable to somebody and is not readable to us.

        The docstring used to assert that universal and the body used to
        enumerate five shapes the code already handled (QA cycle 4 F7): the two
        cheapest counterexamples, a `processes` written EMPTY and a `processes`
        whose every row is dropped, appeared nowhere, and the test passed
        because of what it did not test. Both are the first thing here now, each
        with a live journal beside the table, which is the condition that makes
        them a loss rather than a new laptop.
        """
        self.assertFalse(os.path.exists(kernel_proc.ptable_path()))
        self.assertEqual(kernel_proc.read_ptable_detail(), ({"version": 1, "processes": {}}, [], ""))

        # A machine with something running on it, which is what every one of the
        # shapes below is lying about.
        kernel_proc.register("owner", {"kind": "main", "type": "main"})
        kernel_proc.claim_lane("owner", os.path.join(self.home, "a.py"))
        # A lane is claimed off a TOOL CALL, and since cycle 5 C3 that line is
        # what makes a journal evidence of work rather than of a registration in
        # flight. Registered-and-never-worked was a shortcut in the fixture.
        kernel_proc.append("owner", {"kind": "tool", "tool_name": "Write"})
        self.assertEqual(kernel_proc.live_journal_pids(), ["owner"])

        for content, expected in (('{"version": 1, "processes": {}}', "carries no row"),
                                  ('{"processes": {"owner": "x"}}', "unreadable and dropped"),
                                  ('{"processes": {"owner": {"pid": "owner", "lanes": 7}}}',
                                   "unreadable and dropped")):
            with open(kernel_proc.ptable_path(), "w", encoding="utf-8") as fh:
                fh.write(content)
            table, dropped, fault = kernel_proc.read_ptable_detail()
            self.assertEqual(table["processes"], {}, content)
            self.assertIn(expected, fault, content)
            self.assertIn("owner", fault, "and it names what is still running")
            self.assertFalse(
                kernel_proc.claim_lane("intruder", os.path.join(self.home, "a.py")),
                f"so the intruder gets nothing out of {content}")

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
        # one leg this test named and never exercised (QA cycle 2, F7). A
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
        """QA cycle 2, F1, the serious one. The protection used to last minutes.

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

        # ... or the blunt one, which since QA cycle 3 F3 costs a SECOND step
        # and `recovery()` now says so. A table that is simply gone while live
        # journals sit beside it is a fault of its own: the deletion path is the
        # cheap attack, and leaving it open while the corruption path fails
        # closed pays an outage against the move nobody would make.
        kernel_proc.append("newsess", {"kind": "tool", "tool_name": "Write"})
        os.unlink(kernel_proc.ptable_path())
        self.assertIn("absent", kernel_proc.read_ptable_detail()[2],
                      "rm alone moves it from one faulted state to another")
        self.assertIn(kernel_proc.journal_dir(), kernel_proc.recovery(),
                      "so the printed recovery has to name the second step")
        # Letting the journals GO QUIET is what ends it. Deleting them is a
        # different move and since cycle 5 M1 it is its own fault: an empty
        # journal directory on a machine that has run hooks is a sweep, not a
        # laptop with nothing on it.
        for pid in os.listdir(kernel_proc.journal_dir()):
            if pid.endswith(".jsonl"):
                self.age_journal(pid[:-len(".jsonl")], kernel_proc.TTL + 300)
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


class SymlinkLoopFaultTest(SandboxHome):
    """QA cycle 3, F1. `read_ptable_detail` had TWO `except OSError` legs and
    they disagreed: the one on `open` carried the fault forward, the one on the
    `getsize` above it returned `fresh_table()`, so the fault died at the next
    write.

    Which leg an unreadable table lands on is chosen by whoever made it
    unreadable, never by the kernel. A directory at the path fails at `open`,
    which is the shape cycle 4 tested and the reason the disagreement went
    unseen; a symlink LOOP fails one line earlier at the stat, and through that
    leg the entire cycle-4 loss reproduced verbatim: deny, one SessionStart,
    fault empty, allow, the owner's row and its lane gone. So the test is
    written with the loop, not the directory: a fail-closed rule that holds for
    one syscall and not the other is not fail-closed.
    """

    def loop(self):
        """A ptable path that is a symlink to itself: ELOOP at the stat."""
        os.makedirs(kernel_proc.kernel_dir(), exist_ok=True)
        path = kernel_proc.ptable_path()
        if os.path.exists(path) or os.path.islink(path):
            os.unlink(path)
        os.symlink(path, path)
        with self.assertRaises(OSError):
            os.path.getsize(path)          # the leg under test, proven to fire

    def test_an_eloop_table_carries_its_fault_like_every_other_unreadable_one(self):
        table, dropped, fault = kernel_proc.read_ptable_detail()
        self.assertEqual(fault, "", "a fresh sandbox is the honest empty table")

        kernel_proc.register("owner", {"kind": "main", "type": "main"})
        self.loop()
        table, dropped, fault = kernel_proc.read_ptable_detail()
        self.assertIn("could not be read", fault)
        self.assertEqual(dropped, [])
        self.assertIn(kernel_proc.FAULT_KEY, table,
                      "the stat leg must CARRY, exactly like the open leg")

    def test_the_fault_outlives_the_register_the_same_way(self):
        """The consequence, not the field. Before the fix this sequence ended
        with a valid one-row table, no fault, and every lane on the machine
        granted away by the first write after it."""
        kernel_proc.register("owner", {"kind": "main", "type": "main"})
        self.assertTrue(kernel_proc.claim_lane("owner",
                                               os.path.join(self.home, "a.py")))
        self.loop()

        kernel_proc.register("newsess", {"kind": "main", "type": "main"})
        table, _dropped, fault = kernel_proc.read_ptable_detail()
        self.assertIn("newsess", table["processes"], "the hook still writes its row")
        self.assertTrue(fault, "and the fault it wrote over is still reported")
        self.assertIn(kernel_proc.FAULT_KEY, fault)
        self.assertFalse(kernel_proc.claim_lane("intruder",
                                                os.path.join(self.home, "a.py")),
                         "so the intruder still cannot take the lane it was denied")

    def test_the_copy_beside_the_file_is_empty_here_and_that_is_honest(self):
        """One thing this leg genuinely cannot do, said out loud rather than
        left to be discovered: the quarantine copy reads the original bytes, and
        for a symlink loop there are no bytes to read. The evidence that
        survives is the carried fault, which is what the gates and the doctor
        actually read; a copy of nothing would have been the misleading half."""
        kernel_proc.register("owner", {"kind": "main", "type": "main"})
        self.loop()
        kernel_proc.register("newsess", {"kind": "main", "type": "main"})
        self.assertEqual(kernel_proc.quarantines(), [])
        self.assertTrue(kernel_proc.read_ptable_detail()[2],
                        "the fault is the record, and it is still there")


class AbsentTableTest(SandboxHome):
    """QA cycle 3, F3. The claim "there is exactly one honest empty table, an
    ABSENT file" was false whenever live journals sat beside it, and the two
    readers said so out loud: `octo ps` printed "the kernel has registered
    nothing on this machine yet" while `octo top` listed two live processes out
    of the same directory.

    The measured consequence is why it is a fault and not a wording bug. The
    attacker's cheap move is not corrupting the table, it is DELETING it, and
    both reach the file through the same door: `rm` is denied by the Bash gate,
    `python3 -c` and `ln -sf` are not. Corruption bought a deny-all the
    attacker also suffers. Deletion bought a silent allow-everything machine:
    no fault, no quarantine copy, no doctor FAIL, no deny.
    """

    def live_owner(self):
        kernel_proc.register("owner", {"kind": "main", "type": "main"})
        kernel_proc.claim_lane("owner", os.path.join(self.home, "a.py"))
        kernel_proc.append("owner", {"kind": "tool", "tool_name": "Write"})
        os.unlink(kernel_proc.ptable_path())

    def test_an_absent_table_with_a_live_journal_is_a_fault(self):
        self.live_owner()
        table, dropped, fault = kernel_proc.read_ptable_detail()
        self.assertTrue(fault, "the table is gone and the machine is not empty")
        self.assertIn("absent", fault)
        self.assertIn("owner", fault, "and it names what is still running")
        self.assertEqual(table["processes"], {})
        self.assertEqual(dropped, [])
        self.assertFalse(kernel_proc.claim_lane("intruder",
                                                os.path.join(self.home, "a.py")),
                         "so the deletion buys the intruder nothing")

    def test_an_absent_table_with_no_journal_is_the_one_honest_empty_table(self):
        """The other half, and the one that keeps the rule from being "deny
        always". A first run, a wiped cache and every sandbox in this suite are
        genuinely empty machines, and they must stay allowed: a fail-closed rule
        that cannot tell a fresh install from a loss is a broken laptop."""
        self.assertFalse(os.path.exists(kernel_proc.ptable_path()))
        self.assertEqual(kernel_proc.read_ptable_detail(),
                         ({"version": 1, "processes": {}}, [], ""))
        self.assertEqual(kernel_proc.live_journal_pids(), [])

    def test_a_journal_that_is_expired_or_exited_holds_nothing_faulted(self):
        """Liveness is the existing definition, not a file count. A journal past
        the TTL and a journal carrying an `exit` line are both dead, so a table
        deleted next to them is a machine that really has nothing running."""
        self.live_owner()
        self.assertTrue(kernel_proc.read_ptable_detail()[2])

        self.age_journal("owner", kernel_proc.TTL + 300)
        self.assertEqual(kernel_proc.read_ptable_detail()[2], "",
                         "past the TTL it is not live and the table may be gone")

        self.age_journal("owner", 0)
        self.assertTrue(kernel_proc.read_ptable_detail()[2], "fresh again")
        kernel_proc.append("owner", {"kind": "exit", "status": "ok"})
        self.assertEqual(kernel_proc.read_ptable_detail()[2], "",
                         "an exited process is not holding anything either")

    def test_the_walk_stops_once_it_has_an_answer(self):
        """The caller needs "is anything alive here", not a census, and the
        number of files in that directory is chosen by whoever writes them."""
        for n in range(12):
            kernel_proc.append(f"p{n}", {"kind": "start"})
            kernel_proc.append(f"p{n}", {"kind": "tool", "tool_name": "Read"})
        self.assertEqual(len(kernel_proc.live_journal_pids()), 8)
        self.assertEqual(len(kernel_proc.live_journal_pids(limit=3)), 3)
        self.assertEqual(len(kernel_proc.live_journal_pids(limit=0)), 12)


class QaCycle4ReaderTest(SandboxHome):
    """The reader's half of QA cycle 4, one leg per finding.

    These are deliberately NOT the whole proof: what a second writer is allowed
    to do is decided at the gates, and that is pinned in
    test_tree_owner.QaCycle4, in the gates' own processes. What lives here is
    the discrimination the gate tests cannot give on their own, because several
    of these findings have two independent guards and a gate test passes on
    either one. Each test below dies when ITS OWN guard is removed.
    """

    def running_machine(self):
        """One live process holding one lane, which is what every shape below
        is about to claim does not exist."""
        kernel_proc.register("owner", {"kind": "main", "type": "main"})
        lane = os.path.join(self.home, "a.py")
        self.assertTrue(kernel_proc.claim_lane("owner", lane))
        return lane

    def test_f2_a_recursion_error_in_the_parser_is_a_fault_not_an_exception(self):
        """The reader's guard, alone. `json.load` on 9998 nested `[` raises
        RecursionError, a RuntimeError, so `except ValueError` and
        `except OSError` both missed it and it left the reader as an exception.
        The gates now deny around this call as well, so a gate test passes with
        either guard in place; this one fails if the reader stops catching it.
        """
        self.running_machine()
        with open(kernel_proc.ptable_path(), "w", encoding="utf-8") as fh:
            fh.write("[" * 9998 + "]" * 9998)
        self.assertLess(os.path.getsize(kernel_proc.ptable_path()),
                        kernel_proc.MAX_PTABLE_BYTES,
                        "the byte ceiling is not what stops this one")
        table, dropped, fault = kernel_proc.read_ptable_detail()
        self.assertIn("could not be parsed", fault)
        self.assertIn("RecursionError", fault)
        self.assertEqual(table["processes"], {})
        self.assertIn(kernel_proc.FAULT_KEY, table, "and it carries like any other")

    def test_f5_a_fifo_is_never_opened_and_the_read_returns(self):
        """`os.path.getsize` succeeds on a fifo and `open` blocks forever with
        no writer. The assertion is the TIMEOUT: this runs in its own process
        because a hang inside the test runner would take the suite with it, and
        a hang is exactly the failure being pinned."""
        os.makedirs(kernel_proc.kernel_dir(), exist_ok=True)
        os.mkfifo(kernel_proc.ptable_path())
        code = (f"import sys; sys.path.insert(0, {str(SCRIPTS)!r});"
                "import kernel_proc; print(kernel_proc.read_ptable_detail()[2])")
        env = dict(os.environ)
        env["HOME"] = self.home
        env["USERPROFILE"] = self.home
        cp = subprocess.run([sys.executable, "-c", code], capture_output=True,
                            text=True, env=env, timeout=30)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertIn("not a regular file", cp.stdout)
        self.assertIn("never opened", cp.stdout)

    def test_f3_the_journal_directory_is_evidence_and_it_can_be_attacked(self):
        """`live_journal_pids` returns `[]` on any OSError, so the evidence the
        deletion guard reads is removable by the same move it guards. The three
        shapes QA measured, each reaching a different errno, and the residual
        that is left after them."""
        self.running_machine()
        jdir = kernel_proc.journal_dir()
        os.unlink(kernel_proc.ptable_path())

        os.chmod(jdir, 0o000)
        try:
            self.assertIn("cannot be read", kernel_proc.read_ptable_detail()[2])
        finally:
            os.chmod(jdir, 0o755)

        import shutil as _shutil
        _shutil.rmtree(jdir)
        with open(jdir, "w", encoding="utf-8") as fh:
            fh.write("not a directory\n")
        self.assertIn("cannot be read", kernel_proc.read_ptable_detail()[2])

        os.unlink(jdir)
        self.assertTrue(kernel_proc._kernel_has_history(),
                        "the lock file every writer leaves is what says so")
        self.assertIn("is gone on a machine", kernel_proc.read_ptable_detail()[2])

        # The residual, stated where it is measured rather than in a footnote.
        for name in os.listdir(kernel_proc.kernel_dir()):
            os.unlink(os.path.join(kernel_proc.kernel_dir(), name))
        self.assertFalse(kernel_proc._kernel_has_history())
        self.assertEqual(kernel_proc.read_ptable_detail(),
                         ({"version": 1, "processes": {}}, [], ""),
                         "a HOME with nothing left is indistinguishable from a "
                         "wiped cache, and denying every fresh install is worse")

    def test_f4_a_deleted_journal_does_not_release_the_lane_it_recorded(self):
        """`_mtime` returns None, `_own_fresh` reads that as False and `is_live`
        reads dead, so the row stayed in the table and simply stopped owning
        anything. `lane_owner` asks the question the gate asks, so it is the one
        that has to treat a missing record as unknown rather than as dead."""
        lane = self.running_machine()
        self.assertEqual(kernel_proc.lane_owner(lane)[0], "owner")
        os.unlink(kernel_proc.journal_path("owner"))
        self.assertFalse(kernel_proc.is_live("owner"),
                         "liveness itself still reads dead, which is honest")
        self.assertEqual(kernel_proc.lane_owner(lane)[0], "owner",
                         "but the lane is held: a missing record is not a death")

    def test_f4_prune_keeps_the_row_and_faults_instead_of_freeing_it(self):
        """The second move: wait out the TTL and let one SessionStart do the
        rest. `prune` treated a row with no journal as dead past `registered_ts
        + TTL`, so the row went and the lane went with it. It is kept and the
        table faults, bounded by PRUNE_AFTER so it still expires on its own."""
        lane = self.running_machine()
        os.unlink(kernel_proc.journal_path("owner"))
        table = kernel_proc.read_ptable()
        table["processes"]["owner"]["registered_ts"] = time.time() - (kernel_proc.TTL + 60)
        kernel_proc._write_ptable(table)

        kernel_proc.register("newsess", {"kind": "main", "type": "main"})
        table, _dropped, fault = kernel_proc.read_ptable_detail()
        self.assertIn("owner", table["processes"], "the row survives the prune")
        self.assertIn("hold lanes with no journal", fault)
        self.assertIn("owner", fault)
        self.assertFalse(kernel_proc.claim_lane("intruder", lane),
                         "so the lane is not transferred either")

    def test_f4_the_keep_is_bounded_and_an_idle_row_still_ages_out(self):
        """The bound, and the one edit that separates it from the test above. A
        row with no journal and NO lane is an ordinary dead row: it prunes, and
        nothing faults. Without that, "any missing journal denies the machine"
        would be the rule, which is the broken-laptop version of the same idea.
        """
        kernel_proc.register("owner", {"kind": "main", "type": "main"})
        kernel_proc.register("idle", {"kind": "main", "type": "main"})
        os.unlink(kernel_proc.journal_path("idle"))
        table = kernel_proc.read_ptable()
        table["processes"]["idle"]["registered_ts"] = time.time() - (kernel_proc.TTL + 60)
        kernel_proc._write_ptable(table)

        kernel_proc.register("newsess", {"kind": "main", "type": "main"})
        table, _dropped, fault = kernel_proc.read_ptable_detail()
        self.assertNotIn("idle", table["processes"])
        self.assertEqual(fault, "")

        # AND THE FAULT IS BOUNDED, not just the row. Two defects lived in the
        # block this replaces, and cycle 5 C2 found both. It asserted the row's
        # absence and OMITTED `assertEqual(fault, "")`, the exclusion that makes
        # its own message ("a fault nobody clears must still expire on its own")
        # load-bearing, with the correct assertion sitting eleven lines above it
        # for the idle case. And its setup jumped from a healthy machine
        # straight to `registered_ts` past PRUNE_AFTER, so `prune` sent the row
        # to `dead` without ever setting a fault: adding the exclusion would
        # have passed against a machine that was never faulted. The sequence
        # here is the real one, fault first at TTL+60, expiry after.
        kernel_proc.claim_lane("owner", os.path.join(self.home, "a.py"))
        os.unlink(kernel_proc.journal_path("owner"))
        table = kernel_proc.read_ptable()
        table["processes"]["owner"]["registered_ts"] = time.time() - (kernel_proc.TTL + 60)
        kernel_proc._write_ptable(table)
        kernel_proc.register("newsess2", {"kind": "main", "type": "main"})
        self.assertIn("hold lanes with no journal",
                      kernel_proc.read_ptable_detail()[2],
                      "the fault has to be SET before its bound means anything")

        table = kernel_proc.read_ptable()
        table["processes"]["owner"]["registered_ts"] = time.time() - (kernel_proc.PRUNE_AFTER + 60)
        kernel_proc._write_ptable(table)
        kernel_proc.register("newsess3", {"kind": "main", "type": "main"})
        self.assertNotIn("owner", kernel_proc.read_ptable()["processes"])
        self.assertEqual(kernel_proc.read_ptable_detail()[2], "",
                         "a fault nobody clears must still expire on its own")

    def test_f6_lanes_that_are_not_lanes_make_the_row_unreadable(self):
        """Measured ALLOW on an otherwise perfect row for `lanes` as a string,
        as null and as a list of numbers: `lanes_of` coerced each to `[]`, the
        row forfeited the path it held, and nothing was dropped or faulted. An
        ABSENT `lanes` is the one shape that stays healthy, because it is what
        every row looks like between `register` and its first write."""
        lane = self.running_machine()
        # The file is re-read RAW each round: `read_ptable` drops the row this
        # test just wrote, so reading through the seam would lose it and the
        # second shape onward would be testing an empty table.
        with open(kernel_proc.ptable_path(), encoding="utf-8") as fh:
            healthy = json.load(fh)
        for bad in (lane, None, [12345], {}, [""], [lane, 3]):
            with self.subTest(lanes=bad):
                table = json.loads(json.dumps(healthy))
                table["processes"]["owner"]["lanes"] = bad
                kernel_proc._write_ptable(table)
                self.assertEqual(kernel_proc.read_ptable_detail()[1], ["owner"],
                                 "the row is dropped and NAMED")

        table = json.loads(json.dumps(healthy))
        table["processes"]["owner"] = {"pid": "owner", "registered_ts": time.time()}
        kernel_proc._write_ptable(table)
        self.assertEqual(kernel_proc.read_ptable_detail()[1], [],
                         "a row that has claimed nothing yet is healthy")


class RecoveryTextTest(SandboxHome):
    """QA cycle 3, F2. The text described the file's PRE-register shape while
    the deny it is attached to only persists into the POST-register one.

    By the time a human reads it a SessionStart has almost certainly fired, so
    `processes` is a valid object again and "repair `processes` to an object" is
    a no-op. What was left of the instruction was "delete the `_faulted` key",
    which taken literally clears the deny AND discards every row the fault
    carried: QA followed it and reproduced the lane transfer the change exists
    to prevent.
    """

    def faulted_after_a_register(self):
        """The state a human actually finds: rows lost, one SessionStart on top."""
        kernel_proc.register("owner", {"kind": "main", "type": "main"})
        kernel_proc.claim_lane("owner", os.path.join(self.home, "a.py"))
        with open(kernel_proc.ptable_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        data["processes"] = list(data["processes"].values())
        with open(kernel_proc.ptable_path(), "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        kernel_proc.register("newsess", {"kind": "main", "type": "main"})

    def test_the_text_describes_the_state_the_file_is_actually_in(self):
        self.faulted_after_a_register()
        text = kernel_proc.recovery()
        with open(kernel_proc.ptable_path(), encoding="utf-8") as fh:
            data = json.load(fh)

        self.assertIsInstance(data["processes"], dict,
                              "a register already repaired the shape")
        self.assertIn(f"{kernel_proc.FAULT_KEY}.rows", text,
                      "so the text has to name where the carried rows are")
        self.assertTrue(data[kernel_proc.FAULT_KEY]["rows"],
                        "and they really are there")
        self.assertIn(kernel_proc.QUARANTINE_PREFIX, text,
                      "the preserved copy was on no surface but the doctor")
        self.assertTrue(kernel_proc.quarantines(), "and it really is there too")
        self.assertIn(kernel_proc.journal_dir(), text,
                      "the `rm` half costs a second step now (F3)")

    def test_following_it_literally_keeps_the_lane_instead_of_transferring_it(self):
        """The whole point of naming `_faulted.rows`: the recovery that KEEPS
        information has to be the one a reader can follow. Restoring the rows
        and then deleting the key leaves the owner still holding its lane, so
        the intruder that was denied is still denied afterwards."""
        self.faulted_after_a_register()
        lane = os.path.join(self.home, "a.py")

        with open(kernel_proc.ptable_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        for row in data.pop(kernel_proc.FAULT_KEY)["rows"]:
            data["processes"][row["pid"]] = row
        with open(kernel_proc.ptable_path(), "w", encoding="utf-8") as fh:
            json.dump(data, fh)

        table, _dropped, fault = kernel_proc.read_ptable_detail()
        self.assertEqual(fault, "")
        self.assertEqual(kernel_proc.lane_owner(lane, table)[0], "owner",
                         "the lane survived the recovery, which is why it is "
                         "the one printed first")

    def test_the_text_says_what_deleting_the_key_alone_costs(self):
        """The half QA followed. It still works and it is still offered; what it
        may not do is read as the cheap option."""
        self.faulted_after_a_register()
        text = kernel_proc.recovery()
        self.assertIn("WITHOUT restoring the rows", text)
        self.assertIn("forgets every lane", text)

    def test_the_agent_proof_claim_says_what_is_verified_and_what_is_open(self):
        """A claim the mechanism does not support is the exact defect this
        change keeps correcting elsewhere. The reason for having no subcommand
        was stated as a fact: "a command an agent could run would be a command
        that clears its own gate". QA verified it for `rm`, `mv` and `>` and
        DEFEATED it with `python3 -c` and `ln -sf`, which the Bash gate's verb
        detection did not see.

        QA CYCLE 9 CLOSED THAT AND THIS TEST MOVED WITH IT. `python3 -c` and
        `ln -sf` at a kernel path are denied now (the floor is a named-path test
        rather than a verb list), so a pin on the words "INTERPRETER PATH IS
        OPEN" would be pinning a residual that no longer exists - the same
        defect one direction over. What is pinned instead is that the two named
        routes are labelled DENIED, and that the honest residual the new text
        keeps is still stated: the deny is a PARSE, so a path built by shell
        expansion this parser does not run still reaches the kernel directory.
        The gate-level half is `TheAgentProofClaimIsMeasured` in
        test_tree_owner.py, which runs those commands rather than reading about
        them.
        """
        doc = kernel_proc.recovery.__doc__
        self.assertIn("python3 -c", doc)
        self.assertIn("ln -sf", doc)
        self.assertIn("mkfifo", doc)
        self.assertNotIn("INTERPRETER PATH IS OPEN", doc,
                         "the residual is closed; the docstring may not still "
                         "advertise it")
        self.assertIn("the deny is a PARSE", doc,
                      "and what IS still open has to stay said")
        self.assertNotIn("a command an agent could run would be a command",
                         kernel_proc.recovery(),
                         "and the unverified version is not printed to anyone")


class QuarantineLedgerTest(SandboxHome):
    """The repair ledger beside the ptable: what it costs, and who it names.

    QA cycle 2, F2 and F3. The bound was on FILES only, so the size of each one
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

    def aged_copy(self, seconds):
        """One copy in the ledger with an mtime `seconds` in the past."""
        os.makedirs(kernel_proc.kernel_dir(), exist_ok=True)
        stamp = "aged%d" % seconds
        path = os.path.join(kernel_proc.kernel_dir(),
                            f"{kernel_proc.QUARANTINE_PREFIX}{stamp}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"ts": 0, "reason": "aged", "ptable": "x"}, fh)
        when = time.time() - seconds
        os.utime(path, (when, when))
        return path

    def test_a_copy_older_than_the_retention_window_is_swept(self):
        """QA cycle 3, F5. Bounded by count and bytes, a copy never expired at
        all: one corruption a year ago held `brain_doctor` at WARN forever, and
        no surface told the operator the files were safe to remove. The window
        is the journal window, because a copy is evidence about a moment and it
        should not outlive the journals that are the only other record of what
        was running at that moment."""
        stale = self.aged_copy(kernel_proc.PRUNE_AFTER + 3600)
        fresh = self.aged_copy(60)
        kernel_proc._trim_quarantines()
        kept = [p for _, p in kernel_proc.quarantines()]
        self.assertNotIn(stale, kept)
        self.assertIn(fresh, kept)

    def test_the_newest_survives_its_own_age(self):
        """The newest is always kept, whatever it weighs or how old it is:
        deleting the only record of the event would leave the doctor counting
        repairs it can no longer show."""
        only = self.aged_copy(kernel_proc.PRUNE_AFTER * 10)
        kernel_proc._trim_quarantines()
        self.assertEqual([p for _, p in kernel_proc.quarantines()], [only])

    def test_the_sweep_runs_on_the_register_path_not_only_on_a_new_repair(self):
        """A bound reached only from `_quarantine` fires only when a NEW copy
        arrives, which is the one moment nothing that matters has expired. So
        `prune_files` calls it, where every other retention window is enforced,
        and a machine that never corrupts its table again still ages the ledger.
        """
        stale = self.aged_copy(kernel_proc.PRUNE_AFTER + 3600)
        keep = self.aged_copy(60)
        kernel_proc.prune_files({"processes": {}})
        kept = [p for _, p in kernel_proc.quarantines()]
        self.assertNotIn(stale, kept)
        self.assertIn(keep, kept)

    def test_the_recovery_says_where_the_copies_are_and_that_deleting_is_safe(self):
        """The other half of F5: ageing them out fixes the doctor, it does not
        tell the operator anything. The one string every deny and both listings
        print has to name the path and say removing them is safe once read."""
        text = kernel_proc.recovery()
        self.assertIn(kernel_proc.QUARANTINE_PREFIX, text)
        self.assertIn(kernel_proc.kernel_dir(), text)
        self.assertIn("safe", text)

    def test_the_ledger_is_bounded_by_a_count(self):
        """The only bound on disk cost the ledger had, and nothing failed when
        it was removed (QA cycle 2, F4)."""
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
        """The collision loop, which nothing failed without (QA cycle 2, F4).
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
        """QA cycle 2, F3. The record carried `ts`, `reason` and the bytes, so
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
        failed when it was removed (QA cycle 2, F4). One repair is an accident
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
        """One repair EVENT, START TO FINISH: a value that is not an object goes
        in, a writer reads it, drops it, preserves what it overwrote, and the
        OPERATOR then clears the carried fault the way `recovery()` says.

        That last step is not decoration, it is what keeps this test about
        FREQUENCY. Since QA cycle 4 F1c a dropped row is carried forward as a
        fault, exactly like a table-level one, so without a repair between the
        events the doctor returns FAIL on the fault at its first branch and the
        three-in-24 h counter below is never reached. An operator who fixes the
        machine after each incident and finds a third one the same day is
        precisely the case that branch exists to catch.
        """
        with open(kernel_proc.ptable_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        data["processes"][name] = "not-a-row"
        with open(kernel_proc.ptable_path(), "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        kernel_proc.update_row("good", {"note": name})
        with open(kernel_proc.ptable_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data.pop(kernel_proc.FAULT_KEY)["reason"],
                         "1 unreadable row(s) dropped: %s" % name,
                         "the drop is carried forward, and this is the operator "
                         "clearing it; the preserved copies are what stay")
        with open(kernel_proc.ptable_path(), "w", encoding="utf-8") as fh:
            json.dump(data, fh)


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
        self.age_journal("gone", kernel_proc.PRUNE_AFTER + 3600)
        os.utime(kernel_proc.lock_path("gone"), (old, old))
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
        self.age_journal("dead", kernel_proc.PRUNE_AFTER + 3600)
        os.utime(kernel_proc.lock_path("dead"), (old, old))
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
        self.age_journal("orphaned", kernel_proc.PRUNE_AFTER - 3600)
        os.utime(kernel_proc.lock_path("orphaned"), (inside, inside))
        self.assertEqual(kernel_proc.prune_files(table), 0,
                         "inside the window the audit trail stays")
        self.assertTrue(os.path.exists(kernel_proc.journal_path("orphaned")))

        past = time.time() - (kernel_proc.PRUNE_AFTER + 3600)
        self.age_journal("orphaned", kernel_proc.PRUNE_AFTER + 3600)
        os.utime(kernel_proc.lock_path("orphaned"), (past, past))
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



class FaultClearsTest(SandboxHome):
    """QA cycle 5, C1 and C2: a fault could be SET and nothing anywhere removed
    it, on any path.

    Every test here names the thing that produces the DENY, `_faulted`, and
    asserts on that, because the pattern behind eleven findings in this PR was
    proofs that followed the object which was fixed (the row, the deletion, the
    registration) instead. The row expiring is not the fault expiring; the row
    was never what denied.
    """

    def faulted_machine(self):
        """One row holding a lane with its journal removed, aged past the TTL so
        the next register FAULTS on it. Returns the lane."""
        kernel_proc.register("owner", {"kind": "main", "type": "main"})
        lane = os.path.join(self.home, "a.py")
        self.assertTrue(kernel_proc.claim_lane("owner", lane))
        os.unlink(kernel_proc.journal_path("owner"))
        table = kernel_proc.read_ptable()
        table["processes"]["owner"]["registered_ts"] = time.time() - (kernel_proc.TTL + 60)
        kernel_proc._write_ptable(table)
        kernel_proc.register("s1", {"kind": "main", "type": "main"})
        self.assertIn("hold lanes with no journal",
                      kernel_proc.read_ptable_detail()[2])
        return lane

    def test_c1_the_recovery_the_gate_prints_is_the_one_that_works(self):
        """`recovery()` prescribes deleting the ROW for this fault. QA followed
        it verbatim and measured the machine still faulted before AND after the
        next register: the gate printed an instruction the operator had just
        executed."""
        self.faulted_machine()
        disk = json.load(open(kernel_proc.ptable_path(), encoding="utf-8"))
        disk["processes"].pop("owner")
        with open(kernel_proc.ptable_path(), "w", encoding="utf-8") as fh:
            json.dump(disk, fh)
        self.assertEqual(kernel_proc.read_ptable_detail()[2], "",
                         "removing the row is what recovery() says, so it must lift")
        kernel_proc.register("s2", {"kind": "main", "type": "main"})
        self.assertEqual(kernel_proc.read_ptable_detail()[2], "",
                         "and a SessionStart must not bring it back")

    def test_c1_the_key_is_actually_removed_from_the_file(self):
        """Not just unreported: the key LEAVES the file, so `octo ps` and the
        doctor stop printing a fault whose condition is gone."""
        self.faulted_machine()
        self.assertIn(kernel_proc.FAULT_KEY,
                      json.load(open(kernel_proc.ptable_path(), encoding="utf-8")))
        disk = json.load(open(kernel_proc.ptable_path(), encoding="utf-8"))
        disk["processes"].pop("owner")
        with open(kernel_proc.ptable_path(), "w", encoding="utf-8") as fh:
            json.dump(disk, fh)
        kernel_proc.register("s2", {"kind": "main", "type": "main"})
        self.assertNotIn(kernel_proc.FAULT_KEY,
                         json.load(open(kernel_proc.ptable_path(), encoding="utf-8")))

    def test_c1_the_blast_radius_is_the_whole_machine_while_it_stands(self):
        """Why C1 is a critical and not a nit: this fault denies a path no row
        has ever touched. Correct while the fault is true, and a permanent
        machine-wide lockout while nothing could clear it."""
        self.faulted_machine()
        untouched = os.path.join(self.home, "work", "solo", "x.py")
        self.assertTrue(kernel_proc.read_ptable_detail()[2],
                        "the deny reaches a tree nobody claimed")
        self.assertEqual(kernel_proc.lane_owner(untouched)[0], None,
                         "and it is not coming from a lane")

    def test_c1_restoring_the_journal_lifts_it_too(self):
        """The other half of the same condition, and the one edit that keeps
        this from being 'deleting rows clears faults'."""
        self.faulted_machine()
        kernel_proc.append("owner", {"kind": "tool", "tool_name": "Write"})
        self.assertEqual(kernel_proc.read_ptable_detail()[2], "")

    def test_c1_a_corrupt_table_fault_still_does_NOT_clear_itself(self):
        """The exclusion. A LATCHED fault is the F1 protection and it must stay
        exactly as sticky: rows that were lost cannot be re-derived, so nothing
        but a human clears it. Without this assertion 'faults now clear' would
        pass just as well by clearing all of them."""
        kernel_proc.register("owner", {"kind": "main", "type": "main"})
        kernel_proc.claim_lane("owner", os.path.join(self.home, "a.py"))
        with open(kernel_proc.ptable_path(), "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "processes": []}, fh)
        self.assertTrue(kernel_proc.read_ptable_detail()[2])
        for n in range(3):
            kernel_proc.register("s%d" % n, {"kind": "main", "type": "main"})
            self.assertTrue(kernel_proc.read_ptable_detail()[2],
                            "three SessionStarts do not clear a lost table")

    def test_c2_the_fault_expires_with_the_row_it_names(self):
        """"Bounded by PRUNE_AFTER, so a fault nobody clears still expires" was
        false: measured, the row pruned, the lane freed, `_faulted` stayed and
        the deny stayed. The bound applied to the row, and the row is not what
        denies."""
        self.faulted_machine()
        table = kernel_proc.read_ptable()
        table["processes"]["owner"]["registered_ts"] = time.time() - (kernel_proc.PRUNE_AFTER + 60)
        kernel_proc._write_ptable(table)
        kernel_proc.register("s2", {"kind": "main", "type": "main"})
        disk = json.load(open(kernel_proc.ptable_path(), encoding="utf-8"))
        self.assertNotIn("owner", disk["processes"], "the row expires")
        self.assertEqual(kernel_proc.read_ptable_detail()[2], "",
                         "and so does the thing that was denying")


class SiblingRegisterRaceTest(SandboxHome):
    """QA cycle 5, C3: two SessionStart hooks on a table-less machine faulted
    each other, and (before C1) nothing could ever clear it. The trigger is a
    first run with two terminals, and it is the state the documented
    `rm ptable.json` recovery puts the machine into, so recovery could loop."""

    def test_c3_a_siblings_brand_new_journal_is_not_a_lost_record(self):
        os.makedirs(kernel_proc.journal_dir(), exist_ok=True)
        kernel_proc.append("sessB", {"kind": "start", "type": "main"})   # mid-register
        kernel_proc.register("sessA", {"kind": "main", "type": "main"})
        self.assertEqual(kernel_proc.read_ptable_detail()[2], "",
                         "a registration in flight holds no lane")

    def test_c3_a_journal_that_has_WORKED_still_faults(self):
        """The exclusion, one edit away: the same absent table beside a journal
        with a `tool` line in it is the real loss and still denies. Without
        this, C3's fix would read as 'stop faulting on deletion'."""
        os.makedirs(kernel_proc.journal_dir(), exist_ok=True)
        kernel_proc.append("victim", {"kind": "start", "type": "main"})
        kernel_proc.append("victim", {"kind": "tool", "tool_name": "Write"})
        kernel_proc.register("sessA", {"kind": "main", "type": "main"})
        os.unlink(kernel_proc.ptable_path())
        fault = kernel_proc.read_ptable_detail()[2]
        self.assertIn("victim", fault)

    def test_c3_the_race_does_not_survive_the_registrations(self):
        """Both siblings register, and the machine ends healthy with both rows:
        the ptable lock serializes them, so the second reads the first's
        published row instead of losing it."""
        os.makedirs(kernel_proc.journal_dir(), exist_ok=True)
        kernel_proc.append("sessB", {"kind": "start", "type": "main"})
        kernel_proc.register("sessA", {"kind": "main", "type": "main"})
        kernel_proc.register("sessB", {"kind": "main", "type": "main"})
        table, dropped, fault = kernel_proc.read_ptable_detail()
        self.assertEqual(fault, "")
        self.assertEqual(sorted(table["processes"]), ["sessA", "sessB"])


class BackdatedJournalTest(SandboxHome):
    """QA cycle 5, C4: F4 was one syscall deep. `lane_owner` guarded DELETION
    (`_mtime is None`) and `_own_fresh` was mtime-only, so one `touch` freed a
    live holder's lane with nothing deleted, nothing edited and the chain
    intact. `touch` is already in the Bash gate's kernel-state verb list, so the
    threat model named the move before the reader did."""

    def held_lane(self):
        kernel_proc.register("owner", {"kind": "main", "type": "main"})
        lane = os.path.join(self.home, "work", "tree", "a.py")
        self.assertTrue(kernel_proc.claim_lane("owner", lane))
        kernel_proc.append("owner", {"kind": "tool", "tool_name": "Write"})
        return lane

    def test_c4_touching_the_journal_does_not_free_the_lane(self):
        lane = self.held_lane()
        self.assertEqual(kernel_proc.lane_owner(lane, ignore="intruder")[0], "owner")
        old = time.time() - (kernel_proc.TTL + 600)
        os.utime(kernel_proc.journal_path("owner"), (old, old))   # the whole attack
        self.assertEqual(kernel_proc.lane_owner(lane, ignore="intruder")[0], "owner",
                         "the chained record says it is seconds old")
        self.assertIn("owner", kernel_proc.live_journal_pids())
        self.assertTrue(kernel_proc.is_live("owner"))
        # And the AGE the deny prints comes from the record too, so the verdict
        # and its explanation do not disagree in front of the operator.
        self.assertLess(kernel_proc.process_age("owner"), kernel_proc.TTL)

    def test_c4_touching_it_past_PRUNE_AFTER_does_not_prune_the_row(self):
        """The cheaper half of the same move: prune read the mtime alone too, so
        backdating a week freed the lane at the next SessionStart without the
        lane check ever being consulted."""
        self.held_lane()
        old = time.time() - (kernel_proc.PRUNE_AFTER + 600)
        os.utime(kernel_proc.journal_path("owner"), (old, old))
        kernel_proc.register("newsess", {"kind": "main", "type": "main"})
        self.assertIn("owner", kernel_proc.read_ptable()["processes"])

    def test_c4_a_process_that_really_went_quiet_still_expires(self):
        """The exclusion, and the one edit: age the RECORD as well as the mtime
        and the lane frees exactly as it always did. Without this the fix would
        pass just as well by never expiring anything."""
        lane = self.held_lane()
        self.age_journal("owner", kernel_proc.TTL + 600)
        self.assertEqual(kernel_proc.lane_owner(lane, ignore="intruder")[0], None)
        self.assertFalse(kernel_proc.is_live("owner"))

    def test_c4_a_future_record_is_skew_not_liveness(self):
        """The mtime rule applied to the record, so the second source cannot be
        used to fake life either."""
        lane = self.held_lane()
        self.age_journal("owner", -(kernel_proc.FUTURE_SKEW + 600))
        self.assertEqual(kernel_proc.lane_owner(lane, ignore="intruder")[0], None)


class WipeResidualTest(SandboxHome):
    """QA cycle 5, M1. The doc claimed the only indistinguishable state was a
    full kernel-directory wipe. Four cheaper ones allowed on both gates with
    `.ptable.lock` present and every history marker intact."""

    def running_machine(self):
        kernel_proc.register("owner", {"kind": "main", "type": "main"})
        kernel_proc.claim_lane("owner", os.path.join(self.home, "a.py"))
        kernel_proc.append("owner", {"kind": "tool", "tool_name": "Write"})

    def test_m1_removing_the_table_and_sweeping_the_journals_is_a_fault(self):
        """State 1: `rm ptable.json journal/*.jsonl`. The directory stays, so the
        journal-evidence guard reads it as usable and no journal reads live. What
        is left is that the kernel never deletes its own table."""
        self.running_machine()
        os.unlink(kernel_proc.ptable_path())
        for name in os.listdir(kernel_proc.journal_dir()):
            os.unlink(os.path.join(kernel_proc.journal_dir(), name))
        fault = kernel_proc.read_ptable_detail()[2]
        self.assertIn("journal directory", fault)
        self.assertIn("empty on a machine", fault)

    def test_m1_a_real_fresh_install_still_allows(self):
        """The one edit that keeps the rule above from being 'deny every first
        run': a HOME that has never run a hook has no kernel directory at all,
        so there is no history to contradict the absence."""
        self.assertFalse(os.path.exists(kernel_proc.kernel_dir()))
        self.assertEqual(kernel_proc.read_ptable_detail(),
                         ({"version": 1, "processes": {}}, [], ""))

    def test_m1_the_sweep_fault_lifts_when_a_journal_comes_back(self):
        """Its bound, asserted rather than assumed: a condition fault, true only
        while there is no record left to read."""
        self.running_machine()
        os.unlink(kernel_proc.ptable_path())
        for name in os.listdir(kernel_proc.journal_dir()):
            os.unlink(os.path.join(kernel_proc.journal_dir(), name))
        self.assertTrue(kernel_proc.read_ptable_detail()[2])
        kernel_proc.register("newsess", {"kind": "main", "type": "main"})
        self.assertEqual(kernel_proc.read_ptable_detail()[2], "")

    def test_m1_backdated_journals_do_not_buy_a_fresh_install(self):
        """States 3 and 4, both closed by C4: `rm ptable.json` or an empty table
        beside journals whose mtime was moved back. Nothing is deleted, so the
        journal-evidence guard sees a healthy directory; the chained record is
        what says those processes are still running."""
        for empty_table in (False, True):
            with self.subTest(empty_table=empty_table):
                self.setUp()
                self.running_machine()
                if empty_table:
                    kernel_proc._write_ptable({"version": 1, "processes": {}})
                else:
                    os.unlink(kernel_proc.ptable_path())
                old = time.time() - (kernel_proc.TTL + 600)
                for name in os.listdir(kernel_proc.journal_dir()):
                    path = os.path.join(kernel_proc.journal_dir(), name)
                    os.utime(path, (old, old))
                self.assertIn("owner", kernel_proc.read_ptable_detail()[2])

    def test_m1_an_empty_table_with_swept_journals_is_the_same_sweep(self):
        """State 2, the same rule as state 1 and the reason it is keyed on the
        RESULT: writing an empty table instead of removing it changes which
        syscall noticed, and nothing else."""
        self.running_machine()
        kernel_proc._write_ptable({"version": 1, "processes": {}})
        for name in os.listdir(kernel_proc.journal_dir()):
            os.unlink(os.path.join(kernel_proc.journal_dir(), name))
        self.assertIn("empty on a machine", kernel_proc.read_ptable_detail()[2])

    def test_m1_a_machine_whose_processes_went_quiet_still_allows(self):
        """The exclusion, and the one edit that keeps the two rules above from
        being "deny every idle laptop": the journals are still THERE, they are
        just old. That is what a quiet machine looks like; an empty directory is
        what a sweep looks like."""
        self.running_machine()
        os.unlink(kernel_proc.ptable_path())
        self.age_journal("owner", kernel_proc.TTL + 600)
        self.assertEqual(kernel_proc.read_ptable_detail(),
                         ({"version": 1, "processes": {}}, [], ""))


class JournalDirectoryWithRowsTest(SandboxHome):
    """QA cycle 5, M2. A damaged journal directory with an INTACT table denied
    correctly and described the state wrongly: a LANE deny naming a dead pid as
    "never journaled", advising the operator to wait for it to exit, with no
    mention that the directory every liveness answer comes from was gone.
    F3's fault only ran on the zero-rows path."""

    def running_machine(self):
        kernel_proc.register("owner", {"kind": "main", "type": "main"})
        lane = os.path.join(self.home, "work", "tree", "a.py")
        kernel_proc.claim_lane("owner", lane)
        kernel_proc.append("owner", {"kind": "tool", "tool_name": "Write"})
        return lane

    def test_m2_a_missing_journal_directory_faults_with_rows_present(self):
        self.running_machine()
        import shutil as _shutil
        _shutil.rmtree(kernel_proc.journal_dir())
        table, dropped, fault = kernel_proc.read_ptable_detail()
        self.assertIn("journal directory", fault)
        self.assertIn("owner", table["processes"],
                      "the rows are intact and stay where they are")

    def test_m2_a_file_or_an_unreadable_directory_faults_too(self):
        import shutil as _shutil
        for how in ("file", "chmod"):
            with self.subTest(how=how):
                self.setUp()
                self.running_machine()
                jdir = kernel_proc.journal_dir()
                if how == "file":
                    _shutil.rmtree(jdir)
                    with open(jdir, "w", encoding="utf-8") as fh:
                        fh.write("x")
                else:
                    os.chmod(jdir, 0o000)
                try:
                    self.assertIn("journal directory",
                                  kernel_proc.read_ptable_detail()[2])
                finally:
                    if how == "chmod":
                        os.chmod(jdir, 0o755)

    def test_m2_it_lifts_when_the_directory_comes_back(self):
        """A condition fault, so there is no key for the operator to delete."""
        self.running_machine()
        import shutil as _shutil
        _shutil.rmtree(kernel_proc.journal_dir())
        kernel_proc.register("newsess", {"kind": "main", "type": "main"})
        self.assertEqual(kernel_proc.read_ptable_detail()[2], "")
        self.assertNotIn(kernel_proc.FAULT_KEY,
                         json.load(open(kernel_proc.ptable_path(), encoding="utf-8")))

    def test_m2_the_healthy_machine_is_the_one_edit_away(self):
        """The exclusion: the same table with its journal directory in place
        faults on nothing."""
        self.running_machine()
        self.assertEqual(kernel_proc.read_ptable_detail()[2], "")

    def test_m2_the_lane_deny_says_the_journal_is_gone(self):
        """The half that is about the MESSAGE. A lane held by a row with no
        journal does not free on silence, because silence is measured out of
        the file that is missing, and both gates used to advise waiting for it."""
        self.running_machine()
        os.unlink(kernel_proc.journal_path("owner"))
        text = kernel_proc.lane_recovery("owner")
        self.assertIn("NO JOURNAL", text)
        self.assertNotIn("of silence", text)
        kernel_proc.append("owner", {"kind": "tool", "tool_name": "Write"})
        self.assertIn("of silence", kernel_proc.lane_recovery("owner"),
                      "and a busy holder keeps the ordinary advice")


class UnreadableRecordTest(SandboxHome):
    """QA cycle 6, C-A. The third appearance of one defect: a reader that could
    not read something returned the value that also means "nothing is here", and
    the caller chose the permissive branch off it.

    `_record_ts` answered None for an unparseable tail, a non-dict tail and a
    missing `ts`, and `_quiet_for` then fell back to the RAW MTIME, which reads
    a backdated file as DEATH. `{"ts":1}` was worse, because it parsed: a number
    saying 1970, taken as a process that went quiet 56 years ago. Every one of
    these leaves the existing chain untouched and costs one appended line, and
    nothing on this path calls `verify()`.
    """

    def held_lane(self):
        kernel_proc.register("owner", {"kind": "main", "type": "main"})
        lane = os.path.join(self.home, "work", "tree", "a.py")
        self.assertTrue(kernel_proc.claim_lane("owner", lane))
        kernel_proc.append("owner", {"kind": "tool", "tool_name": "Write"})
        return lane

    def tear(self, pid, tail: bytes):
        """Append `tail` and backdate the mtime: the measured attack, verbatim."""
        path = kernel_proc.journal_path(pid)
        with open(path, "ab") as fh:
            fh.write(tail)
        old = time.time() - (kernel_proc.TTL + 600)
        os.utime(path, (old, old))

    def test_ca_an_unreadable_tail_plus_a_touch_does_not_free_the_lane(self):
        for tail in (b"not-json\n", b'{"ts":1}\n', b'{"ts":null}\n', b"[]\n"):
            with self.subTest(tail=tail):
                self.setUp()
                lane = self.held_lane()
                self.tear("owner", tail)
                self.assertIs(kernel_proc._quiet_for("owner", time.time()),
                              kernel_proc.UNKNOWN)
                self.assertTrue(kernel_proc._own_fresh("owner", time.time(),
                                                       kernel_proc.TTL))
                self.assertEqual(kernel_proc.lane_owner(lane, ignore="x")[0], "owner")

    def test_ca_the_age_the_deny_prints_says_unknown_rather_than_never(self):
        """-1 means "never journaled" to both gates. A torn record is a process
        that DID journal, so it gets its own answer instead of borrowing one."""
        self.held_lane()
        self.tear("owner", b"not-json\n")
        age = kernel_proc.process_age("owner")
        self.assertNotEqual(age, age, "NaN, not -1 and not a number")

    def test_ca_a_tail_that_contradicts_line_zero_is_unknown(self):
        """The ANCHOR check. `append` copies `start_ts` forward unchanged, so a
        tail whose `start_ts` disagrees with line 0's is not this kernel's line.
        Without it, a forger backdates `start_ts` alongside `ts` and the shape
        check passes."""
        self.held_lane()
        path = kernel_proc.journal_path("owner")
        with open(path, encoding="utf-8") as fh:
            lines = [l for l in fh.read().split("\n") if l.strip()]
        rec = json.loads(lines[-1])
        rec["ts"] = rec["start_ts"] = time.time() - (kernel_proc.TTL + 600)
        lines[-1] = json.dumps(rec, separators=(",", ":"))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        old = time.time() - (kernel_proc.TTL + 600)
        os.utime(path, (old, old))
        self.assertIs(kernel_proc._quiet_for("owner", time.time()),
                      kernel_proc.UNKNOWN)

    def test_ca_an_appended_line_dated_before_its_own_start_ts_is_unknown(self):
        """RENAMED IN CYCLE 7, because the name was a claim this test never
        measured. It was called `..._a_tail_older_than_the_line_before_it_...`
        and presented as the DIRECTION check; the forged line copies line 0
        (whose `start_ts` is seconds old) and then backdates `ts` past TTL, so
        it fails SHAPE - `ts` predates its own `start_ts` - and never reaches a
        direction check at all. QA proved the masking with a double mutant:
        deleting SHAPE and DIRECTION together kills it, deleting DIRECTION alone
        does not.

        So it keeps the coverage it actually has, which is real (SHAPE at the
        file level, through `_quiet_for`, rather than as a unit), and DIRECTION
        is measured where it can be isolated:
        `AppendMonotoneReaderTest.test_c7_two_appended_lines_plus_a_touch_...`,
        which is the attack this one was believed to cover."""
        self.held_lane()
        path = kernel_proc.journal_path("owner")
        with open(path, encoding="utf-8") as fh:
            head = json.loads(fh.read().split("\n")[0])
        forged = dict(head)
        forged.update({"seq": 99, "kind": "tool",
                       "ts": time.time() - (kernel_proc.TTL + 600)})
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(forged, separators=(",", ":")) + "\n")
        old = time.time() - (kernel_proc.TTL + 600)
        os.utime(path, (old, old))
        self.assertIs(kernel_proc._quiet_for("owner", time.time()),
                      kernel_proc.UNKNOWN)

    def test_ca_the_exclusion_a_coherently_quiet_journal_still_expires(self):
        """The half that makes the rule a measurement and not an appetite for
        denying: a journal whose WHOLE history says it went quiet frees its lane
        on schedule. Without this, "any journal I cannot read denies the
        machine" would be the shipped rule."""
        lane = self.held_lane()
        self.age_journal("owner", kernel_proc.TTL + 600)
        self.assertIsInstance(kernel_proc._quiet_for("owner", time.time()), float)
        self.assertFalse(kernel_proc._own_fresh("owner", time.time(), kernel_proc.TTL))
        self.assertIsNone(kernel_proc.lane_owner(lane, ignore="x")[0])

    def test_ca_prune_bounds_an_unknown_by_the_row_and_not_by_the_journal(self):
        """TTL and PRUNE_AFTER answer DIFFERENTLY here, and that is deliberate.
        Liveness holds on UNKNOWN, so expiry has to have a clock or a torn
        journal never expires and `>> not-json` becomes a permanent denial of
        service on that tree. The clock is the ROW's `registered_ts`, which is
        in the ptable, not in the journal the writer just tore."""
        self.held_lane()
        self.tear("owner", b"not-json\n")
        kernel_proc.register("newsess", {"kind": "main", "type": "main"})
        self.assertIn("owner", kernel_proc.read_ptable()["processes"],
                      "a torn journal does not expire the row on the attacker's clock")

        table = kernel_proc.read_ptable()
        table["processes"]["owner"]["registered_ts"] = \
            time.time() - (kernel_proc.PRUNE_AFTER + 600)
        kernel_proc._write_ptable(table)
        kernel_proc.register("newsess2", {"kind": "main", "type": "main"})
        self.assertNotIn("owner", kernel_proc.read_ptable()["processes"],
                         "but it DOES expire, on the clock the journal cannot reach")

    def test_ca_a_row_whose_registration_time_is_unreadable_is_kept(self):
        """An UNKNOWN age on an UNKNOWN clock has nothing to expire against, so
        it is kept. `float(ent.get('registered_ts') or 0)` used to read a
        garbage value as 0, which on every clock in this file means infinitely
        old, and raised ValueError inside the ptable lock on the way there."""
        self.held_lane()
        self.tear("owner", b"not-json\n")
        table = kernel_proc.read_ptable()
        table["processes"]["owner"]["registered_ts"] = "not-a-number"
        kernel_proc._write_ptable(table)
        kernel_proc.register("newsess", {"kind": "main", "type": "main"})
        self.assertIn("owner", kernel_proc.read_ptable()["processes"])


class TruncatedJournalTest(SandboxHome):
    """QA cycle 6, C-B. The C3 filter reads a property of a FILE, and the file
    is attacker-writable: truncating a live holder's journal to its own first
    line copies the start line verbatim, so it stays genuine and chain-valid
    while the journal reads as "a registration in flight" and is skipped.
    `truncate -s 0` reaches the same skip through the zero-byte leg. With the
    table emptied, that is the silent allow-everything machine `_absent_table`
    exists to stop."""

    def running_machine(self):
        kernel_proc.register("owner", {"kind": "main", "type": "main"})
        kernel_proc.claim_lane("owner", os.path.join(self.home, "a.py"))
        kernel_proc.append("owner", {"kind": "tool", "tool_name": "Write"})
        # A holder that has been running a while, which is what a holder looks
        # like. The truncation below then sets the mtime to NOW.
        kernel_proc.backdate_journal(kernel_proc.journal_path("owner"),
                                     kernel_proc.START_ONLY_GRACE + 600)

    def truncate(self, pid, to_zero=False):
        path = kernel_proc.journal_path(pid)
        with open(path, "rb") as fh:
            first = fh.read().split(b"\n")[0]
        with open(path, "wb") as fh:
            fh.write(b"" if to_zero else first + b"\n")
        os.utime(path, None)

    def test_cb_a_start_only_journal_older_than_the_grace_reads_live(self):
        self.running_machine()
        self.truncate("owner")
        self.assertFalse(kernel_proc.has_work_trace("owner"),
                         "the setup really does reach the C3 branch")
        self.assertIn("owner", kernel_proc.live_journal_pids())

    def test_cb_a_zero_byte_journal_reads_live_too(self):
        """The other door into the same skip: `has_work_trace` returns False for
        an empty file, and a file with no `start_ts` in it has no age to be
        young by, so it is UNKNOWN and counted."""
        self.running_machine()
        self.truncate("owner", to_zero=True)
        self.assertIn("owner", kernel_proc.live_journal_pids())

    def test_cb_the_emptied_table_faults_instead_of_reading_fresh(self):
        self.running_machine()
        self.truncate("owner")
        kernel_proc._write_ptable({"version": 1, "processes": {}})
        fault = kernel_proc.read_ptable_detail()[2]
        self.assertIn("read live", fault)
        self.assertFalse(kernel_proc.claim_lane("intruder",
                                                os.path.join(self.home, "a.py")))

    def test_cb_the_exclusion_a_real_registration_in_flight_still_allows(self):
        """C3 itself, and it must keep working: two SessionStart hooks on a
        table-less machine, `register` writing its journal before it takes the
        ptable lock, the sibling's brand-new start line beside it. That is a
        first run with two terminals and the documented `rm ptable.json`
        recovery, so counting it produced a fault that was false."""
        kernel_proc.register("owner", {"kind": "main", "type": "main"})
        self.assertFalse(kernel_proc.has_work_trace("owner"))
        self.assertEqual(kernel_proc.live_journal_pids(), [],
                         "a start line written seconds ago is a race, not a truncation")

    def test_cb_the_grace_is_read_off_line_zero_and_not_off_the_mtime(self):
        """The direction the bound must not be gameable in: an attacker wants
        the SKIP, and the mtime is the field one syscall sets. Touching a
        truncated journal forward must not buy the in-flight grace."""
        self.running_machine()
        self.truncate("owner")
        os.utime(kernel_proc.journal_path("owner"), None)
        self.assertFalse(kernel_proc._registration_in_flight("owner", time.time()))


class CarrierKindTest(SandboxHome):
    """QA cycle 6, M-C, and a literal recurrence of
    `lesson_unsigned_input_must_not_select_the_trusted_check` (PR #282): an
    editable field decided WHICH verification ran. A genuine `latched` carrier
    flipped on disk to `zero-rows` with `pids: []` re-derived vacuously, the
    gates allowed, and `_publish` popped the key and deleted the evidence."""

    def machine(self):
        kernel_proc.register("owner", {"kind": "main", "type": "main"})
        kernel_proc.claim_lane("owner", os.path.join(self.home, "a.py"))
        kernel_proc.append("owner", {"kind": "tool", "tool_name": "Write"})

    def carry(self, **fields):
        table = kernel_proc.read_ptable()
        carrier = {"reason": "rows lost", "ts": time.time(), "kind": "latched",
                   "pids": [], "count": 0, "rows": None}
        carrier.update(fields)
        table[kernel_proc.FAULT_KEY] = carrier
        kernel_proc._write_ptable(table)
        return carrier

    def test_mc_a_weaker_kind_with_no_pids_does_not_resolve(self):
        self.machine()
        self.carry(kind="zero-rows", pids=[])
        self.assertTrue(kernel_proc.read_ptable_detail()[2],
                        "the fault still stands")
        kernel_proc.register("newsess", {"kind": "main", "type": "main"})
        with open(kernel_proc.ptable_path(), encoding="utf-8") as fh:
            table = json.load(fh)
        self.assertIn(kernel_proc.FAULT_KEY, table,
                      "and the evidence is not deleted by the next writer")

    def test_mc_the_exclusion_a_real_condition_fault_still_lifts(self):
        """One edit, `pids`. A `zero-rows` fault that names a pid with no
        journal beside it IS resolved, and it has to lift or the whole condition
        machinery is a lockout again (C1)."""
        self.machine()
        self.carry(kind="zero-rows", pids=["ghost"])
        self.assertFalse(kernel_proc.read_ptable_detail()[2])

    def test_mc_a_kind_this_module_never_writes_reads_as_latched(self):
        self.machine()
        carrier = self.carry(kind="not-a-kind", pids=["ghost"])
        self.assertEqual(kernel_proc._carrier_kind(carrier), kernel_proc.FAULT_LATCHED)
        self.assertTrue(kernel_proc.read_ptable_detail()[2])

    def test_mc_a_carrier_from_before_this_branch_reads_as_latched(self):
        """The upgrade path, named rather than discovered: a carrier written
        before `kind` existed has none, so it is the strongest kind. Fail-closed,
        and it turns an old prune-written `lost-lanes` fault into one a human
        clears."""
        self.machine()
        table = kernel_proc.read_ptable()
        table[kernel_proc.FAULT_KEY] = {"reason": "old carrier", "ts": time.time()}
        kernel_proc._write_ptable(table)
        self.assertEqual(kernel_proc.fault_kind(kernel_proc.read_ptable_detail()[0]),
                         kernel_proc.FAULT_LATCHED)

    def test_mc_a_present_but_shapeless_carrier_is_a_fault(self):
        """`data.get(FAULT_KEY)` returned None for a table with no fault AND for
        `"_faulted": null`, and the same collapse ran for 0, "" and []. The key
        is written as an object with a reason or not written, so its PRESENCE is
        the fault."""
        for value in (None, 0, "", [], {}):
            with self.subTest(value=value):
                self.setUp()
                self.machine()
                table = kernel_proc.read_ptable()
                table[kernel_proc.FAULT_KEY] = value
                kernel_proc._write_ptable(table)
                self.assertTrue(kernel_proc.read_ptable_detail()[2],
                                "a value nobody can read is not 'nothing is wrong'")

    def test_mc_no_kind_resolves_while_the_journals_are_unusable(self):
        """The derived precondition, asked for every kind and read off disk
        without touching the carrier: the journals are the evidence every
        re-derivation leans on."""
        self.machine()
        carrier = self.carry(kind="zero-rows", pids=["ghost"])
        self.assertTrue(kernel_proc.fault_resolved(carrier, kernel_proc.read_ptable()))
        shutil.rmtree(kernel_proc.journal_dir(), ignore_errors=True)
        self.assertFalse(kernel_proc.fault_resolved(carrier, kernel_proc.read_ptable()))

    def test_a_lifted_fault_leaves_a_line_in_the_journal(self):
        """The other half of a ledger that only ever recorded the SETTING. A set
        fault quarantines, denies and FAILs the doctor; a cleared one used to
        leave nothing at all."""
        self.machine()
        self.carry(kind="zero-rows", pids=["ghost"])
        kernel_proc.register("newsess", {"kind": "main", "type": "main"})
        lines = [l for l in kernel_proc.read_journal("newsess") if l]
        lifted = [l for l in lines if l.get("kind") == "fault"]
        self.assertTrue(lifted, "the lift is recorded")
        self.assertEqual(lifted[0]["fault"], "lifted")
        self.assertEqual(lifted[0]["fault_kind"], kernel_proc.FAULT_ZERO_ROWS)


class AppendMonotoneReaderTest(SandboxHome):
    """QA cycle 7, and the fourth appearance of C-A wearing a fourth coat.

    Cycle 6 shipped a reader that checked the LAST record in an 8 KiB tail
    window against the two lines around it, and the commit claimed a forgery
    now cost rewriting the file. QA walked through all three of its guards with
    two APPENDED lines, each copying line 0's `start_ts` with `ts` set equal to
    it, plus one `os.utime`: shape held, anchor held, and the pairwise
    direction check compared two lines that were BOTH the attacker's. A holder
    that had worked 0 s ago read as quiet for 1200 s and both gates allowed the
    intruder onto its lane.

    Two more measurements say why neither obvious patch was the fix. The CHAIN
    does not close it: `prev` is an unkeyed sha256, so recomputing it is one
    more expression in the same `python3 -c`, and with the chain recomputed
    `verify()` returns 0 while the lane still transfers. The WINDOW does not
    close it either: three appended lines of 3900 bytes evict every real record
    from the 8 KiB tail, so a windowed guard reads only what the attacker put
    there.

    So the reader stopped asking "is the last record well-formed" and started
    answering the FRESHEST credible age in the WHOLE file. The kernel's own
    writers only append; appending can only add a candidate, and another
    candidate can only make the answer NEWER. There is no line that can be
    appended to make it say "older".

    EVERY TEST BELOW ISOLATES ONE GUARD. Cycle 7 found six of twelve mutants
    surviving a green suite because each existing fixture tripped several
    guards at once, so each one died to a neighbour or to nothing. These are
    built so that deleting the guard they name fails THIS test and deleting any
    other guard does not.
    """

    def held_lane(self):
        kernel_proc.register("owner", {"kind": "main", "type": "main"})
        lane = os.path.join(self.home, "work", "tree", "a.py")
        self.assertTrue(kernel_proc.claim_lane("owner", lane))
        kernel_proc.append("owner", {"kind": "tool", "tool_name": "Write"})
        return lane

    def rewrite(self, pid, recs):
        """Write `recs` as a correctly chained journal. The attacker computes
        the chain too, so a test that leaves it broken measures the chain and
        not the guard it names."""
        path = kernel_proc.journal_path(pid)
        out, prev = [], None
        for rec in recs:
            rec = dict(rec, prev=prev)
            raw = json.dumps(rec, separators=(",", ":")).encode()
            out.append(raw)
            prev = hashlib.sha256(raw).hexdigest()
        with open(path, "wb") as fh:
            fh.write(b"\n".join(out) + b"\n")
        return path

    # ── DIRECTION ───────────────────────────────────────────────────────────

    def test_c7_two_appended_lines_plus_a_touch_do_not_free_the_lane(self):
        """THE MEASURED BREAK, verbatim, and the DIRECTION guard is the only
        thing that catches it.

        Both appended lines copy line 0's `start_ts` and set `ts` equal to it,
        so SHAPE passes (`ts` does not predate its own `start_ts`) and ANCHOR
        passes (that `start_ts` IS line 0's). Only the step backwards from the
        real record at `now` to the forged record at `start_ts` is wrong, and
        only a direction check that reaches past the attacker's own lines sees
        it. The `os.utime` is not decoration: without a stale mtime `_quiet_for`
        short-circuits and never reads the record at all, which is why QA's
        matrix has five rows and neither ingredient does anything alone.
        """
        lane = self.held_lane()
        path = kernel_proc.journal_path("owner")
        self.assertTrue(kernel_proc.forge_journal(path, "tail"))
        self.assertIs(kernel_proc._quiet_for("owner", time.time()),
                      kernel_proc.UNKNOWN)
        self.assertTrue(kernel_proc._own_fresh("owner", time.time(),
                                               kernel_proc.TTL))
        self.assertEqual(kernel_proc.lane_owner(lane, ignore="x")[0], "owner",
                         "the holder keeps its lane; the intruder is denied")

    def test_c7_the_chain_recomputed_does_not_buy_the_lane_either(self):
        """`forge_journal` chains its forgeries correctly, so this states the
        measurement rather than assuming it: the journal VERIFIES and is still
        refused. A fix that called `verify()` here would have passed the shape
        QA happened to build (it copied `prev` verbatim) and failed this one."""
        self.held_lane()
        path = kernel_proc.journal_path("owner")
        self.assertTrue(kernel_proc.forge_journal(path, "tail"))
        self.assertEqual(kernel_proc.verify("owner"), 0,
                         "the forgery is chain-valid, which is why the chain "
                         "is not the guard")

    # ── FRESHEST ────────────────────────────────────────────────────────────

    def test_c7_a_staircase_of_small_backwards_steps_does_not_age_the_holder(self):
        """The FRESHEST guard, and the general form of the break above.

        Every appended line steps back by less than FUTURE_SKEW, so every step
        satisfies a direction check on its own and the tail walks past TTL one
        legal-looking line at a time. A reader that answers the LAST line's age
        is walked wherever the attacker wants; a reader that answers the
        freshest age in the file cannot be, because the real record at `now` is
        still in it. Deleting the direction guard does not fail this test, and
        that is the point: this one names FRESHEST.
        """
        lane = self.held_lane()
        path = kernel_proc.journal_path("owner")
        self.assertTrue(kernel_proc.forge_journal(path, "staircase"))
        quiet = kernel_proc._quiet_for("owner", time.time())
        self.assertIsInstance(quiet, float)
        self.assertLessEqual(quiet, kernel_proc.TTL,
                             "the freshest record in the file is seconds old")
        self.assertTrue(kernel_proc._own_fresh("owner", time.time(),
                                               kernel_proc.TTL))
        self.assertEqual(kernel_proc.lane_owner(lane, ignore="x")[0], "owner")

    # ── ANCHOR ──────────────────────────────────────────────────────────────

    def test_c7_a_line_whose_start_ts_contradicts_line_zero_is_unknown(self):
        """The ANCHOR guard, isolated by keeping time moving FORWARDS.

        `append` copies `start_ts` forward unchanged, so two lines that disagree
        about it did not both come from this kernel. The forged line is dated
        AFTER line 0 and after its own `start_ts`, so shape and direction are
        both satisfied and the freshest age in the file is the forged one:
        without the anchor the answer is a number past TTL and the lane frees.
        """
        lane = self.held_lane()
        now = time.time()
        start = round(now - 4000, 6)
        path = self.rewrite("owner", [
            {"seq": 0, "ts": start, "start_ts": start, "pid": "owner",
             "kind": "start"},
            {"seq": 1, "ts": round(now - (kernel_proc.TTL + 300), 6),
             "start_ts": round(start + 7, 6), "pid": "owner", "kind": "tool"},
        ])
        stale = now - (kernel_proc.TTL + 300)
        os.utime(path, (stale, stale))
        self.assertIs(kernel_proc._quiet_for("owner", time.time()),
                      kernel_proc.UNKNOWN)
        self.assertEqual(kernel_proc.lane_owner(lane, ignore="x")[0], "owner")

    def test_c7_the_exclusion_one_coherent_start_ts_still_expires(self):
        """The half that keeps the anchor a measurement instead of an appetite
        for denying: the SAME two lines with the SAME timestamps and one
        `start_ts` throughout are a process that genuinely went quiet, and its
        lane frees on schedule."""
        lane = self.held_lane()
        now = time.time()
        start = round(now - 4000, 6)
        path = self.rewrite("owner", [
            {"seq": 0, "ts": start, "start_ts": start, "pid": "owner",
             "kind": "start"},
            {"seq": 1, "ts": round(now - (kernel_proc.TTL + 300), 6),
             "start_ts": start, "pid": "owner", "kind": "tool"},
        ])
        stale = now - (kernel_proc.TTL + 300)
        os.utime(path, (stale, stale))
        self.assertIsInstance(kernel_proc._quiet_for("owner", time.time()), float)
        self.assertIsNone(kernel_proc.lane_owner(lane, ignore="x")[0])

    # ── SHAPE ───────────────────────────────────────────────────────────────

    def test_c7_a_ts_that_predates_its_own_start_ts_is_not_a_kernel_line(self):
        """The SHAPE guard's second clause, as a unit so nothing else can kill
        it. `append` writes `ts` as `now` and copies `start_ts` forward, so `ts`
        can never predate the line's own `start_ts` in a file this kernel
        wrote."""
        start = time.time()
        good = {"seq": 1, "ts": start, "start_ts": start, "pid": "owner",
                "kind": "tool", "prev": None}
        self.assertIsNotNone(
            kernel_proc._kernel_line(json.dumps(good).encode()),
            "the benign half: this exact line, one field different, is read")
        bad = dict(good, ts=start - 3600)
        self.assertIsNone(kernel_proc._kernel_line(json.dumps(bad).encode()))

    def test_c7_a_line_missing_a_core_key_is_not_a_kernel_line(self):
        """The SHAPE guard's first clause. `append` writes every one of
        `_CORE_KEYS` on every line and `_fit` never drops them, so a line
        missing one is not this kernel's line however well-formed its
        timestamps are. The old `{"ts":1}` fixture could not name this guard:
        it died on `start_ts` being absent whether the key check ran or not."""
        now = time.time()
        good = {"seq": 1, "ts": now, "start_ts": now, "pid": "owner",
                "kind": "tool", "prev": None}
        self.assertIsNotNone(kernel_proc._kernel_line(json.dumps(good).encode()))
        for key in kernel_proc._CORE_KEYS:
            if key in ("ts", "start_ts"):
                continue        # those two are the other clause's job
            with self.subTest(missing=key):
                bad = {k: v for k, v in good.items() if k != key}
                self.assertIsNone(kernel_proc._kernel_line(json.dumps(bad).encode()))

    # ── _num ────────────────────────────────────────────────────────────────

    def test_c7_a_boolean_registered_ts_is_not_a_clock_and_keeps_the_row(self):
        """`_num` excludes `bool` on purpose, and this is where the exclusion is
        load-bearing rather than tidy: `True` is an `int` to `isinstance` and
        `float(True)` is 1.0, which every clock in this file reads as 1970 and
        therefore as infinitely old.

        Reached through the ptable, because through the journal it cannot be
        isolated: `ts` and `start_ts` both coerce to 1.0 and the ANCHOR guard
        fires on the result whether `_num` sees the boolean or not. Here the
        row's own clock is the only reader, and without the exclusion a torn
        journal plus one boolean field expires the row and frees its lane at the
        next SessionStart.
        """
        lane = self.held_lane()
        path = kernel_proc.journal_path("owner")
        with open(path, "ab") as fh:
            fh.write(b"not-json\n")
        stale = time.time() - (kernel_proc.TTL + 600)
        os.utime(path, (stale, stale))
        self.assertIs(kernel_proc._quiet_for("owner", time.time()),
                      kernel_proc.UNKNOWN)

        table = kernel_proc.read_ptable()
        table["processes"]["owner"]["registered_ts"] = True
        with open(kernel_proc.ptable_path(), "w", encoding="utf-8") as fh:
            json.dump(table, fh)
        self.assertIsNone(kernel_proc._row_ts(
            kernel_proc.read_ptable()["processes"]["owner"]))

        table = kernel_proc.read_ptable()
        kernel_proc.prune(table)
        self.assertIn("owner", table["processes"],
                      "a boolean is not a registration time, so it is not a "
                      "row that registered in 1970")
        self.assertEqual(kernel_proc.lane_owner(lane, ignore="x")[0], "owner")


class EndingNeedsBothHalvesTest(SandboxHome):
    """QA cycle 8. The cheapest lane transfer in this PR's history: ONE appended
    line, 15 bytes, no `os.utime`, no timestamp forgery, no chain work.

    `is_live` reads `has_exit` FIRST on the subagent branch, before `_own_fresh`
    runs at all, so an "exit" short-circuits every freshness guard cycle 7 put
    in. The reader accepted any parseable object carrying `kind == "exit"`, so
    `{"kind":"exit"}` was a complete ending, and both gates went from `deny` to
    no decision at all while the intruder took the lane. It BYPASSES cycle 7's
    invariant rather than violating it: `_journal_age` correctly answered
    UNKNOWN for that torn file, and UNKNOWN never got the chance to hold.

    Validating the line cannot be the fix and this class does not pretend it is:
    a real exit line and a forged one are byte-identical by construction, since
    the exit hook writes it with the same `append` a forger calls. So the
    ENDING is defined as the two writes a real ending makes - the journal line
    AND the ptable row - and the row is behind the lock, `sane_table`, the fault
    carrier and the quarantine copy. That does not add a boundary; it removes a
    cheaper way around the one that was already there.
    """

    def held_lane(self):
        """A SUBAGENT holding a lane. `ppid` is what puts `is_live` on the
        branch that reads the exit first, and a row keyed `parent` instead
        misses it entirely - which is how a first reproduction of this attack
        came back clean."""
        kernel_proc.register("sess-parent", {"kind": "main", "type": "main"})
        kernel_proc.append("sess-parent", {"kind": "tool", "tool_name": "Read"})
        kernel_proc.register("owner", {"kind": "subagent", "type": "subagent",
                                       "ppid": "sess-parent"})
        lane = os.path.join(self.home, "work", "tree", "a.py")
        self.assertTrue(kernel_proc.claim_lane("owner", lane))
        kernel_proc.append("owner", {"kind": "tool", "tool_name": "Write"})
        self.assertTrue(kernel_proc.is_live("owner"), "the control is live")
        return lane

    def test_c8_a_bare_exit_object_is_not_an_ending(self):
        """THE MEASURED BREAK, verbatim. 15 bytes with no `seq`, no `ts`, no
        `start_ts`, no `pid` and no `prev` used to end a process. That is
        `{"ts":1}` from cycle 6 wearing a different key, and `_kernel_line`
        refuses it on the same grounds."""
        lane = self.held_lane()
        with open(kernel_proc.journal_path("owner"), "ab") as fh:
            fh.write(b'{"kind":"exit"}\n')
        self.assertFalse(kernel_proc.has_exit_line("owner"))
        self.assertFalse(kernel_proc.has_exit("owner"))
        self.assertTrue(kernel_proc.is_live("owner"))
        self.assertEqual(kernel_proc.lane_owner(lane, ignore="x")[0], "owner")

    def test_c8_a_well_formed_exit_line_alone_is_not_an_ending(self):
        """The half a shape check can never catch, isolated from it: this line
        is written by `append` itself, so it satisfies every rule any reader
        could impose on the file. Only the ptable row separates it from a real
        ending, and the row is a second write in a second file."""
        lane = self.held_lane()
        kernel_proc.append("owner", {"kind": "exit", "status": "ok"})
        self.assertTrue(kernel_proc.has_exit_line("owner"),
                        "the journal half is genuinely there")
        self.assertFalse(kernel_proc.has_exit("owner"),
                         "and it is not an ending on its own")
        self.assertTrue(kernel_proc.is_live("owner"))
        self.assertEqual(kernel_proc.lane_owner(lane, ignore="x")[0], "owner")

    def test_c8_an_exited_field_that_is_not_true_is_not_an_ending(self):
        """`is True`, not truthiness, and cycle 6's `"_faulted": null` is the
        anchor for it. The hook writes the literal `True`; any other shape is a
        foreign writer's row, and reading it as an ending is the direction that
        frees the lane."""
        lane = self.held_lane()
        kernel_proc.append("owner", {"kind": "exit", "status": "ok"})
        for value in ("yes", 1, [1], {"a": 1}):
            with self.subTest(exited=value):
                self.assertTrue(kernel_proc.update_row("owner",
                                                       {"exited": value}))
                self.assertFalse(kernel_proc.has_exit("owner"))
                self.assertEqual(kernel_proc.lane_owner(lane, ignore="x")[0],
                                 "owner")

    def test_c8_the_exclusion_a_real_ending_still_frees_the_lane(self):
        """The half that keeps this a measurement and not an appetite for
        denying. Both writes, in the order `r__subagent-stop__proc-exit.py`
        makes them, and the lane frees. Without this, "no subagent ever exits"
        would be the shipped rule and every lane would wait out its TTL."""
        lane = self.held_lane()
        kernel_proc.append("owner", {"kind": "exit", "status": "ok"})
        self.assertTrue(kernel_proc.update_row("owner", {"exited": True}))
        self.assertTrue(kernel_proc.has_exit("owner"))
        self.assertFalse(kernel_proc.is_live("owner"))
        self.assertIsNone(kernel_proc.lane_owner(lane, ignore="x")[0],
                          "a process that really ended releases what it held")

    def test_c8_the_writers_idempotence_guard_reads_the_journal_not_the_row(self):
        """`r__subagent-stop__proc-exit.py` guards on `has_exit_line`, and the
        two readings have to stay separable for it. `update_row` returns False
        for a pid with no row, so a guard that asked the ENDING would append a
        second exit line on every re-fired SubagentStop, forever."""
        self.held_lane()
        kernel_proc.append("owner", {"kind": "exit", "status": "ok"})
        table = kernel_proc.read_ptable()
        del table["processes"]["owner"]
        with open(kernel_proc.ptable_path(), "w", encoding="utf-8") as fh:
            json.dump(table, fh)
        self.assertFalse(kernel_proc.update_row("owner", {"exited": True}),
                         "no row to mark")
        self.assertTrue(kernel_proc.has_exit_line("owner"),
                        "the writer sees its own line and does not repeat it")
        self.assertFalse(kernel_proc.has_exit("owner"),
                         "while liveness has no corroboration and holds")


class UnreadableRegistrationTimeTest(SandboxHome):
    """QA cycle 7's leftover, closed in cycle 8. `prune` had the invariant on
    one branch and its exact violation on the next: the UNKNOWN branch keeps a
    row whose `registered_ts` cannot be read ("no clock at all"), while the
    absent-journal branch substituted `0.0` for the same unreadable value. 0.0
    is 1970 on every clock in this file, so the row read infinitely old and was
    dropped outright - with its lanes, with no fault and with nothing on any
    surface to say a holder had just been forgotten."""

    def held_lane(self):
        kernel_proc.register("owner", {"kind": "main", "type": "main"})
        lane = os.path.join(self.home, "work", "tree", "a.py")
        self.assertTrue(kernel_proc.claim_lane("owner", lane))
        kernel_proc.append("owner", {"kind": "tool", "tool_name": "Write"})
        return lane

    def test_c8_no_journal_and_no_readable_clock_keeps_and_faults_the_row(self):
        lane = self.held_lane()
        os.unlink(kernel_proc.journal_path("owner"))
        table = kernel_proc.read_ptable()
        table["processes"]["owner"]["registered_ts"] = "not-a-time"
        with open(kernel_proc.ptable_path(), "w", encoding="utf-8") as fh:
            json.dump(table, fh)

        table = kernel_proc.read_ptable()
        self.assertIsNone(kernel_proc._row_ts(table["processes"]["owner"]))
        kernel_proc.prune(table)
        self.assertIn("owner", table["processes"],
                      "a row with no clock is not a row that registered in 1970")
        self.assertTrue(kernel_proc.carried_fault(table),
                        "and holding lanes with no journal is a fault, not a "
                        "quiet drop")
        self.assertEqual(kernel_proc.lane_owner(lane, table=table,
                                                ignore="x")[0], "owner")

    def test_c8_the_exclusion_a_readable_clock_past_prune_after_still_expires(self):
        """One field different, and the row expires on schedule. Without this
        the rule would read "no row whose journal is missing ever expires"."""
        self.held_lane()
        os.unlink(kernel_proc.journal_path("owner"))
        table = kernel_proc.read_ptable()
        table["processes"]["owner"]["registered_ts"] = (
            time.time() - (kernel_proc.PRUNE_AFTER + 600))
        with open(kernel_proc.ptable_path(), "w", encoding="utf-8") as fh:
            json.dump(table, fh)
        table = kernel_proc.read_ptable()
        kernel_proc.prune(table)
        self.assertNotIn("owner", table["processes"])


class OversizedJournalTest(SandboxHome):
    """QA cycle 9, and it is an ISOLATION guard wearing a performance costume.

    `_journal_age` reads the whole journal on the stale path, so the WORK became
    a quantity the attacker chooses: the same interpreter hole sets the size
    (append) and the staleness (`os.utime`) that makes the reader run at all.
    Every decision stayed correct at every size measured, which is availability
    right up to the moment the harness is asked - `~/.claude/settings.json`
    gives these gates `"timeout": 5`, and a killed hook writes no stdout, so it
    emits no `permissionDecision`, which is the same "(none)" every matrix in
    this PR records as an ALLOW. Measured on the real gate before the cap:
    0 MB 0.27 s, 5 MB 0.25 s, 50 MB 1.96 s, 300 MB 8.01 s, killed. After it:
    0.11 s flat at every one of those sizes, still denying.

    A slow reader is a permissive reader when somebody else owns the clock.
    """

    def held_lane(self):
        kernel_proc.register("owner", {"kind": "main", "type": "main"})
        lane = os.path.join(self.home, "work", "tree", "a.py")
        self.assertTrue(kernel_proc.claim_lane("owner", lane))
        kernel_proc.append("owner", {"kind": "tool", "tool_name": "Write"})
        return lane

    def stale(self, path):
        old = time.time() - (kernel_proc.TTL + 600)
        os.utime(path, (old, old))

    def test_c9_a_journal_past_the_cap_is_unknown_and_keeps_its_lane(self):
        """At the SHIPPED constant, not a patched one. The file is made sparse
        (`os.truncate` extends with zeros and allocates nothing), which is the
        whole point of the guard: the answer costs one `getsize` and the bytes
        are never read, so a padded journal buys the fail-closed branch in O(1)
        instead of buying a timeout."""
        lane = self.held_lane()
        path = kernel_proc.journal_path("owner")
        os.truncate(path, kernel_proc.MAX_JOURNAL_SCAN + 1)
        self.stale(path)
        started = time.perf_counter()
        self.assertIs(kernel_proc._quiet_for("owner", time.time()),
                      kernel_proc.UNKNOWN)
        self.assertLess(time.perf_counter() - started, 0.5,
                        "answered without reading the file")
        self.assertTrue(kernel_proc._own_fresh("owner", time.time(),
                                               kernel_proc.TTL))
        self.assertEqual(kernel_proc.lane_owner(lane, ignore="x")[0], "owner")

    def test_c9_the_exclusion_the_boundary_answers_on_both_sides(self):
        """One journal, one constant moved by a byte in each direction, so the
        cap is measured as a BOUNDARY rather than as "big files deny". Without
        this half the shipped rule could be "no journal ever expires" and every
        count would look identical."""
        lane = self.held_lane()
        path = kernel_proc.journal_path("owner")
        kernel_proc.backdate_journal(path, kernel_proc.TTL + 600)
        size = os.path.getsize(path)
        real = kernel_proc.MAX_JOURNAL_SCAN
        self.addCleanup(setattr, kernel_proc, "MAX_JOURNAL_SCAN", real)

        kernel_proc.MAX_JOURNAL_SCAN = size          # at the cap: read
        quiet = kernel_proc._quiet_for("owner", time.time())
        self.assertIsInstance(quiet, float)
        self.assertIsNone(kernel_proc.lane_owner(lane, ignore="x")[0],
                          "a coherently quiet journal under the cap expires")

        kernel_proc.MAX_JOURNAL_SCAN = size - 1      # one byte over: unknown
        self.assertIs(kernel_proc._quiet_for("owner", time.time()),
                      kernel_proc.UNKNOWN)
        self.assertEqual(kernel_proc.lane_owner(lane, ignore="x")[0], "owner")

    def test_c9_the_line_cap_answers_on_both_sides_of_its_own_boundary(self):
        """THE LINE CAP, isolated from the byte cap, and it needed its own test:
        a mutation run found this guard SURVIVING a green suite, because the
        boundary test above moves `MAX_JOURNAL_SCAN` and nothing moved
        `MAX_JOURNAL_LINES`. Deleting the line cap changed no assertion, which
        is the guard-masking this whole PR keeps correcting - found here by the
        same method, on a guard added to fix the last finding.

        The constant is moved rather than the file grown, because the two caps
        bind in different places by design (20000 lines is about 2.4 MB of short
        records, well under the 8 MiB byte cap) and the point is the BRANCH, not
        the size. Both sides asserted, so the rule stays "past this many lines"
        rather than "always UNKNOWN"."""
        lane = self.held_lane()
        path = kernel_proc.journal_path("owner")
        kernel_proc.backdate_journal(path, kernel_proc.TTL + 600)
        n = sum(1 for ln in open(path, "rb") if ln.strip())
        real = kernel_proc.MAX_JOURNAL_LINES
        self.addCleanup(setattr, kernel_proc, "MAX_JOURNAL_LINES", real)

        kernel_proc.MAX_JOURNAL_LINES = n            # at the cap: read
        self.assertIsInstance(kernel_proc._quiet_for("owner", time.time()), float)
        self.assertIsNone(kernel_proc.lane_owner(lane, ignore="x")[0])

        kernel_proc.MAX_JOURNAL_LINES = n - 1        # one line over: unknown
        self.assertIs(kernel_proc._quiet_for("owner", time.time()),
                      kernel_proc.UNKNOWN)
        self.assertEqual(kernel_proc.lane_owner(lane, ignore="x")[0], "owner",
                         "and UNKNOWN holds the lane, so padding buys the "
                         "fail-closed branch rather than a timeout")

    def test_c9_a_fan_out_over_many_rows_is_bounded_by_the_budget(self):
        """The per-file caps bound a FILE and the attack answered with more
        files: twelve capped stale rows took `prune` 4.79 s against the register
        hook's 5 s SessionStart budget, measured. So the three callers that fan
        out open a budget and `_journal_age` answers UNKNOWN once it is spent -
        which HOLDS, so exhausting it keeps lanes held rather than freeing them.

        The budget is squeezed to a millisecond here so the test is fast and
        deterministic; the shipped value is measured in the docstring (4.79 s ->
        1.52 s over 12 rows, and 1.51 s over 60, flat because the bound is the
        budget and not the row count)."""
        lane = self.held_lane()
        path = kernel_proc.journal_path("owner")
        kernel_proc.backdate_journal(path, kernel_proc.TTL + 600)
        self.addCleanup(kernel_proc.reset_scan_budget, kernel_proc.SCAN_BUDGET)

        kernel_proc.reset_scan_budget(-1.0)          # already spent
        self.assertIs(kernel_proc._quiet_for("owner", time.time()),
                      kernel_proc.UNKNOWN)

        kernel_proc.reset_scan_budget(60.0)          # room to work
        self.assertIsInstance(kernel_proc._quiet_for("owner", time.time()), float)

        # and the fan-out opens its own, so an exhausted budget never leaks
        # from one caller into the next
        kernel_proc.reset_scan_budget(-1.0)
        self.assertIsNone(kernel_proc.lane_owner(lane, ignore="x")[0],
                          "lane_owner resets before it walks")

    def test_c9_the_cap_clears_the_largest_journal_this_kernel_writes(self):
        """The constant is sized from the machine, not from taste: 476 journals
        on the reference box run to 275 KB at the largest and 28 KB at p95. If
        a future change makes the kernel write journals near the cap, this fails
        before an operator discovers it as a lane that will not free."""
        self.assertGreaterEqual(kernel_proc.MAX_JOURNAL_SCAN, 20 * 275 * 1024,
                                "at least 20x the largest journal measured")
        self.assertGreaterEqual(kernel_proc.MAX_JOURNAL_LINES, 20 * 704,
                                "at least 20x the most lines measured")


class ScanBudgetFanOutTest(SandboxHome):
    """QA cycle 9, second pass. The budget that bounded the attacker's cost is
    reachable WITHOUT an attacker, because a machine's own steady state is a
    fan-out: 476 rows is what the reference box carries, and resolving a stale
    row costs a whole-journal scan against a budget the whole walk shares.

    Measured on that distribution with no attacker anywhere: 476 quiet rows
    resolved in 1.45 s here (correct, `lane_owner` None) and in 1.51 s on a
    loaded box (exhausted, a dead row returned as holder). The steady state sits
    ON the boundary, so the verdict depended on how busy the machine was, which
    is worse to diagnose than a clean failure. The direction is fail-closed
    throughout - it denies, it never transfers - so this is availability, and it
    is fixed where it is cheap rather than by raising a number that only moves
    the row count at which it breaks.
    """

    def rows(self, n, tree):
        for i in range(n):
            pid = "p%03d" % i
            kernel_proc.register(pid, {"pid": pid, "type": "main"})
            self.assertTrue(kernel_proc.claim_lane(pid,
                                                   os.path.join(tree, "f%03d.py" % i), tree))
            kernel_proc.append(pid, {"kind": "tool", "tool_name": "Write"})
            kernel_proc.backdate_journal(kernel_proc.journal_path(pid),
                                         kernel_proc.TTL + 600)

    def test_c9_lane_owner_reaches_the_live_holder_before_spending_the_budget(self):
        """PROBE CHEAP BEFORE EXPENSIVE. The live holder is registered LAST, so
        under the old registration-order walk it was reached only after every
        stale row had been scanned - and with the budget gone, the first stale
        row read UNKNOWN, UNKNOWN read live, and a process that ended long ago
        was named as the holder.

        The budget is emptied outright here, which is the strongest form of the
        test: freshest-first means the real holder is answered by ONE stat and
        the budget is never consulted at all."""
        tree = os.path.join(self.home, "work", "tree")
        os.makedirs(tree, exist_ok=True)
        self.rows(6, tree)
        kernel_proc.register("holder", {"pid": "holder", "type": "main"})
        lane = os.path.join(tree, "live.py")
        self.assertTrue(kernel_proc.claim_lane("holder", lane, tree))
        kernel_proc.append("holder", {"kind": "tool", "tool_name": "Write"})

        self.addCleanup(kernel_proc.reset_scan_budget, kernel_proc.SCAN_BUDGET)
        kernel_proc.reset_scan_budget(-1.0)          # nothing left to scan with
        owner, _ = kernel_proc.lane_owner(tree, ignore="intruder")
        self.assertEqual(owner, "holder",
                         "the row that actually holds the lane, not the first "
                         "stale row an exhausted budget could not read")

    def test_c9_an_exhausted_budget_says_so_instead_of_wait_for_it_to_exit(self):
        """M2 IN THE SHAPE CYCLE 9 CREATED. A holder named because the budget
        ran out is denied correctly and described wrongly: "wait for that
        process to exit" about a process that exited an hour ago is the exact
        failure `lane_recovery` already exists to fix, and for a fail-closed
        gate the description is most of the cost."""
        tree = os.path.join(self.home, "work", "tree")
        os.makedirs(tree, exist_ok=True)
        self.rows(1, tree)
        self.addCleanup(kernel_proc.reset_scan_budget, kernel_proc.SCAN_BUDGET)

        kernel_proc.reset_scan_budget(60.0)
        self.assertIn("of silence", kernel_proc.lane_recovery("p000"),
                      "a holder we could read keeps the ordinary advice")

        kernel_proc.reset_scan_budget(-1.0)
        text = kernel_proc.lane_recovery("p000")
        self.assertIn("scan budget", text)
        self.assertIn("--release p000", text)
        self.assertNotIn("Wait for that process to exit", text)

    def test_c9_prune_files_opens_its_own_budget_instead_of_inheriting(self):
        """`prune` calls `prune_files` at the END of its own fan-out, so on a
        machine big enough to spend the budget the sweep ran with none left,
        every `is_live` read UNKNOWN, UNKNOWN read live, and nothing was swept.
        The sweep that bounds directory growth was disabled exactly on the
        machines whose directories are largest, and nothing shrinks a directory
        that is never swept."""
        tree = os.path.join(self.home, "work", "tree")
        os.makedirs(tree, exist_ok=True)
        kernel_proc.register("gone", {"pid": "gone", "type": "main"})
        path = kernel_proc.journal_path("gone")
        kernel_proc.backdate_journal(path, kernel_proc.PRUNE_AFTER + 600)
        # THE LOCK FILE COUNTS TOO. `prune_files` reads the mtime of every file
        # it owns for that pid, so a backdated journal beside a fresh `.lock`
        # never reaches the liveness question at all. The first version of this
        # test left the lock alone and failed for that reason, which would have
        # been reported as a broken sweep: an invalid fixture is not a finding.
        old = time.time() - (kernel_proc.PRUNE_AFTER + 600)
        os.utime(kernel_proc.lock_path("gone"), (old, old))
        table = kernel_proc.read_ptable()
        table["processes"].pop("gone", None)         # row already expired

        self.addCleanup(kernel_proc.reset_scan_budget, kernel_proc.SCAN_BUDGET)
        kernel_proc.reset_scan_budget(-1.0)          # as prune leaves it
        self.assertEqual(kernel_proc.prune_files(table), 2,
                         "journal and lock both swept: the sweep opens its own "
                         "budget rather than inheriting a spent one")
        self.assertFalse(os.path.exists(path))


class NonRegularKernelStateTest(SandboxHome):
    """QA cycle 9 F1. A FIFO at a kernel-state path is not a slow read, it is a
    reader that never returns, and a PreToolUse hook that never returns is
    neither fail-closed nor fail-open: the harness kills it at `timeout: 5`, it
    writes no stdout, it emits no `permissionDecision`, and every matrix in this
    PR reads that as ALLOW. Measured over 20 s on both gates.

    The guard already existed for the PROCESS TABLE (cycle 4 F5,
    `read_ptable`'s `S_ISREG` pre-check) and for nothing else, which is the
    cross-function symmetry miss this cycle names: `mkfifo` on a HOLDER'S
    JOURNAL bought the same wedge back at O(1) cost, no `os.utime` and no
    oversized file, because `is_live` -> `has_exit` -> `has_exit_line` opens the
    journal before any freshness check runs.

    EVERY TEST HERE RUNS UNDER AN ALARM, because the failure mode of a revert is
    a HANG and a hanging test reports nothing. The alarm turns it back into a
    named failure.
    """

    def deadline(self, seconds=10):
        import signal
        if not hasattr(signal, "SIGALRM"):       # Windows: no alarm, no guard
            return
        def blew(_sig, _frm):
            raise AssertionError(
                "no answer within %ds: this is the HANG, which is what a "
                "non-regular kernel path buys when nothing checks S_ISREG"
                % seconds)
        old = signal.signal(signal.SIGALRM, blew)
        signal.alarm(seconds)
        self.addCleanup(signal.signal, signal.SIGALRM, old)
        self.addCleanup(signal.alarm, 0)

    def held_lane(self):
        kernel_proc.register("owner", {"kind": "main", "type": "main"})
        lane = os.path.join(self.home, "work", "tree", "a.py")
        self.assertTrue(kernel_proc.claim_lane("owner", lane))
        kernel_proc.append("owner", {"kind": "tool", "tool_name": "Write"})
        return lane

    def fifo_journal(self, pid="owner"):
        path = kernel_proc.journal_path(pid)
        os.unlink(path)
        os.mkfifo(path)
        return path

    def test_f1_a_fifo_at_a_journal_path_answers_unknown_and_holds_the_lane(self):
        self.deadline()
        lane = self.held_lane()
        path = self.fifo_journal()
        self.assertIs(kernel_proc._journal_age("owner", time.time()),
                      kernel_proc.UNKNOWN,
                      "an unopenable journal is UNKNOWN, never a hang")
        # and with the mtime backdated too, so `_quiet_for` cannot short-circuit
        # on it: this is the state that used to free the lane on both gates.
        stale = time.time() - (kernel_proc.TTL + 300)
        os.utime(path, (stale, stale))
        self.assertIs(kernel_proc._quiet_for("owner", time.time()),
                      kernel_proc.UNKNOWN)
        self.assertTrue(kernel_proc._own_fresh("owner", time.time(),
                                               kernel_proc.TTL))
        self.assertEqual(kernel_proc.lane_owner(lane, ignore="x")[0], "owner")

    def test_f1_the_ending_reader_does_not_open_it_either(self):
        """`has_exit_line` is the one that runs FIRST and with a FRESH mtime, so
        it is the half a backdating-free attack reaches. Its own contract is
        unchanged: it cannot see an exit line, and no exit means live."""
        self.deadline()
        self.held_lane()
        self.fifo_journal()
        self.assertFalse(kernel_proc.has_exit_line("owner"))
        self.assertFalse(kernel_proc.has_exit("owner"))

    def test_f1_appending_to_a_fifo_journal_raises_rather_than_blocking(self):
        """The WRITE half. `append`'s OSError is the one failure the hot-path
        gate turns into a deny, so it has to arrive as an OSError and not as a
        wedged process."""
        self.deadline()
        self.held_lane()
        self.fifo_journal()
        with self.assertRaises(OSError):
            kernel_proc.append("owner", {"kind": "tool"})

    def test_f1_a_fifo_at_the_lock_path_does_not_wedge_the_writer(self):
        """The lock file is kernel state too, and every locked writer opens it
        with `open(..., "a")`, which blocks on a fifo exactly as the journal
        did."""
        self.deadline()
        self.held_lane()
        lock = kernel_proc.lock_path("owner")
        os.unlink(lock)
        os.mkfifo(lock)
        with self.assertRaises(OSError):
            kernel_proc.append("owner", {"kind": "tool"})

    def test_f1_a_character_device_at_a_journal_path_is_unknown_too(self):
        """S_ISREG's OWN shape, and the mutation run is why this test exists as
        a separate one. Deleting `S_ISREG` from `_kernel_fd` left every fifo
        test GREEN: `O_NONBLOCK` opens a fifo with no writer and the first read
        returns EOF, so the fifo is answered by the OTHER guard. A guard masked
        by its neighbour is the exact defect this PR already recorded for
        `MAX_JOURNAL_LINES`, one function over.

        A CHARACTER DEVICE separates them. `/dev/zero` opens fine with
        `O_NONBLOCK` and then yields infinite bytes with no newline in them, so
        the line iterator buffers until the machine gives up: measured as a hard
        hang at 20 s with the check removed, which is the same wedge a fifo
        used to buy. `ln -sf /dev/zero <journal>` is one command.
        """
        self.deadline()
        if not (os.path.exists("/dev/zero") and os.path.exists("/dev/null")):
            self.skipTest("no character devices on this platform")
        lane = self.held_lane()
        path = kernel_proc.journal_path("owner")

        # THE ISOLATING ASSERTION, TAKEN AT THE OPEN AND NOT AT THE READ, and
        # that is deliberate rather than timid: with `S_ISREG` removed,
        # `_journal_age` on /dev/zero does not fail, it BUFFERS - the line
        # iterator asks for a newline that never comes and allocates until the
        # machine dies. Running the mutant through the reader OOM'd this box
        # once already, so the mutant is caught one syscall earlier, where the
        # answer is instant and costs nothing.
        os.unlink(path)
        os.symlink("/dev/zero", path)
        with self.assertRaises(OSError):
            os.close(kernel_proc._kernel_fd(path, os.O_RDONLY))

        # and the end-to-end half on a character device that DOES terminate, so
        # the reader's answer is measured rather than assumed.
        os.unlink(path)
        os.symlink("/dev/null", path)
        self.assertIs(kernel_proc._journal_age("owner", time.time()),
                      kernel_proc.UNKNOWN)
        self.assertFalse(kernel_proc.has_exit_line("owner"))
        self.assertEqual(kernel_proc.lane_owner(lane, ignore="x")[0], "owner")

    def test_f1_the_exclusion_a_regular_journal_still_reads_and_still_expires(self):
        """One edit from the violation: the same path, a REGULAR file. Without
        this the rule would read "nothing is ever readable", which passes a
        block-everything guard."""
        self.deadline()
        lane = self.held_lane()
        self.assertIsInstance(kernel_proc._quiet_for("owner", time.time()), float)
        self.assertEqual(kernel_proc.lane_owner(lane, ignore="x")[0], "owner")
        self.age_journal_whole("owner", kernel_proc.TTL + 300)
        self.assertIsNone(kernel_proc.lane_owner(lane, ignore="x")[0],
                          "a readable journal that went quiet still frees")

    def age_journal_whole(self, pid, seconds):
        kernel_proc.backdate_journal(kernel_proc.journal_path(pid), seconds)


class InvocationBudgetTest(SandboxHome):
    """QA cycle 9 F2. `SCAN_BUDGET` bounds a FAN-OUT; the harness timeout bounds
    an INVOCATION, and the two are not the same number.

    `lane_owner` calls `reset_scan_budget()` on entry and the Bash gate calls
    `lane_owner` ONCE PER TARGET, so N targets opened N budgets: instrumented
    and load-independent, 1/2/4/8/16 targets opened 1/2/4/8/16 of them, ceiling
    `SCAN_BUDGET` x N. Measured end to end, 8 targets with one stale row and
    8000 journal lines took 6.65 s, past the harness `timeout: 5`, and a killed
    gate emits no decision, which reads as ALLOW.

    Deterministic on purpose, no clock to wait on: `arm_invocation_budget`
    measures from THIS MODULE'S IMPORT, so a tiny budget is already spent by the
    time any test runs.
    """

    def setUp(self):
        super().setUp()
        self.addCleanup(setattr, kernel_proc, "_invoke_until", None)
        self.addCleanup(kernel_proc.reset_scan_budget, kernel_proc.SCAN_BUDGET)

    def test_f2_a_second_fan_out_does_not_get_a_second_budget(self):
        """THE DEFECT, as a unit. Each `reset_scan_budget` used to hand out a
        full `SCAN_BUDGET` however many had already been spent."""
        kernel_proc.arm_invocation_budget(0.001)
        for fan_out in range(1, 5):
            kernel_proc.reset_scan_budget()
            self.assertTrue(kernel_proc._scan_exhausted(),
                            "fan-out %d got a fresh budget past the invocation "
                            "deadline" % fan_out)
        self.assertTrue(kernel_proc.invocation_budget_spent())

    def test_f2_an_unspent_invocation_budget_leaves_the_fan_out_alone(self):
        """The exclusion, one edit away: the same call with the deadline still
        ahead. Without it the rule would read "every scan is exhausted", which
        denies everything and passes as a guard."""
        kernel_proc.arm_invocation_budget(3600)
        kernel_proc.reset_scan_budget()
        self.assertFalse(kernel_proc._scan_exhausted())
        self.assertFalse(kernel_proc.invocation_budget_spent())

    def test_f2_unarmed_is_still_per_fan_out(self):
        """A library caller, a test or the CLI arms nothing and keeps the old
        behaviour, which is what stops a long-running test process from
        accumulating its way into spurious UNKNOWNs."""
        kernel_proc._invoke_until = None
        kernel_proc.reset_scan_budget()
        self.assertFalse(kernel_proc._scan_exhausted())
        self.assertFalse(kernel_proc.invocation_budget_spent())

    def test_f2_an_exhausted_invocation_holds_the_lane_rather_than_freeing_it(self):
        """The direction of the failure, which is the half that makes the bound
        safe to have: past the deadline every row answers UNKNOWN, UNKNOWN reads
        LIVE, and the gate denies. Fail-closed, and it costs one `stat`."""
        kernel_proc.register("owner", {"kind": "main", "type": "main"})
        lane = os.path.join(self.home, "work", "tree", "a.py")
        self.assertTrue(kernel_proc.claim_lane("owner", lane))
        kernel_proc.backdate_journal(kernel_proc.journal_path("owner"),
                                     kernel_proc.TTL + 600)
        self.assertIsNone(kernel_proc.lane_owner(lane, ignore="x")[0],
                          "a quiet holder frees while there is budget to read it")
        kernel_proc.arm_invocation_budget(0.001)
        self.assertEqual(kernel_proc.lane_owner(lane, ignore="x")[0], "owner",
                         "and an unread record is held, not freed")

    def test_f2_the_budget_is_checked_DURING_a_pass_and_not_only_before_it(self):
        """The mid-pass check, isolated with a fake clock so the pre-check
        CANNOT be what fails. Deleting the pre-check leaves this green and
        deleting this leaves the pre-check's own test green, which is what
        "isolating" has to mean here: the mutation run found this one surviving
        a green suite because every existing fixture was small enough that one
        file never outlasted a whole budget.

        The clock is faked rather than raced: `reset_scan_budget` reads
        `monotonic` once, the pre-check reads it once and finds time to spare,
        and the reading taken 1000 lines in is a million seconds later.
        """
        kernel_proc.register("owner", {"kind": "main", "type": "main"})
        for _ in range(3):
            kernel_proc.append("owner", {"kind": "tool"})
        path = kernel_proc.journal_path("owner")
        with open(path, "rb") as fh:
            raw = fh.read()
        one = raw.split(b"\n")[0]
        with open(path, "ab") as fh:               # >1000 lines, all unreadable
            fh.write(b"\n".join([one] * 2000) + b"\n")

        real = kernel_proc.time
        ticks = iter([0.0, 0.1] + [1e6] * 64)
        class Clock:
            def __getattr__(self, name):
                return getattr(real, name)
            def monotonic(self):
                try:
                    return next(ticks)
                except StopIteration:
                    return 1e6
        kernel_proc.time = Clock()
        self.addCleanup(setattr, kernel_proc, "time", real)
        kernel_proc.reset_scan_budget(1.0)          # tick 0: deadline at 1.0
        self.assertIs(kernel_proc._journal_age("owner", real.time()),
                      kernel_proc.UNKNOWN,
                      "tick 1 (0.1) leaves the pre-check satisfied; the pass "
                      "has to notice the clock itself")

    def test_f2_both_gates_arm_it(self):
        """The bound is only real if the two processes the harness kills are the
        two that arm it. A source assertion, because the alternative is a
        wall-clock one and this file asserts no timing."""
        for name in ("g__pretool-bash__tree-owner.py",
                     "g__pretool-write__tree-owner.py"):
            body = (SCRIPTS / name).read_text(encoding="utf-8")
            self.assertIn("kernel_proc.arm_invocation_budget()", body, name)


class ClocklessRowExpiryTest(SandboxHome):
    """QA cycle 9 F3, and it is cycle 7's fix having been one case too wide.

    Cycle 7 replaced `registered = 0.0` (1970, infinitely old, so a row whose
    registration time could not be read was dropped WITH ITS LANES, no fault,
    nothing on any surface) with keeping the row. It kept all of them, lanes or
    no lanes. Measured at now + 70 days: five injected clock-less rows, zero
    dropped, five still present, where the parent commit dropped all five. The
    ptable is attacker-writable, so that is unbounded growth in the file every
    fan-out walks.

    The split is on what the row HOLDS, because that is what cycle 7 was
    actually protecting: dropping a row with lanes FREES A LANE; dropping one
    with none frees nothing.
    """

    def rows(self, count, lanes=None):
        kernel_proc.register("seed", {"kind": "main", "type": "main"})
        table = kernel_proc.read_ptable()
        for i in range(count):
            table["processes"]["ghost-%d" % i] = {
                "pid": "ghost-%d" % i, "type": "main",
                "registered_ts": "not-a-time",
                "lanes": list(lanes or []),
            }
        with open(kernel_proc.ptable_path(), "w", encoding="utf-8") as fh:
            json.dump(table, fh)
        return kernel_proc.read_ptable()

    def test_f3_a_clockless_row_holding_nothing_expires(self):
        table = self.rows(5)
        kernel_proc.prune(table, time.time() + 70 * 24 * 3600)
        left = [p for p in table["processes"] if p.startswith("ghost-")]
        self.assertEqual(left, [], "a row with no clock and no lanes grants "
                                   "nothing and must not accumulate forever")

    def test_f3_the_exclusion_a_clockless_row_holding_a_lane_is_kept_and_faulted(self):
        """One edit from the violation: the same rows, with a lane. This is
        cycle 7's finding and it must stay closed - dropping these is what freed
        a holder's lane silently."""
        lane = os.path.join(self.home, "work", "tree", "a.py")
        table = self.rows(5, [lane])
        kernel_proc.prune(table, time.time() + 70 * 24 * 3600)
        left = sorted(p for p in table["processes"] if p.startswith("ghost-"))
        self.assertEqual(len(left), 5)
        self.assertTrue(kernel_proc.carried_fault(table))
        self.assertEqual(kernel_proc.lane_owner(lane, table=table,
                                                ignore="x")[0], "ghost-0")

    def test_f3_a_clockless_row_with_an_unreadable_journal_expires_too(self):
        """The UNKNOWN branch beside it, which had the same hole for the same
        reason: a journal that is THERE and unreadable, a row with no clock, and
        nothing held."""
        kernel_proc.register("torn", {"kind": "main", "type": "main"})
        with open(kernel_proc.journal_path("torn"), "ab") as fh:
            fh.write(b"not-json\n")
        stale = time.time() - (kernel_proc.TTL + 600)
        os.utime(kernel_proc.journal_path("torn"), (stale, stale))
        table = kernel_proc.read_ptable()
        table["processes"]["torn"]["registered_ts"] = "not-a-time"
        table["processes"]["torn"]["lanes"] = []
        self.assertIs(kernel_proc._quiet_for("torn", time.time()),
                      kernel_proc.UNKNOWN)
        kernel_proc.prune(table, time.time() + 70 * 24 * 3600)
        self.assertNotIn("torn", table["processes"])


class NormalisationClassTest(SandboxHome):
    """The spelling class `norm_path` folds (QA cycle 16, issue #300).

    Every path rule in this brain compares strings that came out of
    `norm_path`, so a spelling it does not fold is a second name for one file
    and `paths_conflict` reads it as a different file. That is one class, and
    the members are enumerated in the function's own header. Each is pinned
    here twice: the fold itself, and the OVER-correction that would make two
    genuinely different files collide.

    WHAT THESE TESTS CANNOT DO: there is no Windows host here. Members 2, 3 and
    5 are exercised by INJECTING the platform facts, which tests the LOGIC and
    not the real Windows result, and the tests say so one by one. Issue #300 is
    not closed by this file; a `windows-latest` CI job is what closes it.
    """

    def inject(self, **facts):
        """Run the rest of the test on a stated platform. Restored on the way
        out: `_PATH_FACTS` is process state, and a module that leaves it set
        hands the next test a platform it never asked for."""
        saved = kernel_proc._PATH_FACTS
        self.addCleanup(setattr, kernel_proc, "_PATH_FACTS", saved)
        base = {"sep": "\\", "altsep": "/", "unc": True, "case_fold": True}
        base.update(facts)
        kernel_proc._PATH_FACTS = base
        return base

    # ── the facts themselves ───────────────────────────────────────────────
    def test_the_facts_are_asked_of_the_platform_not_of_its_name(self):
        """`os.name == 'nt'` is a branch nothing on this machine runs, and an
        unexercised branch is a claim with no measurement behind it. Each fact
        has to come from something that ANSWERS on the host it runs on."""
        import ast
        import inspect
        import textwrap
        facts = kernel_proc.path_facts(refresh=True)
        self.assertEqual(facts["sep"], os.sep)
        self.assertIs(facts["altsep"], os.altsep)
        self.assertEqual(
            facts["unc"],
            bool(os.path.splitdrive(os.sep * 2 + "server" + os.sep + "share")[0]))
        # Read as CODE, not as text: the header of `_measure_case_fold` argues
        # AGAINST `os.name` in prose, and a substring search over the source
        # would match that sentence and call the argument the defect.
        banned = ("os.name", "sys.platform", "platform.system", "platform.uname")
        for func in (kernel_proc.norm_path, kernel_proc.path_facts,
                     kernel_proc._measure_case_fold):
            tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                    self.assertNotIn(node.value.id + "." + node.attr, banned,
                                     func.__name__)

    def test_the_case_fact_agrees_with_the_filesystem_it_reports_on(self):
        """The control the fact has to survive: spell a file the other way and
        look. Skipped, not guessed, when the probe would land on a DIFFERENT
        filesystem from the one the fact reports on, because one probe answers
        for one filesystem and pretending otherwise is the residual the
        function's docstring already states."""
        probe_dir = tempfile.mkdtemp(prefix="case-probe-")
        self.addCleanup(shutil.rmtree, probe_dir, True)
        library = os.path.abspath(kernel_proc.__file__)
        if os.stat(probe_dir).st_dev != os.stat(library).st_dev:
            self.skipTest("the probe directory is on another filesystem")
        upper = os.path.join(probe_dir, "CaseProbe.tmp")
        with open(upper, "w") as fh:
            fh.write("x")
        folds = os.path.exists(os.path.join(probe_dir, "caseprobe.tmp"))
        self.assertEqual(kernel_proc._measure_case_fold(), folds)

    # ── member 1: a leading `//` ───────────────────────────────────────────
    def test_member_1_the_two_spellings_are_one_file_and_normalize_equal(self):
        """Measured before it is asserted: the kernel opens `//x` and `/x` as
        the same inode, so the two spellings are one file and the gates have to
        read them as one path."""
        target = os.path.join(self.home, "a.py")
        with open(target, "w") as fh:
            fh.write("x")
        self.assertEqual(os.stat("/" + target).st_ino, os.stat(target).st_ino)
        self.assertEqual(kernel_proc.norm_path("/" + target),
                         kernel_proc.norm_path(target))
        self.assertTrue(kernel_proc.paths_conflict(
            kernel_proc.norm_path("/" + target), kernel_proc.norm_path(target)))

    def test_member_1_is_off_where_a_double_separator_is_a_NAMESPACE(self):
        """The over-correction. On a platform whose `splitdrive` reports a drive
        for `\\\\server\\share`, that leading pair is a UNC share and NOT the
        local root, so collapsing it would rewrite the path to another machine
        into a path on this one. INJECTED: no Windows host here."""
        self.inject()
        self.assertTrue(kernel_proc.norm_path("\\\\srv\\share\\f").endswith(
            "\\\\srv\\share\\f"))

    # ── member 2: mixed separators ─────────────────────────────────────────
    def test_member_2_mixed_separators_fold_where_altsep_is_a_separator(self):
        """`C:\\work\\tree/pkg` and `C:\\work\\tree\\pkg` are one path wherever
        `os.altsep` is a separator. This is the spelling issue #300 reports the
        tree-owner gate letting through. INJECTED, so it proves the fold and
        not the Windows result."""
        self.inject()
        self.assertEqual(kernel_proc.norm_path("C:\\work\\tree/pkg"),
                         kernel_proc.norm_path("C:\\work\\tree\\pkg"))

    def test_member_2_is_off_where_a_backslash_is_a_FILENAME(self):
        """The over-correction, on the real platform this suite runs on:
        `os.altsep` is None here, `a\\b` is a legal POSIX filename, and folding
        it would make two different files collide."""
        kernel_proc.path_facts(refresh=True)
        self.assertIn("\\", kernel_proc.norm_path("/tmp/a\\b"))
        self.assertNotEqual(kernel_proc.norm_path("/tmp/a\\b"),
                            kernel_proc.norm_path("/tmp/a/b"))

    # ── member 3: case ─────────────────────────────────────────────────────
    def test_member_3_case_folds_where_the_filesystem_folds(self):
        """INJECTED. One fact separates this from the test below."""
        self.inject(case_fold=True)
        self.assertEqual(kernel_proc.norm_path("C:\\Work\\PKG"),
                         kernel_proc.norm_path("c:\\work\\pkg"))

    def test_member_3_does_not_fold_where_the_filesystem_distinguishes(self):
        """The benign fixture, one edit from the violation above: the same
        paths on a filesystem that reports case-SENSITIVE stay two files.
        Lowercasing unconditionally is the obvious over-correction, and on this
        machine `/A` and `/a` really are different files."""
        self.inject(case_fold=False)
        self.assertNotEqual(kernel_proc.norm_path("C:\\Work\\PKG"),
                            kernel_proc.norm_path("c:\\work\\pkg"))

    def test_member_3_leaves_this_filesystem_alone(self):
        """And on the measured facts of the host actually running this, where
        the probe reports case-sensitive, the two spellings stay apart."""
        facts = kernel_proc.path_facts(refresh=True)
        if facts["case_fold"]:
            self.skipTest("this filesystem folds case; the fold is the fact")
        self.assertNotEqual(kernel_proc.norm_path("/A"), kernel_proc.norm_path("/a"))

    # ── member 4: a trailing separator ─────────────────────────────────────
    def test_member_4_a_trailing_separator_is_folded(self):
        """Native, and injected. `normpath` folds this for the separator IT
        knows; the fold is done in `norm_path` so it holds for the separator
        the FACTS name."""
        self.assertEqual(kernel_proc.norm_path("/tmp/x/"), kernel_proc.norm_path("/tmp/x"))
        self.inject()
        self.assertEqual(kernel_proc.norm_path("C:\\work\\pkg\\"),
                         kernel_proc.norm_path("C:\\work\\pkg"))

    def test_member_4_keeps_the_separator_a_ROOT_needs(self):
        """The over-correction: `/` is not the empty string, and `C:\\` is not
        `C:`, which is a drive-RELATIVE path and a different file."""
        self.assertEqual(kernel_proc.norm_path("/"), os.sep)
        self.inject(case_fold=False)
        self.assertTrue(kernel_proc.norm_path("C:\\").endswith("C:\\"))

    # ── member 5: a verbatim / device prefix ───────────────────────────────
    def test_member_5_a_verbatim_or_device_prefix_reaches_the_same_file(self):
        """INJECTED. `\\\\?\\C:\\x` and `\\\\.\\C:\\x` open `C:\\x`, and
        `\\\\?\\UNC\\srv\\share` is the share itself, so it folds back to the
        double-separator spelling rather than to a local path."""
        self.inject()
        plain = kernel_proc.norm_path("C:\\work\\pkg")
        self.assertEqual(kernel_proc.norm_path("\\\\?\\C:\\work\\pkg"), plain)
        # ALL BACKSLASHES on purpose. The first draft spelled this one
        # `\\.\C:\work/pkg`, and reverting the mixed-separator fold reddened
        # this test too: an anchor that answers for two mechanisms says nothing
        # about either (QA cycle 15 found three of its own pinned that way).
        self.assertEqual(kernel_proc.norm_path("\\\\.\\C:\\work\\pkg"), plain)
        self.assertEqual(kernel_proc.norm_path("\\\\?\\UNC\\srv\\share\\f"),
                         kernel_proc.norm_path("\\\\srv\\share\\f"))

    def test_the_fold_is_one_funnel_and_the_gates_read_it(self):
        """The reason all of this lives in `norm_path`: `paths_conflict` is
        what every path rule asks, and it compares what this function returned.
        A per-caller fix would be a list of the callers someone remembered."""
        lane = kernel_proc.norm_path(os.path.join(self.home, "work", "a.py"))
        for spelling in ("/" + os.path.join(self.home, "work", "a.py"),
                         os.path.join(self.home, "work", "") + "/a.py",
                         os.path.join(self.home, "work", ".", "a.py")):
            self.assertTrue(kernel_proc.paths_conflict(
                kernel_proc.norm_path(spelling), lane), spelling)
