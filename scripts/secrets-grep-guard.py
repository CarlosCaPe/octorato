#!/usr/bin/env python3
"""secrets-grep-guard.py — PreToolUse:Bash hook: deny raw reads of secret-bearing files.

Denies Bash commands that read secret-bearing files (env files, credential files,
SSH/AWS/wrangler config dirs) without piping through a redactor first.
Values leak when a label and secret share a line — a raw cat/grep exposes them
to the transcript. The fix is a redaction pipe; if that's present, we pass.

Fail-CLOSED on specific match, ALLOW on everything else. Error toward allow:
only the exact combination of (reader + secret-path + no redactor) triggers.

Stdin:  {"tool_name": "Bash", "tool_input": {"command": str}, ...}
Stdout: deny JSON on match, nothing on pass.
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


# ── reader commands ──────────────────────────────────────────────────────────

_READER_RE = re.compile(
    r"\b(grep|cat|head|tail|less|rg|awk|sed\s+-n|xxd|strings)\b",
    re.IGNORECASE,
)

# ── secret-bearing path patterns ─────────────────────────────────────────────

_SECRET_PATH_PATTERNS = [
    # explicit file names / extensions
    # Allow ~ as a leading separator (e.g. ~/.env, ~user/.env) in addition to
    # whitespace/quotes. The trailing boundary allows end-of-string, whitespace,
    # quotes, or a dot (e.g. .env.local handled by the next pattern).
    re.compile(r'(?:^|[\s\'"~/])(\.env)(?:$|[\s\'"\.])', re.IGNORECASE),
    re.compile(r'(?:^|[\s\'"~/])(\.env\.\S+)', re.IGNORECASE),
    re.compile(r'(?:^|[\s\'"~/])(\.dev\.vars)(?:$|[\s\'"\.])', re.IGNORECASE),
    # filenames containing credential/secret/token keywords
    re.compile(r'[\w/.\-]*(credential|secret|token)[\w/.\-]*', re.IGNORECASE),
    # sensitive dirs
    re.compile(r'~/\.aws/', re.IGNORECASE),
    re.compile(r'~/\.ssh/', re.IGNORECASE),
    re.compile(r'~/\.config/', re.IGNORECASE),
    re.compile(r'~/\.wrangler/', re.IGNORECASE),
    # wrangler secret subcommand
    re.compile(r'\bwrangler\s+secret\b', re.IGNORECASE),
]

# ── redactor pipe patterns (allow if any present after the reader) ────────────

_REDACTOR_RE = re.compile(
    r"\|\s*(sed\b|cut\b|grep\s+-o\b|awk\s+|python|jq\b)",
    re.IGNORECASE,
)

_DENY_REASON = (
    "Secret-bearing file: pipe through a redactor (values leak when label+secret "
    "share a line). See feedback_secrets_grep_safety."
)


def _has_reader(command: str) -> bool:
    return bool(_READER_RE.search(command))


def _has_secret_path(command: str) -> bool:
    return any(p.search(command) for p in _SECRET_PATH_PATTERNS)


def _has_redactor(command: str) -> bool:
    return bool(_REDACTOR_RE.search(command))


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

        if not (_has_reader(command) and _has_secret_path(command)):
            return 0  # at least one condition missing — pass

        if _has_redactor(command):
            return 0  # redactor present — pass

        # All three conditions met: deny
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": _DENY_REASON,
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
