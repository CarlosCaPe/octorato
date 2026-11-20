#!/usr/bin/env python3
"""source-attribution-check.py: Stop hook, every answer MUST end with its provenance.

The operator's rule (CLAUDE.md "Cite sources"): always close the response stating on
whose authority it rests. v6 promotes this from advisory to a fail-closed GATE:
block ONCE when the final reply carries no provenance marker, so the footer is
appended before the operator ever sees the answer.

Read order: the payload's last_assistant_message is the reply being judged.
The transcript tail is only a fallback for a harness that does not send that
key (absent, null or not a string), because the file on disk can lag the Stop
event and its last assistant entry is then the previous reply. An empty or
whitespace message means a text-free final turn: nothing to attribute.
  - the fallback reads ONLY the LAST assistant entry (ported from
    cadence-stop-hook.py:63-97);
  - one forced rewrite per turn via the stop_hook_active loop guard.

Quiet provenance (2026-11-20): the footer stays for the agent but is hidden on
the operator's screen by default. A reply with no visible marker also passes
when this session holds a provenance-ledger entry with a non-empty Basis,
that counts for this reply (scripts/provenance_ledger.py reply_view: newer
than the operator's prompt and than any full reply of this turn that already
ended a stop, never stamped more than 120 s in the future; the reply panel's
own walk and freshness rule). Session: the payload's session_id, else
OCTO_PROVENANCE_SESSION (set by panel_preflight.py for its synthetic payload).
A ledger lookup that errors counts as no entry (the reply is then blocked
once), never as provenance.

Fail-open on every other error: a broken hook must never hold a conversation hostage.

Stdin:  {"last_assistant_message": str, "transcript_path": str,
         "stop_hook_active": bool, ...}
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
for _stream in (sys.stdin, sys.stdout, sys.stderr):
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
    "This turn has no provenance. Record it off-screen (the default; the operator "
    "does not see it): `python3 ~/.claude/scripts/provenance_ledger.py record --basis "
    "'<file>:<line> / operator / vendor doc / own reasoning' --engine '<model>' "
    "[--touched ...] [--verified ...] [--graph ...] [--verdict 'ACTIVATE/LOAD/SELF']`. "
    "Print the footer line in the reply ('Provenance: <basis>' EN / 'Procedencia: "
    "<base>' ES / 'Herkunft: <basis>' DE) only when the operator asked to see it. "
    "See CLAUDE.md 'Cite sources'."
)


def _ledger_has_provenance(data: dict, text: str) -> bool:
    """True when an entry that counts for this reply (provenance_ledger.reply_view:
    newer than the prompt and than a full reply of this turn that already
    ended a stop, not stamped in the future) has a non-empty Basis. Any error
    reads as False (no entry)."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import provenance_ledger
        sid = str(data.get("session_id") or os.environ.get(
            provenance_ledger.PREFLIGHT_SESSION_ENV) or "").strip()
        tp = str(data.get("transcript_path") or "")
        got, _bound = provenance_ledger.reply_view(sid, tp, text)
        return any(str(e.get("basis") or "").strip() for e in got)
    except Exception:
        return False


def _quiet(short: str, full: str, payload=None) -> str:
    """The block reason to print: one short line naming the detail file the
    full text was written to (scripts/stop_block.py), or the FULL reason when
    that write fails, so the instructions always reach the model."""
    try:
        import stop_block
        return stop_block.shown(__file__, short, full, payload, 'CODE.cite-sources')
    except Exception:
        return full


def main() -> int:
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0

    # Loop guard: already blocked this turn once, never loop.
    if data.get("stop_hook_active"):
        return 0

    # The harness hands the final reply in the payload. Prefer it: the
    # transcript on disk can lag the Stop event by a few hundred ms, and the
    # last assistant entry there is then the PREVIOUS reply (measured: a reply
    # carrying "Procedencia:" was blocked because the tail still held the
    # status line before it). The transcript stays only as a fallback for a
    # harness that does not send the key.
    msg = data.get("last_assistant_message")
    transcript = data.get("transcript_path") or ""
    if not isinstance(msg, str) and not transcript:
        return 0

    try:
        text = msg if isinstance(msg, str) else _last_assistant_text(transcript)
        if not text.strip():
            return 0  # tool-only final turn: nothing to attribute
        if MARKERS.search(text):
            return 0  # footer present, allow
    except Exception:
        return 0  # fail-open: a broken hook never holds the conversation

    if _ledger_has_provenance(data, text):
        return 0  # recorded off-screen (quiet provenance), allow

    try:
        print(json.dumps({"decision": "block", "reason": _quiet(
            "Reply has no provenance footer or recorded entry; record one with provenance_ledger.py record",
            _BLOCK_REASON, data)}))
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
