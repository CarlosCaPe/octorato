#!/usr/bin/env python3
"""g__pretool__kernel.py: PreToolUse `*` gate. No tool call runs unjournaled.

v8 Phase 1a + Phase 3 (docs/architecture/v8-kernel.md section 3). THE hot-path
script: every tool call of every process passes through here exactly once, the
call is journaled before it runs, and the process's quota is checked off the
line that append() just returned, so the hot path stays ONE invocation and one
lock window. Nothing is re-read to enforce a cap.

QUOTA (Phase 3, rule FLOW.kernel-quota). Policy is the tracked slot
`registry/kernel.yaml` (public defaults, everything unlimited) overridden key by
key by the gitignored occupant `company/config/kernel.json`
(memory-model.md, "What is public vs private"). `max_tool_calls` is compared
against the `seq` of the line just written, which counts every journal line of
the process, `start` and `quota` included: an exact tool count would mean
reading the whole journal on every call, and a ceiling that is off by a handful
of non-tool lines is the honest price of one lock window. `max_minutes` is
compared against `start_ts`, carried forward on every line for exactly this.
0 is unlimited, and 0 is the shipped default.

A QA-typed process (its ptable `type` matched by the same regex the receipt
ledger uses to recognise a real verifier) gets its caps MULTIPLIED by
`qa_multiplier`, never waived: the main loop picks `subagent_type`, so an
exemption would be a cap the model could name its way out of. The ptable is
read only when a cap is already breached at the base rate, so the common call
pays zero extra reads.

Quota fails OPEN on its own errors. A malformed occupant, an unreadable policy
or a missing ptable row falls back to the tracked defaults and lets the call
run: a quota file that could stop work by being unparseable would be worse than
no quota at all. What it does NOT do is write the ptable; the hot path never
does. It journals one `quota` line per refused call, and
`r__subagent-stop__proc-exit.py` reads those to stamp `exit: quota`.

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
json, os, sys, time, hashlib, fcntl. No git spawn, no pathlib. `re` is imported
lazily, inside the QA-multiplier branch that only a breached call reaches, so a
normal call still never pays for it. The policy YAML is read by a 12-line
scalar parser rather than PyYAML for the same reason: importing PyYAML on every
tool call of every process costs more than the whole gate.

Stdin:  PreToolUse payload {"session_id", "agent_id", "tool_name",
        "tool_use_id", "tool_input", "cwd", ...}
Stdout: deny JSON on an unwritable journal or a breached quota, else nothing.
        Exit always 0.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import kernel_proc  # noqa: E402  (stdlib-only, hot-path budgeted)


# ── quota policy (Phase 3) ──────────────────────────────────────────────────

# The tracked slot's own defaults, restated here as the last line of defence:
# if registry/kernel.yaml is missing or unreadable on this machine, the gate
# still knows the shape and still enforces nothing, which is the safe direction.
DEFAULTS = {
    "subagent": {"max_tool_calls": 0, "max_minutes": 0},
    "main": {"max_tool_calls": 0, "max_minutes": 0},
    "qa_multiplier": 3,
    "qa_agent_types_regex": "(qa|review|reality|evidence|checker|verif|audit)",
}
_TIERS = ("subagent", "main")
_CAPS = ("max_tool_calls", "max_minutes")


def policy_path() -> str:
    """registry/kernel.yaml, resolved from THIS script, never from HOME: a
    sandbox selftest rebinds HOME but runs the real repo's gate, and the tracked
    defaults belong to the repo the gate came from."""
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "registry", "kernel.yaml")


def occupant_path() -> str:
    """company/config/kernel.json, resolved from the BRAIN dir, because that is
    where an operator's private config lives and where a sandbox seed puts it."""
    return os.path.join(kernel_proc.brain_dir(), "company", "config", "kernel.json")


def _scalar(raw: str):
    """One YAML scalar: quoted string, or bare value with its trailing comment
    stripped. Ints come back as ints so a cap never compares str to int."""
    raw = raw.strip()
    if raw[:1] in ('"', "'"):
        q = raw[0]
        end = raw.find(q, 1)
        return raw[1:end] if end > 0 else raw[1:]
    raw = raw.split("#", 1)[0].strip()
    try:
        return int(raw)
    except ValueError:
        return raw


def mini_yaml(text: str) -> dict:
    """The 12 lines of YAML this policy actually is: top-level scalars and
    one level of two-space-indented scalars. Not a YAML parser and not trying to
    be one; PyYAML on the hot path costs more than everything else here put
    together. brain_doctor validates registry/kernel.yaml with the real parser,
    so a file this reader would misread is caught there, not silently."""
    out, block = {}, None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indented = line[:1] in (" ", "\t")
        if ":" not in line:
            continue
        key, _, rest = line.strip().partition(":")
        key = key.strip()
        if indented:
            if block is not None and rest.strip():
                out.setdefault(block, {})[key] = _scalar(rest)
            continue
        if rest.strip():
            out[key] = _scalar(rest)
            block = None
        else:
            block = key
            out.setdefault(key, {})
    return out


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def load_policy() -> tuple:
    """(policy, notes). Defaults, then the tracked slot, then the gitignored
    occupant, each layer overriding key by key so a file that sets only
    `subagent` is complete. Every failure is a NOTE and never a deny."""
    policy = {"subagent": dict(DEFAULTS["subagent"]), "main": dict(DEFAULTS["main"]),
              "qa_multiplier": DEFAULTS["qa_multiplier"],
              "qa_agent_types_regex": DEFAULTS["qa_agent_types_regex"]}
    notes = []
    for path, parse in ((policy_path(), mini_yaml), (occupant_path(), json.loads)):
        try:
            data = parse(_read(path))
        except FileNotFoundError:
            continue
        except Exception as exc:
            notes.append(f"{os.path.basename(path)} unreadable ({exc.__class__.__name__}), "
                         "falling back to defaults")
            continue
        if not isinstance(data, dict):
            notes.append(f"{os.path.basename(path)} is not a mapping, ignored")
            continue
        for tier in _TIERS:
            sub = data.get(tier)
            if sub is None:
                continue
            if not isinstance(sub, dict):
                notes.append(f"{os.path.basename(path)}: `{tier}` is not a mapping, ignored")
                continue
            for cap in _CAPS:
                if cap not in sub:
                    continue
                try:
                    policy[tier][cap] = max(0, int(sub[cap]))
                except (TypeError, ValueError):
                    notes.append(f"{os.path.basename(path)}: `{tier}.{cap}` is not a "
                                 f"number ({sub[cap]!r}), keeping {policy[tier][cap]}")
        if "qa_multiplier" in data:
            try:
                policy["qa_multiplier"] = max(1, int(data["qa_multiplier"]))
            except (TypeError, ValueError):
                notes.append(f"{os.path.basename(path)}: `qa_multiplier` is not a "
                             f"number ({data['qa_multiplier']!r}), keeping "
                             f"{policy['qa_multiplier']}")
        if data.get("qa_agent_types_regex"):
            policy["qa_agent_types_regex"] = str(data["qa_agent_types_regex"])
    return policy, notes


