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


# ── narrowing readers (v10): the reader that opens the file prints no value ──
# The v10 census found 9 of 10 denies were reads that print only key NAMES or
# counts: `grep -c`, `grep -l`, `grep -o '^[A-Z_]*='`, `awk -F= '{print $1}'`,
# `cut -d= -f1 .env`. Those are already the redacted shape; the redactor rule
# above only recognised them AFTER a pipe. A pipeline stage that names the
# secret path passes when that stage itself can only emit names or counts.

def _words(stage: str) -> list:
    import shlex
    try:
        return shlex.split(stage, posix=True)
    except ValueError:
        return stage.split()


def _grep_narrows(words: list) -> bool:
    flags, pattern = set(), None
    i = 1
    while i < len(words):
        w = words[i]
        if w in ("-e", "--regexp") and i + 1 < len(words) and pattern is None:
            pattern = words[i + 1]; i += 2; continue
        if w.startswith("--"):
            flags.add(w)
        elif w.startswith("-") and len(w) > 1:
            flags.update("-" + ch for ch in w[1:])
        elif pattern is None:
            pattern = w
        i += 1
    # count, list-files, list-non-matching and quiet print no line content
    if flags & {"-c", "-l", "-L", "-q", "--count", "--files-with-matches",
                "--files-without-match", "--quiet", "--silent"}:
        return True
    if ("-o" in flags or "--only-matching" in flags) and pattern:
        # Anchored at line start, no wildcard that can cross into the value:
        # no '.', no negated class, no \S/\s, and '=' only as the last char.
        p = pattern
        return (p.startswith("^") and "." not in p and "[^" not in p
                and "\\S" not in p and "\\s" not in p and "=" not in p[:-1])
    return False


_RE_AWK_NAME_ONLY = re.compile(r"^-F\s*['\"]?=['\"]?$")


def _awk_narrows(words: list) -> bool:
    sep = any(_RE_AWK_NAME_ONLY.match(w) for w in words[1:]) or any(
        w == "-F" and j + 1 < len(words) and words[j + 1] == "="
        for j, w in enumerate(words))
    prog = next((w for w in words[1:] if "print" in w), "")
    if not sep or not prog:
        return False
    # every print/printf prints $1 and nothing else from the record
    return "$0" not in prog and not re.search(r"\$(?:[2-9]|\d{2,}|NF|\()", prog) \
        and "substr" not in prog and "getline" not in prog and "system" not in prog


def _stage_narrows(stage: str) -> bool:
    words = _words(stage.strip())
    while words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
        words = words[1:]                               # VAR=x prefix
    if not words:
        return False
    cmd = os.path.basename(words[0])
    if cmd in ("grep", "egrep", "fgrep", "rg"):
        return cmd != "rg" and _grep_narrows(words)
    if cmd == "awk":
        return _awk_narrows(words)
    if cmd == "cut":
        return any(w.startswith(("-f", "-c", "-b", "--fields")) for w in words[1:])
    if cmd == "wc":
        return True
    return False


def _narrowing_read(segment: str) -> bool:
    """Every pipeline stage that names a secret path only emits names/counts."""
    stages = [s for s in re.split(r"(?<!\|)\|(?!\|)", segment) if s.strip()]
    hits = [s for s in stages if _has_secret_path(s)]
    return bool(hits) and all(_stage_narrows(s) for s in hits)


def _has_reader(command: str) -> bool:
    return bool(_READER_RE.search(command))


def _has_secret_path(command: str) -> bool:
    return any(p.search(command) for p in _SECRET_PATH_PATTERNS)


def _has_redactor(command: str) -> bool:
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
        for seg in re.split(r"(?:&&|\|\||;|\n)", command):
            if _has_reader(seg) and _has_secret_path(seg) and not _has_redactor(seg) \
                    and not _narrowing_read(seg):
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
