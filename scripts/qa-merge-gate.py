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

2026-10-01 (docs/specs/202610012100-qa-receipt-bound-to-head): a PASS approves
the COMMIT the reviewer read, not the pull request. The reviewer adds a third
line, QA-HEAD: <40-digit commit>, and an approved merge of a pull request must
pin that commit in its own arguments: `gh pr merge <n> --match-head-commit <sha>`
or a REST merge with `-f sha=<sha>`. GitHub refuses a direct merge whose head
differs from the pin, so the pinned commit is the merged one; `--auto` is refused
because GitHub's re-check of the pin on auto-merge is not established. The pin is
read the way gh reads its arguments (value flags, clustered short flags), so a
pin that is really the subject of the merge never counts. The newest receipt for
that pull request and commit decides, by the harness timestamp of the transcript
entry it was recorded from, so a NEEDS-WORK cannot be outvoted by an older PASS.
The lookup makes no network call and is cut off after 3 seconds, which blocks.
While an approval is exported, a command that mentions a merge inside syntax
this gate does not parse (backslash, heredoc, $'...', substitution, sh -c,
eval) is blocked whole: on the approved path the gate reads plain commands only.
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
_PAT_GH_MERGE = re.compile(
    r"^\s*gh\s+(?:(?:-R|--repo)(?:=\S+|\s+\S+)\s+)*pr\s+(?:-\S+(?:\s+[^\s-]\S*)?\s+)*merge\b")

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
        return str(int(m.group(1)))
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


def _repo_flag_values(sub: str) -> list:
    """The -R/--repo values gh actually receives as flags: the canonical argv
    (root and `pr`-level flags already moved after `merge`) walked with gh's
    value-flag table, so a word another flag consumes (`--body "-Rx"`,
    `-t -Rx`) is that flag's value, never a repo. Every spelling pflag
    accepts is read: `-R x`, `-Rx`, `-R=x`, `-dRx`, `--repo x`, `--repo=x`."""
    try:
        argv = _bash_words(_canonical(sub))
    except ValueError:
        return []
    if "merge" not in argv:
        return []
    values, _ = _walk_flags(argv[argv.index("merge") + 1:], _MERGE_SHORT_VALUE, _MERGE_LONG_VALUE)
    return [v for name, v in values if name in ("-R", "--repo") and v]


def _effective_cwds(cmd: str, matched_sub: str, session_cwd: str) -> list:
    """The directory the matched sub-command runs in, once per reading: the
    session cwd moved by each plain `cd <path>` before it. The two readings can
    disagree (a `cd` inside a heredoc body the bash-shaped reader reads as a
    line, which bash never runs), so the gate treats the target as unprotected
    only when EVERY reading's directory is. Residual, the same as before this
    change: a `cd` inside a pipeline or a subshell is applied although bash
    runs it in a child shell."""
    start = session_cwd or os.getcwd()
    out = []
    for reading in (_split_bash(cmd), _split_master(cmd)):
        cwd = start
        for raw in reading:
            if raw == matched_sub:
                break
            s = _strip_leading(raw).strip()
            m = re.match(r"^cd\s+(\S+)", s)
            if m:
                p = os.path.expanduser(m.group(1).strip("'\""))
                cwd = p if os.path.isabs(p) else os.path.join(cwd, p)
        if cwd not in out:
            out.append(cwd)
    return out


def _is_protected_target(cmd: str, matched_sub: str, session_cwd: str):
    """True = protected, False = positively NOT protected, None = unresolvable
    (treated as protected: the gate stays fail-closed when unsure).

    The stricter of two judges: the current scope reader and the previous
    gate's, kept verbatim. Every reading that could UNGATE more (real -R
    flags, quoted values, PR forms) met a bash expansion it cannot see
    (`$'-t'`, `{-t,}`, `$T`) and came out looser than before; with the
    previous judge as a floor, the new one can only add gating."""
    new = _scope_current(cmd, matched_sub, session_cwd)
    try:
        old = _scope_previous(cmd, matched_sub, session_cwd)
    except Exception:
        old = None
    if new is True or old is True:
        return True
    if new is None or old is None:
        return None
    return False


def _scope_previous(cmd: str, matched_sub: str, session_cwd: str):
    """The previous gate's scope judge, verbatim in logic: its own split
    (_split_master), its own prefix peel, `gh pr merge` only at the head, the
    first raw -R, and a single cwd."""
    sub = _strip_leading_previous(matched_sub)
    if _api_write_action(sub) is not None:
        m = _API_REPO_ANY_RE.search(sub)
        if not m:
            return None
        slug = _canon_slug(m.group(1))
        known = {s for s in (_remote_slug(r) for r in _protected_roots()) if s}
        if not known or slug is None:
            return None
        return slug in known
    if re.match(r"^\s*gh\s+pr\s+merge\b", sub):
        m = re.search(r"(?:^|\s)(?:-R|--repo)[=\s]+(\S+)", sub)
        if m:
            slug = _canon_slug(m.group(1))
            known = [s for s in (_remote_slug(r) for r in _protected_roots()) if s]
            if not known or slug is None:
                return None
            return slug in known
    cwd = session_cwd or os.getcwd()
    for raw in _split_master(cmd):
        if raw == matched_sub:
            break
        s = _strip_leading_previous(raw).strip()
        m = re.match(r"^cd\s+(\S+)", s)
        if m:
            p = os.path.expanduser(m.group(1).strip("'\""))
            cwd = p if os.path.isabs(p) else os.path.join(cwd, p)
    target = None
    m = re.match(r"^\s*git\s+((?:(?:-C|-c)\s+\S+\s+)*)", sub)
    if m and m.group(1):
        c = re.search(r"-C\s+(\S+)", m.group(1))
        if c:
            raw = os.path.expanduser(c.group(1).strip("'\""))
            target = raw if os.path.isabs(raw) else os.path.join(cwd, raw)
    return _protected_dir(target or cwd)


def _strip_leading_previous(s: str) -> str:
    """The previous prefix peel: grouping, assignments, redirections,
    `command`, and `env` with its flags and assignments."""
    s = s.lstrip()
    prev = None
    while s != prev:
        prev = s
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


