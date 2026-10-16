#!/usr/bin/env python3
"""g__stop__reply-panel.py: no reply to the operator leaves the turn unreviewed (v11).

THE FAILURE THIS EXISTS FOR
v7 made an unverified send to a third party impossible: no message leaves
without a PASS panel receipt for its exact digest (FLOW.panel-before-send).
The replies the operator reads had no such floor. On 2026-10-14 the first
manual panel of a design reply found 8 defects (a wrong score, a false claim,
missing residuals, a verdict written before the reviewer returned). The
operator then directed that every reply goes through a panel, wired in code.

WHERE IT RUNS, AND WHY THERE
Claude Code has no hook that can stop text before it is displayed
(MessageDisplay hooks "have no decision control"). So this gate runs at Stop,
after the reply was shown. The protocol (draft, panel, then emit the reviewed
text) keeps an unreviewed reply off the screen; this gate makes skipping the
protocol cost a rewrite turn, every time. Residuals: docs/architecture/
v11-reply-panel.md.

THE DECISION (FR-03, checked in this order; the first that holds exits 0)
  1. OCTO_REPLY_PANEL=off in this hook's own environment (the shell that
     launched Claude Code). Read before any import that can fail.
  2. last_assistant_message is empty or whitespace. An ABSENT key is not
     empty: the gate cannot decide and exits 2.
  3. The operator's own prompt for this turn carries the word `panel-skip`
     (never printed by this gate, so its own feedback cannot read as a waiver).
  4. A Pending_Panel exists and the reply is at most 30 words: an `Agent` call
     in this turn, after the operator prompt, whose subagent_type is a panel
     reviewer, whose prompt carries a `PANEL-TO: operator` block that
     panel_digest.recompute_from_report accepts, and which has not completed
     (no task notification naming its tool use id, no tool_result for it whose
     toolUseResult.isAsync is not true). Each one exempts ONE stop chain: its
     id is recorded in ~/.claude/.cache/receipts/reply-pending.jsonl, and a
     recorded id still exempts while stop_hook_active is true.
  5. For digest(reply, recipients=["operator"]) in this session, the deciding
     receipt (receipt_ledger.panel_receipts_for, first entry) is a PASS whose
     verdict_ts is strictly newer than the operator prompt, and PASS receipts
     newer than the prompt come from at least QUORUM distinct reviewer agent
     ids: 3 for a SELF reply, 1 for a SOURCED one (FR-06). A reply is SOURCED
     only when it has a Provenance / Procedencia / Herkunft line and EVERY
     such line has a Basis that names something: `Basis` (any case) then a
     colon or whitespace, not empty and not only none / nothing / n/a / na /
     a run of dashes (any case, trailing punctuation ignored), with no
     standalone `self` or own reasoning word (EN, ES, DE with or without the
     umlaut) and no item that is only a self source (`myself`,
     `self-evident`). `self` inside a longer token (`selftest.py`,
     `self-review of <path>`) is not a self source.
Otherwise exit 2, stderr naming the source class, the quorum, the digest, the
panel-request command and the
accepted reviewer types. stop_hook_active changes nothing: no block-once.

THE OPERATOR PROMPT
The newest user entry, walking back over tool results, task notifications,
peer messages and hand-backs and isMeta entries (Stop-hook feedback,
hook-injected text), whose origin.kind is human (or that has no origin). Any
other origin kind ends the walk with no prompt. A compact summary reached
first anchors the turn instead, with empty text and its own timestamp
(AC-22): a context continuation carries no operator words, so the skip word
cannot apply to it. It is read with the backward reader and origin helpers of
g__pretool-mcp__outward-send.py, loaded by file name, never copied; a helper
that is missing there is an error that names it.

FAIL-CLOSED
Anything that keeps the gate from deciding (unparseable payload, a payload
without last_assistant_message, no operator prompt, unreadable
transcript, an import error, a missing helper, a ledger that cannot be read,
a spent record that cannot be written) exits 2 with the error named. A
missing receipts directory is not an error: it reads as no receipt. The
operator's ways out are the skip word for one turn and the off switch for a
session. CLAUDE_CODE_CHILD_SESSION is ignored on purpose: the harness sets it
in every hook command.

Stdin:  Stop payload {"session_id", "transcript_path", "stop_hook_active",
        "last_assistant_message", ...}
Exit:   0 lets the stop through; 2 sends the reply back with stderr.
Selftest: --selftest <fixture_dir> (registry/fixtures/FLOW.panel-before-reply).
"""
from __future__ import annotations

