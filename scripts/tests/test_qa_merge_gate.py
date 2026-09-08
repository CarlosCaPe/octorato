#!/usr/bin/env python3
"""Unit tests for the QA merge gate's parsing and for the selftest env allowlist.

The fixtures prove the gate blocks and allows end to end; these tests pin the two
parsing rules a fixture cannot show directly (every sub-command is collected, and
a flag before the PR number does not hide it) plus the harness rule that a fixture
cannot escape its sandbox through "_env".
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
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

    def test_unclosed_quote_yields_the_sentinel_not_a_number(self):
        # Pins commit 5948a9f's claim ("unclosed quotes deny"): the shlex failure
        # path must fall through to the sentinel. Falling back to a whitespace
        # split would read `"280` as 280 and hand an approvable number to a
        # command whose real argument list nobody can know.
        for cmd in (f'{GH_MERGE} "280', f"{GH_MERGE} -t 'x 280", f'{GH_MERGE} 281 "'):
            with self.subTest(cmd=cmd):
                self.assertEqual("unknown", gate._extract_pr_id(cmd))


class TestWrapperPeel(unittest.TestCase):
    """B1: the ^gh / ^git anchor must survive every leading wrapper.

    Each of these was measured ALLOWED by the live gate on 2026-09-08 while
    invoking gh for real. The peel is deny-by-default (drop leading tokens until
    a command head appears), so this list is evidence, not the definition.
    """

    WRAPPED = (
        "time", "nohup", "nice", "timeout 30", "stdbuf -o0", "setsid", "sudo",
        "exec", "eval", "xargs", "nice -n 5", "sudo -u builder",
        "env A=1 command", "nohup nice -n 5 timeout 30",
    )

    def test_every_wrapper_still_identifies_the_merge(self):
        for w in self.WRAPPED:
            with self.subTest(wrapper=w):
                found = gate._find_publish_subcmds(f"{w} {GH_MERGE} 291")
                self.assertEqual([("gh")], [f for _s, f in found])
                self.assertEqual("291", gate._extract_pr_id(found[0][0]))

    def test_leading_backslash_and_absolute_path_are_the_same_verb(self):
        for cmd in (f"\\{GH_MERGE} 291", f"/usr/bin/{GH_MERGE} 291",
                    f"'gh' pr merge 291", f"time \\{GH_MERGE} 291"):
            with self.subTest(cmd=cmd):
                self.assertEqual("291", gate._extract_pr_id(cmd))
                self.assertTrue(gate._find_publish_subcmds(cmd))

    def test_wrapped_git_push_to_main_is_identified(self):
        for w in ("time", "sudo -u builder", "timeout 30"):
            with self.subTest(wrapper=w):
                found = gate._find_publish_subcmds(f"{w} git push origin main")
                self.assertEqual([("push")], [f for _s, f in found])

    def test_quoted_mention_survives_the_peel(self):
        # The peel must not buy wrapper coverage by unquoting: these are the
        # false positives command-boundary anchoring exists to prevent.
        for cmd in (f'git commit -m "{GH_MERGE} 96"',
                    f"git commit -m '{GH_MERGE} 96'",
                    f'echo "{GH_MERGE} 96" >> notes.txt'):
            with self.subTest(cmd=cmd):
                self.assertEqual([], gate._find_publish_subcmds(cmd))

    def test_documented_residual_stays_documented(self):
        # bash -c / eval "..." keep the merge inside a QUOTED token, which is
        # the same shape as the false positive above. Asserted so the docstring's
        # residual list and the code cannot drift apart silently.
        for cmd in (f'bash -c "{GH_MERGE} 96"', f"eval '{GH_MERGE} 96'"):
            with self.subTest(cmd=cmd):
                self.assertEqual([], gate._find_publish_subcmds(cmd))


class TestApiForms(unittest.TestCase):
    def test_auto_merge_graphql_mutation_is_a_merge(self):
        # B3: `gh pr merge --auto` was denied while the exact API call it makes
        # was allowed.
        for mutation in ("enablePullRequestAutoMerge", "mergePullRequest",
                         "mergeBranch"):
            with self.subTest(mutation=mutation):
                cmd = ("gh api graphql -f query='mutation{%s(input:{x:1})"
                       "{clientMutationId}}'" % mutation)
                self.assertEqual([("api")],
                                 [f for _s, f in gate._find_publish_subcmds(cmd)])
                self.assertEqual("unknown", gate._extract_pr_id(cmd))

    def test_graphql_read_is_not_a_merge(self):
        self.assertEqual(
            [], gate._find_publish_subcmds("gh api graphql -f query='query{viewer{login}}'"))


class TestGhAliases(unittest.TestCase):
    """B4: an alias expands inside gh, so the verb anchor never sees `pr merge`."""

    def _with_aliases(self, body: str):
        d = tempfile.mkdtemp(prefix="gh-cfg-")
        self.addCleanup(shutil.rmtree, d, True)
        (Path(d) / "config.yml").write_text(body, encoding="utf-8")
        patcher = unittest.mock.patch.dict(os.environ, {"GH_CONFIG_DIR": d})
        patcher.start()
        self.addCleanup(patcher.stop)
        gate._aliases_cache = None
        self.addCleanup(setattr, gate, "_aliases_cache", None)

    def test_alias_is_resolved_to_the_merge_it_runs(self):
        self._with_aliases("git_protocol: https\naliases:\n"
                           "    co: pr checkout\n    mrg: pr merge\n"
                           "    zap: '!gh pr merge \"$1\" --admin'\n")
        found = gate._find_publish_subcmds("gh mrg 291")
        self.assertEqual([("gh")], [f for _s, f in found])
        self.assertEqual("291", gate._extract_pr_id("gh mrg 291"))
        self.assertTrue(gate._find_publish_subcmds("gh zap 291"))

    def test_a_non_merge_alias_is_not_a_merge(self):
        self._with_aliases("aliases:\n    co: pr checkout\n")
        self.assertEqual([], gate._find_publish_subcmds("gh co 291"))

    def test_defining_a_merge_alias_is_gated(self):
        # Resolution alone loses the race: `gh alias set` writes the config file
        # AFTER this hook has already read it, in the same line.
        for cmd in ('gh alias set m "pr merge"',
                    "gh alias set m 'pr merge --admin'",
                    "gh alias import aliases.yml"):
            with self.subTest(cmd=cmd):
                self.assertEqual([("alias")],
                                 [f for _s, f in gate._find_publish_subcmds(cmd)])

    def test_defining_a_harmless_alias_is_not_gated(self):
        self.assertEqual([], gate._find_publish_subcmds('gh alias set co "pr checkout"'))


class TestRepoScope(unittest.TestCase):
    """B2: gh resolves the target as -R, else GH_REPO, else cwd — so must this."""

    def _sandbox(self):
        d = Path(tempfile.mkdtemp(prefix="qa-gate-scope-"))
        self.addCleanup(shutil.rmtree, d, True)
        for rel, url in ((".claude", "CarlosCaPe/octorato"),
                         ("other", "someone/unrelated")):
            (d / rel / ".git").mkdir(parents=True)
            (d / rel / ".git" / "config").write_text(
                '[remote "origin"]\n\turl = https://github.com/%s.git\n' % url,
                encoding="utf-8")
        return d

    def _protected(self, command: str, env: dict | None = None):
        home = self._sandbox()
        patcher = unittest.mock.patch.dict(
            os.environ, dict({"HOME": str(home), "USERPROFILE": str(home)},
                             **(env or {})))
        patcher.start()
        self.addCleanup(patcher.stop)
        gate._BRAIN = home / ".claude"
        gate._PROTECTED_CFG = gate._BRAIN / "company" / "config" / "protected-repos.json"
        self.addCleanup(setattr, gate, "_BRAIN", Path.home() / ".claude")
        sub = gate._find_publish_subcmds(command)[0][0]
        return gate._is_protected_target(command, sub, str(home / "other"))

    def test_plain_merge_from_an_unrelated_repo_is_not_protected(self):
        self.assertIs(False, self._protected(f"{GH_MERGE} 291"))

    def test_gh_repo_inline_prefix_names_the_real_target(self):
        self.assertIs(True, self._protected(
            f"GH_REPO=CarlosCaPe/octorato {GH_MERGE} 291"))

    def test_gh_repo_same_line_export_names_the_real_target(self):
        self.assertIs(True, self._protected(
            f"export GH_REPO=CarlosCaPe/octorato; {GH_MERGE} 291"))

    def test_gh_repo_from_the_process_env_names_the_real_target(self):
        self.assertIs(True, self._protected(
            f"{GH_MERGE} 291", {"GH_REPO": "CarlosCaPe/octorato"}))

    def test_unparseable_gh_repo_is_unresolvable_not_safe(self):
        self.assertIsNone(self._protected(f"GH_REPO=garbage {GH_MERGE} 291"))

    def test_another_gh_host_is_unresolvable_not_safe(self):
        self.assertIsNone(self._protected(
            f"GH_HOST=ghe.example.com {GH_MERGE} 291"))

    def test_gh_repo_to_a_non_protected_repo_still_ungates(self):
        self.assertIs(False, self._protected(
            f"GH_REPO=someone/unrelated {GH_MERGE} 291"))

    def test_an_alias_definition_has_no_repo_so_it_gates(self):
        self.assertIsNone(self._protected('gh alias set m "pr merge"'))


class TestCrashPolicy(unittest.TestCase):
    """M15: the branch that chooses fail-open vs fail-closed on a crash."""

    def setUp(self):
        self.addCleanup(setattr, gate, "_PUBLISH_IDENTIFIED", False)

    def test_a_crash_after_identification_denies(self):
        with unittest.mock.patch.object(gate, "main", side_effect=RuntimeError("boom")):
            gate._PUBLISH_IDENTIFIED = True
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                rc = gate._guarded_main()
        self.assertEqual(2, rc)
        self.assertIn("crashed AFTER", err.getvalue())

    def test_a_crash_before_identification_stays_open(self):
        with unittest.mock.patch.object(gate, "main", side_effect=RuntimeError("boom")):
            gate._PUBLISH_IDENTIFIED = False
            rc = gate._guarded_main()
        self.assertEqual(0, rc)

    def test_a_deliberate_block_is_not_swallowed(self):
        with unittest.mock.patch.object(gate, "main", return_value=2):
            self.assertEqual(2, gate._guarded_main())


class TestUnresolvableTargetGates(unittest.TestCase):
    """M16: `except Exception: protected = None`. A target the gate could not
    resolve is not a target it proved safe."""

    def _main_with(self, command: str, side_effect):
        payload = json.dumps({"tool_name": "Bash",
                              "tool_input": {"command": command},
                              "cwd": "/nonexistent/repo"})
        env = {k: v for k, v in os.environ.items()
               if k not in ("OCTO_MERGE_APPROVE", "OCTO_QA_OK")}
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch.object(gate, "_is_protected_target",
                                           side_effect=side_effect), \
                unittest.mock.patch("sys.stdin", io.StringIO(payload)):
            err, out = io.StringIO(), io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
                rc = gate.main()
        self.addCleanup(setattr, gate, "_PUBLISH_IDENTIFIED", False)
        return rc, err.getvalue()

    def test_a_resolver_that_raises_still_gates(self):
        rc, err = self._main_with("git push origin main", ValueError("cannot resolve"))
        self.assertEqual(2, rc)
        self.assertIn("needs operator approval", err)

    def test_a_resolver_that_returns_none_still_gates(self):
        rc, err = self._main_with("git push origin main", lambda *a: None)
        self.assertEqual(2, rc)
        self.assertIn("needs operator approval", err)

    def test_a_positively_unprotected_target_ungates(self):
        # the control: only a POSITIVE False ungates, so the two above are not
        # passing merely because everything denies.
        rc, _err = self._main_with("git push origin main", lambda *a: False)
        self.assertEqual(0, rc)


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
    """Every deny asserts its REASON, not just rc=2.

    rc 2 is also what the fail-closed crash handler returns, so replacing the
    whole post-identification body with `raise` left all five deny tests green:
    they were pinning "something refused", which the crash path satisfies. A
    gate that denies for the wrong reason is a gate nobody can debug, so the
    stderr line is the assertion and the exit code is the sanity check.
    """

    def _run(self, command: str, env: dict):
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
        return cp.returncode, cp.stderr

    def _deny(self, command: str, env: dict, *reasons: str):
        rc, err = self._run(command, env)
        self.assertEqual(2, rc, err)
        for reason in reasons:
            self.assertIn(reason, err)
        self.assertNotIn("crashed AFTER", err)

    def test_chained_second_pr_is_denied(self):
        self._deny(f"{GH_MERGE} 280 && {GH_MERGE} 281",
                   {"OCTO_MERGE_APPROVE": "280", "OCTO_QA_OK": "1"},
                   "waives the QA receipt only", "merges 280, 281",
                   "OCTO_MERGE_APPROVE=280")

    def test_sentinel_is_never_approvable(self):
        self._deny(f"{GH_MERGE} feat/x",
                   {"OCTO_MERGE_APPROVE": "unknown", "OCTO_QA_OK": "1"},
                   "merges 'unknown', which is a sentinel")

    def test_api_branch_sentinel_is_never_approvable(self):
        self._deny("gh api --method PATCH /repos/o/r/git/refs/heads/main -f sha=abc",
                   {"OCTO_MERGE_APPROVE": "main", "OCTO_QA_OK": "1"},
                   "merges 'main', which is a sentinel")

    def test_approved_pr_with_flag_before_number_is_allowed(self):
        rc, err = self._run(f"{GH_MERGE} -R owner/repo 280",
                            {"OCTO_MERGE_APPROVE": "280", "OCTO_QA_OK": "1"})
        self.assertEqual(0, rc, err)

    def test_flag_value_number_does_not_authorize_the_real_target(self):
        self._deny(f"{GH_MERGE} -t 280 281",
                   {"OCTO_MERGE_APPROVE": "280", "OCTO_QA_OK": "1"},
                   "waives the QA receipt only", "merges 281")

    def test_qa_ok_alone_never_authorizes(self):
        self._deny(f"{GH_MERGE} 280", {"OCTO_QA_OK": "1"},
                   "waives the QA receipt only", "OCTO_MERGE_APPROVE unset")

    def test_no_approval_denies_for_the_approval_reason(self):
        self._deny(f"{GH_MERGE} 280", {},
                   "needs operator approval", "export OCTO_MERGE_APPROVE=280")

    def test_wrapped_merge_denies_for_the_approval_reason(self):
        # B1 end to end: `time gh pr merge 291` reached GitHub before this.
        self._deny(f"time {GH_MERGE} 291", {}, "merge of PR #291 needs operator approval")

    def test_alias_definition_denies_with_its_own_reason(self):
        self._deny('gh alias set m "pr merge"', {},
                   "DEFINES a gh alias that expands to a merge")


if __name__ == "__main__":
    unittest.main()
