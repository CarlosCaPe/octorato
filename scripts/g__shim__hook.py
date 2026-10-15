#!/usr/bin/env python3
"""g__shim__hook.py: run an Octorato gate under a second harness (v11 AC-05).

Every Octorato gate reads one payload shape, the Claude Code PreToolUse stdin:
tool_name, tool_input, cwd, session_id, transcript_path. A second harness
sends its own shape and reads its own block contract. This shim sits between
the two:

  harness payload --translate--> Claude-shaped payload --> gate (subprocess)
  gate deny       --translate--> the harness's block (exit 2, reason on stderr)

Usage (as the hook command a projector writes):

  python3 g__shim__hook.py --harness gemini-cli --gate g__pretool__arming-surface.py
  python3 g__shim__hook.py --harness codex-cli  --gate g__pretool-bash__prod-write.py [--fail-open]
  python3 g__shim__hook.py --selftest [fixture_dir]

Fail-closed by default. For a fail-closed gate (every gate unless the projector
passes --fail-open) the shim BLOCKS when:
  - the payload is not JSON, not an object, or not the harness's pre-tool event;
  - a tool has no translation (unknown tool, a Gemini MCP call whose server and
    tool cannot be recovered from mcp_context, an apply_patch with no readable
    file operation);
  - the gate crashes, times out, or cannot be found;
  - the harness is not `supported` in registry/runtimes.yaml (always, see below).
An unreadable payload never becomes an allow: a harness upgrade that changes
the payload shape turns into loud blocks, not silent passes.

Status. The harness id must be an entry of registry/runtimes.yaml (read next to
this script, never from an argument) with `status: supported`. A `gap` harness
is refused with a block and a message naming the status: the mapping code is
here and proven by the selftest, but a harness the census has not measured
blocking is never run as if it were guarded. The selftest drives the same code
with the status supplied in-process, which no command line can reach.

Block contract. Both harnesses document "exit 2 with the reason on stderr"
(registry/census/gemini.json and codex.json, contract.block_contract), and for
Gemini CLI any other non-zero exit is a non-blocking warning. So a deny is
always exit 2 with the reason on stderr, and the shim never lets an exception
escape as exit 1. The JSON forms each harness also documents are not used: one
contract both harnesses read the same way leaves nothing to drift.

Translation, per harness (sources: the census records and the module docstring
of scripts/runtime_census.py):

  Gemini CLI (BeforeTool)
    run_shell_command {command, dir_path?} -> Bash {command}; cwd joins dir_path
    write_file {file_path, content}        -> Write
    replace {file_path, old_string, new_string, allow_multiple?} -> Edit
    mcp_<server>_<tool> + mcp_context {server_name, tool_name}
                                           -> mcp__<server>__<tool>
      The mcp_context shape is ASSUMED in the census (payload_shape: assumed).
      The name alone cannot be split (server and tool may both hold `_`), so
      without a context whose parts rebuild the exact tool_name, the call has
      no translation and a fail-closed gate blocks it.

  Codex CLI (PreToolUse)
    Bash {command}                         -> Bash {command}
    apply_patch {command: <patch text>}    -> one gate call PER file operation:
      *** Add File: p      -> Write {p, content}
      *** Update File: p   -> Edit {p, old_string, new_string} (context kept)
      *** Move to: q       -> also Write {q, new side of the hunks}
      *** Delete File: p   -> Write {p, ""} (a delete destroys the content; a
                              path-guard gate sees it as the write it is)
      Relative paths resolve against the payload cwd. Any denial blocks the
      whole patch. A patch with no readable operation blocks.
    mcp__<server>__<tool>                  -> unchanged (no mcp_context needed)

Self-contained on purpose: it imports nothing from the brain, so the only file
that decides whether a second harness is guarded is this one, which is on the
arming surface (scripts/g__pretool__arming-surface.py, `g__shim__*.py`).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

for _stream in (sys.stdin, sys.stdout, sys.stderr):
    try:
        # stdin strict: a byte that is not UTF-8 must fail the read (and block),
        # not be replaced by U+FFFD inside a path the gate then fails to match.
        _stream.reconfigure(encoding="utf-8",
                            errors="strict" if _stream is sys.stdin else "replace")
    except (AttributeError, ValueError):
        pass

_HERE = os.path.dirname(os.path.abspath(__file__))
BRAIN = os.path.dirname(_HERE)
RUNTIMES = os.path.join(BRAIN, "registry", "runtimes.yaml")
DEFAULT_FIXTURES = os.path.join("registry", "fixtures", "ARCHITECTURE.hook-shim")

BLOCK_EXIT = 2
GATE_TIMEOUT_S = 60
_GATE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.py")
_CLAUDE_MCP = re.compile(r"mcp__([^_]+(?:_[^_]+)*)__(.+)")


class TranslationError(ValueError):
    """The harness payload cannot be read into the fields a gate decides on."""


class RefusedHarness(ValueError):
    """The harness is unknown to the registry or not `supported` there."""


# --- registry -----------------------------------------------------------------

_ENTRY = re.compile(r"^  ([A-Za-z0-9_-]+):\s*(?:#.*)?$")
_STATUS = re.compile(r"^    status:\s*([A-Za-z0-9_-]+)\s*(?:#.*)?$")


def registry_status(harness: str, path: str = RUNTIMES) -> str | None:
    """`status` of one entry under `runtimes:`; None when absent or ambiguous.

    A line reader, not a YAML load: the hook runs on every tool call of the
    harness and must not depend on PyYAML being importable there. The format
    it reads is the two-space entry / four-space field layout the file holds.
    A repeated entry, a repeated status or an unreadable file reads as None,
    which the caller treats as not supported.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    in_runtimes, current, seen, found = False, None, set(), []
    for line in lines:
        if line.startswith("runtimes:"):
            in_runtimes = True
            continue
        if in_runtimes and line and not line.startswith(" ") and not line.startswith("#"):
            in_runtimes = False
        if not in_runtimes:
            continue
        m = _ENTRY.match(line)
        if m:
            current = m.group(1)
            if current == harness and current in seen:
                return None
            seen.add(current)
            continue
        m = _STATUS.match(line)
        if m and current == harness:
            found.append(m.group(1))
    return found[0] if len(found) == 1 else None


