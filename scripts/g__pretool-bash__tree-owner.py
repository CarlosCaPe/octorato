#!/usr/bin/env python3
"""g__pretool-bash__tree-owner.py: one writer per tree and per lane (Bash side).

v8 Phase 2, ISOLATION (docs/architecture/v8-kernel.md section 3). The Write twin
(g__pretool-write__tree-owner.py) stops a second writer on one file. This one
stops the shape that actually destroyed work: a shell command. Three classes,
all resolved against the kernel's lanes and all denied, never advised.

WHOLE-TREE verbs, denied while ANY other live process holds a lane in that
worktree root, because they move every file at once and cannot be scoped:
`git checkout <branch>`, `git switch`, `git reset --hard|--merge|--keep`,
`git stash` (except `list`/`show`), `git clean -f`, `git worktree remove`.

PATHSPEC verbs, denied when the path they name is another live process's lane:
`git checkout -- <paths>`, `git restore <paths>`. This is the weekend, verbatim:
three builders on one tree, one of them ran `git checkout --` over files another
had written, 14 files gone (memory lesson_session_isolation_worktree).

BASH mutations, same lane test on their targets: `rm`, `mv`, `cp` (destination),
`sed -i`, `tee`, and `>` / `>>` redirect targets. Lane matching is equality or
path prefix, so `rm -rf <dir>` is denied when someone else's lane sits anywhere
under `<dir>`.

Plus one agent-proof rule: `octo ... --release` (or `octo.py`) is denied from
Bash outright. Releasing a stuck lane is the OPERATOR's move, made from a
terminal where no hook fires; an agent that can release the lane it is being
denied by has no gate at all. The CLI's own `_looks_like_agent_shell()` markers
can be stripped with `env -u`; a boundary-split deny here cannot.

Boundaries come from the dimension gate's proven splitter, imported rather than
copied (`_split_subcmds`, `_broad_git_verb`; receipt_ledger.py:90-96 pattern),
so a mention inside quotes never fires: `git commit -m "revert the git
checkout"` is one token to shlex and never reaches a verb test. Targets are
resolved against `cd`, `git -C` and `--work-tree`.

BROAD STAGING (`git add -A|--all|.`, `git commit -a`), classified by the imported
`_broad_git_verb`, is denied when another live process holds a lane in that root.
The dimension gate denies the same shape per SESSION and keeps doing so; this one
denies it per PROCESS, which is the half it cannot see: two subagents of one
session are one dimension to it, so B's `git add -A` swallowing A's uncommitted
files was never stopped. Both gates deny independently and either deny wins.

A `-c` body is re-scanned, not trusted: `bash -c "rm -rf <lane>"` (and `sh`,
`zsh`, `dash`, plus a best-effort pass over a `python -c` body) is unwrapped and
run through the same scan, up to 3 levels deep. `_SHELL_C` comes from
receipt_ledger.py, the detector that gate already proves. A verb quoted inside an
ordinary argument stays text: only a `-c` body is a command.

Also denied on the same lane test, same shape, added after QA measured them
passing: `git rm`, `git mv`, `git add -u|./`, `unlink`, `truncate`, `xargs <rm>`
and `find ... -delete` (or `-exec rm`). Globs reduce to their longest literal
directory before the lane test, so `git checkout -- pkg/*.py` cannot walk past a
lane by never naming it literally, and `:/` / `:(top)` mean the whole root.

QA CYCLE 10 closed four more, all of them in THIS parser rather than in any one
gate, which is why fixing them here fixes every gate that imports it:
`install` (its destination is the last positional, or `-t DIR`, or every
positional under `-d`) is `cp`; `busybox`/`toybox` are WRAPPERS whose next token
is the real program, peeled like `env` and `nohup`; `$HOME`, `${HOME}` and a
leading `~` are EXPANDED before a path is normalized, because a shell sets HOME
in every session and this process knows its own, so `rm "$HOME/.claude/x"` is no
longer a one-token bypass of every path rule here; and a non-symbolic `ln` (or
`cp -l`) is denied on its SOURCE as well as its destination, because a hardlink
is a second name for one inode, `realpath` does not resolve it, and the write
through the new name is invisible to every gate afterwards.

QA CYCLE 11 closed the channel the floor had never looked at, and it is the
one the machine actually uses. Measured over the harness transcripts: of 16350
distinct real Bash commands, 3186 carry a HEREDOC and 3601 carry a `-c`. Both
gates covered `-c`; neither covered the heredoc, so `python3 - <<'EOF' /
open('<kdir>/journal/x.jsonl','a').write('x') / EOF` was ALLOWED while the same
write behind `-c` was denied. With `python3 - <<EOF` the program arrives on
STDIN and there is no flag whose argument is the program. Heredoc bodies are
now split off before anything else is parsed (`split_heredocs`) and handed back
only to a command that RUNS stdin as its program (`stdin_is_program`: no
operand, or `-` / `/dev/stdin`, and no `-c`); here-strings and process
substitutions and a PIPE INTO A SHELL are the same channel in other syntax (the
pipe was omitted from this list until QA cycle 14, and it is the common one: 61
real commands on this machine pipe into a shell), and the first three are lifted
from the
merge gate's `_stdin_channel_texts` rather than rediscovered. The same reading
removes an over-fire that was already live in the other direction: a body
nobody executes is DATA, so `cat > notes.md <<'EOF'` whose prose said
`rm -rf pkg/` is no longer read as a deletion. Second half of the same cycle,
`python3.12`: `_interp_base` strips a trailing VERSION, because the old
`rstrip("0123456789")` left `python3.` with the dot and matched nothing, so the
only versioned interpreter on this host escaped both the raw-text test and the
`-c` re-scan. Adversarial QA found that one independently in the merge gate,
which makes it one bug in shared logic rather than two.

NAMED RESIDUALS, measured as passing and deliberately not covered here. The list
is pinned by a test, so it stays equal to what the gate actually does:
`rsync --delete`, `shred`, `perl -pi` AGAINST A LANE (against the KERNEL
DIRECTORY they are denied, see below);
`git apply|rebase|merge|pull|cherry-pick|revert`; variable and brace expansion
OTHER than HOME (`rm -rf $DIR`, `rm -rf {pkg,x}`, unknowable without running the
shell); a `-c` body nested deeper
than 3; xargs fed from STDIN BY ANOTHER PROGRAM OR A FILE
(`cat list | xargs rm`, `xargs rm < list`), where the
targets never appear in the command at all. `find … | xargs rm` is NOT one of
them: `find`'s root argument is itself a path, so it is handed to the receiver
and the deny lands on the directory being searched. QA cycle 15 narrowed this sentence:
it used to be read as covering `echo <path> | xargs rm` too, and that one is a
BYPASS rather than a residual, because the target IS echo's argument, right
there in the line. It is covered now, and the residual is only the half where
the text is genuinely produced by something this gate cannot read;
and a heredoc fed to `ssh` or a container `exec`, whose body is a command on
ANOTHER machine, where this machine's kernel directory is not the one being
named. Each is a distinct verb
table or an evaluator, not a gap in this one, and none is the weekend shape.

QA CYCLE 12 closed the four channels cycle 11 had claimed and the one it had
never looked at, and it enumerates each class rather than pinning one member,
because "close a member, call the class done" is the failure this file has now
repeated three times (verb, then path, then flag). The five, with the class
written out where the class is what matters, are at the parser itself; in
summary: COMMAND SUBSTITUTION is a command (`$(…)`, backticks, nested, in an
assignment, in a redirect TARGET, inside double quotes, inside an unquoted
heredoc body); an UNQUOTED heredoc terminator makes the body a command channel
whoever receives it; the terminator line is matched the way BASH matches it
(equality, tabs stripped only for `<<-`); the DELIMITER is any word in any
quoting (`<<\\EOF`, `<<'1EOF'`, `<<'E!'`, `<<"EOF"`, `<<E'OF'`, `<< EOF`); a
grouping opener is not the receiver (`( python3 - <<'EOF' … )`); stdin has every
name PROCFS gives it (`/proc/self/fd/0` was missing); a project runner is a
wrapper BY SHAPE (`uv run python -`), which inverts the tool name away; a valued
option does not hide the operand (`bash -o pipefail`, `python3 -X utf8`), and
`bash -s` MEANS stdin rather than being an unknown flag; and the parse is
BOUNDED, denying on oversize instead of letting the harness kill decide, since
a kill produces no verdict and no verdict reads as ALLOW.

Cycle 12 leaves two residuals of its own, each MEASURED as allowed and pinned
by `QaCycle12.test_named_residuals_of_cycle_12`: a runner whose SUBCOMMAND sits
where an operand would (`deno run -`, `bun run -`); and `${ cmd; }` /
`${| cmd; }`, ksh93 value substitution, which bash gained in 5.3 and which this
host (bash 5.2.21) rejects outright. Two are retired rather than restated:
`python3 -W ignore <<EOF` is covered, and so is `uv run --with rich python -`
(cycle 13's inversion walks past the flag without a per-runner table).

QA CYCLE 13 IS ABOUT THE ENUMERATION ITSELF. Cycle 12's answer to "you closed a
member and called the class done" was to write the class out as a list, and the
LIST became the new place to be wrong. Two of its rows were false and the
measurement that should have caught them was taken against the wrong target:

  * the row that said `$((expr))` is "ARITHMETIC, not a command, left verbatim
    on purpose" is a false statement about bash, which expands `$(cmd)` and
    backticks inside `$(( ))`, `(( ))`, `$[ ]` and `let` before evaluating
    anything. Four shapes ran a command this parser never saw. The convergence
    test with the merge gate ran GREEN over the divergence, because its corpus
    held only `echo $((1 << 3))` — an expression with nothing inside it to
    disagree about;
  * the WRAPPER table was measured against the KERNEL DIRECTORY, where the
    named-path floor denies whatever verb arrives, so a wrapper that was never
    peeled still produced a deny. Re-measured against a REAL HELD LANE with a
    passing positive control, eight wrappers installed on this host walked:
    `setsid -w`, `flock`, `ionice`, `taskset`, `unshare`, `strace`,
    `systemd-run`, `watch -x` — and `setsid -w` is mandated by the hard rules
    of every brief this repo is built under, so it stood in front of nearly
    every command an agent here runs.

So the wrapper stops being a table. THE RULE IS NOW A SHAPE: a head this file
models nothing about is peeled forward to the first token it DOES model,
bounded by remote runners, script runners, the `install` collision, a reserved
word, a control token and a scan depth. The `-c` channel learns the two
spellings that eat the next word without being the token `-c` (a bundle ending
in `c`, and the same on an unmodeled head), `eval` gets its own line, a heredoc
is paired with the operand that reads it BY DESCRIPTOR rather than by fd 0, a
missing terminator is still a heredoc because bash runs the body anyway, an
opener inside a substitution keeps its host, a computed write target reaches a
LANE and not only the kernel directory, and the character budget is charged
where the characters are WALKED instead of tested after the walking.

THE WRAPPER CLASS IS NOT CLOSED, and this file will not claim it is. What
changed is that closing it no longer depends on naming its members: the members
named above are covered because the SHAPE covers them, not because they are
listed. The shape has a stated end — the stop words and the four bounds — and a
command can be written past that end. It no longer has a token-count bound: QA
cycle 14 measured real traffic putting a wrapper's program past the `_PEEL_SCAN`
= 8 that cycle 13 called "measured, not chosen", so the number was deleted and
`_WRAPPERS` became a peel target, which lets an option chain be consumed by the
table that understands it. Cycle 13's residuals
are pinned by `QaCycle13.test_named_residuals_of_cycle_13`: a wrapper whose
program is COMPUTED (`setsid $(echo rm) -f x`), a wrapper that hides its program
past the scan depth or behind a token ending in `)`/`;`, and a python heredoc
body that deletes a LANE (an interpreter body is tested against the kernel floor
as raw text and re-scanned as commands only for a shell). Over-fire is measured rather
than assumed, and TWO OF CYCLE 14'S OWN SENTENCES DID NOT SURVIVE THE RECOUNT,
which is worth more than the numbers they carried. "58 lane-directory gains, all
of them unexpanded `$VAR`" was wrong in the direction that flatters: cycle 15
measured 54 at hit level of which 52 are LITERAL paths and only 2 carry a
`$VAR`, the inverse of the claim. And "`curl -o /dev/null` is 796 of them"
attached a GAINED-set hit count to the LOST set, where every verb is `>` and a
`curl` hit cannot appear at all, because the older code never modelled
`curl -o`. A number carried forward across a rewrite is a claim about code that
no longer exists.

RESTATED FROM A RUN AGAINST THIS TIP, against 9452b86 over 19403 distinct real
commands: 69 gain a hit and 4 lose one. 41 gained hits land in a directory where
lanes can exist, of which 18 carry an unexpanded `$VAR`, so the majority are
LITERAL — which is what cycle 15 measured and what cycle 14 had backwards. The
gains sit exactly where the new tables are: `curl` 22, `sqlite3` 18, `ffmpeg`
13, `aws` 7, `gzip` 7. The 4 losses are all OVER-FIRE going away, not coverage:
83 of them are `sed` hits on ONE command whose targets were fragments of python
source (`["echo`, `'s`, `list(mine.split_command_substitutions(...))`) read as
sed operands.

Two over-fires in that set were mine and are gone, both found by the corpus and
not by a test: `2>&1;` read the trailing `;` as part of a filename, and a
`gh issue comment --body "… a > 30 && b …"` in backticks was read as a deferred
command because the body held backticks and the command held `[[`. The deferred
scan is now bounded to the VALUE OF AN ASSIGNMENT, which is the mechanism it
models, because documentation is not an assignment.

Three residuals belong specifically to the hardlink rule and are stated rather
than discovered: a SYMBOLIC link over a lane's path is denied (it is a write to
that path) but a symbolic link whose SOURCE is a lane is not, because it stores
a path rather than an inode and the write through it resolves back to the lane
where the ordinary test still runs; a hardlink made by a tool outside this table
(`rsync --link-dest`, `pax -l`, `python3 -c "os.link(...)"`) is as invisible as
any other evaluator; and an alias that ALREADY EXISTS on disk when the session
starts was never seen by this gate at all. The deny is on the act of aliasing,
so it can only cover aliases this gate watched being made.

The kernel's own state is not a lane but a floor, and since QA cycle 9 that
floor is a NAMED-PATH test rather than a verb table: any segment that names a
path inside `~/.claude/.cache/kernel` (the process table, the journals, the
locks) - or any ANCESTOR of it by the same prefix test (`~/.claude/.cache`,
`~/.claude`, `$HOME` as the target of an `rm -rf`) - is denied for EVERY hooked
process, this gate included, WHATEVER VERB carries it, unless the program is on
the short read-only list in `_KSTATE_READONLY`. For an interpreter the same test
runs against the raw segment text, because there the path is inside a quoted
program and no parser will tokenize it out - and since cycle 11 that same
raw-text test runs against a heredoc body or a here-string the interpreter
executes, which is the same program arriving through a channel with no flag. `touch`, `chmod`, `chattr` and `dd
of=` are read for this floor only, never as lane writes. A process that can
rewrite the table can grant itself any lane and erase the record; a process that
can put a FIFO at a journal path can wedge every gate that reads it. The
operator's terminal is not hooked and stays the only writer.

Hot path: the command is parsed first and the process table is read ONLY when
the parse found something that can collide, so an ordinary `ls` or `pytest`
costs no I/O at all. Every deny names the holding pid, its type and its age, and
journals a `deny` line. Everything else fails OPEN.

Stdin:  PreToolUse payload {"session_id", "agent_id", "tool_name",
        "tool_input": {"command": ...}, "cwd", ...}
Stdout: deny JSON on a conflict, else nothing. Exit always 0.
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import kernel_proc  # noqa: E402  (stdlib-only, hot-path budgeted)

_HERE = os.path.dirname(os.path.abspath(__file__))
RULE_ID = "ARCHITECTURE.kernel-isolation"
_RESET_FLAGS = ("--hard", "--merge", "--keep")


# The borrowed helpers are MEMOIZED, and QA cycle 12 C8 is why. Each of these
# `exec_module`s a whole file, `scan()` calls both, and `scan()` recurses once
# per `-c` body, per process substitution and (since C1) per command
# substitution. Measured before memoizing: 2000 recursions cost 22.6 s, ~11 ms
# of module execution each, so the parse budget stopped the recursion long
# after the harness timeout would have. One load per process now.
_SHELL_C_CACHE = None
_DIM_CACHE = None


def _shell_c():
    """Borrow the `<shell> -c <body>` detector the receipt gate already proves
    (receipt_ledger.py:79). One regex for the whole brain, same reason as the
    splitter: a second copy drifts and the drift is invisible until a deny fails
    to fire."""
    global _SHELL_C_CACHE
    if _SHELL_C_CACHE is not None:
        return _SHELL_C_CACHE
    import importlib.util
    path = os.path.join(_HERE, "receipt_ledger.py")
    spec = importlib.util.spec_from_file_location("receipt_ledger_borrow", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _SHELL_C_CACHE = mod._SHELL_C
    return _SHELL_C_CACHE


def _dim_helpers():
    """Borrow the command-boundary splitter and the broad-stage classifier the
    dimension gate already proves (dimension-awareness-hook.py:214,:259). One
    parser for the whole brain: a second copy would drift and the drift would be
    invisible until a deny failed to fire."""
    global _DIM_CACHE
    if _DIM_CACHE is not None:
        return _DIM_CACHE
    import importlib.util
    path = os.path.join(_HERE, "dimension-awareness-hook.py")
    spec = importlib.util.spec_from_file_location("dimension_awareness_hook", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _DIM_CACHE = (mod._split_subcmds, mod._broad_git_verb)
    return _DIM_CACHE


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
        rec = {"kind": "deny", "rule": RULE_ID, "gate": "tree-owner"}
        rec.update(fields)
        kernel_proc.append(pid, rec)
    except Exception:
        pass


def describe(pid: str, row: dict) -> str:
    """The one line a human reads while blocked, so it says what is KNOWN.

    A parent link still proves `subagent`: only a child is ever given one. Its
    ABSENCE proves nothing, and calling that a main loop was a guess printed as
    a fact. `claim_lane` creates a row with neither `type` nor `ppid` when a
    register hook loses its race with the process's first write, and for that
    row the deny used to read `(main loop, never journaled)` about a subagent.
    `UNKNOWN_TYPE` is the word every other reader already uses for exactly this,
    so the gates and `octo ps`/`top`/`replay` cannot drift apart on it.
    """
    row = row or {}
    age = kernel_proc.process_age(pid)
    kind = (row.get("type") or ("subagent" if row.get("ppid")
                                else f"type {kernel_proc.UNKNOWN_TYPE}"))
    # THREE STATES, because `process_age` now has three answers (C-A). NaN is
    # "its journal is there and its last record cannot be read", which is
    # neither "never journaled" nor a number, and printing either of those for
    # it is the verdict-and-explanation split this function exists to avoid.
    when = ("last activity UNKNOWN (its journal's last record is unreadable, so "
            "it is held, not free)" if age != age
            else "never journaled" if age < 0
            else f"last active {int(age)}s ago")
    return f"pid {pid} ({kind}, {when})"


# ── THE OWNERSHIP LOOP IS O(HITS x ROWS), AND ONLY ONE WAS BOUNDED ──────────
#
# QA cycle 15 blocker 1, and it is cycle 14's lesson on a new axis: cycle 14
# said the budget was measured on the wrong COMMAND shape, and cycle 15 found it
# measured on the wrong TABLE shape. The 1.88 s at 8000 tokens was taken against
# a 3-row fixture ptable. THIS MACHINE RUNS 146 ROWS AND 110 LANES, and
# `lane_owner` walks every row for every hit, so the cost is per-hit TIMES rows.
# Measured end to end with the table seeded to the live shape, on the input QA
# names, `"rm -f " + " ".join(["x"]*k)`, which is 2k+5 bytes and under every
# character cap:
#
#     2000 tokens 1.95 s      6000 tokens KILLED rc124, empty stdout
#     4000 tokens 4.83 s      8000 tokens KILLED rc124, empty stdout
#                             8200 tokens DENY in 0.24 s (the cap works above it)
#
# AFTER, at the same live shape and measured the same way. TWO RUNS ARE QUOTED,
# not one, because the first pair of numbers this comment carried came from a
# quiet moment and a second run under load contradicted them by 5x — which is
# the error this whole chain has been about, a number measured under one load
# stated as a property of the code:
#
#                     run A (load 9)          run B (load ~20)
#     same path       0.25 / 0.24 / 0.33 s    1.61 / 1.22 / 1.30 s
#     distinct paths  0.24 / 0.29 / 0.46 s    0.48 / 1.72 / 2.35 s
#     under a lane    0.17 / 0.14 / 0.15 s    0.31 / 0.40 / 0.41 s  (DENY, early exit)
#                     (2000 / 4000 / 8000 tokens)
#
# THE CLAIM IS THE WORST OBSERVED, 2.35 s against the 5 s kill, and every shape
# returns a VERDICT in both runs — which is the property that was missing, since
# before this the same band returned rc 124 and empty stdout. At 500 rows it is
# faster still, because the row count left the inner loop.
#
# A killed hook writes no stdout and empty stdout is ALLOW, so the band under
# the cap was fail-open by clock on the real machine while every fixture-shaped
# measurement said it was fine.
#
# THE FIX IS NOT ANOTHER NUMBER, because the product is what is unbounded, and
# a cap on one factor cannot bound a product. Three changes, none of which moves
# the AUTHORITY away from `kernel_proc.lane_owner`:
#
#   1. the hits are DEDUPED before the loop. `rm -f x x x …` is one target
#      repeated k times, and the old loop asked the same question k times;
#   2. a NEGATIVE PREFILTER answers "this path cannot collide with any lane" in
#      O(depth + log n) out of an index built once. It may only ever say NO or
#      MAYBE; every MAYBE still goes to `lane_owner`, which keeps liveness,
#      row ordering, the scan budget and the journalling exactly where they are.
#      `test_c15_the_prefilter_never_hides_a_real_owner` asserts it has no false
#      negatives against `lane_owner` itself;
#   3. a MEMO per distinct target inside one call, because the loop can still
#      see the same path through two different verbs.
#
# What is deliberately NOT done here is a second implementation of the ownership
# rule. This file has been burned three times by a second copy of a shared rule
# drifting from the first, so the prefilter is allowed to be wrong in exactly
# one direction and a test pins that direction.
def _lane_prefilter(table: dict):
    """A callable answering "could this path collide with ANY lane" cheaply.

    Returns True for MAYBE and False for DEFINITELY NOT. Building it walks the
    table once; each query is a set lookup per path component plus one bisect.
    On any error it returns a function that always says MAYBE, so a prefilter
    that cannot be built costs speed and never coverage."""
    try:
        import bisect
        lanes = []
        for row in (table or {}).get("processes", {}).values():
            if not isinstance(row, dict):
                return lambda target: True      # an unreadable row hides lanes
            for lane in (kernel_proc.lanes_of(row) or []):
                norm = kernel_proc.norm_path(lane)
                if norm:
                    lanes.append(norm)
        exact = set(lanes)
        ordered = sorted(exact)

        def maybe(target: str) -> bool:
            if not target:
                return False
            if target in exact:
                return True
            # an ANCESTOR of the target is somebody's lane
            node = target
            while True:
                parent = os.path.dirname(node)
                if not parent or parent == node:
                    break
                if parent in exact:
                    return True
                node = parent
            # a lane lives UNDER the target
            below = target.rstrip(os.sep) + os.sep
            i = bisect.bisect_left(ordered, below)
            return i < len(ordered) and ordered[i].startswith(below)
        return maybe
    except Exception:
        return lambda target: True


def glob_owner(pattern: str, table: dict, pid, icase: bool = False) -> tuple:
    """(pid, row) of a LIVE process whose lane the glob actually reaches. The
    prefix test cannot answer this one: the pattern has no literal directory to
    prefix with, so each lane is matched against it instead."""
    import time
    now = time.time()
    skip = kernel_proc.safe_pid(pid) if pid else None
    for other, row in (table.get("processes") or {}).items():
        if other == skip:
            continue
        if not any(glob_hits(pattern, kernel_proc.norm_path(l), icase)
                   for l in kernel_proc.lanes_of(row)):
            continue
        if kernel_proc.is_live(other, table, now):
            return other, row
    return None, None


# ── token helpers (no `re` on the hot path) ─────────────────────────────────

def is_env_assign(tok: str) -> bool:
    if "=" not in tok:
        return False
    name = tok.split("=", 1)[0]
    if not name or not (name[0].isalpha() or name[0] == "_"):
        return False
    return all(c.isalnum() or c == "_" for c in name)


def peel_env(tokens: list) -> list:
    i = 0
    while i < len(tokens) and is_env_assign(tokens[i]):
        i += 1
    return tokens[i:]


# THE ONLY TWO EXPANSIONS THIS GATE PERFORMS, and the line is drawn where the
# answer stops being deterministic. `~` and `$HOME` do not depend on the state
# of a shell nobody ran: HOME is set in every login shell and THIS PROCESS KNOWS
# ITS OWN, so expanding them reads a value the gate already holds rather than
# guessing one. Every OTHER variable (`$DIR`, `$PWD`, `$1`) and brace expansion
# stay unexpanded and stay a NAMED RESIDUAL, because their value lives in a
# shell this gate never runs and inventing one would deny work nobody owns.
#
# QA cycle 10 F3: `rm "$HOME/.claude/settings.json"` was a one-token bypass of
# every path rule in this file, the kernel floor included, while the same
# command spelled absolutely was correctly denied. `$HOME` is expanded only at
# the START of a token and only when what follows it is a separator or the end
# of the token, so `$HOMEBREW/bin` is left alone.
def expand_home(path: str) -> str:
    if path.startswith("${HOME}"):
        path = os.path.expanduser("~") + path[len("${HOME}"):]
    elif path.startswith("$HOME") and (
            len(path) == 5 or not (path[5].isalnum() or path[5] == "_")):
        path = os.path.expanduser("~") + path[5:]
    return os.path.expanduser(path)


def _collapse_slashes(tok: str) -> str:
    """*tok* with runs of `/` collapsed to one. QA cycle 13: `//dev/stdin` and
    `/dev//fd/0` are the same files to the kernel and were different strings to
    this table, which is one `/` between a program and a table lookup. POSIX
    reserves a LEADING `//` for the implementation, so `os.path.normpath` keeps
    it and cannot be used here; Linux treats it as `/`."""
    while "//" in tok:
        tok = tok.replace("//", "/")
    return tok


# Character devices that ACCEPT a write and store nothing. `curl -o /dev/null`
# is the standard way to measure an HTTP status and it appears in 796 hits over
# 19403 real commands; reading it as a write costs an ownership lookup per hit
# and puts a target in the report that can never be anyone's lane.
_NULL_SINKS = ("/dev/null", "/dev/zero", "/dev/stdout", "/dev/stderr",
               "/dev/tty", "/dev/full", "/dev/random", "/dev/urandom")


def is_null_sink(path: str) -> bool:
    return _collapse_slashes(expand_home(path or "")) in _NULL_SINKS


def resolve(path: str, here: str) -> str:
    path = expand_home(path)
    return kernel_proc.norm_path(path if os.path.isabs(path) else os.path.join(here, path))


# Wrappers that prefix a command without changing what it does to the file
# system. `env -u CLAUDE_SESSION_ID octo ps --release ...` is the documented
# bypass attempt (v8-kernel.md section 2), so peeling these is part of the rule.
#
# The option table is PER WRAPPER, because the same letter means different
# things: `-i` is a flag for env and sudo (clean environment / login shell) and
# takes a value for stdbuf (input buffer). One shared table swallowed the
# command after `env -i`. `cd` names the options that MOVE the working
# directory, and `arg` counts leading positionals to skip (timeout's duration).
_WRAPPERS = {
    "env": {"valued": ("-u", "--unset", "-S", "--split-string"),
            "cd": ("-C", "--chdir"), "arg": 0},
    "sudo": {"valued": ("-u", "--user", "-g", "--group", "-p", "--prompt",
                        "-C", "--close-from", "-h", "--host", "-R", "--chroot",
                        "-U", "--other-user", "-T", "--command-timeout",
                        "-r", "--role", "-t", "--type"),
             "cd": ("-D", "--chdir"), "arg": 0},
    "command": {"valued": (), "cd": (), "arg": 0},
    "nohup": {"valued": (), "cd": (), "arg": 0},
    "exec": {"valued": ("-a",), "cd": (), "arg": 0},
    "time": {"valued": ("-f", "--format", "-o", "--output"), "cd": (), "arg": 0},
    "nice": {"valued": ("-n", "--adjustment"), "cd": (), "arg": 0},
    "timeout": {"valued": ("-s", "--signal", "-k", "--kill-after"), "cd": (), "arg": 1},
    "stdbuf": {"valued": ("-i", "-o", "-e", "--input", "--output", "--error"),
               "cd": (), "arg": 0},
    "xargs": {"valued": ("-n", "-I", "-i", "-P", "-d", "-a", "-E", "-e", "-s", "-L",
                         "--max-args", "--replace", "--max-procs", "--delimiter",
                         "--arg-file", "--max-lines"),
              "cd": (), "arg": 0},
    # A MULTI-CALL BINARY IS A WRAPPER, NOT A PROGRAM. `busybox rm -f <lane>`
    # runs busybox's own rm and the file is exactly as gone; QA cycle 10 F2
    # measured it passing while the bare `rm` was denied, for no reason other
    # than that the first token was not a verb anybody had listed. This is the
    # same shape as `env`/`nohup`/`command` above (peel the token, the next one
    # is the real program), so it belongs in THIS table rather than in a new
    # one. `toybox` is the same binary shape and is peeled with it.
    "busybox": {"valued": (), "cd": (), "arg": 0},
    "toybox": {"valued": (), "cd": (), "arg": 0},
}


# ── THE WRAPPER CLASS, INVERTED (QA cycle 13) ───────────────────────────────
#
# `_WRAPPERS` above is a TABLE, and cycle 13 measured what a table is worth
# against a real held lane with `rm -f <lane>/f.txt` as the passing control:
#
#   setsid -w rm -f <lane>/f.txt        ALLOW      ionice -c 3 rm …   ALLOW
#   flock /tmp/l rm -f <lane>/f.txt     ALLOW      taskset -c 0 rm …  ALLOW
#   unshare -r rm …                     ALLOW      strace -o … rm …   ALLOW
#   systemd-run --user rm …             ALLOW      watch -x rm …      ALLOW
#
# every one of them installed on this host, and `setsid -w` is MANDATED by the
# hard rules of the briefs this repo is built under, so the table was missing
# the wrapper that stands in front of nearly every command an agent here runs.
# Cycle 10 added `busybox`/`toybox` to the table; cycle 12 added the `<tool>
# run <program>` shape. Both were members. The class is "runs the next token"
# and it has more members than anyone will enumerate — `nsenter`, `chrt`,
# `catchsegv`, `ltrace`, `runuser`, `setarch`, `numactl`, `firejail`, `proot`,
# `bwrap`, `daemonize`, `retry`, `parallel` are the next thirteen, and that
# list is not closed either.
#
# So the name is inverted away, exactly as the kernel floor stopped being a
# verb list in 63c875e and the interpreter test stopped being a name test in
# `stdin_is_program`. THE RULE: when the head is a program this file MODELS
# (a mutator, a state verb, a code host, a read-only reader, `git`, `find`,
# `octo`, or a wrapper already in the table), it is the program and nothing is
# peeled. When the head is a program this file models NOTHING about, the first
# later token that IS a modeled program is the real program, whatever the head
# was called. `uv run --python 3.12 python -` peels without `uv`, `--python` or
# `3.12` being named anywhere, and so does the wrapper nobody has invented yet.
#
# BOUNDED FOUR WAYS, because an inversion that over-fires is a gate people
# route around:
#   * a REMOTE runner is never peeled. `docker run python3 -` writes the
#     container's file system, `ssh host rm -f x` writes another machine's, and
#     peeling either would turn the header's stated residual into a false deny;
#   * a SCRIPT runner's `run` is never peeled. `npm run rm` runs a package.json
#     script called `rm` and `cargo run rm` runs the crate's own binary; both
#     were measured DENYING at cycle 12's tip and both are over-fires;
#   * the peel TARGET must be a program that acts. `install` is excluded from
#     that set on its own, because it is the one modeled program whose name is
#     also every package manager's subcommand (`pip install x`, `apt-get
#     install -y a b`), and a read-only reader is excluded because peeling to
#     one would SUPPRESS the kernel floor for the segment rather than sharpen
#     it;
#   * the scan reads tokens as they arrived (`pre_peel`) for the kernel floor,
#     so a peel that finds nothing still leaves every path rule in place.
#
# Under-fire that remains, stated: a wrapper whose program is COMPUTED
# (`setsid $(echo rm) -f x`) peels to a marker, not a program. The marker is
# not a modeled program either, so the segment falls back to the token scan,
# which is the behaviour a computed verb has had since cycle 12.
_RUN_VERBS = ("run", "exec", "x")
# Heads whose `run` takes a SCRIPT NAME or a crate, never a program on PATH.
# Measured at cycle 12's tip: `npm run rm -- <lane>` and `cargo run rm <lane>`
# both denied, and neither runs a real `rm`.
_SCRIPT_RUNNERS = ("npm", "yarn", "pnpm", "cargo", "make", "just", "task",
                   "nx", "turbo", "gradle", "mvn", "composer", "dotnet", "go",
                   "rake", "bundle")
# Runners whose `run` puts the program on ANOTHER machine or in another
# filesystem namespace. `docker run python3 - <<EOF` writes the CONTAINER's
# `~/.claude/.cache/kernel`, not this host's, so peeling them would turn a
# stated under-fire (the header's ssh / container-exec residual) into a false
# deny. They stay unpeeled, and the residual stays what it already says it is.
# QA cycle 13 measured the same claim from the OTHER side, over the real Bash
# commands out of this machine's transcripts: `aws s3 cp ~/x s3://bucket/y`
# peeled to `cp` and resolved `s3://bucket/y` against the cwd. A cloud CLI's
# `cp`, `rm`, `mv` and `state rm` act on a namespace that is not this file
# system, which is the same sentence `docker` and `ssh` are on this list for,
# so they go on it rather than into a second list that means the same thing.
# The line is drawn at "has a file verb of its own": `gh` and `heroku` are
# remote too and are NOT here, because nothing they spell collides with a
# program in these tables and adding them would be padding.
_REMOTE_RUNNERS = ("docker", "podman", "nerdctl", "kubectl", "oc", "ssh",
                   "scp", "rsync",
                   "lxc", "machinectl", "distrobox", "toolbox", "flatpak",
                   "apptainer", "singularity", "vagrant",
                   "aws", "gcloud", "az", "gsutil", "rclone", "mc", "s3cmd",
                   "b2", "wrangler", "terraform", "tofu", "pulumi")
# Shell RESERVED WORDS. A head that is one of these is not "a program this file
# models nothing about", it is a compound command, and the inversion must not
# read the next word as its program. Measured: a python heredoc body carrying
# `for ln in mem.read_text().splitlines():` peeled at `ln` — a real mutator in
# a real table, in a line that is not a shell command at all.
_SHELL_KEYWORDS = ("for", "while", "until", "if", "then", "else", "elif", "fi",
                   "do", "done", "case", "esac", "in", "select", "function",
                   "return", "coproc", "declare", "local", "export", "readonly",
                   "typeset", "let", "trap", "alias", "unalias", "set", "unset",
                   "shift", "break", "continue", "eval", "exec", "builtin",
                   "source", "times", "getopts", "read", "printf", "mapfile",
                   "readarray", "wait", "jobs", "fg", "bg", "kill", "ulimit",
                   "umask", "hash", "help", "logout", "suspend", "compgen",
                   "complete", "compopt", "enable", "caller", "shopt")


# ── THE `-c` CHANNEL, AND THE TWO SPELLINGS THAT WERE NOT IT ────────────────
#
# QA cycle 13. `_shell_c` matches an ANCHORED `<shell> -c <body>` and the scan
# adds a `"-c" in tokens` fallback for a wrapped one. Both look for the token
# `-c`, EXACTLY, so two ordinary spellings walked past a real held lane:
#
#   bash -ec 'rm -f <lane>/f.txt'          ALLOW      a short-option BUNDLE
#   script -qc 'rm -f <lane>/f.txt' /dev/null  ALLOW  the same, on a wrapper
#   eval 'rm -f <lane>/f.txt'              ALLOW      no flag at all
#
# `stdin_is_program` already reads bundles (`bash -se` is `bash -s -e`, cycle
# 12 C7); the `-c` side never learned. QA cycle 14 corrected the rule and the
# sentence that justified it: cycle 13 accepted only a bundle whose LAST letter
# is `c`, arguing that "`-ce` would make `e` the program instead". That is false
# about bash, measured — `bash -ce "rm -f <lane>"` deletes the file and exits 0,
# because `c` takes the next word wherever it sits in the cluster. So the test
# is CONTAINS `c`, not ends with it.
#
# On an UNMODELED head the rule is the merge gate's inversion rather than a
# wrapper table (`qa-merge-gate._reparse_args`): when no program this file
# knows comes first, a `-c`/`--command` flag — or a bundle ending in `c` — is a
# re-parse whatever the wrapper is called, which is what closes `script -qc`,
# `flock /tmp/l -c` and `su -c` without any of the three being named. It is
# bounded by the head test: `grep -rc x .`, `wc -lc f` and `sort -uc f` are all
# read-only programs this file models, so none of them reaches this rule.
#
# `eval` is the one member with no flag: every argument it takes, joined, is a
# command line. It is not a wrapper (there is no program to peel forward to)
# and not a `-c` host, so it gets its own line at the dispatch.
_BUNDLE_C_MAX = 6                 # `-euxoc` and shorter; past that it is data
# Where a forward peel STOPS, and it is no longer a token COUNT. QA cycle 14
# blocker 2: the old `_PEEL_SCAN = 8` carried the sentence "measured, not
# chosen: the deepest real wrapper shape on this host is `uv run --python 3.12
# python -`, whose program sits at token 4", and the corpus contradicted it —
# `env -u A -u B -u C -u D <program>` chains put the program past token 8, and a
# chosen number that real traffic exceeds is a hole with a justification
# attached. The number is DELETED rather than re-chosen: the walk already stops
# at the first control token and the first reserved word, which is where a
# command actually ends, and the handoff to `_WRAPPERS` above means an option
# chain is consumed by the table that understands it instead of by this scan.
_CONTROL_TOKENS = (";", ";;", ";&", ";;&", "&", "&&", "||", "|", "|&",
                   "(", ")", "{", "}", "!", "\n")
# Reserved words that CLOSE or SEPARATE a command. Narrower than
# `_SHELL_KEYWORDS`, which also holds builtins: `exec` is a reserved word and
# also a wrapper, so stopping the forward search on it would undo the peel that
# `mise exec -- python3 -` needs.
_STOP_WORDS = ("do", "done", "then", "else", "elif", "fi", "esac", "in",
               "case", "for", "while", "until", "if", "select", "function")


def _c_flag_index(tokens: list, host_is_modeled: bool) -> int:
    """Index of the flag whose NEXT token is a shell command, or -1.

    On a modeled shell the flag comes from `_PROGRAM_FLAGS_BY_HOST`; a bundle
    is read only for a host that HAS `-c` in that row, so `python -c` keeps its
    exact match and `perl -e` is unaffected. On an unmodeled head only `-c`,
    `--command` and a bundle ending in `c` count."""
    if host_is_modeled:
        key = _host_key(os.path.basename(tokens[0]))
        flags = _PROGRAM_FLAGS_BY_HOST.get(key, _PROGRAM_FLAGS)
    else:
        flags = _PROGRAM_FLAGS
    bundles = "-c" in flags
    for i, tok in enumerate(tokens[1:], 1):
        if tok in flags or tok.partition("=")[0] in flags:
            return i
        if (bundles and len(tok) > 2 and len(tok) <= _BUNDLE_C_MAX
                and tok.startswith("-") and not tok.startswith("--")
                and tok[1:].isalpha()
                # On a MODELED SHELL `c` means command wherever it sits in the
                # cluster, so CONTAINS is the rule. On an unmodeled head it must
                # be LAST, because a middle `c` is an ordinary letter far more
                # often than a command flag: `tar -cf a.tar dir` and `ps -ef`
                # are not shells, and reading their next token as a command line
                # is a false deny (measured: `tar -cf x.tar --remove-files
                # <lane>` stopped reaching its own consuming-target rule).
                and (("c" in tok[1:]) if host_is_modeled else tok.endswith("c"))):
            return i
    return -1


def _modeled_program(name: str) -> bool:
    """True when this file has a table for what *name* does to the file system.

    The set is every table the scan dispatches on, so "modeled" means the same
    thing here as it does at the dispatch: a head this returns True for is the
    program, and nothing in front of it needs peeling."""
    base = os.path.basename(name)
    return (is_code_host(base) or base in _MUTATORS or base in _STATE_VERBS
            or base in _KSTATE_READONLY or base in _WRAPPERS
            or base in ("git", "find", "octo"))


def _peel_target(name: str) -> bool:
    """True when *name* is a program worth peeling FORWARD to: one that acts.

    Narrower than `_modeled_program` on purpose, and the two exclusions are the
    bounds the header states. `install` is every package manager's subcommand,
    so peeling to it would read `apt-get install -y a b` as a copy into `b`. A
    read-only reader is excluded because a peel to `cat` would move the head out
    of the branch that applies the kernel floor, which makes the gate weaker
    rather than sharper.

    A WRAPPER IS A PEEL TARGET (QA cycle 14 blocker 2). Excluding them meant an
    unmodeled head could not HAND OFF to the table, so
    `setsid -w env -u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE -u GIT_PREFIX
    rm -f <lane>` walked: `setsid` is unmodeled, `env` was not a target, and by
    the time the flat search reached `rm` it had spent its scan depth on `env`'s
    own `-u` pairs. Peeling to `env` instead lets `peel_wrappers` consume those
    pairs with the option table that already knows `-u` is valued, and the loop
    lands on `rm` with depth to spare. Measured over 19403 distinct real
    commands: counting to the first acting program OR wrapper, 661 of 662
    unmodeled-head segments have it at index 7 or less."""
    base = os.path.basename(name)
    return (is_code_host(base) or base in _STATE_VERBS
            or (base in _MUTATORS and base != "install")
            or base in _WRAPPERS
            or base in ("git", "find", "octo"))


def _peel_unknown_head(tokens: list):
    """*tokens* from the real program on, when the HEAD is a program this file
    models nothing about and a later token is one it does; None otherwise.

    This is the whole wrapper rule (see the header above). It subsumes the
    cycle-12 `<tool> run <program>` shape — `run` is simply a token that is not
    a modeled program, so the search walks past it — which is why the flag
    under-fire that shape carried (`uv run --python 3.12 python -`) closes with
    it rather than needing a per-runner option table."""
    if len(tokens) < 2 or tokens[0].startswith("-"):
        return None
    head = os.path.basename(tokens[0])
    if (_modeled_program(head) or head in _REMOTE_RUNNERS
            or head in _SHELL_KEYWORDS or tokens[0] in _SHELL_KEYWORDS
            or tokens[0].endswith(")")):
        return None
    if head in _SCRIPT_RUNNERS and tokens[1] in _RUN_VERBS:
        return None
    # THE SEARCH STOPS AT A COMMAND BOUNDARY, and it has to, because the
    # borrowed splitter does not see every one of them. Measured over the real
    # corpus: `case "$ST" in … pend) ;; *) break;; esac\ndone\naws ssm …\naws
    # s3 cp …` arrives as ONE segment (the splitter does not break a `case`
    # block on its newlines), its head is `pend)`, and a search with no bound
    # walks past `;;`, `esac`, `done` and two whole commands to land on the
    # `cp` of an `aws s3 cp` three lines later. A wrapper's program sits in
    # front of its own arguments, so the walk ends at the first control token
    # and the first reserved word, which is where the command ends. There is no
    # token-count bound: one was measured wrong (see `_PEEL_SCAN`, deleted).
    for j, tok in enumerate(tokens[1:], 1):
        if (tok in _CONTROL_TOKENS or tok in _STOP_WORDS
                or tok.endswith(";") or tok.endswith(")")):
            return None
        if _peel_target(tok):
            return tokens[j:]
    return None


def peel_wrappers(tokens: list, here: str) -> tuple:
    """(tokens with wrapper prefixes removed, the cwd they leave behind).

    `env -C <dir> rm x` and `sudo -D <dir> rm x` move the directory a relative
    target resolves against, so the peel returns it rather than dropping it."""
    while True:
        if not tokens or os.path.basename(tokens[0]) not in _WRAPPERS:
            peeled = _peel_unknown_head(tokens)
            if peeled is None:
                return tokens, here
            tokens = peeled
            continue
        spec = _WRAPPERS[os.path.basename(tokens[0])]
        skip = spec["arg"]
        i = 1
        while i < len(tokens):
            tok = tokens[i]
            name, eq, val = tok.partition("=")
            if name in spec["cd"]:
                target = val if eq else (tokens[i + 1] if i + 1 < len(tokens) else "")
                if target:
                    here = resolve(target, here)
                i += 1 if eq else 2
                continue
            if name in spec["valued"]:
                i += 1 if eq else 2
                continue
            if tok.startswith("-") or is_env_assign(tok):
                i += 1
                continue
            if skip:
                skip -= 1
                i += 1
                continue
            break
        if i >= len(tokens):
            return [], here
        tokens = tokens[i:]


def _is_descriptor(operand: str) -> bool:
    """True when a redirect operand names a DESCRIPTOR rather than a file.
    Trailing shell punctuation is stripped first: this parser is not the shell,
    so `2>&1;` reaches it with the `;` still attached."""
    core = (operand or "").rstrip(";&|)}")
    return not core or core.isdigit() or core == "-"


def redirect_targets(tokens: list) -> tuple:
    """(files this segment writes by redirection, the remaining tokens).

    `2>&1` writes no file (its operand names a descriptor, not a path) and a
    plain input redirect writes nothing at all, so both drop out here rather
    than becoming phantom targets.

    QA CYCLE 15 BLOCKER 2c: the old reader stripped digits and then required the
    core to start with `>`, which is three spellings short. `&>file` and
    `&>>file` (stdout AND stderr, the common one) start with `&`; `>&file` is
    the same redirection written the other way round and is NOT `>&1`, which
    names a descriptor; `{fd}>file` opens a file and binds a new descriptor to
    it; and `1<>file` opens for READING AND WRITING, so it is a write whatever
    the `<` suggests. All four reached the kernel directory."""
    targets, rest, i = [], [], 0
    while i < len(tokens):
        tok = tokens[i]
        core = tok.lstrip("0123456789")
        # `{fd}>file` / `{fd}>>file`: bash's named-descriptor form
        if core.startswith("{") and "}" in core:
            core = core[core.index("}") + 1:]
        # `&>file`, `&>>file`: stdout and stderr to one FILE
        if core.startswith("&>"):
            after = core[2:].lstrip(">")
            if after:
                targets.append(after)
            elif i + 1 < len(tokens):
                targets.append(tokens[i + 1])
                i += 1
            i += 1
            continue
        # `<>file`: opened for reading AND writing, so it is a write
        if core.startswith("<>"):
            after = core[2:]
            if after:
                targets.append(after)
            elif i + 1 < len(tokens):
                targets.append(tokens[i + 1])
                i += 1
            i += 1
            continue
        if core.startswith(">"):
            after = core.lstrip(">")
            if after.startswith("&"):
                # `>&1` names a DESCRIPTOR; `>&file` names a FILE. The operand
                # may arrive with shell punctuation still attached, because the
                # tokenizer is not the shell: `2>&1;` and `2>&1)` are the same
                # descriptor as `2>&1`, and reading the trailing `;` as part of
                # a filename put junk targets on real commands (measured over
                # the corpus, which is what caught it).
                operand = after[1:]
                if operand and not _is_descriptor(operand):
                    targets.append(operand)
                elif not operand and i + 1 < len(tokens):
                    nxt = tokens[i + 1]
                    if not _is_descriptor(nxt):
                        targets.append(nxt)
                    i += 1
            elif after:
                targets.append(after)
            elif i + 1 < len(tokens):
                if not tokens[i + 1].startswith("&"):
                    targets.append(tokens[i + 1])
                i += 1
            i += 1
            continue
        if core.startswith("<"):
            if not core.lstrip("<") and i + 1 < len(tokens):
                i += 1
            i += 1
            continue
        rest.append(tok)
        i += 1
    return targets, rest


# Options that ALWAYS consume a separate argument. `--backup`, `--reflink` and
# `--sparse` are deliberately absent: their argument is optional and only ever
# arrives with `=`, so listing them would eat the first SOURCE of
# `cp --backup src dst` and turn a covered command into an uncovered one.
_VALUED_MUTATOR_OPTS = {
    "truncate": ("-s", "--size", "-r", "--reference"),
    "sed": ("-e", "--expression", "-f", "--file", "-l", "--line-length"),
    "install": ("-m", "--mode", "-o", "--owner", "-g", "--group",
                "-t", "--target-directory", "-S", "--suffix", "--strip-program"),
    "ln": ("-t", "--target-directory", "-S", "--suffix"),
    "cp": ("-t", "--target-directory", "-S", "--suffix"),
}


def _positional(base: str, args: list) -> list:
    valued = _VALUED_MUTATOR_OPTS.get(base, ())
    out, i = [], 0
    while i < len(args):
        tok = args[i]
        name, eq, _val = tok.partition("=")
        if name in valued:
            i += 1 if eq else 2
            continue
        if tok.startswith("-"):
            i += 1
            continue
        out.append(tok)
        i += 1
    return out


def _valued(args: list, names: tuple):
    """The value of the first of `names` present, as `-t DIR` or `--long=VAL`."""
    for i, tok in enumerate(args):
        name, eq, val = tok.partition("=")
        if name in names:
            if eq:
                return val
            if i + 1 < len(args):
                return args[i + 1]
    return None


def _short_flag(args: list, letter: str, long_forms: tuple) -> bool:
    """A bundled short flag (`-sf` carries `s`) or one of its long spellings."""
    for tok in args:
        if tok in long_forms:
            return True
        if tok.startswith("-") and not tok.startswith("--") and letter in tok[1:]:
            return True
    return False


# `cp`, `install` and `ln` all take SOURCES and then a DESTINATION, so they get
# ONE target rule rather than three copies that drift apart.
#
# QA cycle 10 F1, the destination half: `install /dev/null <lane>` overwrites
# the file exactly as `cp /dev/null <lane>` does, and this gate denied the
# second and allowed the first for one reason, that `install` was missing from a
# list of verbs. The destination is the last positional, or the directory named
# by `-t`, or EVERY positional under `install -d`, which creates directories
# instead of copying files.
#
# QA cycle 10 F4, the SOURCE half, and it is NOT symmetrical with the others: a
# non-symbolic `ln` (and `cp -l`) creates a SECOND NAME FOR THE SAME INODE.
# `realpath` does not resolve a hardlink, so the new name is a path no gate can
# connect back to the protected one, and the later write through it is invisible
# by construction. The `ln` is therefore the last moment anything is decidable
# and it is where the deny has to land. A SYMBOLIC link is not this: it is a new
# file whose content is a path, and a write through it resolves to the original,
# where the ordinary lane test still runs. So `-s` keeps only the destination.
def _copy_targets(base: str, args: list, positional: list) -> list:
    if base == "install" and _short_flag(args, "d", ("--directory",)):
        return positional               # `install -d a b c` creates all of them
    into = _valued(args, ("-t", "--target-directory"))
    if into:
        dest, sources = [into], positional
    elif len(positional) >= 2:
        dest, sources = positional[-1:], positional[:-1]
    elif positional:
        # `ln <src>` links into the cwd under the source's basename; a lone
        # `cp`/`install` argument is an error and names no destination.
        dest = [os.path.basename(positional[0])] if base == "ln" else []
        sources = positional
    else:
        return []
    if base == "ln" and not _short_flag(args, "s", ("--symbolic",)):
        return dest + sources
    if base == "cp" and _short_flag(args, "l", ("--link",)):
        return dest + sources
    return dest


# ── PROGRAMS THAT WRITE A PATH THEY ARE HANDED (QA cycle 14 blocker 5) ───────
#
# The lane rule has always been a MUTATOR table, and a table is an enumeration.
# This one is stated AS an enumeration with an end rather than dressed up as a
# closed class, because the honest inversion does not exist here: on the kernel
# floor a path is denied wherever it appears, so position alone decides, but a
# LANE has no floor and the only thing separating `curl -o <lane>` from
# `grep -f <lane>` is knowing what the flag means.
#
# Measured against a held lane at e00fad7, every one of these ALLOWED while the
# same write spelled `rm`/`cp` denied. Traffic counts are from 19403 distinct
# real commands on this machine: `-o`/`-O` output flags appear in 595 of them.
_OUTPUT_FLAGS = {
    "curl": ("-o", "--output", "--trace", "--trace-ascii", "--dump-header",
             "-D", "--stderr"),
    "wget": ("-O", "--output-document", "-o", "--output-file",
             "--append-output"),
    "sort": ("-o", "--output"),
    "less": ("--log-file", "--LOG-FILE", "-o", "-O"),
    "tar": ("-f", "--file"),
    "openssl": ("-out",),
    "gpg": ("-o", "--output"),
    "tee": ("-a", "--append"),
    "csplit": ("-f", "--prefix"),
    "pandoc": ("-o", "--output"),
    "psql": ("-o", "--output", "-L", "--log-file"),
    "patch": ("-o", "--output", "-r", "--reject-file"),
    "strip": ("-o",),
    "gcc": ("-o",), "g++": ("-o",), "cc": ("-o",), "clang": ("-o",),
    "go": ("-o",), "rustc": ("-o",),
}
# AN EMPTY ROW IS THE `uniq` SHAPE, ONE CYCLE LATER (QA cycle 15 blocker 3).
# The version this replaces carried `ffmpeg`, `convert`, `sqlite3`,
# `wkhtmltopdf`, `mysql`, `split`, `jq`, `diff` and `dd` with EMPTY flag tuples.
# They armed the trigger, they read as modelled, and they covered nothing,
# because every one of those programs writes a POSITIONAL. That is exactly the
# member `uniq` was — a write a flag screen cannot see — reintroduced by the
# commit that named it. The empty rows are gone; the ones whose output position
# can actually be stated moved to `_POSITIONAL_OUTPUT`, and the rest
# (`wkhtmltopdf`, `mysql`, `jq`, `diff`) left the file, because a row that
# covers nothing is worse than no row: it makes the table look finished.
# `test_c15_no_output_flag_row_is_empty` makes the shape impossible to add back.
# `dd` left this table too: its `of=` was already read by `mutation_targets`.

# Programs whose output is a POSITIONAL, with WHICH positional stated. `uniq`
# is the member a `--help` screen for output FLAGS cannot see, and it is why the
# header no longer claims a flag probe proves anything.
_POSITIONAL_OUTPUT = {
    "uniq": "last",         # `uniq IN OUT`
    "ffmpeg": "last",       # `ffmpeg -i IN … OUT`
    "convert": "last", "magick": "last",
    "zip": "first",         # `zip ARCHIVE files…`
    "objcopy": "last",      # `objcopy IN OUT`, and IN-PLACE with one operand
    "sqlite3": "first",     # `sqlite3 DB "SQL"` writes the database
    "split": "last",        # the PREFIX its pieces are written under
}
_CONSUMING = {
    "gzip": ("-k", "--keep"), "bzip2": ("-k", "--keep"),
    "xz": ("-k", "--keep"), "lzma": ("-k", "--keep"),
    "zstd": ("--rm",), "compress": (),
}


# Programs that take a COMMAND as a string argument rather than behind `-c`.
# Enumerated, with a stated end, and each measured executing on this host.
# `env -S` is the sharpest of them, because `-S` was already in env's VALUED
# option table, so the command WAS the value and the peel dropped it whole.
_COMMAND_STRING = {
    "env": ("-S", "--split-string"),
    "watch": (),          # first non-flag argument
    "parallel": (),
    "hyperfine": (),
    "entr": (),
    "xargs": (),          # only when its command is one quoted string
    "flock": (),
    "script": ("-c", "--command"),
    "su": ("-c", "--command"),
    # `ssh` is deliberately NOT here although `ssh host "rm -f x"` is exactly
    # this shape: the command runs on ANOTHER machine, where this host's lanes
    # do not exist, and reading it as local would turn the stated remote
    # residual into a false deny. Same sentence `_REMOTE_RUNNERS` is on.
}
# The flags of a command-string program that CONSUME a value without being the
# command, so the first non-flag argument is found rather than guessed.
_COMMAND_STRING_VALUED = {
    "watch": ("-n", "--interval", "-d", "--differences"),
    "parallel": ("-j", "--jobs", "-N", "--delimiter"),
    "hyperfine": ("-w", "--warmup", "-m", "--min-runs", "-M", "--max-runs",
                  "--prepare", "--cleanup"),
    "entr": (),
    "xargs": ("-n", "-I", "-i", "-P", "-d", "-a", "-E", "-e", "-s", "-L"),
    "flock": (),
}


# ── A SUBSTITUTION THAT RUNS LATER (QA cycle 14) ─────────────────────────────
#
# `x="a[\$(rm -f <lane>; echo 0)]"; echo $((x))` deletes the file under bash and
# allowed at the gate. The escape makes `\$(` literal text at assignment time,
# so `split_command_substitutions` copies it through correctly; the command runs
# when `$((x))` evaluates the variable, in a shell this gate never enters.
#
# The residual it would otherwise fall into says "unknowable without running the
# shell", and that is NOT true here: the path is spelled out in the command. So
# the rule is on the DEFERRING CONSTRUCT rather than on the variable. When a
# command carries a deferred evaluator (`$((`, `eval`, `let`, `declare -i`), a
# substitution that was escaped or single-quoted is a command that evaluator can
# reach, and its body is scanned. Without one of those constructs the same text
# is quoted prose and stays untouched, which is what keeps
# `echo 'x $(rm -f k)'` allowed.
# Constructs that can evaluate text held in a variable. QA cycle 15 blocker 2b:
# the first four were the whole list, and `(( x ))`, `[[ $x -eq 0 ]]`,
# `${y:x}` and `arr[x]=1` are all arithmetic or expansion contexts outside it.
_DEFERRED_EVAL = ("$((", "$[", "((", "[[", "${", "eval", "let ",
                  "declare -i", "typeset -i")
# `name[expr]=` — an array subscript is an arithmetic context too
_ARRAY_SUBSCRIPT = re.compile(r"\w+\[[^]]+\]\s*=")
# `NAME=`, `NAME="`, `export NAME='` … immediately before the region, with no
# whitespace between: the value of an assignment and not an argument to a
# command.
_ASSIGNED_VALUE = re.compile(r"(?:^|[\s;&|(])\w+=[\"']?[^\s\"']*$")


def deferred_substitution_bodies(text: str) -> list:
    """Bodies of substitutions written so they do NOT run now, in a command that
    carries something able to run them later."""
    if not (any(m in text for m in _DEFERRED_EVAL)
            or _ARRAY_SUBSCRIPT.search(text)):
        return []
    out, i, n = [], 0, len(text)

    def stored(at: int) -> bool:
        """True when the region starting at *at* is the VALUE OF AN ASSIGNMENT.

        The whole class is "text put in a variable now and evaluated later", so
        the assignment is not decoration, it is the mechanism. Requiring it is
        what keeps PROSE out: measured over the corpus, a `gh issue comment
        --body "… \\`tool_calls_per_min > 30 && …\\` …"` was read as a deferred
        command because the body happened to contain backticks and the command
        happened to contain `[[`, and the `> 30` inside it became a redirect
        target. Documentation is not an assignment."""
        return bool(_ASSIGNED_VALUE.search(text[:at]))

    while i < n:
        # an ESCAPED substitution: literal now, a command when re-evaluated
        if text.startswith("\\$(", i) and stored(i):
            j = _match_paren(text, i + 2)
            body = text[i + 3:j - 1] if text[j - 1:j] == ")" else text[i + 3:]
            if body:
                out.append(body)
            i = j
            continue
        if text.startswith("\\`", i) and stored(i):
            j = text.find("`", i + 2)
            if j < 0:
                break
            out.append(text[i + 2:j])
            i = j + 1
            continue
        # a SINGLE-QUOTED REGION is literal now and a command when re-evaluated,
        # and the substitution may sit ANYWHERE inside it. The old reader
        # matched only `'$(`, so one character between the quote and the `$(`
        # walked, and the backtick spelling walked in every position.
        if text[i] == "'" and stored(i):
            close = text.find("'", i + 1)
            region = text[i + 1:close if close >= 0 else n]
            k = 0
            while k < len(region):
                if region.startswith("$(", k):
                    j = _match_paren(region, k + 1)
                    body = (region[k + 2:j - 1] if region[j - 1:j] == ")"
                            else region[k + 2:])
                    if body:
                        out.append(body)
                    k = j
                    continue
                if region[k] == "`":
                    j = region.find("`", k + 1)
                    if j < 0:
                        break
                    out.append(region[k + 1:j])
                    k = j + 1
                    continue
                k += 1
            i = (close + 1) if close >= 0 else n
            continue
        # a backtick inside DOUBLE quotes, escaped so it does not run now
        if text[i] == "`":
            j = text.find("`", i + 1)
            if j < 0:
                break
            i = j + 1
            continue
        i += 1
    return out


# Programs whose non-flag arguments are the TEXT (or the PATHS) they emit on
# stdout. `ls` and `find` are here because the thing they print is derived from
# an argument that is itself a path, so handing that argument to the receiver is
# conservative in the right direction.
_LITERAL_EMITTERS = ("echo", "printf", "ls", "find")
# Programs that read stdin as ARGUMENTS for another command rather than as a
# program. QA cycle 15 blocker 2a: `echo <path> | xargs rm -f` deleted the file
# and allowed, while `echo 'rm -f <path>' | bash` denied beside it — the pipe
# rule cycle 14 added only covered stdin-as-a-PROGRAM. The residual sentence did
# not cover it either: it says xargs-from-stdin is the case "where the targets
# never appear in the command at all", and here the target IS echo's argument,
# spelled out in the line.
_ARGUMENT_CONSUMERS = ("xargs",)


def literal_text_of(tokens: list) -> str:
    """The literal TEXT a segment emits on stdout, or "".

    Only `echo` and `printf` qualify, and only their non-flag arguments: this
    is the one case where the gate can know what lands on the next program's
    stdin without running anything."""
    if not tokens or os.path.basename(tokens[0]) not in _LITERAL_EMITTERS:
        return ""
    words = [t for t in tokens[1:] if not t.startswith("-")]
    return " ".join(words)


# ── THE COVERAGE BLOCK IS GENERATED, NOT MAINTAINED ─────────────────────────
#
# These lists have grown every cycle for three cycles, and every cycle the
# PROSE that described them drifted from the tables themselves: cycle 14's
# header said the read-only list held programs that "provably cannot write"
# while three of them could, and cycle 15 found nine rows that armed the trigger
# and covered nothing. Both are the same failure — a human-maintained
# description of a machine-maintained set — and the fix is the one the sibling
# gate made this session: stop writing the description and DERIVE it, then
# assert the documented block still equals the derivation, so adding a row
# without regenerating turns the suite red instead of leaving a sentence that
# used to be true.
#
# QA CYCLE 16 FOUND THE SAME FAILURE ONE LEVEL UP. `coverage_manifest()` did
# derive its members from the dispatch tables, and the DICT NAMING WHICH TABLES
# to derive from was hand-written — a human-maintained description of a
# machine-maintained set, again, just moved up a layer where the test could not
# see it. It named 11 of the 24 tables that hold program and verb names, so the
# block under-reported 56 modelled programs against a docstring that claimed
# "every program this file models": every interpreter in `_CODE_HOSTS` (bash,
# node, perl, python, deno …), every head in `_SCRIPT_RUNNERS` (make, npm,
# cargo, mvn …), `_REMOTE_COPY_VERBS`, `_C_HOSTS`, `_STDIN_FLAGS`, and `shred`,
# which `_EXEC_MUTATORS` models as a mutator and which appeared on no line.
#
# So the ROSTER is asserted too, and it is asserted against the FILE rather than
# against a list. `_ROSTER` says which tables fill which line;
# `_ROSTER_EXCLUSIONS` names every other `_`-prefixed table in this module with
# the reason it holds no program or verb name; `roster_partition()` reads this
# module's own source for the set of tables that exist. A table in neither is
# UNCLASSIFIED and a name in either that no longer exists is STALE, and both
# `--coverage` and the suite fail naming it. A roster nobody can forget to
# update is the point: forgetting is now a red test rather than a quiet
# under-report.
#
# `coverage_manifest()` is the derivation. `--coverage` prints it,
# `test_c15_the_documented_coverage_equals_the_derivation` asserts the block
# below matches it, and `_COVERAGE_BLOCK` is that block. Regenerate with:
#
#     python3 scripts/g__pretool-bash__tree-owner.py --coverage
#
# BEGIN GENERATED COVERAGE
_COVERAGE_BLOCK = """\
argument-consumer: xargs
code-host: Rscript awk bash bun dash deno gawk ksh lua mawk node perl php \\
py python python3 ruby sed sh tclsh zsh
command-string: entr env flock hyperfine parallel script su watch xargs
consuming: bzip2 compress gzip lzma xz zstd
git-pathspec-verb: checkout mv restore rm
literal-emitter: echo find ls printf
mutator: cp dd install ln mv rm sed shred tee truncate unlink
output-flag: cc clang csplit curl g++ gcc go gpg less openssl pandoc patch \\
psql rustc sort strip tar tee wget
parsed-head: git octo
positional-output: convert ffmpeg magick objcopy split sqlite3 uniq zip
read-only: b2sum base64 basename cat cd cksum cmp cut date df diff dirname \\
du echo egrep false fgrep file grep head jq ls md5sum od popd printf pushd \\
pwd readlink realpath rg sha1sum sha256sum stat strings tail test true \\
wait wc which
remote-copy-verb: copy copyto cp download fetch get move mv pull sync
remote-runner: apptainer aws az b2 distrobox docker flatpak gcloud gsutil \\
kubectl lxc machinectl mc nerdctl oc podman pulumi rclone rsync s3cmd scp \\
singularity ssh terraform tofu toolbox vagrant wrangler
run-verb: exec run x
script-runner: bundle cargo composer dotnet go gradle just make mvn npm nx \\
pnpm rake task turbo yarn
state-verb: chattr chmod touch
wrapper: busybox command env exec nice nohup stdbuf sudo time timeout \\
toybox xargs
"""
# END GENERATED COVERAGE

# Which tables fill which line of the manifest. Held as NAMES, resolved through
# `globals()` when the manifest is built, because most of these tables are
# defined below this point and the roster is not a second copy of them.
_ROSTER = {
    "argument-consumer": ("_ARGUMENT_CONSUMERS",),
    "code-host": ("_CODE_HOSTS", "_C_HOSTS", "_PROGRAM_FLAGS_BY_HOST",
                  "_VALUED_HOST_OPTS", "_STDIN_FLAGS"),
    "command-string": ("_COMMAND_STRING", "_COMMAND_STRING_VALUED"),
    "consuming": ("_CONSUMING",),
    "git-pathspec-verb": ("_PATHSPEC_VERBS",),
    "literal-emitter": ("_LITERAL_EMITTERS",),
    "mutator": ("_MUTATORS", "_EXEC_MUTATORS", "_VALUED_MUTATOR_OPTS"),
    "output-flag": ("_OUTPUT_FLAGS",),
    "parsed-head": ("_PARSED_HEADS",),
    "positional-output": ("_POSITIONAL_OUTPUT",),
    "read-only": ("_KSTATE_READONLY",),
    "remote-copy-verb": ("_REMOTE_COPY_VERBS",),
    "remote-runner": ("_REMOTE_RUNNERS",),
    "run-verb": ("_RUN_VERBS",),
    "script-runner": ("_SCRIPT_RUNNERS",),
    "state-verb": ("_STATE_VERBS",),
    "wrapper": ("_WRAPPERS",),
}
# The other side of the partition. Every entry is a table of STRINGS that names
# no program and no verb, with the reason stated per entry, because "it is not a
# program" asserted without saying what it IS is how the last three descriptions
# drifted.
_ROSTER_EXCLUSIONS = {
    "_ALWAYS_TRIGGER": "the parse-arming word list: shell tokens (`>`, "
                       "`delete`, `source`) beside program names that reach "
                       "the roster through the table that models them",
    "_BROAD_ADD": "git-add flags and pathspecs (`-u`, `./`, `:/`)",
    "_CONTROL_TOKENS": "shell operators that END a command (`;`, `&&`, `|`)",
    "_DEFERRED_EVAL": "shell constructs that evaluate text later (`$((`, "
                      "`eval`, `declare -i`)",
    "_FD_DIRS": "directories that hold file descriptors, not programs",
    "_FIND_FILTERS": "find's own name/path predicates",
    "_GIT_EQ_ONLY": "a git global option that only ever arrives attached",
    "_GIT_VALUED": "git's global options that consume a value",
    "_GROUP_OPENERS": "tokens that open a compound command",
    "_KDIR_SPELLINGS": "spellings of ONE directory, the kernel's own",
    "_NULL_SINKS": "character devices that accept a write and store nothing",
    "_PROGRAM_FLAGS": "the fallback flag whose argument is a program, not the "
                      "program",
    "_RESET_FLAGS": "the modes of `git reset`",
    "_ROSTER": "this partition's own left half",
    "_ROSTER_EXCLUSIONS": "this partition's own right half",
    "_SHELL_KEYWORDS": "reserved words and builtins: `printf` and `read` here "
                       "are the shell's, not the programs of the same name",
    "_STDIN_OPERANDS": "operands that name stdin (`-`, `/dev/stdin`)",
    "_STOP_WORDS": "reserved words that close or separate a command",
    "_SUBST_OPENERS": "the two process-substitution openers",
    "_TOP_PATHSPECS": "git pathspec magic that means the repository root",
    "_TRIGGERS": "DERIVED: the union of the tables above, built by "
                 "`_build_triggers`",
    "_WHOLE_TREE_SPECS": "pathspecs that mean the whole tree",
}


def _module_name_tables() -> dict:
    """Every `_`-prefixed module-level table of strings in THIS FILE, by name.

    The set of names comes from the module's own source and the value of each
    from the loaded module, which is what makes forgetting one impossible: a
    table added anywhere below is seen whether or not anybody remembered it, a
    DERIVED table (`_TRIGGERS`) is seen because its value is read rather than
    its literal, and a runtime cache that holds no strings is not seen at all.
    `ast` is imported here and not at module scope: this gate runs on every Bash
    call and only `--coverage` and the suite ever reach this function."""
    import ast
    with open(os.path.abspath(__file__), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    names = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        for target in targets:
            if (isinstance(target, ast.Name) and target.id.startswith("_")
                    and not target.id.startswith("__")):
                names.append(target.id)
    out, here = {}, globals()
    for name in names:
        members = _table_members(here.get(name))
        if members is not None:
            out[name] = members
    return out


def _table_members(value):
    """The strings a table holds, or None when it is not a table of strings.
    A dict contributes its KEYS: every dict in the roster is keyed by the
    program it models."""
    if isinstance(value, (str, bytes)) or not isinstance(
            value, (tuple, list, set, frozenset, dict)):
        return None
    members = list(value.keys()) if isinstance(value, dict) else list(value)
    if not members or not all(isinstance(m, str) for m in members):
        return None
    return members


def roster_partition() -> tuple:
    """(unclassified, stale) — both empty is the only passing state.

    UNCLASSIFIED: a table of strings this file defines that neither `_ROSTER`
    nor `_ROSTER_EXCLUSIONS` mentions, so the manifest under-reports it in
    silence. STALE: a name either one mentions that this file no longer
    defines, which is a reason left standing for a table that is gone."""
    tables = _module_name_tables()
    named = set(_ROSTER_EXCLUSIONS)
    for group in _ROSTER.values():
        named.update(group)
    return sorted(set(tables) - named), sorted(named - set(tables))


def coverage_manifest() -> str:
    """Every program and verb this file models, by the table that models it.

    The single source of truth for what the gate covers. Derived from the
    dispatch tables themselves AND from the set of tables this module defines,
    so it cannot drift from either: a row added without regenerating the block
    above fails the suite, and a TABLE added without classifying it fails
    here."""
    unclassified, stale = roster_partition()
    if unclassified or stale:
        raise AssertionError(
            "the coverage roster does not partition this module's tables. "
            "Unclassified (add to _ROSTER or _ROSTER_EXCLUSIONS with a stated "
            "reason): " + (", ".join(unclassified) or "none") + ". Stale "
            "(named but no longer defined): " + (", ".join(stale) or "none"))
    here, lines = globals(), []
    for label in sorted(_ROSTER):
        names = sorted({name for table in _ROSTER[label]
                        for name in (_table_members(here[table]) or [])})
        line = label + ":"
        for name in names:
            if len(line) + 1 + len(name) > 74:
                lines.append(line + " \\")
                line = ""
            line += (" " if line else "") + name
        lines.append(line)
    return "\n".join(lines) + "\n"


def _build_triggers() -> tuple:
    """Every word whose presence means this command is worth parsing.

    The union of the dispatch tables plus the handful of shell tokens that are
    not program names. Built once at import; `scan`'s fast path is a substring
    test over it."""
    words = set(_ALWAYS_TRIGGER)
    words.update(_MUTATORS)
    words.update(_STATE_VERBS)
    words.update(_OUTPUT_FLAGS)
    words.update(_CONSUMING)
    words.update(_POSITIONAL_OUTPUT)
    words.update(_COMMAND_STRING)
    words.update(_REMOTE_COPY_VERBS)
    words.update(("scp", "rsync"))
    return tuple(sorted(words))


def command_string_args(base: str, args: list) -> list:
    """The argument(s) of *base* that are a COMMAND LINE in a string.

    For a program with a named flag the value of that flag is the command; for
    the rest it is the first argument that is neither a flag nor the value of
    one, and only when it CONTAINS A SPACE, because `watch date` is a program
    name and `watch "rm -f x"` is a command line. That single test is what keeps
    this from re-reading every wrapper's program as a string."""
    named = _COMMAND_STRING.get(base)
    if named is None:
        return []
    out = []
    if named:
        for i, tok in enumerate(args):
            name, eq, val = tok.partition("=")
            if name in named:
                if eq and val:
                    out.append(val)
                elif i + 1 < len(args):
                    out.append(args[i + 1])
        return out
    valued = _COMMAND_STRING_VALUED.get(base, ())
    i = 0
    while i < len(args):
        tok = args[i]
        if tok.partition("=")[0] in valued:
            i += 1 if "=" in tok else 2
            continue
        if tok.startswith("-") and tok != "-":
            i += 1
            continue
        if " " in tok.strip():
            out.append(tok)
        break
    return out


