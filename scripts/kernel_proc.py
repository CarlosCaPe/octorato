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
import stat as _stat
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
#
# THREE bounds, not one. A count alone bounds the number of files and nothing
# else, and the multiplicand is chosen by whoever wrote the corrupt table: QA
# measured a 46.1 MB corrupt ptable producing a 47.7 MB copy, 245 MB peak RSS,
# 1.64 s of it inside the ptable lock, and a 20-file worst case near 954 MB. So
# the copy is capped per file, the ledger is capped in total, and the table
# itself is capped BEFORE it is parsed, which is what actually takes the big
# read out of the lock window (the parse ran under the lock too). And a copy
# expires on the journal window, because bounded by count and bytes alone a copy
# never expired at all: one corruption held the doctor at WARN forever.
QUARANTINE_PREFIX = "ptable.corrupt-"
MAX_QUARANTINE = 20                       # files
MAX_QUARANTINE_BYTES = 1024 * 1024        # of the original preserved per file
MAX_QUARANTINE_TOTAL = 8 * 1024 * 1024    # of ledger on disk, newest always kept
MAX_PTABLE_BYTES = 8 * 1024 * 1024        # past this the file is a fault, unparsed

# The key under which a table that could not be read carries its own fault
# forward. See `_faulted_table`: this is what keeps the gates fail-closed after
# a register hook publishes over an unreadable table.
FAULT_KEY = "_faulted"
MAX_FAULT_ROWS = 64                       # values carried under FAULT_KEY
MAX_FAULT_BYTES = 64 * 1024               # ... and the byte bound on them

# WHAT KIND OF FAULT, because until cycle 5 there was only one and it was the
# wrong one for most of them. `prune` wrote this key, `carried_fault` read it,
# and NOTHING in this file ever popped it: no `del`, no `pop`, on any path. So
# every fault behaved like the one class that has to be sticky (a table whose
# rows were lost, where only a human can say what was in it), including the
# ones whose whole content is a CONDITION that can go away. QA measured the
# consequence on the lost-lanes fault: `recovery()` says to delete the row, the
# operator deletes the row, the deny stays, and it denies a write to a tree no
# row on the machine ever touched. A permanent machine-wide lockout shipped by
# a change whose purpose is fail-closed safety.
#
# So a fault says what it is, and the reader re-derives the ones that can be
# re-derived:
#
#   latched           the table itself was unreadable. The rows are gone, their
#                     count is unknown, and nothing on disk can tell us what
#                     they held. Only a human clears it (`recovery()`), which is
#                     the F1 protection and stays exactly as sticky as it was.
#   lost-lanes        named rows hold lanes with no journal beside them. The
#                     rows ARE the evidence, so the fault is true exactly while
#                     they are there: remove them (or put the journals back) and
#                     it lifts on the next read.
#   journal-evidence  the journal directory cannot be used as evidence. True
#                     exactly while the directory is unusable.
#   zero-rows         the table lost its rows while named processes were
#                     running. True while any of them still reads live: once
#                     they are gone the lanes they held are moot, and this is
#                     what makes "the fault outlives the register" (F1) a bound
#                     rather than a life sentence.
#
# The bound each one carries is now the bound on the thing that PRODUCES the
# deny, which is the defect cycle 5 named: every bound this file claimed
# ("PRUNE_AFTER expires it") was a bound on the row, and the row was not what
# was denying.
FAULT_LATCHED = "latched"
FAULT_LOST_LANES = "lost-lanes"
FAULT_JOURNAL_EVIDENCE = "journal-evidence"
FAULT_ZERO_ROWS = "zero-rows"
MAX_FAULT_PIDS = 64                       # pids a condition fault re-derives on

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


def recovery(kind: str = "") -> str:
    """The way out of a faulted table, worded ONCE so the two gates, the two
    listings and the doctor cannot drift on it.

    It describes the state the operator is actually IN, which is the POST-
    register one, and QA cycle 3 F2 is why that had to be said. This text used
    to describe the file's PRE-register shape, and the deny it is attached to
    only persists into the shape AFTER a register: by the time a human reads
    it a SessionStart has almost certainly fired (startup, resume, clear,
    compact), `register` republished the table it read, so `processes` is a
    valid object again and "repair `processes` to an object" is a no-op. What
    was left of the instruction was "delete the `_faulted` key", which taken
    literally clears the deny AND discards every row the fault carried. QA
    followed it verbatim and reproduced the lane transfer this seam exists to
    prevent. So the rows are named where they actually are, `_faulted.rows`,
    the quarantine copy is named too (it was on no surface outside the doctor's
    three-in-24 h branch), and deleting the key alone is labelled with what it
    costs instead of reading as the cheap option.

    The `rm` half carries a second step now, which is the honest price of
    closing the deletion path (`_absent_table`): an absent table with a live
    journal beside it is itself a fault, so `rm` alone moves the machine from
    one faulted state to another until the next SessionStart writes a table or
    those journals age past the TTL. Stated here rather than discovered.

    NOT an `octo` subcommand and not an env hatch, and the reason is now what
    is TRUE rather than what was claimed. The claim was that a command an agent
    could run would be a command that clears its own gate. What the Bash gate
    actually verifies today is the direct file verbs: `rm`, `mv`, `cp`, `sed`,
    `tee`, `unlink`, `truncate` and a `>` redirect aimed at the kernel
    directory are denied, and so are `touch`, `chmod`, `chattr` and `dd`. The
    INTERPRETER PATH IS OPEN, and QA measured it: `python3 -c` is rescanned as
    shell text, so Python source that unlinks or rewrites this file is never
    seen, and `ln` is in no verb list at all, so `ln -sf` reaches the same
    path. Closing that is a real expansion of the gate's verb detection with
    its own false-positive risk and it is deliberately not this change. Until
    it lands the honest statement is: an agent that goes through an interpreter
    can still reach the kernel's state, which is a reason to keep the recovery
    out of its hands, not evidence that it already is.
    """
    latched = (
        "The table ITSELF was unreadable, so its rows are gone and their count "
        "is unknown: nothing on disk can say what they held, which is why this "
        "one is the class a human clears. By the time you read this a "
        "SessionStart has almost certainly run, so %(ptable)s is valid JSON "
        "again with a `%(key)s` key beside `processes`. Move whatever "
        "`%(key)s.rows` holds (it is null when the file left the reader nothing "
        "to carry) back into `processes`, then delete the `%(key)s` key, which "
        "is the only thing that lifts THIS one; deleting it WITHOUT restoring "
        "the rows lifts it just as well and forgets every lane it carried, so "
        "it is a choice, not a formality. Or `rm %(ptable)s` and move "
        "`%(jdir)s/*.jsonl` aside (or leave them untouched for %(ttl)ds), "
        "because an absent table with a live journal beside it is a fault too: "
        "the deny lifts once the next SessionStart rebuilds the table or those "
        "journals go quiet. Either way every lane held right now is forgotten "
        "until each process claims again."
    )
    lost_lanes = (
        "The fault names ROWS THAT HOLD LANES WITH NO JOURNAL. Delete those "
        "rows from `processes` in %(ptable)s, or put their journals back. Do "
        "NOT delete the `%(key)s` key for this one: here the row is the "
        "evidence, so clearing the key alone re-faults on the next prune. The "
        "deny is re-derived from those rows and lifts on the next read; it also "
        "lifts on its own once prune expires them, %(prune)ds after they "
        "registered."
    )
    journal_evidence = (
        "The fault names %(jdir)s. Put it back as a readable directory: restore "
        "it, remove whatever replaced it, or `chmod u+rx` it. There is no key "
        "to delete, the deny is re-derived from the directory and lifts on the "
        "next read. If it is GONE on a machine that has run hooks and there is "
        "nothing to restore, `rm -rf %(kdir)s` is the whole-cache reset, and "
        "that is the one state this cannot tell apart from a fresh install."
    )
    zero_rows = (
        "The table lost its rows while the processes the fault names were "
        "running, and nothing on disk holds what they were. The deny lifts when "
        "those processes exit or their journals under %(jdir)s go quiet for "
        "%(ttl)ds, by which time the lanes it is protecting are moot; to lift "
        "it sooner, delete the `%(key)s` key from %(ptable)s, which forgets "
        "every lane they held."
    )
    tail = (
        "The file as it was is preserved beside it as %(qdir)s%(qpre)s*.json, "
        "newest last by name; read that, and then deleting those copies is safe."
    )
    branches = {FAULT_LATCHED: latched, FAULT_LOST_LANES: lost_lanes,
                FAULT_JOURNAL_EVIDENCE: journal_evidence,
                FAULT_ZERO_ROWS: zero_rows}
    order = (FAULT_LATCHED, FAULT_LOST_LANES, FAULT_JOURNAL_EVIDENCE,
             FAULT_ZERO_ROWS)
    body = branches.get(kind) or " ".join(branches[k] for k in order)
    return ("Recovery, from a terminal where no hook fires. %s %s"
            % (body, tail)) % {
        "ptable": ptable_path(), "key": FAULT_KEY, "jdir": journal_dir(),
        "kdir": kernel_dir(), "ttl": TTL, "prune": PRUNE_AFTER,
        "qdir": os.path.join(kernel_dir(), ""), "qpre": QUARANTINE_PREFIX}


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


