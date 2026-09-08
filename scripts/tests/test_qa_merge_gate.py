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

# Snapshot taken at import, BEFORE any test has patched anything. TestRepoScope
# asserts against these, so a cleanup that restores the wrong value (or none)
# fails loudly instead of leaking a dead path into every later test.
_ORIG_BRAIN = gate._BRAIN
_ORIG_PROTECTED_CFG = gate._PROTECTED_CFG


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

    def test_a_reparsing_head_does_not_hide_the_merge(self):
        # Replaces test_documented_residual_stays_documented, whose only job was
        # to assert this vulnerability EXISTED. The trade it pinned was false:
        # the property that separates these from the quoted mention above is not
        # quoting, it is that bash/sh/ssh/script RE-PARSE their string argument
        # as a command while git commit and echo never do (A4).
        for cmd in (f'bash -c "{GH_MERGE} 96"', f"sh -lc '{GH_MERGE} 96'",
                    f'ssh localhost "{GH_MERGE} 96"',
                    f'script -qc "{GH_MERGE} 96" /dev/null',
                    f'zsh -c "{GH_MERGE} 96"',
                    f'bash <<EOF\n{GH_MERGE} 96\nEOF'):
            with self.subTest(cmd=cmd):
                found = gate._find_publish_subcmds(cmd)
                self.assertEqual([("gh")], [f for _s, f in found])
                self.assertEqual("96", gate._extract_pr_id(found[0][0]))

    def test_eval_reparses_its_arguments_quoted_or_not(self):
        # `eval gh pr merge 96` denied through the peel while `eval "gh pr merge
        # 96"` allowed (measured 2026-09-08) — the quoting, not the command, was
        # deciding. eval concatenates ALL its arguments and runs the result, so
        # both are the same command and both deny.
        for cmd in (f'eval "{GH_MERGE} 96"', f"eval '{GH_MERGE} 96'",
                    f"eval {GH_MERGE} 96"):
            with self.subTest(cmd=cmd):
                found = gate._find_publish_subcmds(cmd)
                self.assertEqual([("gh")], [f for _s, f in found])
                self.assertEqual("96", gate._extract_pr_id(found[0][0]))

    def test_a_head_that_does_not_reparse_keeps_the_mention_benign(self):
        # The control for the test above: without it, "recursion into a quoted
        # argument" would just be the false positive re-introduced.
        for cmd in (f'git commit -m "{GH_MERGE} 96"',
                    f'echo "{GH_MERGE} 96" >> notes.txt',
                    'echo "git push origin main"',
                    f"python3 - <<'PY'\nprint('{GH_MERGE} 96')\nPY"):
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
        gate._aliases_cache = {}
        self.addCleanup(setattr, gate, "_aliases_cache", {})

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

    def setUp(self):
        # Registered FIRST so it runs LAST (cleanups are LIFO): by then every
        # patch below must have put the module back exactly as it was.
        self.addCleanup(self._assert_module_globals_restored)

    def _assert_module_globals_restored(self):
        # D (tenth instance of the PR #282 class): the old cleanup captured its
        # restore value AFTER patcher.start(), so `Path.home()` already resolved
        # to the sandbox and it restored _BRAIN to a dead path; _PROTECTED_CFG
        # was never restored at all. Measured: every later in-process test ran
        # with gate._BRAIN pointing at a deleted temp dir. It changed no verdict
        # only because later classes mock around it — luck, not isolation.
        self.assertEqual(_ORIG_BRAIN, gate._BRAIN)
        self.assertEqual(_ORIG_PROTECTED_CFG, gate._PROTECTED_CFG)

    def _protected(self, command: str, env: dict | None = None):
        home = self._sandbox()
        # patch.object snapshots the CURRENT value before setting, so the
        # restore cannot depend on anything the other patches changed.
        for name, value in (("_BRAIN", home / ".claude"),
                            ("_PROTECTED_CFG",
                             home / ".claude" / "company" / "config"
                             / "protected-repos.json")):
            p = unittest.mock.patch.object(gate, name, value)
            p.start()
            self.addCleanup(p.stop)
        patcher = unittest.mock.patch.dict(
            os.environ, dict({"HOME": str(home), "USERPROFILE": str(home)},
                             **(env or {})))
        patcher.start()
        self.addCleanup(patcher.stop)
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


