#!/usr/bin/env python3
"""canon-heal-hook — the per-edit reflex (autonomic Hz of the content canon).

Wired as a PostToolUse Write|Edit hook. After any file write, if that file
carries a canon marker, it self-heals to the canonical value via canon-render
--file. This is the smallest "transcend the marionette" unit: a fact edited by
hand snaps back to canon on save, with no prompt, no review, no string pulled.

Safe by construction:
  • acts ONLY on files that already contain "<!--canon:" (a cheap substring
    guard) — never touches arbitrary files;
  • canon-render writes via plain file I/O, not the Edit tool, so it does NOT
    retrigger this hook (no loop);
  • canon-render is idempotent — a file already in unison is a no-op;
  • any error exits 0 (a reflex must never block the operator's edit).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    fp = (data.get("tool_input") or {}).get("file_path")
    if not fp:
        return 0
    path = Path(fp)
    if not path.is_absolute():
        path = (ROOT / fp).resolve()
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return 0
    if "<!--canon:" not in text:
        return 0  # not a subscribed surface — stay silent
    try:
        subprocess.run(
            ["python3", str(ROOT / "scripts" / "canon-render.py"), "--file", str(path)],
            timeout=30,
            capture_output=True,
        )
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
