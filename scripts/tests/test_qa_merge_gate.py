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


class TestOptionsAfterTheCommandFlag(unittest.TestCase):
    """QA cycle 4, root cause (a). `_command_flag_value` returned the token
    IMMEDIATELY after `-c`, but bash, sh, dash and ksh keep parsing OPTIONS after
    it: the command string is the first NON-option word, and `--` ends option
    parsing. So the gate read `--` or `-e` as the command, the recursion found
    nothing in it, and the fall-through direct match cannot see a quoted token.

    `bash -c -- "…"`, `bash -c -e "…"` and `sh -c -- "…"` all ALLOWED and all
    three were proved to execute, by running them with a fake `gh` first on PATH
    and reading `pr merge` back out of its log.
    """

    def test_an_option_between_the_flag_and_the_string_does_not_hide_it(self):
        for cmd in (f'bash -c -- "{GH_MERGE} 292"',
                    f'bash -c -e "{GH_MERGE} 292"',
                    f'sh -c -- "{GH_MERGE} 292"',
                    f'dash -c -- "{GH_MERGE} 292"',
                    f'ksh -c -x -- "{GH_MERGE} 292"',
                    f'bash --norc -c -- "{GH_MERGE} 292"',
                    'sh -c -e -x "git push origin main"'):
            with self.subTest(cmd=cmd):
                self.assertTrue(gate._find_publish_subcmds(cmd), cmd)

    def test_the_end_of_options_marker_hands_over_the_next_word_even_if_it_looks_like_a_flag(self):
        self.assertEqual("-x", gate._command_flag_value(["-c", "--", "-x"]))
        self.assertIsNone(gate._command_flag_value(["-c", "--"]))

    def test_the_string_itself_is_still_the_string(self):
        self.assertEqual(f"{GH_MERGE} 292",
                         gate._command_flag_value(["-c", f"{GH_MERGE} 292"]))

    def test_the_benign_twin_one_edit_away_stays_benign(self):
        for cmd in (f'bash -c -- "gh pr view 292"',
                    f'sh -c -- "git status --short"'):
            with self.subTest(cmd=cmd):
                self.assertEqual([], gate._find_publish_subcmds(cmd), cmd)


class TestTheEqualsSpellingIsTheSameFlag(unittest.TestCase):
    """QA cycle 4, root cause (c). `--command "x"` denied and `--command="x"`
    allowed — the same flag, spelled the way `su(1)` and `flock(1)` document it.
    """

    def test_both_spellings_of_the_long_flag_carry_the_command(self):
        for cmd in (f'su --command="{GH_MERGE} 292"',
                    f'su --command="{GH_MERGE} 292" git',
                    f'flock --command="{GH_MERGE} 292" /tmp/l',
                    f'flock --command "{GH_MERGE} 292" /tmp/l'):
            with self.subTest(cmd=cmd):
                self.assertTrue(gate._find_publish_subcmds(cmd), cmd)

    def test_the_inline_value_is_the_value(self):
        self.assertEqual("x y", gate._command_flag_value(["--command=x y"]))
        self.assertIsNone(gate._command_flag_value(["--command="]))

    def test_an_unrelated_long_flag_with_an_equals_is_not_the_command_flag(self):
        self.assertIsNone(gate._command_flag_value(["--rcfile=/dev/null"]))
        self.assertIsNone(gate._command_flag_value(["--exec=/bin/true"]))


