#!/usr/bin/env python3
"""merge-hooks-codex.py: project hooks.json into a Codex CLI hooks.json.

v11 spec 202610141000, AC-04, task T07. The Hook_Projector for Codex CLI.
Shared logic, modes and rules of what is projected: scripts/hook_projector.py.
Per the spec it writes only while Codex CLI is `supported` in
registry/runtimes.yaml; today it is `gap`, so the default run refuses and
--check prints the dry-run projection.

Target: a Codex hooks.json given by --out (`~/.codex/hooks.json` or
`.codex/hooks.json`, registry/census/codex.json contract.config_paths). There
is no default target.

Shape written (census contract, learn.chatgpt.com/docs/hooks; field names
`matcher`, `hooks`, `type`, `command`, `timeout` present in the codex-cli
0.159.3 binary, whose hook handler field is `timeout_sec`, so seconds):

  {"hooks": {"PreToolUse": [
     {"matcher": "^(Bash|apply_patch)$",
      "hooks": [{"type": "command",
                 "command": "python3 <shim-dir>/g__shim__hook.py --harness codex-cli --gate <gate>.py",
                 "timeout": 60}]}]}}

Tool-name map, derived from g__shim__hook.TOOL_YIELDS["codex-cli"] (every
Codex tool the shim can translate into the Claude tool):
  Bash  -> Bash               (shell)
  Write -> Bash, apply_patch  (a `*** Begin Patch` span in a shell command is a write)
  Edit  -> Bash, apply_patch
  mcp__<server>__<tool> -> unchanged (mcp)
  *     -> Bash, apply_patch, mcp__.+
  anything else (Agent, Skill, NotebookEdit, MultiEdit): unprojected.
Hosted tools are not covered by Codex PreToolUse (feature.md, Out of Scope).

Trust: non-managed Codex hooks run only after `/hooks` trust, recorded against
each hook's hash (census contract.trust_step), so every changed command needs
the operator's trust step again on each machine.

Sandbox (dry-run only). The boundary for Codex is capability, not detection
(docs/architecture/v8-arming-surface.md, "Second harnesses"): --check prints
the config.toml setting whose writable roots exclude ~/.claude. Keys measured
on 2026-10-15 with codex-cli 0.159.3 (`codex sandbox -c ...`, CODEX_HOME in a
temp dir): with `sandbox_mode = "workspace-write"` and
`sandbox_workspace_write.writable_roots = [<dir>]`, the cwd and <dir> were
writable, a directory outside both refused with "Read-only file system", and
`test -w ~/.claude` was false inside the sandbox. The session cwd is always
writable, so Codex must not be started from inside ~/.claude.

Usage:
  python3 scripts/merge-hooks-codex.py --check [--out ~/.codex/hooks.json] [--project DIR]
  python3 scripts/merge-hooks-codex.py --update-registry
  python3 scripts/merge-hooks-codex.py --out <hooks.json>   (refused unless supported)
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hook_projector as hp  # noqa: E402

_SHELL_TOOL = "Bash"
WILDCARD = hp.table_wildcard("codex-cli", _SHELL_TOOL)


def translate(token: str):
    pieces = hp.table_pieces("codex-cli", token, _SHELL_TOOL)
    if pieces:
        return pieces
    if hp._CLAUDE_MCP.match(token):
        return [hp.Piece(re.escape(token), "mcp")]
    return None


def hook_config(gate: str, command: str) -> dict:
    return {"type": "command", "command": command, "timeout": hp.HOOK_TIMEOUT_S}


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def sandbox_setting(args) -> tuple[list[str], list[str]]:
    """The config.toml lines for the Codex sandbox boundary; drift when the
    project root would make ~/.claude writable."""
    brain = Path(os.path.realpath(os.path.expanduser("~/.claude")))
    roots: list[str] = []
    drift: list[str] = []
    if args.project is not None:
        proj = Path(os.path.realpath(os.path.expanduser(str(args.project))))
        if _inside(proj, brain) or _inside(brain, proj):
            drift.append(f"--project {proj} contains or is inside ~/.claude: as a writable "
                         "root it would make the live brain writable")
        else:
            roots.append(str(proj))
    lines = [
        "  Codex sandbox (dry-run; put in config.toml; keys measured with codex-cli 0.159.3):",
        '    sandbox_mode = "workspace-write"',
        "    [sandbox_workspace_write]",
        f"    writable_roots = {json.dumps(roots)}",
        "  ~/.claude is not a writable root; the session cwd always is, so never start",
        "  Codex from inside ~/.claude. Not passed: exclude_slash_tmp (default false keeps",
        "  /tmp writable, outside ~/.claude).",
    ]
    return lines, drift


SPEC = hp.HarnessSpec(id="codex-cli", script="merge-hooks-codex.py", event="PreToolUse",
                      translate=translate, wildcard=WILDCARD, hook_config=hook_config,
                      extra_check=sandbox_setting)


if __name__ == "__main__":
    raise SystemExit(hp.run(SPEC))
