#!/usr/bin/env python3
"""Anchors for the v8 Phase 4 JOURNAL closure (replay summary, receipts, denies).

Phase 1b proved a run could be replayed. Phase 4 proves it is COMPLETE: the
refusals are in it, the receipts are in it, and every refusal names a rule the
registry carries. What is pinned here is exactly that, plus the one property
the whole design rests on and no reader can see by inspection - `journal_deny`
is FAIL-OPEN. Thirteen fail-closed gates now call it from inside their deny
path. If it could raise, or change what the gate returned, the mirror would
have made the brain less safe than it was without a journal.

Timing is never asserted (v8-kernel.md section 3).
"""
from __future__ import annotations

import io
import json
import os
import subprocess
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
import receipt_ledger  # noqa: E402

REPLAY_FIXTURE = ROOT / "registry" / "fixtures" / "ARCHITECTURE.kernel-process" / "replay"
AGENT_MARKERS = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SESSION_ID")


class ReplayCase(unittest.TestCase):
    def setUp(self):
        self._env = {k: os.environ.get(k) for k in
                     ("HOME", "USERPROFILE") + AGENT_MARKERS}
        self.home = tempfile.mkdtemp(prefix="octo-replay-test-")
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

    def seed_run(self):
        """One parent, one child: two calls, one of them refused, one receipt."""
        kernel_proc.register("sess-1", {"kind": "main", "worktree": "/w",
                                        "source": "startup"})
        kernel_proc.register("agent-1", {"kind": "subagent", "ppid": "sess-1",
                                         "type": "Reality Checker", "worktree": "/w"})
        kernel_proc.append("agent-1", {"kind": "tool", "tool_name": "Read",
                                       "tool_use_id": "toolu_a"})
        kernel_proc.append("agent-1", {"kind": "tool", "tool_name": "Bash",
                                       "tool_use_id": "toolu_b"})
        kernel_proc.journal_deny("ARCHITECTURE.session-isolation",
                                 "broad git add on a shared tree",
                                 "toolu_b", "agent-1")


# ── the run summary ─────────────────────────────────────────────────────────

class SummaryTest(ReplayCase):
    def test_an_unpaired_deny_is_not_listed_under_refused(self):
        """The header counts paired denies; the summary must count the same set.

        Listing every deny under `refused` made the summary contradict the
        header two lines above it, which is worse than omitting the line.
        """
        self.seed_run()
        kernel_proc.journal_deny("COMMS.paste-ready-raw-message",
                                 "the draft is not raw", None, "agent-1")
        rc, out, _ = self.run_octo(["replay", "agent-1"])
        self.assertEqual(rc, 0)
        self.assertIn("tools     2 (1 refused)", out)
        self.assertIn("refused   ARCHITECTURE.session-isolation 1", out)
        self.assertIn("other denies  COMMS.paste-ready-raw-message 1", out)
        refused_line = [l for l in out.splitlines() if l.startswith("  refused ")][0]
        self.assertNotIn("paste-ready", refused_line)

    def test_the_other_denies_line_is_absent_when_every_deny_paired(self):
        self.seed_run()
        _, out, _ = self.run_octo(["replay", "agent-1"])
        self.assertNotIn("other denies", out)

    def test_summary_breaks_the_run_down_by_tool_rule_and_receipt_kind(self):
        self.seed_run()
        kernel_proc.journal_receipt("agent-1", "seek", "toolu_a", {"kind": "seek"})
        rc, out, _ = self.run_octo(["replay", "agent-1"])
        self.assertEqual(rc, 0)
        self.assertIn("summary", out)
        self.assertIn("tools     Bash 1, Read 1", out,
                      "tools by name, biggest first then alphabetical")
        self.assertIn("refused   ARCHITECTURE.session-isolation 1", out)
        self.assertIn("receipts  seek 1", out)
        self.assertIn("exit      (none yet)", out)

    def test_summary_names_the_children_of_this_process(self):
        self.seed_run()
        kernel_proc.register("agent-2", {"kind": "subagent", "ppid": "sess-1",
                                         "type": "Evidence Collector", "worktree": "/w"})
        rc, out, _ = self.run_octo(["replay", "sess-1"])
        self.assertEqual(rc, 0)
        self.assertIn("children  2: agent-1, agent-2", out)

    def test_an_empty_dimension_says_none_rather_than_nothing(self):
        kernel_proc.register("sess-1", {"kind": "main", "worktree": "/w"})
        rc, out, _ = self.run_octo(["replay", "sess-1"])
        self.assertEqual(rc, 0)
        self.assertIn("refused   (none)", out)
        self.assertIn("receipts  (none)", out)
        self.assertIn("children  0", out)

    def test_refused_counts_only_denies_that_pair_with_a_journaled_call(self):
        """A Stop block refuses a TURN, not a tool call the gate journaled.

        Counting it as a refused tool call reported more refusals than there
        were calls, which is how a summary loses the reader's trust.
        """
        self.seed_run()
        kernel_proc.journal_deny("COMMS.paste-ready-raw-message",
                                 "the draft is not raw", "toolu_never_ran", "agent-1")
        st = octo._stats(kernel_proc.read_journal("agent-1"))
        self.assertEqual(st["tools"], 2)
        self.assertEqual(st["denies"], 2, "both refusals stay visible")
        self.assertEqual(st["refused"], 1, "only the one that paired with a call")
        _, out, _ = self.run_octo(["replay", "agent-1"])
        self.assertIn("tools     2 (1 refused)", out)
        self.assertIn("COMMS.paste-ready-raw-message", out,
                      "an unpaired deny still shows on the timeline")


