#!/usr/bin/env python3
"""PreToolUse Bash hook — QA gate (FAIL-CLOSED for merge actions).

NOTE on security boundary: the command-matching below IDENTIFIES the action; the
AGENT-PROOF env channel (OCTO_MERGE_APPROVE, which an inline env cannot pass to
the harness-run hook) AUTHORIZES it. The two fail differently, and conflating
them is how this gate was bypassed: the env channel is immune to FORGERY, not to
EVASION. Authorization is only consulted AFTER the command is identified as a
merge, so a command shape the matcher does not identify never reaches the env
check at all — an evasion is a total bypass, not a degraded authorization.
Detection is command-boundary-anchored: the string is split on UNQUOTED shell
separators (; && || | & newline), heredoc BODIES are removed (they are data on
stdin, not command lines), and each sub-command is matched at EVERY command-head
position it contains, on DECODED tokens. Decoding is what makes `gh "pr" merge`
the same command as `gh pr merge`; it cannot manufacture a verb out of a quoted
MENTION (`git commit -m "gh pr merge 96"`), because a whole-token quote is ONE
token and one token can never supply the two words a verb needs after a head.
A head whose STRING ARGUMENT is itself a command (`bash -c`, `sh -lc`, `eval`,
`ssh host`, `script -qc`, a shell reading a heredoc) has that argument
re-identified; a head that does not re-parse (`git commit`, `echo`, `cat`,
`python3 -`) does not. That property, not the presence of quotes, is the line.

RESIDUAL, each one MEASURED against this file on 2026-09-08 by feeding the
payload on stdin (deny = exit 2). This list is what remains, not what is
convenient — the previous one omitted five reachable families:

  1. The VERB supplied by an expansion instead of by literal text:
     ``X="pr merge"; gh $X 291``, ``$(echo "gh pr merge 291")``,
     ``C="gh pr merge 291"; eval "$C"``. All measured ALLOW. The opaque-HEAD
     case is closed (``$(echo gh) pr merge 291``, ``${PATH:0:0}gh``, ``$'gh'``,
     ``G=gh; $G pr merge 291`` all deny) because the remainder still carries the
     verb. Substituting same-line assignments everywhere would close this and
     would also deny ``docs='gh pr merge'; echo $docs``, a legitimate command in
     the over-fire corpus, so it is left open and named rather than traded for a
     false positive.
  2. A merge that lives in a FILE this hook never sees: ``./deploy.sh``,
     ``printf ... > /tmp/x.sh; bash /tmp/x.sh``, a Makefile target, a git hook.
     Measured ALLOW. The gate reads the command string, not the filesystem.
  3. A merge through a NON-SHELL runtime: ``python3 -c "...requests.put(...)"``,
     node, or any HTTP client that is not curl. Measured ALLOW. Only `gh api`
     and `curl` are recognized API tools.
  4. `gh repo set-default`, which records a resolved base repo in the cwd repo's
     own git config; the cwd repo here resolves by its remote `url`. Measured
     ALLOW as a command; its EFFECT on a later `gh pr merge` is not measured (no
     such config exists to test against), so it is stated, not claimed fixed.
  5. A REPO-LOCAL git alias: `_git_aliases` reads only the user-global config,
     because the target repo is not resolved until after identification. The
     DEFINITION is gated on any line that writes one (`git config alias.x`,
     `git -c alias.x=`), so this is reachable only across two separate tool
     calls into a repo that already carried the alias.
  6. GH_REPO/GH_HOST/GH_CONFIG_DIR set in a way this hook cannot see. All three
     channels that ARE reachable are read (see _line_env): the inline prefix, a
     same-line export, and the harness process env. A Bash tool call does not
     keep exports for the next call — measured — so there is no fourth today.
  7. The v7 boundary itself: the receipt files live under $HOME and the model can
     append to them. Only the harness env (OCTO_MERGE_APPROVE) is a real
     boundary. See docs/architecture/v7-nothing-ships-unverified.md.

KNOWN COST, not a hole: a gh-merge line whose PR number the RAW parse cannot
read (`gh "pr" merge 291`, an unclosed quote) is identified as a merge and falls
to the 'unknown' sentinel, which no approval can name — so that spelling denies
forever, even for the operator. The number is read off the raw form on purpose:
flattening the quoting there would read a flag VALUE as the PR.

When a Bash command is detected as a merge action, this hook BLOCKS execution
unless the operator's AGENT-PROOF env approval is present for EVERY merge
sub-command in the line.
Detected forms: `gh pr merge` (including through a gh ALIAS, resolved from gh's
own config, and the alias DEFINITION that would arm one); `git push` directly to
main/master; and the gh api / curl API equivalents (a write call to REST
`/pulls/<N>/merge`, a GraphQL `mergePullRequest` / `enablePullRequestAutoMerge` /
`mergeBranch` mutation, `POST /repos/.../merges` into main/master, or a
`PATCH`/`DELETE` of `/git/refs/heads/(main|master)`). API reads pass; only a
write method or body flag qualifies. The one channel, plus its receipt waiver:

  1. OCTO_MERGE_APPROVE=<pr_number>  — env var, PR-scoped, AGENT-PROOF (preferred).
     A PreToolUse hook runs in the HARNESS process and does NOT inherit env vars
     the agent sets inline (e.g. `OCTO_MERGE_APPROVE=96 gh pr merge 96` does NOT
     reach this hook).  Only the operator, who exports the var in their shell
     before invoking Claude Code, can set it — making it a true operator signal.

  2. OCTO_QA_OK=1: an explicit waiver of the QA RECEIPT for the PR named in
     OCTO_MERGE_APPROVE. It is not a channel and authorizes nothing on its own:
     without a matching OCTO_MERGE_APPROVE=<same pr> the merge is still denied.
     Scope, precisely: per COMMAND, not per session-lifetime "once" — nothing
     consumes it, so every merge of that same PR while the shell keeps the var
     exported is waived. DISCOURAGED; unset it after the merge it was for.

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
and re-read from that agent's transcript. OCTO_QA_OK=1 is the explicit bypass of
that receipt only, and only for the PR named in OCTO_MERGE_APPROVE.
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
    r'(?:[\s:/\'"+])(?:HEAD:)?\+?(main|master)(?=$|\s|[\'"])'
)
# NOTE on the trailing lookahead: `:` is deliberately NOT there. In a refspec
# `<src>:<dst>` the branch that gets written is the DESTINATION, so
# `git push origin main:refs/heads/feature-x` pushes local main INTO feature-x
# and is not a publish to main; matching the `main` before the colon denied a
# legitimate command (over-fire measured 2026-09-08). Every real push to main
# still matches, because the destination spelling always leaves `main` at the
# end of its token: `origin main`, `HEAD:main`, `:main`, `feature:refs/heads/main`,
# `main:main` (the second one), `+main`.

# Extracts the PR number from `gh pr merge [flags] <N> [flags]`. The number is NOT
# always the first argument: `gh pr merge -R owner/repo 280` and the --repo spelling
# are documented forms, and reading only the first token yielded "unknown",
# which denied a correctly approved PR. So: take the first BARE all-digit token.
# A flag and its value are skipped because neither is all digits.
_GH_MERGE_HEAD = re.compile(r"^\s*gh\s+pr\s+merge(?=\s|$)")
_BARE_NUM = re.compile(r"^\d+$")

# Flags of `gh pr merge` that CONSUME the next token (verbatim from `gh help pr
# merge`, FLAGS + INHERITED FLAGS). Their value must never be read as the PR:
# `gh pr merge -t 280 281` merges 281, and taking 280 approved the wrong PR.
# Every other flag there is boolean. A flag wrongly listed here can only cost an
# extra deny (the number becomes unseen, and an unseen number is a sentinel);
# one wrongly omitted would allow the wrong merge, so the list errs long.
_GH_VALUE_FLAGS = frozenset({
    "-A", "--author-email", "-b", "--body", "-F", "--body-file",
    "--match-head-commit", "-t", "--subject", "-R", "--repo",
})
# short letters of the above, for a bundle like `-dt 280 281`
_GH_VALUE_SHORTS = frozenset("AbFtR")


_ARG_TOKENS_CACHE: dict[str, list[str] | None] = {}


def _arg_tokens(s: str):
    """Argument tokens of *s* (quoting honoured), or None when it does not parse.

    Replaces `shlex.split(posix=True)`, which was called TWICE over the same
    string (the help walk and the PR-number walk) and whose character state
    machine cost 4.1 s of an 8.4 s run on an 80 KB `-b` body — against a hook
    timeout of 5 s (QA cycle 3, bypass 6). This file's own tokenizer does the
    same job in milliseconds, and it keeps `$(...)` and `<(...)` as ONE opaque
    word where shlex splits them into fragments a PR number could hide in.
    Memoized because the two walks ask the identical question.
    """
    if s in _ARG_TOKENS_CACHE:
        return _ARG_TOKENS_CACHE[s]
    toks = _tokens_with_offsets(s)
    out = None if toks is None else [t for t, _s, _e in toks]
    if len(_ARG_TOKENS_CACHE) > 256:
        _ARG_TOKENS_CACHE.clear()
    _ARG_TOKENS_CACHE[s] = out
    return out


def _gh_merge_pr_num(sub: str) -> str | None:
    """First bare numeric ARGUMENT of a gh-pr-merge sub-command, else None.

    Flag values are skipped, so only a positional token can be the PR. `--flag=value`
    carries its value inside the token; a bare `--` ends flag parsing.
    """
    m = _GH_MERGE_HEAD.match(sub)
    if not m:
        return None
    # A real tokenizer, not whitespace: a quoted flag value ("x 280") is ONE
    # token, so a number inside it can never be read as the PR (QA cycle 3). An
    # unclosed quote is unparseable and falls through to the sentinel, which
    # denies.
    toks = _arg_tokens(sub[m.end():])
    if toks is None:
        return None
    i, flags_done = 0, False
    while i < len(toks):
        tok = toks[i].strip("\"'")
        i += 1
        if not flags_done and tok == "--":
            flags_done = True
            continue
        if not flags_done and tok.startswith("-") and len(tok) > 1:
            if "=" in tok:                       # --body=x: value is inside
                continue
            if tok in _GH_VALUE_FLAGS or (
                not tok.startswith("--") and tok[-1] in _GH_VALUE_SHORTS
            ):
                i += 1                           # consume the value token
            continue
        if _BARE_NUM.match(tok):
            return tok
    return None


def _gh_merge_is_help(sub: str) -> bool:
    """True when a gh-pr-merge line only ASKS FOR HELP and merges nothing.

    `gh pr merge --help` prints usage and exits; denying it was a false positive
    that cost QA two read-only tool calls this session. The check walks tokens
    with the SAME value-flag rules as _gh_merge_pr_num rather than searching the
    string, because `gh pr merge -t "-h" 291` is a real merge whose `-h` is a
    flag VALUE — a substring search there would turn a merge into an allow.
    """
    m = _GH_MERGE_HEAD.match(sub)
    if not m:
        return False
    toks = _arg_tokens(sub[m.end():])
    if toks is None:
        return False
    i, flags_done = 0, False
    while i < len(toks):
        tok = toks[i]
        i += 1
        if not flags_done and tok == "--":
            flags_done = True
            continue
        if flags_done or not tok.startswith("-") or len(tok) == 1:
            continue
        if tok in ("-h", "--help"):
            return True
        if "=" in tok:
            continue
        if tok in _GH_VALUE_FLAGS or (
            not tok.startswith("--") and tok[-1] in _GH_VALUE_SHORTS
        ):
            i += 1                               # consume the value token
    return False


_GIT_PUSH_HEAD = re.compile(r"^\s*git\s+(?:-C\s+\S+\s+|-c\s+\S+\s+)*push(?=\s|$)")
# git-push flags that CONSUME the next token, so a `-n` sitting in a flag VALUE
# is never read as `--dry-run`. Erring long here can only cost an extra deny.
_GIT_PUSH_VALUE_FLAGS = frozenset({
    "-o", "--push-option", "--repo", "--receive-pack", "--exec",
})


def _git_push_is_dry_run(sub: str) -> bool:
    """True when a git-push line only REHEARSES the push and writes nothing.

    `git push --dry-run origin main` denied (measured 2026-09-08) — an over-fire
    on a command whose whole point is that it does not publish, and the kind that
    teaches people to route around the gate. Walked as TOKENS, not searched as a
    substring, for the same reason `_gh_merge_is_help` is: a `--dry-run` sitting
    inside a quoted flag VALUE (`git push -o "--dry-run" origin main`) is a value,
    not a flag, and a substring search there would turn a real push into an allow.
    """
    m = _GIT_PUSH_HEAD.match(sub)
    if not m:
        return False
    toks = _arg_tokens(sub[m.end():])
    if toks is None:
        return False
    i, flags_done = 0, False
    while i < len(toks):
        tok = toks[i]
        i += 1
        if not flags_done and tok == "--":
            flags_done = True
            continue
        if flags_done or not tok.startswith("-") or len(tok) == 1:
            continue
        if tok in ("--dry-run", "-n"):
            return True
        if "=" in tok:
            continue
        if tok in _GIT_PUSH_VALUE_FLAGS:
            i += 1                               # consume the value token
    return False


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
# GraphQL mutations that merge. `enablePullRequestAutoMerge` is the mutation
# `gh pr merge --auto` itself makes: the CLI spelling was gated while the exact
# API call behind it was not, so `gh api graphql -f query='mutation{
# enablePullRequestAutoMerge(...)}'` armed a merge that lands the moment checks
# go green. `mergeBranch` is the GraphQL twin of POST /repos/../merges.
_API_GRAPHQL_MERGE = re.compile(
    r"\b(?:mergePullRequest|enablePullRequestAutoMerge|mergeBranch)\b")
_API_MERGES_RE = re.compile(r"repos/[\w.-]+/[\w.-]+/merges\b")
_API_REFS_RE = re.compile(r"git/refs\b")
_API_MASTER_BRANCH_RE = re.compile(r"heads/(main|master)\b")
# owner/repo out of any of the three REST paths, to protect-check the TARGET
# repo (not cwd: the agent can fire the call from anywhere). No path repo
# (e.g. GraphQL) → unresolvable → gate, fail-closed.
_API_REPO_ANY_RE = re.compile(
    r"repos/([\w.-]+/[\w.-]+?)/(?:pulls/\d+/merge|merges|git/refs)\b"
)
# owner/repo out of a github remote URL given as an ARGUMENT (git push accepts a
# URL where a remote name goes).
_URL_SLUG_RE = re.compile(r"github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?(?=$|[\s/])")
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
# The stdin payload of THIS invocation, kept so the crash handler can journal
# its refusal: a fail-closed crash used to print and exit 2 with no journal
# line, so `octo replay` showed nothing for the one refusal nobody can re-run.
_LAST_PAYLOAD: dict | None = None

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
    for raw in _line_parts(cmd):
        if raw == matched_sub:
            break
        s = _unwrap_sub(raw).strip()
        m = re.match(r"^cd\s+(\S+)", s)
        if m:
            p = os.path.expanduser(m.group(1).strip("'\""))
            cwd = p if os.path.isabs(p) else os.path.join(cwd, p)
    return cwd


def _is_protected_target(cmd: str, matched_sub: str, session_cwd: str):
    """True = protected, False = positively NOT protected, None = unresolvable
    (treated as protected: the gate stays fail-closed when unsure)."""
    # `sub` (raw, quoting intact) is read for VALUES; `dec` (decoded) is read to
    # decide WHICH form this is. Deciding the form on the raw string meant
    # `gh "pr" merge 291` fell past the gh branch into the cwd branch and could
    # resolve to a repo it does not target.
    cfg_dir = _cfg_dir_for(cmd, matched_sub)
    sub, dec = _normalize(matched_sub, cfg_dir)

    # An alias DEFINITION has no repo: gh's config is per-user, so an alias that
    # expands to a merge arms every repo the agent can reach, protected ones
    # included. Unresolvable by construction → gate.
    if _alias_definition_form(dec):
        return None

    # gh api / curl write (PR merge, branch merge into main/master, or a
    # main/master ref update): the target repo is in the REST path, NOT the cwd
    # (the agent can fire the API call from anywhere, so cwd-based resolution
    # would under-gate). Resolve owner/repo from the path and compare against
    # the protected slugs. GraphQL / any form with no path repo is unresolvable
    # → None (gate, fail-closed).
    if _api_write_action(dec) is not None:
        m = _API_REPO_ANY_RE.search(dec)
        if not m:
            return None
        slug = _canon_slug(m.group(1))
        known = {s for s in (_remote_slug(r) for r in _protected_roots()) if s}
        if not known or slug is None:
            return None
        return slug in known

    # gh pr merge: the target is -R/--repo if given, else GH_REPO, else the cwd
    # repo — the same order gh itself resolves in. Reading only -R and the cwd
    # let `GH_REPO=<protected slug> gh pr merge <n>`, fired from an unrelated
    # repo, resolve to that unrelated repo and UNGATE a merge of the protected
    # one. GH_HOST moves the whole request to another server, which this gate
    # cannot check against, so a non-github.com host is unresolvable, not safe.
    if _PAT_GH_MERGE.match(dec):
        line_env = _line_env(cmd, matched_sub)
        host = (line_env.get("GH_HOST") or "").strip().strip("\"'").lower()
        if host and host not in ("github.com", "api.github.com"):
            return None
        m = re.search(r"(?:^|\s)(?:-R|--repo)[=\s]+(\S+)", sub)
        raw = m.group(1) if m else (line_env.get("GH_REPO") or "").strip()
        if raw:
            slug = _canon_slug(raw)
            known = [s for s in (_remote_slug(r) for r in _protected_roots()) if s]
            if not known or slug is None:
                return None  # unparseable either side → gate
            return slug in known  # exact canonical match, no suffix tricks

    # A push can name its target as a URL instead of a remote name, and then the
    # cwd repo is not the repo being written: `git push https://github.com/<brain>
    # main`, fired from an unrelated repo, resolved to that unrelated repo and
    # ungated (measured 2026-09-08 — it only denied from a non-repo cwd, by luck).
    # Positive check only: a URL that names a protected repo gates; anything else
    # falls through, because `git push otherremote main` inside the brain is still
    # a push to the brain.
    if _PAT_GIT_PUSH.match(dec):
        known = {s for s in (_remote_slug(r) for r in _protected_roots()) if s}
        for m in _URL_SLUG_RE.finditer(dec):
            if (_canon_slug(m.group(1)) or "") in known:
                return True

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
#
# SECURITY (measured against the live gate, 2026-09-08): the publish patterns are
# anchored at the START of the sub-command, so ANY leading token that is not the
# verb defeats the anchor. `env A=1 gh pr merge` and `command gh pr merge` were
# peeled by name — and `time`, `nohup`, `nice`, `timeout 30`, `stdbuf -o0`,
# `setsid`, `sudo`, `exec`, `eval`, `xargs` and a leading `\gh` all walked
# straight through, each one actually invoking gh.
#
# DESIGN CHOICE — deny-by-default over an allowlist. Naming wrappers is a list
# that has to grow every time someone finds another one, and the one you have not
# named is a total bypass. So the default is inverted: leading tokens are DROPPED
# until one of them IS a command head this gate knows how to read. An
# unrecognized leading token is suspicious, not trusted, and no wrapper needs to
# be named — including the ones whose own options consume a following token
# (`timeout N`, `nice -n 5`, `stdbuf -o0`, `sudo -u x`), because those options and
# their values are just more unrecognized tokens on the way to the head.
#
# The cost, MEASURED 2026-09-08 rather than guessed: a command that passes an
# unquoted merge command as arguments (`echo gh pr merge 280`, `grep -rn gh pr
# merge scripts/`) is identified as a merge, so it denies from inside a PROTECTED
# repo and ungates elsewhere like any other merge. Quoting it — how anyone writes
# that line anyway — makes it a non-match. A QUOTED mention
# (`git commit -m "gh pr merge 96"`) is never a match: the tokenizer keeps a
# quoted argument as ONE token and a head only counts as a whole bare token.
# That is the fail-closed side of the trade, and it is loud, not silent.
_W_GROUP = re.compile(r"^[({]\s*")
_W_GROUP_END = re.compile(r"[\s;)}]+$")
_CMD_HEADS = frozenset({"gh", "git", "curl", "cd"})


# Characters that end a bulk run in `_tokenize`. Inside double quotes only these
# four are special; outside quotes, add whitespace, both quote marks and `<`.
_DQ_STOP = re.compile(r"[\"\\$`]")
_PLAIN_RUN = re.compile(r"[^\s'\"\\$`<]+")

_TOKENS_CACHE: dict[str, list | None] = {}


def _tokens_with_offsets(s: str):
    """Memoized `_tokenize`. The peel, the env walk, the PR-number walk and the
    help walk all ask the identical question about the identical string, and the
    answer depends on nothing else — an 80 KB `-b` body was tokenized FIVE times
    per invocation, 1.9 s of a run against a 5 s hook timeout. Callers only read
    the tuples, so one list is safe to share."""
    if s in _TOKENS_CACHE:
        return _TOKENS_CACHE[s]
    out = _tokenize(s)
    if len(_TOKENS_CACHE) > 256:
        _TOKENS_CACHE.clear()
    _TOKENS_CACHE[s] = out
    return out


def _tokenize(s: str):
    """[(decoded_token, start, end)] for *s*, split on UNQUOTED whitespace.

    Quotes and backslash escapes are honored, so a quoted argument stays one
    token (that is what keeps a quoted mention from looking like a merge) and
    `\\gh` decodes to `gh`. Offsets are into the ORIGINAL string, so slicing
    from `end` preserves the rest of the command verbatim — flattening the
    quoting there would let a quoted flag value be re-read as the PR number.
    Returns None when the string does not tokenize (unclosed quote).
    """
    toks: list[tuple[str, int, int]] = []
    buf: list[str] = []
    start = -1
    in_single = in_double = False
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if ch == "\\" and not in_single and i + 1 < n:
            if start < 0:
                start = i
            buf.append(s[i + 1])
            i += 2
            continue
        # A command substitution is ONE word to the shell no matter how many
        # spaces it contains, so it has to be one token here too. Without this,
        # `$(echo gh) pr merge 96` tokenized as `$(echo` + `gh)` and the opaque
        # head below could never see it. Nothing is executed: the group is
        # consumed as opaque text.
        if ch == "$" and not in_single and i + 1 < n and s[i + 1] == "(":
            if start < 0:
                start = i
            depth, j = 0, i + 1
            while j < n:
                if s[j] == "(":
                    depth += 1
                elif s[j] == ")":
                    depth -= 1
                    if depth == 0:
                        j += 1
                        break
                j += 1
            buf.append(s[i:j])
            i = j
            continue
        # Process substitution is ONE word to the shell too, and unlike `$(...)`
        # it is a CHANNEL: `bash <(echo "gh pr merge 292")` hands the shell a
        # file whose contents are that command line. Splitting it into `<(echo`
        # and `gh pr merge 292)` is how the channel disappeared entirely (QA
        # cycle 3, bypass 4 — measured executing the real gh). It is not a
        # substitution inside double quotes, so both quote states matter here.
        if (ch == "<" and not in_single and not in_double
                and i + 1 < n and s[i + 1] == "("):
            if start < 0:
                start = i
            depth, j = 0, i + 1
            while j < n:
                if s[j] == "(":
                    depth += 1
                elif s[j] == ")":
                    depth -= 1
                    if depth == 0:
                        j += 1
                        break
                j += 1
            buf.append(s[i:j])
            i = j
            continue
        if ch == "`" and not in_single:
            if start < 0:
                start = i
            j = s.find("`", i + 1)
            j = n if j < 0 else j + 1
            buf.append(s[i:j])
            i = j
            continue
        if ch == "'" and not in_double:
            if start < 0:
                start = i
            in_single = not in_single
            i += 1
            continue
        if ch == '"' and not in_single:
            if start < 0:
                start = i
            in_double = not in_double
            i += 1
            continue
        if ch.isspace() and not in_single and not in_double:
            if start >= 0:
                toks.append(("".join(buf), start, i))
                buf, start = [], -1
            i += 1
            continue
        if start < 0:
            start = i
        # Bulk-take the run of characters none of the branches above can claim,
        # instead of stepping one at a time. EXACT, not an approximation: every
        # stop character below is a character one of those branches handles in
        # this state, and every other character reached this line to be appended
        # verbatim anyway. It is what keeps a padded argument from starving the
        # hook: a 500 KB `-b` body ran 4.9 s against a 5 s timeout, and a gate the
        # harness kills is a gate that never says no (QA cycle 3, bypass 6).
        if in_single:
            j = s.find("'", i)          # in single quotes NOTHING else is special
            if j < 0:
                j = n
        elif in_double:
            m2 = _DQ_STOP.search(s, i)
            j = n if m2 is None else m2.start()
        else:
            m2 = _PLAIN_RUN.match(s, i)
            j = m2.end() if m2 else i
        if j <= i:
            buf.append(ch)              # no run here: guarantee forward progress
            i += 1
        else:
            buf.append(s[i:j])
            i = j
    if in_single or in_double:
        return None
    if start >= 0:
        toks.append(("".join(buf), start, n))
    return toks


def _ws_tokens(s: str):
    """Quote-blind whitespace tokens, used ONLY when the string does not
    tokenize. An unclosed quote is a shell syntax error, so nothing runs; the
    fallback exists so the gate still IDENTIFIES the merge instead of losing the
    anchor and falling open."""
    return [(m.group(0), m.start(), m.end()) for m in re.finditer(r"\S+", s)]


# A head the SHELL will resolve and this tokenizer cannot: `$(echo gh)`,
# `` `echo gh` ``, `${PATH:0:0}gh`, `$'gh'`, `$G`. It is not decidable without
# executing something, so it is treated the deny-by-default way: the remainder
# is tried against every head this gate knows, and if the remainder is a merge
# verb the line is a merge whoever the head turns out to be.
_OPAQUE_HEAD = re.compile(r"[$`]")


def _peel_candidates(s: str) -> list[tuple[str, str]]:
    """[(raw_form, decoded_form)] for EVERY command-head position in *s*.

    raw_form     = the DECODED head plus the ORIGINAL remainder, quoting intact.
                   PR-number extraction reads this one, because a quoted flag
                   value must stay ONE token there (`-t "x 280" 281` merges 281).
    decoded_form = the decoded head plus every following token DECODED and joined
                   by single spaces. VERB matching reads this one, because
                   `gh "pr" merge 1`, `gh pr me\\rge 1` and `git "push" origin main`
                   are the same command to the shell and were three total bypasses
                   while the matcher looked at the raw remainder (QA cycle 4, A1).
                   Decoding cannot manufacture a verb out of a quoted MENTION: a
                   whole-token quote (`git commit -m "gh pr merge 96"`) is ONE
                   token, and one token can never supply the two words a verb
                   needs after a head.

    EVERY position, not just the first (A2): the old peel stopped at the first
    head it recognized, so a benign head in front swallowed the merge behind it
    (`git status & gh pr merge 291` allowed). The patterns stay anchored — the
    anchor just gets tried at each head, which is also what keeps a merge inside
    a loop body (`do gh pr merge 1`) identified.
    """
    s = s.lstrip()
    m = _W_GROUP.match(s)
    while m:
        s = s[m.end():]
        m = _W_GROUP.match(s)
    # ...and the closer, so a subshell's `)` is not glued to the last argument
    # (`(gh pr merge 291)` yielded the PR token `291)`, which is not a number,
    # which is the unapprovable sentinel — fail-closed but unmergeable forever).
    s = _W_GROUP_END.sub("", s)
    toks = _tokens_with_offsets(s)
    if toks is None:
        toks = _ws_tokens(s)
    out: list[tuple[str, str]] = []
    for i, (text, _start, end) in enumerate(toks):
        bare = text.strip("\"'")
        head = os.path.basename(bare)
        tail = [t for t, _s2, _e2 in toks[i + 1:]]
        if head in _CMD_HEADS:
            out.append((head + s[end:], " ".join([head] + tail)))
        elif _OPAQUE_HEAD.search(bare):
            for h in ("gh", "git", "curl"):
                out.append((h + s[end:], " ".join([h] + tail)))
    if not out:
        flat = " ".join(t for t, _s2, _e2 in toks) if toks else s
        out.append((s, flat))
    return out


# gh aliases (B4). `gh mrg 291` reached GitHub: an alias expands inside gh, so
# the verb anchor never sees `pr merge`. Aliases live in gh's own config file, so
# resolving them is a deterministic file read of the same shape as _remote_slug.
# A6: gh honours BOTH YAML spellings of the block, so both are read. The
# block-style `aliases:` on its own line was the only one recognized, and
# `aliases: {mrg: pr merge}` — verified honoured by the installed gh 2.88.1 —
# resolved to nothing, which put the alias back outside the anchor.
_ALIAS_BLOCK_RE = re.compile(r"^aliases:\s*$")
_ALIAS_FLOW_RE = re.compile(r"^aliases:\s*\{(.*)\}\s*$")
_ALIAS_ENTRY_RE = re.compile(r"^\s+([\w.-]+):\s*(.+?)\s*$")
_ALIAS_FLOW_ENTRY_RE = re.compile(r"^\s*([\w.-]+)\s*:\s*(.+?)\s*$")
_GH_FIRST_WORD_RE = re.compile(r"^gh\s+([A-Za-z][\w.-]*)(?=\s|$)")
_aliases_cache: dict = {}


def _gh_config_dir(cfg_dir: str | None = None) -> Path:
    """gh's config directory, GH_CONFIG_DIR first — from the COMMAND LINE when
    the caller could see one (A6: `GH_CONFIG_DIR=/tmp/x gh mrg 291` set it for
    gh and not for this hook, so alias resolution read the wrong file and the
    merge walked), else from this process's env, else the default."""
    d = cfg_dir if cfg_dir else os.environ.get("GH_CONFIG_DIR")
    return Path(os.path.expanduser(d)) if d else Path.home() / ".config" / "gh"


