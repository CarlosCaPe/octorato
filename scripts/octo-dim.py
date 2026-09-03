#!/usr/bin/env python3
"""octo-dim.py — 4D session dimension manager.

Manages a shared registry (~/.claude/connectome/sessions.json) of concurrent
Claude Code sessions (dimensions) running in parallel git worktrees. Allows
sessions to declare themselves, advertise which file paths they own (lanes),
and see who else is alive — so they can coordinate without colliding.

Concurrency model: atomic tempfile+os.replace writes. Multiple concurrent
writers are tolerated on a last-writer-wins basis (no distributed lock).
A brief comment wherever writes happen notes the accepted race window.

Session id resolution order:
  1. env  CLAUDE_SESSION_ID
  2. --session-id arg (parsed early so subcommands can override)
  3. f"{hostname}-{pid}"  (fallback)

stdlib only. Never crashes the caller (all exceptions caught at top level).
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import socket
import subprocess
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


# fcntl is POSIX-only; degrade to no-lock on Windows
try:
    import fcntl as _fcntl
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False

# ── paths ────────────────────────────────────────────────────────────────────
BRAIN = Path.home() / ".claude"
REGISTRY_DIR = BRAIN / "connectome"
REGISTRY = REGISTRY_DIR / "sessions.json"
APPROVALS_FILE = REGISTRY_DIR / "merge-approvals.json"
# Aprobaciones de ESCRITURA EN PRODUCCION. Archivo aparte a proposito: aprobar un
# merge jamas debe autorizar tocar una instancia o un Worker, y al reves tampoco.
PROD_APPROVALS_FILE = REGISTRY_DIR / "prod-approvals.json"
# Ventana corta para produccion. Ver g__pretool-bash__prod-write.py para el porque:
# la aprobacion cubre UNA operacion, no una jornada.
PROD_TTL_DEFAULT = 600
DIM_ROOT = Path.home() / ".octorato" / "dim"

# ── registry helpers ──────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load() -> dict:
    """Load registry; return empty skeleton on any error."""
    try:
        with REGISTRY.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict) or "sessions" not in data:
            return {"sessions": {}}
        return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"sessions": {}}


@contextlib.contextmanager
def _registry_lock():
    """Acquire an exclusive advisory lock on sessions.json.lock (POSIX only).
    On Windows or any error, degrades to a no-op context (fail-open).
    """
    lock_path = REGISTRY_DIR / "sessions.json.lock"
    if not _HAS_FCNTL:
        yield
        return
    try:
        REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
        lf = open(lock_path, "w")  # noqa: WPS515 — intentional open for locking
        try:
            _fcntl.flock(lf.fileno(), _fcntl.LOCK_EX)
            yield
        finally:
            _fcntl.flock(lf.fileno(), _fcntl.LOCK_UN)
            lf.close()
    except Exception:
        yield  # fail-open: lock acquisition failure must never block the caller


def _save(data: dict, deleted_sids: set[str] | None = None) -> None:
    """Atomic write via tempfile + os.replace, protected by an advisory lock.

    Under the lock we re-read the current file and merge: the caller's session
    entries win per-key, but entries written by concurrent processes since the
    caller's _load() are preserved.  This means 20 concurrent `register` calls
    with distinct ids all persist (no lost-update) — the classic last-writer-
    wins hazard is eliminated.

    deleted_sids: session ids that should be removed from the merged result
    (used by unregister/prune which need real deletions, not just upserts).
    """
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with _registry_lock():
            # Re-read under lock to pick up concurrent writes since caller's _load()
            try:
                with REGISTRY.open("r", encoding="utf-8") as fh:
                    on_disk = json.load(fh)
                if not isinstance(on_disk, dict) or "sessions" not in on_disk:
                    on_disk = {"sessions": {}}
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                on_disk = {"sessions": {}}
            # Merge: caller's sessions win per-key; other keys survive
            on_disk["sessions"].update(data.get("sessions", {}))
            # Apply explicit deletions (prune / unregister)
            for sid in (deleted_sids or set()):
                on_disk["sessions"].pop(sid, None)
            merged = on_disk

            fd, tmp = tempfile.mkstemp(dir=REGISTRY_DIR, prefix=".sessions.tmp.")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(merged, fh, indent=2)
                os.replace(tmp, REGISTRY)
            except Exception:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
    except Exception:
        pass  # fail-open: _save failure must never crash callers


def _resolve_session(args) -> str:
    """Resolve session id per documented priority order."""
    from_env = os.environ.get("CLAUDE_SESSION_ID", "")
    if from_env:
        return from_env
    if hasattr(args, "session_id") and args.session_id:
        return args.session_id
    host = socket.gethostname()
    pid = os.getpid()
    return f"{host}-{pid}"


_FUTURE_SKEW = 120  # seconds; heartbeat this far ahead of now is considered NOT live


def _is_live(entry: dict, ttl: int) -> bool:
    """True if heartbeat is within ttl seconds of now (and not far in the future)."""
    hb = entry.get("heartbeat", "")
    if not hb:
        return False
    try:
        hb_dt = datetime.fromisoformat(hb)
        if hb_dt.tzinfo is None:
            hb_dt = hb_dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = (now - hb_dt).total_seconds()
        # Heartbeat dated far in the future → clock skew / corrupt entry → not live
        if delta < -_FUTURE_SKEW:
            return False
        return delta <= ttl
    except (ValueError, TypeError):
        return False


def _age_str(entry: dict) -> str:
    """Human-readable age string for started field."""
    started = entry.get("started", "")
    if not started:
        return "unknown"
    try:
        s_dt = datetime.fromisoformat(started)
        if s_dt.tzinfo is None:
            s_dt = s_dt.replace(tzinfo=timezone.utc)
        secs = int((datetime.now(timezone.utc) - s_dt).total_seconds())
        if secs < 60:
            return f"{secs}s"
        if secs < 3600:
            return f"{secs // 60}m"
        if secs < 86400:
            return f"{secs // 3600}h {(secs % 3600) // 60}m"
        return f"{secs // 86400}d"
    except (ValueError, TypeError):
        return "?"


# ── merge-approvals helpers ───────────────────────────────────────────────────

@contextlib.contextmanager
def _approvals_lock(store: Path = APPROVALS_FILE):
    """Exclusive advisory lock on <store>.lock (POSIX only)."""
    lock_path = REGISTRY_DIR / (store.name + ".lock")
    if not _HAS_FCNTL:
        yield
        return
    try:
        REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
        lf = open(lock_path, "w")  # noqa: WPS515
        try:
            _fcntl.flock(lf.fileno(), _fcntl.LOCK_EX)
            yield
        finally:
            _fcntl.flock(lf.fileno(), _fcntl.LOCK_UN)
            lf.close()
    except Exception:
        yield  # fail-open


def _load_approvals(store: Path = APPROVALS_FILE) -> dict:
    """Return the approvals dict; empty on any error."""
    try:
        raw = store.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            return {}
        approvals = data.get("approvals", {})
        return approvals if isinstance(approvals, dict) else {}
    except Exception:
        return {}


def _save_approvals(approvals: dict, store: Path = APPROVALS_FILE) -> None:
    """Atomic write of the approvals store under advisory lock."""
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with _approvals_lock(store):
            # Re-read + merge under lock to survive concurrent writes
            try:
                raw = store.read_text(encoding="utf-8")
                on_disk = json.loads(raw)
                if not isinstance(on_disk, dict) or not isinstance(on_disk.get("approvals"), dict):
                    on_disk = {"approvals": {}}
            except Exception:
                on_disk = {"approvals": {}}
            on_disk["approvals"].update(approvals)
            merged = on_disk
            fd, tmp = tempfile.mkstemp(dir=REGISTRY_DIR, prefix=".approvals.tmp.")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(merged, fh, indent=2)
                os.replace(tmp, store)
            except Exception:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
    except Exception:
        pass  # fail-open


def _is_fresh(record: dict) -> bool:
    """True if (now - ts) <= ttl seconds."""
    try:
        ts_dt = datetime.fromisoformat(record.get("ts", ""))
        if ts_dt.tzinfo is None:
            ts_dt = ts_dt.replace(tzinfo=timezone.utc)
        delta = (datetime.now(timezone.utc) - ts_dt).total_seconds()
        return 0 <= delta <= int(record.get("ttl", 900))
    except Exception:
        return False


# ── subcommand handlers ───────────────────────────────────────────────────────

def cmd_register(args) -> int:
    sid = _resolve_session(args)
    now = _now_iso()
    try:
        data = _load()
        existing = data["sessions"].get(sid, {})
        entry = {
            "session_id": sid,
            "branch": args.branch or existing.get("branch", ""),
            "worktree": args.worktree or existing.get("worktree", ""),
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "started": existing.get("started", now),  # preserve original start
            "heartbeat": now,
            "lanes": existing.get("lanes", []),
        }
        data["sessions"][sid] = entry
        _save(data)
        print(f"registered: {sid}")
    except Exception as exc:
        print(f"register warning (non-fatal): {exc}", file=sys.stderr)
    return 0


def cmd_heartbeat(args) -> int:
    sid = _resolve_session(args)
    now = _now_iso()
    try:
        data = _load()
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
        data["sessions"][sid] = entry
        _save(data)
    except Exception as exc:
        print(f"heartbeat warning (non-fatal): {exc}", file=sys.stderr)
    return 0


def cmd_list(args) -> int:
    ttl = args.ttl
    try:
        data = _load()
        sessions = data.get("sessions", {})
        if not sessions:
            print("(no sessions registered)")
            return 0
        # header
        print(f"{'STATUS':<6}  {'ID':<32}  {'BRANCH':<20}  {'WORKTREE':<30}  {'AGE'}")
        print("-" * 100)
        for sid, entry in sessions.items():
            status = "LIVE " if _is_live(entry, ttl) else "STALE"
            branch = (entry.get("branch") or "")[:20]
            worktree = (entry.get("worktree") or "")[:30]
            age = _age_str(entry)
            print(f"{status:<6}  {sid[:32]:<32}  {branch:<20}  {worktree:<30}  {age}")
    except Exception as exc:
        print(f"list warning (non-fatal): {exc}", file=sys.stderr)
    return 0


def cmd_prune(args) -> int:
    ttl = args.ttl
    try:
        data = _load()
        before = len(data["sessions"])
        stale_sids = {
            sid for sid, e in data["sessions"].items()
            if not _is_live(e, ttl)
        }
        data["sessions"] = {
            sid: e for sid, e in data["sessions"].items()
            if sid not in stale_sids
        }
        after = len(data["sessions"])
        _save(data, deleted_sids=stale_sids)
        removed = before - after
        print(f"pruned {removed} stale session(s); {after} remain")
    except Exception as exc:
        print(f"prune warning (non-fatal): {exc}", file=sys.stderr)
    return 0


def cmd_claim(args) -> int:
    sid = _resolve_session(args)
    path = str(Path(args.path).resolve())
    try:
        data = _load()
        entry = data["sessions"].get(sid, {
            "session_id": sid,
            "branch": "",
            "worktree": "",
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "started": _now_iso(),
            "heartbeat": _now_iso(),
            "lanes": [],
        })
        lanes = entry.get("lanes", [])
        if path not in lanes:
            lanes.append(path)
        entry["lanes"] = lanes
        data["sessions"][sid] = entry
        _save(data)
        print(f"claimed: {path} → session {sid}")
    except Exception as exc:
        print(f"claim warning (non-fatal): {exc}", file=sys.stderr)
    return 0


def cmd_release(args) -> int:
    """Remove a path from this session's lanes — or from EVERY session with
    --from-any (operator coordination tool for un-sticking a lane conflict)."""
    path = str(Path(args.path).resolve())
    try:
        data = _load()
        touched = []
        if getattr(args, "from_any", False):
            targets = list(data["sessions"].items())
        else:
            sid = _resolve_session(args)
            targets = [(sid, data["sessions"].get(sid))] if sid in data["sessions"] else []
        for sid, entry in targets:
            if not entry:
                continue
            lanes = entry.get("lanes") or []
            if path in lanes:
                lanes.remove(path)
                entry["lanes"] = lanes
                data["sessions"][sid] = entry
                touched.append(sid)
        if touched:
            _save(data)
            for sid in touched:
                print(f"released: {path} ← session {sid}")
        else:
            print(f"(no session holds a lane on {path})")
    except Exception as exc:
        print(f"release warning (non-fatal): {exc}", file=sys.stderr)
    return 0


def cmd_unregister(args) -> int:
    sid = _resolve_session(args)
    try:
        data = _load()
        if sid in data["sessions"]:
            del data["sessions"][sid]
            _save(data, deleted_sids={sid})
            print(f"unregistered: {sid}")
        else:
            print(f"(session {sid} not found in registry)")
    except Exception as exc:
        print(f"unregister warning (non-fatal): {exc}", file=sys.stderr)
    return 0


def cmd_approve_merge(args) -> int:
    """Upsert a PR/branch approval into merge-approvals.json.

    The file channel gets its teeth here: if an agent shell is detected we
    REFUSE, exactly like approve-prod. A merge approval is granted by the
    OPERATOR in their own terminal, never by the agent that wants to merge.
    The env channel (OCTO_MERGE_APPROVE) stays the real boundary because an
    inline env never reaches the gate hook; this refusal closes the file
    channel so the agent cannot self-approve by writing merge-approvals.json.
    """
    marker = _looks_like_agent_shell()
    if marker and not getattr(args, "i_am_the_operator", False):
        print(
            f"✗ approve-merge REFUSED: agent shell detected ({marker}).\n"
            "  A merge approval is granted by the OPERATOR in their own\n"
            "  terminal, never by the agent that wants to merge. Run in your\n"
            "  shell:\n"
            f"    export OCTO_MERGE_APPROVE={args.pr_or_branch}\n"
            "  (env channel, agent-proof) or re-run this command outside\n"
            "  Claude Code.",
            file=sys.stderr,
        )
        return 2
    pr_id = str(args.pr_or_branch)
    by = args.by or os.environ.get("USER", "operator")
    ttl = int(args.ttl)
    record = {"by": by, "ts": _now_iso(), "ttl": ttl}
    _save_approvals({pr_id: record})
    print(
        f"recorded (audit log): PR/branch '{pr_id}' by '{by}' "
        f"(ttl={ttl}s, expires in {ttl // 60}m{ttl % 60}s)\n"
        f"NOTE: qa-merge-gate no longer treats this file as a gate pass (an agent\n"
        f"can forge it). To authorize the merge, export the agent-proof env in the\n"
        f"terminal that launched Claude Code:\n"
        f"    export OCTO_MERGE_APPROVE={pr_id}"
    )
    return 0


# ── aprobaciones de escritura en produccion ──────────────────────────────────
# Marcadores que el arnes de Claude Code exporta en el ambiente de su herramienta
# Bash. Si estan presentes, quien invoca no es el operador en su terminal: es un
# agente. `approve-prod` se NIEGA en ese caso, y esa negativa es lo que le da
# dientes al canal de archivo. El canal env (OCTO_PROD_APPROVE) sigue siendo la
# frontera real, porque un env en linea nunca llega al hook.
_AGENT_ENV_MARKERS = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SESSION_ID")


def _looks_like_agent_shell() -> str:
    for marker in _AGENT_ENV_MARKERS:
        if os.environ.get(marker):
            return marker
    return ""


def cmd_approve_prod(args) -> int:
    """Registra la aprobacion del operador para escribir en un destino de produccion."""
    marker = _looks_like_agent_shell()
    if marker and not getattr(args, "i_am_the_operator", False):
        print(
            f"✗ approve-prod RECHAZADO: se detecto ambiente de agente ({marker}).\n"
            "  Una aprobacion de produccion la da el OPERADOR en su propia terminal,\n"
            "  nunca el agente que quiere escribir. Corre esto en tu shell:\n"
            f"    export OCTO_PROD_APPROVE={','.join(args.destinations)}\n"
            "  (canal env, a prueba de agente) o vuelve a correr este comando fuera\n"
            "  de Claude Code.",
            file=sys.stderr,
        )
        return 2
    by = args.by or os.environ.get("USER", "operator")
    ttl = int(args.ttl)
    ts = _now_iso()
    records = {str(d): {"by": by, "ts": ts, "ttl": ttl} for d in args.destinations}
    _save_approvals(records, store=PROD_APPROVALS_FILE)
    print(
        f"aprobado(s): {', '.join(records)} por '{by}' "
        f"(ttl={ttl}s, caduca en {ttl // 60}m{ttl % 60}s)"
    )
    return 0


def cmd_prod_approvals(args) -> int:
    """Lista las aprobaciones de produccion vivas."""
    approvals = _load_approvals(PROD_APPROVALS_FILE)
    if not approvals:
        print("(sin aprobaciones de produccion registradas)")
        return 0
    show_all = getattr(args, "all", False)
    print(f"{'ESTADO':<6}  {'DESTINO':<40}  {'POR':<16}  {'TS':<25}  {'TTL'}")
    print("-" * 100)
    for dest, record in approvals.items():
        fresh = _is_fresh(record)
        if not fresh and not show_all:
            continue
        status = "VIVA  " if fresh else "VENC  "
        by = (record.get("by") or "?")[:16]
        ts = (record.get("ts") or "?")[:25]
        print(f"{status}  {dest[:40]:<40}  {by:<16}  {ts:<25}  {record.get('ttl', '?')}s")
    return 0


def cmd_revoke_prod(args) -> int:
    """Quita una aprobacion de produccion antes de que caduque sola."""
    dest = str(args.destination)
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with _approvals_lock(PROD_APPROVALS_FILE):
            try:
                data = json.loads(PROD_APPROVALS_FILE.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or not isinstance(data.get("approvals"), dict):
                    data = {"approvals": {}}
            except Exception:
                data = {"approvals": {}}
            if dest not in data["approvals"]:
                print(f"(no hay aprobacion para '{dest}')")
                return 0
            del data["approvals"][dest]
            fd, tmp = tempfile.mkstemp(dir=REGISTRY_DIR, prefix=".prod-approvals.tmp.")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=2)
                os.replace(tmp, PROD_APPROVALS_FILE)
            except Exception:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
    except Exception as exc:
        print(f"revoke-prod warning (non-fatal): {exc}", file=sys.stderr)
        return 0
    print(f"revocada: aprobacion de '{dest}'")
    return 0


def cmd_approvals(args) -> int:
    """List current approvals with freshness status."""
    approvals = _load_approvals()
    if not approvals:
        print("(no merge approvals on record)")
        return 0
    show_all = getattr(args, "all", False)
    print(f"{'STATUS':<6}  {'PR/BRANCH':<20}  {'BY':<16}  {'TS':<25}  {'TTL'}")
    print("-" * 80)
    for pr_id, record in approvals.items():
        fresh = _is_fresh(record)
        if not fresh and not show_all:
            continue
        status = "LIVE  " if fresh else "STALE "
        by = (record.get("by") or "?")[:16]
        ts = (record.get("ts") or "?")[:25]
        ttl = record.get("ttl", "?")
        print(f"{status}  {pr_id[:20]:<20}  {by:<16}  {ts:<25}  {ttl}s")
    return 0


def cmd_revoke_merge(args) -> int:
    """Remove an approval from merge-approvals.json."""
    pr_id = str(args.pr_or_branch)
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with _approvals_lock():
            try:
                raw = APPROVALS_FILE.read_text(encoding="utf-8")
                data = json.loads(raw)
                if not isinstance(data, dict) or not isinstance(data.get("approvals"), dict):
                    data = {"approvals": {}}
            except Exception:
                data = {"approvals": {}}
            if pr_id not in data["approvals"]:
                print(f"(no approval found for '{pr_id}')")
                return 0
            del data["approvals"][pr_id]
            fd, tmp = tempfile.mkstemp(dir=REGISTRY_DIR, prefix=".approvals.tmp.")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=2)
                os.replace(tmp, APPROVALS_FILE)
            except Exception:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
    except Exception as exc:
        print(f"revoke warning (non-fatal): {exc}", file=sys.stderr)
        return 0
    print(f"revoked: approval for '{pr_id}' removed")
    return 0


def cmd_worktree_init(args) -> int:
    """Idempotently create a git worktree for this dimension.

    Requires a STABLE session id (--session-id or CLAUDE_SESSION_ID). The
    hostname-pid fallback is refused here: it changes per invocation AND
    [:8] of "<host>-<pid>" collapses to the hostname prefix, so every
    session on one machine would "fork" into the SAME worktree — a shared
    tree with extra steps (observed: dim/dataqbs- on 2026-06-04).
    """
    sid_explicit = (getattr(args, "session_id", "") or
                    os.environ.get("CLAUDE_SESSION_ID", ""))
    if not sid_explicit:
        print("worktree-init: no stable session id; pass --session-id <id> or set "
              "CLAUDE_SESSION_ID. Refusing to fork into a hostname-derived path "
              "that all sessions would share.")
        return 1
    sid = sid_explicit
    # [:12] not [:8]: session ids are UUID hex; 8 chars is weaker than it looks
    # across many short-lived sessions, and a prefix collision silently re-shares
    # a worktree — the exact de-isolation this command exists to prevent.
    short = re.sub(r"[^a-z0-9]", "", sid.lower())[:12] or "dim0"
    # --repo isolates an ARM (or any repo); default is the brain. Arm worktrees
    # live OUT of the repo tree (~/.octorato/arm/<name>/) so they never depend on
    # the arm gitignoring a worktree dir. Same dim/<id> branch = isolation AND
    # per-session attribution (which session made which change) in arms too.
    repo_arg = (getattr(args, "repo", "") or "").strip()
    if repo_arg:
        repo = Path(os.path.expanduser(repo_arg)).resolve()
        dim_root = Path.home() / ".octorato" / "arm" / repo.name
    else:
        repo = BRAIN
        dim_root = DIM_ROOT
    target = dim_root / short
    branch = f"dim/{short}"

    # Only short-circuit if target is actually a git worktree (has a .git entry)
    if target.exists() and (target / ".git").exists():
        print(str(target))
        return 0

    dim_root.mkdir(parents=True, exist_ok=True)

    # Try with -b (new branch)
    result = subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", str(target), "-b", branch],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        # Branch may already exist; try attaching without -b
        result2 = subprocess.run(
            ["git", "-C", str(repo), "worktree", "add", str(target), branch],
            capture_output=True, text=True,
        )
        if result2.returncode != 0:
            msg = result2.stderr.strip() or result.stderr.strip()
            print(f"worktree-init: could not create worktree: {msg}")
            return 0  # never hard-fail

    _link_private_data(repo, target)
    print(str(target))
    return 0


def _link_private_data(repo: Path, target: Path) -> None:
    """Point the new worktree at the main checkout's gitignored private data.

    A worktree receives TRACKED files only, so `company/` never appears in one.
    Everything that reads it therefore ran blind from a worktree: the pre-push
    leak guard soft-failed open, check-generic found no blocklist, brain_doctor
    reported it absent. A client's company name reached a public branch through
    exactly that gap, from a worktree this very function had created.

    A symlink, not a copy: the blocklist must never be duplicated, and an
    inherited link keeps the two in sync with no staleness window. Best-effort
    on purpose, since worktree creation must never hard-fail; when it cannot be
    made (Windows without privileges, for one), pre-push still resolves the
    blocklist through --git-common-dir, which is the guard that actually blocks.
    """
    source = repo / "company"
    link = target / "company"
    if not source.is_dir() or link.exists() or link.is_symlink():
        return
    try:
        link.symlink_to(source, target_is_directory=True)
    except (OSError, NotImplementedError):
        pass  # pre-push's own resolution covers this case


# ── main ──────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="octo-dim",
        description="4D session dimension manager — parallel worktree registry",
    )
    p.add_argument("--session-id", default="", help="Override session id")

    sub = p.add_subparsers(dest="cmd", required=True)

    reg = sub.add_parser("register", help="Upsert this session in the registry")
    reg.add_argument("--branch", default="", help="Current git branch")
    reg.add_argument("--worktree", default="", help="Current worktree path")

    sub.add_parser("heartbeat", help="Update heartbeat timestamp")

    lst = sub.add_parser("list", help="List all sessions")
    lst.add_argument("--ttl", type=int, default=900, help="Live TTL in seconds")

    prn = sub.add_parser("prune", help="Remove stale sessions")
    prn.add_argument("--ttl", type=int, default=900, help="Live TTL in seconds")

    clm = sub.add_parser("claim", help="Add a path to this session's lanes")
    clm.add_argument("path", help="Absolute or relative path to claim")

    rel = sub.add_parser("release", help="Remove a path from lanes (yours, or any with --from-any)")
    rel.add_argument("path", help="Absolute or relative path to release")
    rel.add_argument("--from-any", action="store_true", dest="from_any",
                     help="Release the lane from EVERY session (operator coordination)")

    sub.add_parser("unregister", help="Remove this session from the registry")

    wi = sub.add_parser("worktree-init", help="Create a git worktree for this dimension")
    # default=SUPPRESS: a subparser default would CLOBBER the value the parent
    # parser already captured from `--session-id X worktree-init` (argparse
    # subparser-default gotcha; this silently de-isolated every fork until 2026-06-04).
    wi.add_argument("--session-id", dest="session_id", default=argparse.SUPPRESS,
                    help="Use this session id instead of auto-resolved")
    wi.add_argument("--repo", default="",
                    help="Repo to isolate (default: the brain ~/.claude). Pass an "
                         "arm path to fork a dim/<id> worktree for arm work.")

    am = sub.add_parser("approve-merge", help="Write a merge audit-log entry (NOT a gate pass; authorize via OCTO_MERGE_APPROVE env)")
    am.add_argument("pr_or_branch", help="PR number or branch name (e.g. 96 or main)")
    am.add_argument("--by", default="", help="Approver name (default: $USER or 'operator')")
    am.add_argument("--ttl", type=int, default=900, help="Approval TTL in seconds (default 900)")
    am.add_argument("--i-am-the-operator", action="store_true", dest="i_am_the_operator",
                    help="Explicit escape when the operator runs this INSIDE a shell "
                         "marked as an agent's. Leaves a trace in history.")

    apv = sub.add_parser("approvals", help="List current merge approvals")
    apv.add_argument("--all", action="store_true", help="Show stale approvals too")

    rv = sub.add_parser("revoke-merge", help="Revoke a merge approval")
    rv.add_argument("pr_or_branch", help="PR number or branch name to revoke")

    ap = sub.add_parser("approve-prod",
                        help="Aprobar una escritura a produccion por destino (solo operador)")
    ap.add_argument("destinations", nargs="+",
                    help="Destino(s): id de instancia, nombre del Worker o token acordado")
    ap.add_argument("--by", default="", help="Quien aprueba (default: $USER)")
    ap.add_argument("--ttl", type=int, default=PROD_TTL_DEFAULT,
                    help=f"Ventana en segundos (default {PROD_TTL_DEFAULT})")
    ap.add_argument("--i-am-the-operator", action="store_true", dest="i_am_the_operator",
                    help="Escape explicito cuando el operador corre esto DENTRO de una "
                         "terminal marcada como de agente. Deja rastro en el historial.")

    pav = sub.add_parser("prod-approvals", help="Listar aprobaciones de produccion")
    pav.add_argument("--all", action="store_true", help="Incluir las ya vencidas")

    rvp = sub.add_parser("revoke-prod", help="Revocar una aprobacion de produccion")
    rvp.add_argument("destination", help="Destino a revocar")

    return p


HANDLERS = {
    "register": cmd_register,
    "heartbeat": cmd_heartbeat,
    "list": cmd_list,
    "prune": cmd_prune,
    "claim": cmd_claim,
    "release": cmd_release,
    "unregister": cmd_unregister,
    "worktree-init": cmd_worktree_init,
    "approve-merge": cmd_approve_merge,
    "approvals": cmd_approvals,
    "revoke-merge": cmd_revoke_merge,
    "approve-prod": cmd_approve_prod,
    "prod-approvals": cmd_prod_approvals,
    "revoke-prod": cmd_revoke_prod,
}


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    handler = HANDLERS.get(args.cmd)
    if handler is None:
        print(f"unknown command: {args.cmd}", file=sys.stderr)
        return 1
    return handler(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        # Top-level safety net — register/heartbeat/list must always exit 0
        print(f"octo-dim fatal (non-crashing): {exc}", file=sys.stderr)
        sys.exit(0)