def _stat_kind(mode) -> str:
    """The name of what is at a path, for a fault message a human reads.

    No symlink row: the caller uses `os.stat`, which follows them, so a symlink
    reports whatever it points at (and a loop never gets here, it raises ELOOP
    one leg earlier). A name the mechanism cannot produce does not belong in a
    message that claims to say what was found.
    """
    for pred, name in ((_stat.S_ISDIR, "directory"), (_stat.S_ISFIFO, "fifo"),
                       (_stat.S_ISSOCK, "socket"), (_stat.S_ISCHR, "character device"),
                       (_stat.S_ISBLK, "block device")):
        if pred(mode):
            return name
    return "special file"


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


def _fault_rows(rows):
    """What of an unreadable `processes` is worth carrying in the table itself.

    Bounded twice, because the size of this value is chosen by whoever wrote the
    corrupt file, and it is about to be published into a table every gate reads
    on every call. The full original is never here: it is in the preserved copy
    beside the file, which is where evidence belongs. What is here is enough for
    the operator to repair by hand, and in the list-shaped case that is a lot,
    since every row is intact and each one carries its own `pid`.
    """
    if isinstance(rows, list):
        rows = rows[:MAX_FAULT_ROWS]
    try:
        blob = json.dumps(rows)
    except (TypeError, ValueError):
        return "unserializable"
    if len(blob) > MAX_FAULT_BYTES:
        return ("%d bytes of rows, too large to carry here; read the preserved "
                "copy" % len(blob))
    return rows


def _fault_carrier(reason: str, kind: str = FAULT_LATCHED, pids=(),
                   count: int = 0, rows=None) -> dict:
    """The value written under FAULT_KEY. One constructor, so the four writers
    of this key cannot drift on its shape and `fault_resolved` always has the
    two fields it re-derives on."""
    return {"reason": reason, "ts": round(time.time(), 6),
            "kind": kind or FAULT_LATCHED,
            "pids": [safe_pid(p) for p in list(pids)[:MAX_FAULT_PIDS]],
            "count": count, "rows": rows}


def fault_resolved(carrier, table=None) -> bool:
    """True when the CONDITION this fault names is measurably gone.

    The one thing missing from this file until cycle 5: a fault could be set and
    nothing anywhere removed it. Every bound the docstrings claimed for it
    ("still bounded: past PRUNE_AFTER it goes with everything else") bounded the
    ROW, and the row is not what produces the deny; QA aged a faulted row past
    PRUNE_AFTER and measured the row pruned, the lane free, `_faulted` still
    there and the deny still on.

    Re-derived, never trusted: the answer comes from the same evidence the fault
    came from (the rows, the journal directory, the journals), so a carrier an
    attacker writes by hand cannot claim to be resolved when it is not, and a
    carrier the kernel wrote clears the moment the operator does what
    `recovery()` says.

    `latched` is the class that does NOT re-derive, and it is the F1 protection:
    a table whose rows were lost stays faulted across as many registrations as
    it takes for a human to look, because nothing on disk can say what those
    rows held. Deleting the key is what clears it, and that is a choice with a
    price, which `recovery()` states.
    """
    if not isinstance(carrier, dict):
        return False
    kind = carrier.get("kind") or FAULT_LATCHED
    pids = carrier.get("pids") or []
    if kind == FAULT_LOST_LANES:
        # True exactly while a named row still holds lanes with no journal.
        # Removing the row (what `recovery()` prescribes) or restoring the
        # journal both lift it; so does prune expiring the row at PRUNE_AFTER,
        # which is the bound this fault was claimed to have and did not.
        procs = (table or {}).get("processes") or {}
        for pid in pids:
            row = procs.get(pid)
            if isinstance(row, dict) and lanes_of(row) \
                    and _mtime(journal_path(pid)) is None:
                return False
        return True
    if kind == FAULT_JOURNAL_EVIDENCE:
        return not journal_evidence_fault()
    if kind == FAULT_ZERO_ROWS:
        if journal_evidence_fault():
            return False
        now = time.time()
        for pid in pids:
            if _own_fresh(pid, now, TTL) and not has_exit(pid):
                return False
        return True
    return False


def fault_kind(table) -> str:
    """The kind of fault this table carries, or ''. The gates read it so the
    recovery they print is the one that works for the fault they hit."""
    carrier = table.get(FAULT_KEY) if isinstance(table, dict) else None
    if isinstance(carrier, dict) and carrier.get("reason"):
        return carrier.get("kind") or FAULT_LATCHED
    return FAULT_LATCHED if carrier else ""


def _faulted_table(data, reason: str, kind: str = FAULT_LATCHED,
                   pids=()) -> dict:
    """The table a reader hands back for a file it could not read: no processes,
    and the fault CARRIED so the next writer publishes it forward.

    This is QA cycle 2, F1, and it is the difference between a fix that lasts
    and one that lasts minutes. `register()` used to publish `fresh_table()`
    plus its own row, so the fault DISAPPEARED at the next SessionStart, and
    SessionStart fires on startup, resume, clear and compact. Measured: the gate
    denied the intruder while the table was faulted, one register hook later the
    table was valid again with one row in it, the same intruder was allowed, and
    the lane the other process held was transferred to it. Publishing the row
    the hook must write is right; publishing an EMPTY BASE under it is not.

    So the fault travels with the table. Ownership stays UNKNOWN - the rows here
    are evidence, never owners, and nothing reads them as lanes - which is what
    keeps both gates fail-closed across as many registrations as it takes for
    the operator to look. `recovery()` is the way out, and it is a file
    operation on purpose.

    QA named two options and this is the second, because it CONTAINS the first:
    a table carrying this key reports a fault on every read, so it is sticky
    until a human clears it, and on top of that the rows are still here. That
    matters for the recovery that keeps information: in the list-shaped case
    nothing is missing from the file, every row is intact and each one carries
    its own `pid`, so an operator who repairs `processes` by hand keeps the
    ownership a `rm` would forget. A bare sticky flag would deny just as hard
    and leave the operator nothing to repair from.
    """
    table = fresh_table()
    rows = data.get("processes") if isinstance(data, dict) and "processes" in data else data
    count = len(rows) if isinstance(rows, (list, dict, str)) else (0 if rows is None else 1)
    table[FAULT_KEY] = _fault_carrier(reason, kind, pids, count,
                                      _fault_rows(rows))
    return table


