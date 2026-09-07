#!/usr/bin/env python3
"""kernel_proc.py: the v8 PROCESS + JOURNAL library (docs/architecture/v8-kernel.md).

Two primitives, one file, stdlib only:

PROCESS - a locked JSON process table at ~/.claude/.cache/kernel/ptable.json.
    Same shape as the session registry (session-isolation-hook.py:52-75,
    octo-dim.py:52-62): read-modify-write under `fcntl.flock`, published with
    `os.replace` so a reader never sees a half-written table. Written from the
    register hooks only, never from the hot path (Phase 2 adds the one
    amortized exception, a lane claim on a first write).

JOURNAL - one append-only, hash-chained file per process at
    ~/.claude/.cache/kernel/journal/<pid>.jsonl. `append()` takes the lock on
    `<pid>.jsonl.lock`, reads the TAIL line, and derives `seq` and
    `prev = sha256(previous raw line)` from it, so the hot path never seeks to
    the head of the file. `start_ts` is copied forward on every line for the
    same reason: Phase 3 reads the elapsed wall time of a process from the one
    line it already holds. Writes go through O_APPEND, every line stays under
    4096 bytes (the POSIX atomic-append bound, trace-storage.md:77-93) and a
    line that would exceed it is truncated with a `trunc` marker rather than
    split.

Liveness (one definition, v8-kernel.md section 2, used by every gate):
    main process    live = own journal mtime, OR any child's journal mtime,
                    within TTL 900 s, so a parent waiting on a long child never
                    reads dead.
    subagent        live = no `exit` line AND parent live AND own journal mtime
                    within TTL, so a killed or hung child expires after 15
                    minutes and releases what it holds.

Import budget: this module is imported by the PreToolUse hot-path gate, so its
module-level imports are exactly json, os, sys, time, hashlib and fcntl (guarded
for Windows). No pathlib, no tempfile, no re, no subprocess: everything heavier
is imported inside the function that needs it, which is never a hot-path
function.

CLI: `python3 scripts/kernel_proc.py --selftest [fixture_dir]` runs the same
register-and-journal flow the register hooks prove, in a sandbox HOME.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time

try:
    import fcntl as _fcntl
    _HAS_FCNTL = True
except ImportError:  # Windows: no flock. O_APPEND still gives per-write atomicity.
    _HAS_FCNTL = False

# ── constants ────────────────────────────────────────────────────────────────

TTL = 900               # seconds; session-isolation-hook.py:48 uses the same window
FUTURE_SKEW = 120       # an mtime this far ahead of now is clock skew, not liveness
MAX_LINE = 4096         # POSIX atomic-append bound; the newline is counted below
PRUNE_AFTER = 7 * 24 * 3600
PID_MAX = 128
MAX_LANES = 512          # a lane list is a working set, not a history
_CORE_KEYS = ("seq", "ts", "start_ts", "pid", "kind", "prev")
_PID_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
KINDS = ("start", "tool", "exit", "deny", "receipt", "quota", "open", "release")
# What every reader prints for a process whose type the kernel never learned.
# `octo top` and `brain-digest` both walk the journal DIRECTORY, so both reach
# pids the ptable has no row for; defaulting those to "main" claimed twice over
# what is not known. One constant so the readers cannot drift apart.
UNKNOWN_TYPE = "?"

# A ptable a writer had to REPAIR is copied aside under this name before it is
# overwritten, one file per repair event, newest kept. It is the repair ledger:
# see `quarantines()` for why the record lives next to the file and not in a
# process journal.
QUARANTINE_PREFIX = "ptable.corrupt-"
MAX_QUARANTINE = 20

UNLOCK = ("export OCTO_KERNEL_OPEN=1 in the shell that launched Claude Code, "
          "then restart")


# ── paths (lazy: HOME is rebound by every sandbox selftest) ──────────────────

def brain_dir() -> str:
    return os.path.join(os.path.expanduser("~"), ".claude")


def kernel_dir() -> str:
    return os.path.join(brain_dir(), ".cache", "kernel")


def ptable_path() -> str:
    return os.path.join(kernel_dir(), "ptable.json")


def ptable_lock_path() -> str:
    return os.path.join(kernel_dir(), ".ptable.lock")


def journal_dir() -> str:
    return os.path.join(kernel_dir(), "journal")


def safe_pid(pid) -> str:
    """A pid reaches us from a hook payload, so it is untrusted text: keep it to
    one path segment. Anything outside [A-Za-z0-9._-] becomes '_' and the result
    is capped, so a crafted agent_id cannot escape the journal directory."""
    s = "".join(c if c in _PID_OK else "_" for c in str(pid))
    s = s.lstrip(".") or "unknown"
    return s[:PID_MAX]


def journal_path(pid) -> str:
    return os.path.join(journal_dir(), safe_pid(pid) + ".jsonl")


def lock_path(pid) -> str:
    return journal_path(pid) + ".lock"


def pending_path() -> str:
    return os.path.join(kernel_dir(), "open-pending.json")


# ── locking ─────────────────────────────────────────────────────────────────

def _flock(fh) -> None:
    if _HAS_FCNTL:
        _fcntl.flock(fh, _fcntl.LOCK_EX)


def _funlock(fh) -> None:
    if _HAS_FCNTL:
        try:
            _fcntl.flock(fh, _fcntl.LOCK_UN)
        except OSError:
            pass


# ── journal ─────────────────────────────────────────────────────────────────

def _dumps(rec: dict) -> bytes:
    return json.dumps(rec, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _tail_line(path: str) -> tuple:
    """(last raw line, file ends on a newline). b'' and True when absent or empty.

    Reads the last 8 KiB only: a line is capped at MAX_LINE, so that window
    always contains at least one whole line once the file is bigger than it.
    FileNotFoundError is the empty case; every other OSError propagates, because
    an unreadable journal is exactly what the gate must refuse to run without.

    The second element is what makes a torn write survivable. A process killed
    mid-append (or a short write) leaves a file that does NOT end on a newline,
    and an appender that ignores that glues its own record onto the fragment:
    one unreadable line, a reused seq, and a chain that never verifies again.
    Reporting the boundary lets append() terminate the fragment first.
    """
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            if size == 0:
                return b"", True
            window = min(size, 8192)
            fh.seek(size - window, os.SEEK_SET)
            chunk = fh.read(window)
    except FileNotFoundError:
        return b"", True
    parts = [p for p in chunk.split(b"\n") if p]
    return (parts[-1] if parts else b""), chunk.endswith(b"\n")


def _first_start_ts(path: str):
    """`start_ts` off line 0, or None. Only reached when the tail is unparseable:
    a torn line would otherwise reset start_ts for every line after it, which
    breaks the invariant the whole file rests on (and Phase 3 reads elapsed wall
    time from any single line). Reading the head is the slow path, and a torn
    tail is exactly where paying for it is right."""
    try:
        with open(path, "rb") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    rec = json.loads(raw.decode("utf-8", "replace"))
                except ValueError:
                    return None
                if isinstance(rec, dict) and rec.get("start_ts") is not None:
                    return float(rec["start_ts"])
                return None
    except OSError:
        return None
    return None


def _count_lines(path: str) -> int:
    n = 0
    try:
        with open(path, "rb") as fh:
            for _ in fh:
                n += 1
    except FileNotFoundError:
        return 0
    return n


def _fit(rec: dict) -> bytes:
    """Serialize under MAX_LINE (newline included), truncating payload fields.

    Shrinks the longest non-core string first, then drops non-core fields
    outright, and marks the line `trunc` the moment anything is lost. The core
    identity fields (seq, ts, start_ts, pid, kind, prev) are never touched: a
    truncated line still chains and still replays.
    """
    line = _dumps(rec)
    limit = MAX_LINE - 1
    if len(line) <= limit:
        return line
    rec = dict(rec)
    rec["trunc"] = True
    core = set(_CORE_KEYS) | {"trunc"}
    line = _dumps(rec)
    while len(line) > limit:
        strings = sorted(((len(v), k) for k, v in rec.items()
                          if k not in core and isinstance(v, str) and len(v) > 16),
                         reverse=True)
        if strings:
            k = strings[0][1]
            over = len(line) - limit
            keep = max(8, len(rec[k]) - over - 8)
            rec[k] = rec[k][:keep] + "..."
            line = _dumps(rec)
            continue
        extras = [k for k in rec if k not in core]
        if not extras:
            return _dumps({k: rec[k] for k in list(_CORE_KEYS) + ["trunc"] if k in rec})
        extras.sort(key=lambda k: len(_dumps({k: rec[k]})), reverse=True)
        rec.pop(extras[0])
        line = _dumps(rec)
    return line


def _write_all(fd: int, data: bytes) -> None:
    """os.write may write FEWER bytes than asked. Ignoring the return value is
    how a partial line reaches disk while the caller is told the append worked.
    Loop until every byte lands; a write that returns 0 is not progress, it is a
    failure, and the caller turns an OSError into a deny."""
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError(f"short write: {len(view)} byte(s) unwritten")
        view = view[written:]


def append(pid, record: dict) -> bytes:
    """Append one chained line to <pid>.jsonl and return the raw bytes written.

    Raises OSError when the journal cannot be created or written. That is the
    ONLY failure the hot-path gate turns into a deny, so it must reach the
    caller unswallowed.
    """
    os.makedirs(journal_dir(), exist_ok=True)
    path = journal_path(pid)
    now = float(record.get("ts") or time.time())
    fh = None
    try:
        fh = open(lock_path(pid), "a")
        _flock(fh)
        prev_raw, on_boundary = _tail_line(path)
        if prev_raw:
            prev_hash = hashlib.sha256(prev_raw).hexdigest()
            try:
                prev = json.loads(prev_raw.decode("utf-8", "replace"))
            except ValueError:
                prev = None
            if isinstance(prev, dict):
                seq = int(prev.get("seq", -1)) + 1
                start_ts = float(prev.get("start_ts") or record.get("start_ts") or now)
            else:
                # Corrupt tail: keep the chain honest (prev still points at the
                # bytes on disk) and recover seq by counting, the one slow path.
                # start_ts comes off line 0, not off `now`: letting a torn line
                # reset it would turn one damaged record into a file whose
                # elapsed time is wrong from there on.
                seq = _count_lines(path)
                start_ts = float(_first_start_ts(path) or record.get("start_ts") or now)
        else:
            prev_hash = None
            seq = 0
            start_ts = float(record.get("start_ts") or now)

        rec = {"seq": seq, "ts": round(now, 6), "start_ts": round(start_ts, 6),
               "pid": safe_pid(pid), "kind": str(record.get("kind") or "tool"),
               "prev": prev_hash}
        for k, v in record.items():
            if k not in ("seq", "ts", "start_ts", "pid", "kind", "prev"):
                rec[k] = v
        line = _fit(rec)
        # A file that does not end on a newline carries a torn record. Open the
        # new line with one, so the fragment closes as its own (unparseable)
        # line instead of swallowing this one. Recovery is precise and bounded:
        # verify_detail() names that line by index and keeps checking, because
        # the chain continues from its bytes like any other line. One damaged
        # record, locatable, never a silent break.
        payload = (b"" if on_boundary else b"\n") + line + b"\n"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            _write_all(fd, payload)
        finally:
            os.close(fd)
        return line
    finally:
        if fh is not None:
            _funlock(fh)
            try:
                fh.close()
            except OSError:
                pass


def read_journal(pid) -> list:
    """Parsed lines, oldest first. Unparseable lines come back as None."""
    out = []
    try:
        with open(journal_path(pid), "rb") as fh:
            for raw in fh:
                raw = raw.rstrip(b"\n")
                if not raw:
                    continue
                try:
                    out.append(json.loads(raw.decode("utf-8", "replace")))
                except ValueError:
                    out.append(None)
    except FileNotFoundError:
        return []
    return out


def verify_detail(pid) -> tuple:
    """(0, 'ok') when the chain is intact, else (1, every break it found).

    Checks, per line: it parses, `seq` increments from 0, `prev` is the sha256
    of the previous raw line (null on the first), and `start_ts` never moves.
    A line that does not parse is recorded and verification CONTINUES from its
    bytes, so a torn write reads as one named line rather than as "broken from
    here on". Return code stays 1: a journal with a torn line is damaged, and
    the point is to locate the damage, not to excuse it.
    """
    path = journal_path(pid)
    try:
        with open(path, "rb") as fh:
            raws = [r.rstrip(b"\n") for r in fh]
    except FileNotFoundError:
        return 1, f"no journal for {safe_pid(pid)}"
    raws = [r for r in raws if r]
    if not raws:
        return 1, f"empty journal for {safe_pid(pid)}"
    prev_raw = None
    start_ts = None
    breaks = []
    for i, raw in enumerate(raws):
        try:
            rec = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            rec = None
        if not isinstance(rec, dict):
            # A torn write, terminated in place by the next append. Report it by
            # index and keep verifying: the chain continues from these bytes, so
            # the damage stays one line instead of poisoning the rest.
            breaks.append(f"line {i} does not parse")
            prev_raw = raw
            continue
        if rec.get("seq") != i:
            breaks.append(f"line {i} carries seq {rec.get('seq')}")
        want = None if prev_raw is None else hashlib.sha256(prev_raw).hexdigest()
        if rec.get("prev") != want:
            breaks.append(f"line {i} prev {rec.get('prev')} != {want}")
        if start_ts is None:
            start_ts = rec.get("start_ts")
        elif rec.get("start_ts") != start_ts:
            breaks.append(f"line {i} start_ts moved to {rec.get('start_ts')}")
        prev_raw = raw
    if breaks:
        return 1, f"{len(breaks)} break(s): " + "; ".join(breaks[:4])
    return 0, f"{len(raws)} line(s) chain"


def verify(pid) -> int:
    """0 when the chain is intact, 1 otherwise. As an exit code:
       python3 -c "import sys,kernel_proc; sys.exit(kernel_proc.verify('<pid>'))"
    """
    return verify_detail(pid)[0]


# ── process table ───────────────────────────────────────────────────────────

def fresh_table() -> dict:
    """The table of a machine no hook has ever run on. Built here so the empty
    result and the repaired result cannot drift into two different shapes."""
    return {"version": 1, "processes": {}}


def _json_kind(value) -> str:
    """The JSON name of a Python value, for a fault message a human reads."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, float)):
        return "number"
    return type(value).__name__