class TestTheCommandHeadIsAPosition(unittest.TestCase):
    """QA cycle 4, root cause (b). `_reparse_args` tested EVERY word ahead of the
    re-parsing head against `_CMD_HEADS` and returned "nothing re-parses" on a
    hit. So any wrapper whose path or user argument had the basename `gh`, `git`,
    `curl` or `cd` was a total bypass — and `git` is the canonical service-account
    and lock-file name, which makes `flock /var/lock/git -c "…"` and
    `sudo -u git bash -c "…"` ordinary shapes. Both measured ALLOW and both proved
    to execute against a fake `gh` on PATH.

    QA's mutant M51 deleted that short-circuit and SURVIVED the whole suite: the
    controls the commit credited to it (`git commit -m "gh pr merge 96"`) are
    protected by the `-c`-flag requirement, not by it.
    """

    def test_a_command_head_in_an_argument_hides_nothing(self):
        for cmd in (f'flock /var/lock/git -c "{GH_MERGE} 292"',
                    f'flock /tmp/locks/gh -c "{GH_MERGE} 292"',
                    'flock /var/lock/curl -c "git push origin main"',
                    f'sudo -u git bash -c "{GH_MERGE} 292"',
                    'sudo -u gh sh -c "git push origin main"',
                    f'runuser -u git -c "{GH_MERGE} 292"'):
            with self.subTest(cmd=cmd):
                self.assertTrue(gate._find_publish_subcmds(cmd), cmd)

    def test_the_head_is_read_past_env_assignments_and_redirections(self):
        for cmd in (f'FOO=1 flock /tmp/git -c "{GH_MERGE} 292"',
                    f'> /tmp/log flock /tmp/git -c "{GH_MERGE} 292"',
                    f'2>/dev/null flock /tmp/git -c "{GH_MERGE} 292"'):
            with self.subTest(cmd=cmd):
                self.assertTrue(gate._find_publish_subcmds(cmd), cmd)

    def test_head_index_skips_only_the_shell_noise(self):
        self.assertEqual(0, gate._head_index(["git", "status"]))
        self.assertEqual(1, gate._head_index(["FOO=1", "git", "status"]))
        self.assertEqual(2, gate._head_index([">", "/tmp/x", "git", "status"]))
        self.assertEqual(1, gate._head_index(["2>&1", "git", "status"]))

    def test_the_real_head_still_short_circuits(self):
        for cmd in (f'git commit -m "{GH_MERGE} 96"',
                    f'FOO=1 git commit -m "{GH_MERGE} 96"',
                    'gh pr view 292 --json state',
                    'cd /repo && git status'):
            with self.subTest(cmd=cmd):
                self.assertEqual([], gate._find_publish_subcmds(cmd), cmd)


class TestACountFlagIsNotACommandChannel(unittest.TestCase):
    """QA cycle 4, root cause (d) — over-fire, treated here as a security failure
    because a gate people route around is off. `grep -c`, `grep -rc`, `grep -ic`
    and `psql -c` all DENIED while publishing nothing.

    Three independent narrowings, each asserted on its own:
      * a `-c` inside a letter BUNDLE is not a command flag on the unnamed path;
      * a program whose `-c` is a count or a query is not a command channel;
      * the value must parse as a whole command LINE, not as a quoted MENTION
        inside somebody else's data.
    """

    def test_the_measured_over_fires_are_gone(self):
        for cmd in (f'grep -c "{GH_MERGE} 292" notes.md',
                    'grep -rc "git push origin main" docs/',
                    f'grep -ic "{GH_MERGE} 292" notes.md',
                    "psql -c \"insert into log values ('git push origin main')\"",
                    f'rg -c "{GH_MERGE} 292" .',
                    'sort -c file.txt', 'uniq -c log', 'gcc -c main.c -o main.o'):
            with self.subTest(cmd=cmd):
                self.assertEqual([], gate._find_publish_subcmds(cmd), cmd)

    def test_a_bundle_is_not_a_command_flag_on_the_unnamed_path(self):
        self.assertIsNone(gate._command_flag_value(["-rc", "x y"], bundles=False))
        self.assertEqual("x y", gate._command_flag_value(["-rc", "x y"]))

    def test_a_quoted_mention_inside_a_value_is_not_a_command_line(self):
        text = "insert into log values ('git push origin main')"
        self.assertEqual([], gate._publish_carriers(text, mentions=False))
        self.assertTrue(gate._publish_carriers(text))

    def test_the_wrapper_twin_one_edit_away_still_denies(self):
        # the SAME `-c` and the SAME value, on a head that is not a counter
        for cmd in (f'flock -c "{GH_MERGE} 292" /tmp/l',
                    f'su -c "{GH_MERGE} 292"'):
            with self.subTest(cmd=cmd):
                self.assertTrue(gate._find_publish_subcmds(cmd), cmd)

    def test_a_stdin_channel_keeps_the_mention_reading(self):
        # the second reading is a stdin-channel rule, not a universal one
        self.assertTrue(gate._find_publish_subcmds(f'bash <(echo "{GH_MERGE} 292")'))


