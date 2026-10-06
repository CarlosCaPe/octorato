#!/usr/bin/env python3
"""r__posttool__sent-ledger.py: PostToolUse reflex that records every message
that left, in ~/.claude/.cache/receipts/sent.jsonl (gitignored, per machine).

WHY
The outward-send gate decides BEFORE a send whether it may leave (receipts,
panel). Once a message is out, the only way back is to recall it: revoke a
WhatsApp message by its id (the support bridge's /api/revoke, the personal
MCP's revoke_message) or hold a mail inside a cancel window. Both need the id
the channel returned, and only the tool RESULT carries it. This reflex reads
the result of the same send tools the gate covers and writes one line per
message:

    {"kind": "sent", "ts", "session_id", "tool_use_id", "channel",
     "recipient", "message_id", "chat_jid", "digest", "panel_receipt", "ok"}

channel        gmail | wa-personal | wa-support
recipient      the chat / phone, or the mail's to+cc+bcc (a reply or forward
               also carries `reply_to`, the message it answers)
text           the normalized text of a WhatsApp message (both channels), so
               the gate can find a chat-validation message by its content
message_id     what the tool returned: Gmail `id`, the personal bridge's
               "[message_id=... chat_jid=...]" status, the support bridge's
               JSON `message_id`; "" when the result carries none
digest         panel_digest.py of what was sent
panel_receipt  entry uuid of the PASS panel receipt that decided that digest;
               a receipt named here with ok not false is SPENT (one send each),
               and tool_use_id is the send that spent it
ok             the channel's own success flag (true/false), null when absent
chat_release   the chat-validated release key (chat, validation message,
               approval) when an approver's yes released this send; once
               written with ok not false, that approval is spent

A recall step is a separate spec; this file only keeps the trail. A reflex,
not a gate: it never blocks and fails open on every error, because a ledger
that cannot be written must never turn a sent message into an error.

Selftest: `--selftest [fixture_dir]` replays registry/fixtures/FLOW.sent-
message-ledger/posttool_*.json in a throwaway HOME and compares the written
lines with each case's expect_*.json.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

_SEND_TOOL = re.compile(
    r"(send_email|send_message|send_file|send_audio_message|__reply$|__forward$)", re.IGNORECASE)
_WA_STATUS = re.compile(r"message_id=([^\s\]]+)(?:\s+chat_jid=([^\s\]]*))?")


def _objects(value, out: list, depth: int = 0) -> None:
    """Every dict reachable in a tool result; JSON held in strings (an MCP text
    block, a Bash stdout line) is parsed too."""
    if depth > 6:
        return
    if isinstance(value, dict):
        out.append(value)
        for v in value.values():
            _objects(v, out, depth + 1)
    elif isinstance(value, list):
        for v in value:
            _objects(v, out, depth + 1)
    elif isinstance(value, str):
        s = value.strip()
        candidates = [s] if s[:1] in "{[" else []
        candidates += [ln.strip() for ln in s.splitlines() if ln.strip()[:1] == "{"]
        for c in candidates:
            try:
                _objects(json.loads(c), out, depth + 1)
            except ValueError:
                continue


def _ok(objs: list):
    flags = [o["success"] for o in objs if isinstance(o.get("success"), bool)]
    if not flags:
        return None
    return all(flags)


def _channel(tool_name: str) -> str:
    if tool_name == "Bash":
        return "wa-support"
    if "whatsapp" in tool_name.lower():
        return "wa-personal"
    return "gmail"


def records_for(data: dict) -> list:
    """The sent lines one PostToolUse payload yields ([] when it is not a
    message send)."""
    tool_name = str(data.get("tool_name", ""))
    tool_input = data.get("tool_input") or {}
    # Every Bash call reaches this reflex: leave before any import unless the
    # command can name the support bridge at all.
    if tool_name == "Bash" and "wa-soporte" not in str((tool_input or {}).get("command", "")):
        # (a raw bridge send never gets here: the gate denies it)
        return []
    import panel_digest
    import receipt_ledger
    response = data.get("tool_response")
    session_id = str(data.get("session_id") or "")
    base = {"session_id": session_id, "tool_use_id": str(data.get("tool_use_id") or ""),
            "channel": _channel(tool_name)}
    objs: list = []
    _objects(response, objs)

    if tool_name == "Bash":
        try:
            sends = panel_digest.support_sends(str((tool_input or {}).get("command", "")))
        except panel_digest.PanelDigestError:
            return []
        if not sends:
            return []
        ids = [o for o in objs if o.get("message_id")]
        out = []
        for i, (recipient, message, archivo) in enumerate(sends):
            hit = ids[i] if len(ids) == len(sends) else (ids[-1] if len(sends) == 1 and ids else {})
            try:
                d = panel_digest.digest(message, [panel_digest.file_sha256(archivo)] if archivo else [],
                                        [recipient])
            except panel_digest.PanelDigestError:
                d = ""
            out.append(dict(base, recipient=recipient, message_id=str(hit.get("message_id") or ""),
                            chat_jid=str(hit.get("chat_jid") or ""), digest=d, ok=_ok(objs),
                            text=panel_digest.normalize(message)))
    elif _SEND_TOOL.search(tool_name):
        try:
            digests = panel_digest.digests_for(tool_name, tool_input)
        except panel_digest.PanelDigestError:
            digests = [""]
        mid, jid = "", ""
        if base["channel"] == "wa-personal":
            for o in objs:
                m = _WA_STATUS.search(str(o.get("message") or ""))
                if m:
                    mid, jid = m.group(1), m.group(2) or ""
            if not mid and isinstance(response, str):
                m = _WA_STATUS.search(response)
                if m:
                    mid, jid = m.group(1), m.group(2) or ""
            recipient = str(tool_input.get("recipient") or "")
        else:
            for o in objs:
                if isinstance(o.get("id"), str) and o.get("id"):
                    mid = o["id"]
                    break
            people = []
            for key in ("to", "cc", "bcc"):
                v = tool_input.get(key)
                people += v if isinstance(v, list) else ([v] if v else [])
            recipient = ",".join(str(p) for p in people)
        rec = dict(base, recipient=recipient, message_id=mid, chat_jid=jid,
                   digest=digests[0], ok=_ok(objs))
        if base["channel"] == "wa-personal":
            rec["text"] = panel_digest.normalize(str(tool_input.get("message") or ""))
        if tool_input.get("messageId"):
            rec["reply_to"] = str(tool_input["messageId"])
        out = [rec]
    else:
        return []

    now = _now(data)
    for rec in out:
        r = receipt_ledger.panel_pass_for(rec["digest"], session_id, now) if rec["digest"] else None
        rec["panel_receipt"] = str((r or {}).get("entry_uuid") or "")
    key = _chat_release_key(data)
    if key:
        for rec in out:
            rec["chat_release"] = key
    return out


def _chat_release_key(data: dict) -> str:
    """The chat-validated release key the gate would honour for this send
    ("" when none): written on the send's line, it spends that approval. The
    gate is loaded by path, so this reads the same function the gate ran."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_outward_send_gate", str(_HERE / "g__pretool-mcp__outward-send.py"))
        gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gate)
        return gate.chat_release(data)[1]
    except Exception:
        return ""