# ── the receipt join ────────────────────────────────────────────────────────

class DenySourceTest(ReplayCase):
    def test_a_harness_refusal_is_labelled_source_harness_on_the_timeline(self):
        """A reader who cannot tell an Octorato gate from a harness denial cannot
        act on either: one is a rule to argue with, the other a permission to
        grant."""
        self.seed_run()
        kernel_proc.journal_deny("HARNESS.permission-denied",
                                 "Claude requested permissions to use Write, but you "
                                 "haven't granted it yet.",
                                 "toolu_b", "agent-1", source="harness",
                                 permission_mode="acceptEdits")
        rc, out, _ = self.run_octo(["replay", "agent-1"])
        self.assertEqual(rc, 0)
        harness = [l for l in out.splitlines() if "HARNESS.permission-denied" in l
                   and "REFUSED" in l or "deny" in l and "HARNESS" in l]
        self.assertTrue(harness, "the harness refusal is missing from the timeline")
        self.assertIn("source=harness", "\n".join(harness))
        octo_line = [l for l in out.splitlines()
                     if "ARCHITECTURE.session-isolation" in l and "  #" in l][0]
        self.assertNotIn("source=", octo_line,
                         "an Octorato refusal is the common case and stays unannotated")

    def test_the_permission_denied_reflex_records_the_runtimes_own_reason(self):
        """2.1.261 sends {tool_name, tool_input, tool_use_id, reason} and no
        denial-kind field: `toolDenialKind` lives on transcript tool_result
        records, never on the hook payload."""
        import subprocess
        fixture = ROOT / "registry" / "fixtures" / "FLOW.kernel-journal" / "permission_denied.json"
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        self.assertNotIn("toolDenialKind", payload,
                         "the fixture must be the shape the runtime actually sends")
        env = dict(os.environ)
        env["HOME"] = env["USERPROFILE"] = self.home
        subprocess.run([sys.executable,
                        str(SCRIPTS / "r__permission-denied__journal.py")],
                       input=json.dumps(payload), capture_output=True, text=True,
                       cwd=self.home, env=env, timeout=30)
        denies = [l for l in kernel_proc.read_journal(payload["agent_id"])
                  if isinstance(l, dict) and l.get("kind") == "deny"]
        self.assertEqual(len(denies), 1)
        self.assertEqual(denies[0]["reason"], payload["reason"])
        self.assertEqual(denies[0]["permission_mode"], payload["permission_mode"])
        self.assertEqual(denies[0]["source"], "harness")