class TestACommandSubstitutionIsAChannel(unittest.TestCase):
    """QA cycle 5, Class A — a fix that closed ONE member of a class and declared
    the class handled. Cycle 3 closed `<(…)` as a channel whose contents are
    re-matched; `$(…)` is the same channel, more common, and its contents were
    never looked at. `cat <(gh pr merge 291)` DENIED while
    `echo $(gh pr merge 291)` ALLOWED, both measured executing a fake `gh` on
    PATH — the asymmetry is the proof, because both spellings run the merge.

    This is NOT residual 1. There the verb comes FROM an expansion and sits
    OUTSIDE the substitution (`$(echo gh) pr merge 291`); here the verb is fully
    literal and sits INSIDE a `$(…)` that runs it.
    """

    def test_every_substitution_spelling_carries_the_merge(self):
        for cmd in (f"echo $({GH_MERGE} 291)",
                    f"x=$({GH_MERGE} 291)",
                    f"echo `{GH_MERGE} 291`",
                    f'eval "$(echo {GH_MERGE} 291)"',
                    f"tee >({GH_MERGE} 291) < /dev/null",
                    "y=`git push origin main`",
                    f"git commit -m \"$({GH_MERGE} 291)\"",
                    f"echo $(x $({GH_MERGE} 291))"):
            with self.subTest(cmd=cmd):
                self.assertTrue(gate._find_publish_subcmds(cmd), cmd)

    def test_the_scanner_returns_the_contents_not_the_wrapper(self):
        self.assertEqual([f"{GH_MERGE} 291"],
                         gate._command_substitution_texts(f"echo $({GH_MERGE} 291)"))
        self.assertEqual([f"{GH_MERGE} 291"],
                         gate._command_substitution_texts(f"echo `{GH_MERGE} 291`"))

    def test_the_opaque_head_reading_is_not_regressed(self):
        # residual 1's deliberate behaviour: the verb comes from the REMAINDER,
        # and the substitution itself carries no publish form.
        self.assertEqual(["echo gh"],
                         gate._command_substitution_texts("$(echo gh) pr merge 291"))
        self.assertEqual([], gate._find_publish_subcmds("echo gh"))
        self.assertTrue(gate._find_publish_subcmds("$(echo gh) pr merge 291"))

    def test_what_a_substitution_is_not(self):
        # arithmetic opens with the same two characters and runs nothing; a
        # substitution inside SINGLE quotes is not one; and the contents are read
        # as a command LINE, so a quoted mention inside them is that command's
        # data (`grep` is reading a file, not merging).
        for cmd in ("echo $((1+2)) && echo done",
                    f"docs='{GH_MERGE}'; echo $docs",
                    f'x=$(grep "{GH_MERGE} 291" notes.md)',
                    'echo "$(git log --oneline -1)"',
                    "msg=$(git rev-parse --short HEAD); echo $msg"):
            with self.subTest(cmd=cmd):
                self.assertEqual([], gate._find_publish_subcmds(cmd), cmd)


