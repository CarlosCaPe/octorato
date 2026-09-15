#!/usr/bin/env python3
"""PreToolUse Bash hook — QA gate (FAIL-CLOSED for merge actions).

NOTE on security boundary: the regex command-matching below is a speed-bump for
honest mistakes; the AGENT-PROOF env channel (OCTO_MERGE_APPROVE, which an inline
env cannot pass to the harness-run hook) is the actual security boundary — shell
indirection (e.g. ``$(echo gh) pr merge``) can evade string-matching and that is
accepted residual risk by design.  Detection is now command-boundary-anchored:
the full command string is split on UNQUOTED shell separators (; && || | newline)
before pattern matching, so a publish pattern that appears only inside a quoted
argument (``git commit -m "gh pr merge 96"``) does NOT trigger the gate.
Shell indirection (``bash -c "..."``, ``$(...)``) remains accepted residual risk.

When a Bash command is detected as a merge action, this hook BLOCKS execution
unless an operator approval is present via one of two AGENT-PROOF env channels.
Detected forms: `gh pr merge`; `git push` directly to main/master; and the
gh api / curl API equivalents (a write call to REST `/pulls/<N>/merge`, a
GraphQL mergePullRequest mutation, `POST /repos/.../merges` into main/master, or
a `PATCH`/`DELETE` of `/git/refs/heads/(main|master)`). API reads pass; only a
write method or body flag qualifies. The two channels:

  1. OCTO_MERGE_APPROVE=<pr_number>  — env var, PR-scoped, AGENT-PROOF (preferred).
     A PreToolUse hook runs in the HARNESS process and does NOT inherit env vars
     the agent sets inline (e.g. `OCTO_MERGE_APPROVE=96 gh pr merge 96` does NOT
     reach this hook).  Only the operator, who exports the var in their shell
     before invoking Claude Code, can set it — making it a true operator signal.

  2. OCTO_QA_OK=1  — legacy blanket override; kept for back-compat but DISCOURAGED.
     Prefer OCTO_MERGE_APPROVE=<n>.

The file channel (~/.claude/connectome/merge-approvals.json, written by
octo-dim.py approve-merge) is NO LONGER an authorizer: an agent owns its own
process env, so it can strip the agent-shell markers (`env -u CLAUDECODE ...`)
or pass --i-am-the-operator and forge that file, which made it a self-approval
route. Only the harness env, which the agent's command-scoped env never reaches,
is a real boundary. octo-dim approve-merge is kept as an operator audit log
(listed by `approvals`), not a gate pass.

v7 (2026-09-05): approval is necessary, not sufficient. A merge also needs a QA
receipt for the PR in the receipt ledger (~/.claude/.cache/receipts/global.jsonl),
written by the SubagentStop hook from a QA subagent's QA-VERDICT/QA-SCOPE lines
and re-read from that agent's transcript. OCTO_QA_OK=1 is the explicit bypass.
Fail-closed ONLY for positively-identified merge commands.
Any parsing error on a non-merge command → exit 0 (fail-open).
Design mirrors grafo-gate.py: same I/O protocol, same stdin JSON shape.

Operator directive 2026-06-01: NO deploy without QA agent approval.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
# Force UTF-8 on stdout/stderr so the ✓ / ✗ / em-dash glyphs in reports
# survive on Windows shells defaulting to cp1252. Without this, a script
# can do its work correctly and still crash with UnicodeEncodeError when
# printing success. Applied repo-wide by _apply-utf8-reconfigure.py.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


# ---------------------------------------------------------------------------
# Anchored publish patterns — applied to the START of each sub-command token.
# Using ^\s* because after splitting we still want to tolerate leading spaces.
# ---------------------------------------------------------------------------

# gh pr merge <N> [flags]  — anchored at sub-command start
_PAT_GH_MERGE = re.compile(r"^\s*gh\s+pr\s+merge\b")

# git [-C <path>] [-c key=val] push [opts] <remote> <ref>
# Catches: git push origin main  /  git push origin "main"  /
#          git push origin +main  /  git push -u origin master  /
#          git -C /x push origin main  /  git push origin HEAD:main
# Does NOT catch: main-feature / feature/main-redesign / my-main /
#                 git push-mirror / git push-all (hyphenated, not a subcommand) /
#                 "push" appearing only inside a quoted arg of a different subcommand.
# FIX 1+2: push must be the git SUBCOMMAND — only the standard global flags
# -C <path> and -c <key=val> are allowed between `git` and `push`.
# `push(?=\s)` requires whitespace after push, so `push-mirror` is rejected.
_PAT_GIT_PUSH = re.compile(
    r"^\s*git\s+"
    r"(?:-C\s+\S+\s+|-c\s+\S+\s+)*"
    r"push(?=\s)"
    r"[^|&;]*?"
    r'(?:[\s:/\'"+])(?:HEAD:)?\+?(main|master)(?=$|\s|:|[\'"])'
)

# Unanchored twins, used ONLY inside a sub-command already known to start with
# a wrapper. Same bodies, no `^\s*`.
# `(?<![\w-])` so `laugh pr merge` and `legit push to master` are not the tool,
# and the push body is BOUNDED. Unanchored, the lazy `[^|&;]*?` re-scanned to the
# end of the sub-command once per `git push` occurrence: QA measured 88k of a
# wrapped line at 8.0 s against this hook's 5 s timeout, and a killed PreToolUse
# hook writes no stdout, which the harness reads as ALLOW. That made a bypass
# this gate did not have before: a slow sub-command first, the bare publish
# behind it. A real `git push origin main` puts the branch within a couple of
# hundred characters of `push`, so the cap costs nothing real and makes each
# attempt O(1) instead of O(len).
_SEARCH_GH_MERGE = re.compile(
    _PAT_GH_MERGE.pattern.replace(r"^\s*", r"(?<![\w-])", 1))
_SEARCH_GIT_PUSH = re.compile(
    _PAT_GIT_PUSH.pattern.replace(r"^\s*", r"(?<![\w-])", 1)
                          .replace(r"[^|&;]*?", r"[^|&;]{0,200}?", 1))


_QUOTED_SPAN = re.compile(r"\"[^\"]*\"|'[^']*'")


def _outside_quotes(sub: str) -> str:
    """*sub* with quoted spans blanked, same length so nothing else shifts.

    The unanchored search must not read an ARGUMENT as a command. QA measured
    the cost of letting it: `grep -rn "<the merge form>" scripts/` behind
    `timeout` gated, and since that line carries no PR number the gate asks for
    an approval that cannot be given, leaving the blanket `OCTO_QA_OK=1` as the
    only exit. An over-gate that expensive is not the safe direction; it is how
    a gate gets switched off. Text the shell will not execute is text this
    search does not read."""
    return _QUOTED_SPAN.sub(lambda m: " " * (m.end() - m.start()), sub)


def _api_write_action_anywhere(sub: str):
    """The API form inside a wrapped sub-command: the tool name may sit after
    the wrapper's flags, so the `^` on `_PAT_API_TOOL` is what has to go."""
    m = re.search(_PAT_API_TOOL.pattern.replace(r"^\s*", "", 1), sub)
    if not m:
        return None
    return _api_write_action(sub[m.start():])


