#!/usr/bin/env python3
"""config-ship-verify.py — PreToolUse:Bash hook: ask before shipping generated configs.

Interrupts Bash commands that import or deploy a generated/templated config to an
external API without first verifying identifiers resolve to real data. "Imports
cleanly" is not the same as "has data"; a generated Datadog dashboard or wrangler
deploy with a --config flag can reference metric names or column names that return
zero rows in production.

Pattern: narrow trigger only on generated-config deploy actions. Normal wrangler
deploy (no --config/generated path), normal curl GETs, and everything else passes.

Stdin:  {"tool_name": "Bash", "tool_input": {"command": str}, ...}
Stdout: ask JSON on match, nothing on pass.
Exit:   always 0.
"""
from __future__ import annotations

import json
import re
import sys
# Force UTF-8 on stdout/stderr so the ✓ / ✗ / em-dash glyphs in reports
# survive on Windows shells defaulting to cp1252. Without this, a script
# can do its work correctly and still crash with UnicodeEncodeError when
# printing success. Applied repo-wide by _apply-utf8-reconfigure.py.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


# ── trigger patterns ──────────────────────────────────────────────────────────

# Pattern A: curl WRITE to a Datadog dashboard endpoint (v1 or v2); GETs pass through
_DD_DASHBOARD_RE = re.compile(
    r"curl\b"
    r"(?=.*?(?:-X\s*(?:POST|PUT|PATCH)\b|--request\s+(?:POST|PUT|PATCH)\b|-[dD]\s+['\"{@]))"
    r".*?api/v[12]/dashboard",
    re.IGNORECASE | re.DOTALL,
)

# Pattern B: wrangler deploy with --config flag or referencing generated/template path
_WRANGLER_GENERATED_RE = re.compile(
    r"\bwrangler\s+(pages\s+)?deploy\b.*?(--config\b|/generated[/\s]|/template[/\s]|generated\.toml|template\.toml)",
    re.IGNORECASE | re.DOTALL,
)

# Pattern C: curl POST to an external API URL with a local JSON file reference
# (i.e., "-d @<file>.json" or "--data @<file>.json") suggesting a config upload
_CURL_POST_JSON_RE = re.compile(
    r"\bcurl\b.*?-X\s+POST\b.*?-[d-]\s*@\S+\.json",
    re.IGNORECASE | re.DOTALL,
)
# Also handle when -d @file.json comes before -X POST
_CURL_POST_JSON_RE2 = re.compile(
    r"\bcurl\b.*?-[d-]\s*@\S+\.json.*?-X\s+POST",
    re.IGNORECASE | re.DOTALL,
)

_ASK_REASON = (
    "Generated config: run the ONE query that verifies an external identifier "
    "(metric/host/column) resolves to >=1 value BEFORE importing. "
    "'Imports cleanly' != 'has data'. See verify-generated-config-identifiers."
)


def _is_triggered(command: str) -> bool:
    if _DD_DASHBOARD_RE.search(command):
        return True
    if _WRANGLER_GENERATED_RE.search(command):
        return True
    if _CURL_POST_JSON_RE.search(command) or _CURL_POST_JSON_RE2.search(command):
        return True
    return False


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0  # fail-open on bad input

    try:
        if data.get("tool_name") != "Bash":
            return 0
        command = (data.get("tool_input") or {}).get("command") or ""
        if not command:
            return 0

        if not _is_triggered(command):
            return 0  # pass

        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": _ASK_REASON,
            }
        }))
    except Exception:
        pass  # fail-open: never break the user's command

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # fail-open: never break the user's command
