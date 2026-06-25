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
# Force UTF-8 on stdout/stderr so the ✓ / ✗ / em-dash glyphs in reports
# survive on Windows shells defaulting to cp1252. Without this, a script
# can do its work correctly and still crash with UnicodeEncodeError when
# printing success. Applied repo-wide by _apply-utf8-reconfigure.py.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


# Drain stdin (the prompt payload) so the pipe never blocks; content unused.
try:
    sys.stdin.read()
except Exception:
    pass

# Ordering is deliberate (panel of 10 + 3 reviews, 2026-06-25): the two
# most-skipped pieces are the 2D verdict and the Provenance footer. Recency
# wins under a multi-injector context wall, so the ritual ask the model must
# RENDER (1D / 2D verdict / 3D) sits LAST in this string, closest to
# generation; the verbose footer spec sits earlier and compressed (full spec
# lives in skills/4d-paradigm-protocol). No em-dashes (brain cadence rule 1).
REMINDER = (
    "4d: Apply the 4D paradigm to this turn. Do not skip it.\n"
    "4D Disclose: state side effects + Impact Radius. 4D Gate: present a Change "
    "Manifest before the first file write and wait for confirmation.\n"
    "PROVENANCE FOOTER (always close with it, one line, label per the user's "
    "language: EN 'Provenance' / ES 'Procedencia' / DE 'Herkunft', default EN; "
    "fields separated by ' · ', include each only when it applies): "
    "Basis (whose authority: own reasoning / vendor·doc / operator / <file>:<line>) · "
    "Engine (main-loop model + any sub-agent on a different engine) · "
    "Touched (files WRITTEN, + created ~ modified - deleted; omit on read-only) · "
    "Verified (one-line build/lint/grep/run evidence; omit if nothing written) · "
    "Graph (SEEK before grep: `impact-radius.py --file <path>`; quote the receipt "
    "SEEK-COMPLETE / SEEK-PARTIAL:n / GREP-FALLBACK). Full spec: "
    "skills/4d-paradigm-protocol.\n"
    "--- RENDER THESE IN YOUR REPLY, they are the most-skipped, do them LAST so "
    "they stay closest to your output ---\n"
    "1D Describe: state what and why before acting.\n"
    "2D Delegate Gate (any non-trivial task): "
    "Q1 ¿quién sabe? `query_connectome.py query \"<task>\"`; "
    "Q2 ¿API? REST > MCP > SDK > scraping; "
    "Q3 ¿quién lo hace? `delegate-check \"<task>\"`. "
    "PRINT the verdict line: ACTIVATE / LOAD / SELF.\n"
    "3D Diligent: validate every write with evidence (build/lint/grep/render).\n"
    "REQUIRED in any non-trivial reply: the 2D verdict line (ACTIVATE/LOAD/SELF) "
    "near the top, and the Provenance footer at the very end."
)

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": REMINDER,
    }
}))
