#!/usr/bin/env python3
"""provenance_ledger.py: the turn's provenance, recorded for the agent, off the operator's screen.

WHY
The Provenance footer (Basis · Engine · Touched · Verified · Graph) and the 2D
verdict line help the agent: they force it to name its sources and its route.
On the operator's screen they are noise. The operator directed (2026-11-20)
that they keep being produced every turn but stay hidden by default, shown
only when he asks. The Stop gates that read the footer from the reply
(source-attribution-check.py, g__stop__reply-panel.py, panel_preflight.py)
therefore accept EITHER the visible footer line (back-compat) OR a ledger
entry recorded here for this session, newer than the operator's last prompt.

WHAT IT WRITES
One JSON line per record to ~/.claude/.cache/provenance/provenance.jsonl
(gitignored by `.cache/`; kept OUT of .cache/receipts/ on purpose, because
every file there is written by a hook and this one is written by the model):
  {"kind": "provenance", "session_id", "ts" (UTC ISO, ms, Z),
   "basis", "engine", "touched", "verified", "graph", "verdict"}
Empty fields are kept as "". The entry is model-written: it carries the same
trust as the footer text it replaces, no more (it is not a harness receipt).

SESSION
--session, else CLAUDE_SESSION_ID (selftest seam), else CLAUDE_CODE_SESSION_ID
(the harness exports it to every Bash call). A record with no session is an
error: an entry no gate can match is never written.

CLI
  provenance_ledger.py record --basis B [--engine E] [--touched T]
                              [--verified V] [--graph G] [--verdict ACTIVATE|LOAD|SELF ...]
  provenance_ledger.py show [--session S]     the latest entry as a footer line
  provenance_ledger.py --selftest             unit checks in a temporary HOME
Exit 0 on success, 2 on a usage or write error.

LIBRARY
  ledger_path(), record(...), entries(session_id), fresh_all(session_id,
  after, now), reply_anchor(prompt_ts, turn_entries, text), footer_line(entry),
  prompt_ts(transcript), reply_view(session_id, transcript, text).

FRESH (one definition, used by every reader)
  An entry counts for a reply when its ts is strictly newer than the anchor
  (the operator prompt, or a later full reply of the same turn that already
  ended a stop: reply_anchor) and not later than now + FUTURE_SKEW_S. ALL
  such entries count; the reply panel lets any SELF Basis win.

BOUND TO THE RECEIPT
  When the reply carries no visible footer, the reply panel's digest is over
  the reply text plus the rendered footer line of every entry used
  (bound_reply_text in g__stop__reply-panel.py), and panel_digest.py
  --panel-request --to operator prints that same text in the reviewed block.
  A later record changes the digest and voids the PASS.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

for _stream in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

_HERE = Path(__file__).resolve().parent
_FILE = "provenance.jsonl"
_REPLY_PANEL = "g__stop__reply-panel.py"
FIELDS = ("basis", "engine", "touched", "verified", "graph", "verdict")
# Env a preflight run hands to the gates it spawns: the payload it builds
# carries no session_id on purpose (panel_preflight.py), so the session whose
# ledger the draft is judged against travels here instead.
PREFLIGHT_SESSION_ENV = "OCTO_PROVENANCE_SESSION"


class LedgerError(Exception):
    pass


def ledger_path() -> Path:
    return Path(os.path.expanduser("~")) / ".claude" / ".cache" / "provenance" / _FILE


def current_session(explicit: str = "") -> str:
    return (explicit or os.environ.get("CLAUDE_SESSION_ID")
            or os.environ.get("CLAUDE_CODE_SESSION_ID") or "").strip()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _ts(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def record(session_id: str, ts: str = "", **fields) -> dict:
    """Append one entry; return it. Raises LedgerError on no session or IO."""
    sid = (session_id or "").strip()
    if not sid:
        raise LedgerError("no session id (pass --session or run inside a Claude Code session)")
    row = {"kind": "provenance", "session_id": sid, "ts": ts or _now_iso()}
    for k in FIELDS:
        row[k] = str(fields.get(k) or "").strip()
    p = ledger_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError as e:
        raise LedgerError(f"cannot write {p}: {type(e).__name__}")
    return row


def entries(session_id: str) -> list:
    """Every well-formed entry of `session_id`, in file order. A missing file
    is no entry; an unreadable one raises OSError (the caller decides)."""
    p = ledger_path()
    if not p.exists():
        return []
    out = []
    with p.open("r", encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            try:
                e = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if isinstance(e, dict) and e.get("kind") == "provenance" \
                    and e.get("session_id") == session_id and _ts(e.get("ts")) is not None:
                out.append(e)
    return out


# An entry stamped later than now by more than this is refused: a forged or
# clock-skewed future ts would otherwise stay "fresh" for every later prompt.
FUTURE_SKEW_S = 120
# Assistant text longer than this many words is a reply, not a status line
# (the reply panel's STATUS_CAP); a reply that ended a stop consumes the
# entries recorded before it.
REPLY_MIN_WORDS = 31


def fresh_all(session_id: str, after: str, now=None) -> list:
    """Every entry of `session_id` with `after` < ts <= now + FUTURE_SKEW_S,
    oldest first. No session or an unparseable `after` is []: nothing can be
    proven fresh. `now` defaults to the wall clock."""
    bound = _ts(after)
    if not session_id or bound is None:
        return []
    from datetime import timedelta
    ceiling = (now or datetime.now(timezone.utc)) + timedelta(seconds=FUTURE_SKEW_S)
    got = [e for e in entries(session_id) if bound < _ts(e["ts"]) <= ceiling]
    return sorted(got, key=lambda e: _ts(e["ts"]))


def fresh(session_id: str, after: str, now=None) -> dict | None:
    """The newest of fresh_all(...), or None."""
    got = fresh_all(session_id, after, now)
    return got[-1] if got else None


def _norm(text: str) -> str:
    return " ".join(str(text or "").split())


def _assistant_text(entry: dict) -> str:
    c = (entry.get("message") or {}).get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(b.get("text", "") for b in c
                         if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str))
    return ""


def reply_anchor(prompt_ts: str, turn_entries: list, current_text: str) -> str:
    """The bound an entry must be newer than: the operator prompt, or a later
    assistant REPLY of the same turn that already ended a stop. A reply here
    is assistant text of at least REPLY_MIN_WORDS words, not equal to the
    current reply, followed by a later user-side entry (tool result,
    notification, hand-back), which is what an earlier stop leaves. Status
    lines (shorter) do not consume entries, so record -> panel request ->
    status line -> notification -> reply keeps its entry."""
    anchor, cur = prompt_ts, _norm(current_text)
    pending = None
    for e in turn_entries or []:
        if not isinstance(e, dict):
            continue
        if e.get("type") == "assistant":
            t = _assistant_text(e)
            if t and len(t.split()) >= REPLY_MIN_WORDS and _norm(t) != cur and e.get("timestamp"):
                pending = str(e["timestamp"])
        elif e.get("type") == "user" and pending:
            if _ts(pending) and (_ts(anchor) is None or _ts(pending) > _ts(anchor)):
                anchor = pending
            pending = None
    return anchor


def footer_line(entry: dict) -> str:
    """The entry rendered as the one-line footer, for `show` (on request)."""
    labels = {"basis": "Basis", "engine": "Engine", "touched": "Touched",
              "verified": "Verified", "graph": "Graph", "verdict": "2D"}
    parts = [f"{labels[k]}: {entry.get(k)}" for k in FIELDS if entry.get(k)]
    return "Provenance: " + " · ".join(parts)


def _reply_panel():
    spec = importlib.util.spec_from_file_location("_pl_reply_panel", _HERE / _REPLY_PANEL)
    if spec is None or spec.loader is None:
        raise LedgerError(f"cannot load {_REPLY_PANEL}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def prompt_ts(transcript: str) -> str | None:
    """Timestamp of the operator prompt behind this turn, read with the reply
    panel's own walk (prompt_read). None when it cannot be placed."""
    mod = _reply_panel()
    p = mod.prompt_read(mod.load(), transcript)
    return (p or {}).get("ts") or None


