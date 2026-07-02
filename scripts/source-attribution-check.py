#!/usr/bin/env python3
"""source-attribution-check.py: Stop hook, every answer MUST end with its provenance.

The operator's rule (CLAUDE.md "Cite sources"): always close the response stating on
whose authority it rests. v6 promotes this from advisory to a fail-closed GATE:
block ONCE when the final reply carries no provenance marker, so the footer is
appended before the operator ever sees the answer.

The two false-positive classes that kept this advisory are killed by porting the
proven tail-read from cadence-stop-hook.py:63-97:
  - read ONLY the LAST assistant entry (never a stale earlier tool-turn message);
  - one forced rewrite per turn via the stop_hook_active loop guard.

Fail-open on every error: a broken hook must never hold a conversation hostage.

Stdin:  {"transcript_path": str, "stop_hook_active": bool, ...}
Stdout: {"decision": "block", "reason": "..."} when the marker is absent, else nothing.
Exit:   always 0.
"""
from __future__ import annotations

import json
import os
import re
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


# Markers that count as a valid provenance/source footer (case-insensitive).
# Current: Provenance (EN) / Procedencia (ES) / Herkunft (DE) one-line footer.
# Back-compat: Source / Fuente / Quelle and legacy "según" / "according to".
MARKERS = re.compile(
    r"(provenance|procedencia|herkunft|source:|fuente:|quelle:|seg[uú]n:|according to)",
    re.IGNORECASE,
)


def _tail_lines(path: str, max_bytes: int = 262144) -> list:
    """Read only the transcript tail: the last assistant entry lives in the
    final KBs, and late-session transcripts run tens of MB."""
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        fh.seek(max(0, size - max_bytes))
        return fh.read().decode("utf-8", errors="replace").splitlines()


def _last_assistant_text(transcript_path: str) -> str:
    """Text blocks of the LAST assistant entry in the JSONL. Stops at that entry
    whether or not it has text, so a tool-only final turn never lints a stale
    earlier reply (the flush-race false positive that kept this advisory)."""
    text_parts: list = []
    try:
        lines = _tail_lines(transcript_path)
    except OSError:
        return ""
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "assistant":
            continue
        content = (entry.get("message") or {}).get("content") or []
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
        elif isinstance(content, str):
            text_parts.append(content)
        break  # ALWAYS stop at the last assistant entry, text or not
    return "\n".join(text_parts)


_BLOCK_REASON = (
    "Your reply has no provenance footer. Close it, in the user's language, with a "
    "final source line: 'Provenance: <basis>' (EN) / 'Procedencia: <base>' (ES) / "
    "'Herkunft: <basis>' (DE). Then deliver the answer. See CLAUDE.md 'Cite sources'."
)


def main() -> int:
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0

    # Loop guard: already blocked this turn once, never loop.
    if data.get("stop_hook_active"):
        return 0

    transcript = data.get("transcript_path") or ""
    if not transcript:
        return 0

    try:
        text = _last_assistant_text(transcript)
        if not text.strip():
            return 0  # tool-only final turn: nothing to attribute
        if MARKERS.search(text):
            return 0  # footer present, allow
    except Exception:
        return 0  # fail-open: a broken hook never holds the conversation

    try:
        print(json.dumps({"decision": "block", "reason": _BLOCK_REASON}))
    except Exception:
        pass
    return 0


def _selftest() -> int:
    import gate_selftest
    argv = sys.argv
    fixture = argv[argv.index("--selftest") + 1] if len(argv) > argv.index("--selftest") + 1 \
        else "registry/fixtures/CODE.cite-sources"
    return gate_selftest.run_gate_selftest(__file__, fixture)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
