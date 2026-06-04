#!/usr/bin/env python3
"""dimension-awareness-hook.py — PreToolUse hook for 4D session dimension awareness
AND lane enforcement.

Two jobs, in order of force:
  1. ENFORCE lanes (Write/Edit only): if the target file is claimed by ANOTHER
     live session, DENY the tool call. Two dimensions must never write one file.
  2. AUTO-CLAIM (Write/Edit only): if the target file is free, claim it for this
     session — the first writer owns the lane, involuntarily. This is what turns
     the lane system from etiquette into a reflex (the cerebellum principle:
     enforcement must fire without anyone choosing to run it).
  3. WARN (all matched tools): when other live dimensions share the tree, inject
     the shared-tree warning as before.

Lanes die with their session: a session that stops heartbeating past the TTL is
no longer live, so its lanes stop blocking (and `octo-dim prune` removes them).
Cooperative handoff: `octo-dim release <path>` / `release <path> --from-any`.

Operator override: OCTO_LANE_OVERRIDE=1 in the HARNESS environment bypasses the
deny. An agent cannot set the harness env for Write/Edit tool calls (an inline
`FOO=1` only scopes a Bash command), so the override is operator-only — the same
agent-proof property as OCTO_MERGE_APPROVE in the merge gate.

Design principles (mirroring grafo-gate.py):
  - FAIL-OPEN on infrastructure errors (bad JSON, unreadable registry, lock
    failure) — a broken hook must never brick a session.
  - FAIL-CLOSED only on a genuine, attributable lane conflict.
  - Fast: no subprocess calls, only JSON reads + datetime math.
  - Registry writes use lock + re-read-merge (same contract as octo-dim.py's
    _save) so concurrent heartbeats/claims from parallel sessions never lose
    each other's updates. The lock/merge block is intentionally duplicated from
    octo-dim.py — hooks stay import-free and self-contained.

Stdin:  {"session_id": str, "tool_name": str, "tool_input": {...}}
Stdout: hookSpecificOutput JSON — additionalContext (warn) or
        permissionDecision: "deny" (lane conflict).
Exit:   always 0 (the deny travels in the JSON, not the exit code).

Known limitation (shared-tree attribution): a file already git-modified by a
session that never wrote through this hook has no lane — the first post-
enforcement writer claims it. Attribution of pre-existing uncommitted edits is
impossible in a shared tree; full isolation still means one worktree per
session (`octo-dim worktree-init`).

Security note — session identity resolution: env CLAUDE_SESSION_ID wins over
the stdin payload field. The harness sets the env; an agent cannot set harness
env for Write/Edit calls (inline `FOO=1` scopes only Bash), so session_id in
the payload is treated as an untrusted hint. This closes the impersonation
bypass: an agent writing session_id=<other> in stdin cannot masquerade as that
session to skip a lane conflict.
"""
from __future__ import annotations

import contextlib
import json
import os
import socket
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

try:
    import fcntl as _fcntl
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False

REGISTRY_DIR = Path.home() / ".claude" / "connectome"
REGISTRY = REGISTRY_DIR / "sessions.json"
DEFAULT_TTL = 900  # seconds
_FUTURE_SKEW = 120  # seconds; heartbeat this far ahead of now is considered NOT live

# Tools whose target path participates in lane enforcement.
_LANE_TOOLS = ("Write", "Edit", "NotebookEdit")


# ── session id (same resolution order as octo-dim.py) ───────────────────────

def _resolve_session(payload: dict | None = None) -> str:
    """Priority: env CLAUDE_SESSION_ID → stdin payload session_id → hostname-pid.

    env wins over payload because CLAUDE_SESSION_ID is set by the harness (the
    operator-controlled process that spawns Claude Code). An agent cannot set the
    harness env for Write/Edit tool calls — an inline `CLAUDE_SESSION_ID=X`
    only scopes a Bash command, not the hook execution environment. This makes
    session identity agent-proof: a rogue payload field cannot impersonate another
    session and bypass the lane conflict check.
    """
    from_env = os.environ.get("CLAUDE_SESSION_ID", "")
    if from_env:
        return from_env
    if payload:
        from_payload = payload.get("session_id", "")
        if from_payload:
            return str(from_payload)
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


