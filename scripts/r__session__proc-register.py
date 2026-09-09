#!/usr/bin/env python3
"""r__session__proc-register.py: SessionStart reflex that opens a kernel process.

v8 Phase 1a (docs/architecture/v8-kernel.md section 3). A main loop gets a pid
(its session id), a worktree (the payload `cwd`) and an append-only journal, so
every later tool call has something to chain onto and `octo ps` has a row to
show.

Why a hook and not a library call: the main loop cannot be trusted to register
itself, and a rule that depends on the model remembering it is skipped under
load (skills/reflexes-over-discipline).

No hook-order assumption. Same-event hooks run in parallel, so this one never
waits on session-isolation-hook.py: when `connectome/sessions.json` already
carries a per-session worktree, it is recorded as `dim_worktree` alongside the
payload `cwd`; when it does not (the fork hook only prints an instruction,
session-isolation-hook.py:225-230), the row is written anyway.

Never blocks. Fail-open on every error: a kernel that bricks a session is worse
than one that misses a row, and the hot-path gate is where the journal is
actually enforced.

Stdin:  SessionStart payload {"session_id", "cwd", "source", ...}
Stdout: nothing. Exit always 0.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _dim_worktree(session_id: str) -> str:
    """The per-session worktree session-isolation-hook.py recorded, when it ran
    first. Absent is normal, never an error."""
    try:
        import kernel_proc
        path = os.path.join(kernel_proc.brain_dir(), "connectome", "sessions.json")
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        entry = ((data or {}).get("sessions") or {}).get(session_id) or {}
        return str(entry.get("worktree") or "")
    except Exception:
        return ""


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    try:
        import kernel_proc
        pid = str(payload.get("session_id") or os.environ.get("CLAUDE_SESSION_ID") or "")
        if not pid:
            return 0
        cwd = str(payload.get("cwd") or os.getcwd())
        entry = {
            "kind": "main",
            "type": "main",
            "worktree": kernel_proc.enclosing_worktree_root(cwd) or cwd,
            "cwd": cwd,
            "dim_worktree": _dim_worktree(pid),
            "source": str(payload.get("source") or ""),
        }
        kernel_proc.register(pid, entry)
    except Exception:
        return 0
    return 0


def _selftest() -> int:
    import kernel_proc
    argv = sys.argv
    i = argv.index("--selftest")
    fixture = argv[i + 1] if len(argv) > i + 1 else None
    return kernel_proc.selftest_flow(fixture)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