import os
import sys

_OFF_ENV = "OCTO_REPLY_PANEL"


def _off() -> bool:
    """The off switch, read before anything that can fail."""
    return os.environ.get(_OFF_ENV, "").strip().lower() == "off"


import importlib.util  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
from pathlib import Path  # noqa: E402

for _stream in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

_HERE = Path(__file__).resolve().parent
_SEND_GATE = "g__pretool-mcp__outward-send.py"
# What this gate borrows from the send gate. Each must exist there.
_HELPERS = ("_reversed_lines", "_prompt_entries_reversed", "_origin",
            "_is_operator_opener", "_entry_text", "_ts")
_SKIP = re.compile(r"(?<![\w-])panel-skip(?![\w-])")
STATUS_CAP = 30
_AGENT_TOOLS = ("Agent", "Task")
_TOOL_USE_ID = re.compile(r"<tool-use-id>\s*([^<\s]+)\s*</tool-use-id>")
_PENDING_FILE = "reply-pending.jsonl"
_KERNEL_RULE = "FLOW.panel-before-reply"
_REQUEST_CMD = ("python3 ~/.claude/scripts/panel_digest.py --panel-request "
                "--to operator --body-file <file>")


class GateError(Exception):
    """The gate cannot decide; the message names why."""


def _load_file(name: str):
    spec = importlib.util.spec_from_file_location("_rp_" + name.replace("-", "_").replace(".", "_"),
                                                  _HERE / name)
    if spec is None or spec.loader is None:
        raise GateError(f"cannot load {name}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check_helpers(mod) -> None:
    """Raise GateError naming the first helper the send gate does not define."""
    for name in _HELPERS:
        if not callable(getattr(mod, name, None)):
            raise GateError(f"send gate helper missing: {name} (in scripts/{_SEND_GATE})")


class _Ctx:
    pass


def load() -> _Ctx:
    """Import everything the decision needs; any failure is a GateError."""
    if str(_HERE) not in sys.path:
        sys.path.insert(0, str(_HERE))
    ctx = _Ctx()
    try:
        import panel_digest
        import receipt_ledger
        ctx.pd, ctx.rl = panel_digest, receipt_ledger
        ctx.send = _load_file(_SEND_GATE)
    except GateError:
        raise
    except Exception as e:  # an import error is named, never swallowed
        raise GateError(f"import failed: {type(e).__name__}: {e}")
    check_helpers(ctx.send)
    return ctx


# ---------------------------------------------------------------------------
# Prompt_Reader
# ---------------------------------------------------------------------------

_WALK_PAST = ("task-notification", "peer")


def _skipped(ctx, entry: dict) -> bool:
    """Entries the walk passes over to reach the operator's own prompt."""
    if entry.get("isMeta") is True or entry.get("isSidechain"):
        return True
    return ctx.send._origin(entry).get("kind") in _WALK_PAST


def prompt_read(ctx, transcript: str) -> dict | None:
    """{"text", "ts", "uuid"} of the operator prompt behind this turn, or None
    when the walk meets an entry it cannot place: an origin kind it does not
    know, or a human-shaped entry the harness did not write. Either ends the
    walk with no prompt (fail closed), as the send gate's turn_read does.

    A compact summary reached before any human entry (AC-22) means the turn
    was opened by a context continuation: it carries no operator words, so
    the anchor is the summary itself with EMPTY text (no skip word can come
    from it) and its own timestamp as the newer-than bound. A summary the
    harness did not write (no uuid or timestamp) ends the walk like any
    entry the gate cannot place.

    OSError propagates: an unreadable transcript is an error, not an empty
    turn."""
    for e in ctx.send._prompt_entries_reversed(transcript):
        if _skipped(ctx, e):
            continue
        if e.get("isCompactSummary"):
            if not ctx.rl.harness_entry(e):
                return None
            return {"text": "", "ts": str(e.get("timestamp") or ""), "uuid": str(e.get("uuid") or "")}
        kind = ctx.send._origin(e).get("kind")
        if kind is not None and kind != "human":
            return None
        if ctx.send._is_operator_opener(e):
            return {"text": ctx.send._entry_text(e), "ts": str(e.get("timestamp") or ""),
                    "uuid": str(e.get("uuid") or "")}
        return None
    return None


def turn_after(ctx, transcript: str, prompt_uuid: str) -> tuple:
    """(entries newer than the operator prompt, oldest first; newest timestamp
    in the file). Sidechain entries are dropped."""
    out, newest = [], ""
    for raw in ctx.send._reversed_lines(transcript):
        try:
            e = json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            continue
        if not isinstance(e, dict):
            continue
        if not newest and e.get("timestamp"):
            newest = str(e["timestamp"])
        if prompt_uuid and e.get("uuid") == prompt_uuid and e.get("type") == "user":
            break
        if not e.get("isSidechain"):
            out.append(e)
    out.reverse()
    return out, newest


# ---------------------------------------------------------------------------
# Pending_Panel
# ---------------------------------------------------------------------------

def _blocks(entry: dict) -> list:
    c = (entry.get("message") or {}).get("content")
    return [b for b in c if isinstance(b, dict)] if isinstance(c, list) else []


def _valid_panel_call(ctx, block: dict) -> bool:
    if block.get("type") != "tool_use" or block.get("name") not in _AGENT_TOOLS:
        return False
    tin = block.get("input")
    if not isinstance(tin, dict):
        return False
    stype, prompt = tin.get("subagent_type"), tin.get("prompt")
    if not isinstance(stype, str) or not ctx.rl.PANEL_AGENT_TYPE.search(stype):
        return False
    if not isinstance(prompt, str):
        return False
    rec = ctx.pd.recompute_from_report(prompt)
    return bool(rec) and rec.get("recipients") == ["operator"]


def pending_panels(ctx, entries: list) -> list:
    """Tool use ids of panel calls in the turn that have not completed, oldest first."""
    calls, done = [], set()
    for e in entries:
        if e.get("type") == "assistant":
            for b in _blocks(e):
                if _valid_panel_call(ctx, b) and b.get("id"):
                    calls.append(str(b["id"]))
            continue
        if e.get("type") != "user":
            continue
        results = [b for b in _blocks(e) if b.get("type") == "tool_result"]
        if results:
            tur = e.get("toolUseResult")
            is_ack = isinstance(tur, dict) and tur.get("isAsync") is True
            if not is_ack:
                done.update(str(b.get("tool_use_id") or "") for b in results)
            continue
        done.update(_TOOL_USE_ID.findall(ctx.send._entry_text(e)))
    return [i for i in calls if i not in done]


def _pending_path(ctx) -> Path:
    return ctx.rl.receipts_dir() / _PENDING_FILE


def spent_ids(ctx) -> set:
    p = _pending_path(ctx)
    if not p.exists():
        return set()
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as e:
        raise GateError(f"spent ledger unreadable: {p} ({type(e).__name__})")
    out = set()
    for ln in text.splitlines():
        try:
            r = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if isinstance(r, dict) and r.get("tool_use_id"):
            out.add(str(r["tool_use_id"]))
    return out


def spend(ctx, tool_use_id: str, session_id: str) -> None:
    from datetime import datetime, timezone
    p = _pending_path(ctx)
    rec = {"kind": "reply-pending", "tool_use_id": tool_use_id, "session_id": session_id,
           "ts": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError as e:
        raise GateError(f"spent ledger not writable: {p} ({type(e).__name__})")


# ---------------------------------------------------------------------------
# The receipt
# ---------------------------------------------------------------------------

def _now(ctx, newest_ts: str):
    """Wall clock, except under selftest, where the newest transcript entry is
    the clock so static fixtures never age out of the 120-minute window."""
    from datetime import datetime, timezone
    if os.environ.get("CLAUDE_SESSION_ID") == ctx.rl.SELFTEST_SESSION and newest_ts:
        t = ctx.send._ts(newest_ts)
        if t is not None:
            return t
    return datetime.now(timezone.utc)


def pass_reviewers(ctx, digest: str, session_id: str, prompt_ts: str, now) -> int:
    """Distinct reviewer agent ids holding a PASS for `digest` newer than the
    operator prompt, or 0 when the deciding receipt is missing, is not a PASS,
    or is not newer than the prompt (FR-02, FR-06). Every receipt is validated
    by receipt_ledger.panel_receipts_for, the reader panel_latest_for uses."""
    g = ctx.rl.global_path()
    if g.exists():
        if not g.is_file():
            raise GateError(f"receipt ledger unreadable: {g} is not a regular file")
        try:
            with g.open("rb"):
                pass
        except OSError as e:
            raise GateError(f"receipt ledger unreadable: {g} ({type(e).__name__})")
    try:
        got = ctx.rl.panel_receipts_for(digest, session_id, now)
    except Exception as e:
        raise GateError(f"receipt ledger raised: {type(e).__name__}: {e}")
    after = ctx.send._ts(prompt_ts)
    if not got or after is None:
        return 0

    def newer(r) -> bool:
        when = ctx.send._ts(r.get("verdict_ts"))
        return when is not None and when > after

    if got[0].get("verdict") != "PASS" or not newer(got[0]):
        return 0
    return len({str(r.get("agent_id") or "") for r in got
                if r.get("verdict") == "PASS" and newer(r) and r.get("agent_id")})


# ---------------------------------------------------------------------------
# Source_Class (FR-06)
# ---------------------------------------------------------------------------
QUORUM = {"SELF": 3, "SOURCED": 1}
# A line that starts with the label; leading blanks, a quote marker and
# markdown emphasis around the label are tolerated ("**Provenance:**"). The
# label is followed by a colon or by a `·` field separator
# ("Procedencia · Basis: ...").
_PROVENANCE = re.compile(r"^[ \t>]*[*_]*(?:Provenance|Procedencia|Herkunft)[*_]*(?::|(?=[ \t]*·))(.*)$",
                         re.MULTILINE)
# The Basis field: the word Basis (any case) at the start of the line or of a
# `·` / `|` field, then a colon or whitespace, then what it names. `Basis /path`
# and `Basis: /path` are the same field; a bare `Basis` names nothing.
_BASIS = re.compile(r"(?:^|·|\|)\s*[*_]*Basis[*_]*(?:\s*:|(?=\s)|$)\s*([^·|]*)", re.IGNORECASE)
# A self source written as its own word: `self`, `SELF`, own reasoning (EN, ES,
# DE). Bounded so that a longer token that merely contains it (`selftest.py`,
# `self-review`, `myself`, `scripts/self_check`) does not match.
_SELF_WORD = re.compile(
    r"(?<![\w./\\-])(?:self|own reasoning|razonamiento propio|eigene Überlegung|eigene Ueberlegung)"
    r"(?![\w./\\-])", re.IGNORECASE)
# A Basis item that is nothing but a self source: `myself`, `self-evident`,
# `my own reasoning`, `reasoning`. Compared whole, after trimming.
_SELF_ITEM = re.compile(
    r"(?:my\s+)?(?:own\s+)?(?:self|myself|self[- ]evident|reasoning|razonamiento(?: propio)?|"
    r"eigene (?:Überlegung|Ueberlegung))", re.IGNORECASE)
# Items of a Basis: separated by , ; + & or the word and / y / und.
_ITEM_SPLIT = re.compile(r"\s*(?:[,;+&]|\band\b|\by\b|\bund\b)\s*", re.IGNORECASE)
# A Basis that names nothing: compared after lower-casing and stripping blanks
# and trailing punctuation. Any run of hyphens, en dashes or em dashes too.
_NO_BASIS = {"none", "nothing", "n/a", "na"}
_DASHES = re.compile("^[-–—]+$")


def _empty_basis(basis: str) -> bool:
    b = basis.strip().lower().rstrip(".,;:!? \t").strip()
    return not b or b in _NO_BASIS or bool(_DASHES.match(b))


def _self_basis(basis: str) -> bool:
    """True when the Basis names self or own reasoning as a source: a
    standalone self word anywhere, or any item that is only a self source.
    A word that merely contains `self` inside a longer token is not one."""
    if _SELF_WORD.search(basis):
        return True
    for item in _ITEM_SPLIT.split(basis):
        it = item.strip().strip("*_`()[]\"' ").rstrip(".,;:!? \t").strip()
        if it and _SELF_ITEM.fullmatch(it):
            return True
    return False


def _line_is_self(line: str) -> bool:
    m = _BASIS.search(line.strip().lstrip("*_ "))
    if not m:
        return True
    basis = m.group(1).strip().strip("*_ ")
    return _empty_basis(basis) or _self_basis(basis)


def source_class(text: str) -> str:
    """SELF when the reply has no provenance line or when ANY provenance line
    is SELF (no Basis field, a Basis that names nothing (see _empty_basis),
    or a Basis that names self or own reasoning in EN, ES or DE, see
    _self_basis). A later
    SOURCED line, a code block included, never lifts an earlier SELF line."""
    lines = _PROVENANCE.findall(text or "")
    if not lines or any(_line_is_self(ln) for ln in lines):
        return "SELF"
    return "SOURCED"


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------

def decide(data: dict) -> tuple:
    """(exit_code, stderr_message)."""
    if _off():
        return 0, ""
    if "last_assistant_message" not in data:
        raise GateError("payload has no last_assistant_message")
    msg = data["last_assistant_message"]
    if not isinstance(msg, str):
        raise GateError("last_assistant_message is not text")
    if not msg.strip():
        return 0, ""
    ctx = load()
    transcript = str(data.get("transcript_path") or "")
    if not transcript:
        raise GateError("the Stop payload names no transcript")
    session_id = str(data.get("session_id") or "")
    try:
        prompt = prompt_read(ctx, transcript)
        if prompt is None:
            raise GateError("no operator prompt found in the transcript")
        if _SKIP.search(prompt["text"]):
            return 0, ""
        entries, newest = turn_after(ctx, transcript, prompt["uuid"])
    except OSError as e:
        raise GateError(f"transcript unreadable: {transcript} ({type(e).__name__})")
    if len(msg.split()) <= STATUS_CAP:
        pend = pending_panels(ctx, entries)
        if pend:
            spent = spent_ids(ctx)
            if data.get("stop_hook_active") is True and any(i in spent for i in pend):
                return 0, ""
            fresh = [i for i in pend if i not in spent]
            if fresh:
                spend(ctx, fresh[-1], session_id)
                return 0, ""
    digest = ctx.pd.digest(msg, recipients=["operator"])
    cls = source_class(msg)
    need = QUORUM[cls]
    have = pass_reviewers(ctx, digest, session_id, prompt["ts"], _now(ctx, newest))
    if have >= need:
        return 0, ""
    return 2, (
        f"REPLY PANEL (FLOW.panel-before-reply): this reply is {cls} (source class) and "
        f"needs PASS receipts from {need} distinct reviewer(s) for its exact text, newer "
        f"than the operator's prompt, with a PASS deciding; it has {have} of {need}. "
        f"A reply is SOURCED only when every Provenance line has a Basis that names a "
        f"source other than self or own reasoning. Digest: {digest}. "
        f"Write the reply to a file, run `{_REQUEST_CMD}`, and hand that block to "
        f"{need} reviewer subagent(s) whose agent type matches "
        f"qa|review|reality|evidence|checker|verif|audit|panel (Reality Checker, Code "
        f"Reviewer, Evidence Collector; general-purpose, claude and fork do not count). "
        f"Each reviewer ends its report with the block, PANEL-VERDICT and PANEL-SHA256. "
        f"Then emit exactly the reviewed text. While a reviewer runs, a status line of "
        f"at most {STATUS_CAP} words may end the turn."
    )


def _journal_deny(reason, payload=None) -> None:
    """Mirror this refusal into the kernel journal. Fail-open by contract."""
    try:
        kp = _load_file("kernel_proc.py")
        p = payload if isinstance(payload, dict) else {}
        kp.journal_deny(_KERNEL_RULE, reason, p.get("tool_use_id"), kp.resolve_pid(p))
    except Exception:
        pass


def main() -> int:
    if _off():
        return 0
    data = None
    try:
        data = json.loads(sys.stdin.read())
        if not isinstance(data, dict):
            raise GateError("the Stop payload is not a JSON object")
        code, message = decide(data)
    except GateError as e:
        code, message = 2, f"REPLY PANEL (FLOW.panel-before-reply) cannot decide: {e}"
    except Exception as e:
        code, message = 2, (f"REPLY PANEL (FLOW.panel-before-reply) cannot decide: "
                            f"{type(e).__name__}: {e}")
    if code == 2:
        print(message, file=sys.stderr)
        _journal_deny(message[:300], data)
    return code


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

def _scrubbed_env(sandbox: Path) -> dict:
    import gate_selftest
    env = dict(os.environ)
    for k in gate_selftest._OVERRIDE_ENV + (_OFF_ENV,):
        env.pop(k, None)
    for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_PREFIX", "GIT_COMMON_DIR",
              "GIT_OBJECT_DIRECTORY", "GIT_NAMESPACE", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
              "GIT_QUARANTINE_PATH"):
        env.pop(k, None)
    env["HOME"] = env["USERPROFILE"] = str(sandbox)
    env["CLAUDE_SESSION_ID"] = gate_selftest.SELFTEST_SESSION
    # The harness sets this in every hook command; the gate must not care.
    env["CLAUDE_CODE_CHILD_SESSION"] = "1"
    return env


def _seed_case(sandbox: Path, session: str, msg: str, fx: dict) -> None:
    import hashlib
    import panel_fixture_seed
    for i, r in enumerate(fx.get("receipts") or []):
        agent_id = r.get("agent_id") or hashlib.sha256(f"{session}:{i}".encode()).hexdigest()[:17]
        panel_fixture_seed.seed_reply_receipt(
            sandbox, session, r.get("text", msg), r["verdict"], r["ts"], agent_id,
            r.get("agent_type", "Reality Checker"))
        if int(r.get("ledger_copies", 1)) > 1:
            # The same reviewer's row recorded several times: still one reviewer.
            ledger = sandbox / ".claude" / ".cache" / "receipts" / "global.jsonl"
            last = ledger.read_text(encoding="utf-8").splitlines()[-1]
            with ledger.open("a", encoding="utf-8") as fh:
                fh.write((last + "\n") * (int(r["ledger_copies"]) - 1))
        if r.get("corrupt_report"):
            # A text block whose text is not a string: the ledger's own report
            # reader raises TypeError on it, past the gate's readability check.
            tp = (sandbox / ".claude" / "projects" / "fx" / session / "subagents"
                  / f"agent-{agent_id}.jsonl")
            rows = [json.loads(ln) for ln in tp.read_text(encoding="utf-8").splitlines() if ln]
            for row in rows:
                if row.get("type") == "assistant":
                    row["message"]["content"].append({"type": "text", "text": 404})
            tp.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    rdir = sandbox / ".claude" / ".cache" / "receipts"
    if fx.get("spent"):
        rdir.mkdir(parents=True, exist_ok=True)
        with (rdir / _PENDING_FILE).open("a", encoding="utf-8") as fh:
            for tid in fx["spent"]:
                fh.write(json.dumps({"kind": "reply-pending", "tool_use_id": tid,
                                     "session_id": session}) + "\n")
    if fx.get("ledger") == "directory":
        (rdir / "global.jsonl").mkdir(parents=True, exist_ok=True)
    if fx.get("pending_ledger") == "directory":
        (rdir / _PENDING_FILE).mkdir(parents=True, exist_ok=True)
    if fx.get("receipts_dir") == "file":
        rdir.parent.mkdir(parents=True, exist_ok=True)
        rdir.write_text("not a directory", encoding="utf-8")


def _run_case(path: Path, fdir: Path) -> list:
    import shutil
    import subprocess
    import tempfile
    import gate_selftest
    want = 2 if path.name.startswith("violation") else 0
    data = json.loads(path.read_text(encoding="utf-8"))
    fx = data.pop("_fixture", {}) or {}
    tp = data.get("transcript_path")
    if isinstance(tp, str) and tp and not os.path.isabs(tp):
        data["transcript_path"] = str((fdir / tp).resolve())
    data.setdefault("session_id", gate_selftest.SELFTEST_SESSION)
    sandbox = Path(tempfile.mkdtemp(prefix="reply-panel-selftest-"))
    fails = []
    try:
        seed = fdir / "home"
        if seed.is_dir():
            shutil.copytree(seed, sandbox, dirs_exist_ok=True)
        _seed_case(sandbox, data["session_id"], str(data.get("last_assistant_message") or ""), fx)
        env = _scrubbed_env(sandbox)
        env.update({k: str(v) for k, v in (fx.get("env") or {}).items()})
        cp = subprocess.run([sys.executable, str(Path(__file__).resolve())],
                            input=json.dumps(data), capture_output=True, text=True,
                            encoding="utf-8", errors="replace", cwd=str(sandbox),
                            env=env, timeout=30)
        err = cp.stderr or ""
        if cp.returncode != want:
            fails.append(f"{path.name}: exit {cp.returncode}, want {want} ({err.strip()[:160]})")
        for s in fx.get("stderr_has") or []:
            if s not in err:
                fails.append(f"{path.name}: stderr lacks {s!r}")
        for s in fx.get("stderr_lacks") or []:
            if s in err:
                fails.append(f"{path.name}: stderr carries {s!r}")
        if fx.get("expect_spent"):
            p = sandbox / ".claude" / ".cache" / "receipts" / _PENDING_FILE
            got = p.read_text(encoding="utf-8") if p.is_file() else ""
            for tid in fx["expect_spent"]:
                if f'"{tid}"' not in got:
                    fails.append(f"{path.name}: {tid} not recorded as spent")
        if want == 2 and _KERNEL_RULE not in gate_selftest._journaled_denies(sandbox):
            fails.append(f"{path.name}: blocked but nothing journaled under {_KERNEL_RULE}")
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)
    return fails


