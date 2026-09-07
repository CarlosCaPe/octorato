#!/usr/bin/env python3
"""Anchors for the v8 kernel CLI (scripts/octo.py).

What is pinned here is what a reader of the kernel depends on: `ps` shows a
seeded table with the parent link and the agent type, `--release` is refused
inside an agent shell and works outside it, `replay` prints the run in journal
order and folds a `deny` into the call it refused, `--verify` turns a broken
chain into a non-zero exit, `journal` hands back the raw bytes, and the golden
fixture compares byte for byte.

Timing is never asserted (v8-kernel.md section 3). `bench` is exercised for its
SHAPE only, and even that is left to the selftest: a unit test that timed the
hot path would fail on a loaded machine and teach the team to ignore it.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

import kernel_proc  # noqa: E402
import octo  # noqa: E402

FIXTURES = ROOT / "registry" / "fixtures" / "ARCHITECTURE.kernel-process"
AGENT_MARKERS = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SESSION_ID")


class OctoCase(unittest.TestCase):
    """Sandbox HOME and a shell with no agent markers: the tests run INSIDE an
    agent most of the time, so the default state has to be the operator's
    terminal or every `--release` test would pass for the wrong reason."""

    def setUp(self):
        self._env = {k: os.environ.get(k) for k in
                     ("HOME", "USERPROFILE") + AGENT_MARKERS}
        self.home = tempfile.mkdtemp(prefix="octo-test-")
        os.environ["HOME"] = self.home
        os.environ["USERPROFILE"] = self.home
        for marker in AGENT_MARKERS:
            os.environ.pop(marker, None)

    def tearDown(self):
        import shutil
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.home, ignore_errors=True)

    def run_octo(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = octo.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def seed(self, tools=2):
        """A parent, a child, and `tools` journaled calls on the child."""
        kernel_proc.register("sess-1", {"kind": "main", "worktree": "/w",
                                        "type": "main", "source": "startup"})
        kernel_proc.register("agent-1", {"kind": "subagent", "ppid": "sess-1",
                                         "type": "Reality Checker", "worktree": "/w"})
        for i in range(tools):
            kernel_proc.append("agent-1", {"kind": "tool", "tool_name": "Bash",
                                           "tool_use_id": f"toolu_{i}"})


class PsTest(OctoCase):
    def test_ps_shows_the_seeded_table_with_parent_type_and_counts(self):
        self.seed()
        rc, out, _ = self.run_octo(["ps"])
        self.assertEqual(rc, 0)
        self.assertIn("PID", out)
        self.assertIn("sess-1", out)
        self.assertIn("agent-1", out)
        self.assertIn("Reality Checker", out, "the agent type is the column that names WHO")
        self.assertIn("2 process(es), 2 live", out)
        agent_row = [l for l in out.splitlines() if l.startswith("agent-1")][0]
        self.assertIn("sess-1", agent_row, "the child row must name its parent")
        self.assertIn("live", agent_row)

    def test_ps_on_an_empty_machine_says_so_instead_of_printing_a_bare_header(self):
        rc, out, _ = self.run_octo(["ps"])
        self.assertEqual(rc, 0)
        self.assertIn("no processes", out)

    def test_ps_prunes_on_read(self):
        """A row whose journal has been gone for longer than the retention
        window is dropped by the read, not left for a register hook that may
        never fire again on this machine."""
        self.seed()
        kernel_proc.register("ancient", {"kind": "main"})
        os.unlink(kernel_proc.journal_path("ancient"))
        table = kernel_proc.read_ptable()
        table["processes"]["ancient"]["registered_ts"] = time.time() - (kernel_proc.TTL + 60)
        kernel_proc._write_ptable(table)
        rc, out, _ = self.run_octo(["ps"])
        self.assertEqual(rc, 0)
        self.assertNotIn("ancient", out)
        self.assertNotIn("ancient", kernel_proc.read_ptable()["processes"])


class ReleaseTest(OctoCase):
    def test_release_is_refused_inside_an_agent_shell(self):
        self.seed()
        os.environ["CLAUDECODE"] = "1"
        rc, out, err = self.run_octo(["ps", "--release", "agent-1"])
        self.assertEqual(rc, 2)
        self.assertIn("REFUSED", err)
        self.assertIn("CLAUDECODE", err, "the refusal names the marker it saw")
        kinds = [l.get("kind") for l in kernel_proc.read_journal("agent-1")]
        self.assertNotIn("release", kinds, "a refused release must journal nothing")

    def test_release_outside_an_agent_shell_frees_the_lanes_and_journals_it(self):
        self.seed()
        kernel_proc.update_row("agent-1", {"lanes": ["/w/a.py", "/w/b.py"]})
        rc, out, err = self.run_octo(["ps", "--release", "agent-1"])
        self.assertEqual(rc, 0, err)
        self.assertIn("2 lane(s) freed", out)
        row = kernel_proc.read_ptable()["processes"]["agent-1"]
        self.assertEqual(row["lanes"], [], "the lanes field is emptied, not left stale")
        self.assertTrue(row.get("released_ts"))
        rel = [l for l in kernel_proc.read_journal("agent-1") if l.get("kind") == "release"]
        self.assertEqual(len(rel), 1)
        self.assertEqual(rel[0]["lanes"], ["/w/a.py", "/w/b.py"],
                         "the journal records WHAT was freed, not just that something was")
        self.assertEqual(kernel_proc.verify("agent-1"), 0, "the chain survives a release")

    def test_release_of_an_unknown_pid_reports_it(self):
        rc, _, err = self.run_octo(["ps", "--release", "nobody"])
        self.assertEqual(rc, 1)
        self.assertIn("nothing to release", err)


class TopTest(OctoCase):
    def test_top_aggregates_tools_and_denies_and_hides_an_empty_token_column(self):
        self.seed(tools=3)
        kernel_proc.append("agent-1", {"kind": "deny", "tool_use_id": "toolu_1",
                                       "rule": "ARCHITECTURE.kernel-isolation"})
        rc, out, _ = self.run_octo(["top"])
        self.assertEqual(rc, 0)
        self.assertIn("DENIES", out)
        self.assertNotIn("TOKENS", out,
                         "no runtime has exposed tokens, so an empty column would be a claim")
        self.assertIn("3 tool call(s), 1 deny(s)", out)

    def test_top_shows_the_token_column_once_a_line_carries_tokens(self):
        self.seed(tools=1)
        kernel_proc.append("agent-1", {"kind": "tool", "tool_name": "Bash",
                                       "tool_use_id": "t9", "tokens": 1200})
        rc, out, _ = self.run_octo(["top"])
        self.assertEqual(rc, 0)
        self.assertIn("TOKENS", out)
        self.assertIn("1200", out)


    def test_top_never_prints_main_for_a_pid_with_no_ptable_row(self):
        """`top` unions the ptable with the journal files on disk, so it reaches
        pids `ps` never sees. It used to render those as type `main`: two claims
        the kernel cannot make, that the process is a main loop and that a
        register hook ever saw it. Measured live, 52 phantom journals buried the
        real processes under fake main loops. A `?` says only what is known, and
        the count is printed so the row is explained rather than hidden."""
        self.seed(tools=1)
        kernel_proc.append("ghost", {"kind": "tool", "tool_name": "Bash",
                                     "tool_use_id": "toolu_ghost"})
        self.assertNotIn("ghost", kernel_proc.read_ptable()["processes"])

        rc, out, _ = self.run_octo(["top"])
        self.assertEqual(rc, 0)
        ghost_row = [l for l in out.splitlines() if l.startswith("ghost")]
        self.assertEqual(len(ghost_row), 1, "the row is shown, never silently dropped")
        self.assertNotIn("main", ghost_row[0], "the kernel does not know this type")
        self.assertIn(octo.UNKNOWN_TYPE, ghost_row[0])
        self.assertIn("1 of them have a journal but no ptable row", out)

        # the real main loop still prints its own type, so `?` is not a blanket
        sess_row = [l for l in out.splitlines() if l.startswith("sess-1")][0]
        self.assertIn("main", sess_row)

    def test_ps_and_top_agree_on_the_type_of_every_row_ps_shows(self):
        """One vocabulary, the way `_row_state` already is. Every pid `ps`
        lists comes from the ptable and carries a type, so no `?` may appear
        there."""
        self.seed(tools=1)
        _, ps_out, _ = self.run_octo(["ps"])
        _, top_out, _ = self.run_octo(["top"])
        self.assertNotIn(octo.UNKNOWN_TYPE, ps_out)
        for pid, kind in (("sess-1", "main"), ("agent-1", "Reality Checker")):
            for out in (ps_out, top_out):
                row = [l for l in out.splitlines() if l.startswith(pid)][0]
                self.assertIn(kind, row)

    def test_replay_uses_the_same_word_as_top_for_a_row_less_pid(self):
        """QA cycle 1 on this fix: `top` said `?` while `replay` still said
        `main` for the same journal. Two readers of one table disagreeing about
        a process is the exact drift UNKNOWN_TYPE exists to prevent, so the
        third reader is pinned here rather than left to the next incident."""
        self.seed(tools=1)
        kernel_proc.append("ghost", {"kind": "tool", "tool_name": "Bash",
                                     "tool_use_id": "toolu_ghost"})
        self.assertNotIn("ghost", kernel_proc.read_ptable()["processes"])

        rc, replay_out, _ = self.run_octo(["replay", "ghost"])
        self.assertEqual(rc, 0)
        type_line = [l for l in replay_out.splitlines() if l.strip().startswith("type")][0]
        self.assertNotIn("main", type_line)
        self.assertIn(octo.UNKNOWN_TYPE, type_line)

        _, top_out, _ = self.run_octo(["top"])
        ghost_row = [l for l in top_out.splitlines() if l.startswith("ghost")][0]
        self.assertIn(octo.UNKNOWN_TYPE, ghost_row)

        # and a pid the kernel DOES know still reads its real type in replay,
        # so the `?` is a statement about knowledge, not a blanket.
        _, known_out, _ = self.run_octo(["replay", "sess-1"])
        known_line = [l for l in known_out.splitlines() if l.strip().startswith("type")][0]
        self.assertIn("main", known_line)
        self.assertNotIn(octo.UNKNOWN_TYPE, known_line)


class RowlessChildTest(OctoCase):
    """QA cycle 2, B: the `children` block of `replay` was the one `_row_type`
    call nothing pinned. Reverting it to `row.get("type") or "main"` passed the
    whole suite, and the state it renders wrong is reachable: `claim_lane`
    creates a row with no `type` when a register hook loses its race with the
    process's first write."""

    def rowless_child(self, pid="kid", parent="sess-1"):
        """A child row exactly as the race leaves it: lanes and a parent link,
        no type. `claim_lane` writes the row, `update_row` merges the link, both
        of them shipped writers."""
        kernel_proc.append(pid, {"kind": "tool", "tool_name": "Bash",
                                 "tool_use_id": "toolu_kid"})
        kernel_proc.claim_lane(pid, os.path.join(self.home, "w", "a.py"))
        kernel_proc.update_row(pid, {"ppid": parent})
        row = kernel_proc.read_ptable()["processes"][pid]
        self.assertNotIn("type", row, "the race leaves no type; that is the point")
        return row

    def test_replay_never_calls_a_type_less_child_a_main_loop(self):
        """A main loop is not something the kernel can infer from a row that is
        missing its type, and a child least of all: `main` in the children block
        would be `octo replay` contradicting `octo top` about one process."""
        self.seed(tools=1)
        self.rowless_child()
        rc, out, _ = self.run_octo(["replay", "sess-1"])
        self.assertEqual(rc, 0)
        lines = out.splitlines()
        section = lines[lines.index("children") + 1:]
        kid_line = [l for l in section if l.strip().startswith("kid")][0]
        self.assertNotIn("main", kid_line, "the kernel does not know this type")
        self.assertIn(octo.UNKNOWN_TYPE, kid_line)
        self.assertIn("no exit recorded", kid_line)

        # and a child the kernel DOES know still reads its real type there, so
        # the `?` is a statement about knowledge and not a blanket.
        agent_line = [l for l in section if l.strip().startswith("agent-1")][0]
        self.assertIn("Reality Checker", agent_line)
        self.assertNotIn(octo.UNKNOWN_TYPE, agent_line)


