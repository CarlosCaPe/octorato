#!/usr/bin/env python3
"""gate_selftest.py: shared fixture-driven liveness harness for fail-closed gates.

A gate that merely EXISTS on disk is not proven to BLOCK. This module runs a gate's
real main path against a pair of realistic hook-stdin fixtures and asserts the two
legs that together prove it is live:

  violation.json  -> the gate MUST block  (deny JSON, block JSON, or non-zero exit)
  benign.json     -> the gate MUST allow  (silent, exit 0, no deny/block)

The benign leg is mandatory. A gate that blocks EVERYTHING would pass a
violation-only test while being unusable, so gaming the harness by blocking all is
impossible: such a gate fails its benign leg.

Fixture layout under registry/fixtures/<rule-id>/:
  violation.json            required; one or more violation*.json all must block
  benign.json               required; one or more benign*.json all must allow
  <name>.jsonl              optional transcript files a payload's transcript_path
                            points at (relative path, rewritten to absolute here)
  home/                     optional seed copied into a throwaway HOME so a gate
                            that reads session/ledger state can be driven

Isolation: every leg runs under a fresh temp HOME and cwd, with the dangerous
operator-override env vars stripped, so no leg can touch real brain state or leak
an approval. The harness is used two ways: a gate script's `--selftest <dir>`
branch calls run_gate_selftest(); brain_doctor's gate-liveness check runs each
gate's `--selftest` proof as a subprocess.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# env vars that could turn a violation into an allow; stripped for every leg
_OVERRIDE_ENV = (
    "OCTO_MERGE_APPROVE", "OCTO_QA_OK", "OCTO_ALLOW_FORCE",
    "OCTO_LANE_OVERRIDE", "OCTO_GRAFO_OVERRIDE",
    # v8: the kernel gates print this one as their own unlock, so an operator
    # who ran the prescribed fix has it exported in the shell that launched
    # Claude Code. Inherited into a selftest leg it disarms the gate under
    # test, the violation fixture "does not block", and the doctor FAILs a
    # brain whose only sin is that the unlock worked.
    "OCTO_KERNEL_OPEN",
)


def emits_block(returncode: int, stdout: str) -> bool:
    """Universal 'did the gate block?' predicate, hook-shape agnostic.

    True when any of: a non-zero exit (exit-code gates like qa-merge-gate),
    a PreToolUse deny, or a Stop block appears.
    """
    if returncode != 0:
        return True
    out = (stdout or "").strip()
    if not out:
        return False
    try:
        obj = json.loads(out)
    except ValueError:
        # some gates print a plain-text block reason to stdout with exit 0;
        # only JSON deny/block counts here, plain text alone does not block.
        return False
    if not isinstance(obj, dict):
        return False
    hso = obj.get("hookSpecificOutput")
    if isinstance(hso, dict) and hso.get("permissionDecision") == "deny":
        return True
    if obj.get("decision") == "block":
        return True
    return False


# ---------------------------------------------------------------------------
# Running a leg. Every leg is a NEW PROCESS that runs the gate as `__main__`,
# exactly as the harness spawns it, so module state, caches and env never leak
# from one leg into the next. What used to make that slow was not the gate: a
# fresh interpreter per leg re-ran startup, re-COMPILED the gate (a script run
# as `__main__` never gets a .pyc, and the arming-surface gate is 5,000 lines)
# and re-imported the stdlib, about 200 ms a leg before the gate read a byte.
# On Linux a leg is now a fork of this process: the stdlib stays imported and
# the gate's code object is compiled once. Everything else is held to what
# `subprocess.run([python, gate])` did, and the parity cases live in
# tests/test_gate_selftest_runner.py:
#   - the child gets its own pid, process group, env, cwd, stdin and pipes,
#     and re-imports every module from the gate's directory, so the gate's
#     caches start empty in every leg;
#   - its import path is the one a fresh interpreter computes under the LEG's
#     env: the user site follows the leg's HOME/PYTHONUSERBASE, and a leg whose
#     env changes any other PYTHON*/locale variable is spawned the old way;
#   - the deadline is the PARENT's, so a gate that installs its own SIGALRM
#     handler or calls alarm(0) cannot disarm it, and on expiry the whole
#     process group is killed and TimeoutExpired raised;
#   - the forked child is a small SUPERVISOR. It stays in this process's
#     group (where a spawned gate's parent is), becomes a child subreaper and
#     forks the gate as the leader of a new group, the leg's. It never reaps the
#     gate, so the gate's pid, which IS the leg's group id, cannot be recycled
#     while the supervisor lives. It exits, relaying the gate's exit status,
#     once the gate has exited and no live process of the leg's group is left
#     among its children (the subreaper adopts every orphan, so that is one
#     /proc read, not a scan). The parent sees that exit with waitid(WNOWAIT)
#     and reaps the supervisor after both pipes reached EOF (as subprocess.run
#     reads to EOF). At the deadline it signals the group and the gate by id
#     only while the supervisor is still alive; once the supervisor has exited
#     the group was empty, and nothing is signalled by an id that could have
#     been recycled. Waiting for the group is stricter than subprocess.run,
#     which would return while a grandchild that closed its pipes lingers. The
#     one gate-visible difference is the gate's parent pid, the supervisor's;
#   - a leg runs forked only while this interpreter starts like a fresh one:
#     the same sys.flags (-O, -I, -s, -E, -X utf8, -X dev ...), warning options
#     and -X options, read from the same one-time probe as the streams. If any
#     differs, every leg is spawned;
#   - non-daemon threads are joined and atexit runs before the exit, exit codes
#     map as CPython maps them (exit(-1) is 255, an unhandled KeyboardInterrupt
#     dies by SIGINT, a stdout closed by the gate is not a flush failure);
#   - only this runner's own children are waited on, never `waitpid(-1)`.
# Anywhere else (Windows has no fork, and macOS forbids it after some system
# frameworks load) the leg is the old `subprocess.run`, unchanged.
# ---------------------------------------------------------------------------
_FORK_OK = sys.platform.startswith("linux") and hasattr(os, "fork")
_CODE_CACHE: dict = {}
# Env names that change how a fresh interpreter starts. A leg that sets one of
# these differently from this process is spawned, not forked. PYTHONUSERBASE
# and HOME are handled in the child (they only move the user site).
_START_ENV = ("LANG", "LC_ALL", "LC_CTYPE")


class LegResult:
    """The fields of subprocess.CompletedProcess a selftest reads."""
    __slots__ = ("returncode", "stdout", "stderr")

    def __init__(self, returncode: int, stdout: str, stderr: str):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _script_code(script: str):
    code = _CODE_CACHE.get(script)
    if code is None:
        with open(script, "rb") as fh:
            src = fh.read()
        # dont_inherit: this module's own `from __future__ import annotations`
        # must not leak into the gate, which `python3 gate.py` never gives it.
        code = compile(src, script, "exec", dont_inherit=True)
        _CODE_CACHE[script] = code
    return code


def _needs_spawn(env: dict) -> bool:
    for k in set(env) | set(os.environ):
        if (k.startswith("PYTHON") and k != "PYTHONUSERBASE") or k in _START_ENV:
            if env.get(k) != os.environ.get(k):
                return True
    return False


def _user_site_for(env: dict):
    """The user site a fresh interpreter would use under `env`, or None.
    Mirrors site._getuserbase on POSIX: PYTHONUSERBASE if set and non-empty,
    else `~/.local` with `~` read from the env's HOME."""
    import site
    if not site.ENABLE_USER_SITE:
        return None
    base = env.get("PYTHONUSERBASE")
    if not base:
        home = env.get("HOME")
        if home is None:
            import pwd
            home = pwd.getpwuid(os.getuid()).pw_dir
        base = os.path.join(home, ".local")
    getp = getattr(site, "_get_path", None)
    if getp is not None:
        return getp(base)
    return os.path.join(base, "lib", "python%d.%d" % sys.version_info[:2],
                        "site-packages")