def _shape_fault(data) -> str:
    """Name the TABLE-level shape that yielded no rows, and how many it swallowed.

    A row-level drop names the pid it lost. A table-level one cannot: nothing in
    a value that is not an object maps back to a pid. So it says what the file
    holds and how many values went with it, which is the whole difference
    between "one row is unreadable" and "every row on this machine just went
    missing".
    """
    if not isinstance(data, dict):
        return ("the ptable's top level is a %s, not an object"
                % _json_kind(data))
    if "processes" not in data:
        return "the ptable carries no `processes` key"
    procs = data["processes"]
    if isinstance(procs, list):
        return ("`processes` is an array of %d value(s), not an object"
                % len(procs))
    return "`processes` is a %s, not an object" % _json_kind(procs)


def sane_table(data) -> tuple:
    """(table, dropped, fault): the ONE place the ptable's SHAPE is decided.

    A row is a process only if it is an object. Every consumer in the kernel
    reads a row as `row.get(...)`, so one value that is not an object used to
    become an AttributeError in whichever reader reached it first, and the
    table is read in far more places than it is written. Deciding the shape
    once, here, is what keeps the readers from each needing their own guard.

    TWO levels, and they are not the same event, which is what QA cycle 3 found.
    `dropped` is per ROW: n rows lost, each named, the rest of the table intact
    and trustworthy. `fault` is per TABLE: `processes` is not an object at all,
    so the count of what was lost is unknown and NOTHING that comes back can be
    trusted as "the state of this machine". Returning `[]` for the second one
    made a total loss the quietest state in the kernel, quieter than losing one
    row, and it is the state where dropping is the WRONG answer: the isolation
    gates read this table to decide who owns a lane, and an empty table means
    "nobody owns anything".

    Returns what it lost, never a bare table: a repair nobody can see is its own
    failure mode, so `octo ps`, `octo top`, `brain_doctor` and both isolation
    gates say what went missing instead of quietly showing one row less, or
    none.
    """
    if not (isinstance(data, dict) and isinstance(data.get("processes"), dict)):
        return fresh_table(), [], _shape_fault(data)
    procs = data["processes"]
    dropped = [pid for pid, row in procs.items() if not isinstance(row, dict)]
    for pid in dropped:
        procs.pop(pid, None)
    return data, dropped, ""


