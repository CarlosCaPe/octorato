#!/usr/bin/env python3
"""r__permission-denied__journal.py: PermissionDenied reflex, the harness's own refusals.

v8 Phase 4 (docs/architecture/v8-kernel.md section 3). Thirteen Octorato gates
journal what THEY refuse. This one journals what the HARNESS refuses, so a
replay of a run shows both kinds of refusal on one timeline instead of only the
half Octorato owns.

Scope, stated as narrowly as the runtime delivers it. On 2.1.261 the event fires
for the AUTO-MODE classifier only, and its payload is the base hook fields plus
`{tool_name, tool_input, tool_use_id, reason}`. A `permission-rule` denial and a
`user-rejected` denial do NOT fire this event at all, so neither is journaled and
neither is claimed; the user rejection stays the residual v8-kernel.md section 6
already names. There is no denial-KIND field to read: `toolDenialKind` lives on
the transcript's tool_result records, not on the hook payload, so this reflex
records the runtime's own `reason` string VERBATIM rather than inventing a
classifier the payload never carried. `permission_mode` is recorded when present
because it is the one field that says which mode was refusing.

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

# What the runtime actually sends, and nothing more. `reason` is the refusal text
# the harness itself wrote; `permission_mode` names the mode that refused. A
# future runtime that adds a real denial-kind field to the PAYLOAD gets a row
# here; until it does, guessing one would be the fabrication this brain forbids.
_RECORDED_KEYS = ("reason", "permission_mode")
_MAX_VALUE = 400


def denial_fields(payload: dict) -> dict:
    """The denial fields the runtime sends, under their original keys."""
    out = {}
    for key in _RECORDED_KEYS:
        value = (payload or {}).get(key)
        if value in (None, ""):
            continue
        if not isinstance(value, str):
            value = str(value)
        out[key] = value[:_MAX_VALUE]
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
        # The runtime's own words, unedited. A payload with no `reason` still
        # gets a deny line: WHICH tool the harness refused is the fact worth
        # recording, and inventing a reason would be worse than naming none.
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
            if d.get("reason") != payload.get("reason"):
                failures.append("the runtime's own reason string was not recorded verbatim")
            if d.get("permission_mode") != payload.get("permission_mode"):
                failures.append("the permission mode that refused was not recorded")
            if d.get("source") != "harness":
                failures.append("the deny line does not say the harness refused")
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
          "tool and the runtime's own reason verbatim (r__permission-denied__journal)")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        i = sys.argv.index("--selftest")
        sys.exit(_selftest(sys.argv[i + 1] if len(sys.argv) > i + 1 else None))
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