class _GateRunner:
    """Runs the gate end to end under a sandbox HOME and asserts on the REASON.

    A mixin rather than a base TestCase, so a second end-to-end class reuses the
    receipt seeding and the deny/allow assertions instead of forking them.
    """

    SESSION = "sess-qa-gate-test"

    def _seed_receipt(self, sandbox: str, pr: str, verdict: str, agent_type: str):
        """A harness-SHAPED QA receipt: ledger line plus the agent transcript it
        points at, laid out where the harness writes one. Anything less is
        rejected by receipt_ledger.qa_pass_for, which is the point."""
        agent_id = "agentqa1"
        tdir = (Path(sandbox) / ".claude" / "projects" / "slug" / self.SESSION
                / "subagents")
        tdir.mkdir(parents=True)
        tpath = tdir / f"agent-{agent_id}.jsonl"
        tpath.write_text(json.dumps({
            "type": "assistant", "uuid": "u1", "parentUuid": None,
            "sessionId": self.SESSION, "timestamp": "2026-09-08T00:00:00Z",
            "message": {"content": [{"type": "text", "text":
                                     f"QA-VERDICT: {verdict}\nQA-SCOPE: PR #{pr}"}]},
        }) + "\n", encoding="utf-8")
        ledger = Path(sandbox) / ".claude" / ".cache" / "receipts"
        ledger.mkdir(parents=True, exist_ok=True)
        (ledger / "global.jsonl").write_text(json.dumps({
            "kind": "qa", "verdict": verdict, "agent_type": agent_type,
            "agent_id": agent_id, "agent_transcript_path": str(tpath),
            "ts": "2026-09-08T00:00:00Z", "scope": f"PR #{pr}",
        }) + "\n", encoding="utf-8")

    def _run(self, command: str, env: dict, receipt: dict | None = None):
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
        if receipt:
            self._seed_receipt(sandbox, **receipt)
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command},
                              "cwd": "/nonexistent/repo",
                              "session_id": self.SESSION})
        cp = subprocess.run([sys.executable, str(SCRIPTS / "qa-merge-gate.py")],
                            input=payload, capture_output=True, text=True, env=full,
                            timeout=30)
        return cp.returncode, cp.stderr

    def _deny(self, command: str, env: dict, *reasons: str, receipt: dict | None = None):
        rc, err = self._run(command, env, receipt)
        self.assertEqual(2, rc, err)
        for reason in reasons:
            self.assertIn(reason, err)
        self.assertNotIn("crashed AFTER", err)

    def _allow(self, command: str, env: dict | None = None):
        """rc 0, and no refusal on stderr. Over-fire is MEASURED here, not
        assumed: a gate people route around is off, so the benign twin of every
        deny is an assertion, not a comment."""
        rc, err = self._run(command, env or {})
        self.assertEqual(0, rc, err)
        self.assertNotIn("QA GATE (fail-closed)", err)


class TestGateEndToEnd(_GateRunner, unittest.TestCase):
    """Every deny asserts its REASON, not just rc=2.

    rc 2 is also what the fail-closed crash handler returns, so replacing the
    whole post-identification body with `raise` left all five deny tests green:
    they were pinning "something refused", which the crash path satisfies. A
    gate that denies for the wrong reason is a gate nobody can debug, so the
    stderr line is the assertion and the exit code is the sanity check.
    """

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

    def test_approval_without_a_qa_receipt_denies_for_the_receipt_reason(self):
        # C: v7's whole contract had ZERO coverage. Mutating `if not qa_ok:` to
        # `if False:` deleted the receipt requirement — an approval alone merged
        # — and 255 tests plus all 27 selftest legs still passed, because every
        # fixture that set OCTO_MERGE_APPROVE also set OCTO_QA_OK=1, so nothing
        # ever took this branch. HOME is a sandbox here, so the ledger is empty
        # and qa_pass_for returns None the same way it does on a real miss.
        self._deny(f"{GH_MERGE} 280", {"OCTO_MERGE_APPROVE": "280"},
                   "carries NO QA receipt", "QA-VERDICT: PASS", "QA-SCOPE: PR #280")

    def test_a_qa_receipt_for_the_approved_pr_allows_the_merge(self):
        # The control: without it the test above passes on a gate that denies
        # every approved merge, receipt or not.
        rc, err = self._run(
            f"{GH_MERGE} 280", {"OCTO_MERGE_APPROVE": "280"},
            receipt={"pr": "280", "verdict": "PASS", "agent_type": "qa-reviewer"})
        self.assertEqual(0, rc, err)

    def test_a_qa_receipt_for_a_DIFFERENT_pr_does_not_travel(self):
        self._deny(f"{GH_MERGE} 280", {"OCTO_MERGE_APPROVE": "280"},
                   "carries NO QA receipt",
                   receipt={"pr": "279", "verdict": "PASS",
                            "agent_type": "qa-reviewer"})

    def test_alias_definition_denies_with_its_own_reason(self):
        for cmd in ('gh alias set m "pr merge"',
                    "git config alias.pm 'push origin main'",
                    "git -c alias.p='push origin main' p"):
            with self.subTest(cmd=cmd):
                self._deny(cmd, {}, "DEFINES a gh or git alias that expands")


class TestQuotedVerbIsStillTheVerb(unittest.TestCase):
    """A1: one quote pair defeated the whole matcher.

    Every line here was measured ALLOWED by the live gate at 2ceb87c while
    actually invoking gh/git (logging stub on PATH). Root cause: the peel decoded
    only the HEAD token and matched the verb words against the raw remainder, so
    `gh "pr" merge` never looked like `gh pr merge`. The verbs are matched on
    DECODED tokens now; a whole-token quoted mention is ONE token and can never
    supply a verb word, which is why this costs no over-fire.
    """

    def test_a_quoted_or_escaped_verb_word_still_identifies_the_merge(self):
        for cmd, form in (('gh "pr" merge 291', "gh"),
                          ('gh pr "merge" 291', "gh"),
                          ("gh 'pr' 'merge' 291", "gh"),
                          ('gh pr me\\rge 291', "gh"),
                          ('git "push" origin main', "push"),
                          ('git push "origin" main', "push"),
                          ('git push origin ma"in"', "push"),
                          ('git push origin "main"', "push")):
            with self.subTest(cmd=cmd):
                self.assertEqual([(form)],
                                 [f for _s, f in gate._find_publish_subcmds(cmd)])

    def test_a_quoted_api_path_still_identifies_the_merge(self):
        cmd = 'gh api -X PUT repos/CarlosCaPe/octorato/pulls/291/me"rge"'
        self.assertEqual([("api")], [f for _s, f in gate._find_publish_subcmds(cmd)])
        self.assertEqual("291", gate._extract_pr_id(cmd))

    def test_the_pr_number_is_still_read_off_the_RAW_form(self):
        # The reason the two normalizations are kept separate. Flattening the
        # quoting for extraction too would read 280 (a flag VALUE) as the PR and
        # let an approval for 280 merge 281.
        self.assertEqual("281", gate._extract_pr_id(f'{GH_MERGE} -t "x 280" 281'))
        self.assertEqual("281", gate._extract_pr_id(f'{GH_MERGE} --body "see 280" 281'))


