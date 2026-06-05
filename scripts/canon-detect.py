#!/usr/bin/env python3
"""canon-detect — sweep EVERY pixel that speaks a canonical fact.

Read-only companion to canon-render. Where canon-render *heals* the surfaces
that opted in (carry a marker), canon-detect *finds the ones that haven't* — it
walks the whole brain, locates every place a canonical fact VALUE appears, and
reports which occurrences are already managed (inside a <!--canon:ID--> span)
versus UNMANAGED (a raw mention not yet wired to the pulse).

This is the "barre cada pixel que hable de octorato" mechanism: one command
surfaces every cell that mentions a fact, so it can be brought under the canon.
It NEVER edits and NEVER invents — it flags, the operator/agent decides
(connector, not fabricator). Drift on external surfaces (dev.to, wikis) that we
cannot edit by code is reported the same way, never silently passed.

Only DISTINCTIVE asserted facts are swept by literal value (URLs, taglines —
strings unlikely to collide). Count/floored facts are noise as bare numbers, so
they are tracked by marker only, not by whole-repo number grep.

Usage:
  python3 scripts/canon-detect.py            # full report
  python3 scripts/canon-detect.py --strict   # exit 1 if any UNMANAGED mention
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
# Force UTF-8 on stdout/stderr so the ✓ / ✗ / em-dash glyphs in reports
# survive on Windows shells defaulting to cp1252. Without this, a script
# can do its work correctly and still crash with UnicodeEncodeError when
# printing success. Applied repo-wide by _apply-utf8-reconfigure.py.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


ROOT = Path(__file__).resolve().parent.parent

# Reuse canon-render's registry loader + renderer (DRY) despite the hyphen name.
_spec = importlib.util.spec_from_file_location("canon_render", ROOT / "scripts" / "canon-render.py")
_cr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cr)

SKIP_DIRS = {".git", "node_modules", "dist", ".astro", "company", "__pycache__",
             ".venv", "venv", "build", ".cache"}
TEXT_EXT = {".md", ".markdown", ".mdx", ".txt", ".svelte", ".astro", ".html",
            ".vue", ".mjs", ".ts", ".tsx", ".jsx", ".yaml", ".yml"}

MARKER_SPAN = re.compile(r"<!--\s*canon:[\w.\-]+\s*-->.*?<!--\s*/canon\s*-->", re.DOTALL)


def distinctive(value: str) -> bool:
    """Worth a literal whole-brain sweep: a multi-word PHRASE (an authoritative
    assertion someone could paraphrase and drift), NOT a bare URL or token.
    URLs appear in too many legitimate links to "manage" each occurrence — they
    are marker-tracked only, like counts. The discipline: the pulse reaches every
    pixel, but only load-bearing assertions get wired; never auto-wrap a mention.
    """
    if "://" in value:
        return False
    return " " in value and len(value) >= 12


def walk_files():
    for p in ROOT.rglob("*"):
        if p.is_dir():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p == _cr.REGISTRY:  # the genome is the source, not a surface to sweep
            continue
        if p.suffix.lower() in TEXT_EXT:
            yield p


def main() -> int:
    strict = "--strict" in sys.argv
    reg = _cr.load_registry()
    if reg is None:
        print("canon-detect: no registry — nothing to sweep (soft-fail)")
        return 0
    facts, _targets = reg

    # Resolve canonical values once; keep only the distinctive, sweepable ones.
    sweepable = {}
    for fid, fact in facts.items():
        try:
            val = _cr.render(fact)
        except Exception:
            continue
        if distinctive(val):
            sweepable[fid] = val

    if not sweepable:
        print("canon-detect: no distinctive facts to sweep (counts are marker-tracked only)")
        return 0

    # fid -> {"managed": [(file,line)], "unmanaged": [(file,line)]}
    tally = {fid: {"managed": [], "unmanaged": []} for fid in sweepable}

    for path in walk_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        # Spans covered by a canon marker = managed regions.
        managed_spans = [m.span() for m in MARKER_SPAN.finditer(text)]
        for fid, val in sweepable.items():
            start = 0
            while (idx := text.find(val, start)) != -1:
                start = idx + len(val)
                inside = any(s <= idx < e for s, e in managed_spans)
                line = text.count("\n", 0, idx) + 1
                rel = path.relative_to(ROOT)
                tally[fid]["managed" if inside else "unmanaged"].append((rel, line))

    total_unmanaged = 0
    print("canon-detect — pulse sweep across the cellular network\n")
    for fid, val in sweepable.items():
        m, u = tally[fid]["managed"], tally[fid]["unmanaged"]
        total_unmanaged += len(u)
        print(f"canon:{fid}  =  {val!r}")
        print(f"  managed (wired to the pulse): {len(m)}   unmanaged (loose pixels): {len(u)}")
        for rel, line in u[:20]:
            print(f"    ⚠ UNMANAGED  {rel}:{line}")
        if len(u) > 20:
            print(f"    … +{len(u) - 20} more")
        print()

    print(f"canon-detect: {total_unmanaged} unmanaged mention(s) across the brain.")
    if total_unmanaged:
        print("  → wire each into a <!--canon:ID-->…<!--/canon--> span to bring it under the pulse.")
    if strict and total_unmanaged:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