def _scope_current(cmd: str, matched_sub: str, session_cwd: str):
    """The current scope reader (see _is_protected_target)."""
    sub = _strip_leading(matched_sub)

    # gh api / curl write (PR merge, branch merge into main/master, or a
    # main/master ref update): the target repo is in the REST path, NOT the cwd
    # (the agent can fire the API call from anywhere, so cwd-based resolution
    # would under-gate). Resolve owner/repo from the path and compare against
    # the protected slugs. GraphQL / any form with no path repo is unresolvable
    # → None (gate, fail-closed). The canonical form is read too, so a root
    # flag before `api` (`gh -X PUT api repos/...`) still finds its path.
    api_sub = sub if _api_write_action(sub) is not None else _canonical(sub)
    if _api_write_action(api_sub) is not None:
        m = _API_REPO_ANY_RE.search(api_sub)
        if not m:
            return None
        slug = _canon_slug(m.group(1))
        known = {s for s in (_remote_slug(r) for r in _protected_roots()) if s}
        if not known or slug is None:
            return None
        return slug in known

    # gh pr merge with an explicit -R/--repo slug: compare against the slugs
    # of the protected roots. No parsable slugs → None (gate).
    if _PAT_GH_MERGE.match(sub) or _PAT_GH_MERGE.match(_canonical(sub)):
        # Every `-R/--repo` value in the text is a candidate: gh keeps the last
        # real flag, but a raw read cannot tell a flag from the same text inside
        # a quoted --body or --subject, so ANY protected or unparseable
        # candidate gates, and only all-unprotected ungates.
        real = _repo_flag_values(sub)
        raw = re.findall(r"(?:^|\s)(?:-R|--repo)[=\s]+(\S+)", sub)
        if real or raw:
            known = [s for s in (_remote_slug(r) for r in _protected_roots()) if s]
            if not known:
                return None  # unparseable protected set → gate
            raw_slugs = [_canon_slug(v) for v in raw]
            if any(sl in known for sl in raw_slugs if sl):
                return True  # a protected slug anywhere in the text gates
            if real:
                slugs = [_canon_slug(v) for v in real]
                if any(sl is None for sl in slugs):
                    return None  # unparseable real flag → gate
                return any(sl in known for sl in slugs)
            # Only quoted text named a repo: gh uses the cwd, so judge that.

    # Resolve the repo the command operates on: git -C wins, else effective cwd.
    # A relative -C is joined against each effective SESSION cwd, never the
    # hook's own cwd (QA finding 3: right answer, deterministic reason). Every
    # candidate directory is judged; one protected or unresolvable gates.
    targets = []
    bases = _effective_cwds(cmd, matched_sub, session_cwd)
    m = re.match(r"^\s*git\s+((?:(?:-C|-c)\s+\S+\s+)*)", sub)
    c = re.search(r"-C\s+(\S+)", m.group(1)) if (m and m.group(1)) else None
    for base in bases:
        if c:
            raw = os.path.expanduser(c.group(1).strip("'\""))
            targets.append(raw if os.path.isabs(raw) else os.path.join(base, raw))
        else:
            targets.append(base)
    verdicts = [_protected_dir(t) for t in targets]
    if any(v is True for v in verdicts):
        return True
    if any(v is None for v in verdicts):
        return None
    return False


def _protected_dir(target: str):
    """True / False / None (unresolvable) for one directory."""
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


# Strip leading wrapper tokens from an already-split sub-command before pattern
# matching. Applied PER sub-command so it never crosses a real separator boundary.
# Covers: grouping openers, env-assignments (VAR=val), redirections, the `env`
# wrapper (with its own -flags and VAR=val args), and the `command` builtin.
# SECURITY: without the env/command peel, `env A=1 gh pr merge` or `command gh pr
# merge` evade the ^gh/^git anchor and bypass the approval gate. Iterative so the
# wrappers may interleave (`env A=1 command git push origin main`). The real
# approval channels stay the agent-proof env/file, never an inline token.
_W_GROUP = re.compile(r"^[({]\s*")
_W_ASSIGN = re.compile(r"^[A-Za-z_]\w*=\S*\s+")
_W_REDIR = re.compile(r"^\d*[<>]+\S*\s+")
_W_ENV = re.compile(r"^env\b\s*")
_W_ENVARG = re.compile(r"^(?:-\S+|[A-Za-z_]\w*=\S*)\s+")
_W_COMMAND = re.compile(r"^command\s+")
# Reserved words and the pipeline negation run the command that follows them.
_W_RESERVED = re.compile(r"^(?:!|if|then|else|elif|do|while|until|time(?:\s+-p)?|coproc)\s+")
# `case WORD in` and a pattern label `pat)` / `(a|b)` precede the command they run.
_W_CASE = re.compile(r"^case\s+\S+\s+in\s+")
# Wrappers that run the command after them: exec, nohup, time -p, nice,
# timeout with its options and duration.
_W_WRAP = re.compile(
    r"^(?:exec|nohup|time\s+-p|nice(?:\s+-n\s*-?\d+|\s+-\d+)?"
    r"|timeout(?:\s+(?:-[sk]\s*\S+|--[\w-]+(?:=\S+)?))*\s+\d[\w.]*)\s+"
)
_W_LABEL = re.compile(r"^\(?[^\s()|;&]+(?:\|[^\s()|;&]+)*\)\s*")


def _strip_leading(s: str) -> str:
    """Return *s* with leading grouping / env-assignments / redirections / the
    `env` wrapper (and its flags+assigns) / the `command` builtin removed."""
    s = s.lstrip()
    prev = None
    while s != prev:
        prev = s
        for pat in (_W_GROUP, _W_ASSIGN, _W_REDIR, _W_COMMAND, _W_RESERVED, _W_CASE, _W_LABEL, _W_WRAP):
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


