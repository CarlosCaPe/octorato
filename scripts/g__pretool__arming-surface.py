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
      naming it). That covers deeper project roots without enumerating them,
      and the live tree really carries one: claude-mem-ref/.claude/settings.json.

      "HOLDS ONE" IS ONLY A QUESTION FOR A VERB THAT TAKES, and asking it of
      every verb cost a merge blocker plus a second door found while fixing it.
      A `.claude` that holds no settings disarms nothing by being DELETED, so
      the eight empty ones on the live tree stay removable, all eight measured.
      But the same "it holds nothing" was answered for verbs that PUT something
      there, where what it holds now says nothing about what it will hold:

        ALLOW  Write <live>/stage/settings.json  {"env":{"OCTO_MERGE_APPROVE":"*"}}
        ALLOW  mv <live>/stage <live>/x/.claude          <- absent destination
        ALLOW  cp /tmp/settings.json <live>/knowledge/…/ECC/.claude/
                                                        <- existing empty one

      Two allowed steps to a project-scope settings file with a forged approval
      inside the live root; and every one of the eight "harmless" empty
      directories was a drop box. This header used to say "creating an empty
      `.claude` is allowed, and the FILE rule denies putting settings into it,
      so the line is held by the file test either way". That is FALSE for both:
      the file rule only ever sees file targets and neither command names a
      file. So the listing is consulted ONLY for a REMOVING verb (`rm`,
      `unlink`, `find -delete`, `git rm`); for every other verb the `.claude`
      directory itself is the target, whatever it holds today. `mkdir` is not a
      mutator and never reaches this gate, so creating one stays free. Cost,
      measured: of 17,232 real Bash calls, ONE aims mv/cp/tee/install/ln at a
      nested `.claude` under the live root, and it is a line testing this gate.
      What is newly denied that a person might do: moving an empty `.claude`
      elsewhere, which `rm -rf` still does.
      CASE. All four of `.Claude/settings.json`, `.claude/SETTINGS.JSON`,
      `Settings.local.json` and `.CLAUDE.JSON` were ALLOW before, which is a
      clean bypass on Windows (where install-runners.py ships the `.cmd`
      thunks) and on default macOS APFS, where those spellings are the SAME
      file. Every comparison here is case-folded now; see `_fold`.

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
`git read-tree -u|--reset` and `git checkout-index -a -f`, aimed at the live
root. They rewrite every file in the set at once, so a file-by-file deny that
ignored them would be trivially walked around with one branch switch. The last
two were reproduced as ALLOW and are named here rather than in the shared
parser, which carries the lane rule and is under edit elsewhere; the borrowed
`git_parse` still resolves their `-C`, so this is a verb table and not a second
parser. `git worktree remove` is deliberately NOT one of them: it deletes a
sibling checkout and rewrites nothing here. Neither is a checkout or switch that
CREATES a branch (`checkout -b`, `checkout -qb`, `switch -c`, `--orphan`): it
makes a ref at HEAD and rewrites no file, the deny copy that fired on it said
"rewrites the whole working tree" and that was simply false, and about ten of
them appear in real traffic. The exemption needs the command to carry exactly
ONE checkout/switch, so `checkout -b tmp && checkout evil` is judged as before.

NO ENV UNLOCK, deliberately. Every other gate here prints one, and an env
unlock for THIS rule would be self-serve: the variable that lifts it is exactly
the kind of thing an agent would write into the settings.json `env` block this
gate exists to protect. Same stance and same words as the kernel's own state
floor, which denies every hooked process including itself: the operator's
terminal is not hooked and stays the only writer.

NAMED RESIDUALS, measured, deliberately not covered:
  - An INTERPRETED write. `python3 scripts/merge-hooks.py` legitimately writes
    settings.json, and a hook never sees inside a subprocess. Only Write/Edit
    and shell mutations are targets here. Two best-effort layers read INLINE
    programs, and they ask DIFFERENT questions on purpose:
      * a `-c` body is read for a protected literal next to a write marker
        (open(…,'w'), write_text, json.dump, writeFileSync); a read of the same
        file through the same `-c` passes, which is why the layer needs the
        marker. Every one of the 14 markers is individually load-bearing, one
        fixture each, all 14 deletions run. The host table is SIX, down from
        ten: `node -c` is not a thing and `perl -c` / `ruby -c` only check
        syntax, so those three could never reach a write, and `python3` was a
        second name for `python` once the version suffix is stripped. Each of
        the six that remain now has its own violation, proven by deletion. Spellings that used to slip and now deny: `python3.12 -c`
        (the version strip kept the dot), `python3 -u -c` and `python3 -I -c`
        (the host was read as tokens[i-1]), a bundled `sh -lc`, and a fused
        `-c"…"`.
      * a HEREDOC body is read only for a protected literal that is the DIRECT
        OPERAND of a write (`open(<literal>,'w')`, `Path(<literal>).write_text`,
        `writeFileSync(<literal>`, a `> <literal>` redirect), and only when the
        opening line feeds an interpreter. The loose marker test was tried first
        and measured on 17,232 real Bash calls: it flipped 23 to DENY, of which
        2 were genuine live writes and 21 were a heredoc writing a DOCUMENT that
        QUOTES a protected path, which is what editing this gate's header, its
        fixtures, its README and CLAUDE.md looks like. Precision 2/23 on a rule
        with no env unlock is a gate that gets routed around, so the narrow test
        ships: 2 of 3,296 real heredoc commands, down from 23, and the direct
        attack still denies. Those 2 are stated rather than rounded away: both
        are one command writing a TEST HARNESS whose text carries the attack
        literal, which no text scan separates from the attack itself.
    Anything that reaches the file through a script file, a VARIABLE, or an
    unlisted write idiom passes on both channels. Both genuine live writes in
    the corpus were the variable shape, which is the honest price of the narrow
    heredoc test and is stated rather than hidden.
    Reproduction: see registry/fixtures/…/README-residuals.txt.
  - A READ SPELLED AS A COPY. `python3 -c "shutil.copy(<live settings>, /tmp/x)"`
    DENIES, although it only reads. `shutil.copy` is a real write idiom and the
    literal scan cannot see which side of the call the needle is on, so the
    over-fire is kept in exchange for the write it catches. Named because the
    README's "reading through the same `-c` passes" is true of `open` and not of
    this one.
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
  - AN ANCESTOR DIRECTORY OF A DEEP PROJECT ROOT, in BOTH directions. `rm -rf
    ~/.claude/claude-mem-ref` takes that root's `.claude/settings.json` without
    naming it or its `.claude` directory, and `mv /tmp/s ~/.claude/x` where
    `/tmp/s/.claude/settings.json` exists plants one the same way. One class,
    one reason: the classifier tests the PATH IT IS GIVEN, and neither command
    gives it a `.claude`. Covering the delete means listing the live tree on the
    hot path for every rm; covering the create means walking an arbitrary source
    tree. Both are costs this gate refuses to pay, and both are strictly weaker
    than the interpreter residual above, which already concedes that an
    adversary running a script file writes anything. `rm -rf ~/.claude` and
    `rm -rf ~/.claude/.claude` stay denied, because they conflict with a path
    the classifier already holds. Reproduction: `rm -rf ~/.claude/claude-mem-ref`
    and `mv /tmp/s ~/.claude/x` are allowed; `mv /tmp/s ~/.claude/x/.claude` is
    not.
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
  - A COMMAND OVER 64 KB THAT CARRIES NEITHER `-c` NOR A HEREDOC. It is not
    scanned by the inline layers and is not denied either, because nothing here
    would have read it. The path and tree layers still run on it.

