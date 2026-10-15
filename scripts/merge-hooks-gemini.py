#!/usr/bin/env python3
"""merge-hooks-gemini.py: project hooks.json into a Gemini CLI settings.json `hooks` block.

v11 spec 202610141000, AC-04, task T06. The Hook_Projector for Gemini CLI.
Shared logic, modes and rules of what is projected: scripts/hook_projector.py.

Target: a Gemini settings.json given by --out (project `.gemini/settings.json`
or user `~/.gemini/settings.json`, registry/census/gemini.json
contract.config_paths). There is no default target; a real home config is
written only when the operator names it.

Shape written (bundle docs/hooks/reference.md, "Configuration schema"):

  {"hooks": {"BeforeTool": [
     {"matcher": "^(run_shell_command|write_file)$",
      "hooks": [{"name": "octorato-<gate>", "type": "command",
                 "command": "python3 <shim-dir>/g__shim__hook.py --harness gemini-cli --gate <gate>.py",
                 "timeout": 60000}]}]}}

`timeout` is in milliseconds in Gemini CLI (same reference, default 60000),
so 60 s is written as 60000. Foreign keys and foreign hooks are kept; only the
hooks whose command runs the shim with `--harness gemini-cli` are managed.

Tool-name map (registry/census/gemini.json contract.tool_map, docs/tools/*):
  Bash  -> run_shell_command (shell)
  Write -> write_file        (file_write)
  Edit  -> replace           (file_edit)
  mcp__<server>__<tool> -> mcp_<server>_<tool> (mcp); a name over 63
    characters is unprojected, since Gemini truncates it with a middle
    replacement (docs/tools/mcp-server.md, "Name sanitization").
  *     -> run_shell_command, write_file, replace, mcp_.+
  anything else (Agent, Skill, NotebookEdit, MultiEdit): unprojected.

Trust: Gemini CLI fingerprints PROJECT hooks and warns before running a hook
whose name or command changed (docs/hooks/index.md, "Security and risks");
a re-projection that changes a command is therefore a new, untrusted hook.

Usage:
  python3 scripts/merge-hooks-gemini.py --check [--out .gemini/settings.json]
  python3 scripts/merge-hooks-gemini.py --update-registry
  python3 scripts/merge-hooks-gemini.py --out <settings.json>   (refused unless supported)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hook_projector as hp  # noqa: E402

_GEMINI_MCP_MAX = 63
_BUILTIN = {
    "Bash": hp.Piece("run_shell_command", "shell"),
    "Write": hp.Piece("write_file", "file_write"),
    "Edit": hp.Piece("replace", "file_edit"),
}
WILDCARD = [_BUILTIN["Bash"], _BUILTIN["Write"], _BUILTIN["Edit"], hp.Piece("mcp_.+", "mcp")]


def translate(token: str):
    if token in _BUILTIN:
        return [_BUILTIN[token]]
    m = hp._CLAUDE_MCP.match(token)
    if m:
        name = f"mcp_{m.group(1)}_{m.group(2)}"
        if len(name) > _GEMINI_MCP_MAX:
            return None
        return [hp.Piece(re.escape(name), "mcp")]
    return None


def hook_config(gate: str, command: str) -> dict:
    return {"name": f"octorato-{gate[:-3] if gate.endswith('.py') else gate}",
            "type": "command", "command": command,
            "timeout": hp.HOOK_TIMEOUT_S * 1000}


SPEC = hp.HarnessSpec(id="gemini-cli", script="merge-hooks-gemini.py", event="BeforeTool",
                      translate=translate, wildcard=WILDCARD, hook_config=hook_config)


if __name__ == "__main__":
    raise SystemExit(hp.run(SPEC))
