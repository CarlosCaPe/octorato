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
separators (; && || | newline), so a pattern inside a quoted argument
(``git commit -m "gh pr merge 96"``) does NOT trigger the gate, and each
sub-command is peeled down to its command head so no wrapper defeats the anchor.

RESIDUAL, measured 2026-09-08 (what actually remains after that peel):
  * A merge hidden inside a QUOTED string a wrapper will re-parse:
    ``bash -c "gh pr merge 96"``, ``eval "gh pr merge 96"``, ``sh -c '...'``.
    Unquoting it here would re-match a quoted MENTION, which is the false
    positive the boundary anchoring exists to prevent, so the two cannot both be
    had by string matching. (Unquoted ``eval gh pr merge 96`` IS caught: the peel
    drops `eval` like any other leading token.)
  * Command substitution: ``$(echo gh) pr merge 96``, backticks.
  * `gh repo set-default`, which records a resolved base repo in the cwd repo's
    own git config; the cwd repo here resolves by its remote `url`. Not measured
    (no such config exists to test against), stated rather than claimed fixed.
  * GH_REPO/GH_HOST set in a way this hook cannot see. All three channels that
    ARE reachable are read (see _line_env): the inline prefix, a same-line
    export, and the harness process env. A Bash tool call does not keep exports
    for the next call — measured — so there is no fourth one today.

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
    r'(?:[\s:/\'"+])(?:HEAD:)?\+?(main|master)(?=$|\s|:|[\'"])'
)

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


def _gh_merge_pr_num(sub: str) -> str | None:
    """First bare numeric ARGUMENT of a gh-pr-merge sub-command, else None.

    Flag values are skipped, so only a positional token can be the PR. `--flag=value`
    carries its value inside the token; a bare `--` ends flag parsing.
    """
    m = _GH_MERGE_HEAD.match(sub)
    if not m:
        return None
    # shlex, not whitespace: a quoted flag value ("x 280") is ONE token, so a
    # number inside it can never be read as the PR (QA cycle 3). An unclosed
    # quote is unparseable and falls through to the sentinel, which denies.
    try:
        import shlex
        toks = shlex.split(sub[m.end():], posix=True)
    except ValueError:
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
        s = _unwrap_sub(raw).strip()
        m = re.match(r"^cd\s+(\S+)", s)
        if m:
            p = os.path.expanduser(m.group(1).strip("'\""))
            cwd = p if os.path.isabs(p) else os.path.join(cwd, p)
    return cwd


def _is_protected_target(cmd: str, matched_sub: str, session_cwd: str):
    """True = protected, False = positively NOT protected, None = unresolvable
    (treated as protected: the gate stays fail-closed when unsure)."""
    sub = _unwrap_sub(matched_sub)

    # An alias DEFINITION has no repo: gh's config is per-user, so an alias that
    # expands to a merge arms every repo the agent can reach, protected ones
    # included. Unresolvable by construction → gate.
    if _alias_definition_form(sub):
        return None

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

    # gh pr merge: the target is -R/--repo if given, else GH_REPO, else the cwd
    # repo — the same order gh itself resolves in. Reading only -R and the cwd
    # let `GH_REPO=<protected slug> gh pr merge <n>`, fired from an unrelated
    # repo, resolve to that unrelated repo and UNGATE a merge of the protected
    # one. GH_HOST moves the whole request to another server, which this gate
    # cannot check against, so a non-github.com host is unresolvable, not safe.
    if _PAT_GH_MERGE.match(sub):
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
_CMD_HEADS = frozenset({"gh", "git", "curl", "cd"})


def _tokens_with_offsets(s: str):
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
        buf.append(ch)
        i += 1
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


def _peel_to_head(s: str) -> str:
    """*s* from its first recognized command head on, wrappers dropped."""
    s = s.lstrip()
    m = _W_GROUP.match(s)
    while m:
        s = s[m.end():]
        m = _W_GROUP.match(s)
    toks = _tokens_with_offsets(s)
    if toks is None:
        toks = _ws_tokens(s)
    for text, _start, end in toks:
        head = os.path.basename(text.strip("\"'"))
        if head in _CMD_HEADS:
            # the DECODED head plus the untouched remainder: `\gh pr merge 1`
            # and `/usr/bin/gh pr merge 1` both normalize to `gh pr merge 1`
            # without disturbing the quoting of any later argument.
            return head + s[end:]
    return s


# gh aliases (B4). `gh mrg 291` reached GitHub: an alias expands inside gh, so
# the verb anchor never sees `pr merge`. Aliases live in gh's own config file, so
# resolving them is a deterministic file read of the same shape as _remote_slug.
_ALIAS_BLOCK_RE = re.compile(r"^aliases:\s*$")
_ALIAS_ENTRY_RE = re.compile(r"^\s+([\w.-]+):\s*(.+?)\s*$")
_GH_FIRST_WORD_RE = re.compile(r"^gh\s+([A-Za-z][\w.-]*)(?=\s|$)")
_aliases_cache: dict | None = None


def _gh_aliases() -> dict:
    """{alias: expansion} read off gh's config.yml. Empty on any error."""
    global _aliases_cache
    if _aliases_cache is not None:
        return _aliases_cache
    _aliases_cache = {}
    try:
        d = os.environ.get("GH_CONFIG_DIR")
        path = (Path(d) if d else Path.home() / ".config" / "gh") / "config.yml"
        text = path.read_text(encoding="utf-8")
    except Exception:
        return _aliases_cache
    in_block = False
    for line in text.splitlines():
        if not in_block:
            in_block = bool(_ALIAS_BLOCK_RE.match(line))
            continue
        if line.strip() and not line[:1].isspace():
            break  # dedent: the aliases block ended
        m = _ALIAS_ENTRY_RE.match(line)
        if m:
            _aliases_cache[m.group(1)] = m.group(2).strip().strip("\"'")
    return _aliases_cache


