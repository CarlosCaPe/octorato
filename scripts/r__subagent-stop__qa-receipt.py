#!/usr/bin/env python3
"""r__subagent-stop__qa-receipt.py: SubagentStop reflex that writes a QA receipt.

v7 phase 3 (docs/architecture/v7-nothing-ships-unverified.md). When a subagent
finishes and its final message carries the verdict protocol

    QA-VERDICT: PASS | FAIL | NEEDS-WORK
    QA-SCOPE: PR #260            (or a branch, a sha, a file set)

this hook, running in the harness process, appends a qa receipt to the global
ledger with the agent id, type and the harness-written agent transcript path.
qa-merge-gate re-reads that transcript before honoring the receipt, so the
line is a pointer, not the proof.

Why here and not in prose: "QA approved" typed by the main loop is
indistinguishable from an invention. The verdict has to come from a different
context and be recorded by something the main loop does not control.

Never blocks. Fail-open on every error.
Stdin: {"session_id", "agent_id", "agent_type", "agent_transcript_path",
        "last_assistant_message", ...}
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _last_text_from(path: str) -> str:
    """Fallback when the payload carries no last_assistant_message."""
    try:
        import receipt_ledger
        lines = receipt_ledger._tail_lines(path)
    except Exception:
        return ""
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "assistant":
            continue
        content = (entry.get("message") or {}).get("content") or []
        if isinstance(content, str):
            return content
        texts = [b.get("text", "") for b in content
                 if isinstance(b, dict) and b.get("type") == "text"]
        if texts:
            return "\n".join(texts)
    return ""


def main() -> int:
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        return 0
    text = str(data.get("last_assistant_message") or "")
    tp = str(data.get("agent_transcript_path") or "")
    if not text and tp:
        text = _last_text_from(tp)
    try:
        import receipt_ledger
        verdict, scope = receipt_ledger.parse_verdict(text)
        if not verdict:
            return 0
        receipt_ledger.append_global({
            "kind": "qa",
            "verdict": verdict,
            "scope": scope,
            "agent_id": data.get("agent_id") or "",
            "agent_type": data.get("agent_type") or "",
            "agent_transcript_path": tp,
            "session_id": data.get("session_id") or "",
        })
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