class TestAnOptionAfterTheCommandFlagCanTakeAValue(unittest.TestCase):
    """QA cycle 5, Class B — the cycle-4 fix left half done. `--` and boolean
    short options after `-c` were handled; an option that takes a VALUE was
    skipped without its value, so the VALUE came back as the command string
    (`bash -c -o pipefail "gh pr merge 292"` returned `pipefail` and ALLOWED),
    and the `+` spellings did not even look like options (`+O` does not start
    with `-`, so it was returned as the command itself).

    `sh -c -o` and `dash -c -o` also allowed but do NOT execute on those shells
    (measured), so they are not counted as bypasses here — only bash's do.
    """

    def test_the_command_string_is_found_past_a_valued_option(self):
        for rest, want in ((["-c", "-o", "pipefail", "CMD"], "CMD"),
                           (["-c", "+o", "pipefail", "CMD"], "CMD"),
                           (["-c", "-O", "extglob", "CMD"], "CMD"),
                           (["-c", "+O", "extglob", "CMD"], "CMD"),
                           (["-co", "pipefail", "CMD"], "CMD"),
                           (["-c", "-Oextglob", "CMD"], "CMD"),
                           (["-c", "--rcfile", "/dev/null", "CMD"], "CMD")):
            with self.subTest(rest=rest):
                self.assertEqual(want, gate._command_flag_value(rest))

    def test_the_boolean_and_double_dash_readings_still_hold(self):
        self.assertEqual("CMD", gate._command_flag_value(["-c", "--", "CMD"]))
        self.assertEqual("CMD", gate._command_flag_value(["-c", "-e", "CMD"]))
        self.assertEqual("CMD", gate._command_flag_value(["-c", "CMD"]))

    def test_the_shapes_that_execute_deny_end_to_end(self):
        for cmd in (f'bash -c -o pipefail "{GH_MERGE} 292"',
                    f'bash -c +O extglob "{GH_MERGE} 292"',
                    f'bash -co pipefail "{GH_MERGE} 292"'):
            with self.subTest(cmd=cmd):
                self.assertTrue(gate._find_publish_subcmds(cmd), cmd)

    def test_a_valued_option_that_carries_no_merge_stays_benign(self):
        for cmd in ('bash -c -o pipefail "ls | wc -l"',
                    'bash -c +O extglob "git status --short"'):
            with self.subTest(cmd=cmd):
                self.assertEqual([], gate._find_publish_subcmds(cmd), cmd)


class TestTheQuotedCommandPathIsDenyByDefaultToo(unittest.TestCase):
    """QA cycle 5, Class C — the architectural one. Deny-by-default was applied
    to BARE-HEAD peeling; the quoted-command path went back to an ENUMERATION of
    CHANNELS (`-c`, `--command`, stdin, ssh RemoteCommand, `eval`), and five
    wrappers arrived in one cycle that run their quoted argument through some
    other channel. An enumeration of channels loses to the next channel exactly
    the way an enumeration of verbs lost to the next verb.

    The fence moved onto the HEAD: on a head that is neither a command head nor
    a head whose arguments are DATA, EVERY argument that parses as a whole
    publish command line is a command that wrapper runs.
    """

    def test_the_five_channels_that_arrived_in_one_cycle(self):
        for cmd in (f'env -S "{GH_MERGE} 291"',
                    f'env --split-string="{GH_MERGE} 291"',
                    f'watch -n1 "{GH_MERGE} 291"',
                    f'parallel "{GH_MERGE} 291" ::: a',
                    f'printf %s "{GH_MERGE} 291" | bash',
                    f'echo "{GH_MERGE} 291" | sh',
                    f'echo "{GH_MERGE} 291" | xargs -I{{}} bash -c "{{}}"',
                    f"git -c core.sshCommand='{GH_MERGE} 291' fetch origin",
                    f"git -c sequence.editor='{GH_MERGE} 291' rebase -i HEAD~1"):
            with self.subTest(cmd=cmd):
                self.assertTrue(gate._find_publish_subcmds(cmd), cmd)

    def test_the_wrapper_nobody_has_named_yet_is_covered_by_the_same_rule(self):
        # the point of the inversion: these were never enumerated anywhere.
        for cmd in (f'systemd-run --user "{GH_MERGE} 291"',
                    f'chpst -u git "{GH_MERGE} 291"',
                    f'nsenter -t 1 -m "{GH_MERGE} 291"'):
            with self.subTest(cmd=cmd):
                self.assertTrue(gate._find_publish_subcmds(cmd), cmd)

    def test_a_head_whose_arguments_are_DATA_still_publishes_nothing(self):
        # the whole cost of the inversion sits here: over-fire is a security
        # failure, because a gate people route around is off.
        for cmd in (f'echo "{GH_MERGE} 291"',
                    f"printf 'next: git push origin main\\n'",
                    f'logger "deploy step: {GH_MERGE} 291"',
                    f'python3 -c "print(\'git push origin main\')"',
                    f'grep -c "{GH_MERGE} 291" notes.md',
                    f'mail -s "{GH_MERGE} 291" ops@example.com',
                    f'sed -n "s/{GH_MERGE} 291//p" notes.md'):
            with self.subTest(cmd=cmd):
                self.assertEqual([], gate._find_publish_subcmds(cmd), cmd)

    def test_a_pipe_into_something_that_only_READS_is_not_a_channel(self):
        for cmd in (f'echo "{GH_MERGE} 291" | grep merge',
                    f'echo "{GH_MERGE} 291" | wc -l',
                    f'echo "{GH_MERGE} 291" | tee /tmp/x',
                    f'echo "{GH_MERGE} 291" | mail -s note ops@example.com'):
            with self.subTest(cmd=cmd):
                self.assertEqual([], gate._find_publish_subcmds(cmd), cmd)

    def test_runs_its_stdin_reads_the_shape_not_a_name(self):
        self.assertTrue(gate._runs_its_stdin("bash"))
        self.assertTrue(gate._runs_its_stdin("sh -x"))
        self.assertTrue(gate._runs_its_stdin("xargs -I{} bash -c '{}'"))
        self.assertFalse(gate._runs_its_stdin("bash /tmp/script.sh"))
        self.assertFalse(gate._runs_its_stdin(f'bash -c "{GH_MERGE} 291"'))
        self.assertFalse(gate._runs_its_stdin("grep merge"))

    def test_the_separator_that_makes_the_pipe_a_channel_is_kept(self):
        self.assertEqual([("a ", "|"), (" b", "")], gate._split_subcmds_sep("a | b"))
        self.assertEqual(["a ", " b"], gate._split_subcmds("a | b"))