def _gh_aliases(cfg_dir: str | None = None) -> dict:
    """{alias: expansion} read off gh's config.yml. Empty on any error."""
    path = _gh_config_dir(cfg_dir) / "config.yml"
    key = str(path)
    cached = _aliases_cache.get(key)
    if cached is not None:
        return cached
    found: dict = {}
    _aliases_cache[key] = found
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return found
    in_block = False
    for line in text.splitlines():
        if not in_block:
            flow = _ALIAS_FLOW_RE.match(line)
            if flow:
                for part in flow.group(1).split(","):
                    m = _ALIAS_FLOW_ENTRY_RE.match(part)
                    if m:
                        found[m.group(1)] = m.group(2).strip().strip("\"'")
                continue
            in_block = bool(_ALIAS_BLOCK_RE.match(line))
            continue
        if line.strip() and not line[:1].isspace():
            break  # dedent: the aliases block ended
        m = _ALIAS_ENTRY_RE.match(line)
        if m:
            found[m.group(1)] = m.group(2).strip().strip("\"'")
    return found


def _expand_gh_alias(sub: str, cfg_dir: str | None = None) -> str:
    """`gh <alias> args` rewritten to what gh will actually run."""
    m = _GH_FIRST_WORD_RE.match(sub)
    if not m:
        return sub
    exp = _gh_aliases(cfg_dir).get(m.group(1))
    if not exp:
        return sub
    rest = sub[m.end(1):]
    if exp.startswith("!"):          # shell alias: the expansion IS the line
        return exp[1:].lstrip() + rest
    return "gh " + exp + rest


