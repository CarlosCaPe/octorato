#!/usr/bin/env python3
"""receipt_ledger.py: the v7 receipt ledger (shared library, not a hook).

THE CONTRACT IT SERVES
"Nothing ships unverified" (docs/architecture/v7-nothing-ships-unverified.md):
an outward action is allowed only when the turn carries machine receipts. A
receipt is written by a HOOK running in the harness process, never typed by
the model, and every consumer re-verifies it against something the model does
not own before trusting it:

  seek receipt     written by r__posttool__receipt-seek.py after a chat, mail
                   or memory lookup. Verified against the session transcript:
                   the receipt's tool_use_id must be a tool_use block in the
                   CURRENT turn. The transcript is harness-owned, so a receipt
                   the model appended by hand names no real tool_use and is
                   ignored.
  gate receipt     written by brain_doctor when gate-liveness PASSES, carrying
                   the brain's git HEAD. Verified by comparing that HEAD to the
                   live one: a receipt from an older tree proves nothing about
                   the gates now on disk.
  qa receipt       written by r__subagent-stop__qa-receipt.py when a subagent
                   ends with a QA-VERDICT line. Carries the agent transcript
                   path so the consumer can re-read the verdict from the file
                   the harness wrote.

Residual, stated plainly: the model can write to any file under $HOME through
Bash, this ledger included. What it cannot do is make the transcript contain a
tool_use it never made, move the brain's HEAD, or produce a subagent transcript
the harness did not write. Every consumer therefore anchors on those, and the
ledger line is only the pointer. Same stance as qa-merge-gate: the env and the
harness are the boundary, the file is the audit trail.

Layout (gitignored, per machine):
  ~/.claude/.cache/receipts/<session_id>.jsonl   seek receipts for one session
  ~/.claude/.cache/receipts/global.jsonl         gate-liveness + qa receipts

A line is JSON: {"kind": ..., "ts": ISO-8601 UTC, ...fields}.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
from pathlib import Path

SELFTEST_SESSION = "__selftest__"   # set by gate_selftest.py, never by the model
SELFTEST_HEAD = "SELFTEST"


def receipts_dir() -> Path:
    return Path(os.path.expanduser("~")) / ".claude" / ".cache" / "receipts"


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name or "")[:120] or "unknown"


def session_path(session_id: str) -> Path:
    return receipts_dir() / f"{_safe(session_id)}.jsonl"


def global_path() -> Path:
    return receipts_dir() / "global.jsonl"


def _append(path: Path, record: dict) -> None:
    record = dict(record)
    record.setdefault("ts", _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def append_session(session_id: str, record: dict) -> None:
    _append(session_path(session_id), record)


def append_global(record: dict) -> None:
    _append(global_path(), record)


def _read(path: Path, max_bytes: int = 1 << 20) -> list:
    out = []
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - max_bytes))
            for line in fh.read().decode("utf-8", errors="replace").splitlines():
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    out.append(obj)
    except OSError:
        pass
    return out


def read_session(session_id: str) -> list:
    return _read(session_path(session_id))


def read_global() -> list:
    return _read(global_path())


# --------------------------------------------------------------------------
# Transcript anchoring
# --------------------------------------------------------------------------

def _tail_lines(path: str, max_bytes: int = 262144) -> list:
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        fh.seek(max(0, size - max_bytes))
        return fh.read().decode("utf-8", errors="replace").splitlines()


def turn_tool_uses(transcript_path: str) -> list:
    """[(tool_use_id, tool_name)] for every tool_use since the last HUMAN prompt.

    A tool RESULT is also a type "user" entry; the walk must not stop there
    (measured on a real session: 656 of 764 user entries are results). This is
    the same walk the Stop gates use, so "the turn" means one thing brain-wide.
    """
    try:
        lines = _tail_lines(transcript_path)
    except OSError:
        return []
    uses = []
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") == "user":
            content = (entry.get("message") or {}).get("content")
            if isinstance(content, list) and any(
                    isinstance(b, dict) and b.get("type") == "tool_result"
                    for b in content):
                continue
            break
        if entry.get("type") != "assistant":
            continue
        content = (entry.get("message") or {}).get("content") or []
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                uses.append((str(block.get("id", "")), str(block.get("name", ""))))
    return uses


def seek_receipts_in_turn(session_id: str, transcript_path: str) -> list:
    """Seek receipts of this session whose tool_use_id is a real tool_use in the
    current turn. A receipt without an id (older harness) counts only when its
    tool_name appears in the turn."""
    uses = turn_tool_uses(transcript_path)
    ids = {u for u, _ in uses if u}
    names = {n for _, n in uses if n}
    hits = []
    for r in read_session(session_id):
        if r.get("kind") != "seek":
            continue
        tid = r.get("tool_use_id")
        if tid:
            if tid in ids:
                hits.append(r)
        elif r.get("tool_name") in names:
            hits.append(r)
    return hits


# --------------------------------------------------------------------------
# Gate receipt
# --------------------------------------------------------------------------

def brain_head(brain_dir: Path) -> str:
    """git HEAD of the brain checkout; "" when unavailable."""
    import subprocess
    try:
        cp = subprocess.run(["git", "-C", str(brain_dir), "rev-parse", "HEAD"],
                            capture_output=True, text=True, timeout=5)
        return cp.stdout.strip() if cp.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def gate_receipt_ok(head: str) -> bool:
    """A gate-liveness PASS was recorded for exactly this HEAD."""
    if not head:
        return False
    for r in read_global():
        if r.get("kind") == "gate-liveness" and r.get("ok") and r.get("head") == head:
            return True
    return False


# --------------------------------------------------------------------------
# QA receipt
# --------------------------------------------------------------------------

_VERDICT = re.compile(r"QA-VERDICT\s*:\s*(PASS|FAIL|NEEDS[ -]WORK)", re.IGNORECASE)
_SCOPE = re.compile(r"QA-SCOPE\s*:\s*([^\n]+)", re.IGNORECASE)


def parse_verdict(text: str) -> tuple:
    """(verdict, scope) from a QA agent's final message, or ("", "")."""
    if not text:
        return "", ""
    vm = _VERDICT.search(text)
    sm = _SCOPE.search(text)
    verdict = vm.group(1).upper().replace(" ", "-") if vm else ""
    scope = sm.group(1).strip() if sm else ""
    return verdict, scope


def qa_pass_for(token: str) -> dict | None:
    """Most recent PASS receipt whose scope names `token` (a PR number like
    '#260' or '260', a branch, a sha) AND whose agent transcript still carries
    the verdict. The transcript re-read is the anchor: the ledger line alone is
    a pointer the model could have typed."""
    if not token:
        return None
    want = {token, f"#{token}", f"PR #{token}", f"PR#{token}"}
    for r in reversed(read_global()):
        if r.get("kind") != "qa" or r.get("verdict") != "PASS":
            continue
        scope = str(r.get("scope", ""))
        if not any(w in scope for w in want):
            continue
        tp = r.get("agent_transcript_path") or ""
        if tp and os.path.exists(tp):
            try:
                text = Path(tp).read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            if "QA-VERDICT" in text and "PASS" in text:
                return r
            continue
        return None
    return None
