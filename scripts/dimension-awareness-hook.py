#!/usr/bin/env python3
"""dimension-awareness-hook.py — PreToolUse hook for 4D session dimension awareness
AND lane enforcement.

Two jobs, in order of force:
  1. ENFORCE lanes (Write/Edit only): if the target file is claimed by ANOTHER
     live session, DENY the tool call. Two dimensions must never write one file.
  2. AUTO-CLAIM (Write/Edit only): if the target file is free, claim it for this
     session — the first writer owns the lane, involuntarily. This is what turns
     the lane system from etiquette into a reflex (the cerebellum principle:
     enforcement must fire without anyone choosing to run it).
  3. DENY broad git staging (Bash only): `git add -A|--all|.` / `git commit -a`
     whose target resolves inside the SHARED ~/.claude checkout while other
     dimensions are live — the exact command that swallows a neighbor's
     uncommitted files. Explicit pathspec passes; staging inside your own
     dimension worktree passes; a nested repo under the brain passes.
     THREAT MODEL: an HONEST agent making a careless mistake, not an adversary —
     wrapped invocations (`sh -c "git add -A"`, `eval`, `$(...)`) bypass the
     detector by design; the fail-closed boundary for merges stays qa-merge-gate.
  4. WARN (all matched tools): when other live dimensions share the tree, inject
     the shared-tree warning as before.

Lanes die with their session: a session that stops heartbeating past the TTL is
no longer live, so its lanes stop blocking (and `octo-dim prune` removes them).
Cooperative handoff: `octo-dim release <path>` / `release <path> --from-any`.

Operator override: OCTO_LANE_OVERRIDE=1 in the HARNESS environment bypasses the
deny. An agent cannot set the harness env for Write/Edit tool calls (an inline
`FOO=1` only scopes a Bash command), so the override is operator-only — the same
agent-proof property as OCTO_MERGE_APPROVE in the merge gate.

Design principles (mirroring grafo-gate.py):
  - FAIL-OPEN on infrastructure errors (bad JSON, unreadable registry, lock
    failure) — a broken hook must never brick a session.
  - FAIL-CLOSED only on a genuine, attributable lane conflict.
  - Fast: no subprocess calls, only JSON reads + datetime math.
  - Registry writes use lock + re-read-merge (same contract as octo-dim.py's
    _save) so concurrent heartbeats/claims from parallel sessions never lose
    each other's updates. The lock/merge block is intentionally duplicated from
    octo-dim.py — hooks stay import-free and self-contained.

Stdin:  {"session_id": str, "tool_name": str, "tool_input": {...}}
Stdout: hookSpecificOutput JSON — additionalContext (warn) or
        permissionDecision: "deny" (lane conflict).
Exit:   always 0 (the deny travels in the JSON, not the exit code).

Known limitation (shared-tree attribution): a file already git-modified by a
session that never wrote through this hook has no lane — the first post-
enforcement writer claims it. Attribution of pre-existing uncommitted edits is
impossible in a shared tree; full isolation still means one worktree per
session (`octo-dim worktree-init`).

Security note — session identity resolution: env CLAUDE_SESSION_ID wins over
the stdin payload field. The harness sets the env; an agent cannot set harness
env for Write/Edit calls (inline `FOO=1` scopes only Bash), so session_id in
the payload is treated as an untrusted hint. This closes the impersonation
bypass: an agent writing session_id=<other> in stdin cannot masquerade as that
session to skip a lane conflict.
"""
from __future__ import annotations

import contextlib
import json
import os
import socket
import sys
import tempfile
from datetime import datetime, timezone
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


try:
    import fcntl as _fcntl
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False

REGISTRY_DIR = Path.home() / ".claude" / "connectome"
REGISTRY = REGISTRY_DIR / "sessions.json"
DEFAULT_TTL = 900  # seconds
_FUTURE_SKEW = 120  # seconds; heartbeat this far ahead of now is considered NOT live

# Tools whose target path participates in lane enforcement.
_LANE_TOOLS = ("Write", "Edit", "NotebookEdit")


