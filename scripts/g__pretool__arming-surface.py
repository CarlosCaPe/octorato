#!/usr/bin/env python3
"""g__pretool__arming-surface.py: the LIVE files that decide whether gates run.

RULE #1 says a rule is wired only when its mechanism is verifiably live. Every
mechanism in this brain is live because ONE file registers it and ONE file is
its body. Those files are the arming surface, and until now nothing watched
them. Measured, twice, on 2026-09-08:

  - ~/.claude/settings.json carries `permissions` and, when present, an `env`
    block that Claude Code injects into the session, HOOKS INCLUDED. The merge
    gate's whole agent-proofness rests on OCTO_MERGE_APPROVE being unreachable
    from the model's process; it is. It is NOT unreachable from the NEXT
    session, because a process that writes an `env` block here exports that
    variable into every hook the harness spawns afterwards.
  - No PreToolUse hook watched settings.json, and none watched the gate scripts
    either: `grep settings.json scripts/g__pretool*.py` returned nothing.

So the claim "the agent cannot self-approve its own gate" was true of the env
and false of the REGISTRATION that invokes the reader of that env. A gate whose
registration and whose body an agent can rewrite is not a gate; it is a note.

THE BOUNDARY, and why it is drawn here.

A blanket deny on the gate scripts would make this brain undevelopable by its
own agent: editing `qa-merge-gate.py` or a tree-owner gate is this operator's
normal work, and it happened in the same session that measured the hole. A gate
that blocks real work gets turned off, which is how the over-firing merge gate
ended up being routed around with base64 payloads an hour earlier.

What separates the two is not the file, it is the COPY. Measured here:

  $ git worktree list
  /home/…/.claude                  [master]        <- the MAIN tree
  /home/…/.octorato/wt/qa-gate     [fix/qa-gate…]  <- a secondary worktree
  … 12 more

`~/.claude` is the main worktree of the octorato repo, and it is the tree the
harness actually reads: `hooks.json` commands are literal `~/.claude/scripts/…`
paths, and settings.json has no other copy at all. Every `wt/*` and `dim/*`
checkout is a sibling directory holding SOURCE. So:

    editing scripts/qa-merge-gate.py in a worktree  = development, reviewed,
                                                      merged through the PR path
    editing ~/.claude/scripts/qa-merge-gate.py      = disarming what is loaded

This gate denies only the second. The PR path stays fully open, and so does the
route by which a merged change reaches the live tree: `ai-sync` / `ai-pull` /
`git pull` run the update inside a subprocess of a thunk, so no protected path
is ever a Bash TARGET and nothing here fires. That is deliberate, not an
oversight: a pull brings the REVIEWED remote state, which is the sanctioned way
for the live tree to change.

Two paths reach the live copy without naming a worktree, and both are covered:
a symlink (every candidate is tested a second time through os.path.realpath),
and a `git -C ~/.claude checkout -- <path>` from anywhere (the shared parser
resolves `-C` before the target is tested).

THE FILE SET, and why each one is an arming surface.

  settings.json, settings.local.json
      The registration surface AND the injected `env`. Both are GITIGNORED
      (measured: `git check-ignore -v` hits .gitignore:42 and :89), so they
      exist ONLY in the live tree. There is no development copy of these two
      and therefore no development case to protect: every write to them is a
      write to the arming surface. This is the file that makes the merge gate's
      OCTO_MERGE_APPROVE forgeable for the next session.
  <any dir>/.claude/settings*.json inside the live root
      The same surface at PROJECT scope, which OUTRANKS user scope. The two
      files above are the USER-scope pair; Claude Code also loads
      `<project root>/.claude/settings.json` and `settings.local.json`, and the
      brain root is itself a project root (`cd ~/.claude` is how this repo is
      developed, and it is literally what the `ai-push` thunk does). Measured
      2026-09-08, before this was covered:

        DENY   Write ~/.claude/settings.json
        ALLOW  Write ~/.claude/.claude/settings.json         (9705 B, 109 allow)
        ALLOW  Write ~/.claude/.claude/settings.local.json  (14756 B, 182 allow)

      The exact disarm this gate exists to prevent was reachable one directory
      over, because the set was named by FILENAME while the effect is "settings
      the next session loads". The test is now a path SHAPE, not a list, so the
      next subdirectory does not reopen it: any `settings*.json` under any
      `.claude/` directory anywhere inside the live root, plus a `.claude`
      directory THAT HOLDS ONE (taking the directory takes the file without
      naming it; a `.claude` holding no settings disarms nothing by being
      deleted, and the live tree carries several of those). That covers deeper
      project roots without enumerating them, and the live tree really carries
      one: claude-mem-ref/.claude/settings.json.

      SCOPES COVERED: user (`<brain>/settings*.json`), project, for every
      project root INSIDE the live tree, and the harness user config
      `~/.claude.json` (next entry, covered by name because it is the one
      member outside the root).
      SCOPES THIS GATE CANNOT SEE, both measured, both a residual below:
      enterprise/managed policy outside $HOME, and any project root outside the
      live root (an arm's own `.claude/settings.json` is that arm's business,
      not this gate's).
      NOT an arming surface, checked rather than assumed: a worktree's
      `hooks.json`. It is octorato's tracked source, projected into the live
      settings.json by merge-hooks.py and guarded by check-hooks-drift.py; the
      harness never loads `<repo>/hooks.json`. Every `wt/*` and `dim/*` copy
      stays writable (measured: 6 of 6 ALLOW).
  ~/.claude.json
      The harness's USER CONFIG, and the one member of this set that lives
      outside the live root: a sibling of the brain directory, not a file
      inside it. It carries `mcpServers`, measured 2026-09-08 as three entries,
      each an object with `command`, `args`, `env` and `type`. Writing it names
      a PROGRAM the next session executes at startup with an environment of the
      writer's choosing, which is the same disarm class as an `env` block in
      settings and a worse one, since it is a direct command rather than a
      variable. The rule is "the surfaces that arm the next session", so this
      one is covered by NAME while everything under the root stays covered by
      shape. There is nothing to fight for a development path, checked rather
      than assumed: a PreToolUse hook only ever sees the AGENT's tool calls,
      never the harness writing its own state file, so denying the agent's
      write costs the harness nothing, exactly like the live settings.json
      whose only legitimate writer is also not a hooked process. Measured
      after: Write, Edit, `sed -i`, a `>` redirect, `cp`, `mv`, `rm` and an
      interpreter write all deny; `cat`, a `-c` READ, `~/.claude.json.bak` and
      a worktree copy all allow.
  hooks.json
      The tracked source of the registrations; settings.json's hook block is
      its projection (brain_doctor: "settings.json hooks == validated hooks.json
      projection"). Deleting a line here unregisters a gate without touching
      the gate.
  scripts/g__pretool*.py, scripts/g__stop__*.py, scripts/qa-merge-gate.py
      The bodies of the fail-closed gates. This gate is inside its own pattern,
      on purpose: a floor that exempts itself is not a floor.
  scripts/gate_selftest.py
      The harness whose verdict brain_doctor reads to declare a gate live. A
      selftest that always passes turns the whole gate-liveness check into a
      rubber stamp, so it arms every gate at once.
  scripts/receipt_ledger.py
      The receipt reader: it decides whether a seek receipt, a gate receipt or
      a QA receipt is real. Every v7 boundary consults it.
  scripts/kernel_proc.py, scripts/dimension-awareness-hook.py
      The modules the gates IMPORT at run time, measured rather than guessed:
      `grep -hE "spec_from_file_location|^import" scripts/g__*.py` names
      exactly kernel_proc, receipt_ledger, dimension-awareness-hook and the two
      tree-owners. Protecting a gate and leaving the library it executes
      writable protects nothing, so the closure is in the set, not just the
      entry points.
  scripts/brain_doctor.py
      The prover. RULE #1 is wired BY brain_doctor: it runs every gate's
      --selftest and .githooks/pre-push blocks on its exit code. A doctored
      doctor reports a corrupt brain as healthy and lets the push through, the
      same failure class as a doctored gate_selftest.py.
  registry/rules.yaml
      The Registry RULE #1 loads. A rule deleted here stops being asserted.
  .githooks/pre-push
      The push-time leak guard and the invoker of brain_doctor's fail-closed
      wiring assertion.

Plus one WHOLE-TREE class: `git checkout <branch>`, `git switch`,
`git reset --hard|--merge|--keep`, `git stash`, `git clean -f`,
aimed at the live root. They rewrite every file in the set at once, so a
file-by-file deny that ignored them would be trivially walked around with one
branch switch. `git worktree remove` is deliberately NOT one of them: it
deletes a sibling checkout and rewrites nothing here.

NO ENV UNLOCK, deliberately. Every other gate here prints one, and an env
unlock for THIS rule would be self-serve: the variable that lifts it is exactly
the kind of thing an agent would write into the settings.json `env` block this
gate exists to protect. Same stance and same words as the kernel's own state
floor, which denies every hooked process including itself: the operator's
terminal is not hooked and stays the only writer.

NAMED RESIDUALS, measured, deliberately not covered:
  - An INTERPRETED write. `python3 scripts/merge-hooks.py` legitimately writes
    settings.json, and a hook never sees inside a subprocess. Only Write/Edit
    and shell mutations are targets here. A best-effort layer reads a `-c`
    body for a protected literal next to a write marker (open(…,'w'),
    write_text, json.dump, writeFileSync); a read of the same file through the
    same `-c` passes, which is why the layer needs the marker. Anything that
    reaches the file through a script file, a variable or an unlisted write
    idiom passes. Reproduction: see registry/fixtures/…/README-residuals.txt.
    Every one of the 14 markers is individually load-bearing: each has a
    violation fixture whose body carries THAT marker and no other, and deleting
    the marker from the list turns that fixture red (proven by running all 14
    deletions). Before that, 12 of 14 were dead weight, provable by deleting
    them with the selftest still green.
  - A SETTINGS SCOPE OUTSIDE THE LIVE ROOT, minus the one that was taken.
    `~/.claude.json` used to be listed here as "the strongest uncovered surface
    left", on the reasoning that the harness rewrites it every session and a
    deny would leave no development path. That reasoning was wrong and is
    recorded here so it does not come back: a PreToolUse hook never sees the
    harness write its own state file, only the agent's tool calls, so there was
    nothing to fight. It is now covered by name (see the file set above).
    What remains: enterprise/managed policy
    (`/etc/claude-code/managed-settings.json` on Linux) is outside $HOME and
    root-owned, so the OS is the gate there and this one never sees it; a
    project root outside the live tree (an arm's `.claude/settings.json`) is
    that arm's business. Reproduction: `Write /etc/claude-code/
    managed-settings.json` and a write to an arm's own settings are allowed.
  - AN ANCESTOR-DIRECTORY DELETE OF A DEEP PROJECT ROOT. `rm -rf
    ~/.claude/claude-mem-ref` takes that root's `.claude/settings.json` without
    naming it or its `.claude` directory. Covering it means listing the live
    tree on the hot path for every rm, which is the cost this gate refuses to
    pay; `rm -rf ~/.claude` and `rm -rf ~/.claude/.claude` are both denied
    because they conflict with a path the classifier already holds.
    Reproduction: `rm -rf ~/.claude/claude-mem-ref` is allowed.
  - `git merge`, `git pull`, `git rebase`, `git apply` in the live tree: the
    shared parser classifies none of them as whole-tree, and they are the
    sanctioned route by which reviewed work lands. Reproduction: `git -C
    ~/.claude merge feat/anything` is allowed.
  - A NON-Bash, NON-Write tool that writes a file. The gate reads targets from
    Write/Edit/NotebookEdit/MultiEdit and from Bash; an MCP tool that takes a
    path and writes it would pass. Measured against the servers registered on
    this runtime today (gmail, whatsapp, bonsai, repomix, claude-in-chrome,
    Google Drive/Calendar, Microsoft Learn, Cloudflare), none writes an
    arbitrary local path, so this is a gap in shape, not in reach. It is left
    open rather than closed by testing every tool that carries a `file_path`,
    because that would deny a READ of settings.json through such a tool, and an
    over-firing gate is the failure mode this whole boundary was drawn to
    avoid. Registering on the `*` matcher is what makes closing it later a
    one-line change here rather than a new registration.
  - Everything the shared parser already names as its own residual (rsync
    --delete, shred, ln -sf, perl -pi, variable expansion, a `-c` body nested
    deeper than 3, xargs fed from stdin). This gate inherits that list rather
    than growing a second parser.

Hot path: one `paths_conflict` against the brain root rejects everything
outside ~/.claude before any listing or realpath happens, and the shared
parser's own trigger test returns [] before it loads anything, so an ordinary
`ls` or `pytest` never reaches the expensive half. Measured warm on this
machine: ~65 ms for `import kernel_proc` on every call (the same import
g__pretool__kernel.py already pays on the same `*` matcher), ~1 ms for a
command with no mutation token, and ~90-190 ms more for one that has a token
(the shared parser loading dimension-awareness-hook.py, which the Bash
tree-owner gate is already paying in parallel for the same command). Same-event
hooks run in parallel, so the wall-clock addition is bounded by the slowest
hook, not the sum. Everything except a real hit fails OPEN.

NO `timeout` IN THE REGISTRATION, decided rather than inherited. The sibling
PreToolUse gates carry `timeout: 5`; this one carries none and takes the
harness default of 60 s. A timeout is a KILL, and a killed hook writes nothing
to stdout, which the harness reads as ALLOW. So for a fail-closed gate the
timeout is not a safety budget, it is the cheapest disarm available to anyone
who can make the gate slow: with `timeout: 5` an adversarial input has to stall
5 s to be let through, with 60 s it has to stall 60. Measured worst cases here
are ~1.3 s for a 200 KB command and ~0.2 s for 500 targets, so neither number
binds on real traffic and the only thing the smaller one changes is how easy
the kill is. The cost of the larger one is honest and accepted: a genuinely
hung call (a stat that blocks on a dead mount) makes the user wait up to a
minute instead of five seconds. For a floor-class gate, waiting is the correct
failure and being skipped is not. Symmetry with the siblings is not a reason.

Stdin:  PreToolUse payload {"tool_name", "tool_input", "cwd", …}
Stdout: deny JSON on a hit, else nothing. Exit always 0.
"""
from __future__ import annotations

