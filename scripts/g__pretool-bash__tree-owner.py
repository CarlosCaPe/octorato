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
        rec = {"kind": "deny", "gate": "tree-owner"}
        rec.update(fields)
        kernel_proc.append(pid, rec)
    except Exception:
        pass


def describe(pid: str, row: dict) -> str:
    age = kernel_proc.process_age(pid)
    kind = (row or {}).get("type") or ("main loop" if not (row or {}).get("ppid") else "subagent")
    when = "never journaled" if age < 0 else f"last active {int(age)}s ago"
    return f"pid {pid} ({kind}, {when})"


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


# Wrappers that prefix a command without changing what it does to the file
# system. `env -u CLAUDE_SESSION_ID octo ps --release ...` is the documented
# bypass attempt (v8-kernel.md section 2), so peeling these is part of the rule,
# not a nicety.
WRAPPERS = ("env", "command", "nohup", "sudo", "stdbuf")
_WRAPPER_OPTS = ("-u", "-C", "-S", "-i", "--unset", "--chdir", "--user")


def peel_wrappers(tokens: list) -> list:
    while tokens and os.path.basename(tokens[0]) in WRAPPERS:
        i = 1
        while i < len(tokens):
            tok = tokens[i]
            if tok in _WRAPPER_OPTS and i + 1 < len(tokens):
                i += 2
            elif tok.startswith("-") or is_env_assign(tok):
                i += 1
            else:
                break
        if i >= len(tokens):
            return []
        tokens = tokens[i:]
    return tokens


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


def mutation_targets(base: str, args: list) -> list:
    """Paths a non-git mutation writes. `cp` writes only its destination; `sed`
    writes nothing unless it is in-place."""
    positional = [a for a in args if not a.startswith("-")]
    if base in ("rm", "mv", "tee"):
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
    return []


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


def git_parse(tokens: list):
    """(repo_or_None, subcommand, rest) for a git invocation, honouring -C,
    --git-dir and --work-tree; None when the tokens are not a git command."""
    i, repo = 1, None
    while i < len(tokens):
        tok = tokens[i]
        if tok == "-C" and i + 1 < len(tokens):
            repo, i = tokens[i + 1], i + 2
        elif tok.startswith(("--git-dir=", "--work-tree=")):
            val = tok.split("=", 1)[1]
            repo, i = (val[:-5] if val.endswith("/.git") else val), i + 1
        elif tok in ("--git-dir", "--work-tree") and i + 1 < len(tokens):
            val = tokens[i + 1]
            repo, i = (val[:-5] if val.endswith("/.git") else val), i + 2
        elif tok.startswith("-"):
            i += 1
        else:
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
    if sub == "checkout" and "--" not in rest:
        return "git checkout <branch>"
    return None


def pathspecs(sub: str, rest: list, base_dir: str) -> list:
    """The paths a pathspec verb rewrites. After `--` every argument is a path;
    without it, only arguments that exist on disk are (so `git checkout main`
    stays a branch switch and is handled as a whole-tree verb instead)."""
    if sub not in ("checkout", "restore"):
        return []
    if "--" in rest:
        return [a for a in rest[rest.index("--") + 1:]]
    args = [a for a in rest if not a.startswith("-")]
    if sub == "restore":
        return args
    out = []
    for a in args:
        probe = a if os.path.isabs(a) else os.path.join(base_dir, a)
        if os.path.exists(os.path.expanduser(probe)):
            out.append(a)
    return out


# ── scan ────────────────────────────────────────────────────────────────────

# A command that contains none of these as a SUBSTRING can touch nothing this
# gate protects, so it never pays for the parse or for loading the splitter.
# Deliberately a superset (`rm` matches "confirm"): a cheap filter is allowed to
# be wrong in the direction of doing more work, never in the direction of
# skipping a command it should have read.
_TRIGGERS = ("git", "rm", "mv", "cp", "sed", "tee", ">", "octo")
_C_HOSTS = ("bash", "sh", "zsh", "dash", "python", "python3", "py")
_MAX_DEPTH = 3