def reply_view(session_id: str, transcript: str, text: str) -> tuple:
    """(entries, bound_text) for a reply `text` judged against `transcript`,
    computed by the reply panel's own functions (ledger_entries,
    bound_reply_text), so the panel request, the preflight and the Stop gates
    read one thing. No session, no transcript or no operator prompt is
    ([], text). Errors propagate: each caller decides (fail closed or open)."""
    if not session_id or not transcript:
        return [], text
    mod = _reply_panel()
    ctx = mod.load()
    prompt = mod.prompt_read(ctx, transcript)
    if prompt is None:
        return [], text
    turn, newest = mod.turn_after(ctx, transcript, prompt["uuid"])
    got = mod.ledger_entries(session_id, prompt["ts"], turn, text, mod._now(ctx, newest))
    return got, mod.bound_reply_text(text, got)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli(argv: list) -> int:
    ap = argparse.ArgumentParser(description="Record the turn's provenance off the operator's screen.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record", help="append this turn's provenance")
    r.add_argument("--session", default="")
    r.add_argument("--basis", required=True, help="whose authority: <file>:<line> / operator / vendor doc / own reasoning")
    r.add_argument("--engine", default="")
    r.add_argument("--touched", default="")
    r.add_argument("--verified", default="")
    r.add_argument("--graph", default="")
    r.add_argument("--verdict", default="", help="the 2D verdict line (ACTIVATE / LOAD / SELF ...)")
    s = sub.add_parser("show", help="print the latest entry of the session as a footer line")
    s.add_argument("--session", default="")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "record":
            row = record(current_session(a.session), **{k: getattr(a, k) for k in FIELDS})
            print(f"provenance recorded {row['ts']} session {row['session_id']}")
            return 0
        sid = current_session(a.session)
        got = entries(sid) if sid else []
        if not got:
            print("no provenance recorded for this session", file=sys.stderr)
            return 2
        print(footer_line(got[-1]))
        return 0
    except (LedgerError, OSError) as e:
        print(f"provenance_ledger: {e}", file=sys.stderr)
        return 2


