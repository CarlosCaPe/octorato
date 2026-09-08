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
substitutions are the same channel in other syntax and are lifted from the
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
than 3; xargs fed from STDIN (`cat list | xargs rm`, `xargs rm < list`),
where the targets never appear in the command at all;
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

Cycle 12 leaves three residuals of its own, each MEASURED as allowed and pinned
by `QaCycle12.test_named_residuals_of_cycle_12`: a runner whose SUBCOMMAND sits
where an operand would (`deno run -`, `bun run -`); a flag that consumes a value
BETWEEN the run verb and the program (`uv run --with rich python -`); and
`${ cmd; }` / `${| cmd; }`, ksh93 value substitution, which bash gained in 5.3
and which this host (bash 5.2.21) rejects outright. One residual is retired
rather than restated: `python3 -W ignore <<EOF` is covered.

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


# The verbs a project runner puts between itself and the real program.
# QA cycle 12 C6: `uv run python - <<EOF` and `poetry run python - <<EOF` both
# passed, and both binaries are installed on this box. The fix is NOT another
# tool list. It is the SHAPE, which inverts the tool name away: whatever the
# first token is, `<tool> run|exec|x … <program>` is a wrapper when the first
# non-flag token after the verb is a program THIS FILE ALREADY HAS A TABLE FOR
# (a code host, a mutator, a state verb, `git`, `find`). `npm run build` is not
# peeled because `build` is in none of them, and `uv run python` is peeled
# without `uv` ever being named.
#
# Stated under-fire: a flag that consumes a value between the verb and the
# program (`uv run --with rich python -`) stops the peel, because without a
# per-runner option table the parser cannot tell `--with rich` from
# `--isolated python`. It fails toward ALLOW, one member wide, and the shape
# above covers the spelling every runner documents.
_RUN_VERBS = ("run", "exec", "x")
# Runners whose `run` puts the program on ANOTHER machine or in another
# filesystem namespace. `docker run python3 - <<EOF` writes the CONTAINER's
# `~/.claude/.cache/kernel`, not this host's, so peeling them would turn a
# stated under-fire (the header's ssh / container-exec residual) into a false
# deny. They stay unpeeled, and the residual stays what it already says it is.
_REMOTE_RUNNERS = ("docker", "podman", "nerdctl", "kubectl", "oc", "ssh",
                   "lxc", "machinectl", "distrobox", "toolbox", "flatpak",
                   "apptainer", "singularity", "vagrant")


def _peel_run_wrapper(tokens: list):
    """*tokens* from the real program on, when they are `<tool> run <program>`;
    None when they are not that shape."""
    if len(tokens) < 3 or tokens[1] not in _RUN_VERBS:
        return None
    if tokens[0].startswith("-"):
        return None
    if os.path.basename(tokens[0]) in _REMOTE_RUNNERS:
        return None
    for j in range(2, len(tokens)):
        if tokens[j].startswith("-"):
            continue
        base = os.path.basename(tokens[j])
        known = (is_code_host(base) or base in _MUTATORS or base in _STATE_VERBS
                 or base in ("git", "find"))
        return tokens[j:] if known else None
    return None


def peel_wrappers(tokens: list, here: str) -> tuple:
    """(tokens with wrapper prefixes removed, the cwd they leave behind).

    `env -C <dir> rm x` and `sudo -D <dir> rm x` move the directory a relative
    target resolves against, so the peel returns it rather than dropping it."""
    while True:
        if not tokens or os.path.basename(tokens[0]) not in _WRAPPERS:
            peeled = _peel_run_wrapper(tokens)
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


def redirect_targets(tokens: list) -> tuple:
    """(files this segment writes by redirection, the remaining tokens).

    `2>&1` writes no file (its operand names a descriptor, not a path) and an
    input redirect writes nothing at all, so both drop out here rather than
    becoming phantom targets."""
    targets, rest, i = [], [], 0
    while i < len(tokens):
        tok = tokens[i]
        core = tok.lstrip("0123456789")
        if core.startswith(">"):
            after = core.lstrip(">")
            if after:
                if not after.startswith("&"):
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
        if a in ("-exec", "-execdir") and i + 1 < len(args):
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
    for part in spec.split(os.sep):
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

_TRIGGERS = ("git", "rm", "mv", "cp", "sed", "tee", ">", "octo", "find",
             "unlink", "truncate", "xargs", "delete", "install", "ln",
             "touch", "chmod", "chattr", "dd")
