#!/usr/bin/env python3
"""g__pretool__kernel.py: PreToolUse `*` gate. No tool call runs unjournaled.

v8 Phase 1a (docs/architecture/v8-kernel.md section 3). THE hot-path script:
every tool call of every process passes through here exactly once, and the call
is journaled before it runs. Phase 3 adds quotas to this same script, read off
the same tail line it already holds under the lock, so the hot path stays ONE
invocation.

pid = payload `agent_id` else `session_id` (kernel_proc.resolve_pid), the same
order the register hooks use, so a child's tool lines land in the child's
journal and not the parent's.

What it denies, and only this: an OSError from the append. Not a missing `start`
line, not a missing ptable row. Same-event hooks run in parallel and a child's
first tool call can beat its own SubagentStart, so treating an unregistered pid
as a violation would deny legitimate work; the append opens the journal for that
pid on the spot instead. It creates the journal directory itself for the same
reason.

The deny prints the unlock verbatim. `OCTO_KERNEL_OPEN` is read from THIS
process's env only (the CLAUDE_SESSION_ID precedent,
dimension-awareness-hook.py:98-105): the harness owns the env, the model owns the
payload, so a payload field never counts. In open mode a call that could not be
journaled is counted, and once the journal is writable again the count is
written back as an `open` line, so the doctor can say how many calls ran
unjournaled instead of guessing.

Import budget: json, os, sys plus kernel_proc, whose own module-level imports are
json, os, sys, time, hashlib, fcntl. No git spawn, no pathlib, no re.

Stdin:  PreToolUse payload {"session_id", "agent_id", "tool_name",
        "tool_use_id", "tool_input", "cwd", ...}
Stdout: deny JSON on an unwritable journal, else nothing. Exit always 0.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import kernel_proc  # noqa: E402  (stdlib-only, hot-path budgeted)


def _deny(reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }, ensure_ascii=False))


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    pid = kernel_proc.resolve_pid(payload)
    if not pid:
        return 0

    record = {
        "kind": "tool",
        "tool_name": str(payload.get("tool_name") or ""),
        "tool_use_id": str(payload.get("tool_use_id") or ""),
        "input_sha256": kernel_proc.input_hash(payload.get("tool_input")),
        "cwd": str(payload.get("cwd") or ""),
    }
    if payload.get("agent_id"):
        record["agent_id"] = str(payload.get("agent_id"))

    try:
        kernel_proc.backfill_open(pid)
        kernel_proc.append(pid, record)
    except OSError as exc:
        if kernel_proc.open_mode():
            kernel_proc.pending_note(pid)
            return 0
        _deny(
            "KERNEL: this tool call cannot be journaled, so it does not run. "
            f"{kernel_proc.journal_path(pid)} is not writable ({exc.__class__.__name__}: {exc}). "
            "v8: a run without a journal has no pid, no replay and no quota. "
            "Repair the path, or run unjournaled on purpose: "
            f"{kernel_proc.UNLOCK}"
        )
        return 0
    except Exception:
        # Anything that is not an unwritable journal fails OPEN: the kernel
        # records runs, it does not get to invent new reasons to stop them.
        return 0
    return 0


# ── selftest (bespoke: state-dependent seeds, dimension-awareness-hook.py:506) ─

def _selftest(fixture_dir: str = None) -> int:
    """Fresh sandbox HOME per leg, the real main() as a subprocess.

    Beyond block-and-allow this asserts two things a generic harness cannot:
    the deny names the unlock verbatim, and an allowed call actually WROTE its
    journal line. A gate that allows everything and journals nothing would pass
    a block/allow harness while being exactly the hole this rule closes.
    """
    import glob
    import shutil
    import subprocess
    import tempfile

    import gate_selftest

    scripts = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(scripts)
    fdir = fixture_dir or os.path.join("registry", "fixtures", "FLOW.kernel-journal")
    if not os.path.isabs(fdir):
        fdir = os.path.join(root, fdir)
    if not os.path.isdir(fdir):
        print(f"selftest FAIL: fixture dir missing: {fdir}", file=sys.stderr)
        return 1

    violations = sorted(glob.glob(os.path.join(fdir, "violation*.json")))
    benigns = sorted(glob.glob(os.path.join(fdir, "benign*.json")))
    if not violations or not benigns:
        print(f"selftest FAIL: need violation*.json and benign*.json in {fdir}",
              file=sys.stderr)
        return 1

    seed = os.path.join(fdir, "home")
    failures = []

    def run_leg(path: str) -> tuple:
        sandbox = tempfile.mkdtemp(prefix="kernel-gate-selftest-")
        try:
            if os.path.isdir(seed):
                shutil.copytree(seed, sandbox, dirs_exist_ok=True)
            env = dict(os.environ)
            for k in ("OCTO_MERGE_APPROVE", "OCTO_QA_OK", "OCTO_ALLOW_FORCE",
                      "OCTO_LANE_OVERRIDE", "OCTO_GRAFO_OVERRIDE",
                      "OCTO_KERNEL_OPEN",
                      "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_PREFIX",
                      "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY", "GIT_NAMESPACE",
                      "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_QUARANTINE_PATH"):
                env.pop(k, None)
            env["HOME"] = sandbox
            env["USERPROFILE"] = sandbox
            env["CLAUDE_SESSION_ID"] = "__selftest__"
            with open(path, encoding="utf-8") as fh:
                payload = fh.read()
            cp = subprocess.run([sys.executable, os.path.abspath(__file__)],
                                input=payload, capture_output=True, text=True,
                                cwd=sandbox, env=env, timeout=30)
            journal = os.path.join(sandbox, ".claude", ".cache", "kernel", "journal")
            wrote = 0
            if os.path.isdir(journal):
                for name in os.listdir(journal):
                    if name.endswith(".jsonl") and os.path.isfile(os.path.join(journal, name)):
                        with open(os.path.join(journal, name), "rb") as fh:
                            wrote += sum(1 for ln in fh if ln.strip())
            return cp.returncode, cp.stdout, wrote
        finally:
            shutil.rmtree(sandbox, ignore_errors=True)

    for vf in violations:
        rc, out, _ = run_leg(vf)
        if not gate_selftest.emits_block(rc, out):
            failures.append(f"{os.path.basename(vf)} did NOT block (rc={rc})")
        elif "OCTO_KERNEL_OPEN=1" not in out:
            failures.append(f"{os.path.basename(vf)} blocked without naming the unlock")
    for bf in benigns:
        rc, out, wrote = run_leg(bf)
        if gate_selftest.emits_block(rc, out):
            failures.append(f"{os.path.basename(bf)} WAS blocked (must allow, rc={rc})")
        elif wrote < 1:
            failures.append(f"{os.path.basename(bf)} was allowed but journaled nothing")

    if failures:
        print("selftest FAIL: " + "; ".join(failures), file=sys.stderr)
        return 1
    print(f"selftest PASS: {len(violations)} block + {len(benigns)} allow "
          f"(g__pretool__kernel.py vs {os.path.basename(fdir)}); "
          f"every allowed call journaled")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _i = sys.argv.index("--selftest")
        sys.exit(_selftest(sys.argv[_i + 1] if len(sys.argv) > _i + 1 else None))
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
