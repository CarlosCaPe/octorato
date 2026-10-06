#!/usr/bin/env python3
"""friction_ledger.py: every gate deny and Stop block, counted by the system (v10 FR-01).

Before v10 no gate wrote its own deny log, so the friction a gate caused existed
only as a hand-run census over the transcripts. This module turns that census
into a ledger the brain keeps itself, WITHOUT touching a single gate body: the
harness already records every refusal in the session transcript, so the ledger
is built by reading what the harness wrote.

    PreToolUse deny   a `tool_result` with is_error whose text starts
                      `PreToolUse:<Tool> hook error:` (an exit-2 deny prefixes
                      `[<command>]: `, a JSON deny carries only its reason)
    Stop block        an `attachment` of type `hook_blocking_error`, which names
                      the blocking command in `blockingError.command`
    harness deny      the auto-mode classifier and the sleep block; not an
                      Octorato gate, counted under a `harness:` name so the
                      report can show it beside the gates and never mix them

Each event becomes one JSONL line in the gitignored
`~/.claude/.cache/friction/ledger.jsonl`:

    {"v": 1, "key", "uuid", "ts", "session", "agent", "kind", "event", "gate",
     "code", "tool", "input_sha256", "input_chars"}

What is NEVER stored: the reason text, the tool input, a message body, a prompt.
`input_sha256` is the sha256 of the input serialised as sorted-key JSON and cut
to 1,200 characters (AC-01), so two identical denied calls share a digest and
nothing about the call can be read back from the line alone. The digest is
UNSALTED: a short input (`ls`, `git status`) can be recovered by hashing
guesses, so the ledger is a local, gitignored file and never leaves the
machine. `input_chars` is the length before the cut. For a Stop block the "input" is the assistant text the block refused.

Hook latency rides along in monthly `latency-YYYY-MM.jsonl` files beside it: the harness writes a
`durationMs` on a hook attachment and on `stop_hook_summary.hookInfos`, but only
for a hook that printed something, so a silent hook (and a hook that denied: the
deny leaves no success attachment) is invisible there. The report says so.

Idempotent. Every line carries `key` (the harness `uuid` of the record, plus the
tool_use id when one record holds several parallel results), and a key already
in the ledger is never appended again: re-reading a transcript, a backfill over
a range that was already ingested, and a resumed session that copied its history
into a new file all leave the ledger unchanged. Reads are incremental: the byte
offset reached in each transcript is kept in `offsets.json`, and only whole
lines are consumed, so a line the harness is still writing is read next time.

Attribution comes from `registry/friction-signatures.json`: the command when the
text names one, else the first signature whose pattern matches the reason. An
unmatched deny is still recorded, as gate `unattributed`, because a deny the
table cannot name is exactly the one worth noticing.

CLI:
    friction_ledger.py ingest <transcript.jsonl>...   one or more files
    friction_ledger.py backfill [--since YYYY-MM-DD]  every transcript under ~/.claude/projects
    friction_ledger.py stats                          line counts, for a quick look

Stdlib only. Library users: `ingest_paths()`, `read_ledger()`, `read_latency()`.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

try:
    import fcntl  # POSIX; on Windows the ledger is appended without a lock
except ImportError:  # pragma: no cover
    fcntl = None

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SIGNATURES = REPO / "registry" / "friction-signatures.json"
HOOKS_JSON = REPO / "hooks.json"
INPUT_CUT = 1200

_PRE_RE = re.compile(r"^PreToolUse:(\S+) hook error: ?(.*)", re.S)
_CMD_RE = re.compile(r"^\[([^\]]+)\]: ?(.*)", re.S)
_SCRIPT_RE = re.compile(r"([\w.\-]+\.py)\b")

# Byte markers: a line is parsed only when it carries one of these, so a 76 MB
# transcript is not json-decoded line by line on the Stop hot path.
_EVENT_MARKERS = (b"hook error", b"hook_blocking_error", b"Permission for this",
                  b"Blocked: sleep", b"denied by a built-", b"auto mode")
_LATENCY_MARKER = b'"durationMs"'


# ── paths ───────────────────────────────────────────────────────────────────

def ledger_dir() -> Path:
    """`OCTO_FRICTION_DIR` for tests, else the gitignored cache under HOME."""
    env = os.environ.get("OCTO_FRICTION_DIR")
    if env:
        return Path(env)
    return Path(os.path.expanduser("~")) / ".claude" / ".cache" / "friction"


def projects_dir() -> Path:
    return Path(os.path.expanduser("~")) / ".claude" / "projects"


# ── attribution ─────────────────────────────────────────────────────────────

_SIG_CACHE: list | None = None


def load_signatures(path: Path | None = None) -> list:
    global _SIG_CACHE
    if path is None and _SIG_CACHE is not None:
        return _SIG_CACHE
    p = path or SIGNATURES
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        sigs = []
        for s in raw.get("signatures", []):
            sigs.append((s["gate"], s["code"], re.compile(s["pattern"]),
                         re.compile(s["tool"]) if s.get("tool") else None))
    except (OSError, ValueError, KeyError, re.error):
        sigs = []
    if path is None:
        _SIG_CACHE = sigs
    return sigs


def classify(text: str, tool: str | None = None) -> tuple[str, str]:
    """(gate, code) for a reason text, by the signature table."""
    for gate, code, pat, tpat in load_signatures():
        if tpat is not None and not tpat.search(tool or ""):
            continue
        if pat.search(text or ""):
            return gate, code
    return "unattributed", "unknown"


def script_of(command: str) -> str:
    m = _SCRIPT_RE.findall(command or "")
    return m[-1] if m else ""


def attribute_pretool(text: str, tool: str | None) -> tuple[str, str]:
    """Gate and code for the text after `PreToolUse:<Tool> hook error: `."""
    m = _CMD_RE.match(text or "")
    if m:
        gate = script_of(m.group(1))
        _, code = classify(m.group(2), tool)
        return (gate or "unattributed"), code
    return classify(text, tool)


def attribute_block(command: str, reason: str) -> tuple[str, str]:
    """The command names the gate; the table only supplies the reason code, and
    only when its row is for that same gate (else the generic `block`)."""
    gate = script_of(command)
    sg, code = classify(reason)
    if not gate:
        return sg, code
    return gate, (code if sg == gate else "block")


def digest(obj) -> tuple[str | None, int]:
    """sha256 of the input cut to 1,200 characters, plus its full length."""
    if obj is None:
        return None, 0
    s = obj if isinstance(obj, str) else json.dumps(obj, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(s[:INPUT_CUT].encode("utf-8")).hexdigest(), len(s)


# ── hooks.json label map (latency) ──────────────────────────────────────────

_LABELS: dict | None = None


def hook_labels() -> dict:
    """statusMessage or command -> script basename, from the tracked hooks.json.

    The harness records a hook under its statusMessage when it has one, so a
    duration reads "♦ delegate reflex..." and not the script; this map undoes it.
    """
    global _LABELS
    if _LABELS is not None:
        return _LABELS
    out = {}
    try:
        h = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
        h = h.get("hooks", h)
        for groups in h.values():
            if not isinstance(groups, list):
                continue  # a comment key, not an event
            for grp in groups:
                if not isinstance(grp, dict):
                    continue
                for x in grp.get("hooks", []):
                    cmd = x.get("command", "")
                    base = script_of(cmd) or cmd
                    out[cmd] = base
                    if x.get("statusMessage"):
                        out[x["statusMessage"]] = base
    except (OSError, ValueError, AttributeError):
        pass
    _LABELS = out
    return out


def label_to_hook(label: str) -> str:
    return hook_labels().get(label) or script_of(label) or label[:60]


# ── transcript reading ──────────────────────────────────────────────────────

def _text_of(c) -> str:
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        out = []
        for x in c:
            if isinstance(x, dict):
                if x.get("type") == "text":
                    out.append(x.get("text", ""))
                elif x.get("type") == "tool_result":
                    out.append(_text_of(x.get("content")))
        return "\n".join(out)
    return ""


def _lines_with(buf: bytes, markers) -> list[tuple[int, bytes]]:
    """(offset, line) for every whole line of `buf` holding any marker, once each.

    One `bytes.find` loop per marker: measured on a 76 MB transcript, six of
    them cost 0.15 s where one regex alternation over the same markers cost
    0.57 s, because `re` has no multi-literal search.
    """
    n = len(buf)
    spans = {}
    for mk in markers:
        i = buf.find(mk)
        while i != -1:
            s = buf.rfind(b"\n", 0, i) + 1
            e = buf.find(b"\n", i)
            e = n if e == -1 else e
            spans[s] = e
            i = buf.find(mk, e)
    return [(s, buf[s:spans[s]]) for s in sorted(spans)]


_ID_WINDOW = 8 * 1024 * 1024


def _tool_inputs(buf: bytes, wanted: dict) -> dict:
    """tool_use id -> (name, input). `wanted` maps an id to the offset of its
    result; the tool_use is searched BACKWARDS from there, inside a bounded
    window, because a call and its result sit next to each other and a forward
    scan of the whole chunk per id was the cold-read hot spot."""
    found = {}
    for tid, pos in wanted.items():
        if not tid:
            continue
        needle = tid.encode()
        lo = max(0, pos - _ID_WINDOW)
        i = buf.rfind(needle, lo, pos)
        while i != -1:
            s = buf.rfind(b"\n", 0, i) + 1
            e = buf.find(b"\n", i)
            line = buf[s:e if e != -1 else len(buf)]
            if b'"tool_use"' in line:
                try:
                    d = json.loads(line)
                except ValueError:
                    d = {}
                for c in (d.get("message") or {}).get("content") or []:
                    if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("id") == tid:
                        found[tid] = (c.get("name"), c.get("input"))
                if tid in found:
                    break
            i = buf.rfind(needle, lo, s) if s > lo else -1
    return found


def _last_assistant_text(buf: bytes, before: int) -> str:
    """The assistant text closest before byte `before` (what a Stop block refused)."""
    end = before
    for _ in range(40):
        s = buf.rfind(b"\n", 0, max(0, end - 1)) + 1
        line = buf[s:end].strip()
        if line and b'"assistant"' in line:
            try:
                d = json.loads(line)
            except ValueError:
                d = {}
            if d.get("type") == "assistant":
                t = _text_of((d.get("message") or {}).get("content"))
                if t:
                    return t
        if s == 0:
            break
        end = s - 1
    return ""


def scan_bytes(buf: bytes, with_latency: bool = True) -> tuple[list, list]:
    """(events, latency samples) from a chunk of whole transcript lines."""
    events, pending = [], {}
    for pos, line in _lines_with(buf, _EVENT_MARKERS):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        uuid = d.get("uuid") or ""
        base = {"v": 1, "uuid": uuid, "ts": d.get("timestamp") or "",
                "session": d.get("sessionId") or d.get("session_id") or "",
                "agent": d.get("agentId") or ""}
        a = d.get("attachment") or {}
        if a.get("type") == "hook_blocking_error":
            be = a.get("blockingError") or {}
            reason = be.get("blockingError") or ""
            gate, code = attribute_block(be.get("command") or a.get("command") or "", reason)
            h, n = digest(_last_assistant_text(buf, pos) or None)
            events.append({**base, "key": uuid, "kind": "stop-block",
                           "event": a.get("hookEvent") or "Stop", "gate": gate, "code": code,
                           "tool": None, "input_sha256": h, "input_chars": n})
            continue
        if d.get("type") != "user":
            continue
        cont = (d.get("message") or {}).get("content")
        if not isinstance(cont, list):
            continue
        for x in cont:
            if not (isinstance(x, dict) and x.get("type") == "tool_result"):
                continue
            rt = _text_of(x.get("content"))
            m = _PRE_RE.match(rt)
            if m:
                kind, tool, body = "pretool-deny", m.group(1), m.group(2)
                gate, code = attribute_pretool(body, tool)
            elif (rt.startswith("Permission for this") or "denied by a built-" in rt[:200]
                  or "denied by the Claude Code auto mode" in rt[:400]
                  or rt.startswith("<tool_use_error>Blocked: sleep")):
                kind, tool = "harness-deny", None
                gate, code = classify(rt)
                if not gate.startswith("harness:"):
                    gate, code = "harness:other", "deny"
            else:
                continue
            tid = x.get("tool_use_id") or ""
            pending[tid] = pos
            events.append({**base, "key": f"{uuid}:{tid}", "kind": kind, "event": "PreToolUse",
                           "gate": gate, "code": code, "tool": tool, "_tid": tid})
    if pending:
        inputs = _tool_inputs(buf, pending)
        for e in events:
            tid = e.pop("_tid", None)
            if tid is None:
                continue
            name, inp = inputs.get(tid, (None, None))
            if not e.get("tool"):
                e["tool"] = name
            h, n = digest(inp)
            e["input_sha256"], e["input_chars"] = h, n
    lat = scan_latency(buf) if with_latency else []
    return events, lat


def scan_latency(buf: bytes) -> list:
    out = []
    for _, line in _lines_with(buf, [_LATENCY_MARKER]):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        uuid, ts = d.get("uuid") or "", d.get("timestamp") or ""
        a = d.get("attachment") or {}
        if a and a.get("durationMs") is not None and a.get("hookEvent"):
            out.append({"key": uuid, "ts": ts, "event": a["hookEvent"],
                        "hook": label_to_hook(a.get("command") or a.get("hookName") or ""),
                        "ms": a["durationMs"], "timed_out": bool(a.get("timedOut"))})
        elif d.get("subtype") == "stop_hook_summary":
            for i, h in enumerate(d.get("hookInfos") or []):
                if h.get("durationMs") is None:
                    continue
                out.append({"key": f"{uuid}:{i}", "ts": ts, "event": "Stop",
                            "hook": label_to_hook(h.get("command") or ""),
                            "ms": h["durationMs"], "timed_out": False})
    return out


# ── ledger I/O ──────────────────────────────────────────────────────────────

class _Lock:
    def __init__(self, path: Path):
        self.path = path
        self.fh = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(self.path, "a+")
        if fcntl is not None:
            fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        try:
            if fcntl is not None:
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
        finally:
            self.fh.close()


def _keys(path: Path) -> set:
    keys = set()
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    keys.add(json.loads(line)["key"])
                except (ValueError, KeyError, TypeError):
                    continue
    except OSError:
        pass
    return keys


def _append(path: Path, rows: list, seen) -> int:
    """Append rows whose key is new. `seen` is a set, or None for rows that are
    new by construction (an incremental read past the file's saved offset)."""
    new = [r for r in rows if r.get("key") and (seen is None or r["key"] not in seen)]
    if not new:
        return 0
    with open(path, "a", encoding="utf-8") as fh:
        for r in new:
            if seen is not None:
                seen.add(r["key"])
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    return len(new)


def _month(ts: str) -> str:
    m = (ts or "")[:7]
    return m if re.fullmatch(r"\d{4}-\d{2}", m) else "unknown"


def latency_file(d: Path, month: str) -> Path:
    return d / f"latency-{month}.jsonl"


def _read_offsets(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def ingest_paths(paths, incremental: bool = True, with_latency: bool = True,
                 max_bytes: int = 0) -> dict:
    """Read each transcript (from its saved offset when incremental), append new rows.

    `max_bytes` > 0 caps the bytes read in this call across all files; whatever
    is left is read by the next call, because the offset only advances over
    whole lines that were read. The Stop reflex uses it so the first Stop of a
    session that predates the ledger cannot cost more than one bounded chunk.
    Returns {"events": n, "latency": n, "files": n, "pending": bool}. Idempotent by key.
    """
    budget = max_bytes if max_bytes > 0 else None
    pending = False
    d = ledger_dir()
    d.mkdir(parents=True, exist_ok=True)
    ledger, offs = d / "ledger.jsonl", d / "offsets.json"
    added_e = added_l = files = 0
    # Dedupe sets load LAZILY: a Stop with nothing new reads no ledger at all.
    # The event ledger is small (hundreds of lines a month) and is always
    # deduped. Latency is large (about 70k rows a month), so it is rotated by
    # month and deduped only when a file is read from byte 0 (a new transcript,
    # a reset offset or a full re-read), which is when a resumed copy can repeat
    # rows; past a saved offset every byte is new by construction.
    seen_e = None
    seen_l = {}
    with _Lock(d / ".lock"):
        offsets = _read_offsets(offs) if incremental else {}
        for p in paths:
            p = str(p)
            try:
                size = os.path.getsize(p)
            except OSError:
                continue
            start = offsets.get(p, 0) if incremental else 0
            if start > size:  # truncated or replaced: read it again, keys dedupe
                start = 0
            if start == size:
                continue
            want = size - start
            if budget is not None:
                if budget <= 0:
                    pending = True
                    continue
                if want > budget:
                    want, pending = budget, True
            with open(p, "rb") as fh:
                fh.seek(start)
                buf = fh.read(want)
                cut = buf.rfind(b"\n")
                if cut == -1 and want < size - start:
                    buf += fh.readline()  # one line longer than the budget: finish it
                    cut = buf.rfind(b"\n")
            if budget is not None:
                budget -= len(buf)
            if cut == -1:
                continue  # no whole line yet
            buf = buf[:cut + 1]
            ev, lat = scan_bytes(buf, with_latency)
            if ev:
                if seen_e is None:
                    seen_e = _keys(ledger)
                added_e += _append(ledger, ev, seen_e)
            if with_latency and lat:
                by_month = {}
                for r in lat:
                    by_month.setdefault(_month(r.get("ts")), []).append(r)
                for month, rows in by_month.items():
                    path = latency_file(d, month)
                    if start == 0:
                        if month not in seen_l:
                            seen_l[month] = _keys(path)
                        added_l += _append(path, rows, seen_l[month])
                    else:
                        added_l += _append(path, rows, None)
            offsets[p] = start + len(buf)
            files += 1
        if files:
            tmp = offs.with_suffix(".tmp")
            tmp.write_text(json.dumps(offsets), encoding="utf-8")
            os.replace(tmp, offs)
    return {"events": added_e, "latency": added_l, "files": files, "pending": pending}


def session_paths(transcript_path: str, session_id: str = "") -> list:
    """The main transcript plus every subagent transcript of that session,
    workflow agents (`subagents/workflows/<id>/`) included."""
    out = [transcript_path]
    tp = Path(transcript_path)
    sid = session_id or tp.stem
    out += sorted(glob.glob(str(tp.parent / sid / "subagents" / "**" / "*.jsonl"), recursive=True))
    return out


def _read_jsonl(path: Path) -> list:
    rows = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return rows


def read_ledger(since: str = "") -> list:
    return [r for r in _read_jsonl(ledger_dir() / "ledger.jsonl") if r.get("ts", "") >= since]


def read_latency(since: str = "") -> list:
    """Latency rows since `since`, reading only the monthly files that can hold them."""
    d = ledger_dir()
    lo = _month(since) if since else ""
    rows = []
    for f in sorted(d.glob("latency-*.jsonl")):
        month = f.stem[len("latency-"):]
        if lo and month != "unknown" and month < lo:
            continue
        rows += [r for r in _read_jsonl(f) if r.get("ts", "") >= since]
    return rows


# ── cli ─────────────────────────────────────────────────────────────────────

def _all_transcripts(root: Path, since_epoch: float) -> list:
    out = []
    for pat in (str(root / "*" / "*.jsonl"), str(root / "*" / "*" / "subagents" / "**" / "*.jsonl")):
        for f in glob.glob(pat, recursive=True):
            try:
                if os.path.getmtime(f) >= since_epoch:
                    out.append(f)
            except OSError:
                continue
    return sorted(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="friction_ledger",
                                 description="gate denies and Stop blocks, from the harness transcript")
    sub = ap.add_subparsers(dest="cmd")
    ing = sub.add_parser("ingest", help="read these transcripts (incremental)")
    ing.add_argument("paths", nargs="+")
    bf = sub.add_parser("backfill", help="read every transcript modified since a date")
    bf.add_argument("--since", default="", help="YYYY-MM-DD; default: all")
    bf.add_argument("--root", default="", help="projects dir; default ~/.claude/projects")
    sub.add_parser("stats", help="how many lines the ledger holds")
    a = ap.parse_args(argv)
    if a.cmd == "ingest":
        print(json.dumps(ingest_paths(a.paths)))
        return 0
    if a.cmd == "backfill":
        since = time.mktime(time.strptime(a.since, "%Y-%m-%d")) if a.since else 0
        files = _all_transcripts(Path(a.root) if a.root else projects_dir(), since)
        t0 = time.monotonic()
        res = ingest_paths(files)
        res["seconds"] = round(time.monotonic() - t0, 1)
        print(json.dumps(res))
        return 0
    if a.cmd == "stats":
        led, lat = read_ledger(), read_latency()
        print(json.dumps({"dir": str(ledger_dir()), "events": len(led), "latency": len(lat)}))
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
