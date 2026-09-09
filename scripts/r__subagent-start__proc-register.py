#!/usr/bin/env python3
"""r__subagent-start__proc-register.py: SubagentStart reflex, a child process.

v8 Phase 1a (docs/architecture/v8-kernel.md section 3). Runtime 2.1.261 delivers
SubagentStart {session_id, agent_id, agent_type, cwd, transcript_path} and puts
agent_id / agent_type on every hook fired inside that subagent. This reflex
turns that into the kernel's PROCESS record: pid = agent_id, ppid = session_id,
type = agent_type, worktree = the enclosing `.git` root of cwd.

The parent link is the point. Before it, a subagent was invisible to the brain:
no record, no parent, no exit status, and two children of one session read as
ONE dimension to the lane gate (dimension-awareness-hook.py:98-105 keys on
session_id). Phase 2 denies cross-process writes off exactly this link.

The transcript path is unknown at start; SubagentStop carries
agent_transcript_path (Phase 1a-2 records it on the `exit` line).

No hook-order assumption: a child's first tool call can beat this hook, and the
hot-path gate is built to journal without a `start` line rather than deny.

Never blocks. Fail-open on every error.

Stdin:  SubagentStart payload {"session_id", "agent_id", "agent_type", "cwd", ...}
Stdout: nothing. Exit always 0.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    try:
        import kernel_proc
        pid = str(payload.get("agent_id") or "")
        if not pid:
            return 0
        cwd = str(payload.get("cwd") or os.getcwd())
        entry = {
            "kind": "subagent",
            "ppid": kernel_proc.safe_pid(payload.get("session_id") or ""),
            "type": str(payload.get("agent_type") or "subagent"),
            "worktree": kernel_proc.enclosing_worktree_root(cwd) or cwd,
            "cwd": cwd,
        }
        if not payload.get("session_id"):
            entry.pop("ppid")
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
