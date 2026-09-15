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
    age = kernel_proc.process_age(pid)
    kind = (row or {}).get("type") or ("main loop" if not (row or {}).get("ppid") else "subagent")
    when = "never journaled" if age < 0 else f"last active {int(age)}s ago"
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

    table = kernel_proc.read_ptable()          # the one ptable read of this call

    owner, row = kernel_proc.lane_owner(target, table, ignore=pid)
    if owner:
        journal_deny(pid, {"target": target, "owner": owner, "why": "lane"})
        deny(
            f"KERNEL ISOLATION: {target} is the lane of {describe(owner, row)}. "
            "One writer per lane, the parent included: a second writer on one "
            "file is how a changeset gets shredded. Wait for that process to "
            "exit (its lane frees on its exit line, or after "
            f"{kernel_proc.TTL}s of silence), work in your own worktree, or have "
            f"the operator free it from a terminal: `octo ps --release {owner}` "
            "(Phase 1b; on a brain without it, edit the ptable row from the terminal)."
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


def build_sandbox(fdir: str, sandbox: str, age_pids=()) -> None:
    """Materialize the fixture world in a throwaway HOME.

    1. copy `home/` (ptable, journals, arms config) verbatim;
    2. rewrite {{SANDBOX}} in every seeded file;
    3. create the git roots and files `setup.json` declares (a `.git` entry is
       what makes a directory a worktree root to the pure-path walk);
    4. stamp every journal mtime to NOW, except the pids the leg wants EXPIRED,
       which are stamped past the TTL so their lanes read released.
    """
    import shutil
    import time

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

    setup_path = os.path.join(fdir, "setup.json")
    setup = {}
    if os.path.isfile(setup_path):
        with open(setup_path, encoding="utf-8") as fh:
            setup = json.load(fh)
    for root in setup.get("roots", []):
        root = root.replace(SANDBOX_TOKEN, sandbox)
        os.makedirs(os.path.join(root, ".git"), exist_ok=True)
    for path in setup.get("files", []):
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
        stamp = now - (kernel_proc.TTL + 300) if pid in (age_pids or ()) else now
        os.utime(os.path.join(jdir, name), (stamp, stamp))


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
            build_sandbox(fdir, sandbox, setup.get("age_pids") or ())
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
            cp = subprocess.run([sys.executable, script], input=body,
                                capture_output=True, text=True, cwd=sandbox,
                                env=env, timeout=30)
            did_block = gate_selftest.emits_block(cp.returncode, cp.stdout)
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
                failures.append(f"{name} did NOT block (rc={cp.returncode})")
                continue
            blocked += 1
            want = setup.get("expect_names")
            if want and want not in cp.stdout:
                failures.append(f"{name} blocked without naming {want}")
        else:
            if did_block:
                failures.append(f"{name} WAS blocked (must allow, rc={cp.returncode})")
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
        sys.exit(0)  # fail-open: never break the user's tool call