def read_ptable_detail() -> tuple:
    """(table, dropped pids, fault). `read_ptable` for callers that must decide.

    DROPS a malformed row rather than raising, and the difference is the whole
    point. QA measured what one `"junk": "not-a-row"` value did to the kernel:
    `octo ps` and `octo top` exited 1, `brain_doctor` reported two kernel checks
    crashed, and worst of all `prune()` raised INSIDE the ptable lock, so both
    register hooks exited 0 having published nothing. A reflex that reports
    success while writing nothing is the failure this seam exists to stop; one
    unreadable row must never be able to take the whole kernel down with it.

    A FAULT is the other half, and it is not a drop. There is exactly one state
    in which an empty table is the truth: the file is not there, because no hook
    has ever run on this machine. Every other way of yielding zero rows - a file
    that is not JSON, a top level that is not an object, a `processes` that is
    an array, a file this process cannot open - is a machine whose process table
    was readable to somebody and is not readable to us. `_write_ptable`
    publishes a fully written temp file with `os.replace`, so the kernel itself
    can produce neither a half-written nor an oddly shaped table: a fault means
    a writer that is not the kernel touched the file. Callers that DECIDE on
    this table (the two isolation gates) must fail closed on it; callers that
    only display it must say it out loud.

    The row-level repair reaches the file on its own: every locked writer
    (`register`, `update_row`, `claim_lane`, `release_lanes`, `prune_locked`)
    reads through here and republishes what it read, so the bad row leaves on
    the next write, with the original preserved by `_publish`. A read never
    writes, and that now includes the quarantine copy.
    """
    try:
        with open(ptable_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return fresh_table(), [], ""     # the one honest empty table
    except ValueError as exc:
        return fresh_table(), [], "the ptable is not valid JSON (%s)" % exc
    except OSError as exc:
        return fresh_table(), [], "the ptable could not be read (%s)" % exc
    return sane_table(data)


def read_ptable() -> dict:
    """The lenient read, for callers that only look something up in the table.

    A caller that DECIDES on the table (a gate) or DISPLAYS it (a listing, the
    doctor) reads `read_ptable_detail` instead, because this one cannot tell a
    fresh machine from an unreadable one.
    """
    return read_ptable_detail()[0]


def quarantines() -> list:
    """[(mtime, path)] of every preserved copy of a repaired ptable, newest first.

    THIS is the repair record, and it is deliberately not a journal line. A
    journal belongs to a process: its mtime IS that process's liveness signal
    (`_own_fresh`), and a repair is a fact about the FILE, not about whichever
    hook happened to be holding the lock when it was noticed. Writing it into
    that hook's journal would attribute the event to the wrong thing and move a
    liveness clock for a reason unrelated to the process. Next to the file, one
    file per event, the count is a `listdir` instead of a walk over every
    journal on the machine, and the copy carries the lost rows so the operator
    can read what was there. `brain_doctor` escalates on the FREQUENCY of these,
    not on the presence of one: a table repaired once is an accident, a table
    repaired three times in a day is a writer that is still running.
    """
    try:
        names = os.listdir(kernel_dir())
    except OSError:
        return []
    out = []
    for name in names:
        if not (name.startswith(QUARANTINE_PREFIX) and name.endswith(".json")):
            continue
        path = os.path.join(kernel_dir(), name)
        mt = _mtime(path)
        if mt is not None:
            out.append((mt, path))
    out.sort(reverse=True)
    return out


def _quarantine(reason: str) -> str:
    """Copy the ptable aside, with the reason, before a writer overwrites it.

    Called from `_publish` only, so the copy is made at the moment the original
    is actually about to be replaced and never on a path that merely reads. The
    raw bytes go in as a STRING: the file being preserved is by definition one
    the parser could not handle, so re-encoding it as JSON would lose exactly
    the evidence worth keeping.

    Never raises. Preserving evidence must not be able to break the register
    hook that noticed the problem; that trade is the whole lesson of the row
    case above.
    """
    try:
        with open(ptable_path(), "rb") as fh:
            raw = fh.read()
    except OSError:
        return ""
    now = time.time()
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime(now)) + "%03d" % (int(now * 1000) % 1000)
    dst = os.path.join(kernel_dir(), "%s%s.json" % (QUARANTINE_PREFIX, stamp))
    # Two repairs inside one millisecond are two events, and one file for both
    # would undercount exactly the frequency the doctor escalates on.
    n = 0
    while os.path.exists(dst) and n < 100:
        n += 1
        dst = os.path.join(kernel_dir(), "%s%s-%d.json" % (QUARANTINE_PREFIX, stamp, n))
    try:
        with open(dst, "w", encoding="utf-8") as fh:
            json.dump({"ts": round(now, 6), "reason": reason,
                       "ptable": raw.decode("utf-8", "replace")}, fh, indent=2)
    except OSError:
        return ""
    for _, old in quarantines()[MAX_QUARANTINE:]:
        try:
            os.unlink(old)
        except OSError:
            pass
    return dst


def _publish(table: dict, dropped=(), fault: str = "") -> None:
    """Write the table, preserving first whatever the read had to repair.

    Every locked writer republishes what it read, which is how the repair
    reaches the file - and also how the evidence used to leave it. QA cycle 3:
    `octo ps` prunes on read, prune is a writer, so on any table with an old
    dead row in it (the normal steady state) `octo ps` silently rewrote the file
    without the corrupt row and the footer that was supposed to name it read
    `dropped == []`. The corruption event left zero trace and the doctor after
    it had nothing to report.

    So the copy is taken HERE, in the one function that replaces the file, and
    not at the read: a caller that reads and decides not to write leaves the
    evidence exactly where it was.
    """
    if fault or dropped:
        _quarantine(fault or "%d unreadable row(s) dropped: %s"
                    % (len(dropped), ", ".join(sorted(dropped)[:5])))
    _write_ptable(table)


