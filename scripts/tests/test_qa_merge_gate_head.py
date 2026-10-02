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
                       f"{pinned} &>/dev/null", f"{pinned} # merged"):
                rc, err = self.run_gate(ok)
                self.assertEqual(rc, 0, f"{ok}\n{err}")
            # On the approved path a command the two readings disagree on blocks:
            # the previous reading keeps the comment and its lone quote.
            rc, _ = self.run_gate(f"{pinned} # merged it's fine")
            self.assertEqual(rc, 2)

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
        # Two pin candidates: neither is trusted, so only the single-pin command
        # reached a receipt lookup.
        self.assertEqual(self.calls, [("96", SHA)])

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

    def test_heredoc_bodies_are_read_line_by_line(self):
        # A body can reach a shell in more ways than a list names, so every body
        # line is read as a command (fail-closed, as on master), each with fresh
        # quote state so a quote in the body hides nothing after it.
        os.environ.pop("OCTO_MERGE_APPROVE", None)
        for cmd in ("cat <<EOF | bash\ngh pr merge 96\nEOF", "exec bash <<EOF\ngh pr merge 96\nEOF",
                    "/usr/bin/env bash <<EOF\ngh pr merge 96\nEOF", "source /dev/stdin <<EOF\ngh pr merge 96\nEOF",
                    "<<EOF bash\ngh pr merge 96\nEOF", "cat <<EOF\nit's\nEOF\ngh pr merge 96",
                    'cat <<"E O"\nx\nE O\ngh pr merge 96'):
            rc, _ = self.run_gate(cmd)
            self.assertEqual(rc, 2, repr(cmd))
        # Plain data with no merge in it passes.
        rc, _ = self.run_gate("cat > notes.md <<'EOF'\nit's fine\nEOF\necho done")
        self.assertEqual(rc, 0)

    def test_a_shift_in_arithmetic_is_not_a_heredoc(self):
        os.environ.pop("OCTO_MERGE_APPROVE", None)
        for cmd in ("echo $((1<<2))\ngh pr merge 96", "(( x = 1 << 2 ))\ngh pr merge 96",
                    "echo $[1<<2]\ngh pr merge 96"):
            rc, _ = self.run_gate(cmd)
            self.assertEqual(rc, 2, repr(cmd))

    def test_ansi_c_and_repo_flag_after_pr_are_read(self):
        with self.lookup({SHA: receipt("PASS")}):
            for cmd in ("gh pr $'merge' 96", "gh pr $'\\x6derge' 96",
                        "gh api -X PUT repos/o/r/pulls/96/$'merge'"):
                rc, err = self.run_gate(cmd)
                self.assertEqual(rc, 2, cmd)
                self.assertIn("does not parse", err, cmd)
            rc, err = self.run_gate("gh pr -R o/r merge 96")
            self.assertEqual(rc, 2)
            self.assertIn("pins no commit", err)
            rc, err = self.run_gate(f"gh pr -R o/r merge 96 --match-head-commit {SHA}")
            self.assertEqual(rc, 0, err)

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

    def test_honest_wrappers_and_path_qualified_gh_are_merges(self):
        with self.lookup({SHA: receipt("PASS")}):
            for cmd in ("/usr/bin/gh pr merge 96", "./bin/gh pr merge 96", "timeout 5 gh pr merge 96",
                        "timeout -k 2 30s gh pr merge 96", "exec gh pr merge 96", "nohup gh pr merge 96",
                        "time -p gh pr merge 96", "nice -n 5 gh pr merge 96", "gh -Rfoo/bar pr merge 96",
                        "(true)#'\ngh pr merge 96\n#'"):
                rc, err = self.run_gate(cmd)
                self.assertEqual(rc, 2, repr(cmd))
            rc, err = self.run_gate(f"timeout 60 /usr/bin/gh pr merge 96 --match-head-commit {SHA}")
            self.assertEqual(rc, 0, err)

    def test_an_expansion_in_an_approved_merge_blocks(self):
        with self.lookup({SHA: receipt("PASS")}):
            for cmd in (f"gh pr merge 96 --match-head-commit {SHA} {{--match-head-commit={OTHER},}}",
                        f"gh pr merge 96 --match-head-commit {SHA} -t {{x,--match-head-commit={OTHER}}}",
                        f"X=--match-head-commit={OTHER}; gh pr merge 96 --match-head-commit {SHA} $X",
                        f'gh pr merge 96 --match-head-commit {SHA} -t "$X"',
                        f"gh pr merge 96 --match-head-commit {SHA} *"):
                rc, err = self.run_gate(cmd)
                self.assertEqual(rc, 2, cmd)
            # Quoted text that bash does not expand stays allowed.
            rc, err = self.run_gate(f"gh pr merge 96 -t '{{a,b}} $y *' --match-head-commit {SHA}")
            self.assertEqual(rc, 0, err)

    def test_a_redirect_never_shifts_the_pin(self):
        with self.lookup({SHA: receipt("PASS")}):
            for cmd in (f"gh pr merge 96 --match-head-commit={OTHER} -t >/dev/null --match-head-commit={SHA}",
                        f"gh pr merge 96 --match-head-commit={OTHER} -t > /dev/null --match-head-commit={SHA}",
                        f"gh pr merge 96 --match-head-commit={OTHER} --subject 2>/dev/null --match-head-commit={SHA}"):
                rc, _ = self.run_gate(cmd)
                self.assertEqual(rc, 2, cmd)
            for cmd in (f"gh pr merge 96 --squash --match-head-commit {SHA} 2>&1 | tail -3",
                        f"gh pr merge 96 --match-head-commit {SHA} >/tmp/log 2>&1",
                        f"gh pr merge 96 -t '>' --match-head-commit {SHA}",
                        f"cd . && (gh pr merge 96 --squash --match-head-commit {SHA})",
                        f"gh api -X PUT repos/{{owner}}/{{repo}}/pulls/96/merge -f sha={SHA}"):
                rc, err = self.run_gate(cmd)
                self.assertEqual(rc, 0, f"{cmd}\n{err}")

    def test_an_unidentified_merge_mention_blocks_while_approved(self):
        with self.lookup({SHA: receipt("PASS")}):
            for cmd in ("env -u GH_TOKEN gh pr merge 96", "env -C . gh pr merge 96",
                        "stdbuf -oL gh pr merge 96", "setsid gh pr merge 96",
                        "builtin command gh pr merge 96",
                        "gh pr list -q .[].number | xargs -n1 gh pr merge --squash"):
                rc, err = self.run_gate(cmd)
                self.assertEqual(rc, 2, cmd)
        # Without an approval nothing merges through this gate, so text that only
        # mentions a merge is left alone.
        os.environ.pop("OCTO_MERGE_APPROVE", None)
        rc, _ = self.run_gate('echo "next: gh pr merge 96 --match-head-commit <sha>"')
        self.assertEqual(rc, 0)

    def test_never_weaker_than_the_previous_reading(self):
        # Each runs `gh pr merge 5` in bash and was blocked before this change.
        os.environ.pop("OCTO_MERGE_APPROVE", None)
        for cmd in ('echo "$\'" ; gh pr merge 5 ; echo "\'"',
                    "echo a\u00a0#; gh pr merge 5", "echo a\v#; gh pr merge 5",
                    "echo a\x1c#; gh pr merge 5", "echo a\u2028#; gh pr merge 5",
                    "bash <<'EOF'\ngh pr \\\n  merge 5 --squash\nEOF",
                    "bash <<'EOF'\necho \"a\nb\"; gh pr merge 5\nEOF",
                    "cat <<$'E'\nx\nE\necho \"a\nb\"; gh pr merge 5",
                    "echo ${x/<</y}\necho \"a\nb\"; gh pr merge 5"):
            rc, _ = self.run_gate(cmd)
            self.assertEqual(rc, 2, repr(cmd))
        # The same shapes are an unidentified or unparsed merge on the approved path.
        os.environ["OCTO_MERGE_APPROVE"] = "5"
        with self.lookup({SHA: receipt("PASS")}):
            for cmd in ("echo a\u00a0#; gh pr merge 5", "echo a\v#; gh pr merge 5"):
                rc, _ = self.run_gate(cmd)
                self.assertEqual(rc, 2, repr(cmd))

    def test_a_second_pin_candidate_is_never_trusted(self):
        with self.lookup({SHA: receipt("PASS")}):
            for cmd in (f"gh pr merge 96 --match-head-commit={SHA} -s=t --match-head-commit={OTHER}",
                        f"gh pr merge 96 --match-head-commit={SHA} -d=t --match-head-commit={OTHER}",
                        f"gh api -X PUT repos/o/r/pulls/96/merge -f sha={SHA} -i=t -f sha={OTHER}",
                        f"gh pr merge 96 --match-head-commit={OTHER} -t {{x}}>/dev/null --match-head-commit={SHA}",
                        f"gh pr merge 96 -t 'see --match-head-commit' --match-head-commit {SHA}",
                        f"gh api -X PUT repos/o/r/pulls/96/merge -f sha={SHA} -f 'sha[]=x'"):
                rc, err = self.run_gate(cmd)
                self.assertEqual(rc, 2, cmd)
                self.assertIn("pins no commit", err, cmd)
            rc, err = self.run_gate(f"gh pr merge 96 -s=t --match-head-commit={SHA}")
            self.assertEqual(rc, 0, err)

    def test_moved_root_flags_parse_before_the_pull_request(self):
        # cobra pairs `-d -t` at the root; pflag then gives `-t` the first word
        # after `merge`, so gh merges 351, never the approved 350.
        with self.lookup({SHA: receipt("PASS")}):
            for cmd in (f"gh -d -t pr merge 96 97 --squash --match-head-commit {SHA}",
                        f"gh -s -b pr merge 96 97 --match-head-commit {SHA}"):
                rc, _ = self.run_gate(cmd)
                self.assertEqual(rc, 2, cmd)

    def test_merge_flags_at_gh_root_are_read(self):
        with self.lookup({SHA: receipt("PASS")}):
            for cmd in ("gh --subject=x pr merge 96", "gh --delete-branch=true pr merge 96",
                        "gh -dRCarlosCaPe/octorato pr merge 96"):
                rc, err = self.run_gate(cmd)
                self.assertEqual(rc, 2, cmd)
                self.assertIn("pins no commit", err, cmd)
            for cmd in (f"gh -dRCarlosCaPe/octorato pr merge 96 --match-head-commit {SHA}",
                        f"gh --squash=true pr merge 96 --match-head-commit {SHA}"):
                rc, err = self.run_gate(cmd)
                self.assertEqual(rc, 0, f"{cmd}\n{err}")
        os.environ.pop("OCTO_MERGE_APPROVE", None)
        rc, _ = self.run_gate("gh --subject=x pr merge 97")
        self.assertEqual(rc, 2)

    def test_assignments_bash_reads_do_not_hide_a_merge(self):
        os.environ.pop("OCTO_MERGE_APPROVE", None)
        for cmd in ("env -S 'gh pr merge 96'", "env --split-string='gh pr merge 96'",
                    "env -iu GH_REPO gh pr merge 96",
                    "X+=1 gh pr merge 96 --squash", "env 'X'=1 gh pr merge 96",
                    'env GH_RE""PO=acme/brain gh pr merge 96', "GH_REPO+=acme/brain gh pr merge 96",
                    "env -u FOO GH_REPO=acme/brain gh pr merge 96"):
            self.assertTrue(gate._find_publish_subcmds(cmd), cmd)
            rc, _ = self.run_gate(cmd)
            self.assertEqual(rc, 2, cmd)

    def test_the_pull_request_is_the_first_positional(self):
        with self.lookup({SHA: receipt("PASS")}):
            for cmd in (f"gh pr merge --squash 96 --match-head-commit {SHA}",
                        f"gh pr merge --squash --delete-branch 96 --match-head-commit {SHA}",
                        f"gh pr merge -t done 96 --match-head-commit {SHA}",
                        f"gh pr merge https://github.com/o/r/pull/96 --match-head-commit {SHA}"):
                rc, err = self.run_gate(cmd)
                self.assertEqual(rc, 0, f"{cmd}\n{err}")
            rc, _ = self.run_gate(f"gh pr merge -t 96 97 --match-head-commit {SHA}")
            self.assertEqual(rc, 2)  # 96 is the subject; the merge is 97, not approved

    def test_flags_between_pr_and_merge_and_a_carriage_return(self):
        with self.lookup({SHA: receipt("PASS")}):
            for cmd in ("gh pr -t x merge 96 --squash", "gh pr --subject x merge 96",
                        f"gh pr --match-head-commit={OTHER} merge 96 --squash",
                        f"gh pr merge 96 -t x\r--match-head-commit={SHA}"):
                rc, _ = self.run_gate(cmd)
                self.assertEqual(rc, 2, repr(cmd))
            for cmd in (f"gh pr -t x merge 96 --match-head-commit {SHA}",
                        f"gh pr --match-head-commit={SHA} merge 96 --squash"):
                rc, err = self.run_gate(cmd)
                self.assertEqual(rc, 0, f"{cmd!r}\n{err}")

    def test_an_approval_never_gates_a_branch_push_outside_the_protected_set(self):
        self.protected.stop()
        try:
            with mock.patch.object(gate, "_is_protected_target", lambda *a, **k: False):
                for cmd in ("git push origin main", "git push origin HEAD:master"):
                    rc, _ = self.run_gate(cmd)
                    self.assertEqual(rc, 0, cmd)
        finally:
            self.protected.start()

    def test_the_approval_is_normalised_like_the_pr(self):
        os.environ["OCTO_MERGE_APPROVE"] = "096"
        with self.lookup({SHA: receipt("PASS")}):
            for cmd in (f"gh pr merge 96 --match-head-commit {SHA}",
                        f"gh pr merge '+96' --match-head-commit {SHA}",
                        f"gh pr merge '#+96' --match-head-commit {SHA}"):
                rc, err = self.run_gate(cmd)
                self.assertEqual(rc, 0, f"{cmd}\n{err}")

    def test_the_approved_number_is_never_ruled_out_of_scope(self):
        self.protected.stop()
        try:
            with mock.patch.object(gate, "_is_protected_target", lambda *a, **k: False), \
                    self.lookup({SHA: receipt("PASS")}):
                for cmd in ("GH_REPO=CarlosCaPe/octorato gh pr merge 96 --squash",
                            "gh pr merge https://github.com/CarlosCaPe/octorato/pull/96",
                            "gh pr merge https://github.com/CarlosCaPe/octorato/pull/96/files --squash",
                            "gh pr merge 'https://github.com/CarlosCaPe/octorato/pull/96#issuecomment-1'",
                            "gh pr merge '#96' --squash", "gh pr merge 096 --squash",
                            ):
                    rc, err = self.run_gate(cmd)
                    self.assertEqual(rc, 2, cmd)
                    self.assertIn("pins no commit", err)
                rc, err = self.run_gate("gh pr merge some-branch --squash")
                self.assertEqual(rc, 2)
                self.assertIn("write the number", err)
                rc, _ = self.run_gate("gh pr merge 97 --squash")   # another number: scope applies
                self.assertEqual(rc, 0)
            with self.lookup({SHA: receipt("PASS")}):
                for cmd in (f"gh pr merge '#96' --match-head-commit {SHA}",
                            f"gh pr merge 096 --match-head-commit {SHA}",
                            f"gh pr merge https://github.com/o/r/pull/96/files --match-head-commit {SHA}"):
                    rc, err = self.run_gate(cmd)
                    self.assertEqual(rc, 0, f"{cmd}\n{err}")
        finally:
            self.protected.start()

    def test_an_approved_api_merge_names_its_pr_in_its_own_endpoint(self):
        with self.lookup({SHA: receipt("PASS")}):
            for cmd in (f"gh api -f x=/pulls/96/merge -X PUT repos/o/r/pulls/97/merge -f sha={SHA}",
                        "gh api graphql -f query='mutation($sha: String, $note: String){ mergePullRequest("
                        "input:{pullRequestId:\"PR_x\", commitBody:$sha}) { clientMutationId } }'"
                        f" -f sha={SHA} -f note=/pulls/96/merge"):
                rc, err = self.run_gate(cmd)
                self.assertEqual(rc, 2, cmd)
            rc, err = self.run_gate(f"gh api -X PUT repos/o/r/pulls/96/merge -f sha={SHA}")
            self.assertEqual(rc, 0, err)

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