# Extracts the PR number from `gh pr merge <N> [flags]`
# (?=\s|$) anchors the digit capture to a whole token.
_PR_NUM_RE = re.compile(r"^\s*gh\s+pr\s+merge\s+(\d+)(?=\s|$)")

# API-form publish — the command-shape bypass of `gh pr merge` / `git push`.
# Intent over mechanism (agent-proof-approval-gate skill, OpenBot lesson #2):
# a REST or GraphQL call that merges a PR, merges a branch INTO main/master, or
# force-updates the main/master ref has the same effect as the CLI forms, so it
# gets the same gate. Covers `gh api` and `curl`. Only WRITE calls gate: a plain
# GET to any of these paths is a read and passes (else the gate over-fires and
# gets switched off). A real write must carry a mutating method or a body flag,
# and that is exactly the token the agent cannot omit and still write.
_PAT_API_TOOL = re.compile(r"^\s*(?:gh\s+api|curl)\b")
_API_WRITE = re.compile(
    r"(?:--method|--request|-X)\s*=?\s*(?:PUT|POST|PATCH|DELETE)\b"
    r"|(?:^|\s)(?:-f|-F|--field|--raw-field|--input|-d|--data|--data-raw|--data-binary)(?=[=\s]|$)",
    re.IGNORECASE,
)
_API_PR_NUM_RE = re.compile(r"/pulls/(\d+)/merge\b")
_API_GRAPHQL_MERGE = re.compile(r"mergePullRequest\b")
_API_MERGES_RE = re.compile(r"repos/[\w.-]+/[\w.-]+/merges\b")
_API_REFS_RE = re.compile(r"git/refs\b")
_API_MASTER_BRANCH_RE = re.compile(r"heads/(main|master)\b")
# owner/repo out of any of the three REST paths, to protect-check the TARGET
# repo (not cwd: the agent can fire the call from anywhere). No path repo
# (e.g. GraphQL) → unresolvable → gate, fail-closed.
_API_REPO_ANY_RE = re.compile(
    r"repos/([\w.-]+/[\w.-]+?)/(?:pulls/\d+/merge|merges|git/refs)\b"
)
# base branch of a POST /merges, so only a merge INTO main/master gates.
_API_BASE_RE = re.compile(
    r'(?:(?:-f|-F|--field|--raw-field)\s*=?\s*base=|"base"\s*:\s*"|(?:^|\s)base=)([\w./-]+)',
    re.IGNORECASE,
)


