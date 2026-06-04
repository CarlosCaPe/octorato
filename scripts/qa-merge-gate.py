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

When a Bash command is detected as a merge action (gh pr merge or git push
directly to main/master), this hook BLOCKS execution
unless an operator approval is present via one of three channels:

  1. OCTO_MERGE_APPROVE=<pr_number>  — env var, PR-scoped, AGENT-PROOF (preferred).
     A PreToolUse hook runs in the HARNESS process and does NOT inherit env vars
     the agent sets inline (e.g. `OCTO_MERGE_APPROVE=96 gh pr merge 96` does NOT
     reach this hook).  Only the operator, who exports the var in their shell
     before invoking Claude Code, can set it — making it a true operator signal.

  2. ~/.claude/connectome/merge-approvals.json  — file-based, convenience, canon-bound.
     Writable by octo-dim.py approve-merge.  An agent could forge it, but the
     write is loud/auditable (PostToolUse hooks, git diff, etc.).

  3. OCTO_QA_OK=1  — legacy blanket override; kept for back-compat but DISCOURAGED.
     Prefer OCTO_MERGE_APPROVE=<n>.

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
from datetime import datetime, timezone
from pathlib import Path

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

# Extracts the PR number from `gh pr merge <N> [flags]`
# (?=\s|$) anchors the digit capture to a whole token.
_PR_NUM_RE = re.compile(r"^\s*gh\s+pr\s+merge\s+(\d+)(?=\s|$)")

# Path to the per-PR approvals file
_APPROVALS_FILE = Path.home() / ".claude" / "connectome" / "merge-approvals.json"

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


# FIX 3+4: strip leading env-assignments, redirections, and grouping chars
# from an already-split sub-command before pattern matching.
# Applied PER sub-command so it never crosses a real separator boundary.
# Order: grouping brackets first, then env-assignments, then redirections.
_STRIP_PREFIX_RE = re.compile(
    r"^(?:[({]\s*)*"               # FIX 4: unquoted ( or { grouping openers
    r"(?:[A-Za-z_]\w*=\S*\s+)*"   # FIX 3: env assignments  VAR=val
    r"(?:\d*[<>]+\S*\s+)*"        # FIX 3: redirections      >/dev/null  2>&1
)


def _strip_leading(s: str) -> str:
    """Return *s* with leading env-vars, redirections, and grouping chars removed."""
    return _STRIP_PREFIX_RE.sub("", s, count=1)


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
    return None


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
    return "unknown"


def _load_approvals() -> dict:
    """Load merge-approvals.json; return empty dict on any error."""
    try:
        raw = _APPROVALS_FILE.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            return {}
        return data.get("approvals", {}) if isinstance(data.get("approvals"), dict) else {}
    except Exception:
        return {}


def _is_fresh_approval(record: dict) -> bool:
    """True if (now - ts) <= ttl seconds."""
    try:
        ts_str = record.get("ts", "")
        ttl = int(record.get("ttl", 900))
        ts_dt = datetime.fromisoformat(ts_str)
        if ts_dt.tzinfo is None:
            ts_dt = ts_dt.replace(tzinfo=timezone.utc)
        delta = (datetime.now(timezone.utc) - ts_dt).total_seconds()
        return 0 <= delta <= ttl
    except Exception:
        return False


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

    # Positively identified as a merge action — extract target id from the matched sub-command.
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
        _nudge(
            f"✓ QA gate: operator-approved PR #{pr_id} via OCTO_MERGE_APPROVE "
            f"(env, agent-proof)."
        )
        return 0

    # ── Channel 2: file-based approval (convenience, canon-bound) ────────────
    approvals = _load_approvals()
    record = approvals.get(pr_id)
    if isinstance(record, dict) and _is_fresh_approval(record):
        by = record.get("by", "?")
        ts = record.get("ts", "?")
        _nudge(
            f"✓ QA gate: PR #{pr_id} approved by {by} at {ts} (file)."
        )
        return 0

    # ── Channel 3: legacy blanket override (DISCOURAGED, back-compat) ────────
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
        f"  Operator: export OCTO_MERGE_APPROVE={pr_id} in your shell (env, agent-proof).\n"
        f"  OR run:   python3 ~/.claude/scripts/octo-dim.py approve-merge {pr_id} --by <name>\n"
        f"  QA (independent reviewer) must have passed first before granting approval.\n"
        f"  Operator directive 2026-06-01: the gate is the agent's approval, not just green CI.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    # Outer try only guards catastrophic interpreter errors.
    # We must NOT silently swallow a deliberate exit(2) block.
    try:
        result = main()
    except Exception:
        result = 0  # fail-open for unexpected crashes on non-merge paths
    sys.exit(result)
