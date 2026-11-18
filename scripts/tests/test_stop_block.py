#!/usr/bin/env python3
"""Tests for scripts/stop_block.py and every blocking Stop gate that uses it.

Pins, for each JSON-block Stop gate in hooks.json, on its own violation
fixtures (registry/fixtures/<rule>/violation*.json):
  (a) the reason the harness prints is ONE line under stop_block.WORD_CAP words;
  (b) the detail file that line names holds the gate's FULL text, byte for byte
      the reason the gate prints when the ledger is unavailable;
  (c) when the ledger cannot be written, the gate prints that FULL reason.
The reply panel (exit 2 + stderr) is pinned the same way by its own --selftest
(a, b) and by the fallback case below (c). Also pins that every blocking Stop
gate listed in hooks.json is covered here, so a new gate cannot skip the split.

Stdlib only:

    python3 -m unittest scripts.tests.test_stop_block
"""
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
FIX = ROOT / "registry" / "fixtures"
sys.path.insert(0, str(SCRIPTS))

import friction_ledger  # noqa: E402
import gate_selftest  # noqa: E402
import stop_block  # noqa: E402

# JSON-block Stop gates and one fixture dir each (the rules.yaml selftest locator)
GATES = {
    "cadence-stop-hook.py": "COMMS.human-cadence",
    "g__stop__draft-promise.py": "COMMS.deliverable-complete-before-send",
    "g__stop__unsourced-attribute.py": "COMMS.unsourced-attribute",
    "g__stop__unsourced-absence.py": "COMMS.unsourced-absence",
    "g__stop__paste-ready-raw.py": "COMMS.paste-ready-raw-message",
    "g__stop__defer-today.py": "FLOW.do-it-today",
    "g__stop__no-menu-question.py": "COMMS.no-menu-question",
    "g__stop__diagram-first.py": "COMMS.diagram-first",
    "source-attribution-check.py": "CODE.cite-sources",
    "claim-verify-stop.py": "CODE.adversarial-verify-operator",
    "g__stop__delegation-audit.py": "FLOW.bulk-fetch-delegation",
    "d__stop__wa-guardia.py": "FLOW.wa-guardia-on-pending",
    "g__stop__goal-anchor.py": "FLOW.root-goal-anchor",
}
EXIT2_GATES = {"g__stop__reply-panel.py"}
# Stop hooks that never block (advisory, tracing, ledgers)
NON_BLOCKING = {"trace-hook.py", "no-pause-suggestion.py", "grafo-ledger-check.py",
                "r__stop__friction-ledger.py"}
SEP = " · detail: "
# gates with no row in registry/friction-signatures.json (before and after)
NO_SIGNATURE = {"g__stop__draft-promise.py", "g__stop__paste-ready-raw.py"}


def _reasons(script: str, fixture: str, broken_ledger: bool) -> list:
    """The printed reason of every violation leg, in the selftest's own order
    and sandbox discipline (one shared sandbox, seeded from the fixture home)."""
    fdir = FIX / fixture
    if script == "d__stop__wa-guardia.py":
        # its chat databases are derived, timed relative to now, and seeded by
        # its own --selftest; seed them the same way before the legs run
        import importlib.util
        spec = importlib.util.spec_from_file_location("_wag", SCRIPTS / script)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod._siembra_bases(fdir.resolve())
    sandbox = Path(tempfile.mkdtemp(prefix="stop-block-test-"))
    old = os.environ.get("OCTO_STOP_BLOCK_DIR")
    try:
        seed = fdir / "home"
        if seed.is_dir():
            shutil.copytree(seed, sandbox, dirs_exist_ok=True)
        if broken_ledger:
            (sandbox / "ledger-is-a-file").write_text("x", encoding="utf-8")
            os.environ["OCTO_STOP_BLOCK_DIR"] = str(sandbox / "ledger-is-a-file" / "sub")
        else:
            os.environ.pop("OCTO_STOP_BLOCK_DIR", None)
        out = []
        for vf in sorted(fdir.glob("violation*.json")):
            rc, stdout = gate_selftest._run_leg(
                SCRIPTS / script, gate_selftest._prep_payload(vf, fdir, sandbox), sandbox)
            lines = stdout.strip().splitlines()
            assert lines, (script, vf.name, rc, "no output: the violation leg did not block")
            obj = json.loads(lines[-1])
            assert obj.get("decision") == "block", (script, vf.name, stdout)
            reason = obj["reason"]
            detail = None
            if SEP in reason:
                p = Path(reason.rsplit(SEP, 1)[1])
                if p.is_file() and sandbox.resolve() in p.resolve().parents:
                    text = p.read_text(encoding="utf-8")
                    detail = text.split("\n\n", 1)[1][:-1]  # header, then body + "\n"
            # the sandbox path differs between runs; a gate may print it
            sb = str(sandbox)
            out.append((vf.name, reason.replace(sb, "<SANDBOX>"),
                        detail.replace(sb, "<SANDBOX>") if detail is not None else None))
        return out
    finally:
        if old is None:
            os.environ.pop("OCTO_STOP_BLOCK_DIR", None)
        else:
            os.environ["OCTO_STOP_BLOCK_DIR"] = old
        shutil.rmtree(sandbox, ignore_errors=True)


