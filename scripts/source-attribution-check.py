#!/usr/bin/env python3
"""Stop hook — every answer MUST end stating its source/authority ("según quién").

The operator's rule: always, always, always close the response telling him on
whose authority the answer rests — Opus's own reasoning, a vendor/doc, the
operator himself, a specific file, etc. (This is the "cite sources" rule from
CLAUDE.md, enforced at exit.)

Mechanism: on Stop, read the last assistant message from the transcript. If it
lacks an attribution marker, block and feed back a reason so the model appends
one. Self-limiting:
  - `stop_hook_active` true  -> already continuing from a stop hook; allow (no loop)
  - marker present           -> allow
  - transcript unreadable    -> allow (fail-open; never trap the operator)
"""
import json
import re
import sys

# Markers that count as a valid source line (case-insensitive, anywhere near end).
MARKERS = re.compile(r"(seg[uú]n:|fuente:|according to|source:)", re.IGNORECASE)


def allow():
    sys.exit(0)


def block(reason: str):
    print(json.dumps({"decision": "block", "reason": reason}))
    sys.exit(0)


def main():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        allow()

    # Loop guard: if we are already in a stop-hook-triggered continuation, let it stop.
    if payload.get("stop_hook_active"):
        allow()

    transcript_path = payload.get("transcript_path")
    if not transcript_path:
        allow()

    # Collect assistant text messages from the JSONL transcript.
    # NOTE: the current turn's final message is often not flushed yet when this
    # Stop hook runs (a race), so we tolerate it by checking the last few
    # assistant messages, not just the single latest one. Per-turn enforcement
    # is handled up front by the UserPromptSubmit 4d-reminder injection.
    texts = []
    try:
        with open(transcript_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                msg = entry.get("message", {})
                if msg.get("role") != "assistant":
                    continue
                content = msg.get("content", "")
                if isinstance(content, list):
                    text = " ".join(
                        b.get("text", "") for b in content
                        if isinstance(b, dict) and b.get("type") == "text"
                    )
                else:
                    text = str(content)
                if text.strip():
                    texts.append(text)
    except Exception:
        allow()

    recent = texts[-3:]
    if not recent:
        allow()

    if any(MARKERS.search(t) for t in recent):
        allow()

    block(
        "Falta la línea de fuente. Cierra SIEMPRE tu respuesta con una línea "
        "final 'Según: <quién>' que indique la autoridad de lo respondido — "
        "p.ej. 'Según: razonamiento de Opus', 'Según: docs de <vendor>', "
        "'Según: el operador', o 'Según: <archivo>:<línea>'. Agrégala ahora."
    )


if __name__ == "__main__":
    main()