def _split_master(cmd: str) -> list[str]:
    """The reading this gate used before the bash-shaped reader: backslash-
    newline joined everywhere, quote state continuous across lines, split on
    ; && || | newline. Kept verbatim so _split_subcmds is never weaker than it
    was: every divergence the new reader has (a comment it opens, a heredoc
    body it reads alone) can only ADD sub-commands to this one."""
    cmd = re.sub(r"\\\n", " ", cmd)
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


def _split_subcmds(cmd: str) -> list[str]:
    """Every sub-command of *cmd* under BOTH readings: the bash-shaped one
    (_split_bash) first, then any piece only the previous reading
    (_split_master) produces. A publish either reading finds is decided, so a
    divergence of the new reader can never make a gate weaker than before."""
    out = list(_split_bash(cmd))
    seen = set(out)
    for part in _split_master(cmd):
        if part not in seen:
            seen.add(part)
            out.append(part)
    return out


def _in_arithmetic(text: str) -> bool:
    """True when *text* ends inside an unclosed `$((`/`((` or `$[`."""
    return text.count("((") > text.count("))") or text.count("$[") > text.count("]")


def _split_bash(cmd: str) -> list[str]:
    """Split *cmd* on unquoted shell separators the way bash does:
    ;  &&  ||  |  |&  &  newline.

    Quote state is tracked so separators inside quotes stay literal. A
    backslash escapes the next character outside single quotes, an unquoted
    `#` at the start of a word opens a comment that runs to the newline (an
    apostrophe inside it opens no quote), and an `&` that belongs to a
    redirection (`2>&1`, `&>`, `>&`, `<&`) is not a separator.

    A heredoc body (`<<WORD` / `<<-WORD`, up to the line that is the
    delimiter) is split too, ONE LINE AT A TIME with fresh quote state: a body
    may be fed to a shell in more ways than a list can name (`| bash`, `exec`,
    `env`, `source /dev/stdin`, `<<EOF bash`), so it is read as commands, and
    reading each line alone keeps a quote in the body from hiding the lines
    after it. A `<<` inside arithmetic (`$((`, `((`, `$[`) is a shift, not a
    heredoc. Returns a list of raw sub-command strings (may be empty after
    stripping).
    """
    parts: list[str] = []
    buf: list[str] = []
    in_single = False
    in_double = False
    i = 0
    n = len(cmd)

    pending: list = []  # heredoc delimiters whose bodies start at the next newline

    def cut():
        parts.append("".join(buf))
        buf.clear()

    def split_bodies(j: int) -> int:
        """*j* is just past a newline: split every pending heredoc body, each
        line on its own, and resume after its delimiter line."""
        while pending:
            delim, strip_tabs = pending.pop(0)
            while j <= n:
                end = cmd.find("\n", j)
                line = cmd[j:] if end == -1 else cmd[j:end]
                j = n + 1 if end == -1 else end + 1
                if (line.lstrip("\t") if strip_tabs else line) == delim:
                    break
                parts.extend(_split_bash(line))
        return min(j, n)

    while i < n:
        ch = cmd[i]
        if in_single:
            buf.append(ch)
            if ch == "'":
                in_single = False
            i += 1
        elif ch == "\\" and i + 1 < n:
            if cmd[i + 1] != "\n":
                buf.append(cmd[i:i + 2])  # one element: never read as a blank or `>`
            i += 2  # backslash-newline is a line continuation: both go
        elif ch == "$" and cmd.startswith("'", i + 1) and not in_double:
            # ANSI-C quoting: a backslash escapes the next character, so `\'`
            # does not close it.
            j = i + 2
            while j < n and cmd[j] != "'":
                j += 2 if cmd[j] == "\\" else 1
            buf.append(cmd[i:j + 1])
            i = j + 1
        elif in_double:
            buf.append(ch)
            if ch == '"':
                in_double = False
            i += 1
        elif ch == "'":
            in_single = True
            buf.append(ch)
            i += 1
        elif ch == '"':
            in_double = True
            buf.append(ch)
            i += 1
        elif cmd.startswith("<<<", i):
            buf.append("<<<")  # here-string: its word is an ordinary argument
            i += 3
        elif cmd.startswith("<<", i) and _in_arithmetic("".join(buf)):
            buf.append("<<")  # a shift inside $(( )), (( )) or $[ ]
            i += 2
        elif cmd.startswith("<<", i):
            j = i + 2
            strip_tabs = cmd.startswith("-", j)
            j += 1 if strip_tabs else 0
            while j < n and cmd[j] in " \t":
                j += 1
            k = j
            while k < n and cmd[k] not in " \t\n;&|<>()":
                if cmd[k] in "'\"":
                    close = cmd.find(cmd[k], k + 1)
                    k = n if close == -1 else close + 1
                elif cmd[k] == "\\":
                    k += 2
                else:
                    k += 1
            word = cmd[j:k]
            if word:
                pending.append((re.sub(r"['\"\\]", "", word), strip_tabs))
            buf.append(cmd[i:k])
            i = k
        elif ch == "#" and (not buf or buf[-1] in (" ", "\t", "(", ")")):
            while i < n and cmd[i] != "\n":
                i += 1
        elif cmd[i:i + 2] in ("&&", "||", "|&"):
            cut()
            i += 2
        elif ch == "&" and cmd[i + 1:i + 2] == ">":
            buf.append(ch)  # &> / &>> redirection
            i += 1
        elif ch == "&" and buf and buf[-1] in (">", "<"):
            buf.append(ch)  # 2>&1, >&2, <&3
            i += 1
        elif ch == "\n":
            cut()
            i = split_bodies(i + 1)
        elif ch in (";", "|", "&"):
            cut()
            i += 1
        else:
            buf.append(ch)
            i += 1
    parts.append("".join(buf))
    return parts


_REDIR_OP = re.compile(r"(?:\{[A-Za-z_]\w*\}|\d*|&)(?:>>|>\||>&|<&|<>|<<<|>|<)")


