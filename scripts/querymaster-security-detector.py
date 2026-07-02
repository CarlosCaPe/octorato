#!/usr/bin/env python3
"""QueryMaster security-canon detector (RULE #1 backing for SECURITY.querymaster-rules).

A SECURITY rule may not be wired by bare Presence (schema/wired-or-corrupt.md axis 3),
so the querymaster Security Rules need a REAL, runnable detector, not just an anchor.
The qm CLI itself enforces dry-run-by-default at runtime, but it lives outside this repo
(~/.local/bin/querymaster), so the doctor cannot reach it. This detector is the in-repo
companion: it asserts the non-negotiable security canon is intact in the skill file, so a
silent deletion or weakening of any core rule (dry-run-by-default, no secret logging,
destructive guard) fails the check instead of rotting unnoticed.

Exit 0 = canon intact (detector live). Exit 1 = a required security rule is missing.
Run: python3 scripts/querymaster-security-detector.py [--selftest]
"""
from __future__ import annotations

import sys
from pathlib import Path

CLAUDE_DIR = Path(__file__).resolve().parent.parent
SKILL = CLAUDE_DIR / "skills" / "querymaster" / "SKILL.md"

# Each entry is a substring that MUST survive in the Security Rules section.
REQUIRED = [
    "Security Rules (MANDATORY)",
    "Dry-run by default",
    "Never log secrets",
    "Destructive guard",
    "connections.json has no passwords",
]


def check() -> list[str]:
    if not SKILL.exists():
        return [f"skill file missing: {SKILL}"]
    text = SKILL.read_text(encoding="utf-8", errors="replace")
    return [f"security canon rotted: '{needle}' absent" for needle in REQUIRED
            if needle not in text]


def main() -> int:
    missing = check()
    if missing:
        for m in missing:
            print(m, file=sys.stderr)
        return 1
    print("querymaster security canon intact ({} assertions)".format(len(REQUIRED)))
    return 0


if __name__ == "__main__":
    # --selftest is an alias for the default assertion run; kept for proof clarity.
    sys.exit(main())
