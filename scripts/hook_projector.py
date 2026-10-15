#!/usr/bin/env python3
"""hook_projector.py: the shared core of the second-harness Hook_Projectors.

v11 spec 202610141000, AC-04 (tasks T06 and T07). `merge-hooks-gemini.py` and
`merge-hooks-codex.py` are thin harness definitions over this module, the way
`merge-hooks-cursor.py` projects hooks.json into Cursor. The difference: a
second harness never runs a gate directly. Every projected hook command is

    python3 <shim-dir>/g__shim__hook.py --harness <id> --gate <gate>.py

so the payload translation and the block contract stay in the one file on the
arming surface (scripts/g__shim__hook.py).

What is projected, and why only that:
  - only the hooks.json pre-tool event (PreToolUse), because that is the only
    event the shim translates (Gemini BeforeTool, Codex PreToolUse);
  - only FAIL-CLOSED gates: a script named as a `Gate` mechanism of a rule with
    `enforcement: fail-closed` in registry/rules.yaml;
  - only a hook whose command is `python3 <dir>/<name>.py` with no arguments,
    because the shim runs `--gate <name>.py` with no arguments;
  - only matcher tokens the harness tool-name map translates. Every token it
    cannot translate is written to that harness's `unprojected.matchers` in
    registry/runtimes.yaml, and every other hooks.json event to
    `unprojected.events`, so nothing is dropped silently (FR-02).
  - when writing for a `supported` harness, only tool classes its census record
    shows blocking (violation blocked AND benign allowed).

The `*` matcher is narrowed, not passed through. Under both harnesses the shim
blocks a tool it cannot translate (fail-closed), so a match-all hook would
block every read. `*` becomes the tools the shim translates (shell, file write,
file edit, MCP). The tools outside that set are the residual of `*`; this is
printed on every run.

Matchers are anchored `^(a|b)$`. Gemini CLI tests a matcher with
`new RegExp(matcher).test(toolName)` (bundle source, matchesToolName), a
substring search, so an unanchored `replace` would also fire on any MCP tool
whose name contains it; a matcher that is not a valid regex is compared by
equality, so a bare `*` would match nothing. Codex CLI compiles its matcher
(its binary carries "invalid matcher"); whether it searches or full-matches is
not documented locally, and an anchored regex reads the same either way.

Every projected hook carries an explicit timeout of HOOK_TIMEOUT_S, above the
shim's GATE_BUDGET_S: a harness that kills the shim first reads it as a
non-blocking failure, never as a block.

Modes (same in both projectors):
  (default)          write the hook config to --out and the unprojected lists
                     to the registry. Refused (exit 2, reason printed) for a
                     harness that is not `supported` in registry/runtimes.yaml.
  --check            dry-run: print the projection, the gates projected and
                     not projected, the unprojected tokens, and (Codex) the
                     sandbox setting. Exit 1 on drift of --out (when given and
                     present) or of the registry's unprojected lists. Writes
                     nothing.
  --update-registry  write only the unprojected lists to the registry. Allowed
                     for a `gap` harness: it records what is NOT projected and
                     arms nothing.

Idempotent: a second run with no source change writes nothing (byte-equal).
Never writes a path it was not given: --out has no default.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

HERE = Path(__file__).resolve().parent
BRAIN = HERE.parent
DEFAULT_HOOKS = BRAIN / "hooks.json"
DEFAULT_RULES = BRAIN / "registry" / "rules.yaml"
DEFAULT_REGISTRY = BRAIN / "registry" / "runtimes.yaml"
SHIM = "g__shim__hook.py"
PRE_TOOL = "PreToolUse"

# The shim's gate budget is 45 s (scripts/g__shim__hook.py GATE_BUDGET_S); the
# harness's own hook timeout must sit above it. Tests assert the order.
HOOK_TIMEOUT_S = 60

_PLAIN_CMD = re.compile(r"^python3?\s+(\S+/)?([A-Za-z0-9][A-Za-z0-9_.-]*\.py)$")
_CLAUDE_MCP = re.compile(r"^mcp__([A-Za-z0-9_-]+?)__([A-Za-z0-9_.-]+)$")
_YAML_PLAIN = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")


@dataclass(frozen=True)
class Piece:
    """One alternative of a projected matcher: a regex fragment and its class."""
    regex: str
    tool_class: str


@dataclass
class HarnessSpec:
    id: str                         # registry/runtimes.yaml key
    script: str                     # the projector file name
    event: str                      # the harness's pre-tool event name
    translate: Callable[[str], list | None]   # one non-* token -> [Piece] or None
    wildcard: list                  # pieces `*` narrows to
    hook_config: Callable[[str, str], dict]   # (gate, command) -> hook entry
    # (args) -> (lines to print, drift messages); dry-run only
    extra_check: Callable[[argparse.Namespace], tuple[list[str], list[str]]] | None = None


@dataclass
class Plan:
    groups: list = field(default_factory=list)       # [(source_matcher, [Piece], [gate])]
    projected: list = field(default_factory=list)    # [(gate, source_matcher)]
    skipped: list = field(default_factory=list)      # [(command, matcher, reason)]
    unprojected_events: list = field(default_factory=list)
    unprojected_matchers: list = field(default_factory=list)


# --- sources ----------------------------------------------------------------

def load_json(path: Path) -> dict | None:
    """The JSON object at path; None when absent; raises on a malformed file."""
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    return data


def load_yaml(path: Path):
    import yaml  # type: ignore[import-not-found]
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def fail_closed_gates(rules_path: Path) -> set[str]:
    """Script names of every `Gate` mechanism of a fail-closed rule."""
    data = load_yaml(rules_path) or {}
    out: set[str] = set()
    for rule in data.get("rules") or []:
        if not isinstance(rule, dict) or rule.get("enforcement") != "fail-closed":
            continue
        for mech in rule.get("mechanism") or []:
            if isinstance(mech, dict) and mech.get("kind") == "Gate":
                name = mech.get("canonical_name")
                if isinstance(name, str):
                    out.add(name)
    return out


def registry_entry(registry_path: Path, harness_id: str) -> dict:
    data = load_yaml(registry_path) or {}
    entry = (data.get("runtimes") or {}).get(harness_id)
    if not isinstance(entry, dict):
        raise ValueError(f"{harness_id!r} has no entry in {registry_path}")
    return entry


def census_blocking_classes(census_path: Path | None) -> set[str]:
    """Tool classes the census record shows blocked with the benign twin allowed."""
    if census_path is None or not census_path.exists():
        return set()
    data = load_json(census_path) or {}
    out = set()
    for cls, rec in (data.get("tool_classes") or {}).items():
        if isinstance(rec, dict) and rec.get("harness_blocked_violation") is True \
                and rec.get("harness_allowed_benign") is True:
            out.add(cls)
    return out


# --- planning -----------------------------------------------------------------

def _tokens(matcher) -> list[str]:
    if not isinstance(matcher, str) or not matcher.strip():
        return ["*"]
    return [t.strip() for t in matcher.split("|") if t.strip()]


def _dedup(seq):
    seen, out = set(), []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def build_plan(hooks: dict, gates: set[str], spec: HarnessSpec,
               scripts_dir: Path) -> Plan:
    plan = Plan()
    bad_tokens: list[str] = []
    events: list[str] = []
    for event, entries in hooks.items():
        if event.startswith("$") or not isinstance(entries, list):
            continue
        if event != PRE_TOOL:
            events.append(event)
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            matcher = entry.get("matcher")
            pieces: list[Piece] = []
            for tok in _tokens(matcher):
                got = spec.wildcard if tok == "*" else spec.translate(tok)
                if got:
                    pieces.extend(got)
                else:
                    bad_tokens.append(tok)
            pieces = _dedup(pieces)
            served: list[str] = []
            for hook in entry.get("hooks") or []:
                cmd = (hook or {}).get("command", "") if isinstance(hook, dict) else ""
                m = _PLAIN_CMD.match(cmd.strip())
                name = m.group(2) if m else (re.findall(r"([A-Za-z0-9_.-]+\.py)", cmd) or [cmd])[0]
                if name not in gates:
                    plan.skipped.append((cmd, matcher, "not a fail-closed gate in registry/rules.yaml"))
                elif not m:
                    plan.skipped.append((cmd, matcher, "carries arguments the shim cannot pass (--gate takes a bare script name)"))
                elif not (scripts_dir / name).is_file():
                    plan.skipped.append((cmd, matcher, f"script {name} not found next to the shim"))
                elif not pieces:
                    plan.skipped.append((cmd, matcher, "no matcher token translates to this harness"))
                else:
                    served.append(name)
                    plan.projected.append((name, matcher or "*"))
            if served:
                plan.groups.append((matcher or "*", pieces, served))
    plan.unprojected_events = sorted(set(events))
    plan.unprojected_matchers = sorted(set(bad_tokens))
    return plan


def matcher_regex(pieces: list[Piece]) -> str:
    return "^(" + "|".join(_dedup(p.regex for p in pieces)) + ")$"


def render(plan: Plan, spec: HarnessSpec, shim_dir: str,
           classes: set[str] | None) -> list[dict]:
    """Hook groups for the harness's pre-tool event. `classes` None = no census
    filter (dry-run candidate); a set = keep only pieces of those classes."""
    out = []
    for _src, pieces, served in plan.groups:
        kept = [p for p in pieces if classes is None or p.tool_class in classes]
        if not kept:
            continue
        hooks = []
        for gate in served:
            cmd = " ".join(shlex.quote(x) for x in (
                "python3", f"{shim_dir.rstrip('/')}/{SHIM}", "--harness", spec.id, "--gate", gate))
            hooks.append(spec.hook_config(gate, cmd))
        out.append({"matcher": matcher_regex(kept), "hooks": hooks})
    return out


# --- config merge ----------------------------------------------------------------

def _is_managed(hook, harness_id: str) -> bool:
    cmd = hook.get("command") if isinstance(hook, dict) else None
    return isinstance(cmd, str) and SHIM in cmd and f"--harness {harness_id}" in cmd


def merge_config(existing: dict | None, groups: list[dict], spec: HarnessSpec) -> dict:
    """existing config with our managed hooks replaced by `groups`; foreign
    hooks, groups, events and top-level keys are kept in place."""
    doc = json.loads(json.dumps(existing or {}))
    hooks = doc.get("hooks")
    if hooks is None:
        hooks = {}
    if not isinstance(hooks, dict):
        raise ValueError("existing config has a `hooks` value that is not an object")
    current = hooks.get(spec.event) or []
    if not isinstance(current, list):
        raise ValueError(f"existing config has a `hooks.{spec.event}` value that is not a list")
    kept = []
    for grp in current:
        if not isinstance(grp, dict):
            kept.append(grp)
            continue
        inner = grp.get("hooks")
        if not isinstance(inner, list):
            kept.append(grp)
            continue
        foreign = [h for h in inner if not _is_managed(h, spec.id)]
        if len(foreign) == len(inner):
            kept.append(grp)
        elif foreign:
            g = dict(grp)
            g["hooks"] = foreign
            kept.append(g)
    new_list = kept + groups
    if new_list:
        hooks[spec.event] = new_list
    else:
        hooks.pop(spec.event, None)
    if hooks or "hooks" in doc:
        doc["hooks"] = hooks
    return doc


def managed_groups(doc: dict | None, spec: HarnessSpec) -> int:
    n = 0
    for grp in ((doc or {}).get("hooks") or {}).get(spec.event) or []:
        if isinstance(grp, dict):
            n += sum(1 for h in grp.get("hooks") or [] if _is_managed(h, spec.id))
    return n


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def dump_json(doc: dict) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


# --- registry -----------------------------------------------------------------------

def _yaml_item(tok: str) -> str:
    return tok if _YAML_PLAIN.match(tok) else json.dumps(tok)


def registry_block(spec: HarnessSpec, events: list[str], matchers: list[str]) -> list[str]:
    return [
        f"    # source: scripts/{spec.script} --update-registry, generated from hooks.json;",
        "    # do not edit by hand. `*` is projected narrowed to the tools the shim",
        "    # translates; every other tool is the residual of `*`.",
        "    unprojected:",
        f"      events: [{', '.join(_yaml_item(e) for e in events)}]",
        f"      matchers: [{', '.join(_yaml_item(m) for m in matchers)}]",
    ]


def update_registry_text(text: str, spec: HarnessSpec, events: list[str],
                         matchers: list[str]) -> str:
    """Replace the `unprojected` field (and the comment lines right above it)
    inside the harness's entry. Every other line is kept byte-equal."""
    lines = text.split("\n")
    start = None
    in_runtimes = False
    for i, line in enumerate(lines):
        if line.startswith("runtimes:"):
            in_runtimes = True
            continue
        if in_runtimes and line == f"  {spec.id}:":
            start = i
            break
    if start is None:
        raise ValueError(f"entry `  {spec.id}:` not found under runtimes:")
    end = len(lines)
    for j in range(start + 1, len(lines)):
        ln = lines[j]
        if ln and not ln.startswith("    ") and not ln.startswith("#"):
            end = j
            break
    field_at = None
    for j in range(start + 1, end):
        if re.match(r"^    unprojected:", lines[j]):
            field_at = j
            break
    if field_at is None:
        raise ValueError(f"entry {spec.id!r} has no `unprojected:` field")
    stop = field_at + 1
    while stop < end and lines[stop].startswith("      "):
        stop += 1
    first = field_at
    while first - 1 > start and lines[first - 1].startswith("    #"):
        first -= 1
    return "\n".join(lines[:first] + registry_block(spec, events, matchers) + lines[stop:])