def _rebase_user_site(env: dict) -> None:
    """In the child: swap this process's user site for the leg's."""
    import site
    if not site.ENABLE_USER_SITE:
        return
    mine = getattr(site, "USER_SITE", None)
    theirs = _user_site_for(env)
    if mine == theirs:
        return
    my_base = os.path.realpath(site.USER_BASE or "") if site.USER_BASE else None

    def _mine(p: str) -> bool:
        if not p or not my_base:
            return False
        rp = os.path.realpath(p)
        return rp == my_base or rp.startswith(my_base + os.sep)

    idx = None
    kept = []
    for p in sys.path:
        if _mine(p):
            if idx is None:
                idx = len(kept)
            continue
        kept.append(p)
    if idx is None:
        # Where site.main() puts it: before the first system site dir.
        sysdirs = set(site.getsitepackages()) if hasattr(site, "getsitepackages") else set()
        idx = next((i for i, p in enumerate(kept) if p in sysdirs), len(kept))
    for name, mod in list(sys.modules.items()):
        f = getattr(mod, "__file__", None)
        if f and _mine(f):
            del sys.modules[name]
    head, tail = kept[:idx], kept[idx:]
    sys.path[:] = head
    if theirs and os.path.isdir(theirs):
        site.addsitedir(theirs)
    sys.path.extend(p for p in tail if p not in sys.path)
    site.USER_SITE = theirs
    if theirs and os.path.isdir(theirs):
        try:
            import usercustomize  # noqa: F401  (site.main does this too)
        except ImportError:
            pass