def output_flag_targets(base: str, args: list) -> list:
    """Paths *base* writes because a FLAG of its own says so."""
    flags = _OUTPUT_FLAGS.get(base)
    if not flags:
        return []
    out = []
    for i, tok in enumerate(args):
        name, eq, val = tok.partition("=")
        if name in flags:
            if eq and val:
                out.append(val)
            elif i + 1 < len(args) and not args[i + 1].startswith("-"):
                out.append(args[i + 1])
        elif (len(tok) > 2 and tok.startswith("-") and not tok.startswith("--")
              and ("/" in tok or tok.startswith("~"))):
            # an attached short value, and a BUNDLE that ends in the flag:
            # `curl -so <path>` is `-s -o <path>`, `curl -o<path>` is attached
            for f in flags:
                if len(f) == 2 and f[1] in tok[1:]:
                    out.append(tok[tok.index(f[1]) + 1:] or "")
                    break
    for i, tok in enumerate(args):
        # the bundle whose value is the NEXT token: `curl -so <path>`
        if (tok.startswith("-") and not tok.startswith("--") and len(tok) > 2
                and "/" not in tok and i + 1 < len(args)
                and not args[i + 1].startswith("-")):
            for f in flags:
                if len(f) == 2 and tok.endswith(f[1]):
                    out.append(args[i + 1])
                    break
    return [t for t in out if t]


