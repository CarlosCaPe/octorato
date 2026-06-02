#!/usr/bin/env python3
"""Stop hook — the graph-before-grep teeth (turn-scoped).

Reads the PER-TURN graph ledger (reset each turn by grafo-turn-reset.py; written by
impact-radius.py seeks and grafo-gate.py brain-scans) and decides, AT TURN END:

  TEETH (exit 2 → the model self-corrects next turn): the turn ran an impact-shaped
  brain SCAN for a concept the graph already KNOWS, yet ran NO seek. That is the exact
  anti-pattern — grepping memory the connectome/lineage could have answered. Classifying
  "known vs unlit" happens HERE (off the hot PreToolUse path); an unlit cold-start scan is
  legitimate and never triggers the teeth.

  ADVISORY (systemMessage, exit 0): the session hit grep-fallbacks (unlit neurons) — a
  PASS that should grow the graph; surface it so an edge gets added.

Fail-open: any error → exit 0 (never wedge the turn).
"""
import os
import sys
import json
import subprocess
from pathlib import Path

CLAUDE = Path.home() / ".claude"
LEDGER = CLAUDE / ".cache" / "graph-ledger"


def load(path: Path):
    rows = []
    if not path.exists():
        return rows
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        pass
    return rows


def concept_is_known(term: str) -> bool:
    """Off the hot path: does the lineage graph actually have an edge for this term?
    Runs the probe under a THROWAWAY session id so its own receipt never pollutes the
    real turn ledger (else classifying would look like the turn seeked)."""
    try:
        env = dict(os.environ, CLAUDE_SESSION_ID="__classify_probe__")
        out = subprocess.run(
            ["python3", str(CLAUDE / "scripts" / "impact-radius.py"), term],
            capture_output=True, text=True, timeout=8, env=env).stdout
        return "SEEK-COMPLETE" in out
    except Exception:
        return False  # if we can't tell, do NOT nudge (no false positives)


def main() -> int:
    sid = os.environ.get("CLAUDE_SESSION_ID", "adhoc")
    turn = load(LEDGER / f"{sid}.turn.jsonl")
    seeked = any(r.get("state") in ("SEEK-COMPLETE", "GREP-FALLBACK") for r in turn)
    scans = [r.get("term") for r in turn if r.get("event") == "brain_scan" and r.get("term")]

    # TEETH: a brain scan of a KNOWN concept with no seek this turn.
    if scans and not seeked:
        offenders = [t for t in dict.fromkeys(scans) if concept_is_known(t)]
        if offenders:
            print(
                "graph-before-grep: this turn SCANNED the brain (grep "
                + ", ".join(repr(t) for t in offenders[:3])
                + ") for concept(s) the graph already KNOWS, with no seek. ¿y el grafo? "
                "Run `impact-radius.py \"<concept>\"` (surfaces) or "
                "`query_connectome.py query \"<need>\"` (skills/agents) — the seek is "
                "deterministic and ~100x cheaper. A scan over a known concept is the "
                "pixelation anti-pattern; seek, then finish.",
                file=sys.stderr)
            return 2  # surfaces to the model; it self-corrects next turn

    # ADVISORY: unlit-neuron fallbacks this session (a PASS that should grow the graph).
    session = load(LEDGER / f"{sid}.jsonl")
    fallbacks = [r.get("target") for r in session if r.get("state") == "GREP-FALLBACK" and r.get("target")]
    if fallbacks:
        print(json.dumps({"systemMessage":
            f"♦ graph ledger: {len(fallbacks)} grep-fallback(s) this session "
            f"(unlit: {', '.join(dict.fromkeys(fallbacks))[:120]}). A fallback is a PASS — "
            "add the edge to connectome/lineage.yaml (or company/ for arm/private) so the "
            "next lookup is a deterministic seek."}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # fail-open