_PR_SET_CHILD_SUBREAPER = 36
_LIBC = None


def _libc():
    global _LIBC
    if _LIBC is None:
        try:
            import ctypes
            _LIBC = ctypes.CDLL(None, use_errno=True)
        except Exception:
            _LIBC = False
    return _LIBC


def _live_in_group(group: int) -> bool:
    """Whether a live (non-zombie) process of `group` is still a child of this
    supervisor. As a child subreaper it adopts every orphaned descendant, so its
    own children list covers the leg's tree. One small /proc read, not a scan."""
    me = os.getpid()
    try:
        with open("/proc/%d/task/%d/children" % (me, me)) as fh:
            kids = [int(x) for x in fh.read().split()]
    except OSError:
        kids = []
        for name in os.listdir("/proc"):
            if name.isdigit():
                try:
                    with open("/proc/%s/stat" % name, "rb") as fh:
                        f = fh.read().rsplit(b")", 1)[1].split()
                except OSError:
                    continue
                if int(f[1]) == me:
                    kids.append(int(name))
    for kid in kids:
        try:
            with open("/proc/%d/stat" % kid, "rb") as fh:
                f = fh.read().rsplit(b")", 1)[1].split()
        except OSError:
            continue
        if f[0] != b"Z" and int(f[2]) == group:
            return True
    return False


