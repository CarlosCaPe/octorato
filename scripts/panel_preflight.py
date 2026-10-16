#!/usr/bin/env python3
"""panel_preflight.py: run the reply-text Stop gates on a draft BEFORE its panel.

THE COST IT CUTS
The reply panel (FLOW.panel-before-reply) binds a PASS to one exact text. Stop
gates run in parallel at Stop, so a later gate (source-attribution, claim-verify,
defer-today, ...) could force an edit to a text that already held its PASS, and
the changed digest needed a full new panel. Measured since v11.0.0: 16 of 32
extra panel rounds followed a clean round (docs/architecture/v11-reply-panel.md,
"Cost controls (measured)"). This runs those gates on the draft first, so the
text the reviewers read is already the text that ends the turn.

WHAT IT RUNS
Every Stop hook in hooks.json except the ones in SKIP (each with its reason):
the script runs from this directory (the worktree copy when run from one) on a
synthetic Stop payload. A Stop gate added later is run by default. The payload
carries no session_id, so a gate's kernel journal write is a no-op (pid ""),
and stop_hook_active is false, so a block-once gate judges as on the first stop.
The gates read the reply from the transcript's last assistant entry, so the
draft is appended as one assistant entry to a temporary copy of the session
transcript (the live one is never written). The transcript is --transcript,
else the one named by CLAUDE_CODE_SESSION_ID under ~/.claude/projects, else a
minimal one with no operator prompt (then gates that read the turn's tool
calls or the operator's ask judge with no context, and the output says so).

A gate blocks when it exits 2 or prints {"decision": "block"}. A gate that
times out or errors is printed as such and does not count as a block: in the
harness the same gate fails open.

It also prints the reply's source class and the quorum the reply panel would
ask for, read with the gate's own classifier (loaded by file name).

CLI
    panel_preflight.py --body-file F [--transcript T]
Exit 0 when no gate would block, 1 when one would, 2 on a usage or read error.
panel_digest.py --preflight and --panel-request --to operator call run().
"""
from __future__ import annotations

import concurrent.futures
import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import uuid as _uuid
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_GATE = "g__stop__reply-panel.py"
# Stop hooks that do not judge the reply text, or that judge it only against
# per-session state a synthetic payload does not have. Every other Stop hook
# runs. scripts/tests/test_panel_preflight.py fails when hooks.json gains a
# Stop hook that is neither run nor listed here with a reason.
SKIP = {
    "g__stop__reply-panel.py": "the panel itself",
    "trace-hook.py": "writes a trace, judges nothing",
    "grafo-ledger-check.py": "judges the turn's graph ledger, not the text",
    "g__stop__delegation-audit.py": "judges and consumes the delegation ledger of the session",
    "d__stop__wa-guardia.py": "arms a chat watcher, judges nothing",
    "g__stop__goal-anchor.py": "judges against the session's pinned goal state",
    "r__stop__friction-ledger.py": "records blocks, judges nothing",
}
DEFAULT_TIMEOUT = 10


class PreflightError(Exception):
    pass


def stop_hooks(hooks_json: Path | None = None) -> list:
    """[(script_name, argv_tail, timeout)] for every Stop hook, in file order."""
    p = hooks_json or (_HERE.parent / "hooks.json")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise PreflightError(f"hooks.json unreadable: {p} ({type(e).__name__})")
    out = []
    for entry in data.get("Stop") or []:
        for h in entry.get("hooks") or []:
            cmd = shlex.split(str(h.get("command") or ""))
            script = next((c for c in cmd if c.endswith(".py")), None)
            if not script:
                continue
            tail = cmd[cmd.index(script) + 1:]
            out.append((Path(script).name, tail, int(h.get("timeout") or DEFAULT_TIMEOUT)))
    return out


def find_transcript(explicit: str | None = None) -> Path | None:
    if explicit:
        p = Path(explicit).expanduser()
        if not p.is_file():
            raise PreflightError(f"transcript not found: {p}")
        return p
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID") or os.environ.get("CLAUDE_SESSION_ID") or ""
    if not sid or "/" in sid:
        return None
    hits = sorted((Path.home() / ".claude" / "projects").glob(f"*/{sid}.jsonl"))
    return hits[0] if hits else None


