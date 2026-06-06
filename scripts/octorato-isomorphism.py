#!/usr/bin/env python3
"""octorato-isomorphism — compute the invariant shared by the three Octorato anchors.

The user's idea (generate huge corpora describing octopus / Linux / tesseract, strip
synonyms, keep what lands in all three) is set intersection over a quotient-by-synonymy.
Brute-forcing 1.2M words has near-zero marginal signal; the invariant is found by
abstraction, not generation. This script does exactly that: reads three curated
descriptor sets, collapses synonyms (V/~), intersects, and maps each invariant to the
Octorato primitive it implies, checking whether that primitive already exists.

Read-only. No network, no writes. Idempotent.

  python3 octorato-isomorphism.py            # human table
  python3 octorato-isomorphism.py --json     # machine output
"""
import json
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


try:
    import yaml
except ImportError:
    sys.exit("PyYAML required: pipx install pyyaml  (or pip install --user pyyaml)")

BRAIN = Path(__file__).resolve().parent.parent
ANCHORS = BRAIN / "skills" / "octorato-isomorphism" / "anchors.yaml"


def build_canonicalizer(groups):
    """Map every synonym to its group's canonical (first) form."""
    canon = {}
    for group in groups:
        head = group[0]
        for word in group:
            canon[word] = head
    return lambda w: canon.get(w, w)


def compute():
    data = yaml.safe_load(ANCHORS.read_text())
    anchors = data["anchors"]
    canonicalize = build_canonicalizer(data.get("synonyms", []))
    skill_map = data.get("skill_map", {})

    # Quotient each anchor by synonymy, then intersect.
    canon_sets = {name: {canonicalize(w) for w in words} for name, words in anchors.items()}
    invariant = set.intersection(*canon_sets.values())

    rows = []
    for word in sorted(invariant):
        spec = skill_map.get(word, {})
        target = spec.get("target", "?")
        kind = spec.get("kind", "unmapped")
        note = spec.get("note", "")
        exists, recommend = resolve(kind, target)
        rows.append(dict(invariant=word, target=target, kind=kind,
                         exists=exists, recommend=recommend, note=note))
    return canon_sets, invariant, rows


def resolve(kind, target):
    """Existence + recommendation. Only `skill` kinds are checked on disk."""
    if kind == "skill":
        present = (BRAIN / "skills" / target / "SKILL.md").exists()
        return ("yes" if present else "MISSING",
                "KEEP" if present else "CREATE — named gap in the invariant")
    if kind in ("core", "script", "memory"):
        return (f"by-design ({kind})", "KEEP — already a primitive, do not duplicate")
    return ("?", "REVIEW — no mapping yet")


def main():
    canon_sets, invariant, rows = compute()
    if "--json" in sys.argv:
        print(json.dumps(dict(
            sizes={k: len(v) for k, v in canon_sets.items()},
            invariant=sorted(invariant), rows=rows), indent=2))
        return

    print("Octorato Isomorphism — invariant of octopus ∧ linux ∧ tesseract")
    print("=" * 72)
    for name, s in canon_sets.items():
        print(f"  {name:<10} {len(s)} distinct concepts (post-synonym)")
    print(f"  INVARIANT  {len(invariant)} words land in all three\n")

    h = f"  {'invariant':<15} {'maps to':<22} {'kind':<8} {'exists':<14} recommend"
    print(h); print("  " + "-" * (len(h) - 2))
    for r in rows:
        print(f"  {r['invariant']:<15} {r['target']:<22} {r['kind']:<8} "
              f"{r['exists']:<14} {r['recommend']}")
    missing = [r for r in rows if r["exists"] == "MISSING"]
    print(f"\n  {len(missing)} skill-kind gap(s): "
          f"{', '.join(r['target'] for r in missing) or 'none'}")
    print("  Finding: the brain already embodies most of the invariant; "
          "gaps are the only work.")


if __name__ == "__main__":
    main()