def _api_write_action(sub: str) -> str | None:
    """If *sub* (already leading-stripped) is an API WRITE that merges a PR,
    merges a branch into main/master, or updates the main/master ref, return a
    scope token for approval matching (the PR number, or 'main'/'master').
    Otherwise None. Only write methods qualify, so API reads pass."""
    if not _PAT_API_TOOL.match(sub) or not _API_WRITE.search(sub):
        return None
    m = _API_PR_NUM_RE.search(sub)          # PR merge, REST
    if m:
        return m.group(1)
    if _API_GRAPHQL_MERGE.search(sub):      # PR merge, GraphQL mutation
        return "unknown"
    if _API_REFS_RE.search(sub):            # ref write to a head
        bm = _API_MASTER_BRANCH_RE.search(sub)
        return bm.group(1) if bm else None
    if _API_MERGES_RE.search(sub):          # branch merge into base
        bm = _API_BASE_RE.search(sub)
        base = bm.group(1).lower() if bm else None
        if base is None or base in ("main", "master"):
            return base or "master"         # unparseable base → fail-closed
        return None                         # merge into a non-default branch
    return None

# Set True by main() the moment a publish/merge sub-command is positively
# identified. The __main__ crash handler keys fail-open vs fail-closed off it.
_PUBLISH_IDENTIFIED = False

# ---------------------------------------------------------------------------
# Repo scoping (root-cause fix, 2026-06-04). The gate guards PROTECTED repos:
# the brain (~/.claude, including its linked worktrees) plus any repo listed in
# the operator-owned, gitignored company/config/protected-repos.json
# ({"protected": ["~/Documents/github/<deploy-arm>", ...]}). A push to main of
# an ordinary working repo is daily flow, not a guarded merge; gating every
# repo's main produced constant false blocks. Resolution is DETERMINISTIC
# (paths and git-config file reads only — the agent classifies nothing) and
# the direction stays fail-closed: unresolvable target → still gated. Only a
# positively-identified NON-protected target is ungated.
# ---------------------------------------------------------------------------

_BRAIN = Path.home() / ".claude"
_PROTECTED_CFG = _BRAIN / "company" / "config" / "protected-repos.json"


def _protected_roots() -> list[Path]:
    roots = [_BRAIN]
    try:
        data = json.loads(_PROTECTED_CFG.read_text(encoding="utf-8"))
        for item in data.get("protected", []):
            roots.append(Path(os.path.expanduser(str(item))))
    except Exception:
        pass  # config absent → only the brain is protected
    out: list[Path] = []
    for r in roots:
        try:
            out.append(r.resolve())
        except Exception:
            continue
    return out


def _remote_slug(repo_root: Path) -> str | None:
    """owner/repo (lowercase) parsed from <root>/.git/config; file reads only."""
    try:
        cfg = (repo_root / ".git" / "config").read_text(encoding="utf-8")
        m = re.search(r"url\s*=\s*\S*github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?\s*$",
                      cfg, re.MULTILINE)
        return m.group(1).lower() if m else None
    except Exception:
        return None


def _canon_slug(s: str) -> str | None:
    """Canonical owner/repo (lowercase) from any -R form: bare slug, https URL,
    ssh host:owner/repo, with or without trailing .git or slash. The INPUT side
    must pass through the same canonicalizer as the known side, else '.git' and
    ssh variants of the brain's own slug classify as ungated (QA finding 1)."""
    s = s.strip().strip("'\"")
    m = re.search(r"(?:github\.com[:/])?([\w.-]+/[\w.-]+?)(?:\.git)?/?$", s)
    return m.group(1).lower() if m else None


def _repo_root_and_gitdir(start: str):
    """Walk up from *start* to the first .git entry. Returns (worktree_root,
    resolved_gitdir_or_None). A linked worktree's .git FILE points into the
    main repo's .git dir — that is how a brain worktree is recognized."""
    try:
        p = Path(start).resolve()
    except Exception:
        return None, None
    while True:
        g = p / ".git"
        if g.is_dir():
            return p, g
        if g.is_file():
            try:
                m = re.search(r"gitdir:\s*(.+)", g.read_text(encoding="utf-8"))
                if m:
                    gd = Path(m.group(1).strip())
                    gd = gd if gd.is_absolute() else (p / gd)
                    return p, gd.resolve()
            except OSError:
                pass
            return p, None
        if p.parent == p:
            return None, None
        p = p.parent