class TestSeparatorsAndHeadPositions(unittest.TestCase):
    """A2: `&` is a separator, and a benign head in front must not swallow the
    merge behind it. Both shapes were measured ALLOWED at 2ceb87c."""

    def test_background_separator_does_not_hide_the_next_command(self):
        for cmd in (f"git status & {GH_MERGE} 291",
                    f"cd /tmp & {GH_MERGE} 291",
                    f"ls & {GH_MERGE} 291"):
            with self.subTest(cmd=cmd):
                found = gate._find_publish_subcmds(cmd)
                self.assertEqual([("gh")], [f for _s, f in found])
                self.assertEqual("291", gate._extract_pr_id(found[0][0]))

    def test_the_separators_that_already_denied_still_deny(self):
        for cmd in (f"git status && {GH_MERGE} 291",
                    f"git status |& {GH_MERGE} 291",
                    f"for i in 291; do {GH_MERGE} $i; done",
                    f"{GH_MERGE} 291 &",
                    f"({GH_MERGE} 291)",
                    f"( {GH_MERGE} 291 )"):
            with self.subTest(cmd=cmd):
                self.assertTrue(gate._find_publish_subcmds(cmd), cmd)

    def test_ampersand_is_a_separator(self):
        # Pinned directly. The two halves of A2 (this split, and trying the
        # anchor at EVERY head position below) overlap on every shape either one
        # can be written as today, so each is pinned at its own seam rather than
        # through a command that both happen to catch. `&` backgrounds what
        # precedes it, so the cwd walk and the env walk have to see two
        # sub-commands here, not one.
        parts = [p.strip() for p in gate._split_subcmds(f"git status & {GH_MERGE} 291")
                 if p.strip()]
        self.assertEqual(["git status", f"{GH_MERGE} 291"], parts)

    def test_every_head_position_is_a_candidate(self):
        cands = gate._peel_candidates(f"git status & {GH_MERGE} 291")
        self.assertEqual(2, len(cands))
        self.assertTrue(any(dec.startswith(GH_MERGE) for _raw, dec in cands), cands)

    def test_a_trailing_ampersand_still_carries_the_pr_number(self):
        found = gate._find_publish_subcmds(f"{GH_MERGE} 291 &")
        self.assertEqual("291", gate._extract_pr_id(found[0][0]))


class TestShellProducedHeads(unittest.TestCase):
    """A3: heads the shell resolves and the tokenizer cannot.

    An opaque head is not decidable without executing something, so it is
    handled the deny-by-default way: the REMAINDER is tried against every head
    this gate knows. `$(cmd) push origin main` is a push to main whoever `cmd`
    turns out to be.
    """

    def test_an_opaque_head_with_a_merge_remainder_is_identified(self):
        for cmd in ("$(echo gh) pr merge 96",
                    "`echo gh` pr merge 96",
                    "${PATH:0:0}gh pr merge 96",
                    "$'gh' pr merge 96",
                    "G=gh; $G pr merge 96",
                    "$HOME/bin/gh pr merge 96",
                    "$(which git) push origin main"):
            with self.subTest(cmd=cmd):
                self.assertTrue(gate._find_publish_subcmds(cmd), cmd)

    def test_an_opaque_word_that_is_not_a_merge_stays_benign(self):
        # The control: the substitution must not turn every `$var` into a merge.
        for cmd in ("docs='gh pr merge'; echo $docs",
                    "echo $HOME",
                    "python3 $SCRIPT --selftest",
                    "$(which git) status"):
            with self.subTest(cmd=cmd):
                self.assertEqual([], gate._find_publish_subcmds(cmd))

    def test_a_command_substitution_is_one_token(self):
        toks = gate._tokens_with_offsets("$(echo gh) pr merge 96")
        self.assertEqual(["$(echo gh)", "pr", "merge", "96"],
                         [t for t, _s, _e in toks])


class TestGitAliases(unittest.TestCase):
    """A5: the git half of the alias surface, which was never fixed.

    `-c` needs no config file at all, so alias RESOLUTION could never catch it;
    the DEFINITION is what gets gated, exactly as `gh alias set` is.
    """

    def test_an_inline_c_alias_to_a_push_is_gated(self):
        for cmd in ("git -c alias.p='push origin main' p",
                    'git -c alias.p="push origin master" p',
                    "git -c alias.z='!gh pr merge 1' z"):
            with self.subTest(cmd=cmd):
                self.assertEqual([("alias")],
                                 [f for _s, f in gate._find_publish_subcmds(cmd)])

    def test_defining_a_push_alias_with_git_config_is_gated(self):
        for cmd in ("git config alias.pm 'push origin main'",
                    "git config --global alias.pm 'push origin main'",
                    "git config alias.pm 'push origin main' && git pm"):
            with self.subTest(cmd=cmd):
                self.assertIn("alias",
                              [f for _s, f in gate._find_publish_subcmds(cmd)])

    def test_a_harmless_git_alias_is_not_gated(self):
        for cmd in ("git config alias.st status",
                    "git config --get alias.st",
                    "git -c alias.l='log --oneline' l"):
            with self.subTest(cmd=cmd):
                self.assertEqual([], gate._find_publish_subcmds(cmd))

    def test_a_global_config_alias_is_resolved_to_what_it_runs(self):
        d = tempfile.mkdtemp(prefix="gitcfg-")
        self.addCleanup(shutil.rmtree, d, True)
        Path(d, "gitconfig").write_text(
            "[user]\n\tname = x\n[alias]\n\tpm = push origin main\n\tst = status\n",
            encoding="utf-8")
        patcher = unittest.mock.patch.dict(
            os.environ, {"GIT_CONFIG_GLOBAL": str(Path(d, "gitconfig"))})
        patcher.start()
        self.addCleanup(patcher.stop)
        gate._git_aliases_cache = {}
        self.addCleanup(setattr, gate, "_git_aliases_cache", {})
        self.assertEqual([("push")],
                         [f for _s, f in gate._find_publish_subcmds("git pm")])
        self.assertEqual([], gate._find_publish_subcmds("git st"))


