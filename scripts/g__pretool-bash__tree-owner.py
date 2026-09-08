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

NAMED RESIDUALS, measured as passing and deliberately not covered here. The list
is pinned by a test, so it stays equal to what the gate actually does:
`rsync --delete`, `shred`, `perl -pi` AGAINST A LANE (against the KERNEL
DIRECTORY they are denied, see below);
`git apply|rebase|merge|pull|cherry-pick|revert`; variable and brace expansion
OTHER than HOME (`rm -rf $DIR`, `rm -rf {pkg,x}`, unknowable without running the
shell); a `-c` body nested deeper
than 3; and xargs fed from STDIN (`cat list | xargs rm`, `xargs rm < list`),
where the targets never appear in the command at all. Each is a distinct verb
table or an evaluator, not a gap in this one, and none is the weekend shape.

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
program and no parser will tokenize it out. `touch`, `chmod`, `chattr` and `dd
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


def _shell_c():
    """Borrow the `<shell> -c <body>` detector the receipt gate already proves
    (receipt_ledger.py:79). One regex for the whole brain, same reason as the
    splitter: a second copy drifts and the drift is invisible until a deny fails
    to fire."""
    import importlib.util
    path = os.path.join(_HERE, "receipt_ledger.py")
    spec = importlib.util.spec_from_file_location("receipt_ledger_borrow", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._SHELL_C


def _dim_helpers():
    """Borrow the command-boundary splitter and the broad-stage classifier the
    dimension gate already proves (dimension-awareness-hook.py:214,:259). One
    parser for the whole brain: a second copy would drift and the drift would be
    invisible until a deny failed to fire."""
    import importlib.util
    path = os.path.join(_HERE, "dimension-awareness-hook.py")
    spec = importlib.util.spec_from_file_location("dimension_awareness_hook", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._split_subcmds, mod._broad_git_verb


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


def peel_wrappers(tokens: list, here: str) -> tuple:
    """(tokens with wrapper prefixes removed, the cwd they leave behind).

    `env -C <dir> rm x` and `sudo -D <dir> rm x` move the directory a relative
    target resolves against, so the peel returns it rather than dropping it."""
    while tokens and os.path.basename(tokens[0]) in _WRAPPERS:
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
    return tokens, here


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
_BROAD_ADD = ("-u", "--update", "./", ":/", ":(top)")
_MAX_DEPTH = 3


def scan(command: str, cwd: str, depth: int = 0) -> list:
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
    hits = []
    for seg in split_subcmds(command or ""):
        seg = seg.strip().rstrip(";").strip()
        # a subshell or group: `(rm -rf pkg)` is a command, not a token soup
        if depth < _MAX_DEPTH and seg[:1] in ("(", "{"):
            inner = seg[1:].strip()
            if inner[-1:] in (")", "}"):
                inner = inner[:-1]
            hits.extend(scan(inner, here, depth + 1))
            continue
        if shell_c is not None:
            m = shell_c.match(seg)
            if m:
                try:
                    body = shlex.split(m.group(1))
                except ValueError:
                    body = []
                if body:
                    hits.extend(scan(body[0], here, depth + 1))
                    continue
        try:
            tokens = shlex.split(seg)
        except ValueError:
            tokens = seg.split()
        redirects, tokens = redirect_targets(tokens)
        for target in redirects:
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
        if host in _CODE_HOSTS:
            if code_names_kernel_state(seg, kdir):
                hits.append(("state", kdir, host))
        elif host not in _KSTATE_READONLY and not (
                host == "find" and not find_targets(tokens[1:])[0]):
            for target in names_kernel_state(pre_peel, here, kdir):
                hits.append(("state", target, host or "assignment"))
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
        if depth < _MAX_DEPTH and base.rstrip("0123456789") in _C_HOSTS and "-c" in tokens:
            i = tokens.index("-c")
            if i + 1 < len(tokens):
                hits.extend(scan(tokens[i + 1], here, depth + 1))
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