def _effective_cwd(cmd: str, matched_sub: str, session_cwd: str) -> str:
    """Session cwd adjusted by any `cd` sub-commands BEFORE the matched one.
    Only plain `cd <path>` is parsed; `cd -`, `pushd`, subshells are ignored,
    which leaves cwd unadjusted and can only OVER-gate, never under-gate."""
    cwd = session_cwd or os.getcwd()
    for raw in _split_subcmds(_join_continuations(cmd)):
        if raw == matched_sub:
            break
        s = _strip_leading(raw).strip()
        m = re.match(r"^cd\s+(\S+)", s)
        if m:
            p = os.path.expanduser(m.group(1).strip("'\""))
            cwd = p if os.path.isabs(p) else os.path.join(cwd, p)
    return cwd


def _is_protected_target(cmd: str, matched_sub: str, session_cwd: str):
    """True = protected, False = positively NOT protected, None = unresolvable
    (treated as protected: the gate stays fail-closed when unsure)."""
    sub = _strip_leading(matched_sub)

    # gh api / curl write (PR merge, branch merge into main/master, or a
    # main/master ref update): the target repo is in the REST path, NOT the cwd
    # (the agent can fire the API call from anywhere, so cwd-based resolution
    # would under-gate). Resolve owner/repo from the path and compare against
    # the protected slugs. GraphQL / any form with no path repo is unresolvable
    # → None (gate, fail-closed).
    if _api_write_action(sub) is not None:
        m = _API_REPO_ANY_RE.search(sub)
        if not m:
            return None
        slug = _canon_slug(m.group(1))
        known = {s for s in (_remote_slug(r) for r in _protected_roots()) if s}
        if not known or slug is None:
            return None
        return slug in known

    # gh pr merge with an explicit -R/--repo slug: compare against the slugs
    # of the protected roots. No parsable slugs → None (gate).
    if _PAT_GH_MERGE.match(sub):
        m = re.search(r"(?:^|\s)(?:-R|--repo)[=\s]+(\S+)", sub)
        if m:
            slug = _canon_slug(m.group(1))
            known = [s for s in (_remote_slug(r) for r in _protected_roots()) if s]
            if not known or slug is None:
                return None  # unparseable either side → gate
            return slug in known  # exact canonical match, no suffix tricks

    # Resolve the repo the command operates on: git -C wins, else effective cwd.
    # A relative -C is joined against the effective SESSION cwd, never the
    # hook's own cwd (QA finding 3: right answer, deterministic reason).
    target = None
    m = re.match(r"^\s*git\s+((?:(?:-C|-c)\s+\S+\s+)*)", sub)
    if m and m.group(1):
        c = re.search(r"-C\s+(\S+)", m.group(1))
        if c:
            raw = os.path.expanduser(c.group(1).strip("'\""))
            base = _effective_cwd(cmd, matched_sub, session_cwd)
            target = raw if os.path.isabs(raw) else os.path.join(base, raw)
    if target is None:
        target = _effective_cwd(cmd, matched_sub, session_cwd)

    root, gitdir = _repo_root_and_gitdir(target)
    if root is None:
        return None
    candidates = [root] + ([gitdir] if gitdir is not None else [])
    for cand in candidates:
        for prot in _protected_roots():
            if cand == prot or prot in cand.parents:
                return True
    # A CLONE of a protected repo living anywhere is still protected: compare
    # the target's own remote slug against the protected slugs (QA finding 2).
    tgt_slug = _remote_slug(root)
    if tgt_slug:
        known = {s for s in (_remote_slug(r) for r in _protected_roots()) if s}
        if tgt_slug in known:
            return True
    return False


# FIX 5: join backslash-newline continuations before any splitting so that
# `gh pr \<newline>merge 96` is treated as a single token.
def _join_continuations(cmd: str) -> str:
    """Replace backslash-newline pairs with a single space."""
    return re.sub(r"\\\n", " ", cmd)


# Strip leading wrapper tokens from an already-split sub-command before pattern
# matching. Applied PER sub-command so it never crosses a real separator boundary.
# Covers: grouping openers, env-assignments (VAR=val), redirections, and EVERY
# command-taking wrapper, `env` and `command` among them, through the shared
# parser's per-wrapper spec (`_wrapper_specs`).
# SECURITY: without the peel, `env A=1 gh pr merge`, `command gh pr merge` or
# `timeout 300 gh pr merge` evade the ^gh/^git anchor and bypass the approval
# gate. The last one was not hypothetical: it merged PR #307 on 2026-09-15.
# Iterative so the wrappers may interleave (`env A=1 sudo nohup timeout 300 ...`).
# The spec is per wrapper, never a flat option set: a flag that takes a value for
# one wrapper and not for another made the peel eat the command itself, which
# looks like coverage and is the opposite. The real approval channels stay the
# agent-proof env/file, never an inline token.
_W_GROUP = re.compile(r"^[({]\s*")
_W_ASSIGN = re.compile(r"^[A-Za-z_]\w*=\S*\s+")
_W_REDIR = re.compile(r"^\d*[<>]+\S*\s+")
_W_ENV = re.compile(r"^env\b\s*")
_W_ENVARG = re.compile(r"^(?:-\S+|[A-Za-z_]\w*=\S*)\s+")
_W_COMMAND = re.compile(r"^command\s+")


