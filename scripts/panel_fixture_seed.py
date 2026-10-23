#!/usr/bin/env python3
"""panel_fixture_seed.py: seed panel receipts into an outward-send fixture home.

seed_reply_receipt is the same seed for a reply to the operator; the reply
panel gate (g__stop__reply-panel.py) calls it per case inside its selftest.

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

Run it from a clean seed (`--reset` drops every panel row and reviewer
transcript first, so a digest change cannot leave stale receipts behind).
Idempotent: a fixture already seeded (same agent id) is skipped. A fixture
whose message the gate cannot read with certainty is skipped too, and printed.

Usage: panel_fixture_seed.py <fixture_dir> [--reset] [--only <payload.json> ...]
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


def seed_receipt(home: Path, session: str, msg, verdict: str, ts: str, agent_id: str,
                 agent_type: str = "Reality Checker", stated_digest: str | None = None,
                 shown=None, with_block: bool = True) -> bool:
    """Write one reviewer transcript entry and its ledger row for message `msg`
    (a panel_digest.Message). The report carries the panel block of `shown`
    (default `msg`) and states `stated_digest` (default msg.digest), so a
    fixture can make the reviewer read one text and state another's digest,
    or (with_block=False) state a digest with no block at all. Returns False
    when this agent id was already seeded."""
    rel = Path(".claude") / "projects" / "fx" / session / "subagents" / f"agent-{agent_id}.jsonl"
    tp = home / rel
    if tp.exists():
        return False
    tp.parent.mkdir(parents=True, exist_ok=True)
    prompt_uuid, entry_uuid = _uuid(agent_id + "p"), _uuid(agent_id + "a")
    t = _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    p_ts = (t - _dt.timedelta(seconds=30)).isoformat().replace("+00:00", "Z")
    digest = stated_digest or msg.digest
    block = (shown or msg).panel_block().rsplit("\nPANEL-SHA256:", 1)[0] if with_block else ""
    report = (f"Reviewed the message.\n{block}\nPANEL-VERDICT: {verdict}\n"
              f"PANEL-SHA256: {digest}")
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


def seed_reply_receipt(home: Path, session: str, text: str, verdict: str, ts: str,
                       agent_id: str, agent_type: str = "Reality Checker") -> bool:
    """A Stop case (FLOW.panel-before-reply): the reviewed message is a reply
    to the operator, so its only recipient is "operator" and it has no
    attachment. Same files and row as seed_receipt."""
    msg = panel_digest.Message(text, [], ["operator"])
    return seed_receipt(home, session, msg, verdict, ts, agent_id, agent_type)


EXTERNAL_INTERPRETER = "/opt/fx-node/bin/node"
EXTERNAL_SCRIPTS = {"codex": "/opt/fx-node/lib/node_modules/@openai/codex/bin/codex.js",
                    "gemini": "/opt/fx-node/lib/node_modules/@google/gemini-cli/bundle/gemini.js"}


def seed_external_receipt(home: Path, session: str, msg, verdict: str, ts: str,
                          tool_use_id: str, engine: str = "codex", model: str = "fx-review-model",
                          cwd: str = "~/.claude", allowed: bool = True,
                          project_dir: str = "") -> None:
    """An External_Review_Receipt (v11 phase 4) for message `msg` (a
    panel_digest.Message), written the way the Bash hook pair writes one: the
    session transcript's harness Bash tool_use and its tool result (at `ts`),
    the output copy ending on the panel block, the pending and complete ledger
    rows, and a Reviewer_Registry pair for (engine, model), `allowed` or not.
    The pinned paths are fixed fake paths: the ledger re-parses the command
    against the paths the receipt recorded and never opens them."""
    import external_review as er
    prompt = "Review the panel block and end with PANEL-VERDICT and PANEL-SHA256."
    model_arg = f" -m {model}" if model != "unknown" else ""
    if engine == "codex":
        command = f"{EXTERNAL_INTERPRETER} {EXTERNAL_SCRIPTS[engine]} exec{model_arg} '{prompt}'"
    else:
        command = f"{EXTERNAL_INTERPRETER} {EXTERNAL_SCRIPTS[engine]}{model_arg} -p '{prompt}'"
    rel_tp = Path(".claude") / "projects" / "fx" / f"{session}.jsonl"
    tp = home / rel_tp
    tp.parent.mkdir(parents=True, exist_ok=True)
    t = _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    use_ts = (t - _dt.timedelta(seconds=20)).isoformat().replace("+00:00", "Z")
    a_uuid, u_uuid = _uuid(tool_use_id + "a"), _uuid(tool_use_id + "u")
    block = msg.panel_block().rsplit("\nPANEL-SHA256:", 1)[0]
    output = f"Reviewed the message.\n{block}\nPANEL-VERDICT: {verdict}\nPANEL-SHA256: {msg.digest}\n"
    entries = [
        {"type": "assistant", "message": {"role": "assistant", "id": f"msg_{tool_use_id}",
                                          "content": [{"type": "tool_use", "id": tool_use_id,
                                                       "name": "Bash",
                                                       "input": {"command": command}}]},
         "uuid": a_uuid, "parentUuid": None, "sessionId": session, "timestamp": use_ts},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tool_use_id, "content": output}]},
         "uuid": u_uuid, "parentUuid": a_uuid, "sessionId": session, "timestamp": ts,
         "toolUseResult": {"stdout": output, "stderr": "", "interrupted": False}},
    ]
    with tp.open("a", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    rdir = home / ".claude" / ".cache" / "receipts"
    (rdir / "external").mkdir(parents=True, exist_ok=True)
    raw = output.encode("utf-8")
    (rdir / "external" / f"{tool_use_id}.out").write_bytes(raw)
    base = {"kind": "external", "engine": engine, "interpreter": EXTERNAL_INTERPRETER,
            "script": EXTERNAL_SCRIPTS[engine], "requested_model": model,
            "prompt_sha256": er.prompt_digest(prompt), "tool_use_id": tool_use_id,
            "session_id": session, "transcript_path": "~/" + rel_tp.as_posix(), "cwd": cwd,
            "project_dir": project_dir}
    rows = [dict(base, state="pending", pre_problems=[], ts=use_ts),
            dict(base, state="complete", exit_code=0, output_sha256=er.sha256_bytes(raw),
                 output_path=f"~/.claude/.cache/receipts/external/{tool_use_id}.out",
                 panel_verdict=verdict, panel_digest=msg.digest, qa_verdict="", ts=ts)]
    with (rdir / "global.jsonl").open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    seed_reviewer_pair(home, engine, model, "allowed" if allowed else "not-allowed")


def seed_reviewer_pair(home: Path, engine: str, model: str, status: str) -> None:
    """Add (engine, model, status) to the Reviewer_Registry of a fixture home,
    written as JSON, which is YAML."""
    path = home / ".claude" / "registry" / "reviewers.yaml"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {"schema": 1, "reviewers": {}, "pairs": []}
    pairs = [p for p in data["pairs"] if (p.get("engine"), p.get("model")) != (engine, model)]
    pairs.append({"engine": engine, "model": model, "status": status,
                  "replay_record": None, "baseline_model": None})
    data["pairs"] = pairs
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def seed_arm(home: Path, name: str, policy: str) -> str:
    """Register arm `name` at ~/arms/<name> with telemetry.export `policy`;
    return its `~` path for a receipt's cwd."""
    cfg = home / ".claude" / "company" / "config" / "arms-paths.json"
    try:
        arms = json.loads(cfg.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        arms = {}
    arms[name] = f"arms/{name}"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps(arms) + "\n", encoding="utf-8")
    root = home / "arms" / name
    root.mkdir(parents=True, exist_ok=True)
    (root / "arm.json").write_text(json.dumps({"telemetry": {"export": policy}}) + "\n",
                                   encoding="utf-8")
    return f"~/arms/{name}"


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


