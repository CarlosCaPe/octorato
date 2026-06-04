#!/usr/bin/env python3
"""memory_sync — sync the brain's private memory store to a standalone remote.

THE MORPHOLOGY (why this script is shaped the way it is):
  The brain's memory (operator identity, generic cross-arm lessons, preferences)
  is BRAIN-scoped private data. It must live in a standalone, BRAIN-OWNED repo —
  never inside an arm (that would invert the brain→arm dependency and break arm
  isolation), never in the public octorato repo (that would leak operator PII +
  distilled lessons into forever-public history).

  So this is a two-layer split, exactly like arms-paths.json:
    - PUBLIC (this file): ships the MECHANISM. Knows there's a memory remote slot;
      never knows the occupant. The remote URL is read from a gitignored config.
    - PRIVATE (company/config/memory.json, gitignored): the actual remote + path.

  The canonical memory dir is already gitignored from the public octorato repo, so
  it holds its OWN nested .git pushing to its OWN private remote. The parent never
  descends into a gitignored dir, so the two indexes never touch. Same wall as
  company/.

  No config present? This SOFT-FAILS to local-only (the zero-config adopter default
  — memory still works on this machine, just isn't synced). Adopters opt in by
  creating their own private repo and writing one config file. BYO-backend by design.

Usage:
  memory_sync.py status   # show config + nested-repo state (default)
  memory_sync.py push     # pull --rebase, commit any changes, push
  memory_sync.py pull     # pull --rebase only (e.g. on a fresh machine)

Exit 0 = success or clean soft-fail. Exit 1 = a real git/IO error.
"""
import json
import subprocess
import sys
from pathlib import Path

BRAIN_DIR = Path(__file__).resolve().parent.parent
CONFIG = BRAIN_DIR / "company" / "config" / "memory.json"


def load_config():
    """Return the brain_memory config dict, or None for local-only soft-fail."""
    if not CONFIG.exists():
        return None
    try:
        cfg = json.loads(CONFIG.read_text()).get("brain_memory")
    except (json.JSONDecodeError, OSError) as e:
        print(f"memory_sync: cannot parse {CONFIG.relative_to(BRAIN_DIR)}: {e}", file=sys.stderr)
        return None
    if not cfg or not cfg.get("remote") or not cfg.get("path"):
        return None
    return cfg


def git(repo: Path, *args, check=True):
    """Run a git command against the nested memory repo and return its stdout."""
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip())
    return r.stdout.strip()


def resolve_repo(cfg):
    repo = (BRAIN_DIR / cfg["path"]).resolve()
    if not repo.is_dir():
        raise RuntimeError(f"memory path does not exist: {repo}")
    # Initialise the nested repo on first run (fresh machine / first adopter sync).
    if not (repo / ".git").exists():
        branch = cfg.get("branch", "main")
        git(repo, "init", "-b", branch)
        git(repo, "remote", "add", "origin", cfg["remote"])
        print(f"  initialised nested repo at {repo.relative_to(BRAIN_DIR)} → origin")
    return repo


def cmd_status(cfg):
    if cfg is None:
        print("memory_sync: no config (company/config/memory.json) — LOCAL-ONLY mode.")
        print("  Memory works on this machine; it is not synced. To enable sync, create a")
        print("  PRIVATE repo and point company/config/memory.json at it. Never inside an arm.")
        return 0
    repo = resolve_repo(cfg)
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD", check=False) or "?"
    dirty = git(repo, "status", "--short", check=False)
    print(f"memory_sync: synced store")
    print(f"  remote: {cfg['remote']}")
    print(f"  path:   {cfg['path']}  (branch {branch})")
    print(f"  files:  {len(git(repo, 'ls-files', check=False).splitlines())}")
    print(f"  state:  {'DIRTY — ' + str(len(dirty.splitlines())) + ' change(s)' if dirty else 'clean'}")
    return 0


def cmd_pull(cfg):
    if cfg is None:
        return cmd_status(cfg)
    repo = resolve_repo(cfg)
    branch = cfg.get("branch", "main")
    print(f"memory_sync: pull --rebase origin/{branch} ...")
    print("  " + (git(repo, "pull", "--rebase", "origin", branch) or "(up to date)"))
    return 0


def cmd_push(cfg):
    if cfg is None:
        return cmd_status(cfg)
    repo = resolve_repo(cfg)
    branch = cfg.get("branch", "main")
    if git(repo, "status", "--short", check=False):
        git(repo, "add", "-A")  # nested repo's own index — never the parent's
        git(repo, "-c", "user.name=octorato-brain",
            "-c", "user.email=octorato@local", "commit", "-m", "sync: brain memory")
        print("  committed local memory changes")
    # Commit first, THEN rebase onto the remote so a second machine doesn't
    # fork history (pull --rebase refuses on a dirty tree). Strict: a failed
    # rebase must abort the push, not push a forked tree. Skip when the
    # remote branch doesn't exist yet (first-ever push).
    if git(repo, "ls-remote", "--heads", "origin", branch, check=False):
        git(repo, "pull", "--rebase", "origin", branch)
    git(repo, "push", "-u", "origin", branch)
    print(f"  pushed → {cfg['remote']}")
    return 0


def main():
    cmd = sys.argv[1].lower() if len(sys.argv) > 1 else "status"
    cfg = load_config()
    try:
        if cmd == "status":
            return cmd_status(cfg)
        if cmd == "pull":
            return cmd_pull(cfg)
        if cmd == "push":
            return cmd_push(cfg)
    except RuntimeError as e:
        print(f"memory_sync FAIL: {e}", file=sys.stderr)
        return 1
    print(f"Unknown command: {cmd}\nCommands: status, push, pull")
    return 1


if __name__ == "__main__":
    sys.exit(main())
