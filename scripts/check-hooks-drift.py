#!/usr/bin/env python3
"""check-hooks-drift.py — guard: settings.json.hooks must equal the projection of hooks.json.

hooks.json (tracked) is the single source of truth for Claude Code hooks. merge-hooks.py
projects it DOWN into the per-machine, gitignored settings.json on every ai-pull. The
recurring failure is the reverse edit: hooks added directly to settings.json never make it
back to hooks.json, so other machines pull a stale source and lose the hooks.

This guard runs on the PUSH path so divergence can exist transiently on one machine but can
NEVER propagate: ai-push is blocked until settings.json.hooks once again equals the validated
projection of hooks.json.

Exit codes:
  0  in sync (or settings.json absent — nothing can diverge)
  1  DRIFT  — settings.json.hooks differs from the hooks.json projection
  2  SCHEMA — hooks.json fails structural validation

Modes:
  (default)  check only; print a unified diff and the two one-command exits
  --adopt    intentional upward capture: promote settings.json.hooks -> hooks.json,
             allowlisting only safe sub-keys, stripping env, and refusing on any secret shape

Edit hooks in hooks.json, then run merge-hooks.py. Use --adopt only when you deliberately
authored a hook in settings.json and want to publish it.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
from pathlib import Path

CLAUDE_DIR = Path(__file__).resolve().parent.parent
HOOKS_FILE = CLAUDE_DIR / "hooks.json"
SETTINGS_FILE = CLAUDE_DIR / "settings.json"
SCHEMA_FILE = CLAUDE_DIR / "hooks.schema.json"
POLICY_FILE = CLAUDE_DIR / ".githooks" / "push-policy.txt"

KNOWN_EVENTS = {"UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop",
                "SubagentStop", "Notification", "PreCompact", "SessionStart"}
# A hook command may only invoke a local interpreter on a ~/.claude script — no inline
# curl/wget, no embedded tokens, no absolute home paths.
SAFE_COMMAND_RE = re.compile(
    r"^(python3?|bash|sh|node)\s+~?/?\.?(/)?\.claude/\S+(\s+--?[\w-]+(\s+\S+)?)*\s*$"
)


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def strip_schema(d: dict) -> dict:
    return {k: v for k, v in d.items() if not k.startswith("$")}


def resolve_script(command: str):
    """(path, exists) for the script a hook command runs; (None, True) if not a script command."""
    m = re.search(r"(?:python3?|bash|sh|node)\s+(~?/\S+)", command)
    if not m:
        return None, True
    path = os.path.expanduser(m.group(1))
    return path, os.path.isfile(path)


def validate_hooks(hooks_config: dict):
    """Mirror merge-hooks.py: drop hooks whose target script does not exist, so the
    projection compared here is exactly what merge-hooks.py would write."""
    clean: dict = {}
    for event, entries in hooks_config.items():
        clean_entries = []
        for entry in entries:
            valid = [h for h in entry.get("hooks", []) if resolve_script(h.get("command", ""))[1]]
            if valid:
                clean_entries.append({**entry, "hooks": valid})
        if clean_entries:
            clean[event] = clean_entries
    return clean


def canonical(obj) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False)


def validate_schema(hooks_data: dict):
    try:
        import jsonschema  # type: ignore
    except ImportError:
        return True, "jsonschema not installed — structural check skipped (soft)"
    if not SCHEMA_FILE.exists():
        return True, "hooks.schema.json absent — structural check skipped"
    try:
        jsonschema.validate(hooks_data, load_json(SCHEMA_FILE))
        return True, "schema OK"
    except jsonschema.ValidationError as exc:  # type: ignore
        return False, f"hooks.json schema violation: {exc.message}"


def load_secret_patterns():
    """[content] regexes from push-policy.txt — the fail-closed secret scan for --adopt."""
    pats, section = [], ""
    if POLICY_FILE.exists():
        for line in POLICY_FILE.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if s == "[content]":
                section = "content"
                continue
            if s == "[paths]":
                section = "paths"
                continue
            if section == "content":
                try:
                    pats.append(re.compile(s))
                except re.error:
                    pass  # POSIX class some Python builds reject — skip, hook still scans at push
    return pats


def adopt(hooks_data: dict, live: dict) -> int:
    """Promote settings.json.hooks -> hooks.json. Allowlist sub-keys, strip env, refuse secrets."""
    safe: dict = {}
    for event, entries in live.items():
        if event not in KNOWN_EVENTS:
            print(f"  ✗ refuse: unknown hook event '{event}'", file=sys.stderr)
            return 1
        clean_entries = []
        for entry in entries:
            clean_hooks = []
            for h in entry.get("hooks", []):
                if "env" in h:
                    print("  ✗ refuse: hook carries an 'env' block (per-machine secret surface)",
                          file=sys.stderr)
                    return 1
                cmd = h.get("command", "")
                if not SAFE_COMMAND_RE.match(cmd):
                    print(f"  ✗ refuse: command not on allowlist (no local-script form): {cmd}",
                          file=sys.stderr)
                    return 1
                allowed = {k: h[k] for k in ("type", "command", "timeout", "statusMessage") if k in h}
                clean_hooks.append(allowed)
            allowed_entry = {"hooks": clean_hooks}
            if "matcher" in entry:
                allowed_entry["matcher"] = entry["matcher"]
            clean_entries.append(allowed_entry)
        safe[event] = clean_entries

    banner = {k: v for k, v in hooks_data.items() if k.startswith("$")}
    out = {**banner, **safe}
    serialized = canonical(out)

    for pat in load_secret_patterns():
        if pat.search(serialized):
            print(f"  ✗ refuse: export matches a secret pattern ({pat.pattern[:40]}…) — aborting",
                  file=sys.stderr)
            return 1

    HOOKS_FILE.write_text(serialized + "\n", encoding="utf-8")
    print("  ✓ adopted settings.json.hooks -> hooks.json (re-run ai-push to commit)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adopt", action="store_true",
                    help="promote settings.json.hooks into hooks.json (intentional)")
    args = ap.parse_args()

    if not HOOKS_FILE.exists():
        print("  no hooks.json — nothing to guard")
        return 0

    hooks_data = load_json(HOOKS_FILE)
    ok, msg = validate_schema(hooks_data)
    if not ok:
        print(f"  ✗ {msg}")
        return 2

    projection = validate_hooks(strip_schema(hooks_data))

    if not SETTINGS_FILE.exists():
        print("  no settings.json yet — run merge-hooks.py / ai-pull to materialize")
        return 0

    live = load_json(SETTINGS_FILE).get("hooks", {})

    if canonical(live) == canonical(projection):
        print("  ✓ hooks in sync (settings.json == hooks.json projection)")
        return 0

    if args.adopt:
        return adopt(hooks_data, live)

    diff = difflib.unified_diff(
        canonical(projection).splitlines(), canonical(live).splitlines(),
        fromfile="hooks.json (source of truth)", tofile="settings.json (live, gitignored)",
        lineterm="",
    )
    print("  ✗ HOOK DRIFT: settings.json.hooks differs from hooks.json")
    print("\n".join(diff))
    print("\n  Resolve with ONE of:")
    print("    python3 ~/.claude/scripts/merge-hooks.py                  # discard local edit, restore from hooks.json")
    print("    python3 ~/.claude/scripts/check-hooks-drift.py --adopt    # publish local edit into hooks.json (intentional)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
