#!/usr/bin/env python3
"""Tests for the reply panel's status-line exemption (FLOW.panel-before-reply).

Pins status_claim (outcome words in EN, ES, DE and digits outside a
provenance line make a status line a claim) and pending_agents (background
launches, SendMessage resumes, hand-backs, task notifications, TaskStop, the
compact-summary reset and the 120-minute window). The end-to-end cases live
in registry/fixtures/FLOW.panel-before-reply (ac24).

Stdlib only:

    python3 -m unittest scripts.tests.test_reply_panel_status_line
"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
GATE = SCRIPTS / "g__stop__reply-panel.py"


def _load_gate():
    spec = importlib.util.spec_from_file_location("reply_panel_gate_sl", GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RP = _load_gate()
CTX = RP.load()


def _ts(t):
    return f"2026-10-14T{t}.000Z"


def _agent(t, tid):
    return {"type": "assistant", "timestamp": _ts(t), "message": {"content": [
        {"type": "tool_use", "id": tid, "name": "Agent", "input": {"subagent_type": "Code Reviewer", "prompt": "x"}}]}}


def _ack(t, tid, agent):
    return {"type": "user", "timestamp": _ts(t), "toolUseResult": {"isAsync": True, "agentId": agent},
            "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "content": "launched"}]}}


def _send(t, tid, to):
    return {"type": "assistant", "timestamp": _ts(t), "message": {"content": [
        {"type": "tool_use", "id": tid, "name": "SendMessage", "input": {"to": to, "message": "round 2"}}]}}


def _sendres(t, tid, ok=True):
    return {"type": "user", "timestamp": _ts(t), "toolUseResult": {"success": ok, "resumedAgentId": "x"},
            "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "content": "{}"}]}}


def _handback(t, agent):
    return {"type": "attachment", "timestamp": _ts(t), "attachment": {
        "type": "queued_command", "origin": {"kind": "peer", "from": agent}}}


def _notification(t, tid):
    return {"type": "user", "timestamp": _ts(t), "origin": {"kind": "task-notification"},
            "message": {"content": f"<task-notification><tool-use-id>{tid}</tool-use-id></task-notification>"}}


def _taskstop(t, task):
    return {"type": "assistant", "timestamp": _ts(t), "message": {"content": [
        {"type": "tool_use", "id": "k" + task, "name": "TaskStop", "input": {"task_id": task}}]}}


def _summary(t):
    return {"type": "user", "timestamp": _ts(t), "isCompactSummary": True, "message": {"content": "summary"}}


class PendingAgentsTests(unittest.TestCase):
    def pend(self, rows, now="10:00:00"):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8") as fh:
            fh.write("".join(json.dumps(r) + "\n" for r in rows))
        try:
            return RP.pending_agents(CTX, fh.name, CTX.send._ts(_ts(now)))
        finally:
            Path(fh.name).unlink()

    def test_async_launch_is_pending(self):
        self.assertEqual(self.pend([_agent("09:50:00", "t1"), _ack("09:50:01", "t1", "a1")]), ["a1"])

    def test_handback_ends_it(self):
        self.assertEqual(self.pend([_agent("09:50:00", "t1"), _ack("09:50:01", "t1", "a1"),
                                    _handback("09:51:00", "a1")]), [])

    def test_sendmessage_resume_is_pending_again(self):
        rows = [_agent("09:50:00", "t1"), _ack("09:50:01", "t1", "a1"), _handback("09:51:00", "a1"),
                _send("09:52:00", "s1", "a1"), _sendres("09:52:01", "s1")]
        self.assertEqual(self.pend(rows), ["a1"])

    def test_failed_sendmessage_is_not_pending(self):
        rows = [_agent("09:50:00", "t1"), _ack("09:50:01", "t1", "a1"), _handback("09:51:00", "a1"),
                _send("09:52:00", "s1", "a1"), _sendres("09:52:01", "s1", ok=False)]
        self.assertEqual(self.pend(rows), [])

    def test_notification_ends_it_by_call_id(self):
        self.assertEqual(self.pend([_agent("09:50:00", "t1"), _ack("09:50:01", "t1", "a1"),
                                    _notification("09:51:00", "t1")]), [])

    def test_taskstop_ends_it(self):
        self.assertEqual(self.pend([_agent("09:50:00", "t1"), _ack("09:50:01", "t1", "a1"),
                                    _taskstop("09:51:00", "a1")]), [])

    def test_sync_agent_is_never_pending(self):
        sync = {"type": "user", "timestamp": _ts("09:51:00"), "toolUseResult": {"isAsync": False},
                "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "done"}]}}
        self.assertEqual(self.pend([_agent("09:50:00", "t1"), sync]), [])

    def test_older_than_window_is_not_pending(self):
        self.assertEqual(self.pend([_agent("07:00:00", "t1"), _ack("07:00:01", "t1", "a1")]), [])

    def test_compact_summary_resets(self):
        self.assertEqual(self.pend([_agent("09:50:00", "t1"), _ack("09:50:01", "t1", "a1"),
                                    _summary("09:55:00")]), [])

    def test_only_unfinished_of_several(self):
        rows = [_agent("09:50:00", "t1"), _ack("09:50:01", "t1", "a1"),
                _agent("09:50:02", "t2"), _ack("09:50:03", "t2", "a2"), _handback("09:51:00", "a1")]
        self.assertEqual(self.pend(rows), ["a2"])


class StatusClaimTests(unittest.TestCase):
    CLEAN = ["Waiting for the reviewers.", "Panel running.", "Reviewers still running.",
             "Esperando la segunda ronda de los revisores.", "Los tres revisores siguen trabajando.",
             "Siguen trabajando dos revisores, el de hechos y el de dominio.",
             "El revisor está verificando la respuesta.", "Die Prüfer laufen noch.",
             "Esperando.\n\nProcedencia: Basis /tmp/claude-1000/x/panel_block.txt", "​"]
    CLAIMS = ["Two of three reviewers have passed.", "PR merged, waiting on QA.", "Done.",
              "Sent the email; waiting on the reviewer.", "Codex found no regressions.",
              "Las correcciones están hechas.", "Listo, falta el revisor.", "Mandé el correo.",
              "Codex no encontró regresiones.", "Alles erledigt.", "Waiting on 2 reviewers.",
              "Test suite NEEDS-WORK, re-running."]

    def test_clean_lines_carry_no_claim(self):
        for t in self.CLEAN:
            with self.subTest(text=t):
                self.assertEqual(RP.status_claim(t), "")

    def test_claims_are_caught(self):
        for t in self.CLAIMS:
            with self.subTest(text=t):
                self.assertNotEqual(RP.status_claim(t), "")


if __name__ == "__main__":
    unittest.main()