# ── session id (same resolution order as octo-dim.py) ───────────────────────

def _resolve_session(payload: dict | None = None) -> str:
    """Priority: env CLAUDE_SESSION_ID → stdin payload session_id → hostname-pid.

    env wins over payload because CLAUDE_SESSION_ID is set by the harness (the
    operator-controlled process that spawns Claude Code). An agent cannot set the
    harness env for Write/Edit tool calls — an inline `CLAUDE_SESSION_ID=X`
    only scopes a Bash command, not the hook execution environment. This makes
    session identity agent-proof: a rogue payload field cannot impersonate another
    session and bypass the lane conflict check.
    """
    from_env = os.environ.get("CLAUDE_SESSION_ID", "")
    if from_env:
        return from_env
    if payload:
        from_payload = payload.get("session_id", "")
        if from_payload:
            return str(from_payload)
    return f"{socket.gethostname()}-{os.getpid()}"


# ── registry helpers ─────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_registry() -> dict:
    try:
        with REGISTRY.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and "sessions" in data:
            return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return {"sessions": {}}


@contextlib.contextmanager
def _registry_lock():
    """Exclusive advisory lock on sessions.json.lock (POSIX only); no-op fallback."""
    lock_path = REGISTRY_DIR / "sessions.json.lock"
    if not _HAS_FCNTL:
        yield
        return
    try:
        REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
        lf = open(lock_path, "w")
        try:
            _fcntl.flock(lf.fileno(), _fcntl.LOCK_EX)
            yield
        finally:
            _fcntl.flock(lf.fileno(), _fcntl.LOCK_UN)
            lf.close()
    except Exception:
        yield  # fail-open


def _upsert_session(sid: str, mutate) -> None:
    """Lock → re-read → mutate(entry) → atomic write. Merge-safe upsert of ONE
    session entry; concurrent writers' entries survive (same contract as
    octo-dim.py's _save). `mutate` receives the current entry dict and edits it
    in place. Non-fatal on any error (fail-open)."""
    try:
        with _registry_lock():
            data = _load_registry()
            now = _now_iso()
            entry = data["sessions"].get(sid, {
                "session_id": sid,
                "branch": "",
                "worktree": "",
                "pid": os.getpid(),
                "host": socket.gethostname(),
                "started": now,
                "lanes": [],
            })
            entry["heartbeat"] = now
            mutate(entry)
            data["sessions"][sid] = entry
            REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=REGISTRY_DIR, prefix=".sessions.tmp.")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=2)
                os.replace(tmp, REGISTRY)
            except Exception:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
    except Exception:
        pass  # fail-open: registry write failure must never block the caller


def _is_live(entry: dict, ttl: int = DEFAULT_TTL) -> bool:
    hb = entry.get("heartbeat", "")
    if not hb:
        return False
    try:
        hb_dt = datetime.fromisoformat(hb)
        if hb_dt.tzinfo is None:
            hb_dt = hb_dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = (now - hb_dt).total_seconds()
        if delta < -_FUTURE_SKEW:
            return False
        return delta <= ttl
    except (ValueError, TypeError):
        return False


# ── broad-staging detection (quote-aware; see skills/command-boundary-hook-matching) ──

BRAIN_TREE = Path.home() / ".claude"
OCTO_ROOT = Path.home() / ".octorato"  # per-session dim worktrees live here (brain + arms)


def _split_subcmds(cmd: str) -> list:
    """Split a shell command on UNQUOTED separators only (; && || | newline)."""
    parts, buf, depth, in_sq, in_dq = [], [], 0, False, False
    cmd = cmd.replace("\\\n", " ")
    i = 0
    while i < len(cmd):
        c = cmd[i]
        if in_sq:
            buf.append(c)
            if c == "'":
                in_sq = False
        elif in_dq:
            buf.append(c)
            if c == '"' and (i == 0 or cmd[i - 1] != "\\"):
                in_dq = False
        elif c == "'":
            in_sq = True
            buf.append(c)
        elif c == '"':
            in_dq = True
            buf.append(c)
        elif c in "({":
            depth += 1
            buf.append(c)
        elif c in ")}":
            depth -= 1
            buf.append(c)
        elif depth == 0 and cmd[i:i + 2] in ("&&", "||"):
            parts.append("".join(buf).strip())
            buf = []
            i += 1
        elif depth == 0 and c in ";\n|":
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(c)
        i += 1
    if buf:
        parts.append("".join(buf).strip())
    return [p for p in parts if p]


