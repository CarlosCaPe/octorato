#!/usr/bin/env python3
"""install-runners.py — make ~/.local/bin runners thin thunks into the tracked ai_sync.py.

The brain's sync runners (ai-pull / ai-push / sync-ai-docs) used to be standalone copies
in ~/.local/bin (POSIX) — untracked, so a fix to one never reached other machines, and the
bash and PowerShell forks drifted into different programs. This installer makes the runners
1-line thunks that exec the single tracked, cross-platform scripts/ai_sync.py. Run it once
per machine (first-time setup, or after pulling a runner change).

Idempotent. Backs up any existing non-thunk runner to <name>.prebrain.bak before overwriting.
Cross-platform: writes POSIX shell thunks on Linux/macOS, .cmd thunks on Windows.
"""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

HOME = Path.home()
AI_SYNC = HOME / ".claude" / "scripts" / "ai_sync.py"
VERBS = {"ai-pull": "pull", "ai-push": "push", "sync-ai-docs": "sync"}
MARKER = "# octorato-thunk"  # lets us recognize our own thunks (idempotent re-runs)


def bin_dir() -> Path:
    if os.name == "nt":
        d = Path(os.environ.get("USERPROFILE", HOME)) / ".local" / "bin"
    else:
        d = HOME / ".local" / "bin"
    d.mkdir(parents=True, exist_ok=True)
    return d


def posix_thunk(verb: str) -> str:
    return (f"#!/usr/bin/env bash\n{MARKER}\n"
            f'exec python3 "$HOME/.claude/scripts/ai_sync.py" {verb} "$@"\n')


def windows_thunk(verb: str) -> str:
    return ("@echo off\nrem octorato-thunk\n"
            f'python3 "%USERPROFILE%\\.claude\\scripts\\ai_sync.py" {verb} %*\n')


def install() -> int:
    if not AI_SYNC.exists():
        print(f"✗ {AI_SYNC} not found — pull the brain first", file=sys.stderr)
        return 1
    d = bin_dir()
    for name, verb in VERBS.items():
        target = d / (name + (".cmd" if os.name == "nt" else ""))
        content = windows_thunk(verb) if os.name == "nt" else posix_thunk(verb)
        if target.exists():
            existing = target.read_text(encoding="utf-8", errors="ignore")
            if MARKER in existing or "octorato-thunk" in existing:
                target.write_text(content, encoding="utf-8")
                print(f"  ✓ {target.name} (thunk refreshed)")
            else:
                backup = target.with_suffix(target.suffix + ".prebrain.bak")
                target.rename(backup)
                target.write_text(content, encoding="utf-8")
                print(f"  ✓ {target.name} (was standalone — backed up to {backup.name})")
        else:
            target.write_text(content, encoding="utf-8")
            print(f"  ✓ {target.name} (created)")
        if os.name != "nt":
            target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f"\nRunners now thunk into {AI_SYNC}")
    return 0


if __name__ == "__main__":
    raise SystemExit(install())
