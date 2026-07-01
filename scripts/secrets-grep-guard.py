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
    # .env / .env.* / .dev.vars
    re.compile(r'(?:^|[\s\'"~/])(\.env)(?:$|[\s\'"\.])', re.IGNORECASE),
    re.compile(r'(?:^|[\s\'"~/])(\.env\.\S+)', re.IGNORECASE),
    re.compile(r'(?:^|[\s\'"~/])(\.dev\.vars)(?:$|[\s\'"\.])', re.IGNORECASE),
    # credential-FILE shapes only: final path segment must be a known secret file
    re.compile(r'(?:^|[\s\'"/])(credentials|secrets)\.(json|yaml|yml|env)(?:$|[\s\'"])', re.IGNORECASE),
    re.compile(r'(?:^|[\s\'"/])[\w.\-]+\.(pem|key|p12|pfx)(?:$|[\s\'"])', re.IGNORECASE),
    re.compile(r'(?:^|[\s\'"/])id_rsa(?:$|[\s\'"])', re.IGNORECASE),
    # ~/.aws/ and ~/.ssh/ dirs
    re.compile(r'~/\.aws/', re.IGNORECASE),
    re.compile(r'~/\.ssh/', re.IGNORECASE),
    # narrow ~/.config/ to gh credentials and per-app credentials files
    re.compile(r'~/\.config/gh/', re.IGNORECASE),
    re.compile(r'~/\.config/[^/]+/credentials', re.IGNORECASE),
]

# ── redactor pipe patterns (allow if any present after the reader) ────────────
# A redactor must VISIBLY mask or narrow the output. A bare pipe to jq/python/awk
# passes the secret through whole (`cat .env | jq .` dumps everything), so it does
# NOT count. What counts:
#   • sed with a substitution command (s/.../.../) — replaces values
#   • awk with sub()/gsub()/gensub() — replaces values
#   • cut with a delimiter/field/char selection — keys-only extraction
#   • grep -o — extracts only the matched pattern, not the whole line
#   • an explicit redact script anywhere in the pipe

_REDACTOR_RE = re.compile(
    r"\|\s*(?:"
    r"sed\s+(?:-\w+\s+)*(?:-e\s*)?['\"]?s[/#|,]"       # sed 's/…/…/' substitution
    r"|awk\s+[^|]*\b(?:sub|gsub|gensub)\s*\("           # awk with a substitution call
    r"|cut\s+-[dcbf]"                                    # cut -d/-f/-c/-b field selection
    r"|grep\s+(?:-\w+\s+)*-o\b"                          # grep -o extraction
    r"|\S*redact\S*"                                     # explicit redact script
    r")",
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

        # Evaluate per shell segment (split on ; && || newline), NOT on the whole
        # string: `cat .env; cat ok | jq .` must not pass on the unrelated jq.
        for seg in re.split(r"(?:&&|\|\||;|\n)", command):
            if _has_reader(seg) and _has_secret_path(seg) and not _has_redactor(seg):
                print(json.dumps({
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": _DENY_REASON,
                    }
                }))
                return 0
    except Exception:
        pass  # fail-open: never break the user's command

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # fail-open: never break the user's command
