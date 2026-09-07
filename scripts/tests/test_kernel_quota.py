#!/usr/bin/env python3
"""Anchors for the v8 kernel PROCESS quota (scripts/g__pretool__kernel.py, Phase 3).

What is pinned here is the behaviour a cap has to have to be trustworthy in
both directions: the shipped default enforces NOTHING (a fresh clone must not
start refusing tool calls), a configured cap refuses the call after it, the
minutes cap is read off `start_ts`, a QA type multiplies its caps instead of
escaping them, the gitignored occupant overrides the tracked slot key by key,
and a malformed occupant degrades to the defaults with a note rather than
denying. A quota that could stop work by being misconfigured would be a worse
failure than no quota.

Every test runs the real gate as a subprocess against a sandbox HOME, the way
the harness runs it. Timing is never asserted (v8-kernel.md section 3).
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
ROOT = SCRIPTS.parent
GATE = SCRIPTS / "g__pretool__kernel.py"
sys.path.insert(0, str(SCRIPTS))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gate = _load("g_pretool_kernel", GATE)


class QuotaBase(unittest.TestCase):
    """A sandbox HOME per test, plus the two helpers every test needs: write an
    occupant, and make one tool call as the harness would."""

    def setUp(self) -> None:
        self.home = Path(tempfile.mkdtemp(prefix="kernel-quota-test-"))
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)

    def write_occupant(self, text) -> None:
        cfg = self.home / ".claude" / "company" / "config"
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / "kernel.json").write_text(
            text if isinstance(text, str) else json.dumps(text), encoding="utf-8")

    def write_ptable(self, rows: dict) -> None:
        kd = self.home / ".claude" / ".cache" / "kernel"
        kd.mkdir(parents=True, exist_ok=True)
        (kd / "ptable.json").write_text(
            json.dumps({"version": 1, "processes": rows}), encoding="utf-8")

    def call(self, pid: str = "child", subagent: bool = True, n: int = 1) -> tuple:
        """n tool calls; returns (denied_indexes, last stdout)."""
        env = dict(os.environ)
        env["HOME"] = str(self.home)
        env["USERPROFILE"] = str(self.home)
        env["CLAUDE_SESSION_ID"] = "__test__"
        env.pop("OCTO_KERNEL_OPEN", None)
        denied, out = [], ""
        for i in range(n):
            payload = {"session_id": "sid" if subagent else pid,
                       "tool_name": "Read", "tool_use_id": f"t{i}",
                       "tool_input": {"i": i}, "cwd": str(self.home)}
            if subagent:
                payload["agent_id"] = pid
            cp = subprocess.run([sys.executable, str(GATE)], input=json.dumps(payload),
                                capture_output=True, text=True, cwd=str(self.home),
                                env=env, timeout=60)
            out = cp.stdout.strip()
            if out:
                denied.append(i)
        return denied, out

    def journal(self, pid: str) -> list:
        path = self.home / ".claude" / ".cache" / "kernel" / "journal" / f"{pid}.jsonl"
        if not path.exists():
            return []
        return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]

    def seed_journal(self, pid: str, lines: int, age_seconds: float = 0.0,
                     ptype: str = "") -> None:
        """A journal with `lines` tool lines whose start_ts is `age_seconds` ago."""
        import time
        env_home = os.environ.get("HOME")
        os.environ["HOME"] = str(self.home)
        os.environ["USERPROFILE"] = str(self.home)
        try:
            for mod in ("kernel_proc",):
                sys.modules.pop(mod, None)
            import kernel_proc
            ts = time.time() - age_seconds
            kernel_proc.append(pid, {"kind": "start", "ts": ts, "start_ts": ts,
                                     "type": ptype})
            for i in range(lines):
                kernel_proc.append(pid, {"kind": "tool", "ts": ts + 0.001 * i,
                                         "tool_name": "Read", "tool_use_id": f"s{i}"})
        finally:
            if env_home is not None:
                os.environ["HOME"] = env_home


class TestDefaultsUnlimited(QuotaBase):
    def test_no_occupant_allows_a_thousand_calls(self):
        """The shipped default is 0 = unlimited, and 0 must never be read as
        'a cap of zero'. A clone that started refusing on call 1 would be the
        single worst way to ship this feature."""
        denied, _ = self.call(n=60)
        self.assertEqual(denied, [])
        # and the arithmetic itself, at a volume a subprocess loop cannot reach
        policy = {"subagent": {"max_tool_calls": 0, "max_minutes": 0},
                  "qa_multiplier": 3, "qa_agent_types_regex": "(qa)"}
        self.assertEqual(gate.breach(policy, "subagent", 1000, 10000.0, ""), "")


class TestCallCap(QuotaBase):
    def test_cap_five_denies_the_sixth_call(self):
        self.write_occupant({"subagent": {"max_tool_calls": 5}})
        denied, out = self.call(n=6)
        self.assertEqual(denied, [5], f"expected only call 6 refused, got {denied}")
        self.assertIn("max_tool_calls 5", out)
        self.assertIn("KERNEL QUOTA", out)

    def test_quota_line_journaled_once_per_refused_call(self):
        """One `quota` line per REFUSED call, not one per breach: a refused call
        is a call that happened, and Phase 4 replays each of them. Five calls
        under a cap of 3 leave two refusals and two quota lines, each pairing
        with the tool line that earned it."""
        self.write_occupant({"subagent": {"max_tool_calls": 3}})
        denied, _ = self.call(n=5)
        self.assertEqual(denied, [3, 4])
        kinds = [l["kind"] for l in self.journal("child")]
        self.assertEqual(kinds.count("quota"), 2)
        self.assertEqual(kinds.count("tool"), 5, "a refused call is still journaled")

    def test_cap_counts_journal_lines_not_only_tool_lines(self):
        """Documented honestly in registry/kernel.yaml: `seq` counts the `start`
        line too, so a registered process reaches its cap one call earlier. The
        test exists so nobody later 'fixes' the off-by-one into a full journal
        read on the hot path."""
        self.write_occupant({"subagent": {"max_tool_calls": 4}})
        self.seed_journal("child", 0)          # a `start` line and nothing else
        denied, _ = self.call(n=4)
        self.assertEqual(denied, [3])


class TestMinutesCap(QuotaBase):
    def test_elapsed_wall_time_over_the_cap_denies(self):
        self.write_occupant({"subagent": {"max_minutes": 30}})
        self.seed_journal("child", 2, age_seconds=45 * 60)
        denied, out = self.call(n=1)
        self.assertEqual(denied, [0])
        self.assertIn("max_minutes 30", out)

    def test_elapsed_wall_time_under_the_cap_allows(self):
        self.write_occupant({"subagent": {"max_minutes": 30}})
        self.seed_journal("child", 2, age_seconds=5 * 60)
        self.assertEqual(self.call(n=1)[0], [])


class TestQaMultiplier(QuotaBase):
    def test_qa_type_gets_three_times_the_cap(self):
        self.write_occupant({"subagent": {"max_tool_calls": 5}, "qa_multiplier": 3})
        self.write_ptable({"child": {"pid": "child", "type": "Reality Checker"}})
        self.assertEqual(self.call(n=15)[0], [], "5 x 3 leaves room for 15 calls")

    def test_qa_type_is_multiplied_not_exempted(self):
        self.write_occupant({"subagent": {"max_tool_calls": 5}, "qa_multiplier": 3})
        self.write_ptable({"child": {"pid": "child", "type": "Evidence Collector"}})
        denied, out = self.call(n=16)
        self.assertEqual(denied, [15])
        self.assertIn("qa_multiplier 3", out)

    def test_a_non_qa_type_gets_no_headroom(self):
        self.write_occupant({"subagent": {"max_tool_calls": 5}, "qa_multiplier": 3})
        self.write_ptable({"child": {"pid": "child", "type": "Rapid Prototyper"}})
        self.assertEqual(self.call(n=6)[0], [5])

    def test_regex_matches_the_receipt_ledger_definition(self):
        """One definition of 'this is QA' across the brain. If the ledger's
        regex moves and this one does not, a persona the ledger trusts for a
        merge receipt silently loses its quota headroom."""
        import receipt_ledger
        self.assertEqual(gate.DEFAULTS["qa_agent_types_regex"],
                         receipt_ledger.QA_AGENT_TYPE.pattern)
        slot = (ROOT / "registry" / "kernel.yaml").read_text(encoding="utf-8")
        self.assertIn(receipt_ledger.QA_AGENT_TYPE.pattern, slot)


class TestOccupantOverridesSlot(QuotaBase):
    def test_occupant_wins_key_by_key(self):
        self.write_occupant({"subagent": {"max_tool_calls": 7}})
        os.environ["HOME"] = str(self.home)
        policy, notes = gate.load_policy()
        self.assertEqual(notes, [])
        self.assertEqual(policy["subagent"]["max_tool_calls"], 7)
        # untouched keys keep the tracked slot's value
        self.assertEqual(policy["subagent"]["max_minutes"], 0)
        self.assertEqual(policy["qa_agent_types_regex"],
                         gate.DEFAULTS["qa_agent_types_regex"])

    def test_tier_is_chosen_by_the_payload(self):
        """agent_id present = subagent, absent = main. Capping the wrong tier
        would either halt the operator's own session or cap nothing."""
        self.write_occupant({"subagent": {"max_tool_calls": 2}, "main": {"max_tool_calls": 0}})
        self.assertEqual(self.call(pid="mainloop", subagent=False, n=6)[0], [])
        self.assertEqual(self.call(pid="kid", subagent=True, n=3)[0], [2])


