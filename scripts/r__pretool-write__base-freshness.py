#!/usr/bin/env python3
"""r__pretool-write__base-freshness.py: PreToolUse warner for a STALE EDIT BASE.

The failure it exists for (2026-08-10): 19 files were edited on a branch 34
commits behind `main`. Every edit was correct in isolation and the base
was never checked, so the change also silently reverted work that landed after
that base (a whole client entry). A merge conflict caught it. Conflict is luck,
not process, and two prior memories about this class fire at MERGE time, hours
after the damage is done. This moves the gate to the FIRST write.

Behaviour: on the first Write|Edit into a given repo (per session, TTL-bounded),
fetch the remote and count how far HEAD is behind the repo's default branch. If
behind > 0, emit a warning. NEVER blocks: a stale base is often deliberate (a
long-lived branch, a hotfix off a tag), so this is a warner, not a gate. The
model still owns the call.

Cost control: one marker file per (repo, session) with a TTL, checked before any
git call, so the fetch happens once per repo per window and not per edit.

Stdin:  {"tool_name": str, "tool_input": {"file_path": str}, "session_id": str}
Stdout: hookSpecificOutput JSON with additionalContext, or nothing.
Exit:   always 0.

Memory: feedback_check_the_base_before_the_first_edit
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

TTL_SECONDS = 900          # one fetch per repo per 15 min per session
FETCH_TIMEOUT = 8          # never make the operator wait on a slow remote
GIT_TIMEOUT = 5
CACHE_DIR = Path.home() / ".cache" / "octorato" / "base-freshness"


def _git(repo: Path, *args: str, timeout: int = GIT_TIMEOUT) -> str | None:
    """Run git in repo, return stripped stdout or None on any failure."""
    try:
        r = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, timeout=timeout,
        )
    except Exception:
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def _repo_root(file_path: str) -> Path | None:
    p = Path(file_path)
    start = p if p.is_dir() else p.parent
    if not start.exists():
        # File not created yet: walk up to the first existing ancestor.
        for anc in start.parents:
            if anc.exists():
                start = anc
                break
        else:
            return None
    top = _git(start, "rev-parse", "--show-toplevel")
    return Path(top) if top else None


def _default_branch(repo: Path) -> str | None:
    """origin's default branch, with a main/master fallback."""
    head = _git(repo, "symbolic-ref", "refs/remotes/origin/HEAD")
    if head:
        return head.rsplit("/", 1)[-1]
    for cand in ("main", "master"):
        if _git(repo, "rev-parse", "--verify", f"refs/remotes/origin/{cand}") is not None:
            return cand
    return None


def _marker(repo: Path, session: str) -> Path:
    key = hashlib.sha1(f"{repo}|{session}".encode()).hexdigest()[:16]
    return CACHE_DIR / f"{key}.stamp"


def _fresh(marker: Path) -> bool:
    try:
        return (time.time() - marker.stat().st_mtime) < TTL_SECONDS
    except FileNotFoundError:
        return False


def _touch(marker: Path) -> None:
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(str(int(time.time())), encoding="utf-8")
    except Exception:
        pass


def _emit(payload: dict) -> None:
    print(json.dumps({"hookSpecificOutput": payload}))


def check(file_path: str, session: str) -> str | None:
    """Return a warning string, or None when the base is fine / unknowable."""
    repo = _repo_root(file_path)
    if repo is None:
        return None

    marker = _marker(repo, session)
    if _fresh(marker):
        return None
    _touch(marker)                      # claim the window even if the rest fails

    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    default = _default_branch(repo)
    if not default:
        return None
    if branch == default:
        return None                     # already on the production branch

    # Best-effort refresh. On timeout we still compare against whatever ref we hold
    # and say so, because a stale-but-nonzero count is already the signal.
    fetched = _git(repo, "fetch", "origin", default, "--quiet", timeout=FETCH_TIMEOUT) is not None

    behind = _git(repo, "rev-list", "--count", f"HEAD..origin/{default}")
    if not behind or not behind.isdigit() or int(behind) == 0:
        return None

    ahead = _git(repo, "rev-list", "--count", f"origin/{default}..HEAD") or "?"
    qualifier = "" if fetched else " (fetch timed out, count may be low)"
    return (
        f"⚠ BASE RANCIA: {repo.name} está {behind} commits DETRÁS de origin/{default} "
        f"(y {ahead} adelante), rama '{branch}'{qualifier}.\n"
        f"   Editar aquí no falla: mergea bien y de paso REVIERTE en silencio lo que entró "
        f"a {default} después de tu base. Ningún lint ni build lo detecta.\n"
        f"   Si esto toca más de un archivo: "
        f"git worktree add <tmp> -b <rama> origin/{default} y trabaja ahí.\n"
        f"   Si la base vieja es deliberada (rama larga, hotfix sobre tag), ignora esto.\n"
        f"   Memoria: feedback_check_the_base_before_the_first_edit"
    )


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if payload.get("tool_name") not in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        return 0
    fp = (payload.get("tool_input") or {}).get("file_path")
    if not fp:
        return 0
    try:
        warning = check(fp, str(payload.get("session_id") or "nosession"))
    except Exception:
        return 0                        # a warner must never break a write
    if warning:
        _emit({"hookEventName": "PreToolUse", "additionalContext": warning})
    return 0


def _selftest() -> int:
    """Liveness proof: a branch behind its default WARNS, a branch at its default is SILENT.

    Builds a throwaway repo with a real origin, so the check exercises the actual
    git plumbing rather than a mock.
    """
    import tempfile

    ok = True
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        origin, clone = t / "origin.git", t / "clone"
        subprocess.run(["git", "init", "--bare", "-q", str(origin)], check=True)
        subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True)
        env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", **os.environ}
        f = clone / "a.txt"
        f.write_text("1")
        for a in (["add", "a.txt"], ["commit", "-qm", "base"], ["branch", "-M", "main"],
                  ["push", "-q", "-u", "origin", "main"]):
            subprocess.run(["git", "-C", str(clone), *a], check=True, env=env)
        # A bare init leaves HEAD on `master`; without this a fresh clone lands on an
        # unborn branch and its commits fork off nothing. Real remotes have HEAD set.
        subprocess.run(["git", "-C", str(origin), "symbolic-ref", "HEAD",
                        "refs/heads/main"], check=True)

        # BENIGN: on the default branch, at its tip -> silent
        if check(str(f), "s1") is not None:
            print("  X benign fixture warned (on default branch)"); ok = False

        # VIOLATION: branch off, then main moves ahead -> must warn
        subprocess.run(["git", "-C", str(clone), "checkout", "-qb", "feat"], check=True, env=env)
        work = t / "w2"
        subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True)
        (work / "b.txt").write_text("2")
        for a in (["add", "b.txt"], ["commit", "-qm", "newer"], ["push", "-q", "origin", "HEAD:main"]):
            subprocess.run(["git", "-C", str(work), *a], check=True, env=env)

        w = check(str(f), "s2")
        if w is None or "BASE RANCIA" not in w:
            print("  X violation fixture did NOT warn (stale base undetected)"); ok = False
        elif "1 commits DETRÁS" not in w:
            print(f"  X warned but miscounted: {w.splitlines()[0]}"); ok = False

        # TTL: a second call in the same session must stay silent
        if check(str(f), "s2") is not None:
            print("  X TTL not honoured (fetched twice in one window)"); ok = False

    print("  OK base-freshness selftest" if ok else "  FAIL base-freshness selftest")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    sys.exit(main())
