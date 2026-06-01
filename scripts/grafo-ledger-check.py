#!/usr/bin/env python3
"""Stop hook — graph ledger check (¿se usó el grafo?).

Reads the per-turn graph ledger written by impact-radius.py and, at the end of a
turn, surfaces how the brain was queried: seeks vs grep-fallbacks. Its job is to
make graph-use VISIBLE so a turn cannot quietly end on a scan.

INCREMENT 1 = ADVISORY (systemMessage, exit 0). It flags grep-fallbacks (unlit
neurons) so an edge gets added and the next lookup is a seek. The real TEETH — a
PreToolUse Bash gate that intercepts an impact-shaped scan, plus a Stop decision:block
when a turn grep'd brain paths AND wrote files with zero seek receipt — land in
increment 2 (they need a ground-truth write-detector, not model narration).

Ledger: ~/.claude/.cache/graph-ledger/<CLAUDE_SESSION_ID>.jsonl (gitignored scratch).
"""
import os
import sys
import json
from pathlib import Path

LEDGER_DIR = Path.home() / ".claude" / ".cache" / "graph-ledger"


def main() -> int:
    sid = os.environ.get("CLAUDE_SESSION_ID", "adhoc")
    f = LEDGER_DIR / f"{sid}.jsonl"
    if not f.exists():
        return 0
    seeks = fallbacks = 0
    unlit = []
    try:
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            st = e.get("state")
            if st == "SEEK-COMPLETE":
                seeks += 1
            elif st == "GREP-FALLBACK":
                fallbacks += 1
                if e.get("target"):
                    unlit.append(e["target"])
    except OSError:
        return 0

    if fallbacks:
        msg = (
            f"♦ graph ledger: {seeks} seek(s), {fallbacks} grep-fallback(s) this session. "
            f"Unlit neurons hit: {', '.join(unlit[-5:])}. "
            "A fallback is a PASS that grows the graph — add the edge to "
            "connectome/lineage.yaml (or company/connectome/lineage.yaml for arm/private) "
            "so the next lookup is a deterministic seek, not a ~100x-costlier scan."
        )
        print(json.dumps({"systemMessage": msg}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
