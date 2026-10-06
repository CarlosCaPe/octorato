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
import hashlib
import json
import os
import re
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
            out = subprocess.run([sys.executable, str(SCRIPTS / "panel_digest.py"), "--body-file", str(body),
                                  "--to", "a@example.test"], capture_output=True, text=True).stdout.strip()
            want = pd.digests_for("mcp__gmail__send_email", {"to": ["a@example.test"], "subject": "Subject",
                                                             "body": "Hello there"})[0]
            self.assertEqual(out, want)

    def test_recipient_changes_digest(self):
        a = pd.digests_for("mcp__whatsapp__send_message", {"recipient": "1", "message": "hi"})
        b = pd.digests_for("mcp__whatsapp__send_message", {"recipient": "2", "message": "hi"})
        self.assertNotEqual(a, b)

    def test_unknown_or_snake_case_key_is_error(self):
        for extra in ({"draft_id": "x"}, {"html_body": "<p>x</p>"}, {"bodyText": "x"}):
            with self.assertRaises(pd.PanelDigestError):
                pd.digests_for("mcp__gmail__send_email", dict({"to": ["a@x"], "subject": "s", "body": "b"}, **extra))

    def test_panel_block_round_trips(self):
        m = pd.message_parts("mcp__gmail__send_email", {"to": ["a@x"], "subject": "s", "body": "b  c"})[0]
        got = pd.recompute_from_report("ok\n" + m.panel_block() + "\nPANEL-VERDICT: PASS")
        self.assertEqual(got["digest"], m.digest)

    def test_bridge_must_be_the_only_command(self):
        s = "wa-soporte" + ".sh"
        for cmd in (f'cp a b && {s} 1 "x" --archivo b', f'{s} 1 "x" > out', f'{s} 1 "x" | tee l',
                    f'{s} 1 "x"; echo done'):
            with self.assertRaises(pd.PanelDigestError):
                pd.support_sends(cmd)
        self.assertEqual(pd.support_sends(f'{s} 1 "a; b & c"'), [("1", "a; b & c", None, [])])