class TestSshCarriesItsCommandTwoWays(unittest.TestCase):
    """QA cycle 4. `ssh -o RemoteCommand='gh pr merge 292' host` ALLOWED; `ssh -G`
    confirms the option carries the command. The old read took `rest[1:]` — every
    word after the FIRST argument — so one option in front shifted the
    destination and the remote command was read a word early."""

    def test_the_remote_command_option_is_a_command(self):
        for cmd in (f"ssh -o RemoteCommand='{GH_MERGE} 292' host",
                    f"ssh -oRemoteCommand='{GH_MERGE} 292' host",
                    "ssh -o RemoteCommand='git push origin main' host"):
            with self.subTest(cmd=cmd):
                self.assertTrue(gate._find_publish_subcmds(cmd), cmd)

    def test_the_destination_is_found_past_valued_options(self):
        for cmd in (f"ssh -p 2222 host {GH_MERGE} 292",
                    f"ssh -i /keys/git host {GH_MERGE} 292",
                    f"ssh -l git -p 22 host {GH_MERGE} 292",
                    f"ssh host {GH_MERGE} 292"):
            with self.subTest(cmd=cmd):
                self.assertTrue(gate._find_publish_subcmds(cmd), cmd)

    def test_ssh_that_runs_nothing_publishing_stays_benign(self):
        for cmd in ("ssh -o StrictHostKeyChecking=no host uptime",
                    "ssh -p 2222 host 'git status --short'",
                    "ssh host"):
            with self.subTest(cmd=cmd):
                self.assertEqual([], gate._find_publish_subcmds(cmd), cmd)


