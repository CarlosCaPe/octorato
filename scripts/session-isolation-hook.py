#!/usr/bin/env python3
"""session-isolation-hook.py — SessionStart hook: isolation by DEFAULT.

When a session starts and other LIVE dimensions already exist on this machine,
this hook auto-forks the new session into its own git worktree (via
octo-dim.py worktree-init) and instructs it to do ALL brain work there.
Isolation stops being advisory. Sharing the main tree becomes the exception,
not the default that everyone falls into.

Design principles (mirroring dimension-awareness-hook.py):
  - FAIL-OPEN. Any exception → exit 0, no output. A broken hook never bricks a session.
  - One subprocess at most (octo-dim.py worktree-init), and only when a fork
    is actually needed.
  - Requires the payload session_id. No hostname-pid fallback here: an
    unstable id would fork every session into the same path (see
    octo-dim.py cmd_worktree_init for the full rationale).

Stdin: {"session_id": str, "cwd": str, "hook_event_name": "SessionStart", ...}
Stdout: {"hookSpecificOutput": {"hookEventName": "SessionStart",
         "additionalContext": "..."}} when a fork happened / is in place.
Exit: always 0.
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
# Force UTF-8 on stdout/stderr so the ✓ / ✗ / em-dash glyphs in reports
# survive on Windows shells defaulting to cp1252. Without this, a script
# can do its work correctly and still crash with UnicodeEncodeError when
# printing success. Applied repo-wide by _apply-utf8-reconfigure.py.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


REGISTRY = Path.home() / ".claude" / "connectome" / "sessions.json"
LOCKFILE = REGISTRY.parent / ".sessions.lock"
SCRIPTS = Path.home() / ".claude" / "scripts"
DEFAULT_TTL = 900  # seconds, same as dimension-awareness-hook.py
_FUTURE_SKEW = 120


@contextmanager
def _registry_lock():
    """Serialize read-modify-write cycles on sessions.json. Without this, two
    sessions starting in the same instant each load {}, each write only itself,
    and NEITHER sees the other → neither forks → shared tree again (the exact
    failure this hook exists to prevent). flock is advisory but both writers
    are this same hook. Fail-open: lock errors degrade to unlocked behavior."""
    fh = None
    try:
        LOCKFILE.parent.mkdir(parents=True, exist_ok=True)
        fh = open(LOCKFILE, "w")
        import fcntl
        fcntl.flock(fh, fcntl.LOCK_EX)
    except Exception:
        fh = None  # degraded: proceed unlocked rather than brick the session
    try:
        yield
    finally:
        if fh is not None:
            try:
                fh.close()  # releases the flock
            except OSError:
                pass


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


def _is_live(entry: dict, ttl: int = DEFAULT_TTL) -> bool:
    hb = entry.get("heartbeat", "")
    if not hb:
        return False
    try:
        hb_dt = datetime.fromisoformat(hb)
        if hb_dt.tzinfo is None:
            hb_dt = hb_dt.replace(tzinfo=timezone.utc)
        delta = (datetime.now(timezone.utc) - hb_dt).total_seconds()
        if delta < -_FUTURE_SKEW:
            return False
        return delta <= ttl
    except (ValueError, TypeError):
        return False


def _emit(context: str) -> None:
    try:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": context,
            }
        }))
    except Exception:
        pass


def main() -> int:
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        return 0

    sid = str(data.get("session_id") or "")
    if not sid:
        return 0  # no stable id → nothing safe to fork; dimension-awareness still warns

    now = _now_iso()
    with _registry_lock():
        # Register/heartbeat self and read others INSIDE the lock, so two
        # sessions starting in the same instant serialize and see each other.
        registry = _load_registry()
        sessions = registry.get("sessions", {})
        entry = sessions.get(sid, {
            "session_id": sid,
            "branch": "",
            "worktree": "",
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "started": now,
            "lanes": [],
        })
        entry["heartbeat"] = now
        sessions[sid] = entry
        registry["sessions"] = sessions
        _save_registry(registry)
        other_live = {
            s: e for s, e in sessions.items() if s != sid and _is_live(e)
        }
    if not other_live:
        return 0  # sole dimension — main tree is yours

    # Already forked? Just remind where home is.
    wt = entry.get("worktree") or ""
    if wt and Path(wt).is_dir() and (Path(wt) / ".git").exists():
        _emit(
            f"♦ DIMENSION: {len(other_live)} other live session(s) on this machine. "
            f"Your isolated worktree is {wt} (branch {entry.get('branch') or '?'}). "
            f"ALL brain writes/commits go through it; never stage in ~/.claude directly."
        )
        return 0

    # Fork now: one git call via octo-dim.
    try:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "octo-dim.py"), "--session-id", sid, "worktree-init"],
            capture_output=True, text=True, timeout=30,
        )
        out = (result.stdout or "").strip().splitlines()
        path = out[-1] if out else ""
        rc = result.returncode
        err = (result.stderr or result.stdout or "no output").strip()[:120]
    except subprocess.TimeoutExpired:
        path, rc, err = "", 1, "octo-dim worktree-init timed out (30s)"

    # Guard against a STALE octo-dim (pre-fix): its hostname-pid fallback forks
    # every session into the SAME path, so a "success" whose directory name does
    # not derive from OUR session id is a false isolation claim — reject it.
    expected_short = re.sub(r"[^a-z0-9]", "", sid.lower())[:12] or "dim0"
    # The directory must CARRY the full sanitized id (name ⊇ expected), not
    # merely be a prefix of it — the inverted form accepted wrong-session
    # paths like a stale octo-dim's sid[:8] or any 4-char prefix (QA round 2).
    name = Path(path).name.rstrip("-") if path else ""
    derived_ok = bool(path) and len(name) >= 4 and name.startswith(expected_short)
    if rc != 0 or not path or not Path(path).is_dir() or not derived_ok:
        _emit(
            f"⚠ DIMENSION: {len(other_live)} other live session(s) and auto-fork FAILED or "
            f"returned a path not derived from this session id ({err!s}; got {path!r}). "
            f"You are NOT isolated: commit only by explicit pathspec, never git add -A."
        )
        return 0

    branch = f"dim/{Path(path).name}"
    # Persist the fork under the lock (avoid lost-update vs a concurrent
    # dimension-awareness heartbeat that also writes the registry).
    with _registry_lock():
        registry = _load_registry()
        sessions = registry.get("sessions", {})
        entry = sessions.get(sid, entry)
        entry["worktree"] = path
        entry["branch"] = branch
        entry["heartbeat"] = _now_iso()
        sessions[sid] = entry
        registry["sessions"] = sessions
        _save_registry(registry)

    _emit(
        f"♦ DIMENSION AUTO-FORK: {len(other_live)} other live session(s) share this machine, "
        f"so you were forked to your own worktree: {path} (branch {branch}). "
        f"Do ALL brain file edits/commits inside that path. The shared ~/.claude stays read-only "
        f"for you; broad staging there is denied by the dimension gate."
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # fail-open: never break session start
