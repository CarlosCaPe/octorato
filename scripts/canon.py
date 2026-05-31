#!/usr/bin/env python3
"""canon — one pulse across the cellular network.

The single command behind "update all Octorato info". Two heartbeats in one
breath, no marionette:

    canon-render   heal every surface already wired to a fact (writes)
    canon-detect   sweep the whole brain for loose pixels (read-only report)

Usage:
  python3 scripts/canon.py            # the pulse: heal wired, then sweep
  python3 scripts/canon.py --check    # no writes; exit 1 if drift OR loose
                                       # pixels (advisory CI / pre-push lane)

This composes the two tools rather than reimplementing them — the entry point
IS the harmony: one signal, every cell reconciles. See skills/octorato-harmony.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


def run(script: str, *args: str) -> int:
    return subprocess.run(["python3", str(SCRIPTS / script), *args]).returncode


def main() -> int:
    check = "--check" in sys.argv

    print("🐙 canon pulse — one signal, every cell reconciles\n")
    print("─── heartbeat 1/2: render (heal wired surfaces) ───")
    rc_render = run("canon-render.py", *(["--check"] if check else []))

    print("\n─── heartbeat 2/2: detect (sweep loose pixels) ───")
    rc_detect = run("canon-detect.py", *(["--strict"] if check else []))

    if check:
        bad = rc_render != 0 or rc_detect != 0
        print(f"\ncanon: {'OUT OF UNISON' if bad else 'in unison'} "
              f"(render={rc_render}, detect={rc_detect})")
        return 1 if bad else 0
    print("\ncanon: pulse complete — wired surfaces healed, loose pixels reported.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
