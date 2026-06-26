#!/usr/bin/env python3
"""merge-hooks-cursor.py — project hooks.json into Cursor's native ~/.cursor/hooks.json.

Octorato's single source of truth for hooks is ~/.claude/hooks.json (Claude Code
schema). merge-hooks.py projects it DOWN into the per-machine Claude settings.json.
This sibling projects the SAME source into Cursor's native hook format so the brain's
reflexes (trace, cadence, canon-heal, impact-radius, delegate/dimension gates, …) fire
inside the Cursor IDE too — not just Claude Code.

Why a separate projector and not Cursor's third-party Claude-hook loader? Cursor *can*
read ~/.claude/settings.json directly (Settings → third-party hooks), but that path is a
per-machine toggle and its matchers are Claude tool-names (Bash, Write|Edit, Skill, Agent)
which do not line up with Cursor tool-names (Shell, Write, Task). This projector does the
event + matcher translation so the hooks actually match Cursor's loop, and it is
version-controlled (regenerated on every ai-pull / ai-sync, exactly like settings.json).

Target: ~/.cursor/hooks.json — a per-machine RUNTIME artifact (gitignored by being outside
the repo), owned the same way settings.json is. Foreign Cursor events the operator authored
by hand are preserved; only the events Octorato emits are managed.

Schema (Cursor native):
  { "version": 1, "hooks": { "<event>": [ { "command", "timeout?", "matcher?" }, ... ] } }

Event map (Claude Code -> Cursor):
  PreToolUse        -> preToolUse        (matcher tool-names translated)
  PostToolUse       -> postToolUse       (Shell) / afterFileEdit (Write|Edit)
  Stop              -> stop
  SessionStart      -> sessionStart
  UserPromptSubmit  -> beforeSubmitPrompt

Matcher tool map (Claude -> Cursor):  Bash->Shell, Write->Write, Edit->Write.
Skill / Agent matchers have no Cursor equivalent and are DROPPED.

Modes:
  (default)  write ~/.cursor/hooks.json (merge: manage our events, keep foreign ones)
  --check    compare only; exit 0 in-sync/absent, exit 1 drift; write nothing
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

CLAUDE_DIR = Path(os.path.expanduser("~/.claude"))
HOOKS_FILE = CLAUDE_DIR / "hooks.json"
CURSOR_DIR = Path(os.path.expanduser("~/.cursor"))
CURSOR_HOOKS_FILE = CURSOR_DIR / "hooks.json"

MARKER = "_octorato_managed_events"

# Claude tool-name -> Cursor tool-name (matcher tokens). None == drop the token.
_TOOL_MAP = {"Bash": "Shell", "Write": "Write", "Edit": "Write",
             "Skill": None, "Agent": None}


def _atomic_write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _script_exists(command: str) -> bool:
    """Mirror merge-hooks.py: only project hooks whose target script is present."""
    m = re.search(r"(?:python3?|bash|sh|node)\s+(~?/\S+)", command)
    if not m:
        return True  # not a recognizable script command — keep it
    return os.path.isfile(os.path.expanduser(m.group(1)))


def _map_matcher(matcher: str | None):
    """(cursor_tokens, dropped_all) — translate Claude matcher tokens to Cursor tool-names."""
    if not matcher:
        return [], False
    tokens = [t.strip() for t in matcher.split("|") if t.strip()]
    mapped, seen = [], set()
    for tok in tokens:
        cur = _TOOL_MAP.get(tok, tok)  # unknown tokens pass through verbatim
        if cur is None:
            continue  # Skill / Agent — no Cursor equivalent
        if cur not in seen:
            seen.add(cur)
            mapped.append(cur)
    dropped_all = bool(tokens) and not mapped
    return mapped, dropped_all


def _target_event(claude_event: str, cursor_tokens: list[str]) -> tuple[str, str | None] | None:
    """(cursor_event, cursor_matcher) for a Claude event + already-mapped matcher tokens."""
    if claude_event == "Stop":
        return "stop", None
    if claude_event == "SessionStart":
        return "sessionStart", None
    if claude_event == "UserPromptSubmit":
        return "beforeSubmitPrompt", None
    if claude_event == "PreToolUse":
        if not cursor_tokens:
            return None
        return "preToolUse", "|".join(cursor_tokens)
    if claude_event == "PostToolUse":
        if not cursor_tokens:
            return None
        # File-edit reflexes belong on Cursor's dedicated afterFileEdit event.
        if cursor_tokens == ["Write"]:
            return "afterFileEdit", "Write"
        return "postToolUse", "|".join(cursor_tokens)
    return None  # unknown Claude event — skip


def build_projection(hooks_data: dict) -> dict:
    """Claude hooks.json dict -> { cursor_event: [ {command, timeout?, matcher?}, ... ] }."""
    projection: dict[str, list] = {}
    for claude_event, entries in hooks_data.items():
        if claude_event.startswith("$") or not isinstance(entries, list):
            continue
        for entry in entries:
            matcher = entry.get("matcher")
            cursor_tokens, dropped_all = _map_matcher(matcher)
            if dropped_all:
                continue  # e.g. Skill|Agent — nothing maps
            target = _target_event(claude_event, cursor_tokens)
            if target is None:
                continue
            cursor_event, cursor_matcher = target
            for hook in entry.get("hooks", []):
                cmd = hook.get("command", "")
                if not cmd or not _script_exists(cmd):
                    continue
                definition: dict = {"command": cmd}
                if "timeout" in hook:
                    definition["timeout"] = hook["timeout"]
                if cursor_matcher:
                    definition["matcher"] = cursor_matcher
                projection.setdefault(cursor_event, []).append(definition)
    return projection


def _load_json(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _canonical(obj) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False)


def main() -> int:
    ap = argparse.ArgumentParser(description="Project hooks.json -> ~/.cursor/hooks.json")
    ap.add_argument("--check", action="store_true",
                    help="compare only; exit 1 on drift, write nothing")
    args = ap.parse_args()

    if not HOOKS_FILE.exists():
        print("  no hooks.json — nothing to project to Cursor")
        return 0

    hooks_data = _load_json(HOOKS_FILE)
    projection = build_projection(hooks_data)

    existing = _load_json(CURSOR_HOOKS_FILE)
    live_hooks = existing.get("hooks", {}) if isinstance(existing.get("hooks"), dict) else {}
    prev_managed = set(existing.get(MARKER, []))

    # The subset of the live file that WE own (managed events only). Foreign events
    # the operator authored by hand are intentionally excluded from the comparison.
    live_managed = {ev: live_hooks[ev] for ev in (prev_managed | set(projection)) if ev in live_hooks}

    in_sync = _canonical(live_managed) == _canonical(projection)

    if args.check:
        if not CURSOR_HOOKS_FILE.exists():
            print("  absent — ~/.cursor/hooks.json not materialized (run ai-pull / merge-hooks-cursor.py)")
            return 0
        if in_sync:
            print(f"  ✓ Cursor hooks in sync ({len(projection)} event(s) managed)")
            return 0
        print("  ✗ Cursor hooks drift — ~/.cursor/hooks.json differs from hooks.json projection")
        return 1

    if in_sync and CURSOR_HOOKS_FILE.exists():
        print("  Cursor hooks already in sync")
        return 0

    # Merge: drop stale managed events, install the current projection, keep foreign events.
    new_hooks = dict(live_hooks)
    for stale in prev_managed - set(projection):
        new_hooks.pop(stale, None)
    new_hooks.update(projection)

    out = dict(existing)
    out["version"] = 1
    out["hooks"] = new_hooks
    out[MARKER] = sorted(projection)

    _atomic_write_json(CURSOR_HOOKS_FILE, out)
    total = sum(len(v) for v in projection.values())
    print(f"  ✓ Cursor hooks projected -> {CURSOR_HOOKS_FILE} "
          f"({total} hook(s) across {len(projection)} event(s): {', '.join(sorted(projection))})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