def _write_ptable(data: dict) -> None:
    os.makedirs(kernel_dir(), exist_ok=True)
    tmp = ptable_path() + ".tmp.%d" % os.getpid()
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
        os.replace(tmp, ptable_path())
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _mtime(path: str):
    try:
        return os.stat(path).st_mtime
    except OSError:
        return None


def _own_fresh(pid, now: float, ttl: int) -> bool:
    mt = _mtime(journal_path(pid))
    if mt is None:
        return False
    age = now - mt
    return -FUTURE_SKEW <= age <= ttl


def has_trace(pid) -> bool:
    """True when the kernel already knows this pid: a journal file exists for it,
    or the ptable carries a row.

    An `exit` is an ENDING, and an ending must never be the thing that brings a
    process into existence. `append()` creates the journal when it is absent
    (that is right for the hot-path gate, whose call IS the process's first
    trace), so a SubagentStop for a pid that never registered and never ran a
    tool would otherwise materialise a whole process out of one line: a journal
    whose first and only record is an `exit` at seq 0, no `start`, no parent, no
    tool. The harness fires SubagentStop for agent ids that never produced a
    transcript, so this is not hypothetical (52 such files in one afternoon on
    the machine where it was measured).

    Journal first, ptable second: the stat is cheap and `register()` writes the
    journal BEFORE it publishes the row, so the journal is the earlier trace.
    The row is still checked, because a journal deleted underneath a live
    process must not turn its exit into a no-op.

    A trace has to be a trace of WORK, not just a name in a file. QA found two
    states that are not: a zero-byte journal, reachable only from a crash between
    the create and the first write, and a row whose value is not an object, which
    `pid in procs` accepts because membership tests the key alone. Both let an
    ending create the same phantom shape this guard exists to stop.
    """
    pid = safe_pid(pid)
    try:
        if os.path.getsize(journal_path(pid)) > 0:
            return True
    except OSError:
        pass
    row = (read_ptable().get("processes") or {}).get(pid)
    return isinstance(row, dict)


def has_exit(pid) -> bool:
    """True when the journal's tail carries an `exit` line. Tail-scoped on
    purpose: `exit` is written last, and a full read on every liveness probe
    would put the whole journal on the hot path."""
    path = journal_path(pid)
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            window = min(size, 16384)
            fh.seek(size - window, os.SEEK_SET)
            chunk = fh.read(window)
    except OSError:
        return False
    for raw in reversed([p for p in chunk.split(b"\n") if p]):
        try:
            rec = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("kind") == "exit":
            return True
    return False


def is_live(pid, table: dict = None, now: float = None, ttl: int = TTL,
            _seen: set = None) -> bool:
    """Liveness exactly as v8-kernel.md section 2 defines it."""
    pid = safe_pid(pid)
    now = time.time() if now is None else now
    table = read_ptable() if table is None else table
    procs = table.get("processes", {})
    if _seen is None:
        _seen = set()
    if pid in _seen:          # a cycle in ppid links: refuse to loop
        return False
    _seen.add(pid)

    entry = procs.get(pid) or {}
    ppid = entry.get("ppid")
    if ppid:
        # subagent: no exit line AND own journal fresh AND parent live
        if has_exit(pid):
            return False
        if not _own_fresh(pid, now, ttl):
            return False
        return is_live(ppid, table, now, ttl, _seen)

    # main process: own journal fresh, or ANY child's journal fresh
    if _own_fresh(pid, now, ttl):
        return True
    for child, ent in procs.items():
        if ent.get("ppid") == pid and _own_fresh(child, now, ttl):
            return True
    return False


def update_row(pid, fields: dict) -> bool:
    """Merge `fields` into one ptable row, under the same lock `register` takes.

    The row is the process's mutable half (the journal is the immutable one), so
    every later phase writes it through here: Phase 1a-2 marks a process exited,
    Phase 1b records a release, Phase 2 claims lanes. Returns False when the pid
    has no row, which is not an error: a child whose register hook lost its race
    still has a journal, and the journal is what the gates read. A HOME with
    no table at all returns False without creating the kernel dir or its lock.
    """
    pid = safe_pid(pid)
    if not os.path.exists(ptable_path()):
        return False
    os.makedirs(kernel_dir(), exist_ok=True)
    fh = None
    try:
        fh = open(ptable_lock_path(), "a")
        _flock(fh)
        table, dropped, fault = read_ptable_detail()
        procs = table.setdefault("processes", {})
        row = procs.get(pid)
        if row is None:
            # Includes the faulted table, where no row is readable at all: a
            # merge into a row we cannot see is not something to invent.
            return False
        row.update({k: v for k, v in fields.items() if v is not None})
        _publish(table, dropped, fault)
        return True
    finally:
        if fh is not None:
            _funlock(fh)
            try:
                fh.close()
            except OSError:
                pass


# ── lanes (v8 Phase 2 ISOLATION) ────────────────────────────────────────────
#
# A lane is a path one process has claimed by writing it. Lanes live in the
# ptable ROW (never in connectome/sessions.json: that registry is keyed by
# session, and two subagents of one session are ONE dimension to it, which is
# exactly the hole Phase 2 closes). Matching is equality or path prefix in
# EITHER direction, so `rm -rf <dir>` collides with a lane sitting under <dir>
# and a write to <dir>/x collides with a lane on <dir>.


def norm_path(path) -> str:
    """Absolute, normalized, `~` expanded. No resolve(): symlink resolution
    costs a stat per component on the hot path, and both sides of every
    comparison come through here, so they normalize the same way."""
    if not path:
        return ""
    return os.path.normpath(os.path.abspath(os.path.expanduser(str(path))))


def paths_conflict(a: str, b: str) -> bool:
    """True when two normalized paths name the same thing or one contains the
    other. The separator check is what keeps `/w/tree-b` out of `/w/tree`."""
    if not a or not b:
        return False
    if a == b:
        return True
    return a.startswith(b + os.sep) or b.startswith(a + os.sep)


def lanes_of(row: dict) -> list:
    lanes = (row or {}).get("lanes")
    return lanes if isinstance(lanes, list) else []


def lane_owner(path, table: dict = None, now: float = None, ignore=None,
               ttl: int = TTL) -> tuple:
    """(pid, row) of a LIVE process other than `ignore` whose lane conflicts
    with `path`; (None, None) when the path is free.

    Read-only and hot-path safe: one ptable read (or none, when the caller
    passes the table it already holds), then a liveness probe ONLY for the rows
    that actually collide. A dead holder owns nothing, which is what makes the
    TTL a release valve rather than a lock nobody can open.

    Passing the enclosing worktree root as `path` answers the whole-tree
    question too: a lane inside the root is a prefix match.
    """
    target = norm_path(path)
    if not target:
        return None, None
    table = read_ptable() if table is None else table
    now = time.time() if now is None else now
    skip = safe_pid(ignore) if ignore else None
    for pid, row in (table.get("processes") or {}).items():
        if pid == skip:
            continue
        if not any(paths_conflict(target, norm_path(l)) for l in lanes_of(row)):
            continue
        if is_live(pid, table, now, ttl):
            return pid, row
    return None, None


def holds_lane(pid, path, table: dict = None) -> bool:
    """True when `pid`'s own row already carries a lane covering `path`. The
    hot path calls this to decide whether a claim is NEW: an already-claimed
    path costs zero writes."""
    row = (table or read_ptable()).get("processes", {}).get(safe_pid(pid)) or {}
    target = norm_path(path)
    return any(paths_conflict(target, norm_path(l)) for l in lanes_of(row))