import fnmatch
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import kernel_proc  # noqa: E402  (stdlib-only, hot-path budgeted)

_HERE = os.path.dirname(os.path.abspath(__file__))
RULE_ID = "ARCHITECTURE.arming-surface"
WRITE_TOOLS = ("Write", "Edit", "NotebookEdit", "MultiEdit")

# Files with exactly one copy that matters: the live one. Relative to the brain
# root so a sandboxed HOME (every selftest leg) resolves its own.
_EXACT = {
    "settings.json":
        "the harness's registration surface: `permissions` and the `env` block "
        "Claude Code injects into every hook it spawns next session, which is "
        "where OCTO_MERGE_APPROVE would become forgeable",
    "settings.local.json":
        "the per-machine half of the same registration surface, injected the "
        "same way",
    "hooks.json":
        "the registration source every gate is projected from: unregister a "
        "line here and the gate stops being invoked without being touched",
    "registry/rules.yaml":
        "the Registry that RULE #1 loads: a rule deleted here stops being "
        "asserted at all",
    ".githooks/pre-push":
        "the push-time gate that runs brain_doctor's wiring assertion",
}

# Gate bodies under scripts/. Patterns, not a list, so a NEW g__pretool*.py
# dropped into the live tree is covered the moment it is created.
_SCRIPT_PATTERNS = ("g__pretool*.py", "g__stop__*.py", "qa-merge-gate.py",
                    "gate_selftest.py", "brain_doctor.py", "receipt_ledger.py",
                    "kernel_proc.py", "dimension-awareness-hook.py")