class TestMalformedNeverDenies(QuotaBase):
    def test_unparseable_occupant_falls_back_with_a_note(self):
        self.write_occupant("{ this is not json")
        os.environ["HOME"] = str(self.home)
        policy, notes = gate.load_policy()
        self.assertTrue(notes, "a malformed occupant must produce a note")
        self.assertEqual(policy["subagent"]["max_tool_calls"], 0)
        self.assertEqual(self.call(n=5)[0], [], "a broken quota file never denies")

    def test_bad_cap_value_keeps_the_default_and_notes_the_key(self):
        self.write_occupant({"subagent": {"max_tool_calls": "lots"}})
        os.environ["HOME"] = str(self.home)
        policy, notes = gate.load_policy()
        self.assertEqual(policy["subagent"]["max_tool_calls"], 0)
        self.assertTrue(any("max_tool_calls" in n for n in notes))
        self.assertEqual(self.call(n=4)[0], [])

    def test_negative_cap_is_read_as_unlimited(self):
        self.write_occupant({"subagent": {"max_tool_calls": -5}})
        os.environ["HOME"] = str(self.home)
        policy, _ = gate.load_policy()
        self.assertEqual(policy["subagent"]["max_tool_calls"], 0)


class TestExitPrecedence(QuotaBase):
    """quota > error > ok. A capped process usually stops mid-task and phrases
    its last message as prose, so reading that prose alone would record the
    symptom (or worse, an `ok`) for a run the kernel itself stopped."""

    def test_quota_outranks_a_clean_last_message(self):
        exit_hook = _load("proc_exit", SCRIPTS / "r__subagent-stop__proc-exit.py")
        self.assertEqual(exit_hook.status_of("all done, report follows", True), "quota")
        self.assertEqual(exit_hook.status_of("Error: boom", True), "quota")
        self.assertEqual(exit_hook.status_of("Error: boom", False), "error")
        self.assertEqual(exit_hook.status_of("all done", False), "ok")
        self.assertEqual(exit_hook.status_of("", False), "error")

    def test_end_to_end_capped_child_exits_quota(self):
        self.write_occupant({"subagent": {"max_tool_calls": 2}})
        self.assertEqual(self.call(pid="kid", n=3)[0], [2])
        env = dict(os.environ)
        env["HOME"] = str(self.home)
        env["USERPROFILE"] = str(self.home)
        subprocess.run([sys.executable, str(SCRIPTS / "r__subagent-stop__proc-exit.py")],
                       input=json.dumps({"session_id": "sid", "agent_id": "kid",
                                         "agent_type": "general-purpose",
                                         "last_assistant_message": "here is my report"}),
                       capture_output=True, text=True, cwd=str(self.home), env=env,
                       timeout=60)
        exits = [l for l in self.journal("kid") if l["kind"] == "exit"]
        self.assertEqual(len(exits), 1)
        self.assertEqual(exits[0]["status"], "quota")
        self.assertFalse(exits[0]["ok"])


class TestMiniYaml(unittest.TestCase):
    """The hot path reads registry/kernel.yaml with a 12-line scalar parser, so
    that reader has to agree with the real one on the real file."""

    def test_agrees_with_pyyaml_on_the_tracked_slot(self):
        text = (ROOT / "registry" / "kernel.yaml").read_text(encoding="utf-8")
        mini = gate.mini_yaml(text)
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML absent")
        real = yaml.safe_load(text)
        for tier in ("subagent", "main"):
            self.assertEqual(mini[tier], real[tier])
        self.assertEqual(mini["qa_multiplier"], real["qa_multiplier"])
        self.assertEqual(mini["qa_agent_types_regex"], real["qa_agent_types_regex"])

    def test_strips_trailing_comments_and_keeps_quoted_regex(self):
        parsed = gate.mini_yaml('subagent:\n  max_tool_calls: 12   # twelve\n'
                                'qa_agent_types_regex: "(qa|review)"  \n')
        self.assertEqual(parsed["subagent"]["max_tool_calls"], 12)
        self.assertEqual(parsed["qa_agent_types_regex"], "(qa|review)")


if __name__ == "__main__":
    unittest.main()