class TestGhAliasSurfaces(unittest.TestCase):
    """A6: two gh alias surfaces the resolver could not see, both verified
    against the installed gh 2.88.1."""

    def _cfg(self, body: str) -> str:
        d = tempfile.mkdtemp(prefix="gh-cfg-")
        self.addCleanup(shutil.rmtree, d, True)
        Path(d, "config.yml").write_text(body, encoding="utf-8")
        gate._aliases_cache = {}
        self.addCleanup(setattr, gate, "_aliases_cache", {})
        return d

    def test_flow_style_aliases_are_read(self):
        d = self._cfg("git_protocol: https\naliases: {mrg: pr merge, co: pr checkout}\n")
        patcher = unittest.mock.patch.dict(os.environ, {"GH_CONFIG_DIR": d})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.assertEqual([("gh")], [f for _s, f in gate._find_publish_subcmds("gh mrg 291")])
        self.assertEqual([], gate._find_publish_subcmds("gh co 291"))

    def test_gh_config_dir_set_on_the_command_line_is_honoured(self):
        # The hook's own env does NOT carry it: the agent set it for gh only.
        d = self._cfg("aliases:\n    mrg: pr merge\n")
        for cmd in (f"GH_CONFIG_DIR={d} gh mrg 291",
                    f"export GH_CONFIG_DIR={d}; gh mrg 291"):
            with self.subTest(cmd=cmd):
                found = gate._find_publish_subcmds(cmd)
                self.assertEqual([("gh")], [f for _s, f in found])
                self.assertEqual(
                    "291",
                    gate._extract_pr_id(found[0][0], gate._cfg_dir_for(cmd, found[0][0])))


class TestOverFireIsASecurityFailure(unittest.TestCase):
    """E: a gate people route around is off. Each of these was DENIED by the
    live gate at 2ceb87c while performing no merge at all."""

    def test_a_heredoc_body_is_data_not_a_command(self):
        for cmd in ("cat > /tmp/n2.md <<'EOF'\nTo publish: git push origin main\nEOF",
                    f"cat > /tmp/notes.md <<'EOF'\nRun this:\n{GH_MERGE} 291\nEOF",
                    f"python3 - <<'PY'\nprint('{GH_MERGE} 291')\nPY"):
            with self.subTest(cmd=cmd):
                self.assertEqual([], gate._find_publish_subcmds(cmd))

    def test_a_shell_reading_that_same_heredoc_still_denies(self):
        # The control: the body is dropped because `cat` does not execute it.
        for cmd in (f"bash <<'EOF'\n{GH_MERGE} 291\nEOF",
                    "sh <<EOF\ngit push origin main\nEOF"):
            with self.subTest(cmd=cmd):
                self.assertTrue(gate._find_publish_subcmds(cmd), cmd)

    def test_an_unterminated_heredoc_marker_swallows_nothing(self):
        cmd = f'echo "a << b"\n{GH_MERGE} 291'
        self.assertEqual([("gh")], [f for _s, f in gate._find_publish_subcmds(cmd)])

    def test_pushing_local_main_INTO_another_branch_is_not_a_publish(self):
        for cmd in ("git push origin main:refs/heads/feature-x",
                    "git push origin master:feature-x",
                    "git push origin main:refs/heads/wip"):
            with self.subTest(cmd=cmd):
                self.assertEqual([], gate._find_publish_subcmds(cmd))

    def test_every_real_push_to_main_still_denies(self):
        # The control for the refspec fix: the destination is what matters, and
        # every spelling of "the destination is main" still matches.
        for cmd in ("git push origin main", "git push origin HEAD:main",
                    "git push origin :main", "git push origin +main",
                    "git push -u origin master", "git push origin main:main",
                    "git push origin feature:refs/heads/main",
                    "git push origin main --force"):
            with self.subTest(cmd=cmd):
                self.assertEqual([("push")],
                                 [f for _s, f in gate._find_publish_subcmds(cmd)])

    def test_asking_for_help_merges_nothing(self):
        for cmd in (f"{GH_MERGE} --help", f"{GH_MERGE} -h", f"{GH_MERGE} 291 --help"):
            with self.subTest(cmd=cmd):
                self.assertEqual([], gate._find_publish_subcmds(cmd))

    def test_a_dash_h_that_is_a_flag_VALUE_is_not_a_help_request(self):
        # The control: `-h` inside a value must not turn a real merge into an
        # allow. This is why the check walks tokens instead of searching.
        for cmd in (f'{GH_MERGE} -t "-h" 291', f'{GH_MERGE} --body "-h" 291'):
            with self.subTest(cmd=cmd):
                self.assertEqual([("gh")],
                                 [f for _s, f in gate._find_publish_subcmds(cmd)])
                self.assertEqual("291", gate._extract_pr_id(cmd))


