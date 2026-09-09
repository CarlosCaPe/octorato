#!/usr/bin/env python3
"""g__pretool-write__tree-owner.py: one writer per tree and per lane (Write side).

v8 Phase 2, ISOLATION (docs/architecture/v8-kernel.md section 3). On its first
write a process CLAIMS the enclosing worktree root and a per-pid lane for that
path, recorded in the kernel process table. A write whose target is already a
lane of a DIFFERENT LIVE process is denied, the parent included: a parent that
owns the tree does not thereby license one child to overwrite another child's
file. That is the weekend failure this rule exists for (three builders, one
tree, 14 files wiped), and it is denied here, not advised.

Lane matching is equality or path prefix in either direction (kernel_proc
.paths_conflict), so claiming `pkg/a.py` also protects it from a write to
`pkg/a.py` itself and makes `pkg` unremovable by anyone else (the Bash twin,
g__pretool-bash__tree-owner.py, is where that shape lands).

Cross-arm: a write whose target sits under an arm root from
company/config/arms-paths.json OTHER than the writing process's own arm root is
denied. Arm Isolation says an arm never knows another arm exists; until now that
was audited after the fact by check-generic and pre-push. Fail-open when the
config is absent: a public adopter has no arms, and a gate that invents a
boundary nobody declared is noise.

NAMED RESIDUAL: the deny needs an arm on BOTH sides. A process whose cwd is in no
arm (a brain session) writing INTO an arm passes, deliberately, because that is
what `sync-ai-docs` does on every push. Arm-to-arm is the boundary this closes;
brain-to-arm stays audited by check-generic and the pre-push gate.

Liveness is kernel_proc's single definition (TTL 900 s), so a killed or hung
holder releases what it holds in 15 minutes and a finished subagent releases it
at once (its `exit` line). Every deny names the holding pid, its type and its
age, because "who holds this" is only actionable next to "for how long", and
journals a `deny` line so the refusal is replayable.

This script also carries the DELEGATE RELEASE: on `PreToolUse[Agent]` the
spawning process's own lanes are dropped and a `release` line is journaled, so a
parent does not hold its children hostage to paths it claimed before delegating.

The kernel's own state is a floor, not a lane: a write targeting
`~/.claude/.cache/kernel` (the process table, the journals, the locks) is denied
for EVERY hooked process, this one included, and so is a write to any ANCESTOR of
it by the same prefix test (`~/.claude/.cache`, `~/.claude`, `$HOME`), because a
process that can rewrite the table can grant itself any lane and erase the
record. The operator's terminal
is not hooked and stays the only writer.

Hot path: one ptable read per call. The arms config is read ONLY when the target
leaves the process's own worktree root, which is the only shape that can be
cross-arm. One flocked write, on a NEW lane claim only.

Everything except a real conflict fails OPEN. The kernel isolates processes; it
does not get to invent new reasons to stop them.

Stdin:  PreToolUse payload {"session_id", "agent_id", "tool_name", "tool_input",
        "cwd", ...} for Write|Edit|NotebookEdit|MultiEdit
Stdout: deny JSON on a conflict, else nothing. Exit always 0.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import kernel_proc  # noqa: E402  (stdlib-only, hot-path budgeted)

RULE_ID = "ARCHITECTURE.kernel-isolation"
WRITE_TOOLS = ("Write", "Edit", "NotebookEdit", "MultiEdit")


def deny(reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }, ensure_ascii=False))


def journal_deny(pid, fields: dict) -> None:
    """Record the refusal in the process's own journal. Best effort: a gate that
    cannot write its own record still denies (the journal gate owns that)."""
    try:
        rec = {"kind": "deny", "rule": RULE_ID, "gate": "tree-owner"}
        rec.update(fields)
        kernel_proc.append(pid, rec)
    except Exception:
        pass


def describe(pid: str, row: dict) -> str:
    """The one line a human reads while blocked, so it says what is KNOWN.

    A parent link still proves `subagent`: only a child is ever given one. Its
    ABSENCE proves nothing, and calling that a main loop was a guess printed as
    a fact. `claim_lane` creates a row with neither `type` nor `ppid` when a
    register hook loses its race with the process's first write, and for that
    row the deny used to read `(main loop, never journaled)` about a subagent.
    `UNKNOWN_TYPE` is the word every other reader already uses for exactly this,
    so the gates and `octo ps`/`top`/`replay` cannot drift apart on it.
    """
    row = row or {}
    age = kernel_proc.process_age(pid)
    kind = (row.get("type") or ("subagent" if row.get("ppid")
                                else f"type {kernel_proc.UNKNOWN_TYPE}"))
    # THREE STATES, because `process_age` now has three answers (C-A). NaN is
    # "its journal is there and its last record cannot be read", which is
    # neither "never journaled" nor a number, and printing either of those for
    # it is the verdict-and-explanation split this function exists to avoid.
    when = ("last activity UNKNOWN (its journal's last record is unreadable, so "
            "it is held, not free)" if age != age
            else "never journaled" if age < 0
            else f"last active {int(age)}s ago")
    return f"pid {pid} ({kind}, {when})"


# ── arms (cross-arm boundary) ───────────────────────────────────────────────

def arms_config_path() -> str:
    return os.path.join(kernel_proc.brain_dir(), "company", "config", "arms-paths.json")


def arm_roots() -> dict:
    """{arm name: [absolute candidate roots]} from company/config/arms-paths.json.

    Same contract ai_sync.load_arms reads: a value is a HOME-relative string or
    an array of candidates. EVERY candidate counts here, not just the first that
    exists: a boundary that moves when a directory is missing is not a boundary.
    Returns {} when the config is absent or unreadable, which fails the check
    open by construction.
    """
    try:
        with open(arms_config_path(), "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (FileNotFoundError, ValueError, OSError):
        return {}
    if not isinstance(raw, dict):
        return {}
    home = os.path.expanduser("~")
    out = {}
    for name, val in raw.items():
        cands = val if isinstance(val, list) else [val]
        roots = [kernel_proc.norm_path(os.path.join(home, str(c)))
                 for c in cands if isinstance(c, (str, bytes))]
        if roots:
            out[str(name)] = roots
    return out


def arm_of(path: str, arms: dict):
    """The arm whose root contains `path`, longest match wins, else None."""
    target = kernel_proc.norm_path(path)
    best, best_len = None, -1
    for name, roots in arms.items():
        for root in roots:
            if kernel_proc.paths_conflict(target, root) and target.startswith(root) \
                    and len(root) > best_len:
                best, best_len = name, len(root)
    return best


# ── main ────────────────────────────────────────────────────────────────────

def target_of(tool_input: dict):
    if not isinstance(tool_input, dict):
        return None
    raw = tool_input.get("file_path") or tool_input.get("notebook_path")
    return kernel_proc.norm_path(raw) if raw else None


def main() -> int:
    # QA cycle 9 F2: the budget that matters is the INVOCATION's, because the
    # invocation is what the harness kills at `timeout: 5`.
    kernel_proc.arm_invocation_budget()
    try:
        payload = json.loads(sys.stdin.read())
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    tool = str(payload.get("tool_name") or "")

    # DELEGATE RELEASE (PreToolUse[Agent]). A process that spawns a child stops
    # being the writer of what it claimed: otherwise a parent's lanes would bind
    # its own children for the whole delegation and this gate would deny exactly
    # the work it was asked to do. It never denies here, it only releases, and
    # the sibling rule is untouched: child A still cannot take child B's lane,
    # and a parent lane claimed AFTER the spawn still binds. Registered as a
    # second hooks.json entry on this same script rather than a third script,
    # because claiming and releasing a lane are one responsibility.
    if tool == "Agent":
        pid = kernel_proc.resolve_pid(payload)
        if pid:
            try:
                n = kernel_proc.release_lanes(pid, "delegate")
                if n:
                    kernel_proc.append(pid, {"kind": "release", "rule": RULE_ID,
                                             "reason": "delegate", "lanes": n})
            except Exception:
                pass
        return 0

    if tool not in WRITE_TOOLS:
        return 0
    target = target_of(payload.get("tool_input") or {})
    if not target:
        return 0
    pid = kernel_proc.resolve_pid(payload)
    if not pid:
        return 0

    kdir = kernel_proc.norm_path(kernel_proc.kernel_dir())
    if kernel_proc.paths_conflict(target, kdir):
        journal_deny(pid, {"target": target, "why": "kernel-state"})
        deny(
            f"KERNEL ISOLATION: {target} is inside the kernel's own state ({kdir}). "
            "The process table and the journals are what every gate reads to decide "
            "who owns what, so a process that can rewrite them can grant itself any "
            "lane and erase the record of having done it. No hooked process edits "
            "them, this one included. The operator's terminal is not hooked and "
            "stays the only writer."
        )
        return 0

    try:
        # the one ptable read of this call, and the one call whose EXCEPTIONS
        # are a deny rather than the fail-open at the bottom of this file. QA
        # cycle 6 F2: `json.load` on a deeply nested file raises RecursionError,
        # which is neither ValueError nor OSError, so it walked past every fault
        # leg in the reader and out through `except Exception: sys.exit(0)`,
        # producing rc=0 with nothing on either stream. The scope is deliberate:
        # a blanket deny on any exception in this hook would wedge the harness
        # on a bug in the path matching or the arms config, where allowing the
        # write is the right failure. Here it is not, because this call IS the
        # ownership question.
        table, dropped, fault = kernel_proc.read_ptable_detail()
    except Exception as exc:
        journal_deny(pid, {"target": target, "why": "ptable-read-raised",
                           "error": f"{type(exc).__name__}: {exc}"})
        deny(
            "KERNEL ISOLATION: reading the process table raised "
            f"{type(exc).__name__}: {exc}, so this gate cannot tell whether "
            f"another process holds {target}. A reader that cannot finish is a "
            "table nobody can read, and an unknown owner is denied, never "
            f"allowed. {kernel_proc.recovery()}"
        )
        return 0
    if not fault and dropped:
        # A ROW-LEVEL DROP IS A DENY TOO (QA cycle 4 F1c). Corrupting one row is
        # the most surgical version of this attack: the holder's row replaced
        # with a string, the fault empty, this gate allowing, and the next
        # register republishing the table without that row so the lane is gone
        # for good. The lanes of a row that could not be read are exactly as
        # unknowable as the lanes of a table that could not be read; the only
        # difference is how many of them there are.
        journal_deny(pid, {"target": target, "why": "ptable-row-unreadable",
                           "dropped": sorted(dropped)[:5]})
        deny(
            "KERNEL ISOLATION: "
            f"{len(dropped)} row(s) in the process table could not be read "
            f"({', '.join(sorted(dropped)[:5])}), so this gate cannot tell "
            f"whether one of them holds {target}. One writer per lane is "
            "fail-closed: rows whose lanes are unreadable are treated as "
            "holding everything, not nothing, because the alternative is the "
            "lane transfer this seam exists to stop. The next register hook "
            "repairs the table and CARRIES THE LOSS FORWARD, so a routine "
            "SessionStart does not clear this. "
            f"{kernel_proc.recovery()}"
        )
        return 0
    if fault:
        # FAIL CLOSED. This gate answers one question, "does another live
        # process hold this path", and it answers it out of the process table.
        # A table it cannot read does not answer that question, it removes it:
        # `sane_table` hands back an EMPTY table for a `processes` that is not
        # an object, and an empty table reads as "nobody owns anything", so the
        # gate that exists to deny the second writer waved it through and the
        # first write after it republished a one-row table with every other
        # lane gone. One writer per tree is a fail-closed rule, so the state
        # where ownership is unknowable is a deny, not an allow.
        #
        # It is not reachable from the kernel's own writers (`_write_ptable`
        # publishes a complete file with `os.replace`), which is the point: a
        # table shaped like this means something that is not the kernel wrote
        # it, and that is the last moment to keep working blind.
        journal_deny(pid, {"target": target, "why": "ptable-unreadable",
                           "fault": fault})
        deny(
            "KERNEL ISOLATION: the process table is unreadable, so this gate "
            f"cannot tell whether another process holds {target}. {fault}. "
            "One writer per tree is fail-closed: an unknown owner is denied, "
            "never allowed, because allowing it is how a second writer takes a "
            "lane and the table that recorded the first one gets overwritten. "
            "The next register hook CARRIES THE FAULT FORWARD (and keeps a "
            "copy of the file when there is one left to copy), so a routine "
            "SessionStart (startup, resume, clear, compact) does not clear "
            "this while the fault stands. "
            f"{kernel_proc.recovery(kernel_proc.fault_kind(table))}"
        )
        return 0

    owner, row = kernel_proc.lane_owner(target, table, ignore=pid)
    if owner:
        journal_deny(pid, {"target": target, "owner": owner, "why": "lane"})
        deny(
            f"KERNEL ISOLATION: {target} is the lane of {describe(owner, row)}. "
            "One writer per lane, the parent included: a second writer on one "
            f"file is how a changeset gets shredded. {kernel_proc.lane_recovery(owner)}"
        )
        return 0

    cwd = str(payload.get("cwd") or "")
    my_root = kernel_proc.enclosing_worktree_root(cwd or target)
    target_root = kernel_proc.enclosing_worktree_root(target)

    # Cross-arm can only happen when the write leaves the process's own tree,
    # so the arms config stays off the hot path for every ordinary write.
    if my_root and target_root and my_root != target_root:
        arms = arm_roots()
        if arms:
            mine = arm_of(cwd or my_root, arms)
            theirs = arm_of(target, arms)
            if mine and theirs and mine != theirs:
                journal_deny(pid, {"target": target, "arm": theirs, "why": "cross-arm"})
                deny(
                    f"KERNEL ISOLATION: this process works in arm '{mine}' and "
                    f"{target} belongs to arm '{theirs}'. An arm never knows "
                    "another arm exists, so a cross-arm write is denied, not "
                    "audited afterwards. Route the change through the operator, "
                    "or run this work in a session whose cwd is that arm."
                )
                return 0

    if not kernel_proc.holds_lane(pid, target, table):
        kernel_proc.claim_lane(pid, target, tree=target_root)
    return 0


# ── selftest (bespoke: state-dependent seeds, dimension-awareness-hook.py:506) ─
#
# Shared by BOTH Phase 2 gates: the Bash twin imports these three functions
# through importlib rather than growing a second copy that can drift
# (receipt_ledger.py:90-96 pattern). The world is built at RUN TIME because it
# cannot be committed: kernel_proc._own_fresh rejects an mtime older than the
# TTL and one more than 120 s in the future, so a committed timestamp is dead on
# arrival, and every path in the seed has to be rewritten to the throwaway HOME.

SANDBOX_TOKEN = "{{SANDBOX}}"


def fixture_dir(fdir: str = None) -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    fdir = fdir or os.path.join("registry", "fixtures", "ARCHITECTURE.kernel-isolation")
    return fdir if os.path.isabs(fdir) else os.path.join(root, fdir)


def _sandbox_in_json(sandbox: str) -> str:
    """The sandbox path as it must appear INSIDE a JSON string literal.

    On Windows the path carries backslashes, and substituting them raw into
    already-serialized JSON yields `"C:\\Users\\..."`, where `\\U` is an invalid
    escape. The payload then does not parse: the gate reads nothing, fails open
    by design, and EVERY violation fixture passes while the harness still calls
    the gate green. That is worse than a broken test, it is a fail-closed rule
    reporting itself alive while it is inert. `json.dumps` escapes the path the
    way the format requires, and on POSIX it is a no-op.
    """
    return json.dumps(sandbox)[1:-1]


def build_sandbox(fdir: str, sandbox: str, setup=None) -> None:
    """Materialize the fixture world in a throwaway HOME.

    1. copy `home/` (ptable, journals, arms config) verbatim;
    2. rewrite {{SANDBOX}} in every seeded file;
    3. apply the per-fixture ptable/journal overrides (below);
    4. create the git roots and files `setup.json` declares (a `.git` entry is
       what makes a directory a worktree root to the pure-path walk);
    5. stamp every journal mtime to NOW, except the pids the leg wants EXPIRED,
       which are stamped past the TTL so their lanes read released.

    The two overrides exist for QA cycle 3 F4, which found the central
    protection of this change covered by no fixture at all: the fail-closed
    fault branch could be DELETED from both gates and both selftests still
    passed with identical counts, because a count that cannot move looks like a
    count that was checked. A faulted table cannot be committed as the shared
    seed (every other fixture needs a readable one), so it is per fixture:

      `_setup.ptable`   a JSON value written verbatim over the seeded table
                        (e.g. `{"processes": []}` for the shape fault), or the
                        string "absent" to delete the file.
      `_setup.journals` "none" to remove every seeded journal, which is what
                        turns a deleted table from a loss into a genuine fresh
                        install (`kernel_proc._absent_table`). It is the pair
                        that makes the violation mean something: the benign leg
                        has to be a table that is empty for an HONEST reason,
                        or "the gate denies when it cannot read the table"
                        would be indistinguishable from "the gate denies".

    QA cycle 4 added six more, all applied LAST (see the block at the end):

      `_setup.corrupt_rows`  [pid, ...] whose row VALUE is replaced in the
                        seeded table, keeping every other row and its rewritten
                        lane paths (F1c).
      `_setup.mangle_lanes` {pid: value} to write a `lanes` that is not a list
                        of paths on an otherwise perfect row (F6).
      `_setup.ptable_nest`  depth of nested `[` written over the table: valid
                        JSON that makes `json.load` raise RecursionError (F2).
      `_setup.ptable_fifo`  a fifo at the ptable path, which `open` blocks on
                        forever (F5); here the selftest timeout is the
                        assertion.
      `_setup.drop_journals` [pid, ...] whose journal file is deleted with the
                        table left intact (F4).
      `_setup.journal_dir`  "gone" or "file" to remove or replace the journal
                        directory, which is where the deletion guard's own
                        evidence lives (F3).
      `_setup.forge_exit` [pid, ...] to append ONE well-formed `exit` line to
                        that pid's journal and change nothing else (cycle 8).
      `_setup.forge_journals` {pid: "tail"|"staircase"} to append the cycle-7
                        forgeries to that pid's journal and backdate its mtime.
                        "tail" is the measured break (two lines copying line 0's
                        `start_ts` with `ts` equal to it); "staircase" is its
                        general form (steps backwards smaller than FUTURE_SKEW,
                        which a pairwise direction check accepts one at a time).
      `_setup.kernel_history` "seen" to leave `.ptable.lock` behind (a machine
                        hooks have run on) or "none" to strip every trace but
                        the table and the journals (a wiped cache). It is the
                        one edit between F3's violation and its benign pair, and
                        it is applied here rather than seeded because `*.lock`
                        is gitignored.
    """
    import shutil
    import time

    setup = setup or {}
    if not isinstance(setup, dict):      # legacy positional: a tuple of pids
        setup = {"age_pids": setup}
    age_pids = setup.get("age_pids") or ()

    seed = os.path.join(fdir, "home")
    if os.path.isdir(seed):
        shutil.copytree(seed, sandbox, dirs_exist_ok=True)

    kernel = os.path.join(sandbox, ".claude", ".cache", "kernel")
    for base, _dirs, names in os.walk(os.path.join(sandbox, ".claude")):
        for name in names:
            path = os.path.join(base, name)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    text = fh.read()
            except (OSError, UnicodeDecodeError):
                continue
            if SANDBOX_TOKEN in text:
                # Every seeded file here is JSON or JSONL (ptable, journals,
                # arms config), so the path goes in escaped for that format.
                fill = (_sandbox_in_json(sandbox)
                        if name.endswith((".json", ".jsonl")) else sandbox)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(text.replace(SANDBOX_TOKEN, fill))

    # Per-fixture kernel state, applied AFTER the {{SANDBOX}} rewrite so an
    # override is never itself rewritten, and before the mtime stamping below
    # so a surviving journal still reads live.
    if "ptable" in setup:
        want = setup["ptable"]
        table_path = os.path.join(kernel, "ptable.json")
        if want == "absent":
            try:
                os.unlink(table_path)
            except OSError:
                pass
        else:
            with open(table_path, "w", encoding="utf-8") as fh:
                json.dump(want, fh)
    if setup.get("journals") == "none":
        jd = os.path.join(kernel, "journal")
        for name in (os.listdir(jd) if os.path.isdir(jd) else []):
            try:
                os.unlink(os.path.join(jd, name))
            except OSError:
                pass

    # setup.json is the world every fixture shares; `setup` above is the one
    # leg's own overrides. Two names, because they are two scopes.
    setup_path = os.path.join(fdir, "setup.json")
    world = {}
    if os.path.isfile(setup_path):
        with open(setup_path, encoding="utf-8") as fh:
            world = json.load(fh)
    for root in world.get("roots", []):
        root = root.replace(SANDBOX_TOKEN, sandbox)
        os.makedirs(os.path.join(root, ".git"), exist_ok=True)
    for path in world.get("files", []):
        path = path.replace(SANDBOX_TOKEN, sandbox)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8"):
            pass

    now = time.time()
    jdir = os.path.join(kernel, "journal")
    for name in (os.listdir(jdir) if os.path.isdir(jdir) else []):
        pid = name[:-len(".jsonl")] if name.endswith(".jsonl") else None
        if pid is None:
            continue
        path = os.path.join(jdir, name)
        # THE WHOLE FILE IS STAMPED, since cycle 5 C4 and cycle 6 C-A. Liveness
        # no longer reads the mtime alone: a stale mtime is re-checked against
        # the last record, because `touch` on a live holder's journal used to
        # free its lane with nothing deleted and the chain intact. That made the
        # seeded `ts` load-bearing, and cycle 6 made the seeded FILE
        # load-bearing. Cycle 7 made the WHOLE file load-bearing: `_journal_age`
        # reads every line and answers the freshest age in it, so rewriting the
        # last line alone - or any prefix - now produces the signature of a
        # forgery rather than of an expiry, and the reader correctly holds the
        # lane. `backdate_journal` shifts every line and re-chains, so
        # `age_pids` says one coherent thing again.
        if pid in (age_pids or ()):
            kernel_proc.backdate_journal(path, kernel_proc.TTL + 300)
        else:
            os.utime(path, (now, now))

    # QA cycle 4 overrides, applied LAST because each one leaves the kernel
    # directory in a state the steps above could not walk. Each names the
    # finding it seeds, so a fixture that stops meaning something is traceable
    # to the branch it was built for.
    table_path = os.path.join(kernel, "ptable.json")
    corrupt = setup.get("corrupt_rows") or ()
    mangled = setup.get("mangle_lanes") or {}
    if corrupt or mangled:
        # F1c and F6: the seeded table keeps every other row, and its lanes keep
        # their rewritten {{SANDBOX}} paths, which an inline `ptable` override
        # cannot do (it is written after the rewrite, verbatim).
        with open(table_path, encoding="utf-8") as fh:
            data = json.load(fh)
        for pid in corrupt:
            data["processes"][pid] = "not-a-row"
        for pid, value in mangled.items():
            data["processes"][pid]["lanes"] = value
        with open(table_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
    if setup.get("ptable_nest"):
        # F2: valid JSON, far under the byte ceiling, and `json.load` raises
        # RecursionError on it, which is neither ValueError nor OSError.
        depth = int(setup["ptable_nest"])
        with open(table_path, "w", encoding="utf-8") as fh:
            fh.write("[" * depth + "]" * depth)
    if setup.get("ptable_fifo"):
        # F5: `os.path.getsize` succeeds on a fifo and `open` then blocks
        # forever with no writer. A gate that never returns is neither
        # fail-closed nor fail-open, so the selftest timeout is the assertion.
        try:
            os.unlink(table_path)
        except OSError:
            pass
        os.mkfifo(table_path)
    for pid in (setup.get("journal_fifo") or ()):
        # QA cycle 9 F1: F5's move at a JOURNAL path instead of the table's.
        # `os.path.getsize` succeeds on a fifo, `_journal_age` passes its size
        # ceiling on 0 bytes and `open` then blocks forever with no writer, so
        # both gates ran past 20 s, were killed at the harness `timeout: 5` and
        # emitted no decision at all - which every matrix here reads as ALLOW.
        # No `os.utime` and no oversized file needed: `is_live` -> `has_exit` ->
        # `has_exit_line` opens the journal before any freshness check, so this
        # is left with a FRESH mtime on purpose. The selftest timeout is the
        # assertion, same as `ptable_fifo`.
        path = os.path.join(jdir, f"{pid}.jsonl")
        try:
            os.unlink(path)
        except OSError:
            pass
        os.mkfifo(path)
    for pid in (setup.get("drop_journals") or ()):
        # F4: the holder's liveness record removed with the table intact.
        try:
            os.unlink(os.path.join(jdir, f"{pid}.jsonl"))
        except OSError:
            pass
    history = setup.get("kernel_history")
    if history == "seen":
        # The F3 violation's ONE edit, and it is written here rather than seeded
        # in `home/` because `*.lock` is gitignored: a fixture whose meaning
        # lives in an untracked file is a gate that is armed on this machine and
        # disarmed in every clone. `.ptable.lock` is what every locked writer
        # opens and nothing in the kernel removes, so its presence is how a
        # machine says hooks have run on it. Its ABSENCE is the benign half: the
        # same two deletions on a HOME that shows no history are byte for byte a
        # wiped cache, which is the residual this pair states rather than hides.
        with open(os.path.join(kernel, ".ptable.lock"), "a"):
            pass
    elif history == "none":
        for name in os.listdir(kernel):
            if name in ("ptable.json", "journal"):
                continue
            try:
                os.unlink(os.path.join(kernel, name))
            except OSError:
                pass
    for pid in (setup.get("torn_journals") or ()):
        # C-A: one appended line that chains to nothing, plus the backdating
        # `touch`. The chain is left untouched and nothing is deleted, which is
        # the whole point: the record the reader falls back to is unreadable, so
        # the answer is UNKNOWN and the lane stays held.
        path = os.path.join(jdir, f"{pid}.jsonl")
        try:
            with open(path, "ab") as fh:
                fh.write(b"not-json\n")
            stale = time.time() - (kernel_proc.TTL + 300)
            os.utime(path, (stale, stale))
        except OSError:
            pass
    for pid in (setup.get("forge_exit") or ()):
        # C-A cycle 8: the cheapest transfer in this PR's history. One appended
        # exit line ends a subagent, because `is_live` reads the ending BEFORE
        # any freshness guard. Written with `append`, so it is the WELL-FORMED
        # forgery: byte-identical to a real exit line, which is why the reader
        # asks the ptable row instead of asking the file harder. Nothing else is
        # touched - no mtime, no timestamps, no chain.
        # BY PATH. `append` would resolve the journal through $HOME, which is
        # rebound for the hook subprocess and NOT for this process, so the exit
        # landed in the real kernel directory and the fixture blocked because
        # nothing had been forged. See `kernel_proc.forge_exit_line`.
        kernel_proc.forge_exit_line(os.path.join(jdir, f"{pid}.jsonl"))
    for pid, mode in (setup.get("forge_journals") or {}).items():
        # C-A cycle 7: the two forgeries a TAIL-LOCAL reader cannot see. Both
        # are pure APPENDS onto a correctly chained journal plus one `os.utime`,
        # and both were measured freeing a live holder's lane through the real
        # gate scripts before the reader started answering the freshest age in
        # the WHOLE file. `kernel_proc.forge_journal` builds them, shared with
        # the unit anchors so the gate-level fixture and the reader-level one
        # cannot drift into two different attacks.
        try:
            kernel_proc.forge_journal(os.path.join(jdir, f"{pid}.jsonl"), mode)
        except OSError:
            pass
    for pid, age in (setup.get("truncate_journals") or {}).items():
        # C-B: the journal truncated to its own first line. The start line is
        # copied verbatim, so it is genuine and chain-valid, and the file's
        # mtime becomes NOW because truncating writes. "stale" leaves the
        # seeded `start_ts` where it is (a process that started long before the
        # truncation: tampering); "fresh" moves it to now (a registration
        # genuinely in flight, which is C3's benign race and must still allow).
        path = os.path.join(jdir, f"{pid}.jsonl")
        try:
            with open(path, "rb") as fh:
                first = fh.read().split(b"\n")[0]
            rec = json.loads(first)
            if age == "fresh":
                rec["start_ts"] = rec["ts"] = round(time.time(), 6)
            else:
                rec["start_ts"] = rec["ts"] = round(
                    time.time() - (kernel_proc.START_ONLY_GRACE + 600), 6)
            with open(path, "wb") as fh:
                fh.write(json.dumps(rec, separators=(",", ":")).encode() + b"\n")
            os.utime(path, None)
        except (OSError, ValueError):
            pass
    if setup.get("fault_carrier"):
        # M-C: a carrier written by hand, on a table whose rows are intact. The
        # `kind` it claims is the untrusted field that used to select which
        # verification ran.
        try:
            with open(table_path, encoding="utf-8") as fh:
                data = json.load(fh)
            carrier = dict(setup["fault_carrier"])
            carrier.setdefault("ts", time.time())
            data[kernel_proc.FAULT_KEY] = carrier
            with open(table_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
        except (OSError, ValueError):
            pass
    want_jdir = setup.get("journal_dir")
    if want_jdir == "gone":
        # F3: the deletion guard's own evidence, removed by the same move.
        shutil.rmtree(jdir, ignore_errors=True)
    elif want_jdir == "file":
        shutil.rmtree(jdir, ignore_errors=True)
        with open(jdir, "w", encoding="utf-8") as fh:
            fh.write("not a directory\n")


def run_isolation_selftest(script: str, fdir: str, my_tools, label: str) -> int:
    """Run EVERY fixture through the real main() of `script`.

    Three assertions, not two. A fixture this gate owns must block (violation)
    or pass (benign) as its name says, AND a fixture belonging to the twin gate
    must pass here: a gate that denies payloads it does not own would pass a
    block-everything harness while making the other tool unusable. A violation
    also has to NAME the holder (`expect_names`), because a deny that does not
    say who holds the lane leaves the operator with nothing to act on.
    """
    import glob
    import shutil
    import subprocess
    import tempfile

    import gate_selftest

    fdir = fixture_dir(fdir)
    if not os.path.isdir(fdir):
        print(f"selftest FAIL: fixture dir missing: {fdir}", file=sys.stderr)
        return 1
    fixtures = sorted(glob.glob(os.path.join(fdir, "violation*.json"))) + \
        sorted(glob.glob(os.path.join(fdir, "benign*.json")))
    mine_v = [f for f in fixtures if os.path.basename(f).startswith("violation")]
    mine_b = [f for f in fixtures if os.path.basename(f).startswith("benign")]
    if not mine_v or not mine_b:
        print(f"selftest FAIL: need violation*.json and benign*.json in {fdir}",
              file=sys.stderr)
        return 1

    failures, blocked, allowed, foreign = [], 0, 0, 0
    for path in fixtures:
        name = os.path.basename(path)
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        setup = payload.pop("_setup", {}) or {}
        sandbox = tempfile.mkdtemp(prefix="kernel-iso-selftest-")
        try:
            build_sandbox(fdir, sandbox, setup)
            body = json.dumps(payload).replace(SANDBOX_TOKEN,
                                               _sandbox_in_json(sandbox))
            env = dict(os.environ)
            for k in ("OCTO_MERGE_APPROVE", "OCTO_QA_OK", "OCTO_ALLOW_FORCE",
                      "OCTO_LANE_OVERRIDE", "OCTO_GRAFO_OVERRIDE", "OCTO_KERNEL_OPEN",
                      "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_PREFIX",
                      "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY", "GIT_NAMESPACE",
                      "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_QUARANTINE_PATH"):
                env.pop(k, None)
            env["HOME"] = sandbox
            env["USERPROFILE"] = sandbox
            env["CLAUDE_SESSION_ID"] = "__selftest__"
            try:
                cp = subprocess.run([sys.executable, script], input=body,
                                    capture_output=True, text=True, cwd=sandbox,
                                    env=env, timeout=30)
            except subprocess.TimeoutExpired:
                # A NAMED FAILURE, not a traceback. The fifo fixture's whole
                # assertion is that the gate RETURNS, and a hook that never
                # returns is neither fail-closed nor fail-open, it is a wedged
                # session. Letting TimeoutExpired escape made that assertion a
                # crash: the selftest died with a stack trace instead of saying
                # which fixture hung and for how long, and a harness that fails
                # by crashing cannot tell a hang from a bug in itself.
                failures.append(f"{name} HUNG: no verdict within 30s")
                continue
            rc, out = cp.returncode, cp.stdout
            did_block = gate_selftest.emits_block(rc, out)
        finally:
            shutil.rmtree(sandbox, ignore_errors=True)

        owns = str(payload.get("tool_name") or "") in my_tools
        if not owns:
            foreign += 1
            if did_block:
                failures.append(f"{name} is not this gate's tool and WAS blocked")
            continue
        if name.startswith("violation"):
            if not did_block:
                failures.append(f"{name} did NOT block (rc={rc})")
                continue
            blocked += 1
            want = setup.get("expect_names")
            if want and want not in out:
                failures.append(f"{name} blocked without naming {want}")
        else:
            if did_block:
                failures.append(f"{name} WAS blocked (must allow, rc={rc})")
                continue
            allowed += 1

    if failures:
        print("selftest FAIL: " + "; ".join(failures), file=sys.stderr)
        return 1
    print(f"selftest PASS: {blocked} block + {allowed} allow, {foreign} foreign "
          f"payload(s) untouched ({label} vs {os.path.basename(fdir)}); "
          f"every deny names its holder")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _i = sys.argv.index("--selftest")
        sys.exit(run_isolation_selftest(
            os.path.abspath(__file__),
            sys.argv[_i + 1] if len(sys.argv) > _i + 1 else None,
            WRITE_TOOLS + ("Agent",), "g__pretool-write__tree-owner.py"))
    try:
        sys.exit(main())
    except Exception:
        # Fail-open, and it stays fail-open ON PURPOSE for everything that is
        # not the ptable read. A hook that denies on any exception of its own
        # wedges every write in the session on a bug in path matching, the arms
        # config or the payload shape, where allowing the call is the right
        # failure. The one exception that must NOT arrive here is the ownership
        # question itself, which is why `main()` denies around
        # `read_ptable_detail` rather than leaving it to this line (QA cycle 4
        # F2: a RecursionError from the parser reached here and exited 0 with
        # empty stdout, empty stderr and no journal line).
        sys.exit(0)