def carried_fault(data) -> str:
    """The fault a previous writer carried forward in this table, or ''.

    A table whose shape is fine again is still not a table anyone can trust
    while this key is in it: the rows it lost were never recovered, so every
    lane on the machine is still unaccounted for. Sticky by construction for a
    LATCHED fault, since every writer republishes what it read.

    Sticky is not the same as permanent, and cycle 5 is why the difference had
    to be written down. A CONDITION fault (`fault_resolved`) is re-derived here
    on every read, so the deny lifts the moment its condition is measurably
    gone: the row deleted, the journal directory restored, the processes that
    were running when the table lost its rows finished. Before this, nothing in
    the file removed this key on any path, so an F4 fault survived the very
    repair `recovery()` prescribes and denied every hooked write on the machine
    for good.
    """
    carrier = data.get(FAULT_KEY) if isinstance(data, dict) else None
    if isinstance(carrier, dict) and carrier.get("reason"):
        if fault_resolved(carrier, data):
            return ""
        kind = carrier.get("kind") or FAULT_LATCHED
        tail = ("the rows it lost are still unaccounted for"
                if kind == FAULT_LATCHED
                else "still true when this table was last read")
        return ("%s (carried in `%s` since %s, kind `%s`: %s)"
                % (carrier["reason"], FAULT_KEY,
                   time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                 time.gmtime(carrier.get("ts") or 0)),
                   kind, tail))
    if carrier:
        return "the ptable carries an unresolved fault under `%s`" % FAULT_KEY
    return ""


def _readable_row(row) -> bool:
    """True when a row is one the kernel could have written, LANES INCLUDED.

    `isinstance(row, dict)` used to be the whole test, and QA cycle 4 F6
    measured what that let through: `lanes` as a string, as `null`, or as a list
    of numbers, on a row that was otherwise perfect. `lanes_of` coerced every one
    of those to `[]` and `norm_path` swallowed the elements, so the row kept its
    pid, its type and its worktree, appeared in every listing as a healthy
    process, and silently forfeited every path it held: no drop, no fault,
    nothing on any surface, and both gates allowed an intruder onto the lane.

    A row whose lanes cannot be read is a row whose OWNERSHIP cannot be read,
    and ownership is the one field the isolation gates ask this table for. So it
    is dropped like any other unreadable row, which is what puts it on the
    surfaces (`octo ps`, the doctor, the quarantine copy) and makes the gates
    fail closed on it.

    An ABSENT `lanes` is readable: that is a process that holds nothing yet, and
    it is the shape of every row between `register` and the first write. A
    `lanes` that is PRESENT and null is not the same thing and is not readable,
    which is why the test is `in` and not `.get()`: `row.get("lanes")` returns
    None for both, and `"lanes": null` is a shape the kernel never writes
    (`claim_lane` writes a list, `register` merges no None values), so it is a
    foreign writer's row wearing the fresh row's answer.
    """
    if not isinstance(row, dict):
        return False
    if "lanes" not in row:
        return True
    lanes = row["lanes"]
    if not isinstance(lanes, list):
        return False
    return all(isinstance(lane, str) and lane for lane in lanes)


def sane_table(data) -> tuple:
    """(table, dropped, fault): the ONE place the ptable's SHAPE is decided.

    A row is a process only if `_readable_row` says so: an object, and one whose
    `lanes` can be read as lanes. Every consumer in the kernel reads a row as
    `row.get(...)`, so one value that is not an object used to become an
    AttributeError in whichever reader reached it first, and the table is read
    in far more places than it is written. Deciding the shape once, here, is
    what keeps the readers from each needing their own guard.

    TWO levels, and they are not the same event, which is what QA cycle 1 found.
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

    A fault SURVIVES the write that follows it (`_faulted_table`), so a table
    whose shape is healthy again still reports one while it carries the key: the
    rows are gone either way, and a gate that stops denying because a hook wrote
    a row is a gate that protects for the length of one SessionStart.
    """
    if not (isinstance(data, dict) and isinstance(data.get("processes"), dict)):
        fault = _shape_fault(data)
        return _faulted_table(data, fault), [], fault
    procs = data["processes"]
    dropped = [pid for pid, row in procs.items() if not _readable_row(row)]
    for pid in dropped:
        procs.pop(pid, None)
    return data, dropped, carried_fault(data)


def live_journal_pids(now: float = None, limit: int = 8, ignore=None) -> list:
    """Pids the JOURNALS say are live, read WITHOUT the process table.

    This is the one question the table cannot answer: whether a table that is
    not there is telling the truth. It applies the two halves of the liveness
    definition (v8-kernel.md section 2) that need no table, a journal mtime
    inside the TTL and no `exit` line, and skips the third, that a subagent's
    parent must be live too. Skipping it can only read live where `is_live`
    would read dead, and that direction is the safe one here: this decides
    whether a missing table is a fresh install or a loss, and calling a loss a
    fresh install is exactly the failure being closed.

    Off the hot path by construction. It is reached only when `ptable.json` is
    not there, which on a working machine happens once, before the first
    register. `limit` stops the walk as soon as there is enough to answer,
    because the caller needs "is anything alive here", not a census, and the
    number of files in that directory is chosen by whoever writes them.

    `ignore` is the one pid that proves nothing, and `register` is the only
    caller that has one. It writes its journal BEFORE it takes the ptable lock
    (deliberately: published-then-written left a window where a sibling prune
    deleted a row whose journal did not exist yet), so on a machine that has
    genuinely never run a hook the first register reads an absent table with
    its own brand-new journal beside it. Counting that would make every fresh
    install fault on its first SessionStart and deny every write on it
    afterwards, which is a worse failure than the one being closed. A journal
    this very call just created is not evidence that somebody ELSE is running.
    """
    now = time.time() if now is None else now
    skip = {safe_pid(ignore)} if ignore else set()
    try:
        names = os.listdir(journal_dir())
    except OSError:
        # "I could not walk the evidence" is NOT "there is no evidence", and
        # this leg must never be the one that decides. It stays permissive on
        # purpose: `_zero_rows_fault` asks `journal_evidence_fault()` FIRST, so
        # an unreadable journal directory has already faulted before anybody
        # reaches here. QA cycle 4 F3 is why the order matters: the deletion
        # guard's evidence lives in the directory the attacker is deleting.
        return []
    out = []
    for name in sorted(names):
        if not name.endswith(".jsonl"):
            continue
        pid = name[:-len(".jsonl")]
        if pid in skip:
            continue
        # mtime first: it is one stat, and it rejects almost everything. The
        # exit check reads a 16 KB tail, so it only ever runs on a fresh one.
        if not _own_fresh(pid, now, TTL):
            continue
        if has_exit(pid):
            continue
        if not has_work_trace(pid):
            # C3, and it uses this file's own doctrine (`has_trace`: a trace has
            # to be evidence of WORK). A journal carrying a `start` line and
            # nothing else belongs to a process that has claimed no lane, because
            # `claim_lane` is what creates a row and it runs off a tool call. So
            # it is not evidence that this machine lost a record of who holds
            # what, and counting it produced a fault that was false AND (before
            # `fault_resolved`) permanent: two SessionStart hooks on a table-less
            # machine, `register` writing its journal before it takes the ptable
            # lock, and the sibling's brand-new start line reading live. The
            # trigger is a first run with two terminals, and it is the state the
            # documented `rm ptable.json` recovery puts the machine into, so the
            # recovery could loop. It weakens nothing real: two registers
            # serialize on the ptable lock, so the second one reads the first
            # one's published row instead of losing it, and a process that HAS
            # worked carries a `tool` line that cannot be forged without breaking
            # the hash chain.
            continue
        out.append(pid)
        if limit and len(out) >= limit:
            break
    return out


