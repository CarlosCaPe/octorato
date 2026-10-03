#!/usr/bin/env python3
"""Tests for the chat-validated release (FLOW.chat-validated-release).

  - every fixture of the rule is denied for the condition it names (`_expect`),
    or allowed when it is benign, and the committed fixtures match the builder
  - the closed yes-list, sender id normalization
  - the support replica path: an approver there releases, its is_from_me never does
  - an attachment's file name must be a whole token of the validation message
  - recipients and the quoted text are compared for equality, never as substrings
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
        self.assertIn("an is_from_me yes never releases",
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
        vtext = pd.validation_text(msg)
        if not v_names_file:
            vtext = vtext.replace("Attach: hoja.txt", "")
        sent = self.home / ".claude" / ".cache" / "receipts" / "sent.jsonl"
        lines = [json.loads(ln) for ln in sent.read_text(encoding="utf-8").splitlines()]
        for ln in lines:
            if ln.get("message_id") == "V101":
                ln["text"] = pd.normalize(vtext)
        sent.write_text("".join(json.dumps(ln) + "\n" for ln in lines), encoding="utf-8")
        return run_gate(self.home, self.fdir, p)

    def test_attachment_name_required(self):
        self.assertIn("does not name the attachment(s) ['hoja.txt']", self._case(False))

    def test_attachment_named_releases(self):
        self.assertEqual(self._case(True), "")


class Validation(unittest.TestCase):
    def setUp(self):
        self.g = _gate_module()

    def test_tokens_are_whole(self):
        m = pd.Message("Hola", [], ["bob@example.test"])
        good = pd.validation_text(m)
        self.assertEqual(self.g._validates(good, m), "")
        bad = good.replace("bob@example.test", "notbob@example.test.evil")
        self.assertIn("names recipients", self.g._validates(bad, m))
        self.assertIn("names recipients", self.g._validates(good.replace("To:", "To: x@example.test"), m))

    def test_block_is_compared_for_equality(self):
        m = pd.Message("Aceptamos la oferta.", [], ["a@example.test"])
        longer = pd.validation_text(pd.Message("Aceptamos la oferta. Salvo la clausula 5.", [],
                                               ["a@example.test"]))
        longer = longer.replace(longer.split("sha256:")[1][:12], m.digest[:12])
        self.assertIn("exactly", self.g._validates(longer, m))

    def test_two_blocks_is_not_a_validation(self):
        m = pd.Message("x", [], ["a@example.test"])
        self.assertIsNone(self.g.parse_validation(pd.validation_text(m) + " «y»"))


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
        self.assertEqual(last.get("chat_release"), f"{seed._jid(101)}|A101")
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


class TrailerCli(Built):
    def test_validation_request_prints_the_chat_trailer(self):
        p = self.payload("benign_custom_trailer")
        tin = self.tmp / "tin.json"
        tin.write_text(json.dumps(p["tool_input"]), encoding="utf-8")
        env = dict(os.environ, HOME=str(self.home))
        out = subprocess.run([sys.executable, str(SCRIPTS / "panel_digest.py"), "--tool-input", str(tin),
                              "--tool-name", p["tool_name"], "--validation-request",
                              "--chat", seed._jid(128)], capture_output=True, text=True, env=env).stdout
        self.assertTrue(out.strip().endswith(seed.ES_TRAILER))
        sent = (self.home / ".claude" / ".cache" / "receipts" / "sent.jsonl").read_text(encoding="utf-8")
        v = [json.loads(ln) for ln in sent.splitlines() if json.loads(ln).get("message_id") == "V128"][0]
        self.assertEqual(pd.normalize(out), v["text"])

    def test_unknown_chat_is_an_error(self):
        p = self.payload("benign_custom_trailer")
        tin = self.tmp / "tin.json"
        tin.write_text(json.dumps(p["tool_input"]), encoding="utf-8")
        cp = subprocess.run([sys.executable, str(SCRIPTS / "panel_digest.py"), "--tool-input", str(tin),
                             "--tool-name", p["tool_name"], "--validation-request", "--chat", "nope@g.us"],
                            capture_output=True, text=True, env=dict(os.environ, HOME=str(self.home)))
        self.assertEqual(cp.returncode, 2)

    def test_es_trailer_words_are_not_an_approval(self):
        self.assertFalse(_gate_module().is_affirmative(seed.ES_TRAILER))


class Selftest(unittest.TestCase):
    def test_gate_selftest_passes(self):
        cp = subprocess.run([sys.executable, str(GATE), "--selftest", str(FIXTURES)],
                            capture_output=True, text=True, timeout=600)
        self.assertEqual(cp.returncode, 0, cp.stderr)


if __name__ == "__main__":
    unittest.main()
