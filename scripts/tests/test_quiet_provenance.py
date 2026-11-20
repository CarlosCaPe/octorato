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
        self.assertEqual(RP.source_class("The tests pass.", [{"basis": "git log"}]), "SOURCED")

    def test_self_entry_is_self(self):
        for basis in ("", "own reasoning", "myself", "none", "---", "razonamiento propio"):
            self.assertEqual(RP.source_class("The tests pass.", [{"basis": basis}]), "SELF", basis)

    def test_any_self_entry_wins_in_any_order(self):
        for order in ([{"basis": "own reasoning"}, {"basis": "git log"}],
                      [{"basis": "git log"}, {"basis": "own reasoning"}]):
            self.assertEqual(RP.source_class("The tests pass.", order), "SELF")

    def test_self_entry_beats_sourced_footer(self):
        text = "The tests pass.\n\nProvenance: Basis: git log\n"
        self.assertEqual(RP.source_class(text, [{"basis": "own reasoning"}]), "SELF")

    def test_self_footer_beats_sourced_entry(self):
        text = "The tests pass.\n\nProvenance: Basis: own reasoning\n"
        self.assertEqual(RP.source_class(text, [{"basis": "git log"}]), "SELF")

    def test_bound_text_binds_entries_only_without_a_footer(self):
        e = [{"basis": "git log", "engine": "main loop"}]
        self.assertEqual(RP.bound_reply_text("Done.", e),
                         "Done.\nProvenance: Basis: git log · Engine: main loop")
        footed = "Done.\n\nProvenance: Basis: git log\n"
        self.assertEqual(RP.bound_reply_text(footed, e), footed)
        self.assertEqual(RP.bound_reply_text("Done.", []), "Done.")


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


class PanelRequest(_Home):
    def _request(self, body: str) -> subprocess.CompletedProcess:
        f = self.tmp / "draft.txt"
        f.write_text(body, encoding="utf-8")
        return subprocess.run([sys.executable, str(SCRIPTS / "panel_digest.py"), "--panel-request",
                               "--to", "operator", "--body-file", str(f), "--transcript",
                               str(self.transcript)], capture_output=True, text=True, env=dict(os.environ))

    def test_block_shows_the_recorded_footer_and_digests_it(self):
        import panel_digest
        provenance_ledger.record(SESSION, ts="2026-10-16T08:01:00.000Z", basis="git log origin/master")
        cp = self._request(DRAFT)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertIn("Provenance: Basis: git log origin/master", cp.stdout)
        bound = DRAFT + "\nProvenance: Basis: git log origin/master"
        self.assertIn(panel_digest.digest(bound, recipients=["operator"]), cp.stdout)
        self.assertNotIn(panel_digest.digest(DRAFT, recipients=["operator"]), cp.stdout)

    def test_digest_only_binds_too(self):
        import panel_digest
        provenance_ledger.record(SESSION, ts="2026-10-16T08:01:00.000Z", basis="git log")
        f = self.tmp / "draft.txt"
        f.write_text(DRAFT, encoding="utf-8")
        cp = subprocess.run([sys.executable, str(SCRIPTS / "panel_digest.py"), "--to", "operator",
                             "--body-file", str(f), "--transcript", str(self.transcript)],
                            capture_output=True, text=True, env=dict(os.environ))
        self.assertEqual(cp.stdout.strip(),
                         panel_digest.digest(DRAFT + "\nProvenance: Basis: git log", recipients=["operator"]))

    def test_unreadable_ledger_fails_the_preflight(self):
        import panel_preflight
        provenance_ledger.ledger_path().mkdir(parents=True)
        res = panel_preflight.run(DRAFT, str(self.transcript))
        fails = [r for r in res["results"] if r["gate"] == "provenance ledger"]
        self.assertEqual(fails and fails[0]["verdict"], "FAIL", res["results"])
        self.assertIn(fails[0], res["blocked"])
        self.assertIn("PREFLIGHT provenance ledger: FAIL", panel_preflight.report(res))


LONG = ("The staging copy is ready, the dump finished without errors and the row counts were "
        "taken from both sides, so the comparison can start as soon as the operator confirms the "
        "release window for tonight.")