def _kernel_has_history() -> bool:
    """True when this HOME has run a hook before, decided WITHOUT the two things
    an attacker deletes (`ptable.json` and the journals).

    Every locked writer opens `.ptable.lock` with mode "a", and nothing in the
    kernel ever removes it, so its presence is the cheapest honest answer to
    "has a register hook ever run here". The test is deliberately wider than
    that one name: any entry in the kernel directory that is neither the table
    nor the journal directory nor a `.tmp.` file from an interrupted publish is
    history, so a quarantine copy or `open-pending.json` counts too and a file a
    later phase adds counts without anyone remembering to list it here.

    A machine that never ran a hook has no kernel directory at all, because
    `register` is what creates it and every read path refuses to (`prune_locked`
    and `claim_lane` return early on an absent table for exactly this reason).
    """
    kdir = kernel_dir()
    try:
        names = os.listdir(kdir)
    except OSError:
        return False
    for name in names:
        if name in ("ptable.json", "journal") or ".tmp." in name:
            continue
        return True
    return False


def journal_evidence_fault() -> str:
    """'' when the journals can be used as evidence, else why they cannot.

    QA cycle 4 F3: the deletion guard reads the journals to decide whether an
    absent table is a fresh install or a loss, and the journals live in a
    directory the same attacker can reach. Measured ALLOW on both gates for all
    three of `rm ptable.json && rm -rf journal/`, `rm ptable.json && chmod 000
    journal/`, and `rm ptable.json` with `journal/` replaced by a regular file:
    `live_journal_pids` returned `[]` on the OSError and `[]` reads as "nothing
    is running here".

    Two of those three are unambiguous and fault unconditionally: a directory
    that exists and cannot be walked, or a non-directory where the journals
    belong, is a state the kernel cannot produce. The third, a directory that is
    simply GONE, is the one that genuinely looks like a fresh install, so it
    faults only when `_kernel_has_history()` says hooks have run on this HOME.

    The residual is real and is not hidden: an attacker who removes the whole
    kernel directory, `.ptable.lock` included, leaves a HOME that is
    byte-for-byte a wiped cache, and no reader can tell those apart from inside.
    That is a strictly larger move than the one this closes, and it is stated in
    `docs/architecture/v8-kernel.md` rather than left to be discovered.

    ASKED ON EVERY READ SINCE CYCLE 5, not only on the zero-rows path, and that
    is M2. A journal directory that is gone, replaced by a file, unreadable or
    swept is reachable by any cache sweep over `~/.claude/.cache`, and with an
    INTACT table it used to produce a LANE deny naming a pid as "never
    journaled" and advising the operator to wait for a process to exit that the
    message could not see was unmeasurable. The state was denied, correctly, and
    described wrongly, which for a fail-closed gate is most of the cost.

    Three syscalls, no directory read, because it now runs on the hot path: a
    `stat` (existence and type), and an `access` for the permission case. The
    old `os.listdir` had to enumerate a directory whose size is chosen by
    whoever writes it, and it also keyed the non-directory case on
    NotADirectoryError, which is the same "decide on the syscall, not on the
    result" shape this whole seam exists to remove.
    """
    jdir = journal_dir()
    try:
        st = os.stat(jdir)
    except FileNotFoundError:
        if not _kernel_has_history():
            return ""          # a HOME no hook has ever run on
        return ("the journal directory %s is gone on a machine whose kernel "
                "state says hooks have run here, so the only record of what is "
                "running was removed along with the process table" % jdir)
    except OSError as exc:
        return ("the journal directory %s cannot be read (%s), so whether "
                "anything is running on this machine is unknowable" % (jdir, exc))
    if not _stat.S_ISDIR(st.st_mode):
        return ("the journal directory %s cannot be read (it is a %s, not a "
                "directory), so whether anything is running on this machine is "
                "unknowable" % (jdir, _stat_kind(st.st_mode)))
    if not os.access(jdir, os.R_OK | os.X_OK):
        return ("the journal directory %s cannot be read (permission denied), "
                "so whether anything is running on this machine is unknowable"
                % jdir)
    # `_any_journal` FIRST: it stops at the first `.jsonl`, so a healthy
    # machine pays one directory batch and `_kernel_has_history` (a listdir
    # of the kernel directory) only runs on the empty case this is about.
    if not _any_journal(jdir) and _kernel_has_history():
        # M1, and it is the same "keyed on the syscall, not on the result"
        # defect one level up: the guard above covers the directory being GONE
        # and said nothing about it being EMPTY. `rm ptable.json
        # journal/*.jsonl` leaves it empty, every history marker intact, and
        # both gates allowed. The kernel cannot produce this state from
        # `register`, which writes its own journal before it takes the ptable
        # lock, so an empty directory on a machine that has run hooks is
        # somebody else's sweep. A real fresh install has no kernel directory
        # at all, so `_kernel_has_history()` is False and it still allows,
        # which is the objection this rule had to survive and does.
        return ("the journal directory %s is empty on a machine whose kernel "
                "state says hooks have run here, so every record of what has "
                "been running was swept" % jdir)
    return ""


def _any_journal(jdir: str) -> bool:
    """True as soon as ONE `.jsonl` is seen. `scandir` stops at the first hit,
    so a healthy directory costs one batch and only an empty one is walked
    whole."""
    try:
        with os.scandir(jdir) as it:
            for ent in it:
                if ent.name.endswith(".jsonl"):
                    return True
    except OSError:
        return True     # unreadable is decided above; never fault from here
    return False


def _zero_rows_fault(what: str, ignore_pid=None) -> tuple:
    """('', '', []) when zero usable rows is the TRUTH about this machine, else
    (fault, kind, pids). The kind and the pids are what let the fault be
    RE-DERIVED later instead of latching for good (`fault_resolved`).

    The one question the table cannot answer about itself, asked in the one
    place it has to be asked, and QA cycle 4 F1 is why it is a function rather
    than a branch inside `_absent_table`. That branch keyed on
    `FileNotFoundError`, so it only ever ran for a table that was DELETED, and
    three cheaper moves walked straight past it: writing
    `{"version":1,"processes":{}}` over the file, corrupting every row's value
    so the drop empties the table, and corrupting only the holder's row. All
    three yielded zero rows from a file that exists, all three read as a fresh
    install, and both gates allowed an intruder onto a held lane. The reader
    contradiction reproduced verbatim: `octo ps` said "the kernel has registered
    nothing on this machine yet" while `octo top` listed four live processes out
    of the same directory.

    So the decision is keyed on the RESULT, zero rows, and never on which
    syscall produced it. It stays correct for a legitimately empty table because
    the kernel never publishes zero rows while a journal that is not the
    writer's own reads live: `register` publishes its own row, and `prune` only
    removes rows whose process failed the liveness test.

    `ignore_pid` is the fresh-install carve-out and only `register` passes it:
    see `live_journal_pids`. It reaches every zero-rows path now, not just the
    absent one, because a register that finds an empty table on disk is in
    exactly the same position as one that finds no table at all.
    """
    evidence = journal_evidence_fault()
    if evidence:
        return evidence, FAULT_JOURNAL_EVIDENCE, []
    live = live_journal_pids(ignore=ignore_pid)
    if not live:
        return "", "", []
    return (("%s while at least %d journal(s) beside it read live (%s): a table "
             "with no rows is not a machine that never registered, it is a "
             "machine whose record of who holds what was removed under running "
             "processes"
             % (what, len(live),
                ", ".join(live[:3]) + (", ..." if len(live) > 3 else ""))),
            FAULT_ZERO_ROWS, live)