_SCRIPT_WHY = ("the body of a fail-closed gate (or the harness and libraries "
               "every gate is proven and read by)")

# PROJECT-scope settings, which outrank the user-scope pair above. A session
# whose cwd is a project root loads `<root>/.claude/settings.json` and
# `settings.local.json` ON TOP of `~/.claude/settings.json`, and the brain root
# IS such a project root: `cd ~/.claude` is how this repo is developed and what
# the `ai-push` thunk does. Measured 2026-09-08 on the live tree, before this
# was covered: ~/.claude/.claude/settings.json (9705 bytes, 109 allow entries)
# and settings.local.json (14756 bytes, 182) both existed and both were
# WRITABLE while ~/.claude/settings.json was denied. Same loaded effect, one
# directory over, which is a set named by FILENAME instead of by EFFECT.
#
# So the test is a path SHAPE, not a list: `<anything>/.claude/settings*.json`
# under the live root. That covers every project root inside the live tree
# without enumerating them, including the vendored reference checkouts measured
# today (claude-mem-ref/.claude/settings.json). A `.claude` directory itself is
# in the set too, because deleting or moving it rewrites the settings it holds
# without ever naming them.
_PROJECT_DIRNAME = ".claude"
_PROJECT_SETTINGS_GLOB = "settings*.json"
_PROJECT_WHY = (
    "a PROJECT-scope settings file, which the harness loads ON TOP of the "
    "user-scope one and which OUTRANKS it: same `permissions` and same `env` "
    "block injected into every hook the next session spawns, one directory "
    "over from the file this gate already denied"
)
_PROJECT_DIR_WHY = (
    "the PROJECT-scope settings directory the harness reads when a session "
    "starts in this root: taking the directory takes settings*.json inside it "
    "without ever naming the file"
)