def claim_lane(pid, path, tree=None) -> bool:
    """Claim `path` (and, on the first write, the enclosing worktree `tree`) for
    `pid`. One flocked read-modify-write, taken ONLY when the caller has
    established the lane is new, so the cost is amortized once per path per
    process and never per write.

    Creates the row when the register hook lost its race with the first tool
    call (same-event hooks run in parallel): the row carries `registered_ts`, so
    prune's grace window keeps it while its journal is being opened.
    """
    pid = safe_pid(pid)
    target = norm_path(path)
    if not target:
        return False
    if not os.path.exists(ptable_path()):
        # No table on disk means no register hook has run on this machine yet.
        # Creating one HERE would publish a row from the hot path with no start
        # line behind it, which is the phantom `kernel-process-live` fails on.
        # Same contract as update_row: read-only when there is nothing to update.
        return False
    os.makedirs(kernel_dir(), exist_ok=True)
    fh = None
    try:
        fh = open(ptable_lock_path(), "a")
        _flock(fh)
        table, dropped, fault = read_ptable_detail()
        if fault:
            # FAIL CLOSED, same reasoning as the gate that called us. A claim is
            # the assertion "nobody else holds this path", and on a table we
            # could not read that assertion has no basis. Writing it anyway is
            # the F1 loss verbatim: the claim republishes a one-row table and
            # every other process's lanes are gone, granted to the claimant.
            return False
        procs = table.setdefault("processes", {})
        row = procs.get(pid)
        if row is None:
            row = {"pid": pid, "registered_ts": round(time.time(), 6)}
            procs[pid] = row
        lanes = list(lanes_of(row))
        if target not in lanes:
            lanes.append(target)
        if len(lanes) > MAX_LANES:
            del lanes[:-MAX_LANES]
        row["lanes"] = lanes
        if tree and not row.get("tree"):
            row["tree"] = norm_path(tree)
        _publish(table, dropped, fault)
        return True
    except OSError:
        return False       # an unclaimable lane must never break the write
    finally:
        if fh is not None:
            _funlock(fh)
            try:
                fh.close()
            except OSError:
                pass


def release_lanes(pid, reason: str = "release") -> int:
    """Drop every lane `pid` holds and return how many. Used by the delegate
    release (v8 Phase 2 D9): a process that spawns a child stops being the
    writer of the paths it claimed, otherwise a parent's lanes would bind its
    own children for the whole delegation and the gate would deny the work it
    was asked to do. The sibling rule is untouched: child A still cannot take
    child B's lane, and a parent lane claimed AFTER the spawn still binds.
    """
    pid = safe_pid(pid)
    if not os.path.exists(ptable_path()):
        return 0
    fh = None
    try:
        fh = open(ptable_lock_path(), "a")
        _flock(fh)
        table, dropped, fault = read_ptable_detail()
        row = (table.get("processes") or {}).get(pid)
        if not row:
            return 0
        n = len(lanes_of(row))
        if not n:
            return 0
        row["lanes"] = []
        _publish(table, dropped, fault)
        return n
    except OSError:
        return 0
    finally:
        if fh is not None:
            _funlock(fh)
            try:
                fh.close()
            except OSError:
                pass


def process_age(pid, now: float = None) -> float:
    """Seconds since this process last journaled, or -1 when it never has. The
    deny prints it, because "who holds this" is only actionable next to "for how
    long"."""
    mt = _mtime(journal_path(pid))
    if mt is None:
        return -1.0
    return max(0.0, (time.time() if now is None else now) - mt)


def prune(table: dict, now: float = None) -> int:
    """Drop process rows that are gone for good, and only those.

    Called from the register hooks only, never from the hot path. An
    exited-but-recent row is KEPT so `octo ps` can still show its exit status
    (Phase 1b).

    A row whose journal is ABSENT is kept while its `registered_ts` is younger
    than TTL. Without that grace window a concurrent register loses rows: ten
    SessionStart hooks firing at once each take the ptable lock in turn, and
    whichever one arrives while a sibling has published its row but not yet
    written its first journal line would delete that sibling outright
    (reproduced 9/10 rows kept). register() now writes the journal FIRST, which
    closes the window; this keeps it closed if a journal is deleted underneath
    a live process.
    """
    now = time.time() if now is None else now
    procs = table.get("processes", {})
    dead = []
    for pid, ent in procs.items():
        if not isinstance(ent, dict):
            # `read_ptable` already drops these, so this fires only for a table
            # a caller assembled by hand. It stays because prune mutates under
            # the ptable lock: raising here leaves the lock holder with an
            # unwritten table and its register hook exiting 0 having published
            # nothing, which is the exact silent failure the seam above names.
            dead.append(pid)
            continue
        mt = _mtime(journal_path(pid))
        if mt is None:
            registered = float(ent.get("registered_ts") or 0)
            if (now - registered) <= TTL:
                continue  # young row, journal not written (or just removed) yet
            dead.append(pid)
        elif (now - mt) > PRUNE_AFTER:
            dead.append(pid)
    for pid in dead:
        procs.pop(pid, None)
    prune_files(table, now)
    return len(dead)


def prune_files(table: dict, now: float = None) -> int:
    """Delete journal and `.lock` files older than PRUNE_AFTER whose pid is not
    live. Without this the kernel directory only ever grows: every session and
    every subagent leaves two files behind forever.

    Grouped BY PID, never file by file, and that is the fix for a real leak.
    `os.listdir` hands back `<pid>.jsonl.lock` before `<pid>.jsonl` half the
    time; removing the lock first and then taking `lock_path(pid)` again to
    remove the journal RE-CREATES the lock (open "a" creates), so the sweep
    left a fresh empty `.lock` behind for every pid it pruned, and the next
    sweep could not remove it either (its mtime was now young). One locked
    block per pid, journal unlinked first and the lock unlinked last while it
    is still held, closes it.

    Bounded and conservative. A pid is swept only when EVERY file it still owns
    is older than the retention window AND its process fails the liveness test,
    so no live writer can be racing it. Register path only, never the hot path.
    Errors are swallowed: cleanup that breaks a session is worse than a stale
    file.
    """
    now = time.time() if now is None else now
    jdir = journal_dir()
    removed = 0
    try:
        names = os.listdir(jdir)
    except OSError:
        return 0
    owned = {}
    for name in names:
        if name.endswith(".jsonl.lock"):
            pid, key = name[:-len(".jsonl.lock")], "lock"
        elif name.endswith(".jsonl"):
            pid, key = name[:-len(".jsonl")], "jsonl"
        else:
            continue
        owned.setdefault(pid, {})[key] = os.path.join(jdir, name)
    for pid, files in owned.items():
        ages = [_mtime(path) for path in files.values()]
        if any(mt is None or (now - mt) <= PRUNE_AFTER for mt in ages):
            continue
        try:
            if is_live(pid, table, now):
                continue
        except Exception:
            continue
        fh = None
        try:
            fh = open(lock_path(pid), "a")
            _flock(fh)
            # journal first; the lock file is the last thing to go, and it goes
            # while this process still holds it, so nothing re-creates it after.
            for key in ("jsonl", "lock"):
                path = files.get(key)
                if not path:
                    continue
                try:
                    os.unlink(path)
                    removed += 1
                except OSError:
                    pass
        except OSError:
            pass
        finally:
            if fh is not None:
                _funlock(fh)
                try:
                    fh.close()
                except OSError:
                    pass
    return removed