# Wrapper programs that take a COMMAND as their argument, peeled for exactly the
# reason `env` and `command` already were: every pattern below anchors at the
# START of a sub-command, so a prefix left in place is a prefix that disarms the
# gate. Measured 2026-09-15: `timeout 300 gh pr merge 307 --squash` ALLOWED
# while the bare form DENIED, and that form merged a PR without the operator's
# approval.
#
# The spec is PER WRAPPER and that is the whole correctness of it. A first cut
# flattened every wrapper's option list into one set, and QA measured what the
# flattening costs: `-E` takes a value for `xargs`, so `sudo -E gh pr merge 9`
# ate `gh` and the remainder `pr merge 9` matched nothing. Six spellings became
# NEW bypasses, `sudo -E` and `sudo -n` among them, which are the two most
# common sudo spellings in scripts. A peel that eats the command is worse than
# no peel, because it looks like coverage.
#
# So the shared parser's table is the source for every wrapper it knows, read
# lazily and only when a sub-command actually starts with a wrapper name. The
# import costs 14 ms in-process, median of 9 (a first measurement said ~30 ms by
# differencing two subprocesses, which charged interpreter start to the import
# and was wrong). Small, but it is per Bash call and the unwrapped 99% should
# not pay it.
_SHARED_PARSER = Path(__file__).resolve().parent / "g__pretool-bash__tree-owner.py"

# Wrappers the shared parser does not carry, in ITS shape so the two compose.
# `arg` is how many POSITIONALS the wrapper eats before the command starts:
# `flock /tmp/x cmd` and `chrt 50 cmd` eat one, the rest eat none.
_EXTRA_WRAPPERS = {
    "setsid": {"valued": (), "cd": (), "arg": 0},
    "ionice": {"valued": ("-c", "--class", "-n", "--classdata", "-p", "--pid"),
               "cd": (), "arg": 0},
    "doas": {"valued": ("-u", "-C"), "cd": (), "arg": 0},
    "flock": {"valued": ("-w", "--wait", "--timeout", "-E", "--conflict-exit-code"),
              "cd": (), "arg": 1},
    "chrt": {"valued": ("-p", "--pid"), "cd": (), "arg": 1},
}
# Names only, so the cheap test that decides whether to import costs a set hit.
_WRAPPER_NAMES = frozenset({
    "env", "sudo", "command", "nohup", "exec", "time", "nice", "timeout",
    "stdbuf", "xargs", "setsid", "ionice", "doas", "flock", "chrt",
})
_WRAPPER_SPECS = None


def _wrapper_specs() -> dict:
    """Per-wrapper {valued, cd, arg}, the shared parser's table plus the extras.

    Falls back to the extras alone if the import fails. That direction is safe:
    an unknown wrapper is simply not peeled, which leaves the gate where it was
    before this change rather than eating a command it cannot parse."""
    global _WRAPPER_SPECS
    if _WRAPPER_SPECS is not None:
        return _WRAPPER_SPECS
    specs = dict(_EXTRA_WRAPPERS)
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_qmg_shared_parser", str(_SHARED_PARSER))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for name, entry in mod._WRAPPERS.items():
            # Validated, not trusted. An entry that is not a mapping made
            # `_peel_wrapper` raise, the exception escaped the finder, and the
            # gate failed OPEN for the WHOLE command, the bare publish in a
            # later sub-command included. A table this gate does not own is
            # untrusted input like any other.
            if isinstance(entry, dict):
                specs[name] = entry
    except Exception:
        pass
    _WRAPPER_SPECS = specs
    return specs


_ENV_ASSIGN_TOKEN = re.compile(r"^[A-Za-z_]\w*=")
_WRAPPER_HEAD = re.compile(r"^([^\s;&|]+)(\s+)")
# A token is a run of quoted segments and unquoted non-space characters, so
# `-u "car los"` is TWO tokens and not four. `\S+` split it at the space and
# the second half stopped the peel, which QA measured as a live bypass: the
# quoted spelling ALLOWED while the unquoted one denied. The shell reads the
# quotes; so must anything that counts tokens.
_WRAPPER_TOKEN = re.compile(r"""^((?:"[^"]*"|'[^']*'|[^\s"'])+)(\s*)""")