class BridgeArgs(unittest.TestCase):
    """One reader for the support script's arguments: the script strips its
    value flags wherever they sit, and so must every reader of the line."""

    S = "wa-soporte" + ".sh"

    def setUp(self):
        self._env = os.environ.pop(pd.MENTIONS_ENV, None)

    def tearDown(self):
        os.environ.pop(pd.MENTIONS_ENV, None)
        if self._env is not None:
            os.environ[pd.MENTIONS_ENV] = self._env

    def test_flag_position_does_not_change_what_is_read(self):
        want = ("G", "hola a todos", None, ["A"])
        for rest in (["G", "hola a todos", "--menciones", "A"],
                     ["--menciones", "A", "G", "hola a todos"],
                     ["G", "--menciones", "A", "hola a todos"],
                     ["G", "hola", "--menciones", "A", "a", "todos"]):
            self.assertEqual(pd.parse_bridge_args(rest), want, rest)

    def test_every_value_flag_of_the_script_is_known(self):
        # The script's own case arms are the source of truth: a flag added
        # there and not here is the bug this reader exists to prevent.
        src = (Path(pd.__file__).parent / pd.SUPPORT_SCRIPT).read_text(encoding="utf-8")
        arms = set(re.findall(r"^\s{4}(--[a-z-]+)\)\s*$", src, re.MULTILINE))
        self.assertTrue(arms)
        self.assertEqual(arms, set(pd.BRIDGE_VALUE_FLAGS))

    def test_the_script_refuses_the_shapes_the_reader_refuses(self):
        # Only shapes that exit in the argument loop, before anything is sent.
        script = str(Path(pd.__file__).parent / pd.SUPPORT_SCRIPT)
        self.assertEqual(subprocess.run(["bash", "-n", script]).returncode, 0)
        for rest in (["G", "m", "--menciones", "A", "--menciones", "B"],
                     ["G", "m", "--menciones", "--archivo", "f"], ["G", "m", "--menciones"],
                     ["G", "m", "--menciones", ""]):
            with self.assertRaises(pd.PanelDigestError, msg=rest):
                pd.parse_bridge_args(rest)
            done = subprocess.run(["bash", script, *rest], capture_output=True, text=True, timeout=20)
            self.assertEqual(done.returncode, 64, (rest, done.stderr))

    def test_mentions_are_split_like_the_script_splits_them(self):
        self.assertEqual(pd.parse_bridge_args(["G", "m", "--menciones", " A ,,B, "])[3], ["A", "B"])

    def test_lines_the_reader_cannot_be_sure_of_deny(self):
        for rest in (["G", "m", "--menciones"], ["G", "m", "--menciones", ""],
                     ["G", "m", "--menciones", ","], ["G", "m", "--menciones", "A", "--menciones", "B"],
                     ["G", "m", "--archivo", "f", "--archivo", "g"],
                     ["G", "m", "--menciones", "--archivo", "f"], ["G", "m", "--archivo", "--menciones"],
                     ["G", "--menciones", "A"], ["--menciones", "A", "G"], ["G"], []):
            with self.assertRaises(pd.PanelDigestError, msg=rest):
                pd.parse_bridge_args(rest)
            self.assertEqual(pd.bridge_recipient(rest), "", rest)

    def test_recipient_is_never_a_flag_value(self):
        self.assertEqual(pd.bridge_recipient(["--menciones", "A", "G", "m"]), "G")
        self.assertEqual(pd.bridge_recipient(["--archivo", "f", "G", "m"]), "G")
        self.assertEqual(pd.bridge_recipient(["G", "m"]), "G")

    def test_mentions_are_part_of_the_digest(self):
        base = pd.digests_for("Bash", {"command": f'{self.S} G "hola"'})
        a = pd.digests_for("Bash", {"command": f'{self.S} G "hola" --menciones A'})
        b = pd.digests_for("Bash", {"command": f'{self.S} G "hola" --menciones B'})
        first = pd.digests_for("Bash", {"command": f'{self.S} --menciones A G "hola"'})
        both = pd.digests_for("Bash", {"command": f'{self.S} G "hola" --menciones B,A'})
        swapped = pd.digests_for("Bash", {"command": f'{self.S} G "hola" --menciones a,b'})
        self.assertEqual(len({base[0], a[0], b[0], both[0]}), 4)
        self.assertEqual(a, first)
        self.assertEqual(both, swapped)

    def test_a_send_without_mentions_keeps_its_old_digest(self):
        old = hashlib.sha256(json.dumps(
            {"text": "hola", "attachments": [], "recipients": ["g"]},
            ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        self.assertEqual(pd.digest("hola", [], ["G"]), old)
        self.assertEqual(pd.digests_for("Bash", {"command": f'{self.S} G "hola"'}), [old])

    def test_flag_text_is_not_message_text(self):
        literal = pd.digests_for("Bash", {"command": f'{self.S} G "hola --menciones A"'})
        flagged = pd.digests_for("Bash", {"command": f'{self.S} G hola --menciones A'})
        self.assertNotEqual(literal, flagged)

    def test_panel_block_carries_mentions_and_round_trips(self):
        m = pd.message_parts("Bash", {"command": f'{self.S} G "hola" --menciones B,A'})[0]
        block = m.panel_block()
        self.assertIn("PANEL-MENTION: a\nPANEL-MENTION: b", block)
        got = pd.recompute_from_report("ok\n" + block + "\nPANEL-VERDICT: PASS")
        self.assertEqual((got["digest"], got["mentions"]), (m.digest, ["a", "b"]))
        without = block.replace("PANEL-MENTION: a\n", "")
        self.assertNotEqual(pd.recompute_from_report(without)["digest"], m.digest)

    def test_what_bash_would_expand_denies(self):
        s = self.S
        for cmd in (f"{s} --menciones {{A,G}} B hola", f"{s} {{A,G}} hola", f"{s} G hola *",
                    f"{s} G hol?", f"{s} G [a-z]x", f"{s} G hola }}", f"{s} G ~ hola",
                    f"{s} ~/x hola", f"{s} G hola --menciones ~a", f"{s} G a\\ b *",
                    f'{s} G "quoted" {{a,b}}', f"{s} G 'a'*"):
            with self.assertRaises(pd.PanelDigestError, msg=cmd):
                pd.support_sends(cmd)

    def test_quoted_or_escaped_expansion_characters_are_text(self):
        s = self.S
        for cmd, text in ((f'{s} G "sizes {{a,b}} and * and ~ and [x]?"', "sizes {a,b} and * and ~ and [x]?"),
                          (f"{s} G 'a {{b,c}} *'", "a {b,c} *"),
                          (f"{s} G a\\*b", "a*b"), (f"{s} G a~b mid~dle", "a~b mid~dle"),
                          (f'{s} G "it\'s {{x}}"', "it's {x}"),
                          (f'{s} G "say \\"hi\\" {{x}}"', 'say "hi" {x}')):
            self.assertEqual(pd.support_sends(cmd)[0][:2], ("G", text), cmd)

    def test_tilde_expands_only_where_the_reader_expands_it(self):
        home_script = "~/.claude/scripts/" + self.S
        with tempfile.TemporaryDirectory() as d:
            old = os.environ.get("HOME")
            os.environ["HOME"] = d
            try:
                (Path(d) / "f.txt").write_text("x", encoding="utf-8")
                got = pd.message_parts("Bash", {"command": f'{home_script} G "hola" --archivo ~/f.txt'})[0]
                self.assertEqual(got.attachments[0][0], pd.file_sha256(str(Path(d) / "f.txt")))
                self.assertEqual(pd.support_sends(f'bash {home_script} G "hola"')[0][0], "G")
                with self.assertRaises(pd.PanelDigestError):
                    pd.support_sends(f"{home_script} ~/f.txt hola")
            finally:
                if old is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old

    def test_inherited_mentions_with_no_flag_deny(self):
        os.environ[pd.MENTIONS_ENV] = "A"
        with self.assertRaises(pd.PanelDigestError):
            pd.digests_for("Bash", {"command": f'{self.S} G "hola"'})
        self.assertTrue(pd.digests_for("Bash", {"command": f'{self.S} G "hola" --menciones B'}))
        os.environ[pd.MENTIONS_ENV] = "  "
        self.assertTrue(pd.digests_for("Bash", {"command": f'{self.S} G "hola"'}))

    def test_cli_mention_matches_the_bridge_reading(self):
        with tempfile.TemporaryDirectory() as d:
            body = Path(d) / "b.txt"
            body.write_text("hola", encoding="utf-8")
            out = subprocess.run([sys.executable, str(Path(pd.__file__)), "--body-file", str(body),
                                  "--to", "G", "--mention", "A"], capture_output=True, text=True).stdout.strip()
        self.assertEqual([out], pd.digests_for("Bash", {"command": f'{self.S} G "hola" --menciones A'}))



def _gate():
    import importlib.util
    path = Path(pd.__file__).parent / "g__pretool-mcp__outward-send.py"
    spec = importlib.util.spec_from_file_location("outward_send_gate", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class GateReadsTheSameRecipient(unittest.TestCase):
    """The recipient a waiver is decided on is the one the panel digest binds."""

    S = "~/.claude/scripts/wa-soporte" + ".sh"

    @classmethod
    def setUpClass(cls):
        cls.gate = _gate()

    def _both(self, command):
        one = self.gate._send_recipient("Bash", {"command": command})
        many = self.gate._bash_recipients(command)
        return one, many

    def test_flag_first_does_not_make_the_mention_the_recipient(self):
        one, many = self._both(f'{self.S} --menciones ALLOWED GROUP "hola"')
        self.assertEqual((one, many), ("GROUP", ["GROUP"]))

    def test_every_flag_position_agrees_with_the_digest(self):
        for command in (f'{self.S} GROUP "hola" --menciones A', f'{self.S} --menciones A GROUP "hola"',
                        f'{self.S} GROUP --archivo f.txt "hola" --menciones A',
                        f'{self.S} --archivo f.txt --menciones A GROUP "hola"', f'{self.S} GROUP "hola"'):
            one, many = self._both(command)
            want = pd.support_sends(command)[0][0]
            self.assertEqual((one, many), (want, [want]), command)

    def test_a_line_the_reader_cannot_read_names_no_recipient(self):
        for command in (f'{self.S} GROUP "hola" --menciones A --menciones B', f'{self.S} GROUP --menciones A',
                        f'{self.S} GROUP "hola" --menciones --archivo f.txt', f'{self.S} GROUP'):
            one, many = self._both(command)
            self.assertEqual((one, many), ("", [""]), command)
            self.assertFalse(self.gate._is_message_send("Bash", {"command": command}))

    def test_an_allowlisted_mention_cannot_borrow_the_waiver(self):
        gate = self.gate
        original = gate._autonomous_cfg
        gate._autonomous_cfg = lambda: [{"jid": "ALLOWED"}]
        try:
            self.assertTrue(gate.autonomous_chat("Bash", {"command": f'{self.S} ALLOWED "hola"'}))
            self.assertTrue(gate.autonomous_chat(
                "Bash", {"command": f'{self.S} --menciones X ALLOWED "hola"'}))
            self.assertFalse(gate.autonomous_chat(
                "Bash", {"command": f'{self.S} --menciones ALLOWED OTHER "hola"'}))
            self.assertFalse(gate.autonomous_chat(
                "Bash", {"command": f'{self.S} OTHER "hola" --menciones ALLOWED'}))
        finally:
            gate._autonomous_cfg = original


class PanelLedger(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="panel-")
        self._home = (os.environ.get("HOME"), os.environ.get("USERPROFILE"))
        os.environ["HOME"] = os.environ["USERPROFILE"] = self.tmp
        self.home = Path(self.tmp)
        self.m = pd.Message("hello", [], ["1"])
        self.d = self.m.digest

    def tearDown(self):
        for key, value in zip(("HOME", "USERPROFILE"), self._home):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_reflex_records_anchored_panel_row(self):
        seed.seed_receipt(self.home, "s1", self.m, "PASS", iso(T), "abc123")
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

    def test_reflex_refuses_stated_digest_that_does_not_recompute(self):
        other = pd.Message("something else", [], ["1"])
        seed.seed_receipt(self.home, "s1", self.m, "PASS", iso(T), "abc999", shown=other)
        (self.home / ".claude/.cache/receipts/global.jsonl").unlink()
        tp = self.home / ".claude/projects/fx/s1/subagents/agent-abc999.jsonl"
        payload = {"session_id": "s1", "agent_id": "abc999", "agent_type": "Reality Checker",
                   "agent_transcript_path": str(tp), "last_assistant_message": ""}
        subprocess.run([sys.executable, str(SCRIPTS / "r__subagent-stop__qa-receipt.py")],
                       input=json.dumps(payload), text=True, env=dict(os.environ), capture_output=True)
        self.assertEqual([r for r in rl.read_global() if r.get("kind") == "panel"], [])

    def test_receipt_is_single_use(self):
        seed.seed_receipt(self.home, "s1", self.m, "PASS", iso(T), "c1")
        r = rl.panel_pass_for(self.d, "s1", T)
        self.assertFalse(rl.panel_receipt_consumed(r["entry_uuid"]))
        rl.append_sent({"panel_receipt": r["entry_uuid"], "ok": None, "digest": self.d})
        self.assertTrue(rl.panel_receipt_consumed(r["entry_uuid"]))

    def test_malformed_digest_records_nothing(self):
        self.assertEqual(rl.parse_panel("PANEL-VERDICT: PASS\nPANEL-SHA256: abc"), ("PASS", ""))

    def test_newest_decides_and_revokes(self):
        seed.seed_receipt(self.home, "s1", self.m, "PASS", iso(T - dt.timedelta(minutes=20)), "a1")
        self.assertIsNotNone(rl.panel_pass_for(self.d, "s1", T))
        seed.seed_receipt(self.home, "s1", self.m, "NEEDS-WORK", iso(T - dt.timedelta(minutes=5)), "a2")
        self.assertIsNone(rl.panel_pass_for(self.d, "s1", T))
        seed.seed_receipt(self.home, "s1", self.m, "PASS", iso(T - dt.timedelta(minutes=1)), "a3")
        self.assertIsNotNone(rl.panel_pass_for(self.d, "s1", T))

    def test_other_session_and_stale_never_count(self):
        seed.seed_receipt(self.home, "s2", self.m, "PASS", iso(T - dt.timedelta(minutes=5)), "b1")
        self.assertIsNone(rl.panel_pass_for(self.d, "s1", T))
        seed.seed_receipt(self.home, "s1", self.m, "PASS", iso(T - dt.timedelta(minutes=121)), "b2")
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