def prune_locked(now: float = None) -> int:
    """Take the ptable lock, prune, publish. Returns the number of rows dropped.

    `prune()` mutates a table a caller already holds under the lock (that is how
    `register` uses it). A reader that wants the same cleanup - `octo ps` prunes
    on read - needs the lock/read/prune/write cycle around it, and duplicating
    that cycle in the CLI would put a second ptable writer outside this module.
    """
    now = time.time() if now is None else now
    # Nothing to prune and nothing to create. `octo ps` prunes on read, and a
    # read must never be the thing that materialises `.cache/kernel/` on a HOME
    # that has never run a hook: the lock file it left behind made a fresh
    # install look like it had kernel state. Registering is what creates the
    # directory; reading is not.
    if not os.path.exists(ptable_path()):
        return 0
    os.makedirs(kernel_dir(), exist_ok=True)
    fh = None
    try:
        fh = open(ptable_lock_path(), "a")
        _flock(fh)
        table, unreadable, fault = read_ptable_detail()
        pruned = prune(table, now)
        if pruned:
            _publish(table, unreadable, fault)
        return pruned
    except OSError:
        return 0
    finally:
        if fh is not None:
            _funlock(fh)
            try:
                fh.close()
            except OSError:
                pass


def register(pid, entry: dict, start_record: dict = None) -> dict:
    """Open the process's journal with a `start` line, then publish its ptable row.

    JOURNAL FIRST, ptable second, and the order is the point. Published-then-
    written left a window where a sibling register (holding the ptable lock,
    running prune) saw a row with no journal file and deleted it; ten parallel
    SessionStart hooks kept 9 rows. Writing the start line first means the
    journal always exists before anything can judge the row by it.

    SessionStart fires on startup, resume, clear and compact, so a pid is
    registered more than once by design. Each registration appends its OWN
    `start` line carrying the `source` that caused it: a resumed session is
    visible in the journal instead of being silently folded into the first one,
    and `octo replay` can say where a run picked up. The ptable row is merged,
    not replaced, and `registered_ts` keeps the FIRST registration.

    Never assumes another hook ran first: same-event hooks run in parallel, and
    SubagentStart may lose the race with the child's own first tool call.
    """
    pid = safe_pid(pid)
    os.makedirs(kernel_dir(), exist_ok=True)

    rec = {"kind": "start"}
    rec.update(start_record or {})
    for k in ("ppid", "type", "worktree", "dim_worktree", "cwd", "source"):
        if entry.get(k):
            rec.setdefault(k, entry[k])
    append(pid, rec)

    fh = None
    try:
        fh = open(ptable_lock_path(), "a")
        _flock(fh)
        table, dropped, fault = read_ptable_detail()
        procs = table.setdefault("processes", {})
        prune(table)
        row = dict(procs.get(pid) or {})
        row.update({k: v for k, v in entry.items() if v not in (None, "")})
        row["pid"] = pid
        row.setdefault("registered_ts", round(time.time(), 6))
        procs[pid] = row
        # register PUBLISHES even on a faulted table, and that is the one writer
        # that must: a hook exiting 0 with no row on disk is the silent failure
        # this whole seam exists to stop. `_publish` keeps the original, so the
        # rows this write cannot carry forward are recoverable rather than gone.
        _publish(table, dropped, fault)
    finally:
        if fh is not None:
            _funlock(fh)
            try:
                fh.close()
            except OSError:
                pass
    return rec


# ── open mode (OCTO_KERNEL_OPEN) ────────────────────────────────────────────

def open_mode() -> bool:
    """Read from the hook's own process env only. A payload field never counts:
    the harness owns the env, the model owns the payload (the CLAUDE_SESSION_ID
    precedent, dimension-awareness-hook.py:98-105)."""
    v = os.environ.get("OCTO_KERNEL_OPEN", "").strip().lower()
    return v not in ("", "0", "false", "no", "off")


def pending_note(pid) -> None:
    """Count one tool call that ran while the journal was unwritable. Best
    effort by construction: the journal is already broken, so a failure here
    must not change the verdict."""
    pid = safe_pid(pid)
    now = round(time.time(), 6)
    try:
        os.makedirs(kernel_dir(), exist_ok=True)
        data = {}
        try:
            with open(pending_path(), "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (FileNotFoundError, ValueError, OSError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        row = data.get(pid) or {}
        row["count"] = int(row.get("count") or 0) + 1
        row.setdefault("first_ts", now)
        row["last_ts"] = now
        data[pid] = row
        tmp = pending_path() + ".tmp.%d" % os.getpid()
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, sort_keys=True)
        os.replace(tmp, pending_path())
    except Exception:
        return


def backfill_open(pid) -> bool:
    """Write the `open` line for calls that ran unjournaled, once the journal is
    writable again, and clear the pending row. One stat on the hot path when
    nothing is pending."""
    path = pending_path()
    if not os.path.exists(path):
        return False
    pid = safe_pid(pid)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, ValueError, OSError):
        return False
    if not isinstance(data, dict) or pid not in data:
        return False
    row = data.pop(pid) or {}
    append(pid, {"kind": "open", "count": int(row.get("count") or 0),
                 "first_ts": row.get("first_ts"), "last_ts": row.get("last_ts")})
    try:
        if data:
            tmp = path + ".tmp.%d" % os.getpid()
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, sort_keys=True)
            os.replace(tmp, path)
        else:
            os.unlink(path)
    except OSError:
        pass
    return True


# ── Phase 4: refusals and receipts ──────────────────────────────────────────

def journal_deny(rule_id, reason, tool_use_id=None, pid=None, **extra) -> bool:
    """Mirror one fail-closed refusal into the refusing process's journal.

    v8 Phase 4 (v8-kernel.md section 3). Every gate that denies calls this from
    its single deny emission point, so a run's REFUSALS are replayable next to
    the calls that were allowed. Before it, a deny reached nothing: the harness
    tells the model, PostToolUse never fires on a denied call, and the trace is
    "not an audit log" (trace-storage.md:121).

    FAIL-OPEN BY CONTRACT, and this is the whole safety argument for touching 13
    gates: every exception is swallowed and the function returns a bool the
    callers ignore. A journal that cannot be written must never turn a deny into
    an allow, nor an allow into a deny. The one place a journal error IS a
    verdict is `g__pretool__kernel.py`, which owns that rule and is not this.

    `pid` is resolved by the CALLER the same way the hot-path gate does
    (`resolve_pid`: payload agent_id else session_id), because only the caller
    holds the payload. A missing pid is a no-op, not a guess: writing a refusal
    into the wrong process's journal would be worse than not writing it.
    """
    try:
        pid = str(pid or "")
        if not pid:
            return False
        rec = {"kind": "deny", "rule": str(rule_id or "")}
        if tool_use_id:
            rec["tool_use_id"] = str(tool_use_id)
        if reason:
            rec["reason"] = str(reason)
        for k, v in (extra or {}).items():
            if k not in _CORE_KEYS and v is not None:
                rec[k] = v
        append(pid, rec)
        return True
    except Exception:
        return False


def journal_receipt(pid, kind, tool_use_id=None, record=None, ts=None) -> bool:
    """Mirror one v7 receipt into the process journal as {kind, ts, id, sha256}.

    The receipt itself stays in the ledger; this copies its IDENTITY only, so a
    replay can say "a seek receipt existed at this point in the run" without the
    journal turning into a second copy of the ledger. Same fail-open contract as
    `journal_deny`: a receipt is written by a PostToolUse reflex, and a journal
    error there must not break the reflex.
    """
    try:
        pid = str(pid or "")
        if not pid:
            return False
        try:
            blob = json.dumps(record, sort_keys=True, separators=(",", ":"),
                              ensure_ascii=True, default=str)
        except Exception:
            blob = str(record)
        rec = {"kind": "receipt", "receipt_kind": str(kind or ""),
               "receipt_sha256": hashlib.sha256(blob.encode("utf-8", "replace")).hexdigest()}
        if tool_use_id:
            rec["tool_use_id"] = str(tool_use_id)
        if ts is not None:
            rec["receipt_ts"] = str(ts)
        append(pid, rec)
        return True
    except Exception:
        return False