def _expand_gh_alias(sub: str) -> str:
    """`gh <alias> args` rewritten to what gh will actually run."""
    m = _GH_FIRST_WORD_RE.match(sub)
    if not m:
        return sub
    exp = _gh_aliases().get(m.group(1))
    if not exp:
        return sub
    rest = sub[m.end(1):]
    if exp.startswith("!"):          # shell alias: the expansion IS the line
        return exp[1:].lstrip() + rest
    return "gh " + exp + rest


# Defining an alias is one ungated command away from an ungated merge, and it
# beats alias RESOLUTION on a single line: `gh alias set m 'pr merge' && gh m 291`
# fires this hook once, before the config file the resolver reads has been
# written. So the definition is gated too. `alias import` reads definitions from
# a file this hook cannot see, so it is unresolvable and always gates.
_PAT_GH_ALIAS_SET = re.compile(r"^\s*gh\s+alias\s+set\b")
_PAT_GH_ALIAS_IMPORT = re.compile(r"^\s*gh\s+alias\s+import\b")
_ALIAS_MERGE_BODY = re.compile(
    r"pr\s+merge\b|/merge\b|mergePullRequest|enablePullRequestAutoMerge|mergeBranch")


def _alias_definition_form(sub: str) -> bool:
    """True when *sub* defines a gh alias that could expand to a merge."""
    if _PAT_GH_ALIAS_IMPORT.match(sub):
        return True
    return bool(_PAT_GH_ALIAS_SET.match(sub) and _ALIAS_MERGE_BODY.search(sub))


def _unwrap_sub(s: str) -> str:
    """Return *s* normalized for pattern matching: leading wrappers dropped and
    a gh alias expanded, repeatedly, because a shell alias can expand back into
    a wrapper (`!time gh pr merge`). Bounded so it cannot loop."""
    cur = s
    for _ in range(5):
        peeled = _peel_to_head(cur)
        expanded = _expand_gh_alias(peeled)
        if expanded == peeled:
            return peeled
        cur = expanded
    return cur


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
    out = {k: v for k, v in os.environ.items() if k in ("GH_REPO", "GH_HOST")}
    for raw in _split_subcmds(_join_continuations(cmd)):
        if raw == matched_sub:
            break
        toks = _tokens_with_offsets(raw)
        if toks is None:
            toks = _ws_tokens(raw)
        words = [t for t, _s, _e in toks]
        if words and os.path.basename(words[0]) == "export":
            words = words[1:]
        for text in words:
            k, sep, v = text.partition("=")
            if sep and re.fullmatch(r"[A-Za-z_]\w*", k):
                out[k] = v.strip("\"'")
            else:
                break
    out.update(_prefix_env(matched_sub))
    return out


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


def _find_publish_subcmds(cmd: str) -> list[tuple[str, str]]:
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
    cmd = _join_continuations(cmd)
    found: list[tuple[str, str]] = []
    for raw_sub in _split_subcmds(cmd):
        s = _unwrap_sub(raw_sub)
        if _PAT_GH_MERGE.match(s):
            found.append((raw_sub, "gh"))
        elif _PAT_GIT_PUSH.match(s):
            found.append((raw_sub, "push"))
        elif _api_write_action(s) is not None:
            found.append((raw_sub, "api"))
        elif _alias_definition_form(s):
            found.append((raw_sub, "alias"))
    return found


def _extract_pr_id(matched_sub: str) -> str:
    """Return the PR number string, or branch literal 'main'/'master'.

    *matched_sub* is the raw sub-command (pre-strip) returned by
    _find_publish_subcmd.  Strip leading prefixes before matching so that
    `FOO=1 git push origin main` still yields 'main'.
    """
    sub = _unwrap_sub(matched_sub)
    num = _gh_merge_pr_num(sub)
    if num:
        return num
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
    # The flag is per INVOCATION, not per process. The hook runs one command per
    # process, so this is a no-op in production; it is what lets a test call
    # main() more than once without a previous merge leaving the crash policy
    # armed for a later non-merge command.
    global _PUBLISH_IDENTIFIED
    _PUBLISH_IDENTIFIED = False
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
    targets = [(_extract_pr_id(sub_raw), form) for sub_raw, form in matches]
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
            "✗ QA GATE (fail-closed): this line DEFINES a gh alias that expands to a "
            "merge.\n  An alias is per-user, so it arms an ungated merge in every repo, "
            "and defining it\n  in the same line that uses it beats alias resolution "
            "(the config file is read\n  before it is written). No PR number exists yet, "
            "so no approval can scope it.\n  Operator: run the merge itself with "
            "OCTO_MERGE_APPROVE=<pr> instead of aliasing it.",
            file=sys.stderr,
        )
        _journal_deny("gh alias definition expanding to a merge blocked", data)
        return 2
    if sentinels:
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
            return 2
        return 0  # fail-open for unexpected crashes on non-merge paths


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    # The guard only covers catastrophic errors; it must NOT swallow a
    # deliberate exit(2) block, which is why main() returns codes rather than
    # raising SystemExit.
    sys.exit(_guarded_main())