class TestTheDepthCapDoesNotEatAnApprovableMerge(_GateRunner, unittest.TestCase):
    """QA cycle 4, M52 (cap 5 → 1) survived both legs: nothing asserted that a
    merge nested INSIDE the cap resolves to its PR number instead of the depth
    deny. The cap has two edges and only the far one was pinned."""

    def test_an_approved_merge_two_to_four_shells_deep_is_approved(self):
        for depth in (2, 3, 4):
            with self.subTest(depth=depth):
                self._allow(_nest(depth, f"{GH_MERGE} 292"),
                            {"OCTO_MERGE_APPROVE": "292", "OCTO_QA_OK": "1"})

    def test_an_unapproved_merge_inside_the_cap_denies_by_PR_NUMBER_not_by_depth(self):
        for depth in (2, 3, 4):
            with self.subTest(depth=depth):
                rc, err = self._run(_nest(depth, f"{GH_MERGE} 292"), {})
                self.assertEqual(2, rc, err)
                self.assertIn("PR #292", err)
                self.assertNotIn("nests shells deeper", err)

    def test_benign_nesting_inside_the_cap_is_not_a_depth_deny(self):
        for depth in (2, 3, 4):
            with self.subTest(depth=depth):
                self._allow(_nest(depth, "gh pr view 292 --json state"))


