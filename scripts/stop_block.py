#!/usr/bin/env python3
"""stop_block.py: one short line on the operator's screen, the full text for the model.

Claude Code prints the whole `reason` of every Stop hook that blocks (JSON
`{"decision": "block", "reason": ...}` or exit 2 + stderr) on the operator's
terminal. A gate's full instructions run to 150+ words, so a turn that trips
three gates floods the screen. This library splits the two audiences:

  * the FULL text (the gate's instructions, unchanged) is written to a
    per-session detail ledger under `~/.claude/.cache/stop-blocks/<session>/`:
    `<gate>.txt` holds the latest block of that gate, `blocks.jsonl` appends
    every block (gate, rule, session, ts, full text);
  * the gate prints ONE line: `<tag + measured fact> · detail: <abs path>`,
    capped at WORD_CAP words. The model reads the path; the operator sees one line.

Why not a native channel: the Stop hook reference
(https://code.claude.com/docs/en/hooks, "Stop decision control") documents
`hookSpecificOutput.additionalContext` on Stop as feedback that "is shown in
the transcript as hook feedback rather than a hook error", i.e. it is visible
too, and `reason` "Tells Claude why it should continue". There is no
documented field that reaches the model on Stop while staying off the screen.

Fail-safe: a gate must never get weaker. If the ledger cannot be written (or
read back), `shown()` returns the FULL reason, so the instructions still reach
the model inline. Only the text changes; the block decision is the gate's own.

Stdlib only. Gates import it guarded:

    try:
        from stop_block import shown as _shown
    except Exception:
        def _shown(gate, short, full, payload=None, rule=""):
            return full
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path

WORD_CAP = 25          # whole shown line, the detail path counted as one word
_SUFFIX_WORDS = 3      # "· detail: <path>"
_SHORT_CAP = WORD_CAP - _SUFFIX_WORDS
PRUNE_DAYS = 7         # session directories older than this are removed
_SAFE = re.compile(r"[^A-Za-z0-9_.-]")


def ledger_root() -> Path:
    """`OCTO_STOP_BLOCK_DIR` for tests, else the gitignored cache under HOME."""
    env = os.environ.get("OCTO_STOP_BLOCK_DIR")
    if env:
        return Path(env)
    return Path(os.path.expanduser("~")) / ".claude" / ".cache" / "stop-blocks"


def _session(payload) -> str:
    sid = ""
    if isinstance(payload, dict):
        sid = str(payload.get("session_id") or "")
    # OCTO_STOP_BLOCK_SESSION: a caller with no session (panel_preflight) names
    # its own, so concurrent runs never share one `adhoc` detail file.
    sid = sid or os.environ.get("OCTO_STOP_BLOCK_SESSION") or os.environ.get("CLAUDE_SESSION_ID") or os.environ.get("CLAUDE_CODE_SESSION_ID") or ""
    sid = _SAFE.sub("_", sid).strip("._")[:80]
    return sid or "adhoc"


def _gate_name(gate: str) -> str:
    stem = Path(str(gate or "gate")).name
    if stem.endswith(".py"):
        stem = stem[:-3]
    return _SAFE.sub("_", stem).strip("._")[:80] or "gate"


def one_line(short: str, cap: int = _SHORT_CAP) -> str:
    """Collapse whitespace to one line and cap the word count."""
    words = str(short or "").split()
    if len(words) > cap:
        words = words[:cap - 1] + ["…"]
    return " ".join(words)


def _prune(root: Path, keep: Path) -> None:
    """Remove stale session directories of THIS ledger only. Never runs under
    an OCTO_STOP_BLOCK_DIR override, never through a symlinked root, and only
    touches real directories shaped like a session name that hold a blocks.jsonl."""
    if os.environ.get("OCTO_STOP_BLOCK_DIR") or root.is_symlink():
        return
    cutoff = time.time() - PRUNE_DAYS * 86400
    try:
        for d in root.iterdir():
            if d == keep or d.is_symlink() or not d.is_dir():
                continue
            if _SAFE.search(d.name) or d.name != d.name.strip("._"):
                continue
            marker = d / "blocks.jsonl"
            if marker.is_symlink() or not marker.is_file():
                continue
            if d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
    except OSError:
        pass


def _write_detail(gate: str, rule: str, payload, full: str) -> Path:
    """Write the full text; return the detail file path. Raises on any failure."""
    root = ledger_root()
    if root.is_symlink():
        raise OSError(f"ledger root is a symlink: {root}")
    sdir = root / _session(payload)
    fresh = not sdir.exists()
    sdir.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or sdir.is_symlink() or not sdir.is_dir():
        raise OSError(f"not a directory: {sdir}")
    now = time.time()
    ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now)) + f".{int(now * 1000) % 1000:03d}Z"
    name = _gate_name(gate)
    header = f"gate: {name}\nrule: {rule or '-'}\nsession: {sdir.name}\nts: {ts}\n\n"
    body = header + full + "\n"
    path = sdir / f"{name}.txt"
    import tempfile
    fd, tname = tempfile.mkstemp(prefix=f".{name}.", suffix=".tmp", dir=str(sdir))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(body)
        os.replace(tname, path)
    except BaseException:
        try:
            os.unlink(tname)
        except OSError:
            pass
        raise
    rec = {"v": 1, "ts": ts, "gate": name, "rule": rule or "", "session": sdir.name,
           "detail": str(path), "reason": full}
    with (sdir / "blocks.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    # Read back: a detail the model cannot read is no detail at all.
    if path.read_text(encoding="utf-8") != body:
        raise OSError(f"detail read-back mismatch: {path}")
    if fresh:
        _prune(root, sdir)
    return path


def shown(gate: str, short: str, full: str, payload=None, rule: str = "") -> str:
    """The reason text to print. One line pointing at the detail ledger, or the
    FULL reason when the ledger cannot be written (never lose the instructions)."""
    full = str(full or "")
    try:
        path = _write_detail(gate, rule, payload, full)
    except Exception:
        return full
    return f"{one_line(short)} · detail: {path.resolve()}"


def words(text: str) -> int:
    return len(str(text or "").split())


# ---------------------------------------------------------------------------
# Selftest: (a) one line under the cap, (b) the ledger holds the full text,
# (c) a ledger write failure emits the full reason.
# ---------------------------------------------------------------------------

def _selftest() -> int:
    import tempfile
    fails = []
    full = ("LINE ONE of the instructions.\n" + "word " * 200).strip()
    tmp = Path(tempfile.mkdtemp(prefix="stop-block-selftest-"))
    old = os.environ.get("OCTO_STOP_BLOCK_DIR")
    try:
        os.environ["OCTO_STOP_BLOCK_DIR"] = str(tmp / "ok")
        line = shown("g__stop__x.py", "X GATE: " + "fact " * 40, full,
                     {"session_id": "s1"}, "FLOW.x")
        if "\n" in line or words(line) > WORD_CAP:
            fails.append(f"(a) shown line not one line under {WORD_CAP} words: {line!r}")
        det = tmp / "ok" / "s1" / "g__stop__x.txt"
        if not det.is_file() or full not in det.read_text(encoding="utf-8"):
            fails.append("(b) detail file lacks the full text")
        if str(det.resolve()) not in line:
            fails.append("(b) shown line does not name the detail path")
        rows = (tmp / "ok" / "s1" / "blocks.jsonl").read_text(encoding="utf-8").splitlines()
        if not rows or json.loads(rows[-1]).get("reason") != full:
            fails.append("(b) blocks.jsonl lacks the full reason")
        # (c) the ledger root is a FILE: mkdir fails, the full reason comes back
        blocker = tmp / "blocker"
        blocker.write_text("x", encoding="utf-8")
        os.environ["OCTO_STOP_BLOCK_DIR"] = str(blocker / "sub")
        back = shown("g__stop__x.py", "X GATE: short", full, {"session_id": "s1"})
        if back != full:
            fails.append("(c) ledger failure did not return the full reason")
        # session id is sanitised (no path traversal out of the root)
        os.environ["OCTO_STOP_BLOCK_DIR"] = str(tmp / "ok")
        line = shown("g__stop__x.py", "X", full, {"session_id": "../../evil"})
        if ".." in line.split("detail: ", 1)[-1].replace(str(tmp), ""):
            fails.append("session id escaped the ledger root")
        # a symlinked ledger root is refused (full reason back) and the prune
        # never deletes through it
        victim = tmp / "victim"
        (victim / "olddir").mkdir(parents=True)
        (victim / "olddir" / "blocks.jsonl").write_text("{}", encoding="utf-8")
        past = time.time() - (PRUNE_DAYS + 3) * 86400
        os.utime(victim / "olddir", (past, past))
        link = tmp / "linkroot"
        link.symlink_to(victim, target_is_directory=True)
        os.environ["OCTO_STOP_BLOCK_DIR"] = str(link)
        if shown("g__stop__x.py", "X", full, {"session_id": "new1"}) != full:
            fails.append("symlinked ledger root was not refused")
        _prune(link, link / "new1")
        if not (victim / "olddir").is_dir():
            fails.append("prune deleted through a symlinked root")
        # the prune keeps foreign directories (no blocks.jsonl) and old sessions
        # are removed only without an override
        real = tmp / "real"
        for n in ("oldsess", "foreign"):
            (real / n).mkdir(parents=True)
            os.utime(real / n, (past, past))
        (real / "oldsess" / "blocks.jsonl").write_text("{}", encoding="utf-8")
        os.utime(real / "oldsess", (past, past))
        os.environ.pop("OCTO_STOP_BLOCK_DIR", None)
        _prune(real, real / "keep")
        if (real / "oldsess").exists() or not (real / "foreign").is_dir():
            fails.append("prune did not keep to stale session directories")
    finally:
        if old is None:
            os.environ.pop("OCTO_STOP_BLOCK_DIR", None)
        else:
            os.environ["OCTO_STOP_BLOCK_DIR"] = old
        shutil.rmtree(tmp, ignore_errors=True)
    if fails:
        print("selftest FAIL: stop_block: " + "; ".join(fails))
        return 1
    print("selftest PASS: stop_block (one line, full detail, full fallback, safe session)")
    return 0


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    print(__doc__)
