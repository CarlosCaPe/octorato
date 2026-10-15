#!/usr/bin/env python3
"""runtime_census.py: measure a harness before the brain calls it supported.

Octorato's gates read one payload shape (the Claude Code hook stdin: tool_name,
tool_input, cwd, session_id). A second harness is useful only if its own hook
payload can be turned into those fields without loss, and only if the harness
actually runs on this machine. Both are measurements, not opinions, so this
script writes them to one tracked record per harness under registry/census/.

Two modes.

  (default)  deterministic, no model, no network. For every tool class
             (shell, file write, file edit, MCP) it takes a Block_Fixture pair
             from registry/fixtures/ (a violation a gate must deny and its
             benign twin), renders each as the harness's DOCUMENTED hook
             payload, translates that payload back into the gate fields, and
             records whether the round trip is lossless. A payload the
             translator cannot read is recorded as a failure, never as allowed.
             A second run with no fixture change leaves the record byte-equal.

  --live     one end-to-end call per harness from an empty sandbox directory
             with a prompt that carries no client data. Records the binary,
             the version, the account tier and the outcome. A 503, a timeout or
             a non-zero exit is a failed attempt with its timestamp, never an
             allow. The deterministic section is regenerated in the same run.

What the record never carries: an arm name, a $HOME path, a secret, a message
body. The MCP fixtures hold message text, so for that class only the key
names of tool_input are recorded. Every path is written with the home
directory folded to "~".

Blocking evidence (did the harness refuse the call through a projected hook)
is NOT produced here: the projected hooks and the shim are later tasks, and
this record marks every harness `status: measured`, never `supported`.

Gemini CLI, per geminicli.com/docs/hooks/reference and docs/tools/*:
  event BeforeTool; stdin {session_id, transcript_path, cwd, hook_event_name,
  timestamp, tool_name, tool_input, mcp_context?}; tools run_shell_command
  {command, description?, dir_path?}, write_file {file_path, content},
  replace {file_path, instruction, old_string, new_string, allow_multiple?};
  MCP tools are named mcp_<server>_<tool>; block = exit 2 with stderr reason,
  or JSON {"decision": "deny", "reason": ...}.

Codex CLI, per learn.chatgpt.com/docs/hooks:
  event PreToolUse; stdin {session_id, transcript_path, cwd, hook_event_name,
  model, permission_mode, turn_id, tool_name, tool_use_id, tool_input};
  shell matches as Bash with tool_input.command; file changes arrive as
  apply_patch with tool_input.command holding the patch text (matchers Edit
  and Write also match it); MCP tools are named mcp__<server>__<tool>; block =
  {"hookSpecificOutput": {"permissionDecision": "deny", ...}}, the older
  {"decision": "block"}, or exit 2 with stderr reason. Non-managed hooks run
  only after `/hooks` trust, recorded against the hook's hash.

Usage:
  python3 scripts/runtime_census.py [--live] [--harness gemini|codex]
                                    [--out registry/census] [--fixtures-root registry/fixtures]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

BRAIN = Path(__file__).resolve().parent.parent
FIXTURES_ROOT = BRAIN / "registry" / "fixtures"
CENSUS_DIR = BRAIN / "registry" / "census"

HARNESSES = ("gemini", "codex")
TOOL_CLASSES = ("shell", "file_write", "file_edit", "mcp")

# One Block_Fixture pair per tool class: a violation its gate must deny and the
# benign twin one edit away, both already tracked under registry/fixtures/.
BLOCK_FIXTURES = {
    "shell": {
        "gate": "SEC.prod-write-gate",
        "violation": "SEC.prod-write-gate/violation.json",
        "benign": "SEC.prod-write-gate/benign.json",
    },
    "file_write": {
        "gate": "ARCHITECTURE.arming-surface",
        "violation": "ARCHITECTURE.arming-surface/violation_settings_write.json",
        "benign": "ARCHITECTURE.arming-surface/benign_settings_write.json",
    },
    "file_edit": {
        "gate": "ARCHITECTURE.arming-surface",
        "violation": "ARCHITECTURE.arming-surface/violation_gate_body_edit.json",
        "benign": "ARCHITECTURE.arming-surface/benign_gate_body_edit.json",
    },
    "mcp": {
        "gate": "COMMS.outward-send-gate",
        "violation": "COMMS.outward-send-gate/violation_absence_assert_then_ask.json",
        "benign": "COMMS.outward-send-gate/benign_hatch_in_prompt.json",
    },
}

# The Claude-shaped fields a gate reads; everything else in a fixture is
# harness bookkeeping the shim may pass through but no gate decides on.
GATE_FIELDS = ("tool_name", "tool_input", "cwd", "session_id")

# Documented contract per harness (sources in the module docstring).
CONTRACTS = {
    "gemini": {
        "name": "Gemini CLI",
        "binary": "gemini",
        "hook_event": "BeforeTool",
        "config_paths": [".gemini/settings.json", "~/.gemini/settings.json"],
        "block_contract": [
            "exit 2 with the reason on stderr",
            "JSON {\"decision\": \"deny\", \"reason\": \"...\"} on stdout",
        ],
        "tool_map": {"Bash": "run_shell_command", "Write": "write_file",
                     "Edit": "replace", "mcp": "mcp_<server>_<tool>"},
        "trust_step": "none documented; hooks load from settings.json",
        "source": "geminicli.com/docs/hooks/reference, docs/tools/shell, docs/tools/file-system",
    },
    "codex": {
        "name": "Codex CLI",
        "binary": "codex",
        "hook_event": "PreToolUse",
        "config_paths": ["~/.codex/hooks.json", "~/.codex/config.toml [hooks]",
                         ".codex/hooks.json", ".codex/config.toml [hooks]"],
        "block_contract": [
            "JSON hookSpecificOutput.permissionDecision = deny with permissionDecisionReason",
            "older JSON {\"decision\": \"block\", \"reason\": \"...\"}",
            "exit 2 with the reason on stderr",
        ],
        "tool_map": {"Bash": "Bash", "Write": "apply_patch", "Edit": "apply_patch",
                     "mcp": "mcp__<server>__<tool>"},
        "trust_step": ("non-managed hooks run only after /hooks trust, recorded against "
                       "the hook's hash; --dangerously-bypass-hook-trust skips it once"),
        "source": "learn.chatgpt.com/docs/hooks",
    },
}

_LIVE_PROMPT = "Reply with exactly the word OCTORATO-CENSUS-OK and nothing else."
_LIVE_TOKEN = "OCTORATO-CENSUS-OK"
_LIVE_TIMEOUT_S = 180


class TranslationError(ValueError):
    """The harness payload cannot be read into the gate fields."""


# --- path hygiene -------------------------------------------------------------

def fold_home(text: str) -> str:
    """Replace the real home directory (both separators) with "~"."""
    home = os.path.expanduser("~")
    if not home or home == "~":
        return text
    variants = {home, home.replace("\\", "/"), home.replace("/", "\\")}
    out = text
    for v in sorted(variants, key=len, reverse=True):
        if v and v != "~":
            out = out.replace(v, "~")
    return out


def _fold_obj(obj):
    if isinstance(obj, str):
        return fold_home(obj)
    if isinstance(obj, list):
        return [_fold_obj(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _fold_obj(v) for k, v in obj.items()}
    return obj


# --- fixtures -----------------------------------------------------------------

def load_fixture(rel: str, root: Path = FIXTURES_ROOT) -> dict:
    path = root / rel
    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop("_setup", None)
    # Every real harness payload carries a session_id; older fixtures omit it
    # (gate_selftest fills the same gap before driving a gate).
    if not data.get("session_id"):
        data["session_id"] = "census"
    return data


def gate_fields(payload: dict) -> dict:
    return {k: payload.get(k) for k in GATE_FIELDS}


# --- rendering: Claude-shaped fixture -> harness payload ----------------------

def _mcp_parts(tool_name: str) -> tuple[str, str]:
    m = re.fullmatch(r"mcp__([^_]+(?:_[^_]+)*)__(.+)", tool_name)
    if not m:
        raise TranslationError(f"not an MCP tool name: {tool_name!r}")
    return m.group(1), m.group(2)


def render_gemini(fx: dict) -> dict:
    tool = fx.get("tool_name")
    ti = fx.get("tool_input") or {}
    base = {
        "session_id": fx.get("session_id") or "census",
        "transcript_path": fx.get("transcript_path") or "",
        "cwd": fx.get("cwd") or "",
        "hook_event_name": "BeforeTool",
        "timestamp": "1970-01-01T00:00:00Z",
    }
    if tool == "Bash":
        base["tool_name"] = "run_shell_command"
        base["tool_input"] = {"command": ti.get("command", "")}
    elif tool == "Write":
        base["tool_name"] = "write_file"
        base["tool_input"] = {"file_path": ti.get("file_path", ""),
                              "content": ti.get("content", "")}
    elif tool == "Edit":
        base["tool_name"] = "replace"
        base["tool_input"] = {"file_path": ti.get("file_path", ""),
                              "instruction": "census",
                              "old_string": ti.get("old_string", ""),
                              "new_string": ti.get("new_string", ""),
                              "allow_multiple": bool(ti.get("replace_all", False))}
    elif isinstance(tool, str) and tool.startswith("mcp__"):
        server, name = _mcp_parts(tool)
        base["tool_name"] = f"mcp_{server}_{name}"
        base["tool_input"] = dict(ti)
        base["mcp_context"] = {"server_name": server, "tool_name": name}
    else:
        raise TranslationError(f"no Gemini rendering for tool {tool!r}")
    return base


def _apply_patch_add(path: str, content: str) -> str:
    lines = content.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    body = "\n".join("+" + ln for ln in lines)
    return f"*** Begin Patch\n*** Add File: {path}\n{body}\n*** End Patch\n"


def _apply_patch_update(path: str, old: str, new: str) -> str:
    old_lines = "\n".join("-" + ln for ln in old.split("\n"))
    new_lines = "\n".join("+" + ln for ln in new.split("\n"))
    return (f"*** Begin Patch\n*** Update File: {path}\n@@\n"
            f"{old_lines}\n{new_lines}\n*** End Patch\n")


def render_codex(fx: dict) -> dict:
    tool = fx.get("tool_name")
    ti = fx.get("tool_input") or {}
    base = {
        "session_id": fx.get("session_id") or "census",
        "transcript_path": fx.get("transcript_path") or None,
        "cwd": fx.get("cwd") or "",
        "hook_event_name": "PreToolUse",
        "model": "census",
        "permission_mode": "default",
        "turn_id": "census",
        "tool_use_id": fx.get("tool_use_id") or "census",
    }
    if tool == "Bash":
        base["tool_name"] = "Bash"
        base["tool_input"] = {"command": ti.get("command", "")}
    elif tool == "Write":
        base["tool_name"] = "apply_patch"
        base["tool_input"] = {"command": _apply_patch_add(
            ti.get("file_path", ""), ti.get("content", ""))}
    elif tool == "Edit":
        base["tool_name"] = "apply_patch"
        base["tool_input"] = {"command": _apply_patch_update(
            ti.get("file_path", ""), ti.get("old_string", ""), ti.get("new_string", ""))}
    elif isinstance(tool, str) and tool.startswith("mcp__"):
        _mcp_parts(tool)
        base["tool_name"] = tool
        base["tool_input"] = dict(ti)
    else:
        raise TranslationError(f"no Codex rendering for tool {tool!r}")
    return base


RENDERERS = {"gemini": render_gemini, "codex": render_codex}


# --- translation: harness payload -> gate fields ------------------------------

def _require_dict(payload) -> dict:
    if not isinstance(payload, dict):
        raise TranslationError("payload is not a JSON object")
    return payload


def translate_gemini(payload) -> dict:
    p = _require_dict(payload)
    tool = p.get("tool_name")
    ti = p.get("tool_input")
    if not isinstance(tool, str) or not isinstance(ti, dict):
        raise TranslationError("missing tool_name or tool_input")
    if tool == "run_shell_command":
        if "command" not in ti:
            raise TranslationError("run_shell_command without command")
        out = {"tool_name": "Bash", "tool_input": {"command": ti["command"]}}
    elif tool == "write_file":
        if "file_path" not in ti or "content" not in ti:
            raise TranslationError("write_file without file_path/content")
        out = {"tool_name": "Write",
               "tool_input": {"file_path": ti["file_path"], "content": ti["content"]}}
    elif tool == "replace":
        for k in ("file_path", "old_string", "new_string"):
            if k not in ti:
                raise TranslationError(f"replace without {k}")
        out = {"tool_name": "Edit",
               "tool_input": {"file_path": ti["file_path"],
                              "old_string": ti["old_string"],
                              "new_string": ti["new_string"]}}
    elif tool.startswith("mcp_"):
        ctx = p.get("mcp_context")
        if not isinstance(ctx, dict) or not ctx.get("server_name") or not ctx.get("tool_name"):
            raise TranslationError("MCP tool without mcp_context server_name/tool_name")
        out = {"tool_name": f"mcp__{ctx['server_name']}__{ctx['tool_name']}",
               "tool_input": dict(ti)}
    else:
        raise TranslationError(f"unknown Gemini tool {tool!r}")
    out["cwd"] = p.get("cwd")
    out["session_id"] = p.get("session_id")
    return out


_PATCH_HEADER = re.compile(r"^\*\*\* (Add|Update|Delete) File: (.+)$")


def parse_apply_patch(text: str) -> dict:
    """Read the one-file patches this census renders back into gate fields."""
    if not isinstance(text, str):
        raise TranslationError("apply_patch command is not text")
    lines = text.split("\n")
    if not lines or lines[0] != "*** Begin Patch":
        raise TranslationError("apply_patch without Begin Patch header")
    try:
        end = lines.index("*** End Patch")
    except ValueError:
        raise TranslationError("apply_patch without End Patch footer")
    if len(lines) < 2:
        raise TranslationError("apply_patch without a file header")
    m = _PATCH_HEADER.match(lines[1])
    if not m:
        raise TranslationError("apply_patch without a File header")
    kind, path = m.group(1), m.group(2)
    body = lines[2:end]
    if kind == "Add":
        if any(not ln.startswith("+") for ln in body):
            raise TranslationError("Add File body with a non-added line")
        content = "\n".join(ln[1:] for ln in body) + ("\n" if body else "")
        return {"tool_name": "Write", "tool_input": {"file_path": path, "content": content}}
    if kind == "Update":
        hunks = [ln for ln in body if not ln.startswith("@@")]
        old = [ln[1:] for ln in hunks if ln.startswith("-")]
        new = [ln[1:] for ln in hunks if ln.startswith("+")]
        if any(ln[:1] not in ("-", "+", " ") for ln in hunks):
            raise TranslationError("Update File hunk with an unreadable line")
        return {"tool_name": "Edit",
                "tool_input": {"file_path": path, "old_string": "\n".join(old),
                               "new_string": "\n".join(new)}}
    raise TranslationError(f"apply_patch kind {kind} not translated")


def translate_codex(payload) -> dict:
    p = _require_dict(payload)
    tool = p.get("tool_name")
    ti = p.get("tool_input")
    if not isinstance(tool, str) or not isinstance(ti, dict):
        raise TranslationError("missing tool_name or tool_input")
    if tool == "Bash":
        if "command" not in ti:
            raise TranslationError("Bash without command")
        out = {"tool_name": "Bash", "tool_input": {"command": ti["command"]}}
    elif tool == "apply_patch":
        out = parse_apply_patch(ti.get("command"))
    elif tool.startswith("mcp__"):
        _mcp_parts(tool)
        out = {"tool_name": tool, "tool_input": dict(ti)}
    else:
        raise TranslationError(f"unknown Codex tool {tool!r}")
    out["cwd"] = p.get("cwd")
    out["session_id"] = p.get("session_id")
    return out


TRANSLATORS = {"gemini": translate_gemini, "codex": translate_codex}


def translate(harness: str, payload) -> dict:
    """Gate fields for a harness payload; raises TranslationError when unreadable.

    `payload` may be the parsed object or raw text. Raw text that is not JSON
    raises as well: an unreadable payload is a failure, never an allow.
    """
    if isinstance(payload, (str, bytes)):
        try:
            payload = json.loads(payload)
        except ValueError as exc:
            raise TranslationError(f"payload is not JSON: {exc}") from exc
    return TRANSLATORS[harness](payload)


# --- deterministic census -----------------------------------------------------

def _redact_values(obj):
    if isinstance(obj, dict):
        return {k: _redact_values(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact_values(v) for v in obj]
    return f"<{type(obj).__name__}>"


def _shape(payload: dict, redact: bool) -> dict:
    """What the record keeps of a rendered payload."""
    if redact:
        return _redact_values(payload)
    return _fold_obj(payload)


def census_leg(harness: str, tool_class: str, leg: str, rel: str,
               root: Path = FIXTURES_ROOT) -> dict:
    """Render one fixture as the harness payload and translate it back."""
    rec = {"leg": leg, "fixture": rel}
    try:
        fx = load_fixture(rel, root)
    except (OSError, ValueError) as exc:
        rec.update(status="failure", translatable=False, reason=f"fixture unreadable: {exc}")
        return rec
    try:
        rendered = RENDERERS[harness](fx)
    except TranslationError as exc:
        rec.update(status="failure", translatable=False, reason=f"render: {exc}")
        return rec
    rec["harness_tool_name"] = rendered.get("tool_name")
    rec["tool_input_keys"] = sorted((rendered.get("tool_input") or {}).keys())
    rec["rendered_payload"] = _shape(rendered, redact=(tool_class == "mcp"))
    try:
        back = translate(harness, json.dumps(rendered))
    except TranslationError as exc:
        rec.update(status="failure", translatable=False, reason=f"translate: {exc}")
        return rec
    want = gate_fields(fx)
    lossless = back == want
    rec.update(status="measured", translatable=True, round_trip_lossless=lossless)
    if not lossless:
        diff = sorted(k for k in GATE_FIELDS if back.get(k) != want.get(k))
        rec["round_trip_diff_fields"] = diff
    return rec


def census_deterministic(harness: str, root: Path = FIXTURES_ROOT) -> dict:
    classes = {}
    for tc in TOOL_CLASSES:
        spec = BLOCK_FIXTURES[tc]
        legs = [census_leg(harness, tc, "violation", spec["violation"], root),
                census_leg(harness, tc, "benign", spec["benign"], root)]
        ok = all(l.get("status") == "measured" and l.get("round_trip_lossless") for l in legs)
        classes[tc] = {
            "gate": spec["gate"],
            "translatable": ok,
            "harness_tool_name": CONTRACTS[harness]["tool_map"][
                {"shell": "Bash", "file_write": "Write", "file_edit": "Edit", "mcp": "mcp"}[tc]],
            "legs": legs,
            # Blocking through a projected hook is a later task; a missing
            # measurement is recorded as null, never as an allow.
            "harness_blocked_violation": None,
            "harness_allowed_benign": None,
            "blocking_note": "not measured: no projected hook or shim exists for this harness yet",
        }
    return classes


# --- live census --------------------------------------------------------------

def _env_value_from_dotenv(name: str) -> str | None:
    """Read one value out of ~/.env at runtime. The value is never written anywhere."""
    path = Path(os.path.expanduser("~/.env"))
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        m = re.match(rf"^\s*(?:export\s+)?{re.escape(name)}\s*=\s*(.*?)\s*$", line)
        if m:
            val = m.group(1)
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                val = val[1:-1]
            return val or None
    return None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(cmd: list[str], cwd: str, env: dict, stdin_text: str | None = None) -> dict:
    """Run one command; a timeout or a 503 reads as a failed attempt."""
    started = _now()
    t0 = time.monotonic()
    kwargs = {"input": stdin_text} if stdin_text is not None else {"stdin": subprocess.DEVNULL}
    try:
        cp = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True,
                            encoding="utf-8", errors="replace",
                            timeout=_LIVE_TIMEOUT_S, **kwargs)
    except subprocess.TimeoutExpired:
        return {"started": started, "elapsed_s": round(time.monotonic() - t0, 1),
                "outcome": "failure", "reason": f"timeout after {_LIVE_TIMEOUT_S}s"}
    except OSError as exc:
        return {"started": started, "elapsed_s": round(time.monotonic() - t0, 1),
                "outcome": "failure", "reason": f"cannot start: {exc.__class__.__name__}"}
    elapsed = round(time.monotonic() - t0, 1)
    out = fold_home(cp.stdout or "")
    err = fold_home(cp.stderr or "")
    rec = {"started": started, "elapsed_s": elapsed, "exit_code": cp.returncode}
    combined = out + "\n" + err
    if re.search(r"\b503\b|UNAVAILABLE|overloaded", combined, re.I):
        rec.update(outcome="failure", reason="503 or unavailable from the service")
    elif re.search(r"\b429\b|quota", combined, re.I):
        rec.update(outcome="failure", reason="429 quota exhausted at the service")
    elif cp.returncode != 0:
        rec.update(outcome="failure", reason=f"exit {cp.returncode}")
    elif _LIVE_TOKEN in out:
        rec.update(outcome="success", reason="expected token in stdout")
    else:
        rec.update(outcome="failure", reason="exit 0 but expected token missing from stdout")
    rec["error_class"] = _error_class(combined)
    rec["stderr_tail"] = err.strip()[-240:]
    return rec


def _error_class(text: str) -> str | None:
    m = re.search(r"\b([A-Z][A-Za-z]+(?:Error|Exception))\b", text)
    return m.group(1) if m else None


def _version(binary: str) -> str | None:
    try:
        cp = subprocess.run([binary, "--version"], capture_output=True, text=True,
                            timeout=60, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    line = (cp.stdout or cp.stderr or "").strip().splitlines()
    return line[0].strip() if line else None


def _binary_record(name: str) -> dict:
    path = shutil.which(name)
    return {"name": name, "path": fold_home(path) if path else None,
            "version": _version(name) if path else None}


def _clean_env() -> dict:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("GEMINI_", "GOOGLE_", "OPENAI_", "CODEX_", "OCTO_", "CLAUDE"))}
    env.setdefault("PATH", os.environ.get("PATH", ""))
    return env


def live_codex(sandbox: str) -> dict:
    binary = _binary_record("codex")
    rec = {"binary": binary, "account": None, "attempts": []}
    if not binary["path"]:
        rec["outcome"] = "failure"
        rec["reason"] = "codex binary not found"
        return rec
    try:
        cp = subprocess.run(["codex", "login", "status"], capture_output=True, text=True,
                            timeout=60, stdin=subprocess.DEVNULL)
        rec["account"] = (cp.stdout or cp.stderr or "").strip().splitlines()[0:1] or None
        if rec["account"]:
            rec["account"] = fold_home(rec["account"][0])
    except (OSError, subprocess.TimeoutExpired, IndexError):
        rec["account"] = None
    env = _clean_env()
    attempt = _run(["codex", "exec", "--skip-git-repo-check", _LIVE_PROMPT], sandbox, env)
    attempt["mode"] = "codex exec --skip-git-repo-check <prompt>, cwd = empty sandbox"
    rec["attempts"].append(attempt)
    rec["outcome"] = attempt["outcome"]
    rec["reason"] = attempt["reason"]
    rec["trust_step_scriptable"] = None
    rec["trust_step_note"] = ("not measured: no Octorato hook is projected yet; the docs state "
                              "non-managed hooks need /hooks trust per hook hash")
    return rec


def live_gemini(sandbox: str) -> dict:
    binary = _binary_record("gemini")
    rec = {"binary": binary, "account": None, "attempts": []}
    if not binary["path"]:
        rec["outcome"] = "failure"
        rec["reason"] = "gemini binary not found"
        return rec
    # Attempt 1: the Google account route (OAuth creds the CLI holds), no API key.
    env = _clean_env()
    env["GEMINI_CLI_TRUST_WORKSPACE"] = "true"
    env["HOME"] = os.environ.get("HOME", "")
    acct = _run(["gemini", "-p", _LIVE_PROMPT], sandbox, env)
    acct["mode"] = "gemini -p <prompt>, Google account (no GEMINI_API_KEY), cwd = empty sandbox"
    acct["account"] = "google-account"
    rec["attempts"].append(acct)
    # Attempt 2: API key read from ~/.env at runtime, never written.
    key = _env_value_from_dotenv("GEMINI_API_KEY")
    if key:
        env2 = dict(env)
        env2["GEMINI_API_KEY"] = key
        api = _run(["gemini", "-p", _LIVE_PROMPT], sandbox, env2)
        api["mode"] = "gemini -p <prompt>, GEMINI_API_KEY from ~/.env, GEMINI_CLI_TRUST_WORKSPACE=true, cwd = empty sandbox"
        api["account"] = "api-key"
        del key, env2
    else:
        api = {"started": _now(), "outcome": "failure", "reason": "GEMINI_API_KEY absent from ~/.env",
               "mode": "gemini -p <prompt>, GEMINI_API_KEY from ~/.env", "account": "api-key"}
    rec["attempts"].append(api)
    rec["outcome"] = api["outcome"]
    rec["reason"] = api["reason"]
    rec["account"] = "api-key" if api["outcome"] == "success" else (
        "google-account" if acct["outcome"] == "success" else None)
    rec["google_account_evidence"] = {
        "error_class": acct.get("error_class"),
        "measured": acct["started"],
        "prior_measurement": {
            "date": "2026-10-15", "version": "0.62.0", "error_class": "IneligibleTierError",
            "message_prefix": "This client is no longer supported for Gemini Code Assist for individuals",
        },
    }
    return rec


LIVE = {"gemini": live_gemini, "codex": live_codex}


def census_live(harness: str) -> dict:
    sandbox = tempfile.mkdtemp(prefix="octorato-census-")
    try:
        rec = LIVE[harness](sandbox)
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)
    rec["measured"] = _now()
    return _fold_obj(rec)


# --- record -------------------------------------------------------------------

def _scrub(obj):
    """Fold every path and refuse to write a home path or a known secret name."""
    text = json.dumps(_fold_obj(obj), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    home = os.path.expanduser("~")
    if home and home != "~" and home in text:
        raise RuntimeError("census record would carry a $HOME path; refusing to write")
    if re.search(r"(?i)(api[_-]?key|token|secret)\s*[:=]\s*[\"']?[A-Za-z0-9_\-]{16,}", text):
        raise RuntimeError("census record would carry a secret-shaped value; refusing to write")
    return text


def build_record(harness: str, live: dict | None, previous: dict | None,
                 root: Path = FIXTURES_ROOT) -> dict:
    contract = CONTRACTS[harness]
    rec = {
        "harness": harness,
        "name": contract["name"],
        "status": "measured",
        "support_note": ("measurements only; `supported` needs blocking evidence through "
                         "projected hooks, which this record does not hold"),
        "contract": contract,
        "block_fixtures": BLOCK_FIXTURES,
        "tool_classes": census_deterministic(harness, root),
        "live": live if live is not None else (previous or {}).get("live", {}),
        "generated_by": "scripts/runtime_census.py",
    }
    return rec


def write_record(harness: str, rec: dict, out_dir: Path = CENSUS_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{harness}.json"
    path.write_text(_scrub(rec), encoding="utf-8")
    return path


def read_record(harness: str, out_dir: Path = CENSUS_DIR) -> dict | None:
    path = out_dir / f"{harness}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--live", action="store_true", help="run one end-to-end call per harness")
    ap.add_argument("--harness", choices=HARNESSES, action="append",
                    help="limit to one harness (repeatable)")
    ap.add_argument("--out", default=str(CENSUS_DIR), help="census directory")
    ap.add_argument("--fixtures-root", default=str(FIXTURES_ROOT))
    args = ap.parse_args(argv)
    out_dir = Path(args.out)
    root = Path(args.fixtures_root)
    rc = 0
    for h in args.harness or HARNESSES:
        previous = read_record(h, out_dir)
        live = census_live(h) if args.live else None
        rec = build_record(h, live, previous, root)
        path = write_record(h, rec, out_dir)
        classes = rec["tool_classes"]
        ok = [c for c in TOOL_CLASSES if classes[c]["translatable"]]
        bad = [c for c in TOOL_CLASSES if not classes[c]["translatable"]]
        line = f"{h}: translatable {','.join(ok) or '-'}; not translatable {','.join(bad) or '-'}"
        if args.live:
            line += f"; live {rec['live'].get('outcome')} ({rec['live'].get('reason')})"
        print(f"{line} -> {fold_home(str(path))}")
        if bad:
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