NET EFFECT ON REAL TRAFFIC, replayed rather than argued. 17,232 Bash tool calls
from this machine's transcripts, this version against the previous one, verdict
read from `permissionDecision` and never from an exit code:

    11 flipped DENY -> ALLOW   (over-fire removed)
       7  `git checkout -b` / `-qb` / `switch -c` in the live tree
       2  read-only `python3 -c` diagnostics that the glob collapse caught
          because `[` in a Python subscript made a command look like a glob
       2  `cat > /tmp/x.py <<EOF` read as an interpreter body it is not
     2 flipped ALLOW -> DENY   (over-fire added)
       2  one command each writing a TEST HARNESS whose text carries the attack
          literal, from the adversarial lab rather than from the work

Net added over-fire: 2 in 17,232, and the 39 disarms the previous version
denied are all still denied.

Hot path: the size cap is tested on the raw string first, then one
`paths_conflict` against the brain root rejects everything outside ~/.claude
before any listing or realpath happens, and the shared parser's own trigger test
returns [] before it loads anything, so an ordinary `ls` or `pytest` never
reaches the expensive half. Measured warm on this
machine: ~65 ms for `import kernel_proc` on every call (the same import
g__pretool__kernel.py already pays on the same `*` matcher), ~1 ms for a
command with no mutation token, and ~90-190 ms more for one that has a token
(the shared parser loading dimension-awareness-hook.py, which the Bash
tree-owner gate is already paying in parallel for the same command). Same-event
hooks run in parallel, so the wall-clock addition is bounded by the slowest
hook, not the sum. Measured again with everything in place, best of five per
shape under CPU load, whole process including interpreter start: `ls -la`
0.124 s, `pytest -q` 0.193 s, an `rm` carrying a mutation token 0.206 s, a Write
into a worktree 0.164 s, a 63 KB `-c` body (the worst case still scanned)
0.267 s, and a 70 KB one 0.119 s because it is refused instead of read.
Everything except a real hit fails OPEN, with ONE exception
that used to be a silent hole: the borrowed parser failing to LOAD now denies.
A blanket `except` around the import turned this into an all-ALLOW with no
output whenever `receipt_ledger.py` or `kernel_proc.py` was missing, and both
are inside the set this gate protects, so the failure was invisible at runtime
and QA's positive control was the only thing that saw it. A load failure is
structural and cannot be provoked by any command an agent writes, so denying on
it costs no legitimate work; a command the parser cannot READ still allows,
because denying on that would hand anyone a session-wide DoS for the price of
one unbalanced quote. Asserted in `--selftest`, which cannot express it as a
fixture: making the load fail needs the loader repointed, and any payload or env
that could repoint it would itself be the disarm.

NO `timeout` IN THE REGISTRATION, and that is NOT what bounds the cost. The
sibling PreToolUse gates carry `timeout: 5`; this one carries none and takes the
harness default of 60 s, because a timeout is a KILL, a killed hook writes
nothing to stdout, and empty stdout reads as ALLOW. That reasoning is still
right and it was being asked to do a job it cannot do. Whatever the timeout is,
an adversary who can make the gate slow needs a BIGGER payload, never a
different technique, so the number only sets the size of the payload. Measured
through main() on this machine before the cap: 24 KB 0.19 s, 97 KB 0.79 s,
195 KB 3.13 s, 390 KB 9.72 s, four times the time for twice the size, entered by
the two characters `-c` ANYWHERE in the command and before any host or needle
test. What bounds it is `_MAX_SCANNED`: past 64 KB a command carrying an
interpreter body or a heredoc is DENIED rather than scanned, which turns the
kill into a refusal. Worst case under the cap is now 0.49 s. The cap is measured
against real traffic, not picked: 17,232 Bash tool calls in this machine's
transcripts, largest 32,359 bytes, p99 5,145, none over the cap. The 60 s
default stays for the honest reason it was chosen (a genuinely hung stat should
make the user wait, not be skipped), and it is no longer load-bearing.

Stdin:  PreToolUse payload {"tool_name", "tool_input", "cwd", …}
Stdout: deny JSON on a hit, else nothing. Exit always 0.
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import kernel_proc  # noqa: E402  (stdlib-only, hot-path budgeted)

_HERE = os.path.dirname(os.path.abspath(__file__))
RULE_ID = "ARCHITECTURE.arming-surface"
WRITE_TOOLS = ("Write", "Edit", "NotebookEdit", "MultiEdit")