def reset_dir(fdir: Path) -> None:
    import shutil
    home = fdir / "home"
    shutil.rmtree(home / ".claude" / "projects" / "fx", ignore_errors=True)
    shutil.rmtree(home / ".claude" / ".cache" / "receipts" / "external", ignore_errors=True)
    ledger = home / ".claude" / ".cache" / "receipts" / "global.jsonl"
    if ledger.exists():
        keep = [ln for ln in ledger.read_text(encoding="utf-8").splitlines()
                if ln.strip() and json.loads(ln).get("kind") not in ("panel", "external")]
        ledger.write_text("".join(ln + "\n" for ln in keep), encoding="utf-8")


def seed_dir(fdir: Path, only=None, reset: bool = False) -> int:
    home = fdir / "home"
    if reset:
        reset_dir(fdir)
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
            msgs = _with_home(home, lambda: panel_digest.message_parts(tool, tin))
        except panel_digest.PanelDigestError as e:
            print(f"skip {payload.name}: {e}")
            continue
        t = _dt.datetime.fromisoformat(ts_h.replace("Z", "+00:00")) - _dt.timedelta(minutes=5)
        ts = t.isoformat().replace("+00:00", "Z")
        for i, m in enumerate(msgs):
            agent_id = hashlib.sha256(f"{payload.stem}:{i}".encode()).hexdigest()[:17]
            if seed_receipt(home, session, m, "PASS", ts, agent_id):
                count += 1
    print(f"seeded {count} panel receipt(s) in {fdir}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        sys.exit(2)
    only = sys.argv[sys.argv.index("--only") + 1:] if "--only" in sys.argv else None
    sys.exit(seed_dir(Path(sys.argv[1]), only, reset="--reset" in sys.argv))