# ── A REMOTE RUNNER COPIES BOTH WAYS (QA cycle 15 blocker 3) ────────────────
#
# `_REMOTE_RUNNERS` is trusted as "not this filesystem", and that is true of the
# UPLOAD direction only. Measured writing a real lane: `aws s3 cp s3://b/k
# <lane>`, `docker cp c1:/etc/passwd <lane>`, `rclone copyto remote:x <lane>`
# and `scp host:/etc/passwd <lane>` — and `scp` was not even on the list.
#
# The rule is the DIRECTION, not the tool: when one operand names something
# remote (a `scheme://`, or a `host:`/`container:` prefix) and the LAST operand
# does not, the last one is a local destination. That reads `aws s3 cp <lane>
# s3://b/k` as the upload it is and leaves it alone.
_REMOTE_COPY_VERBS = ("cp", "copy", "copyto", "sync", "get", "download",
                      "fetch", "pull", "mv", "move")
# `scheme://…`, or `host:path` / `container:path`. Anchored and built from
# `[\w.-]`, which contains no separator, so an ordinary absolute or relative
# path can never match: `/tmp/x:y` fails at the leading `/` and `dir/f:x` at the
# `/` before the colon.
_REMOTE_MARK = re.compile(r"^(?:[a-zA-Z][\w+.-]*://|[\w.-]+:)")