# ── helpers shared with the hooks ───────────────────────────────────────────

def input_hash(tool_input) -> str:
    """sha256 of the tool input. The journal records the HASH, never the
    content: a run stays verifiable and its verdicts reconstructible while the
    payload itself stays in the harness transcript (v8-kernel.md section 6)."""
    try:
        blob = json.dumps(tool_input, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, default=str)
    except Exception:
        blob = str(tool_input)
    return hashlib.sha256(blob.encode("utf-8", "replace")).hexdigest()


def enclosing_worktree_root(path: str):
    """Nearest ancestor holding a `.git` entry, or None. Pure path walk, no git
    spawn: this runs inside a hook (dimension-awareness-hook.py:310-319)."""
    p = os.path.abspath(path or ".")
    while True:
        if os.path.exists(os.path.join(p, ".git")):
            return p
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent


def resolve_pid(payload: dict) -> str:
    """pid = payload agent_id else session_id. One resolution order for the
    register hooks and the gate, so a child's tool line and its start line land
    in the same journal."""
    if not isinstance(payload, dict):
        return ""
    for key in ("agent_id", "session_id"):
        v = payload.get(key)
        if v:
            return str(v)
    return ""


# ── selftest ────────────────────────────────────────────────────────────────

def _scripts_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _fixture_dir(fixture_dir: str = None) -> str:
    root = os.path.dirname(_scripts_dir())
    fdir = fixture_dir or os.path.join("registry", "fixtures",
                                       "ARCHITECTURE.kernel-process")
    return fdir if os.path.isabs(fdir) else os.path.join(root, fdir)


def _sandbox_env(sandbox: str) -> dict:
    """A hook's env for a sandbox run: HOME rebound, open mode off, and every
    GIT_* variable a git hook exports stripped, so a selftest launched from
    pre-push never operates on the live repo (brain_doctor.py:47-56)."""
    env = dict(os.environ)
    for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_PREFIX",
              "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY", "GIT_NAMESPACE",
              "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_QUARANTINE_PATH",
              "OCTO_KERNEL_OPEN"):
        env.pop(k, None)
    env["HOME"] = sandbox
    env["USERPROFILE"] = sandbox
    env["CLAUDE_SESSION_ID"] = "__selftest__"
    return env


def _feed(script: str, payload: dict, sandbox: str, env: dict) -> tuple:
    """Run one hook script exactly as the harness does: payload on stdin."""
    import subprocess
    cp = subprocess.run([sys.executable, os.path.join(_scripts_dir(), script)],
                        input=json.dumps(payload), capture_output=True,
                        text=True, cwd=sandbox, env=env, timeout=30)
    return cp.returncode, cp.stdout


def selftest_flow(fixture_dir: str = None) -> int:
    """Prove the PROCESS primitive end to end in a sandbox HOME.

    Feeds the two register fixtures and three tool payloads carrying agent_id
    through the REAL hook scripts as subprocesses, then asserts: the ptable
    holds parent and child with the parent link and a worktree, the child's
    journal holds start + 3 tool lines, both chains verify, and both processes
    read live. Shared by the two register hooks and by this module's own
    --selftest so there is one implementation, not three.
    """
    import shutil
    import tempfile

    fdir = _fixture_dir(fixture_dir)
    if not os.path.isdir(fdir):
        print(f"selftest FAIL: fixture dir missing: {fdir}", file=sys.stderr)
        return 1

    sandbox = tempfile.mkdtemp(prefix="kernel-selftest-")
    saved = (os.environ.get("HOME"), os.environ.get("USERPROFILE"))
    failures = []
    try:
        seed = os.path.join(fdir, "home")
        if os.path.isdir(seed):
            shutil.copytree(seed, sandbox, dirs_exist_ok=True)

        env = _sandbox_env(sandbox)

        def feed(script: str, payload: dict) -> tuple:
            return _feed(script, payload, sandbox, env)

        with open(os.path.join(fdir, "start.json"), encoding="utf-8") as fh:
            start = json.load(fh)
        with open(os.path.join(fdir, "subagent_start.json"), encoding="utf-8") as fh:
            sub = json.load(fh)

        rc, _ = feed("r__session__proc-register.py", start)
        if rc != 0:
            failures.append(f"session register exited {rc}")
        rc, _ = feed("r__subagent-start__proc-register.py", sub)
        if rc != 0:
            failures.append(f"subagent register exited {rc}")

        parent = str(start.get("session_id") or "")
        child = str(sub.get("agent_id") or "")
        for i in range(3):
            rc, out = feed("g__pretool__kernel.py", {
                "session_id": parent, "agent_id": child,
                "tool_name": "Bash", "tool_use_id": f"toolu_selftest_{i}",
                "tool_input": {"command": f"echo {i}"}, "cwd": sandbox,
            })
            if rc != 0 or out.strip():
                failures.append(f"tool call {i} was not allowed silently (rc={rc})")

        # read the sandbox state through this very library
        os.environ["HOME"] = sandbox
        os.environ["USERPROFILE"] = sandbox
        table = read_ptable()
        procs = table.get("processes", {})
        if safe_pid(parent) not in procs:
            failures.append("ptable has no parent row")
        crow = procs.get(safe_pid(child)) or {}
        if not crow:
            failures.append("ptable has no child row")
        else:
            if crow.get("ppid") != safe_pid(parent):
                failures.append(f"child ppid {crow.get('ppid')} != {safe_pid(parent)}")
            if not crow.get("worktree"):
                failures.append("child row carries no worktree")
            if not crow.get("type"):
                failures.append("child row carries no agent type")
        lines = read_journal(child)
        kinds = [(l or {}).get("kind") for l in lines]
        if kinds != ["start", "tool", "tool", "tool"]:
            failures.append(f"child journal kinds {kinds} != start + 3 tool")
        for who, pid in (("child", child), ("parent", parent)):
            code, why = verify_detail(pid)
            if code != 0:
                failures.append(f"{who} chain broken: {why}")
        if not is_live(child, table):
            failures.append("child does not read live")
        if not is_live(parent, table):
            failures.append("parent does not read live")
    finally:
        os.environ["HOME"] = saved[0] or ""
        if saved[1] is None:
            os.environ.pop("USERPROFILE", None)
        else:
            os.environ["USERPROFILE"] = saved[1]
        shutil.rmtree(sandbox, ignore_errors=True)

    if failures:
        print("selftest FAIL: " + "; ".join(failures), file=sys.stderr)
        return 1
    print(f"selftest PASS: process registered, journal chained "
          f"(kernel_proc vs {os.path.basename(fdir)})")
    return 0


