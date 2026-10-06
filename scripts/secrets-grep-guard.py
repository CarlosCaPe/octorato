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
import os
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
    r"\b(grep|cat|head|tail|less|rg|awk|sed\s+-n|xxd|strings|cut)\b",
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


# ── exact name-only reads (v10) ───────────────────────────────────────────────
# The v10 census found most denies were reads that print only key NAMES. The
# exemption is three EXACT shapes, never a parser of what a command "can" print:
# QA of the first attempt (a grep/awk/cut flag reader) leaked values six ways
# (`awk -F= '{print $1} 1'`, `-v f=2 '{print $f}'`, `grep -l | xargs cat`, a
# second `-e '.*'`, ...) and turned `grep -c` / `grep -q` into a value oracle
# (one probe per character). So: a single plain sub-command, no pipe, chain,
# redirect, process or command substitution, one file operand, and exactly
#   grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' <file>   (-o/-E in either order, or -oE/-Eo)
#   awk -F= '{print $1}' <file>                   (exactly that program)
#   wc -l <file>
# Everything else that reads a secret file still needs a redactor.
# Residual, stated: a key NAME is printed (names are not secrets here), and
# `wc -l` prints a line count.
_NAME_PATTERN = "^[A-Za-z_][A-Za-z0-9_]*="
_RE_NOT_PLAIN = re.compile(r"[|<>`]|\$\(")


def _words(stage: str):
    import shlex
    try:
        return shlex.split(stage, posix=True)
    except ValueError:
        return None


def _exact_name_read(segment: str) -> bool:
    if _RE_NOT_PLAIN.search(segment):
        return False
    w = _words(segment.strip())
    if not w:
        return False
    if w[0] == "grep" and len(w) in (4, 5):
        flags, rest = w[1:-2], w[-2:]
        if sorted(flags) not in (["-oE"], ["-Eo"], ["-E", "-o"]):
            return False
        pattern, path = rest
        return pattern == _NAME_PATTERN and not path.startswith("-")
    if w[0] == "awk":
        if len(w) == 4 and w[1] == "-F=":
            prog, path = w[2], w[3]
        elif len(w) == 5 and w[1] == "-F" and w[2] == "=":
            prog, path = w[3], w[4]
        else:
            return False
        return prog == "{print $1}" and not path.startswith("-")
    if w[0] == "wc" and len(w) == 3 and w[1] == "-l":
        return not w[2].startswith("-")
    return False


def _segments(command: str) -> list:
    """Split on ; && || and newline OUTSIDE quotes. A plain re.split cut
    `awk -F= '{print $1; print}' .env` inside its program, so neither half
    carried both the reader and the path and the value printed (QA of v10)."""
    out, cur, quote, i = [], [], None, 0
    while i < len(command):
        ch = command[i]
        if quote:
            if ch == quote:
                quote = None
            elif ch == "\\" and quote == '"' and i + 1 < len(command):
                cur.append(ch); i += 1; ch = command[i]
            cur.append(ch); i += 1; continue
        if ch in "'\"":
            quote = ch
        elif ch == "\n" or ch == ";":
            out.append("".join(cur)); cur = []; i += 1; continue
        elif command.startswith(("&&", "||"), i):
            out.append("".join(cur)); cur = []; i += 2; continue
        cur.append(ch); i += 1
    out.append("".join(cur))
    return out


def _has_reader(command: str) -> bool:
    return bool(_READER_RE.search(command))


def _has_secret_path(command: str) -> bool:
    return any(p.search(command) for p in _SECRET_PATH_PATTERNS)


def _has_redactor(command: str) -> bool:
    # A later pipeline stage that itself reads the secret file is not a
    # redactor of the stage before it: `grep -c '' .env | grep -o '.*' .env`
    # prints the file whole (QA of v10).
    stages = re.split(r"(?<!\|)\|(?!\|)", command)
    if any(_has_reader(st) and _has_secret_path(st) for st in stages[1:]):
        return False
    return bool(_REDACTOR_RE.search(command))


# -- v8 kernel journal (Phase 4, v8-kernel.md) --------------------------------
_KERNEL_RULE = "SECURITY.never-read-secrets-raw"


def _journal_deny(reason, payload=None, tool_use_id=None) -> None:
    """Mirror this refusal into the refusing process's journal.

    FAIL-OPEN by contract: every error is swallowed and the verdict this gate
    just reached is unchanged. A journal that cannot be written must never turn
    a deny into an allow. kernel_proc is loaded by PATH through importlib, not
    by name, so nothing on sys.path can shadow it.
    """
    try:
        import importlib.util
        import os as _os
        _path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "kernel_proc.py")
        _spec = importlib.util.spec_from_file_location("_kernel_proc_journal", _path)
        _kp = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_kp)
        _payload = payload if isinstance(payload, dict) else {}
        _kp.journal_deny(_KERNEL_RULE, reason,
                         tool_use_id if tool_use_id is not None else _payload.get("tool_use_id"),
                         _kp.resolve_pid(_payload))
    except Exception:
        pass


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
        for seg in _segments(command):
            if _has_reader(seg) and _has_secret_path(seg) and not _has_redactor(seg) \
                    and not _exact_name_read(seg):
                print(json.dumps({
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": _DENY_REASON,
                    }
                }))
                _journal_deny(_DENY_REASON, data)
                return 0
    except Exception:
        pass  # fail-open: never break the user's command

    return 0


def _selftest() -> int:
    import gate_selftest
    argv = sys.argv
    fixture = argv[argv.index("--selftest") + 1] if len(argv) > argv.index("--selftest") + 1 \
        else "registry/fixtures/SECURITY.never-read-secrets-raw"
    return gate_selftest.run_gate_selftest(__file__, fixture)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # fail-open: never break the user's command
