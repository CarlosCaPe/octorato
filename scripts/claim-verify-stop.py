#!/usr/bin/env python3
"""claim-verify-stop.py — Stop hook: block-once when visual/runtime claims lack proof.

When the assistant asserts completion of a visual, runtime, or deploy change
("verified", "done", "deployed", "live", etc.) but the recent transcript shows
no verification evidence (no agent-browser, screenshot, curl check, dist grep),
block once and ask for the proof.

Conservative by design: any doubt → pass. A false positive here disrupts real
work more than a false negative. If transcript is missing or unreadable → pass.

Loop safety: stop_hook_active=true means we already blocked this turn — pass,
never loop. Fail-open on every exception.

Stdin:  {"transcript_path": str, "stop_hook_active": bool, ...}
Stdout: {"decision": "block", "reason": "..."} on violations, else nothing.
Exit:   always 0.
"""
from __future__ import annotations

import json
import os
import re
import signal as _signal_mod
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


BUDGET_S = 5  # hard self-timeout; a hung Stop hook blocks the shell


# ── condition A: completion assertion about a visual/runtime artifact ─────────

_RE_VERIFY_CLAIM = re.compile(
    r"(?:"
    r"(verified|confirmed|tested|validated)\b[^.!?\n]{0,60}\b(render|screenshot|page|ui|button|site|dashboard|preview|deploy|live|visual|runtime)"
    r"|"
    r"(render|screenshot|page|ui|button|site|dashboard|preview|deploy|live|visual|runtime)\b[^.!?\n]{0,60}\b(verified|confirmed|tested|validated)"
    r")",
    re.IGNORECASE,
)

# ── condition B: verification evidence in recent transcript ───────────────────

_RE_EVIDENCE = re.compile(
    r"(agent-browser|screenshot|"
    r'"tool_name"\s*:\s*"Read"[^}]*dist/|'       # Read of built artifact
    r'grep[^|]*dist/|grep[^|]*build/|'            # grep of dist/build
    r'curl\b.*https?://|'                          # curl with an HTTP check
    r'"tool_name"\s*:\s*"Bash"[^}]*curl)',
    re.IGNORECASE | re.DOTALL,
)

_BLOCK_REASON = (
    "You claimed verified/done on a visual or runtime change with no proof in the "
    "transcript. Show it: agent-browser screenshot + Read, or curl, or grep the "
    "built output. See verify-visually-before-claiming."
)


# ── transcript helpers (copied verbatim from cadence-stop-hook.py) ────────────

def _tail_lines(path: str, max_bytes: int = 262144) -> list:
    """Read only the transcript tail: the last assistant entry lives in the
    final KBs, and late-session transcripts run tens of MB (QA finding 7)."""
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        fh.seek(max(0, size - max_bytes))
        return fh.read().decode("utf-8", errors="replace").splitlines()


def _last_assistant_text(transcript_path: str) -> str:
    """Text blocks of the LAST assistant entry in the JSONL. Stops at that
    entry whether or not it has text: falling through to an OLDER message
    lints a stale reply, producing spurious blocks when the final action was
    a tool call (QA finding 2)."""
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


def _recent_transcript_text(transcript_path: str, max_bytes: int = 8192) -> str:
    """Raw text of the last max_bytes of the transcript for evidence scanning."""
    try:
        with open(transcript_path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - max_bytes))
            return fh.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def main() -> int:
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        return 0

    if data.get("stop_hook_active"):
        # One-shot contract: already blocked this turn — never loop.
        return 0

    transcript = data.get("transcript_path") or ""
    if not transcript:
        return 0

    # Set up hard budget
    _signal = None
    try:
        def _bail(*_):
            raise TimeoutError()
        _signal_mod.signal(_signal_mod.SIGALRM, _bail)
        _signal_mod.alarm(BUDGET_S)
        _signal = _signal_mod
    except Exception:
        pass

    try:
        # Condition A: last assistant message claims completion on a visual noun
        last_text = _last_assistant_text(transcript)
        if not last_text.strip():
            return 0

        if not _RE_VERIFY_CLAIM.search(last_text):
            return 0  # condition A not met — pass

        # Condition B: scan last 8KB for evidence; if any found — pass
        recent = _recent_transcript_text(transcript, max_bytes=8192)
        if _RE_EVIDENCE.search(recent):
            return 0  # evidence found — pass

        # Both conditions met, no evidence: block once
        print(json.dumps({"decision": "block", "reason": _BLOCK_REASON}))

    except Exception:
        pass  # fail-open: a broken hook must never hold a conversation hostage
    finally:
        if _signal is not None:
            try:
                _signal.alarm(0)
            except Exception:
                pass

    return 0


def _selftest() -> int:
    import gate_selftest
    argv = sys.argv
    fixture = argv[argv.index("--selftest") + 1] if len(argv) > argv.index("--selftest") + 1 \
        else "registry/fixtures/CODE.adversarial-verify-operator"
    return gate_selftest.run_gate_selftest(__file__, fixture)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
