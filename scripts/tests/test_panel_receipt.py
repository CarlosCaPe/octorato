#!/usr/bin/env python3
"""Tests for the panel receipt (FLOW.panel-before-send) and the sent-message
ledger (FLOW.sent-message-ledger).

  - the digest ignores whitespace layout and changes with one word or one
    attachment byte; an unreadable attachment is an error, never a skip
  - the SubagentStop reflex records a `panel` row anchored to the reviewer's
    transcript entry, and records nothing when the digest is malformed
  - panel_latest_for: the newest receipt for a digest decides, a NEEDS-WORK
    revokes, another session's or a stale receipt never counts
  - both selftests (gate vs FLOW.panel-before-send, reflex vs
    FLOW.sent-message-ledger) pass

Stdlib only:  python3 -m unittest scripts.tests.test_panel_receipt
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import panel_digest as pd  # noqa: E402
import panel_fixture_seed as seed  # noqa: E402
import receipt_ledger as rl  # noqa: E402

import datetime as dt  # noqa: E402

T = dt.datetime(2026, 10, 2, 12, 0, 0, tzinfo=dt.timezone.utc)


def iso(t):
    return t.isoformat().replace("+00:00", ".000Z")


class Digest(unittest.TestCase):
    def test_layout_insensitive_word_sensitive(self):
        self.assertEqual(pd.digest("a  b\r\nc "), pd.digest("a b c"))
        self.assertNotEqual(pd.digest("a b c"), pd.digest("a b d"))

    def test_attachment_bytes_change_digest_and_missing_is_error(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "x.pdf"
            f.write_bytes(b"one")
            d1 = pd.digests_for("mcp__whatsapp__send_file", {"recipient": "1", "media_path": str(f)})
            f.write_bytes(b"two")
            d2 = pd.digests_for("mcp__whatsapp__send_file", {"recipient": "1", "media_path": str(f)})
            self.assertNotEqual(d1, d2)
            with self.assertRaises(pd.PanelDigestError):
                pd.digests_for("mcp__whatsapp__send_file", {"recipient": "1", "media_path": str(f) + ".gone"})

    def test_cli_matches_library(self):
        with tempfile.TemporaryDirectory() as d:
            body = Path(d) / "b.txt"
            body.write_text("Subject\nHello there")
            out = subprocess.run([sys.executable, str(SCRIPTS / "panel_digest.py"), "--body-file", str(body)],
                                 capture_output=True, text=True).stdout.strip()
            want = pd.digests_for("mcp__gmail__send_email", {"subject": "Subject", "body": "Hello there"})[0]
            self.assertEqual(out, want)


class PanelLedger(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="panel-")
        self._home = (os.environ.get("HOME"), os.environ.get("USERPROFILE"))
        os.environ["HOME"] = os.environ["USERPROFILE"] = self.tmp
        self.home = Path(self.tmp)
        self.d = pd.digest("hello")

    def tearDown(self):
        for key, value in zip(("HOME", "USERPROFILE"), self._home):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_reflex_records_anchored_panel_row(self):
        seed.seed_receipt(self.home, "s1", self.d, "PASS", iso(T), "abc123")
        # drop the seeded row: the reflex must write its own
        (self.home / ".claude/.cache/receipts/global.jsonl").unlink()
        tp = self.home / ".claude/projects/fx/s1/subagents/agent-abc123.jsonl"
        payload = {"session_id": "s1", "agent_id": "abc123", "agent_type": "Reality Checker",
                   "agent_transcript_path": str(tp), "last_assistant_message": ""}
        env = dict(os.environ)
        subprocess.run([sys.executable, str(SCRIPTS / "r__subagent-stop__qa-receipt.py")],
                       input=json.dumps(payload), text=True, env=env, capture_output=True)
        rows = [r for r in rl.read_global() if r.get("kind") == "panel"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["digest"], self.d)
        self.assertTrue(rows[0]["entry_uuid"])
        self.assertIsNotNone(rl.panel_pass_for(self.d, "s1", T))

    def test_malformed_digest_records_nothing(self):
        self.assertEqual(rl.parse_panel("PANEL-VERDICT: PASS\nPANEL-SHA256: abc"), ("PASS", ""))

    def test_newest_decides_and_revokes(self):
        seed.seed_receipt(self.home, "s1", self.d, "PASS", iso(T - dt.timedelta(minutes=20)), "a1")
        self.assertIsNotNone(rl.panel_pass_for(self.d, "s1", T))
        seed.seed_receipt(self.home, "s1", self.d, "NEEDS-WORK", iso(T - dt.timedelta(minutes=5)), "a2")
        self.assertIsNone(rl.panel_pass_for(self.d, "s1", T))
        seed.seed_receipt(self.home, "s1", self.d, "PASS", iso(T - dt.timedelta(minutes=1)), "a3")
        self.assertIsNotNone(rl.panel_pass_for(self.d, "s1", T))

    def test_other_session_and_stale_never_count(self):
        seed.seed_receipt(self.home, "s2", self.d, "PASS", iso(T - dt.timedelta(minutes=5)), "b1")
        self.assertIsNone(rl.panel_pass_for(self.d, "s1", T))
        seed.seed_receipt(self.home, "s1", self.d, "PASS", iso(T - dt.timedelta(minutes=121)), "b2")
        self.assertIsNone(rl.panel_pass_for(self.d, "s1", T))


class Selftests(unittest.TestCase):
    def _run(self, *args):
        return subprocess.run([sys.executable, *args], capture_output=True, text=True,
                              cwd=str(SCRIPTS.parent))

    def test_gate_selftest_panel_fixtures(self):
        cp = self._run("scripts/g__pretool-mcp__outward-send.py", "--selftest",
                       "registry/fixtures/FLOW.panel-before-send")
        self.assertEqual(cp.returncode, 0, cp.stderr)

    def test_gate_selftest_comms_fixtures(self):
        cp = self._run("scripts/g__pretool-mcp__outward-send.py", "--selftest",
                       "registry/fixtures/COMMS.outward-send-gate")
        self.assertEqual(cp.returncode, 0, cp.stderr)

    def test_sent_ledger_selftest(self):
        cp = self._run("scripts/r__posttool__sent-ledger.py", "--selftest")
        self.assertEqual(cp.returncode, 0, cp.stderr)


if __name__ == "__main__":
    unittest.main()
