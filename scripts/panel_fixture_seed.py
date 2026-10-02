#!/usr/bin/env python3
"""panel_fixture_seed.py: seed panel receipts into an outward-send fixture home.

Requirement 5 of g__pretool-mcp__outward-send.py denies every message send that
carries no PASS panel receipt for its exact digest. A fixture that exists to
prove ANOTHER check (an absence claim, a promise, a missing send ask) must not
be denied by the panel instead, or its leg proves nothing about that check. So
every message-send fixture of such a directory gets a PASS receipt for its own
body, written the way the harness and the SubagentStop reflex write one:

  home/.claude/projects/fx/<session>/subagents/agent-<id>.jsonl
        a reviewer transcript: one prompt entry, one assistant entry ending
        PANEL-VERDICT / PANEL-SHA256, every harness field present, timestamped
        five minutes before the fixture's own operator turn
  home/.claude/.cache/receipts/global.jsonl
        the `panel` row pointing at that entry by uuid (path under `~`, which
        the reader expands inside the selftest's throwaway HOME)

Idempotent: a fixture already seeded (same agent id) is skipped. A fixture
whose message the gate cannot read with certainty is skipped too, and printed.

Usage: panel_fixture_seed.py <fixture_dir> [--only <payload.json> ...]
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import panel_digest  # noqa: E402


def _human_ts(transcript: Path) -> str:
    ts = ""
    try:
        for line in transcript.read_text(encoding="utf-8").splitlines():
            e = json.loads(line)
            if e.get("type") == "user" and e.get("timestamp"):
                ts = e["timestamp"]
    except (OSError, ValueError):
        return ""
    return ts


def _uuid(seed: str) -> str:
    h = hashlib.sha256(seed.encode()).hexdigest()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def seed_receipt(home: Path, session: str, digest: str, verdict: str, ts: str,
                 agent_id: str, agent_type: str = "Reality Checker",
                 report_digest: str | None = None) -> bool:
    """Write one reviewer transcript entry and its ledger row. `report_digest`
    lets a fixture make the transcript say something other than the row (a
    forged row). Returns False when this agent id was already seeded."""
    rel = Path(".claude") / "projects" / "fx" / session / "subagents" / f"agent-{agent_id}.jsonl"
    tp = home / rel
    if tp.exists():
        return False
    tp.parent.mkdir(parents=True, exist_ok=True)
    prompt_uuid, entry_uuid = _uuid(agent_id + "p"), _uuid(agent_id + "a")
    t = _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    p_ts = (t - _dt.timedelta(seconds=30)).isoformat().replace("+00:00", "Z")
    report = (f"Reviewed the message.\nPANEL-VERDICT: {verdict}\n"
              f"PANEL-SHA256: {report_digest or digest}")
    entries = [
        {"type": "user", "message": {"role": "user", "content": "Panel: review this outgoing message."},
         "uuid": prompt_uuid, "parentUuid": None, "sessionId": session, "timestamp": p_ts},
        {"type": "assistant", "message": {"role": "assistant", "id": f"msg_{agent_id}",
                                          "content": [{"type": "text", "text": report}]},
         "uuid": entry_uuid, "parentUuid": prompt_uuid, "sessionId": session, "timestamp": ts},
    ]
    tp.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries), encoding="utf-8")
    ledger = home / ".claude" / ".cache" / "receipts" / "global.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    row = {"kind": "panel", "verdict": verdict, "digest": digest, "agent_id": agent_id,
           "agent_type": agent_type, "agent_transcript_path": "~/" + rel.as_posix(),
           "session_id": session, "entry_uuid": entry_uuid, "entry_ts": ts, "ts": ts}
    with ledger.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return True


def _with_home(home: Path, fn):
    """Run fn with HOME pointed at the fixture home, so `~` attachments resolve
    exactly as they will inside the selftest sandbox."""
    import os
    old = os.environ.get("HOME")
    os.environ["HOME"] = str(home)
    try:
        return fn()
    finally:
        if old is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = old


def seed_dir(fdir: Path, only=None) -> int:
    home = fdir / "home"
    count = 0
    for payload in sorted(fdir.glob("*.json")):
        if only and payload.name not in only:
            continue
        data = json.loads(payload.read_text(encoding="utf-8"))
        tool, tin = str(data.get("tool_name", "")), data.get("tool_input") or {}
        session = data.get("session_id") or "__selftest__"
        tp = data.get("transcript_path") or ""
        ts_h = _human_ts(fdir / tp) if tp else ""
        if not ts_h:
            print(f"skip {payload.name}: no operator turn timestamp")
            continue
        try:
            digests = _with_home(home, lambda: panel_digest.digests_for(tool, tin))
        except panel_digest.PanelDigestError as e:
            print(f"skip {payload.name}: {e}")
            continue
        t = _dt.datetime.fromisoformat(ts_h.replace("Z", "+00:00")) - _dt.timedelta(minutes=5)
        ts = t.isoformat().replace("+00:00", "Z")
        for i, d in enumerate(digests):
            agent_id = hashlib.sha256(f"{payload.stem}:{i}".encode()).hexdigest()[:17]
            if seed_receipt(home, session, d, "PASS", ts, agent_id):
                count += 1
    print(f"seeded {count} panel receipt(s) in {fdir}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        sys.exit(2)
    only = sys.argv[sys.argv.index("--only") + 1:] if "--only" in sys.argv else None
    sys.exit(seed_dir(Path(sys.argv[1]), only))
