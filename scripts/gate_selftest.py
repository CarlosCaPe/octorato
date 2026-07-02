#!/usr/bin/env python3
"""gate_selftest.py — shared fixture-driven liveness harness for fail-closed gates.

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
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# env vars that could turn a violation into an allow; stripped for every leg
_OVERRIDE_ENV = (
    "OCTO_MERGE_APPROVE", "OCTO_QA_OK", "OCTO_ALLOW_FORCE",
    "OCTO_LANE_OVERRIDE", "OCTO_GRAFO_OVERRIDE",
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


def _prep_payload(raw_path: Path, fixture_dir: Path, sandbox: Path) -> str:
    """Load a fixture payload and rewrite a relative transcript_path to absolute."""
    data = json.loads(raw_path.read_text(encoding="utf-8"))
    tp = data.get("transcript_path")
    if isinstance(tp, str) and tp and not os.path.isabs(tp):
        data["transcript_path"] = str((fixture_dir / tp).resolve())
    return json.dumps(data)


def _run_leg(script: Path, payload: str, sandbox: Path) -> tuple[int, str]:
    env = dict(os.environ)
    for k in _OVERRIDE_ENV:
        env.pop(k, None)
    env["HOME"] = str(sandbox)
    env["USERPROFILE"] = str(sandbox)
    env["CLAUDE_SESSION_ID"] = "__selftest__"
    cp = subprocess.run(
        [sys.executable, str(script)],
        input=payload, capture_output=True, text=True,
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
        for vf in violations:
            rc, out = _run_leg(script, _prep_payload(vf, fdir, sandbox), sandbox)
            if not emits_block(rc, out):
                failures.append(f"{vf.name} did NOT block (rc={rc})")
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