# The ONE member of the set that lives outside the live root. `~/.claude.json`
# is the harness's user config, a sibling of the brain directory rather than a
# file inside it, and it carries `mcpServers`: measured 2026-09-08, three
# entries, each an object with `command`, `args`, `env` and `type`. Writing it
# names a PROGRAM the next session executes at startup with an environment of
# the writer's choosing, which is the same disarm class as an `env` block in
# settings and a worse one, since it is a direct command rather than a
# variable. The rule this gate enforces is "the surfaces that arm the next
# session"; most of them sit under the live root, this one does not, so it is
# covered by NAME while everything under the root stays covered by shape.
#
# There is no development case to protect, checked rather than assumed: a
# PreToolUse hook only ever sees the AGENT's tool calls, never the harness
# writing its own state file, so denying the agent's write costs the harness
# nothing. Same position as the live settings.json, whose only legitimate
# writer is also not a hooked process.
_USER_CONFIG_NAME = ".claude.json"
_USER_CONFIG_WHY = (
    "the harness's user config, which carries `mcpServers`: each entry names a "
    "`command` plus its `args` and `env`, so a write here hands the NEXT "
    "session a program to run at startup in an environment of the writer's "
    "choosing. It is the one arming surface outside the live root, covered by "
    "name because it has no copy anywhere else"
)

# Whole-tree git verbs, as the shared parser labels them: they rewrite every
# file in the set at once. `git worktree remove` is the one the shared parser
# calls whole-tree that is NOT one here, measured: it deletes a SIBLING
# checkout and never rewrites a file in the live tree, so denying it would cost
# real housekeeping (removing a merged worktree from ~/.claude) to prevent
# nothing. The collision it does cause, taking a tree another process is
# working in, stays denied by the tree-owner gate that owns that rule.
_TREE_KINDS = ("tree",)
_TREE_EXEMPT = ("git worktree remove",)

