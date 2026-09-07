#!/usr/bin/env python3
"""r__subagent-stop__proc-exit.py: SubagentStop reflex, the child's exit line.

v8 Phase 1a-2 (docs/architecture/v8-kernel.md section 3). Phase 1a gave a
subagent a pid, a parent and a journal; it had no ending. This reflex closes
the record: one `exit` line carrying the status, the harness-written
`agent_transcript_path`, how many tool calls the process made and how long it
ran, plus the ptable row marked exited so `octo ps` (Phase 1b) and the lane
gate (Phase 2) stop treating a finished child as a live holder.

Three fields only the harness knows come from
`<session-dir>/subagents/agent-<id>.meta.json` (spawnDepth, model, toolUseId):
the depth of the spawn tree, the engine the child actually ran on (the ladder
row that was really used, not the one intended) and the tool_use id of the
Agent call that created it, which is the link back to the parent's own journal
line. The file is read when present and its absence is never an error.

Liveness (v8-kernel.md section 2) reads an `exit` line as terminal, so writing
it twice would be writing a second ending: a repeated SubagentStop for the same
pid is a no-op, not a second line.

Never blocks. Fail-open on every error.

Stdin:  {"session_id", "agent_id", "agent_type", "agent_transcript_path",
         "transcript_path", "last_assistant_message", ...}
Stdout: nothing. Exit always 0.
"""
from __future__ import annotations

import json
import re
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# A child that opens its final message with one of these is reporting its own
# failure. Matched on the first line only: an error named mid-report is a
# finding, not a crash.
# Word-bounded: "Errors were found and fixed" and "Exceptionally good" are ok.
_ERROR_HEAD = re.compile(r"^(?:error|fatal|exception)\b|^traceback \(most recent call last\)")


def status_of(text) -> str:
    """ok | error, read from the child's last assistant message.

    No final message at all is the crash case: the process ended without ever
    saying anything. Everything that is not an opening error marker is ok.
    """
    # TODO(Phase 3, v8-kernel.md section 3): exit precedence is quota > error >
    # ok. The hot-path gate writes the `quota` line; this hook will read the
    # journal tail for it and stamp status "quota" ahead of both branches below.
    s = str(text or "").strip()
    if not s:
        return "error"
    first = s.splitlines()[0].strip().lstrip("*_# ").lower()
    return "error" if _ERROR_HEAD.match(first) else "ok"


def meta_path(payload: dict, pid: str) -> str:
    """`<session-dir>/subagents/agent-<id>.meta.json`, or '' when unresolvable.

    The agent transcript is that same path with a `.jsonl` suffix, so it is the
    direct route. The main `transcript_path` is the fallback: the session dir is
    the transcript file without its suffix (projects/<slug>/<session>.jsonl next
    to projects/<slug>/<session>/subagents/).
    """
    atp = str(payload.get("agent_transcript_path") or "")
    if atp.endswith(".jsonl"):
        return atp[:-6] + ".meta.json"
    tp = str(payload.get("transcript_path") or "")
    if tp.endswith(".jsonl"):
        name = pid if pid.startswith("agent-") else "agent-" + pid
        return os.path.join(tp[:-6], "subagents", name + ".meta.json")
    return ""


def read_meta(path: str) -> dict:
    """spawnDepth / model / toolUseId under the journal's snake_case names."""
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for src, dst in (("spawnDepth", "spawn_depth"), ("model", "model"),
                     ("toolUseId", "spawn_tool_use_id")):
        if data.get(src) not in (None, ""):
            out[dst] = data[src]
    return out


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    try:
        import time

        import kernel_proc
        pid = str(payload.get("agent_id") or "")
        if not pid or kernel_proc.has_exit(pid):
            return 0
        lines = [l for l in kernel_proc.read_journal(pid) if isinstance(l, dict)]
        tail = lines[-1] if lines else {}
        now = time.time()
        rec = {
            "kind": "exit",
            "status": status_of(payload.get("last_assistant_message")),
            "tool_count": sum(1 for l in lines if l.get("kind") == "tool"),
            "seq_before": int(tail.get("seq", -1)),
            "duration": round(max(0.0, now - float(tail.get("start_ts") or now)), 3),
        }
        rec["ok"] = rec["status"] == "ok"
        if payload.get("agent_transcript_path"):
            rec["agent_transcript_path"] = str(payload["agent_transcript_path"])
        if payload.get("agent_type"):
            rec["type"] = str(payload["agent_type"])
        rec.update(read_meta(meta_path(payload, pid)))
        kernel_proc.append(pid, rec)
        row = {k: rec[k] for k in ("status", "tool_count", "duration", "model",
                                   "spawn_depth", "spawn_tool_use_id",
                                   "agent_transcript_path") if k in rec}
        row.update({"exited": True, "exit_ts": round(now, 6)})
        kernel_proc.update_row(pid, row)
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        import kernel_proc
        _i = sys.argv.index("--selftest")
        sys.exit(kernel_proc.selftest_exit_flow(
            sys.argv[_i + 1] if len(sys.argv) > _i + 1 else None))
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
