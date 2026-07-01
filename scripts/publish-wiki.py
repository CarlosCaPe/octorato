#!/usr/bin/env python3
"""publish-wiki.py - publish docs/wiki/ to the public GitHub wiki.

WHY: the GitHub wiki (github.com/CarlosCaPe/octorato/wiki) is a separate repo
(octorato.wiki.git) that no mechanism ever wrote to. docs/wiki/ in the brain is
the reviewed source of truth, the wiki was a manual mirror, and manual mirrors
die: the public wiki went stale on 2026-06-03 and stayed stale. This script is
the missing mechanism. ai_sync.py's `push` verb calls it after every successful
brain push (best-effort), so the wiki tracks docs/wiki/ without anyone
remembering to copy pages by hand.

How it works:
    - clone-or-pull the wiki repo into a gitignored cache
      (~/.claude/.cache/octorato-wiki), so repeat runs are cheap
    - copy every docs/wiki/*.md over the checkout. Wiki page names match the
      file names, so this is a straight overwrite. docs/wiki/README.md is
      SKIPPED: the wiki's landing page is Home.md, and a repo-style README
      must never clobber it.
    - `git status` clean means the wiki already matches: exit 0, no commit
    - otherwise commit `wiki: sync from docs/wiki @ <short-sha>` and, with
      --push, publish it

Modes:
    (default)   dry-run per the dry-run-gate-pattern: clone/pull, compute the
                diff, PRINT the plan, restore the cache, write nothing to the
                remote. Never exits non-zero (a network hiccup is a warning).
    --push      apply: commit and push the sync. Exits non-zero on failure so
                callers can surface it (ai-push treats that as a one-line
                warning, never as its own failure).

Stdlib only. Never raises: every subprocess result is checked and reported.
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

BRAIN = Path(__file__).resolve().parent.parent
DOCS_WIKI = BRAIN / "docs" / "wiki"
CACHE = BRAIN / ".cache" / "octorato-wiki"
WIKI_URL = "https://github.com/CarlosCaPe/octorato.wiki.git"
SKIP = {"README.md"}  # repo landing page; the wiki's landing page is Home.md


def run(args, cwd=None):
    """Run a command; return (returncode, stdout, stderr). Never raises."""
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except OSError as e:
        return 1, "", str(e)


def clone_or_pull():
    """Bring the wiki cache to the remote tip. Returns True on success."""
    if (CACHE / ".git").is_dir():
        # A dirty cache (a previous aborted run) would make the pull fail or
        # merge stale copies; the cache is disposable, so hard-reset first.
        run(["git", "reset", "--hard", "HEAD"], cwd=CACHE)
        run(["git", "clean", "-fd"], cwd=CACHE)
        code, _, e = run(["git", "pull", "--ff-only"], cwd=CACHE)
        if code != 0:
            print(f"publish-wiki: pull failed ({e.splitlines()[-1] if e else 'unknown'})")
            return False
        return True
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    code, _, e = run(["git", "clone", WIKI_URL, str(CACHE)])
    if code != 0:
        print(f"publish-wiki: clone failed ({e.splitlines()[-1] if e else 'unknown'})")
        return False
    return True


def copy_pages():
    """Overlay docs/wiki/*.md onto the cache checkout. Returns pages copied."""
    pages = sorted(p for p in DOCS_WIKI.glob("*.md") if p.name not in SKIP)
    for page in pages:
        shutil.copyfile(page, CACHE / page.name)
    return pages


def changed_files():
    # NOTE: run() strips stdout, which eats the leading space of the first
    # porcelain line (` M file`), so column offsets are unreliable here.
    # Split on the first whitespace run instead: `XY path` -> path.
    _, out, _ = run(["git", "status", "--porcelain"], cwd=CACHE)
    return [line.strip().split(None, 1)[1]
            for line in out.splitlines() if len(line.split(None, 1)) == 2]


def main() -> int:
    ap = argparse.ArgumentParser(description="publish docs/wiki to the GitHub wiki")
    ap.add_argument("--push", action="store_true",
                    help="apply: commit and push (default is dry-run)")
    args = ap.parse_args()

    if not DOCS_WIKI.is_dir():
        print("publish-wiki: docs/wiki/ not found; nothing to publish")
        return 1 if args.push else 0

    if not clone_or_pull():
        # Network or auth trouble. Dry-run stays green (nothing was promised);
        # --push must surface the failure to its caller.
        return 1 if args.push else 0

    pages = copy_pages()
    changed = changed_files()

    if not changed:
        print(f"publish-wiki: wiki already current ({len(pages)} pages checked)")
        return 0

    _, sha, _ = run(["git", "rev-parse", "--short", "HEAD"], cwd=BRAIN)
    msg = f"wiki: sync from docs/wiki @ {sha or 'unknown'}"

    if not args.push:
        print(f"publish-wiki: DRY-RUN, would commit + push {len(changed)} page(s):")
        for name in changed:
            print(f"  {name}")
        print(f'  commit message: "{msg}"')
        print("publish-wiki: re-run with --push to apply")
        # Leave the cache clean so the next pull is a fast-forward.
        run(["git", "reset", "--hard", "HEAD"], cwd=CACHE)
        run(["git", "clean", "-fd"], cwd=CACHE)
        return 0

    for name in changed:
        run(["git", "add", name], cwd=CACHE)
    code, _, e = run(["git", "commit", "-m", msg], cwd=CACHE)
    if code != 0:
        print(f"publish-wiki: commit failed ({e.splitlines()[-1] if e else 'unknown'})")
        return 1
    code, _, e = run(["git", "push"], cwd=CACHE)
    if code != 0:
        print(f"publish-wiki: push failed ({e.splitlines()[-1] if e else 'unknown'})")
        return 1
    print(f"publish-wiki: pushed {len(changed)} page(s) to the GitHub wiki ({msg})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