def agent_type(pid: str) -> str:
    """The process's `type` off its ptable row. One extra read, and only a call
    already over its base cap ever pays it."""
    try:
        row = kernel_proc.read_ptable().get("processes", {}).get(kernel_proc.safe_pid(pid))
        return str((row or {}).get("type") or "")
    except Exception:
        return ""


def is_qa_type(atype: str, pattern: str) -> bool:
    if not atype:
        return False
    import re  # lazy: only a breached call reaches here
    try:
        return bool(re.search(pattern, atype, re.IGNORECASE))
    except re.error:
        return False


def breach(policy: dict, tier: str, lines: int, minutes: float, atype: str) -> str:
    """The breached quota, named, or '' when the call is within its caps.

    Checked at the base rate first; the QA multiplier is applied only to a cap
    that is already breached, so the ptable read stays off the common path.
    """
    mult = 1
    checked_qa = False
    for cap_name, used, unit in (("max_tool_calls", lines, "journal line"),
                                 ("max_minutes", minutes, "minute")):
        cap = int(policy.get(tier, {}).get(cap_name) or 0)
        if cap <= 0 or used <= cap:
            continue
        if not checked_qa:
            checked_qa = True
            if is_qa_type(atype, policy.get("qa_agent_types_regex") or ""):
                mult = max(1, int(policy.get("qa_multiplier") or 1))
        if used <= cap * mult:
            continue
        shown = f"{used:.1f}" if unit == "minute" else str(int(used))
        headroom = (f" (QA type {atype!r}: base cap {cap} x qa_multiplier {mult})"
                    if mult > 1 else "")
        return (f"{cap_name} {cap * mult}{headroom}, used {shown} {unit}"
                f"{'' if str(shown) == '1' else 's'}")
    return ""


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
        line = kernel_proc.append(pid, record)
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

    # ── quota, off the line we just wrote ────────────────────────────────────
    # The call is journaled either way: a refused call is a call that happened,
    # and Phase 4 replays it as REFUSED. Only the permission decision is left.
    if kernel_proc.open_mode():
        # The operator turned journaling off on purpose; a cap enforced on a
        # partial record would be enforced on a number it cannot trust.
        return 0
    try:
        head = json.loads(line.decode("utf-8", "replace"))
        used_lines = int(head.get("seq", 0)) + 1
        start_ts = float(head.get("start_ts") or head.get("ts") or 0.0)
        used_min = max(0.0, (float(head.get("ts") or 0.0) - start_ts) / 60.0) if start_ts else 0.0
        tier = "subagent" if payload.get("agent_id") else "main"
        policy, notes = load_policy()
        why = breach(policy, tier, used_lines, used_min, agent_type(pid))
    except Exception:
        return 0
    if not why:
        return 0

    try:
        kernel_proc.append(pid, {"kind": "quota", "tier": tier, "breach": why,
                                 "used_lines": used_lines,
                                 "used_minutes": round(used_min, 3),
                                 "tool_name": record["tool_name"],
                                 "tool_use_id": record["tool_use_id"]})
    except Exception:
        # A quota line that cannot be written does not buy the call a pass:
        # the deny below stands on the tool line, which is already on disk.
        pass
    _deny(
        f"KERNEL QUOTA: {tier} process {kernel_proc.safe_pid(pid)} is over its "
        f"{why}, so this call does not run. "
        + (" ".join(notes) + " " if notes else "")
        + "The cap lives in company/config/kernel.json (shape and defaults: "
        "registry/kernel.yaml). Raise it there, or run this process uncapped on "
        f"purpose: {kernel_proc.UNLOCK}"
    )
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
        _fd = sys.argv[_i + 1] if len(sys.argv) > _i + 1 else None
        # One script proves two rules, so --selftest dispatches on the fixture
        # directory. FLOW.kernel-journal needs the bespoke harness (it asserts
        # the deny names the unlock and that an allowed call really journaled);
        # FLOW.kernel-quota is a plain block/allow rule over seeded state, which
        # is exactly what the shared harness is for.
        if _fd and os.path.basename(str(_fd).rstrip("/\\")) == "FLOW.kernel-quota":
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import gate_selftest
            sys.exit(gate_selftest.run_gate_selftest(os.path.abspath(__file__), _fd))
        sys.exit(_selftest(_fd))
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
