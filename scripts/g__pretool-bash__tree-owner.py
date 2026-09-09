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

NAMED RESIDUALS, measured as passing and deliberately not covered here. The list
is pinned by a test, so it stays equal to what the gate actually does:
`rsync --delete`, `shred`, `ln -sf`, `perl -pi`; a `python -c` body (only
best-effort, scanned as shell text) including one aimed at the state dir;
`git apply|rebase|merge|pull|cherry-pick|revert`; brace expansion
(`rm -rf {pkg,x}`, unknowable without running the shell) and a variable NOBODY here can read
(`rm -rf $UNSET`, `export DIR=$OTHER && rm -rf $DIR`); a `-c` body nested deeper
than 3; and xargs fed from STDIN (`cat list | xargs rm`, `xargs rm < list`),
where the targets never appear in the command at all. Each is a distinct verb
table or an evaluator, not a gap in this one, and none is the weekend shape.

The kernel's own state is not a lane but a floor: any mutation targeting
`~/.claude/.cache/kernel` (the process table, the journals, the locks) is denied
for EVERY hooked process, this gate included, and so is a mutation of any
ANCESTOR of it by the same prefix test (`~/.claude/.cache`, `~/.claude`, `$HOME`
as the target of an `rm -rf`), since a command that takes the parent takes the
ledger with it. `touch`, `chmod`, `chattr` and `dd of=` are read for this floor
only, never as lane writes. A process that can rewrite the table can grant itself
any lane and erase the record. The operator's terminal is not hooked and stays
the only writer.

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
    age = kernel_proc.process_age(pid)
    kind = (row or {}).get("type") or ("main loop" if not (row or {}).get("ppid") else "subagent")
    when = "never journaled" if age < 0 else f"last active {int(age)}s ago"
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


# WHICH `NAME=value` IN A COMMAND LINE ACTUALLY CHANGES A LATER EXPANSION. Two
# spellings look identical and behave oppositely, and getting it wrong is a
# FAIL-OPEN in one direction, so the difference is the whole function:
#
#   HOME=/tmp/x; rm -f $HOME/.claude/settings.json    -> /tmp/x/... (a statement)
#   HOME=/tmp/x  rm -f $HOME/.claude/settings.json    -> the LIVE file (a prefix)
#
# A PREFIX assignment is put in the environment of the command it prefixes, and
# the shell has already expanded that command's own words by then, so `$HOME`
# on that line is still the old one. Reading a prefix as a statement would let
# one space in front of `rm` disarm the gate, so a segment holding anything
# other than assignments contributes NOTHING.
#
# Boundaries come from the brain's one splitter, borrowed not copied, for the
# same reason every other reader here borrows it: a raw-text scan matches
# `HOME=/tmp` inside `git commit -m "HOME=/tmp"` and shadows the real variable
# from inside a quoted argument. `shlex` then removes the quotes, so
# `export HOME="/tmp/a b"` keeps its space.
#
# A VALUE THIS PROCESS CANNOT EVALUATE (`$`, a backtick, a glob) maps to None,
# which means unknowable, not "use the environment": `export HOME=$REAL && rm
# -rf $HOME/.claude` abstains exactly as every unexpanded variable did before.
# LAST ASSIGNMENT WINS, and that ordering is a security property: taking the
# first would read `HOME=/tmp/x; HOME=<live>; rm -f $HOME/.claude/settings.json`
# as a sandbox while the shell aims at the brain.
_ASSIGN_HOSTS = ("export", "declare", "typeset", "readonly", "local")
_UNEVALUABLE = ("$", "`", "*", "?")


def command_assignments(command: str) -> dict:
    """{name: value or None} for the variables *command* sets for LATER words."""
    import shlex
    split_subcmds, _broad = _dim_helpers()
    out = {}
    for seg in split_subcmds(command or ""):
        try:
            toks = shlex.split(seg.strip().rstrip(";").strip())
        except ValueError:
            continue                      # unparseable: shadow nothing, deny wins
        if not toks:
            continue
        i = 1 if toks[0] in _ASSIGN_HOSTS else 0
        found = {}
        while i < len(toks) and is_env_assign(toks[i]):
            name, _eq, val = toks[i].partition("=")
            found[name] = None if any(c in val for c in _UNEVALUABLE) else val
            i += 1
        if i < len(toks) and toks[0] not in _ASSIGN_HOSTS:
            continue                      # a PREFIX: scoped to that one command
        out.update(found)                 # later segments overwrite earlier ones
    return out