def registry_unprojected(registry_path: Path, harness_id: str) -> tuple[list, list]:
    entry = registry_entry(registry_path, harness_id)
    u = entry.get("unprojected") or {}
    return list(u.get("events") or []), list(u.get("matchers") or [])


# --- CLI -----------------------------------------------------------------------------

def _print_plan(plan: Plan, groups: list[dict], spec: HarnessSpec, label: str) -> None:
    print(f"  {spec.id}: {label}")
    print(f"  projected fail-closed gates ({len(plan.projected)} hook(s), each through {SHIM}):")
    for gate, src in plan.projected:
        print(f"    + {gate}  (hooks.json matcher {src})")
    print(f"  pre-tool hooks NOT projected ({len(plan.skipped)}):")
    for cmd, src, why in plan.skipped:
        print(f"    - {cmd}  [{src}]: {why}")
    print(f"  unprojected events: {', '.join(plan.unprojected_events) or '(none)'}")
    print(f"  unprojected matcher tokens: {', '.join(plan.unprojected_matchers) or '(none)'}")
    wild = ", ".join(_dedup(p.regex for p in spec.wildcard))
    print(f"  `*` narrowed to: {wild} (any other tool runs unguarded under this harness)")
    print(f"  {spec.event} projection ({sum(len(g['hooks']) for g in groups)} hook(s), "
          f"timeout {HOOK_TIMEOUT_S} s each):")
    print(json.dumps({"hooks": {spec.event: groups}}, indent=2, ensure_ascii=False))


