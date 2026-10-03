#!/usr/bin/env python3
"""Tests for the chat-validated release (FLOW.chat-validated-release).

  - every fixture of the rule is denied for the condition it names (`_expect`),
    or allowed when it is benign, and the committed fixtures match the builder
  - the closed yes-list, sender id normalization
  - the support replica path: an approver there releases, its is_from_me never does
  - an attachment's file name must be in the validation message
  - the sent-ledger reflex writes the release key, and the gate then refuses
    a second send on that approval

Stdlib only:  python3 -m unittest scripts.tests.test_chat_release
"""
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
REPO = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))
import chat_release_fixture_seed as seed  # noqa: E402
import panel_digest as pd  # noqa: E402
import panel_fixture_seed  # noqa: E402

GATE = SCRIPTS / "g__pretool-mcp__outward-send.py"
REFLEX = SCRIPTS / "r__posttool__sent-ledger.py"
FIXTURES = REPO / "registry" / "fixtures" / "FLOW.chat-validated-release"


def _gate_module():
    spec = importlib.util.spec_from_file_location("outward_send_gate", GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_gate(home: Path, fdir: Path, payload: dict) -> str:
    """The deny reason, or "" when the gate allows."""
    data = dict(payload)
    data["transcript_path"] = str((fdir / data["transcript_path"]).resolve())
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home), CLAUDE_SESSION_ID="__selftest__")
    env.pop("OCTO_KERNEL_OPEN", None)
    cp = subprocess.run([sys.executable, str(GATE)], input=json.dumps(data), capture_output=True,
                        text=True, env=env, cwd=str(home), timeout=60)
    if not cp.stdout.strip():
        return ""
    return json.loads(cp.stdout)["hookSpecificOutput"]["permissionDecisionReason"]