# --- translation ----------------------------------------------------------------

def _require(cond: bool, why: str) -> None:
    if not cond:
        raise TranslationError(why)


def _str_field(d: dict, key: str, why: str) -> str:
    v = d.get(key)
    _require(isinstance(v, str), why)
    return v


def _base(p: dict, event: str) -> dict:
    _require(p.get("hook_event_name") == event,
             f"hook_event_name {p.get('hook_event_name')!r} is not {event}")
    cwd = p.get("cwd")
    _require(isinstance(cwd, str) and cwd != "", "payload has no cwd")
    out = {"hook_event_name": "PreToolUse", "cwd": cwd}
    for k in ("session_id", "transcript_path", "tool_use_id", "permission_mode"):
        if isinstance(p.get(k), str) and p.get(k):
            out[k] = p[k]
    return out


def _call(base: dict, tool: str, tool_input: dict, **extra) -> dict:
    d = dict(base)
    d.update(extra)
    d["tool_name"] = tool
    d["tool_input"] = tool_input
    return d


def translate_gemini(p: dict) -> list[dict]:
    base = _base(p, "BeforeTool")
    tool = p.get("tool_name")
    ti = p.get("tool_input")
    _require(isinstance(tool, str) and isinstance(ti, dict),
             "missing tool_name or tool_input")
    if tool == "run_shell_command":
        cmd = _str_field(ti, "command", "run_shell_command without command")
        d = ti.get("dir_path")
        cwd = base["cwd"]
        if d is not None:
            _require(isinstance(d, str) and d != "", "dir_path is not a path")
            cwd = os.path.normpath(os.path.join(cwd, d))
        return [_call(base, "Bash", {"command": cmd}, cwd=cwd)]
    if tool == "write_file":
        return [_call(base, "Write", {
            "file_path": _str_field(ti, "file_path", "write_file without file_path"),
            "content": _str_field(ti, "content", "write_file without content")})]
    if tool == "replace":
        am = ti.get("allow_multiple", False)
        _require(isinstance(am, bool), "allow_multiple is not a boolean")
        return [_call(base, "Edit", {
            "file_path": _str_field(ti, "file_path", "replace without file_path"),
            "old_string": _str_field(ti, "old_string", "replace without old_string"),
            "new_string": _str_field(ti, "new_string", "replace without new_string"),
            "replace_all": am})]
    if tool.startswith("mcp_"):
        ctx = p.get("mcp_context")
        _require(isinstance(ctx, dict), f"MCP tool {tool!r} without mcp_context: "
                 "server and tool cannot be split from the name alone")
        server, name = ctx.get("server_name"), ctx.get("tool_name")
        _require(isinstance(server, str) and server and isinstance(name, str) and name,
                 "mcp_context without server_name/tool_name")
        _require(f"mcp_{server}_{name}" == tool,
                 f"mcp_context {server!r}/{name!r} does not rebuild tool_name {tool!r}")
        return [_call(base, f"mcp__{server}__{name}", dict(ti))]
    raise TranslationError(f"Gemini tool {tool!r} has no translation")