# A5: git aliases got none of the treatment gh's got. `git pm` runs whatever
# `alias.pm` says, so the `push` anchor never sees it, and `git -c alias.p=...`
# needs no config file at all — which is why RESOLUTION alone could never be
# the fix and the DEFINITION is gated as well (see _alias_definition_form).
_GIT_FIRST_WORD_RE = re.compile(
    r"^git\s+((?:-C\s+\S+\s+|-c\s+\S+\s+)*)([A-Za-z][\w.-]*)(?=\s|$)")
_GIT_C_ALIAS_RE = re.compile(r"-c\s+alias\.([\w.-]+)=(\S+|'[^']*'|\"[^\"]*\")")
_GIT_ALIAS_SECTION_RE = re.compile(r"^\s*\[\s*alias\s*\]\s*$", re.IGNORECASE)
_GIT_SECTION_RE = re.compile(r"^\s*\[")
_GIT_ALIAS_ENTRY_RE = re.compile(r"^\s*([\w.-]+)\s*=\s*(.+?)\s*$")
_git_aliases_cache: dict = {}


def _git_aliases() -> dict:
    """{alias: expansion} from the user's global git config. File reads only.

    Global scope only, deliberately: the repo-local config lives in the TARGET
    repo, which is not resolved until after identification. A repo-local alias
    is therefore residual, and it is stated as such rather than claimed closed.
    """
    p = os.environ.get("GIT_CONFIG_GLOBAL") or str(Path.home() / ".gitconfig")
    cached = _git_aliases_cache.get(p)
    if cached is not None:
        return cached
    found: dict = {}
    _git_aliases_cache[p] = found
    try:
        text = Path(p).read_text(encoding="utf-8")
    except Exception:
        return found
    in_block = False
    for line in text.splitlines():
        if _GIT_SECTION_RE.match(line):
            in_block = bool(_GIT_ALIAS_SECTION_RE.match(line))
            continue
        if not in_block:
            continue
        m = _GIT_ALIAS_ENTRY_RE.match(line)
        if m:
            found[m.group(1)] = m.group(2).strip().strip("\"'")
    return found