def _unit_checks() -> list:
    """AC-01 on the digest itself, AC-17 on the helper check (in-process and
    end to end against a copy whose send gate lacks one helper)."""
    import shutil
    import subprocess
    import tempfile
    import types
    import panel_digest
    fails = []
    a = panel_digest.digest("The fix  is in.\nTests pass.", recipients=["operator"])
    b = panel_digest.digest("The fix is in. Tests\r\n  pass.", recipients=["operator"])
    c = panel_digest.digest("The fix is out. Tests pass.", recipients=["operator"])
    if a != b or a == c:
        fails.append("AC-01: whitespace changed the digest or a changed word did not")
    stub = types.SimpleNamespace(**{n: (lambda *x: None) for n in _HELPERS if n != "_origin"})
    try:
        check_helpers(stub)
        fails.append("AC-17: a send gate without _origin passed the helper check")
    except GateError as e:
        if "_origin" not in str(e):
            fails.append(f"AC-17: the helper error does not name _origin: {e}")
    tmp = Path(tempfile.mkdtemp(prefix="reply-panel-helper-"))
    try:
        for n in (Path(__file__).name, "panel_digest.py", "receipt_ledger.py", "kernel_proc.py"):
            shutil.copy2(_HERE / n, tmp / n)
        src = (_HERE / _SEND_GATE).read_text(encoding="utf-8")
        (tmp / _SEND_GATE).write_text(src.replace("def _origin(", "def _origin_gone("),
                                      encoding="utf-8")
        payload = {"session_id": "s", "transcript_path": str(tmp / "none.jsonl"),
                   "last_assistant_message": "a reply", "stop_hook_active": False}
        env = _scrubbed_env(tmp)
        cp = subprocess.run([sys.executable, str(tmp / Path(__file__).name)],
                            input=json.dumps(payload), capture_output=True, text=True,
                            encoding="utf-8", errors="replace", cwd=str(tmp), env=env, timeout=30)
        if cp.returncode != 2 or "_origin" not in (cp.stderr or ""):
            fails.append(f"AC-17: missing helper gave exit {cp.returncode}, "
                         f"stderr {(cp.stderr or '').strip()[:120]!r}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return fails


def _selftest() -> int:
    if str(_HERE) not in sys.path:
        sys.path.insert(0, str(_HERE))
    argv = sys.argv
    i = argv.index("--selftest")
    arg = argv[i + 1] if len(argv) > i + 1 else "registry/fixtures/FLOW.panel-before-reply"
    fdir = Path(arg)
    if not fdir.is_absolute():
        fdir = (_HERE.parent / fdir).resolve()
    cases = sorted(fdir.glob("violation*.json")) + sorted(fdir.glob("benign*.json"))
    if not fdir.is_dir() or not any(c.name.startswith("violation") for c in cases) \
            or not any(c.name.startswith("benign") for c in cases):
        print(f"selftest FAIL: need violation*.json and benign*.json in {fdir}", file=sys.stderr)
        return 1
    fails = _unit_checks()
    try:
        # A pre-flight check against helper drift in the live send gate.
        check_helpers(_load_file(_SEND_GATE))
    except Exception as e:
        fails.append(f"live send gate: {e}")
    for c in cases:
        fails.extend(_run_case(c, fdir))
    nv = sum(1 for c in cases if c.name.startswith("violation"))
    if fails:
        print(f"selftest FAIL: {nv} block + {len(cases) - nv} allow "
              f"({Path(__file__).name} vs {fdir.name}): " + "; ".join(fails), file=sys.stderr)
        return 1
    print(f"selftest PASS: {nv} block + {len(cases) - nv} allow + 2 unit checks "
          f"({Path(__file__).name} vs {fdir.name})")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    try:
        sys.exit(main())
    except Exception as e:
        print(f"REPLY PANEL (FLOW.panel-before-reply) cannot decide: {type(e).__name__}: {e}",
              file=sys.stderr)
        sys.exit(2)