class Built(unittest.TestCase):
    """A fresh fixture tree per test: the builder output plus a throwaway HOME."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chat-release-"))
        self.fdir = self.tmp / "fx"
        seed.build(self.fdir)
        self.home = self.tmp / "home"
        shutil.copytree(self.fdir / "home", self.home)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def payload(self, name: str) -> dict:
        return json.loads((self.fdir / f"{name}.json").read_text(encoding="utf-8"))


class Fixtures(Built):
    def test_every_case_denies_for_its_own_condition(self):
        for c in seed.CASES:
            with self.subTest(case=c["name"]):
                home = self.tmp / f"h-{c['n']}"
                shutil.copytree(self.fdir / "home", home)
                reason = run_gate(home, self.fdir, self.payload(c["name"]))
                if c["expect"]:
                    self.assertIn(c["expect"], reason)
                else:
                    self.assertEqual(reason, "")

    def test_committed_fixtures_match_the_builder(self):
        for p in sorted(self.fdir.glob("*.json*")):
            with self.subTest(file=p.name):
                self.assertEqual(p.read_text(encoding="utf-8"),
                                 (FIXTURES / p.name).read_text(encoding="utf-8"))
        for rel in (".claude/.cache/receipts/sent.jsonl",
                    ".claude/company/config/outward-send-autonomous.json"):
            self.assertEqual((self.fdir / "home" / rel).read_text(encoding="utf-8"),
                             (FIXTURES / "home" / rel).read_text(encoding="utf-8"))


class YesList(unittest.TestCase):
    def setUp(self):
        self.g = _gate_module()

    def test_closed_list(self):
        for t in ("sí", "Sí, así", "si asi envialo", "envíalo", "Mándalo!", "OK", "dale 👍",
                  "send-ok", "yes", "Go ahead.", "@5215500000000 sí"):
            self.assertTrue(self.g.is_affirmative(t), t)
        for t in ("sí pero cambia el asunto", "no", "espera", "perfecto, mándalo ya", "sí, mándalo",
                  "okey", "👍", "", "ok no"):
            self.assertFalse(self.g.is_affirmative(t), t)

    def test_retraction_words(self):
        for t in ("no", "Espera", "para", "cancela eso", "stop", "cambia el asunto"):
            self.assertTrue(self.g.is_retraction(t), t)
        self.assertFalse(self.g.is_retraction("ok"))

    def test_sender_ids(self):
        s = self.g.sender_id
        self.assertEqual(s("10000000000001@lid"), "10000000000001")
        self.assertEqual(s("5215511111111:12@s.whatsapp.net"), "5215511111111")
        self.assertEqual(s("+5215511111111"), "5215511111111")


class SupportReplica(Built):
    def _support(self, rows):
        db = self.home / ".config" / "whatsapp-support" / "bridge" / "store" / "messages.db"
        db.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE messages (id TEXT, chat_jid TEXT, sender TEXT, content TEXT, "
                    "timestamp TIMESTAMP, is_from_me BOOLEAN)")
        for r in rows:
            con.execute("INSERT INTO messages VALUES (?,?,?,?,?,?)", r)
        con.commit()
        con.close()

    def test_approver_in_support_replica_releases(self):
        jid = seed._jid(113)
        self._support([("S1", jid, f"{seed.APPROVER}@lid", "sí", "2026-10-03 11:58:00+00:00", 0)])
        self.assertEqual(run_gate(self.home, self.fdir, self.payload("violation_store_missing")), "")

    def test_bridge_own_account_never_approves(self):
        jid = seed._jid(113)
        self._support([("S1", jid, seed.OPERATOR, "sí", "2026-10-03 11:58:00+00:00", 1)])
        self.assertIn("not an approver",
                      run_gate(self.home, self.fdir, self.payload("violation_store_missing")))


class Attachments(Built):
    def _case(self, v_names_file: bool) -> str:
        att = self.home / "attach" / "hoja.txt"
        att.parent.mkdir(parents=True, exist_ok=True)
        att.write_text("hoja firmada", encoding="utf-8")
        p = self.payload("benign_approved_by_approver")
        p["tool_input"] = dict(p["tool_input"], attachments=[str(att)])
        msg = pd.message_parts(p["tool_name"], p["tool_input"])[0]
        panel_fixture_seed.seed_receipt(self.home, p["session_id"], msg, "PASS",
                                        "2026-10-03T11:55:00Z", "attachcase0000001")
        sent = self.home / ".claude" / ".cache" / "receipts" / "sent.jsonl"
        lines = [json.loads(ln) for ln in sent.read_text(encoding="utf-8").splitlines()]
        for ln in lines:
            if ln.get("message_id") == "V101" and v_names_file:
                ln["text"] += " Adjunto: hoja.txt"
        sent.write_text("".join(json.dumps(ln) + "\n" for ln in lines), encoding="utf-8")
        return run_gate(self.home, self.fdir, p)

    def test_attachment_name_required(self):
        self.assertIn("does not name hoja.txt", self._case(False))

    def test_attachment_named_releases(self):
        self.assertEqual(self._case(True), "")


class SingleUse(Built):
    def test_reflex_records_key_and_gate_refuses_reuse(self):
        p = self.payload("benign_approved_by_approver")
        data = dict(p, transcript_path=str((self.fdir / p["transcript_path"]).resolve()),
                    tool_response={"id": "G101"}, tool_use_id="t101",
                    _now="2026-10-03T12:00:00+00:00")
        env = dict(os.environ, HOME=str(self.home), CLAUDE_SESSION_ID="__selftest__")
        subprocess.run([sys.executable, str(REFLEX)], input=json.dumps(data), text=True,
                       capture_output=True, env=env, timeout=60)
        sent = self.home / ".claude" / ".cache" / "receipts" / "sent.jsonl"
        last = json.loads(sent.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(last.get("chat_release"), f"{seed._jid(101)}|V101|A101")
        self.assertIn("already released a send", run_gate(self.home, self.fdir, p))

    def test_reflex_records_whatsapp_text(self):
        p = self.payload("benign_whatsapp_third_party")
        data = dict(p, transcript_path=str((self.fdir / p["transcript_path"]).resolve()),
                    tool_response="[message_id=W1 chat_jid=x]", tool_use_id="t103",
                    _now="2026-10-03T12:00:00+00:00")
        env = dict(os.environ, HOME=str(self.home), CLAUDE_SESSION_ID="__selftest__")
        subprocess.run([sys.executable, str(REFLEX)], input=json.dumps(data), text=True,
                       capture_output=True, env=env, timeout=60)
        sent = self.home / ".claude" / ".cache" / "receipts" / "sent.jsonl"
        last = json.loads(sent.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(last.get("text"), pd.normalize(p["tool_input"]["message"]))


class Selftest(unittest.TestCase):
    def test_gate_selftest_passes(self):
        cp = subprocess.run([sys.executable, str(GATE), "--selftest", str(FIXTURES)],
                            capture_output=True, text=True, timeout=600)
        self.assertEqual(cp.returncode, 0, cp.stderr)


if __name__ == "__main__":
    unittest.main()