# CASE. Every test below compares path COMPONENTS, and this brain runs on two
# platforms where the file system does not: Windows, which is where
# install-runners.py ships the `.cmd` thunks, and default macOS APFS. On both,
# `.Claude/SETTINGS.JSON` and `.claude/settings.json` are the SAME file, and
# measured on this ext4 host before the fold, all four of `.Claude/settings.json`,
# `.claude/SETTINGS.JSON`, `Settings.local.json` and `.CLAUDE.JSON` were ALLOW.
# `os.path.normcase` would close Windows and leave macOS open (it is identity on
# every POSIX host), so the fold is unconditional. The price on Linux, where the
# two really are different files, is that a directory literally named `.CLAUDE`
# would be protected while arming nothing; nothing on this tree carries one, and
# denying a write to a path that does not exist costs nothing. That is the
# cheaper side of the trade, and it is the whole reason this is a fold and not a
# platform test.
def _fold(text: str) -> str:
    return (text or "").casefold()


def _conflict(a: str, b: str) -> bool:
    """`kernel_proc.paths_conflict`, case-folded. That helper is a pure prefix
    and equality test on normalized strings, so folding BOTH operands keeps the
    containment relationship it measures; both sides here are derived from the
    same brain root, so neither can fold into the other by accident."""
    return kernel_proc.paths_conflict(a, b) or \
        kernel_proc.paths_conflict(_fold(a), _fold(b))

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
#
# THE HOST TABLE IS SIX, not ten, and the four that left were dead weight of
# exactly the kind the marker list carried a commit ago. QA mutated all ten:
# eight survived deletion and only `sh` was load-bearing, so "every host is
# independently load-bearing" was a claim, not a measurement.
#
# Three left on reasoning about what the programs DO: `node -c` is not a thing
# (node takes `-e` / `--check`), and `perl -c` / `ruby -c` are syntax-check-only
# flags that never execute the body, so none of the three could reach a write
# through a `-c`. They stay covered where they ARE reachable, nested inside a
# shell host, which is the shape their four fixtures already use.
#
# The fourth left on a MEASUREMENT, after the rewrite: deleting `python3` still
# left every fixture green, because `_is_c_host` strips a version suffix and
# `python3` reduces to `python`, which is in the table. An entry that another
# entry already answers for is not a second guard, it is a second name, and this
# gate spent a commit learning that about the markers. `py` is not that (it
# strips to itself), so it stays.
#
# Each of the six now has a violation whose deny turns on THAT entry, verified
# by deleting each one and watching exactly its own fixtures go red, with a
# no-op control green in the same run.
_C_HOSTS = ("bash", "sh", "zsh", "dash", "python", "py")
_WRITE_MARKERS = ("'w'", '"w"', "'w+'", '"w+"', "'a'", '"a"',
                  "write_text", ".write(", "writelines", "json.dump(",
                  "writeFileSync", "appendFileSync", "os.replace(", "shutil.copy")

# The length at which a command stops being SCANNED and starts being DENIED.
#
# `interpreter_write` runs shlex over the command, and shlex is quadratic in the
# length of a single token. Measured end to end through main() on this machine:
# 24 KB 0.19 s, 97 KB 0.79 s, 195 KB 3.13 s, 390 KB 9.72 s. Four times the time
# for twice the size, so the 60 s harness default is reachable near 1 MB, and
# the path is entered by the two characters `-c` anywhere in the command,
# before any host or needle test. The header used to argue that no `timeout` is
# safer than `timeout: 5` because a KILLED hook writes no stdout and empty
# stdout reads as ALLOW. That is true, and it is NOT what bounds this: with any
# timeout the adversary needs a BIGGER payload, never a different technique, so
# the timeout only sets the size. The honest fix turns the kill into a deny.
#
# 64 KB, measured against real traffic rather than picked: 17,232 Bash tool
# calls from this machine's transcripts, largest 32,359 bytes, p99 5,145,
# p99.9 13,845, and ZERO over 64 KB. Past the cap, a command carrying an
# interpreter body or a heredoc is denied and told why; a command past the cap
# carrying neither is left alone, because this layer would not have read it.
#
# LEXING ONLY THE `-c` SEGMENT WAS TRIED AND DOES NOT HELP, measured rather than
# assumed, which is why the cap is the whole fix and not half of it. shlex is
# quadratic in the length of ONE TOKEN, and in this attack the payload IS that
# token, so pulling a single token from an offset costs the same as splitting
# the command: at 195 KB, shlex.split 1.56 s against one-token-from-offset
# 1.83 s. Narrowing the entry (a real fix, kept: the host is checked before the
# body is read) changes which commands reach the lexer, never what the lexer
# costs once one does.
_MAX_SCANNED = 64 * 1024


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
    return any(fnmatch.fnmatchcase(_fold(basename), p) for p in _SCRIPT_PATTERNS)


def project_scope(target: str, brain: str, removing: bool) -> tuple:
    """(live_path, why) when `target` is project-scope settings INSIDE the live
    root, else (None, None). Pure string work for the FILE shape, no stat and no
    listing, so it costs nothing on the hot path.

    Only paths strictly under the live root are tested here. The root itself
    and any ancestor of it are already a hit through _EXACT (a target that
    contains ~/.claude contains ~/.claude/settings.json), so they never reach
    this and never need a second answer.
    """
    if not _fold(target).startswith(_fold(brain) + os.sep):
        return None, None
    parts = [_fold(p) for p in target[len(brain) + 1:].split(os.sep)]
    if not parts or not parts[0]:
        return None, None
    if len(parts) >= 2 and parts[-2] == _PROJECT_DIRNAME and \
            fnmatch.fnmatchcase(parts[-1], _PROJECT_SETTINGS_GLOB):
        return target, _PROJECT_WHY
    if parts[-1] == _PROJECT_DIRNAME and _holds_settings(target, removing):
        return target, _PROJECT_DIR_WHY
    return None, None


# Verbs that only ever make a path GO AWAY. Everything else names, at its
# destination, the file that will EXIST once the command has run, which is the
# distinction `_holds_settings` turns on below.
_REMOVING_VERBS = ("rm", "unlink", "find -delete", "git rm")


