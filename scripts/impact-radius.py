#!/usr/bin/env python3
"""impact-radius.py — automate the Disclose Impact Radius scan.

The #1 recurrent failure: codify a concept in ONE file, leave its references
elsewhere stale → the brain goes "pixelated" (coherent in patches). The 4D
Disclose rule already says "scan for repercussions", but it was a manual grep
that gets skipped. This makes it one command, so it can't be skipped silently.

Given a concept TERM (or a changed file), it lists every brain file that
references the concept. Reconcile the Provenance footer's `Touched` against this
list: files here NOT in Touched = a SKIP; files in Touched NOT implied here =
possible over-reach. Loop until they reconcile (no skip, no excess).

Usage:
  impact-radius.py "<term>"        # every brain file referencing term
  impact-radius.py --file <path>   # derive the term from a changed file, scan
"""
import sys
import subprocess
from pathlib import Path

CLAUDE_DIR = Path(__file__).resolve().parent.parent
SCAN = ["CLAUDE.md", "README.md", "WHITEPAPER.md", "ROADMAP.md", "SHOWCASE.md",
        "CONTRIBUTING.md", "skills", "agents", "commands", "docs"]


def scan(term: str, exclude: str | None = None) -> list[str]:
    targets = [str(CLAUDE_DIR / g) for g in SCAN if (CLAUDE_DIR / g).exists()]
    if not targets:
        return []
    try:
        out = subprocess.run(
            ["grep", "-rilF", "--include=*.md", "--include=*.py", "--include=*.json",
             "--", term, *targets],
            capture_output=True, text=True, timeout=30,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return []
    files = set()
    for p in out.splitlines():
        p = p.strip()
        if not p:
            continue
        try:
            rel = Path(p).resolve().relative_to(CLAUDE_DIR).as_posix()
        except ValueError:
            continue
        files.add(rel)
    if exclude:
        files.discard(exclude)
    return sorted(files)


def term_from_file(path: str) -> tuple[str | None, str | None]:
    """Return (term, rel) for a changed file. Skills → the skill dir name."""
    p = Path(path)
    try:
        rel = p.resolve().relative_to(CLAUDE_DIR).as_posix()
    except (ValueError, OSError):
        return None, None
    if rel.endswith("/SKILL.md"):
        return p.parent.name, rel
    if rel.endswith(".py"):
        return p.stem, rel
    return None, rel


def main():
    if len(sys.argv) < 2:
        print(__doc__.strip())
        sys.exit(0)
    if sys.argv[1] == "--file":
        if len(sys.argv) < 3:
            print("usage: impact-radius.py --file <path>", file=sys.stderr)
            sys.exit(2)
        term, rel = term_from_file(sys.argv[2])
        if not term:
            print(f"(no auto-term for {sys.argv[2]} — pass an explicit term)")
            sys.exit(0)
    else:
        term, rel = " ".join(sys.argv[1:]), None
    files = scan(term, exclude=rel)
    if not files:
        print(f"Impact Radius of '{term}': no other references found in the repo.")
    else:
        print(f"Impact Radius of '{term}' — referenced in {len(files)} repo file(s):")
        for f in files:
            print(f"  {f}")
        print("\nReconcile your Provenance `Touched` against this list: "
              "every relevant file here must be updated or consciously skipped.")
    print(off_repo_reminder())


def off_repo_reminder() -> str:
    # The repo grep cannot see these surfaces — they must be checked by hand
    # when a concept changes, or the concept goes stale off-repo (the wiki-skip
    # failure). Reconcile or consciously annotate each; never silently leave.
    return (
        "\n⚠ OFF-REPO surfaces this scan can NOT see — reconcile each by hand:\n"
        "  • the GitHub wiki (separate `octorato.wiki` repo)\n"
        "  • arm-rendered pages (e.g. dataqbs.com/octorato) + their RAG knowledge files\n"
        "  • external posts (dev.to, Wikidata) — point-in-time: update or annotate, don't leave stale"
    )


if __name__ == "__main__":
    main()
