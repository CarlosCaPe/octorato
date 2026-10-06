#!/usr/bin/env python3
"""statusline.py: one short line for Claude Code's statusLine slot.

    gate ok · 3 live · spec panel-receipt-send-gate draft 4/20

Claude Code runs the configured `statusLine.command` on every render, writes a
JSON object to its stdin (session_id, cwd, workspace.current_dir, model, ...)
and shows the first line of stdout. It renders often, so the budget is tight
(AC-20 of the v10 spec: median <= 200 ms, p95 <= 500 ms over 100 calls).

What it costs to know each field, measured on a brain with ~1,000 journals:
importing receipt_ledger + kernel_proc ~80 ms, the live-process sweep ~80 ms,
the gate receipt read (tree hash + ledger) ~20 ms, the dirty check ~70 ms. So
the expensive half (gate state, live count) is computed by `--refresh` and
cached in ~/.claude/.cache/statusline/state-<brain>.json. A render reads only that file
and the spec headers, with nothing imported beyond the standard library:

  fresh cache (< TTL)  print it
  stale cache          print it, and start ONE detached `--refresh` (an O_EXCL
                       lock file keeps a burst of renders from starting many)
  no cache at all      compute in-process once (the very first render)

The spec field is cheap and depends on the cwd, so it is never cached: the spec
whose directory holds the cwd, else the newest spec under docs/specs whose
Status is not `converged`, read from the repo around the cwd and then from the
brain. The gate state is the outward-send gate's reading of THIS brain: ok
(receipt for this gate tree), dirty (gate surfaces differ from HEAD), none.

Never raises: any failure prints what it has, because a status line that
crashes shows nothing at all.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
BRAIN = os.path.dirname(_HERE)
TTL = 20                 # seconds a cached gate/live reading is shown as current
LOCK_STALE = 60          # a refresh lock older than this is abandoned
HEAD_LINES = 30
_STATUS = re.compile(r"^\s*>?\s*\*\*Status:\*\*\s*([A-Za-z-]+)", re.MULTILINE)
_TASK = re.compile(r"^\s*[-*]\s+\[([ xX])\]", re.MULTILINE)
_STAMP = re.compile(r"^\d{12}-")
# ANSI escape sequences, then any other non-printable character: a spec name is
# a directory name anyone can create, and the status line is a terminal.
_ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[@-Z\\-_])")


def printable(text: str) -> str:
    text = _ANSI.sub("", str(text))
    return "".join(ch for ch in text if ch.isprintable())


def cache_dir() -> str:
    return os.path.join(os.path.expanduser("~"), ".claude", ".cache", "statusline")


def _brain_key(brain: str = BRAIN) -> str:
    """A worktree copy and the live brain must not share one cached reading."""
    import hashlib
    return hashlib.sha1(os.path.abspath(brain).encode("utf-8", "replace")).hexdigest()[:10]


def state_path() -> str:
    return os.path.join(cache_dir(), f"state-{_brain_key()}.json")


def lock_path() -> str:
    return os.path.join(cache_dir(), f"refresh-{_brain_key()}.lock")


# ── expensive half: computed by --refresh, cached ───────────────────────────

def compute_state(brain: str = BRAIN) -> dict:
    sys.path.insert(0, _HERE)
    # `git status` (inside gate_surfaces_dirty) would otherwise take the brain's
    # .git/index.lock on every background refresh and can make the operator's
    # own commit fail on "index.lock exists". receipt_ledger copies os.environ
    # into every git call, so setting it here reaches all of them.
    os.environ["GIT_OPTIONAL_LOCKS"] = "0"
    state = {"ts": time.time(), "gate": "?", "live": None}
    try:
        from pathlib import Path
        import receipt_ledger
        root = Path(brain)
        gates = receipt_ledger.gate_tree_hash(root)
        if not gates:
            state["gate"] = "?"
        elif receipt_ledger.gate_surfaces_dirty(root):
            state["gate"] = "dirty"
        else:
            state["gate"] = "ok" if receipt_ledger.gate_receipt_ok(gates) else "none"
    except Exception:  # noqa: BLE001
        state["gate"] = "?"
    try:
        import kernel_proc
        table = kernel_proc.read_ptable()
        now = time.time()
        state["live"] = sum(1 for pid in table.get("processes", {})
                            if kernel_proc.is_live(pid, table, now))
    except Exception:  # noqa: BLE001
        state["live"] = None
    return state


def write_state(state: dict) -> None:
    os.makedirs(cache_dir(), exist_ok=True)
    tmp = f"{state_path()}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh)
    os.replace(tmp, state_path())


def read_state():
    try:
        with open(state_path(), encoding="utf-8") as fh:
            st = json.load(fh)
        return st if isinstance(st, dict) else None
    except (OSError, ValueError):
        return None


def _spawn_refresh() -> None:
    """One detached refresh at a time; the lock is the O_EXCL create."""
    try:
        os.makedirs(cache_dir(), exist_ok=True)
        try:
            if time.time() - os.path.getmtime(lock_path()) > LOCK_STALE:
                os.unlink(lock_path())
        except OSError:
            pass
        fd = os.open(lock_path(), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
    except OSError:
        return  # another render already started one
    try:
        kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
              "stderr": subprocess.DEVNULL, "close_fds": True}
        if os.name == "nt":
            kw["creationflags"] = 0x00000008 | 0x00000200  # DETACHED | NEW_PROCESS_GROUP
        else:
            kw["start_new_session"] = True
        subprocess.Popen([sys.executable, os.path.abspath(__file__), "--refresh"], **kw)
    except OSError:
        try:
            os.unlink(lock_path())
        except OSError:
            pass


def refresh() -> int:
    try:
        write_state(compute_state())
    finally:
        try:
            os.unlink(lock_path())
        except OSError:
            pass
    return 0


# ── cheap half: computed on every render ────────────────────────────────────

def _spec_info(spec_dir: str):
    try:
        with open(os.path.join(spec_dir, "feature.md"), encoding="utf-8", errors="replace") as fh:
            head = "".join(fh.readline() for _ in range(HEAD_LINES))
    except OSError:
        return None
    m = _STATUS.search(head)
    status = m.group(1).lower() if m else "?"
    done = total = 0
    try:
        with open(os.path.join(spec_dir, "plan.md"), encoding="utf-8", errors="replace") as fh:
            marks = _TASK.findall(fh.read())
        total, done = len(marks), sum(1 for x in marks if x in "xX")
    except OSError:
        pass
    return {"name": os.path.basename(spec_dir.rstrip("/\\")), "status": status,
            "done": done, "total": total}


def _repo_root(cwd: str):
    """Nearest ancestor holding docs/specs; no git call."""
    d = os.path.abspath(cwd or ".")
    for _ in range(40):
        if os.path.isdir(os.path.join(d, "docs", "specs")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent
    return None


def active_spec(cwd: str, brain: str = BRAIN):
    cwd = os.path.abspath(cwd or ".")
    roots = []
    for r in (_repo_root(cwd), brain):
        if r and r not in roots:
            roots.append(r)
    for root in roots:
        base = os.path.join(root, "docs", "specs")
        rel = os.path.relpath(cwd, base) if cwd.startswith(base + os.sep) else None
        if rel:
            info = _spec_info(os.path.join(base, rel.split(os.sep)[0]))
            if info:
                return info
        try:
            names = sorted((n for n in os.listdir(base)
                            if os.path.isdir(os.path.join(base, n))), reverse=True)
        except OSError:
            continue
        for n in names:
            info = _spec_info(os.path.join(base, n))
            if info and info["status"] != "converged":
                return info
    return None


def line(payload: dict, state) -> str:
    parts = []
    if state:
        parts.append(f"gate {state.get('gate') or '?'}")
        live = state.get("live")
        parts.append(f"{live if live is not None else '?'} live")
    else:
        parts.extend(["gate ?", "? live"])
    ws = payload.get("workspace") if isinstance(payload.get("workspace"), dict) else {}
    cwd = ws.get("current_dir") or payload.get("cwd") or os.getcwd()
    spec = active_spec(str(cwd))
    if spec:
        name = printable(_STAMP.sub("", spec["name"]))[:40]
        tasks = f" {spec['done']}/{spec['total']}" if spec["total"] else ""
        parts.append(f"spec {name} {printable(spec['status'])}{tasks}")
    else:
        parts.append("no open spec")
    return " · ".join(parts)


def selftest() -> int:
    """Hermetic: sandbox HOME and a synthetic spec tree. Proves the first render
    fills the cache, the second answers from it, and the spec field follows cwd."""
    import shutil
    import tempfile
    sandbox = tempfile.mkdtemp(prefix="statusline-selftest-")
    env = dict(os.environ, HOME=sandbox, USERPROFILE=sandbox)
    try:
        for name, status in (("200001010000-open-one", "draft"), ("200001020000-done-one", "converged")):
            d = os.path.join(sandbox, "repo", "docs", "specs", name)
            os.makedirs(d)
            with open(os.path.join(d, "feature.md"), "w", encoding="utf-8") as fh:
                fh.write(f"# F\n\n> **Status:** {status}\n")
            with open(os.path.join(d, "plan.md"), "w", encoding="utf-8") as fh:
                fh.write("- [x] T01 a\n- [ ] T02 b\n")
        repo = os.path.join(sandbox, "repo")
        outs = []
        for cwd in (repo, os.path.join(repo, "docs", "specs", "200001020000-done-one")):
            cp = subprocess.run([sys.executable, os.path.abspath(__file__)], env=env,
                                input=json.dumps({"workspace": {"current_dir": cwd}}),
                                capture_output=True, text=True, timeout=60)
            outs.append(cp.stdout.strip())
        cached = os.path.isfile(os.path.join(sandbox, ".claude", ".cache", "statusline",
                                             f"state-{_brain_key()}.json"))
        ok = (cached and outs[0].startswith("gate ") and " live · spec open-one draft 1/2" in outs[0]
              and "spec done-one converged 1/2" in outs[1])
        if not ok:
            print(f"selftest FAIL: cached={cached} outs={outs}", file=sys.stderr)
            return 1
        print("selftest PASS: cache filled on first render, spec follows cwd")
        return 0
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--refresh" in argv:
        return refresh()
    if "--selftest" in argv:
        return selftest()
    try:
        raw = sys.stdin.read() if not sys.stdin.isatty() else ""
        payload = json.loads(raw) if raw.strip() else {}
        if not isinstance(payload, dict):
            payload = {}
    except (OSError, ValueError):
        payload = {}
    state = read_state()
    try:
        if state is None:
            state = compute_state()
            write_state(state)
        elif time.time() - float(state.get("ts") or 0) > TTL:
            _spawn_refresh()
    except Exception:  # noqa: BLE001
        pass
    try:
        out = line(payload, state)
    except Exception:  # noqa: BLE001
        out = "octorato"
    try:
        sys.stdout.write(out + "\n")
    except (OSError, UnicodeEncodeError):
        sys.stdout.write(out.encode("ascii", "replace").decode() + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
