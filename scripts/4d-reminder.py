#!/usr/bin/env python3
"""UserPromptSubmit hook — injects the 4D paradigm reminder into every prompt.

The operator noticed that without an explicit "4d:" cue, the 4D reasoning gets
skipped. This hook makes the cue unconditional: every input prompt now carries
the 4D + 2D-gate reminder as additionalContext, so it is never optional.

Emits JSON on stdout per the UserPromptSubmit hook contract:
  { "hookSpecificOutput": { "hookEventName": "UserPromptSubmit",
                            "additionalContext": "<reminder>" } }
"""
import json
import sys

# Drain stdin (the prompt payload) so the pipe never blocks; content unused.
try:
    sys.stdin.read()
except Exception:
    pass

REMINDER = (
    "4d: Apply the 4D paradigm to this turn — do not skip it.\n"
    "1D Describe: state what and why before acting.\n"
    "2D Delegate Gate (run at task start for any non-trivial task):\n"
    "  Q1 ¿quién sabe?  -> python3 ~/.claude/scripts/query_connectome.py query \"<task>\"\n"
    "  Q2 ¿tiene API?   -> REST > MCP > SDK > scraping\n"
    "  Q3 ¿quién lo hace? -> python3 ~/.claude/scripts/delegate-check \"<task>\"\n"
    "  Report the 3-line verdict (ACTIVATE / LOAD / SELF).\n"
    "3D Diligent: validate every write with evidence (build/lint/grep/render).\n"
    "4D Disclose: state side effects + Impact Radius.\n"
    "4D Gate: present a Change Manifest before the first file write and wait for confirmation.\n"
    "ALWAYS close every answer with a final one-line PROVENANCE footer (label per "
    "language, matching the user's input: EN 'Provenance' / ES 'Procedencia' / "
    "DE 'Herkunft'; default EN). Named fields separated by ' · '; include a field "
    "ONLY when it applies:\n"
    "  Basis: on whose authority the answer rests (own reasoning / vendor·doc / "
    "operator / <file>:<line>).\n"
    "  Engine: the main-loop model, plus any sub-agent/sub-tool that ran on a "
    "different engine (e.g. a Haiku arm) — makes model-routing visible.\n"
    "  Touched: files WRITTEN this turn with markers (+ created, ~ modified, "
    "- deleted); OMIT entirely on read-only turns.\n"
    "  Verified: one-line 3D evidence (build/lint/grep/run); OMIT when nothing "
    "was written.\n"
    "Keep paths relative and the whole footer to one line. Never mismatch the language."
)

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": REMINDER,
    }
}))