_ENV_ASSIGN = None  # compiled lazily to keep import cost zero on the hot path


def _broad_git_verb(tokens: list):
    """Return ('add'|'commit', repo_or_None) when tokens are a broad-stage git
    invocation; (None, None) otherwise. Mentions inside quoted args never reach
    here because shlex already consumed the quotes per sub-command."""
    global _ENV_ASSIGN
    import re as _re
    if _ENV_ASSIGN is None:
        _ENV_ASSIGN = _re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
    i = 0
    while i < len(tokens) and _ENV_ASSIGN.match(tokens[i]):
        i += 1
    if i >= len(tokens) or os.path.basename(tokens[i]) != "git":
        return None, None
    i += 1
    repo = None
    while i < len(tokens):
        t = tokens[i]
        if t == "-C" and i + 1 < len(tokens):
            repo = tokens[i + 1]
            i += 2
        elif t.startswith(("--git-dir=", "--work-tree=")):
            # --git-dir=~/.claude/.git points at the shared index regardless
            # of cwd; treat its parent/value as the target repo.
            val = t.split("=", 1)[1]
            repo = val[:-5] if val.endswith("/.git") else val
            i += 1
        elif t in ("--git-dir", "--work-tree") and i + 1 < len(tokens):
            val = tokens[i + 1]
            repo = val[:-5] if val.endswith("/.git") else val
            i += 2
        elif t.startswith("-"):
            i += 1
        else:
            break
    if i >= len(tokens):
        return None, None
    sub, rest = tokens[i], tokens[i + 1:]
    if sub == "add":
        for t in rest:
            if t in ("-A", "--all", ".", ":/", ":(top)"):
                return "add", repo
    elif sub == "commit":
        for t in rest:
            if t == "--all":
                return "commit", repo
            # short-flag cluster containing 'a' (-a, -am, -aF…); long flags excluded
            if _re.match(r"^-[A-Za-z]*a[A-Za-z]*$", t):
                return "commit", repo
    return None, None


def _enclosing_worktree_root(path: Path):
    """Nearest ancestor (incl. path) that holds a `.git` entry — the git working
    tree root. None when the path is not inside any repo."""
    p = path
    while True:
        if (p / ".git").exists():
            return p
        if p.parent == p:
            return None
        p = p.parent


def _broad_stage_on_shared_tree(cmd: str, session_cwd: str):
    """Return (verb, repo_root) when a sub-command broad-stages a SHARED working
    tree — a repo's MAIN checkout (the brain OR any arm), where another live
    session's uncommitted files could be swallowed by `git add -A` / `commit -a`.

    PASS (never deny):
      - per-session dim worktrees (under ~/.octorato/, OR any linked worktree
        whose `.git` is a FILE pointer, not a directory) — those are isolated;
      - a target outside any git repo.
    Over-strict by design: it also fires in a repo whose only other live session
    is elsewhere, and in vendored nested repos. The fix (explicit pathspec, or
    fork a worktree) is good practice regardless, so the cost is near zero. This
    generalizes the former brain-only gate so ARM trees get the same protection."""
    import shlex
    try:
        octo = OCTO_ROOT.resolve()
    except Exception:
        octo = OCTO_ROOT
    cwd = Path(session_cwd or os.getcwd())
    for seg in _split_subcmds(cmd):
        try:
            tokens = shlex.split(seg)
        except ValueError:
            tokens = seg.split()
        if not tokens:
            continue
        if tokens[0] == "cd" and len(tokens) > 1:
            p = Path(os.path.expanduser(tokens[1]))
            cwd = p if p.is_absolute() else cwd / p
            continue
        verb, repo = _broad_git_verb(tokens)
        if not verb:
            continue
        target = Path(os.path.expanduser(repo)) if repo else cwd
        if not target.is_absolute():
            target = cwd / target
        try:
            target = target.resolve()
        except Exception:
            continue
        root = _enclosing_worktree_root(target)
        if root is None:
            continue  # not in a repo → nothing shared to protect
        if root == octo or octo in root.parents:
            continue  # isolated per-session dim worktree
        gitentry = root / ".git"
        if gitentry.is_file():
            continue  # linked worktree (.git is a pointer file) → isolated
        return verb, root
    return None