def _drop_redirections(sub: str) -> str:
    """*sub* without its unquoted redirections (`>/dev/null`, `2>&1`, `-t >x`):
    bash removes them before the command sees its argv, so a pin walk over
    them would hand the wrong word to a value flag. A trailing `)` that
    closes a subshell goes too."""
    out, i, n = [], 0, len(sub)
    in_s = in_d = False
    word_start = True
    while i < n:
        c = sub[i]
        if in_s:
            out.append(c); in_s = c != "'"; i += 1; continue
        if in_d:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(sub[i + 1]); i += 2; continue
            in_d = c != '"'; i += 1; continue
        if c == "\\" and i + 1 < n:
            out.append(sub[i:i + 2]); i += 2; word_start = False; continue
        m = _REDIR_OP.match(sub, i) if (word_start or c in "<>") else None
        if m and (m.group(0)[-1] in "<>&|" or m.group(0).endswith(">")):
            j = m.end()
            while j < n and sub[j] in " \t":
                j += 1
            while j < n and sub[j] not in " \t":  # the target word, quotes kept whole
                if sub[j] in "'\"":
                    close = sub.find(sub[j], j + 1)
                    j = n if close == -1 else close + 1
                else:
                    j += 2 if sub[j] == "\\" else 1
            out.append(" "); i = j; word_start = True; continue
        if c == "'":
            in_s = True
        elif c == '"':
            in_d = True
        out.append(c)
        word_start = c in " \t"
        i += 1
    return re.sub(r"\s*\)+\s*$", "", "".join(out))


def _bash_words(text: str) -> list:
    """shlex POSIX split on bash's blanks only (space, tab, newline): shlex's
    default also splits on a carriage return, which bash keeps inside a word,
    so `-t x\r--match-head-commit=<sha>` would read as a pin gh never gets."""
    import shlex
    lex = shlex.shlex(text, posix=True)
    lex.whitespace = " \t\n"
    lex.whitespace_split = True
    lex.commenters = ""
    return list(lex)


def _flag_span(argv: list, j: int) -> int:
    """How many words the gh flag at argv[j] takes: 2 when it is a value flag
    of `pr merge` without its value attached, else 1."""
    tok = argv[j]
    if tok.startswith("--"):
        return 2 if (tok in _MERGE_LONG_VALUE and "=" not in tok and j + 1 < len(argv)) else 1
    for k in range(1, len(tok)):
        if tok[k] not in _MERGE_SHORT_VALUE and tok[k + 1:k + 2] == "=":
            return 1
        if tok[k] in _MERGE_SHORT_VALUE:
            return 2 if (not tok[k + 1:] and j + 1 < len(argv)) else 1
    return 1


def _canonical(sub: str) -> str:
    """The stripped sub-command as gh sees its argv: quotes removed (`'gh'`
    runs gh), and every flag cobra skips before the subcommand (at the root
    and between `pr` and `merge`) moved right after it, in order, so
    `gh -R o/r pr -t x merge 96` reads as `gh pr merge -R o/r -t x 96`.
    A sub-command that cannot be split is returned unchanged."""
    import shlex
    sub = _drop_redirections(_strip_leading(sub))
    try:
        argv = _bash_words(sub)
    except ValueError:
        return sub
    if argv and os.path.basename(argv[0]) == "gh":
        argv[0] = "gh"
        # Flags before the subcommand, read the way cobra's root `stripFlags`
        # skips them: `--name=value` and a short cluster longer than two
        # characters (`-dR<slug>`) are one word; any other flag also takes the
        # next word. gh then resolves the rest (`gh --subject=x pr merge 96`).
        def skip(words, k):
            # cobra's stripFlags: a `--name=value` or a short cluster longer
            # than two characters is one word; any other flag takes the next.
            tok = words[k]
            one = "=" in tok or (not tok.startswith("--") and len(tok) > 2)
            return 1 if one or k + 1 >= len(words) else 2

        moved, i = [], 1
        while i < len(argv) and argv[i].startswith("-") and argv[i] != "--":
            span = skip(argv, i)
            moved += argv[i:i + span]
            i += span
        head = argv[i:]
        cut = 1  # the subcommand word itself (`pr`, `api`, ...)
        if head[:1] == ["pr"]:
            # Flags gh skips between `pr` and `merge` (`gh pr -t x merge 96`),
            # by the same root rule, since cobra strips them before `merge`.
            j = 1
            while j < len(head) and head[j].startswith("-") and head[j] != "--":
                span = skip(head, j)
                moved += head[j:j + span]
                del head[j:j + span]
            cut = 2 if len(head) > 1 else 1
        # pflag then parses the moved words FIRST, so they go right after the
        # subcommand, in their original order, ahead of what followed it.
        argv = argv[:1] + head[:cut] + moved + head[cut:]
    return shlex.join(argv)


# While the operator has an approval exported, a command that MENTIONS a
# publish inside shell syntax this gate does not parse is blocked whole.
# Hand-reading bash failed open three review cycles in a row (backslash-newline,
# heredoc bodies, $'...', escaped blanks), and an approved merge is exactly the
# case where a misread pin merges an unreviewed commit, so on that path the gate
# reads only plain commands and refuses to guess about the rest. Without an
# approval nothing can merge through this gate anyway, so ordinary work that
# quotes a merge in a heredoc is left alone (measured: 487 of 20,846 real
# commands would block if this ran always). The mention is looked for with
# quotes and backslashes removed, so `\gh` and `'gh'` count.
_PUBLISH_MENTION = re.compile(
    r"\bpr\b(?:\s+-\S+(?:\s+[^\s-]\S*)?)*\s+merge\b|\bpulls/[^\s/]+/merge\b|/merges\b|mergePullRequest"
    r"|\bgit\b[^\n]*\bpush\b[^\n]*\b(?:main|master)\b|/git/refs/heads/(?:main|master)\b",
    re.IGNORECASE,
)
_UNPARSED_SYNTAX = re.compile(
    r"\\|\$'|<<|`|\$\(|[<>]\(|\beval\b|\b(?:ba|z|da|k)?sh\s+(?:-\w+\s+)*-\w*c\b"
)