def run(spec: HarnessSpec, argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog=spec.script,
                                 description=f"Project hooks.json into {spec.id} hooks through {SHIM}")
    ap.add_argument("--check", action="store_true",
                    help="dry-run: print the projection; exit 1 on drift; write nothing")
    ap.add_argument("--update-registry", action="store_true",
                    help="write only the unprojected lists to the registry (any status)")
    ap.add_argument("--out", type=Path, help="the harness hook config file to write or check")
    ap.add_argument("--hooks", type=Path, default=DEFAULT_HOOKS)
    ap.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    ap.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    ap.add_argument("--census", type=Path, default=None,
                    help="census record (default: the registry entry's `census`)")
    ap.add_argument("--scripts-dir", type=Path, default=HERE,
                    help="where the gates are checked to exist (default: next to this file)")
    ap.add_argument("--shim-dir", default=os.path.expanduser("~/.claude/scripts"),
                    help="directory of the shim in the projected command")
    ap.add_argument("--project", type=Path, default=None,
                    help="(Codex) the project root for the sandbox writable roots")
    args = ap.parse_args(argv)

    try:
        hooks = load_json(args.hooks)
        if hooks is None:
            print(f"  no {args.hooks}: nothing to project")
            return 0
        gates = fail_closed_gates(args.rules)
        entry = registry_entry(args.registry, spec.id)
    except Exception as exc:
        print(f"  ✗ {spec.script}: cannot read sources: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    status = entry.get("status")
    census = args.census
    if census is None and isinstance(entry.get("census"), str):
        census = args.registry.resolve().parent.parent / entry["census"]
    plan = build_plan(hooks, gates, spec, args.scripts_dir)
    supported = status == "supported"
    blocking = census_blocking_classes(census) if supported else set()
    effective = render(plan, spec, args.shim_dir, blocking) if supported else []

    reg_text = args.registry.read_text(encoding="utf-8")
    reg_new = update_registry_text(reg_text, spec, plan.unprojected_events, plan.unprojected_matchers)

    if args.check:
        if supported:
            _print_plan(plan, effective, spec,
                        f"supported; census classes blocking: {', '.join(sorted(blocking)) or '(none)'}")
        else:
            candidate = render(plan, spec, args.shim_dir, None)
            _print_plan(plan, candidate, spec,
                        f"status {status!s}: DRY-RUN candidate, not writable until the census "
                        "marks the harness supported (no census class filter applied)")
        drift = []
        if reg_new != reg_text:
            drift.append(f"{args.registry}: unprojected lists differ from the projection "
                         f"(run {spec.script} --update-registry)")
        if args.out is not None:
            try:
                existing = load_json(args.out)
            except Exception as exc:
                drift.append(f"{args.out}: unreadable: {exc}")
                existing = None
            else:
                if existing is None:
                    print(f"  absent: {args.out} not materialized")
                elif not supported and managed_groups(existing, spec):
                    drift.append(f"{args.out}: holds {spec.id} shim hooks although the harness is "
                                 f"{status}, not supported")
                elif supported and merge_config(existing, effective, spec) != existing:
                    drift.append(f"{args.out}: differs from the projection")
        if spec.extra_check:
            lines, more = spec.extra_check(args)
            for line in lines:
                print(line)
            drift.extend(more)
        if drift:
            for d in drift:
                print(f"  ✗ drift: {d}")
            return 1
        print("  ✓ in sync")
        return 0

    if args.update_registry:
        if reg_new != reg_text:
            atomic_write_text(args.registry, reg_new)
            print(f"  ✓ {args.registry}: {spec.id} unprojected events "
                  f"{len(plan.unprojected_events)}, matcher tokens {len(plan.unprojected_matchers)}")
        else:
            print(f"  {args.registry}: {spec.id} unprojected lists already in sync")
        return 0

    if not supported:
        print(f"  ✗ {spec.script}: refused. {spec.id} is `{status}` in {args.registry}, not "
              "`supported`: no census record shows it blocking the shell, file write and file "
              "edit classes (AC-03, AC-04), so no hook config is written. Run with --check for "
              "the dry-run projection.", file=sys.stderr)
        return 2
    if args.out is None:
        print(f"  ✗ {spec.script}: --out is required to write (no default target)", file=sys.stderr)
        return 2
    try:
        existing = load_json(args.out)
        merged = merge_config(existing, effective, spec)
    except Exception as exc:
        print(f"  ✗ {spec.script}: {args.out}: {exc}", file=sys.stderr)
        return 2
    changed = False
    if existing != merged or existing is None:
        atomic_write_text(args.out, dump_json(merged))
        changed = True
    if reg_new != reg_text:
        atomic_write_text(args.registry, reg_new)
        changed = True
    n = sum(len(g["hooks"]) for g in effective)
    print(f"  {'✓ projected' if changed else 'already in sync'}: {n} hook(s) -> {args.out}")
    return 0
