#!/usr/bin/env python3
"""PreToolUse Bash hook — QA gate (FAIL-CLOSED for merge actions).

NOTE on security boundary: the regex command-matching below is a speed-bump for
honest mistakes; the AGENT-PROOF env channel (OCTO_MERGE_APPROVE, which an inline
env cannot pass to the harness-run hook) is the actual security boundary — shell
indirection (e.g. ``$(echo gh) pr merge``) can evade string-matching and that is
accepted residual risk by design.

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

# Patterns that positively identify a merge / direct-push action.
# Order matters: most-specific first to reduce false-negative risk.
_MERGE_PATTERNS = (
    re.compile(r"\bgh\s+pr\s+merge\b"),
    re.compile(r"\bgit\b[^|&;]*?\bpush\b[^|&;]*?(?:^|[\s:/'\"+])(?:HEAD:)?\+?(main|master)(?=$|\s|:|['\"])"),
)

# Extracts the PR number from `gh pr merge <N> [flags]`
# (?=\s|$) anchors the digit capture to a whole token — prevents leading-digit
# extraction from non-numeric selectors like `96x`, `96.5`, `96-evil`.
_PR_NUM_RE = re.compile(r"\bgh\s+pr\s+merge\s+(\d+)(?=\s|$)")

# Path to the per-PR approvals file
_APPROVALS_FILE = Path.home() / ".claude" / "connectome" / "merge-approvals.json"


def _is_merge_command(cmd: str) -> bool:
    return any(p.search(cmd) for p in _MERGE_PATTERNS)


def _extract_pr_id(cmd: str) -> str:
    """Return the PR number string, or branch literal 'main'/'master'."""
    m = _PR_NUM_RE.search(cmd)
    if m:
        return m.group(1)
    # Fall back: detect a direct push target branch (same hardened pattern as _MERGE_PATTERNS)
    push_m = re.search(r"\bgit\b[^|&;]*?\bpush\b[^|&;]*?(?:^|[\s:/'\"+])(?:HEAD:)?\+?(main|master)(?=$|\s|:|['\"])", cmd)
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

    # Fast path: not a merge command → exit 0 silently.
    if not _is_merge_command(cmd):
        return 0

    # Positively identified as a merge action — extract target id.
    pr_id = _extract_pr_id(cmd)

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