def _unparsed_publish(cmd: str) -> bool:
    """True when *cmd* mentions a publish and carries syntax the gate does not
    parse (a backslash, a heredoc, ANSI-C quoting, a substitution, `sh -c`,
    `eval`)."""
    if not _UNPARSED_SYNTAX.search(cmd):
        return False

    def ansi_c(m):
        try:
            return m.group(1).encode("latin-1", "backslashreplace").decode("unicode_escape")
        except Exception:
            return m.group(1)

    decoded = re.sub(r"\$'((?:\\.|[^'\\])*)'", ansi_c, cmd)
    return bool(_PUBLISH_MENTION.search(re.sub(r"['\"\\]", "", decoded)))


def _find_publish_subcmd(cmd: str) -> str | None:
    """The first publish sub-command, or None; see _find_publish_subcmds."""
    subs = _find_publish_subcmds(cmd)
    return subs[0] if subs else None


def _find_publish_subcmds(cmd: str) -> list:
    """Every sub-command that matches a publish pattern, in order.

    Processing order (split → FIX 3+4 → pattern):
      1. Split the way bash does (_split_subcmds): separators, quotes, escapes,
         line continuations, comments and heredoc bodies.
      2. Per sub-command, strip leading env-assignments, redirections,
         grouping chars, reserved words and case labels (FIX 3+4), AFTER
         splitting so we never cross a real separator.
      3. Match patterns anchored at the start of the stripped sub-command, or
         of its canonical argv (_canonical).

    A publish keyword appearing only inside a quoted argument is NOT matched
    because the split step keeps quoted content intact.
    """
    found = []
    for raw_sub in _split_subcmds(cmd):
        for sub in {_strip_leading(raw_sub), _canonical(raw_sub)}:
            if (_PAT_GH_MERGE.match(sub) or _PAT_GIT_PUSH.match(sub)
                    or _api_write_action(sub) is not None):
                found.append(raw_sub)
                break
    return found


def _extract_pr_id(matched_sub: str) -> str:
    """Return the PR number string, or branch literal 'main'/'master'.

    *matched_sub* is the raw sub-command (pre-strip) returned by
    _find_publish_subcmd.  Strip leading prefixes before matching so that
    `FOO=1 git push origin main` still yields 'main'.
    """
    sub = _strip_leading(matched_sub)
    m = _PR_NUM_RE.match(sub)
    if m:
        return str(int(m.group(1)))
    if _PAT_GH_MERGE.match(sub):
        target = _merge_target(sub)
        if target:
            return target
    push_m = _PAT_GIT_PUSH.match(sub)
    if push_m:
        return push_m.group(1)
    api = _api_write_action(sub)
    if api is not None:
        return api
    return "unknown"


def _norm_pr(value: str) -> str:
    """`0350` and `350` are one pull request; anything else is kept as is."""
    value = str(value or "").strip()
    return str(int(value)) if value.isdigit() else value


def _merge_target(sub: str) -> str:
    """The pull request number of `gh pr merge [flags] <n|url> [flags]`: the
    first positional after `merge`, skipping flags and their values the way
    gh does. "" when it is not a number or a pull request URL."""
    import shlex
    try:
        argv = _bash_words(sub)
    except ValueError:
        return ""
    if "merge" not in argv:
        return ""
    rest = argv[argv.index("merge") + 1:]
    i = 0
    while i < len(rest):
        tok = rest[i]
        if tok == "--":
            rest = rest[i + 1:]
            i = 0
            break
        if tok.startswith("--"):
            i += 2 if (tok in _MERGE_LONG_VALUE and "=" not in tok) else 1
            continue
        if tok.startswith("-") and len(tok) > 1:
            takes = False
            for j in range(1, len(tok)):
                if tok[j] not in _MERGE_SHORT_VALUE and tok[j + 1:j + 2] == "=":
                    break
                if tok[j] in _MERGE_SHORT_VALUE:
                    takes = not tok[j + 1:]
                    break
            i += 2 if takes else 1
            continue
        break
    if i >= len(rest):
        return ""
    ref = rest[i]
    # The forms gh resolves to a pull request number: `96`, `096`, `+96`, `#96`, and
    # a URL to the pull request or any page under it (`/files`, `#comment`).
    m = re.match(r"^#?\+?(\d+)$", ref)
    if m:
        return str(int(m.group(1)))
    m = re.match(r"^https?://[^/]+/[^/]+/[^/]+/pull/(\d+)(?:[/?#].*)?$", ref)
    return str(int(m.group(1))) if m else ""


# -- Commit pin (docs/specs/202610012100-qa-receipt-bound-to-head) -------------
# gh's flag parser gives a flag that takes a value the next token, whatever it
# looks like, and lets short flags cluster (`-st` = squash, then subject). A pin
# is therefore only the value of the pin flag itself; reading the raw text, or a
# token after another value flag, would accept a pin gh sends as the subject.
# Tables from cli/cli pkg/cmd/pr/merge/merge.go and pkg/cmd/api/api.go (gh 2.88).
_MERGE_SHORT_VALUE = set("tbFAR")
_MERGE_LONG_VALUE = {"--subject", "--body", "--body-file", "--author-email",
                     "--repo", "--match-head-commit"}
_API_SHORT_VALUE = set("fFHXqtp")
_API_LONG_VALUE = {"--field", "--raw-field", "--header", "--method", "--input",
                   "--jq", "--template", "--preview", "--hostname", "--cache"}
_API_FIELD_FLAGS = {"-f", "-F", "--field", "--raw-field"}
_SHA40 = re.compile(r"[0-9a-fA-F]{40}")
_LOOKUP_DEADLINE = 3.0  # seconds; the hook itself is killed at 5 (hooks.json)