class TestPinnedInternals(unittest.TestCase):
    """Seven mutants that survived both the 255 tests and all 27 selftest legs.

    Each test below dies when its mutation is re-applied. They pin INTERNALS on
    purpose: the fixtures prove the gate blocks, and these prove WHY it blocks,
    which is the part a refactor silently deletes.
    """

    def test_group_chars_are_stripped_before_the_head_scan(self):
        # mutant: _W_GROUP strip removed. `(gh ...` is one token whose basename
        # is `(gh`, so without the strip nothing anchors.
        self.assertEqual([("gh")],
                         [f for _s, f in gate._find_publish_subcmds(f"({GH_MERGE} 291)")])
        self.assertEqual("291", gate._extract_pr_id(f"({GH_MERGE} 291)"))

    def test_prefix_env_stops_at_the_command_head(self):
        # mutant: the break-on-head removed. Without it an ARGUMENT that looks
        # like an assignment is read as env, and
        # `gh pr merge 291 --body GH_REPO=someone/unrelated` would resolve the
        # target to an unrelated repo and ungate a protected merge.
        self.assertEqual({}, gate._prefix_env(f"{GH_MERGE} 291 --body GH_REPO=x/y"))
        self.assertEqual({"GH_REPO": "o/r"},
                         gate._prefix_env(f"GH_REPO=o/r {GH_MERGE} 291"))

    def test_cd_is_a_command_head_so_the_cwd_walk_sees_it_through_a_wrapper(self):
        # mutant: `cd` dropped from _CMD_HEADS. The cwd walk peels to a head
        # before reading `cd <path>`, so without it a wrapped cd is invisible
        # and the effective cwd is wrong.
        cmd = "nohup cd /tmp/zz; git push origin main"
        sub = gate._find_publish_subcmds(cmd)[0][0]
        self.assertEqual("/tmp/zz", gate._effective_cwd(cmd, sub, "/base"))

    def test_curl_is_a_command_head_so_a_wrapped_api_write_anchors(self):
        # mutant: `curl` dropped from _CMD_HEADS. Then the peel finds no head,
        # the ^curl anchor fails and the API write walks.
        cmd = "time curl -X PUT https://api.github.com/repos/o/r/pulls/1/merge"
        self.assertEqual([("api")], [f for _s, f in gate._find_publish_subcmds(cmd)])
        self.assertEqual("1", gate._extract_pr_id(cmd))

    def test_the_unclosed_quote_fallback_still_yields_tokens(self):
        # mutant: _ws_tokens returns []. Then a wrapped command with an unclosed
        # quote has no tokens, no head is found, the anchor is lost and the gate
        # falls OPEN on the one input it cannot parse.
        self.assertTrue(gate._ws_tokens('time gh pr merge 291 "'))
        self.assertEqual([("gh")],
                         [f for _s, f in gate._find_publish_subcmds(f'time {GH_MERGE} 291 "')])
        self.assertEqual("unknown", gate._extract_pr_id(f'time {GH_MERGE} 291 "'))


class TestCrossScriptContract(unittest.TestCase):
    """receipt_ledger imports two names out of this gate. 2ceb87c deleted one of
    them and the consumer's `except Exception` swallowed it, so the split
    silently became a no-op. No test noticed, which is the whole problem."""

    def test_receipt_ledger_can_still_borrow_the_splitter(self):
        ledger = _load("receipt_ledger_under_test", "receipt_ledger.py")
        split, strip = ledger._qa_gate_helpers()
        self.assertEqual(2, len([p for p in split("a && b") if p.strip()]))
        self.assertEqual("git status", strip("A=1 2>/dev/null git status"))

    def test_receipt_ledger_subcommands_actually_splits(self):
        ledger = _load("receipt_ledger_under_test2", "receipt_ledger.py")
        self.assertGreaterEqual(len(ledger.subcommands("echo a && echo b")), 2)


class TestCrashPathJournalsItsRefusal(unittest.TestCase):
    """A fail-closed crash printed and exited 2 without a kernel journal line,
    so the one refusal nobody can re-run left no record."""

    def setUp(self):
        self.addCleanup(setattr, gate, "_PUBLISH_IDENTIFIED", False)
        self.addCleanup(setattr, gate, "_LAST_PAYLOAD", None)

    def test_the_crash_handler_journals(self):
        seen = []
        with unittest.mock.patch.object(gate, "main", side_effect=RuntimeError("boom")), \
                unittest.mock.patch.object(gate, "_journal_deny",
                                           side_effect=lambda *a, **k: seen.append(a)):
            gate._PUBLISH_IDENTIFIED = True
            gate._LAST_PAYLOAD = {"session_id": "s"}
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(2, gate._guarded_main())
        self.assertEqual(1, len(seen))
        self.assertIn("crashed", seen[0][0])
        self.assertEqual({"session_id": "s"}, seen[0][1])


