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
# On Linux a leg is now a fork of this process: the stdlib stays imported, the
# gate's code object is compiled once, and the child still gets its own pid,
# env, cwd, stdin and stdout, and re-imports every module from the gate's own
# directory, so the gate's caches start empty in every leg as they did before.
# Anywhere else (Windows has no fork, and macOS forbids it after some system
# frameworks load) the leg is the old `subprocess.run`, unchanged.
# ---------------------------------------------------------------------------
_FORK_OK = sys.platform.startswith("linux") and hasattr(os, "fork")
_CODE_CACHE: dict = {}


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


def _text_io(name: str):
    """(encoding, errors) a fresh interpreter would pick for this std stream:
    the same env decides it, so this process's own choice is the answer."""
    import locale
    stream = getattr(sys, "__%s__" % name, None)
    enc = getattr(stream, "encoding", None) or locale.getpreferredencoding(False)
    errs = getattr(stream, "errors", None) or "strict"
    return enc, errs


def _fork_child(script: str, code, cwd: str, env: dict, timeout: float,
                fds: tuple) -> None:
    """Runs in the forked child and never returns."""
    rc = 1
    try:
        import atexit
        import builtins
        import importlib.machinery
        import io
        import signal
        import traceback
        import types
        atexit._clear()  # the parent's handlers are not this process's
        signal.signal(signal.SIGALRM, signal.SIG_DFL)
        if timeout:
            signal.alarm(max(1, int(-(-timeout // 1))))
        fin, fout, ferr = fds
        os.dup2(fin, 0)
        os.dup2(fout, 1)
        os.dup2(ferr, 2)
        in_enc, in_err = _text_io("stdin")
        out_enc, out_err = _text_io("stdout")
        sys.stdin = sys.__stdin__ = io.TextIOWrapper(
            io.FileIO(0, "r", closefd=False), encoding=in_enc, errors=in_err)
        sys.stdout = sys.__stdout__ = io.TextIOWrapper(
            io.FileIO(1, "w", closefd=False), encoding=out_enc, errors=out_err)
        sys.stderr = sys.__stderr__ = io.TextIOWrapper(
            io.FileIO(2, "w", closefd=False), encoding=out_enc,
            errors="backslashreplace", line_buffering=True)
        os.chdir(cwd)
        os.environ.clear()
        os.environ.update(env)
        # A fresh `python3 gate.py`: the script's directory first on sys.path,
        # argv naming only the script, and NO module from that directory
        # already imported, so every cache the gate keeps starts empty.
        here = os.path.dirname(os.path.realpath(script))
        for name, mod in list(sys.modules.items()):
            f = getattr(mod, "__file__", None)
            if f and os.path.dirname(os.path.realpath(f)) == here:
                del sys.modules[name]
        if sys.path and sys.path[0] != here:
            sys.path.insert(0, here)
        sys.argv = [script]
        main = types.ModuleType("__main__")
        main.__file__ = script
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
        except BaseException:
            traceback.print_exc()
            rc = 1
        try:
            atexit._run_exitfuncs()
        except BaseException:
            pass
        for s in (sys.stdout, sys.stderr):
            try:
                s.flush()
            except BaseException:
                rc = rc or 120
    finally:
        os._exit(rc & 0xFF if rc >= 0 else 1)


def run_scripts(legs: list, workers: int = 1) -> list:
    """Run each leg and return a LegResult per leg, in the order given.

    A leg is a dict: script, input (str), cwd, env, timeout, and optionally
    encoding/errors for the text streams (default: the locale's, as
    `subprocess.run(text=True)` uses). `workers` > 1 runs that many legs at
    once, and is only for legs that share NOTHING on disk; a leg that reads what
    an earlier one wrote must use 1. A leg past its timeout raises
    subprocess.TimeoutExpired, as subprocess.run does."""
    if not _FORK_OK:
        out = []
        for leg in legs:
            kw = {}
            if leg.get("encoding"):
                kw = {"encoding": leg["encoding"], "errors": leg.get("errors") or "strict"}
            cp = subprocess.run([sys.executable, leg["script"]], input=leg["input"],
                                capture_output=True, text=True, cwd=leg["cwd"],
                                env=leg["env"], timeout=leg["timeout"], **kw)
            out.append(LegResult(cp.returncode, cp.stdout, cp.stderr))
        return out

    import io
    import locale
    results = [None] * len(legs)
    running = {}
    timed_out = []

    def _reap(block: bool) -> bool:
        pid, status = os.waitpid(-1, 0 if block else os.WNOHANG)
        if pid == 0 or pid not in running:
            return False
        i, files = running.pop(pid)
        leg = legs[i]
        enc = leg.get("encoding") or locale.getpreferredencoding(False)
        errs = leg.get("errors") or "strict"
        texts = []
        for fh in files[1:]:
            fh.seek(0)
            texts.append(io.TextIOWrapper(io.BytesIO(fh.read()), encoding=enc,
                                          errors=errs).read())
        for fh in files:
            fh.close()
        if os.WIFSIGNALED(status):
            rc = -os.WTERMSIG(status)
            if os.WTERMSIG(status) == 14:  # SIGALRM: the leg's own timeout
                timed_out.append(i)
        else:
            rc = os.WEXITSTATUS(status)
        results[i] = LegResult(rc, texts[0], texts[1])
        return True

    sys.stdout.flush()
    sys.stderr.flush()
    for i, leg in enumerate(legs):
        while len(running) >= max(1, workers):
            _reap(True)
        script = leg["script"]
        code = _script_code(script)
        if not os.path.isdir(leg["cwd"]):
            raise FileNotFoundError(2, "No such file or directory", leg["cwd"])
        enc = leg.get("encoding") or locale.getpreferredencoding(False)
        errs = leg.get("errors") or "strict"
        fin, fout, ferr = (tempfile.TemporaryFile() for _ in range(3))
        fin.write(leg["input"].encode(enc, errs))
        fin.flush()
        fin.seek(0)
        pid = os.fork()
        if pid == 0:
            _fork_child(script, code, leg["cwd"], leg["env"], leg["timeout"],
                        (fin.fileno(), fout.fileno(), ferr.fileno()))
        running[pid] = (i, (fin, fout, ferr))
    while running:
        _reap(True)
    if timed_out:
        leg = legs[timed_out[0]]
        raise subprocess.TimeoutExpired([sys.executable, leg["script"]], leg["timeout"])
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
    cp = subprocess.run(
        [sys.executable, str(script)],
        input=payload, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        cwd=str(sandbox), env=env, timeout=30,
    )
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
