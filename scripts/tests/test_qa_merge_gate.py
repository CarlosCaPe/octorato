#!/usr/bin/env python3
"""Unit tests for the QA merge gate's parsing and for the selftest env allowlist.

The fixtures prove the gate blocks and allows end to end; these tests pin the two
parsing rules a fixture cannot show directly (every sub-command is collected, and
a flag before the PR number does not hide it) plus the harness rule that a fixture
cannot escape its sandbox through "_env".
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
GH_MERGE = "gh" + " pr " + "merge"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


gate = _load("qa_merge_gate_under_test", "qa-merge-gate.py")
gate_selftest = _load("gate_selftest_under_test", "gate_selftest.py")


class TestSubcommandCollection(unittest.TestCase):
    def test_every_merge_in_a_chain_is_collected(self):
        for sep in ("&&", ";", "||"):
            with self.subTest(sep=sep):
                cmd = f"{GH_MERGE} 280 --squash {sep} {GH_MERGE} 281 --squash"
                found = gate._find_publish_subcmds(cmd)
                self.assertEqual(2, len(found))
                ids = [gate._extract_pr_id(sub) for sub, _form in found]
                self.assertEqual(["280", "281"], ids)

    def test_quoted_mention_is_still_not_a_match(self):
        self.assertEqual([], gate._find_publish_subcmds(f'git commit -m "{GH_MERGE} 96"'))

    def test_form_label_marks_the_api_shape(self):
        found = gate._find_publish_subcmds(
            "gh api --method PUT /repos/o/r/pulls/280/merge")
        self.assertEqual([("api")], [f for _s, f in found])


class TestPrNumberExtraction(unittest.TestCase):
    def test_flag_before_the_number(self):
        for cmd in (f"{GH_MERGE} -R owner/repo 280",
                    f"{GH_MERGE} --repo owner/repo 280 --squash",
                    f"{GH_MERGE} 280 -R owner/repo"):
            with self.subTest(cmd=cmd):
                self.assertEqual("280", gate._extract_pr_id(cmd))

    def test_flag_value_is_not_read_as_the_pr(self):
        for flag in ("-t", "--subject", "-b", "--body", "-A", "--author-email",
                     "-F", "--body-file", "--match-head-commit", "-R", "--repo"):
            with self.subTest(flag=flag):
                self.assertEqual("281", gate._extract_pr_id(f"{GH_MERGE} {flag} 280 281"))
        self.assertEqual("281", gate._extract_pr_id(f"{GH_MERGE} -R X -t 280 281"))
        self.assertEqual("281", gate._extract_pr_id(f"{GH_MERGE} -dt 280 281"))

    def test_equals_form_and_double_dash(self):
        self.assertEqual("281", gate._extract_pr_id(f"{GH_MERGE} --subject=280 281"))
        self.assertEqual("281", gate._extract_pr_id(f"{GH_MERGE} -- 281"))

    def test_boolean_flags_do_not_eat_the_number(self):
        for flag in ("--admin", "--auto", "-d", "-s", "-m", "-r", "--delete-branch"):
            with self.subTest(flag=flag):
                self.assertEqual("280", gate._extract_pr_id(f"{GH_MERGE} {flag} 280"))

    def test_branch_argument_has_no_number(self):
        self.assertEqual("unknown", gate._extract_pr_id(f"{GH_MERGE} feat/x"))


class TestSelftestEnvAllowlist(unittest.TestCase):
    def _prep(self, payload: dict):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "leg.json"
            f.write_text(json.dumps(payload), encoding="utf-8")
            return gate_selftest._prep_payload(f, Path(d), Path(d))

    def test_octo_keys_pass(self):
        _p, env = self._prep({"_env": {"OCTO_MERGE_APPROVE": "280", "OCTO_QA_OK": "1"}})
        self.assertEqual({"OCTO_MERGE_APPROVE": "280", "OCTO_QA_OK": "1"}, env)

    def test_home_and_path_are_ignored(self):
        _p, env = self._prep({"_env": {"HOME": "/etc", "USERPROFILE": "/etc",
                                       "PATH": "/evil", "CLAUDE_SESSION_ID": "x",
                                       "LD_PRELOAD": "/evil.so"}})
        self.assertEqual({}, env)

    def test_env_key_is_not_visible_to_the_gate(self):
        payload, _env = self._prep({"tool_name": "Bash", "_env": {"OCTO_QA_OK": "1"}})
        self.assertNotIn("_env", json.loads(payload))

    def test_sandbox_home_survives_a_fixture_that_tries_to_set_it(self):
        # end to end: the leg must run with the sandbox HOME, not the fixture's
        with tempfile.TemporaryDirectory() as d:
            probe = Path(d) / "probe.py"
            probe.write_text("import os,sys;sys.stdin.read();print(os.environ['HOME'])",
                             encoding="utf-8")
            sandbox = Path(d) / "sandbox"
            sandbox.mkdir()
            rc, out = gate_selftest._run_leg(probe, "{}", sandbox, {"HOME": "/etc"})
            self.assertEqual(0, rc)
            self.assertEqual(str(sandbox), out.strip())


class TestGateEndToEnd(unittest.TestCase):
    def _run(self, command: str, env: dict) -> int:
        full = dict(os.environ)
        for k in ("OCTO_MERGE_APPROVE", "OCTO_QA_OK"):
            full.pop(k, None)
        # sandbox HOME like gate_selftest._run_leg: the gate resolves the brain's
        # protected-repo scope from HOME, so the real one makes the result depend
        # on whose machine runs the suite.
        sandbox = tempfile.mkdtemp(prefix="qa-gate-test-")
        self.addCleanup(shutil.rmtree, sandbox, True)
        full["HOME"] = sandbox
        full["USERPROFILE"] = sandbox
        full.update(env)
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command},
                              "cwd": "/nonexistent/repo"})
        cp = subprocess.run([sys.executable, str(SCRIPTS / "qa-merge-gate.py")],
                            input=payload, capture_output=True, text=True, env=full,
                            timeout=30)
        return cp.returncode

    def test_chained_second_pr_is_denied(self):
        self.assertEqual(2, self._run(f"{GH_MERGE} 280 && {GH_MERGE} 281",
                                      {"OCTO_MERGE_APPROVE": "280", "OCTO_QA_OK": "1"}))

    def test_sentinel_is_never_approvable(self):
        self.assertEqual(2, self._run(f"{GH_MERGE} feat/x",
                                      {"OCTO_MERGE_APPROVE": "unknown", "OCTO_QA_OK": "1"}))

    def test_api_branch_sentinel_is_never_approvable(self):
        self.assertEqual(2, self._run(
            "gh api --method PATCH /repos/o/r/git/refs/heads/main -f sha=abc",
            {"OCTO_MERGE_APPROVE": "main", "OCTO_QA_OK": "1"}))

    def test_approved_pr_with_flag_before_number_is_allowed(self):
        self.assertEqual(0, self._run(f"{GH_MERGE} -R owner/repo 280",
                                      {"OCTO_MERGE_APPROVE": "280", "OCTO_QA_OK": "1"}))

    def test_flag_value_number_does_not_authorize_the_real_target(self):
        self.assertEqual(2, self._run(f"{GH_MERGE} -t 280 281",
                                      {"OCTO_MERGE_APPROVE": "280", "OCTO_QA_OK": "1"}))

    def test_qa_ok_alone_never_authorizes(self):
        self.assertEqual(2, self._run(f"{GH_MERGE} 280", {"OCTO_QA_OK": "1"}))


if __name__ == "__main__":
    unittest.main()