class ReceiptJoinTest(ReplayCase):
    def test_a_seek_inside_a_subagent_lands_in_the_agents_journal(self):
        """The ledger stays keyed by session; the JOURNAL is keyed by process.

        Mirroring by session id credited the parent with the child's seek, which
        is the same class of error as attributing a refusal to the wrong run.
        """
        self.seed_run()
        receipt_ledger.append_session("sess-1", {
            "kind": "seek", "agent_id": "agent-1", "tool_use_id": "toolu_a",
            "tool_name": "mcp__whatsapp__list_messages", "query": "27,180"})
        agent = [l for l in kernel_proc.read_journal("agent-1")
                 if isinstance(l, dict) and l.get("kind") == "receipt"]
        parent = [l for l in kernel_proc.read_journal("sess-1")
                  if isinstance(l, dict) and l.get("kind") == "receipt"]
        self.assertEqual(len(agent), 1, "the child made the seek, the child records it")
        self.assertEqual(parent, [], "the parent must not be credited with it")
        self.assertEqual(kernel_proc.verify("agent-1"), 0)

    def test_a_seek_with_no_agent_falls_back_to_the_session(self):
        kernel_proc.register("sess-1", {"kind": "main", "worktree": "/w"})
        receipt_ledger.append_session("sess-1", {"kind": "seek", "agent_id": "",
                                                 "tool_use_id": "toolu_a"})
        kinds = [l.get("kind") for l in kernel_proc.read_journal("sess-1")
                 if isinstance(l, dict)]
        self.assertIn("receipt", kinds)

    def test_the_seek_reflex_puts_the_agent_id_in_the_record(self):
        """The mirror can only attribute what the writer recorded."""
        src = (SCRIPTS / "r__posttool__receipt-seek.py").read_text(encoding="utf-8")
        self.assertIn('"agent_id": data.get("agent_id")', src)


    def test_a_childs_replay_labels_the_session_receipts_as_the_parents(self):
        """The ledger is keyed by SESSION, so a child shows its parent's seeks.

        Labelling that section plainly is the difference between a reader
        crediting the child with a seek it made and one it never did.
        """
        self.seed_run()
        receipt_ledger.append_session("sess-1", {
            "kind": "seek", "tool_use_id": "toolu_a",
            "tool_name": "mcp__whatsapp__list_messages", "query": "27,180"})
        rc, out, _ = self.run_octo(["replay", "agent-1"])
        self.assertEqual(rc, 0)
        self.assertIn("receipts (session)", out)
        self.assertIn("seek  toolu_a", out)

        rc, out, _ = self.run_octo(["replay", "sess-1"])
        self.assertEqual(rc, 0)
        self.assertIn("\nreceipts\n", out,
                      "the session's own replay has no borrowed receipts to flag")

    def test_writing_a_receipt_mirrors_its_identity_into_the_journal(self):
        kernel_proc.register("sess-1", {"kind": "main", "worktree": "/w"})
        receipt_ledger.append_session("sess-1", {
            "kind": "seek", "tool_use_id": "toolu_a", "query": "secret query text"})
        mirrored = [l for l in kernel_proc.read_journal("sess-1")
                    if isinstance(l, dict) and l.get("kind") == "receipt"]
        self.assertEqual(len(mirrored), 1)
        rec = mirrored[0]
        self.assertEqual(rec["receipt_kind"], "seek")
        self.assertEqual(rec["tool_use_id"], "toolu_a")
        self.assertEqual(len(rec["receipt_sha256"]), 64)
        self.assertNotIn("secret query text", json.dumps(rec),
                         "the journal mirrors identity, never the receipt's content")
        self.assertEqual(kernel_proc.verify("sess-1"), 0)

    def test_a_global_receipt_naming_no_process_is_not_mirrored_into_one(self):
        kernel_proc.register("sess-1", {"kind": "main", "worktree": "/w"})
        receipt_ledger.append_global({"kind": "gate-liveness", "ok": True})
        kinds = [l.get("kind") for l in kernel_proc.read_journal("sess-1")
                 if isinstance(l, dict)]
        self.assertNotIn("receipt", kinds)


# ── orphan rule ids: RULE #1 pointed at the journal ─────────────────────────

def orphan_deny_rules(pids, registered, since=None) -> dict:
    """Deny rule ids in these journals that no registry row carries.

    The doctor's `kernel-replay` check asks exactly this question over the last
    7 days; the helper is here so the QUESTION is unit-tested without running
    the whole doctor against the machine's real journals.
    """
    out = {}
    for pid in pids:
        for line in kernel_proc.read_journal(pid):
            if not isinstance(line, dict) or line.get("kind") != "deny":
                continue
            if since is not None and float(line.get("ts") or 0) < since:
                continue
            rule = str(line.get("rule") or "")
            if rule not in registered:
                out.setdefault(rule or "(unnamed)", []).append(pid)
    return out