class TestProtectedTargetResolution(unittest.TestCase):
    """The two repo-resolution mutants: the clone-slug check and the linked
    worktree gitdir candidate. Both survived the whole suite."""

    def setUp(self):
        self.addCleanup(self._assert_module_globals_restored)

    def _assert_module_globals_restored(self):
        self.assertEqual(_ORIG_BRAIN, gate._BRAIN)
        self.assertEqual(_ORIG_PROTECTED_CFG, gate._PROTECTED_CFG)

    def _home(self):
        d = Path(tempfile.mkdtemp(prefix="qa-gate-resolve-"))
        self.addCleanup(shutil.rmtree, d, True)
        for name, url in ((".claude", "CarlosCaPe/octorato"),
                          ("other", "someone/unrelated")):
            (d / name / ".git").mkdir(parents=True)
            (d / name / ".git" / "config").write_text(
                '[remote "origin"]\n\turl = https://github.com/%s.git\n' % url,
                encoding="utf-8")
        for name, value in (("_BRAIN", d / ".claude"),
                            ("_PROTECTED_CFG",
                             d / ".claude" / "company" / "config"
                             / "protected-repos.json")):
            p = unittest.mock.patch.object(gate, name, value)
            p.start()
            self.addCleanup(p.stop)
        return d

    def _protected(self, home, cwd):
        cmd = "git push origin main"
        sub = gate._find_publish_subcmds(cmd)[0][0]
        return gate._is_protected_target(cmd, sub, str(cwd))

    def test_a_clone_of_a_protected_repo_anywhere_is_protected(self):
        # mutant: the tgt_slug comparison removed. A clone of the brain living
        # outside every protected PATH would then classify as ungated.
        home = self._home()
        clone = home / "elsewhere" / "octorato-clone"
        (clone / ".git").mkdir(parents=True)
        (clone / ".git" / "config").write_text(
            '[remote "origin"]\n\turl = git@github.com:CarlosCaPe/octorato.git\n',
            encoding="utf-8")
        self.assertIs(True, self._protected(home, clone))

    def test_an_unrelated_clone_is_still_ungated(self):
        home = self._home()
        self.assertIs(False, self._protected(home, home / "other"))

    def test_a_linked_worktree_of_a_protected_repo_is_protected(self):
        # mutant: the gitdir candidate dropped from `candidates`. A linked
        # worktree's .git is a FILE pointing into the main repo's .git dir, and
        # that pointer is the ONLY thing tying it to the brain: its own path is
        # outside every protected root and it carries no remote of its own.
        home = self._home()
        (home / ".claude" / ".git" / "worktrees" / "wt1").mkdir(parents=True)
        wt = home / "wt" / "qa-gate"
        wt.mkdir(parents=True)
        (wt / ".git").write_text(
            "gitdir: %s\n" % (home / ".claude" / ".git" / "worktrees" / "wt1"),
            encoding="utf-8")
        self.assertIs(True, self._protected(home, wt))

    def test_a_push_to_the_protected_repo_BY_URL_is_protected(self):
        # The target of a push can be a URL where a remote name goes, and then
        # the cwd repo is not the repo being written. Fired from an unrelated
        # repo this ungated; it only denied from a non-repo cwd, by luck.
        home = self._home()
        for url in ("https://github.com/CarlosCaPe/octorato.git",
                    "git@github.com:CarlosCaPe/octorato.git",
                    "https://github.com/CarlosCaPe/octorato"):
            with self.subTest(url=url):
                cmd = f"git push {url} main"
                sub = gate._find_publish_subcmds(cmd)[0][0]
                self.assertIs(True, gate._is_protected_target(
                    cmd, sub, str(home / "other")))

    def test_a_push_to_an_unrelated_url_from_an_unrelated_repo_still_ungates(self):
        # The control: the URL check is positive-only, so it must not gate
        # everything that happens to carry a github URL.
        home = self._home()
        cmd = "git push https://github.com/someone/unrelated.git main"
        sub = gate._find_publish_subcmds(cmd)[0][0]
        self.assertIs(False, gate._is_protected_target(cmd, sub, str(home / "other")))

    def test_a_linked_worktree_of_an_unrelated_repo_is_not_protected(self):
        home = self._home()
        (home / "other" / ".git" / "worktrees" / "wt1").mkdir(parents=True)
        wt = home / "wt" / "other-arm"
        wt.mkdir(parents=True)
        (wt / ".git").write_text(
            "gitdir: %s\n" % (home / "other" / ".git" / "worktrees" / "wt1"),
            encoding="utf-8")
        self.assertIs(False, self._protected(home, wt))


if __name__ == "__main__":
    unittest.main()


def _nest(levels: int, inner: str) -> str:
    """`inner` wrapped in *levels* nested `bash -c` invocations, quoted so a real
    shell actually runs it. Built, not hand-written, because hand-escaping five
    levels is how a nesting test ends up testing its own typo."""
    import shlex
    cur = inner
    for _ in range(levels):
        cur = "bash -c " + shlex.quote(cur)
    return cur


class TestCommandFlagIsMatchedExactly(unittest.TestCase):
    """QA cycle 3, bypass 1 — MEASURED allowing rc 0 and proven to execute the
    real gh through a fake `gh` on PATH.

    `_reparse_arg` found the command flag by SUBSTRING: `w.startswith("-") and
    "c" in w.lstrip("-")`. `--norc` contains a `c`, so the command string came
    back as the literal `-c`, the recursion found nothing in it, and the caller
    then `continue`d PAST the direct match as well. A wrong guess REPLACED the
    check instead of falling back to it, and that is the shape under test here,
    not the one flag.
    """

    def test_a_shell_option_that_merely_contains_c_is_not_the_command_flag(self):
        for flag in ("--norc", "--noprofile", "--rcfile", "--login"):
            with self.subTest(flag=flag):
                self.assertFalse(gate._is_command_flag(flag))

    def test_the_real_command_flag_and_its_bundles_are(self):
        for flag in ("-c", "-lc", "-ic", "-xc", "-qc", "--command"):
            with self.subTest(flag=flag):
                self.assertTrue(gate._is_command_flag(flag))

    def test_norc_no_longer_hides_the_merge_behind_it(self):
        for cmd in (f'bash --norc -c "{GH_MERGE} 292"',
                    f'bash --rcfile /dev/null -c "{GH_MERGE} 292"',
                    f'bash --noprofile --norc -c "{GH_MERGE} 292"'):
            with self.subTest(cmd=cmd):
                self.assertEqual(["gh"],
                                 [f for _s, f in gate._find_publish_subcmds(cmd)])

    def test_a_reparse_that_resolves_nothing_does_not_delete_the_direct_match(self):
        # `script -q` re-parses nothing (`-q` is not a command flag), so the
        # re-parse comes back empty and the DIRECT match has to run. Pinning the
        # fall-through itself, which is what the `continue` used to eat.
        found = gate._find_publish_subcmds(f"script -q {GH_MERGE} 292")
        self.assertEqual(["gh"], [f for _s, f in found])


