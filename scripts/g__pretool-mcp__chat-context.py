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

import hashlib
import json
import re
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


def _query_tail(db_path: str, jids: list[str]) -> list[tuple]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        marks = ",".join("?" for _ in jids)
        return con.execute(
            "SELECT timestamp, is_from_me, content FROM messages "
            f"WHERE chat_jid IN ({marks}) AND content != '' "
            "ORDER BY timestamp DESC LIMIT ?",
            (*jids, TAIL_LIMIT),
        ).fetchall()
    finally:
        con.close()


def _chat_tail(jids: list[str]) -> str:
    """Merged recent history across the chat's JIDs, oldest first. '' if unreadable."""
    src = _store_dir() / "messages.db"
    if not src.exists():
        return ""
    rows = None
    try:
        # WAL readers don't block the bridge's writer: read the live file first
        # (a copy of only the main file would MISS committed rows still in -wal).
        rows = _query_tail(str(src), jids)
    except sqlite3.Error:
        # locked / rollback-journal mode: fall back to copying db + sidecars
        tmpdir = None
        try:
            tmpdir = tempfile.mkdtemp(prefix="chat-context-")
            dst = Path(tmpdir) / "messages.db"
            shutil.copyfile(src, dst)
            for ext in ("-wal", "-shm"):
                side = Path(str(src) + ext)
                if side.exists():
                    shutil.copyfile(side, str(dst) + ext)
            rows = _query_tail(str(dst), jids)
        except (sqlite3.Error, OSError):
            return ""
        finally:
            if tmpdir:
                shutil.rmtree(tmpdir, ignore_errors=True)
    except OSError:
        return ""
    lines = []
    for ts, mine, content in reversed(rows or []):
        who = "YO" if mine else "CHAT"
        text = " ".join(str(content).split())[:160]
        lines.append(f"[{str(ts)[:16]}] {who}: {text}")
    return "\n".join(lines)


def _deny(reason: str) -> bool:
    try:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }))
        return True
    except OSError:
        return False


_SAFE_KEY_RE = re.compile(r"^[0-9-]+\Z")


def _sentinel_key(raw: str, recipient: str) -> str:
    """Filename-safe sentinel key. recipient is MODEL-CONTROLLED: anything outside
    plain digits/hyphens (group jids) is hashed so it can never become a path."""
    if _SAFE_KEY_RE.match(raw):
        return raw
    return hashlib.sha256(recipient.encode("utf-8")).hexdigest()[:20]


def _write_sentinel(sentinel: Path, recipient: str) -> None:
    try:
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        sentinel.write_text(json.dumps({"ts": time.time(), "recipient": recipient}))
    except OSError:
        pass  # gate fires again next attempt; a repeat deny is the safe failure


# crash-handler breadcrumb: lets the fail-closed wrapper arm the block-once
# sentinel for the REAL chat, so a gate bug denies once instead of livelocking
_CRASH_STATE: dict = {"sentinel": None, "recipient": ""}


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
        key, jids = _sentinel_key(digits, recipient), [recipient]
    else:
        pn, lid = _lid_pair(digits, recipient.endswith("@lid"))
        key = _sentinel_key(pn, recipient)
        # always include the literal recipient JID: an unresolved @lid must still
        # query its own chat, never only a fabricated @s.whatsapp.net twin
        jids = sorted({recipient if "@" in recipient else f"{pn}@s.whatsapp.net",
                       f"{pn}@s.whatsapp.net"}
                      | ({f"{lid}@lid"} if lid else set()))

    sentinel = _sentinel_dir() / f"{key}.json"
    _CRASH_STATE["sentinel"], _CRASH_STATE["recipient"] = sentinel, recipient
    try:
        age = time.time() - json.loads(sentinel.read_text())["ts"]
        if age < TTL_SECONDS:
            return  # context already loaded for this chat window
    except (OSError, ValueError, KeyError):
        pass

    tail = _chat_tail(jids)
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
    if _deny(body):
        # sentinel only after the deny reached stdout: a swallowed deny must NOT
        # arm the pass-through for the next attempt
        _write_sentinel(sentinel, recipient)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from gate_selftest import run_gate_selftest
        fixtures = sys.argv[2] if len(sys.argv) > 2 else \
            "registry/fixtures/COMMS.chat-context-before-send"
        raise SystemExit(run_gate_selftest(__file__, fixtures))
    try:
        main()
    except Exception:
        # fail-CLOSED on unexpected crashes: a gate bug degrades to block-once,
        # never to a silent bypass. Arm the real chat's sentinel when known so
        # the retry passes; unknown sentinel -> the deny warns it may repeat.
        try:
            known = _CRASH_STATE["sentinel"] is not None
            _deny("CHAT-CONTEXT GATE: error interno del gate. Lee el chat destino "
                  "manualmente (ambos JIDs) y reenvia; "
                  + ("el reintento pasa." if known else
                     "si el bloqueo se repite, avisa al operador (bug del gate)."))
            if known:
                _write_sentinel(_CRASH_STATE["sentinel"], _CRASH_STATE["recipient"])
        except Exception:
            pass
    raise SystemExit(0)