def _expand_git_alias(sub: str) -> str:
    """`git [-c ...] <alias> args` rewritten to what git will actually run.

    A same-line `-c alias.<n>=<body>` wins over the config file, exactly as git
    resolves it — and that is the spelling that needs no config file at all.
    """
    m = _GIT_FIRST_WORD_RE.match(sub)
    if not m:
        return sub
    inline = {k: v.strip("'\"") for k, v in _GIT_C_ALIAS_RE.findall(m.group(1))}
    exp = inline.get(m.group(2)) or _git_aliases().get(m.group(2))
    if not exp:
        return sub
    rest = sub[m.end(2):]
    if exp.startswith("!"):          # shell alias: the expansion IS the line
        return exp[1:].lstrip() + rest
    # `-C <path>` is kept (it names the repo the command operates on), the
    # `-c alias.*` entry is dropped: leaving a `-c` whose VALUE contains spaces
    # between `git` and the expanded verb defeats the push anchor.
    return "git " + _GIT_C_ALIAS_RE.sub("", m.group(1)) + exp + rest


def _expand_alias(sub: str, cfg_dir: str | None = None) -> str:
    """Either alias vocabulary, whichever the head belongs to."""
    out = _expand_gh_alias(sub, cfg_dir)
    return out if out != sub else _expand_git_alias(sub)


