#!/usr/bin/env python3
"""g__pretool-bash__pipe-verdict.py: PreToolUse gate for CODE.pipe-verdict.

In a shell pipeline without `pipefail`, the exit status is the status of the
LAST stage. `git push ... | tail -3` reports tail's 0 even when the pre-push
hook rejected the push, and `pytest | tee log` reports tee's 0 on a red suite.
The harness then shows "exit code 0" and the model reads a verdict that belongs
to another program.

This gate denies a Bash command where a VERDICT command (one whose exit status
is the result: a push, a selftest, a test suite, the brain doctor) sits in a
pipeline stage that is not the last one, unless the command already arms
`pipefail` before it or reads `PIPESTATUS`. The fix it prints is one edit:
prefix `set -o pipefail;`, or redirect to a file and read `$?`.

Not seen (residuals, by design): a pipeline inside `bash -c "..."`, `$( ... )`
or backticks, an `eval` string, and verdict commands not in _VERDICT_PATTERNS.

Stdin:  {"tool_name": str, "tool_input": {"command": str}, ...}
Stdout: deny JSON on match, nothing on pass.
Exit:   always 0. Fail-open on its own errors (bad input, parser exception).
"""
from __future__ import annotations

import json
import os
import re
import sys

for _stream in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

_KERNEL_RULE = "CODE.pipe-verdict"

# A stage is a verdict when one of these matches it (after wrapper stripping).
# Anchored to a command position so `echo git push` or `grep pytest` does not count.
_VERDICT_PATTERNS = (
    ("git push", re.compile(r"^\s*git\s+(?:-[Cc]\s+\S+\s+)*push\b")),
    ("--selftest", re.compile(r"^\s*\S*(?:python3?|\.py)\b[^\n]*\s--selftest\b")),
    ("pytest", re.compile(r"^\s*(?:\S*/)?(?:pytest|py\.test)\b")),
    ("python -m pytest/unittest", re.compile(r"^\s*\S*python3?\s+(?:-\S+\s+)*-m\s+(?:pytest|unittest)\b")),
    ("npm/pnpm/yarn test", re.compile(r"^\s*(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?test\b")),
    ("go test", re.compile(r"^\s*go\s+test\b")),
    ("cargo test", re.compile(r"^\s*cargo\s+test\b")),
    ("make test", re.compile(r"^\s*make\s+(?:\S+\s+)*(?:test|check)\b")),
    ("brain_doctor", re.compile(r"^\s*\S*python3?\s+\S*brain_doctor\.py\b")),
)

_PIPEFAIL_RE = re.compile(r"(?:\bset\s+(?:-[a-zA-Z]*\s+)*-[a-zA-Z]*o\s+pipefail\b|\bset\s+-o\s+pipefail\b|\bshopt\b.*\bpipefail\b)")
_PIPESTATUS_RE = re.compile(r"\bPIPESTATUS\b")

# Leading wrappers peeled before matching (same family as git-discipline).
_W_ASSIGN = re.compile(r"^[A-Za-z_]\w*=\S*\s+")
_W_GROUP = re.compile(r"^[({]\s*")
_W_PREFIX = re.compile(r"^(?:env|command|exec|time|nice|nohup|sudo|timeout\s+\S+)\s+")
_W_FLAG = re.compile(r"^-\S+\s+")


def _strip_wrappers(stage: str) -> str:
    s = stage.lstrip()
    prev = None
    while s != prev:
        prev = s
        for pat in (_W_GROUP, _W_ASSIGN, _W_PREFIX):
            m = pat.match(s)
            if m:
                s = s[m.end():]
                # flags right after a prefix wrapper (env -i, nice -n 5 ...)
                while True:
                    m2 = _W_FLAG.match(s)
                    if not m2:
                        break
                    s = s[m2.end():]
                break
    return s


