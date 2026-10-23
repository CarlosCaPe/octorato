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

  More than one memory dir? List the extra ones in `brain_memory.stores` as
  {path, branch}. Each becomes its own nested repo on its own branch of the same
  remote; nothing is copied between dirs.

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
# Force UTF-8 on stdout/stderr so the ✓ / ✗ / em-dash glyphs in reports
# survive on Windows shells defaulting to cp1252. Without this, a script
# can do its work correctly and still crash with UnicodeEncodeError when
# printing success. Applied repo-wide by _apply-utf8-reconfigure.py.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


BRAIN_DIR = Path(__file__).resolve().parent.parent
CONFIG = BRAIN_DIR / "company" / "config" / "memory.json"


def load_config():
    """Return the brain_memory config dict, or None for local-only soft-fail."""
    if not CONFIG.exists():
        return None
    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8")).get("brain_memory")
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


def list_stores(cfg):
    """Expand the config into one store per nested repo.

    The primary store is brain_memory itself. Optional `brain_memory.stores`
    entries ({path, branch}, optional remote) add more memory dirs. Each one is
    its OWN nested .git on its OWN branch, of the same private remote unless the
    entry names another. Nothing is copied between dirs, so deletions and edits
    from other machines stay git's job. Store dirs may not nest inside each
    other (the outer repo would swallow the inner one). Remotes are compared as
    written, so spell one remote the same way in every entry.
    """
    stores = [{"path": cfg["path"], "branch": cfg.get("branch", "main"), "remote": cfg["remote"]}]
    for extra in cfg.get("stores") or []:
        if not isinstance(extra, dict) or not extra.get("path") or not extra.get("branch"):
            raise RuntimeError("brain_memory.stores: every entry needs a path and a branch")
        store = {"path": extra["path"], "branch": extra["branch"],
                 "remote": extra.get("remote") or cfg["remote"]}
        new = (BRAIN_DIR / store["path"]).resolve()
        for s in stores:
            old = (BRAIN_DIR / s["path"]).resolve()
            if old == new:
                raise RuntimeError(f"brain_memory.stores: path {store['path']} is listed twice")
            if old in new.parents or new in old.parents:
                raise RuntimeError(f"brain_memory.stores: {store['path']} and {s['path']} nest inside each other")
            if s["remote"] == store["remote"] and s["branch"] == store["branch"]:
                raise RuntimeError(f"brain_memory.stores: branch {store['branch']} is used twice on one remote")
        stores.append(store)
    return stores


def resolve_repo(store):
    repo = (BRAIN_DIR / store["path"]).resolve()
    if not repo.is_dir():
        raise RuntimeError(f"memory path does not exist: {repo}")
    # Initialise the nested repo on first run (fresh machine / first adopter sync).
    if not (repo / ".git").exists():
        git(repo, "init", "-b", store["branch"])
        git(repo, "remote", "add", "origin", store["remote"])
        print(f"  initialised nested repo at {store['path']} → origin")
    # An existing .git keeps whatever origin it was cloned or edited with; refuse
    # to sync it unless that origin is the configured remote (never the wrong or
    # the public repo).
    origin = git(repo, "remote", "get-url", "origin", check=False)
    if origin != store["remote"]:
        raise RuntimeError(f"nested repo origin does not match the configured remote for {store['path']}; "
                           f"fix it with `git -C \"{repo}\" remote set-url origin <configured remote>`")
    return repo


def check_branch(repo, branch):
    """Refuse to sync a nested repo that sits on another branch: a pull would
    rebase the wrong branch, a push would fail on a missing refspec."""
    head = git(repo, "symbolic-ref", "--short", "HEAD", check=False)
    if head != branch:
        raise RuntimeError(f"nested repo is on branch {head or '?'}, config says {branch}; "
                           f"run `git -C \"{repo}\" checkout -B {branch}` or fix the config")


def remote_has_branch(repo, branch):
    """True/False for the remote branch; an unreachable remote raises instead of
    reading as 'no branch yet' (exit 2 is git's 'no matching ref')."""
    r = subprocess.run(["git", "-C", str(repo), "ls-remote", "--exit-code", "--heads",
                        "origin", f"refs/heads/{branch}"], capture_output=True, text=True)
    if r.returncode == 0:
        return True
    if r.returncode == 2:
        return False
    raise RuntimeError((r.stderr or r.stdout).strip() or f"git ls-remote exited {r.returncode}")


def status_store(store):
    repo = resolve_repo(store)
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD", check=False) or "?"
    dirty = git(repo, "status", "--short", check=False)
    print(f"  path:  {store['path']}  (branch {branch})")
    print(f"  files:  {len(git(repo, 'ls-files', check=False).splitlines())}")
    print(f"  state:  {'DIRTY — ' + str(len(dirty.splitlines())) + ' change(s)' if dirty else 'clean'}")


def cmd_status(cfg):
    if cfg is None:
        print("memory_sync: no config (company/config/memory.json) — LOCAL-ONLY mode.")
        print("  Memory works on this machine; it is not synced. To enable sync, create a")
        print("  PRIVATE repo and point company/config/memory.json at it. Never inside an arm.")
        return 0
    print(f"memory_sync: {len(list_stores(cfg))} synced store(s)")
    return each_store(cfg, status_store)


def each_store(cfg, action):
    """Run action on every store. One store failing does not skip the others;
    the run still exits 1 so the failure is never silent."""
    failed = 0
    for store in list_stores(cfg):
        try:
            action(store)
        except RuntimeError as e:
            # git's own stderr names the remote; never echo the URL.
            msg = str(e).replace(store["remote"], "<remote>")
            print(f"memory_sync FAIL [{store['path']}]: {msg}", file=sys.stderr)
            failed += 1
    return 1 if failed else 0


def pull_store(store):
    repo = resolve_repo(store)
    branch = store["branch"]
    print(f"memory_sync: pull --rebase origin/{branch} ({store['path']}) ...")
    check_branch(repo, branch)
    if not remote_has_branch(repo, branch):
        print("  (no remote branch yet; the first push creates it)")
        return
    print("  " + (git(repo, "pull", "--rebase", "origin", branch) or "(up to date)"))


def push_store(store):
    repo = resolve_repo(store)
    branch = store["branch"]
    print(f"memory_sync: push {store['path']} → origin/{branch}")
    check_branch(repo, branch)
    if git(repo, "status", "--short", check=False):
        git(repo, "add", "-A")  # nested repo's own index — never the parent's
        git(repo, "-c", "user.name=octorato-brain",
            "-c", "user.email=octorato@local", "commit", "-m", "sync: brain memory")
        print("  committed local memory changes")
    if not git(repo, "rev-parse", "--verify", "-q", "HEAD", check=False):
        print("  (empty store, nothing to push yet)")
        return
    # Commit first, THEN rebase onto the remote so a second machine doesn't
    # fork history (pull --rebase refuses on a dirty tree). Strict: a failed
    # rebase must abort the push, not push a forked tree. Skip when the
    # remote branch doesn't exist yet (first-ever push).
    if remote_has_branch(repo, branch):
        git(repo, "pull", "--rebase", "origin", branch)
    git(repo, "push", "-u", "origin", branch)
    print(f"  pushed → origin/{branch}")


def cmd_pull(cfg):
    if cfg is None:
        return cmd_status(cfg)
    return each_store(cfg, pull_store)


def cmd_push(cfg):
    if cfg is None:
        return cmd_status(cfg)
    return each_store(cfg, push_store)


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