class OrphanRuleTest(ReplayCase):
    def test_a_deny_naming_an_unregistered_rule_is_an_orphan(self):
        self.seed_run()
        kernel_proc.journal_deny("FLOW.a-rule-nobody-registered", "why", "toolu_b", "agent-1")
        registered = {"ARCHITECTURE.session-isolation"}
        orphans = orphan_deny_rules(["agent-1"], registered)
        self.assertEqual(list(orphans), ["FLOW.a-rule-nobody-registered"])

    def test_a_deny_with_no_rule_at_all_is_an_orphan_too(self):
        kernel_proc.register("sess-1", {"kind": "main", "worktree": "/w"})
        kernel_proc.append("sess-1", {"kind": "deny", "reason": "no rule named"})
        self.assertEqual(list(orphan_deny_rules(["sess-1"], {"X.y"})), ["(unnamed)"])

    def test_the_window_excludes_a_deny_older_than_the_cutoff(self):
        kernel_proc.register("sess-1", {"kind": "main", "worktree": "/w"})
        kernel_proc.append("sess-1", {"kind": "deny", "rule": "OLD.gone",
                                      "ts": time.time() - 30 * 24 * 3600})
        self.assertEqual(orphan_deny_rules(["sess-1"], set(),
                                           since=time.time() - 7 * 24 * 3600), {})

    def test_every_rule_the_shipped_gates_journal_is_registered(self):
        """The static half of the doctor check, run at unit-test speed.

        Each gate hard-codes the rule id it journals in `_KERNEL_RULE`. If one
        drifts (a rule renamed in the registry, a copy-paste into a new gate),
        the deny lines it writes become orphans on the first real refusal, and
        the doctor would be the first to notice - after the fact.
        """
        import re

        import yaml
        registered = {r.get("id") for r in
                      (yaml.safe_load((ROOT / "registry" / "rules.yaml")
                                      .read_text(encoding="utf-8")) or {}).get("rules", [])}
        pattern = re.compile(r'^_KERNEL_RULE = "([^"]+)"', re.M)
        found = {}
        for path in sorted(SCRIPTS.glob("*.py")):
            m = pattern.search(path.read_text(encoding="utf-8"))
            if m:
                found[path.name] = m.group(1)
        self.assertGreaterEqual(len(found), 13,
                                "every fail-closed gate should journal its refusals")
        orphans = {f: r for f, r in found.items() if r not in registered}
        self.assertEqual(orphans, {}, f"gates journal unregistered rule ids: {orphans}")