def _holds_settings(directory: str, removing: bool) -> bool:
    """True when a `.claude` directory is worth protecting from THIS verb.

    ONE QUESTION PER VERB, because "what does it hold?" is only the right
    question for a verb that TAKES something.

    A REMOVING verb (rm, unlink, find -delete, git rm) takes what is there, so
    the listing answers it exactly. The live tree carries eight `.claude`
    directories that hold no settings at all (vendored reference checkouts under
    knowledge/, the `home/.claude` fixture roots), and denying housekeeping on
    those buys nothing: a directory with no settings disarms nothing by being
    deleted. They stay removable, measured, all eight.

    EVERY OTHER VERB puts something there, so what the directory holds NOW says
    nothing about what it will hold, and the whole question is wrong. Two doors
    were open because it was asked anyway, and both are closed by not asking:

      the ABSENT one, the merge blocker, reproduced five ways by QA:
        ALLOW  Write <live>/stage/settings.json  {"env":{"OCTO_MERGE_APPROVE":"*"}}
        ALLOW  mv <live>/stage <live>/x/.claude
      the EXISTING-BUT-EMPTY one, found by re-testing the fix against the real
      tree, and the reason this is a verb rule rather than an absence rule:
        ALLOW  cp /tmp/settings.json <live>/knowledge/…/ECC/.claude/
      the eight empty directories were a drop box, and the deny that fires on
      the file (`…/.claude/settings.json`) never sees a command that only names
      the directory.

    The header sentence that used to cover all of this, "creating an empty
    `.claude` is allowed, and the FILE rule denies putting settings into it, so
    the line is held by the file test either way", is FALSE for both: the file
    rule only ever sees file targets, and neither command names a file.

    Cost, measured rather than argued: 17,232 real Bash calls from this
    machine's transcripts contain ONE that aims mv/cp/tee/install/ln at a nested
    `.claude` under the live root, and it is a line testing this gate. `mkdir`
    is not a mutator and never reaches here, so creating one stays free, and
    `rm -rf` on an empty one stays allowed. What is now denied that was not:
    moving an empty `.claude` somewhere else, which `rm` still does.

    Unreadable counts as TRUE. A directory of exactly this shape that cannot be
    listed is the ambiguous case, and this gate resolves ambiguity closed. One
    listdir, reached only for a REMOVING verb and only after the fast-out has
    proven the path is inside the live root, so an ordinary command never pays
    it.
    """
    if not removing:
        return True               # the verb writes: the directory IS the target
    try:
        names = os.listdir(directory)
    except (FileNotFoundError, NotADirectoryError):
        return False              # nothing there to take
    except OSError:
        return True
    return any(fnmatch.fnmatchcase(_fold(n), _PROJECT_SETTINGS_GLOB) for n in names)


def classify(target: str, removing: bool = False) -> tuple:
    """(live_path, why) when `target` reaches a live arming surface, else
    (None, None). Containment counts in BOTH directions: `rm -rf
    ~/.claude/scripts` never names a gate and takes every one of them."""
    if not target:
        return None, None
    brain = brain_root()
    cfg = user_config_path(brain)
    if _conflict(target, cfg):
        return cfg, _USER_CONFIG_WHY           # the one member outside the root
    if not _conflict(target, brain):
        return None, None                      # fast out: not in the brain
    for rel, why in _EXACT.items():
        live = os.path.join(brain, *rel.split("/"))
        if _conflict(target, live):
            return live, why
    live, why = project_scope(target, brain, removing)
    if live:
        return live, why
    sdir = scripts_dir()
    if _conflict(target, sdir):
        if _fold(target) == _fold(sdir) or _fold(sdir).startswith(_fold(target) + os.sep):
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


def hit(target: str, removing: bool = False) -> tuple:
    for cand in candidates(target):
        live, why = classify(cand, removing)
        if live:
            return live, why
    return None, None


# ── Bash side: one parser for the whole brain, borrowed not copied ───────────

class ParserUnavailable(Exception):
    """The shared command parser could not be LOADED. Distinct from a command
    it cannot read, and answered the opposite way; see `bash_targets`."""


_PARSER_PATH = os.path.join(_HERE, "g__pretool-bash__tree-owner.py")
_PARSER_MOD = None


def _parser():
    """Borrow the command scanner the Bash tree-owner gate already proves
    (g__pretool-bash__tree-owner.py:553). It resolves `cd`, `git -C`,
    `--work-tree`, redirects, subshells, wrappers and `-c` bodies, and it is
    boundary-aware, so `git commit -m "edit settings.json"` is one token to
    shlex and never becomes a target. A second copy would drift, and the drift
    would be invisible until a deny failed to fire. The whole module is kept,
    not just `scan`, because `glob_hits` and `git_parse` are borrowed too."""
    global _PARSER_MOD
    if _PARSER_MOD is None:
        import importlib.util
        try:
            spec = importlib.util.spec_from_file_location(
                "tree_owner_bash_borrow", _PARSER_PATH)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except Exception as exc:
            raise ParserUnavailable(f"{type(exc).__name__}: {exc}") from exc
        _PARSER_MOD = mod
    return _PARSER_MOD


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


def _needle_marker(body: str, needles: list):
    """(literal, marker) when a `-c` body writes a protected path.

    This is the LOOSE test and it belongs to the `-c` channel alone. It was
    tried on heredoc bodies and measured unshippable there; `heredoc_write`
    carries the narrow one, with the measurement that separated them."""
    marker = next((m for m in _WRITE_MARKERS if m in body), None)
    if not marker:
        return None
    for needle in needles:
        if needle in body:
            return needle, marker
    return None


def _is_c_host(base: str) -> bool:
    """`python3.12 -c` used to pass: `rstrip("0123456789")` leaves `python3.`,
    with the dot, and no entry in the table carries one. A version suffix is
    digits AND dots."""
    if not base:
        return False
    return base in _C_HOSTS or base.rstrip("0123456789.") in _C_HOSTS


def _host_of(tokens: list, i: int) -> str:
    """The program a `-c` at index *i* belongs to, walking BACK past its own
    flags. `tokens[i - 1]` alone missed `python3 -u -c` and `python3 -I -c`,
    both ordinary spellings and both measured ALLOW before this."""
    j = i - 1
    while j >= 0 and tokens[j].startswith("-") and tokens[j] != "--":
        j -= 1
    return os.path.basename(tokens[j]) if j >= 0 else ""


