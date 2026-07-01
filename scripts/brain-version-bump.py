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
    --push      with --apply, also push the tag to origin. After the push, emit a
                GitHub Release (the changelog) for every bump, and for a
                minor/major bump queue a community news DRAFT under
                ~/.claude/knowledge/release-news/<version>.md (machine-local,
                gitignored, never auto-published). Patches get the Release only,
                so they never spam the news queue.

All git calls are pinned to the repo root via `-C`, so the result does not
depend on the caller's working directory (ai-push runs it as a post-push step).
The release/news emission is best-effort and never breaks the caller.
"""
import re
import subprocess
import sys
from pathlib import Path
from shutil import which

TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
# Conventional-commit header: type(scope)!: subject
CC_RE = re.compile(r"^(?P<type>[a-z]+)(?P<scope>\([^)]*\))?(?P<bang>!)?:", re.I)
# Breaking-change trailer: a line starting with BREAKING CHANGE: / BREAKING-CHANGE:
# (conventional-commit spec form) OR Octorato-Major: (the form the CHANGELOG documents).
# Anchored + multiline so prose like "NONBREAKING CHANGE foo" in a subject does NOT
# trip a major bump, and the hyphen variant is caught. Both forms bump MAJOR.
BREAKING_RE = re.compile(r"^(BREAKING[ -]CHANGE|Octorato-Major):", re.M)

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


def _release_notes(commits):
    """Group commit subjects since the last tag into a changelog body."""
    feats, fixes, other = [], [], []
    for subj, _ in commits:
        m = CC_RE.match(subj)
        t = (m.group("type").lower() if m else "")
        (feats if t == "feat" else fixes if t == "fix" else other).append(subj)
    out = []
    for title, group in (("Features", feats), ("Fixes", fixes), ("Other", other)):
        if group:
            out.append(f"### {title}")
            out += [f"- {s}" for s in group]
    return "\n".join(out) or "- (no commit summaries since last tag)"


def _news_draft(version, prev_tag, bump, notes):
    """A generic, community-facing DRAFT. The operator adds the angle and publishes;
    nothing here is auto-published, and nothing is brand-specific."""
    return (
        f"# Octorato {version}\n\n"
        f"_Status: DRAFT, queued by brain-version-bump on a {bump} release. "
        f"Review, add the why-it-matters angle, then publish via your news flow. "
        f"Not auto-published._\n\n"
        f"**Release:** {version} (previous: {prev_tag or 'none'})\n\n"
        f"## What changed\n{notes}\n\n"
        f"## Why it matters\n"
        f"<!-- One short paragraph for the community: what this unlocks, what it "
        f"removes, why a reader should care. Never echo the commit list as-is. -->\n\n"
        f"Source: GitHub Release {version}.\n"
    )


def _unreleased_body(root):
    """The `## [Unreleased]` body from CHANGELOG.md, or "" when absent/empty.
    Tiny duplicate of the changelog-sync.py parser, kept inline so a missing
    sibling script can never break the release path. Best-effort by contract."""
    try:
        text = (Path(root) / "CHANGELOG.md").read_text(encoding="utf-8")
        body, inside = [], False
        for line in text.split("\n"):
            if re.match(r"^## \[Unreleased\]\s*$", line, re.I):
                inside = True
                continue
            if inside and line.startswith("## "):
                break
            if inside:
                body.append(line)
        return "\n".join(body).strip("\n").strip()
    except Exception:
        return ""


def emit_release(root, version, prev_tag, bump, commits):
    """Best-effort, AFTER the tag is pushed: a GitHub Release for every bump (that is
    the changelog), plus a queued news DRAFT for substantive bumps (minor/major).
    Never raises. A failure here must never break the caller (ai-push)."""
    notes = _release_notes(commits)
    # Curated prose beats grouped commit subjects: when CHANGELOG.md carries a
    # non-empty [Unreleased] section, promote it to the top of the Release body
    # so the human-written summary reaches the Release even though branch
    # protection keeps any bot from committing the CHANGELOG entry itself.
    # The news draft below keeps the plain grouped list (the operator rewrites it).
    unreleased = _unreleased_body(root)
    release_body = f"{unreleased}\n\n---\n\n{notes}" if unreleased else notes
    # 1. GitHub Release = the changelog entry. Idempotent, needs gh, skips quietly.
    if which("gh"):
        seen = subprocess.run(["gh", "release", "view", version],
                              cwd=root, capture_output=True, text=True).returncode == 0
        if not seen:
            r = subprocess.run(
                ["gh", "release", "create", version, "--title", version,
                 "--notes", release_body, "--verify-tag"],
                cwd=root, capture_output=True, text=True)
            if r.returncode == 0:
                print(f"  released {version} (GitHub)")
            else:
                sys.stderr.write(
                    f"brain-version: gh release skipped ({r.stderr.strip()})\n")
    # 2. Queued news draft — ONLY for substantive bumps, so patches never spam news.
    if bump in ("minor", "major"):
        try:
            qdir = Path.home() / ".claude" / "knowledge" / "release-news"
            qdir.mkdir(parents=True, exist_ok=True)
            draft = qdir / f"{version}.md"
            if not draft.exists():
                draft.write_text(_news_draft(version, prev_tag, bump, notes),
                                 encoding="utf-8")
                print(f"  news draft queued: {draft} (review, then publish)")
        except OSError as e:
            sys.stderr.write(f"brain-version: news draft skipped ({e})\n")


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
            # Tag is on the remote now: emit the GitHub Release (changelog) and,
            # for minor/major, queue a news draft. Best-effort, never fatal.
            emit_release(root, nxt, tag, bump, commits)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