def _peel_wrapper(s: str):
    """Guarded front door. The table comes from another file, so ANY shape
    of it that raises degrades to 'not peeled' instead of deciding the gate:
    QA measured `valued: None` and `arg: \"1\"` crashing the finder and
    failing OPEN for the whole command, one level below the non-mapping case
    the isinstance check already caught."""
    try:
        return _peel_wrapper_unguarded(s)
    except Exception:
        return None


def _peel_wrapper_unguarded(s: str):
    """*s* with ONE leading wrapper (its flags, their values, its positionals)
    removed, or None when it does not start with one. Basename-matched, so
    `/usr/bin/timeout` peels exactly as `timeout` does."""
    head = _WRAPPER_HEAD.match(s)
    if not head:
        return None
    name = os.path.basename(head.group(1))
    if name not in _WRAPPER_NAMES:
        return None
    spec = _wrapper_specs().get(name)
    if not isinstance(spec, dict):
        return None          # unknown or unusable: leave the sub-command alone
    takes_value = set(spec.get("valued", ())) | set(spec.get("cd", ()))
    rest = s[head.end():]
    eat = spec.get("arg", 0)
    while rest:
        tok = _WRAPPER_TOKEN.match(rest)
        if not tok:
            break
        word = tok.group(1)
        if word.startswith("-"):
            rest = rest[tok.end():]
            # `--flag=value` carries its own value; only the bare spelling of a
            # value-taking flag reaches for the next token.
            if "=" not in word and word in takes_value:
                nxt = _WRAPPER_TOKEN.match(rest)
                if nxt:
                    rest = rest[nxt.end():]
            continue
        if _ENV_ASSIGN_TOKEN.match(word):
            rest = rest[tok.end():]          # `env A=1 B=2 cmd`
            continue
        if eat:
            eat -= 1
            rest = rest[tok.end():]
            continue
        break
    return rest


def _strip_leading(s: str) -> str:
    """Return *s* with leading grouping / env-assignments / redirections / the
    `env` wrapper (and its flags+assigns) / the `command` builtin / any
    command-taking wrapper (`timeout`, `sudo`, `nohup`, ...) removed."""
    s = s.lstrip()
    prev = None
    while s != prev:
        prev = s
        peeled = _peel_wrapper(s)
        if peeled is not None:
            s = peeled
            continue
        for pat in (_W_GROUP, _W_ASSIGN, _W_REDIR, _W_COMMAND):
            m = pat.match(s)
            if m:
                s = s[m.end():]
                break
        else:
            m = _W_ENV.match(s)
            if m:
                s = s[m.end():]
                while True:
                    m2 = _W_ENVARG.match(s)
                    if not m2:
                        break
                    s = s[m2.end():]
    return s


def _split_subcmds(cmd: str) -> list[str]:
    """Split *cmd* on unquoted shell separators (;  &&  ||  |  newline).

    Tracks single-quote and double-quote state so that separators inside
    quoted strings are treated as literal characters and do NOT cause a split.
    Returns a list of raw sub-command strings (may be empty after stripping).
    """
    parts: list[str] = []
    buf: list[str] = []
    in_single = False
    in_double = False
    i = 0
    n = len(cmd)
    while i < n:
        ch = cmd[i]
        if ch == "'" and not in_double:
            in_single = not in_single
            buf.append(ch)
            i += 1
        elif ch == '"' and not in_single:
            in_double = not in_double
            buf.append(ch)
            i += 1
        elif not in_single and not in_double:
            # Check for two-char separators first
            two = cmd[i:i + 2]
            if two in ("&&", "||"):
                parts.append("".join(buf))
                buf = []
                i += 2
            elif ch in (";", "|", "\n"):
                parts.append("".join(buf))
                buf = []
                i += 1
            else:
                buf.append(ch)
                i += 1
        else:
            buf.append(ch)
            i += 1
    parts.append("".join(buf))
    return parts


