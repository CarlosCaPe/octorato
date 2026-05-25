#!/usr/bin/env python3
"""ai_sync.py — single cross-platform runner for the octorato brain.

One logic path for Linux, macOS, and Windows. The bash and PowerShell runners had
diverged into different programs (the bash one even hardcoded private arm codes, which
is why it could never be committed). This is the version-controlled, generic source of
truth; the per-machine ~/.local/bin/{ai-pull,ai-push,sync-ai-docs} (and the .cmd shims
on Windows) are thin thunks that call into here.

Generic by construction:
  - arms come from the gitignored company/config/arms-paths.json (never hardcoded here)
  - the git remote is derived from `git remote get-url origin` (no hardcoded user/repo)
So this file carries no client data and is safe in the public repo.

Verbs:
  pull   [arm…|--status]   git pull + merge hooks + ensure leak-guard + refresh connectome + sync
  push   ["msg"]           guarded stage + commit + push + amend connectome + sync
  sync   [arm…]            project CLAUDE.md -> copilot-instructions.md + .cursorrules
  status                   alias for `pull --status`
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

CLAUDE = Path(__file__).resolve().parent.parent
HOME = Path.home()
ARMS_CFG = CLAUDE / "company" / "config" / "arms-paths.json"
POLICY = CLAUDE / ".githooks" / "push-policy.txt"

# Staged on push — allowlist, never `git add -A`, so personal files never slip in.
BRAIN_PATHS = ["CLAUDE.md", "README.md", "CONTRIBUTING.md", "HEBBIAN_LEARNING.md",
               "LICENSE", "hooks.json", "hooks.schema.json", "skills/", "agents/",
               "scripts/", "hooks/", ".githooks/", "commands/", ".gitignore",
               "assets/", "templates/"]

_USE_COLOR = sys.stdout.isatty() and os.name != "nt"
def _c(code, s): return f"\033[{code}m{s}\033[0m" if _USE_COLOR else s
def info(s): print(_c("0;32", s))
def warn(s): print(_c("1;33", s))
def err(s): print(_c("0;31", s))


def git(*args, check=False, quiet=False):
    """Run a git command in the brain dir; return (returncode, stdout, stderr)."""
    p = subprocess.run(["git", *args], cwd=CLAUDE, capture_output=True, text=True)
    if check and p.returncode != 0 and not quiet:
        err(f"git {' '.join(args)} failed: {p.stderr.strip()}")
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def py() -> str:
    return sys.executable or "python3"


def script_step(rel: str, *args, fatal=False, label="") -> bool:
    """Run a brain python script if present. Returns True on success/absent."""
    path = CLAUDE / rel
    if not path.exists():
        return True
    if label:
        info(label)
    code = subprocess.run([py(), str(path), *args]).returncode
    if code != 0 and fatal:
        return False
    return True


# ── arms config ─────────────────────────────────────────────────────────────

def load_arms() -> dict[str, Path]:
    """name -> resolved repo path. Values are HOME-relative strings or arrays of
    candidate HOME-relative paths (first existing wins). Mirrors the PS1 contract."""
    if not ARMS_CFG.exists():
        return {}
    try:
        raw = json.loads(ARMS_CFG.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        warn(f"⚠ could not parse {ARMS_CFG}")
        return {}
    arms: dict[str, Path] = {}
    for name, val in raw.items():
        candidates = val if isinstance(val, list) else [val]
        chosen = None
        for rel in candidates:
            p = HOME / rel
            if p.exists():
                chosen = p
                break
        arms[name] = chosen or (HOME / candidates[0])
    return arms


# ── self-heal + leak-guard ────────────────────────────────────────────────────

def self_heal_origin():
    code, url, _ = git("remote", "get-url", "origin")
    if code == 0 and "dotclaude" in url:
        new = url.replace("dotclaude", "octorato")
        warn(f"  Rebrand: origin {url} -> {new}")
        git("remote", "set-url", "origin", new)


def ensure_hooks_path():
    """F5: the push-time leak guard only runs if core.hooksPath points at .githooks."""
    code, val, _ = git("config", "--get", "core.hooksPath")
    if val != ".githooks":
        git("config", "core.hooksPath", ".githooks")
        info("  ✓ enabled leak-guard (core.hooksPath=.githooks)")


# ── connectome ──────────────────────────────────────────────────────────────

def connectome_stale() -> bool:
    m = CLAUDE / "neural_map.json"
    if not m.exists():
        return True
    newest = m.stat().st_mtime
    for base, pat in (("skills", "SKILL.md"), ("agents", "*.md")):
        for f in (CLAUDE / base).rglob(pat):
            if f.stat().st_mtime > newest:
                return True
    return False


# ── secret scan (E: fail-closed, independent of core.hooksPath) ───────────────

_POSIX = {"[[:space:]]": r"\s", "[[:alnum:]]": r"[A-Za-z0-9]", "[[:digit:]]": r"\d",
          "[[:alpha:]]": r"[A-Za-z]", "[[:upper:]]": r"[A-Z]", "[[:lower:]]": r"[a-z]"}

def _content_patterns():
    pats, section = [], ""
    if not POLICY.exists():
        return pats
    for line in POLICY.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s in ("[paths]", "[content]"):
            section = s
            continue
        if section == "[content]":
            for k, v in _POSIX.items():
                s = s.replace(k, v)
            try:
                pats.append(re.compile(s))
            except re.error:
                pass
    return pats


def scan_staged_secrets() -> bool:
    """Scan added lines in the staged diff against push-policy [content]. True = clean."""
    pats = _content_patterns()
    if not pats:
        return True
    _, diff, _ = git("diff", "--cached", "--unified=0")
    bad = []
    for line in diff.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        for p in pats:
            if p.search(line[1:]):
                bad.append(p.pattern[:48])
                break
    if bad:
        err("✗ ai-push aborted: staged content matches a secret pattern (fail-closed):")
        for b in sorted(set(bad)):
            err(f"    {b}…")
        return False
    return True


# ── sync ──────────────────────────────────────────────────────────────────────

def sync(names=None) -> int:
    arms = load_arms()
    if not arms:
        warn("  no arms registered (company/config/arms-paths.json absent) — nothing to sync")
        return 0
    targets = names or list(arms)
    print("=== Syncing .claude/CLAUDE.md → copilot-instructions.md + .cursorrules ===")
    synced = skipped = 0
    for name in targets:
        repo = arms.get(name)
        src = repo / ".claude" / "CLAUDE.md" if repo else None
        if not src or not src.exists():
            print(f"  SKIP {name} — no .claude/CLAUDE.md")
            skipped += 1
            continue
        content = src.read_bytes()
        copilot = repo / ".github" / "copilot-instructions.md"
        copilot.parent.mkdir(parents=True, exist_ok=True)
        copilot.write_bytes(content)
        (repo / ".cursorrules").write_bytes(content)
        info(f"  ✓ {name}: CLAUDE.md → copilot + cursor")
        synced += 1
    print(f"\nDone. Synced: {synced} | Skipped: {skipped}")
    return 0


# ── pull ────────────────────────────────────────────────────────────────────

def pull(args) -> int:
    if not (CLAUDE / ".git").is_dir():
        warn("⚠ ~/.claude is not a git repo — skipping pull")
    else:
        self_heal_origin()
        if args.status:
            git("fetch", "--quiet")
            _, local, _ = git("rev-parse", "HEAD")
            code, upstream, _ = git("rev-parse", "@{u}")
            if code != 0:
                warn("⚠ no upstream configured")
            elif local == upstream:
                info("✓ Up to date")
            else:
                warn("⚠ Changes available — run 'ai-pull'")
                print(git("--no-pager", "log", "--oneline", "HEAD..@{u}")[1])
            return 0
        _, pre, _ = git("rev-parse", "HEAD")
        print("=== Pulling ~/.claude/ ===")
        code, out, e = git("pull")
        if code != 0:
            err(f"✗ Pull failed — aborting (tree left untouched): {e or out}")
            return 1  # F7: never continue a sync against a half-pulled tree
        _, post, _ = git("rev-parse", "HEAD")
        if pre != post:
            info("✓ Pulled new changes:")
            print(git("--no-pager", "log", "--oneline", f"{pre}..{post}")[1])
        else:
            info("✓ Already up to date")

    script_step("scripts/merge-hooks.py", label="=== Merging shared hooks ===")
    ensure_hooks_path()

    if connectome_stale():  # F9: a pull-only machine otherwise never refreshes the graph
        script_step("scripts/generate_neural_map.py", label="🧠 Connectome stale — regenerating")

    print()
    sync(args.arms or None)

    script_step("scripts/brain_doctor.py", label="\n=== Brain doctor ===")
    return 0


# ── push ──────────────────────────────────────────────────────────────────────

def push(args) -> int:
    # Anything to do?
    dirty = git("diff", "--quiet")[0] or git("diff", "--cached", "--quiet")[0] \
        or bool(git("ls-files", "--others", "--exclude-standard")[1])
    if not dirty:
        info("✓ No changes in ~/.claude/")
        sync(None)
        return 0

    for p in BRAIN_PATHS:
        if (CLAUDE / p).exists():
            git("add", p)
    # stage tracked deletions
    _, dels, _ = git("diff", "--cached", "--name-only", "--diff-filter=D")
    # (already staged by add of the dir; explicit re-add not needed)

    msg = " ".join(args.message) if args.message else None
    if not msg:
        _, names, _ = git("diff", "--cached", "--name-only")
        msg = "update: " + ", ".join(names.splitlines()[:5])

    # Generic-rule guard (client/person tokens)
    if (CLAUDE / "scripts" / "check-generic.py").exists():
        if subprocess.run([py(), str(CLAUDE / "scripts" / "check-generic.py"),
                           "--message", msg, "--staged", "--quiet"]).returncode != 0:
            err("⚠ ai-push aborted: staged files / message violate the brain-stays-generic rule.")
            return 1

    # Hooks drift guard (FATAL) — the recurring "brain never sticks" bug
    if not script_step("scripts/check-hooks-drift.py", fatal=True):
        err("⚠ ai-push aborted: settings.json hooks diverged from hooks.json.")
        err("   Run merge-hooks.py (discard) or check-hooks-drift.py --adopt (publish), then retry.")
        return 1

    # In-script secret scan (E) — fail-closed even if core.hooksPath isn't set / --no-verify
    if not scan_staged_secrets():
        return 1

    # Stats-drift (advisory)
    script_step("scripts/check-stats-drift.py")

    git("commit", "-m", msg, check=True)
    info(f"✓ Committed: {msg}")

    code, _, e = git("push", "origin", "HEAD")
    if code != 0:
        warn(f"⚠ Push failed: {e}")
        return 1
    info("✓ Pushed to remote")

    # Regenerate connectome and fold into the just-pushed commit
    if (CLAUDE / "scripts" / "generate_neural_map.py").exists():
        info("🧠 Regenerating connectome...")
        subprocess.run([py(), str(CLAUDE / "scripts" / "generate_neural_map.py")],
                       stdout=subprocess.DEVNULL)
        if git("diff", "--quiet", "--", "neural_map.json")[0] != 0:
            git("add", "neural_map.json")
            git("commit", "--amend", "--no-edit")
            git("push", "--force-with-lease", "origin", "HEAD")
            info("✓ Connectome updated and amended")

    print()
    sync(None)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="octorato brain sync (cross-platform)")
    sub = ap.add_subparsers(dest="verb", required=True)

    p_pull = sub.add_parser("pull")
    p_pull.add_argument("arms", nargs="*")
    p_pull.add_argument("--status", action="store_true")

    p_push = sub.add_parser("push")
    p_push.add_argument("message", nargs="*")

    p_sync = sub.add_parser("sync")
    p_sync.add_argument("arms", nargs="*")

    sub.add_parser("status")

    args = ap.parse_args()
    if args.verb == "pull":
        return pull(args)
    if args.verb == "push":
        return push(args)
    if args.verb == "sync":
        return sync(args.arms or None)
    if args.verb == "status":
        ns = argparse.Namespace(arms=[], status=True)
        return pull(ns)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