def remote_copy_targets(base: str, args: list) -> list:
    """The LOCAL path a remote copy writes, or []. Empty for an upload."""
    if base not in ("scp", "rsync") and not any(
            a in _REMOTE_COPY_VERBS for a in args[:3]):
        return []
    positional = [a for a in args if not a.startswith("-")]
    positional = [a for a in positional if a not in _REMOTE_COPY_VERBS]
    if len(positional) < 2:
        return []
    if not any(_REMOTE_MARK.match(a) for a in positional[:-1]):
        return []                      # nothing remote: not this rule's shape
    last = positional[-1]
    return [] if _REMOTE_MARK.match(last) else [last]


def consuming_targets(base: str, args: list) -> list:
    """Paths *base* removes or replaces just by running. `gzip <lane>` leaves
    `<lane>.gz` and no `<lane>`; `zip -qm` and `tar --remove-files` delete what
    they packed."""
    if base in _CONSUMING:
        if any(a in _CONSUMING[base] for a in args):
            return []
        return _positional(base, args)
    if base == "zip" and _short_flag(args, "m", ("--move",)):
        return _positional(base, args)[1:]        # the archive is the first
    if base == "tar" and any(a == "--remove-files" for a in args):
        return _positional(base, args)
    return []


def mutation_targets(base: str, args: list) -> list:
    """Paths a non-git mutation writes. `cp` writes only its destination; `sed`
    writes nothing unless it is in-place."""
    positional = _positional(base, args)
    if base in ("rm", "mv", "tee", "unlink", "truncate"):
        return positional
    if base in ("cp", "install", "ln"):
        return _copy_targets(base, args, positional)
    if base == "sed":
        in_place = any(a == "-i" or (a.startswith("-i") and not a.startswith("--"))
                       or a.startswith("--in-place") for a in args)
        if not in_place:
            return []
        scripted = any(a in ("-e", "-f") or a.startswith(("--expression", "--file"))
                       for a in args)
        return positional if scripted else positional[1:]
    if base in ("touch", "chmod", "chattr"):
        # `chmod 644 f` / `chattr +i f`: the first positional is the mode, not a path
        return positional if base == "touch" else positional[1:]
    if base == "dd":
        return [a.split("=", 1)[1] for a in args if a.startswith("of=") and len(a) > 3]
    return []


_EXEC_MUTATORS = ("rm", "unlink", "shred", "truncate", "mv", "cp", "sed", "tee",
                  "install", "ln")
_FIND_FILTERS = ("-name", "-iname", "-path", "-ipath", "-wholename")


def find_targets(args: list) -> tuple:
    """(search roots, name filter or None) for a `find` that deletes.

    Only the token IMMEDIATELY after -exec/-execdir is the program being run:
    scanning the whole argument list for the word `rm` made
    `find pkg -exec grep rm {} \\;` look like a deletion. And a `find` carrying
    a -name/-path filter does not touch every file under its root, so the roots
    come back with that filter attached rather than as a bare directory."""
    exec_mutates = False
    for i, a in enumerate(args):
        # `-ok`/`-okdir` run exactly what `-exec`/`-execdir` run; the only
        # difference is a confirmation prompt, and a prompt is not a gate
        # (QA cycle 14 blocker 5: `-exec` denied, `-ok` allowed).
        if a in ("-exec", "-execdir", "-ok", "-okdir") and i + 1 < len(args):
            if os.path.basename(args[i + 1]) in _EXEC_MUTATORS:
                exec_mutates = True
    if "-delete" not in args and not exec_mutates:
        return [], None, False
    roots = []
    for a in args:
        if a.startswith("-") or a in ("(", ")", "!"):
            break
        roots.append(a)
    pattern, icase = None, False
    for i, a in enumerate(args):
        if a in _FIND_FILTERS and i + 1 < len(args):
            pattern, icase = args[i + 1], a in ("-iname", "-ipath")
            break
    return (roots or ["."]), pattern, icase


def is_release(tokens: list) -> bool:
    """`octo ... --release` in any invocation shape, interpreter prefix included."""
    toks = list(tokens)
    if toks and os.path.basename(toks[0]).split(".")[0] in ("python", "python3", "py"):
        j = 1
        while j < len(toks) and toks[j].startswith("-"):
            j += 1
        toks = toks[j:]
    if not toks:
        return False
    if os.path.basename(toks[0]) not in ("octo", "octo.py"):
        return False
    return any(a == "--release" or a.startswith("--release=") for a in toks[1:])


# git's VALUED global options. `-c key=val` is the one that mattered: skipping
# it as a plain flag left `key=val` looking like the subcommand, so
# `git -c commit.gpgsign=false checkout -- <lane>` parsed as a verb nobody
# guards. The borrowed _broad_git_verb has the same blind spot, which is why it
# is handed a NORMALIZED token list below instead of the raw one.
_GIT_VALUED = ("-c", "--config-env", "--namespace", "--super-prefix")
_GIT_EQ_ONLY = ("--exec-path",)


def git_parse(tokens: list):
    """(repo_or_None, subcommand, rest), honouring -C, --git-dir, --work-tree
    and every valued global; None when the tokens are not a git command."""
    i, repo = 1, None
    while i < len(tokens):
        tok = tokens[i]
        name, eq, val = tok.partition("=")
        if name == "-C":
            repo = val if eq else (tokens[i + 1] if i + 1 < len(tokens) else None)
            i += 1 if eq else 2
            continue
        if name in ("--git-dir", "--work-tree"):
            v = val if eq else (tokens[i + 1] if i + 1 < len(tokens) else "")
            repo = v[:-5] if v.endswith("/.git") else v
            i += 1 if eq else 2
            continue
        if name in _GIT_VALUED:
            i += 1 if eq else 2
            continue
        if name in _GIT_EQ_ONLY and eq:
            i += 1
            continue
        if tok.startswith("-"):
            i += 1
            continue
        break
    if i >= len(tokens):
        return None
    return repo, tokens[i], tokens[i + 1:]


def whole_tree_verb(sub: str, rest: list):
    """The verb name when this git subcommand rewrites the whole working tree."""
    if sub == "switch":
        return "git switch"
    if sub == "reset" and any(f in rest for f in _RESET_FLAGS):
        return "git reset " + next(f for f in _RESET_FLAGS if f in rest)
    if sub == "stash":
        first = next((a for a in rest if not a.startswith("-")), None)
        if first not in ("list", "show"):
            return "git stash"
    if sub == "clean":
        for a in rest:
            if a == "--force" or (a.startswith("-") and not a.startswith("--") and "f" in a):
                return "git clean -f"
    if sub == "worktree" and rest[:1] == ["remove"]:
        return "git worktree remove"
    # A bare `git checkout` prints state and changes nothing; only a checkout
    # that NAMES something switches the tree.
    if sub == "checkout" and "--" not in rest \
            and any(not a.startswith("-") for a in rest):
        return "git checkout <branch>"
    return None


_PATHSPEC_VERBS = ("checkout", "restore", "rm", "mv")


def pathspecs(sub: str, rest: list, base_dir: str) -> list:
    """The paths a pathspec verb rewrites. After `--` every argument is a path;
    without it, only arguments that exist on disk are (so `git checkout main`
    stays a branch switch and is handled as a whole-tree verb instead)."""
    if sub not in _PATHSPEC_VERBS:
        return []
    if "--" in rest:
        return [a for a in rest[rest.index("--") + 1:]]
    args = [a for a in rest if not a.startswith("-")]
    if sub in ("restore", "rm", "mv"):
        return args
    out = []
    for a in args:
        probe = expand_home(a)
        probe = probe if os.path.isabs(probe) else os.path.join(base_dir, probe)
        if os.path.exists(probe) or _is_glob(a):
            out.append(a)
    return out


_MAGIC = "*?["
_TOP_PATHSPECS = (":/", ":(top)", ":(top,glob)", ":(icase)")


def _is_glob(spec: str) -> bool:
    return any(c in spec for c in _MAGIC)


_WHOLE_TREE_SPECS = ("*", "./*", ".", "./")


def spec_target(spec: str, base_dir: str) -> tuple:
    """('path', dir) when the spec can only act inside a literal directory;
    ('glob', pattern) when it cannot.

    `pkg/*.py` reduces to `pkg`, which prefix-matches every lane under it, so a
    glob cannot walk past the lane test by never naming a lane literally. But a
    spec whose FIRST component is already a glob (`*.log`, `zz*`) has no literal
    directory, and reducing it to the tree root denied `rm -f *.log` under any
    live sibling lane: a false deny on a command that touches nothing anyone
    owns. Those are matched with fnmatch against each lane instead. Only the
    specs that really do mean everything (`*`, `./*`, `.`, `:/`, `:(top)`) keep
    the root."""
    spec = spec.strip()
    if spec in _TOP_PATHSPECS or spec in _WHOLE_TREE_SPECS:
        return "path", base_dir
    if spec.startswith(":"):
        close = spec.find(")")
        spec = spec[close + 1:] if spec.startswith(":(") and close != -1 else spec.lstrip(":")
        if not spec:
            return "path", base_dir
        if spec in _WHOLE_TREE_SPECS:
            return "path", base_dir
    spec = expand_home(spec)
    if not _is_glob(spec):
        return "path", resolve(spec, base_dir)
    keep = []
    # A shell path uses `/` on every platform, and on Windows `os.sep` is `\`,
    # so splitting on os.sep alone leaves `pkg/*.py` as ONE part: the whole
    # spec then reads as a glob with no literal directory to reduce to, and the
    # prefix test that should have named `pkg` never runs.
    for part in spec.replace("/", os.sep).split(os.sep):
        if _is_glob(part):
            break
        keep.append(part)
    literal = os.sep.join(keep)
    if literal:
        return "path", resolve(literal, base_dir)
    return "glob", (spec if os.path.isabs(spec) else os.path.join(base_dir, spec))


def glob_hits(pattern: str, lane: str, icase: bool = False) -> bool:
    """Does this glob reach a lane, or any directory on its way? fnmatch's `*`
    spans separators, so a lane deeper than the pattern still matches; the
    ancestor walk covers the reverse, a pattern naming a directory the lane
    lives in. `icase` is `find -iname/-ipath`: the filter that matched a.py
    while the command said A.PY."""
    import fnmatch
    # The pattern comes from a shell command and separates with `/`; the lane
    # comes from the process table, already normalized to `os.sep`. Match them
    # in one alphabet or a Windows lane never matches a `*/a.py` pattern.
    if os.sep != "/":
        pattern = pattern.replace("/", os.sep)
    if icase:
        pattern, lane = pattern.lower(), lane.lower()
    if fnmatch.fnmatchcase(lane, pattern):
        return True
    node = lane
    while True:
        parent = os.path.dirname(node)
        if parent == node:
            return False
        if fnmatch.fnmatchcase(parent, pattern):
            return True
        node = parent


# ── scan ────────────────────────────────────────────────────────────────────

# THE TRIGGER WAS THE LAST VERB ALLOW-LIST IN THIS FILE (QA cycle 14). It was
# hand-written and it drifted from the tables the scan dispatches on, so a
# program could be fully modelled below and never reach the model: `curl -so
# <lane> URL` and `gzip <lane>` were parsed correctly by their own helpers and
# `scan` returned [] before calling either, because neither word was on this
# list. That is cycle 9's finding one more level up — the floor stopped being a
# verb list, then the parser did, and the FAST PATH in front of both still was.
#
# So it is DERIVED, not written. Every table the dispatch reads contributes its
# own keys, which makes drift impossible by construction rather than by review:
# adding a program to `_OUTPUT_FLAGS` or `_CONSUMING` arms the trigger for it in
# the same edit. `test_c14_every_dispatch_table_is_a_trigger` asserts the
# equality so a future table added without this line fails.
# Heads with a HAND-WRITTEN parser instead of a name table: `git_parse` reads
# one and the `--release` rule reads the other. They are modelled, so the
# roster reports them, and they arm the trigger through `_ALWAYS_TRIGGER`.
_PARSED_HEADS = ("git", "octo")
_ALWAYS_TRIGGER = (">", "find", "delete", "xargs", "source") + _PARSED_HEADS
_C_HOSTS = ("bash", "sh", "zsh", "dash", "python", "python3", "py")
_MUTATORS = ("rm", "mv", "cp", "sed", "tee", "unlink", "truncate", "install",
             "ln", "dd")
# Verbs that can damage the kernel's ledger without being a lane write. They are
# tested against the state floor ONLY, never against a lane: `touch`/`chmod` on
# a sibling's file is not the collision this rule is about.
# QA cycle 15 blocker 3: `dd` was here on the reasoning that these verbs never
# write a LANE. `touch` and `chmod` do not destroy content; `dd if=/dev/zero
# of=<lane>` does, so `dd` moved to `_MUTATORS` and this list holds only the
# three the reasoning is actually true of.
_STATE_VERBS = ("touch", "chmod", "chattr")

