#!/usr/bin/env python3
"""r__pretool-bash__external-review.py: open an External_Review_Receipt (v11 AC-18).

PreToolUse Bash reflex. When the command is an Accepted_Review_Call (one
simple command whose first two tokens are a pinned interpreter and a pinned
script, with only that engine's allowlisted arguments), it appends a PENDING
`external` receipt to ~/.claude/.cache/receipts/global.jsonl with the engine,
the pinned paths, the requested model, the prompt digest, the harness
tool_use_id, the session id, the cwd, the transcript path and the problems
the pin, environment, startup-file and engine-config checks found (empty
when all hold). The PostToolUse twin, r__posttool-bash__external-review.py,
completes it only when that list is empty and every check still holds.

Never blocks, prints nothing, fails open: a review run any other way still
runs, it just never counts. Logic: scripts/external_review.py.
Selftest: python3 scripts/external_review.py --selftest
          (registry/fixtures/FLOW.external-review-receipt).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    try:
        import external_review
        sys.exit(external_review.hook_main(external_review.pre_hook))
    except Exception:
        sys.exit(0)