_C_HOSTS = ("bash", "sh", "zsh", "dash", "python", "python3", "py")
_MUTATORS = ("rm", "mv", "cp", "sed", "tee", "unlink", "truncate", "install", "ln")
# Verbs that can damage the kernel's ledger without being a lane write. They are
# tested against the state floor ONLY, never against a lane: `touch`/`chmod` on
# a sibling's file is not the collision this rule is about.
_STATE_VERBS = ("touch", "chmod", "chattr", "dd")

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
# directory is denied unless its program is on the short read-only list below.
# The set of verbs that can create, replace or unlink a path is open-ended; the
# set of programs that provably cannot is small, nameable and closed.
#
# THE OVER-FIRE IS REAL AND IT IS THE PRICE, stated rather than discovered: a
# READ of kernel state through a tool that is not on this list is denied too
# (`xxd ptable.json`, `python3 -c "print(open(p).read())"`). The deny names the
# path and the operator's terminal is not hooked, so the cost is one message and
# a `cat`, against a wedged session for the other direction.
_KSTATE_READONLY = (
    "cat", "head", "tail", "less", "more", "ls", "stat", "file", "wc",
    "grep", "egrep", "fgrep", "rg", "sort", "uniq", "cut", "diff", "cmp",
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
        if not tok or tok.startswith("-"):
            continue
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
#   `$((expr))`     ARITHMETIC, not a command           left verbatim on purpose
#   `${ cmd; }`     ksh93/bash-5.3 value substitution   RESIDUAL: this host runs
#                   `${| cmd; }`                        bash 5.2.21, which
#                                                       rejects it outright
#   `$[expr]`       removed arithmetic form             not a command
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
# 14/14 agreement measured against e0f9444. This gate takes no runtime import of
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


def _heredoc_ops(line: str) -> list:
    """[(delimiter, quoted, tabstrip)] for every heredoc *line* opens, in order.

    Quote-aware, so `echo "a <<EOF b"` opens nothing: an operator inside an
    ordinary quoted argument is text. `<<<` is skipped explicitly because it is
    a here-string, handled by `stdin_channel_texts`.
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
                ops.append((word, quoted, tabstrip))
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
    """(*cmd* with heredoc BODIES removed, [(opening_line, body, quoted)]).

    `quoted` is the third element since QA cycle 12 C2: an UNQUOTED terminator
    means bash expands `$(...)` and backticks in the body before any command
    receives it, so the body is a command channel whatever the receiver is.
    The old pattern captured the quote character and then ignored it.
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
        for term, quoted, tabstrip in _heredoc_ops(line):
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
                continue                     # no terminator: not a heredoc
            bodies.append((line, "\n".join(lines[i:end]), quoted))
            i = end + 1
    return "\n".join(kept), bodies


def _claim_heredocs(seg: str, pending: dict) -> list:
    """The (opening_line, body, quoted) triples *seg* opens, removed from
    *pending*.

    A sub-command claims a body by naming its terminator, which is how a body
    gets back the cwd of the line it belongs to. Bodies nothing claims stay in
    *pending* and are drained by the caller against the starting cwd.
    """
    out = []
    if not pending or "<<" not in seg:
        return out
    for term, _quoted, _tabstrip in _heredoc_ops(seg):
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
    backticks are masked and their bodies handed back; `$((...))` is arithmetic
    and is copied through verbatim; single-quoted text is literal and is copied
    through as-is; double-quoted text still expands, so it is scanned.

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
            j = _match_paren(text, i + 2)
            out.append(text[i:j])
            i = j
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
_STDIN_OPERANDS = ("-", "/dev/stdin", "/dev/fd/0", "/proc/self/fd/0",
                   "/proc/thread-self/fd/0")
_FD_DIRS = ("/dev/fd", "/proc/self/fd", "/proc/thread-self/fd")


def is_stdin_operand(tok: str) -> bool:
    """True when *tok* names this process's stdin, in any spelling procfs
    provides. `-` is the shell convention; the rest are real paths."""
    if tok == "-" or tok in _STDIN_OPERANDS:
        return True
    head, sep, base = tok.rpartition("/")
    if not sep or base != "0":
        return False
    if head in _FD_DIRS:
        return True
    parts = head.split("/")
    return (len(parts) == 4 and parts[0] == "" and parts[1] == "proc"
            and parts[2].isdigit() and parts[3] == "fd")


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


def stdin_is_program(tokens: list) -> bool:
    """True when this command runs whatever arrives on its STDIN.

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
        return False
    host = os.path.basename(tokens[0])
    if not is_code_host(host):
        return False
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
                return False
            if tok in stdin_flags:
                return True
            # a short-option BUNDLE: `bash -se` is `bash -s -e`
            if not tok.startswith("--") and any(
                    len(f) == 2 and f[1] in tok[1:] for f in stdin_flags):
                return True
            if tok in valued or name in valued:
                i += 1 if "=" in tok else 2
                continue
            i += 1
            continue
        if is_stdin_operand(tok):
            return True
        return False                 # a script operand: stdin is its input
    return True                      # no operand at all: stdin is the program


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


def stdin_program_host(opening: str, here: str, split_subcmds) -> str:
    """The interpreter on *opening* that reads its program from stdin, else "".

    The whole LINE is read rather than one sub-command, because the receiver of
    a heredoc need not be the command that opens it: `cat <<'EOF' | python3 -`
    declares the body on `cat` and executes it on `python3`.
    """
    import shlex
    for seg in split_subcmds(opening or ""):
        try:
            toks = shlex.split(seg)
        except ValueError:
            toks = seg.split()
        toks = strip_group_openers(toks)
        _redirects, toks = redirect_targets(toks)
        toks, _here = peel_wrappers(peel_env(toks), here)
        if stdin_is_program(toks):
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
# Two SIZE bounds, because the segment budget can only be spent once the text
# has been split and the splitting is itself O(characters) of pure-Python char
# loop. Both measured on this box at 512 KiB, worst line shape:
#   `_split_subcmds` + `split_command_substitutions` over the parsed text  1.7 s
#   `split_heredocs` over a command that is nothing but openers            2.6 s
# `_MAX_PARSE_CHARS` bounds the FIRST pair and is measured against the command
# with data heredoc bodies REMOVED, so `cat > f <<'EOF'` writing a megabyte
# stays allowed and stays cheap (99 ms at 512 KiB, its body is never
# tokenized). `_MAX_COMMAND_CHARS` bounds the raw text before anything is read,
# because `cmd.split("\n")` on an unbounded string is a memory decision rather
# than a parse decision.
_MAX_PARSE_CHARS = 256 * 1024
_MAX_COMMAND_CHARS = 4 * 1024 * 1024


class ParseTooLarge(Exception):
    """The command has more sub-commands than the parse budget allows, so no
    verdict can be reached by reading it. Denied, never dropped."""


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
        budget = [_MAX_SEGMENTS]
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
    if len(body_cmd) > _MAX_PARSE_CHARS:
        raise ParseTooLarge(
            f"{len(body_cmd)} characters of command line to parse, past the "
            f"{_MAX_PARSE_CHARS} this gate reads inside the harness timeout")
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
    for opening, body, quoted in heredocs:
        terms = [t for t, _q, _s in _heredoc_ops(opening)]
        i = nth.get(opening, 0)
        nth[opening] = i + 1
        term = terms[i] if i < len(terms) else (terms[0] if terms else "")
        pending.setdefault(term, []).append((opening, body, quoted))
    hits = []
    here0 = here
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
                    body = shlex.split(m.group(1))
                except ValueError:
                    body = []
                if body:
                    hits.extend(scan(body[0], here, depth + 1, budget, subs))
                    continue
        try:
            tokens = shlex.split(seg)
        except ValueError:
            tokens = seg.split()
        redirects, tokens = redirect_targets(tokens)
        for target in redirects:
            # `echo hi > $(echo <kdir>)/ptable.json` (QA cycle 12 C1): the
            # destination is computed by a command, so the literal path is not
            # in the token and never was. The body's text answers instead.
            if subst_names_kernel_state(target, subs, kdir):
                hits.append(("state", kdir, ">"))
            hits.append(("path", resolve(target, here), ">"))
        pre_peel = list(tokens)
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
            for target in names_kernel_state(pre_peel, here, kdir):
                hits.append(("state", target, host or "assignment"))
            for tok in pre_peel:
                if subst_names_kernel_state(tok, subs, kdir):
                    hits.append(("state", kdir, host or "assignment"))
                    break
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
        if not tokens:
            continue
        if tokens[0] in ("cd", "pushd") and len(tokens) > 1:
            here = resolve(tokens[1], here)
            continue
        if is_release(tokens):
            hits.append(("release", None, "octo --release"))
            continue
        base = os.path.basename(tokens[0])
        # a wrapped or non-anchored `-c` form the raw-segment match above missed
        if depth < _MAX_DEPTH and _interp_base(base) in _C_HOSTS and "-c" in tokens:
            i = tokens.index("-c")
            if i + 1 < len(tokens):
                hits.extend(scan(tokens[i + 1], here, depth + 1, budget, subs))
                continue
        if base == "git":
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
        if base in _MUTATORS:
            for target in mutation_targets(base, tokens[1:]):
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
        for opening, body, quoted in items:
            hits.extend(heredoc_hits(opening, body, quoted, here0, kdir, depth,
                                     split_subcmds, budget, subs))
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
    for opening, body, quoted in _claim_heredocs(seg, pending):
        hits.extend(heredoc_hits(opening, body, quoted, here, kdir, depth,
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


def heredoc_hits(opening: str, body: str, quoted: bool, here: str, kdir: str,
                 depth: int, split_subcmds, budget: list = None,
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
        _masked, body_subs = split_command_substitutions(body)
        for sub_body in body_subs.values():
            hits.extend(scan(sub_body, here, depth + 1, budget, subs))
    host = stdin_program_host(opening, here, split_subcmds)
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
                           "limit": _MAX_SEGMENTS})
        deny(
            f"KERNEL ISOLATION: this command has more than {_MAX_SEGMENTS} "
            f"sub-commands to parse ({exc}), which is past the budget this gate "
            "can read inside the harness timeout. A parse that cannot finish "
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
    for kind, target, verb in hits:
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
    for kind, target, verb in hits:
        if kind == "state":
            continue          # floor-only: already tested above
        if kind in ("glob", "iglob"):
            owner, row = glob_owner(target, table, pid, kind == "iglob")
        else:
            owner, row = kernel_proc.lane_owner(target, table, ignore=pid)
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