class CorruptRowTest(OctoCase):
    """QA cycle 2, A: with one ptable value that is not an object, `ps` and
    `top` exited 1 and `replay` exited 1 on a healthy journal. The reader keeps
    working now, and says what it dropped: an invisible repair is its own
    failure mode."""

    def corrupt(self):
        """Written straight to the file, bad row first. These three readers walk
        every row, so position does not decide reachability the way it does for
        `lane_owner`; putting it first only makes the walk hit it immediately."""
        with open(kernel_proc.ptable_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        procs = {"junk": "not-a-row"}
        procs.update(data["processes"])
        data["processes"] = procs
        with open(kernel_proc.ptable_path(), "w", encoding="utf-8") as fh:
            json.dump(data, fh)

    def test_ps_top_and_replay_all_survive_and_footnote_the_row(self):
        self.seed(tools=1)
        self.corrupt()
        for argv in (["ps"], ["top"], ["replay", "agent-1"]):
            rc, out, err = self.run_octo(argv)
            self.assertEqual(rc, 0, f"{argv}: {err}")
            self.assertIn("agent-1", out, f"{argv} still shows the healthy rows")
        for argv in (["ps"], ["top"]):
            _, out, _ = self.run_octo(argv)
            self.assertIn("1 unreadable row(s) dropped on read: junk", out, argv)

    def test_ps_names_the_row_even_when_its_own_prune_erases_it(self):
        """QA cycle 3, F3. `cmd_ps` pruned BEFORE it read, and `prune_locked` is
        a writer: on a table carrying one old dead row (the steady state of any
        machine that has run for a while, not an exotic fixture) it republished
        the file without the corrupt row, and the read that followed measured
        `dropped == []`. So `octo ps` was the process that erased the corruption
        and the only one that could have named it, the footer printed nothing,
        and the doctor after it had nothing left to report.

        The read now sits on BOTH sides of the prune. The row still leaves the
        file, which is the intended repair; what changed is that the listing
        that erased it says so, and the original is preserved beside the file.
        """
        self.seed(tools=1)
        kernel_proc.register("ancient", {"kind": "main"})
        os.unlink(kernel_proc.journal_path("ancient"))
        table = kernel_proc.read_ptable()
        table["processes"]["ancient"]["registered_ts"] = time.time() - (kernel_proc.TTL + 60)
        kernel_proc._write_ptable(table)
        self.corrupt()                      # bad row last: everything above writes

        rc, out, _ = self.run_octo(["ps"])
        self.assertEqual(rc, 0)
        self.assertIn("1 unreadable row(s) dropped on read: junk", out,
                      "the listing that erased the row is the one that must name it")
        self.assertNotIn("ancient", out, "the prune still ran")
        with open(kernel_proc.ptable_path(), encoding="utf-8") as fh:
            self.assertNotIn("junk", json.load(fh)["processes"])
        kept = kernel_proc.quarantines()
        self.assertEqual(len(kept), 1, "and the file it overwrote is preserved")
        with open(kept[0][1], encoding="utf-8") as fh:
            self.assertIn("junk", json.load(fh)["ptable"])

    def test_a_table_of_nothing_but_bad_rows_still_says_what_it_dropped(self):
        """The empty-table path prints its own line and used to return before
        anything else could. A reader that says `no processes` while a corrupt
        row sits in the file has told the operator the opposite of the truth."""
        kernel_proc.register("gone", {"kind": "main", "type": "main"})
        with open(kernel_proc.ptable_path(), "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "processes": {"junk": "not-a-row"}}, fh)
        rc, out, _ = self.run_octo(["ps"])
        self.assertEqual(rc, 0)
        self.assertIn("no processes", out)
        self.assertIn("1 unreadable row(s) dropped on read: junk", out)


class UnreadableTableTest(OctoCase):
    """QA cycle 3, F1, at the reader. With `processes` shaped as an array,
    `octo ps` printed `no processes: the kernel has registered nothing on this
    machine yet` over a file holding every row on the machine. A listing is
    allowed to say it found nothing; it is not allowed to say nothing was ever
    registered, because that is a claim about the machine and only an ABSENT
    file supports it.
    """

    def list_shaped(self):
        kernel_proc.register("sess-1", {"kind": "main", "type": "main", "worktree": "/w"})
        with open(kernel_proc.ptable_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        data["processes"] = list(data["processes"].values())
        with open(kernel_proc.ptable_path(), "w", encoding="utf-8") as fh:
            json.dump(data, fh)

    def test_ps_says_the_table_is_unreadable_not_that_nothing_is_registered(self):
        self.list_shaped()
        rc, out, _ = self.run_octo(["ps"])
        self.assertEqual(rc, 0, "one unreadable file must not take the reader down")
        self.assertNotIn("registered nothing on this machine", out,
                         "the file is right there and it is full of rows")
        self.assertIn("THE PROCESS TABLE IS UNREADABLE", out)
        self.assertIn("array of 1 value(s)", out)
        self.assertIn(kernel_proc.ptable_path(), out, "and where to read it")

    def test_top_says_it_too_and_neither_reader_writes(self):
        """Both listings read the same seam, and a reader that cannot read the
        table still must not repair the file: the fault is the evidence."""
        self.list_shaped()
        with open(kernel_proc.ptable_path(), "rb") as fh:
            before = fh.read()
        rc, out, _ = self.run_octo(["top"])
        self.assertEqual(rc, 0)
        self.assertNotIn("no activity in the last 24 h", out)
        self.assertIn("THE PROCESS TABLE IS UNREADABLE", out)
        with open(kernel_proc.ptable_path(), "rb") as fh:
            self.assertEqual(fh.read(), before)
        self.assertEqual(kernel_proc.quarantines(), [])


class ReplayTest(OctoCase):
    def seed_refusal(self):
        self.seed(tools=0)
        kernel_proc.append("agent-1", {"kind": "tool", "tool_name": "Read",
                                       "tool_use_id": "toolu_a"})
        kernel_proc.append("agent-1", {"kind": "tool", "tool_name": "Bash",
                                       "tool_use_id": "toolu_b"})
        kernel_proc.append("agent-1", {"kind": "deny", "tool_use_id": "toolu_b",
                                       "rule": "ARCHITECTURE.kernel-isolation",
                                       "reason": "a.py belongs to a live sibling"})
        kernel_proc.append("agent-1", {"kind": "exit", "status": "ok", "tool_count": 2,
                                       "duration": 4.0})

    def test_replay_keeps_journal_order_and_folds_the_deny_into_its_call(self):
        self.seed_refusal()
        rc, out, err = self.run_octo(["replay", "agent-1"])
        self.assertEqual(rc, 0, err)
        body = out[out.index("timeline"):]
        order = [l.split()[2] for l in body.splitlines()[1:] if l.startswith("  #")]
        self.assertEqual(order, ["start", "tool", "REFUSED", "exit"],
                         "the refused call replaces its own tool line, and the deny "
                         "line is not printed twice")
        refused = [l for l in body.splitlines() if "REFUSED" in l][0]
        self.assertIn("ARCHITECTURE.kernel-isolation", refused)
        self.assertIn("toolu_b", refused)
        self.assertIn("a.py belongs to a live sibling", refused)
        self.assertIn("tools     2 (1 refused)", out)

    def test_replay_lists_children_and_marks_the_chain(self):
        self.seed()
        rc, out, _ = self.run_octo(["replay", "sess-1"])
        self.assertEqual(rc, 0)
        self.assertIn("chain     ok", out)
        self.assertIn("children", out)
        self.assertIn("agent-1", out.split("children", 1)[1])

    def test_verify_turns_a_broken_chain_into_a_non_zero_exit(self):
        self.seed()
        path = kernel_proc.journal_path("agent-1")
        with open(path, "rb") as fh:
            raw = fh.read().replace(b'"tool_name":"Bash"', b'"tool_name":"Bosh"', 1)
        with open(path, "wb") as fh:
            fh.write(raw)
        rc, out, _ = self.run_octo(["replay", "agent-1"])
        self.assertEqual(rc, 0, "without --verify a damaged journal still replays")
        self.assertIn("chain     BROKEN", out, "the damage is always REPORTED")
        rc, _, _ = self.run_octo(["replay", "agent-1", "--verify"])
        self.assertEqual(rc, 1, "--verify is what makes it an exit code")

    def test_replay_of_an_unknown_pid_exits_non_zero(self):
        rc, _, err = self.run_octo(["replay", "ghost"])
        self.assertEqual(rc, 1)
        self.assertIn("no journal", err)

    def test_replay_joins_the_receipt_ledger_by_session(self):
        """A subagent's receipts live under its PARENT's session id
        (receipt_ledger.py:270-274), so joining by its own pid would find
        nothing and print `(none)` on a run that had receipts."""
        self.seed()
        import receipt_ledger
        receipt_ledger.append_session("sess-1", {"kind": "seek",
                                                 "tool_use_id": "toolu_seek_1"})
        rc, out, _ = self.run_octo(["replay", "agent-1"])
        self.assertEqual(rc, 0)
        tail = out.split("receipts", 1)[1]
        self.assertIn("toolu_seek_1", tail)


class GoldenFixtureTest(OctoCase):
    def test_the_golden_replay_matches_expected_txt_byte_for_byte(self):
        rdir = FIXTURES / "replay"
        rc, out, err = self.run_octo(["replay", "--fixture", str(rdir)])
        self.assertEqual(rc, 0, err)
        self.assertEqual(out.encode("utf-8"), (rdir / "expected.txt").read_bytes())

    def test_the_golden_carries_a_refusal_and_a_full_life(self):
        """If the fixture stopped covering the shapes replay exists to print,
        the byte compare above would keep passing while proving less."""
        text = (FIXTURES / "replay" / "expected.txt").read_text(encoding="utf-8")
        self.assertIn("REFUSED", text)
        self.assertIn("start", text)
        self.assertIn("exit", text)
        self.assertIn("chain     ok", text)

    def test_a_tampered_fixture_fails_verify(self):
        rdir = Path(self.home) / "tampered"
        rdir.mkdir()
        raw = (FIXTURES / "replay" / "journal.jsonl").read_bytes()
        (rdir / "journal.jsonl").write_bytes(raw.replace(b'"seq":2', b'"seq":9', 1))
        rc, _, _ = self.run_octo(["replay", "--fixture", str(rdir), "--verify"])
        self.assertEqual(rc, 1)


class JournalTest(OctoCase):
    def test_journal_prints_the_raw_lines_unchanged(self):
        self.seed(tools=1)
        rc, out, _ = self.run_octo(["journal", "agent-1"])
        self.assertEqual(rc, 0)
        with open(kernel_proc.journal_path("agent-1"), encoding="utf-8") as fh:
            on_disk = fh.read()
        self.assertEqual(out, on_disk, "raw means raw: no reformatting, no filtering")
        for line in out.strip().splitlines():
            json.loads(line)

    def test_journal_of_an_unknown_pid_exits_non_zero(self):
        rc, _, err = self.run_octo(["journal", "ghost"])
        self.assertEqual(rc, 1)
        self.assertIn("cannot read", err)


class SelftestTest(OctoCase):
    def test_the_bundled_selftest_passes(self):
        rc, out, err = self.run_octo(["--selftest", str(FIXTURES)])
        self.assertEqual(rc, 0, err)
        self.assertIn("selftest PASS", out)


if __name__ == "__main__":
    unittest.main()
