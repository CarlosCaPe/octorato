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
  push   ["msg"]           guarded stage + commit + push + amend connectome + sync.
                           If HEAD is on a PR-protected branch (master/main with
                           branch protection requiring PR), auto-creates a feature
                           branch, opens a PR via gh, waits for required checks,
                           squash-merges, and returns to the protected branch.
  sync   [arm…]            project CLAUDE.md -> copilot-instructions.md + .cursorrules
  status                   alias for `pull --status`
  cycle  ["msg"]           ai-sync: integrate (pull --rebase --autostash) THEN publish
                           (push), retrying the loop when a sibling machine pushes
                           mid-flight. The canonical one-command reconcile for running
                           one brain across many machines — no more pull/push dance.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Windows consoles default to cp1252, which crashes on the Unicode glyphs this
# script uses for status output (→, ✓, ⚠, ✗, ─, 🧠, em-dash, ellipsis). Force
# stdout/stderr to UTF-8 with replacement so the script runs cleanly on
# Windows without requiring users to set PYTHONIOENCODING themselves.
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

CLAUDE = Path(__file__).resolve().parent.parent
HOME = Path.home()
ARMS_CFG = CLAUDE / "company" / "config" / "arms-paths.json"
POLICY = CLAUDE / ".githooks" / "push-policy.txt"

# Staged on push — allowlist, never `git add -A`, so personal files never slip in.
# Top-level governance docs (CHANGELOG, SUPPORT, etc.) must be listed explicitly;
# otherwise `ai-push` silently drops them with no warning (lesson 2026-05-28).
BRAIN_PATHS = ["CLAUDE.md", "README.md", "FAQ.md", "CONTRIBUTING.md", "HEBBIAN_LEARNING.md",
               "CODE_OF_CONDUCT.md", "SECURITY.md", "SUPPORT.md", "CHANGELOG.md",
               "ROADMAP.md", "SHOWCASE.md", "WHITEPAPER.md", "LICENSE",
               "budgets.yaml.example", "requirements.txt",
               "hooks.json", "hooks.schema.json", "skills/", "agents/",
               "scripts/", "hooks/", ".githooks/", "commands/", ".gitignore",
               "assets/", "templates/", ".github/", "connectome/", "docs/",
               "registry/"]

_USE_COLOR = sys.stdout.isatty() and os.name != "nt"
def _c(code, s): return f"\033[{code}m{s}\033[0m" if _USE_COLOR else s
def info(s): print(_c("0;32", s))
def warn(s): print(_c("1;33", s))
def err(s): print(_c("0;31", s))