class TestTheParseFitsTheHookBudget(unittest.TestCase):
    """`hooks.json` gives this gate 5 seconds, and a hook that is killed writes no
    stdout, which the harness reads as ALLOW — a timeout is a bypass with a
    stopwatch. Three quadratics were inherited from the parent and measured
    against that budget on 2026-09-08:

      * `_peel_candidates` built and joined a tail LIST for every token, head or
        not: 20000 benign words took 39.7 s.
      * `_api_write_action` ran a 1.7 ms regex per CANDIDATE, and an opaque head
        synthesizes one `curl` candidate per token: 5000 `$a` tokens took 45.5 s.
      * `_split_heredocs` scanned every remaining line per `<<WORD`: 2000
        unterminated openers took 3.6 s.

    Asserted against the real budget rather than against a ratio, because the
    contract is "finishes inside 5 s".

    On FENCE SIZE, which is the whole design of this class. Two of these shapes
    are superlinear and bounded rather than eliminated, so each has a measured
    EDGE — the size at which it reaches 5 s — and the fence deliberately does not
    sit there. A fence at the edge is red the first time the box is busy, and a
    fence that goes red under normal agent load gets deleted, which is strictly
    worse than no fence. So every leg is sized at roughly a THIRD of the budget
    on a BUSY box, and what it therefore catches is a regression of about 3x or
    more in the cost of that shape, not the last 20% before the edge. The edges
    themselves are measurements recorded in residual 9, not assertions; do not
    read a green run here as "the shape is 5 s-safe at any size".

Sized against a LOADED box on purpose, not a quiet one, because that is
    the box a fence has to survive. Re-measured 2026-09-08 on 4 cores across
    load averages 8 to 20 (2x to 5x oversubscribed, five sibling agents), worst
    observed over eight rounds reported: 20000 benign words 1.01 s, 5000 opaque
    tokens well under, 2000 `<<` openers well under, 1500 opaque/write-marker
    pairs 0.84 s (edge 3500), 3500 `$(…)` substitutions 1.86 s (edge ~6000).
    Both bounded legs take a min of 5 for the reason in `_under_budget`: at a
    min of 3 the substitution shape returned 2.87 s once at load 19.6, and not
    as one unlucky sample but as three consecutive slow ones. The module ran
    green at load 18.1, 19.0 and 20.1, which is the evidence that these are
    sized and not tuned to a quiet box.
    """

    BUDGET = 5.0

    def _under_budget(self, label: str, cmd: str, runs: int = 1):
        """Best of *runs*, because the number that matters is the cost of the
        PARSE and not the cost of whatever else the box was doing during one
        sample. The spread is not small and it is not noise around a mean: one
        substitution line measured 0.69 s to 1.27 s over six single runs at load
        12, and a min of THREE still returned 2.87 s at load 19.6, as three
        consecutive slow samples rather than one unlucky one. A min of five over
        eight rounds stays inside 1.86 s on a shape 40% larger. So `runs` is 5
        for the two bounded shapes, which are sized closest to the budget, and
        stays 1 for the legs with a 5x-90x margin, where no spread this box
        produces can reach 5 s."""
        import time
        spent = float("inf")
        for _ in range(runs):
            for cache in ("_PARTS_CACHE", "_ENV_CHAIN_CACHE", "_TOKENS_CACHE",
                          "_ARG_TOKENS_CACHE"):
                getattr(gate, cache, {}).clear()
            start = time.monotonic()
            gate._find_publish_subcmds(cmd)
            spent = min(spent, time.monotonic() - start)
        self.assertLess(spent, self.BUDGET,
                        f"{label} took {spent:.1f}s of a {self.BUDGET}s hook budget")

    def test_a_long_benign_word_list_parses_inside_the_budget(self):
        self._under_budget("20000 benign words", " ".join(["word"] * 20000))

    def test_a_long_opaque_head_line_parses_inside_the_budget(self):
        self._under_budget("5000 opaque tokens", "git " + " ".join(["$a"] * 5000))
        # 1500 pairs, not the 1000 this shipped with. Residual 9 measures the
        # EDGE of this shape at 3500 pairs (4.99 s), and a fence three and a
        # half times under the regime it claims to defend defends nothing that
        # will ever happen. Raised TOWARD the edge and not TO it, and 1500
        # rather than the 2000 tried first, because the ceiling is the busy box:
        # at load 17, 3500 pairs is 4.07 s and 2000 is 3.47 s, a 1.4x margin
        # that goes red on any hotter box. 1500 is 0.84 s worst of eight
        # min-of-5 rounds across loads 10-20, a 6x margin, and still catches the
        # 3x-and-up regression this class is for.
        self._under_budget("1500 opaque-token/write-marker pairs",
                           "git " + " ".join(["$a -f"] * 1500), runs=5)

    def test_a_long_command_substitution_line_parses_inside_the_budget(self):
        """The cost this cycle INTRODUCED, and until now the one cost in
        residual 9 with no regression fence at all: reading the contents of
        every `$(…)` runs each one through the whole recursion, so a line of N
        substitutions naming a head is N parses. Residual 9 measured the curve
        (0.56 s at 1000, 3.05 s at 4000, roughly 6000 to reach the budget) and
        then said it was "pinned", which it was not — no leg in this class
        carried a `$(` at all. Measured is not fenced, and a residual written to
        be honest is the last place to blur the two.

        Sized at 3500, against an edge of roughly 6000, and the size is a TRADE
        made in this direction on purpose. 2000 and 2500 were both measured
        first and both dropped: they are quieter (worst of eight rounds 1.09 s
        at 2500 against 1.86 s at 3500) but the regression below stays GREEN at
        both, and a fence that cannot fail is the thing this PR keeps finding in
        other people's code. So headroom was spent, not hoarded, down to a 2.7x
        margin — still three times the 1.2x a fence at the edge would have, and
        green through eight rounds and three whole-module runs at loads 8 to 20.

        FAILABILITY, run rather than asserted, and reported with the runs that
        did NOT go red as well. Revert the one line in `_line_env_chain` that
        reads three keys back to the whole-process walk it replaced — the cost
        this recursion exposed and paid down, and the regression this leg most
        plausibly has to catch — copy the tree, and run THIS test against the
        copy in a shell of 491 variables. It goes RED: 5.44 s of the 5 s budget
        against 1.33 s for the fix, same box, same load. It also came back GREEN
        twice on the same revert, at 4.04 s and at 4.6 s, when the box was
        quieter.

        That straddle is the honest limit of a wall-clock budget assertion and
        it is worth stating plainly rather than quoting only the red run. The
        revert costs a steady 4x-6x, but this box's own throughput swings about
        3x between load 8 and load 20, so a fixed 5 s line falls inside the
        regression's range instead of below it: the leg catches this regression
        at the loads where it crosses 5 s, and 5 s is the contract, so that is
        the right thing for it to measure. What it does NOT do is detect every
        regression at every load, and a green run here is not proof that no
        constant-factor cost was added — on the 91-variable environment of this
        session the same revert is 2.33 s against 1.34 s, a real 1.7x that stays
        green at any size that keeps the fixed side sane. The env-size
        dependence is the point: the three-key read is what makes this parse
        cost the same in a fat shell as in a lean one, and a fat shell is where
        the revert crosses."""
        self._under_budget("3500 $(…) substitutions naming a head",
                           " ".join(f"$(gh pr merge {i})" for i in range(3500)),
                           runs=5)

    def test_many_unterminated_heredoc_openers_parse_inside_the_budget(self):
        self._under_budget("2000 << openers",
                           "\n".join(f"echo 'a << T{i}'" for i in range(2000)))

    def test_the_heredoc_terminator_scan_is_not_quadratic(self):
        """Pinned on `_split_heredocs` alone, and at 8000 lines, because the
        whole-parse budget test could not tell: the terminator scan cost 0.57 s
        at 2000 lines and the 5 s budget swallowed it, so reverting the fix left
        the anchor green. On its own it is a clean quadratic — 0.57 s / 2.10 s /
        9.17 s at 2000 / 4000 / 8000 — against 0.00 / 0.01 / 0.03 with the index.
        One second at 8000 is a 30x margin on the fix and a clear failure without
        it."""
        import time
        cmd = "\n".join(f"echo 'a << T{i}'" for i in range(8000))
        start = time.monotonic()
        gate._split_heredocs(cmd)
        spent = time.monotonic() - start
        self.assertLess(spent, 1.0,
                        f"_split_heredocs took {spent:.1f}s on 8000 openers")

    def test_the_alias_form_test_short_circuits_before_its_lazy_regexes(self):
        """`_PAT_GIT_CONFIG_ALIAS` and `_PAT_GIT_C_ALIAS_DEF` both carry a lazy
        `[^|&;]*?` run that backtracks across the whole sub-command, and
        `_normalize` asks this question once per CANDIDATE. Both patterns REQUIRE
        the word `alias`, so a C-level substring test decides it first.

        Pinned on the function and at 200 calls because the whole-parse budget
        test could not tell at 5000 tokens: the other fixes absorbed it and the
        anchor stayed green through a revert. On its own it is 0.004 s fixed
        against 1.282 s reverted, on the same 36 KB string."""
        import time
        sub = "git " + " ".join(["$a"] * 12000)
        start = time.monotonic()
        for _ in range(200):
            gate._alias_definition_form(sub)
        spent = time.monotonic() - start
        self.assertLess(spent, 0.2,
                        f"200 _alias_definition_form calls took {spent:.2f}s")
        # and it still SAYS yes when the line really does define one
        self.assertTrue(gate._alias_definition_form(
            "git config alias.pm 'push origin main'"))

    def test_the_heredoc_index_still_finds_the_right_terminator(self):
        """The index replaced a linear scan from the CURRENT position, so it has
        to keep that: the first terminator at or past the opener, never an
        earlier line that happens to carry the same word."""
        cmd = "EOF\nbash <<EOF\ngh pr merge 292\nEOF\necho done"
        body_cmd, bodies = gate._split_heredocs(cmd)
        self.assertEqual([("bash <<EOF", "gh pr merge 292")], bodies)
        self.assertEqual(["gh"], [f for _s, f in gate._find_publish_subcmds(cmd)])

    def test_two_heredocs_on_one_line_keep_their_own_bodies(self):
        cmd = "cat <<A <<B\nfirst\nA\nsecond\nB"
        _body, bodies = gate._split_heredocs(cmd)
        self.assertEqual([("cat <<A <<B", "first"), ("cat <<A <<B", "second")],
                         bodies)

    def test_the_merge_at_the_end_of_a_long_line_is_still_found(self):
        cmd = " ".join(["word"] * 20000) + " ; " + f"{GH_MERGE} 292"
        self.assertEqual(["gh"], [f for _s, f in gate._find_publish_subcmds(cmd)])

    def test_the_curl_candidate_bound_keeps_a_real_api_write(self):
        # the bound drops synthesized `curl` heads PAST the last write marker;
        # a real one, and an opaque head in front of one, must survive it.
        self.assertTrue(gate._find_publish_subcmds(
            "curl -X PUT https://api.github.com/repos/o/r/pulls/280/merge"))
        self.assertTrue(gate._find_publish_subcmds(
            "$TOOL -X PUT https://api.github.com/repos/o/r/pulls/280/merge"))