_BUNDLED_C = re.compile(r"-[A-Za-z]*c")


def _c_bodies(tokens: list) -> list:
    """Every `-c` PROGRAM argument in a token list.

    Three spellings, all reachable and the last two measured ALLOW before this:
    `-c <body>`, a short-flag bundle ending in c (`sh -lc <body>`), and a FUSED
    `-c<body>` (`python3 -c'open(...)'`, which shlex hands back as one token).

    The bundle branch was written first and was DEAD, which is what a surviving
    mutant showed: `interpreter_write` fast-outs on `"-c" not in command`, and
    `sh -lc "…"` carries no literal `-c`, so the body was never reached. The
    fast-out is the same `_BUNDLED_C` regex now. A branch with no fixture is a
    claim; this one was a claim that was also false."""
    out = []
    for i, tok in enumerate(tokens):
        if tok == "-c" or _BUNDLED_C.fullmatch(tok):
            body = tokens[i + 1] if i + 1 < len(tokens) else None
        elif tok.startswith("-c") and len(tok) > 2 and not tok.startswith("--"):
            body = tok[2:]
        else:
            continue
        if body and _is_c_host(_host_of(tokens, i)):
            out.append(body)
    return out


def interpreter_write(command: str):
    """(literal, marker) when a `<interp> -c <body>` writes a protected path.

    Best-effort by construction and gated on a write marker: the same shape
    reading the same file is a real, frequent command (`python3 -c "json.load
    (open('~/.claude/hooks.json'))"`) and must pass."""
    import shlex
    # The fast-out has to know the bundle too: `sh -lc "…"` carries no literal
    # "-c", so the old substring test returned before the body was ever read.
    if not _BUNDLED_C.search(command):
        return None
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    needles = _needles()
    for body in _c_bodies(tokens):
        found = _needle_marker(body, needles)
        if found:
            return found
    return None


# ── heredoc bodies: the dominant real idiom, and it was uncovered ────────────
#
# The residual said "an inline `-c` body is read; a script file passes". A
# heredoc body is INLINE, sits in the command string exactly as a `-c` argument
# does, and was read by nothing. Measured on this machine's own transcripts,
# 17,232 Bash tool calls: 2,424 feed a heredoc to an interpreter against 2,221
# carrying a host `-c`, so the uncovered channel was the MORE common one, and
# two real transcript commands rewrote a live settings file through it.
#
# MINIMAL, AND MARKED FOR REMOVAL. Checked rather than assumed before writing
# it: `grep -rn heredoc scripts/*.py` returns nothing on this branch, and
# `git grep _split_heredocs` across every ref hits only
# `fix/qa-gate-blanket-override`, which has not landed. So there is nothing to
# inherit yet and this is the SECOND reader, not a third. When that logic
# reaches the shared `scan()`, heredoc bodies arrive as ordinary segments and
# this block goes; nothing else here depends on it.
_HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")


def heredoc_bodies(command: str) -> list:
    """Every heredoc BODY in the command.

    An opener whose terminator line never appears is NOT a heredoc, so a `<<`
    inside ordinary prose (`echo "a << b"`) can never swallow the rest of the
    command. Terminator positions are indexed once instead of rescanned per
    opener, so a line carrying many openers with no terminator stays linear."""
    if "<<" not in command:
        return []
    lines = command.split("\n")
    at = {}
    for j, ln in enumerate(lines):
        at.setdefault(ln.strip(), []).append(j)
    bodies, i = [], 0
    while i < len(lines):
        line = lines[i]
        i += 1
        for _quote, term in _HEREDOC_RE.findall(line):
            end = next((j for j in at.get(term, ()) if j >= i), None)
            if end is None:
                continue
            bodies.append("\n".join(lines[i:end]))
            i = end + 1
    return bodies


def _protected_pairs(brain: str) -> list:
    """(path, why) for every CONCRETE protected file, for tests that need a
    path instead of a shape (the glob test below). The project-scope pair is
    named at the one root that is always there, the brain root itself, exactly
    as the interpreter needles are; a deeper project root stays covered by the
    shape classifier for literal targets."""
    pairs = [(user_config_path(brain), _USER_CONFIG_WHY)]
    for rel, why in _EXACT.items():
        pairs.append((os.path.join(brain, *rel.split("/")), why))
    for name in ("settings.json", "settings.local.json"):
        pairs.append((os.path.join(brain, _PROJECT_DIRNAME, name), _PROJECT_WHY))
    sdir = scripts_dir()
    try:
        names = os.listdir(sdir)
    except OSError:
        names = []
    for name in names:
        if _is_gate_script(name):
            pairs.append((os.path.join(sdir, name), _SCRIPT_WHY))
    return pairs


def glob_hit(pattern: str, icase: bool) -> tuple:
    """(live_path, why) when a GLOB reaches a protected path.

    The glob used to be collapsed to its literal directory (`os.path.dirname`),
    which threw the filter away and answered with the root alone. Measured, that
    was inconsistent in both directions: `find <live> -name '*.pyc' -delete`
    DENIED, and so would any `find <live> -name X -delete` whatever X was, while
    the `-path` spelling of the same command ALLOWED, because its pattern kept a
    leading `*` and the dirname landed outside the root. Worse, the collapse
    fired on commands that were not globs at all: `[` is a glob character, so
    `cd ~/.claude/scripts && python3 -c "... cp = bd._run_selftest_locator(
    mine[0][1]) ..."` reduced to the scripts directory and denied a READ-ONLY
    diagnostic, twice in the real corpus. The filter is the whole point of the
    command, so the filter is what decides: the pattern is matched
    against the protected paths with the shared parser's own `glob_hits`, the
    same helper the lane rule uses for the same question."""
    if not pattern:
        return None, None
    try:
        hits = _parser().glob_hits
    except ParserUnavailable:
        raise
    brain = brain_root()
    for path, why in _protected_pairs(brain):
        try:
            if hits(pattern, path, icase):
                return path, why
        except Exception:
            continue
    return None, None