def _now(data: dict):
    """Wall clock, except under selftest, where the payload's own `now` is the
    clock so a seeded receipt stays inside its window."""
    import receipt_ledger
    if os.environ.get("CLAUDE_SESSION_ID") == receipt_ledger.SELFTEST_SESSION and data.get("_now"):
        return _dt.datetime.fromisoformat(str(data["_now"]).replace("Z", "+00:00"))
    return _dt.datetime.now(_dt.timezone.utc)


def main() -> int:
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        return 0
    try:
        import receipt_ledger
        for rec in records_for(data):
            receipt_ledger.append_sent(rec)
    except Exception:
        return 0
    return 0


def _selftest(fixture_dir: str) -> int:
    import shutil
    import subprocess
    import tempfile
    fdir = Path(fixture_dir)
    if not fdir.is_absolute():
        fdir = (_HERE.parent / fdir).resolve()
    cases = sorted(fdir.glob("posttool_*.json"))
    if not cases:
        print(f"selftest FAIL: no posttool_*.json in {fdir}", file=sys.stderr)
        return 1
    failures = []
    for case in cases:
        sandbox = Path(tempfile.mkdtemp(prefix="sent-ledger-"))
        try:
            if (fdir / "home").is_dir():
                shutil.copytree(fdir / "home", sandbox, dirs_exist_ok=True)
            env = dict(os.environ, HOME=str(sandbox), USERPROFILE=str(sandbox),
                       CLAUDE_SESSION_ID="__selftest__")
            subprocess.run([sys.executable, str(Path(__file__).resolve())],
                           input=case.read_text(encoding="utf-8"), capture_output=True,
                           text=True, cwd=str(sandbox), env=env, timeout=30)
            ledger = sandbox / ".claude" / ".cache" / "receipts" / "sent.jsonl"
            got = [json.loads(ln) for ln in ledger.read_text(encoding="utf-8").splitlines()
                   if ln.strip()] if ledger.exists() else []
            want = json.loads((fdir / case.name.replace("posttool_", "expect_")).read_text(encoding="utf-8"))
            if len(got) != len(want):
                failures.append(f"{case.name}: {len(got)} line(s) written, expected {len(want)}")
                continue
            for g, w in zip(got, want):
                bad = {k: (g.get(k), v) for k, v in w.items() if g.get(k) != v}
                if bad:
                    failures.append(f"{case.name}: {bad}")
                if g.get("kind") != "sent" or not g.get("ts"):
                    failures.append(f"{case.name}: line lacks kind/ts")
        finally:
            shutil.rmtree(sandbox, ignore_errors=True)
    if failures:
        print("selftest FAIL: " + "; ".join(failures), file=sys.stderr)
        return 1
    print(f"selftest PASS: {len(cases)} case(s) (r__posttool__sent-ledger.py vs {fdir.name})")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        i = sys.argv.index("--selftest")
        sys.exit(_selftest(sys.argv[i + 1] if len(sys.argv) > i + 1
                           else "registry/fixtures/FLOW.sent-message-ledger"))
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
