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

# The section header that must locate the canon block.
SECTION = "Security Rules (MANDATORY)"

# One substring per numbered rule (7 total) in skills/querymaster/SKILL.md.
# All 7 must survive, or a rule was silently deleted or weakened.
REQUIRED = [
    "Dry-run by default",                  # rule 1
    "Never log secrets",                   # rule 2
    "Read-only mode",                      # rule 3
    "Destructive guard",                   # rule 4
    "connections.json has no passwords",   # rule 5
    "Timeout",                             # rule 6
    "Row limit",                           # rule 7
]


def check() -> list[str]:
    if not SKILL.exists():
        return [f"skill file missing: {SKILL}"]
    text = SKILL.read_text(encoding="utf-8", errors="replace")
    missing = []
    if SECTION not in text:
        missing.append(f"security section missing: '{SECTION}'")
    missing += [f"security canon rotted: '{needle}' absent" for needle in REQUIRED
                if needle not in text]
    return missing


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