# ── the kernel floor is a NAMED-PATH floor, not a verb list ──────────────────
#
# QA CYCLE 9 F1. The floor above was an ALLOWLIST OF VERBS, and an allowlist of
# verbs loses to the next verb. Measured on this file at HEAD~1: `rm`, `mv`,
# `truncate` and `unlink` denied, while `mkfifo`, `ln -sf`, `shred -u`,
# `install` and `busybox rm` all passed undecided. So
# `mkfifo $HOME/bf && ln -sf $HOME/bf <kernel>/journal/<holder>.jsonl` was
# allowed, and from then on every tree-owner gate blocked inside `open()`, was
# killed at the harness `timeout: 5`, wrote no stdout and emitted no decision -
# which every matrix in this PR reads as ALLOW. `kernel_proc._kernel_fd` closes
# the hang; this closes the move that creates it.
#
# THE HEADER OF THIS FILE ARGUED THE OTHER WAY AND THE ARGUMENT IS REFUTED, so
# it is corrected rather than left standing. It said effect recognition "stays a
# named residual" because "after C-A neither form transfers a lane any more (an
# unreadable record is UNKNOWN and unknown holds)". That holds for a record the
# reader can READ AND REJECT. A fifo is not an unreadable record, it is a reader
# that never returns, and a hook that never returns is not UNKNOWN, it is no
# decision at all.
#
# SO THE FLOOR IS INVERTED: any segment that NAMES a path inside the kernel
# directory is denied unless the path is a plain OPERAND of a program on the
# short list below. The set of verbs that can create, replace or unlink a path
# is open-ended. The set that provably cannot is NOT "small, nameable and
# closed" — that sentence stood here for four cycles and QA cycle 14 refuted it
# by running three members of the list: `sort -o`, `uniq`'s second positional
# and `less --log-file` all write, and all three were on it. What is closed is
# the POSITION, not the program: a path handed to a flag is a write whatever the
# program is called, and that half of the test now runs on every program
# including this list.
#
# THE OVER-FIRE IS REAL AND IT IS THE PRICE, stated rather than discovered: a
# READ of kernel state through a tool that is not on this list is denied too
# (`xxd ptable.json`, `python3 -c "print(open(p).read())"`). The deny names the
# path and the operator's terminal is not hooked, so the cost is one message and
# a `cat`, against a wedged session for the other direction.
# QA CYCLE 14 / BLOCKER 1. The header used to say this list was "the set of
# programs that provably cannot create, replace or unlink a path", and that
# sentence was FALSE. Measured on this host:
#
#   sort -o /tmp/qaf /etc/hostname      wrote 11 bytes
#   uniq /etc/hostname /tmp/qaf         wrote 11 bytes      (a POSITIONAL write)
#   less --log-file=<kdir>/ptable.json  writes the log
#
# and all three ALLOWED at the gate while `curl -so <kdir>/ptable.json` and
# `gzip <kdir>/ptable.json` denied. The floor worked for every program NOT on
# the list, so the list WAS the hole: it is the third time on this stack that an
# allow-list of "safe" things turned out to be the attack surface.
#
# WHAT THE LIST MEANS NOW, and it is a narrower claim that can actually be
# checked: these are programs whose POSITIONAL OPERANDS ARE INPUTS. It is not a
# claim that they cannot write. The write positions are covered separately and
# by POSITION rather than by name:
#
#   * a kernel path attached to a FLAG (`--log-file=<kdir>/x`, `-o<kdir>/x`) is
#     denied on EVERY program, this list included — `names_kernel_state` reads
#     the value half of a flag token, which it used to skip whole because the
#     token started with `-`;
#   * `sort`, `less` and `more` are OFF the list, because a flag of theirs takes
#     an output FILE, and `uniq` is off because its SECOND POSITIONAL is an
#     output. The cost is a false deny on `sort <kdir>/x` and `less <kdir>/x`,
#     which are reads nobody on this machine performs, and it fails toward deny.
#
# `test_c14_no_readonly_member_takes_an_output_file` re-runs the screen that
# found `sort` and `less` (a `--help` probe for output-file flags) so a member
# added later without that check fails. THE SCREEN CANNOT PROVE THE NEGATIVE and
# the test says so: it reads FLAGS, and `uniq`'s write is a POSITIONAL, which is
# exactly the member the screen missed and a human found by running it.
_KSTATE_READONLY = (
    "cat", "head", "tail", "ls", "stat", "file", "wc",
    "grep", "egrep", "fgrep", "rg", "cut", "diff", "cmp",
    "du", "df", "md5sum", "sha1sum", "sha256sum", "b2sum", "cksum", "base64",
    "od", "strings", "jq", "readlink", "realpath", "basename", "dirname",
    "echo", "printf", "test", "true", "false", "pwd", "which", "wait", "date",
    "cd", "pushd", "popd",
)
# Programs that take CODE as an argument. For these the token scan is blind by
# construction: the path lives inside a quoted program, not in a token, which is
# exactly the interpreter hole the header names. They are matched on the raw
# SEGMENT TEXT instead, and the over-fire is the same one, one step wider: a
# read-only one-liner that merely mentions the path is denied.
_CODE_HOSTS = ("bash", "sh", "zsh", "dash", "ksh", "python", "python3", "py",
               "perl", "ruby", "node", "deno", "bun", "php", "awk", "gawk",
               "mawk", "sed", "tclsh", "lua", "Rscript")
# How the kernel directory can be SPELLED in a command. The absolute form comes
# from `kernel_proc.kernel_dir()`; these cover the spellings a shell would have
# expanded and the parser never does.
_KDIR_SPELLINGS = ("~/.claude/.cache/kernel", "$HOME/.claude/.cache/kernel",
                   "${HOME}/.claude/.cache/kernel", ".claude/.cache/kernel")


def flag_values_naming_kernel_state(tokens: list, here: str, kdir: str) -> list:
    """Every FLAG VALUE of one segment that resolves inside `kdir`.

    Split out of `names_kernel_state` in QA cycle 14 so the read-only branch of
    the floor can run it too: the list exempts a program's OPERANDS, never its
    flags. Both the attached long form (`--log-file=<kdir>/x`) and the attached
    short form (`-o<kdir>/x`) are read; a detached value (`-o <kdir>/x`) lands
    in the operand scan of `names_kernel_state`, where it is a bare token."""
    out = []
    for tok in tokens:
        if not tok or not tok.startswith("-") or tok == "--":
            continue
        value = tok.partition("=")[2]
        if not value:
            stripped = tok.lstrip("-")
            value = stripped if ("/" in stripped or
                                 stripped.startswith(("~", "$HOME"))) else ""
        if not value:
            continue
        try:
            target = resolve(value, here)
        except Exception:
            continue
        if kernel_proc.paths_conflict(target, kdir):
            out.append(target)
    return out


def names_kernel_state(tokens: list, here: str, kdir: str) -> list:
    """Every token of one segment that RESOLVES to a path inside `kdir`.

    Env-assignment VALUES are scanned too (`K=~/.claude/.cache/kernel` in one
    segment and `rm $K/journal/x` in the next is one move, and the second
    segment carries no path a parser can resolve), and so is the token that
    names the program, because `/usr/bin/env` style invocation is already peeled
    and what is left may itself be the target.
    """
    out = []
    for tok in tokens:
        if not tok:
            continue
        if tok.startswith("-"):
            continue          # handled by `flag_values_naming_kernel_state`
        for cand in (tok, tok.partition("=")[2]):
            if not cand:
                continue
            try:
                target = resolve(cand, here)
            except Exception:
                continue
            if kernel_proc.paths_conflict(target, kdir):
                out.append(target)
                break
    return out


def code_names_kernel_state(seg: str, kdir: str) -> bool:
    """True when a segment's raw text spells the kernel directory. Used only for
    the interpreter hosts, where the path is inside a quoted program."""
    if kdir and kdir in seg:
        return True
    return any(spell in seg for spell in _KDIR_SPELLINGS)
# ── the heredoc is a COMMAND CHANNEL WITH NO FLAG (QA cycle 11) ─────────────
#
# The floor above was described as closed while the dominant idiom on this
# machine was open. Measured over the harness transcripts: of 16350 distinct
# real Bash commands, 3186 carry a heredoc and 3601 carry a `-c`. Both gates
# covered `-c`. Neither covered the heredoc, and the interpreter half of the
# floor looks for a FLAG whose argument is the program:
#
#     python3 -c "open('<kdir>/journal/x.jsonl','a').write('x')"   denied
#     python3 -  <<'EOF' ... same body ... EOF                     ALLOWED
#     python3    <<'EOF' ... same body ... EOF                     ALLOWED
#
# With `python3 - <<EOF` the program arrives on STDIN and there is no flag to
# find, so `code_names_kernel_state` was handed an opening line that names
# nothing and the body was split into "segments" that tokenize to noise. Same
# effect, same directory, different channel.
#
# THE BODY IS SPLIT OFF BEFORE ANYTHING ELSE IS PARSED, which fixes the hole in
# both directions at once. A heredoc body is DATA unless the command it feeds
# reads its PROGRAM from stdin, and scanning data as if it were a command is an
# over-fire that was already live here: `cat > notes.md <<'EOF'` whose prose
# said `rm -rf pkg/` had that line split out as a segment and read as a
# deletion. Bodies now go back to the command that receives them, and only
# there.
#
# `stdin_is_program` is the test, and it is a POSITION test rather than a name
# test: an interpreter with no operand, or with `-` or `/dev/stdin` as its
# operand, runs what arrives on stdin (`python3 <<EOF`, `bash -s <<EOF`,
# `cat <<EOF | python3 -`). One carrying `-c`/`-m`/`-e`, or a script file, does
# not: there the program is elsewhere and the body is its input.
#
# Here-strings and process substitutions are the same channel wearing other
# syntax and are lifted from the merge gate's `_stdin_channel_texts` rather
# than rediscovered: `bash <<< "rm -rf <lane>"` hands a command to a shell, and
# `<(...)`/`>(...)` is a command by construction whatever the outer program is.
#
# ── QA CYCLE 12: the four ways a body was still reached, and the class ───────
#
# Cycle 11 closed ONE spelling of the heredoc and the matrix then read the rest
# of the class as closed with it. It was not. Five findings, and four of them
# live inside the channel cycle 11 had just claimed:
#
#   C2  `cat <<EOF` with `$(rm -f <kdir>/ptable.json)` in the body. An UNQUOTED
#       terminator means BASH expands the body before anything receives it, so
#       the body is a command channel whoever the receiver is; only a QUOTED
#       terminator (`<<'EOF'`, `<<"EOF"`, `<<\EOF`) makes it literal. The old
#       pattern captured the quote character and then dropped it.
#   C3  a decoy line of `"  EOF"` closed the parse early because the terminator
#       match was `.strip()`. Bash requires the line to EQUAL the delimiter;
#       only `<<-` strips, and only leading TABS.
#   C4  the delimiter charset was `['"]?[A-Za-z_][\w.-]*`, so `<<\EOF`,
#       `<<'1EOF'` and `<<'E!'` were not heredocs at all to this parser.
#   C5  `( python3 - <<'EOF' … )`: the host read was `shlex.split(...)[0]`,
#       which is `(`, so the receiver came back empty and the body was dropped.
#
# THE CLASS, ENUMERATED, because closing one member and calling the class done
# is the failure this PR chain has now repeated three times (verb, then path,
# then flag). A heredoc redirection in bash is:
#
#   operator      `<<`  or  `<<-` (the dash strips leading TABS from every body
#                 line AND from the terminator line, nothing else);
#   spacing       blanks are allowed between the operator and the delimiter
#                 (`cat << EOF`);
#   delimiter     any WORD: bare (`EOF`, `END1`, `_x`, `a.b-c`), single-quoted
#                 (`'EOF'`, `'1EOF'`, `'E!'`, `'a b'` — a delimiter may contain
#                 a space when quoted), double-quoted (`"EOF"`),
#                 backslash-escaped (`\EOF`), or PARTIALLY quoted (`E'OF'`,
#                 `"E"OF`);
#   quoting       the body is LITERAL when any character of the delimiter was
#                 quoted or escaped, and EXPANDED otherwise. That is the whole
#                 rule, and it is per delimiter, not per quote style;
#   terminator    a line equal to the delimiter, exactly, with no leading or
#                 trailing whitespace (`<<-` allows leading tabs);
#   neighbours    `<<<` is a HERE-STRING, a different operator, and `<` is a
#                 file redirect; several heredocs may open on one line and
#                 their bodies follow in the order the delimiters appear.
#
# `_heredoc_ops` implements exactly that list, quote-aware so a `<<` inside an
# ordinary quoted argument is not an operator, and `split_heredocs` matches the
# terminator by equality (tab-stripped only for `<<-`). The "no terminator line
# means it was never a heredoc" rule stays: it is what keeps `echo "a << b"`
# from swallowing the rest of the command.
#
# RESIDUAL, stated: `<<` inside an ARITHMETIC context (`$(( 1 << 2 ))`) is read
# as an operator here, so a later line equal to `2` would be eaten as a body.
# It costs coverage, never a false deny, and no real command on this host has
# the shape.
#
# ── QA CYCLE 12 / C1: command substitution is a command ─────────────────────
#
# `$(...)` and backticks were never parsed as commands anywhere in this file.
# They were caught only INCIDENTALLY, when a literal kernel path survived
# tokenization as a bare token and the outer verb was not read-only, which is
# why `x=$(rm -f <kdir>/ptable.json)` denied while `echo $(python3 -c "…")`,
# `true $(rm -f …)` and `` echo `…` `` all sailed through: `echo` is on the
# read-only list, so the token scan never ran, and an interpreter that COMPUTES
# the path leaves no literal to find.
#
# THE CLASS, ENUMERATED. Every construct in bash that runs a command inside a
# word, and what this parser does with each:
#
#   `$(cmd)`        command substitution, nestable      SCANNED as a command
#   `` `cmd` ``     legacy form, nests via `` \` ``     SCANNED as a command
#   `<(cmd)`        process substitution (input)        SCANNED (since cycle 11)
#   `>(cmd)`        process substitution (output)       SCANNED (since cycle 11)
#   `$(<file)`      bash's file-read fast path          scanned; runs no command
#   `$((expr))`     ARITHMETIC                          SCANNED INSIDE (see the
#   `$[expr]`       the removed spelling of it          correction below)
#   `(( expr ))`    the arithmetic COMMAND
#   `let "expr"`    the builtin form
#   `${ cmd; }`     ksh93/bash-5.3 value substitution   RESIDUAL: this host runs
#                   `${| cmd; }`                        bash 5.2.21, which
#                                                       rejects it outright
#
# ── QA CYCLE 13 / THE CORRECTION: THAT LINE WAS FALSE ABOUT BASH ────────────
#
# Cycle 12 wrote "`$((expr))` ARITHMETIC, not a command, left verbatim on
# purpose" and the enumeration made it look checked. It is wrong. Bash performs
# COMMAND SUBSTITUTION on an arithmetic expression before evaluating it, so
# every arithmetic context is an ordinary word context. Measured on bash
# 5.2.21, each of these removes its file:
#
#   echo $(( $(rm -f a; echo 1) ))        x=$((`rm -f b; echo 2`))
#   (( $(rm -f c; echo 3) ))              echo $[ $(rm -f d; echo 1) ]
#
# So `split_command_substitutions` copies the `$((` through — the arithmetic
# itself runs nothing — and CONTINUES SCANNING INSIDE IT. `(( … ))` and `$[ … ]`
# needed no special case once that was true: they are plain characters this
# scanner walks past, and the `$(` inside them is masked like any other.
#
# THE SHAPE OF THIS MISS IS THE FINDING. Cycle 12's answer to "the class was
# not closed" was to ENUMERATE the class, and the enumeration became the new
# place to be wrong: a table of eight rows, seven right and one a false
# statement about the shell, presented with the authority of a list. The
# convergence test could not see it either, because its corpus held
# `echo $((1 << 3))` — an arithmetic expression with nothing inside it to
# disagree about — so the two implementations disagreed on four shapes while
# the test ran green. A convergence corpus that avoids the divergence is the
# same shape as a fixture set that avoids the bug, and
# `SharedParserConvergence.CORPUS` now carries `echo $(( $(c) ))`,
# `echo $(( $(rm -f /x) ))`, `x=$((`b`))` and `echo $(( 1 + $(a) ))`, all four
# measured RED against the provider at e0f9444 before the fix and green after.
#
# STATED OVER-FIRE, one line wide: a `#` COMMENT is not stripped anywhere in
# this parser, so a substitution written inside one is read as the command it
# textually is. `echo hi  # $(rm -rf pkg/)` is denied on a line that runs
# nothing. It fails toward DENY, which is the correct direction here and the
# same direction the `-c` raw-text rule has always failed in.
#
# POSITIONS, also enumerated, because a substitution is a WORD construct and
# every word position is therefore a channel: an ordinary argument, the RHS of
# an assignment (`x=$(…)`), a REDIRECT TARGET (`echo hi > $(echo <kdir>)/p`),
# the word of a here-string, the body of an UNQUOTED heredoc (C2 above), and
# anywhere inside DOUBLE quotes. Not inside single quotes and not in a quoted
# heredoc body, where the text is literal and nothing runs.
#
# `split_command_substitutions` masks each one with an opaque marker and hands
# back the bodies, which buys three things at once:
#   1. the body is scanned as a command, with the cwd of the segment it sits in;
#   2. the outer command still tokenizes, and a body containing `;` or `|` can
#      no longer tear the outer command apart at `_split_subcmds` (the splitter
#      tracks `(` depth, so `$(a; b)` survived, but `` `a; b` `` did not);
#   3. a token that CONTAINS a marker is opaque, which is the honest answer for
#      `echo hi > $(echo <kdir>)/ptable.json`: the destination is computed by a
#      command this gate does not run, so the raw-text kernel floor is applied
#      to the body TEXT instead, and a substitution that spells the kernel
#      directory cannot be laundered through a write target.
# The deliberate opaque-token behaviour for a verb that COMES FROM a
# substitution (`$(echo rm) -f x`) is unchanged: the marker is not a read-only
# program either, so the token scan still runs over the segment.
#
# WHERE THIS BELONGS, and it is NOT here. `qa-merge-gate.py` is the PROVIDER of
# the command-boundary parser for this brain (`receipt_ledger._qa_gate_helpers()`
# borrows `_split_subcmds` and `_strip_leading` from it; this file borrows its
# splitter from `dimension-awareness-hook.py` and `_stdin_channel_texts` from
# that gate in cycle 11), so the AUTHORITY on "what is a command substitution"
# is `qa-merge-gate._command_substitution_texts`, which landed on
# `fix/qa-gate-blanket-override` at e0f9444 while this cycle was being written.
# An import the other way would close a cycle through a module that
# `exec_module`s this one.
#
# What is here is not a second copy of that rule, it is the SPANS the rule
# implies, and the difference is load-bearing. A texts-only extractor discards
# WHERE each substitution was, and points 2 and 3 above both need the position:
# the outer command has to keep tokenizing with the substitution as one token,
# and a computed write target has to be recognizable as opaque. The body half of
# the two is one function call apart —
# `list(split_command_substitutions(t)[1].values())` is exactly
# `_command_substitution_texts(t)` — and
# `SharedParserConvergence.test_the_substitution_rule_has_one_authority` asserts
# that equality over a corpus, SKIPPING with a named reason on a base where the
# provider does not carry the function yet and arming itself the moment it does.
#
# IT SKIPS ON THIS BASE, and that has to be said out loud because it is easy to
# read the wrong way (QA cycle 15). Every "convergence N/N" figure in this PR's
# reports is a HARNESS number: it was measured by loading the provider out of
# the sibling branch by hand. The assertion is NOT exercised where it ships, so
# the honest reading of a green suite here is "this one did not run".
# `qa-merge-gate.py` gains `_command_substitution_texts` on
# `fix/qa-gate-blanket-override`, which has now been through its own cycle 10
# and carries the function; this test arms itself when that merges.
# 18/18 agreement measured by hand against e0f9444. This gate takes no runtime import of
# an unmerged branch: an import that silently fails open would disable C1 until
# the sibling merged, which is the worst of both.
#
# `>(…)` is the one member the two split differently on purpose: the merge gate
# returns it from `_command_substitution_texts`, this file leaves it to
# `stdin_channel_texts` where `<(…)` already lives, so the convergence corpus is
# the `$(…)` and backtick class.
_SUBST_OPENERS = ("<(", ">(")
# Characters that END an unquoted word. Bash's own metacharacter set, which is
# what decides where a heredoc delimiter stops.
_WORD_ENDS = " \t\n;|&<>()"


def _read_word(text: str, i: int) -> tuple:
    """(word, quoted, index just past it) reading one shell WORD at *text*[i].

    `quoted` is True when ANY character of the word was quoted or escaped,
    which is bash's own rule for whether a heredoc body expands. Partial
    quoting counts, so `E'OF'` yields ("EOF", True).
    """
    out, quoted, n = [], False, len(text)
    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n:
            out.append(text[i + 1])
            quoted = True
            i += 2
            continue
        if c == "'":
            j = text.find("'", i + 1)
            if j < 0:
                out.append(text[i + 1:])
                return "".join(out), True, n
            out.append(text[i + 1:j])
            quoted = True
            i = j + 1
            continue
        if c == '"':
            j, buf = i + 1, []
            while j < n and text[j] != '"':
                if text[j] == "\\" and j + 1 < n:
                    buf.append(text[j + 1])
                    j += 2
                    continue
                buf.append(text[j])
                j += 1
            out.append("".join(buf))
            quoted = True
            i = min(j + 1, n)
            continue
        if c in _WORD_ENDS:
            break
        out.append(c)
        i += 1
    return "".join(out), quoted, i


def _heredoc_fd(line: str, at: int) -> int:
    """The descriptor the `<<` at *line*[at] feeds. 0 unless digits immediately
    precede the operator, which is bash's own rule: `3<<EOF` opens fd 3 and
    `python3 /dev/fd/3 3<<'EOF'` is the shape QA cycle 13 measured allowing.
    The digits must start a word, so `foo3<<EOF` is a word and a heredoc on
    stdin rather than a redirection of fd 3."""
    j = at
    while j > 0 and line[j - 1].isdigit():
        j -= 1
    if j == at:
        return 0
    if j > 0 and line[j - 1] not in _WORD_ENDS:
        return 0
    try:
        return int(line[j:at])
    except ValueError:
        return 0


def _heredoc_ops(line: str) -> list:
    """[(delimiter, quoted, tabstrip, fd)] for every heredoc *line* opens.

    Quote-aware, so `echo "a <<EOF b"` opens nothing: an operator inside an
    ordinary quoted argument is text. `<<<` is skipped explicitly because it is
    a here-string, handled by `stdin_channel_texts`. The FD is the fourth
    element since QA cycle 13: a heredoc feeds a descriptor, and the program
    that runs it is the one whose operand names THAT descriptor, not always 0.
    """
    if "<<" not in line:
        return []                    # the C-level test that keeps a 20000-line
    ops, i, n = [], 0, len(line)     # DATA body off this char loop entirely
    in_sq = in_dq = False
    while i < n:
        c = line[i]
        if in_sq:
            if c == "'":
                in_sq = False
            i += 1
            continue
        if in_dq:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_dq = False
                i += 1
                continue
            # `<<` cannot open a heredoc inside a double-quoted word either
            i += 1
            continue
        if c == "\\":
            i += 2
            continue
        if c == "'":
            in_sq = True
            i += 1
            continue
        if c == '"':
            in_dq = True
            i += 1
            continue
        if line.startswith("<<<", i):
            i += 3
            continue
        if line.startswith("<<", i):
            j = i + 2
            tabstrip = False
            if j < n and line[j] == "-":
                tabstrip = True
                j += 1
            while j < n and line[j] in " \t":
                j += 1
            word, quoted, j = _read_word(line, j)
            if word:
                ops.append((word, quoted, tabstrip, _heredoc_fd(line, i)))
                i = j
            else:
                i += 2
            continue
        i += 1
    return ops