# Defining an alias is one ungated command away from an ungated merge, and it
# beats alias RESOLUTION on a single line: `gh alias set m 'pr merge' && gh m 291`
# fires this hook once, before the config file the resolver reads has been
# written. So the definition is gated too. `alias import` reads definitions from
# a file this hook cannot see, so it is unresolvable and always gates.
_PAT_GH_ALIAS_SET = re.compile(r"^\s*gh\s+alias\s+set\b")
_PAT_GH_ALIAS_IMPORT = re.compile(r"^\s*gh\s+alias\s+import\b")
_ALIAS_MERGE_BODY = re.compile(
    r"pr\s+merge\b|/merge\b|mergePullRequest|enablePullRequestAutoMerge|mergeBranch")
# A5: the git half. `git config alias.pm '...'` writes the file AFTER this hook
# read it, and `git -c alias.p='push origin main' p` never writes one at all, so
# resolution could not be the fix for either — the DEFINITION is what gets gated,
# exactly as `gh alias set` is. A git alias body can also be a push to main, which
# no gh alias body ever is, so it gets its own body pattern.
_PAT_GIT_CONFIG_ALIAS = re.compile(
    r"^\s*git\s+[^|&;]*?\bconfig\b[^|&;]*?\balias\.[\w.-]+")
_PAT_GIT_C_ALIAS_DEF = re.compile(r"^\s*git\s+[^|&;]*?-c\s+alias\.[\w.-]+=")
_ALIAS_PUSH_BODY = re.compile(
    r"push\b[^|&;]*?(?:[\s:/\'\"+])(?:HEAD:)?\+?(?:main|master)(?=$|\s|[\'\"])")


def _alias_definition_form(sub: str) -> bool:
    """True when *sub* defines a gh or git alias that could expand to a merge."""
    if _PAT_GH_ALIAS_IMPORT.match(sub):
        return True
    if _PAT_GH_ALIAS_SET.match(sub) and _ALIAS_MERGE_BODY.search(sub):
        return True
    if (_PAT_GIT_CONFIG_ALIAS.match(sub) or _PAT_GIT_C_ALIAS_DEF.match(sub)) and (
            _ALIAS_MERGE_BODY.search(sub) or _ALIAS_PUSH_BODY.search(sub)):
        return True
    return False


def _is_publish_form(dec: str):
    """Which publish pattern the DECODED normalized sub-command *dec* matches.

    One place, so candidate selection in _normalize and the form label in
    _find_publish_subcmds can never disagree about what a merge is.
    """
    if _PAT_GH_MERGE.match(dec):
        return None if _gh_merge_is_help(dec) else "gh"
    if _PAT_GIT_PUSH.match(dec):
        return None if _git_push_is_dry_run(dec) else "push"
    if _api_write_action(dec) is not None:
        return "api"
    if _alias_definition_form(dec):
        return "alias"
    return None


def _normalize(s: str, cfg_dir: str | None = None) -> tuple[str, str]:
    """(raw_form, decoded_form) of *s*: wrappers peeled, aliases expanded.

    Of the candidate head positions, the one that IS a publish form wins; else
    the first. Expansion is repeated because a shell alias can expand back into
    a wrapper (`!time gh pr merge`), and bounded so it cannot loop.
    """
    cur = s
    fallback = (s, s)
    for _ in range(5):
        cands = _peel_candidates(cur)
        fallback = cands[0]
        for raw, dec in cands:
            if _is_publish_form(dec):
                return raw, dec
        nxt = None
        for raw, _dec in cands:
            expanded = _expand_alias(raw, cfg_dir)
            if expanded != raw:
                nxt = expanded
                break
        if nxt is None:
            break
        cur = nxt
    return fallback


def _unwrap_sub(s: str, cfg_dir: str | None = None) -> str:
    """The RAW normalized form — quoting of the arguments preserved. Read by PR
    extraction, where a quoted flag value must stay one token."""
    return _normalize(s, cfg_dir)[0]


def _unwrap_sub_match(s: str, cfg_dir: str | None = None) -> str:
    """The DECODED normalized form — read by verb matching only."""
    return _normalize(s, cfg_dir)[1]


def _prefix_env(sub: str) -> dict:
    """VAR=val assignments in the wrapper prefix of *sub* (before the head).

    `GH_REPO=o/r gh pr merge 291` and `env GH_REPO=o/r gh pr merge 291` both put
    the variable here, and the peel above drops it — so it has to be read before
    it is dropped, not after.
    """
    toks = _tokens_with_offsets(sub)
    if toks is None:
        toks = _ws_tokens(sub)
    out = {}
    for text, _s, _e in toks:
        if os.path.basename(text.strip("\"'")) in _CMD_HEADS:
            break                    # the head: the prefix ends here
        k, sep, v = text.partition("=")
        if sep and re.fullmatch(r"[A-Za-z_]\w*", k):
            out[k] = v.strip("\"'")
    return out


def _line_env(cmd: str, matched_sub: str) -> dict:
    """Env the matched sub-command will actually see, from what is VISIBLE.

    Three reachable channels, all of them visible to a PreToolUse hook:
      * the wrapper prefix of the sub-command itself (see _prefix_env);
      * an `export VAR=val` or a bare assignment in an EARLIER sub-command of the
        same line. Measured 2026-09-08: an `export` in one Bash tool call does
        NOT survive into the next call, and the hook process never sees it, so
        same-line is the only way an agent can set a variable for a merge;
      * the hook's own process env, which is what an operator export before
        launching the harness looks like.
    Later channels lose to earlier ones, the way the shell resolves them.
    """
    parts = _line_parts(cmd)
    chain = _line_env_chain(cmd)
    try:
        idx = parts.index(matched_sub)
    except ValueError:
        idx = len(parts)          # not a part of this line: every assignment applies
    out = dict(chain[idx])
    out.update(_prefix_env(matched_sub))
    return out


_ENV_CHAIN_CACHE: dict[str, list[dict]] = {}


def _line_env_chain(cmd: str) -> list[dict]:
    """chain[i] = the env sub-command i of *cmd* sees, computed ONCE per line.

    This used to be O(n²) and it was a real hole, not a nuisance:
    `_cfg_dir_for` called `_line_env` once PER sub-command, and each call
    re-split and re-tokenized the WHOLE command. 500 `;`-joined no-ops plus a
    merge took 9.7 s (measured 2026-09-08) against this gate's `hooks.json`
    timeout of 5 s, and 2000 took 132 s. The gate still returned 2; it just
    never got to say so. A fail-closed contract that depends on the process
    surviving is not fail-closed, so the fix is the complexity, not the
    timeout. One extra entry at the end: the env after every part, which is
    what a sub-command that is not in this list should see.
    """
    # The process env is part of the answer, so it is part of the key: caching on
    # the command string alone would hand a stale chain to the next caller after
    # an export (and to the next test that patches os.environ).
    key = (cmd, os.environ.get("GH_REPO"), os.environ.get("GH_HOST"),
           os.environ.get("GH_CONFIG_DIR"))
    chain = _ENV_CHAIN_CACHE.get(key)
    if chain is not None:
        return chain
    acc = {k: v for k, v in os.environ.items()
           if k in ("GH_REPO", "GH_HOST", "GH_CONFIG_DIR")}
    chain = []
    for raw in _line_parts(cmd):
        chain.append(dict(acc))
        toks = _tokens_with_offsets(raw)
        if toks is None:
            toks = _ws_tokens(raw)
        words = [t for t, _s, _e in toks]
        if words and os.path.basename(words[0]) == "export":
            words = words[1:]
        for text in words:
            k, sep, v = text.partition("=")
            if sep and re.fullmatch(r"[A-Za-z_]\w*", k):
                acc[k] = v.strip("\"'")
            else:
                break
    chain.append(dict(acc))
    if len(_ENV_CHAIN_CACHE) > 64:
        _ENV_CHAIN_CACHE.clear()
    _ENV_CHAIN_CACHE[key] = chain
    return chain