# ── output helpers ───────────────────────────────────────────────────────────

def _emit(payload: dict) -> None:
    try:
        print(json.dumps({"hookSpecificOutput": payload}))
    except Exception:
        pass  # stdout failure → fail-open


def _deny(reason: str) -> None:
    _emit({
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    })


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    try:
        raw = sys.stdin.read()
        data = json.loads(raw)
    except Exception:
        return 0  # bad JSON → fail-open, no output

    tool_name = (data.get("tool_name") or "")
    tool_input = data.get("tool_input") or {}
    my_sid = _resolve_session(data)

    # Target path (lane tools only)
    target_path: str | None = None
    if tool_name in _LANE_TOOLS:
        raw_path = tool_input.get("file_path") or tool_input.get("notebook_path") or None
        if raw_path:
            try:
                target_path = str(Path(raw_path).resolve())
            except Exception:
                target_path = None

    # Load registry, find other LIVE sessions
    try:
        registry = _load_registry()
        sessions = registry.get("sessions", {})
    except Exception:
        return 0  # registry unreadable → fail-open

    other_live = {
        sid: entry
        for sid, entry in sessions.items()
        if sid != my_sid and _is_live(entry)
    }

    # ── 1. ENFORCE: lane conflict → deny (unless operator override) ──────────
    if target_path and other_live:
        for sid, entry in other_live.items():
            if target_path in (entry.get("lanes") or []):
                if os.environ.get("OCTO_LANE_OVERRIDE") == "1":
                    break  # operator override — fall through to warn
                _deny(
                    f"⛔ 4D lane: {target_path} is owned by live dimension "
                    f"{sid[:12]}…. Two dimensions must not write one file. "
                    f"Options: coordinate via the operator, wait for that "
                    f"session to finish (TTL {DEFAULT_TTL}s), have the operator "
                    f"run `octo-dim release {target_path} --from-any` or set "
                    f"OCTO_LANE_OVERRIDE=1, or fork your own worktree "
                    f"(`octo-dim worktree-init`)."
                )
                # Still record our heartbeat; the denied write claims nothing.
                _upsert_session(my_sid, lambda e: None)
                return 0

    # ── 1b. ENFORCE: broad git staging on the SHARED brain tree → deny ───────
    # The exact collision mode: one session's `git add -A` swallows another's
    # uncommitted files. Explicit pathspec passes; own-worktree staging passes.
    if tool_name == "Bash" and other_live:
        try:
            hit = _broad_stage_on_shared_tree(
                tool_input.get("command") or "", data.get("cwd") or ""
            )
        except Exception:
            hit = None  # detector failure → fall through to the warning (fail-open)
        if hit:
            verb, root = hit
            is_brain = str(root) == str(BRAIN_TREE)
            repo_flag = "" if is_brain else f" --repo {root}"
            where = "the SHARED brain tree" if is_brain else f"a SHARED working tree ({root})"
            _deny(
                f"⛔ 4D DIMENSION GATE: broad `git {verb}` on {where} "
                f"while {len(other_live)} other live dimension(s) exist. This can swallow "
                f"another session's uncommitted files into your commit. Stage by EXPLICIT "
                f"pathspec (`git add <file>…`), or fork your own worktree first: "
                f"`python3 ~/.claude/scripts/octo-dim.py --session-id <sid> worktree-init{repo_flag}`."
            )
            _upsert_session(my_sid, lambda e: None)  # heartbeat; denied call claims nothing
            return 0

    # ── 2. AUTO-CLAIM: free path + concurrent dimensions → first writer owns ──
    if target_path and other_live:
        def _claim(entry: dict, path=target_path) -> None:
            lanes = entry.get("lanes") or []
            if path not in lanes:
                lanes.append(path)
            entry["lanes"] = lanes
        _upsert_session(my_sid, _claim)
    else:
        # Sole dimension or non-lane tool: heartbeat only.
        _upsert_session(my_sid, lambda e: None)

    if not other_live:
        return 0  # sole dimension — no warning needed

    # ── 3. WARN: shared-tree awareness (as before) ────────────────────────────
    n = len(other_live)
    ids_branches = ", ".join(
        f"{sid[:12]}…({e.get('branch') or 'no-branch'})"
        for sid, e in other_live.items()
    )
    warning = (
        f"⚠ 4D: {n} other live dimension(s) share this working tree "
        f"[{ids_branches}]. "
        f"You are NOT isolated — commit ONLY by explicit pathspec (never git add -A), "
        f"and consider `python3 ~/.claude/scripts/octo-dim.py worktree-init` "
        f"to fork your own dimension."
    )
    if target_path:
        warning += f" Lane auto-claimed: {target_path} → this session."

    _emit({"hookEventName": "PreToolUse", "additionalContext": warning})
    return 0


