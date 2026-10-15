#!/usr/bin/env python3
"""Tests for `runtime_census.py --gates` (T08): the offline leg and the pieces of
the live leg that need no model. No network, no harness binary, temp dirs only.

    python3 -m unittest scripts.tests.test_runtime_census_gates
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
BRAIN = SCRIPTS.parent


def _load():
    spec = importlib.util.spec_from_file_location("runtime_census_gates_t", SCRIPTS / "runtime_census.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rc = _load()
SECRETS_LOC = ["scripts/secrets-grep-guard.py", "--selftest", "registry/fixtures/SECURITY.baseline"]
QUOTA_LOC = ["scripts/g__pretool__kernel.py", "--selftest", "registry/fixtures/FLOW.kernel-quota"]


class OfflineLegTest(unittest.TestCase):
    def test_projected_gates_match_the_projector_on_both_harnesses(self):
        for h in rc.HARNESSES:
            gates = rc.projected_gates(h)
            self.assertIn("g__pretool__arming-surface.py", gates)
            for gate, matcher in gates.items():
                self.assertTrue(matcher.startswith("^(") and matcher.endswith(")$"), matcher)
                self.assertTrue((SCRIPTS / gate).is_file(), gate)

    def test_every_projected_gate_has_a_selftest_locator(self):
        for gate in rc.projected_gates("codex"):
            self.assertTrue(rc.selftest_locators(gate), gate)

    def test_a_gate_selftest_passes_with_every_leg_through_the_shim(self):
        for h in rc.HARNESSES:
            run = rc.run_selftest_through_shim(h, "secrets-grep-guard.py",
                                               rc.projected_gates(h)["secrets-grep-guard.py"],
                                               SECRETS_LOC)
            self.assertEqual(run["result"], "pass", run)
            self.assertEqual(run["legs_through_shim"]["shim_denied"], 1)
            self.assertEqual(run["legs_through_shim"]["shim_allowed"], 1)
            self.assertEqual(run["legs_through_shim"]["shim_untranslatable"], 0)

    def test_a_projection_that_misses_the_tool_fails_the_violation_leg(self):
        # The harness would not run the hook for an unmatched tool: an allow, so
        # the gate's own violation leg must fail. A gap in the projection is
        # never reported as a pass.
        run = rc.run_selftest_through_shim("codex", "secrets-grep-guard.py",
                                           "^(nothing_matches)$", SECRETS_LOC)
        self.assertEqual(run["result"], "fail")
        self.assertEqual(sum(run["legs_through_shim"].values()), 0)
        self.assertTrue(run["legs_not_matched_by_projection"])

    def test_a_selftest_with_no_harness_tool_is_not_routed_not_passed(self):
        run = rc.run_selftest_through_shim("gemini", "g__pretool__kernel.py",
                                           rc.projected_gates("gemini")["g__pretool__kernel.py"],
                                           QUOTA_LOC)
        self.assertEqual(run["result"], "not_routed")
        self.assertEqual(sum(run["legs_through_shim"].values()), 0)

    def test_offline_leg_is_deterministic_and_carries_no_temp_or_home_path(self):
        a = rc.gates_offline("codex", only=["secrets-grep-guard.py"])
        b = rc.gates_offline("codex", only=["secrets-grep-guard.py"])
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
        text = json.dumps(a)
        self.assertNotIn(os.path.expanduser("~"), text)
        self.assertNotIn(tempfile.gettempdir() + "/", text)
        self.assertEqual(a["result"], "pass")

    def test_subprocess_run_is_restored_after_a_selftest(self):
        real = subprocess.run
        rc.run_selftest_through_shim("codex", "secrets-grep-guard.py", "^(Bash)$", SECRETS_LOC)
        self.assertIs(subprocess.run, real)

    def test_the_offline_leg_never_marks_the_live_registry_supported(self):
        shim = rc._shim()
        rc.gates_offline("gemini", only=["secrets-grep-guard.py"])
        for hid in ("gemini-cli", "codex-cli"):
            self.assertEqual(shim.registry_status(hid), "gap")
            code, msg = shim.decide(hid, "secrets-grep-guard.py", "{}")
            self.assertEqual(code, 2)
            self.assertIn("refused", msg)

    def test_record_carries_gates_and_live_block_forward(self):
        gates = rc.gates_offline("codex", only=["secrets-grep-guard.py"])
        live_block = {"measured": "2026-01-01T00:00:00Z", "outcome": "ran", "reason": "exit 0",
                      "classes": {c: {"harness_blocked_violation": True,
                                      "harness_allowed_benign": True,
                                      "violation_evidence": "t", "benign_evidence": "t"}
                                  for c in ("shell", "file_write", "file_edit")}}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            rec = rc.build_record("codex", None, None, gates=gates, live_block=live_block)
            rc.write_record("codex", rec, out)
            first = (out / "codex.json").read_bytes()
            self.assertEqual(rc.main(["--out", str(out), "--harness", "codex"]), 0)
            self.assertEqual(first, (out / "codex.json").read_bytes())
            data = json.loads(first)
            self.assertEqual(data["status"], "measured")
            self.assertTrue(data["tool_classes"]["shell"]["harness_blocked_violation"])
            self.assertIsNone(data["tool_classes"]["mcp"]["harness_blocked_violation"])
            self.assertEqual(data["tool_classes"]["shell"]["shim_selftest_legs"]["denied"],
                             gates["summary"]["shim_denied"])


class LiveLegPiecesTest(unittest.TestCase):
    def _targets(self, tmp):
        home, work = os.path.join(tmp, "home"), os.path.join(tmp, "work")
        os.makedirs(os.path.join(home, ".claude"))
        os.makedirs(work)
        targets = rc._live_targets(home, work)
        rc._seed_targets(targets)
        return home, work, targets

    def test_judge_needs_the_file_and_a_journaled_deny_from_the_harness(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, work, t = self._targets(tmp)
            for cls in ("shell", "file_write"):
                with open(t[cls]["benign"], "w", encoding="utf-8") as fh:
                    fh.write("{}\n")
            with open(t["file_edit"]["violation"], "w", encoding="utf-8") as fh:
                fh.write('{"census": 2}\n')
            denies = [{"verb": "Bash", "target": t["shell"]["violation"], "session": "s1"},
                      # the precheck's own deny must not count
                      {"verb": "Write", "target": t["file_write"]["violation"],
                       "session": rc._PRECHECK_SESSION}]
            got = rc.judge_live(t, denies, rc._after(t))
            self.assertIs(got["shell"]["harness_blocked_violation"], True)
            self.assertIs(got["shell"]["harness_allowed_benign"], True)
            self.assertIsNone(got["file_write"]["harness_blocked_violation"])
            self.assertIs(got["file_edit"]["harness_blocked_violation"], False)
            self.assertIsNone(got["file_edit"]["harness_allowed_benign"])

    def test_a_deny_for_the_wrong_tool_class_is_not_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            _home, _work, t = self._targets(tmp)
            denies = [{"verb": "Bash", "target": t["file_write"]["violation"], "session": "s1"}]
            got = rc.judge_live(t, denies, rc._after(t))
            self.assertIsNone(got["file_write"]["harness_blocked_violation"])

    def test_sandbox_brain_flips_only_the_copy(self):
        shim = rc._shim()
        with tempfile.TemporaryDirectory() as tmp:
            sd = rc.build_sandbox_brain(tmp, "codex")
            reg = os.path.join(os.path.dirname(sd), "registry", "runtimes.yaml")
            self.assertEqual(shim.registry_status("codex-cli", reg), "supported")
            self.assertEqual(shim.registry_status("gemini-cli", reg), "gap")
            self.assertFalse(os.path.isdir(os.path.join(os.path.dirname(sd), "registry", "fixtures")))
        self.assertEqual(shim.registry_status("codex-cli"), "gap")

    def test_precheck_blocks_violations_allows_twins_and_leaves_no_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, work, t = self._targets(tmp)
            sd = rc.build_sandbox_brain(tmp, "gemini")
            got = rc._precheck("gemini", sd, rc._live_env(home), t, work)
            for cls in ("shell", "file_write", "file_edit"):
                self.assertEqual(got[f"{cls}:violation"], "blocked")
                self.assertEqual(got[f"{cls}:benign"], "allowed")
            self.assertEqual(rc._journal_denies(home), [])

    def test_codex_hooks_override_is_toml_with_the_projected_command(self):
        groups = rc.live_hook_groups("codex", "/opt/x/scripts")
        cfg = rc.codex_hooks_override(groups)
        key, value = cfg.split("=", 1)
        doc = tomllib.loads(f"v = {value}")
        self.assertEqual(key, "hooks.PreToolUse")
        hook = doc["v"][0]["hooks"][0]
        self.assertEqual(hook["command"], "python3 /opt/x/scripts/g__shim__hook.py --harness "
                                          "codex-cli --gate g__pretool__arming-surface.py")
        self.assertEqual(hook["timeout"], 60)

    def test_empty_write_renders_a_patch_the_shim_reads(self):
        shim = rc._shim()
        payload = rc.render_codex({"tool_name": "Write", "cwd": "/w",
                                   "tool_input": {"file_path": "/w/empty.md"}})
        calls = shim.translate("codex-cli", json.dumps(payload))
        self.assertEqual(calls[0]["tool_name"], "Write")
        self.assertEqual(calls[0]["tool_input"]["content"], "")

    def test_a_429_status_wins_over_an_unavailable_word(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = rc._run([sys.executable, "-c",
                         "import sys; sys.stderr.write('UNAVAILABLE x\\nstatus: 429\\n'); sys.exit(1)"],
                        tmp, dict(os.environ))
            self.assertTrue(r["reason"].startswith("429"), r["reason"])


if __name__ == "__main__":
    unittest.main()
