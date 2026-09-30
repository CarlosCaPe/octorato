#!/usr/bin/env python3
"""r__subagent-stop__qa-receipt.py: SubagentStop reflex that writes a QA receipt.

v7 phase 3 (docs/architecture/v7-nothing-ships-unverified.md). When a subagent
finishes and its final message carries the verdict protocol

    QA-VERDICT: PASS | FAIL | NEEDS-WORK
    QA-SCOPE: PR #260            (or a branch, a sha, a file set)

or the v9 converge protocol (skills/sdd-converge)

    CONVERGE-VERDICT: CONVERGED | GAPS
    CONVERGE-SCOPE: docs/specs/<yyyymmddHHMM>-<feature-name>

this hook, running in the harness process, appends a qa receipt to the global
ledger with the agent id, type and the harness-written agent transcript path.
qa-merge-gate re-reads that transcript before honoring the receipt, so the
line is a pointer, not the proof. A verdict delivered through SubagentHandback
(no final text block) is read from the transcript by the same function.

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


def main() -> int:
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        return 0
    text = str(data.get("last_assistant_message") or "")
    tp = str(data.get("agent_transcript_path") or "")
    try:
        import receipt_ledger
        # The payload can carry a message without the verdict (or none at all)
        # when the agent reported through SubagentHandback; the transcript is
        # the fallback, read by the same function the consumers re-read with.
        fallback = None
        base = {
            "agent_id": data.get("agent_id") or "",
            "agent_type": data.get("agent_type") or "",
            "agent_transcript_path": tp,
            "session_id": data.get("session_id") or "",
        }
        for kind, parse in (("qa", receipt_ledger.parse_verdict),
                             ("converge", receipt_ledger.parse_converge)):
            verdict, scope = parse(text)
            if not verdict and tp:
                if fallback is None:
                    fallback = receipt_ledger.last_assistant_text(tp)
                verdict, scope = parse(fallback)
            if verdict:
                receipt_ledger.append_global(dict(base, kind=kind, verdict=verdict, scope=scope))
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
