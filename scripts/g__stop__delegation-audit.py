#!/usr/bin/env python3
"""g__stop__delegation-audit.py: Stop gate for FLOW.bulk-fetch-delegation.

The model-ladder rule ("never burn the build/judgment engine on what a cheaper
tier does") was chronically skipped under load: the PreToolUse nudge in
delegate-gate.py is fail-open because that event carries no main-loop vs
sub-agent discriminator. This gate closes the loop where the discriminator DOES
exist: Stop fires only when the MAIN loop ends its turn, and the per-turn
ledger written by d__posttool__delegation-ledger.py (PostToolUse *) records
what the turn actually did.

Blocks ONCE (stop_hook_active pattern, same as g__stop__draft-promise.py) when
the ended turn:
  - made >= FETCH_CALLS_MIN external-fetch tool calls (mcp__* / WebFetch /
    WebSearch), AND
  - their responses totalled >= FETCH_BYTES_MIN bytes, AND
  - never invoked Agent/Task/Workflow (zero delegation), AND
  - the reply does not carry the waiver token `delegation-ok`.

The demanded rewrite: route the bulk fetch through a cheap-tier sub-agent that
returns a compressed digest, or keep the result and waive consciously with
`delegation-ok <reason>` in the reply (judgment-tier triage of sensitive
content is a valid reason). Mirrors the `draft-promise-ok` waiver idiom.

Ledger handling: the production ledger is consumed (truncated) on every audit
so each turn starts clean. Fixtures inject `ledger_path` in the payload
(relative paths resolve against the fixture transcript's directory); fixture
ledgers are never truncated. Exit code is always 0; blocking is carried only by
the {"decision": "block"} JSON.
"""
import json
import os
import sys
from pathlib import Path

FETCH_CALLS_MIN = 6
FETCH_BYTES_MIN = 40_000
WAIVER = "delegation-ok"
FETCH_PREFIX = "mcp__"
FETCH_TOOLS = {"WebFetch", "WebSearch"}
_TAIL_BYTES = 262_144


def _tail_lines(path: Path, max_bytes: int = _TAIL_BYTES):
    size = path.stat().st_size
    with path.open("rb") as fh:
        if size > max_bytes:
            fh.seek(size - max_bytes)
            fh.readline()  # drop the partial line at the cut
        return fh.read().decode("utf-8", "replace").splitlines()


def _last_assistant_text(transcript_path: str) -> str:
    p = Path(transcript_path or "")
    if not p.is_file():
        return ""
    for ln in reversed(_tail_lines(p)):
        ln = ln.strip()
        if not ln:
            continue
        try:
            entry = json.loads(ln)
        except ValueError:
            continue
        if entry.get("type") != "assistant":
            continue
        parts = []
        content = (entry.get("message") or {}).get("content") or []
        if isinstance(content, list):
            for blk in content:
                if isinstance(blk, dict) and blk.get("type") == "text":
                    parts.append(blk.get("text") or "")
        # first (most recent) assistant record only; older ones are stale replies
        return "\n".join(parts)
    return ""


def _load(p: Path):
    if not p.is_file():
        return []
    recs = []
    for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            recs.append(json.loads(ln))
        except ValueError:
            continue
    return recs


def _ledger_records(data: dict):
    """Return (records, production_ledger_or_None). Fixture ledgers are read-only."""
    lp = data.get("ledger_path")
    if isinstance(lp, str) and lp:
        p = Path(lp)
        if not p.is_absolute():
            p = Path(os.path.dirname(data.get("transcript_path") or "")) / lp
        return _load(p), None
    sid = data.get("session_id") or os.environ.get("CLAUDE_SESSION_ID", "adhoc")
    p = Path.home() / ".claude" / ".cache" / "delegation-ledger" / f"{sid}.turn.jsonl"
    return _load(p), p


_WRITE_VERBS = ("send", "create", "update", "delete", "revoke", "draft", "label")


def _is_fetch(tool: str) -> bool:
    """External read-shaped calls only; mcp write-verbs (sends etc.) never count."""
    if tool in FETCH_TOOLS:
        return True
    if not tool.startswith(FETCH_PREFIX):
        return False
    action = tool.rsplit("__", 1)[-1]
    return not action.startswith(_WRITE_VERBS)


def main() -> int:
    data = json.loads(sys.stdin.read() or "{}")
    # Consume the ledger on EVERY Stop fire, including the stop_hook_active
    # refire after another gate blocked: records appended while the model
    # answered that block must not leak into the NEXT turn's audit.
    recs, prod_ledger = _ledger_records(data)
    if prod_ledger is not None and prod_ledger.is_file():
        try:
            prod_ledger.write_text("", encoding="utf-8")  # next turn starts clean
        except OSError:
            pass
    if data.get("stop_hook_active"):
        return 0  # already blocked once this turn; never loop
    if not recs:
        return 0
    if any(r.get("delegation") for r in recs):
        return 0
    fetches = [r for r in recs if _is_fetch(str(r.get("tool", "")))]
    n = len(fetches)
    total = sum(int(r.get("b") or 0) for r in fetches)
    if n < FETCH_CALLS_MIN or total < FETCH_BYTES_MIN:
        return 0
    if WAIVER in _last_assistant_text(data.get("transcript_path", "")):
        return 0
    print(json.dumps({
        "decision": "block",
        "reason": (
            f"FLOW.bulk-fetch-delegation: this turn made {n} external fetch calls "
            f"(~{total // 1024} KB) in the MAIN loop with zero delegation "
            "(no Agent/Task/Workflow). Ladder rule: bulk fetch goes to a cheap-tier "
            "sub-agent that returns a compressed digest; the main loop keeps the "
            "judgment. Close the turn either by delegating the sweep now, or by "
            "keeping it consciously with `delegation-ok <reason>` in the reply "
            "(e.g. sensitive-content triage that needs judgment tier). "
            "This gate blocks only once per turn."
        ),
    }))
    return 0


def _selftest() -> int:
    import gate_selftest
    argv = sys.argv
    fixture = argv[argv.index("--selftest") + 1] if len(argv) > argv.index("--selftest") + 1 \
        else "registry/fixtures/FLOW.bulk-fetch-delegation"
    return gate_selftest.run_gate_selftest(__file__, fixture)


if __name__ == "__main__":
    try:
        if "--selftest" in sys.argv:
            sys.exit(_selftest())
        sys.exit(main())
    except Exception:
        sys.exit(0)