def _absent_table(ignore_pid=None) -> tuple:
    """What an ABSENT ptable means, which is not always "a machine with nothing
    on it". QA cycle 3 F3.

    The claim this file used to make, that there is exactly one honest empty
    table and it is an absent file, is false whenever a live journal sits
    beside it, and the two readers said so out loud: `octo ps` printed "the
    kernel has registered nothing on this machine yet" while `octo top` listed
    two live processes out of the same directory. One of them was wrong.

    It matters because of WHICH move it covers. Corrupting the table is the
    loud attack and it was already guarded; DELETING it is the cheap one, it
    reaches the file through the same unguarded door, and it bought a silent
    allow-everything machine: no fault, no quarantine copy, no doctor FAIL, no
    deny. Failing closed on the loud path and open on the quiet one pays the
    outage against the move nobody would make.

    So the rule is the least surprising one that stays coherent: an absent
    table with any live journal beside it is a FAULT, because a machine with
    running processes and no record of them has lost the record; an absent
    table with no live journal is a genuine fresh install and stays the one
    honest empty table, which is what a first run, a wiped cache and every
    sandbox in the test suite actually are.

    The cost is real and belongs in the recovery, not in a footnote: after the
    `rm` half of `recovery()` the machine sits in THIS fault until the next
    SessionStart writes a table or the journals age past the TTL, so the
    operator gets one more step rather than a surprise. `recovery()` states it.

    `ignore_pid` is the fresh-install carve-out, and only `register` passes it:
    see `live_journal_pids`. It is an explicit argument rather than module state
    because exactly one caller is entitled to it, and a hidden set of "journals
    this process wrote" would quietly extend that to every caller in the same
    interpreter.

    Since QA cycle 4 F1 this function owns only the ABSENT half of the question
    and the decision itself lives in `_zero_rows_fault`, because keying that
    decision on `FileNotFoundError` was the defect: writing an empty
    `processes` over the file reaches the same zero rows without ever touching
    this branch.
    """
    fault, kind, pids = _zero_rows_fault("the ptable is absent", ignore_pid)
    if not fault:
        return fresh_table(), [], ""     # the one honest empty table
    return _faulted_table(None, fault, kind, pids), [], fault


def read_ptable_detail(ignore_pid=None) -> tuple:
    """(table, dropped pids, fault). `read_ptable` for callers that must decide.

    `ignore_pid` is passed by `register` alone and only reaches the absent-file
    branch (`_absent_table`): it names the pid whose journal this very call just
    created, which is the one journal that is not evidence of anybody else.

    DROPS a malformed row rather than raising, and the difference is the whole
    point. QA measured what one `"junk": "not-a-row"` value did to the kernel:
    `octo ps` and `octo top` exited 1, `brain_doctor` reported two kernel checks
    crashed, and worst of all `prune()` raised INSIDE the ptable lock, so both
    register hooks exited 0 having published nothing. A reflex that reports
    success while writing nothing is the failure this seam exists to stop; one
    unreadable row must never be able to take the whole kernel down with it.

    A FAULT is the other half, and it is not a drop. Zero rows is the truth
    about this machine in exactly one state, and the state is about the MACHINE
    rather than about the file: no journal beside the table reads live, and the
    journals themselves can be walked (`_zero_rows_fault`). How the file reached
    zero rows does not enter into it, which is QA cycle 4 F1: keying that
    decision on `FileNotFoundError` covered only a DELETED table, and writing
    `{"version":1,"processes":{}}` over it, or corrupting every row's value,
    reached the same zero rows and read as a fresh install. Any other way of
    yielding zero rows - a file that is not JSON, a top level that is not an
    object, a `processes` that is an array, a file this process cannot open or
    cannot parse, a table under an unreadable journal directory - is a machine
    whose process table was readable to somebody and is not readable to us.
    `_write_ptable`
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

    A SIZE CEILING comes before the parse, and it is the one that takes the big
    read out of the lock window: every locked writer parses through here, so a
    46.1 MB table (QA measured one) meant 245 MB of peak RSS and seconds of
    parse INSIDE the ptable lock, chosen by whoever wrote the file. A table past
    the ceiling is a fault like any other unreadable one, and it is never
    parsed. A real one is kilobytes: a thousand rows is ~300 KB.
    """
    path = ptable_path()
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return _absent_table(ignore_pid)
    except OSError as exc:
        # CARRIES, like the `open` leg below, and QA cycle 3 F1 is why the two
        # are written out separately instead of trusting them to look alike.
        # They did not: this one returned `fresh_table()`, so the fault died at
        # the next `register` and the whole loss reproduced verbatim (deny, one
        # SessionStart, fault empty, ALLOW, the owner's row and lane gone, and
        # no quarantine file because nothing was ever carried for `_publish` to
        # preserve). Which leg a fault lands on is chosen by the ATTACKER, not
        # by the kernel: a directory at this path used to fail at `open` and hit
        # the carrying leg, an ELOOP symlink fails HERE at the stat and hit the
        # forgetting one. A fail-closed rule that depends on which syscall
        # noticed is not fail-closed. (The directory now stops one line below,
        # at the regular-file test added for F5, and keeps the same words.)
        fault = "the ptable could not be read (%s)" % exc
        return _faulted_table(None, fault), [], fault
    if not _stat.S_ISREG(st.st_mode):
        # QA cycle 4 F5. `os.path.getsize` SUCCEEDS on a FIFO, and the `open`
        # below then blocks forever waiting for a writer: both gates were still
        # running at 60 s, and a PreToolUse hook that never returns is neither
        # fail-closed nor fail-open, it is a hung session. The kernel publishes
        # this path with `os.replace` of a regular temp file, so anything that
        # is not a regular file is a foreign writer's, and it faults without
        # ever being opened. The wording keeps "could not be read" because that
        # is what it is, and because the directory case used to arrive at the
        # `open` leg below with those words.
        fault = ("the ptable could not be read (it is a %s, not a regular "
                 "file, so it was never opened)" % _stat_kind(st.st_mode))
        return _faulted_table(None, fault), [], fault
    size = st.st_size
    if size > MAX_PTABLE_BYTES:
        fault = ("the ptable is %d bytes, past the %d byte ceiling, so it was "
                 "not parsed" % (size, MAX_PTABLE_BYTES))
        return _faulted_table(None, fault), [], fault
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return _absent_table(ignore_pid)  # raced with a delete: ask the journals
    except ValueError as exc:
        fault = "the ptable is not valid JSON (%s)" % exc
        return _faulted_table(None, fault), [], fault
    except OSError as exc:
        # A file this process cannot OPEN is not an empty machine either: it is
        # a table that is readable to somebody and not to us, so it faults with
        # every other unreadable shape and the gates fail closed on it.
        fault = "the ptable could not be read (%s)" % exc
        return _faulted_table(None, fault), [], fault
    except Exception as exc:
        # QA cycle 4 F2, and the catch-all is the fix rather than one more named
        # leg. `json.load` on 20 KB of `[` nested 9998 deep raises
        # RecursionError, which is a RuntimeError and therefore caught by
        # neither `ValueError` nor `OSError`: it escaped every fault leg, reached
        # the gates' outer `except Exception: sys.exit(0)`, and produced rc=0
        # with empty stdout and empty stderr. No deny, no journal line, no
        # quarantine, no doctor FAIL, from a file well under the byte ceiling:
        # strictly quieter than the deletion this seam had just closed. A parse
        # that fails is a table we could not read, whatever the parser called
        # the failure, so the class is caught by shape and not by name.
        fault = ("the ptable could not be parsed (%s: %s)"
                 % (type(exc).__name__, exc))
        return _faulted_table(None, fault), [], fault

    table, dropped, fault = sane_table(data)
    if fault:
        return table, dropped, fault
    if table.get("processes"):
        # M2: A TABLE WITH ROWS STILL NEEDS ITS JOURNALS. Every liveness answer
        # in this file comes out of that directory, so a table full of rows and
        # no journals beside it is a table nobody can read ownership out of. The
        # gates denied this state already, but as a LANE deny naming a pid as
        # "never journaled" and telling the operator to wait for it to exit,
        # which is advice the message could not know was unmeasurable. The fault
        # is the honest description and it carries the recovery that works.
        # A CONDITION fault: put the directory back and it lifts on the next
        # read, no key to delete.
        evidence = journal_evidence_fault()
        if evidence:
            table[FAULT_KEY] = _fault_carrier(evidence, FAULT_JOURNAL_EVIDENCE)
            return table, dropped, evidence
        return table, dropped, ""
    # ZERO ROWS FROM A FILE THAT EXISTS (QA cycle 4 F1). Reached three ways:
    # `processes` written empty, every row dropped, or a table that really has
    # nothing in it. The first two are a loss and the third is the truth, and
    # nothing in the file tells them apart, so the journals do
    # (`_zero_rows_fault`). Off the hot path by construction: a machine with
    # anything registered on it has rows, so this runs only before the first
    # register or after everything on it has ended.
    zero, zkind, zpids = _zero_rows_fault(
        ("every row in the ptable was unreadable and dropped (%s)"
         % ", ".join(sorted(dropped)[:5])) if dropped
        else "the ptable is present and carries no row", ignore_pid)
    if not zero:
        return table, dropped, ""
    # The dropped VALUES are not carried: they are junk by definition, which is
    # why they were dropped, and the file exactly as it was is preserved beside
    # it by `_publish`. The fault names the pids; the quarantine copy has the
    # bytes.
    return _faulted_table(None, zero, zkind, zpids), dropped, zero


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
    repair is a fact about the FILE, not about whichever hook happened to be
    holding the lock when it was noticed, so it belongs beside the file: it
    outlives the journal retention that would delete it with that hook's
    journal, it survives the process ending, and the count the doctor escalates
    on is one `listdir` instead of a walk over every journal on the machine.

    (The argument this docstring used to make, that a journal line would move an
    unrelated liveness clock, does not hold and is dropped rather than left
    standing: the hook holding the lock owns that journal and is alive at that
    instant, so writing to it would be true. The reason above is the one that
    survives.)

    The copy carries the lost rows so the operator can read what was there, and
    the publishing pid so the process that overwrote the table is named.
    `brain_doctor` escalates on the FREQUENCY of these, not on the presence of
    one: a table repaired once is an accident, a table repaired three times in a
    day is a writer that is still running.
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