def scan(command: str, cwd: str, depth: int = 0) -> list:
    """Every collision candidate in one command, as (kind, path, verb) where
    kind is 'release', 'tree' or 'path'. Pure parsing: no process table, no
    liveness, no I/O beyond the existence probe a bare `git checkout <arg>`
    needs to tell a branch from a file."""
    import shlex

    if not any(t in command for t in _TRIGGERS):
        return []
    split_subcmds, broad_git_verb = _dim_helpers()
    shell_c = _shell_c() if depth < _MAX_DEPTH else None
    here = kernel_proc.norm_path(cwd or os.getcwd())
    hits = []
    for seg in split_subcmds(command or ""):
        if shell_c is not None:
            m = shell_c.match(seg.strip())
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
            hits.append(("path", kernel_proc.norm_path(os.path.join(here, target)), ">"))
        tokens = peel_wrappers(peel_env(tokens))
        if not tokens:
            continue
        if tokens[0] == "cd" and len(tokens) > 1:
            nxt = os.path.expanduser(tokens[1])
            here = kernel_proc.norm_path(nxt if os.path.isabs(nxt) else os.path.join(here, nxt))
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
            broad, broad_repo = broad_git_verb(tokens)
            if broad:
                stage_dir = here
                if broad_repo:
                    broad_repo = os.path.expanduser(broad_repo)
                    stage_dir = kernel_proc.norm_path(
                        broad_repo if os.path.isabs(broad_repo)
                        else os.path.join(here, broad_repo))
                root = kernel_proc.enclosing_worktree_root(stage_dir) or stage_dir
                hits.append(("stage", kernel_proc.norm_path(root), f"git {broad}"))
                continue
            parsed = git_parse(tokens)
            if not parsed:
                continue
            repo, sub, rest = parsed
            base_dir = here
            if repo:
                repo = os.path.expanduser(repo)
                base_dir = kernel_proc.norm_path(
                    repo if os.path.isabs(repo) else os.path.join(here, repo))
            root = kernel_proc.enclosing_worktree_root(base_dir) or base_dir
            verb = whole_tree_verb(sub, rest)
            if verb:
                hits.append(("tree", kernel_proc.norm_path(root), verb))
            for spec in pathspecs(sub, rest, base_dir):
                spec = os.path.expanduser(spec)
                hits.append(("path",
                             kernel_proc.norm_path(spec if os.path.isabs(spec)
                                                   else os.path.join(base_dir, spec)),
                             f"git {sub}"))
            continue
        for target in mutation_targets(base, tokens[1:]):
            target = os.path.expanduser(target)
            hits.append(("path",
                         kernel_proc.norm_path(target if os.path.isabs(target)
                                               else os.path.join(here, target)),
                         base))
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
                "session, where no hook fires. If the holder is simply finished, "
                f"its lane frees on its own after {kernel_proc.TTL}s of silence."
            )
            return 0

    table = kernel_proc.read_ptable()      # the one ptable read of this call
    for kind, target, verb in hits:
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
                "one session need."
            )
        elif kind == "tree":
            deny(
                f"KERNEL ISOLATION: `{verb}` rewrites the whole working tree at "
                f"{target}, and {describe(owner, row)} holds a lane in it. This "
                "is the shape that wiped 14 files across three builders on one "
                "tree. Scope the change to your own paths, work in your own "
                "worktree, or wait for that process to exit (its lanes free on "
                f"its exit line, or after {kernel_proc.TTL}s of silence)."
            )
        else:
            deny(
                f"KERNEL ISOLATION: `{verb}` targets {target}, the lane of "
                f"{describe(owner, row)}. One writer per lane, the parent "
                "included. Touch your own paths, or wait for that process to "
                f"exit (lanes free on the exit line, or after {kernel_proc.TTL}s "
                f"of silence). The operator can free a stuck one: octo ps "
                f"--release {owner}"
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