_PATCH_OP = re.compile(r"^\*\*\* (Add|Update|Delete) File: (.+)$")
_MOVE_TO = re.compile(r"^\*\*\* Move to: (.+)$")


def parse_apply_patch(text, cwd: str) -> list[tuple[str, dict]]:
    """Every file operation of an apply_patch body as (tool_name, tool_input).

    Strict: a line outside the grammar fails the parse, so a patch this reader
    does not understand blocks rather than being half-read.
    """
    _require(isinstance(text, str), "apply_patch command is not text")
    lines = text.split("\n")
    while lines and lines[-1] == "":
        lines.pop()
    _require(len(lines) >= 2 and lines[0] == "*** Begin Patch" and lines[-1] == "*** End Patch",
             "apply_patch without Begin/End Patch")
    body = lines[1:-1]

    def _abs(path: str) -> str:
        path = path.strip()
        _require(path != "", "apply_patch file header without a path")
        return os.path.normpath(path if os.path.isabs(path) else os.path.join(cwd, path))

    ops, i = [], 0
    while i < len(body):
        m = _PATCH_OP.match(body[i])
        _require(bool(m), f"apply_patch line {i + 2} is not a file header: {body[i][:60]!r}")
        kind, path = m.group(1), _abs(m.group(2))
        i += 1
        chunk = []
        while i < len(body) and not _PATCH_OP.match(body[i]):
            chunk.append(body[i])
            i += 1
        if kind == "Add":
            _require(all(ln.startswith("+") for ln in chunk), "Add File with a non-added line")
            content = "\n".join(ln[1:] for ln in chunk) + ("\n" if chunk else "")
            ops.append(("Write", {"file_path": path, "content": content}))
        elif kind == "Delete":
            _require(not chunk, "Delete File followed by body lines")
            ops.append(("Write", {"file_path": path, "content": ""}))
        else:
            move = None
            if chunk and _MOVE_TO.match(chunk[0]):
                move = _abs(_MOVE_TO.match(chunk[0]).group(1))
                chunk = chunk[1:]
            old, new = [], []
            for ln in chunk:
                if ln.startswith("@@") or ln == "*** End of File":
                    continue
                if ln == "" or ln[0] == " ":
                    old.append(ln[1:])
                    new.append(ln[1:])
                elif ln[0] == "-":
                    old.append(ln[1:])
                elif ln[0] == "+":
                    new.append(ln[1:])
                else:
                    raise TranslationError(f"Update File hunk line unreadable: {ln[:60]!r}")
            _require(bool(old or new or move), "Update File with no hunk and no move")
            ops.append(("Edit", {"file_path": path, "old_string": "\n".join(old),
                                 "new_string": "\n".join(new)}))
            if move:
                ops.append(("Write", {"file_path": move, "content": "\n".join(new)}))
    _require(bool(ops), "apply_patch with no file operation")
    return ops


def translate_codex(p: dict) -> list[dict]:
    base = _base(p, "PreToolUse")
    tool = p.get("tool_name")
    ti = p.get("tool_input")
    _require(isinstance(tool, str) and isinstance(ti, dict),
             "missing tool_name or tool_input")
    if tool == "Bash":
        return [_call(base, "Bash", {"command": _str_field(ti, "command", "Bash without command")})]
    if tool == "apply_patch":
        return [_call(base, t, i) for t, i in parse_apply_patch(ti.get("command"), base["cwd"])]
    if tool.startswith("mcp__"):
        _require(bool(_CLAUDE_MCP.fullmatch(tool)), f"not an MCP tool name: {tool!r}")
        return [_call(base, tool, dict(ti))]
    raise TranslationError(f"Codex tool {tool!r} has no translation")


