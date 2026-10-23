#!/usr/bin/env python3
"""Regenerate the FLOW.kernel-quota seed under home/, deterministically.

The seed is TRACKED proof data, not a build artifact: a gate whose seed is
missing on another checkout is a dead gate (the reason .gitignore negates
`.claude/`, `.cache/` and `company/` under registry/fixtures). This script only
has to exist so the 400-odd journal lines are reviewable as a recipe instead of
as an opaque blob, and so a reviewer can regenerate them and diff.

Deterministic by construction: every timestamp is a fixed epoch, so a
regeneration that changes nothing produces byte-identical files, hash chain
included. That fixed epoch is also what makes the minutes fixtures stale-proof.
An elapsed time computed from a baked `start_ts` only GROWS, so a violation
seeded as "over the minutes cap" stays over it forever, while a benign one can
never be seeded that way: the benign legs therefore prove themselves on the
call-count axis, which does not move with the calendar, or on a journal that
does not exist yet (elapsed 0).

    python3 registry/fixtures/FLOW.kernel-quota/make_seed.py

Processes seeded (caps come from home/.claude/company/config/kernel.json:
subagent 400 calls, main 1 minute, qa_multiplier 3):

    over    subagent, 401 tool lines  -> over the 400-call cap
    qa      subagent, 401 tool lines, type "Evidence Collector"
            -> over the base cap, well under 400 x 3
    slowmain    main loop, ancient start_ts -> over the 1-minute cap
    qamain      main loop, ancient start_ts, type "Reality Checker"
            -> over 1 x 3 too, which is the point: the multiplier is headroom,
               never an exemption
"""
from __future__ import annotations

import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

EPOCH = 1700000000.0        # fixed: determinism, and an elapsed time that only grows
TOOL_LINES = 401            # one more than the 400-call cap in the seeded occupant


def main() -> int:
    home = os.path.join(HERE, "home")
    shutil.rmtree(home, ignore_errors=True)
    os.environ["HOME"] = home
    os.environ["USERPROFILE"] = home
    import kernel_proc  # imported AFTER HOME is rebound: every path is lazy

    os.makedirs(kernel_proc.journal_dir(), exist_ok=True)
    cfg = os.path.join(home, ".claude", "company", "config")
    os.makedirs(cfg, exist_ok=True)
    with open(os.path.join(cfg, "kernel.json"), "w", encoding="utf-8") as fh:
        # `qa_agent_types_regex` is deliberately absent: the layer below
        # (registry/kernel.yaml) must supply it, which is the override-key-by-key
        # contract under test.
        json.dump({"subagent": {"max_tool_calls": 400, "max_minutes": 0},
                   "main": {"max_tool_calls": 0, "max_minutes": 1},
                   "qa_multiplier": 3}, fh, indent=2)
        fh.write("\n")

    procs = {
        "over": {"pid": "over", "ppid": "sid-parent", "type": "general-purpose",
                 "tools": TOOL_LINES},
        "qa": {"pid": "qa", "ppid": "sid-parent", "type": "Evidence Collector",
               "tools": TOOL_LINES},
        "slowmain": {"pid": "slowmain", "type": "", "tools": 2},
        "qamain": {"pid": "qamain", "type": "Reality Checker", "tools": 2},
    }
    table = {"version": 1, "processes": {}}
    for pid, spec in procs.items():
        ts = EPOCH
        kernel_proc.append(pid, {"kind": "start", "ts": ts, "start_ts": ts,
                                 "type": spec["type"], "source": "fixture"})
        for i in range(spec["tools"]):
            ts += 1.0
            kernel_proc.append(pid, {"kind": "tool", "ts": ts, "tool_name": "Read",
                                     "tool_use_id": f"seed-{i}",
                                     "input_sha256": "0" * 64, "cwd": ""})
        row = {"pid": pid, "registered_ts": EPOCH}
        if spec["type"]:
            row["type"] = spec["type"]
        if spec.get("ppid"):
            row["ppid"] = spec["ppid"]
        table["processes"][pid] = row
    with open(kernel_proc.ptable_path(), "w", encoding="utf-8") as fh:
        json.dump(table, fh, indent=2, sort_keys=True)
        fh.write("\n")

    for pid in procs:
        if kernel_proc.verify(pid) != 0:
            print(f"seed FAIL: chain broken for {pid}", file=sys.stderr)
            return 1
        os.remove(kernel_proc.lock_path(pid))     # lock files are runtime, not seed
    print("seed written: " + ", ".join(sorted(procs)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