# Interpreter `-c` bodies: best-effort only, and only with a write marker, so a
# `python3 -c` that READS settings.json (a real, frequent shape) still passes.
#
# Every marker below is PROVEN, one fixture each. The list used to be a claim:
# only `'w'` and `.write(` appeared in any fixture, and they appeared in the
# SAME body, so deleting the other 12 left the selftest green and the list said
# nothing about what the gate catches. Each entry now has
# `violation_marker_<slug>.json` whose `-c` body carries THAT marker and no
# other (checked mechanically), a `benign_marker_<slug>.json` one edit away
# that reads the same file through the same idiom, and the violation's
# expectation names the marker in the deny text, so a fixture cannot pass on
# some other entry's behalf. Deleting any one marker turns exactly its own
# fixture red; all 14 deletions were run.
# `writeFileSync`/`appendFileSync` are Node idioms and node takes `-e`, not
# `-c`, so their reachable shape is a nested one (`sh -c "node -e …"`) and that
# is what their fixtures use.
_C_HOSTS = ("bash", "sh", "zsh", "dash", "python", "python3", "py", "node",
            "perl", "ruby")
_WRITE_MARKERS = ("'w'", '"w"', "'w+'", '"w+"', "'a'", '"a"',
                  "write_text", ".write(", "writelines", "json.dump(",
                  "writeFileSync", "appendFileSync", "os.replace(", "shutil.copy")


def deny(reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }, ensure_ascii=False))


def journal_deny(pid, fields: dict) -> None:
    try:
        rec = {"kind": "deny", "rule": RULE_ID, "gate": "arming-surface"}
        rec.update(fields)
        kernel_proc.append(pid, rec)
    except Exception:
        pass


def brain_root() -> str:
    return kernel_proc.norm_path(kernel_proc.brain_dir())


def scripts_dir() -> str:
    return os.path.join(brain_root(), "scripts")


def user_config_path(brain: str) -> str:
    """`~/.claude.json`, derived from the brain root so a sandboxed HOME (every
    selftest leg) resolves its own instead of the real one."""
    return os.path.join(os.path.dirname(brain), _USER_CONFIG_NAME)


def _is_gate_script(basename: str) -> bool:
    return any(fnmatch.fnmatch(basename, p) for p in _SCRIPT_PATTERNS)


def project_scope(target: str, brain: str) -> tuple:
    """(live_path, why) when `target` is project-scope settings INSIDE the live
    root, else (None, None). Pure string work, no stat and no listing, so it
    costs nothing on the hot path.

    Only paths strictly under the live root are tested here. The root itself
    and any ancestor of it are already a hit through _EXACT (a target that
    contains ~/.claude contains ~/.claude/settings.json), so they never reach
    this and never need a second answer.
    """
    if not target.startswith(brain + os.sep):
        return None, None
    parts = target[len(brain) + 1:].split(os.sep)
    if len(parts) >= 2 and parts[-2] == _PROJECT_DIRNAME and \
            fnmatch.fnmatch(parts[-1], _PROJECT_SETTINGS_GLOB):
        return target, _PROJECT_WHY
    if parts[-1] == _PROJECT_DIRNAME and _holds_settings(target):
        return target, _PROJECT_DIR_WHY
    return None, None


def _holds_settings(directory: str) -> bool:
    """True when a `.claude` directory actually holds settings to take.

    The shape alone over-fires, measured: the live tree carries `.claude`
    directories that hold no settings at all (vendored reference checkouts
    under knowledge/, the `home/.claude` fixture roots), and denying
    housekeeping on those buys nothing, since a directory with no settings
    disarms nothing by being deleted. Nothing is lost by asking: creating an
    empty `.claude` is allowed, and the FILE rule denies putting settings into
    it, so the line is held by the file test either way.

    Unreadable counts as TRUE. A directory of exactly this shape that cannot be
    listed is the ambiguous case, and this gate resolves ambiguity closed. One
    listdir, reached only after the fast-out has proven the path is inside the
    live root, so an ordinary command never pays it.
    """
    try:
        names = os.listdir(directory)
    except (FileNotFoundError, NotADirectoryError):
        return False
    except OSError:
        return True
    return any(fnmatch.fnmatch(n, _PROJECT_SETTINGS_GLOB) for n in names)


def classify(target: str) -> tuple:
    """(live_path, why) when `target` reaches a live arming surface, else
    (None, None). Containment counts in BOTH directions: `rm -rf
    ~/.claude/scripts` never names a gate and takes every one of them."""
    if not target:
        return None, None
    brain = brain_root()
    cfg = user_config_path(brain)
    if kernel_proc.paths_conflict(target, cfg):
        return cfg, _USER_CONFIG_WHY           # the one member outside the root
    if not kernel_proc.paths_conflict(target, brain):
        return None, None                      # fast out: not in the brain
    for rel, why in _EXACT.items():
        live = os.path.join(brain, *rel.split("/"))
        if kernel_proc.paths_conflict(target, live):
            return live, why
    live, why = project_scope(target, brain)
    if live:
        return live, why
    sdir = scripts_dir()
    if kernel_proc.paths_conflict(target, sdir):
        if target == sdir or sdir.startswith(target + os.sep):
            # the target IS scripts/ or an ancestor of it: it takes every gate
            return sdir, _SCRIPT_WHY + ", all of them at once"
        if _is_gate_script(os.path.basename(target)):
            return target, _SCRIPT_WHY
    return None, None