def _walk_flags(argv: list, short_value: set, long_value: set) -> tuple:
    """(values, bools) as gh's parser sees them: values is [(flag, value)] for
    flags that take a value, bools the set of long flags seen without one."""
    values, bools = [], set()
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok == "--":
            break
        if tok.startswith("--") and len(tok) > 2:
            name, eq, val = tok.partition("=")
            if name in long_value:
                if eq:
                    values.append((name, val))
                elif i + 1 < len(argv):
                    values.append((name, argv[i + 1]))
                    i += 1
            else:
                bools.add(name)
            i += 1
            continue
        if tok.startswith("-") and len(tok) > 1:
            for j in range(1, len(tok)):
                if tok[j] not in short_value and tok[j + 1:j + 2] == "=":
                    break  # pflag: `-s=t` gives the bool its value and ends the cluster
                if tok[j] in short_value:
                    rest = tok[j + 1:]
                    if rest.startswith("="):
                        rest = rest[1:]
                    if rest:
                        values.append(("-" + tok[j], rest))
                    elif i + 1 < len(argv):
                        values.append(("-" + tok[j], argv[i + 1]))
                        i += 1
                    break
        i += 1
    return values, bools


def _argv_after(sub: str, n_words: int) -> list | None:
    """shlex argv of *sub* after its first *n_words* words, or None."""
    import shlex
    try:
        # No comments=True: *sub* comes from _split_subcmds, which already drops
        # an unquoted `#` comment at the start of a word, the only place bash
        # opens one. shlex would also cut at a mid-word `#` (`-t#x`), which bash
        # keeps, and hide a later pin that gh sends (last pin wins).
        argv = _bash_words(sub)
    except ValueError:
        return None
    return argv[n_words:] if len(argv) >= n_words else None


def _merge_pin(sub: str) -> tuple:
    """(pin, auto) for an already-stripped merge sub-command. pin is the 40-digit
    commit the merge is pinned to, lower case, or "" when there is none that gh
    would send; auto is True for `gh pr merge --auto`. The pin text must occur
    exactly once in the command: with one candidate, any misreading of gh's
    grammar can only lose it, never swap in another commit."""
    if _PAT_GH_MERGE.match(sub):
        argv = _argv_after(sub, 3)
        if argv is None:
            return "", False
        if sum(tok.count("match-head-commit") for tok in argv) != 1:
            return "", "--auto" in argv  # zero or several candidates: none is trusted
        values, bools = _walk_flags(argv, _MERGE_SHORT_VALUE, _MERGE_LONG_VALUE)
        pins = [v for name, v in values if name == "--match-head-commit"]
        pin = pins[-1] if pins else ""
        return (pin.lower() if _SHA40.fullmatch(pin) else ""), "--auto" in bools
    if re.match(r"^\s*gh\s+api\b", sub):
        argv = _argv_after(sub, 2)
        if argv is None:
            return "", False
        if sum(tok.count("sha=") + tok.count("sha[") for tok in argv) != 1:
            return "", False  # zero or several `sha=` candidates: none is trusted
        values, _ = _walk_flags(argv, _API_SHORT_VALUE, _API_LONG_VALUE)
        if any(name == "--input" for name, _ in values):
            # With --input, gh sends the file as the body and moves every field
            # flag to the query string (`gh help api`), so `-f sha=` pins nothing.
            return "", False
        shas = {v[4:] for name, v in values if name in _API_FIELD_FLAGS and v.startswith("sha=")}
        if len(shas) != 1:
            return "", False
        pin = shas.pop()
        return (pin.lower() if _SHA40.fullmatch(pin) else ""), False
    return "", False  # curl and anything else: no readable pin


def _api_endpoint(sub: str) -> str:
    """The endpoint positional of `gh api [flags] <endpoint> [flags]`, read
    with gh api's value-flag table; "" when there is none."""
    try:
        argv = _bash_words(sub)
    except ValueError:
        return ""
    if argv[:2] != ["gh", "api"]:
        return ""
    i, rest = 0, argv[2:]
    while i < len(rest):
        tok = rest[i]
        if tok == "--":
            return rest[i + 1] if i + 1 < len(rest) else ""
        if tok.startswith("--"):
            i += 2 if (tok in _API_LONG_VALUE and "=" not in tok) else 1
            continue
        if tok.startswith("-") and len(tok) > 1:
            takes = False
            for k in range(1, len(tok)):
                if tok[k] not in _API_SHORT_VALUE and tok[k + 1:k + 2] == "=":
                    break
                if tok[k] in _API_SHORT_VALUE:
                    takes = not tok[k + 1:]
                    break
            i += 2 if takes else 1
            continue
        return tok
    return ""


_ENDPOINT_PR = re.compile(r"^/?repos/[^/\s]+/[^/\s]+/pulls/(\d+)/merge/?$")
_ANY_PULLS_MERGE = re.compile(r"/?pulls/\d+/merge\b")


def _api_merge_matches(sub: str, pr_id: str) -> bool:
    """An approved `gh api` merge must be a REST call whose own endpoint is
    the approved pull request, and the text must name one merge path only: a
    second `/pulls/N/merge` (in a field, a header, a GraphQL body) is where
    the approved number was being read from instead of the call gh makes."""
    canon = _canonical(sub)
    m = _ENDPOINT_PR.match(_api_endpoint(canon))
    return bool(m) and m.group(1) == pr_id and len(_ANY_PULLS_MERGE.findall(canon)) == 1


def _qa_lookup_with_deadline(pr_id: str, pin: str):
    """('ok', receipt-or-None) or ('timeout', None). The lookup runs in a daemon
    thread joined for _LOOKUP_DEADLINE seconds: that pre-empts even a read that
    blocks, and the thread dies with the process when the hook returns."""
    import threading
    box = {}

    def work():
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import receipt_ledger
            box["r"] = receipt_ledger.qa_latest_for(pr_id, pin)
        except Exception:
            box["r"] = None

    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(_LOOKUP_DEADLINE)
    if t.is_alive():
        return "timeout", None
    return "ok", box.get("r")


def _expands(sub: str) -> bool:
    """True when bash would expand part of *sub* before gh sees it: a `$` or
    a backtick outside single quotes, a glob character outside any quotes, or
    a brace expansion (`{a,b}`, `{1..3}`); `{owner}` is literal. An honest pinned merge has none, and an expansion can carry a
    different pin than the one this gate reads (`{--match-head-commit=X,}`)."""
    in_s = in_d = False
    i = 0
    while i < len(sub):
        c = sub[i]
        if in_s:
            in_s = c != "'"
        elif c == "\\":
            i += 1
        elif c == "'" and not in_d:
            in_s = True
        elif c == '"':
            in_d = not in_d
        elif c in "$`":
            return True
        elif not in_d and c in "*?[":
            return True
        elif not in_d and c == "{":
            m = re.match(r"\{[^\s{}]*(?:,|\.\.)[^\s{}]*\}", sub[i:])
            if m:
                return True
        i += 1
    return False


