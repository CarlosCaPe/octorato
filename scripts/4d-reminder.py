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
    "ALWAYS close every answer with a final source line stating on whose authority "
    "it rests (Opus's own reasoning, a vendor/doc, the operator, or <file>:<line>) "
    "AND naming the engine(s) that produced the work: the main-loop model, plus any "
    "sub-agent / sub-tool that ran on a different engine (e.g. a Haiku arm). When work "
    "was delegated to a cheaper engine, say so — this makes model-routing visible. "
    "Write that line in the SAME language as the user's input, using the neutral "
    "source noun: English -> 'Source: <who>'; Spanish -> 'Fuente: <quién>'; "
    "German -> 'Quelle: <wer>'; any other language -> default to English "
    "'Source: <who>'. Never mismatch the language."
)

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": REMINDER,
    }
}))
