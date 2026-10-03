#!/usr/bin/env python3
"""chat_release_fixture_seed.py: build the fixtures of FLOW.chat-validated-release.

The chat-validated release (g__pretool-mcp__outward-send.py, chat_release) reads
five things a fixture has to hold at once: the private allowlist with
`approvers`, the personal bridge store, the sent ledger, a PASS panel receipt
per send and the gate receipt. Writing them by hand drifts (a digest changes,
a timestamp moves), so this script rebuilds the whole directory from the CASES
table below. Every id is synthetic and exists nowhere: chats 120363900000000NNN,
approver 10000000000001, a non-approver 20000000000002, the operator's own
phone 34600000000, mail at example.test.

Each payload carries `_expect`, the substring its deny reason must hold (""
for a benign case); scripts/tests/test_chat_release.py checks it, the selftest
harness ignores it.

Timeline of a case (the operator turn at 12:00 is the selftest clock): panel
receipt 11:55, validation message V 11:57, approval 11:58. A case overrides
what it needs.

Usage: chat_release_fixture_seed.py [fixture_dir]   (default: the rule's dir)
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import panel_digest  # noqa: E402
import panel_fixture_seed  # noqa: E402

DAY = "2026-10-03"
HUMAN_TS = f"{DAY}T12:00:00.000Z"
APPROVER = "10000000000001"
OTHER = "20000000000002"
OPERATOR = "34600000000"
PROMPT = "revisa el grupo de validación y atiende lo pendiente"


def _jid(n: int) -> str:
    return f"120363900000000{n:03d}@g.us"


def _mail(n: int, to: str = "office@example.test") -> dict:
    return {"to": [to], "subject": f"Solicitud {n}",
            "body": f"Buenos días, adjunto la solicitud número {n} firmada. Saludos."}


def _v_text(tin: dict, to: str) -> str:
    return (f"Para validar, este correo sale a {to}:\nAsunto: {tin['subject']}\n"
            f"{tin['body']}\n¿Lo envío?")


# name, chat, payload kind, overrides. Fields:
#   tool / tool_input      the send S (default: a Gmail send_email of _mail(n))
#   v                      sent-ledger V line overrides (None = no V line)
#   rows                   store rows (id, sender, content, "HH:MM:SS", is_from_me)
#   panel                  panel receipt time HH:MM:SS, None for no receipt
#   extra_sent             more sent-ledger lines
#   expect                 deny-reason substring ("" = allow)
CASES = [
    {"name": "benign_approved_by_approver", "n": 101,
     "rows": [("A101", APPROVER, "Sí, así envíalo @5215500000000", "11:58:00", 0)], "expect": ""},
    {"name": "benign_approved_by_operator_phone", "n": 102,
     "rows": [("A102", OPERATOR, "ok", "11:58:00", 1)], "expect": ""},
    {"name": "benign_whatsapp_third_party", "n": 103, "tool": "mcp__whatsapp__send_message",
     "tool_input": {"recipient": "5215511111103", "message": "Hola, la cita queda el martes 10:00."},
     "rows": [("A103", APPROVER, "dale!", "11:58:00", 0)], "expect": ""},
    {"name": "violation_approved_by_non_approver", "n": 104,
     "rows": [("A104", OTHER, "sí", "11:58:00", 0)],
     "expect": "not an approver"},
    {"name": "violation_approval_before_validation", "n": 105,
     "rows": [("A105", APPROVER, "envíalo", "11:56:30", 0)],
     "expect": "before the validation message"},
    {"name": "violation_approval_outside_window", "n": 106, "panel": "10:40:00",
     "v": {"ts": "10:45:00"}, "rows": [("A106", APPROVER, "mándalo", "11:50:00", 0)],
     "expect": "minutes passed"},
    {"name": "violation_retraction_after_approval", "n": 107,
     "rows": [("A107", APPROVER, "ok", "11:58:00", 0),
              ("R107", APPROVER, "espera, no lo mandes todavía", "11:59:00", 0)],
     "expect": "took the approval back"},
    {"name": "violation_validation_body_differs", "n": 108,
     "v": {"text": "Para validar, sale a office@example.test: Asunto: Solicitud 108 "
                   "Buenos días, adjunto la solicitud número 999 firmada. Saludos."},
     "rows": [("A108", APPROVER, "sí", "11:58:00", 0)],
     "expect": "does not quote"},
    {"name": "violation_recipient_not_named", "n": 109,
     "v": {"text": "Para validar: Solicitud 109 Buenos días, adjunto la solicitud número 109 "
                   "firmada. Saludos."},
     "rows": [("A109", APPROVER, "sí", "11:58:00", 0)],
     "expect": "does not name office@example.test"},
    {"name": "violation_second_send_reuses_approval", "n": 110,
     "rows": [("A110", APPROVER, "sí", "11:58:00", 0)],
     "extra_sent": [{"channel": "gmail", "recipient": "office@example.test", "message_id": "G110",
                     "chat_release": f"{_jid(110)}|V110|A110", "ok": True, "ts": "11:59:00"}],
     "expect": "already released a send"},
    {"name": "violation_deploy_with_approval", "n": 111, "tool": "Bash",
     "tool_input": {"command": "npx wrangler deploy"}, "panel": None, "v": None,
     "rows": [("A111", APPROVER, "sí", "11:58:00", 0)],
     "expect": "deploys and releases are never released"},
    {"name": "violation_ambiguous_reply", "n": 112,
     "rows": [("A112", APPROVER, "sí pero cambia el asunto", "11:58:00", 0)],
     "expect": "not on the closed yes-list"},
    {"name": "violation_store_missing", "n": 113, "rows": [],
     "expect": "support bridge replica is missing"},
    {"name": "violation_validation_before_panel", "n": 114, "v": {"ts": "11:50:00"},
     "rows": [("A114", APPROVER, "sí", "11:58:00", 0)],
     "expect": "posted before the panel receipt"},
    {"name": "violation_agent_own_yes", "n": 115,
     "rows": [("A115", OPERATOR, "ok", "11:58:00", 1)],
     "extra_sent": [{"channel": "wa-personal", "recipient": _jid(115), "message_id": "A115",
                     "text": "ok", "ok": True, "ts": "11:58:05"}],
     "expect": "no approver replied yes"},
]


def _ts(hms: str) -> str:
    return f"{DAY}T{hms}+00:00"


def build(fdir: Path) -> int:
    home = fdir / "home"
    if fdir.exists():
        for p in fdir.iterdir():
            if p.is_dir():
                shutil.rmtree(p)
            elif p.suffix in (".json", ".jsonl"):
                p.unlink()
    fdir.mkdir(parents=True, exist_ok=True)
    receipts = home / ".claude" / ".cache" / "receipts"
    receipts.mkdir(parents=True, exist_ok=True)
    (receipts / "global.jsonl").write_text(json.dumps(
        {"kind": "gate-liveness", "ok": True, "head": "SELFTEST", "gates": "SELFTEST",
         "ts": "2026-09-05T00:00:00+00:00"}) + "\n", encoding="utf-8")
    cfg = {"_comment": "selftest seed for FLOW.chat-validated-release; synthetic ids only",
           "chats": []}
    store_dir = home / ".config" / "whatsapp-mcp" / "store"
    store_dir.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(store_dir / "messages.db")
    con.execute("CREATE TABLE messages (id TEXT, chat_jid TEXT, sender TEXT, content TEXT, "
                "timestamp TIMESTAMP, is_from_me BOOLEAN, media_type TEXT, filename TEXT, url TEXT, "
                "media_key BLOB, file_sha256 BLOB, file_enc_sha256 BLOB, file_length INTEGER, "
                "PRIMARY KEY (id, chat_jid))")
    sent = []
    for c in CASES:
        n, jid = c["n"], _jid(c["n"])
        session = f"fx-cvr-{n}"
        tool = c.get("tool", "mcp__gmail__send_email")
        tin = c.get("tool_input") or _mail(n)
        cfg["chats"].append({"jid": jid, "label": f"fixture validation chat {n}", "since": DAY,
                             "approvers": [f"{APPROVER}@lid"], "window_minutes": 60})
        for rid, sender, content, hms, from_me in c.get("rows", []):
            con.execute("INSERT INTO messages (id, chat_jid, sender, content, timestamp, is_from_me) "
                        "VALUES (?,?,?,?,?,?)", (rid, jid, sender, content, f"{DAY} {hms}+00:00", from_me))
        to = (tin.get("to") or [tin.get("recipient", "")])[0] if isinstance(tin, dict) else ""
        if c.get("v", {}) is not None and tool != "Bash":
            if tool.startswith("mcp__whatsapp"):
                vtext = f"Para validar, este mensaje sale a {to}: {tin['message']} ¿Lo envío?"
            else:
                vtext = _v_text(tin, to)
            v = {"session_id": session, "tool_use_id": f"tv{n}", "channel": "wa-personal",
                 "recipient": jid, "message_id": f"V{n}", "chat_jid": jid, "digest": "",
                 "ok": True, "panel_receipt": "", "text": panel_digest.normalize(vtext),
                 "ts": "11:57:00"}
            v.update(c.get("v") or {})
            v["text"] = panel_digest.normalize(v["text"])
            sent.append(v)
        for extra in c.get("extra_sent", []):
            sent.append(dict({"session_id": session, "tool_use_id": f"tx{n}", "digest": "",
                              "chat_jid": "", "panel_receipt": ""}, **extra))
        payload = {"session_id": session, "tool_name": tool, "tool_input": tin, "cwd": "/home/user",
                   "transcript_path": f"{c['name']}_transcript.jsonl", "_expect": c["expect"]}
        (fdir / f"{c['name']}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                                                encoding="utf-8")
        entries = [
            {"type": "user", "message": {"role": "user", "content": PROMPT}, "uuid": f"u-cvr-{n}",
             "parentUuid": None, "sessionId": session, "timestamp": HUMAN_TS},
            {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": f"t{n}", "name": tool, "input": tin}]},
             "uuid": f"a-cvr-{n}", "parentUuid": f"u-cvr-{n}", "sessionId": session,
             "timestamp": HUMAN_TS},
        ]
        (fdir / f"{c['name']}_transcript.jsonl").write_text(
            "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries), encoding="utf-8")
        panel = c.get("panel", "11:55:00")
        if panel and tool != "Bash":
            old = os.environ.get("HOME")
            os.environ["HOME"] = str(home)
            try:
                msgs = panel_digest.message_parts(tool, tin)
            finally:
                os.environ["HOME"] = old or ""
            for i, m in enumerate(msgs):
                panel_fixture_seed.seed_receipt(home, session, m, "PASS", f"{DAY}T{panel}Z",
                                                f"cvr{n:03d}{i:02d}0000000000"[:17])
    con.commit()
    con.close()
    for s in sent:
        s["ts"] = _ts(s["ts"])
        s["kind"] = "sent"
    (receipts / "sent.jsonl").write_text(
        "".join(json.dumps(s, ensure_ascii=False) + "\n" for s in sent), encoding="utf-8")
    cfg_path = home / ".claude" / "company" / "config" / "outward-send-autonomous.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"built {len(CASES)} case(s) in {fdir}")
    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        _HERE.parent / "registry" / "fixtures" / "FLOW.chat-validated-release"
    sys.exit(build(target))
