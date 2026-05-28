#!/usr/bin/env python3
"""
merge-hooks.py — Merge shared hooks.json into local settings.json

Called by ai-pull after pulling the brain. Ensures hooks defined in
hooks.json (committed, shared) are present in the local settings.json
(gitignored, per-machine) without overwriting machine-specific config
(permissions, MCP servers, model, etc.).

Merge strategy:
  - hooks.json is the SOURCE OF TRUTH for the hooks section
  - settings.json keeps all other keys untouched
  - If settings.json doesn't exist, creates it with just the hooks
  - Idempotent: safe to run multiple times
"""

import json
import os
import re
import shutil
import sys
import tempfile

# Windows consoles default to cp1252, which crashes on the Unicode glyphs this
# script uses for status output (✓, ⚠). Force stdout/stderr to UTF-8 with
# replacement so the script runs cleanly on Windows without requiring users to
# set PYTHONIOENCODING themselves. Same pattern as ai_sync.py / brain_doctor.py.
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

CLAUDE_DIR = os.path.expanduser("~/.claude")
HOOKS_FILE = os.path.join(CLAUDE_DIR, "hooks.json")
SETTINGS_FILE = os.path.join(CLAUDE_DIR, "settings.json")


def _atomic_write_json(path, data):
    """Write JSON via tempfile + os.replace so a Ctrl+C mid-write can't corrupt the target."""
    target_dir = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=target_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _resolve_script(command):
    """Extract the script path from a hook command and check if it exists.

    Returns (resolved_path, exists) tuple. Handles ~ expansion.
    Looks for the first argument that looks like a file path after the interpreter.
    """
    # Match: python3 /path/to/script.py  OR  bash /path/to/script.sh  etc.
    m = re.search(r'(?:python3?|bash|sh|node)\s+(~?/\S+)', command)
    if not m:
        # Not a recognizable script command — skip validation (e.g., inline shell)
        return None, True
    path = os.path.expanduser(m.group(1))
    return path, os.path.isfile(path)


def _validate_hooks(hooks_config):
    """Validate all hook commands point to existing scripts.

    Returns (clean_config, warnings) where clean_config has broken hooks removed.
    """
    clean = {}
    warnings = []
    for event, entries in hooks_config.items():
        clean_entries = []
        for entry in entries:
            hook_list = entry.get("hooks", [])
            valid_hooks = []
            for hook in hook_list:
                cmd = hook.get("command", "")
                path, exists = _resolve_script(cmd)
                if not exists:
                    warnings.append(f"SKIPPED broken hook: {cmd}\n    Script not found: {path}")
                else:
                    valid_hooks.append(hook)
            if valid_hooks:
                clean_entries.append({**entry, "hooks": valid_hooks})
        if clean_entries:
            clean[event] = clean_entries
    return clean, warnings


def main():
    # Read shared hooks
    if not os.path.exists(HOOKS_FILE):
        print("  No hooks.json found — skipping hook merge")
        return

    with open(HOOKS_FILE, "r", encoding="utf-8") as f:
        hooks_data = json.load(f)

    # Remove the $schema comment key (not a real hook)
    hooks_config = {k: v for k, v in hooks_data.items() if not k.startswith("$")}

    if not hooks_config:
        print("  hooks.json is empty — skipping")
        return

    # Validate: only merge hooks whose script targets actually exist
    hooks_config, warnings = _validate_hooks(hooks_config)
    for w in warnings:
        print(f"  ⚠ {w}")

    # Read existing settings (or start fresh)
    settings = {}
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                settings = json.load(f)
        except (json.JSONDecodeError, IOError):
            print("  Warning: settings.json is corrupt — recreating with hooks only")
            settings = {}

    # Merge: replace the hooks section entirely (hooks.json is source of truth)
    old_hooks = settings.get("hooks", {})
    settings["hooks"] = hooks_config

    # Check if anything changed
    if old_hooks == hooks_config:
        print("  Hooks already in sync")
        return

    # Write back atomically (tempfile + os.replace) so a crash mid-write doesn't corrupt settings
    _atomic_write_json(SETTINGS_FILE, settings)

    # Report what changed
    new_events = set(hooks_config.keys())
    old_events = set(old_hooks.keys()) if isinstance(old_hooks, dict) else set()
    added = new_events - old_events
    updated = new_events & old_events

    parts = []
    if added:
        parts.append(f"added: {', '.join(added)}")
    if updated:
        parts.append(f"updated: {', '.join(updated)}")
    print(f"  ✓ Hooks merged into settings.json ({'; '.join(parts) or 'synced'})")


if __name__ == "__main__":
    main()
