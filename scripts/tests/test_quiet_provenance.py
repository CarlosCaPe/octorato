#!/usr/bin/env python3
"""Tests for quiet provenance (docs/specs/202611200722-quiet-provenance).

Pins: provenance_ledger.py records and reads entries per session; the reply
panel's classifier reads a fresh ledger entry with the footer rules; the
preflight judges a footer-less draft as SOURCED when this session recorded a
sourced Basis after the prompt, and the spawned source-attribution gate lets
it through; the UserPromptSubmit reminder tells the agent to record, not print.

Stdlib only:

    python3 -m unittest scripts.tests.test_quiet_provenance
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import provenance_ledger  # noqa: E402


def _load(name: str):
    spec = importlib.util.spec_from_file_location("_qp_" + name.replace("-", "_").replace(".", "_"),
                                                  SCRIPTS / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RP = _load("g__stop__reply-panel.py")
SESSION = "qp-test-session"
PROMPT_TS = "2026-10-16T08:00:00.000Z"
DRAFT = ("```\nbranch ──► tests ──► ✓\n```\n\n- The tests pass on the branch.\n")


def _transcript(path: Path) -> None:
    path.write_text(json.dumps({
        "type": "user", "uuid": "u1", "parentUuid": None, "sessionId": SESSION,
        "timestamp": PROMPT_TS, "message": {"role": "user", "content": "Do the tests pass?"},
        "origin": {"kind": "human"},
    }) + "\n", encoding="utf-8")


class _Home(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="qp-test-"))
        self.old = {k: os.environ.get(k) for k in ("HOME", "USERPROFILE", "CLAUDE_SESSION_ID",
                                                    "CLAUDE_CODE_SESSION_ID", "OCTO_STOP_BLOCK_DIR")}
        os.environ["HOME"] = os.environ["USERPROFILE"] = str(self.tmp)
        os.environ.pop("CLAUDE_SESSION_ID", None)
        os.environ["CLAUDE_CODE_SESSION_ID"] = SESSION
        os.environ["OCTO_STOP_BLOCK_DIR"] = str(self.tmp / "stop-blocks")
        self.transcript = self.tmp / "session.jsonl"
        _transcript(self.transcript)

    def tearDown(self):
        import shutil
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)


class LedgerCli(_Home):
    def test_record_then_show_uses_harness_session(self):
        cli = [sys.executable, str(SCRIPTS / "provenance_ledger.py")]
        cp = subprocess.run(cli + ["record", "--basis", "git log", "--engine", "main loop",
                                   "--verdict", "LOAD"], capture_output=True, text=True,
                            env=dict(os.environ))
        self.assertEqual(cp.returncode, 0, cp.stderr)
        rows = provenance_ledger.entries(SESSION)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["verdict"], "LOAD")
        cp = subprocess.run(cli + ["show"], capture_output=True, text=True, env=dict(os.environ))
        self.assertEqual(cp.stdout.strip(), "Provenance: Basis: git log · Engine: main loop · 2D: LOAD")

    def test_record_without_session_fails(self):
        env = dict(os.environ)
        env.pop("CLAUDE_CODE_SESSION_ID", None)
        cp = subprocess.run([sys.executable, str(SCRIPTS / "provenance_ledger.py"), "record",
                             "--basis", "x"], capture_output=True, text=True, env=env)
        self.assertEqual(cp.returncode, 2)
        self.assertEqual(provenance_ledger.entries(SESSION), [])

    def test_prompt_ts_uses_the_reply_panel_walk(self):
        self.assertEqual(provenance_ledger.prompt_ts(str(self.transcript)), PROMPT_TS)


class Classifier(unittest.TestCase):
    def test_no_footer_no_entry_is_self(self):
        self.assertEqual(RP.source_class("The tests pass."), "SELF")

    def test_sourced_entry_is_sourced(self):
        self.assertEqual(RP.source_class("The tests pass.", {"basis": "git log"}), "SOURCED")

    def test_self_entry_is_self(self):
        for basis in ("", "own reasoning", "myself", "none", "---", "razonamiento propio"):
            self.assertEqual(RP.source_class("The tests pass.", {"basis": basis}), "SELF", basis)

    def test_self_entry_beats_sourced_footer(self):
        text = "The tests pass.\n\nProvenance: Basis: git log\n"
        self.assertEqual(RP.source_class(text, {"basis": "own reasoning"}), "SELF")

    def test_self_footer_beats_sourced_entry(self):
        text = "The tests pass.\n\nProvenance: Basis: own reasoning\n"
        self.assertEqual(RP.source_class(text, {"basis": "git log"}), "SELF")


class Preflight(_Home):
    def test_footerless_draft_with_fresh_entry(self):
        import panel_preflight
        provenance_ledger.record(SESSION, ts="2026-10-16T08:01:00.000Z", basis="git log origin/master")
        res = panel_preflight.run(DRAFT, str(self.transcript))
        self.assertEqual(res["class"], "SOURCED")
        sa = [r for r in res["results"] if r["gate"] == "source-attribution-check.py"]
        self.assertEqual(sa and sa[0]["verdict"], "PASS", res["results"])

    def test_footerless_draft_with_stale_entry(self):
        import panel_preflight
        provenance_ledger.record(SESSION, ts="2026-10-16T07:59:00.000Z", basis="git log")
        res = panel_preflight.run(DRAFT, str(self.transcript))
        self.assertEqual(res["class"], "SELF")
        sa = [r for r in res["results"] if r["gate"] == "source-attribution-check.py"]
        self.assertEqual(sa and sa[0]["verdict"], "BLOCK", res["results"])


class Reminder(unittest.TestCase):
    def test_reminder_records_instead_of_printing(self):
        cp = subprocess.run([sys.executable, str(SCRIPTS / "4d-reminder.py")], input="{}",
                            capture_output=True, text=True)
        ctx = json.loads(cp.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("provenance_ledger.py record", ctx)
        self.assertIn("only when the operator asks", ctx)
        self.assertNotIn("Provenance footer at the very end", ctx)


if __name__ == "__main__":
    unittest.main()
