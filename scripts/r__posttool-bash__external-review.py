#!/usr/bin/env python3
"""r__posttool-bash__external-review.py: complete an External_Review_Receipt (v11 AC-18).

PostToolUse Bash reflex. For the same harness tool_use_id as a pending
`external` receipt whose pre-call checks all held, it re-parses the command,
re-runs every pin, environment, startup-file and engine-config check after
the call, and only then copies the full output to
~/.claude/.cache/receipts/external/<tool_use_id>.out and appends the COMPLETE
receipt with the output's SHA-256, the exit code and the panel and QA
verdicts the output ends on. Any failed check writes nothing.

Never blocks, prints nothing, fails open. Logic: scripts/external_review.py.
Consumers: receipt_ledger.panel_receipts_for (AC-24 to AC-27) and
r__subagent-stop__qa-receipt.py (`external_reviewers`, AC-28).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    try:
        import external_review
        sys.exit(external_review.hook_main(external_review.post_hook))
    except Exception:
        sys.exit(0)
