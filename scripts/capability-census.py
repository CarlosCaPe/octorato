#!/usr/bin/env python3
"""capability-census.py - the live-source census heartbeat (UserPromptSubmit hook).

The connectome-heartbeat surfaces what the BRAIN has (skills/agents). It is
structurally blind to what is ALREADY LIVE outside the connectome: registered MCP
servers, connected client arms, and the authoritative vendor docs a task points at.

That blind spot is the recurring "I keep having to tell you to read from X source"
failure. This beat closes it: every prompt, inject the live inventory the model
already holds, framed as inventory-in-hand (read it now) not options to propose.

Doctrine: reflexes-over-discipline. A rule the model must remember gets skipped under
load; a hook fires on its own. Pairs with the connectome-heartbeat (brain recall) and
the 4d-reminder (gate). This one is external-capability recall.

Emits the UserPromptSubmit contract:
  {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "..."}}

Fail-open: a skipped beat is survivable, a hung prompt is not. Hard self-timeout.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

BUDGET_S = 2
HOME = Path.home()
BRAIN = Path(__file__).resolve().parent.parent  # ~/.claude


def read_prompt() -> str:
    try:
        data = json.loads(sys.stdin.read() or "{}")
        return str(data.get("prompt", ""))
    except Exception:
        return ""


def collect_mcps() -> list[str]:
    """Live MCP server names from the registry files (fast, no subprocess)."""
    names: set[str] = set()
    candidates = [HOME / ".claude.json", BRAIN / "settings.json", Path.cwd() / ".mcp.json"]
    for p in candidates:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        srv = data.get("mcpServers")
        if isinstance(srv, dict):
            names.update(srv.keys())
        projects = data.get("projects")
        if isinstance(projects, dict):
            for proj in projects.values():
                if isinstance(proj, dict) and isinstance(proj.get("mcpServers"), dict):
                    names.update(proj["mcpServers"].keys())
    return sorted(names)


def collect_arms(prompt_lc: str) -> tuple[list[str], list[str]]:
    """Connected arm codes from the gitignored config; flag any named in the prompt."""
    try:
        data = json.loads((BRAIN / "company" / "config" / "arms-paths.json").read_text(encoding="utf-8"))
        arms = list(data.keys()) if isinstance(data, dict) else []
    except Exception:
        arms = []
    mentioned = [a for a in arms if re.search(rf"\b{re.escape(a.lower())}\b", prompt_lc)]
    return arms, mentioned


def topic_hints(prompt_lc: str) -> list[str]:
    hints: list[str] = []
    if any(k in prompt_lc for k in ("claude", "anthropic", "hook", "sdk", "opus", "sonnet", "haiku", " api")):
        hints.append("Vendor topic (Claude/Anthropic): READ the official docs (docs.claude.com) / claude-api skill BEFORE answering from memory.")
    if any(k in prompt_lc for k in ("email", "correo", "inbox", "gmail", "mail")):
        hints.append("Inbox task: the Gmail MCP is live. Search it now, do not ask.")
    if any(k in prompt_lc for k in ("build", "crea", "crear", "monta", "montar", "setup", "integ", "implement", "automat")):
        hints.append("Before building: census first. Check connected arms + `git log -15` + `gh pr list`. Did this already get built?")
    return hints


def build_block(prompt: str) -> str:
    lc = prompt.lower()
    mcps = collect_mcps()
    arms, mentioned = collect_arms(lc)
    lines = ["⚙ CAPABILITY CENSUS (live sources in hand, not options to propose):"]
    lines.append(f"  Live MCPs: {', '.join(mcps) if mcps else '(none registered)'}")
    if arms:
        lines.append(f"  Connected arms: {', '.join(arms)}")
    if mentioned:
        lines.append(f"  -> prompt names arm(s) {', '.join(mentioned)}: open/grep that arm; a brain seek is NOT the arm.")
    for h in topic_hints(lc):
        lines.append(f"  -> {h}")
    lines.append("  Rule: read-only + accessible (live MCP / connected arm / readable file / vendor docs) = DO it now, never offer or ask.")
    return "\n".join(lines)


def emit(text: str) -> None:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": text,
    }}))


def main() -> int:
    try:
        import signal

        def _bail(*_):
            raise TimeoutError

        signal.signal(signal.SIGALRM, _bail)
        signal.alarm(BUDGET_S)
    except Exception:
        signal = None  # type: ignore

    try:
        prompt = read_prompt()  # inside the armed budget: stdin is the one hang surface
        stripped = prompt.strip()
        if len(stripped) < 5 or stripped.startswith("/"):
            return 0  # trivial / slash-command prompts: nothing to census
        emit(build_block(prompt))
    except TimeoutError:
        emit("⚙ capability-census skipped (over budget). Run runtime MCP census "
             "(Claude Code: `claude mcp list`; Cursor: GetMcpTools / Settings→MCP) "
             "+ check the arm manually if non-trivial.")
    except Exception as exc:
        emit(f"⚙ capability-census unavailable ({type(exc).__name__}). Recall live MCPs + the relevant arm manually.")
    finally:
        if signal is not None:
            try:
                signal.alarm(0)
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
