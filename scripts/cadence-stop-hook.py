#!/usr/bin/env python3
"""cadence-stop-hook.py — Stop hook: human-cadence enforcement for CHAT output.

The file linter (cadence-lint.py, PostToolUse) covers prose WRITES, but chat
replies — the comments and messages the operator actually asked for — never
pass through a Write tool. They relied on instruction + discipline, and the
tells kept shipping (operator caught it twice, 2026-06-04). This hook closes
that gap: when the assistant finishes a reply, lint its text against the
mechanical subset of the 10 no-rules; on violations, BLOCK once with the list
so the reply is rewritten before the operator ever sees it.

Reuses lint_text() from the sibling cadence-lint.py (same dir — works from
~/.claude/scripts/ AND from the ~/.octorato/bin/ bridge), so canon lives in
exactly one file.

Loop safety: payload field stop_hook_active=true means we already blocked this
turn — pass, never loop. Fail-open on every error: a broken linter must never
hold a conversation hostage.

What gets stripped before linting (not prose):
  - fenced code blocks (``` ... ```)
  - inline code spans (`...`)
  - the Provenance/Procedencia/Herkunft footer line (machine receipt, exempt)
  - lines containing 'cadence-ok' (deliberate quotation)

Stdin:  {"transcript_path": str, "stop_hook_active": bool, ...}
Stdout: {"decision": "block", "reason": "..."} on violations, else nothing.
Exit:   always 0.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
# Force UTF-8 on stdout/stderr so the ✓ / ✗ / em-dash glyphs in reports
# survive on Windows shells defaulting to cp1252. Without this, a script
# can do its work correctly and still crash with UnicodeEncodeError when
# printing success. Applied repo-wide by _apply-utf8-reconfigure.py.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


_FOOTER = re.compile(r"^\s*(Provenance|Procedencia|Herkunft)\s*:", re.IGNORECASE)
_FENCE = re.compile(r"```.*?```", re.DOTALL)
_INLINE = re.compile(r"`[^`\n]*`")


def _load_linter():
    """Import lint_text from the sibling cadence-lint.py (canon, single file)."""
    sibling = Path(__file__).resolve().parent / "cadence-lint.py"
    spec = importlib.util.spec_from_file_location("cadence_lint", sibling)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tail_lines(path: str, max_bytes: int = 262144) -> list:
    """Read only the transcript tail: the last assistant entry lives in the
    final KBs, and late-session transcripts run tens of MB (QA finding 7)."""
    import os
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


def _strip_non_prose(text: str) -> str:
    text = _FENCE.sub("", text)
    # Unclosed trailing fence: drop it and everything after, else its code
    # content gets linted as prose and false-blocks (QA finding 3).
    text = re.sub(r"```.*", "", text, flags=re.DOTALL)
    text = _INLINE.sub("", text)
    kept = [
        ln for ln in text.splitlines()
        if not _FOOTER.match(ln) and "cadence-ok" not in ln
    ]
    return "\n".join(kept)


def main() -> int:
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        return 0

    if data.get("stop_hook_active"):
        # One-shot contract (QA finding 1): Claude Code sets this true on the
        # Stop event AFTER our block, so a rewrite that still has violations
        # ships anyway. Intended: one forced rewrite per turn, never a loop.
        return 0

    transcript = data.get("transcript_path") or ""
    if not transcript:
        return 0

    try:
        text = _strip_non_prose(_last_assistant_text(transcript))
        if not text.strip():
            return 0
        lint = _load_linter()
        hits = lint.lint_text(text)
    except Exception:
        return 0  # fail-open: a broken linter never holds the conversation

    if not hits:
        return 0

    listing = "; ".join(
        f"rule {n} ({label}): …{frag[:48]}…" for n, label, _ln, frag in hits[:12]
    )
    extra = f" (+{len(hits) - 12} more)" if len(hits) > 12 else ""
    try:
        print(json.dumps({
            "decision": "block",
            "reason": (
                f"✍ CADENCE on your reply: {len(hits)} violation(s) of the human-cadence "
                f"no-rules the operator explicitly banned. {listing}{extra}. "
                f"REWRITE the reply now applying skills/human-cadence: same meaning, "
                f"no em-dashes, no AI filler, no contrast frames, no rigid transitions, "
                f"no filler openers, no summary tails. Then deliver the rewritten version."
            ),
        }))
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
