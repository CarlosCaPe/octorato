#!/usr/bin/env python3
"""quickstart.py — zero-to-alive for a brand-new Octorato user, in one command.

A stranger clones the brain and runs this. No company brain, no sealed worlds, no
config: it checks prerequisites, wires the bin runners, builds the connectome,
runs the health check, and prints the first thing to TRY so the brain proves
itself alive. The 5-minute "it works" moment.

Going further (your own brain + sealed worlds + multi-machine sync) is a separate,
later step, documented in the README.

Idempotent. Safe to re-run. No network, no writes outside ~/.claude.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

if sys.platform == "win32":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

CLAUDE = Path(__file__).resolve().parent.parent
_COLOR = sys.stdout.isatty() and sys.platform != "win32"


def _c(code, s):
    return f"\033[{code}m{s}\033[0m" if _COLOR else s


def info(s): print(_c("0;32", s))
def warn(s): print(_c("1;33", s))
def err(s):  print(_c("0;31", s))
def step(n, total, s): print(_c("1;36", f"\n[{n}/{total}] {s}"))


def run_script(rel: str, *args) -> bool:
    """Run a brain python script if present. True on success or absent."""
    path = CLAUDE / rel
    if not path.exists():
        warn(f"  (skipped: {rel} not found in this checkout)")
        return True
    code = subprocess.run([sys.executable or "python3", str(path), *args]).returncode
    return code == 0


def main() -> int:
    print(_c("1;35", "\n🐙  Octorato quickstart. Let's bring your brain to life.\n"))
    total = 4

    # 1. Prerequisites
    step(1, total, "Checking prerequisites")
    ok = True
    if sys.version_info < (3, 9):
        err(f"  ✗ Python {sys.version_info.major}.{sys.version_info.minor} found; need 3.9+")
        ok = False
    else:
        info(f"  ✓ Python {sys.version_info.major}.{sys.version_info.minor}")
    if shutil.which("git"):
        info("  ✓ git")
    else:
        err("  ✗ git not found. Install it first.")
        ok = False
    if shutil.which("claude"):
        info("  ✓ Claude Code CLI (`claude`)")
    else:
        warn("  ! Claude Code CLI not on PATH. Octorato is its brain, so install it:")
        warn("    https://docs.claude.com/claude-code")
    if not (CLAUDE / "CLAUDE.md").exists():
        err(f"  ✗ This doesn't look like a brain checkout ({CLAUDE}/CLAUDE.md missing).")
        err("    Clone first:  git clone https://github.com/CarlosCaPe/octorato.git ~/.claude")
        return 1
    info(f"  ✓ Brain checkout at {CLAUDE}")
    if not ok:
        err("\nFix the ✗ items above, then re-run. Nothing was changed.")
        return 1

    # 2. Wire the runners
    step(2, total, "Wiring the bin runners (ai-sync / ai-push / ai-pull)")
    run_script("scripts/install-runners.py")

    # 3. Build the connectome
    step(3, total, "Building the connectome (the skill/agent graph)")
    run_script("scripts/generate_neural_map.py")

    # 4. Health check
    step(4, total, "Running the brain health check")
    healthy = run_script("scripts/brain_doctor.py")

    # First-value moment
    print(_c("1;32", "\n" + "─" * 64))
    if healthy:
        print(_c("1;32", "✓ Your brain is alive."))
    else:
        warn("Brain wired, but the health check flagged something. See above; "
             "most items self-heal with `python3 scripts/brain_doctor.py --fix`.")
    print("─" * 64)
    print("""
TRY IT NOW (the 5-minute proof):
  1. Open Claude Code in any folder:   claude
  2. Ask it something real, e.g.:
       "summarize what this repo does and propose one improvement"
  3. Watch what a brain adds on top of a plain agent:
       • a Provenance footer on every answer (Basis / Engine / Touched / Verified)
       • the 2D delegate gate picking the right skill/agent for the task
       • skills loading themselves from this library

WHY THIS, NOT PLAIN CLAUDE CODE:
  Your AI agent forgets who you are and mixes your worlds. An octorato is its
  second brain: memory that lasts, every world sealed from the others, and a
  receipt on every action. One brain for clients, projects, courses, anything
  you keep separate. The difference between a clever assistant and one you can
  trust on real work (and, when a world happens to be a client, bill for).

GOING FURTHER (your own brain + sealed worlds):
  Create your own company brain and sealed "arms" (a client, a project, a
  research topic, a course you're taking), then keep every machine in sync with
  one command:  ai-sync
  Full guide in the README.
""")
    print(_c("1;35", "Welcome aboard. 🐙\n"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
