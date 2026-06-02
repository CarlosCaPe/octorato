#!/usr/bin/env python3
"""PreToolUse Bash hook — QA gate (FAIL-CLOSED for merge actions).

When a Bash command is detected as a merge action (gh pr merge, git merge into
main/master, or git push directly to main/master), this hook BLOCKS execution
unless the env var OCTO_QA_OK=1 is set (confirming an independent QA agent
has already reviewed the diff).

Fail-closed ONLY for positively-identified merge commands.
Any parsing error on a non-merge command → exit 0 (fail-open).
Design mirrors grafo-gate.py: same I/O protocol, same stdin JSON shape.

Operator directive 2026-06-01: NO deploy without QA agent approval.
"""
import os
import re
import sys
import json

# Patterns that positively identify a merge / direct-push action.
# Order matters: most-specific first to reduce false-negative risk.
_MERGE_PATTERNS = (
    re.compile(r"\bgh\s+pr\s+merge\b"),
    re.compile(r"\bgit\s+merge\b.*\b(main|master)\b"),
    re.compile(r"\bgit\s+push\b[^|&;]*?(?:^|[\s:/])(?:HEAD:)?(main|master)(?=$|\s|:)"),
)


def _is_merge_command(cmd: str) -> bool:
    return any(p.search(cmd) for p in _MERGE_PATTERNS)


def _nudge(text: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": text,
        }
    }))


def main() -> int:
    # Parse stdin — if this fails we cannot know if it's a merge, so exit 0.
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0

    try:
        tool_input = data.get("tool_input") or {}
        cmd = (tool_input.get("command") or "")
    except Exception:
        return 0

    # Fast path: not a merge command → exit 0 silently.
    if not _is_merge_command(cmd):
        return 0

    # Positively identified as a merge action — check override.
    qa_ok = os.environ.get("OCTO_QA_OK", "").strip()
    if qa_ok == "1":
        _nudge(
            "QA gate: override present (OCTO_QA_OK=1) — proceeding. "
            "Make sure the QA agent's approval is on record for this diff."
        )
        return 0

    # BLOCK — fail-closed.
    print(
        "✗ QA GATE (fail-closed): no merge without an independent QA review.\n"
        "Spawn a QA sub-agent (Reality Checker / Evidence Collector / Code Reviewer) "
        "to validate the diff vs intent, THEN re-run with OCTO_QA_OK=1 to confirm "
        "QA passed.\n"
        "Operator directive 2026-06-01: the gate is the agent's approval, not just green CI.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    # Outer try only guards catastrophic interpreter errors.
    # We must NOT silently swallow a deliberate exit(2) block.
    try:
        result = main()
    except Exception:
        result = 0  # fail-open for unexpected crashes on non-merge paths
    sys.exit(result)
