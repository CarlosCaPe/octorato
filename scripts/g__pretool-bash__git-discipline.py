#!/usr/bin/env python3
"""g__pretool-bash__git-discipline.py: PreToolUse gate for the deterministic subset of GIT.version-control.

Two string-deterministic prohibitions from CLAUDE.md become fail-closed here; the
intent-bound halves (atomic commits, pull-before-push) stay model-side.

  (a) Bash: deny `git push --force` (NOT --force-with-lease) whose target resolves
      to main/master. Force-with-lease on a feature branch passes. Operator override
      via the agent-proof env OCTO_ALLOW_FORCE=1 (an inline env never reaches a
      harness-run hook, the qa-merge-gate precedent).
  (b) Write|Edit: deny a file_path whose name carries a sequential-copy suffix
      (_old / _backup / _final / _copy<N>). Git IS the version history.

Fail-CLOSED on a positive match, ALLOW on everything else. Deny-JSON shape reused
from dimension-awareness-hook.py.

Stdin:  {"tool_name": str, "tool_input": {...}, ...}
Stdout: deny JSON on match, nothing on pass.
Exit:   always 0.
"""
from __future__ import annotations

import json
import os
import re
import sys
# Force UTF-8 on stdout/stderr so glyphs survive on Windows shells (cp1252).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


_LANE_TOOLS = {"Write", "Edit", "NotebookEdit", "MultiEdit"}

# Sequential-copy filename suffixes (CLAUDE.md: "Never use sequential file names").
_BAD_SUFFIX_RE = re.compile(r"(_old|_backup|_final|_copy\d*)\.[^./]+$", re.IGNORECASE)

# git push ... main|master  (push must be the git subcommand; main/master a whole ref token)
_PAT_GIT_PUSH_MAIN = re.compile(
    r"^\s*git\s+"
    r"(?:-C\s+\S+\s+|-c\s+\S+\s+)*"
    r"push(?=\s)"
    r"[^|&;]*?"
    r"""(?:[\s:/'"+])(?:HEAD:)?\+?(main|master)(?=$|\s|:|['"])"""
)


def _split_subcmds(cmd: str) -> list:
    """Split on UNQUOTED shell separators only (; && || | newline)."""
    parts, buf, in_sq, in_dq = [], [], False, False
    cmd = cmd.replace("\\\n", " ")
    i, n = 0, len(cmd)
    while i < n:
        c = cmd[i]
        if c == "'" and not in_dq:
            in_sq = not in_sq
            buf.append(c)
        elif c == '"' and not in_sq:
            in_dq = not in_dq
            buf.append(c)
        elif not in_sq and not in_dq and cmd[i:i + 2] in ("&&", "||"):
            parts.append("".join(buf))
            buf = []
            i += 1
        elif not in_sq and not in_dq and c in ";|\n":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(c)
        i += 1
    parts.append("".join(buf))
    return [p for p in parts if p.strip()]


def _has_bare_force(sub: str) -> bool:
    """True if the sub-command carries --force / -f but NOT --force-with-lease."""
    import shlex
    try:
        tokens = shlex.split(sub)
    except ValueError:
        tokens = sub.split()
    force = False
    for t in tokens:
        if t.startswith("--force-with-lease"):
            return False  # the safe variant anywhere disarms the gate for this sub
        if t == "--force":
            force = True
        elif re.match(r"^-[a-zA-Z]*f[a-zA-Z]*$", t):  # short cluster containing f
            force = True
    return force


def _deny(reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}))


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0  # bad input → fail-open

    try:
        tool = data.get("tool_name") or ""
        tool_input = data.get("tool_input") or {}

        # (b) sequential-copy filename
        if tool in _LANE_TOOLS:
            fp = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
            if fp and _BAD_SUFFIX_RE.search(os.path.basename(str(fp))):
                _deny(
                    f"⛔ GIT discipline: '{os.path.basename(str(fp))}' uses a sequential-copy "
                    f"suffix (_old/_backup/_final/_copy). Git IS the version history. "
                    f"Use the single canonical name and let git track it."
                )
                return 0
            return 0

        # (a) force-push to main/master
        if tool == "Bash":
            if os.environ.get("OCTO_ALLOW_FORCE") == "1":
                return 0  # operator override (agent-proof env)
            cmd = tool_input.get("command") or ""
            for sub in _split_subcmds(cmd):
                if _PAT_GIT_PUSH_MAIN.match(sub) and _has_bare_force(sub):
                    _deny(
                        "⛔ GIT discipline: `git push --force` to main/master is denied. "
                        "Use --force-with-lease on a feature branch, or the operator can "
                        "set OCTO_ALLOW_FORCE=1 (agent-proof env) for the rare legit case. "
                        "Never force-push a protected default branch."
                    )
                    return 0
    except Exception:
        pass  # fail-open: never break the user's tool call

    return 0


def _selftest() -> int:
    import gate_selftest
    argv = sys.argv
    fixture = argv[argv.index("--selftest") + 1] if len(argv) > argv.index("--selftest") + 1 \
        else "registry/fixtures/GIT.version-control"
    return gate_selftest.run_gate_selftest(__file__, fixture)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # fail-open
