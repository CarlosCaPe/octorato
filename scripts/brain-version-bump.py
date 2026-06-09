#!/usr/bin/env python3
"""brain-version-bump.py - move the brain's semver label by change class.

The brain carries two labels. The README count floor moves only when the real
count crosses a ten boundary (see sync-readme-counts.py --floor), so small
changes never churn it. The semver git tag is the other label, and this tool
moves it on every push that has commits, sizing the bump by the
conventional-commit type of the commits since the last tag:

    major  ->  a commit typed with `!` (feat!: / fix!:) or a `BREAKING CHANGE`
               trailer in the body
    minor  ->  any `feat` commit
    patch  ->  any other conventional commit (fix/docs/chore/refactor/perf/...)
    none   ->  no commits since the last tag, or nothing conventional

That is the operator's own model: the label moves every time there are
changes, and WHICH digit moves depends on the change.

Modes:
    (default)   print current -> next + reason. Writes nothing.
    --check     exit 1 if a bump is pending (CI / visibility). Writes nothing.
    --apply     create the annotated tag locally.
    --push      with --apply, also push the tag to origin.

All git calls are pinned to the repo root via `-C`, so the result does not
depend on the caller's working directory (ai-push runs it as a post-push step).
"""
import re
import subprocess
import sys

TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
# Conventional-commit header: type(scope)!: subject
CC_RE = re.compile(r"^(?P<type>[a-z]+)(?P<scope>\([^)]*\))?(?P<bang>!)?:", re.I)
# Breaking-change trailer (spec form): a line starting with BREAKING CHANGE: or
# BREAKING-CHANGE:. Anchored + multiline so prose like "NONBREAKING CHANGE foo"
# in a subject does NOT trip a major bump, and the hyphen variant is caught.
BREAKING_RE = re.compile(r"^BREAKING[ -]CHANGE:", re.M)

# Change-class policy (config-as-code). type -> bump when no `!`/BREAKING.
MINOR_TYPES = {"feat"}
# everything else conventional is a patch; non-conventional commits are ignored
# for sizing but still count as "there were changes" -> patch floor.
RANK = {"none": 0, "patch": 1, "minor": 2, "major": 3}


def git(root, *args):
    r = subprocess.run(["git", "-C", root, *args],
                       capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def repo_root():
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write("brain-version-bump: not a git repo\n")
        sys.exit(2)
    return r.stdout.strip()


def tag_exists(root, tag):
    code, _, _ = git(root, "rev-parse", "-q", "--verify", f"refs/tags/{tag}")
    return code == 0


def latest_tag(root):
    _, out, _ = git(root, "tag", "--sort=-v:refname")
    for line in out.splitlines():
        if TAG_RE.match(line.strip()):
            return line.strip()
    return None


def commits_since(root, tag):
    rng = f"{tag}..HEAD" if tag else "HEAD"
    # %x1e record separator, %x1f field separator: subject<US>body
    code, out, _ = git(root, "log", rng, "--no-merges",
                       "--format=%s%x1f%b%x1e")
    if code != 0 or not out:
        return []
    recs = []
    for chunk in out.split("\x1e"):
        chunk = chunk.strip("\n")
        if not chunk.strip():
            continue
        subj, _, body = chunk.partition("\x1f")
        recs.append((subj.strip(), body.strip()))
    return recs


def classify(commits):
    """Return ('none'|'patch'|'minor'|'major', reason)."""
    if not commits:
        return "none", "no commits since last tag"
    bump = "patch"
    reason = f"{len(commits)} commit(s), no feat/breaking -> patch"
    for subj, body in commits:
        m = CC_RE.match(subj)
        is_breaking = bool(m and m.group("bang")) or \
            bool(BREAKING_RE.search(subj)) or bool(BREAKING_RE.search(body))
        if is_breaking:
            return "major", f"breaking change in: {subj!r}"
        if m and m.group("type").lower() in MINOR_TYPES:
            if RANK["minor"] > RANK[bump]:
                bump = "minor"
                reason = f"feat commit: {subj!r}"
    return bump, reason


def next_version(tag, bump):
    if tag is None:
        major, minor, patch = 0, 0, 0
    else:
        major, minor, patch = map(int, TAG_RE.match(tag).groups())
    if bump == "major":
        return f"v{major + 1}.0.0"
    if bump == "minor":
        return f"v{major}.{minor + 1}.0"
    if bump == "patch":
        return f"v{major}.{minor}.{patch + 1}"
    return tag  # none


def main():
    apply = "--apply" in sys.argv
    push = "--push" in sys.argv
    check = "--check" in sys.argv

    root = repo_root()
    tag = latest_tag(root)
    commits = commits_since(root, tag)
    bump, reason = classify(commits)
    nxt = next_version(tag, bump)

    cur = tag or "(none)"
    if bump == "none":
        print(f"brain-version: {cur} (no bump pending)")
        return 0

    # Collision guard: if the computed name already exists (a partial prior run,
    # a tag minted on another branch, a reset), walk forward by the same class
    # until the name is free — otherwise --apply would no-op forever on a stuck
    # version.
    while tag_exists(root, nxt):
        nxt = next_version(nxt, bump)

    print(f"brain-version: {cur} -> {nxt}  [{bump}]  {reason}")

    if check:
        return 1  # a bump is pending

    if apply:
        msg = f"brain {nxt} ({len(commits)} commit(s) since {cur}: {bump})"
        code, _, e = git(root, "tag", "-a", nxt, "-m", msg)
        if code != 0:
            # "already exists" is the benign idempotent case (a race or a
            # partial prior run). Any OTHER failure (bad object store, read-only
            # .git) must surface, still without breaking ai-push.
            if "already exists" in e:
                return 0
            sys.stderr.write(f"brain-version: tag {nxt} failed ({e})\n")
            return 0
        print(f"  tagged {nxt}")
        if push:
            code, _, e = git(root, "push", "origin", nxt)
            if code != 0:
                sys.stderr.write(f"brain-version: tag push failed ({e})\n")
                return 0
            print(f"  pushed {nxt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
