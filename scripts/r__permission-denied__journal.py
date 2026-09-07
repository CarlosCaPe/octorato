#!/usr/bin/env python3
"""r__permission-denied__journal.py: PermissionDenied reflex, the harness's own refusals.

v8 Phase 4 (docs/architecture/v8-kernel.md section 3). Thirteen Octorato gates
journal what THEY refuse. This one journals what the HARNESS refuses, so a
replay of a run shows both kinds of refusal on one timeline instead of only the
half Octorato owns.

Scope, stated as narrowly as the runtime documents it: `PermissionDenied` is
documented for AUTO-MODE denials only (v8-kernel.md section 2). A user rejection
in default mode has no documented hook event and stays a residual (section 6).
So this reflex claims exactly what it observes: it records whatever denial-kind
field the payload carries, VERBATIM and unrenamed, rather than mapping it onto a
vocabulary the brain invented. When the runtime later fires this event for
`permission-rule` or `user-rejected` denials too, the journal already carries the
evidence and nobody has to re-run the experiment to find out.

rule id: `HARNESS.permission-denied`. It is registered in registry/rules.yaml
because the `kernel-replay` doctor check FAILS on a deny line whose rule id is
in no registry row (an unregistered deny is an orphan mechanism, RULE #1). The
row is DETECTOR tier: this reflex observes and records a refusal the harness
already made, it never makes one.

pid = payload `agent_id` else `session_id` (kernel_proc.resolve_pid), the same
order the hot-path gate uses, so a child's denied call lands in the child's
journal next to the calls that ran.

Never blocks. Fail-open on every error: this is a recorder.

Stdin:  PermissionDenied payload {"session_id", "agent_id", "tool_name",
        "tool_use_id", "cwd", plus whatever denial-kind field the runtime sends}
Stdout: nothing. Exit always 0.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

RULE_ID = "HARNESS.permission-denied"

# Field names are the runtime's to choose, not ours. Anything whose name carries
# "denial", or is the bare `kind`/`decision`/`permission_decision`, is copied
# under its ORIGINAL key. Recording it verbatim is the point: the PR's QA proof
# reads back which keys actually arrived, and a renamed field would have thrown
# that evidence away.
_KIND_HINTS = ("denial", "denied")
_KIND_KEYS = ("kind", "decision", "permission_decision", "permissiondecision",
              "reason", "message", "permission_mode", "mode")
_MAX_VALUE = 400


def denial_fields(payload: dict) -> dict:
    """Every denial-shaped field the payload carries, under its original key."""
    out = {}
    for key, value in (payload or {}).items():
        if key in ("session_id", "agent_id", "tool_name", "tool_use_id", "cwd",
                   "tool_input", "transcript_path", "hook_event_name",
                   "agent_type", "permission_mode_source"):
            continue
        flat = str(key).replace("_", "").lower()
        if not (any(h in flat for h in _KIND_HINTS) or flat in
                tuple(k.replace("_", "") for k in _KIND_KEYS)):
            continue
        if isinstance(value, (dict, list)):
            try:
                value = json.dumps(value, sort_keys=True, ensure_ascii=False)
            except Exception:
                value = str(value)
        elif not isinstance(value, (str, int, float, bool)):
            value = str(value)
        if isinstance(value, str):
            value = value[:_MAX_VALUE]
        out[str(key)] = value
    return out


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    try:
        import kernel_proc
        pid = kernel_proc.resolve_pid(payload)
        if not pid:
            return 0
        extra = denial_fields(payload)
        extra["source"] = "harness"
        tool = str(payload.get("tool_name") or "")
        if tool:
            extra["tool_name"] = tool
        reason = extra.pop("reason", "") or f"harness denied {tool or 'a tool call'}"
        kernel_proc.journal_deny(RULE_ID, reason,
                                 payload.get("tool_use_id"), pid, **extra)
    except Exception:
        return 0
    return 0


def _selftest(fixture_dir: str = None) -> int:
    """Feed the fixture payload through THIS script in a sandbox HOME and read
    the deny line back with the same library the doctor reads it with.

    `permission_denied.json` is named so on purpose: `run_gate_selftest` globs
    `violation*` and `benign*` at the top level of a fixture dir
    (gate_selftest.py:114-115), so this seed is inert to it. A reflex has no
    fixture PAIR to prove (it denies nothing); `incident-fixture-coverage`
    checks only `g__` names.
    """
    import shutil
    import tempfile

    import kernel_proc

    fdir = fixture_dir or os.path.join("registry", "fixtures", "FLOW.kernel-journal")
    if not os.path.isabs(fdir):
        fdir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), fdir)
    seed_path = os.path.join(fdir, "permission_denied.json")
    if not os.path.isfile(seed_path):
        print(f"selftest FAIL: fixture missing: {seed_path}", file=sys.stderr)
        return 1
    with open(seed_path, encoding="utf-8") as fh:
        payload = json.load(fh)

    sandbox = tempfile.mkdtemp(prefix="kernel-permdenied-")
    saved = (os.environ.get("HOME"), os.environ.get("USERPROFILE"))
    failures = []
    try:
        seed = os.path.join(fdir, "home")
        if os.path.isdir(seed):
            shutil.copytree(seed, sandbox, dirs_exist_ok=True)
        env = kernel_proc._sandbox_env(sandbox)
        rc, out = kernel_proc._feed(os.path.basename(__file__), payload, sandbox, env)
        if rc != 0:
            failures.append(f"the reflex exited {rc}")
        if out.strip():
            failures.append("a reflex printed on stdout; it must never emit a verdict")

        # a payload with no pid at all must be a silent no-op, never a crash
        rc2, _ = kernel_proc._feed(os.path.basename(__file__),
                                   {"hook_event_name": "PermissionDenied",
                                    "tool_name": "Bash"}, sandbox, env)
        if rc2 != 0:
            failures.append(f"a payload with no pid exited {rc2}")

        os.environ["HOME"] = sandbox
        os.environ["USERPROFILE"] = sandbox
        pid = kernel_proc.resolve_pid(payload)
        lines = [ln for ln in kernel_proc.read_journal(pid) if isinstance(ln, dict)]
        denies = [ln for ln in lines if ln.get("kind") == "deny"]
        if len(denies) != 1:
            failures.append(f"{len(denies)} deny line(s) written, expected exactly 1")
        else:
            d = denies[0]
            if d.get("rule") != RULE_ID:
                failures.append(f"deny rule {d.get('rule')!r} != {RULE_ID}")
            if d.get("tool_name") != payload.get("tool_name"):
                failures.append("the deny line does not name the tool")
            if d.get("tool_use_id") != payload.get("tool_use_id"):
                failures.append("the deny line does not carry the tool_use_id")
            recorded = {k: v for k, v in d.items() if k in denial_fields(payload)}
            if not recorded:
                failures.append("no denial-kind field was recorded verbatim")
        if kernel_proc.verify(pid) != 0:
            failures.append("the chain broke after the deny line")
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
    print("selftest PASS: an auto-mode denial is journaled with its rule id, its "
          "tool and its denial kind verbatim (r__permission-denied__journal)")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        i = sys.argv.index("--selftest")
        sys.exit(_selftest(sys.argv[i + 1] if len(sys.argv) > i + 1 else None))
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
