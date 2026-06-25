#!/usr/bin/env python3
"""
check-stats-drift — guard that the brain's headline floors stay TRUTHFUL.

Design rule (set 2026-05-25): prose/marketing surfaces (README, site CV) use
STABLE ROUNDED FLOORS ("180+ skills", "150+ agents"); only the auto-generated
wiki catalog pages carry exact live counts. This guard catches the two ways a
floor goes wrong:

  1. The real count drops BELOW the floor  → the floor is now a lie (too high).
  2. The real count crosses the NEXT round  → the floor is stale/under-selling
     (operator: "a que pase de 190 le cambiamos" → bump 180+ → 190+).

It also fails if any FORBIDDEN stale exact token re-appears in prose (a
regression to hardcoded counts).

Run by ai-push (non-fatal warning) so drift surfaces on every brain push.

Exit 0 = floors healthy. Exit 1 = drift (warn). Never blocks; it informs.
"""
from __future__ import annotations
import re, subprocess, sys, pathlib
import sys

# Force UTF-8 on stdout/stderr so the ✓ / ✗ / em-dash glyphs in reports
# survive on Windows shells defaulting to cp1252. Without this, a script
# can do its work correctly and still crash with UnicodeEncodeError when
# printing success. Applied repo-wide by _apply-utf8-reconfigure.py.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


BRAIN = pathlib.Path.home() / ".claude"
STATS = BRAIN / "scripts" / "brain-stats.py"

# Floors currently asserted in prose (README + site). Keep in sync with the
# tokens actually written. {label: (floor, next_round)}
FLOORS = {
    "skills": (230, 240),   # "230+"; bump to 240+ when real >= 240
    "agents": (160, 170),   # "160+"; bump to 170+ when real >= 170
}
FORBIDDEN_STALE = ["162 agent", "110 reusable", "110 skill", "4,621", "4.621"]


def canonical() -> dict:
    out = subprocess.run([sys.executable, str(STATS), "--json"],
                         capture_output=True, text=True)
    import json
    return json.loads(out.stdout)


def main() -> int:
    s = canonical()
    issues: list[str] = []

    for label, (floor, nxt) in FLOORS.items():
        real = s.get(label, 0)
        if real < floor:
            issues.append(f"{label}: real {real} < floor {floor} — the '{floor}+' claim is now FALSE; lower the floor")
        elif real >= nxt:
            issues.append(f"{label}: real {real} >= {nxt} — bump the floor '{floor}+' → '{nxt}+' (operator rule)")

    # Forbidden stale tokens in prose surfaces (README + wiki prose + site copy if present)
    surfaces = [BRAIN / "README.md"] + list((BRAIN / "docs" / "wiki").glob("*.md"))
    for f in surfaces:
        if not f.is_file():
            continue
        txt = f.read_text(encoding="utf-8", errors="replace")
        for tok in FORBIDDEN_STALE:
            if tok in txt:
                issues.append(f"{f.name}: forbidden stale token '{tok}' reappeared")

    if not issues:
        print(f"✓ stats-drift: floors healthy (skills={s['skills']}, agents={s['agents']}, divisions={s['divisions']})")
        return 0
    print("⚠ stats-drift detected:")
    for i in issues:
        print(f"   - {i}")
    print("   → update the floors in README.md + the site (cv.ts / cv_translations.ts / i18n / chat.ts)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