class TestReparseCapFailsClosed(unittest.TestCase):
    """QA cycle 3, bypass 2 — depth 3 denied and depth 4 ALLOWED, measured
    executing the real gh. The cap is a cost bound; "I stopped looking" was
    being spent as "there is nothing there"."""

    def test_a_merge_nested_past_the_cap_is_still_identified(self):
        cmd = _nest(gate._MAX_REPARSE_DEPTH + 2, f"{GH_MERGE} 292")
        self.assertTrue(gate._find_publish_subcmds(cmd),
                        "a shell left unread at the cap must still be a finding")

    def test_a_merge_inside_the_cap_is_read_as_the_merge_it_is(self):
        cmd = _nest(gate._MAX_REPARSE_DEPTH, f"{GH_MERGE} 292")
        self.assertEqual(["gh"], [f for _s, f in gate._find_publish_subcmds(cmd)])

    def test_benign_nesting_inside_the_cap_stays_benign(self):
        cmd = _nest(gate._MAX_REPARSE_DEPTH, "git status --short")
        self.assertEqual([], gate._find_publish_subcmds(cmd))


class TestStdinChannelsBesidesHeredocs(unittest.TestCase):
    """QA cycle 3, bypasses 3 and 4. `_HEREDOC_RE` matches `<<WORD` only, so a
    here-string never became a body and `_reparses_stdin` was never consulted;
    process substitution was opaque to the peel outright. Both measured
    executing the real gh."""

    def test_a_here_string_into_a_shell_is_a_command(self):
        for cmd in (f'bash <<< "{GH_MERGE} 292"',
                    f'bash /dev/stdin <<< "{GH_MERGE} 292"',
                    f'bash <<<"{GH_MERGE} 292"'):
            with self.subTest(cmd=cmd):
                self.assertEqual(["gh"],
                                 [f for _s, f in gate._find_publish_subcmds(cmd)])

    def test_a_process_substitution_is_a_command(self):
        cmd = f'bash <(echo "{GH_MERGE} 292")'
        self.assertEqual(["gh"], [f for _s, f in gate._find_publish_subcmds(cmd)])

    def test_a_process_substitution_is_one_token(self):
        toks = gate._tokens_with_offsets('bash <(echo "a b")')
        self.assertEqual(["bash", '<(echo "a b")'], [t for t, _s, _e in toks])

    def test_a_here_string_carrying_no_command_stays_data(self):
        self.assertEqual([], gate._find_publish_subcmds("cat <<< 'hello world'"))
        self.assertEqual([], gate._find_publish_subcmds('bash <<< "echo hi"'))


class TestUnnamedWrapperInversion(unittest.TestCase):
    """QA cycle 3, bypass 5. `_REPARSE_HEADS` is an ALLOWLIST and the wrapper
    nobody named is a total bypass — cycle 1's finding one layer up. The peel was
    inverted for BARE heads; this inverts it for the quoted-argument case too.

    The benign twins are the whole point of the boundary and are asserted here,
    not assumed: neither `echo "…"` nor `git commit -m "…"` carries a
    `-c`-style flag, and `gcc -c main.c` carries one whose value is not a
    command."""

    def test_a_wrapper_this_gate_never_heard_of_is_still_a_reparse(self):
        for cmd in (f'flock /tmp/l -c "{GH_MERGE} 292"',
                    f'su -c "{GH_MERGE} 292"',
                    f'su -l someone -c "{GH_MERGE} 292"',
                    'runuser -u x -c "git push origin main"'):
            with self.subTest(cmd=cmd):
                self.assertTrue(gate._find_publish_subcmds(cmd), cmd)

    def test_the_quoted_mention_controls_stay_benign(self):
        for cmd in (f'echo "{GH_MERGE} 96"',
                    f'git commit -m "{GH_MERGE} 96"',
                    'gcc -c main.c -o main.o',
                    'git commit -m "docs: how to git push origin main"'):
            with self.subTest(cmd=cmd):
                self.assertEqual([], gate._find_publish_subcmds(cmd), cmd)


