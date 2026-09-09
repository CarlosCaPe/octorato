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

A payload may carry a top-level "_env" object (stripped before the payload reaches
the gate) naming env vars to set for THAT leg only, after the override strip. Only
OCTO_* keys are applied, and never HOME/USERPROFILE/PATH/CLAUDE_SESSION_ID, so a
fixture can drive an operator override but can never escape the sandbox. It is
how a fixture proves override semantics (e.g. an operator flag that must still
deny when it is scoped to a different PR); it cannot leak into any other leg.

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

# a fixture's "_env" may set these and only these: the operator override vars
_ENV_ALLOWED = re.compile(r"^OCTO_[A-Z0-9_]+$")
# belt and braces: never let a fixture touch the sandbox or the interpreter
_ENV_NEVER = frozenset({"HOME", "USERPROFILE", "PATH", "CLAUDE_SESSION_ID",
                        "PYTHONPATH", "PYTHONHOME"})

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
    # qa-merge-gate's crash-handler fault injection. Stripped like the rest so a
    # stray export cannot poison every leg; the one fixture that needs it
    # declares it in its own "_env" and gets it back after this strip.
    "OCTO_GATE_CRASH_SELFTEST",
    # the same, for the crash injected DURING identification (the path the
    # crash guard cannot see, because the flag it reads is still unset there).
    "OCTO_GATE_CRASH_IDENT",
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


SELFTEST_SESSION = "__selftest__"
_KERNEL_RULE_RE = re.compile(r'^_KERNEL_RULE = "([^"]+)"', re.M)


def _prep_payload(raw_path: Path, fixture_dir: Path, sandbox: Path) -> tuple[str, dict]:
    """Load a fixture payload; rewrite a relative transcript_path to absolute.

    Returns (stdin_json, leg_env). "_env" is a harness key, not hook input, so it
    is removed from the payload the gate reads.
    """
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
    # "_env" is a harness key, not hook input: it is lifted out here so the gate
    # never sees it in the payload it reads.
    raw_env = data.pop("_env", None)
    leg_env = {}
    if isinstance(raw_env, dict):
        for k, v in raw_env.items():
            k = str(k)
            # Allowlist: a fixture may drive the operator override vars and nothing
            # else. Without this it could set HOME or PATH and break the sandbox
            # the harness exists to provide, or shadow the interpreter under test.
            if _ENV_ALLOWED.match(k) and k not in _ENV_NEVER:
                leg_env[k] = str(v)
    return json.dumps(data), leg_env


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


def _run_leg(script: Path, payload: str, sandbox: Path,
             leg_env: dict | None = None) -> tuple[int, str]:
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
    # fixture-declared env, applied AFTER the strip so a leg can exercise an
    # operator override deliberately; scoped to this subprocess only. Filtered
    # here as well as in _prep_payload: this is the only place the value reaches
    # a process, so the allowlist has to hold at THIS boundary, not upstream.
    for k, v in (leg_env or {}).items():
        if _ENV_ALLOWED.match(str(k)) and str(k) not in _ENV_NEVER:
            env[str(k)] = str(v)
    cp = subprocess.run(
        [sys.executable, str(script)],
        input=payload, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        cwd=str(sandbox), env=env, timeout=30,
    )
    return cp.returncode, cp.stdout


def _materialize_seed(sandbox: Path) -> None:
    """Rename every `dotgit` directory the seed copied into a real `.git`.

    A fixture cannot SHIP a `.git` directory: git refuses to record a tree entry
    named `.git` at any depth, so a seed that needs a repository has to spell it
    `dotgit` in the repo and be renamed here. Without this, a gate whose verdict
    depends on which repository the command targets can only be fixture-proven on
    an unresolvable target, which is the one case that denies for free.
    """
    for path in sorted(sandbox.rglob("dotgit"), key=lambda p: len(p.parts), reverse=True):
        if path.is_dir():
            try:
                path.rename(path.with_name(".git"))
            except OSError:
                pass


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
            _materialize_seed(sandbox)
        failures = []
        rule = _kernel_rule_of(script)
        for vf in violations:
            payload, leg_env = _prep_payload(vf, fdir, sandbox)
            rc, out = _run_leg(script, payload, sandbox, leg_env)
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
            payload, leg_env = _prep_payload(bf, fdir, sandbox)
            rc, out = _run_leg(script, payload, sandbox, leg_env)
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