def _trim_quarantines(now: float = None) -> None:
    """Hold the ledger to THREE bounds, count, bytes and AGE, newest first.

    A count alone bounds the number of files and lets whoever wrote the corrupt
    table choose the size of each one: QA measured a 20-file worst case near
    954 MB from a 46.1 MB original. The newest is always kept, whatever it
    weighs or how old it is, because deleting the event that just happened
    would leave the doctor counting repairs it can no longer show.

    AGE is QA cycle 3 F5. Bounded by count and bytes, a copy never expired, so
    one corruption a year ago held `brain_doctor` at WARN forever and nothing
    printed where the files were or that removing them was safe. Both halves
    are fixed: `recovery()` names the path and says the copies are safe to
    delete once read, and a copy older than PRUNE_AFTER goes on its own. The
    window is the journal window on purpose, not a new number: the copy is
    evidence about a moment, and it should not outlive the journals that are
    the only other record of what was running at that moment.

    The bound needs a beat that is not a corruption, or an ageing rule reached
    only from `_quarantine` would fire only when a NEW copy arrives, which is
    the one moment nothing has expired that matters. So `prune_files` calls it
    on the register path, where every other retention window is enforced.
    """
    now = time.time() if now is None else now
    total = 0
    for n, (mt, path) in enumerate(quarantines()):
        try:
            total += os.path.getsize(path)
        except OSError:
            pass
        if n == 0:
            continue
        if (n >= MAX_QUARANTINE or total > MAX_QUARANTINE_TOTAL
                or (now - mt) > PRUNE_AFTER):
            try:
                os.unlink(path)
            except OSError:
                pass


def _quarantine(reason: str, pid=None) -> str:
    """Copy the ptable aside, with the reason and WHO, before a writer overwrites it.

    Called from `_publish` only, so the copy is made at the moment the original
    is actually about to be replaced and never on a path that merely reads. The
    raw bytes go in as a STRING: the file being preserved is by definition one
    the parser could not handle, so re-encoding it as JSON would lose exactly
    the evidence worth keeping.

    WHO, because the record used to carry `ts`, `reason` and the bytes, and the
    process that overwrote every lane on the machine left no trace naming
    itself. `pid` is the kernel process the writer is acting for (absent from
    `prune_locked`, which acts for no one); `os_pid` and `argv0` name the OS
    process and the script, which is what the operator greps for when the writer
    is not the kernel at all.

    BOUNDED, because the size of what is copied is chosen by whoever wrote the
    corrupt file. At most `MAX_QUARANTINE_BYTES` of the original is preserved
    and the truncation is recorded next to the original size, so the copy is a
    bounded cost with an honest label rather than an unbounded one that looks
    complete.

    Never raises. Preserving evidence must not be able to break the register
    hook that noticed the problem; that trade is the whole lesson of the row
    case above.
    """
    try:
        size = os.path.getsize(ptable_path())
        with open(ptable_path(), "rb") as fh:
            raw = fh.read(MAX_QUARANTINE_BYTES)
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
                       "pid": safe_pid(pid) if pid else "",
                       "os_pid": os.getpid(),
                       "argv0": os.path.basename(sys.argv[0] or "") or "-",
                       "bytes": size, "kept_bytes": len(raw),
                       "truncated": len(raw) < size,
                       "ptable": raw.decode("utf-8", "replace")}, fh, indent=2)
    except OSError:
        return ""
    _trim_quarantines()
    return dst


