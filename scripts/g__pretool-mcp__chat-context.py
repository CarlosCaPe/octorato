#!/usr/bin/env python3
"""g__pretool-mcp__chat-context.py: PreToolUse gate for COMMS.chat-context-before-send.

Entering a live chat without loading its history is the no-context-chatbot
failure: the message ignores what was already said in the thread, and the
operator has to correct it. This gate makes the read involuntary.

Rule: the FIRST outbound WhatsApp message to a given conversation inside a TTL
window is DENIED once, and the deny carries the merged tail of the chat so the
model re-reads before re-issuing (or correcting) the send. WhatsApp contacts
live under TWO JIDs post-@lid-migration (phone@s.whatsapp.net holds our sends,
NNN@lid holds their replies); the tail merges BOTH via whatsmeow_lid_map, so a
one-JID read cannot fake coverage.

Block-once mechanics: the deny writes a per-chat sentinel (TTL 30 min); the
re-issued send passes. Infra errors (missing bridge DB) do NOT bypass the gate:
the deny still fires with a "history unavailable, read the chat another way"
note - the rule is about reading context, not about this DB being up.

State lives under $HOME so the gate_selftest sandbox can seed it:
  ~/.cache/octorato/chat-context/<key>.json    sentinel (block-once marker)
  ~/.config/whatsapp-mcp/store/messages.db     bridge history (optional)
  ~/.config/whatsapp-mcp/store/whatsapp.db     whatsmeow_lid_map (optional)

Stdin:  {"tool_name": str, "tool_input": {"recipient": str, "message": str}}
Stdout: PreToolUse deny JSON on first-send-without-context; nothing on pass.
Exit:   always 0 (the deny travels in the JSON, not the exit code).
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

TOOL = "mcp__whatsapp__send_message"
TTL_SECONDS = 1800
TAIL_LIMIT = 14


def _home() -> Path:
    return Path.home()


def _sentinel_dir() -> Path:
    return _home() / ".cache" / "octorato" / "chat-context"


def _store_dir() -> Path:
    return _home() / ".config" / "whatsapp-mcp" / "store"


def _lid_pair(digits: str, is_lid: bool) -> tuple[str, str | None]:
    """Resolve (pn, lid) via whatsmeow_lid_map; missing map -> (digits, None)."""
    db = _store_dir() / "whatsapp.db"
    if not db.exists():
        return digits, None
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            if is_lid:
                row = con.execute(
                    "SELECT pn FROM whatsmeow_lid_map WHERE lid = ?", (digits,)
                ).fetchone()
                return (row[0], digits) if row else (digits, None)
            row = con.execute(
                "SELECT lid FROM whatsmeow_lid_map WHERE pn = ?", (digits,)
            ).fetchone()
            return digits, (row[0] if row else None)
        finally:
            con.close()
    except sqlite3.Error:
        return digits, None


def _chat_tail(jids: list[str]) -> str:
    """Merged recent history across the chat's JIDs, oldest first. '' if unreadable."""
    src = _store_dir() / "messages.db"
    if not src.exists():
        return ""
    tmp = None
    try:
        # copy first: the Go bridge holds the write lock on the live DB
        fd, tmp = tempfile.mkstemp(suffix=".db")
        Path(tmp).unlink()
        shutil.copyfile(src, tmp)
        con = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
        try:
            marks = ",".join("?" for _ in jids)
            rows = con.execute(
                "SELECT timestamp, is_from_me, content FROM messages "
                f"WHERE chat_jid IN ({marks}) AND content != '' "
                "ORDER BY timestamp DESC LIMIT ?",
                (*jids, TAIL_LIMIT),
            ).fetchall()
        finally:
            con.close()
        lines = []
        for ts, mine, content in reversed(rows):
            who = "YO" if mine else "CHAT"
            text = " ".join(str(content).split())[:160]
            lines.append(f"[{str(ts)[:16]}] {who}: {text}")
        return "\n".join(lines)
    except (sqlite3.Error, OSError):
        return ""
    finally:
        if tmp:
            Path(tmp).unlink(missing_ok=True)


def _deny(reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    if data.get("tool_name") != TOOL:
        return
    recipient = str((data.get("tool_input") or {}).get("recipient") or "")
    if not recipient:
        return
    digits = recipient.split("@", 1)[0]

    if recipient.endswith("@g.us"):
        key, jids = digits, [recipient]
    else:
        pn, lid = _lid_pair(digits, recipient.endswith("@lid"))
        key = pn
        jids = [f"{pn}@s.whatsapp.net"] + ([f"{lid}@lid"] if lid else [])

    sentinel = _sentinel_dir() / f"{key}.json"
    try:
        age = time.time() - json.loads(sentinel.read_text())["ts"]
        if age < TTL_SECONDS:
            return  # context already loaded for this chat window
    except (OSError, ValueError, KeyError):
        pass

    tail = _chat_tail(jids)
    try:
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        sentinel.write_text(json.dumps({"ts": time.time(), "recipient": recipient}))
    except OSError:
        pass  # deny still fires; worst case it fires again next attempt

    body = (
        f"CHAT-CONTEXT GATE (bloquea 1 vez por chat cada {TTL_SECONDS // 60} min): "
        f"primer envio a {recipient} sin haber cargado su historial. "
        f"JIDs del hilo: {', '.join(jids)}.\n"
    )
    if tail:
        body += "Tail reciente del chat (ambos JIDs, viejo->nuevo):\n" + tail + "\n"
    else:
        body += ("Historial NO disponible (bridge DB ilegible): lee el chat por otra via "
                 "antes de reenviar.\n")
    body += ("Si tras leer el contexto tu mensaje sigue siendo correcto, reenvialo tal "
             "cual (este segundo intento pasa); si el contexto lo cambia, corrigelo primero.")
    _deny(body)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from gate_selftest import run_gate_selftest
        fixtures = sys.argv[2] if len(sys.argv) > 2 else \
            "registry/fixtures/COMMS.chat-context-before-send"
        raise SystemExit(run_gate_selftest(__file__, fixtures))
    try:
        main()
    except Exception:  # fail-open only on truly unexpected crashes
        pass
    raise SystemExit(0)
