#!/usr/bin/env python3
"""octo-dim.py — 4D session dimension manager.

Manages a shared registry (~/.claude/connectome/sessions.json) of concurrent
Claude Code sessions (dimensions) running in parallel git worktrees. Allows
sessions to declare themselves, advertise which file paths they own (lanes),
and see who else is alive — so they can coordinate without colliding.

Concurrency model: atomic tempfile+os.replace writes. Multiple concurrent
writers are tolerated on a last-writer-wins basis (no distributed lock).
A brief comment wherever writes happen notes the accepted race window.

Session id resolution order:
  1. env  CLAUDE_SESSION_ID
  2. --session-id arg (parsed early so subcommands can override)
  3. f"{hostname}-{pid}"  (fallback)

stdlib only. Never crashes the caller (all exceptions caught at top level).
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import socket
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# fcntl is POSIX-only; degrade to no-lock on Windows
try:
    import fcntl as _fcntl
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False

# ── paths ────────────────────────────────────────────────────────────────────
BRAIN = Path.home() / ".claude"
REGISTRY_DIR = BRAIN / "connectome"
REGISTRY = REGISTRY_DIR / "sessions.json"
DIM_ROOT = Path.home() / ".octorato" / "dim"

# ── registry helpers ──────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load() -> dict:
    """Load registry; return empty skeleton on any error."""
    try:
        with REGISTRY.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict) or "sessions" not in data:
            return {"sessions": {}}
        return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"sessions": {}}


@contextlib.contextmanager
def _registry_lock():
    """Acquire an exclusive advisory lock on sessions.json.lock (POSIX only).
    On Windows or any error, degrades to a no-op context (fail-open).
    """
    lock_path = REGISTRY_DIR / "sessions.json.lock"
    if not _HAS_FCNTL:
        yield
        return
    try:
        REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
        lf = open(lock_path, "w")  # noqa: WPS515 — intentional open for locking
        try:
            _fcntl.flock(lf.fileno(), _fcntl.LOCK_EX)
            yield
        finally:
            _fcntl.flock(lf.fileno(), _fcntl.LOCK_UN)
            lf.close()
    except Exception:
        yield  # fail-open: lock acquisition failure must never block the caller


def _save(data: dict, deleted_sids: set[str] | None = None) -> None:
    """Atomic write via tempfile + os.replace, protected by an advisory lock.

    Under the lock we re-read the current file and merge: the caller's session
    entries win per-key, but entries written by concurrent processes since the
    caller's _load() are preserved.  This means 20 concurrent `register` calls
    with distinct ids all persist (no lost-update) — the classic last-writer-
    wins hazard is eliminated.

    deleted_sids: session ids that should be removed from the merged result
    (used by unregister/prune which need real deletions, not just upserts).
    """
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with _registry_lock():
            # Re-read under lock to pick up concurrent writes since caller's _load()
            try:
                with REGISTRY.open("r", encoding="utf-8") as fh:
                    on_disk = json.load(fh)
                if not isinstance(on_disk, dict) or "sessions" not in on_disk:
                    on_disk = {"sessions": {}}
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                on_disk = {"sessions": {}}
            # Merge: caller's sessions win per-key; other keys survive
            on_disk["sessions"].update(data.get("sessions", {}))
            # Apply explicit deletions (prune / unregister)
            for sid in (deleted_sids or set()):
                on_disk["sessions"].pop(sid, None)
            merged = on_disk

            fd, tmp = tempfile.mkstemp(dir=REGISTRY_DIR, prefix=".sessions.tmp.")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(merged, fh, indent=2)
                os.replace(tmp, REGISTRY)
            except Exception:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
    except Exception:
        pass  # fail-open: _save failure must never crash callers


def _resolve_session(args) -> str:
    """Resolve session id per documented priority order."""
    from_env = os.environ.get("CLAUDE_SESSION_ID", "")
    if from_env:
        return from_env
    if hasattr(args, "session_id") and args.session_id:
        return args.session_id
    host = socket.gethostname()
    pid = os.getpid()
    return f"{host}-{pid}"


_FUTURE_SKEW = 120  # seconds; heartbeat this far ahead of now is considered NOT live


def _is_live(entry: dict, ttl: int) -> bool:
    """True if heartbeat is within ttl seconds of now (and not far in the future)."""
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


def _age_str(entry: dict) -> str:
    """Human-readable age string for started field."""
    started = entry.get("started", "")
    if not started:
        return "unknown"
    try:
        s_dt = datetime.fromisoformat(started)
        if s_dt.tzinfo is None:
            s_dt = s_dt.replace(tzinfo=timezone.utc)
        secs = int((datetime.now(timezone.utc) - s_dt).total_seconds())
        if secs < 60:
            return f"{secs}s"
        if secs < 3600:
            return f"{secs // 60}m"
        if secs < 86400:
            return f"{secs // 3600}h {(secs % 3600) // 60}m"
        return f"{secs // 86400}d"
    except (ValueError, TypeError):
        return "?"


# ── subcommand handlers ───────────────────────────────────────────────────────

def cmd_register(args) -> int:
    sid = _resolve_session(args)
    now = _now_iso()
    try:
        data = _load()
        existing = data["sessions"].get(sid, {})
        entry = {
            "session_id": sid,
            "branch": args.branch or existing.get("branch", ""),
            "worktree": args.worktree or existing.get("worktree", ""),
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "started": existing.get("started", now),  # preserve original start
            "heartbeat": now,
            "lanes": existing.get("lanes", []),
        }
        data["sessions"][sid] = entry
        _save(data)
        print(f"registered: {sid}")
    except Exception as exc:
        print(f"register warning (non-fatal): {exc}", file=sys.stderr)
    return 0


def cmd_heartbeat(args) -> int:
    sid = _resolve_session(args)
    now = _now_iso()
    try:
        data = _load()
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
        _save(data)
    except Exception as exc:
        print(f"heartbeat warning (non-fatal): {exc}", file=sys.stderr)
    return 0


def cmd_list(args) -> int:
    ttl = args.ttl
    try:
        data = _load()
        sessions = data.get("sessions", {})
        if not sessions:
            print("(no sessions registered)")
            return 0
        # header
        print(f"{'STATUS':<6}  {'ID':<32}  {'BRANCH':<20}  {'WORKTREE':<30}  {'AGE'}")
        print("-" * 100)
        for sid, entry in sessions.items():
            status = "LIVE " if _is_live(entry, ttl) else "STALE"
            branch = (entry.get("branch") or "")[:20]
            worktree = (entry.get("worktree") or "")[:30]
            age = _age_str(entry)
            print(f"{status:<6}  {sid[:32]:<32}  {branch:<20}  {worktree:<30}  {age}")
    except Exception as exc:
        print(f"list warning (non-fatal): {exc}", file=sys.stderr)
    return 0


def cmd_prune(args) -> int:
    ttl = args.ttl
    try:
        data = _load()
        before = len(data["sessions"])
        stale_sids = {
            sid for sid, e in data["sessions"].items()
            if not _is_live(e, ttl)
        }
        data["sessions"] = {
            sid: e for sid, e in data["sessions"].items()
            if sid not in stale_sids
        }
        after = len(data["sessions"])
        _save(data, deleted_sids=stale_sids)
        removed = before - after
        print(f"pruned {removed} stale session(s); {after} remain")
    except Exception as exc:
        print(f"prune warning (non-fatal): {exc}", file=sys.stderr)
    return 0


def cmd_claim(args) -> int:
    sid = _resolve_session(args)
    path = str(Path(args.path).resolve())
    try:
        data = _load()
        entry = data["sessions"].get(sid, {
            "session_id": sid,
            "branch": "",
            "worktree": "",
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "started": _now_iso(),
            "heartbeat": _now_iso(),
            "lanes": [],
        })
        lanes = entry.get("lanes", [])
        if path not in lanes:
            lanes.append(path)
        entry["lanes"] = lanes
        data["sessions"][sid] = entry
        _save(data)
        print(f"claimed: {path} → session {sid}")
    except Exception as exc:
        print(f"claim warning (non-fatal): {exc}", file=sys.stderr)
    return 0


def cmd_unregister(args) -> int:
    sid = _resolve_session(args)
    try:
        data = _load()
        if sid in data["sessions"]:
            del data["sessions"][sid]
            _save(data, deleted_sids={sid})
            print(f"unregistered: {sid}")
        else:
            print(f"(session {sid} not found in registry)")
    except Exception as exc:
        print(f"unregister warning (non-fatal): {exc}", file=sys.stderr)
    return 0


def cmd_worktree_init(args) -> int:
    """Idempotently create a git worktree for this dimension."""
    sid = _resolve_session(args)
    short = sid[:8]
    target = DIM_ROOT / short
    branch = f"dim/{short}"

    # Only short-circuit if target is actually a git worktree (has a .git entry)
    if target.exists() and (target / ".git").exists():
        print(str(target))
        return 0

    DIM_ROOT.mkdir(parents=True, exist_ok=True)

    # Try with -b (new branch)
    result = subprocess.run(
        ["git", "-C", str(BRAIN), "worktree", "add", str(target), "-b", branch],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        # Branch may already exist; try attaching without -b
        result2 = subprocess.run(
            ["git", "-C", str(BRAIN), "worktree", "add", str(target), branch],
            capture_output=True, text=True,
        )
        if result2.returncode != 0:
            msg = result2.stderr.strip() or result.stderr.strip()
            print(f"worktree-init: could not create worktree: {msg}")
            return 0  # never hard-fail

    print(str(target))
    return 0


# ── main ──────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="octo-dim",
        description="4D session dimension manager — parallel worktree registry",
    )
    p.add_argument("--session-id", default="", help="Override session id")

    sub = p.add_subparsers(dest="cmd", required=True)

    reg = sub.add_parser("register", help="Upsert this session in the registry")
    reg.add_argument("--branch", default="", help="Current git branch")
    reg.add_argument("--worktree", default="", help="Current worktree path")

    sub.add_parser("heartbeat", help="Update heartbeat timestamp")

    lst = sub.add_parser("list", help="List all sessions")
    lst.add_argument("--ttl", type=int, default=900, help="Live TTL in seconds")

    prn = sub.add_parser("prune", help="Remove stale sessions")
    prn.add_argument("--ttl", type=int, default=900, help="Live TTL in seconds")

    clm = sub.add_parser("claim", help="Add a path to this session's lanes")
    clm.add_argument("path", help="Absolute or relative path to claim")

    sub.add_parser("unregister", help="Remove this session from the registry")

    wi = sub.add_parser("worktree-init", help="Create a git worktree for this dimension")
    wi.add_argument("--session-id", dest="session_id", default="",
                    help="Use this session id instead of auto-resolved")

    return p


HANDLERS = {
    "register": cmd_register,
    "heartbeat": cmd_heartbeat,
    "list": cmd_list,
    "prune": cmd_prune,
    "claim": cmd_claim,
    "unregister": cmd_unregister,
    "worktree-init": cmd_worktree_init,
}


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    handler = HANDLERS.get(args.cmd)
    if handler is None:
        print(f"unknown command: {args.cmd}", file=sys.stderr)
        return 1
    return handler(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        # Top-level safety net — register/heartbeat/list must always exit 0
        print(f"octo-dim fatal (non-crashing): {exc}", file=sys.stderr)
        sys.exit(0)