# Two whole-tree rewrites the shared parser does not name, both reproduced here
# as ALLOW before this: `git read-tree -u --reset <tree>` and
# `git checkout-index -a -f` overwrite every file in the working tree exactly as
# a branch switch does, so a file-by-file deny that let them through protects
# nothing. They are recognised HERE rather than in the shared parser because
# that parser carries the LANE rule and is under edit on another branch; the
# borrowed `git_parse` still does the `-C` / `--work-tree` resolution, so this
# is a verb table, not a second parser. When they land upstream this goes.
def _has_flag(rest: list, letter: str, long_name: str) -> bool:
    """A short letter, alone or bundled (`-af`), or its exact long spelling.
    The long names are matched EXACTLY rather than against a shared list, so
    `--all` cannot answer for `--force` the way a shared list let it."""
    for tok in rest:
        if tok.startswith("--"):
            if tok.split("=", 1)[0] == "--" + long_name:
                return True
            continue
        if tok.startswith("-") and letter in tok[1:]:
            return True
    return False


def _extra_tree_verb(sub: str, rest: list):
    # `read-tree` writes the WORKING TREE only with -u; without it the index
    # alone moves and no file here changes, so `git read-tree -m HEAD` passes.
    if sub == "read-tree" and _has_flag(rest, "u", "update"):
        return "git read-tree -u --reset" if "--reset" in rest else "git read-tree -u"
    # `checkout-index -a` writes every file in the index; `-f` lets it overwrite
    # the ones already there. `-a` alone still creates whatever is missing, so
    # the deny turns on -a and -f only sharpens it.
    if sub == "checkout-index" and _has_flag(rest, "a", "all"):
        return "git checkout-index -a"
    return None


_EXTRA_TREE_NAMES = ("read-tree", "checkout-index")


def extra_tree_hits(command: str, cwd: str) -> list:
    """(root, verb) for the whole-tree git verbs the shared parser misses.

    A substring test comes first so this costs nothing on the hot path: without
    it every Bash command would pay a second shlex pass for two rare verbs."""
    import shlex
    if not any(name in command for name in _EXTRA_TREE_NAMES):
        return []
    mod = _parser()
    out = []
    try:
        segments = mod._dim_helpers()[0](command or "")
    except Exception:
        segments = [command or ""]
    here = cwd
    for seg in segments:
        try:
            tokens = shlex.split(seg.strip().rstrip(";"))
        except ValueError:
            continue
        if not tokens:
            continue
        if tokens[0] in ("cd", "pushd") and len(tokens) > 1:
            here = mod.resolve(tokens[1], here)   # `cd ~/.claude && git read-tree`
            continue
        if os.path.basename(tokens[0]) != "git":
            continue
        parsed = mod.git_parse(tokens)
        if not parsed:
            continue
        repo, sub, rest = parsed
        verb = _extra_tree_verb(sub, rest)
        if not verb:
            continue
        base_dir = mod.resolve(repo, here) if repo else here
        root = kernel_proc.enclosing_worktree_root(base_dir) or base_dir
        out.append((root, verb))
    return out


_BRANCH_VERBS = ("checkout", "switch")


def branch_creation_only(command: str) -> bool:
    """True when the ONE checkout/switch in this command creates a branch.

    `git checkout -b`, `checkout -qb` and `switch -c` make a new ref AT HEAD and
    rewrite no file, yet the shared parser labels them whole-tree (they NAME
    something) and this gate then printed "rewrites the whole working tree",
    which is false. About ten of them appear in real traffic.

    The exemption is scoped to a command carrying exactly ONE such verb, on
    purpose: `git -C ~/.claude checkout -b tmp && git -C ~/.claude checkout evil`
    would otherwise be exempted by its harmless half. Two of them and the
    command is judged as before."""
    import shlex
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    seen = [i for i, t in enumerate(tokens) if t in _BRANCH_VERBS]
    if len(seen) != 1:
        return False
    i = seen[0]
    letter = "b" if tokens[i] == "checkout" else "c"
    for tok in tokens[i + 1:]:
        if not tok.startswith("-"):
            return False
        if tok == "--orphan":
            return True
        if not tok.startswith("--") and \
                (letter in tok[1:] or letter.upper() in tok[1:]):
            return True
    return False


# The heredoc reader is NOT the `-c` reader, and the difference is measured.
#
# The first version applied the `-c` layer's needle-plus-marker test to heredoc
# bodies unchanged. Replayed against 17,232 real Bash calls from this machine's
# transcripts (3,296 of them carrying a heredoc), that flipped 23 commands from
# ALLOW to DENY and exactly 2 of them were genuine live writes. Precision 2/23.
# The other 21 were the same shape every time: a heredoc that writes a DOCUMENT
# whose CONTENT quotes a protected path, which is what editing this gate's own
# header, its fixtures, its README-residuals and CLAUDE.md looks like. A gate
# that denies its own development, with no env unlock, is the failure the whole
# boundary was drawn around, so that version is not shippable at any price.
#
# A `-c` body is a one-line ARGUMENT; a heredoc body is a DOCUMENT. The loose
# test survives on the first because there is no room in it for prose. On the
# second it cannot tell code from data, so the heredoc reader asks a narrower
# question: is the protected path the DIRECT OPERAND of a write? Measured on the
# same corpus that fires on 2 of 3,296, down from 23, and the direct attack
# shape (`python3 - <<PY` then open(literal,'w')) still denies. The 2 are
# stated rather than rounded to zero: both are one command writing a TEST
# HARNESS whose text carries the attack literal, which no text scan separates
# from the attack, and both came from the adversarial lab, not from the work.
#
# The price is stated rather than hidden: a heredoc that reaches the file
# through a VARIABLE escapes this reader, and both genuine live writes in the
# corpus were that shape. It is the same residual the `-c` layer already names
# ("a path built from a variable"), now true of both channels instead of one.
_HEREDOC_HOST = re.compile(
    r"(?:^|[\s;&|(])(?:[\w./-]*/)?(?:bash|sh|zsh|dash|python[0-9.]*|py)\b[^\n]*<<")

