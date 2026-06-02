#!/usr/bin/env python3
"""dimension-awareness-hook.py — PreToolUse hook for 4D session dimension awareness.

Warns when multiple Claude Code sessions (dimensions) share the same working
tree so each session avoids stomping on the other's in-progress changes.

Design principles (mirroring grafo-gate.py):
  - FAIL-OPEN always. Any exception → exit 0. A broken hook must never brick a session.
  - Fast: no subprocess calls, only JSON reads + datetime math.
  - No denied commands. This hook ONLY warns; it never blocks.
  - Output format: {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                    "additionalContext": "..."}} — same as grafo-gate.py.

Stdin: {"tool_name": str, "tool_input": {...}}
Stdout: JSON additionalContext if other live sessions exist, else nothing.
Exit: always 0.

Concurrency: reads registry with best-effort; stale/corrupted registry → no-op warn.
"""
from __future__ import annotations

import json
import os
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

REGISTRY = Path.home() / ".claude" / "connectome" / "sessions.json"
DEFAULT_TTL = 900  # seconds


# ── session id (same resolution order as octo-dim.py) ───────────────────────

def _resolve_session(payload: dict | None = None) -> str:
    """Priority: stdin payload session_id → env CLAUDE_SESSION_ID → hostname-pid."""
    if payload:
        from_payload = payload.get("session_id", "")
        if from_payload:
            return str(from_payload)
    from_env = os.environ.get("CLAUDE_SESSION_ID", "")
    if from_env:
        return from_env
    return f"{socket.gethostname()}-{os.getpid()}"


# ── registry helpers ─────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_registry() -> dict:
    try:
        with REGISTRY.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and "sessions" in data:
            return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return {"sessions": {}}


def _save_registry(data: dict) -> None:
    """Atomic write. Race window: last-writer-wins (same note as octo-dim.py)."""
    import tempfile
    registry_dir = REGISTRY.parent
    registry_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=registry_dir, prefix=".sessions.tmp.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, REGISTRY)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass


_FUTURE_SKEW = 120  # seconds; heartbeat this far ahead of now is considered NOT live


def _is_live(entry: dict, ttl: int = DEFAULT_TTL) -> bool:
    hb = entry.get("heartbeat", "")
    if not hb:
        return False
    try:
        hb_dt = datetime.fromisoformat(hb)
        if hb_dt.tzinfo is None:
            hb_dt = hb_dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = (now - hb_dt).total_seconds()
        # Heartbeat dated far in the future → clock skew / corrupt entry → not live
        if delta < -_FUTURE_SKEW:
            return False
        return delta <= ttl
    except (ValueError, TypeError):
        return False


# ── heartbeat update (best-effort) ───────────────────────────────────────────

def _update_heartbeat(sid: str) -> None:
    """Touch this session's heartbeat in the registry. Non-fatal on any error."""
    try:
        now = _now_iso()
        data = _load_registry()
        entry = data["sessions"].get(sid, {
            "session_id": sid,
            "branch": "",
            "worktree": "",
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "started": now,
            "lanes": [],
        })
        entry["heartbeat"] = now
        data["sessions"][sid] = entry
        _save_registry(data)
    except Exception:
        pass  # fail-open: heartbeat failure must never block the caller


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    # Parse stdin (same defensive pattern as grafo-gate.py)
    try:
        raw = sys.stdin.read()
        data = json.loads(raw)
    except Exception:
        return 0  # bad JSON → fail-open, no output

    tool_name = (data.get("tool_name") or "")
    tool_input = data.get("tool_input") or {}

    # Resolve own session id — payload field takes priority over env (FIX 1)
    my_sid = _resolve_session(data)

    # Best-effort heartbeat update (non-blocking)
    _update_heartbeat(my_sid)

    # Determine target path for lane-conflict check
    target_path: str | None = None
    if tool_name in ("Write", "Edit"):
        target_path = tool_input.get("file_path") or None
        if target_path:
            try:
                target_path = str(Path(target_path).resolve())
            except Exception:
                target_path = None

    # Load registry and find other LIVE sessions
    try:
        registry = _load_registry()
        sessions = registry.get("sessions", {})
    except Exception:
        return 0  # registry unreadable → fail-open

    other_live = {
        sid: entry
        for sid, entry in sessions.items()
        if sid != my_sid and _is_live(entry)
    }

    if not other_live:
        return 0  # sole dimension — no warning needed

    # Build warning message
    n = len(other_live)
    ids_branches = ", ".join(
        f"{sid[:12]}…({e.get('branch') or 'no-branch'})"
        for sid, e in other_live.items()
    )

    warning = (
        f"⚠ 4D: {n} other live dimension(s) share this working tree "
        f"[{ids_branches}]. "
        f"You are NOT isolated — commit ONLY by explicit pathspec (never git add -A), "
        f"and consider `python3 ~/.claude/scripts/octo-dim.py worktree-init` "
        f"to fork your own dimension."
    )

    # Strengthen warning if target_path is claimed by another session
    if target_path:
        for sid, entry in other_live.items():
            lanes = entry.get("lanes") or []
            if target_path in lanes:
                warning += (
                    f" CONFLICT: {target_path!r} is claimed by session "
                    f"{sid[:20]}… — coordinate before writing."
                )
                break  # one conflict note is enough

    # Emit in grafo-gate.py format
    try:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": warning,
            }
        }))
    except Exception:
        pass  # stdout failure → fail-open

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # fail-open: never break the user's tool call
