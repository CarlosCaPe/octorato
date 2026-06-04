#!/usr/bin/env python3
"""
trace-hook.py — observability surface 1 — capture hook.

Reads a Claude Code hook event from stdin and appends a JSONL trace record to
~/.claude/traces/YYYY-MM-DD.jsonl. Best-effort: any error silently swallowed
so the hook never blocks the underlying tool call.

Currently handles:
  - PostToolUse on Skill tool → emits a `skill_fire` record

Future tasks (#4, #5) extend this script with `agent_activate` and
`phase_boundary` handlers.

Schema: ~/.claude/schemas/trace-event.schema.json (v1.0)
Layout: ~/.claude/docs/architecture/trace-storage.md
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

TRACES_DIR = Path.home() / ".claude" / "traces"
ARM_PATH_RE = re.compile(r"/Documents/github/([^/]+)(/|$)")


def _now_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _today_filename() -> Path:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return TRACES_DIR / f"{today}.jsonl"


def _task_id_from(session_id: str) -> str:
    # SHA-1 of session_id → exactly 40 hex chars (matches schema contract).
    # Autonomous turns without session_id get an ad-hoc UUID v4 (§9 Q4 default).
    if not session_id:
        return uuid.uuid4().hex
    return hashlib.sha1(session_id.encode("utf-8")).hexdigest()


def _arm_from_cwd() -> str | None:
    m = ARM_PATH_RE.search(os.getcwd())
    return m.group(1) if m else None


def _extract_tokens(tool_response: dict | None) -> dict | None:
    # Pull `{input, output}` from tool_response.tokens if Claude Code exposes it.
    # Returns None otherwise. Schema requires both keys to be ints when present.
    if not isinstance(tool_response, dict):
        return None
    tokens = tool_response.get("tokens")
    if isinstance(tokens, dict) and "input" in tokens and "output" in tokens:
        try:
            return {"input": int(tokens["input"]), "output": int(tokens["output"])}
        except (TypeError, ValueError):
            return None
    return None


def _build_skill_fire(payload: dict) -> dict | None:
    tool_input = payload.get("tool_input") or {}
    skill_name = tool_input.get("skill")
    if not skill_name:
        return None
    tool_response = payload.get("tool_response") or {}
    error = (tool_response or {}).get("error") if isinstance(tool_response, dict) else None
    return {
        "schemaVersion": "1.0",
        "ts": _now_iso(),
        "event": "skill_fire",
        "name": str(skill_name)[:200],
        "task_id": _task_id_from(payload.get("session_id") or ""),
        "arm": _arm_from_cwd(),
        "duration_ms": None,
        "tokens": _extract_tokens(tool_response),
        "status": "error" if error else "ok",
        "error": str(error)[:500] if error else None,
    }


def _build_agent_activate(payload: dict) -> dict | None:
    tool_input = payload.get("tool_input") or {}
    name = (tool_input.get("subagent_type") or "general-purpose").strip()
    if not name:
        return None
    tool_response = payload.get("tool_response") or {}
    error = (tool_response or {}).get("error") if isinstance(tool_response, dict) else None
    return {
        "schemaVersion": "1.0",
        "ts": _now_iso(),
        "event": "agent_activate",
        "name": str(name)[:200],
        "task_id": _task_id_from(payload.get("session_id") or ""),
        "arm": _arm_from_cwd(),
        "duration_ms": None,
        "tokens": _extract_tokens(tool_response),
        "status": "error" if error else "ok",
        "error": str(error)[:500] if error else None,
    }


def _build_phase_boundary(payload: dict, phase_name: str) -> dict:
    # phase_name is one of the 6 4D phases; the schema enforces the enum.
    return {
        "schemaVersion": "1.0",
        "ts": _now_iso(),
        "event": "phase_boundary",
        "name": phase_name,
        "task_id": _task_id_from(payload.get("session_id") or ""),
        "arm": _arm_from_cwd(),
        "duration_ms": None,
        "tokens": None,
        "status": "ok",
        "error": None,
    }


VALID_PHASES = ("describe", "delegate", "gate", "execute", "diligent", "disclose")


def _append_record(record: dict) -> None:
    TRACES_DIR.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    # POSIX O_APPEND: appends < 4096 bytes are atomic; no flock needed.
    with _today_filename().open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def main() -> int:
    # Optional --phase flag: when present, emit a phase_boundary record using
    # the runtime event's session_id; ignore tool_name dispatch entirely. This
    # is how UserPromptSubmit / PreToolUse(Write|Edit) / PostToolUse(Write|Edit)
    # / Stop hooks call this script with different phases.
    phase = None
    args = sys.argv[1:]
    if args and args[0] == "--phase" and len(args) >= 2 and args[1] in VALID_PHASES:
        phase = args[1]

    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # Malformed stdin — never block the tool call.

    try:
        if phase is not None:
            record = _build_phase_boundary(payload, phase)
        else:
            tool = payload.get("tool_name")
            if tool == "Skill":
                record = _build_skill_fire(payload)
            elif tool == "Agent":
                record = _build_agent_activate(payload)
            else:
                record = None
        if record is not None:
            _append_record(record)
    except Exception:
        pass  # Best-effort. Trace failure must never affect the agent.

    return 0


if __name__ == "__main__":
    sys.exit(main())
