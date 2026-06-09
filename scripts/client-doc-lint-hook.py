#!/usr/bin/env python3
"""client-doc-lint-hook.py — PostToolUse(Bash) reflex wrapper for client-doc-lint.

Fires after a Bash command. If the command produced/touched a CLIENT deliverable
PDF (filename matches propuesta|cotiza|contrato|propos), it runs client-doc-lint
on that PDF and, only when the lint FAILS, surfaces the verdict as
additionalContext so the model fixes it before declaring "listo para enviar".

Design (per command-boundary-hook-matching + hook-profile-gating + reflexes-over-discipline):
  - ADVISORY ONLY: always exit 0, never blocks the tool.
  - Boundary-safe: ignores echo/comment/commit-message lines so a .pdf MENTIONED
    in a string does not false-fire; only acts on real .pdf paths that EXIST.
  - Scoped: only client-document filenames, to stay quiet on unrelated PDFs.
  - Fail-open: any internal error → exit 0 silently (a hook must never crash a tool).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
LINT = SCRIPT_DIR / "client-doc-lint.py"
CLIENT_DOC = re.compile(r"(propuesta|cotiza|contrato|propos)", re.I)
PDF_TOKEN = re.compile(r"""(?:^|[\s'"=])((?:/|\.{0,2}/|~)?[^\s'"]+\.pdf)""", re.I)
SKIP_LINE = re.compile(r"^\s*(echo|#|cat\b|printf)|commit\s+-m|-m\s+['\"]", re.I)


def emit(msg: str) -> None:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PostToolUse", "additionalContext": msg}}))


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    if data.get("tool_name") != "Bash":
        return 0
    cmd = (data.get("tool_input") or {}).get("command", "") or ""
    if not LINT.exists():
        return 0

    # Boundary-safe: drop lines that only MENTION a pdf (echo/commit/comment).
    paths = []
    for line in cmd.splitlines():
        if SKIP_LINE.search(line):
            continue
        for m in PDF_TOKEN.finditer(line):
            p = m.group(1).replace("~", str(Path.home()), 1)
            if CLIENT_DOC.search(Path(p).name):
                paths.append(p)
    seen, fails = set(), []
    for p in paths:
        if p in seen:
            continue
        seen.add(p)
        fp = Path(p)
        if not fp.exists():
            continue
        try:
            r = subprocess.run([sys.executable, str(LINT), str(fp)],
                               capture_output=True, text=True, timeout=90)
        except Exception:
            continue
        if r.returncode != 0:
            fails.append(r.stdout.strip())
    if fails:
        emit("client-doc-lint marcó FAIL en un entregable de cliente recién "
             "generado. Corrige ANTES de declararlo listo para enviar:\n\n"
             + "\n\n".join(fails))
    return 0


if __name__ == "__main__":
    sys.exit(main())