def git(*args, check=False, quiet=False):
    """Run a git command in the brain dir; return (returncode, stdout, stderr)."""
    # encoding+errors pinned: on Windows, text=True decodes with cp1252 and git
    # diff/log output carries arbitrary UTF-8 (commit bodies, non-latin file
    # content), which crashed the sync mid-run twice. utf-8/replace is lossless
    # for our decisions (returncode + token matching) and never raises.
    p = subprocess.run(["git", *args], cwd=CLAUDE, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
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
    if not _is_repo():
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
    script_step("scripts/merge-hooks-cursor.py", label="=== Projecting hooks → Cursor ===")
    ensure_hooks_path()

    if connectome_stale():  # F9: a pull-only machine otherwise never refreshes the graph
        script_step("scripts/generate_neural_map.py", label="🧠 Connectome stale — regenerating")

    print()
    sync(args.arms or None)

    script_step("scripts/brain_doctor.py", label="\n=== Brain doctor ===")
    return 0


# ── push ──────────────────────────────────────────────────────────────────────

# ─── PR-flow helpers ──────────────────────────────────────────────────────────
# Octorato master is PR-protected (enforce_admins=true, required_pull_request_reviews).
# When ai-push runs from HEAD=master/main, route through gh CLI: branch → push →
# PR → wait checks → squash-merge → return. Falls back gracefully if gh is missing.

def _owner_repo() -> str:
    """Parse `owner/repo` from the origin URL. Empty string if not a github remote."""
    _, url, _ = git("remote", "get-url", "origin")
    m = re.search(r'github\.com[:/]([^/]+)/([^/.\s]+?)(?:\.git)?/?$', url)
    return f"{m.group(1)}/{m.group(2)}" if m else ""


def _is_pr_required(branch: str) -> bool:
    """True if `branch` has protection requiring a PR (via gh REST)."""
    if not shutil.which("gh"):
        return False
    repo = _owner_repo()
    if not repo:
        return False
    p = subprocess.run(
        ["gh", "api", f"repos/{repo}/branches/{branch}/protection",
         "--jq", ".required_pull_request_reviews != null"],
        cwd=CLAUDE, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    return p.returncode == 0 and p.stdout.strip() == "true"


def _branch_slug(msg: str) -> str:
    """First line of commit msg → kebab slug + short timestamp, max 40+6 chars."""
    first = msg.splitlines()[0].lower()
    first = re.sub(r'^[a-z]+(\([^)]+\))?:\s*', '', first)  # strip conv-commit prefix
    slug = re.sub(r'[^a-z0-9]+', '-', first)[:40].strip('-') or "update"
    return f"{slug}-{int(time.time()) % 100000}"


def _push_via_pr(branch: str, target: str, msg: str) -> int:
    """Push current branch → open PR → watch checks → squash-merge → return to target.

    Invariant: the working tree ALWAYS ends on `target`, success or failure.
    Leaving it parked on the feature branch broke a co-tenant session once
    (dogfooded 2026-07-07); every exit path below checks out target first.
    """
    def _bail(rc_: int) -> int:
        git("checkout", target)
        return rc_

    code, _, e = git("push", "-u", "origin", branch)
    if code != 0:
        warn(f"⚠ Push of {branch} failed: {e}")
        return _bail(1)
    info(f"✓ Pushed branch {branch}")

    if not shutil.which("gh"):
        warn(f"⚠ gh CLI not found — open the PR manually:")
        warn(f"   https://github.com/{_owner_repo()}/pull/new/{branch}")
        return _bail(0)

    title = msg.splitlines()[0][:72]
    body = (f"Auto-opened by `ai-push` ({target} is PR-protected).\n\n"
            f"```\n{msg}\n```\n\n"
            "🤖 Generated with [Claude Code](https://claude.com/claude-code)")
    rc = subprocess.run(
        ["gh", "pr", "create", "--base", target, "--head", branch,
         "--title", title, "--body", body],
        cwd=CLAUDE,
    ).returncode
    if rc != 0:
        err("⚠ gh pr create failed — branch is pushed; open PR manually.")
        return _bail(1)
    info("✓ PR opened")

    # GH Actions takes ~5-15s to register check runs after pr create.
    # `gh pr checks --watch --required` exits immediately with "no checks
    # reported" if invoked too early (race seen during dogfood). Sleep first,
    # then watch with an explicit poll interval. Retry once on early exit
    # if no check actually failed (still racing).
    info("⏳ Waiting 15s for checks to register...")
    time.sleep(15)
    info("⏳ Watching required checks (timeout 10 min)...")
    watch_start = time.time()
    rc = subprocess.run(
        ["gh", "pr", "checks", "--watch", "--required", "--interval", "10"],
        cwd=CLAUDE, timeout=600,
    ).returncode
    if rc != 0 and (time.time() - watch_start) < 30:
        # Early exit — likely race. Confirm no actual failure before retrying.
        p = subprocess.run(
            ["gh", "pr", "view", "--json", "statusCheckRollup",
             "--jq", "[.statusCheckRollup[].conclusion] | unique | join(\",\")"],
            cwd=CLAUDE, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        if "FAILURE" not in p.stdout and "CANCELLED" not in p.stdout:
            info("⏳ Early exit detected — retrying watch...")
            time.sleep(10)
            rc = subprocess.run(
                ["gh", "pr", "checks", "--watch", "--required", "--interval", "10"],
                cwd=CLAUDE, timeout=600,
            ).returncode
    if rc != 0:
        warn("⚠ Required checks failed — PR left open for manual review.")
        return _bail(1)
    info("✓ Required checks passed")

    rc = subprocess.run(
        ["gh", "pr", "merge", "--squash", "--delete-branch"],
        cwd=CLAUDE,
    ).returncode
    if rc != 0:
        warn("⚠ Squash-merge failed — PR left open.")
        return _bail(1)
    info("✓ Merged + branch deleted")

    rc_co, _, _ = git("checkout", target)
    rc_pl, _, e = git("pull", "--ff-only")
    if rc_co != 0 or rc_pl != 0:
        warn(f"⚠ {target} sync failed post-merge; skipping semver tag: {e}")
        return 1
    info(f"✓ Local {target} synced")
    # Now on {target} at the squash-merged commit — the correct point to move
    # the semver label for the PR flow (mirror of the direct-push call site).
    # The gh-missing early return above never reaches here, so we never tag an
    # un-merged commit.
    script_step("scripts/brain-version-bump.py", "--apply", "--push",
                label="🏷  Moving semver label...")
    return 0


# ── co-tenancy guard (reuses the dimension-awareness-hook / octo-dim registry) ──
SESSIONS_REGISTRY = CLAUDE / "connectome" / "sessions.json"
_DIM_TTL = 900          # seconds; the "live" window dimension-awareness-hook displays
_DIM_FUTURE_SKEW = 120  # heartbeat this far ahead of now → clock skew → not live


def _cotenant_window() -> int:
    """Safety window (seconds) for the co-tenancy ABORT decision.

    Wider than the 900s live-display TTL on purpose: a guard must err conservative.
    A neighbor session idle but not yet aged out is probably still holding the tree
    (its branch checked out, its work uncommitted) even though its heartbeat went
    stale past the live TTL. This closes the real gap from 2026-06-03 where a
    co-tenant at 1122s age slipped under the 900s window and ai-push would not have
    aborted. Tunable via OCTO_COTENANCY_GRACE; never narrower than the live TTL.
    """
    try:
        return max(int(os.environ.get("OCTO_COTENANCY_GRACE", "1800")), _DIM_TTL)
    except (ValueError, TypeError):
        return 1800


def _is_repo() -> bool:
    """Hay repo aqui, sea checkout principal o worktree enlazado.

    `(CLAUDE / ".git").is_dir()` decia que NO en un worktree, porque ahi `.git`
    es un ARCHIVO que apunta al directorio comun. O sea que ai-sync se negaba a
    correr justo en el aislamiento que el mismo recomienda: su mensaje de
    co-tenencia manda a forkear un worktree y despues no funciona dentro de uno.
    """
    rc, _out, _e = git("rev-parse", "--is-inside-work-tree", quiet=True)
    return rc == 0


def _this_tree() -> str:
    """El arbol de trabajo en el que ESTE proceso commitearia."""
    rc, out, _e = git("rev-parse", "--show-toplevel", quiet=True)
    return out.strip() if rc == 0 and out.strip() else str(CLAUDE)


def _same_path(a, b) -> bool:
    try:
        return os.path.realpath(str(a)) == os.path.realpath(str(b))
    except OSError:
        return str(a) == str(b)


def _entry_tree(entry: dict) -> str:
    """Arbol que declara una entrada del registro.

    Sin `worktree` se asume el checkout principal, que es donde vive una sesion
    que nunca se forkeo. Conservador a proposito: una entrada vieja cuenta como
    co-inquilina del arbol por omision en vez de desaparecer del guardia.
    """
    return str((entry or {}).get("worktree") or CLAUDE)


def _cotenants_on_tree(ttl: int, tree: str) -> list:
    """Sesiones vivas que trabajan en ESTE MISMO arbol, en ESTA MISMA maquina.

    El peligro nunca fue "hay dos sesiones", fue "hay dos escritores en un
    arbol": un `git add` amplio de una se traga el trabajo sin commitear de la
    otra. Contar sesiones castigaba justo a quien ya se habia aislado, y el
    mensaje le recomendaba forkear un worktree que ya tenia. Aqui se cuenta por
    arbol, asi que dos dimensiones con su propio checkout pasan y dos sesiones
    en el mismo checkout abortan.

    Tambien se filtra por host. El registro viaja en el repo del cerebro, o sea
    que trae sesiones de OTRAS maquinas; sus rutas se parecen a las de aqui y no
    son el mismo disco. El comentario viejo afirmaba que eso "nunca dispara
    entre maquinas" y el codigo no lo comprobaba.

    FAIL-OPEN: cualquier error de lectura devuelve [] y el guardia no bloquea,
    misma disciplina que el hook que refleja.
    Devuelve [(session_id, branch, age_seconds), ...].
    """
    try:
        with SESSIONS_REGISTRY.open(encoding="utf-8") as fh:
            data = json.load(fh)
        sessions = data.get("sessions", {}) if isinstance(data, dict) else {}
        now = datetime.now(timezone.utc)
        host = socket.gethostname()
        seen = []
        for sid, entry in sessions.items():
            entry = entry or {}
            if (entry.get("host") or host) != host:
                continue                      # otra maquina, otro disco
            if not _same_path(_entry_tree(entry), tree):
                continue                      # su propio checkout, no me estorba
            hb = entry.get("heartbeat", "")
            if not hb:
                continue
            try:
                hb_dt = datetime.fromisoformat(hb)
            except (ValueError, TypeError):
                continue
            if hb_dt.tzinfo is None:
                hb_dt = hb_dt.replace(tzinfo=timezone.utc)
            delta = (now - hb_dt).total_seconds()
            if -_DIM_FUTURE_SKEW <= delta <= ttl:
                seen.append((sid, entry.get("branch") or "no-branch", int(max(delta, 0))))
        return seen
    except Exception:
        return []  # fail-open: unreadable registry → no guard, never brick ai-push


def push(args) -> int:
    # Co-tenancy guard: never commit in a tree another session shares. ai-push stages
    # whole BRAIN_PATHS dirs and then commits the entire index, so a second writer's
    # uncommitted work gets swallowed into the wrong commit (CLAUDE.md Core Principle
    # #7, skills/session-isolation). A conservative grace window keeps a recently idle
    # neighbor counted. Override only when you own the tree.
    window = _cotenant_window()
    tree = _this_tree()
    seen = _cotenants_on_tree(window, tree)
    if len(seen) > 1 and os.environ.get("OCTO_ALLOW_SHARED") != "1":
        err(f"⚠ ai-push aborted: {len(seen)} sessions live in the SAME working tree "
            f"(co-tenancy window {window}s):")
        err(f"     tree: {tree}")
        for sid, branch, age in seen:
            err(f"     {sid[:20]}… ({branch}, last seen {age}s ago)")
        err("   Two writers on one tree corrupt each other's commits.")
        err("   Isolate first: python3 scripts/octo-dim.py worktree-init --session-id <id>")
        err("   Override (only if you own the whole tree): OCTO_ALLOW_SHARED=1 ai-push \"msg\"")
        return 1

    # Anything to do?
    dirty = git("diff", "--quiet")[0] or git("diff", "--cached", "--quiet")[0] \
        or bool(git("ls-files", "--others", "--exclude-standard")[1])
    if not dirty:
        info("✓ No changes in ~/.claude/")
        sync(None)
        return 0

    # Compose message early so we can derive a branch slug if needed
    # (staging happens below; message uses staged names as fallback later if empty).
    raw_msg = " ".join(args.message) if args.message else None

    # Detect PR-protected HEAD before staging, so we can branch-off cleanly.
    _, current_branch, _ = git("rev-parse", "--abbrev-ref", "HEAD")
    use_pr_flow = (current_branch in ("master", "main")
                   and _is_pr_required(current_branch))
    target_branch = current_branch
    if use_pr_flow:
        # Provisional slug from msg (or "update" fallback); stage+commit follow.
        slug = _branch_slug(raw_msg or "update")
        feat_branch = f"auto/{slug}"
        info(f"🛡  {current_branch} is PR-protected — auto-branching to {feat_branch}")
        rc, _, e = git("checkout", "-b", feat_branch)
        if rc != 0:
            err(f"⚠ checkout -b {feat_branch} failed: {e}")
            return 1

    # Regenerate capability manifest so docs/CAPABILITIES.md is current before staging.
    # Must run BEFORE the git add loop so the updated file is captured in this commit.
    # docs/ is in BRAIN_PATHS (line ~68), so the regen output is always staged.
    script_step("scripts/capability_manifest.py", label="📖 Regenerating capability manifest")

    for p in BRAIN_PATHS:
        if (CLAUDE / p).exists():
            git("add", p)
    # stage tracked deletions
    # (already staged by add of the dir; explicit re-add not needed)

    # Empty-cycle guard: `dirty` above also trips on untracked noise OUTSIDE
    # BRAIN_PATHS (e.g. a runtime daemon.status.json), in which case nothing got
    # staged. Without this guard the flow used to create+push an EMPTY auto
    # branch, fail `gh pr create` ("No commits between..."), and leave the
    # shared working tree parked off-master (dogfooded 2026-07-07).
    if git("diff", "--cached", "--quiet")[0] == 0:
        info("✓ Nothing staged from BRAIN_PATHS — nothing to publish")
        if use_pr_flow:
            git("checkout", target_branch)
            git("branch", "-D", feat_branch)
        sync(None)
        return 0

    msg = raw_msg
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

    rc_commit, _, _ = git("commit", "-m", msg, check=True)
    if rc_commit != 0:
        # git() with check=True only REPORTS the failure; enforce it here or the
        # flow pushes a branch with no commit on it.
        if use_pr_flow:
            git("checkout", target_branch)
            git("branch", "-D", feat_branch)
        err("⚠ ai-push aborted: commit failed.")
        return 1
    info(f"✓ Committed: {msg}")

    if use_pr_flow:
        rc = _push_via_pr(git("rev-parse", "--abbrev-ref", "HEAD")[1], target_branch, msg)
        if rc != 0:
            return rc
    else:
        code, _, e = git("push", "origin", "HEAD")
        if code != 0:
            warn(f"⚠ Push failed: {e}")
            return 1
        info("✓ Pushed to remote")
        # Move the semver label by change-class (advisory, never fatal).
        # Direct-push path only: in the PR flow HEAD is the feature branch, so
        # tagging here would label an un-merged commit. The bump size (patch/
        # minor/major) is derived from the conventional-commit types since the
        # last tag — see scripts/brain-version-bump.py.
        script_step("scripts/brain-version-bump.py", "--apply", "--push",
                    label="🏷  Moving semver label...")

    # Publish docs/wiki to the GitHub wiki mirror (best-effort). The wiki is a
    # separate repo no gate protects; a wiki failure must NEVER fail ai-push,
    # so this warns in one line and moves on. Master/main only: publishing from
    # a feature branch (or with a PR still open) would mirror unreviewed content
    # to the public wiki, skirting the review gate.
    _, wiki_branch, _ = git("rev-parse", "--abbrev-ref", "HEAD")
    if wiki_branch in ("master", "main") and (CLAUDE / "scripts" / "publish-wiki.py").exists():
        info("📖 Publishing docs/wiki to the GitHub wiki...")
        if subprocess.run([py(), str(CLAUDE / "scripts" / "publish-wiki.py"),
                           "--push"]).returncode != 0:
            warn("⚠ wiki publish failed (brain push unaffected); retry with: python3 scripts/publish-wiki.py --push")

    # Refresh the local connectome. neural_map.json is gitignored (per-machine,
    # regenerated on demand) — so we rebuild it locally for this machine's query/
    # heartbeat, but never add/commit/push it. No force-push of the branch, ever.
    if (CLAUDE / "scripts" / "generate_neural_map.py").exists():
        info("🧠 Refreshing local connectome...")
        subprocess.run([py(), str(CLAUDE / "scripts" / "generate_neural_map.py")],
                       stdout=subprocess.DEVNULL)

    print()
    sync(None)
    return 0


# ── cycle (ai-sync): canonical reconcile = integrate-then-publish, race-safe ────

def _unpushed() -> bool:
    """True if local HEAD has commits its upstream doesn't yet have."""
    code, out, _ = git("rev-list", "--count", "@{u}..HEAD")
    return code == 0 and out.strip().isdigit() and int(out.strip()) > 0


def cycle(args) -> int:
    """ai-sync: one canonical reconcile of ~/.claude — integrate, then publish.

    The pull/push dance exists because `push` does a bare `git push` that a sibling
    machine's earlier push rejects (non-fast-forward). `cycle` removes the dance: it
    pulls --rebase FIRST (replaying local work on the remote tip, so the push is
    always a fast-forward), then publishes, and RETRIES the loop if another machine
    pushed mid-flight. Built for running one brain across many machines, where every
    machine both learns and shares, so divergence is the norm, not the exception.

    Per attempt:
      pull --rebase --autostash   integrate remote, keep local (committed + uncommitted)
      push(args)                  commit dirty + publish (direct or PR flow), all guards
      still-unpushed?             a race or the pre-committed-skip case → re-integrate, retry
    """
    if not _is_repo():
        err("✗ ~/.claude is not a git repo — cannot sync")
        return 1

    self_heal_origin()
    ensure_hooks_path()

    # Co-tenancy guard (mirrors push): never reconcile a tree a sibling SESSION on
    # THIS machine shares. Different machines have different trees, so this never
    # fires across separate machines — only across two live sessions on one of them.
    window = _cotenant_window()
    tree = _this_tree()
    seen = _cotenants_on_tree(window, tree)
    if len(seen) > 1 and os.environ.get("OCTO_ALLOW_SHARED") != "1":
        err(f"⚠ ai-sync aborted: {len(seen)} sessions live in the SAME working tree "
            f"(co-tenancy window {window}s):")
        err(f"     tree: {tree}")
        for sid, branch, age in seen:
            err(f"     {sid[:20]}… ({branch}, last seen {age}s ago)")
        err("   Two writers on one tree corrupt each other's commits.")
        err("   Isolate first: python3 scripts/octo-dim.py worktree-init --session-id <id>")
        err("   Override (only if you own the whole tree): OCTO_ALLOW_SHARED=1 ai-sync")
        return 1

    attempts = 3
    for attempt in range(1, attempts + 1):
        print(f"━━ ai-sync: reconcile ~/.claude (attempt {attempt}/{attempts}) ━━")

        # 1. INTEGRATE — bring the remote in and replay local work on top.
        #    --autostash protects uncommitted edits across the rebase; --rebase keeps
        #    history linear so the publish below is a clean fast-forward.
        code, out, e = git("pull", "--rebase", "--autostash")
        # --autostash has TWO failure modes with DIFFERENT exit codes:
        #   (a) the rebase itself conflicts (a local commit vs the remote on the same
        #       lines): exit != 0, a rebase is in progress, `rebase --abort` recovers.
        #   (b) the rebase lands but RE-APPLYING the autostash conflicts (an UNCOMMITTED
        #       edit collides with what we pulled): git exits 0, yet leaves conflict
        #       markers in the file and the work parked in a stash.
        # Mode (b) is the headline case (local edits + a sibling touched the same lines)
        # and is invisible in the exit code, so check for unmerged paths explicitly. If
        # we missed it, push() would stage and PUBLISH the conflict markers to the public
        # brain and the operator's edits would be silently abandoned in a stash.
        _, unmerged, _ = git("ls-files", "--unmerged")
        if code != 0 or unmerged.strip():
            if code != 0:
                git("rebase", "--abort")        # mode (a): undo the half-rebase
                err("✗ ai-sync stopped: two machines changed the same lines.")
                err("   Resolve by hand, then re-run ai-sync.")
            else:
                git("reset", "--hard", "HEAD")  # mode (b): clear the markers; the
                                                # operator's edits stay safe in the stash
                err("✗ ai-sync stopped: your local edits touch the same lines the remote changed.")
                err("   Your uncommitted work is SAFE in the stash. Recover it with:")
                err("      git stash pop      # then resolve the markers and re-run ai-sync")
            tail = (e or out).strip().splitlines()
            if tail:
                err(f"   {tail[-1]}")
            return 1

        # 2. PUBLISH — commit any local changes and push (direct, or via the PR flow
        #    for a protected master). push() carries every guard: generic, secrets,
        #    hooks-drift, semver, co-tenancy, connectome refresh, arm sync.
        rc = push(args)

        if rc != 0:
            # push failed. If commits are still unpushed (a non-fast-forward because a
            # sibling pushed during step 1→2, or the known "push skips when work was
            # pre-committed" case), loop to re-integrate and retry.
            if _unpushed() and attempt < attempts:
                warn("↻ remote moved during sync — re-integrating and retrying...")
                continue
            return rc

        # push returned 0. Belt-and-suspenders: push() can report "no changes" when
        # work was committed earlier but never pushed (lesson: ai-push pre-committed
        # skip). If a commit is still unpushed, push it; on non-fast-forward, loop.
        if _unpushed():
            # The default branch is PR-routed; a leftover unpushed commit there means
            # the PR flow didn't finish, not a race. Surface it instead of bouncing a
            # direct push off branch protection (which would just be rejected 3x).
            _, head, _ = git("rev-parse", "--abbrev-ref", "HEAD")
            if head in ("master", "main"):
                err("✗ ai-sync: commits remain unpushed on the protected default branch.")
                err("   The PR flow didn't complete. Check `gh pr list` and re-run ai-sync.")
                return 1
            pc, _, pe = git("push", "origin", "HEAD")
            if pc != 0:
                if attempt < attempts:
                    warn("↻ remote moved during sync — re-integrating and retrying...")
                    continue
                err(f"✗ ai-sync: could not push after {attempts} attempts: {pe}")
                return 1
            info("✓ Pushed pre-committed work")
        break
    else:
        err(f"✗ ai-sync: still racing after {attempts} attempts — try again in a moment.")
        return 1

    info("\n✓ ai-sync complete — brain reconciled (pull --rebase + push).")
    return 0


def selftest() -> int:
    """Fixtures del guardia de co-tenencia.

    Vive aqui y no en un archivo suelto porque una prueba que solo existe en el
    directorio temporal de una sesion muere con la sesion. Cada caso aisla UNA
    variable, y la mutacion correspondiente lo pone rojo: quitar el filtro de
    arbol tumba el caso de "dos sesiones aisladas", quitar el de host tumba el
    de la otra maquina, y evaporar la entrada sin worktree tumba el legado.
    """
    import tempfile
    from datetime import timedelta

    host = socket.gethostname()
    ahora = datetime.now(timezone.utc)
    original = SESSIONS_REGISTRY
    casos = fallas = 0

    def chk(nombre, ok):
        nonlocal casos, fallas
        casos += 1
        fallas += 0 if ok else 1
        print(f"  {nombre:<62} {'PASS' if ok else 'FAIL'}")

    def registro(entradas):
        global SESSIONS_REGISTRY
        fh = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump({"sessions": entradas}, fh)
        fh.close()
        SESSIONS_REGISTRY = Path(fh.name)

    def hb(seg):
        return (ahora - timedelta(seconds=seg)).isoformat()

    A, B = "/tmp/octorato-arbol-a", "/tmp/octorato-arbol-b"
    try:
        registro({"s1": {"branch": "dim/a", "worktree": A, "host": host, "heartbeat": hb(10)},
                  "s2": {"branch": "dim/a2", "worktree": A, "host": host, "heartbeat": hb(20)}})
        chk("dos sesiones en el MISMO arbol -> co-tenencia",
            len(_cotenants_on_tree(1800, A)) == 2)

        registro({"s1": {"branch": "dim/a", "worktree": A, "host": host, "heartbeat": hb(10)},
                  "s2": {"branch": "dim/b", "worktree": B, "host": host, "heartbeat": hb(20)}})
        chk("dos sesiones AISLADAS -> solo yo, no bloquea",
            len(_cotenants_on_tree(1800, A)) == 1)

        registro({"s1": {"branch": "dim/a", "worktree": A, "host": host, "heartbeat": hb(10)},
                  "s2": {"branch": "dim/a2", "worktree": A, "host": "otra-maquina",
                         "heartbeat": hb(20)}})
        chk("mismo path pero OTRO host -> otro disco, no bloquea",
            len(_cotenants_on_tree(1800, A)) == 1)

        registro({"s1": {"branch": "dim/a", "worktree": str(CLAUDE), "host": host,
                         "heartbeat": hb(10)},
                  "s2": {"branch": "no-branch", "host": host, "heartbeat": hb(20)}})
        chk("entrada vieja SIN worktree cuenta como el checkout principal",
            len(_cotenants_on_tree(1800, str(CLAUDE))) == 2)

        registro({"s1": {"branch": "dim/a", "worktree": A, "host": host, "heartbeat": hb(10)},
                  "s2": {"branch": "dim/a2", "worktree": A, "host": host, "heartbeat": hb(9999)}})
        chk("vecino fuera de la ventana no cuenta",
            len(_cotenants_on_tree(1800, A)) == 1)

        registro({"s1": {"branch": "x", "worktree": A, "host": host, "heartbeat": "no-es-fecha"}})
        chk("heartbeat ilegible no revienta el guardia",
            _cotenants_on_tree(1800, A) == [])

        globals()["SESSIONS_REGISTRY"] = Path("/no/existe/registro.json")
        chk("registro ausente es fail-open, devuelve vacio",
            _cotenants_on_tree(1800, A) == [])
    finally:
        globals()["SESSIONS_REGISTRY"] = original

    print(f"\n  {casos - fallas}/{casos}")
    return 1 if fallas else 0


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

    p_cycle = sub.add_parser("cycle")
    p_cycle.add_argument("message", nargs="*")

    sub.add_parser("status")
    sub.add_parser("selftest")

    args = ap.parse_args()
    if args.verb == "pull":
        return pull(args)
    if args.verb == "push":
        return push(args)
    if args.verb == "sync":
        return sync(args.arms or None)
    if args.verb == "cycle":
        return cycle(args)
    if args.verb == "selftest":
        return selftest()
    if args.verb == "status":
        ns = argparse.Namespace(arms=[], status=True)
        return pull(ns)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