def _publish(table: dict, dropped=(), fault: str = "", pid=None) -> None:
    """Write the table, preserving first whatever the read had to repair.

    Every locked writer republishes what it read, which is how the repair
    reaches the file - and also how the evidence used to leave it. QA cycle 1:
    `octo ps` prunes on read, prune is a writer, so on any table with an old
    dead row in it (the normal steady state) `octo ps` silently rewrote the file
    without the corrupt row and the footer that was supposed to name it read
    `dropped == []`. The corruption event left zero trace and the doctor after
    it had nothing to report.

    So the copy is taken HERE, in the one function that replaces the file, and
    not at the read: a caller that reads and decides not to write leaves the
    evidence exactly where it was.

    ONE copy per EVENT, not one per write. A fault is now carried forward
    (`_faulted_table`), so every writer after the first one reads a fault too,
    and quarantining on each of them would fill the ledger with copies of a
    table that is no longer the corrupt one and would trip the doctor's
    three-in-24 h escalation off a single event. The carrier records the copy it
    already has, so the second writer knows the evidence is kept and where. A
    dropped ROW is always a new event: it is repaired by this very write, so
    seeing one again means it happened again.
    """
    carrier = table.get(FAULT_KEY) if isinstance(table, dict) else None
    # A RESOLVED CONDITION LEAVES THE FILE HERE, and this is the removal that
    # did not exist anywhere in this module until cycle 5. `carried_fault`
    # stops REPORTING a resolved fault, which lifts the deny on the next read;
    # this is what stops it being re-read forever, so `octo ps` and the doctor
    # do not keep printing a fault whose condition is gone. One place, the same
    # function that already owns every replacement of this file.
    if isinstance(carrier, dict) and carrier.get("reason") \
            and fault_resolved(carrier, table):
        table.pop(FAULT_KEY, None)
        carrier = None
    already = isinstance(carrier, dict) and carrier.get("quarantine")
    reason = fault or ("%d unreadable row(s) dropped: %s"
                       % (len(dropped), ", ".join(sorted(dropped)[:5])))
    if dropped or (fault and not already):
        kept = _quarantine(reason, pid)
    else:
        kept = ""
    if dropped and not fault:
        # A DROP IS CARRIED FORWARD TOO, and QA cycle 4 F1c is why. Corrupting
        # one row was the most surgical version of this whole attack: the
        # holder's row replaced with a string, `fault` empty, the gates allowed,
        # and the very next `register` republished the table WITHOUT that row,
        # so `lane_owner` returned the holder before the registration and `None`
        # after it. Repairing in memory is right; letting the repair erase the
        # only evidence that a lane went missing is not. The rows this write
        # cannot carry forward are unaccounted for in exactly the sense the
        # table-level fault means, so they stick the same way: both gates keep
        # failing closed and the doctor keeps FAILing until a human looks.
        # LATCHED: a row that could not be read is a row whose lanes nothing on
        # disk can reconstruct, so this one does not re-derive its way out.
        carrier = _fault_carrier(reason, FAULT_LATCHED)
        table[FAULT_KEY] = carrier
    if kept and isinstance(carrier, dict) and not already:
        carrier["quarantine"] = os.path.basename(kept)
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


def _record_ts(pid):
    """The `ts` of the last CHAINED RECORD in this pid's journal, or None.

    The kernel writes this field, it sits inside the hash chain, and unlike the
    file's mtime it is not something a caller can rewrite with one syscall.
    """
    try:
        raw, _ends = _tail_line(journal_path(pid))
    except OSError:
        return None
    if not raw:
        return None
    try:
        rec = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return None
    if not isinstance(rec, dict):
        return None
    try:
        return float(rec.get("ts"))
    except (TypeError, ValueError):
        return None


def _own_fresh(pid, now: float, ttl: int) -> bool:
    """Freshness from the journal, mtime FIRST and the chained record second.

    C4, and it is F4's own sentence applied to a BACKDATED liveness record
    instead of a removed one. `lane_owner` guards deletion (`_mtime is None`)
    and this function was mtime-only, so `touch -d` on a live holder's journal
    freed its lane with nothing deleted, nothing edited and the chain intact:
    `live_journal_pids` returned `[]`, `lane_owner` returned None, both gates
    ALLOWED, while the last record in that file said the process was seconds
    old. `touch` is already in the Bash gate's `_STATE_VERBS` for the kernel
    directory, so the threat model named the move before the reader did; the
    docstring that enumerated "chmod, truncation and garbage already blocked;
    only deletion was permissive" was missing the fourth member of its own list.

    So a stale mtime is a QUESTION, not a verdict, and the answer comes from the
    record. The cost is one tail read and it is paid only when the mtime already
    says stale, which on a healthy machine means a process that has really gone
    quiet: the live path is the same single stat it always was.

    The honest claim, since a claim that overstates is worse than none: this
    raises the price of faking death from one metadata syscall to rewriting the
    last line of a hash-chained file (and the Bash gate denies the direct verbs
    that reach it). It is not unforgeable. The direction it can still be wrong
    in is the safe one: an mtime touched FORWARD keeps a lane held, which
    expires at PRUNE_AFTER, rather than handing it to a second writer.
    """
    age = _quiet_for(pid, now)
    return age is not None and age <= ttl


def _skew_age(now: float, stamp: float) -> float:
    """Seconds since `stamp`, with a stamp far enough in the FUTURE reported as
    infinitely old. A clock ahead of ours is skew, and skew is not liveness."""
    age = now - stamp
    return age if age >= -FUTURE_SKEW else float("inf")


def _quiet_for(pid, now: float):
    """Seconds since this pid's journal last showed activity, or None when the
    journal file is not there.

    ONE definition of "how long has this been quiet", read by liveness
    (`_own_fresh`, TTL) and by row expiry (`prune`, PRUNE_AFTER), because both
    were reading the mtime alone and both were reachable by the same `touch`.
    Backdating past PRUNE_AFTER did not even need the lane check to be fooled:
    prune would drop the row outright at the next SessionStart and the lane
    with it.

    None is returned only for an ABSENT journal, which is the case `lane_owner`
    and `prune` each decide for themselves (F4): a removed record is not a dead
    process.
    """
    mt = _mtime(journal_path(pid))
    if mt is None:
        return None
    age = _skew_age(now, mt)
    if age <= TTL:
        return age          # fresh by mtime: no second opinion is needed
    ts = _record_ts(pid)
    return age if ts is None else min(age, _skew_age(now, ts))


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

    The row half of that is now UNREACHABLE from here, and it is kept anyway as
    defence in depth, which is a different claim from the one this docstring
    used to make. `read_ptable` drops a value that is not an object before this
    function ever sees it (`sane_table`), so on the live path `procs.get(pid)`
    is `None` either way and `isinstance` and `is not None` cannot be told
    apart. It stays because it is the same predicate the read applies, at the
    point of use, so a future caller that reaches this with a table that did not
    come through the seam still gets the right answer; the anchor for it calls
    it with such a table on purpose.
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