# A write whose DESTINATION is the literal itself. `{q}` is the escaped needle.
#
# The `>` entry looked redundant and is not, measured both ways: a PLAIN
# `> <path>` on a heredoc line is already caught, because the shared parser
# splits the command on newlines and reads each body line as a sub-command, so
# the redirect becomes an ordinary path hit. QUOTING it hides it from that
# parser, and then this pattern is the only cover:
#     bash <<'EOF'
#     eval "echo x > ~/.claude/settings.json"
#     EOF
# denies with the entry and allows without it, which is what its fixture pins.
# The accident that covers the plain form also goes away when the shared
# `_split_heredocs` lands and bodies stop being sub-commands.
_DIRECT_WRITE = (
    r"""open\s*\(\s*['"]{q}['"]\s*,\s*['"][waxWAX]""",
    r"""(?:pathlib\.)?Path\s*\(\s*['"]{q}['"]\s*\)\s*\."""
    r"""(?:write_text|write_bytes|open\s*\(\s*['"][wa])""",
    r"""(?:writeFileSync|appendFileSync)\s*\(\s*['"`]{q}['"`]""",
    r""">>?\s*['"]?{q}""",
    r"""(?:os\.replace|shutil\.copy2?|shutil\.move)\s*\([^)]*,\s*['"]{q}['"]""",
)


def heredoc_write(command: str):
    """(literal, "direct write") when a heredoc body writes a protected path as
    the direct operand of a write call or a shell redirect."""
    if not _HEREDOC_HOST.search(command):
        return None
    bodies = heredoc_bodies(command)
    if not bodies:
        return None
    needles = _needles()
    for body in bodies:
        for needle in needles:
            quoted = re.escape(needle)
            for pat in _DIRECT_WRITE:
                if re.search(pat.format(q=quoted), body):
                    return needle, "direct write"
    return None


def bash_targets(command: str, cwd: str) -> list:
    """(kind, target, verb) triples worth testing, from the shared parser.

    TWO failures, answered opposite ways, and conflating them was a fail-OPEN
    that no runtime signal showed. QA's whole batch on a minimal sandbox came
    back all-ALLOW and only its positive control caught why: the borrowed parser
    imports `receipt_ledger.py` and `kernel_proc.py`, so with either one missing
    the import raised, the blanket `except` returned [], and every Bash command
    was allowed with no output at all. In a fail-CLOSED gate that is the worst
    possible shape: silent, total, and invisible.

      - The module cannot LOAD. Structural, never input-dependent: no command an
        agent can write makes an import fail, so denying costs no legitimate
        work and cannot be triggered on purpose. It propagates and main() DENIES.
      - The module cannot READ this command. Input-dependent by definition, so
        denying on it hands anyone a DoS: write one unparseable command and the
        gate blocks the session. It still returns [], as before.

    The protected set already holds every file the load needs, so a load failure
    means the brain is broken, not that a command is odd. Loud is the point.

    Measured at scale, by accident and then on purpose: with the parser one
    directory away from where the module looks for it, the previous version
    allowed 17,232 of 17,232 real Bash commands from this machine's transcripts,
    including every one of the 39 disarms it denies when the parser is there.
    Not one line of output, not one non-zero exit, nothing to notice.
    """
    scan = _parser().scan                 # ParserUnavailable propagates: DENY
    try:
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
        f"ARMING SURFACE: `{verb}` rewrites every tracked file at {root}, "
        f"which is the LIVE brain the harness loads. One branch switch swaps "
        f"settings.json's projection, hooks.json and every gate script at once, "
        f"so a file-by-file deny that let this through would protect nothing. "
        f"{_DEV_PATH} {_ONLY_WRITER}"
    )


def deny_parser(detail: str) -> None:
    deny(
        f"ARMING SURFACE: the shared command parser could not be loaded "
        f"({_PARSER_PATH}: {detail}), so this gate cannot read Bash commands at "
        f"all. That is a fail-OPEN with no runtime signal: the parser imports "
        f"receipt_ledger.py and kernel_proc.py, both inside the set this gate "
        f"protects, and with either one missing every Bash command was allowed "
        f"and nothing was printed. A floor that cannot read denies instead. "
        f"Restore the file from a worktree, or run the restore in the "
        f"operator's own terminal, which is not hooked. {_ONLY_WRITER}"
    )


def deny_oversize(size: int, channel: str) -> None:
    deny(
        f"ARMING SURFACE: this command is {size} bytes and carries {channel}, "
        f"which this gate reads with shlex, and shlex is quadratic in the length "
        f"of one token (measured through this gate: 24 KB 0.19 s, 97 KB 0.79 s, "
        f"195 KB 3.13 s, 390 KB 9.72 s). Past {_MAX_SCANNED} bytes the scan is a "
        f"stall, and a stalled hook is KILLED, which writes no stdout, which the "
        f"harness reads as ALLOW. So oversize is denied rather than timed out. "
        f"The cap costs nothing real: 17,232 Bash calls in this machine's "
        f"transcripts, largest 32,359 bytes, p99 5,145, none over the cap. Split "
        f"the body into a script file and run that instead."
    )


