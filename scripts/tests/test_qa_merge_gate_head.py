#!/usr/bin/env python3
"""The merge gate binds a QA PASS to the commit it reviewed.

docs/specs/202610012100-qa-receipt-bound-to-head. Each test drives the gate's
own main() with a hook payload, the operator's approval in the environment, and
a stand-in for the receipt lookup, so what is proven is the gate's decision:
the pin it reads from the command, the --auto refusal, the newest-verdict rule,
the deadline, the bypass and the messages. The lookup itself is proven in
test_receipt_ledger.py.

Stdlib only:  python3 -m unittest scripts.tests.test_qa_merge_gate_head
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import receipt_ledger  # noqa: E402

_spec = importlib.util.spec_from_file_location("qa_merge_gate", SCRIPTS / "qa-merge-gate.py")
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)

SHA = "c" * 40
OTHER = "d" * 40


def receipt(verdict):
    return {"kind": "qa", "verdict": verdict, "agent_type": "Reality Checker", "verdict_ts": "2026-10-01T10:00:00Z"}


class GateHead(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gate-head-")
        self.env = mock.patch.dict(os.environ, {"HOME": self.tmp, "USERPROFILE": self.tmp,
                                                "OCTO_MERGE_APPROVE": "96"})
        self.env.start()
        os.environ.pop("OCTO_QA_OK", None)
        self.protected = mock.patch.object(gate, "_is_protected_target", lambda *a, **k: True)
        self.protected.start()
        self.calls = []

    def tearDown(self):
        self.protected.stop()
        self.env.stop()

    def lookup(self, answers):
        """Patch the ledger lookup: answers maps a commit to its newest receipt."""
        def fake(token, head):
            self.calls.append((token, head))
            return answers.get(head)
        return mock.patch.object(receipt_ledger, "qa_latest_for", fake)

    def run_gate(self, command):
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command},
                              "session_id": "s", "cwd": self.tmp})
        err, out = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(payload)), \
                contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            rc = gate.main()
        return rc, err.getvalue()

    # ---- the pin (AC-03, AC-04, AC-05) ----
    def test_an_approved_merge_with_no_pin_blocks_and_names_the_flag(self):
        with self.lookup({SHA: receipt("PASS")}):
            for cmd in ("gh pr merge 96 --squash --delete-branch",
                        f"gh pr merge 96 --match-head-commit {SHA[:12]}",
                        "gh pr merge 96 --match-head-commit"):
                rc, err = self.run_gate(cmd)
                self.assertEqual(rc, 2, cmd)
                self.assertIn("--match-head-commit", err, cmd)
                self.assertIn("QA-HEAD", err, cmd)
        self.assertEqual(self.calls, [])

    def test_a_pin_that_gh_would_not_send_is_no_pin(self):
        cases = [f'gh pr merge 96 -t "ship --match-head-commit {SHA}"',
                 f"gh pr merge 96 -t --match-head-commit={SHA}",
                 f"gh pr merge 96 --subject --match-head-commit={SHA}",
                 f"gh pr merge 96 --subject=x -b --match-head-commit={SHA}",
                 f"gh pr merge 96 -A --match-head-commit={SHA}",
                 f"gh pr merge 96 -R --match-head-commit={SHA}",
                 f"gh pr merge 96 -F --match-head-commit={SHA}",
                 f"gh pr merge 96 -t=--match-head-commit={SHA}",
                 f"gh pr merge 96 -st --match-head-commit={SHA}",
                 f"gh pr merge 96 -sdt --match-head-commit={SHA}",
                 f"gh pr merge 96 -mt --match-head-commit={SHA}",
                 f"gh api -X PUT repos/o/r/pulls/96/merge -f commit_message=sha={SHA}",
                 f"gh api -X PUT repos/o/r/pulls/96/merge -H sha={SHA}",
                 f"gh api -X PUT repos/o/r/pulls/96/merge --input body.json",
                 f"gh api -X PUT repos/o/r/pulls/96/merge --input body.json -f sha={SHA}",
                 f"gh api -X PUT repos/o/r/pulls/96/merge -f sha={SHA} --input -",
                 f"gh api -X PUT repos/o/r/pulls/96/merge -f sha={SHA} --input=body.json",
                 f"curl -X PUT -d '{{\"sha\":\"{SHA}\"}}' https://api.github.com/repos/o/r/pulls/96/merge"]
        with self.lookup({SHA: receipt("PASS")}):
            for cmd in cases:
                rc, err = self.run_gate(cmd)
                self.assertEqual(rc, 2, cmd)
                self.assertIn("pins no commit", err, cmd)
        self.assertEqual(self.calls, [])

    def test_a_passing_pin_opens_the_gate_in_every_readable_form(self):
        forms = [f"gh pr merge 96 --squash --delete-branch --match-head-commit {SHA}",
                 f"gh pr merge 96 -sd --match-head-commit={SHA.upper()}",
                 f"gh pr merge 96 -R o/r -t done --match-head-commit {SHA}",
                 f"gh pr merge 96 --match-head-commit {OTHER} --match-head-commit {SHA}",
                 f"gh api -X PUT repos/o/r/pulls/96/merge -f sha={SHA}",
                 f"gh api -X PUT repos/o/r/pulls/96/merge --raw-field=sha={SHA}",
                 f"gh api -X PUT repos/o/r/pulls/96/merge -Fsha={SHA}"]
        with self.lookup({SHA: receipt("PASS")}):
            for cmd in forms:
                rc, err = self.run_gate(cmd)
                self.assertEqual(rc, 0, f"{cmd}\n{err}")
        self.assertTrue(all(c == ("96", SHA) for c in self.calls), self.calls)

    # ---- every sub-command, and what bash actually passes (AC-19) ----
    def test_a_chained_unpinned_merge_cannot_ride_on_a_pinned_one(self):
        pinned = f"gh pr merge 96 --squash --match-head-commit {SHA}"
        with self.lookup({SHA: receipt("PASS")}):
            for tail in (" || gh pr merge 96 --squash", "; gh pr merge 96 --auto",
                         " && gh api -X PUT repos/o/r/pulls/96/merge"):
                rc, _ = self.run_gate(pinned + tail)
                self.assertEqual(rc, 2, tail)
            # Every separator bash honours, and a comment whose apostrophe opens no quote.
            for tail in (" & gh pr merge 96", " |& gh pr merge 96",
                         " # it's done\ngh pr merge 96"):
                rc, _ = self.run_gate(pinned + tail)
                self.assertEqual(rc, 2, tail)
            rc, _ = self.run_gate("echo hi # don't\ngh pr merge 96 --squash")
            self.assertEqual(rc, 2)
            # Redirection ampersands are not separators.
            for ok in (f"{pinned} && echo done", f"{pinned} 2>&1 | tee log",
                       f"{pinned} &>/dev/null", f"{pinned} # merged it's fine"):
                rc, err = self.run_gate(ok)
                self.assertEqual(rc, 0, f"{ok}\n{err}")

    def test_a_pin_behind_a_shell_comment_is_no_pin(self):
        with self.lookup({SHA: receipt("PASS")}):
            for cmd in (f"gh pr merge 96 --squash # --match-head-commit {SHA}",
                        f"gh api -X PUT repos/o/r/pulls/96/merge # -f sha={SHA}"):
                rc, err = self.run_gate(cmd)
                self.assertEqual(rc, 2, cmd)
                self.assertIn("pins no commit", err, cmd)
            rc, _ = self.run_gate(f"gh pr merge 96 -t 'fix #12' --match-head-commit {SHA}")
            self.assertEqual(rc, 0)

    def test_a_mid_word_hash_hides_no_later_pin(self):
        # bash keeps a mid-word `#`; gh sends the LAST pin, which nobody reviewed.
        with self.lookup({SHA: receipt("PASS")}):
            for cmd in (f"gh pr merge 96 --match-head-commit {SHA} -t#x --match-head-commit {OTHER}",
                        f"gh pr merge 96 --match-head-commit {SHA} --subject=#x --match-head-commit {OTHER}",
                        f"gh api -X PUT repos/o/r/pulls/96/merge -f sha={SHA} -f x=#y -f sha={OTHER}"):
                rc, _ = self.run_gate(cmd)
                self.assertEqual(rc, 2, cmd)
            rc, _ = self.run_gate(f"gh pr merge 96 -t#x --match-head-commit {SHA}")
            self.assertEqual(rc, 0)
        self.assertIn(("96", OTHER), self.calls)

    # ---- syntax the gate does not read, while an approval is exported (AC-20) ----
    def test_an_approved_merge_inside_unparsed_syntax_blocks(self):
        pinned = f"gh pr merge 96 --squash --match-head-commit {SHA}"
        shapes = [f"{pinned} # done \\\ngh pr merge 96",               # continuation in a comment
                  "echo a\\\\\ngh pr merge 96",                         # escaped backslash, then newline
                  f"{pinned}\ncat <<EOF\nit's\nEOF\ngh pr merge 96",    # heredoc body with a quote
                  f"{pinned} -t $'x\\''\ngh pr merge 96\necho '",       # ANSI-C quoting
                  f"gh pr merge 96 --match-head-commit {SHA} -t x\\ #y --match-head-commit {OTHER}",
                  f"\\gh pr merge 96 --match-head-commit {SHA}",
                  f"bash -c 'gh pr merge 96 --match-head-commit {SHA}'",
                  f"echo \"$(gh pr merge 96)\"; {pinned}"]
        with self.lookup({SHA: receipt("PASS")}):
            for cmd in shapes:
                rc, err = self.run_gate(cmd)
                self.assertEqual(rc, 2, cmd)
                self.assertIn("does not parse", err, cmd)
        self.assertEqual(self.calls, [])

    def test_without_an_approval_quoted_merges_in_data_are_left_alone(self):
        os.environ.pop("OCTO_MERGE_APPROVE", None)
        for cmd in ("cat > notes.md <<'EOF'\nrun gh pr merge 96 --match-head-commit <sha>\nEOF",
                    "python3 - <<'PY'\nprint('gh pr merge 96')\nPY",
                    "git commit -q -F - <<'EOF'\nteach gh pr merge <n> --match-head-commit\nEOF"):
            rc, _ = self.run_gate(cmd)
            self.assertEqual(rc, 0, cmd)
        # A heredoc fed to a shell is a script, so its merge is still a merge.
        rc, _ = self.run_gate("bash <<EOF\ngh pr merge 96 --squash\nEOF")
        self.assertEqual(rc, 2)

    def test_reserved_words_quoted_heads_and_global_repo_flag_are_merges(self):
        with self.lookup({SHA: receipt("PASS")}):
            for cmd in ("if true; then gh pr merge 96; fi", "! gh pr merge 96",
                        "'gh' pr merge 96", "gh -R o/r pr merge 96", "time gh pr merge 96",
                        "while true; do gh pr merge 96; done"):
                rc, err = self.run_gate(cmd)
                self.assertEqual(rc, 2, cmd)
                self.assertIn("pins no commit", err, cmd)
            for cmd in (f"'gh' pr merge 96 --match-head-commit {SHA}",
                        f"gh -R o/r pr merge 96 --match-head-commit {SHA}",
                        f"if true; then gh pr merge 96 --match-head-commit {SHA}; fi"):
                rc, err = self.run_gate(cmd)
                self.assertEqual(rc, 0, f"{cmd}\n{err}")

    def test_split_matches_bash_on_escapes_continuations_ansi_c_and_case(self):
        # Each of these runs `gh pr merge 5` in bash; with no approval it must block.
        os.environ.pop("OCTO_MERGE_APPROVE", None)
        for cmd in ("echo \\ #x; gh pr merge 5", "echo a\\\t#x; gh pr merge 5",
                    "echo \\>& gh pr merge 5", "echo \\<&gh pr merge 5",
                    "echo $'a\\'b'; gh pr merge 5", "echo x # c \\\ngh pr merge 5",
                    "gh pr \\\nmerge 5", "echo a\\\\\ngh pr merge 5",
                    "case x in x) gh pr merge 5;; esac", "for i in 1; do gh pr merge 5; done"):
            rc, _ = self.run_gate(cmd)
            self.assertEqual(rc, 2, repr(cmd))

    # ---- --auto (AC-06) ----
    def test_auto_is_refused_on_an_approved_merge(self):
        with self.lookup({SHA: receipt("PASS")}):
            rc, err = self.run_gate(f"gh pr merge 96 --auto --squash --match-head-commit {SHA}")
        self.assertEqual(rc, 2)
        self.assertIn("--auto", err)
        # `--auto` as the subject is not the flag.
        with self.lookup({SHA: receipt("PASS")}):
            rc, _ = self.run_gate(f"gh pr merge 96 -t --auto --match-head-commit {SHA}")
        self.assertEqual(rc, 0)

    # ---- the receipt (AC-07, AC-08, AC-09) ----
    def test_the_newest_verdict_for_the_pinned_commit_decides(self):
        cmd = f"gh pr merge 96 --squash --match-head-commit {SHA}"
        for answers, want in (({}, 2),
                              ({OTHER: receipt("PASS")}, 2),
                              ({SHA: receipt("NEEDS-WORK")}, 2),
                              ({SHA: receipt("FAIL")}, 2),
                              ({SHA: receipt("PASS")}, 0)):
            with self.lookup(answers):
                rc, err = self.run_gate(cmd)
            self.assertEqual(rc, want, (answers, err))
            if want == 2:
                self.assertIn("QA-HEAD", err)
        with self.lookup({SHA: receipt("NEEDS-WORK")}):
            _, err = self.run_gate(cmd)
        self.assertIn("NEEDS-WORK", err)

    # ---- the deadline (AC-15) ----
    def test_a_lookup_stuck_past_the_deadline_blocks(self):
        def stuck(token, head):
            time.sleep(30)
            return receipt("PASS")
        with mock.patch.object(gate, "_LOOKUP_DEADLINE", 0.5), \
                mock.patch.object(receipt_ledger, "qa_latest_for", stuck):
            t0 = time.monotonic()
            rc, err = self.run_gate(f"gh pr merge 96 --match-head-commit {SHA}")
            took = time.monotonic() - t0
        self.assertEqual(rc, 2)
        self.assertIn("did not finish", err)
        self.assertLess(took, 5)

    # ---- no network (AC-10) ----
    def test_the_decision_starts_no_process_and_opens_no_socket(self):
        import socket
        import subprocess
        def refuse(*a, **k):
            raise AssertionError("the gate must not start a process or open a socket")
        with self.lookup({SHA: receipt("PASS")}), \
                mock.patch.object(socket.socket, "connect", refuse), \
                mock.patch.object(subprocess, "Popen", refuse):
            rc, err = self.run_gate(f"gh pr merge 96 --match-head-commit {SHA}")
        self.assertEqual(rc, 0, err)

    # ---- the bypass and the old rule (AC-11, AC-12) ----
    def test_the_bypass_lifts_the_receipt_the_pin_and_the_auto_refusal(self):
        os.environ["OCTO_QA_OK"] = "1"
        try:
            with self.lookup({}):
                rc, _ = self.run_gate("gh pr merge 96 --auto --squash")
        finally:
            os.environ.pop("OCTO_QA_OK", None)
        self.assertEqual(rc, 0)
        self.assertEqual(self.calls, [])

    def test_a_branch_push_keeps_todays_rule(self):
        os.environ["OCTO_MERGE_APPROVE"] = "main"
        seen = []
        with mock.patch.object(receipt_ledger, "qa_pass_for", lambda *a, **k: seen.append(a) or receipt("PASS")), \
                self.lookup({}):
            rc, _ = self.run_gate("git push origin main")
        self.assertEqual(rc, 0)
        self.assertEqual(seen[0][0], "main")
        self.assertEqual(self.calls, [])

    def test_without_approval_the_message_still_shows_the_pinned_command(self):
        os.environ["OCTO_MERGE_APPROVE"] = "1"
        rc, err = self.run_gate(f"gh pr merge 96 --match-head-commit {SHA}")
        self.assertEqual(rc, 2)
        self.assertIn("--match-head-commit", err)


if __name__ == "__main__":
    unittest.main()