def _fork_child(script: str, code, leg: dict, fds: tuple, close: list,
                info_w: int) -> None:
    """Runs in the forked child, the leg's supervisor, and never returns.

    The supervisor stays in THIS process's group, as a spawned gate's parent
    would be, so a gate that reads or joins its parent's group sees what it saw
    before. It forks the gate as the leader of a new group (the leg's), tells
    the parent the gate's pid on `info_w`, and becomes a child subreaper so every
    orphaned descendant of the gate is adopted here. It never reaps the gate:
    the gate stays a zombie, which keeps its pid, and so the leg's group id,
    from being recycled while this supervisor lives."""
    try:
        fin, fout, ferr = fds
        os.dup2(fin, 0)
        os.dup2(fout, 1)
        os.dup2(ferr, 2)
        for fd in set(close) | {fin, fout, ferr}:
            if fd > 2:
                try:
                    os.close(fd)
                except OSError:
                    pass
        libc = _libc()
        if libc:
            libc.prctl(_PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0)
        gate = os.fork()
        if gate == 0:
            os.close(info_w)
            os.setpgid(0, 0)
            _gate_child(script, code, leg)
        try:
            os.setpgid(gate, gate)
        except OSError:
            pass  # the gate already did it, or already left
        os.write(info_w, str(gate).encode())
        os.close(info_w)
        # Only the gate and what it starts may hold the leg's pipes.
        for fd in (0, 1, 2):
            os.close(fd)
        while True:
            try:
                info = os.waitid(os.P_PID, gate, os.WEXITED | os.WNOWAIT)
                break
            except InterruptedError:
                continue
        import time
        while _live_in_group(gate):
            time.sleep(0.01)
        if info.si_code == os.CLD_EXITED:
            os._exit(info.si_status & 0xFF)
        import resource
        import signal
        sig = info.si_status
        try:
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        except (ValueError, OSError):
            pass
        try:
            signal.signal(sig, signal.SIG_DFL)
        except (OSError, ValueError, RuntimeError):
            pass
        os.kill(os.getpid(), sig)
    finally:
        os._exit(1)


def _gate_child(script: str, code, leg: dict) -> None:
    """Runs the gate as `__main__` in the supervisor's child; never returns."""
    rc = 1
    sigint = False
    try:
        import atexit
        import builtins
        import importlib.machinery
        import io
        import signal
        import traceback
        import types
        atexit._clear()  # the parent's handlers are not this process's
        # The gate's own streams are what a fresh interpreter would open,
        # whatever the leg says: a leg's encoding/errors describe how the
        # PARENT encodes the input and decodes the output, never how the gate
        # writes. A gate printing an unencodable character must crash here as
        # it crashes spawned.
        in_enc, in_err = _text_io("stdin")
        out_enc, out_err = _text_io("stdout")
        err_enc, err_err = _text_io("stderr")
        sys.stdin = sys.__stdin__ = io.TextIOWrapper(
            io.FileIO(0, "r", closefd=False), encoding=in_enc, errors=in_err)
        sys.stdout = sys.__stdout__ = io.TextIOWrapper(
            io.FileIO(1, "w", closefd=False), encoding=out_enc, errors=out_err)
        sys.stderr = sys.__stderr__ = io.TextIOWrapper(
            io.FileIO(2, "w", closefd=False), encoding=err_enc,
            errors=err_err, line_buffering=True)
        os.chdir(leg["cwd"])
        env = leg["env"]
        os.environ.clear()
        os.environ.update(env)
        # A fresh `python3 gate.py`: the script's directory first on sys.path,
        # argv naming only the script, the leg's own user site, and NO module
        # from the script's directory already imported, so every cache the
        # gate keeps starts empty.
        _rebase_user_site(env)
        here = os.path.dirname(os.path.realpath(script))
        for name, mod in list(sys.modules.items()):
            f = getattr(mod, "__file__", None)
            if f and os.path.dirname(os.path.realpath(f)) == here:
                del sys.modules[name]
        if not sys.path or sys.path[0] != here:
            sys.path.insert(0, here)
        sys.argv = [script]
        sys.orig_argv = [sys.executable, script]
        main = types.ModuleType("__main__")
        main.__file__ = script
        main.__cached__ = None
        main.__builtins__ = builtins
        main.__loader__ = importlib.machinery.SourceFileLoader("__main__", script)
        sys.modules["__main__"] = main
        try:
            exec(code, main.__dict__)
            rc = 0
        except SystemExit as exc:
            c = exc.code
            if c is None:
                rc = 0
            elif isinstance(c, int):
                rc = c
            else:
                print(c, file=sys.stderr)
                rc = 1
        except KeyboardInterrupt:
            traceback.print_exc()
            rc, sigint = 1, True
        except BaseException:
            traceback.print_exc()
            rc = 1
        # CPython's finalization order: join non-daemon threads, run atexit,
        # flush the std streams. A stream the gate closed is not a failure.
        try:
            if "threading" in sys.modules:
                sys.modules["threading"]._shutdown()
        except BaseException:
            pass
        try:
            atexit._run_exitfuncs()
        except BaseException:
            pass
        for s in (sys.stdout, sys.stderr):
            try:
                if not s.closed:
                    s.flush()
            except BaseException:
                if s is sys.stdout and rc == 0:
                    rc = 120
        if sigint:
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            os.kill(os.getpid(), signal.SIGINT)
    finally:
        os._exit(rc & 0xFF)