def deny_heredoc(literal: str, _marker: str) -> None:
    deny(
        f"ARMING SURFACE: this heredoc body writes {literal} as the direct "
        f"target of a write, in the LIVE brain tree. A heredoc body is an "
        f"interpreter program inside the command string, exactly like a `-c` "
        f"argument, and it is the more common of the two here: 2,424 heredocs "
        f"fed to an interpreter against 2,221 host `-c` across 17,232 real Bash "
        f"calls, and the residual text used to claim only a `-c` body was read. "
        f"Reading the same file through the same heredoc is allowed, and so is "
        f"a heredoc that merely QUOTES this path in the document it writes; "
        f"only the path as the write's own destination is denied. {_DEV_PATH} "
        f"{_ONLY_WRITER}"
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
            # a Write CREATES its target, so an absent `.claude` is protected
            live, why = hit(target, removing=False)
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
    here = kernel_proc.norm_path(str(payload.get("cwd") or "") or os.getcwd())

    # THE CAP, tested before anything reads the command, because every reader
    # below (this gate's shlex and the shared parser's) grows superlinearly with
    # one long token. Denying here is also strictly safer than denying later: an
    # oversize command that ALSO names a protected path was going to be denied
    # anyway, so nothing legitimate is lost by answering earlier.
    if len(command) > _MAX_SCANNED:
        channel = "an interpreter `-c` body" if _BUNDLED_C.search(command) else ""
        if "<<" in command and heredoc_bodies(command):
            channel = (channel + " and a heredoc") if channel else "a heredoc body"
        if channel:
            journal_deny(pid, {"why": "oversize", "bytes": len(command),
                               "channel": channel, "command": command[:200]})
            deny_oversize(len(command), channel)
            return 0
        return 0                      # nothing here would have read it

    try:
        hits = bash_targets(command, str(payload.get("cwd") or ""))
        for root, verb in extra_tree_hits(command, here):
            hits.append(("tree", root, verb))
    except ParserUnavailable as exc:
        journal_deny(pid, {"why": "parser-unavailable", "detail": str(exc),
                           "command": command[:200]})
        deny_parser(str(exc))
        return 0

    for kind, target, verb in hits:
        if kind in _TREE_KINDS:
            if verb in _TREE_EXEMPT:
                continue
            if verb.startswith(("git checkout", "git switch")) and \
                    branch_creation_only(command):
                continue                  # a new branch at HEAD rewrites nothing
            if target and _fold(kernel_proc.norm_path(target)) == _fold(brain):
                journal_deny(pid, {"root": target, "verb": verb, "why": "live-tree"})
                deny_tree(verb, brain)
                return 0
            continue
        if kind in ("glob", "iglob"):
            try:
                live, why = glob_hit(target, kind == "iglob")
            except ParserUnavailable as exc:
                deny_parser(str(exc))
                return 0
        elif kind in ("path", "state"):
            live, why = hit(target, removing=verb in _REMOVING_VERBS)
        else:
            continue                      # 'stage' stages, it does not rewrite
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

    found = heredoc_write(command)
    if found:
        journal_deny(pid, {"literal": found[0], "marker": found[1],
                           "why": "heredoc-write", "command": command[:200]})
        deny_heredoc(found[0], found[1])
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
            # {{PAD}} keeps an oversize fixture SMALL on disk: the cap is 64 KB
            # and a literal payload would be a 64 KB file in the repo for every
            # leg that needs one.
            body = body.replace("{{PAD}}", "x" * int(setup.get("pad_bytes") or 0))
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
            for rel, _mode in (setup.get("chmod") or []):
                try:
                    os.chmod(os.path.join(sandbox, *rel.split("/")), 0o755)
                except OSError:
                    pass
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

    ok, why = _assert_parser_load_denies()
    if not ok:
        failures.append(why)
    else:
        blocked += 1

    if failures:
        print("selftest FAIL: " + "; ".join(failures), file=sys.stderr)
        return 1
    print(f"selftest PASS: {blocked} block + {allowed} allow "
          f"(g__pretool__arming-surface.py vs {os.path.basename(fdir)}); "
          f"every deny names its live file, the same edit in a worktree allows, "
          f"and a gate that cannot load its parser denies instead of allowing")
    return 0


def _assert_parser_load_denies() -> tuple:
    """The fail-OPEN leg, asserted here because it CANNOT be a fixture.

    A fixture drives the gate through stdin, and nothing an agent can put in a
    payload makes the borrowed parser fail to import. Making it fail needs the
    loader pointed at a path that is not there, and doing that from a fixture
    would mean an env var or a setup key that redirects the parser, which is a
    disarm: point it at a module whose `scan` returns [] and the gate allows
    everything. So the assertion runs the real `main()` in a child with
    `_PARSER_PATH` rebound in memory, which no payload can reach.

    Without it the regression is invisible: QA's whole batch on a minimal
    sandbox came back all-ALLOW, and only its positive control showed that the
    parser's import of receipt_ledger.py had failed and every Bash command had
    been let through in silence."""
    import subprocess
    import tempfile
    boot = (
        "import importlib.util,sys;"
        "spec=importlib.util.spec_from_file_location('g',%r);"
        "m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);"
        "m._PARSER_PATH='/nonexistent/parser-that-is-not-there.py';"
        "sys.exit(m.main())" % os.path.abspath(__file__)
    )
    payload = json.dumps({"tool_name": "Bash", "cwd": "/tmp",
                          "tool_input": {"command": "echo hi > /tmp/x"}})
    sandbox = tempfile.mkdtemp(prefix="arming-parserfail-")
    try:
        env = dict(os.environ)
        env["HOME"] = sandbox
        env["USERPROFILE"] = sandbox
        env["CLAUDE_SESSION_ID"] = "__selftest__"
        cp = subprocess.run([sys.executable, "-c", boot], input=payload,
                            capture_output=True, text=True, cwd=sandbox,
                            env=env, timeout=30)
    finally:
        import shutil as _sh
        _sh.rmtree(sandbox, ignore_errors=True)
    import gate_selftest
    if not gate_selftest.emits_block(cp.returncode, cp.stdout):
        return False, ("parser-load failure did NOT block (fail-open): "
                       f"rc={cp.returncode} out={(cp.stdout or '')[:120]!r}")
    if "parser-that-is-not-there.py" not in (cp.stdout or ""):
        return False, "parser-load deny did not name the parser it could not load"
    return True, ""


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
    # a `.claude` holding ONLY settings.local.json: the glob is `settings*.json`
    # and the local half is the per-machine registration surface, so the
    # directory is just as much a take as one holding settings.json.
    _touch(os.path.join(live, "local-only-ref", ".claude", "settings.local.json"), "{}\n")
    # a `.claude` of the same shape whose listing FAILS. `_holds_settings`
    # resolves that ambiguity CLOSED, and nothing proved it until now.
    os.makedirs(os.path.join(live, "sealed-ref", ".claude"), exist_ok=True)
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
    for rel, mode in (setup.get("chmod") or []):
        try:
            os.chmod(os.path.join(sandbox, *rel.split("/")), int(mode, 8))
        except OSError:
            pass
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
