#!/usr/bin/env python3
"""UserPromptSubmit hook — injects the 4D paradigm reminder into every prompt.

The operator noticed that without an explicit "4d:" cue, the 4D reasoning gets
skipped. This hook makes the cue unconditional: every input prompt now carries
the 4D + 2D-gate reminder as additionalContext, so it is never optional.

Emits JSON on stdout per the UserPromptSubmit hook contract:
  { "hookSpecificOutput": { "hookEventName": "UserPromptSubmit",
                            "additionalContext": "<reminder>" } }
"""
import datetime
import json
import sys
# Force UTF-8 on stdout/stderr so the ✓ / ✗ / em-dash glyphs in reports
# survive on Windows shells defaulting to cp1252. Without this, a script
# can do its work correctly and still crash with UnicodeEncodeError when
# printing success. Applied repo-wide by _apply-utf8-reconfigure.py.
for _stream in (sys.stdin, sys.stdout, sys.stderr):
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
# most-skipped pieces are the 2D verdict and the Provenance footer. Since
# 2026-11-20 both are recorded off-screen (scripts/provenance_ledger.py) and
# shown only on request: they help the agent and block the operator's reading. Recency
# wins under a multi-injector context wall, so the ritual ask the model must
# RENDER (1D / 2D verdict / 3D) sits LAST in this string, closest to
# generation; the verbose footer spec sits earlier and compressed (full spec
# lives in skills/4d-paradigm-protocol). No em-dashes (brain cadence rule 1).
# Calendar facts are DATA, never derivation. A model computing a weekday in
# its head is modular arithmetic in one forward pass: it fails silently and
# fluently (the weekday-hallucination class). Injecting today's weekday kills
# the whole class; anything beyond it (days-between, deadlines) must come from
# a tool receipt (`date`, python), never mental math.
_TODAY = datetime.date.today()
REMINDER = (
    f"TODAY IS: {_TODAY.strftime('%A')} {_TODAY.isoformat()} (injected as data; "
    "for any other date arithmetic run `date`/python and cite the receipt, "
    "never derive it mentally).\n"
    "4d: Apply the 4D paradigm to this turn. Do not skip it.\n"
    "4D Disclose: state side effects + Impact Radius. 4D Gate: present a Change "
    "Manifest before the first file write and wait for confirmation.\n"
    "PROVENANCE (always produce it, but OFF the operator's screen: record it every "
    "turn with `python3 ~/.claude/scripts/provenance_ledger.py record --basis ... "
    "--engine ... [--touched ...] [--verified ...] [--graph ...] [--verdict ...]` "
    "and do NOT print it; print the one-line footer, label per the user's language "
    "EN 'Provenance' / ES 'Procedencia' / DE 'Herkunft', only when the operator asks "
    "to see it (`provenance_ledger.py show` renders it). Fields (each only when it "
    "applies): "
    "Basis (whose authority: own reasoning / vendor·doc / operator / <file>:<line>) · "
    "Engine (main-loop model + any sub-agent on a different engine) · "
    "Touched (files WRITTEN, + created ~ modified - deleted; omit on read-only) · "
    "Verified (one-line build/lint/grep/run evidence; omit if nothing written) · "
    "[PATHS: every path in Basis and Touched MUST be ABSOLUTE and OPENABLE in the "
    "host OS's native form (C:\\Users\\... on Windows, /home/... on POSIX), never "
    "repo-relative and never a bare filename. Several files in one directory: give "
    "the directory once, then the basenames. File outside the working directory: "
    "add a percent-encoded file:// URL so it opens from any client.] · "
    "Graph (SEEK before grep: `impact-radius.py --file <path>`; quote the receipt "
    "SEEK-COMPLETE / SEEK-PARTIAL:n / GREP-FALLBACK). Full spec: "
    "skills/4d-paradigm-protocol.\n"
    "--- DO THESE EVERY TURN, they are the most-skipped, so they sit LAST, closest "
    "to your output ---\n"
    "1D Describe: state what and why before acting.\n"
    "2D Delegate Gate (any non-trivial task): "
    "Q1 ¿quién sabe? `query_connectome.py query \"<task>\"`; "
    "Q2 ¿API? REST > MCP > SDK > scraping; "
    "Q3 ¿quién lo hace? `delegate-check \"<task>\"`. "
    "Record the verdict line (ACTIVATE / LOAD / SELF) with --verdict in the "
    "provenance ledger; do not print it.\n"
    "3D Diligent: validate every write with evidence (build/lint/grep/render).\n"
    "REQUIRED every turn: the 2D verdict and the provenance recorded with "
    "provenance_ledger.py record (the Stop gates read it there), hidden on the "
    "operator's screen by default and shown only when the operator asks. The "
    "screen gets the diagram and the short bullets, not these logs."
)

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": REMINDER,
    }
}))
