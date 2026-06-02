#!/usr/bin/env python3
"""PreToolUse hook — involuntary delegation reflex (FAIL-OPEN).

When a non-trivial / batchable Bash command runs, or when Write/Edit fires
on substantive implementation, this injects a 2D Delegate nudge reminding the
model to prefer routing that work to a sub-agent on the cheapest sufficient
model rather than burning the main-loop context.

It NEVER blocks. A broken hook must not break the user's command.
Design mirrors grafo-gate.py: same I/O protocol, same fail-open guarantee.
"""
import sys
import json
import re

# Heuristics for "non-trivial / batchable" Bash
_TRIVIAL_MAX_LEN = 180
_BATCHABLE_PATTERNS = re.compile(
    r"( && | \| |(?<!\S)for |(?<!\S)find |(?<!\S)xargs|grep -r|npm run|"
    r"(?<!\S)build|(?<!\S)test|(?<!\S)pytest)",
)


def _is_nontrivial_bash(cmd: str) -> bool:
    if len(cmd) > _TRIVIAL_MAX_LEN:
        return True
    return bool(_BATCHABLE_PATTERNS.search(cmd))


def _nudge(text: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": text,
        }
    }))


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0

    tool_name = (data.get("tool_name") or "").strip()
    tool_input = data.get("tool_input") or {}

    # Already delegation — good behaviour, stay silent.
    if tool_name in ("Agent", "Task"):
        return 0

    if tool_name == "Bash":
        cmd = (tool_input.get("command") or "")
        if _is_nontrivial_bash(cmd):
            _nudge(
                "♦ 2D Delegate — this looks like substantive/batchable work. "
                "Per the connector stance, prefer routing execution to a sub-agent "
                "on the cheapest sufficient model (Haiku mechanical / Sonnet build / "
                "Opus risky-review), not the main loop. "
                "SELF is only for opinion requests."
            )
        return 0

    if tool_name in ("Write", "Edit"):
        _nudge(
            "♦ 2D Delegate — non-trivial implementation should use a coworking "
            "builder + QA sub-agent pair (shift-left/continuous). "
            "If this is a trivial 1-liner, proceed; otherwise consider spawning agents."
        )
        return 0

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # fail-open: never break the user's command