def _pinned_form(pr_id: str) -> str:
    return (f"gh pr merge {pr_id} --squash --delete-branch --match-head-commit <40-digit commit>\n"
            f"    (or gh api -X PUT repos/<owner>/<repo>/pulls/{pr_id}/merge -f sha=<40-digit commit>)")


_QA_PROTOCOL = ("    QA-VERDICT: PASS\n    QA-SCOPE: PR #{pr}\n    QA-HEAD: <the 40-digit commit it reviewed>")


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


_NUDGES: list = []


def _nudge(text: str) -> None:
    """Buffered: main() prints one hook output for the whole command."""
    _NUDGES.append(text)


def _flush_nudges() -> None:
    if _NUDGES:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": "\n".join(_NUDGES),
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

    global _PUBLISH_IDENTIFIED
    if (os.environ.get("OCTO_MERGE_APPROVE", "").strip()
            and os.environ.get("OCTO_QA_OK", "").strip() != "1"
            and _unparsed_publish(cmd)):
        _PUBLISH_IDENTIFIED = True
        print(
            "✗ QA GATE (fail-closed): an approval is exported, and this command mentions a\n"
            "  merge or a push to main inside\n"
            "  shell syntax the gate does not parse (a backslash, a heredoc, $'...', a\n"
            "  substitution, sh -c, eval). Write the merge as one plain command, e.g.\n"
            "    gh pr merge <n> --squash --delete-branch --match-head-commit <sha>\n"
            "  and put long text in a file (--body-file, git commit -F <file>).",
            file=sys.stderr,
        )
        _journal_deny("publish mentioned inside unparsed shell syntax", data)
        return 2

    subs = _find_publish_subcmds(cmd)
    if (os.environ.get("OCTO_MERGE_APPROVE", "").strip()
            and os.environ.get("OCTO_QA_OK", "").strip() != "1"):
        for raw in _split_subcmds(cmd):
            if raw not in subs and _PUBLISH_MENTION.search(re.sub(r"['\"\\]", "", raw)):
                _PUBLISH_IDENTIFIED = True
                print(
                    "✗ QA GATE (fail-closed): an approval is exported, and a part of this command\n"
                    "  names a merge the gate cannot read as one (a wrapper such as env -u,\n"
                    "  stdbuf, setsid or xargs in front of gh, or merge text in an argument).\n"
                    "  Run the merge as its own plain command:\n"
                    "    gh pr merge <n> --squash --delete-branch --match-head-commit <sha>",
                    file=sys.stderr,
                )
                _journal_deny("publish mentioned in an unidentified sub-command", data)
                return 2
    # Fast path: no sub-command starts with a publish pattern → exit 0 silently.
    if not subs:
        return 0

    # Positively identified as a merge action — from here on, a crash must fail
    # CLOSED (the __main__ handler reads this flag and exits 2, not 0).
    _PUBLISH_IDENTIFIED = True
    del _NUDGES[:]
    # Every publish sub-command is decided on its own and all must pass: a
    # chain such as `merge --match-head-commit <sha> || merge` would otherwise
    # let the second, unpinned merge ride on the first one's check.
    for matched_sub in subs:
        rc = _decide(cmd, matched_sub, data)
        if rc != 0:
            return rc
    _flush_nudges()
    return 0


