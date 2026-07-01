#!/usr/bin/env python3
"""changelog-sync.py - heal CHANGELOG.md when releases were cut without entries.

Releases are cut server-side: version-bump.yml runs brain-version-bump.py on
every push to master, which tags and creates a GitHub Release. CHANGELOG.md is
manual, and master branch protection (required PRs, required checks,
enforce_admins) means no bot can commit the matching entry. The result is a
structural drift: tags run ahead of the CHANGELOG top and brain_doctor's
release-drift check WARNs forever.

This tool reconciles locally, so the repair rides the normal PR flow:

    - missing versions = semver tags strictly greater than the CHANGELOG's top
      released heading (`## [YYYY-MM-DD]: vX.Y.Z`)
    - the NEWEST missing version takes the curated `## [Unreleased]` body
      verbatim when that section is non-empty (that prose was written for it);
      the [Unreleased] heading stays as the standing intake, its body empties
    - every other missing version (or when [Unreleased] is empty) takes the
      GitHub Release notes (`gh release view`), falling back to grouped commit
      subjects from `git log <prev>..<tag>` when gh is missing or fails

Modes:
    (default)   print what would change. Writes nothing.
    --check     exit 1 if entries are missing, 0 if reconciled. Writes nothing.
    --apply     write CHANGELOG.md, one line per entry added. Idempotent: a
                second --apply finds nothing missing and is a no-op.

All git calls are pinned to the repo root via `-C`, so the result does not
depend on the caller's working directory. Everything outside the touched
section is preserved byte-for-byte.
"""
import re
import subprocess
import sys
from pathlib import Path
from shutil import which

TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
RELEASED_RE = re.compile(r"^## \[\d{4}-\d{2}-\d{2}\]: v(\d+\.\d+\.\d+)\s*$")
UNRELEASED_RE = re.compile(r"^## \[Unreleased\]\s*$", re.I)


def git(root, *args):
    r = subprocess.run(["git", "-C", root, *args],
                       capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def repo_root():
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write("changelog-sync: not a git repo\n")
        sys.exit(2)
    return r.stdout.strip()


def semver_tuple(version):
    return tuple(int(x) for x in version.lstrip("v").split("."))


def list_tags(root):
    """All vX.Y.Z tags, newest first by integer semver tuple."""
    _, out, _ = git(root, "tag")
    tags = [t.strip() for t in out.splitlines() if TAG_RE.match(t.strip())]
    return sorted(tags, key=semver_tuple, reverse=True)


def parse_changelog(text):
    """Locate the top released version and the [Unreleased] section.

    Returns (lines, top_version, unrel_idx, sect_end, body_lines):
        lines      - text split on newline (rejoin with newline is lossless)
        top_version- first `## [date]: vX.Y.Z` heading's version, or None
        unrel_idx  - line index of `## [Unreleased]`, or None
        sect_end   - index of the first `## ` line after [Unreleased] (or EOF);
                     when there is no [Unreleased], the index of the first
                     released heading (insert point after the title block)
        body_lines - the [Unreleased] body, surrounding blank lines stripped
    """
    lines = text.split("\n")
    top_version = None
    unrel_idx = None
    first_heading = len(lines)
    for i, line in enumerate(lines):
        if unrel_idx is None and UNRELEASED_RE.match(line):
            unrel_idx = i
            continue
        m = RELEASED_RE.match(line)
        if m:
            if top_version is None:
                top_version = m.group(1)
            first_heading = min(first_heading, i)
    if unrel_idx is not None:
        sect_end = len(lines)
        for i in range(unrel_idx + 1, len(lines)):
            if lines[i].startswith("## "):
                sect_end = i
                break
        body = lines[unrel_idx + 1:sect_end]
    else:
        sect_end = first_heading
        body = []
    while body and not body[0].strip():
        body.pop(0)
    while body and not body[-1].strip():
        body.pop()
    return lines, top_version, unrel_idx, sect_end, body


def tag_date(root, tag):
    code, out, _ = git(root, "for-each-ref",
                       "--format=%(creatordate:short)", f"refs/tags/{tag}")
    if code == 0 and out:
        return out
    code, out, _ = git(root, "log", "-1", "--format=%cs", tag)
    return out if code == 0 and out else "unknown-date"


def release_body(root, tag, prev):
    """Release notes for a tag: GitHub Release body first, commit-subject
    fallback second. Returns (lines, source_label)."""
    if which("gh"):
        r = subprocess.run(
            ["gh", "release", "view", tag, "--json", "body", "-q", ".body"],
            cwd=root, capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip("\n").split("\n"), "GitHub Release notes"
    rng = f"{prev}..{tag}" if prev else tag
    code, out, _ = git(root, "log", rng, "--no-merges", "--format=- %s")
    if code == 0 and out:
        return out.split("\n"), "commit subjects"
    return ["- (no release notes found for this tag)"], "empty fallback"


def build_entries(root, missing, unreleased_body, tags):
    """One (heading, body_lines, source) per missing version, newest first."""
    entries = []
    for i, tag in enumerate(missing):
        date = tag_date(root, tag)
        heading = f"## [{date}]: {tag}"
        if i == 0 and unreleased_body:
            body, source = list(unreleased_body), "[Unreleased] promotion"
        else:
            lower = [t for t in tags if semver_tuple(t) < semver_tuple(tag)]
            prev = lower[0] if lower else None
            body, source = release_body(root, tag, prev)
        entries.append((heading, body, source))
    return entries


def main():
    apply = "--apply" in sys.argv
    check = "--check" in sys.argv

    root = repo_root()
    changelog = Path(root) / "CHANGELOG.md"
    if not changelog.exists():
        sys.stderr.write("changelog-sync: CHANGELOG.md not found at repo root\n")
        return 2
    text = changelog.read_text(encoding="utf-8")
    lines, top_version, unrel_idx, sect_end, body = parse_changelog(text)

    tags = list_tags(root)
    if top_version:
        top = semver_tuple(top_version)
        missing = [t for t in tags if semver_tuple(t) > top]
    else:
        missing = list(tags)

    top_label = f"v{top_version}" if top_version else "(none)"
    newest_label = tags[0] if tags else "(none)"
    print(f"changelog-sync: CHANGELOG top {top_label}, newest tag {newest_label}")

    if not missing:
        print("  reconciled, no entries missing")
        return 0

    entries = build_entries(root, missing, body, tags)
    promoted = bool(body) and entries and entries[0][2] == "[Unreleased] promotion"

    if check:
        for heading, _, source in entries:
            print(f"  missing {heading[3:]} (would fill from {source})")
        return 1

    if not apply:
        for heading, _, source in entries:
            print(f"  missing {heading[3:]} (would fill from {source})")
        print("  dry-run, no writes; use --apply")
        return 0

    entry_lines = []
    for heading, ebody, _ in entries:
        entry_lines.extend([heading, *ebody, ""])
    if unrel_idx is not None:
        if promoted:
            # Promote the curated body out; the heading stays as the intake.
            new_lines = lines[:unrel_idx + 1] + [""] + entry_lines + lines[sect_end:]
        else:
            new_lines = lines[:sect_end] + entry_lines + lines[sect_end:]
    else:
        new_lines = lines[:sect_end] + entry_lines + lines[sect_end:]
    changelog.write_text("\n".join(new_lines), encoding="utf-8")
    for heading, _, source in entries:
        print(f"  added {heading[3:]} (from {source})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