def _terminator_index(lines: list) -> tuple:
    """({exact line: [indices]}, {tab-stripped line: [indices]}).

    Built once per command instead of re-walking the tail for every `<<`. The
    old spelling was a nested loop, so a command carrying many openers and no
    terminators cost O(lines^2) — the parse-cost cliff from the other side.
    """
    exact, detabbed = {}, {}
    for j, line in enumerate(lines):
        exact.setdefault(line, []).append(j)
        stripped = line.lstrip("\t")
        if stripped != line:
            detabbed.setdefault(stripped, []).append(j)
    return exact, detabbed


def _find_terminator(index, term: str, tabstrip: bool, start: int):
    """The first line at or after *start* that CLOSES a heredoc on *term*.

    Bash wants the line to equal the delimiter exactly. `<<-` strips leading
    TABS (only tabs, only leading) from body lines and from this one, so the
    tab-stripped view is consulted for that operator and for no other. QA cycle
    12 C3: the old test was `lines[j].strip() == term`, so a decoy line of
    `"  EOF"` closed the parse here while bash kept the body open, and every
    command after the decoy was read as data.
    """
    exact, detabbed = index
    hits = exact.get(term) or []
    if tabstrip:
        hits = sorted(set(hits) | set(detabbed.get(term) or []))
    for j in hits:
        if j >= start:
            return j
    return None


def split_heredocs(cmd: str, budget: list = None) -> tuple:
    """(*cmd* with heredoc BODIES removed, [(opening_line, body, quoted, fd)]).

    `quoted` is the third element since QA cycle 12 C2: an UNQUOTED terminator
    means bash expands `$(...)` and backticks in the body before any command
    receives it, so the body is a command channel whatever the receiver is.
    The old pattern captured the quote character and then ignored it. `fd` is
    the fourth since cycle 13, so a body can be paired with the operand that
    reads it.

    A MISSING TERMINATOR IS STILL A HEREDOC (QA cycle 13). Bash warns
    ("here-document delimited by end-of-file") and runs the body anyway, so the
    old `continue` — "no terminator: not a heredoc" — handed the body to the
    command splitter, where a body destined for an interpreter was read as a
    list of shell words instead of as the program it is. One byte cheaper than
    the decoy closed in cycle 12 C3, and in the opposite direction. The rest of
    the input IS the body, which is exactly what bash does with it; the quote
    awareness added in C3 is what makes that safe, because `echo "a << b"` no
    longer opens anything for it to swallow.
    """
    if "<<" not in cmd:
        return cmd, []
    lines = cmd.split("\n")
    index = None
    kept, bodies, i = [], [], 0
    while i < len(lines):
        line = lines[i]
        kept.append(line)
        i += 1
        # THE CHAR LOOP IS THE COST, so it is charged before it runs and only
        # for the lines that actually enter it. A 4 MB data body costs nothing
        # here: it is skipped whole by `i = end + 1` and never reaches this.
        if "<<" in line:
            _spend_chars(budget, len(line))
        for term, quoted, tabstrip, fd in _heredoc_ops(line):
            # An OPENER is a sub-command's worth of parsing too, and a command
            # made of nothing but openers is the cheapest way to buy this loop
            # (QA cycle 12 C8): 200000 of them cost 17 s before the charge.
            if budget is not None:
                budget[0] -= 1
                if budget[0] < 0:
                    raise ParseTooLarge(
                        f"more than {_MAX_SEGMENTS} sub-commands to parse")
            if index is None:
                # built on the FIRST opener, never for a command that only
                # mentions `<<` inside a quoted argument
                index = _terminator_index(lines)
            end = _find_terminator(index, term, tabstrip, i)
            if end is None:
                end = len(lines)             # bash: end of input closes it
            bodies.append((line, "\n".join(lines[i:end]), quoted, fd))
            i = min(end + 1, len(lines))
    return "\n".join(kept), bodies


def _claim_heredocs(seg: str, pending: dict) -> list:
    """The (opening_line, body, quoted, fd) records *seg* opens, removed from
    *pending*.

    A sub-command claims a body by naming its terminator, which is how a body
    gets back the cwd of the line it belongs to. Bodies nothing claims stay in
    *pending* and are drained by the caller against the starting cwd.
    """
    out = []
    if not pending or "<<" not in seg:
        return out
    for term, _quoted, _tabstrip, _fd in _heredoc_ops(seg):
        items = pending.get(term)
        if items:
            out.append(items.pop(0))
            if not items:
                pending.pop(term, None)
    return out


# The marker a masked command substitution leaves behind. Plain identifier
# characters so `shlex` keeps it as one token and `os.path.join` treats it as an
# ordinary path component.
_SUBST_MARK = "__OCTOSUBST"


def _match_paren(text: str, k: int) -> int:
    """Index just past the `)` that closes the `(` at *text*[k], quotes
    respected. An unterminated substitution returns the end of the text, so its
    body is the rest of the command rather than nothing."""
    depth, i, n = 0, k, len(text)
    in_sq = in_dq = False
    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n:
            i += 2
            continue
        if in_sq:
            if c == "'":
                in_sq = False
            i += 1
            continue
        if in_dq:
            if c == '"':
                in_dq = False
            i += 1
            continue
        if c == "'":
            in_sq = True
        elif c == '"':
            in_dq = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def split_command_substitutions(text: str) -> tuple:
    """(*text* with every COMMAND SUBSTITUTION masked, {marker: body}).

    QA cycle 12 C1. See the enumeration above for what counts: `$(...)` and
    backticks are masked and their bodies handed back; single-quoted text is
    literal and is copied through as-is; double-quoted text still expands, so it
    is scanned. `$((...))` has its OPENER copied and its inside SCANNED, because
    arithmetic is evaluated after expansion — QA cycle 14 caught this docstring
    still saying "copied through verbatim", which is what the code did before
    cycle 13 and not what it does now.

    Contract note for the convergence with `qa-merge-gate.py`: a texts-only
    extractor is exactly `list(split_command_substitutions(t)[1].values())`.
    The masked text is the half this gate needs and a texts-only helper cannot
    provide, because a `(kind, path, verb)` hit has to know that the token
    holding the substitution is opaque.
    """
    if "$(" not in text and "`" not in text:
        return text, {}
    out, subs, i, n = [], {}, 0, len(text)
    in_dq = False
    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n:
            out.append(text[i:i + 2])
            i += 2
            continue
        if not in_dq and c == "'":
            j = text.find("'", i + 1)
            j = n if j < 0 else j + 1
            out.append(text[i:j])
            i = j
            continue
        if c == '"':
            in_dq = not in_dq
            out.append(c)
            i += 1
            continue
        if text.startswith("$((", i):
            # ARITHMETIC IS A WORD CONTEXT, NOT A SEALED SPAN (QA cycle 13).
            # The `$((` is copied because the arithmetic itself runs no command,
            # and then the scan CONTINUES INSIDE IT, because bash performs
            # command substitution on an arithmetic expression before evaluating
            # it. Measured on bash 5.2.21, all four removing the file:
            #   echo $(( $(rm -f a; echo 1) ))      x=$((`rm -f b; echo 2`))
            #   (( $(rm -f c; echo 3) ))            echo $[ $(rm -f d; echo 1) ]
            # The old spelling skipped the whole span with `_match_paren`, so a
            # command written inside one was never a command to this parser and
            # `echo $(( $(rm -f <lane>) ))` allowed. It is also what the
            # convergence corpus could not see, because the corpus held only
            # `echo $((1 << 3))`, which has nothing inside it to disagree about.
            out.append(text[i:i + 3])
            i += 3
            continue
        if text.startswith("$(", i):
            j = _match_paren(text, i + 1)
            body = text[i + 2:j - 1] if text[j - 1:j] == ")" else text[i + 2:j]
            mark = "%s%d__" % (_SUBST_MARK, len(subs))
            subs[mark] = body
            out.append(mark)
            i = j
            continue
        if c == "`":
            j, buf = i + 1, []
            while j < n:
                if text[j] == "\\" and j + 1 < n:
                    buf.append(text[j + 1])
                    j += 2
                    continue
                if text[j] == "`":
                    break
                buf.append(text[j])
                j += 1
            mark = "%s%d__" % (_SUBST_MARK, len(subs))
            subs[mark] = "".join(buf)
            out.append(mark)
            i = min(j + 1, n)
            continue
        out.append(c)
        i += 1
    return "".join(out), subs


def markers_in(text: str) -> list:
    """Every substitution marker *text* carries, found in ONE pass.

    QA cycle 12 C8, second cliff: the first spelling asked `mark in seg` for
    every registered marker, which is O(markers x segment) and cost 5.5 s on a
    256 KiB line of 15000 substitutions. The markers are self-describing, so
    reading them out of the text costs one scan instead.
    """
    if _SUBST_MARK not in text:
        return []
    out, i = [], 0
    while True:
        k = text.find(_SUBST_MARK, i)
        if k < 0:
            return out
        j = text.find("__", k + len(_SUBST_MARK))
        if j < 0:
            return out
        out.append(text[k:j + 2])
        i = j + 2


def subst_names_kernel_state(tok: str, subs: dict, kdir: str) -> bool:
    """True when *tok* holds a masked substitution whose BODY spells the kernel
    directory. The value of a substitution is unknowable without running it, so
    a write whose destination is computed by a command that names the kernel
    directory is denied on the body's text, the same raw-text rule the `-c` and
    heredoc channels already pay for."""
    if not subs or _SUBST_MARK not in tok:
        return False
    return any(code_names_kernel_state(subs[mark], kdir)
               for mark in markers_in(tok) if mark in subs)


def subst_target_forms(tok: str, subs: dict) -> list:
    """*tok* with each masked substitution replaced by a PATH-SHAPED word from
    its own body, one form per candidate.

    QA cycle 13: `subst_names_kernel_state` applied the raw-text test to the
    KERNEL directory and to nothing else, so one rule had two scopes — a
    computed write target that spelled the kernel directory denied, while
    `echo hi > $(echo <lane>)/f.txt` reached another process's lane. The value
    of a substitution is unknowable without running it either way; what is
    knowable is the text, so the text answers for a lane exactly as it already
    answered for the kernel.

    A word counts when it LOOKS like a path (it carries a separator, or a `~` /
    `$HOME` prefix). A bare word does not: `$(date +%F).log` names no directory
    and resolving `+%F` against the cwd would invent a target.

    THE WORD IS SUBSTITUTED INTO THE TOKEN, not returned on its own, because the
    token is what names the target. `echo hi > $(echo <tree>)/notes.txt` writes
    `<tree>/notes.txt` and nothing else; returning the bare `<tree>` would put a
    hit on the whole tree and prefix-match every lane under it, which is a false
    deny on a command that touches one file. `echo hi > $(echo <lane-dir>)/f.txt`
    reconstructs to `<lane-dir>/f.txt`, which IS the collision."""
    if not subs or _SUBST_MARK not in tok:
        return []
    import shlex
    out = []
    for mark in markers_in(tok):
        body = subs.get(mark)
        if not body:
            continue
        try:
            words = shlex.split(body)
        except ValueError:
            words = body.split()
        for word in words:
            if word.startswith("-"):
                continue
            # A word made of nothing but separators is not a path. Cycle 13
            # justified this by saying the root "prefix-matches every lane
            # there is"; QA cycle 14 refuted it —
            # `kernel_proc.paths_conflict("/", <lane>)` is False by design, so
            # a root hit changes no verdict. What it does is cost an ownership
            # lookup and put a meaningless target in the deny report, on the 14
            # real commands measured carrying `> $T/g_$(echo $ref | tr '/'
            # '_').py`. Kept for that, and pinned on the hits rather than on a
            # verdict it cannot move.
            if not word.strip("/. "):
                continue
            if "/" in word or word.startswith(("~", "$HOME", "${HOME}")):
                out.append(tok.replace(mark, word))
    return out


# Flags whose argument IS the program, PER HOST since QA cycle 12 C7. A single
# shared tuple could only hold `-c`, because the same letter is a program flag
# for one interpreter and an ordinary option for another: `-e` is a program for
# perl and node and errexit for every shell, `-m` is a module for python and
# monitor mode for bash, `-f` is a program file for awk and noglob for sh. The
# per-host table says which is which instead of guessing, and a host with no
# row falls back to `-c`, which every shell honours.
_PROGRAM_FLAGS = ("-c", "--command")             # the fallback, and the export
_PROGRAM_FLAGS_BY_HOST = {
    "bash": ("-c", "--command"), "sh": ("-c",), "zsh": ("-c",), "dash": ("-c",),
    "ksh": ("-c",),
    "python": ("-c", "-m"), "py": ("-c", "-m"),
    "perl": ("-e", "-E"),
    "ruby": ("-e",),
    "node": ("-e", "--eval", "-p", "--print"),
    "deno": ("-e", "--eval"), "bun": ("-e", "--eval"),
    "php": ("-r",),
    "awk": ("-f",), "gawk": ("-f", "--file", "--source"), "mawk": ("-f",),
    "sed": ("-e", "--expression", "-f", "--file"),
    "lua": ("-e",), "Rscript": ("-e",),
}
# Options that CONSUME THE NEXT TOKEN without being a program. QA cycle 12 C7
# measured every one of these passing: the value landed where an operand would
# be, `stdin_is_program` read it as a script and the body became data.
# `sed -i` and `perl -i` are deliberately absent: their argument is optional and
# only ever arrives attached, so listing them would eat the script.
_VALUED_HOST_OPTS = {
    "bash": ("-o", "+o", "-O", "+O", "--rcfile", "--init-file"),
    "sh": ("-o", "+o"), "zsh": ("-o", "+o"), "dash": ("-o", "+o"),
    "ksh": ("-o", "+o"),
    "python": ("-X", "-W", "--check-hash-based-pycs"),
    "py": ("-X", "-W"),
    "perl": ("-I",),
    "ruby": ("-I", "-r", "-C", "-K", "-E", "--encoding"),
    "node": ("-r", "--require", "--import", "--loader", "--experimental-loader",
             "--conditions", "--max-old-space-size", "--stack-size"),
    "awk": ("-v", "-F", "--assign", "--field-separator"),
    "gawk": ("-v", "-F", "--assign", "--field-separator"),
    "mawk": ("-v", "-F"),
    "lua": ("-l",),
}
# Flags that MEAN "read the program from stdin". `bash -s` is not an unknown
# option to be skipped, it is the operand-free spelling of `bash -`: the
# positional arguments after it are `$0` and friends, not a script. QA cycle 12
# C7 called this a straight defect rather than a residual, and it is.
_STDIN_FLAGS = {"bash": ("-s",), "sh": ("-s",), "zsh": ("-s",), "dash": ("-s",),
                "ksh": ("-s",)}
# Paths that NAME this process's own stdin. Not a list of spellings someone
# thought of: on Linux the kernel provides exactly `/dev/stdin`, `/dev/fd/N`
# (a symlink to `/proc/self/fd`), `/proc/self/fd/N`, `/proc/thread-self/fd/N`
# and `/proc/<pid>/fd/N`, so the set is closed by procfs rather than by this
# table. QA cycle 12 C6: the old tuple held three of them and `/proc/self/fd/0`
# — the spelling a script writes when it wants to be portable — was not one.
# QA cycle 13 takes the last enumeration out of it. The tuple pinned the fd to
# ZERO, so `python3 /dev/fd/3 3<<'EOF'` — which executes — read as a script
# operand and its body became data; and the spellings were compared as STRINGS,
# so `//dev/stdin` and `/dev//fd/0` were different files to this table and the
# same file to the kernel. The number is parsed out instead of listed, and the
# separators are collapsed before the comparison.
_STDIN_OPERANDS = ("-", "/dev/stdin")
_FD_DIRS = ("/dev/fd", "/proc/self/fd", "/proc/thread-self/fd")


def fd_operand(tok: str):
    """The DESCRIPTOR *tok* names, or None when it names no descriptor.

    QA cycle 13. The old spelling answered a yes/no about fd 0, so
    `python3 /dev/fd/3 3<<'EOF'` — a real, executing shape — read as a script
    operand and its body became data. A heredoc feeds a descriptor and a
    program reads its program from one; the two are paired by NUMBER, and 0 is
    only the common case. `-` is the shell convention for stdin, so it is 0."""
    tok = _collapse_slashes(tok)
    if tok in _STDIN_OPERANDS:
        return 0
    head, sep, base = tok.rpartition("/")
    if not sep or not base.isdigit():
        return None
    if head in _FD_DIRS:
        return int(base)
    parts = head.split("/")
    if (len(parts) == 4 and parts[0] == "" and parts[1] == "proc"
            and parts[2].isdigit() and parts[3] == "fd"):
        return int(base)
    return None


def is_stdin_operand(tok: str) -> bool:
    """True when *tok* names any descriptor of this process, in any spelling
    procfs provides. Kept as the yes/no half of `fd_operand` for the callers
    that only ask whether stdin is the program at all."""
    return fd_operand(tok) is not None


def _interp_base(name: str) -> str:
    """*name* with a trailing VERSION removed: `python3.12` -> `python`.

    QA cycle 11 F2. The old spelling was `name.rstrip("0123456789")`, which
    leaves `python3.` (the DOT survives) and matches nothing, so `python3.12`
    — the only versioned interpreter installed on this host — escaped both the
    `_CODE_HOSTS` raw-text test and the `-c` re-scan while bare `python3` was
    caught. Adversarial QA found the identical defect in the merge gate's own
    host match, which makes it one bug in shared logic rather than two.

    Used ONLY to widen the interpreter tables. `_KSTATE_READONLY` keeps its
    exact match on purpose: `base64` normalizes to `base` and a read-only
    program must never lose its place in that list to a version strip.
    """
    base = name
    while base and (base[-1].isdigit() or base[-1] == "."):
        base = base[:-1]
    base = base.rstrip("-_")
    return base or name


def is_code_host(name: str) -> bool:
    """True when *name* is a program whose PROGRAM is text, version or not."""
    return name in _CODE_HOSTS or _interp_base(name) in _CODE_HOSTS


def _host_key(name: str) -> str:
    """The row of the per-host option tables that *name* uses."""
    if name in _PROGRAM_FLAGS_BY_HOST or name in _VALUED_HOST_OPTS:
        return name
    return _interp_base(name)


def stdin_program_fd(tokens: list):
    """The DESCRIPTOR this command reads its program from, or None.

    QA cycle 13 splits the number out of `stdin_is_program`, which only ever
    answered about 0. Everything else about the test is unchanged, including
    that it is a POSITION test and not a name test.

    A position test, not a name test. `python3 <<EOF`, `python3 - <<EOF`,
    `bash -s <<EOF` and `python3 -W ignore - <<EOF` run the body;
    `python3 script.py <<EOF` and `python3 -c '…' <<EOF` do not, and for those
    the body is the program's INPUT, which is data.

    Options are read against the PER-HOST tables above rather than a single
    shared tuple (QA cycle 12 C7). `--` ends the options: whatever follows is
    an operand, so a script name there still means the body is data.

    Residual, stated and narrowed: a valued option NEITHER table knows still
    puts a non-flag token where an operand would be and the body reads as data.
    It fails toward ALLOW, which is the right failure for a rule whose cost is
    denying the dominant idiom.
    """
    if not tokens:
        return None
    host = os.path.basename(tokens[0])
    if not is_code_host(host):
        return None
    key = _host_key(host)
    program = _PROGRAM_FLAGS_BY_HOST.get(key, _PROGRAM_FLAGS)
    valued = _VALUED_HOST_OPTS.get(key, ())
    stdin_flags = _STDIN_FLAGS.get(key, ())
    i, end_of_flags = 1, False
    while i < len(tokens):
        tok = tokens[i]
        if not end_of_flags and tok.startswith("-") and tok != "-":
            if tok == "--":
                end_of_flags = True
                i += 1
                continue
            name = tok.partition("=")[0]
            if tok in program or name in program:
                return None
            if tok in stdin_flags:
                return 0
            # a short-option BUNDLE: `bash -se` is `bash -s -e`
            if not tok.startswith("--") and any(
                    len(f) == 2 and f[1] in tok[1:] for f in stdin_flags):
                return 0
            if tok in valued or name in valued:
                i += 1 if "=" in tok else 2
                continue
            i += 1
            continue
        fd = fd_operand(tok)
        if fd is not None:
            return fd
        return None                  # a script operand: stdin is its input
    return 0                         # no operand at all: stdin is the program


def stdin_is_program(tokens: list) -> bool:
    """True when this command runs whatever arrives on one of its descriptors.
    The yes/no half of `stdin_program_fd`, for the here-string channel, where
    the text always arrives on 0."""
    return stdin_program_fd(tokens) is not None


# Tokens that open a GROUP rather than name a program. QA cycle 12 C5:
# `( python3 - <<'EOF' … )` shlex-split to `['(', 'python3', …]`, so the host
# came back empty and the body was discarded. The sibling gate's head-position
# rule skips the same set.
_GROUP_OPENERS = ("(", "{", "!", "then", "else", "elif", "do", "time")


def strip_group_openers(tokens: list) -> list:
    """*tokens* with any leading grouping or compound-command keyword removed,
    so the next token is the program. Handles `( python3` and `(python3`."""
    while tokens:
        head = tokens[0]
        if head in _GROUP_OPENERS:
            tokens = tokens[1:]
            continue
        if len(head) > 1 and head[0] in "({":
            tokens = [head[1:]] + tokens[1:]
            continue
        break
    return tokens


def stdin_program_host(opening: str, here: str, split_subcmds, fd: int = 0) -> str:
    """The interpreter on *opening* that reads its program from descriptor *fd*,
    else "".

    The whole LINE is read rather than one sub-command, because the receiver of
    a heredoc need not be the command that opens it: `cat <<'EOF' | python3 -`
    declares the body on `cat` and executes it on `python3`.

    Two things widened in QA cycle 13. The receiver is matched by DESCRIPTOR, so
    `python3 /dev/fd/3 3<<'EOF'` pairs the operand with the opener that feeds
    it instead of failing the fd-0 test. And a substitution's contents are read
    as opening lines of their own: `x=$(python3 - <<'EOF' … EOF )` is the
    ordinary `result=$(python3 - <<EOF …)` idiom, and it opened its heredoc
    inside a word, where the old spelling shlex-split the line to
    `['x=$(python3', '-']`, peeled `x=$(python3` off as an env assignment and
    came back with no host at all.
    """
    import shlex
    masked, opening_subs = split_command_substitutions(opening or "")
    for text in [masked] + list(opening_subs.values()):
        for seg in split_subcmds(text):
            try:
                toks = shlex.split(seg)
            except ValueError:
                toks = seg.split()
            toks = strip_group_openers(toks)
            _redirects, toks = redirect_targets(toks)
            toks, _here = peel_wrappers(peel_env(toks), here)
            if stdin_program_fd(toks) == fd:
                return os.path.basename(toks[0])
    return ""