def _pipelines(cmd: str) -> list:
    """Split into lists (; && || & newline), each a list of pipe stages.

    Quotes are honoured: a `|` inside '...' or "..." is text. `||` separates
    lists, it is not a pipe. `|&` is a pipe. Comments (# at word start) end
    the line.
    """
    cmd = cmd.replace("\\\n", " ")
    lists, stages, buf = [], [], []
    in_sq = in_dq = False
    i, n = 0, len(cmd)

    def end_stage():
        stages.append("".join(buf))
        buf.clear()

    def end_list():
        end_stage()
        lists.append([s for s in stages if s.strip()])
        stages.clear()

    while i < n:
        c = cmd[i]
        if c == "\\" and not in_sq and i + 1 < n:
            buf.append(cmd[i:i + 2])
            i += 2
            continue
        if c == "'" and not in_dq:
            in_sq = not in_sq
        elif c == '"' and not in_sq:
            in_dq = not in_dq
        elif not in_sq and not in_dq:
            two = cmd[i:i + 2]
            if c == "#" and (i == 0 or cmd[i - 1] in " \t\n;"):
                while i < n and cmd[i] != "\n":
                    i += 1
                continue
            if two in ("&&", "||"):
                end_list()
                i += 2
                continue
            if two == "|&":
                end_stage()
                i += 2
                continue
            if c == "|":
                end_stage()
                i += 1
                continue
            if c in ";\n":
                end_list()
                i += 1
                continue
            if c == "&" and two != "&>" and (i == 0 or cmd[i - 1] not in "<>"):
                end_list()
                i += 1
                continue
        buf.append(c)
        i += 1
    end_list()
    return [p for p in lists if p]


def _verdict_name(stage: str):
    norm = _strip_wrappers(stage)
    for name, pat in _VERDICT_PATTERNS:
        if pat.search(norm):
            return name
    return None


def find_masked_verdict(cmd: str):
    """Return (verdict_name, stage_text) for the first masked verdict, or None."""
    if _PIPESTATUS_RE.search(cmd):
        return None
    pf = _PIPEFAIL_RE.search(cmd)
    pf_at = pf.start() if pf else None
    pos = 0
    for stages in _pipelines(cmd):
        for stage in stages[:-1]:  # the last stage owns the exit code
            name = _verdict_name(stage)
            if not name:
                continue
            at = cmd.find(stage.strip(), pos)
            if pf_at is not None and (at == -1 or pf_at < at):
                continue  # pipefail armed before this pipeline
            return name, stage.strip()
    return None


def _journal_deny(reason, payload=None) -> None:
    """Mirror the refusal into the kernel journal. Fail-open by contract."""
    try:
        import importlib.util
        _path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kernel_proc.py")
        _spec = importlib.util.spec_from_file_location("_kernel_proc_journal", _path)
        _kp = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_kp)
        _payload = payload if isinstance(payload, dict) else {}
        _kp.journal_deny(_KERNEL_RULE, reason, _payload.get("tool_use_id"), _kp.resolve_pid(_payload))
    except Exception:
        pass


def _deny(reason: str, payload: dict) -> None:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}))
    _journal_deny(reason, payload)


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    try:
        if (data.get("tool_name") or "") != "Bash":
            return 0
        cmd = (data.get("tool_input") or {}).get("command") or ""
        hit = find_masked_verdict(cmd)
        if hit:
            name, stage = hit
            _deny(
                f"⛔ PIPE-VERDICT: `{stage[:120]}` ({name}) is piped into a later stage with no "
                f"`pipefail`, so the exit code you will read belongs to the last stage, not to "
                f"{name}. Prefix the command with `set -o pipefail;`, or redirect instead: "
                f"`<cmd> > log 2>&1; echo \"x=$?\"` and read the log. For a push, confirm with "
                f"`git ls-remote` before saying it landed.",
                data,
            )
    except Exception:
        pass
    return 0


def _selftest() -> int:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import gate_selftest
    argv = sys.argv
    idx = argv.index("--selftest")
    fixture = argv[idx + 1] if len(argv) > idx + 1 else "registry/fixtures/CODE.pipe-verdict"
    return gate_selftest.run_gate_selftest(__file__, fixture)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
