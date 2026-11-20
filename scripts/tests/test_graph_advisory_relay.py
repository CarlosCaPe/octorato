#!/usr/bin/env python3
"""Tests for the graph-ledger advisory relay (grafo-ledger-check.py -> grafo-turn-reset.py).

The Stop hook writes its grep-fallback advisory to a per-session file instead of a
systemMessage on the operator's screen; the next UserPromptSubmit hands it to the
model as additionalContext. Pins:
  - per-session isolation: session A's advisory never reaches session B;
  - no real session id ("adhoc", or no session-scoped ledger): nothing written or relayed;
  - an undecodable advisory file: exit 0, no output, the file is deleted anyway;
  - neither hook emits a systemMessage.

Stdlib only:

    python3 -m unittest scripts.tests.test_graph_advisory_relay
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
CHECK = SCRIPTS / "grafo-ledger-check.py"
RELAY = SCRIPTS / "grafo-turn-reset.py"


def _run(script: Path, home: Path, payload, env_sid=None):
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_SESSION_ID"}
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)  # Path.home() reads USERPROFILE on Windows, not HOME
    if env_sid is not None:
        env["CLAUDE_SESSION_ID"] = env_sid
    data = payload if isinstance(payload, str) else json.dumps(payload)
    cp = subprocess.run([sys.executable, str(script)], input=data, capture_output=True,
                        text=True, env=env, encoding="utf-8")
    return cp.returncode, cp.stdout.strip()


class AdvisoryRelayTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self.ledger = self.home / ".claude" / ".cache" / "graph-ledger"
        self.ledger.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _fallback(self, sid: str, target: str):
        (self.ledger / f"{sid}.jsonl").write_text(
            json.dumps({"state": "GREP-FALLBACK", "target": target}) + "\n", encoding="utf-8")

    def test_session_a_advisory_never_reaches_session_b(self):
        self._fallback("sess-a", "unlit-a")
        rc, out = _run(CHECK, self.home, {"session_id": "sess-a"}, env_sid="sess-a")
        self.assertEqual((rc, out), (0, ""))
        self.assertTrue((self.ledger / "sess-a.advisory.txt").exists())

        rc, out = _run(RELAY, self.home, {"session_id": "sess-b"}, env_sid="sess-b")
        self.assertEqual((rc, out), (0, ""))
        self.assertTrue((self.ledger / "sess-a.advisory.txt").exists())

        rc, out = _run(RELAY, self.home, {"session_id": "sess-a"}, env_sid="sess-a")
        self.assertEqual(rc, 0)
        msg = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(msg["hookEventName"], "UserPromptSubmit")
        self.assertIn("unlit-a", msg["additionalContext"])
        self.assertFalse((self.ledger / "sess-a.advisory.txt").exists())

        rc, out = _run(RELAY, self.home, {"session_id": "sess-a"}, env_sid="sess-a")
        self.assertEqual((rc, out), (0, ""))

    def test_payload_session_id_keys_the_file(self):
        self._fallback("ledger-sid", "unlit-x")
        _run(CHECK, self.home, {"session_id": "payload-sid"}, env_sid="ledger-sid")
        self.assertTrue((self.ledger / "payload-sid.advisory.txt").exists())
        self.assertFalse((self.ledger / "ledger-sid.advisory.txt").exists())

    def test_adhoc_is_never_written_or_relayed(self):
        self._fallback("adhoc", "unlit-shared")
        rc, out = _run(CHECK, self.home, {})
        self.assertEqual((rc, out), (0, ""))
        rc, out = _run(CHECK, self.home, {"session_id": "real-sid"})
        self.assertEqual((rc, out), (0, ""))
        self.assertEqual(sorted(p.name for p in self.ledger.glob("*.advisory.txt")), [])

        (self.ledger / "adhoc.advisory.txt").write_text("stale shared advisory", encoding="utf-8")
        rc, out = _run(RELAY, self.home, {})
        self.assertEqual((rc, out), (0, ""))
        rc, out = _run(RELAY, self.home, {"session_id": "adhoc"}, env_sid="adhoc")
        self.assertEqual((rc, out), (0, ""))

    def test_undecodable_file_is_deleted_without_output(self):
        bad = self.ledger / "sess-c.advisory.txt"
        bad.write_bytes(b"\xff\xfe\x00\xc3(broken")
        rc, out = _run(RELAY, self.home, {"session_id": "sess-c"})
        self.assertEqual((rc, out), (0, ""))
        self.assertFalse(bad.exists())

    def test_bad_stdin_fails_open(self):
        self._fallback("sess-d", "unlit-d")
        self.assertEqual(_run(CHECK, self.home, "not json", env_sid="sess-d")[0], 0)
        self.assertEqual(_run(RELAY, self.home, "not json")[0], 0)

    def test_no_system_message_in_either_hook(self):
        for script in (CHECK, RELAY, SCRIPTS / "impact-radius-hook.py"):
            self.assertNotIn('"systemMessage"', script.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