def stdin_channel_texts(seg: str) -> tuple:
    """(here-string texts, process-substitution bodies) of one segment.

    Lifted from `qa-merge-gate._stdin_channel_texts`, which found the same hole
    from the other side: the heredoc scan matches `<<WORD` only, so a here-string
    was never a body and the stdin test was never consulted. The two are
    returned SEPARATELY because they are not the same claim: a here-string is a
    command only when its receiver reads stdin as a program, while a process
    substitution runs its own body whatever the outer program is.
    """
    import shlex
    here_strings, substitutions = [], []
    i = 0
    while True:
        k = seg.find("<<<", i)
        if k < 0:
            break
        rest = seg[k + 3:].lstrip()
        try:
            piece = shlex.split(rest)[:1]
        except ValueError:
            piece = rest.split()[:1]
        if piece:
            here_strings.append(piece[0])
        i = k + 3
    for opener in _SUBST_OPENERS:
        i = 0
        while True:
            k = seg.find(opener, i)
            if k < 0:
                break
            depth, j = 1, k + 2
            while j < len(seg) and depth:
                if seg[j] == "(":
                    depth += 1
                elif seg[j] == ")":
                    depth -= 1
                j += 1
            substitutions.append(seg[k + 2:j - 1] if depth == 0 else seg[k + 2:])
            i = max(j, k + 2)
    return here_strings, substitutions


_BROAD_ADD = ("-u", "--update", "./", ":/", ":(top)")
_MAX_DEPTH = 3
# THE PARSE BUDGET (QA cycle 12 C8). `arm_invocation_budget()` bounds the
# JOURNAL reads; nothing bounded the parse, and the harness kills this hook at
# `timeout: 5`. A kill produces no verdict, and no verdict reads as ALLOW in
# every matrix in this PR, so the cliff was a silent bypass for anyone willing
# to pad a command.
#
# MEASURED on this box, and the cost is per SEGMENT PARSED, not per byte: a
# 20000-line DATA heredoc costs 7.6 ms (the body is split off and never
# tokenized), while 20000 command lines cost 4.95 s and a 20000-line EXECUTED
# heredoc body costs 7.07 s. So the budget counts segments, which leaves a
# large file written through `cat > f <<'EOF'` exactly as cheap as it is today
# and bounds only the shape that actually costs.
#
# 2000 segments is ~0.5 s at the measured 250 us/segment, against a largest
# real command of 2.57 ms. Exhausting it means the parse is INCOMPLETE, and an
# incomplete parse answers UNKNOWN, which never allows (commit 27d51b3).
_MAX_SEGMENTS = 2000
_TRIGGERS = _build_triggers()


def _split_words(text: str):
    """`shlex.split`, with Windows path separators surviving the split.

    POSIX shlex reads a backslash as an escape, so `rm -rf C:\\work\\tree`
    tokenizes to `C:worktree`: every separator is eaten, the target resolves to
    a path that exists nowhere, and it matches no lane. The gate then denies
    nothing, which is how a rule labelled fail-closed goes silently inert on
    Windows while the doctor still reports it wired. Doubling the backslashes
    first restores them verbatim and changes no other POSIX rule (quoting, word
    splitting, comments), so one command parses the same on both platforms.

    A backslash that genuinely was an escape (`a\\ b`) survives as a literal
    backslash inside the token. That token only ever reaches path matching,
    where a literal backslash matches no lane either, so nothing loosens.

    Raises ValueError exactly as `shlex.split` does, so each call site keeps the
    fallback it already chose.
    """
    import shlex

    return shlex.split(text.replace("\\", "\\\\") if os.name == "nt" else text)



class ParseTooLarge(Exception):
    """The command is larger than the parse budget allows — in sub-commands or
    in characters — so no verdict can be reached by reading it. Denied, never
    dropped."""


# THE CHARACTER BUDGET IS CHARGED WHERE THE CHARACTERS ARE WALKED (QA cycle
# 13), which is the half cycle 12 got backwards. `_MAX_PARSE_CHARS` was a TEST
# taken AFTER `split_heredocs` had already char-walked every line carrying
# `<<`, and heredoc bodies were exempt from it by design, and then the
# substitution scanner walked an unquoted body in a pure-Python loop. Both were
# free, and QA measured the consequence directly: multi-megabyte shapes at
# 13.3 s and 11.8 s, and under a 5 s emulated kill `rc 124 with zero bytes on
# stdout, twice` — the no-verdict-reads-as-allow path this budget exists to
# close. So the count is now a SPEND, like the segment count beside it, taken
# at each of the three places that read characters:
#   `split_heredocs`  charges every line it hands to the `<<` char loop;
#   `scan`            charges the text it hands to the two splitters, per frame,
#                     so a recursion adds to the same purse instead of getting
#                     a fresh one;
#   `heredoc_hits`    charges an UNQUOTED body before scanning it for
#                     substitutions, which is the walk nothing charged at all.
#
# THE NUMBER IS MEASURED, TWICE, AND THE SECOND MEASUREMENT IS THE ONE THAT
# COUNTS. 256 KiB fitted at idle and not at the load this box runs: a 200 KiB
# single-line command cost 6.1 s at load 18 (`shlex.read_token` accumulates one
# token character by character, so a long word is quadratic), past the harness
# `timeout: 5` and straight into the silent bypass. At 96 KiB the worst shape
# measured 1.4-1.7 s at load 18 and the margin is real. The ceiling is also far
# above the work: over 19403 distinct real Bash commands from this machine's
# transcripts the LARGEST is 33098 characters, the p99 is 5800, the p999 is
# 15459 and the median is 302, so
# the cap clears the largest command anyone here has ever issued.
# Nested text is charged TWICE on purpose, once as part of its outer frame and
# once as the recursion that re-reads it, because that is how many times it is
# walked: the cap bounds the WALKING, not the command.
# `_MAX_COMMAND_CHARS` stays a MEMORY bound on the raw text before anything is
# read, because `cmd.split("\n")` on an unbounded string is a memory decision
# rather than a parse decision, and it stays high so a data heredoc writing a
# large file is still allowed and still cheap (its body is never tokenized).
_MAX_PARSE_CHARS = 48 * 1024
_MAX_COMMAND_CHARS = 4 * 1024 * 1024
# THE COST IS PER TOKEN, NOT PER BYTE (QA cycle 14 blocker 3), and cycle 13
# measured the wrong worst shape. One long word is `shlex`-quadratic and looked
# like the ceiling; MANY SHORT TOKENS is worse, because every token is resolved
# and every hit costs a `lane_owner` lookup. Measured end to end through the
# real hook against a real held lane, which is what faces the harness kill:
#
#   95 KiB, one long word     1.74 s sequential
#   95 KiB, `rm -f x x x …`   6.63 s sequential, 9.85 s with three concurrent
#
# against a `timeout: 5`. A killed hook writes nothing and empty stdout is
# ALLOW, so the band just under the old 96 KiB cap was a fail-open by clock.
# So tokens are charged where they are spent, beside the characters, and the
# number comes from the same end-to-end measurement at load 19:
#
#   2000 tok 1.05 s   4000 tok 1.34 s   8000 tok 1.88 s   16000 tok 3.89 s
#
# 8192 leaves better than a 2x margin at the measured worst and clears real
# traffic: over 19403 distinct real commands from this machine the LARGEST is
# 4429 tokens, p999 is 1206 and the median is 20, so exactly two real commands
# would meet the cap. `_MAX_PARSE_CHARS` drops to 48 KiB by the same rule, 1.45x
# the largest real command (33098 bytes) and comfortably under a second for the
# long-word shape.
#
# ABOVE EITHER CAP THE ANSWER IS DENY, never unbounded work: an exhausted budget
# raises `ParseTooLarge` and `main` denies on it. That is the whole point of the
# caps, and it is written here because a cap whose over-limit behaviour is
# unstated is where this class hides.
_MAX_PARSE_TOKENS = 8192


def _spend_chars(budget: list, n: int) -> None:
    """Charge *n* characters to the parse budget, raising when it is spent."""
    if budget is None or len(budget) < 2:
        return
    budget[1] -= n
    if budget[1] < 0:
        raise ParseTooLarge(
            f"more than {_MAX_PARSE_CHARS} characters of command text to walk")


def _spend_tokens(budget: list, n: int) -> None:
    """Charge *n* TOKENS to the parse budget, raising when it is spent. Every
    token is resolved and may cost an ownership lookup, so this is where the
    end-to-end cost actually lives (QA cycle 14 blocker 3)."""
    if budget is None or len(budget) < 3:
        return
    budget[2] -= n
    if budget[2] < 0:
        raise ParseTooLarge(
            f"more than {_MAX_PARSE_TOKENS} tokens to resolve")


def scan(command: str, cwd: str, depth: int = 0, budget: list = None,
         subs: dict = None) -> list:
    """Every collision candidate in one command, as (kind, path, verb) where
    kind is 'release', 'tree', 'stage' or 'path'. Pure parsing: no process
    table, no liveness, no I/O beyond the existence probe a bare
    `git checkout <arg>` needs to tell a branch from a file."""
    import shlex

    kdir = kernel_proc.norm_path(kernel_proc.kernel_dir())
    # The trigger table is a VERB table too, and `mkfifo`/`ln` are in none of
    # its entries, so the fast path used to return [] before the floor below
    # could look at anything. A command that spells the kernel directory is
    # always worth parsing, whatever verb it carries.
    if not any(t in command for t in _TRIGGERS) and \
            not code_names_kernel_state(command, kdir):
        return []
    split_subcmds, broad_git_verb = _dim_helpers()
    shell_c = _shell_c() if depth < _MAX_DEPTH else None
    here = kernel_proc.norm_path(cwd or os.getcwd())
    if budget is None:
        budget = [_MAX_SEGMENTS, _MAX_PARSE_CHARS, _MAX_PARSE_TOKENS]
    if len(command or "") > _MAX_COMMAND_CHARS:
        raise ParseTooLarge(
            f"{len(command)} characters, past the {_MAX_COMMAND_CHARS} this "
            "gate reads")
    # The trigger test above reads the WHOLE command, bodies included, because a
    # body is where the kernel path lives; the parse below reads the command
    # with the bodies taken out, because a body is not a command line. The
    # bodies are then handed back to whatever executes them, and to nothing
    # else (QA cycle 11).
    body_cmd, heredocs = split_heredocs(command or "", budget)
    # The two splitters below are O(characters) of pure-Python char loop and
    # `shlex` is worse than that on a long word, so the text they are about to
    # read is charged here, per FRAME: a recursion spends from the same purse.
    _spend_chars(budget, len(body_cmd))
    # COMMAND SUBSTITUTIONS come out next and BEFORE `_split_subcmds`, because a
    # backtick body carrying `;` or `|` tears the outer command apart at the
    # splitter (which tracks `(` depth, so `$(a; b)` survived and `` `a; b` ``
    # did not). Masking first makes both shapes one token, and the bodies are
    # handed back to the segment they appear in, with that segment's cwd.
    body_cmd, own_subs = split_command_substitutions(body_cmd)
    # A marker keeps its meaning INSIDE a nested scan. `bash -c "rm -f $(echo
    # <kdir>)/ptable.json"` masks the substitution at this frame and then hands
    # the `-c` body to a recursion that never saw it, so the inherited registry
    # travels with the recursion while only the ones created HERE are scanned
    # and drained here.
    subs = dict(subs or {})
    subs.update(own_subs)
    seen_subs = set()
    # Each substitution is a COMMAND, so it spends the same budget a segment
    # does. Charged up front because the masking has already happened and the
    # count is exact: a command carrying more of them than the budget allows
    # cannot be read inside the timeout however cheap each one is.
    budget[0] -= len(own_subs)
    if budget[0] < 0:
        raise ParseTooLarge(
            f"more than {_MAX_SEGMENTS} sub-commands to parse")
    # Keyed by TERMINATOR, so a sub-command can claim its own body back. A line
    # that opens two of them (`cat <<A | python3 - <<B`) returns its bodies in
    # the order its terminators appear, which is the pairing used here; a body
    # no key finds is drained at the end rather than dropped.
    pending, nth = {}, {}
    for opening, body, quoted, fd in heredocs:
        terms = [t for t, _q, _s, _f in _heredoc_ops(opening)]
        i = nth.get(opening, 0)
        nth[opening] = i + 1
        term = terms[i] if i < len(terms) else (terms[0] if terms else "")
        pending.setdefault(term, []).append((opening, body, quoted, fd))
    hits = []
    here0 = here
    if depth < _MAX_DEPTH:
        for body in deferred_substitution_bodies(command or ""):
            hits.extend(scan(body, here, depth + 1, budget, subs))
    piped_text = ""
    for seg in split_subcmds(body_cmd):
        budget[0] -= 1
        if budget[0] < 0:
            raise ParseTooLarge(
                f"more than {_MAX_SEGMENTS} sub-commands to parse")
        seg = seg.strip().rstrip(";").strip()
        # a subshell or group: `(rm -rf pkg)` is a command, not a token soup
        if depth < _MAX_DEPTH and seg[:1] in ("(", "{"):
            inner = seg[1:].strip()
            if inner[-1:] in (")", "}"):
                inner = inner[:-1]
            hits.extend(scan(inner, here, depth + 1, budget, subs))
            continue
        if shell_c is not None:
            m = shell_c.match(seg)
            if m:
                try:
                    body = _split_words(m.group(1))
                except ValueError:
                    body = []
                while body and body[0] == "--":
                    body = body[1:]          # `bash -c -- "…"`: `--` ends the
                if body:                     # options, it is not the program
                    hits.extend(scan(body[0], here, depth + 1, budget, subs))
                    continue
        try:
            tokens = _split_words(seg)
        except ValueError:
            tokens = seg.split()
        _spend_tokens(budget, len(tokens))
        redirects, tokens = redirect_targets(tokens)
        for target in redirects:
            if is_null_sink(target):
                continue
            # `echo hi > $(echo <kdir>)/ptable.json` (QA cycle 12 C1): the
            # destination is computed by a command, so the literal path is not
            # in the token and never was. The body's text answers instead.
            if subst_names_kernel_state(target, subs, kdir):
                hits.append(("state", kdir, ">"))
            for form in subst_target_forms(target, subs):
                hits.append(("path", resolve(form, here), ">"))
            hits.append(("path", resolve(target, here), ">"))
        pre_peel = list(tokens)
        # A COMMAND STRING IS READ BEFORE THE PEEL (QA cycle 14 blocker 5).
        # `env -S "rm -f <lane>"` names a wrapper whose option table lists `-S`
        # as valued, so the peel dropped the command as if it were noise and the
        # segment came back empty. The string is claimed here, while the flag
        # and its value are still adjacent.
        if depth < _MAX_DEPTH and pre_peel:
            pre_base = os.path.basename(pre_peel[0])
            if pre_base in _COMMAND_STRING:
                for text in command_string_args(pre_base, pre_peel[1:]):
                    hits.extend(scan(text, here, depth + 1, budget, subs))
        tokens, here = peel_wrappers(peel_env(tokens), here)
        # THE KERNEL FLOOR, BEFORE ANY VERB DISPATCH AND BEFORE THE EMPTY TEST,
        # because the verb is what kept losing and an ENV ASSIGNMENT has no verb
        # at all. `mkfifo`, `ln -sf`, `shred -u`, `install` and `busybox rm`
        # reach this line and none of them reaches the `_MUTATORS` branch below;
        # `K=<kdir> && mkfifo $K/journal/x` peels to NOTHING here and the path
        # lives in the segment that was dropped, which is why the scan reads the
        # tokens as they arrived rather than as they were peeled.
        host = os.path.basename(tokens[0]) if tokens else ""
        if is_code_host(host):
            if code_names_kernel_state(seg, kdir):
                hits.append(("state", kdir, host))
        elif host not in _KSTATE_READONLY and not (
                host == "find" and not find_targets(tokens[1:])[0]):
            for target in (names_kernel_state(pre_peel, here, kdir)
                           + flag_values_naming_kernel_state(pre_peel, here, kdir)):
                hits.append(("state", target, host or "assignment"))
            for tok in pre_peel:
                if subst_names_kernel_state(tok, subs, kdir):
                    hits.append(("state", kdir, host or "assignment"))
                    break
        else:
            # A READ-ONLY HEAD IS EXEMPT IN ITS OPERANDS, NOT IN ITS FLAGS (QA
            # cycle 14 blocker 1). The list means "this program's positionals
            # are inputs"; it has never meant "this program writes nothing", and
            # a flag that carries an output path is a write whatever the program
            # is called. So the flag half of the same scan still runs here.
            for target in flag_values_naming_kernel_state(pre_peel, here, kdir):
                hits.append(("state", target, host or "assignment"))
        # THE SUBSTITUTION BODIES this segment carries, scanned as commands with
        # the cwd this segment runs in. Kept OUT of the branch above because a
        # read-only head (`echo $(rm -f <kdir>/ptable.json)`) is exactly the
        # shape that was passing: the outer verb touches nothing, the inner one
        # touches everything.
        if own_subs and _SUBST_MARK in seg and depth < _MAX_DEPTH:
            for mark in markers_in(seg):
                if mark in own_subs and mark not in seen_subs:
                    seen_subs.add(mark)
                    hits.extend(scan(own_subs[mark], here, depth + 1, budget,
                                     subs))
        # THE STDIN CHANNELS, resolved against the cwd THIS segment runs in.
        # Claiming a body inside the loop rather than after it is what keeps
        # `cd pkg && bash <<EOF ... rm -f a.py ... EOF` covered: the body is a
        # command list and its relative paths mean what the `cd` made them
        # mean.
        if pending or "<<" in seg or "<(" in seg or ">(" in seg:
            hits.extend(stdin_channel_hits(seg, tokens, here, kdir, depth,
                                           split_subcmds, pending, budget, subs))
        # A PIPE IS A STDIN CHANNEL TOO (QA cycle 14 blocker 5). The header
        # listed heredoc, here-string and process substitution as "the same
        # channel in other syntax" and left out the PIPE, which is the common
        # one: 61 real commands on this machine pipe into a shell. When this
        # segment runs stdin as its program and the segment before it emitted
        # literal text, that text is the program.
        prior, piped_text = piped_text, literal_text_of(tokens)
        if (prior and depth < _MAX_DEPTH and tokens
                and stdin_program_fd(tokens) is not None
                and _interp_base(os.path.basename(tokens[0])) in _C_HOSTS):
            hits.extend(scan(prior, here, depth + 1, budget, subs))
        # …and the OTHER half of the same channel: an argument consumer runs a
        # command whose arguments arrive on stdin, so the literal text is not a
        # program, it is the operand list. `xargs` is peeled by the wrapper
        # table, so the command it runs is already in `tokens`; the text is
        # appended to it and the pair is scanned as one command.
        if (prior and depth < _MAX_DEPTH and pre_peel
                and os.path.basename(pre_peel[0]) in _ARGUMENT_CONSUMERS
                and tokens):
            import shlex as _sh
            hits.extend(scan(" ".join(_sh.quote(t) for t in tokens) + " " + prior,
                             here, depth + 1, budget, subs))
        # `source <(echo "rm -f <lane>")` and `. <(…)`: the substitution's own
        # body is already scanned as a command by `stdin_channel_hits`, and that
        # is not the whole claim — `source` executes the OUTPUT of that body, so
        # literal text it emits is a program the same way a pipe's is.
        if (depth < _MAX_DEPTH and tokens
                and os.path.basename(tokens[0]) in ("source", ".")):
            import shlex as _shlex
            for body in stdin_channel_texts(seg)[1]:
                try:
                    inner = _shlex.split(body)
                except ValueError:
                    inner = body.split()
                text = literal_text_of(inner)
                if text:
                    hits.extend(scan(text, here, depth + 1, budget, subs))
        if not tokens:
            continue
        if tokens[0] in ("cd", "pushd", "popd") and len(tokens) > 1:
            # QA CYCLE 15 BLOCKER 2d: this read `tokens[1]` as the directory, so
            # `cd -- <kdir> && rm -f ptable.json` moved the cwd to `<cwd>/--`
            # and the relative `rm` resolved somewhere harmless. `cd <kdir>`
            # denied beside it, which is the tell. `-P`, `-L`, `-e`, `-@` and
            # `pushd -n` are the same shape.
            target = ""
            for tok in tokens[1:]:
                if tok == "--":
                    continue
                if tok.startswith("-") and tok != "-":
                    continue
                target = tok
                break
            if target:
                here = resolve(target, here)
            continue
        if is_release(tokens):
            hits.append(("release", None, "octo --release"))
            continue
        base = os.path.basename(tokens[0])
        # `eval a b c` re-parses its arguments, JOINED, as one command line. No
        # flag, nothing to peel forward to, so it gets its own line.
        if depth < _MAX_DEPTH and base in ("eval", "source", "."):
            joined = " ".join(tokens[1:])
            if joined and base == "eval":
                hits.extend(scan(joined, here, depth + 1, budget, subs))
                continue
        # a wrapped or non-anchored `-c` form the raw-segment match above
        # missed, in every spelling that consumes the next word: the exact flag
        # on a modeled shell, a short-option BUNDLE ending in `c` on one, and
        # the same two on a head this file models nothing about (QA cycle 13).
        # A HEAD THIS FILE MODELS AS A WRITER KEEPS ITS OWN FLAGS (QA cycle 15
        # blocker 3). The unmodeled-head `-c` rule matched an exact `-c` on any
        # head, read the next token as a command and `continue`d, so
        # `wget -c -O <lane>` and `curl -c /tmp/jar -o <lane>` never reached
        # their own output-flag rule. `-c` is continue and cookie-jar there.
        write_modelled = (base in _OUTPUT_FLAGS or base in _CONSUMING
                          or base in _POSITIONAL_OUTPUT)
        c_host = _interp_base(base) in _C_HOSTS
        # A REMOTE runner is excluded here for the same reason it is excluded
        # from the peel: `docker run alpine sh -c '…'` and `ssh host -c <cipher>`
        # do not run that text on this file system, and `-c` is not even a
        # command flag for the second one.
        if depth < _MAX_DEPTH and (c_host or (not _modeled_program(base)
                                              and base not in _REMOTE_RUNNERS
                                              and not write_modelled)):
            i = _c_flag_index(tokens, c_host)
            # `bash -c -- "rm -f <lane>"`: `--` ends OPTION parsing, it does not
            # consume the argument the flag already claimed, so the program is
            # the token after it (QA cycle 14 blocker 5). Cycle 12 wrote "a
            # valued option does not hide the operand" and this was the spelling
            # that did.
            while i >= 0 and i + 1 < len(tokens) and tokens[i + 1] == "--":
                i += 1
            if i >= 0 and i + 1 < len(tokens):
                hits.extend(scan(tokens[i + 1], here, depth + 1, budget, subs))
                continue
        if base == "git":
            # THE GIT CONFIG CHANNEL, which the sibling gate's own docstring
            # names: `git -c alias.zap='!rm -f' zap <lane>` runs a shell command
            # out of a config value. Only a `!` alias is a shell command; every
            # other `-c` value is configuration.
            if depth < _MAX_DEPTH:
                for j, tok in enumerate(tokens[1:], 1):
                    if tok != "-c" or j + 1 >= len(tokens):
                        continue
                    key, _eq, val = tokens[j + 1].partition("=")
                    if key.startswith("alias.") and val.startswith("!"):
                        hits.extend(scan(val[1:] + " " + " ".join(tokens[j + 2:]),
                                         here, depth + 1, budget, subs))
            parsed = git_parse(tokens)
            if not parsed:
                continue
            repo, sub, rest = parsed
            base_dir = resolve(repo, here) if repo else here
            root = kernel_proc.enclosing_worktree_root(base_dir)
            # Outside a repo there is no tree to own: a fallback to the cwd
            # would make `git stash` in /tmp or $HOME prefix-match every lane
            # under it. Tree and stage hits need a real root; path hits do not.
            broad, _ = broad_git_verb(["git", sub] + rest)   # normalized: globals stripped
            if not broad and sub == "add" and any(a in _BROAD_ADD for a in rest):
                broad = "add"
            if broad:
                if root:
                    hits.append(("stage", root, f"git {broad}"))
                continue
            verb = whole_tree_verb(sub, rest)
            if verb and root:
                hits.append(("tree", root, verb))
            for spec in pathspecs(sub, rest, base_dir):
                kind, value = spec_target(spec, base_dir)
                hits.append((kind, value, f"git {sub}"))
            continue
        if base == "find":
            roots, pattern, icase = find_targets(tokens[1:])
            for root in roots:
                if pattern:
                    # the filter is the point: `find . -name '*.pyc' -delete`
                    # reaches .pyc files, not every lane under the root
                    hits.append(("iglob" if icase else "glob",
                                 os.path.join(resolve(root, here), "*" + pattern),
                                 "find -delete"))
                else:
                    hits.append(("path", resolve(root, here), "find -delete"))
            continue
        # THE WRITE TABLES RUN BEFORE ANY BRANCH THAT CAN `continue` (QA cycle
        # 15 blocker 3). They used to sit after the unmodeled-head `-c` rule,
        # which matches an exact `-c` on ANY unmodeled head, reads the next
        # token as a command and `continue`s — so `wget -c -O <lane>` and
        # `curl -c /tmp/jar -o <lane>` skipped their own output-flag rule
        # entirely, while `curl -so <lane>` denied beside them. `-c` means
        # continue and cookie-jar there, not command.
        for target in output_flag_targets(base, tokens[1:]):
            if is_null_sink(target):
                continue
            kind, value = spec_target(target, here)
            hits.append((kind, value, base))
        for target in consuming_targets(base, tokens[1:]):
            kind, value = spec_target(target, here)
            hits.append((kind, value, base))
        for target in remote_copy_targets(base, tokens[1:]):
            kind, value = spec_target(target, here)
            hits.append((kind, value, base))
        if base in _POSITIONAL_OUTPUT:
            positional = _positional(base, tokens[1:])
            where = _POSITIONAL_OUTPUT[base]
            picked = []
            if where == "first" and positional:
                picked = positional[:1]
            elif where == "last" and len(positional) >= 2:
                picked = positional[-1:]
            elif where == "last" and len(positional) == 1 and base == "objcopy":
                picked = positional          # one operand: rewritten in place
            for target in picked:
                kind, value = spec_target(target, here)
                hits.append((kind, value, base))
        # A PROGRAM WHOSE ARGUMENT IS A COMMAND STRING (QA cycle 14 blocker 5).
        # `env -S "rm -f <lane>"` puts the whole command in a flag VALUE that
        # env's option table was dropping as noise; `watch -n 0.1 "rm -f
        # <lane>"` hands its first non-flag argument to a shell. Both are the
        # `-c` channel wearing another name, so they route to the same
        # recursion. Enumerated, with a stated end: the members are the ones
        # measured executing on this host.
        if depth < _MAX_DEPTH and base in _COMMAND_STRING:
            for text in command_string_args(base, tokens[1:]):
                hits.extend(scan(text, here, depth + 1, budget, subs))
        if base in _MUTATORS:
            for target in mutation_targets(base, tokens[1:]):
                if is_null_sink(target):
                    continue
                kind, value = spec_target(target, here)
                hits.append((kind, value, base))
            continue
        if base in _STATE_VERBS:
            for target in mutation_targets(base, tokens[1:]):
                hits.append(("state", resolve(target, here), base))
    # A body no segment claimed still has to be read: an opener this parser
    # could not put back with its own sub-command is a body with no cwd, not a
    # body with no content. It is resolved against the cwd the command started
    # in, which is the only one still known here.
    for items in pending.values():
        for opening, body, quoted, fd in items:
            hits.extend(heredoc_hits(opening, body, quoted, fd, here0, kdir,
                                     depth, split_subcmds, budget, subs))
    # A substitution no segment claimed is still a command bash will run. It is
    # resolved against the cwd the command started in, the only one still known.
    if depth < _MAX_DEPTH:
        for mark, body in own_subs.items():
            if mark not in seen_subs:
                seen_subs.add(mark)
                hits.extend(scan(body, here0, depth + 1, budget, subs))
    return hits


