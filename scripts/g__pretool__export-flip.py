#!/usr/bin/env python3
"""g__pretool__export-flip.py: an agent never opens an arm to trace export.

The Export_Flip_Gate of the v11 tracing spec (AC-16). An arm's
`telemetry.export` is `deny` unless the operator writes `allow` with his own
hand; the Export_Guard (g__wrap__export-guard.py) then starts the upstream
tracing hook for that arm. This PreToolUse gate denies the agent's write that
would make that flip.

WHAT IT DECIDES ON, by tool:

  Write, Edit, MultiEdit (structural)
    The target is an arm manifest when its basename, or the basename of its
    real path (a symlink named anything that points at one), is `arm.json` or
    `arm.json.template` (the template seeds every new arm), compared
    case-folded. For such a target the gate computes the file AS IT WOULD BE
    AFTER the call (Write: the content; Edit and MultiEdit: the current file
    with every replacement applied in order, `replace_all` honoured) and
    parses it with the same strict JSON the guard uses. It denies when the
    result has `telemetry.export == "allow"` (any occurrence, a repeated key
    included) and the file as it is NOW does not. Keeping an `allow` the
    operator already wrote (a version bump in an open arm) is not a flip and
    passes; so does writing `deny`, removing the field, or any other file.
    An Edit or MultiEdit of an arm manifest the gate cannot read denies: the
    result cannot be computed, and fail-closed means not guessing.
  NotebookEdit
    On an arm manifest, denied: there is no JSON result to check.
  Bash (a speed bump, see below)
    A command that names an arm manifest (`arm.json` as a path component,
    case-folded, `farm.json` does not count) is denied when it also carries
    the word `allow`, a redirect INTO an arm manifest path, or a verb that
    writes a file whose bytes the gate cannot see (cp, mv, install, ln,
    rsync, tee, dd, truncate). Reads (cat, jq, grep without `allow`, git add,
    git diff) and removals (rm: an absent field is deny) pass.

Everything else passes untouched. A payload that is not one JSON object, or
any internal error, DENIES (fail-closed), with the reason.

Not journaled yet. A gate that declares `_KERNEL_RULE` journals every refusal
under that rule id, and the id must be registered in registry/rules.yaml
(test_octo_replay); registration is task T18, which adds both together.

No env unlock, on purpose: the flip is the operator's, made in his own
editor or terminal, which no hook sees. An unlock variable would be exactly
what an agent writes into a settings `env` block to flip the arm.

WHY THE SHELL LAYER IS A SPEED BUMP. A gate that parses the text the agent
writes cannot be a boundary: spellings are unbounded, readers are finite. The
Write/Edit path is structural (it checks the resulting bytes), the Bash path
catches the honest accident (`sed -i s/deny/allow/ arm.json`, a jq rewrite,
an echo into the file, a copy of another arm's manifest) and stops there.

NAMED RESIDUALS, measured by construction, deliberately not covered:
  - An interpreter or program that writes the file without naming it and the
    value on the command line: `python3 flip.py`, `node -e` reading the path
    from a variable, `make`, a git hook.
  - Obfuscated values or paths: `al""low`, `$V`, `${A}low`, base64, `arm.js*`,
    `printf` escapes, `sed y///`.
  - Git routes that rewrite the file from history or a patch: `git checkout
    <ref> -- arm.json`, `git restore --source`, `git apply`, `git stash pop`,
    `git merge`, `patch`. They land committed or reviewed bytes, and the
    Doctor's export check (T16) is the detector.
  - A file written under another name and renamed by a program the gate does
    not parse, or a hard link to an arm manifest under another basename.
  - An arm's `.claude/settings.json` setting the tracing switch: not this
    gate's field; the guard makes it inert for a deny arm and the Doctor
    detects it (plan.md, Risks).
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

_MANIFESTS = {"arm.json", "arm.json.template"}
_WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
_READ_MAX = 1 << 20

_SH_MANIFEST = re.compile(r"(?<![A-Za-z0-9_.-])arm\.json", re.I)
_SH_ALLOW = re.compile(r"\ballow\b", re.I)
_SH_REDIRECT = re.compile(r">\|?\s*[\"']?[^\s;&|<>\"']*(?<![A-Za-z0-9_.-])arm\.json", re.I)
_SH_PUT = re.compile(r"(?<![\w.-])(cp|mv|install|ln|rsync|tee|dd|truncate)(?![\w.-])")


def _deny(reason: str, payload=None) -> None:
    msg = (f"⛔ export-flip: {reason}. An arm's telemetry.export goes to `allow` only "
           f"by the operator's own hand, outside this session (v11 AC-16). Writing "
           f"`deny`, removing the field, or keeping an `allow` already there passes.")
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": msg,
    }}, ensure_ascii=False))


def _is_manifest(path: str) -> bool:
    names = {os.path.basename(path).casefold()}
    try:
        names.add(os.path.basename(os.path.realpath(path)).casefold())
    except (OSError, ValueError):
        pass
    return bool(names & _MANIFESTS)


def sets_allow(text) -> bool:
    """True when `text` parses as JSON whose top-level telemetry carries
    export == "allow", counting every repeated key (no last-wins)."""
    if not isinstance(text, str):
        return False
    try:
        tree = json.loads(text, object_pairs_hook=lambda pairs: ("__pairs__", pairs))
    except ValueError:
        return False
    if not (isinstance(tree, tuple) and tree[0] == "__pairs__"):
        return False
    for key, val in tree[1]:
        if key == "telemetry" and isinstance(val, tuple) and val[0] == "__pairs__":
            if any(k == "export" and v == "allow" for k, v in val[1]):
                return True
    return False


def _read(path: str):
    """Current text of the file, or None when absent or unreadable."""
    try:
        with open(path, "rb") as fh:
            data = fh.read(_READ_MAX + 1)
    except OSError:
        return None
    if len(data) > _READ_MAX:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _apply(before: str, edits: list) -> str:
    text = before
    for e in edits:
        if not isinstance(e, dict):
            raise ValueError("an edit is not an object")
        old, new = e.get("old_string"), e.get("new_string")
        if not isinstance(old, str) or not isinstance(new, str):
            raise ValueError("old_string/new_string missing")
        if old == "":
            text = new if text == "" else text
        elif e.get("replace_all"):
            text = text.replace(old, new)
        else:
            text = text.replace(old, new, 1)
    return text


def decide_write(tool: str, ti: dict, cwd: str):
    """None to allow, else the deny reason."""
    raw = ti.get("file_path") or ti.get("notebook_path")
    if not isinstance(raw, str) or not raw:
        return None
    path = os.path.expanduser(raw)
    if not os.path.isabs(path):
        path = os.path.join(cwd, path)
    if not _is_manifest(path):
        return None
    if tool == "NotebookEdit":
        return f"NotebookEdit on the arm manifest {raw}"
    real = os.path.realpath(path)
    before = _read(real)
    if tool == "Write":
        after = ti.get("content")
        if not isinstance(after, str):
            return f"Write to the arm manifest {raw} with no readable content"
    else:
        edits = ti.get("edits") if tool == "MultiEdit" else [ti]
        if not isinstance(edits, list):
            return f"{tool} of the arm manifest {raw} with no readable edits"
        if before is None:
            if os.path.exists(real) or not all(
                    isinstance(e, dict) and e.get("old_string") == "" for e in edits):
                return f"{tool} of the arm manifest {raw}, whose current bytes cannot be read"
            before = ""
        try:
            after = _apply(before, edits)
        except ValueError as exc:
            return f"{tool} of the arm manifest {raw}: {exc}"
    if sets_allow(after) and not sets_allow(before):
        return f"{tool} would set telemetry.export to `allow` in {raw}"
    return None


def decide_bash(cmd) -> str | None:
    if not isinstance(cmd, str) or not _SH_MANIFEST.search(cmd):
        return None
    if _SH_ALLOW.search(cmd):
        return "a shell command naming an arm manifest and the value `allow`"
    if _SH_REDIRECT.search(cmd):
        return "a shell redirect into an arm manifest, whose bytes the gate cannot see"
    m = _SH_PUT.search(cmd)
    if m:
        return (f"`{m.group(1)}` in a shell command naming an arm manifest: it writes "
                f"bytes the gate cannot see")
    return None


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
    except Exception as exc:
        _deny(f"unreadable hook payload ({type(exc).__name__}), fail-closed")
        return 0
    if not isinstance(payload, dict):
        _deny("hook payload is not a JSON object, fail-closed")
        return 0
    try:
        tool = payload.get("tool_name") or ""
        ti = payload.get("tool_input")
        if tool not in _WRITE_TOOLS and tool != "Bash":
            return 0
        if not isinstance(ti, dict):
            _deny(f"{tool} payload with no tool_input object, fail-closed", payload)
            return 0
        cwd = payload.get("cwd")
        if not (isinstance(cwd, str) and os.path.isabs(cwd)):
            cwd = os.getcwd()
        reason = decide_write(tool, ti, cwd) if tool in _WRITE_TOOLS \
            else decide_bash(ti.get("command"))
        if reason:
            _deny(reason, payload)
    except Exception as exc:
        _deny(f"internal error ({type(exc).__name__}: {exc}), fail-closed", payload)
    return 0


def _selftest() -> int:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import gate_selftest
    argv = sys.argv
    i = argv.index("--selftest")
    fixture = argv[i + 1] if len(argv) > i + 1 else "registry/fixtures/SECURITY.export-flip"
    return gate_selftest.run_gate_selftest(__file__, fixture)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    try:
        sys.exit(main())
    except Exception:
        _deny("internal error, fail-closed")
        sys.exit(0)