def _draft_entry(text: str) -> dict:
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return {"type": "assistant", "uuid": str(_uuid.uuid4()), "timestamp": now,
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def _minimal_transcript(text: str) -> str:
    return json.dumps(_draft_entry(text)) + "\n"


def _child_env() -> dict:
    env = dict(os.environ)
    for k in ("CLAUDE_SESSION_ID", "CLAUDE_CODE_SESSION_ID"):
        env.pop(k, None)
    return env


def _verdict(cp) -> tuple:
    out, err = (cp.stdout or "").strip(), (cp.stderr or "").strip()
    if cp.returncode == 2:
        return "BLOCK", err or out
    for ln in out.splitlines()[::-1]:
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("decision") == "block":
            return "BLOCK", str(d.get("reason") or "")
    if cp.returncode != 0:
        return "ERROR", f"exit {cp.returncode}: {(err or out)[:200]}"
    return "PASS", ""


def _run_one(script: str, tail: list, timeout: int, payload: dict, cwd: str) -> dict:
    path = _HERE / script
    if not path.is_file():
        return {"gate": script, "verdict": "ERROR", "reason": "script missing in " + str(_HERE)}
    try:
        cp = subprocess.run([sys.executable, str(path), *tail], input=json.dumps(payload),
                            capture_output=True, text=True, encoding="utf-8", errors="replace",
                            cwd=cwd, env=_child_env(), timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"gate": script, "verdict": "TIMEOUT", "reason": f"over {timeout}s (fails open at Stop)"}
    v, reason = _verdict(cp)
    return {"gate": script, "verdict": v, "reason": reason}


def source_class(text: str) -> tuple:
    """(class, quorum) from the reply-panel gate's own classifier."""
    spec = importlib.util.spec_from_file_location("_pf_reply_panel", _HERE / _GATE)
    if spec is None or spec.loader is None:
        raise PreflightError(f"cannot load {_GATE}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cls = mod.source_class(text)
    return cls, mod.QUORUM[cls]


def run(text: str, transcript: str | None = None, hooks_json: Path | None = None) -> dict:
    """{"results": [...], "blocked": [...], "class", "quorum", "context"}."""
    src = find_transcript(transcript)
    tmp = Path(tempfile.mkdtemp(prefix="panel-preflight-"))
    try:
        tp = tmp / "transcript.jsonl"
        if src is not None:
            shutil.copyfile(src, tp)
            raw = tp.read_bytes()
            with tp.open("a", encoding="utf-8") as fh:
                if raw and not raw.endswith(b"\n"):
                    fh.write("\n")
                fh.write(json.dumps(_draft_entry(text)) + "\n")
            context = str(src)
        else:
            tp.write_text(_minimal_transcript(text), encoding="utf-8")
            context = "none (no session transcript found; turn-aware gates judge without context)"
        payload = {"hook_event_name": "Stop", "transcript_path": str(tp), "stop_hook_active": False,
                   "last_assistant_message": text, "cwd": os.getcwd()}
        hooks = [h for h in stop_hooks(hooks_json) if h[0] not in SKIP]
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(hooks))) as ex:
            futs = [ex.submit(_run_one, s, t, to, payload, os.getcwd()) for s, t, to in hooks]
            results = [f.result() for f in futs]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    cls, quorum = source_class(text)
    return {"results": results, "blocked": [r for r in results if r["verdict"] == "BLOCK"],
            "class": cls, "quorum": quorum, "context": context}


def report(res: dict) -> str:
    lines = [f"PREFLIGHT {r['gate']}: {r['verdict']}" + (f" ({r['reason'][:300]})" if r["reason"] else "")
             for r in res["results"]]
    lines.append(f"PREFLIGHT context: {res['context']}")
    lines.append(f"PREFLIGHT source class: {res['class']}, reply panel quorum: {res['quorum']}")
    lines.append("PREFLIGHT verdict: " + ("BLOCK (" + ", ".join(r["gate"] for r in res["blocked"]) + ")"
                                           if res["blocked"] else "PASS"))
    return "\n".join(lines)


def _cli(argv: list) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Run the reply-text Stop gates on a draft reply.")
    ap.add_argument("--body-file", required=True, help="file with the exact reply text")
    ap.add_argument("--transcript", help="session transcript to judge the draft against")
    a = ap.parse_args(argv)
    try:
        text = Path(a.body_file).read_text(encoding="utf-8")
        res = run(text, a.transcript)
    except (PreflightError, OSError, ValueError) as e:
        print(f"panel_preflight: {e}", file=sys.stderr)
        return 2
    print(report(res))
    return 1 if res["blocked"] else 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