class RepoScopeEveryReading(unittest.TestCase):
    """The target repo is judged under both readings; one protected gates."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gate-cwd-"))
        self.brain = self.tmp / "brain"
        self.other = self.tmp / "other"
        for d in (self.brain, self.other):
            (d / ".git").mkdir(parents=True)
            (d / ".git" / "config").write_text("[core]\n")
        self.roots = mock.patch.object(gate, "_protected_roots", lambda: [self.brain.resolve()])
        self.roots.start()

    def tearDown(self):
        self.roots.stop()

    def protected(self, cmd):
        sub = [s for s in gate._split_subcmds(cmd) if "push" in s][-1]
        return gate._is_protected_target(cmd, sub, str(self.brain))

    def test_a_cd_bash_never_runs_cannot_move_the_target(self):
        cmd = f"cat <<'EOF'\n'\ncd {self.other}\n'\nEOF\ngit push origin main"
        self.assertTrue(self.protected(cmd))

    def test_every_repo_flag_value_is_a_candidate(self):
        (self.brain / ".git" / "config").write_text(
            '[remote "origin"]\n\turl = https://github.com/acme/brain.git\n')
        cwd = str(self.other)
        judge = lambda cmd: gate._is_protected_target(cmd, cmd, cwd)
        # A -R inside a quoted body or subject must not outvote the real flag.
        for cmd in ('gh pr merge 96 -R acme/brain --body "note -R other/repo"',
                    'gh pr merge 96 -R acme/brain -t "x -R other/repo"',
                    'gh pr merge 96 --repo acme/brain --subject "see --repo other/x"',
                    "gh -R other/repo pr merge 96 -R acme/brain",
                    "gh pr merge 96 -R acme/brain",
                    "gh pr merge 97 -Racme/brain --squash", "gh -Racme/brain pr merge 97",
                    "gh pr -Racme/brain merge 97", "gh pr merge 97 -sRacme/brain",
                    "gh pr merge 97 -dR acme/brain", "gh pr merge 97 -R=acme/brain",
                    "gh pr merge 97 --repo=acme/brain"):
            self.assertIsNot(judge(cmd), False, cmd)
        self.assertFalse(judge("gh pr merge 96 -R other/repo"))
        # A word another flag consumes is that flag's value, never a repo: the
        # directory decides, and here it is the protected one.
        for cmd in ('gh pr merge 350 --body "-R other/repo"', 'gh pr merge 350 --body "-Rother/repo"',
                    "gh pr merge 350 --subject -Rother/repo", "gh pr merge 350 -t -Rother/repo",
                    "gh pr merge 350 --match-head-commit -Rother/repo",
                    "gh pr merge 350 -b '-dR other/repo'", "gh pr merge 350 --author-email -Rother/repo",
                    "gh pr merge 350 -F -Rother/repo", "gh pr merge 350 --body-file -Rother/repo"):
            self.assertTrue(gate._is_protected_target(cmd, cmd, str(self.brain)), cmd)
        # Spellings the previous judge reads move the target out of the brain;
        # the attached and clustered ones it does not read stay gated in the
        # brain (the previous judge is the floor), and still gate a protected
        # slug from anywhere (see above).
        for cmd in ("gh pr merge 97 -R other/repo", "gh pr merge 97 -R=other/repo",
                    "gh pr merge 97 --repo=other/repo", "gh pr merge 97 --repo other/repo"):
            self.assertFalse(gate._is_protected_target(cmd, cmd, str(self.brain)), cmd)
        for cmd in ("gh pr merge 97 -Rother/repo", "gh pr merge 97 -dRother/repo",
                    "gh -Rother/repo pr merge 97", "gh pr -Rother/repo merge 97"):
            self.assertIsNot(gate._is_protected_target(cmd, cmd, str(self.brain)), False, cmd)
        # A repo named only inside a quoted value is not a flag: the cwd decides.
        brain_cwd = str(self.brain)
        self.assertTrue(gate._is_protected_target(
            "gh pr merge 351 --body ' -R other/repo' --squash",
            "gh pr merge 351 --body ' -R other/repo' --squash", brain_cwd))

    def test_a_root_flag_before_api_keeps_the_rest_path_as_target(self):
        (self.brain / ".git" / "config").write_text(
            '[remote "origin"]\n\turl = https://github.com/acme/brain.git\n')
        for cmd in ("gh -X PUT api repos/acme/brain/pulls/97/merge",
                    "gh --method=PUT api repos/acme/brain/pulls/97/merge",
                    "gh --hostname github.com api -X PUT repos/acme/brain/pulls/97/merge"):
            self.assertTrue(gate._is_protected_target(cmd, cmd, str(self.other)), cmd)
        # From the brain the previous judge reads the directory: still gated.
        self.assertIsNot(gate._is_protected_target(
            "gh -X PUT api repos/acme/other/pulls/97/merge",
            "gh -X PUT api repos/acme/other/pulls/97/merge", str(self.brain)), False)

    def test_scope_is_never_looser_than_the_previous_judge(self):
        (self.brain / ".git" / "config").write_text(
            '[remote "origin"]\n\turl = https://github.com/acme/brain.git\n')
        for cmd in ("gh pr merge 350 --squash $'-t' -Rother/repo",
                    'gh pr merge 351 --squash $"-t" -Rother/repo',
                    "T=-t; gh pr merge 351 --squash $T -Rother/repo",
                    "gh pr merge 351 --squash {-t,} -Rother/repo",
                    "gh pr merge 350 --squash $(echo -t) -Rother/repo"):
            sub = [s for s in gate._split_subcmds(cmd) if "merge" in s][0]
            self.assertIsNot(gate._is_protected_target(cmd, sub, str(self.brain)), False, cmd)

    def test_any_pointer_at_a_protected_repo_gates_from_anywhere(self):
        # Issue #351: from a non-protected directory, with no approval.
        (self.brain / ".git" / "config").write_text(
            '[remote "origin"]\n\turl = https://github.com/acme/brain.git\n')
        cwd = str(self.other)
        for cmd in ("GH_REPO=acme/brain gh pr merge 96 --squash",
                    "export GH_REPO=acme/brain; gh pr merge 96",
                    "gh pr merge https://github.com/acme/brain/pull/96 --squash",
                    "gh api -X PUT -f commit_title=repos/a/b/merges repos/acme/brain/pulls/96/merge",
                    "gh pr merge 96 --squash -t 'x -R other/repo' -R acme/brain"):
            sub = [s for s in gate._split_subcmds(cmd) if "merge" in s][-1]
            self.assertIsNot(gate._is_protected_target(cmd, sub, cwd), False, cmd)
        for cmd in ("gh pr merge Https://GitHub.com/acme/brain/pull/96 --squash",
                    "gh pr merge HTTPS://github.com/acme/brain/pull/96",
                    'GH_REPO=acme/"brain" gh pr merge 96 --squash',
                    'GH_REPO=ac""me/brain gh pr merge 96', "GH_REPO=acme/br\\ain gh pr merge 96",
                    "GH_REPO=$R gh pr merge 96"):
            sub = [s for s in gate._split_subcmds(cmd) if "merge" in s][-1]
            self.assertIsNot(gate._is_protected_target(cmd, sub, cwd), False, cmd)
        for cmd in ("gh pr merge https://github.com/acme/br%61in/pull/96 --squash",
                    "gh pr merge https://github.com/acme%2Fbrain/pull/96",
                    "GH_REPO+=acme/brain gh pr merge 96", 'env GH_RE""PO=acme/brain gh pr merge 96',
                    "env 'GH_REPO'=acme/brain gh pr merge 96",
                    "printf -v GH_REPO %s acme/brain; export GH_REPO; gh pr merge 96"):
            sub = [s for s in gate._split_subcmds(cmd) if "merge" in s][-1]
            self.assertIsNot(gate._is_protected_target(cmd, sub, cwd), False, cmd)
        # Repo pointers through GIT_DIR, a same-command remote rewrite, insteadOf.
        for cmd in (f"GIT_DIR={self.brain}/.git gh pr merge 96",
                    "git remote set-url origin https://github.com/acme/brain && gh pr merge 96"):
            sub = [s for s in gate._split_subcmds(cmd) if "merge" in s][-1]
            self.assertIsNot(gate._is_protected_target(cmd, sub, cwd), False, cmd)
        iof = self.tmp / "iof"
        (iof / ".git").mkdir(parents=True)
        (iof / ".git" / "config").write_text('[url "https://github.com/acme/"]\n\tinsteadOf = zz:\n[remote "origin"]\n\turl = zz:brain\n')
        self.assertIsNot(gate._is_protected_target("gh pr merge 96", "gh pr merge 96", str(iof)), False)
        for cmd in ("GIT_CONFIG_GLOBAL=../g gh pr merge 96",
                    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=url.x.insteadOf GIT_CONFIG_VALUE_0=y gh pr merge 96",
                    "export GIT_CONFIG_PARAMETERS=x; gh pr merge 96"):
            sub = [s for s in gate._split_subcmds(cmd) if "merge" in s][-1]
            self.assertIsNot(gate._is_protected_target(cmd, sub, cwd), False, cmd)
        inc = self.tmp / "inc"
        (inc / ".git").mkdir(parents=True)
        (inc / ".git" / "config").write_text('[include]\n\tpath = ../../g\n[remote "origin"]\n\turl = https://github.com/acme/other.git\n')
        self.assertIsNot(gate._is_protected_target("gh pr merge 96", "gh pr merge 96", str(inc)), False)
        # An optioned env, or a variable that moves git's config, is unreadable.
        for cmd in ("env -S 'gh pr merge -R CarlosCaPe/octorato 9'",
                    "env -S 'gh pr merge 9' -R CarlosCaPe/octorato",
                    "env -C /x gh pr merge 9", "env --chdir=/x gh pr merge 9",
                    "env -iC /x gh pr merge 9", "env --uns FOO gh pr merge 9",
                    "HOME=/x gh pr merge 9", "export HOME=/x; gh pr merge 9",
                    "XDG_CONFIG_HOME=/x gh pr merge 9", "GIT_COMMON_DIR=/x gh pr merge 9"):
            sub = [s for s in gate._split_subcmds(cmd) if "merge" in s][-1]
            self.assertIsNot(gate._is_protected_target(cmd, sub, cwd), False, cmd)
        for cmd in ("env X=1 gh pr merge 9", "cd $HOME/x && gh pr merge 9"):
            sub = [s for s in gate._split_subcmds(cmd) if "merge" in s][-1]
            self.assertFalse(gate._env_with_option(sub), cmd)
        # A linked worktree whose common config, or a config.worktree, rewrites urls.
        for name in ("config", "config.worktree"):
            wt = self.tmp / ("wt-" + name)
            common = self.tmp / ("common-" + name)
            (common / "worktrees" / "w").mkdir(parents=True)
            (common / "config").write_text('[remote "origin"]\n\turl = https://github.com/acme/other.git\n')
            (common / name).write_text('[url "https://github.com/CarlosCaPe/octorato.git"]\n\tinsteadOf = x\n',
                                       ) if name == "config.worktree" else (common / "config").write_text(
                '[remote "origin"]\n\turl = https://github.com/acme/other.git\n'
                '[url "https://github.com/CarlosCaPe/octorato.git"]\n\tinsteadOf = x\n')
            (common / "worktrees" / "w" / "commondir").write_text("../..\n")
            wt.mkdir()
            (wt / ".git").write_text(f"gitdir: {common}/worktrees/w\n")
            self.assertIsNot(gate._is_protected_target("gh pr merge 9", "gh pr merge 9", str(wt)), False, name)
        # git push ignores GH_REPO: a pointer must not gate it.
        self.assertFalse(gate._is_protected_target(
            "GH_REPO=acme/brain git push origin main", "GH_REPO=acme/brain git push origin main", cwd))
        # A linked worktree of a protected clone, and an ssh remote with a port.
        clone = self.tmp / "clone"
        (clone / ".git" / "worktrees" / "wt").mkdir(parents=True)
        (clone / ".git" / "config").write_text('[remote "origin"]\n\turl = ssh://git@github.com:22/acme/brain.git\n')
        (clone / ".git" / "worktrees" / "wt" / "commondir").write_text("../..\n")
        linked = self.tmp / "linked"
        linked.mkdir()
        (linked / ".git").write_text(f"gitdir: {clone / '.git' / 'worktrees' / 'wt'}\n")
        self.assertTrue(gate._is_protected_target("gh pr merge 96", "gh pr merge 96", str(clone)))
        self.assertTrue(gate._is_protected_target("gh pr merge 96", "gh pr merge 96", str(linked)))
        # A fork clone whose `upstream` is protected is protected.
        fork = self.tmp / "fork"
        (fork / ".git").mkdir(parents=True)
        (fork / ".git" / "config").write_text(
            '[remote "origin"]\n\turl = https://github.com/someone/brain.git\n'
            '[remote "upstream"]\n\turl = https://github.com/acme/brain.git\n')
        self.assertTrue(gate._is_protected_target("gh pr merge 96", "gh pr merge 96", str(fork)))
        # Pointers at an unprotected repo from an unprotected directory stay ungated.
        for cmd in ("GH_REPO=acme/other gh pr merge 96 --squash",
                    "GH_REPO='acme/other' gh pr merge 96",
                    "gh pr merge https://github.com/acme/other/pull/96"):
            self.assertFalse(gate._is_protected_target(cmd, cmd, cwd), cmd)

    def test_a_cd_both_readings_agree_on_still_moves_it(self):
        self.assertFalse(self.protected(f"cd {self.other} && git push origin main"))
        self.assertTrue(self.protected("git push origin main"))


class SeekNeedsBothReadings(unittest.TestCase):
    def test_the_rule_holds_inside_sh_c(self):
        inner = "cat >/dev/null <<'EOF'\n'\npython3 ~/.claude/scripts/query_connectome.py memory x\n'\nEOF"
        self.assertFalse(receipt_ledger.bash_is_seek('bash -c "' + inner + '"'))

    def test_a_seek_only_one_reading_finds_is_no_receipt(self):
        # Inside a comment bash never runs it; the previous reader, which knows no
        # comments, would have counted it. A receipt must hold under both readings.
        one = "echo x # ; python3 ~/.claude/scripts/query_connectome.py memory x"
        self.assertFalse(receipt_ledger.bash_is_seek(one))
        self.assertTrue(receipt_ledger.bash_is_seek(
            "python3 ~/.claude/scripts/query_connectome.py memory x"))


_os_spec = importlib.util.spec_from_file_location("outward_send", SCRIPTS / "g__pretool-mcp__outward-send.py")
outward = importlib.util.module_from_spec(_os_spec)
_os_spec.loader.exec_module(outward)


class WaiverNeedsEveryRecipient(unittest.TestCase):
    def setUp(self):
        self.cfg = mock.patch.object(outward, "_autonomous_cfg", lambda: [{"jid": "111@g.us"}])
        self.cfg.start()

    def tearDown(self):
        self.cfg.stop()

    def waived(self, command):
        return outward.autonomous_chat("Bash", {"command": command})

    def test_a_listed_chat_is_waived(self):
        self.assertTrue(self.waived("bash ~/.claude/scripts/wa-soporte.sh 111@g.us hola"))

    def test_any_unlisted_recipient_under_any_reading_voids_the_waiver(self):
        S = "~/.claude/scripts/wa-soporte.sh"
        # Body lines read alone name the listed chat first; the previous reading,
        # like bash, resyncs on the quote and runs the send to the other chat.
        cmd = f"cat <<'EOF'\n'\n{S} 111@g.us x\n'\nEOF\n{S} 222@s.whatsapp.net hola"
        self.assertFalse(self.waived(cmd))
        self.assertFalse(self.waived(f"{S} 111@g.us a; {S} 222@s.whatsapp.net b"))


if __name__ == "__main__":
    unittest.main()