def _find_publish_subcmd(cmd: str) -> str | None:
    """Return the first sub-command that matches a publish pattern, or None.

    Processing order (FIX 5 → split → FIX 3+4 → pattern):
      1. Join backslash-newline continuations (FIX 5) so multi-line commands
         are not split at the wrong boundary.
      2. Split on unquoted shell separators (; && || | newline).
      3. Per sub-command, strip leading env-assignments, redirections, and
         grouping chars (FIX 3+4) — AFTER splitting so we never cross a real
         separator.
      4. Match patterns anchored at the start of the stripped sub-command.

    A publish keyword appearing only inside a quoted argument is NOT matched
    because the split step keeps quoted content intact.
    """
    cmd = _join_continuations(cmd)
    for raw_sub in _split_subcmds(cmd):
        sub = _strip_leading(raw_sub)
        if _PAT_GH_MERGE.match(sub):
            return raw_sub
        if _PAT_GIT_PUSH.match(sub):
            return raw_sub
        if _api_write_action(sub) is not None:
            return raw_sub
        # A sub-command that STARTS with a wrapper carries a command after it,
        # and the peel has to land on that command exactly for the anchored
        # patterns above to see it. Three QA cycles found three layers it had
        # to read to land there (quotes, then backslashes, then a quoted flag),
        # each one a live bypass, and hand-rolling a shell tokenizer is a race
        # that keeps producing a next layer.
        #
        # So the anchor is dropped for this case ONLY: inside a wrapped
        # sub-command the publish patterns are searched anywhere. The peel is
        # still what decides IF a sub-command is wrapped, but no longer what
        # decides whether the publish inside it is seen. Over-gating is the
        # direction this errs in: `sudo git commit -m "gh pr merge 9"` now
        # gates, which costs one `OCTO_MERGE_APPROVE` and merges nothing.
        if _starts_with_wrapper(raw_sub) and _publish_anywhere(sub):
            return raw_sub
    return None


def _starts_with_wrapper(raw_sub: str) -> bool:
    head = _WRAPPER_HEAD.match(_strip_grouping(raw_sub))
    return bool(head) and os.path.basename(head.group(1)) in _WRAPPER_NAMES


def _strip_grouping(s: str) -> str:
    """Only the cheap, unambiguous prefixes, so the wrapper test reads the same
    first word `_strip_leading` would start from."""
    out = s.lstrip()
    prev = None
    while out != prev:
        prev = out
        for pat in (_W_GROUP, _W_ASSIGN, _W_REDIR):
            m = pat.match(out)
            if m:
                out = out[m.end():]
                break
    return out


def _publish_anywhere(sub: str) -> bool:
    bare = _outside_quotes(sub)
    return bool(_SEARCH_GH_MERGE.search(bare) or _SEARCH_GIT_PUSH.search(bare)
                or _api_write_action_anywhere(bare))


def _extract_pr_id(matched_sub: str) -> str:
    """Return the PR number string, or branch literal 'main'/'master'.

    *matched_sub* is the raw sub-command (pre-strip) returned by
    _find_publish_subcmd.  Strip leading prefixes before matching so that
    `FOO=1 git push origin main` still yields 'main'.
    """
    sub = _strip_leading(matched_sub)
    m = _PR_NUM_RE.match(sub)
    if m:
        return m.group(1)
    push_m = _PAT_GIT_PUSH.match(sub)
    if push_m:
        return push_m.group(1)
    api = _api_write_action(sub)
    if api is not None:
        return api
    return "unknown"


# -- v8 kernel journal (Phase 4, v8-kernel.md) --------------------------------
_KERNEL_RULE = "CODE.qa-merge-gate"


def _journal_deny(reason, payload=None, tool_use_id=None) -> None:
    """Mirror this refusal into the refusing process's journal.

    FAIL-OPEN by contract: every error is swallowed and the verdict this gate
    just reached is unchanged. A journal that cannot be written must never turn
    a deny into an allow. kernel_proc is loaded by PATH through importlib, not
    by name, so nothing on sys.path can shadow it.
    """
    try:
        import importlib.util
        import os as _os
        _path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "kernel_proc.py")
        _spec = importlib.util.spec_from_file_location("_kernel_proc_journal", _path)
        _kp = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_kp)
        _payload = payload if isinstance(payload, dict) else {}
        _kp.journal_deny(_KERNEL_RULE, reason,
                         tool_use_id if tool_use_id is not None else _payload.get("tool_use_id"),
                         _kp.resolve_pid(_payload))
    except Exception:
        pass


def _nudge(text: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": text,
        }
    }))