def has_work_trace(pid) -> bool:
    """True when this pid's journal records anything but its own registrations.

    `has_trace` already says a trace has to be evidence of WORK; this is the
    same predicate one level up, for the one caller that has to tell "a process
    is running here" from "a process is starting here". A `start` line is what
    `register` writes before it takes the ptable lock, so a journal that carries
    only start lines proves a registration in flight and nothing else, and a
    registration in flight holds no lane: `claim_lane` creates the row it needs
    and runs off a tool call.

    Tail-scoped like `has_exit`, and the two out-of-window cases both answer
    TRUE, which is the fail-closed direction here (it keeps the fault): a
    journal bigger than the window has more in it than the registrations we can
    see, and a line that will not parse is not a line anyone can dismiss.
    """
    path = journal_path(pid)
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            if size == 0:
                return False
            window = min(size, 16384)
            fh.seek(size - window, os.SEEK_SET)
            chunk = fh.read(window)
    except OSError:
        return False
    if size > window:
        return True
    for raw in [p for p in chunk.split(b"\n") if p]:
        try:
            rec = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            return True
        if not isinstance(rec, dict) or rec.get("kind") != "start":
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
        _publish(table, dropped, fault, pid)
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

    A colliding row whose JOURNAL FILE IS GONE holds its lane, and QA cycle 4 F4
    is why that is not the same as `is_live`. `_mtime` returns None for a
    deleted journal, `_own_fresh` reads that as False and `is_live` reads dead,
    so `rm journal/<holder>.jsonl` freed the holder's lane with the table fully
    intact and both gates allowed the intruder onto it. That is the same
    inference this whole seam rejects for the process table: a missing RECORD is
    not a dead process, it is a record somebody removed, and the permissive
    branch is the wrong one to select from it. The state is unreachable from the
    kernel's own writers, because `prune` removes a row before `prune_files`
    can reach that pid's journal. chmod, truncation and garbage in the journal
    already blocked; only deletion was permissive.
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
        if _mtime(journal_path(pid)) is None:
            return pid, row          # record removed, not process ended (F4)
        if is_live(pid, table, now, ttl):
            return pid, row
    return None, None


def lane_recovery(pid) -> str:
    """The "what do I do now" half of a lane deny, which is not the same
    sentence for a holder that is merely busy and one whose liveness record is
    gone.

    M2. A lane held by a row with no journal beside it is denied correctly and
    was described wrongly: both gates told the operator to "wait for that
    process to exit (its lane frees on its exit line, or after 900s of
    silence)", and neither of those can happen, because silence is measured out
    of the file that is missing. Reachable by any cache sweep over
    `~/.claude/.cache`, so it is not an exotic state, and a fail-closed gate
    whose advice cannot work is most of the cost of failing closed.
    """
    pid = safe_pid(pid)
    if _mtime(journal_path(pid)) is None:
        return ("That row has NO JOURNAL beside it (%s is missing), so its lane "
                "does NOT free on silence: silence is measured out of the file "
                "that is gone. Put the journal (or the whole of %s) back, or "
                "have the operator remove the `%s` row from %s. Failing both, "
                "prune expires the row %ds after it registered."
                % (journal_path(pid), journal_dir(), pid, ptable_path(),
                   PRUNE_AFTER))
    return ("Wait for that process to exit (its lane frees on its exit line, "
            "or after %ds of silence), work in your own worktree, or have the "
            "operator free it from a terminal: `octo ps --release %s` (Phase "
            "1b; on a brain without it, edit the ptable row from the terminal)."
            % (TTL, pid))


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
        if fault or dropped:
            # FAIL CLOSED, same reasoning as the gate that called us. A claim is
            # the assertion "nobody else holds this path", and on a table we
            # could not read that assertion has no basis. Writing it anyway is
            # the F1 loss verbatim: the claim republishes a one-row table and
            # every other process's lanes are gone, granted to the claimant.
            #
            # `dropped` counts here for the same reason it counts at the gates
            # (QA cycle 4 F1c): a row that could not be read is a set of lanes
            # that could not be read, so the assertion has no basis for those
            # paths either. The row is still repaired, by `register`, which is
            # the writer that must publish through anything.
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
        _publish(table, dropped, fault, pid)
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
        _publish(table, dropped, fault, pid)
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
    long".

    Through `_quiet_for`, so the number in the message is not the one the
    attacker wrote. With the raw mtime a `touch`-backdated journal produced a
    correct DENY (the chained record kept the lane) carrying the sentence "last
    active 4000s ago" about a process that had just journaled: the verdict came
    from the record and the explanation came from the metadata, which is the
    kind of split that teaches an operator to distrust the right answer.
    """
    quiet = _quiet_for(pid, time.time() if now is None else now)
    if quiet is None:
        return -1.0
    return max(0.0, 0.0 if quiet == float("inf") else quiet)


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

    A row that HOLDS LANES and whose journal is absent is neither pruned nor
    trusted: it is kept and the table is FAULTED (QA cycle 2 F4). Freeing that
    lane is what `rm journal/<holder>.jsonl` was buying, one SessionStart after
    the deletion, and freeing it silently is the half that mattered.

    THE BOUND IS ON THE FAULT, NOT ON THE ROW, and cycle 5 C2 is why that
    sentence had to be rewritten rather than repeated. This docstring used to
    say the row "is still bounded: past PRUNE_AFTER it goes with everything
    else, so a fault the operator never clears expires on its own". QA aged the
    row past PRUNE_AFTER and measured what actually happened: the row pruned,
    the lane free, `_faulted` still in the table and the deny still on, because
    nothing anywhere removed that key. The bound applied to the row and the row
    was not the thing denying. The fault carries its pids now and
    `fault_resolved` re-derives it, so it lifts when the rows go, whether they
    go because the operator deleted them (which is what `recovery()` prescribes,
    and it did NOT work before) or because prune expired them here.
    """
    now = time.time() if now is None else now
    procs = table.get("processes", {})
    dead, lost = [], []
    for pid, ent in procs.items():
        if not isinstance(ent, dict):
            # `read_ptable` already drops these, so this fires only for a table
            # a caller assembled by hand. It stays because prune mutates under
            # the ptable lock: raising here leaves the lock holder with an
            # unwritten table and its register hook exiting 0 having published
            # nothing, which is the exact silent failure the seam above names.
            dead.append(pid)
            continue
        # `_quiet_for`, not `_mtime`: prune read the raw mtime, so `touch -d
        # "8 days ago"` on a live holder's journal dropped its row outright at
        # the next SessionStart and freed the lane without the lane check ever
        # being consulted. That is C4's move against the cheaper target.
        quiet = _quiet_for(pid, now)
        if quiet is None:
            registered = float(ent.get("registered_ts") or 0)
            if (now - registered) <= TTL:
                continue  # young row, journal not written (or just removed) yet
            if lanes_of(ent) and (now - registered) <= PRUNE_AFTER:
                lost.append(pid)
                continue
            dead.append(pid)
        elif quiet > PRUNE_AFTER:
            dead.append(pid)
    for pid in dead:
        procs.pop(pid, None)
    if lost and not carried_fault(table):
        reason = ("%d process row(s) hold lanes with no journal beside them "
                  "(%s): a journal the kernel did not delete is a liveness "
                  "record somebody removed, and the lanes those rows hold "
                  "cannot be released by anything that reads them"
                  % (len(lost), ", ".join(sorted(lost)[:5])))
        table[FAULT_KEY] = _fault_carrier(reason, FAULT_LOST_LANES,
                                          sorted(lost))
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
    # The repair ledger ages on the same beat and the same window: this is the
    # register-path sweep, and a bound that only ran when a NEW copy arrived
    # would never expire the old ones (see `_trim_quarantines`).
    _trim_quarantines(now)
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
        # `pid` is handed in so the journal this call wrote four lines up does
        # not read as "somebody else is running" on a machine whose table has
        # never existed (`_absent_table`). Every other reader of an absent table
        # is asking about processes that are not itself.
        table, dropped, fault = read_ptable_detail(pid)
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
        _publish(table, dropped, fault, pid)
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