def _selftest() -> int:
    import tempfile
    fails = []
    old = {k: os.environ.get(k) for k in ("HOME", "USERPROFILE", "CLAUDE_SESSION_ID")}
    tmp = tempfile.mkdtemp(prefix="provenance-ledger-selftest-")
    try:
        os.environ["HOME"] = os.environ["USERPROFILE"] = tmp
        os.environ.pop("CLAUDE_SESSION_ID", None)
        try:
            record("", basis="x")
            fails.append("record with no session did not raise")
        except LedgerError:
            pass
        record("s1", ts="2026-10-14T10:00:00.000Z", basis="old.log")
        record("s1", ts="2026-10-14T10:05:00.000Z", basis="new.log", engine="main loop")
        record("s2", ts="2026-10-14T10:06:00.000Z", basis="other session")
        from datetime import datetime as _dt
        now = _dt.fromisoformat("2026-10-14T10:10:00+00:00")
        got = fresh_all("s1", "2026-10-14T10:01:00.000Z", now)
        if [x["basis"] for x in got] != ["new.log"]:
            fails.append(f"fresh_all picked {got!r}, want [new.log]")
        if fresh_all("s1", "2026-10-14T09:00:00.000Z", now)[0]["basis"] != "old.log":
            fails.append("fresh_all did not return every fresh entry, oldest first")
        if fresh_all("s1", "2026-10-14T10:05:00.000Z", now):
            fails.append("an entry equal to the anchor counted as newer")
        if fresh_all("s3", "2026-10-14T09:00:00.000Z", now):
            fails.append("another session's entry was returned")
        if fresh_all("s1", "not a time", now):
            fails.append("an unparseable anchor proved freshness")
        record("s4", ts="2026-10-14T10:20:00.000Z", basis="future")
        if fresh_all("s4", "2026-10-14T09:00:00.000Z", now):
            fails.append("an entry stamped beyond now + FUTURE_SKEW_S counted")
        long_reply = " ".join(["word"] * REPLY_MIN_WORDS)
        turn = [{"type": "assistant", "timestamp": "2026-10-14T10:02:00.000Z",
                 "message": {"content": [{"type": "text", "text": long_reply}]}},
                {"type": "user", "timestamp": "2026-10-14T10:02:30.000Z"}]
        if reply_anchor("2026-10-14T10:00:00.000Z", turn, "the current reply") != "2026-10-14T10:02:00.000Z":
            fails.append("a full reply that ended a stop did not move the anchor")
        if reply_anchor("2026-10-14T10:00:00.000Z", turn[:1], "x") != "2026-10-14T10:00:00.000Z":
            fails.append("a reply with no later user-side entry moved the anchor")
        if reply_anchor("2026-10-14T10:00:00.000Z", turn, long_reply) != "2026-10-14T10:00:00.000Z":
            fails.append("the current reply itself moved the anchor")
        e = got[-1] if got else {}
        line = footer_line(e)
        if line != "Provenance: Basis: new.log · Engine: main loop":
            fails.append(f"footer_line gave {line!r}")
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    if fails:
        print("selftest FAIL (provenance_ledger.py): " + "; ".join(fails), file=sys.stderr)
        return 1
    print("selftest PASS: 11 unit checks (provenance_ledger.py)")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    sys.exit(_cli(sys.argv[1:]))