def _cfg_dir_for(cmd: str, sub: str) -> str | None:
    """GH_CONFIG_DIR as the sub-command will see it. A6: reading it only from the
    hook's own env made `GH_CONFIG_DIR=/tmp/x gh mrg 291` resolve aliases out of
    the wrong file, so the alias resolver could not see the alias that ran."""
    try:
        return _line_env(cmd, sub).get("GH_CONFIG_DIR") or None
    except Exception:
        return None


def _split_subcmds(cmd: str) -> list[str]:
    """Split *cmd* on unquoted shell separators (;  &&  ||  |  &  newline).

    `&` is a separator (A2): it BACKGROUNDS the command before it and starts a
    new one, so `git status & gh pr merge 291` is two commands, and omitting it
    made the whole tail one sub-command whose head was `git status`. `&&` is
    matched first, so it is unaffected; a `&` inside `2>&1` or `|&` splits into
    fragments that are not commands and match nothing.

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
            # A `#` that STARTS a word opens a shell comment: everything to the
            # end of the line is text the shell never runs. Keeping it made the
            # peel try a head position inside a comment, so
            # `git status # gh pr merge 292` DENIED — an over-fire measured
            # 2026-09-08 on a command that publishes nothing. A `#` in the
            # middle of a word is not a comment (`curl https://x#frag`), which
            # is why the preceding character has to be whitespace or nothing.
            if ch == "#" and (i == 0 or cmd[i - 1].isspace()):
                j = cmd.find("\n", i)
                i = n if j < 0 else j
                continue
            # Check for two-char separators first
            two = cmd[i:i + 2]
            if two in ("&&", "||"):
                parts.append("".join(buf))
                buf = []
                i += 2
            elif ch in (";", "|", "\n", "&"):
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


_HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][\w.-]*)\1")
# Heads that RE-PARSE a string argument (or stdin) as a command. This set, not
# the presence of quotes, is what separates a quoted MENTION from a quoted
# COMMAND (A4).
_REPARSE_HEADS = frozenset({"bash", "sh", "zsh", "dash", "ksh", "ssh", "script",
                            "eval"})
_STDIN_REPARSE_HEADS = frozenset({"bash", "sh", "zsh", "dash", "ksh", "ssh"})
# Single-letter options that may legitimately share a bundle with `c` on a shell
# or a shell-like wrapper (`bash -lc`, `sh -ic`, `script -qc`). A bundle carrying
# any letter outside this set is not a command flag, which is what stops the old
# substring test from reading `--norc` as one.
_SHELL_OPT_LETTERS = frozenset("abcefhiklmnopqrstuvxBCDEHIPT")
# Recursion bound. It is a COST bound, not a security one: at the cap a remaining
# re-parsing head is treated as a merge and DENIED, because "I stopped looking"
# is not "there is nothing there". Failing OPEN here meant depth 3 denied and
# depth 4 allowed — four nested `bash -c` executed the real gh (QA cycle 3,
# bypass 2). Raised from 3 to 5 so the deny lands past any nesting a real command
# uses, and the cost stays bounded because each level parses a shorter string.
_MAX_REPARSE_DEPTH = 5


def _split_heredocs(cmd: str) -> tuple[str, list[tuple[str, str]]]:
    """(*cmd* with heredoc BODIES removed, [(opening_line, body)]).

    A heredoc body is DATA written to a command's stdin, not a command line, and
    treating it as one is where this gate's worst over-fire lived: a note whose
    prose read `To publish: git push origin main` was BLOCKED (measured
    2026-09-08), which is a security failure with extra steps — a gate people
    route around is off. The bodies are returned rather than discarded because a
    SHELL reading its stdin does execute them; see _find_publish_subcmds.

    A `<<WORD` with no matching terminator line is not treated as a heredoc at
    all, so a `<<` inside ordinary text (`echo "a << b"`) can never swallow the
    commands that follow it.
    """
    lines = cmd.split("\n")
    kept: list[str] = []
    bodies: list[tuple[str, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        kept.append(line)
        i += 1
        for _q, term in _HEREDOC_RE.findall(line):
            end = None
            for j in range(i, len(lines)):
                if lines[j].strip() == term:
                    end = j
                    break
            if end is None:
                continue                      # no terminator: not a heredoc
            bodies.append((line, "\n".join(lines[i:end])))
            i = end + 1
    return "\n".join(kept), bodies


# Cross-script contract, restored. `receipt_ledger._qa_gate_helpers()` imports
# `_split_subcmds` AND `_strip_leading` from this file to split a Bash command
# the same way the merge gate does; 2ceb87c replaced the old peel and deleted
# this name, and the consumer's `except Exception` turned that into a SILENT
# fallback in which `receipt_ledger.subcommands()` stopped splitting at all —
# no test failed, and the seek-receipt detection behind the outward-send gate
# quietly degraded. The gate itself uses the richer peel above; this stays as
# the published, prefix-only stripper its consumer asked for.
_STRIP_PREFIX_RE = re.compile(
    r"^(?:[({]\s*)*"               # grouping openers
    r"(?:[A-Za-z_]\w*=\S*\s+)*"    # env assignments  VAR=val
    r"(?:\d*[<>]+\S*\s+)*"         # redirections     >/dev/null  2>&1
)


def _strip_leading(s: str) -> str:
    """*s* with leading env-vars, redirections and grouping chars removed."""
    return _STRIP_PREFIX_RE.sub("", s, count=1)


_PARTS_CACHE: dict[str, list[str]] = {}


def _line_parts(cmd: str) -> list[str]:
    """The sub-commands of *cmd*: continuations joined, heredoc bodies removed,
    split on unquoted separators. One definition, so the matcher, the cwd walk
    and the env walk can never disagree about where a sub-command starts.

    Memoized: it depends on nothing but the string, and the cwd walk, the env
    chain and the matcher all ask for the same line. Re-deriving it per
    sub-command is where 11.8 s of a 14 s parse went (see _line_env_chain).
    """
    parts = _PARTS_CACHE.get(cmd)
    if parts is None:
        parts = _split_subcmds(_split_heredocs(_join_continuations(cmd))[0])
        if len(_PARTS_CACHE) > 64:
            _PARTS_CACHE.clear()
        _PARTS_CACHE[cmd] = parts
    return parts


def _is_command_flag(w: str) -> bool:
    """True when *w* is the flag that says 'the next token is a COMMAND'.

    Matched EXACTLY, or as a shorthand bundle whose letters are ALL known shell
    options and one of them is `c` (`-lc`, `-ic`, `-xc`, `-qc`, `-lic`). The old
    test was a SUBSTRING — `w.startswith("-") and "c" in w.lstrip("-")` — so
    `--norc` looked like a command flag, `_reparse_arg` returned the literal
    `-c` as the command to run, and the caller then skipped the direct match on
    the outer sub-command as well. `bash --norc -c "gh pr merge 292"` allowed
    and executed the real gh (QA cycle 3, bypass 1). A wrong guess must never
    REPLACE the check; here it cannot even be made, and the caller falls through
    to the direct match either way.
    """
    if not w.startswith("-") or w in ("-", "--"):
        return False
    if w.startswith("--"):
        return w == "--command"
    letters = w[1:]
    return "c" in letters and all(ch in _SHELL_OPT_LETTERS for ch in letters)


def _command_flag_value(words: list[str]) -> str | None:
    """The token a `-c`-style flag in *words* hands to a shell, else None."""
    for i, w in enumerate(words):
        if _is_command_flag(w) and i + 1 < len(words):
            return words[i + 1]
    return None


def _publish_carriers(text: str) -> list[str]:
    """The parts of *text* that ARE a publish form, when *text* is content a
    shell will execute. Empty list when it carries none.

    Two readings, because a channel can carry the command either way: as one of
    its own sub-commands (`cd /r && gh pr merge 292` behind a `-c`), or as a
    quoted argument it hands on (`echo "gh pr merge 292"` inside a `<(...)`).
    A single-word token is never a carrier — one token cannot supply the two
    words a verb needs after a head, which is what keeps a mention benign.
    """
    out = [sub for sub in _split_subcmds(text)
           if _is_publish_form(_unwrap_sub_match(sub))]
    if out:
        return out
    toks = _tokens_with_offsets(text)
    if toks is None:
        toks = _ws_tokens(text)
    return [t for t, _s, _e in toks
            if " " in t and _is_publish_form(_unwrap_sub_match(t))]


def _stdin_channel_texts(raw_sub: str) -> list[str]:
    """Texts *raw_sub* feeds to a command's STDIN through a channel that is not
    a heredoc: a here-string (`<<< "…"`, `<<<"…"`) or a process substitution
    (`<(…)`, which is also how `/dev/stdin` gets its content).

    `_HEREDOC_RE` matches `<<WORD` only, so a here-string never became a body and
    `_reparses_stdin` was never consulted: `bash <<< "gh pr merge 292"` and
    `bash /dev/stdin <<< "…"` both allowed and both executed the real gh (QA
    cycle 3, bypass 3).
    """
    toks = _tokens_with_offsets(raw_sub)
    if toks is None:
        toks = _ws_tokens(raw_sub)
    words = [t for t, _s, _e in toks]
    out: list[str] = []
    for i, w in enumerate(words):
        if w.startswith("<<<"):
            rest = w[3:].strip()
            if rest:
                out.append(rest)
            elif i + 1 < len(words):
                out.append(words[i + 1])
        start = w.find("<(")
        if start >= 0:
            depth, j = 0, start + 1
            while j < len(w):
                if w[j] == "(":
                    depth += 1
                elif w[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            out.append(w[start + 2:j])
    return out


def _reparse_args(raw_sub: str) -> list[str]:
    """Every command STRING *raw_sub* will hand to a shell, in order.

    A4: the property that separates a quoted MENTION from a quoted COMMAND is not
    quoted-vs-unquoted, it is whether the head RE-PARSES its argument. `git commit
    -m "gh pr merge 96"` never does, `echo "…"` never does; `bash -c`, `sh -lc`,
    `eval`, `ssh host`, `script -qc` always do.

    But `_REPARSE_HEADS` is an ALLOWLIST, and the wrapper nobody named is a total
    bypass: `flock /tmp/l -c "gh pr merge 292"` and `su -c "…"` walked straight
    through (QA cycle 3, bypass 5). That is cycle 1's wrapper finding one layer up
    — the deny-by-default peel only inverted identification for BARE head tokens,
    and when the command is a quoted ARGUMENT identification was back on an
    enumeration. So it is inverted here the same way: when no head this gate reads
    comes first, ANY `-c`-style flag or stdin channel whose content PARSES as a
    publish form is a re-parse, whatever the wrapper is called.

    The inversion is bounded by that parse, which is what keeps its over-fire at
    zero on the corpus: `echo "gh pr merge 96"` carries no command flag, and
    `git commit -m "…"` is a command head, so neither reaches it. `gcc -c main.c`
    has the flag and no publish form. The residual cost is a command that takes a
    literal `-c "git push origin main"` and does NOT execute it — measured as none
    on the over-fire corpus, and loud rather than silent when it happens.
    """
    toks = _tokens_with_offsets(raw_sub)
    if toks is None:
        toks = _ws_tokens(raw_sub)
    words = [t for t, _s, _e in toks]
    named = None
    for i, w in enumerate(words):
        head = os.path.basename(w.strip("\"'"))
        if head in _CMD_HEADS:
            return []              # a command head comes first: nothing re-parses
        if head in _REPARSE_HEADS:
            named = i
            break
    out: list[str] = []
    if named is not None:
        rest = words[named + 1:]
        head = os.path.basename(words[named].strip("\"'"))
        if head == "eval":
            # eval concatenates ALL its arguments and runs the result. It carries
            # no `-c`, so the flag walk never saw it and `eval "gh pr merge 291"`
            # allowed (measured 2026-09-08) — while UNQUOTED `eval gh pr merge
            # 291` denied through the peel, the tell that the quoting, not the
            # command, was doing the deciding.
            if rest:
                out.append(" ".join(rest))
        elif head == "ssh":
            # everything after the destination is the remote command line
            if len(rest) >= 2:
                out.append(" ".join(rest[1:]))
        else:
            v = _command_flag_value(rest)
            if v is not None:
                out.append(v)
    if not out:
        v = _command_flag_value(words[1:] if words else [])
        if v is not None:
            out.extend(_publish_carriers(v))
    for text in _stdin_channel_texts(raw_sub):
        out.extend(_publish_carriers(text))
    return out


def _reparses_stdin(opening_line: str) -> bool:
    """True when the command that opened a heredoc will EXECUTE the body."""
    toks = _tokens_with_offsets(opening_line)
    if toks is None:
        toks = _ws_tokens(opening_line)
    for text, _s, _e in toks:
        head = os.path.basename(text.strip("\"'"))
        if head in _CMD_HEADS:
            return False
        if head in _STDIN_REPARSE_HEADS:
            return True
    return False


def _find_publish_subcmds(cmd: str, _depth: int = 0) -> list[tuple[str, str]]:
    """Return EVERY (raw_sub, form) matching a publish pattern, in order.

    Every one, not just the first: a line chaining two merges is two merges, and
    gating only the head let the second through under the approval granted for
    the first. *form* is "gh", "push", "api" or "alias" and says which pattern
    matched, which is what makes a branch sentinel refusable on the API form
    alone and an alias definition refusable with its own reason.

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
    body_cmd, heredocs = _split_heredocs(_join_continuations(cmd))
    found: list[tuple[str, str]] = []
    for raw_sub in _split_subcmds(body_cmd):
        inners = _reparse_args(raw_sub)
        before = len(found)
        if _depth < _MAX_REPARSE_DEPTH:
            for inner in inners:
                found.extend(_find_publish_subcmds(inner, _depth + 1))
        elif inners:
            # At the cap. Stopping the walk is a cost decision; ALLOWING what is
            # behind it is not one this gate gets to make, so the unresolved
            # re-parse is itself the finding. `_extract_pr_id` will read no
            # number off it and land on the unapprovable sentinel — deny, and
            # nothing an approval can name.
            found.append((raw_sub, "depth"))
        # FALL THROUGH, not `continue`. A re-parse that produced no finding is a
        # guess that did not pay off, and the old code still skipped the direct
        # match after it: one misread flag (`--norc` read as `-c`, so the command
        # string came back as the literal `-c`) DELETED the check instead of
        # falling back to it, and the merge behind it walked. The direct match now
        # runs whenever the re-parse found nothing, so a wrong guess can only cost
        # a wasted look. It is skipped when the re-parse DID find the merge,
        # because that is the same merge read twice.
        if len(found) > before:
            continue
        form = _is_publish_form(_unwrap_sub_match(raw_sub, _cfg_dir_for(cmd, raw_sub)))
        if form:
            found.append((raw_sub, form))
    for opening, body in heredocs:
        if not _reparses_stdin(opening):
            continue                       # a body nothing executes is data
        if _depth < _MAX_REPARSE_DEPTH:
            found.extend(_find_publish_subcmds(body, _depth + 1))
        else:
            found.append((opening, "depth"))
    return found