def selftest_exit_flow(fixture_dir: str = None) -> int:
    """Prove the exit line end to end in a sandbox HOME (v8 Phase 1a-2).

    Runs the whole life of one child through the REAL hooks: register the
    session, register the subagent, two tool calls, then SubagentStop. Asserts
    the `exit` line closes the chain with status ok, the tool count and a
    duration; that the meta.json fields are picked up from the session dir; that
    a second SubagentStop writes no second ending; and that a child whose last
    message opens with an error is recorded as `error`, not `ok`.

    Two legs guard the boundary an exit must not cross. A process whose journal
    was opened by the HOT-PATH GATE (first line a `tool`, no `start`, because
    its first call beat its own register hook) still gets its ending. A PHANTOM
    stop, an agent id with no journal and no row, creates nothing at all.
    """
    import shutil
    import tempfile

    fdir = _fixture_dir(fixture_dir)
    stop_seed = os.path.join(fdir, "subagent_stop.json")
    if not os.path.isfile(stop_seed):
        print(f"selftest FAIL: fixture missing: {stop_seed}", file=sys.stderr)
        return 1

    sandbox = tempfile.mkdtemp(prefix="kernel-exit-selftest-")
    saved = (os.environ.get("HOME"), os.environ.get("USERPROFILE"))
    failures = []
    try:
        seed = os.path.join(fdir, "home")
        if os.path.isdir(seed):
            shutil.copytree(seed, sandbox, dirs_exist_ok=True)
        env = _sandbox_env(sandbox)
        with open(os.path.join(fdir, "start.json"), encoding="utf-8") as fh:
            start = json.load(fh)
        with open(os.path.join(fdir, "subagent_start.json"), encoding="utf-8") as fh:
            sub = json.load(fh)
        with open(stop_seed, encoding="utf-8") as fh:
            stop = json.load(fh)
        parent = str(start.get("session_id") or "")
        child = str(sub.get("agent_id") or "")

        # the harness's own layout: <projects>/<slug>/<session>.jsonl next to
        # <projects>/<slug>/<session>/subagents/agent-<id>.{jsonl,meta.json}
        sess_dir = os.path.join(sandbox, "projects", "sandbox", parent)
        subs = os.path.join(sess_dir, "subagents")
        os.makedirs(subs, exist_ok=True)
        atp = os.path.join(subs, f"agent-{child}.jsonl")
        with open(atp, "w", encoding="utf-8") as fh:
            fh.write("")
        with open(atp[:-6] + ".meta.json", "w", encoding="utf-8") as fh:
            json.dump({"agentType": sub.get("agent_type"), "toolUseId": "toolu_seed",
                       "spawnDepth": 1, "model": "sonnet"}, fh)
        stop["transcript_path"] = sess_dir + ".jsonl"
        stop["agent_transcript_path"] = atp

        _feed("r__session__proc-register.py", start, sandbox, env)
        _feed("r__subagent-start__proc-register.py", sub, sandbox, env)
        for i in range(2):
            _feed("g__pretool__kernel.py", {
                "session_id": parent, "agent_id": child, "tool_name": "Bash",
                "tool_use_id": f"toolu_exit_{i}", "tool_input": {"command": "true"},
                "cwd": sandbox}, sandbox, env)
        rc, out = _feed("r__subagent-stop__proc-exit.py", stop, sandbox, env)
        if rc != 0 or out.strip():
            failures.append(f"exit hook was not silent (rc={rc})")
        _feed("r__subagent-stop__proc-exit.py", stop, sandbox, env)  # idempotent

        os.environ["HOME"] = sandbox
        os.environ["USERPROFILE"] = sandbox
        lines = [l for l in read_journal(child) if isinstance(l, dict)]
        exits = [l for l in lines if l.get("kind") == "exit"]
        if len(exits) != 1:
            failures.append(f"{len(exits)} exit line(s), a repeated SubagentStop must add none")
        if exits:
            e = exits[0]
            if e.get("status") != "ok" or e.get("ok") is not True:
                failures.append(f"exit status {e.get('status')} != ok")
            if e.get("tool_count") != 2:
                failures.append(f"tool_count {e.get('tool_count')} != 2")
            if not isinstance(e.get("duration"), (int, float)):
                failures.append("exit line carries no duration")
            if e.get("agent_transcript_path") != atp:
                failures.append("exit line does not carry the agent transcript path")
            if e.get("spawn_depth") != 1 or e.get("model") != "sonnet" \
                    or e.get("spawn_tool_use_id") != "toolu_seed":
                failures.append("meta.json fields (spawnDepth, model, toolUseId) not recorded")
        code, why = verify_detail(child)
        if code != 0:
            failures.append(f"chain broken after exit: {why}")
        row = (read_ptable().get("processes", {}).get(safe_pid(child)) or {})
        if not row.get("exited") or row.get("status") != "ok":
            failures.append(f"ptable row not marked exited: {row}")
        if is_live(child):
            failures.append("an exited child still reads live")

        # A failing child, in its own process so its exit is read alone. Its
        # journal is opened by the HOT-PATH GATE and never by a register hook:
        # that is the legitimate no-`start` process (a first tool call that beat
        # its own SubagentStart), and its ending must still be recorded.
        bad = dict(stop)
        bad["agent_id"] = child + "-bad"
        bad["agent_transcript_path"] = ""
        bad["last_assistant_message"] = "Error: the build did not compile."
        _feed("g__pretool__kernel.py", {
            "session_id": parent, "agent_id": bad["agent_id"], "tool_name": "Bash",
            "tool_use_id": "toolu_exit_bad", "tool_input": {"command": "true"},
            "cwd": sandbox}, sandbox, env)
        first = [l.get("kind") for l in read_journal(bad["agent_id"])
                 if isinstance(l, dict)]
        if first[:1] != ["tool"]:
            failures.append(f"the gate did not open the journal with a tool line: {first}")
        _feed("r__subagent-stop__proc-exit.py", bad, sandbox, env)
        bad_exits = [l for l in read_journal(bad["agent_id"])
                     if isinstance(l, dict) and l.get("kind") == "exit"]
        if not bad_exits or bad_exits[0].get("status") != "error":
            failures.append("a child reporting an error was not recorded as error")

        # A PHANTOM stop: an agent id the kernel never saw. The harness fires
        # SubagentStop for ids that never registered, never ran a tool and
        # never produced a transcript; `append()` creates the journal it writes
        # to, so recording that exit invented a whole process (a journal whose
        # only line is an exit at seq 0, no row, no parent, no tool). Nothing
        # must be created here, and the hook must still say nothing and exit 0.
        ghost = dict(stop)
        ghost["agent_id"] = child + "-ghost"
        rc, out = _feed("r__subagent-stop__proc-exit.py", ghost, sandbox, env)
        if rc != 0 or out.strip():
            failures.append(f"the phantom stop was not silent (rc={rc})")
        if os.path.exists(journal_path(ghost["agent_id"])):
            failures.append("an exit for an unknown pid created a journal")
        if safe_pid(ghost["agent_id"]) in (read_ptable().get("processes") or {}):
            failures.append("an exit for an unknown pid created a ptable row")
    finally:
        os.environ["HOME"] = saved[0] or ""
        if saved[1] is None:
            os.environ.pop("USERPROFILE", None)
        else:
            os.environ["USERPROFILE"] = saved[1]
        shutil.rmtree(sandbox, ignore_errors=True)

    if failures:
        print("selftest FAIL: " + "; ".join(failures), file=sys.stderr)
        return 1
    print(f"selftest PASS: exit line written once, chained, ptable marked "
          f"(proc-exit vs {os.path.basename(fdir)})")
    return 0


def _cli() -> int:
    if "--selftest" in sys.argv:
        i = sys.argv.index("--selftest")
        fixture = sys.argv[i + 1] if len(sys.argv) > i + 1 else None
        return selftest_flow(fixture)
    print(__doc__.strip().splitlines()[0])
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