_PROBE: dict = {}
_PROBE_SRC = (
    "import sys, json; print(json.dumps({'streams': [[s.encoding, s.errors] "
    "for s in (sys.stdin, sys.stdout, sys.stderr)], 'flags': list(sys.flags), "
    "'warn': sys.warnoptions, 'x': sorted(map(str, sys._xoptions.items()))}))")


def _fresh() -> dict:
    """What a fresh `python3` started from this process's env looks like: the
    std streams it opens when they are pipes, as they are for every leg, and its
    interpreter flags. Asked of a real fresh interpreter once per process and
    env, never read off this one: a module imported here may have called
    `sys.stdout.reconfigure(errors="replace")` (many in scripts/ do), and this
    process may run under -O or -I. A leg whose env changes PYTHONIOENCODING,
    PYTHONUTF8 or the locale is spawned (_needs_spawn), so this process's env is
    the one that decides."""
    key = tuple(os.environ.get(k) for k in ("PYTHONIOENCODING", "PYTHONUTF8") + _START_ENV)
    got = _PROBE.get(key)
    if got is None:
        cp = subprocess.run([sys.executable, "-c", _PROBE_SRC], stdin=subprocess.PIPE,
                            capture_output=True, text=True, timeout=30)
        got = _PROBE[key] = json.loads(cp.stdout)
    return got


def _text_io(name: str):
    """(encoding, errors) a fresh interpreter opens this std stream with."""
    rows = _fresh()["streams"]
    return tuple(rows[("stdin", "stdout", "stderr").index(name)])


def _starts_like_fresh() -> bool:
    """True when this interpreter's flags and options equal a fresh one's, so a
    fork of it runs the gate as `python3 gate.py` would. Under `python3 -O` an
    `assert` in a gate is compiled away here and kept there, and that is a
    verdict, so any difference means every leg is spawned."""
    f = _fresh()
    return (list(sys.flags) == f["flags"] and list(sys.warnoptions) == f["warn"]
            and sorted(map(str, sys._xoptions.items())) == f["x"])


def _spawn(leg: dict) -> LegResult:
    kw = {}
    if leg.get("encoding"):
        kw = {"encoding": leg["encoding"], "errors": leg.get("errors") or "strict"}
    cp = subprocess.run([sys.executable, leg["script"]], input=leg["input"],
                        capture_output=True, text=True, cwd=leg["cwd"],
                        env=leg["env"], timeout=leg["timeout"], **kw)
    return LegResult(cp.returncode, cp.stdout, cp.stderr)


class _Leg:
    """What proc_group needs from a child: its pid and a per-pid kill. Once the
    child is reaped its pid may belong to someone else, so the per-pid kill
    becomes a no-op."""
    __slots__ = ("pid", "reaped")

    def __init__(self, pid: int, reaped: bool):
        self.pid = pid
        self.reaped = reaped

    def kill(self) -> None:
        if self.reaped:
            return
        import signal
        try:
            os.kill(self.pid, signal.SIGKILL)
        except OSError:
            pass


_PROC_GROUP = None