class ReplyAnchor(unittest.TestCase):
    PROMPT = "2026-10-16T08:00:00.000Z"

    def _text(self, ts, text, **msg):
        return {"type": "assistant", "timestamp": ts,
                "message": dict(msg, content=[{"type": "text", "text": text}])}

    def test_narration_with_a_tool_call_does_not_move_reply_anchor(self):
        turn = [self._text("2026-10-16T08:01:00.000Z", LONG),
                {"type": "assistant", "timestamp": "2026-10-16T08:01:01.000Z",
                 "message": {"content": [{"type": "tool_use", "id": "t1"}]}},
                {"type": "user", "timestamp": "2026-10-16T08:01:02.000Z",
                 "message": {"content": [{"type": "tool_result", "tool_use_id": "t1"}]}}]
        self.assertEqual(provenance_ledger.reply_anchor(self.PROMPT, turn, "now"), self.PROMPT)

    def test_reply_that_ended_a_stop_moves_reply_anchor(self):
        note = {"type": "user", "timestamp": "2026-10-16T08:01:30.000Z",
                "origin": {"kind": "task-notification"}, "message": {"content": "<task-notification/>"}}
        turn = [self._text("2026-10-16T08:01:00.000Z", LONG), note]
        self.assertEqual(provenance_ledger.reply_anchor(self.PROMPT, turn, "now"), "2026-10-16T08:01:00.000Z")
        ended = [self._text("2026-10-16T08:01:00.000Z", LONG, stop_reason="end_turn")]
        self.assertEqual(provenance_ledger.reply_anchor(self.PROMPT, ended, "now"), "2026-10-16T08:01:00.000Z")

    def test_short_status_line_does_not_move_reply_anchor(self):
        note = {"type": "user", "timestamp": "2026-10-16T08:01:30.000Z",
                "origin": {"kind": "task-notification"}, "message": {"content": "<task-notification/>"}}
        turn = [self._text("2026-10-16T08:01:00.000Z", "Reviewer launched."), note]
        self.assertEqual(provenance_ledger.reply_anchor(self.PROMPT, turn, "now"), self.PROMPT)


class FutureCap(_Home):
    def test_future_cap_and_write_time_clamp(self):
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        iso = lambda d: d.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        provenance_ledger.record(SESSION, ts=iso(now + timedelta(hours=1)), basis="far ahead")
        self.assertEqual(provenance_ledger.fresh_all(SESSION, iso(now - timedelta(minutes=5)), now), [])
        provenance_ledger.record(SESSION, ts=iso(now + timedelta(seconds=100)), basis="inside skew")
        # A prompt that arrives after the write but before the stamp: the entry is spent.
        self.assertEqual(provenance_ledger.fresh_all(SESSION, iso(now + timedelta(seconds=50)), now), [])


class AfterPass(_Home):
    """A SOURCED entry recorded after the reviewer's PASS changes the digest: the
    Stop gate finds no PASS for the new text and blocks."""

    def test_record_after_pass_blocks(self):
        import panel_fixture_seed
        reply = "The tests pass on the branch and the release note is drafted."
        rows = [
            {"type": "user", "uuid": "u1", "parentUuid": None, "sessionId": SESSION, "timestamp": PROMPT_TS,
             "message": {"role": "user", "content": "Do the tests pass?"}, "origin": {"kind": "human"}},
            {"type": "assistant", "uuid": "a1", "parentUuid": "u1", "sessionId": SESSION,
             "timestamp": "2026-10-16T08:05:00.000Z",
             "message": {"role": "assistant", "content": [{"type": "text", "text": reply}]}},
        ]
        self.transcript.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        panel_fixture_seed.seed_reply_receipt(self.tmp, SESSION, reply, "PASS",
                                              "2026-10-16T08:03:00.000Z", "a" * 17, "Reality Checker")
        provenance_ledger.record(SESSION, ts="2026-10-16T08:04:00.000Z", basis="git log")
        payload = {"session_id": SESSION, "hook_event_name": "Stop", "stop_hook_active": False,
                   "last_assistant_message": reply, "transcript_path": str(self.transcript)}
        env = dict(os.environ)
        env["CLAUDE_SESSION_ID"] = "__selftest__"  # the transcript is the clock, as in the selftest
        cp = subprocess.run([sys.executable, str(SCRIPTS / "g__stop__reply-panel.py")],
                            input=json.dumps(payload), capture_output=True, text=True, env=env)
        self.assertEqual(cp.returncode, 2, cp.stderr)
        self.assertIn("REPLY PANEL 0/1 (SOURCED)", cp.stderr)


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