class GateSelftestJournalTest(ReplayCase):
    """D5: the selftest runner must PROVE a gate journals, not assume it.

    Ten of twelve fixture-driven gates had violation fixtures with no
    session_id, so `journal_deny` resolved no pid and quietly did nothing for
    the whole selftest. Every gate passed while none of them proved the mirror.
    """

    def test_a_fixture_with_no_session_id_gets_the_selftest_one(self):
        import gate_selftest
        fdir = ROOT / "registry" / "fixtures" / "SECURITY.never-read-secrets-raw"
        raw = json.loads((fdir / "violation.json").read_text(encoding="utf-8"))
        prepared = json.loads(gate_selftest._prep_payload(
            fdir / "violation.json", fdir, Path(self.home)))
        self.assertEqual(prepared["session_id"],
                         raw.get("session_id") or gate_selftest.SELFTEST_SESSION)

    def test_a_fixture_that_names_its_own_session_keeps_it(self):
        import gate_selftest
        fdir = Path(self.home)
        (fdir / "violation.json").write_text(
            json.dumps({"session_id": "fixture-owned", "tool_name": "Bash"}),
            encoding="utf-8")
        prepared = json.loads(gate_selftest._prep_payload(
            fdir / "violation.json", fdir, fdir))
        self.assertEqual(prepared["session_id"], "fixture-owned")

    def test_the_assertion_fails_when_a_gate_stops_journaling(self):
        """The control. An assertion that cannot fail proves nothing, so a copy
        of a real gate with its mirror call removed must be caught."""
        import shutil
        import subprocess
        src = SCRIPTS / "secrets-grep-guard.py"
        body = src.read_text(encoding="utf-8")
        broken = SCRIPTS / "_selftest_control_secrets_guard.py"
        stripped = body.replace("_journal_deny(_DENY_REASON, data)", "pass")
        self.assertNotEqual(stripped, body, "the control did not remove the mirror call")
        broken.write_text(stripped, encoding="utf-8")
        self.addCleanup(lambda: broken.unlink(missing_ok=True))
        fdir = ROOT / "registry" / "fixtures" / "SECURITY.never-read-secrets-raw"
        env = dict(os.environ)
        env["HOME"] = env["USERPROFILE"] = self.home
        cp = subprocess.run(
            [sys.executable, str(SCRIPTS / "gate_selftest.py"), str(broken), str(fdir)],
            capture_output=True, text=True, timeout=120, env=env, cwd=str(ROOT))
        self.assertEqual(cp.returncode, 1,
                         "a gate that blocks but journals nothing must not pass")
        self.assertIn("journaled", cp.stderr)
        # and the real one still passes, so the control is measuring the edit
        cp_ok = subprocess.run(
            [sys.executable, str(SCRIPTS / "gate_selftest.py"), str(src), str(fdir)],
            capture_output=True, text=True, timeout=120, env=env, cwd=str(ROOT))
        self.assertEqual(cp_ok.returncode, 0, cp_ok.stderr)
        shutil.rmtree(self.home, ignore_errors=True)
        os.makedirs(self.home, exist_ok=True)


# ── the fail-open contract ──────────────────────────────────────────────────

class FailOpenTest(ReplayCase):
    def test_journal_deny_swallows_an_unwritable_journal_dir(self):
        """The journal directory is a FILE: every append raises OSError."""
        os.makedirs(os.path.join(self.home, ".claude", ".cache", "kernel"), exist_ok=True)
        with open(kernel_proc.journal_dir(), "w", encoding="utf-8") as fh:
            fh.write("not a directory")
        self.assertFalse(kernel_proc.journal_deny("X.y", "reason", "toolu_1", "sess-1"))
        self.assertFalse(kernel_proc.journal_receipt("sess-1", "seek", "toolu_1", {}))

    def test_journal_deny_is_a_no_op_without_a_pid_rather_than_a_guess(self):
        self.assertFalse(kernel_proc.journal_deny("X.y", "reason", "toolu_1", ""))
        self.assertFalse(kernel_proc.journal_deny("X.y", "reason", "toolu_1", None))

    def test_a_gates_verdict_is_unchanged_when_the_journal_cannot_be_written(self):
        """The property the whole mirror rests on, proved end to end.

        The gate runs twice on the same violation: once with a working journal,
        once with the journal directory replaced by a file. Byte-identical
        stdout and the same exit code both times, so a broken journal can never
        turn a deny into an allow (nor an allow into a deny).
        """
        gate = SCRIPTS / "g__pretool-bash__git-discipline.py"
        payload = json.dumps({
            "session_id": "sess-fo", "hook_event_name": "PreToolUse",
            "tool_name": "Bash", "tool_use_id": "toolu_fo",
            "tool_input": {"command": "git push --force origin main"},
            "cwd": self.home,
        })

        def run_gate(home):
            env = dict(os.environ)
            env["HOME"] = home
            env["USERPROFILE"] = home
            env.pop("OCTO_ALLOW_FORCE", None)
            cp = subprocess.run([sys.executable, str(gate)], input=payload,
                                capture_output=True, text=True, cwd=home,
                                env=env, timeout=30)
            return cp.returncode, cp.stdout

        rc_ok, out_ok = run_gate(self.home)
        self.assertIn('"permissionDecision": "deny"', out_ok)
        self.assertTrue(any(l.get("kind") == "deny"
                            for l in kernel_proc.read_journal("sess-fo")
                            if isinstance(l, dict)),
                        "the working case must actually journal, or the test proves nothing")

        broken = tempfile.mkdtemp(prefix="octo-replay-broken-")
        try:
            os.makedirs(os.path.join(broken, ".claude", ".cache", "kernel"), exist_ok=True)
            with open(os.path.join(broken, ".claude", ".cache", "kernel", "journal"),
                      "w", encoding="utf-8") as fh:
                fh.write("not a directory")
            rc_broken, out_broken = run_gate(broken)
        finally:
            import shutil
            shutil.rmtree(broken, ignore_errors=True)

        self.assertEqual(rc_ok, rc_broken)
        self.assertEqual(out_ok, out_broken,
                         "a journal failure must not change one byte of the verdict")