class GateSplitTest(unittest.TestCase):
    def test_every_gate_one_line_full_detail_full_fallback(self):
        for script, fixture in GATES.items():
            with self.subTest(gate=script):
                quiet = _reasons(script, fixture, broken_ledger=False)
                loud = _reasons(script, fixture, broken_ledger=True)
                self.assertTrue(quiet)
                self.assertEqual([q[0] for q in quiet], [l[0] for l in loud])
                for (leg, line, detail), (_, full, _d) in zip(quiet, loud):
                    # (a) one line under the cap
                    self.assertNotIn("\n", line, f"{script} {leg}")
                    self.assertLessEqual(stop_block.words(line), stop_block.WORD_CAP,
                                         f"{script} {leg}: {line}")
                    # (b) the detail file holds the full text
                    self.assertIsNotNone(detail, f"{script} {leg}: no detail file: {line}")
                    self.assertEqual(detail, full, f"{script} {leg}")
                    # FR-04: the friction ledger still attributes the shown line
                    if script not in NO_SIGNATURE:
                        _gate, code = friction_ledger.attribute_block(f"python3 {script}", line)
                        self.assertNotEqual(code, "block", f"{script} {leg}: {line}")
                    # (c) a broken ledger prints the full reason, never the short line
                    self.assertNotIn(SEP, full, f"{script} {leg}")
                    self.assertGreater(len(full), len(line.split(SEP)[0]), f"{script} {leg}")

    def test_reply_panel_fallback_prints_full_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "f").write_text("x", encoding="utf-8")
            env = dict(os.environ)
            env.update({"HOME": tmp, "OCTO_STOP_BLOCK_DIR": str(Path(tmp, "f", "sub"))})
            env.pop("OCTO_REPLY_PANEL", None)
            cp = subprocess.run([sys.executable, str(SCRIPTS / "g__stop__reply-panel.py")],
                                input=json.dumps({"session_id": "s", "stop_hook_active": False}),
                                capture_output=True, text=True, env=env, cwd=tmp, timeout=30)
        self.assertEqual(cp.returncode, 2)
        self.assertEqual(cp.stderr.strip(), "REPLY PANEL (FLOW.panel-before-reply) cannot decide: "
                                             "payload has no last_assistant_message")

    def test_reply_panel_short_line(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("_rp", SCRIPTS / "g__stop__reply-panel.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        msg = ("REPLY PANEL (FLOW.panel-before-reply): this reply is SELF (source class) and "
               "needs PASS receipts from 3 distinct reviewer(s) for its exact text, newer "
               "than the operator's prompt, with a PASS deciding; it has 0 of 3. More.")
        self.assertEqual(mod._short(msg), "REPLY PANEL 0/3 (SELF): reviewer PASS receipts "
                                          "missing for this exact reply")

    def test_every_blocking_stop_hook_is_covered(self):
        hooks = json.loads((ROOT / "hooks.json").read_text(encoding="utf-8"))
        stop = hooks.get("hooks", hooks)["Stop"]
        scripts = set()
        for group in stop:
            for h in group.get("hooks", []):
                parts = h.get("command", "").split()
                scripts.update(Path(p).name for p in parts if p.endswith(".py"))
        uncovered = scripts - set(GATES) - EXIT2_GATES - NON_BLOCKING
        self.assertEqual(uncovered, set(), "a Stop hook is neither split nor declared non-blocking")
        for name in set(GATES) | EXIT2_GATES:
            self.assertIn("stop_block", (SCRIPTS / name).read_text(encoding="utf-8"), name)


class LibraryTest(unittest.TestCase):
    def test_selftest(self):
        cp = subprocess.run([sys.executable, str(SCRIPTS / "stop_block.py"), "--selftest"],
                            capture_output=True, text=True, timeout=30)
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)


if __name__ == "__main__":
    unittest.main()