def _proc_group():
    """proc_group.py, loaded by path. The one guarded group-kill implementation
    lives there (a second copy is what its own test forbids). Loaded WITHOUT
    touching sys.path: every forked leg inherits this process's path, and a
    scripts/ entry added here would let a gate outside scripts/ import what a
    fresh interpreter could not."""
    global _PROC_GROUP
    if _PROC_GROUP is None:
        import importlib.util
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "proc_group.py")
        spec = importlib.util.spec_from_file_location("_gate_selftest_proc_group", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _PROC_GROUP = mod
    return _PROC_GROUP


def run_scripts(legs: list, workers: int = 1) -> list:
    """Run each leg and return a LegResult per leg, in the order given.

    A leg is a dict: script, input (str), cwd, env, timeout, and optionally
    encoding/errors for the text streams (default: the locale's, as
    `subprocess.run(text=True)` uses). `workers` > 1 runs that many legs at
    once, and is only for legs that share NOTHING a verdict reads; a leg that
    reads what an earlier one wrote must use 1. A leg past its timeout raises
    subprocess.TimeoutExpired, as subprocess.run does."""
    # Asked here, in the parent, so every fork inherits the answer instead of
    # each child spawning its own probe interpreter.
    if not _FORK_OK or not _starts_like_fresh():
        return [_spawn(leg) for leg in legs]

    import io
    import locale
    import selectors
    import time

    pg = _proc_group()
    _libc()
    results = [None] * len(legs)
    running = {}            # pid -> state dict
    sel = selectors.DefaultSelector()

    def _finish(pid: int) -> None:
        st = running.pop(pid)
        leg = legs[st["i"]]
        enc = leg.get("encoding") or locale.getpreferredencoding(False)
        errs = leg.get("errors") or "strict"
        out, err = (io.TextIOWrapper(io.BytesIO(bytes(st["buf"][fd])),
                                     encoding=enc, errors=errs).read()
                    for fd in st["order"])
        _, status = os.waitpid(pid, 0)      # the leader is reaped only now
        rc = -os.WTERMSIG(status) if os.WIFSIGNALED(status) else os.WEXITSTATUS(status)
        results[st["i"]] = LegResult(rc, out, err)

    def _kill(pid: int) -> None:
        st = running.get(pid)
        if st is None:
            return
        if not st["exited"]:
            st["exited"] = os.waitid(
                os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None
        if not st["exited"] and st["gate"]:
            # The supervisor is alive, so it has not exited and cannot have let
            # the gate be reaped: the gate's pid, which is the leg's group id,
            # still names THIS leg. Kill the group and the gate itself (it may
            # have left its group, and a spawned leg's timeout killed it).
            pg.kill_group(_Leg(st["gate"], False), group=st["gate"])
            _Leg(st["gate"], False).kill()
        # If the supervisor already exited, it saw the group empty and the gate
        # may since have been reaped by init: nothing of the leg's is signalled
        # by id any more. What still holds the pipes left the group on purpose.
        _Leg(pid, False).kill()             # the supervisor, ours to reap
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass
        for fd in list(st["fds"]):
            try:
                sel.unregister(fd)
            except (KeyError, ValueError):
                pass
            os.close(fd)
        st["fds"].clear()
        running.pop(pid, None)

    def _pump() -> None:
        now = time.monotonic()
        nearest = min(st["deadline"] for st in running.values())
        waiting_exit = any(not st["fds"] for st in running.values())
        tick = 0.002 if waiting_exit else 0.05
        events = sel.select(timeout=max(0.0, min(nearest - now, tick)))
        for key, _mask in events:
            fd = key.fd
            pid = key.data
            st = running[pid]
            chunk = os.read(fd, 65536)
            if chunk:
                st["buf"][fd] += chunk
            else:
                sel.unregister(fd)
                os.close(fd)
                st["fds"].discard(fd)
        for pid in list(running):
            st = running[pid]
            if not st["exited"]:
                # WNOWAIT: see the exit, leave the zombie, keep the pgid taken.
                st["exited"] = os.waitid(
                    os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None
            if st["exited"] and not st["fds"]:
                _finish(pid)
            elif time.monotonic() >= st["deadline"]:
                leg = legs[st["i"]]
                _kill(pid)
                raise subprocess.TimeoutExpired([sys.executable, leg["script"]],
                                                leg["timeout"])

    sys.stdout.flush()
    sys.stderr.flush()
    try:
        for i, leg in enumerate(legs):
            while len(running) >= max(1, workers):
                _pump()
            if _needs_spawn(leg["env"]):
                results[i] = _spawn(leg)
                continue
            script = leg["script"]
            code = _script_code(script)
            if not os.path.isdir(leg["cwd"]):
                raise FileNotFoundError(2, "No such file or directory", leg["cwd"])
            enc = leg.get("encoding") or locale.getpreferredencoding(False)
            errs = leg.get("errors") or "strict"
            with tempfile.TemporaryFile() as fin:
                fin.write(leg["input"].encode(enc, errs))
                fin.flush()
                fin.seek(0)
                out_r, out_w = os.pipe()
                err_r, err_w = os.pipe()
                close = [sel.fileno(), out_r, err_r]
                for st in running.values():
                    close.extend(st["fds"])
                info_r, info_w = os.pipe()
                close.append(info_r)
                pid = os.fork()
                if pid == 0:
                    _fork_child(script, code, leg, (fin.fileno(), out_w, err_w),
                                close, info_w)
                os.close(info_w)
                os.close(out_w)
                os.close(err_w)
                raw = b""
                while True:
                    chunk = os.read(info_r, 32)
                    if not chunk:
                        break
                    raw += chunk
                os.close(info_r)
                gate_pid = int(raw) if raw.strip().isdigit() else None
            timeout = leg.get("timeout")
            running[pid] = {
                "i": i, "gate": gate_pid, "exited": False,
                "fds": {out_r, err_r}, "order": (out_r, err_r),
                "buf": {out_r: bytearray(), err_r: bytearray()},
                "deadline": time.monotonic() + timeout if timeout else float("inf"),
            }
            sel.register(out_r, selectors.EVENT_READ, pid)
            sel.register(err_r, selectors.EVENT_READ, pid)
        while running:
            _pump()
    finally:
        for pid in list(running):
            _kill(pid)
        sel.close()
    return results

SELFTEST_SESSION = "__selftest__"
_KERNEL_RULE_RE = re.compile(r'^_KERNEL_RULE = "([^"]+)"', re.M)


def _prep_payload(raw_path: Path, fixture_dir: Path, sandbox: Path) -> str:
    """Load a fixture payload and rewrite a relative transcript_path to absolute."""
    data = json.loads(raw_path.read_text(encoding="utf-8"))
    tp = data.get("transcript_path")
    if isinstance(tp, str) and tp and not os.path.isabs(tp):
        data["transcript_path"] = str((fixture_dir / tp).resolve())
    # Every real harness payload carries a session_id; most fixtures predate the
    # v8 kernel and omit it, which silently turned the journal mirror inside each
    # gate into a no-op for the whole selftest. A gate cannot be proven to
    # journal its refusals by a leg whose payload names no process, so the same
    # id the env already advertises is filled in when the fixture has none.
    if not data.get("session_id"):
        data["session_id"] = SELFTEST_SESSION
    return json.dumps(data)


def _kernel_rule_of(script: Path) -> str:
    """The rule id a gate journals, read off its own `_KERNEL_RULE` constant."""
    try:
        m = _KERNEL_RULE_RE.search(script.read_text(encoding="utf-8"))
    except OSError:
        return ""
    return m.group(1) if m else ""


def _journaled_denies(sandbox: Path) -> list:
    """Every deny rule id in every journal the sandbox collected.

    Read back off disk rather than through the kernel library: the gates ran as
    subprocesses, so the file is the only evidence the mirror actually fired.
    Every journal, not just `__selftest__`: a fixture may carry its own
    session_id, and scoping the read to one pid would report "nothing journaled"
    for a gate that journaled correctly under the id its own fixture named.
    """
    jdir = sandbox / ".claude" / ".cache" / "kernel" / "journal"
    out = []
    try:
        paths = sorted(jdir.glob("*.jsonl"))
    except OSError:
        return []
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict) and rec.get("kind") == "deny":
                out.append(str(rec.get("rule") or ""))
    return out


def _run_leg(script: Path, payload: str, sandbox: Path) -> tuple[int, str]:
    env = dict(os.environ)
    for k in _OVERRIDE_ENV:
        env.pop(k, None)
    # git exports GIT_DIR / GIT_INDEX_FILE / GIT_WORK_TREE to its hooks; a leg
    # that runs git would then act on the LIVE repo. Strip them (see
    # brain_doctor.GIT_HOOK_ENV for the incident).
    for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_PREFIX",
              "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY", "GIT_NAMESPACE",
              "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_QUARANTINE_PATH"):
        env.pop(k, None)
    env["HOME"] = str(sandbox)
    env["USERPROFILE"] = str(sandbox)
    env["CLAUDE_SESSION_ID"] = "__selftest__"
    # One leg at a time: every leg of a gate shares this sandbox, and a later
    # leg reads what an earlier one left there (a spent receipt, a journal).
    cp = run_scripts([{"script": str(script), "input": payload,
                       "cwd": str(sandbox), "env": env, "timeout": 30,
                       "encoding": "utf-8", "errors": "replace"}], workers=1)[0]
    return cp.returncode, cp.stdout


def run_gate_selftest(script_path, fixture_dir) -> int:
    """Return 0 iff every violation blocks AND every benign allows. Prints one line."""
    script = Path(script_path).resolve()
    fdir = Path(fixture_dir)
    if not fdir.is_absolute():
        fdir = (Path(__file__).resolve().parent.parent / fdir).resolve()
    if not fdir.exists():
        print(f"selftest FAIL: fixture dir missing: {fdir}", file=sys.stderr)
        return 1

    violations = sorted(fdir.glob("violation*.json"))
    benigns = sorted(fdir.glob("benign*.json"))
    if not violations or not benigns:
        print(f"selftest FAIL: need violation*.json and benign*.json in {fdir}",
              file=sys.stderr)
        return 1

    sandbox = Path(tempfile.mkdtemp(prefix="gate-selftest-"))
    try:
        seed = fdir / "home"
        if seed.is_dir():
            shutil.copytree(seed, sandbox, dirs_exist_ok=True)
        failures = []
        rule = _kernel_rule_of(script)
        for vf in violations:
            rc, out = _run_leg(script, _prep_payload(vf, fdir, sandbox), sandbox)
            if not emits_block(rc, out):
                failures.append(f"{vf.name} did NOT block (rc={rc})")
        # v8 Phase 4: a gate that refuses must also RECORD the refusal. The
        # block/allow counts are unchanged; this is an extra assertion over the
        # legs that already blocked, and it applies only to a gate that declares
        # the rule it journals. Drift here would surface as an empty
        # `octo replay` after a real incident, which is the one moment nobody
        # can go back and re-run.
        if rule and not failures:
            journaled = _journaled_denies(sandbox)
            if not journaled:
                failures.append(f"{len(violations)} leg(s) blocked but nothing was "
                                f"journaled under {rule}")
            elif rule not in journaled:
                failures.append(f"journaled deny rule {journaled[0]!r} != {rule!r}")
        for bf in benigns:
            rc, out = _run_leg(script, _prep_payload(bf, fdir, sandbox), sandbox)
            if emits_block(rc, out):
                failures.append(f"{bf.name} WAS blocked (must allow, rc={rc})")
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)

    if failures:
        print("selftest FAIL: " + "; ".join(failures), file=sys.stderr)
        return 1
    print(f"selftest PASS: {len(violations)} block + {len(benigns)} allow "
          f"({script.name} vs {fdir.name})")
    return 0


if __name__ == "__main__":
    # Direct CLI: gate_selftest.py <script> <fixture_dir>
    if len(sys.argv) != 3:
        print("usage: gate_selftest.py <script.py> <fixture_dir>", file=sys.stderr)
        sys.exit(2)
    sys.exit(run_gate_selftest(sys.argv[1], sys.argv[2]))