# ── the golden fixture ──────────────────────────────────────────────────────

class GoldenTest(ReplayCase):
    def test_the_golden_replay_matches_byte_for_byte_with_verify(self):
        expected = (REPLAY_FIXTURE / "expected.txt").read_text(encoding="utf-8")
        rc, out, _ = self.run_octo(["replay", "--fixture", str(REPLAY_FIXTURE), "--verify"])
        self.assertEqual(rc, 0)
        self.assertEqual(out, expected)

    def test_the_golden_carries_a_receipt_and_a_child(self):
        """Phase 4 widened the contract; a fixture that lost either would still
        pass a byte compare against a regenerated expected.txt, so the SHAPE is
        pinned here rather than only the bytes."""
        expected = (REPLAY_FIXTURE / "expected.txt").read_text(encoding="utf-8")
        self.assertIn("receipts  seek 1", expected)
        self.assertIn("children  1: kernel-golden-child", expected)
        self.assertIn("REFUSED", expected)
        kinds = [json.loads(l)["kind"] for l in
                 (REPLAY_FIXTURE / "journal.jsonl").read_text(encoding="utf-8").splitlines() if l]
        self.assertEqual(kinds, ["start", "tool", "receipt", "tool", "deny", "tool",
                                 "deny", "deny", "exit"])
        self.assertIn("source=harness", expected,
                      "the golden must show a harness refusal apart from an Octorato one")
        self.assertIn("other denies  COMMS.paste-ready-raw-message 1", expected,
                      "and a deny that refused a turn, not a call")


class TopTest(ReplayCase):
    def test_top_reports_denies_by_rule(self):
        self.seed_run()
        kernel_proc.journal_deny("ARCHITECTURE.session-isolation", "again",
                                 "toolu_a", "agent-1")
        rc, out, _ = self.run_octo(["top"])
        self.assertEqual(rc, 0)
        self.assertIn("denies by rule", out)
        self.assertIn("ARCHITECTURE.session-isolation  2", out)

    def test_top_and_ps_agree_on_the_word_for_a_process_that_aged_out(self):
        """One vocabulary for two readers: `expired`, not `exited` in one and
        `expired` in the other."""
        kernel_proc.register("sess-old", {"kind": "main", "worktree": "/w"})
        path = kernel_proc.journal_path("sess-old")
        old = time.time() - (kernel_proc.TTL + 600)
        # BOTH halves, since cycle 5 C4: liveness re-checks a stale mtime
        # against the `ts` of the last chained record, so `os.utime` alone is
        # the attack it now refuses, not an expiry.
        with open(path, encoding="utf-8") as fh:
            lines = [l for l in fh.read().split("\n") if l.strip()]
        rec = json.loads(lines[-1]); rec["ts"] = old
        lines[-1] = json.dumps(rec, separators=(",", ":"))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        os.utime(path, (old, old))
        _, ps_out, _ = self.run_octo(["ps"])
        _, top_out, _ = self.run_octo(["top"])
        ps_row = [l for l in ps_out.splitlines() if l.startswith("sess-old")][0]
        top_row = [l for l in top_out.splitlines() if l.startswith("sess-old")][0]
        self.assertIn("expired", ps_row)
        self.assertIn("expired", top_row)


class PruneTest(ReplayCase):
    def test_reading_an_empty_home_creates_no_kernel_state(self):
        """`octo ps` prunes on read. A read must not be what materialises the
        kernel directory on a machine that has never run a hook: the lock file
        it left behind made a fresh install look like it had state."""
        rc, out, _ = self.run_octo(["ps"])
        self.assertEqual(rc, 0)
        self.assertFalse(os.path.exists(os.path.join(
            self.home, ".claude", ".cache", "kernel", ".ptable.lock")))
        self.assertFalse(os.path.exists(kernel_proc.ptable_path()))


if __name__ == "__main__":
    unittest.main()