@contextlib.contextmanager
def _registry_lock():
    """Exclusive advisory lock on sessions.json.lock (POSIX only); no-op fallback."""
    lock_path = REGISTRY_DIR / "sessions.json.lock"
    if not _HAS_FCNTL:
        yield
        return
    try:
        REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
        lf = open(lock_path, "w")
        try:
            _fcntl.flock(lf.fileno(), _fcntl.LOCK_EX)
            yield
        finally:
            _fcntl.flock(lf.fileno(), _fcntl.LOCK_UN)
            lf.close()
    except Exception:
        yield  # fail-open


def _upsert_session(sid: str, mutate) -> None:
    """Lock → re-read → mutate(entry) → atomic write. Merge-safe upsert of ONE
    session entry; concurrent writers' entries survive (same contract as
    octo-dim.py's _save). `mutate` receives the current entry dict and edits it
    in place. Non-fatal on any error (fail-open)."""
    try:
        with _registry_lock():
            data = _load_registry()
            now = _now_iso()
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
            mutate(entry)
            data["sessions"][sid] = entry
            REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=REGISTRY_DIR, prefix=".sessions.tmp.")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=2)
                os.replace(tmp, REGISTRY)
            except Exception:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
    except Exception:
        pass  # fail-open: registry write failure must never block the caller


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
        if delta < -_FUTURE_SKEW:
            return False
        return delta <= ttl
    except (ValueError, TypeError):
        return False


# ── output helpers ───────────────────────────────────────────────────────────

def _emit(payload: dict) -> None:
    try:
        print(json.dumps({"hookSpecificOutput": payload}))
    except Exception:
        pass  # stdout failure → fail-open


def _deny(reason: str) -> None:
    _emit({
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    })


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    try:
        raw = sys.stdin.read()
        data = json.loads(raw)
    except Exception:
        return 0  # bad JSON → fail-open, no output

    tool_name = (data.get("tool_name") or "")
    tool_input = data.get("tool_input") or {}
    my_sid = _resolve_session(data)

    # Target path (lane tools only)
    target_path: str | None = None
    if tool_name in _LANE_TOOLS:
        raw_path = tool_input.get("file_path") or tool_input.get("notebook_path") or None
        if raw_path:
            try:
                target_path = str(Path(raw_path).resolve())
            except Exception:
                target_path = None

    # Load registry, find other LIVE sessions
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

    # ── 1. ENFORCE: lane conflict → deny (unless operator override) ──────────
    if target_path and other_live:
        for sid, entry in other_live.items():
            if target_path in (entry.get("lanes") or []):
                if os.environ.get("OCTO_LANE_OVERRIDE") == "1":
                    break  # operator override — fall through to warn
                _deny(
                    f"⛔ 4D lane: {target_path} is owned by live dimension "
                    f"{sid[:12]}…. Two dimensions must not write one file. "
                    f"Options: coordinate via the operator, wait for that "
                    f"session to finish (TTL {DEFAULT_TTL}s), have the operator "
                    f"run `octo-dim release {target_path} --from-any` or set "
                    f"OCTO_LANE_OVERRIDE=1, or fork your own worktree "
                    f"(`octo-dim worktree-init`)."
                )
                # Still record our heartbeat; the denied write claims nothing.
                _upsert_session(my_sid, lambda e: None)
                return 0

    # ── 2. AUTO-CLAIM: free path + concurrent dimensions → first writer owns ──
    if target_path and other_live:
        def _claim(entry: dict, path=target_path) -> None:
            lanes = entry.get("lanes") or []
            if path not in lanes:
                lanes.append(path)
            entry["lanes"] = lanes
        _upsert_session(my_sid, _claim)
    else:
        # Sole dimension or non-lane tool: heartbeat only.
        _upsert_session(my_sid, lambda e: None)

    if not other_live:
        return 0  # sole dimension — no warning needed

    # ── 3. WARN: shared-tree awareness (as before) ────────────────────────────
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
    if target_path:
        warning += f" Lane auto-claimed: {target_path} → this session."

    _emit({"hookEventName": "PreToolUse", "additionalContext": warning})
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # fail-open: never break the user's tool call