def candidates(target: str) -> list:
    """The path as written and the path the file system actually reaches. A
    symlink under a worktree pointing at the live file is a path that LOOKS
    like development, so both spellings are tested."""
    out = []
    norm = kernel_proc.norm_path(target)
    if norm:
        out.append(norm)
        try:
            real = kernel_proc.norm_path(os.path.realpath(norm))
        except Exception:
            real = ""
        if real and real != norm:
            out.append(real)
    return out


def hit(target: str) -> tuple:
    for cand in candidates(target):
        live, why = classify(cand)
        if live:
            return live, why
    return None, None


# ── Bash side: one parser for the whole brain, borrowed not copied ───────────

def _bash_scan():
    """Borrow the command scanner the Bash tree-owner gate already proves
    (g__pretool-bash__tree-owner.py:553). It resolves `cd`, `git -C`,
    `--work-tree`, redirects, subshells, wrappers and `-c` bodies, and it is
    boundary-aware, so `git commit -m "edit settings.json"` is one token to
    shlex and never becomes a target. A second copy would drift, and the drift
    would be invisible until a deny failed to fire."""
    import importlib.util
    path = os.path.join(_HERE, "g__pretool-bash__tree-owner.py")
    spec = importlib.util.spec_from_file_location("tree_owner_bash_borrow", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.scan


def _needles() -> list:
    """Literal spellings of a protected path an interpreter body could carry.

    The project-scope pair is spelled out here rather than derived from the
    path SHAPE the classifier uses, because a literal scan has nothing to match
    a shape against: it needs the string. That names the one project root that
    is always there (the brain root itself, the root `cd ~/.claude` opens); a
    deeper project root inside the live tree is covered by the classifier for
    Write/Edit and shell mutations, and is a named residual for this
    best-effort `-c` layer only.
    """
    brain = brain_root()
    out = []
    rels = list(_EXACT) + [_PROJECT_DIRNAME + "/settings.json",
                           _PROJECT_DIRNAME + "/settings.local.json"]
    for rel in rels:
        out.append(os.path.join(brain, *rel.split("/")))
        out.append("~/.claude/" + rel)
    out.append(user_config_path(brain))
    out.append("~/" + _USER_CONFIG_NAME)
    return out


def interpreter_write(command: str):
    """(literal, marker) when a `<interp> -c <body>` writes a protected path.

    Best-effort by construction and gated on a write marker: the same shape
    reading the same file is a real, frequent command (`python3 -c "json.load
    (open('~/.claude/hooks.json'))"`) and must pass."""
    import shlex
    if "-c" not in command:
        return None
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    for i, tok in enumerate(tokens):
        if tok != "-c" or i + 1 >= len(tokens):
            continue
        base = os.path.basename(tokens[i - 1]) if i else ""
        if base.rstrip("0123456789") not in _C_HOSTS and base not in _C_HOSTS:
            continue
        body = tokens[i + 1]
        marker = next((m for m in _WRITE_MARKERS if m in body), None)
        if not marker:
            continue
        for needle in _needles():
            if needle in body:
                return needle, marker
    return None


def bash_targets(command: str, cwd: str) -> list:
    """(kind, target, verb) triples worth testing, from the shared parser."""
    try:
        scan = _bash_scan()
        return scan(command, cwd)
    except Exception:
        return []            # a parser that cannot read the command denies nothing


# ── deny copy ───────────────────────────────────────────────────────────────

_ONLY_WRITER = (
    "No hooked process edits the live copy, this gate included. The operator's "
    "terminal is not hooked and stays the only writer. There is no env unlock "
    "for this rule on purpose: the variable that lifted it would be writable "
    "from the very file this protects."
)
_DEV_PATH = (
    "Editing this file is normal development and stays allowed IN A WORKTREE "
    "(`git worktree list`; every ~/.octorato/wt/* checkout is source). Make the "
    "change there, open a PR, and let `ai-sync` / `git pull` land it here."
)


def deny_file(verb: str, target: str, live: str, why: str) -> None:
    deny(
        f"ARMING SURFACE: `{verb}` targets {target}, which reaches {live} in the "
        f"LIVE brain tree ({brain_root()}). That file is {why}. It is not source "
        f"here, it is what the harness loads, so writing it disarms the gates for "
        f"the next session without ever running a gated command. {_DEV_PATH} "
        f"{_ONLY_WRITER}"
    )


def deny_tree(verb: str, root: str) -> None:
    deny(
        f"ARMING SURFACE: `{verb}` rewrites the whole working tree at {root}, "
        f"which is the LIVE brain the harness loads. One branch switch swaps "
        f"settings.json's projection, hooks.json and every gate script at once, "
        f"so a file-by-file deny that let this through would protect nothing. "
        f"{_DEV_PATH} {_ONLY_WRITER}"
    )


def deny_interp(literal: str, marker: str) -> None:
    deny(
        f"ARMING SURFACE: this interpreter body writes {literal} (write marker "
        f"`{marker}`) in the LIVE brain tree. Reading that file through the same "
        f"`-c` is allowed; writing it is not, because it is what the harness "
        f"loads. {_DEV_PATH} {_ONLY_WRITER}"
    )


# ── main ────────────────────────────────────────────────────────────────────

def write_targets(tool_input: dict) -> list:
    out = []
    for key in ("file_path", "notebook_path", "path"):
        val = tool_input.get(key)
        if isinstance(val, str) and val:
            out.append(val)
    edits = tool_input.get("edits")
    if isinstance(edits, list):
        for e in edits:
            if isinstance(e, dict) and isinstance(e.get("file_path"), str):
                out.append(e["file_path"])
    return out


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    tool = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return 0
    pid = kernel_proc.resolve_pid(payload)

    if tool in WRITE_TOOLS:
        for target in write_targets(tool_input):
            live, why = hit(target)
            if live:
                journal_deny(pid, {"target": target, "live": live, "verb": tool})
                deny_file(tool, kernel_proc.norm_path(target), live, why)
                return 0
        return 0

    if tool != "Bash":
        return 0
    command = str(tool_input.get("command") or "")
    if not command.strip():
        return 0
    brain = brain_root()

    for kind, target, verb in bash_targets(command, str(payload.get("cwd") or "")):
        if kind in _TREE_KINDS:
            if verb in _TREE_EXEMPT:
                continue
            if target and kernel_proc.norm_path(target) == brain:
                journal_deny(pid, {"root": target, "verb": verb, "why": "live-tree"})
                deny_tree(verb, brain)
                return 0
            continue
        if kind in ("glob", "iglob"):
            target = os.path.dirname(target or "")
        elif kind not in ("path", "state"):
            continue                      # 'stage' stages, it does not rewrite
        live, why = hit(target)
        if live:
            journal_deny(pid, {"target": target, "live": live, "verb": verb,
                               "command": command[:200]})
            deny_file(verb, kernel_proc.norm_path(target), live, why)
            return 0

    found = interpreter_write(command)
    if found:
        journal_deny(pid, {"literal": found[0], "marker": found[1],
                           "why": "interpreter-write", "command": command[:200]})
        deny_interp(found[0], found[1])
    return 0


# ── selftest ────────────────────────────────────────────────────────────────

def _selftest(fdir: str = None) -> int:
    """Every leg through the real main(), each in its own sandbox HOME.

    The sandbox is what makes this testable at all: kernel_proc.brain_dir() is
    HOME-relative and lazy, so `$HOME/.claude` inside the sandbox IS the live
    tree for the leg, and `$HOME/wt/<name>` is a worktree of it. The benign
    legs are the point of the pair: the SAME edit one directory over must be
    allowed, or this gate makes the brain undevelopable.
    """
    import glob as _glob
    import shutil
    import subprocess
    import tempfile

    root = os.path.dirname(_HERE)
    fdir = fdir or os.path.join("registry", "fixtures", RULE_ID)
    if not os.path.isabs(fdir):
        fdir = os.path.join(root, fdir)
    if not os.path.isdir(fdir):
        print(f"selftest FAIL: fixture dir missing: {fdir}", file=sys.stderr)
        return 1
    fixtures = sorted(_glob.glob(os.path.join(fdir, "violation*.json"))) + \
        sorted(_glob.glob(os.path.join(fdir, "benign*.json")))
    if not any(os.path.basename(f).startswith("violation") for f in fixtures) or \
       not any(os.path.basename(f).startswith("benign") for f in fixtures):
        print(f"selftest FAIL: need violation*.json and benign*.json in {fdir}",
              file=sys.stderr)
        return 1

    import gate_selftest
    failures, blocked, allowed = [], 0, 0
    for path in fixtures:
        name = os.path.basename(path)
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        setup = payload.pop("_setup", {}) or {}
        sandbox = tempfile.mkdtemp(prefix="arming-selftest-")
        try:
            _build_sandbox(sandbox, setup)
            body = json.dumps(payload).replace("{{SANDBOX}}", sandbox)
            env = dict(os.environ)
            for k in ("OCTO_MERGE_APPROVE", "OCTO_QA_OK", "OCTO_ALLOW_FORCE",
                      "OCTO_LANE_OVERRIDE", "OCTO_GRAFO_OVERRIDE",
                      "OCTO_KERNEL_OPEN", "GIT_DIR", "GIT_WORK_TREE",
                      "GIT_INDEX_FILE", "GIT_PREFIX", "GIT_COMMON_DIR",
                      "GIT_OBJECT_DIRECTORY", "GIT_NAMESPACE",
                      "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_QUARANTINE_PATH"):
                env.pop(k, None)
            env["HOME"] = sandbox
            env["USERPROFILE"] = sandbox
            env["CLAUDE_SESSION_ID"] = "__selftest__"
            cp = subprocess.run([sys.executable, os.path.abspath(__file__)],
                                input=body, capture_output=True, text=True,
                                cwd=sandbox, env=env, timeout=30)
            did_block = gate_selftest.emits_block(cp.returncode, cp.stdout)
        finally:
            shutil.rmtree(sandbox, ignore_errors=True)

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
                failures.append(f"{name} WAS blocked (must allow): "
                                f"{(cp.stdout or '').strip()[:160]}")
                continue
            allowed += 1

    if failures:
        print("selftest FAIL: " + "; ".join(failures), file=sys.stderr)
        return 1
    print(f"selftest PASS: {blocked} block + {allowed} allow "
          f"(g__pretool__arming-surface.py vs {os.path.basename(fdir)}); "
          f"every deny names its live file, and the same edit in a worktree allows")
    return 0


def _build_sandbox(sandbox: str, setup: dict) -> None:
    """A live brain and a worktree of it, one directory apart. The worktree's
    `.git` is a FILE, exactly as `git worktree add` writes it, so the shared
    parser's `enclosing_worktree_root` finds the same roots it finds live."""
    live = os.path.join(sandbox, ".claude")
    for rel in ("scripts", "registry", ".githooks", ".git"):
        os.makedirs(os.path.join(live, rel), exist_ok=True)
    for rel in ("settings.json", "settings.local.json", "hooks.json"):
        _touch(os.path.join(live, rel), "{}\n")
    # the harness user config, a SIBLING of the live root, plus a neighbour one
    # character away from it that must stay writable.
    _touch(os.path.join(sandbox, ".claude.json"), '{"mcpServers": {}}\n')
    _touch(os.path.join(sandbox, ".claude.json.bak"), "{}\n")
    # PROJECT scope, the second surface. `<live>/.claude/settings*.json` is what
    # a session whose cwd is the live root loads ON TOP of the user-scope pair,
    # `<live>/.claude/commands/` is a neighbour inside the same directory that
    # must stay writable, and `<live>/vendor-ref/.claude/` is a DEEPER project
    # root of the same shape (the live tree really carries one).
    for rel in ("settings.json", "settings.local.json"):
        _touch(os.path.join(live, ".claude", rel), "{}\n")
    _touch(os.path.join(live, ".claude", "commands", "note.md"), "# stub\n")
    _touch(os.path.join(live, "vendor-ref", ".claude", "settings.json"), "{}\n")
    # a `.claude` directory of the same shape holding NO settings: the live tree
    # carries several, and they must stay removable.
    _touch(os.path.join(live, "knowledge-ref", ".claude", "commands", "x.md"), "#\n")
    _touch(os.path.join(live, "registry", "rules.yaml"), "rules: []\n")
    _touch(os.path.join(live, ".githooks", "pre-push"), "#!/bin/sh\n")
    for name in ("qa-merge-gate.py", "g__pretool__kernel.py",
                 "g__stop__goal-anchor.py", "gate_selftest.py",
                 "receipt_ledger.py", "kernel_proc.py", "brain_doctor.py",
                 "dimension-awareness-hook.py", "merge-hooks.py", "README.md"):
        _touch(os.path.join(live, "scripts", name), "# stub\n")
    wt = os.path.join(sandbox, "wt", "state-gate")
    for rel in ("scripts", "registry", ".githooks"):
        os.makedirs(os.path.join(wt, rel), exist_ok=True)
    _touch(os.path.join(wt, ".git"), "gitdir: " + os.path.join(live, ".git") + "\n")
    _touch(os.path.join(wt, "hooks.json"), "{}\n")
    # the SAME project-scope shape one directory over: source, not loaded, and
    # the over-fire control for the whole project-scope rule.
    _touch(os.path.join(wt, ".claude", "settings.json"), "{}\n")
    _touch(os.path.join(wt, ".claude.json"), "{}\n")
    _touch(os.path.join(wt, "registry", "rules.yaml"), "rules: []\n")
    _touch(os.path.join(wt, ".githooks", "pre-push"), "#!/bin/sh\n")
    for name in ("qa-merge-gate.py", "g__pretool__kernel.py",
                 "g__stop__goal-anchor.py", "gate_selftest.py",
                 "receipt_ledger.py", "kernel_proc.py"):
        _touch(os.path.join(wt, "scripts", name), "# stub\n")
    if setup.get("symlink"):
        src, dst = setup["symlink"]
        src = src.replace("{{SANDBOX}}", sandbox)
        dst = dst.replace("{{SANDBOX}}", sandbox)
        try:
            os.symlink(dst, src)
        except (OSError, NotImplementedError):
            pass


def _touch(path: str, body: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _i = sys.argv.index("--selftest")
        sys.exit(_selftest(sys.argv[_i + 1] if len(sys.argv) > _i + 1 else None))
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # fail-open: never break the user's tool call