def _selftest() -> int:
    """Bespoke liveness proof. The broad-stage deny fires only with a LIVE
    concurrent dimension on a SHARED tree, both time-and-state dependent, so a
    static committed fixture cannot express it. Here we build a throwaway HOME
    with a fresh live sibling session and a shared .git tree at runtime, then run
    the real main() twice: `git add -A` must deny, explicit pathspec must allow.
    """
    import gate_selftest
    ok = True
    sandbox = Path(tempfile.mkdtemp(prefix="dim-selftest-"))
    try:
        tree = sandbox / ".claude"
        (tree / ".git").mkdir(parents=True, exist_ok=True)
        conn = tree / "connectome"
        conn.mkdir(parents=True, exist_ok=True)
        (conn / "sessions.json").write_text(json.dumps({"sessions": {
            "other-live-dimension": {
                "session_id": "other-live-dimension",
                "branch": "sibling", "lanes": [],
                "heartbeat": _now_iso(),
            }
        }}), encoding="utf-8")

        def run(cmd: str):
            env = dict(os.environ)
            for k in ("OCTO_LANE_OVERRIDE",):
                env.pop(k, None)
            env["HOME"] = str(sandbox)
            env["USERPROFILE"] = str(sandbox)
            env["CLAUDE_SESSION_ID"] = "me-this-dimension"
            payload = json.dumps({"tool_name": "Bash",
                                  "tool_input": {"command": cmd},
                                  "cwd": str(tree)})
            cp = subprocess.run([sys.executable, str(Path(__file__).resolve())],
                                input=payload, capture_output=True, text=True,
                                cwd=str(tree), env=env, timeout=30)
            return gate_selftest.emits_block(cp.returncode, cp.stdout)

        if not run("git add -A"):
            print("selftest FAIL: 'git add -A' on shared tree did NOT deny", file=sys.stderr)
            ok = False
        if run("git add scripts/foo.py"):
            print("selftest FAIL: explicit-pathspec stage WAS denied", file=sys.stderr)
            ok = False
    finally:
        import shutil as _sh
        _sh.rmtree(sandbox, ignore_errors=True)
    if ok:
        print("selftest PASS: broad-stage denies, explicit pathspec allows "
              "(dimension-awareness-hook.py)")
    return 0 if ok else 1


if __name__ == "__main__":
    import subprocess
    import tempfile
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # fail-open: never break the user's tool call