def _extract_pr_id(matched_sub: str, cfg_dir: str | None = None) -> str:
    """Return the PR number string, or branch literal 'main'/'master'.

    *matched_sub* is the raw sub-command (pre-strip) returned by
    _find_publish_subcmd.  Strip leading prefixes before matching so that
    `FOO=1 git push origin main` still yields 'main'.

    The two forms are read for two different things, and swapping them is a bug
    either way: the PR NUMBER comes off the RAW form, where a quoted flag value
    is still one token (`-t "x 280" 281` merges 281, and flattening it approved
    280); the branch and API scopes come off the DECODED form, where
    `origin ma"in"` is `origin main`. A gh-merge line whose number the raw parse
    cannot read falls through to the 'unknown' sentinel, which is unapprovable —
    fail-closed, not a guess.
    """
    raw, dec = _normalize(matched_sub, cfg_dir)
    num = _gh_merge_pr_num(raw)
    if num:
        return num
    push_m = _PAT_GIT_PUSH.match(dec)
    if push_m:
        return push_m.group(1)
    api = _api_write_action(dec)
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
    # The flag is per INVOCATION, not per process. The hook runs one command per
    # process, so this is a no-op in production; it is what lets a test call
    # main() more than once without a previous merge leaving the crash policy
    # armed for a later non-merge command.
    global _PUBLISH_IDENTIFIED, _LAST_PAYLOAD
    _PUBLISH_IDENTIFIED = False
    _LAST_PAYLOAD = None
    # Parse stdin — if this fails we cannot know if it's a merge, so exit 0.
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    _LAST_PAYLOAD = data if isinstance(data, dict) else None

    try:
        tool_input = data.get("tool_input") or {}
        cmd = (tool_input.get("command") or "")
    except Exception:
        return 0

    # Fast path: no sub-command starts with a publish pattern → exit 0 silently.
    matches = _find_publish_subcmds(cmd)
    if not matches:
        return 0
    matched_sub = matches[0][0]

    # Positively identified as a merge action — from here on, a crash must fail
    # CLOSED (_guarded_main reads this flag and exits 2, not 0).
    _PUBLISH_IDENTIFIED = True
    # Fault injection for the crash-handler fixture, and for nothing else. It
    # needs BOTH the harness-only session marker gate_selftest._run_leg sets and
    # an OCTO_ override the fixture declares, so it is reachable only from the
    # selftest harness — and even if it were reachable, its ONLY effect is to
    # make this gate DENY, so it can never be an authorization path.
    if (os.environ.get("CLAUDE_SESSION_ID") == "__selftest__"
            and os.environ.get("OCTO_GATE_CRASH_SELFTEST") == "1"):
        raise RuntimeError("selftest fault injected after merge identification")
    # One entry per merge in the line. A chained line is gated as a whole: every
    # target must carry the same operator approval, so an approval for one PR can
    # never ride a second merge appended after it.
    targets = [(_extract_pr_id(sub_raw, _cfg_dir_for(cmd, sub_raw)), form)
               for sub_raw, form in matches]
    pr_id = targets[0][0]

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

    # ── Sentinels are not identifiers, so they are not approvable ────────────
    # "unknown" means the parse found no PR number, and on the API forms a bare
    # branch name is whatever the URL happened to carry. Both used to be exportable
    # as OCTO_MERGE_APPROVE (the deny text even told the operator to), which turned
    # one approval into a pass for every URL, branch and GraphQL merge form.
    sentinels = [pid for pid, form in targets
                 if pid == "unknown" or (form == "api" and pid in ("main", "master"))]

    # ── The one channel: env, PR-scoped, agent-proof ─────────────────────────
    env_approve = os.environ.get("OCTO_MERGE_APPROVE", "").strip()
    qa_ok = os.environ.get("OCTO_QA_OK", "").strip() == "1"
    if any(form == "alias" for _pid, form in targets):
        print(
            "✗ QA GATE (fail-closed): this line DEFINES a gh or git alias that expands "
            "to a merge.\n  An alias is per-user, so it arms an ungated merge in every "
            "repo, and defining it\n  in the same line that uses it beats alias "
            "resolution (the config file is read\n  before it is written) — and "
            "`git -c alias.x=...` writes no config file at all.\n  No PR number exists "
            "yet, so no approval can scope it.\n  Operator: run the merge itself with "
            "OCTO_MERGE_APPROVE=<pr> instead of aliasing it.",
            file=sys.stderr,
        )
        _journal_deny("alias definition expanding to a merge blocked", data)
        return 2
    if any(form == "depth" for _pid, form in targets):
        print(
            "✗ QA GATE (fail-closed): this line nests shells deeper than the gate "
            f"re-parses ({_MAX_REPARSE_DEPTH} levels).\n  What runs at the bottom is "
            "unreadable from here, and 'I stopped looking' is not 'there is nothing\n"
            "  there' — allowing it made four nested `bash -c` a total bypass while "
            "three denied.\n  No PR number is readable, so no approval can scope it.\n"
            "  Operator: run the merge itself with OCTO_MERGE_APPROVE=<pr>, not "
            "through nested shells.",
            file=sys.stderr,
        )
        _journal_deny("re-parse depth cap reached with a shell still to read: blocked", data)
        return 2
    if sentinels:
        _journal_deny(f"merge of sentinel {sentinels[0]!r} blocked: not an identifier", data)
        print(
            f"✗ QA GATE (fail-closed): this line merges {sentinels[0]!r}, which is a "
            f"sentinel, not\n  an identifier: no OCTO_MERGE_APPROVE value can approve it "
            f"(setting it to that\n  literal would approve every merge that parses the "
            f"same way).\n  Operator: re-run with an explicit PR number and export "
            f"OCTO_MERGE_APPROVE=<that number>.",
            file=sys.stderr,
        )
        return 2
    mismatched = [pid for pid, _form in targets if pid != env_approve]
    if env_approve and not mismatched:
        # v7 phase 3: the operator's approval is necessary, not sufficient. An
        # independent QA verdict must exist as a HARNESS-written receipt for this
        # PR (r__subagent-stop__qa-receipt.py), re-read from the agent transcript.
        # "QA approved" typed by the main loop is not a receipt. OCTO_QA_OK=1 waives
        # THIS receipt only (bootstrap, or a docs-only PR), never the PR-scoped
        # approval above: it is read only inside this matched-PR branch.
        if not qa_ok:
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
                    f"agent transcript.\n  Explicit operator bypass of the receipt: "
                    f"OCTO_QA_OK=1 (logged), which still needs OCTO_MERGE_APPROVE={pr_id}.",
                    file=sys.stderr,
                )
                _journal_deny(f"merge of PR #{pr_id} blocked: operator-approved but no QA receipt", data)
                return 2
            _nudge(f"✓ QA gate: QA receipt for PR #{pr_id} ({qa.get('agent_type') or 'subagent'}, {qa.get('ts', '')}).")
        else:
            _nudge(
                f"⚠ QA gate: OCTO_QA_OK waived the QA receipt for PR #{pr_id} "
                f"(receipt waiver, discouraged, logged). The PR-scoped "
                f"OCTO_MERGE_APPROVE={pr_id} still authorized this merge."
            )
        _nudge(
            f"✓ QA gate: operator-approved PR #{pr_id} via OCTO_MERGE_APPROVE "
            f"(env, agent-proof); {len(targets)} merge sub-command(s), all on that PR."
        )
        return 0

    # ── (removed) file channel: merge-approvals.json is agent-forgeable, so it
    #    is NOT an authorizer. The agent owns its process env and can strip the
    #    agent-shell markers or pass --i-am-the-operator to write that file, which
    #    made it a self-approval route. Only the harness env below is agent-proof.

    # ── OCTO_QA_OK is NOT an authorizer ───────────────────────────────────────
    # It waives the QA receipt for the PR named in OCTO_MERGE_APPROVE and nothing
    # else. As a blanket it let a merge of 280 through while the operator had
    # approved 279, arming auto-merge on the wrong number.
    if qa_ok:
        scoped = f"OCTO_MERGE_APPROVE={env_approve}" if env_approve else "OCTO_MERGE_APPROVE unset"
        _journal_deny("OCTO_QA_OK waives the QA receipt only; approval missing or "
                      "scoped to another PR", data)
        print(
            f"✗ QA GATE (fail-closed): OCTO_QA_OK=1 waives the QA receipt only, not the\n"
            f"  approval. This command merges {', '.join(pid for pid, _f in targets)}, "
            f"but {scoped}.\n"
            f"  Operator: export OCTO_MERGE_APPROVE={pr_id} in your shell, then re-run.",
            file=sys.stderr,
        )
        return 2

    # ── BLOCK — fail-closed ───────────────────────────────────────────────────
    label = f"PR #{pr_id}" if pr_id not in ("main", "master") else f"branch '{pr_id}'"
    if len(targets) > 1:
        label += f" (+{len(targets) - 1} more merge sub-command(s) in the same line)"
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


def _guarded_main() -> int:
    """main() with the crash policy. A FUNCTION, not an inline __main__ block:
    the branch that decides fail-open vs fail-closed on a crash is the one branch
    an agent most benefits from breaking, and code that cannot be called cannot
    be tested — mutating it was invisible to the whole suite.

    Fail-open ONLY while we cannot know this is a merge; once a publish/merge
    sub-command was positively identified, a crash exits 2, because any exception
    after identification would otherwise silently open the gate.
    """
    try:
        return main()
    except Exception:
        if _PUBLISH_IDENTIFIED:
            print(
                "✗ QA GATE (fail-closed): gate crashed AFTER a merge/publish path "
                "was identified — blocking instead of failing open.",
                file=sys.stderr,
            )
            _journal_deny("gate crashed after merge identification: blocked",
                          _LAST_PAYLOAD)
            return 2
        return 0  # fail-open for unexpected crashes on non-merge paths


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    # The guard only covers catastrophic errors; it must NOT swallow a
    # deliberate exit(2) block, which is why main() returns codes rather than
    # raising SystemExit.
    sys.exit(_guarded_main())