def stdin_channel_hits(seg: str, tokens: list, here: str, kdir: str,
                       depth: int, split_subcmds, pending: dict,
                       budget: list = None, subs: dict = None) -> list:
    """Collision candidates one segment carries on STDIN rather than in a token.

    Three channels, one rule each, and the difference between them is who
    decides that the text is a command:

    * a HEREDOC body counts when the LINE that declares it hands stdin to an
      interpreter as its PROGRAM (`python3 - <<EOF`, and `cat <<EOF | python3 -`
      where the declarer and the receiver are different commands). Fed to
      anything else it is data, and reading data as a command is the over-fire
      that was already live here;
    * a HERE-STRING is the same test on this segment's own head, in other
      syntax;
    * a PROCESS SUBSTITUTION needs no such test: `<(...)` runs its body whatever
      the outer program is, so it is scanned unconditionally.
    """
    hits = []
    for opening, body, quoted, fd in _claim_heredocs(seg, pending):
        hits.extend(heredoc_hits(opening, body, quoted, fd, here, kdir, depth,
                                 split_subcmds, budget, subs))
    if depth >= _MAX_DEPTH:
        return hits
    strings, substitutions = stdin_channel_texts(seg)
    for text in substitutions:
        hits.extend(scan(text, here, depth + 1, budget, subs))
    if strings and stdin_is_program(tokens):
        host = os.path.basename(tokens[0])
        for text in strings:
            if code_names_kernel_state(text, kdir):
                hits.append(("state", kdir, host + " <<<"))
            if _interp_base(host) in _C_HOSTS:
                hits.extend(scan(text, here, depth + 1, budget, subs))
    return hits


def heredoc_hits(opening: str, body: str, quoted: bool, fd: int, here: str,
                 kdir: str, depth: int, split_subcmds, budget: list = None,
                 subs: dict = None) -> list:
    """What one heredoc body is worth, given the line that declared it.

    For a body the interpreter runs, the raw-text kernel test applies exactly as
    it does to a `-c` body: the path lives inside a program, not in a token, so
    a MENTION is denied along with a write. That over-fire is the price already
    paid for `-c`, and cycle 11 keeps the two channels equal rather than making
    the quieter one stricter.

    MEASURED on 3186 real heredocs rather than assumed. 40 commands are newly
    denied: 20 genuinely reach the live kernel directory through an interpreter,
    8 name a SANDBOX directory spelled `.claude/.cache/kernel` — the relative
    spelling `_KDIR_SPELLINGS` has carried since cycle 9, but cycle 11 is the
    first to apply the path test to heredoc BODIES, so those 8 are NEWLY
    REACHABLE through this channel even though the spelling they match is old —
    and 12 name the path only in PROSE inside a patch script, which is this
    rule's own false-positive class and the same one `-c` has had all along.
    Against them, 15 false denies GO AWAY, because a data heredoc is no longer
    split into segments and read as commands. Net over-fire +5 in 3186, and a
    data body is the shape that was denying commit messages.

    QA cycle 12 C2 adds the half that does not depend on the receiver at all.
    An UNQUOTED terminator (`cat <<EOF`) means BASH expands `$(...)` and
    backticks in the body before `cat` ever sees it, so the body is a command
    channel whoever receives it; a QUOTED terminator (`<<'EOF'`, `<<"EOF"`,
    `<<\\EOF`, `<<E'OF'`) makes it literal and it stays data. The expansion is
    read first and the receiver test second, because they are two different
    claims about the same text.
    """
    hits = []
    if not quoted and depth < _MAX_DEPTH:
        # the walk cycle 12 left uncharged: a body is exempt from the parse cap
        # by design, and then this scanner reads every character of it
        _spend_chars(budget, len(body))
        _masked, body_subs = split_command_substitutions(body)
        for sub_body in body_subs.values():
            hits.extend(scan(sub_body, here, depth + 1, budget, subs))
    host = stdin_program_host(opening, here, split_subcmds, fd)
    if not host:
        return hits                  # a data heredoc: `cat > notes <<EOF`
    if code_names_kernel_state(body, kdir):
        hits.append(("state", kdir, host + " <<"))
    if depth < _MAX_DEPTH and _interp_base(host) in _C_HOSTS:
        hits.extend(scan(body, here, depth + 1, budget, subs))
    return hits


# ── main ────────────────────────────────────────────────────────────────────

def main() -> int:
    # QA cycle 9 F2: the budget that matters is the INVOCATION's, because the
    # invocation is what the harness kills at `timeout: 5`.
    kernel_proc.arm_invocation_budget()
    try:
        payload = json.loads(sys.stdin.read())
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    if str(payload.get("tool_name") or "") != "Bash":
        return 0
    command = str((payload.get("tool_input") or {}).get("command") or "")
    if not command.strip():
        return 0
    pid = kernel_proc.resolve_pid(payload)

    try:
        hits = scan(command, str(payload.get("cwd") or ""))
    except ParseTooLarge as exc:
        # NOT the fail-open below. Every other parser failure is a bug in
        # reading a command the shell will run anyway; this one is the parse
        # REFUSING to finish, and a parse that does not finish has not looked at
        # the part of the command that matters. Before the budget the harness
        # made this decision by killing the hook at `timeout: 5`, which produces
        # no verdict at all, and no verdict is read as ALLOW by every matrix in
        # this PR. Unknown never allows (commit 27d51b3).
        journal_deny(pid, {"why": "parse-too-large", "command": command[:200],
                           "detail": str(exc), "limit": _MAX_SEGMENTS,
                           "chars": _MAX_PARSE_CHARS})
        deny(
            f"KERNEL ISOLATION: this command is past the parse budget ({exc}), "
            f"which is what this gate can read inside the harness timeout "
            f"({_MAX_SEGMENTS} sub-commands, {_MAX_PARSE_CHARS} characters of "
            f"command text, {_MAX_PARSE_TOKENS} tokens). A parse that cannot finish "
            "cannot tell whether the command writes into the kernel's own state "
            "or into another process's lane, and an unknown answer is denied, "
            "never allowed. Split it into separate calls, or write the file "
            "with the Write tool instead of through a shell."
        )
        return 0
    except Exception:
        return 0            # a parser that cannot read the command denies nothing
    if not hits:
        return 0

    for kind, _target, _verb in hits:
        if kind == "release":
            journal_deny(pid, {"why": "release", "command": command[:200]})
            deny(
                "KERNEL ISOLATION: `--release` frees a lane another process "
                "holds, so it is the operator's move, not an agent's, and it is "
                "denied from Bash. Ask the operator to run `octo ps` and "
                "`octo ps --release <pid>` in the terminal that launched this "
                "session, where no hook fires: `octo ps --release <pid>` (Phase 1b; "
                "on a brain without it, edit the ptable row from the terminal). If "
                "the holder is simply finished, its lane frees on its own after "
                f"{kernel_proc.TTL}s of silence."
            )
            return 0

    kdir = kernel_proc.norm_path(kernel_proc.kernel_dir())
    # THE FILESYSTEM ROOT IS AN ANCESTOR OF EVERYTHING AND CONFLICTS WITH
    # NOTHING (QA cycle 15 blocker 2e). `kernel_proc.paths_conflict("/", x)` is
    # False on purpose — cycle 14 corrected a claim of mine that said otherwise,
    # and that correction is right: a junk `/` hit must not deny the machine.
    # But the header two screens up says an ANCESTOR of the kernel directory is
    # denied, and `/` is the ancestor of every path there is, so
    # `rm -rf --no-preserve-root /`, `find / -delete`, `find / -exec rm` and
    # `chmod -R 000 /` all walked while `rm -rf /*` and `rm -rf ~` denied beside
    # them. The gap was the DESIGN of `paths_conflict`, not a bug in it, so it
    # is closed here where the destructive intent is known rather than there
    # where every caller would inherit it.
    for kind, target, verb in hits:
        if kind in ("path", "state") and target == os.sep:
            journal_deny(pid, {"target": target, "verb": verb, "why": "root"})
            deny(
                f"KERNEL ISOLATION: `{verb}` targets the filesystem root, which "
                "contains every lane on this machine and the kernel's own state "
                f"({kdir}) with them. A path test cannot express this — `/` is a "
                "prefix of everything, so treating it as a collision would deny "
                "the machine on any junk hit — so it is denied here, once, by "
                "name. Name what you actually mean to remove."
            )
            return 0
        if kind in ("path", "state") and kernel_proc.paths_conflict(target, kdir):
            journal_deny(pid, {"target": target, "verb": verb, "why": "kernel-state"})
            deny(
                f"KERNEL ISOLATION: `{verb}` targets {target}, inside the kernel's "
                "own state ({0}). The process table and the journals are what every "
                "gate reads to decide who owns what, so a process that can rewrite "
                "them can grant itself any lane and erase the record of having done "
                "it. No hooked process edits them, this one included. The operator's "
                "terminal is not hooked and stays the only writer.".format(kdir)
            )
            return 0

    checked_hits = [(k, t, v) for k, t, v in hits if k != "state"] or [hits[0]]
    try:
        # the one ptable read of this call, and the one call whose EXCEPTIONS
        # are a deny rather than the fail-open at the bottom of this file. QA
        # cycle 6 F2: `json.load` on a deeply nested file raises RecursionError,
        # which is neither ValueError nor OSError, so it walked past every fault
        # leg in the reader and out through `except Exception: sys.exit(0)`,
        # producing rc=0 with nothing on either stream. The scope is deliberate:
        # a blanket deny on any exception in this hook would wedge the harness
        # on a bug in the command parsing, where allowing the call is the right
        # failure. Here it is not, because this call IS the ownership question.
        table, dropped, fault = kernel_proc.read_ptable_detail()
    except Exception as exc:
        kind, target, verb = checked_hits[0]
        journal_deny(pid, {"target": target, "verb": verb,
                           "why": "ptable-read-raised", "command": command[:200],
                           "error": f"{type(exc).__name__}: {exc}"})
        deny(
            "KERNEL ISOLATION: reading the process table raised "
            f"{type(exc).__name__}: {exc}, so this gate cannot tell whether "
            f"another process holds {target}. A reader that cannot finish is a "
            "table nobody can read, and an unknown owner is denied, never "
            f"allowed. {kernel_proc.recovery()}"
        )
        return 0
    if not fault and dropped:
        # A ROW-LEVEL DROP IS A DENY TOO (QA cycle 4 F1c). Corrupting one row is
        # the most surgical version of this attack: the holder's row replaced
        # with a string, the fault empty, this gate allowing, and the next
        # register republishing the table without that row so the lane is gone
        # for good. The lanes of a row that could not be read are exactly as
        # unknowable as the lanes of a table that could not be read.
        kind, target, verb = checked_hits[0]
        journal_deny(pid, {"target": target, "verb": verb,
                           "why": "ptable-row-unreadable", "command": command[:200],
                           "dropped": sorted(dropped)[:5]})
        deny(
            "KERNEL ISOLATION: "
            f"{len(dropped)} row(s) in the process table could not be read "
            f"({', '.join(sorted(dropped)[:5])}), so this gate cannot tell "
            f"whether one of them holds {target}, which `{verb}` takes. One "
            "writer per lane is fail-closed: rows whose lanes are unreadable "
            "are treated as holding everything, not nothing, because the "
            "alternative is the lane transfer this seam exists to stop. The "
            "next register hook repairs the table and CARRIES THE LOSS "
            "FORWARD, so a routine SessionStart does not clear this. "
            f"{kernel_proc.recovery()}"
        )
        return 0
    if fault:
        # FAIL CLOSED. This gate answers one question, "does another live
        # process hold this path", and it answers it out of the process table.
        # A table it cannot read does not answer that question, it removes it:
        # `sane_table` hands back an EMPTY table for a `processes` that is not
        # an object, and an empty table reads as "nobody owns anything", so the
        # gate that exists to deny the second writer waved it through and the
        # first write after it republished a one-row table with every other
        # lane gone. One writer per tree is a fail-closed rule, so the state
        # where ownership is unknowable is a deny, not an allow.
        #
        # It is not reachable from the kernel's own writers (`_write_ptable`
        # publishes a complete file with `os.replace`), which is the point: a
        # table shaped like this means something that is not the kernel wrote
        # it, and that is the last moment to keep working blind.
        # `state` hits are floor-only and were already tested above, so the
        # targets named here are exactly the ones the ownership loop below would
        # have looked up.
        #
        # The SENTENCE is picked from the hit's kind, and QA cycle 3 F6 is why.
        # A `tree` or `stage` hit is not a contested path, it is a whole working
        # tree, and the first version of this deny said "cannot tell whether
        # another process holds <root>" about `git stash` in the process's OWN
        # tree, which is allowed when the table is readable and where nobody was
        # contesting anything. Denying it is right (that verb rewrites every
        # file under the root, including files a process this gate can no longer
        # see may be holding), so the fix is the message, not the verdict: it
        # has to say what is actually unknown, which is whether anyone ELSE is
        # writing in that tree.
        kind, target, verb = checked_hits[0]
        journal_deny(pid, {"target": target, "verb": verb, "why": "ptable-unreadable",
                           "fault": fault, "command": command[:200]})
        if kind in ("tree", "stage"):
            what = (f"cannot tell whether any OTHER process is writing in "
                    f"{target}, which `{verb}` takes whole. In your own tree "
                    "this is allowed while the table is readable; it is denied "
                    "now because who else is in that tree is exactly what was "
                    "lost")
        else:
            what = f"cannot tell whether another process holds {target}"
        deny(
            "KERNEL ISOLATION: the process table is unreadable, so this gate "
            f"{what}. {fault}. "
            "One writer per tree is fail-closed: an unknown owner is denied, "
            "never allowed, because allowing it is how a second writer takes a "
            "lane and the table that recorded the first one gets overwritten. "
            "The next register hook CARRIES THE FAULT FORWARD (and keeps a "
            "copy of the file when there is one left to copy), so a routine "
            "SessionStart (startup, resume, clear, compact) does not clear "
            "this while the fault stands. "
            f"{kernel_proc.recovery(kernel_proc.fault_kind(table))}"
        )
        return 0
    # DEDUPED, PREFILTERED AND MEMOISED (QA cycle 15 blocker 1). `dict.fromkeys`
    # keeps the first occurrence of each hit in order, so the deny still names
    # the first colliding target the command mentions.
    maybe_collides = _lane_prefilter(table)
    owner_memo = {}
    for kind, target, verb in dict.fromkeys(hits):
        if kind == "state":
            continue          # floor-only: already tested above
        if kind in ("glob", "iglob"):
            owner, row = glob_owner(target, table, pid, kind == "iglob")
        elif not maybe_collides(target):
            continue          # no lane can be at, above or below it
        elif target in owner_memo:
            owner, row = owner_memo[target]
        else:
            owner, row = kernel_proc.lane_owner(target, table, ignore=pid)
            owner_memo[target] = (owner, row)
        if not owner:
            continue
        journal_deny(pid, {"target": target, "owner": owner, "verb": verb,
                           "why": kind, "command": command[:200]})
        if kind == "stage":
            deny(
                f"KERNEL ISOLATION: broad `{verb}` stages every dirty file under "
                f"{target}, and {describe(owner, row)} holds a lane there. That is "
                "the collision verbatim: your commit swallows their uncommitted "
                "work. Stage by EXPLICIT pathspec (`git add <file>...`), or work "
                "in your own worktree. The dimension gate denies this per session; "
                "this one denies it per process, which is what two subagents of "
                f"one session need. Its lanes free on its exit line, after "
                f"{kernel_proc.TTL}s of silence, or when it delegates. The operator can "
                f"free a stuck one: `octo ps --release {owner}` (Phase 1b; on a brain "
                "without it, edit the ptable row from the terminal)."
            )
        elif kind == "tree":
            deny(
                f"KERNEL ISOLATION: `{verb}` rewrites the whole working tree at "
                f"{target}, and {describe(owner, row)} holds a lane in it. This "
                "is the shape that wiped 14 files across three builders on one "
                "tree. Scope the change to your own paths, work in your own "
                "worktree. " + f"Its lanes free on its exit line, after "
                f"{kernel_proc.TTL}s of silence, or when it delegates. The operator can "
                f"free a stuck one: `octo ps --release {owner}` (Phase 1b; on a brain "
                "without it, edit the ptable row from the terminal)."
            )
        else:
            deny(
                f"KERNEL ISOLATION: `{verb}` targets {target}, the lane of "
                f"{describe(owner, row)}. One writer per lane, the parent "
                f"included. Touch your own paths. {kernel_proc.lane_recovery(owner)}"
            )
        return 0
    return 0


# ── selftest (bespoke; the harness lives in the Write twin, imported here) ───

def _selftest(fdir: str = None) -> int:
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "tree_owner_write", os.path.join(_HERE, "g__pretool-write__tree-owner.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.run_isolation_selftest(os.path.abspath(__file__), fdir, ("Bash",),
                                      "g__pretool-bash__tree-owner.py")


if __name__ == "__main__":
    if "--coverage" in sys.argv:
        sys.stdout.write(coverage_manifest())
        sys.exit(0)
    if "--selftest" in sys.argv:
        _i = sys.argv.index("--selftest")
        sys.exit(_selftest(sys.argv[_i + 1] if len(sys.argv) > _i + 1 else None))
    try:
        sys.exit(main())
    except Exception:
        # Fail-open, and it stays fail-open ON PURPOSE for everything that is
        # not the ptable read. A hook that denies on any exception of its own
        # wedges every Bash call in the session on a bug in the command parsing
        # or the arms config, where allowing the call is the right failure. The
        # one exception that must NOT arrive here is the ownership question
        # itself, which is why `main()` denies around `read_ptable_detail`
        # rather than leaving it to this line (QA cycle 4 F2: a RecursionError
        # from the parser reached here and exited 0 with empty stdout, empty
        # stderr and no journal line).
        sys.exit(0)