def main() -> int:
    # Parse stdin — if this fails we cannot know if it's a merge, so exit 0.
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0

    try:
        tool_input = data.get("tool_input") or {}
        cmd = (tool_input.get("command") or "")
    except Exception:
        return 0

    # Fast path: no sub-command starts with a publish pattern → exit 0 silently.
    matched_sub = _find_publish_subcmd(cmd)
    if matched_sub is None:
        return 0

    # Positively identified as a merge action — from here on, a crash must fail
    # CLOSED (the __main__ handler reads this flag and exits 2, not 0).
    global _PUBLISH_IDENTIFIED
    _PUBLISH_IDENTIFIED = True
    pr_id = _extract_pr_id(matched_sub)

    # ── Repo scope: only PROTECTED repos are gated ────────────────────────────
    try:
        protected = _is_protected_target(cmd, matched_sub, data.get("cwd") or "")
    except Exception:
        protected = None  # unresolvable → keep gating (fail-closed)
    if protected is False:
        _nudge(
            "✓ QA gate: publish targets a non-protected repo (repo-scope) — ungated. "
            "Protected set: the brain + company/config/protected-repos.json."
        )
        return 0

    # ── Channel 1: env, PR-scoped, agent-proof (preferred) ───────────────────
    env_approve = os.environ.get("OCTO_MERGE_APPROVE", "").strip()
    if env_approve and env_approve == pr_id:
        # v7 phase 3: the operator's approval is necessary, not sufficient. An
        # independent QA verdict must exist as a HARNESS-written receipt for this
        # PR (r__subagent-stop__qa-receipt.py), re-read from the agent transcript.
        # "QA approved" typed by the main loop is not a receipt. OCTO_QA_OK=1 stays
        # the operator's explicit blanket bypass (bootstrap, or a docs-only PR).
        if os.environ.get("OCTO_QA_OK", "").strip() != "1":
            try:
                sys.path.insert(0, str(Path(__file__).resolve().parent))
                import receipt_ledger
                qa = receipt_ledger.qa_pass_for(pr_id, str(data.get("session_id") or ""), str(data.get("transcript_path") or ""))
            except Exception:
                qa = None
            if qa is None:
                print(
                    f"✗ QA GATE (fail-closed): PR #{pr_id} is operator-approved but carries NO QA "
                    f"receipt.\n  v7: run an independent QA subagent (judgment tier) on the PR and "
                    f"have it end with\n    QA-VERDICT: PASS\n    QA-SCOPE: PR #{pr_id}\n  The "
                    f"SubagentStop hook records the verdict; the ledger line is re-read from the "
                    f"agent transcript.\n  Explicit operator bypass: OCTO_QA_OK=1 (blanket, logged).",
                    file=sys.stderr,
                )
                _journal_deny(f"merge of PR #{pr_id} blocked: operator-approved but no QA receipt", data)
                return 2
            _nudge(f"✓ QA gate: QA receipt for PR #{pr_id} ({qa.get('agent_type') or 'subagent'}, {qa.get('ts', '')}).")
        _nudge(
            f"✓ QA gate: operator-approved PR #{pr_id} via OCTO_MERGE_APPROVE "
            f"(env, agent-proof)."
        )
        return 0

    # ── (removed) file channel: merge-approvals.json is agent-forgeable, so it
    #    is NOT an authorizer. The agent owns its process env and can strip the
    #    agent-shell markers or pass --i-am-the-operator to write that file, which
    #    made it a self-approval route. Only the harness env below is agent-proof.

    # ── Channel 2: legacy blanket override (DISCOURAGED, back-compat) ─────────
    if os.environ.get("OCTO_QA_OK", "").strip() == "1":
        _nudge(
            f"⚠ QA gate: legacy blanket OCTO_QA_OK override — "
            f"prefer PR-scoped OCTO_MERGE_APPROVE={pr_id}."
        )
        return 0

    # ── BLOCK — fail-closed ───────────────────────────────────────────────────
    label = f"PR #{pr_id}" if pr_id not in ("unknown", "main", "master") else f"branch '{pr_id}'"
    print(
        f"✗ QA GATE (fail-closed): merge of {label} needs operator approval.\n"
        f"  Operator: export OCTO_MERGE_APPROVE={pr_id} in your shell (env, agent-proof),\n"
        f"  then re-run the merge. The file channel (octo-dim approve-merge) is an audit\n"
        f"  log, not a gate pass: the agent can forge it, so only the harness env counts.\n"
        f"  QA (independent reviewer) must have passed first before granting approval.\n"
        f"  Operator directive 2026-06-01: the gate is the agent's approval, not just green CI.",
        file=sys.stderr,
    )
    _journal_deny(f"merge of {label} blocked: no operator approval in OCTO_MERGE_APPROVE", data)
    return 2


def _selftest() -> int:
    import gate_selftest
    argv = sys.argv
    fixture = argv[argv.index("--selftest") + 1] if len(argv) > argv.index("--selftest") + 1 \
        else "registry/fixtures/CODE.qa-merge-gate"
    return gate_selftest.run_gate_selftest(__file__, fixture)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    # Outer try only guards catastrophic interpreter errors.
    # We must NOT silently swallow a deliberate exit(2) block.
    # Fail-open ONLY while we cannot know this is a merge; once a publish/merge
    # sub-command was positively identified, a crash exits 2 (fail-closed) —
    # otherwise any exception after identification would silently open the gate.
    try:
        result = main()
    except Exception:
        if _PUBLISH_IDENTIFIED:
            print(
                "✗ QA GATE (fail-closed): gate crashed AFTER a merge/publish path "
                "was identified — blocking instead of failing open.",
                file=sys.stderr,
            )
            result = 2
        else:
            result = 0  # fail-open for unexpected crashes on non-merge paths
    sys.exit(result)