class TestOverFireRegressions(_GateRunner, unittest.TestCase):
    """Two commands that DENIED while publishing nothing (measured 2026-09-08).
    Over-fire is treated as a security failure here: a gate people route around
    is off."""

    def test_a_shell_comment_is_not_a_command(self):
        self._allow(f"git status # {GH_MERGE} 292")
        self._allow(f"git log --oneline # then {GH_MERGE} 292")

    def test_a_hash_inside_a_word_is_not_a_comment(self):
        # a URL fragment must not swallow the rest of the line
        self.assertEqual(
            ["curl https://x#frag ", f" {GH_MERGE} 292"],
            gate._split_subcmds(f"curl https://x#frag ; {GH_MERGE} 292"))

    def test_a_merge_followed_by_a_comment_still_denies(self):
        self._deny(f"{GH_MERGE} 292 # ship it", {},
                   "needs operator approval", "PR #292")

    def test_a_dry_run_push_writes_nothing(self):
        self._allow("git push --dry-run origin main")
        self._allow("git push -n origin main")

    def test_a_real_push_to_main_still_denies(self):
        self._deny("git push origin main", {}, "needs operator approval",
                   "branch 'main'")

    def test_a_dry_run_that_is_a_flag_VALUE_is_not_a_rehearsal(self):
        self.assertFalse(gate._git_push_is_dry_run(
            'git push -o "--dry-run" origin main'))
        self.assertTrue(gate._git_push_is_dry_run("git push --dry-run origin main"))

    def test_a_hyphenated_subcommand_is_not_push(self):
        self._allow("git push-mirror origin main")

    def test_only_an_all_digit_token_is_the_pr_number(self):
        # a branch or URL argument has no PR number, and guessing one out of a
        # token that merely STARTS with digits would make it approvable.
        self.assertIsNone(gate._gh_merge_pr_num(f"{GH_MERGE} 2fa-branch"))
        self.assertEqual("292", gate._gh_merge_pr_num(f"{GH_MERGE} 292"))


class TestLineContinuationsAreJoined(unittest.TestCase):
    """FIX 5 shipped with ZERO coverage: mutating `_join_continuations` to
    `return cmd` flipped this shape deny→allow while all 90 unit tests and the
    30-fixture selftest stayed green."""

    def test_a_backslash_newline_does_not_break_the_verb(self):
        self.assertEqual(
            ["gh"], [f for _s, f in gate._find_publish_subcmds("gh pr \\\n merge 292")])

    def test_the_pr_number_survives_the_join(self):
        found = gate._find_publish_subcmds("gh pr \\\n merge 292")
        self.assertEqual("292", gate._extract_pr_id(found[0][0]))


class TestTheGateOutlivesItsOwnTimeout(unittest.TestCase):
    """QA cycle 3, bypass 6. `hooks.json` gives this gate 5 seconds. 500
    `;`-joined no-ops plus a merge took 9.7 s and 2000 took 132 s, because
    `_cfg_dir_for` re-derived the whole line PER sub-command. The gate still
    returned 2; it just never got to say so, and a fail-closed contract that
    depends on the process surviving is not fail-closed.

    Asserted as CALL COUNTS, not as wall-clock, so it pins the complexity rather
    than the machine it runs on.
    """

    def _count_splits(self, cmd: str) -> int:
        real = gate._split_subcmds
        calls = []

        def counting(c):
            calls.append(c)
            return real(c)

        gate._PARTS_CACHE.clear()
        gate._ENV_CHAIN_CACHE.clear()
        gate._TOKENS_CACHE.clear()
        gate._split_subcmds = counting
        try:
            gate._find_publish_subcmds(cmd)
        finally:
            gate._split_subcmds = real
        return len(calls)

    def test_the_line_is_not_re_split_once_per_sub_command(self):
        n_small = self._count_splits("; ".join(["true"] * 50 + [f"{GH_MERGE} 292"]))
        n_big = self._count_splits("; ".join(["true"] * 500 + [f"{GH_MERGE} 292"]))
        self.assertEqual(n_small, n_big,
                         "the split count must not grow with the sub-command count")
        self.assertLess(n_big, 20, "the whole line should be split a few times, once")

    def test_the_line_is_tokenized_once_per_distinct_string(self):
        big = 'gh pr merge -b "' + "x" * 20000 + '" 292'
        real = gate._tokenize
        calls = []

        def counting(s):
            calls.append(s)
            return real(s)

        gate._PARTS_CACHE.clear()
        gate._ENV_CHAIN_CACHE.clear()
        gate._TOKENS_CACHE.clear()
        gate._ARG_TOKENS_CACHE.clear()
        gate._tokenize = counting
        try:
            gate._find_publish_subcmds(big)
        finally:
            gate._tokenize = real
        self.assertEqual(len(calls), len(set(calls)),
                         "the same string must never be tokenized twice")


class TestTokenizerBulkTakeIsExact(unittest.TestCase):
    """The bulk-run take in `_tokenize` is a speed change, so it has to be an
    IDENTITY, not an approximation. Pinned against the character-by-character
    semantics on the strings where the two could differ."""

    CASES = [
        "a 'b c' d", 'a "b c" d', "a\\ b", "'un'closed", '"un\\"closed"',
        "a$(echo b c)d", "a`echo b`c", "x'y\"z'w", 'x"y\'z"w', "  a  b  ",
        "a\\\nb", "$'gh' pr merge 1", "${PATH:0:0}gh pr merge 1", "a<b", "a>b",
        "'a b' 'c d'", '"" a', "'' a", "a#b # c", "\\", "'", '"',
    ]

    def test_every_shape_tokenizes_the_way_a_shell_words_it(self):
        for s in self.CASES:
            with self.subTest(s=s):
                toks = gate._tokenize(s)
                if toks is None:
                    continue
                for text, start, end in toks:
                    self.assertLessEqual(start, end)
                    self.assertEqual(s[start:end].strip(), s[start:end])

    def test_an_unclosed_quote_is_still_unparseable(self):
        self.assertIsNone(gate._tokenize("'un'closed 'x"))
        self.assertIsNone(gate._tokenize('a "b'))

    def test_a_quoted_argument_stays_one_token(self):
        self.assertEqual(["a", "b c", "d"],
                         [t for t, _s, _e in gate._tokenize("a 'b c' d")])
        self.assertEqual(["a", "b c", "d"],
                         [t for t, _s, _e in gate._tokenize('a "b c" d')])