TRANSLATORS = {"gemini-cli": translate_gemini, "codex-cli": translate_codex}


def translate(harness: str, raw: str) -> list[dict]:
    """Claude-shaped gate payloads for one harness payload; raises when unreadable."""
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise TranslationError(f"payload is not JSON: {exc}") from exc
    _require(isinstance(payload, dict), "payload is not a JSON object")
    return TRANSLATORS[harness](payload)


# --- gate run ---------------------------------------------------------------------

def _gate_verdict(rc: int, stdout: str, stderr: str) -> tuple[bool, str]:
    """(blocked, reason). Same predicate as gate_selftest.emits_block, inlined so
    this file imports nothing from the brain."""
    reason = ""
    out = (stdout or "").strip()
    obj = None
    if out:
        try:
            obj = json.loads(out)
        except ValueError:
            obj = None
    if isinstance(obj, dict):
        hso = obj.get("hookSpecificOutput")
        if isinstance(hso, dict) and hso.get("permissionDecision") == "deny":
            return True, str(hso.get("permissionDecisionReason") or "")
        if obj.get("decision") == "block":
            return True, str(obj.get("reason") or "")
    if rc != 0:
        reason = (stderr or "").strip() or out
        return True, reason
    return False, reason


def run_gate(gate_path: str, call: dict, env: dict | None, cwd: str | None,
             fail_closed: bool) -> tuple[bool, str]:
    body = json.dumps(call, ensure_ascii=True)
    try:
        cp = subprocess.run([sys.executable, gate_path], input=body,
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", env=env, cwd=cwd, timeout=GATE_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return fail_closed, f"gate timed out after {GATE_TIMEOUT_S}s"
    except OSError as exc:
        return fail_closed, f"gate could not start: {exc}"
    blocked, reason = _gate_verdict(cp.returncode, cp.stdout, cp.stderr)
    if blocked and not fail_closed and cp.returncode != 0 and cp.returncode != BLOCK_EXIT \
            and not (cp.stdout or "").strip():
        # a fail-open gate that crashed: its own contract is to allow
        return False, reason
    return blocked, reason


def decide(harness: str, gate: str, raw: str, *, fail_closed: bool = True,
           status_of=registry_status, env: dict | None = None,
           cwd: str | None = None) -> tuple[int, str]:
    """(exit_code, stderr_text) the harness must see. Never raises."""
    tag = f"OCTORATO SHIM ({harness} -> {gate})"
    try:
        if harness not in TRANSLATORS:
            raise RefusedHarness(f"harness {harness!r} has no translation in this shim "
                                 f"(known: {', '.join(sorted(TRANSLATORS))})")
        status = status_of(harness)
        if status != "supported":
            raise RefusedHarness(
                f"harness {harness!r} is {status or 'absent'!s} in registry/runtimes.yaml, "
                "not `supported`: no census shows it blocking, so the shim refuses to run "
                "a gate under it")
        if not _GATE_NAME.fullmatch(gate or ""):
            raise RefusedHarness(f"gate {gate!r} is not a script name in scripts/")
        gate_path = os.path.join(_HERE, gate)
        if not os.path.isfile(gate_path):
            raise RefusedHarness(f"gate {gate!r} does not exist in scripts/")
    except RefusedHarness as exc:
        return BLOCK_EXIT, f"{tag}: refused: {exc}"
    except Exception as exc:  # status reader fault: never an allow
        return BLOCK_EXIT, f"{tag}: refused: {type(exc).__name__}: {exc}"

    try:
        calls = translate(harness, raw)
    except Exception as exc:
        why = f"payload not translatable: {type(exc).__name__}: {exc}"
        if fail_closed:
            return BLOCK_EXIT, f"{tag}: blocked (fail-closed): {why}"
        return 0, f"{tag}: skipped (fail-open gate): {why}"

    for call in calls:
        try:
            blocked, reason = run_gate(gate_path, call, env, cwd, fail_closed)
        except Exception as exc:
            blocked, reason = fail_closed, f"{type(exc).__name__}: {exc}"
        if blocked:
            target = (call.get("tool_input") or {}).get("file_path") or call.get("tool_name")
            prefix = f"{tag}: denied" + (f" [{target}]" if len(calls) > 1 else "")
            return BLOCK_EXIT, f"{prefix}: {reason or 'the gate denied without a reason'}"
    return 0, ""


# --- CLI ----------------------------------------------------------------------------

def _arg(argv: list[str], name: str) -> str | None:
    if name in argv:
        i = argv.index(name)
        return argv[i + 1] if i + 1 < len(argv) else ""
    return None


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--selftest":
        return _selftest(argv[1] if len(argv) > 1 else None)
    harness = _arg(argv, "--harness") or ""
    gate = _arg(argv, "--gate") or ""
    fail_closed = "--fail-open" not in argv
    try:
        raw = sys.stdin.read()
    except Exception as exc:  # undecodable stdin
        raw = None
        read_error = f"{type(exc).__name__}: {exc}"
    else:
        read_error = ""
    if raw is None:
        if fail_closed:
            sys.stderr.write(f"OCTORATO SHIM ({harness} -> {gate}): blocked (fail-closed): "
                             f"stdin unreadable: {read_error}\n")
            return BLOCK_EXIT
        return 0
    rc, msg = decide(harness, gate, raw, fail_closed=fail_closed)
    if msg:
        sys.stderr.write(msg.rstrip("\n") + "\n")
    return rc


# --- selftest -------------------------------------------------------------------------

def _selftest(fdir: str | None = None) -> int:
    """Every fixture leg through decide(), the gate as a real subprocess under a
    sandbox HOME; plus CLI legs through the real registry and argv path.

    Fixture file (violation*.json must block, benign*.json must allow):
      {"harness": "gemini-cli", "gate": "<script>.py",
       "payload": {...} | "payload_raw": "<text>",
       "status": "supported" (default) | "gap" | null,
       "fail_open": false, "home_from": "<other fixture dir with home/>",
       "_setup": {"expect_reason": "<substring>" | ["<substring>", ...]}}
    A leg the GATE must deny carries ": denied" in expect_reason, so a payload the
    shim failed to translate cannot pass for a gate's refusal.
    `{{SANDBOX}}` expands to the leg's HOME; a relative transcript_path resolves
    against this fixture directory.
    """
    import glob as _glob
    import shutil
    import tempfile

    fdir = fdir or DEFAULT_FIXTURES
    if not os.path.isabs(fdir):
        fdir = os.path.join(BRAIN, fdir)
    if not os.path.isdir(fdir):
        print(f"selftest FAIL: fixture dir missing: {fdir}", file=sys.stderr)
        return 1
    files = sorted(_glob.glob(os.path.join(fdir, "violation*.json"))) + \
        sorted(_glob.glob(os.path.join(fdir, "benign*.json")))
    names = [os.path.basename(f) for f in files]
    if not any(n.startswith("violation") for n in names) or \
       not any(n.startswith("benign") for n in names):
        print(f"selftest FAIL: need violation*.json and benign*.json in {fdir}",
              file=sys.stderr)
        return 1

    strip = ("OCTO_MERGE_APPROVE", "OCTO_QA_OK", "OCTO_ALLOW_FORCE", "OCTO_LANE_OVERRIDE",
             "OCTO_GRAFO_OVERRIDE", "OCTO_KERNEL_OPEN", "GIT_DIR", "GIT_WORK_TREE",
             "GIT_INDEX_FILE", "GIT_PREFIX", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY",
             "GIT_NAMESPACE", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_QUARANTINE_PATH")
    failures, blocked, allowed = [], 0, 0
    for path, name in zip(files, names):
        with open(path, encoding="utf-8") as fh:
            fx = json.load(fh)
        setup = fx.get("_setup") or {}
        sandbox = tempfile.mkdtemp(prefix="shim-selftest-")
        try:
            os.makedirs(os.path.join(sandbox, ".claude", "scripts"), exist_ok=True)
            os.makedirs(os.path.join(sandbox, "wt", "shim", "scripts"), exist_ok=True)
            if fx.get("home_from"):
                seed = os.path.join(os.path.dirname(fdir), fx["home_from"], "home")
                if os.path.isdir(seed):
                    shutil.copytree(seed, sandbox, dirs_exist_ok=True)
            if "payload_raw" in fx:
                raw = fx["payload_raw"]
            else:
                payload = fx["payload"]
                tp = payload.get("transcript_path") if isinstance(payload, dict) else None
                if isinstance(tp, str) and tp and not os.path.isabs(tp):
                    payload["transcript_path"] = os.path.abspath(os.path.join(fdir, tp))
                raw = json.dumps(payload).replace(
                    "{{SANDBOX}}", json.dumps(sandbox.replace("\\", "/"))[1:-1])
            env = {k: v for k, v in os.environ.items() if k not in strip}
            env.update(HOME=sandbox, USERPROFILE=sandbox, CLAUDE_SESSION_ID="__selftest__")
            status = fx.get("status", "supported")
            rc, msg = decide(fx["harness"], fx["gate"], raw,
                             fail_closed=not fx.get("fail_open", False),
                             status_of=lambda _h, _s=status: _s,
                             env=env, cwd=sandbox)
        except Exception as exc:
            failures.append(f"{name}: leg raised {type(exc).__name__}: {exc}")
            continue
        finally:
            shutil.rmtree(sandbox, ignore_errors=True)
        if name.startswith("violation"):
            if rc != BLOCK_EXIT:
                failures.append(f"{name} did NOT block (rc={rc})")
                continue
            if not msg.strip():
                failures.append(f"{name} blocked with no reason on stderr")
                continue
            want = setup.get("expect_reason") or []
            want = [want] if isinstance(want, str) else want
            said = msg.replace("\\", "/")
            missing = [w for w in want if w not in said]
            if missing:
                failures.append(f"{name} blocked without {missing!r}: {msg[:160]}")
                continue
            blocked += 1
        else:
            if rc != 0:
                failures.append(f"{name} WAS blocked (must allow): {msg[:160]}")
                continue
            allowed += 1

    # CLI legs: the real argv, stdin and registry path, no status override.
    cli = [
        ("cli unparseable payload blocks", ["--harness", "gemini-cli", "--gate",
                                            "g__pretool__arming-surface.py"], "{not json", True),
        ("cli unknown harness refused", ["--harness", "claude-code", "--gate",
                                         "g__pretool__arming-surface.py"], "{}", True),
        ("cli undecodable stdin blocks", ["--harness", "codex-cli", "--gate",
                                          "g__pretool__arming-surface.py"], b"\xff\xfe\x00", True),
    ]
    for status_name in ("gemini-cli", "codex-cli"):
        if registry_status(status_name) != "supported":
            cli.append((f"cli {status_name} refused while not supported",
                        ["--harness", status_name, "--gate", "g__pretool__arming-surface.py"],
                        json.dumps({"hook_event_name": "BeforeTool", "cwd": "/tmp",
                                    "tool_name": "write_file",
                                    "tool_input": {"file_path": "/tmp/x", "content": ""}}),
                        True))
    for label, args, stdin, must_block in cli:
        data = stdin if isinstance(stdin, bytes) else stdin.encode("utf-8")
        env = {k: v for k, v in os.environ.items()
               if k not in strip and k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
        cp = subprocess.run([sys.executable, os.path.abspath(__file__)] + args,
                            input=data, capture_output=True, env=env, timeout=60)
        err = cp.stderr.decode("utf-8", "replace")
        if must_block and (cp.returncode != BLOCK_EXIT or not err.strip()):
            failures.append(f"{label}: rc={cp.returncode} err={err[:120]!r}")
        else:
            blocked += 1

    if failures:
        print("selftest FAIL: " + "; ".join(failures), file=sys.stderr)
        return 1
    print(f"selftest PASS: {blocked} block + {allowed} allow "
          f"(g__shim__hook.py vs {os.path.basename(fdir)}); every block is exit 2 with "
          f"the reason on stderr, an unreadable payload blocks, and a harness not "
          f"`supported` in registry/runtimes.yaml is refused")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except BaseException as exc:  # never exit 1: Gemini reads 1 as a warning, not a block
        try:
            sys.stderr.write(f"OCTORATO SHIM: blocked (internal error): "
                             f"{type(exc).__name__}: {exc}\n")
        except Exception:
            pass
        os._exit(BLOCK_EXIT)
