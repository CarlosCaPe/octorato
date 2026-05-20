#!/usr/bin/env python3
"""
check-generic.py — Block commits that leak arm/client/person identifiers.

The brain (~/.claude/) is open-source. Its git history is public. Anything
that references an arm code, client name, coworker, internal project, vendor
incident, or other sensitive token must NEVER reach the remote.

This script enforces the "Brain Stays Generic" rule from CLAUDE.md by scanning:
  - staged file contents (only files Git is about to commit)
  - the commit message (if provided)
against a private blocklist that lives in company/brain-blocklist.txt (gitignored).

Usage:
    python3 check-generic.py --message "commit message text"
    python3 check-generic.py --message-file .git/COMMIT_EDITMSG
    python3 check-generic.py --staged-only             # scan staged files only
    python3 check-generic.py --message "..." --staged  # both

Exit codes:
    0 — clean (proceed with commit)
    1 — leak detected (block the commit, show matches)
    2 — config error (no blocklist found, malformed args)

The blocklist file is a plaintext list, one token per line, '#' comments allowed.
Tokens are matched case-insensitively as whole words (\\b boundaries).
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

CLAUDE_DIR = Path(os.environ.get("CLAUDE_DIR", Path.home() / ".claude"))
BLOCKLIST_FILE = CLAUDE_DIR / "company" / "brain-blocklist.txt"
TEMPLATE_FILE = CLAUDE_DIR / "templates" / "company" / "brain-blocklist.txt.template"

# Files we never scan (binary, generated, vendored)
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".ico", ".woff",
                 ".woff2", ".ttf", ".eot", ".zip", ".tar", ".gz", ".whl",
                 ".pyc", ".so", ".dylib", ".dll", ".exe", ".bin"}
SKIP_PATH_PARTS = {"__pycache__", ".git", "node_modules", ".venv", "venv"}

# Filename patterns that must NEVER appear at the brain root.
# SDD artifacts (feature*.md, plan*.md, spec*.md) leak internal roadmap and
# inspiration sources into the public repo even when they contain zero client
# identifiers. They belong in the arm, in docs/specs-archive/, in templates/,
# or in company/ (gitignored) — never at root. See CLAUDE.md §"Brain Stays Generic".
ROOT_FORBIDDEN_PATTERNS = (
    re.compile(r"^feature(-.+)?\.md$", re.IGNORECASE),
    re.compile(r"^plan(-.+)?\.md$", re.IGNORECASE),
    re.compile(r"^spec(-.+)?\.md$", re.IGNORECASE),
)


def check_forbidden_paths(files):
    """Return list of files that violate root-level SDD-artifact rule."""
    violations = []
    for name in files:
        p = Path(name)
        if p.parent != Path("."):
            continue  # only root-level files
        for pat in ROOT_FORBIDDEN_PATTERNS:
            if pat.match(p.name):
                violations.append(name)
                break
    return violations


def load_blocklist():
    """Return (tokens, source_msg)."""
    if not BLOCKLIST_FILE.exists():
        msg = (
            f"No blocklist found at {BLOCKLIST_FILE}.\n"
            f"  This means brain-generic enforcement is disabled.\n"
            f"  To enable: copy {TEMPLATE_FILE} to {BLOCKLIST_FILE}\n"
            f"  and fill in the identifiers that must NEVER appear in this repo's history."
        )
        return None, msg
    tokens = []
    for line in BLOCKLIST_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        tokens.append(line)
    return tokens, f"loaded {len(tokens)} tokens from {BLOCKLIST_FILE}"


def build_pattern(tokens):
    """Whole-word, case-insensitive, escaped."""
    if not tokens:
        return None
    escaped = sorted({re.escape(t) for t in tokens if t}, key=len, reverse=True)
    return re.compile(r"\b(" + "|".join(escaped) + r")\b", re.IGNORECASE)


def staged_files():
    """List files staged for commit. Empty if not in a git repo with staged changes."""
    try:
        out = subprocess.check_output(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            cwd=str(CLAUDE_DIR), stderr=subprocess.DEVNULL, text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    files = []
    for name in out.splitlines():
        name = name.strip()
        if not name:
            continue
        if any(part in SKIP_PATH_PARTS for part in Path(name).parts):
            continue
        if Path(name).suffix.lower() in SKIP_SUFFIXES:
            continue
        files.append(name)
    return files


def staged_content(path):
    """Return the staged (index) version of a file. Empty if absent."""
    try:
        out = subprocess.check_output(
            ["git", "show", f":{path}"],
            cwd=str(CLAUDE_DIR), stderr=subprocess.DEVNULL,
        )
        return out.decode("utf-8", errors="replace")
    except subprocess.CalledProcessError:
        return ""


def scan_text(pattern, text, label):
    """Yield (label, lineno, line_excerpt, match) for each hit."""
    if not pattern or not text:
        return
    for lineno, line in enumerate(text.splitlines(), start=1):
        for m in pattern.finditer(line):
            excerpt = line.strip()
            if len(excerpt) > 120:
                excerpt = excerpt[:120] + "…"
            yield (label, lineno, excerpt, m.group(0))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--message", help="Commit message text to scan")
    parser.add_argument("--message-file", help="Path to a file containing the commit message (e.g. .git/COMMIT_EDITMSG)")
    parser.add_argument("--staged", action="store_true", help="Also scan staged file contents")
    parser.add_argument("--staged-only", action="store_true", help="Scan staged files only (no message)")
    parser.add_argument("--quiet", action="store_true", help="Print less on success")
    args = parser.parse_args()

    # Hard rule: no SDD artifacts at brain root. Runs BEFORE blocklist (doesn't
    # need company/brain-blocklist.txt to fire) — this is a structural rule, not
    # a token rule. The Datadog port spec slipped past blocklist enforcement
    # because it had zero client tokens; this stops the class of leak.
    if args.staged or args.staged_only:
        forbidden = check_forbidden_paths(staged_files())
        if forbidden:
            print("✗ check-generic: BLOCKED — SDD artifacts at brain root")
            print("  These files leak internal roadmap/sources into the public repo.")
            print("  Move them to the arm, docs/specs-archive/, templates/, or company/.")
            for f in forbidden:
                print(f"    forbidden: {f}")
            print()
            print("Rule: CLAUDE.md §'Brain Stays Generic' — SDD artifacts NEVER at brain root.")
            sys.exit(1)

    tokens, source_msg = load_blocklist()
    if tokens is None:
        # Soft-fail: warn but allow the commit. The rule itself in CLAUDE.md is the policy;
        # this script is an enforcement helper that requires the operator to configure it.
        print(f"⚠ check-generic: {source_msg}", file=sys.stderr)
        sys.exit(0)
    if not tokens:
        if not args.quiet:
            print("check-generic: blocklist is empty — nothing to enforce")
        sys.exit(0)

    pattern = build_pattern(tokens)
    hits = []

    # Scan commit message
    message = None
    if args.message_file:
        try:
            message = Path(args.message_file).read_text(encoding="utf-8")
        except OSError as e:
            print(f"check-generic: could not read {args.message_file}: {e}", file=sys.stderr)
            sys.exit(2)
    elif args.message:
        message = args.message

    if message is not None:
        hits.extend(scan_text(pattern, message, "<commit message>"))

    # Scan staged file contents
    if args.staged or args.staged_only:
        for f in staged_files():
            content = staged_content(f)
            hits.extend(scan_text(pattern, content, f))

    if not hits:
        if not args.quiet:
            print(f"✓ check-generic: clean ({source_msg})")
        sys.exit(0)

    print("✗ check-generic: BLOCKED — sensitive tokens detected")
    print(f"  Blocklist source: {BLOCKLIST_FILE}")
    print(f"  Hits: {len(hits)}")
    seen = set()
    for label, lineno, excerpt, match in hits[:25]:
        key = (label, lineno, match)
        if key in seen:
            continue
        seen.add(key)
        print(f"    {label}:{lineno}  «{match}»  → {excerpt}")
    if len(hits) > 25:
        print(f"    … {len(hits) - 25} more hits suppressed")
    print()
    print("Refusing to allow this commit. Options:")
    print("  • Rewrite the offending text to be generic (no arm/client/person identifiers)")
    print("  • If a token is a false positive (e.g. a real English word that happens to match),")
    print("    remove it from company/brain-blocklist.txt")
    sys.exit(1)


if __name__ == "__main__":
    main()