def resolve(path: str, here: str) -> str:
    """One token, absolute. THE single place a written path becomes a real one.

    `~` is expanded and `$VAR` was not, and the order below is why that mattered
    more than it looks: the ABSOLUTENESS test runs after expansion, so
    `$HOME/.claude/x` was judged relative and joined onto the live cwd, landing
    on `<cwd>/$HOME/.claude/x` — a path that exists nowhere and matches nothing.
    Expanding here, before `isabs`, is the only place that can fix it: after the
    join the leading `/` is gone and no later reader can put it back. Tilde
    first, then the variable, which is the order the shell itself uses.
    `kernel_proc.expand_env` resolves only names this process can actually read
    and leaves the rest verbatim, so an undefined `$SOMEDIR` still reaches the
    callers carrying its `$` and keeps the unknowable reading it had."""
    path = kernel_proc.expand_env(os.path.expanduser(path))
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


_VALUED_MUTATOR_OPTS = {
    "truncate": ("-s", "--size", "-r", "--reference"),
    "sed": ("-e", "--expression", "-f", "--file", "-l", "--line-length"),
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


def mutation_targets(base: str, args: list) -> list:
    """Paths a non-git mutation writes. `cp` writes only its destination; `sed`
    writes nothing unless it is in-place."""
    positional = _positional(base, args)
    if base in ("rm", "mv", "tee", "unlink", "truncate"):
        return positional
    if base == "cp":
        return positional[-1:] if len(positional) >= 2 else []
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


_EXEC_MUTATORS = ("rm", "unlink", "shred", "truncate", "mv", "cp", "sed", "tee")
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
        probe = a if os.path.isabs(a) else os.path.join(base_dir, a)
        if os.path.exists(os.path.expanduser(probe)) or _is_glob(a):
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
    spec = os.path.expanduser(spec)
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

_TRIGGERS = ("git", "rm", "mv", "cp", "sed", "tee", ">", "octo", "find",
             "unlink", "truncate", "xargs", "delete",
             "touch", "chmod", "chattr", "dd")
_C_HOSTS = ("bash", "sh", "zsh", "dash", "python", "python3", "py")
_MUTATORS = ("rm", "mv", "cp", "sed", "tee", "unlink", "truncate")
# Verbs that can damage the kernel's ledger without being a lane write. They are
# tested against the state floor ONLY, never against a lane: `touch`/`chmod` on
# a sibling's file is not the collision this rule is about.
_STATE_VERBS = ("touch", "chmod", "chattr", "dd")
_BROAD_ADD = ("-u", "--update", "./", ":/", ":(top)")
_MAX_DEPTH = 3


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


def scan(command: str, cwd: str, depth: int = 0) -> list:
    """Every collision candidate in one command, as (kind, path, verb) where
    kind is 'release', 'tree', 'stage' or 'path'. Pure parsing: no process
    table, no liveness, no I/O beyond the existence probe a bare
    `git checkout <arg>` needs to tell a branch from a file."""
    if not any(t in command for t in _TRIGGERS):
        return []
    if depth == 0:
        # `resolve` below expands `$VAR` from this process's environment, which
        # is stale for any name THIS command assigns. Read those first, at the
        # top level only: a `-c` body or a subshell inherits the outer
        # assignments and must not clear them.
        kernel_proc.set_command_assignments(command_assignments(command))
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
                    body = _split_words(m.group(1))
                except ValueError:
                    body = []
                if body:
                    hits.extend(scan(body[0], here, depth + 1))
                    continue
        try:
            tokens = _split_words(seg)
        except ValueError:
            tokens = seg.split()
        redirects, tokens = redirect_targets(tokens)
        for target in redirects:
            hits.append(("path", resolve(target, here), ">"))
        tokens, here = peel_wrappers(peel_env(tokens), here)
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

    table = kernel_proc.read_ptable()      # the one ptable read of this call
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
                "included. Touch your own paths, or wait for that process to "
                f"exit (lanes free on the exit line, or after {kernel_proc.TTL}s "
                f"of silence). The operator can free a stuck one: `octo ps "
                f"--release {owner}` (Phase 1b; on a brain without it, edit the "
                "ptable row from the terminal)."
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
        sys.exit(0)  # fail-open: never break the user's tool call