def _decide(cmd: str, matched_sub: str, data: dict) -> int:
    """0 to allow this one publish sub-command, 2 to block the whole command."""
    pr_id = _extract_pr_id(_canonical(matched_sub))

    # ── Repo scope: only PROTECTED repos are gated ────────────────────────────
    try:
        protected = _is_protected_target(cmd, matched_sub, data.get("cwd") or "")
    except Exception:
        protected = None  # unresolvable → keep gating (fail-closed)
    approved = _norm_pr(os.environ.get("OCTO_MERGE_APPROVE", ""))
    unreadable_pr = pr_id == "unknown" and not _PAT_GIT_PUSH.match(_strip_leading(matched_sub))
    if protected is False and approved and (pr_id == approved or unreadable_pr):
        # While an approval is exported, scope may only ungate a merge whose
        # target is a number the gate read and that is NOT the approved one:
        # GH_REPO or a URL can aim gh at a protected repo from any directory,
        # and a target the gate cannot read may be the approved PR.
        protected = None
    if protected is False:
        _nudge(
            "✓ QA gate: publish targets a non-protected repo (repo-scope) — ungated. "
            "Protected set: the brain + company/config/protected-repos.json."
        )
        return 0

    # ── Channel 1: env, PR-scoped, agent-proof (preferred) ───────────────────
    env_approve = _norm_pr(os.environ.get("OCTO_MERGE_APPROVE", ""))
    if env_approve and env_approve == pr_id:
        # v7 phase 3: the operator's approval is necessary, not sufficient. An
        # independent QA verdict must exist as a HARNESS-written receipt for this
        # PR (r__subagent-stop__qa-receipt.py), re-read from the agent transcript.
        # "QA approved" typed by the main loop is not a receipt. OCTO_QA_OK=1 stays
        # the operator's explicit blanket bypass (bootstrap, or a docs-only PR).
        if os.environ.get("OCTO_QA_OK", "").strip() != "1":
            if pr_id.isdigit():
                # A pull request: the PASS must be for the commit this merge pins.
                if _expands(_strip_leading(matched_sub)):
                    print(
                        f"✗ QA GATE (fail-closed): PR #{pr_id} is approved, but the merge carries a\n"
                        f"  shell expansion ($, a backtick, braces or a glob), so the pin gh receives\n"
                        f"  is not the one this gate can read. Write it literally:\n"
                        f"    {_pinned_form(pr_id)}",
                        file=sys.stderr,
                    )
                    _journal_deny(f"merge of PR #{pr_id} blocked: expansion in the merge", data)
                    return 2
                if (_canonical(matched_sub).startswith("gh api")
                        and not _api_merge_matches(matched_sub, pr_id)):
                    print(
                        f"✗ QA GATE (fail-closed): PR #{pr_id} is approved, but this API call does not\n"
                        f"  merge it through its own REST endpoint (a GraphQL merge ignores `sha`, and\n"
                        f"  a second /pulls/<n>/merge in a field is not the call gh makes). Use:\n"
                        f"    {_pinned_form(pr_id)}",
                        file=sys.stderr,
                    )
                    _journal_deny(f"merge of PR #{pr_id} blocked: API endpoint is not the approved PR", data)
                    return 2
                pin, auto = _merge_pin(_canonical(matched_sub))
                if auto:
                    print(
                        f"✗ QA GATE (fail-closed): PR #{pr_id} is approved, but `--auto` is refused.\n"
                        f"  GitHub enforces the commit pin on a direct merge; whether it re-checks it\n"
                        f"  when an auto-merge fires is not established. Merge directly:\n"
                        f"    {_pinned_form(pr_id)}",
                        file=sys.stderr,
                    )
                    _journal_deny(f"merge of PR #{pr_id} blocked: --auto on an approved merge", data)
                    return 2
                if not pin:
                    print(
                        f"✗ QA GATE (fail-closed): PR #{pr_id} is approved, but the merge pins no commit.\n"
                        f"  A QA PASS approves the commit it reviewed. Pin that commit, the one in the\n"
                        f"  reviewer's QA-HEAD line, in the command's own arguments:\n"
                        f"    {_pinned_form(pr_id)}\n"
                        f"  A pin inside another argument (a subject, a body) is not a pin: gh would not\n"
                        f"  send it. A JSON body (--input, curl -d) cannot be read; use -f sha=.",
                        file=sys.stderr,
                    )
                    _journal_deny(f"merge of PR #{pr_id} blocked: no commit pin", data)
                    return 2
                state, qa = _qa_lookup_with_deadline(pr_id, pin)
                if state == "timeout":
                    print(
                        f"✗ QA GATE (fail-closed): the QA receipt lookup for PR #{pr_id} did not finish\n"
                        f"  within {_LOOKUP_DEADLINE:g} seconds, so the merge is blocked rather than left to a hook timeout.",
                        file=sys.stderr,
                    )
                    _journal_deny(f"merge of PR #{pr_id} blocked: receipt lookup timed out", data)
                    return 2
                if qa is None or qa.get("verdict") != "PASS":
                    found = (f"the newest QA verdict for that commit is {qa.get('verdict')}"
                             if qa else "no QA receipt names that pull request and that commit")
                    print(
                        f"✗ QA GATE (fail-closed): PR #{pr_id} at {pin[:12]}: {found}.\n"
                        f"  Run an independent QA subagent (judgment tier) on that exact commit and have\n"
                        f"  its final report end with\n" + _QA_PROTOCOL.format(pr=pr_id) + "\n"
                        f"  The SubagentStop hook records it; the gate re-reads that transcript entry, and\n"
                        f"  the newest verdict for the commit decides. Explicit operator bypass: OCTO_QA_OK=1.",
                        file=sys.stderr,
                    )
                    _journal_deny(f"merge of PR #{pr_id} blocked: no PASS for the pinned commit", data)
                    return 2
                _nudge(f"✓ QA gate: QA PASS for PR #{pr_id} at {pin[:12]} "
                       f"({qa.get('agent_type') or 'subagent'}, {qa.get('verdict_ts', '')}).")
            else:
                try:
                    sys.path.insert(0, str(Path(__file__).resolve().parent))
                    import receipt_ledger
                    qa = receipt_ledger.qa_pass_for(pr_id, str(data.get("session_id") or ""), str(data.get("transcript_path") or ""))
                except Exception:
                    qa = None
                if qa is None:
                    print(
                        f"✗ QA GATE (fail-closed): {pr_id} is operator-approved but carries NO QA "
                        f"receipt.\n  Run an independent QA subagent (judgment tier) and have its final "
                        f"report end with\n" + _QA_PROTOCOL.format(pr=pr_id) + "\n  The SubagentStop "
                        f"hook records the verdict; the ledger line is re-read from the agent transcript.\n"
                        f"  Explicit operator bypass: OCTO_QA_OK=1 (blanket, logged).",
                        file=sys.stderr,
                    )
                    _journal_deny(f"merge of {pr_id} blocked: operator-approved but no QA receipt", data)
                    return 2
                _nudge(f"✓ QA gate: QA receipt for {pr_id} ({qa.get('agent_type') or 'subagent'}, {qa.get('ts', '')}).")
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
    if pr_id == "unknown" and _PAT_GH_MERGE.match(_canonical(matched_sub)):
        print(
            "✗ QA GATE (fail-closed): this `gh pr merge` names its pull request in a form the\n"
            "  gate cannot read (a branch name, or a reference it does not parse). Approval and\n"
            "  the QA receipt are per pull request number, so write the number:\n"
            "    gh pr merge <n> --squash --delete-branch --match-head-commit <40-digit commit>",
            file=sys.stderr,
        )
        _journal_deny("merge of an unreadable pull request reference blocked", data)
        return 2
    label = f"PR #{pr_id}" if pr_id not in ("unknown", "main", "master") else f"branch '{pr_id}'"
    print(
        f"✗ QA GATE (fail-closed): merge of {label} needs operator approval.\n"
        f"  Operator: export OCTO_MERGE_APPROVE={pr_id} in your shell (env, agent-proof),\n"
        f"  then re-run the merge. The file channel (octo-dim approve-merge) is an audit\n"
        f"  log, not a gate pass: the agent can forge it, so only the harness env counts.\n"
        f"  QA (independent reviewer) must have passed first, on the commit the merge pins:\n"
        f"    {_pinned_form(pr_id) if pr_id.isdigit() else 'git push (no commit pin for a branch push)'}\n"
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
