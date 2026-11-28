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
  4. A status line: the reply is at most 30 words, a subagent launched or
     messaged AFTER the operator prompt is still running, and fewer than
     STATUS_STOPS_MAX (3) status stops were already exempted for this
     prompt. Running (pending_agents): an Agent or Task call acknowledged as
     a background launch, or an agent resumed by SendMessage, with no
     hand-back, task notification, TaskStop or kernel `exit` line since,
     launched or messaged within PENDING_MAX_MINUTES (30). Those two are the
     boundary. The claim-word check (status_claim: an outcome word such as
     passed / merged / arreglé / erledigt, or a digit outside a provenance
     line) is an extra speed bump, not a boundary. Each exempted stop is
     appended to ~/.claude/.cache/receipts/reply-pending.jsonl with the
     prompt uuid; a ledger that cannot be read or written is an error.
  5. For digest(reply, recipients=["operator"]) in this session, the deciding
     receipt (receipt_ledger.panel_receipts_for, first entry) is a PASS whose
     verdict_ts is strictly newer than the operator prompt, and PASS receipts
     newer than the prompt come from at least QUORUM distinct reviewer agent
     ids: 3 for a SELF reply, 1 for a SOURCED or INPUT one (FR-06). An
     External_Review_Receipt (a review run on another engine through a
     pinned call, v11 phase 4) counts as one reviewer by its tool_use_id, and
     the quorum is counted only when, with every external PASS set aside,
     the newest receipt left is a harness reviewer's PASS newer than the
     prompt (AC-25, the order panel_pass_for uses): an external receipt adds
     to a quorum, never forms one, and never stands in for a revoked PASS. An INPUT
     reply only asks the operator for a fact (input_needed). A reply is SOURCED
     only when it has provenance, a Provenance / Procedencia / Herkunft line
     or provenance-ledger entries that count for it (ledger_entries:
     scripts/provenance_ledger.py, quiet provenance, the footer recorded off
     the operator's screen; every entry of this session newer than the
     prompt or than a full reply of this turn that already ended a stop, and
     not stamped in the future), and EVERY such line and entry has a Basis
     that names something: `Basis` (any case) then a
     colon or whitespace, not empty and not only none / nothing / n/a / na /
     a run of dashes (any case, trailing punctuation ignored), with no
     standalone `self` or own reasoning word (EN, ES, DE with or without the
     umlaut) and no item that is only a self source (`myself`,
     `self-evident`). `self` inside a longer token (`selftest.py`,
     `self-review of <path>`) is not a self source.
     The digest is over bound_reply_text: the reply itself when it shows a
     provenance line or uses no entry, else the reply plus the rendered
     footer of the newest entry used, which is the text panel_digest.py
     --panel-request --to operator puts in the reviewed block. A record made
     after the review changes the digest, so it voids the PASS.
Otherwise exit 2, stderr naming the source class, the quorum, the digest, the
panel-request command and the
accepted reviewer types. Block-once (operator directive 2026-11-07): while
stop_hook_active is true the stop goes through and the skip is journaled, so a
receipt that cannot be recorded never loops the turn until the harness cap.

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
# Pending subagents and the status line
# ---------------------------------------------------------------------------

def _blocks(entry: dict) -> list:
    c = (entry.get("message") or {}).get("content")
    return [b for b in c if isinstance(b, dict)] if isinstance(c, list) else []


# Lines worth parsing for the pending scan: async acks, SendMessage calls and
# results, hand-backs, task notifications, TaskStop, compact summaries.
_PENDING_HINTS = (b"isAsync", b"Agent\"", b"Task\"", b"SendMessage", b"resumedAgentId", b"peer", b"tool-use-id",
                  b"TaskStop", b"isCompactSummary")
# A subagent with no stop record is counted as running for at most this long
# after its launch or message: a killed or crashed agent leaves no hand-back.
PENDING_MAX_MINUTES = 30
# Status stops exempted per operator prompt; the next stop needs a reviewed
# reply. Counted in reply-pending.jsonl by prompt uuid.
STATUS_STOPS_MAX = 3


def _exit_ts(agent: str):
    """Time of the newest `exit` line in the kernel journal of `agent` (the
    SubagentStop reflex writes it), or None when there is none or it cannot
    be read. A missing record reads as still running, bounded by
    PENDING_MAX_MINUTES and STATUS_STOPS_MAX."""
    from datetime import datetime, timezone
    try:
        kp = _load_file("kernel_proc.py")
        with open(kp.journal_path(agent), "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 16384))
            chunk = fh.read()
    except Exception:
        return None
    for raw in reversed([c for c in chunk.split(b"\n") if c]):
        try:
            rec = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("kind") == "exit":
            try:
                return datetime.fromtimestamp(float(rec.get("ts")), timezone.utc)
            except (TypeError, ValueError):
                return None
    return None


def _peer_from(entry: dict) -> str:
    """The agent id of a hand-back entry (a user entry or a queued_command
    attachment whose origin kind is peer), else ""."""
    for o in (entry.get("origin"), (entry.get("attachment") or {}).get("origin")):
        if isinstance(o, dict) and o.get("kind") == "peer" and o.get("from"):
            return str(o["from"])
    return ""


def pending_agents(ctx, transcript: str, now, since=None) -> list:
    """Subagents of this session still running, oldest launch first: an Agent
    or Task call acknowledged as launched in the background (toolUseResult
    isAsync true), or an agent resumed by SendMessage, with no hand-back (a
    peer-origin entry from that agent), task notification naming the call or
    TaskStop after its last launch and no kernel `exit` line since it
    (_exit_ts), launched or messaged at most PENDING_MAX_MINUTES before `now`
    and strictly after `since` (the operator prompt: an agent of an earlier
    turn does not count unless messaged again in this one). Agents launched
    before the newest compact summary are not counted. Any subagent counts:
    a panel reviewer, a QA seat, a builder. OSError propagates."""
    calls, sends, launched, done, tid2agent = {}, {}, {}, {}, {}
    with open(transcript, "rb") as fh:
        for raw in fh:
            if not any(h in raw for h in _PENDING_HINTS):
                continue
            try:
                e = json.loads(raw.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                continue
            if not isinstance(e, dict) or e.get("isSidechain"):
                continue
            ts = ctx.send._ts(e.get("timestamp"))
            if ts is None:
                continue
            if e.get("isCompactSummary"):
                calls, sends, launched, done, tid2agent = {}, {}, {}, {}, {}
                continue
            who = _peer_from(e)
            if who:
                done[who] = ts
                continue
            if e.get("type") == "assistant":
                for b in _blocks(e):
                    if b.get("type") != "tool_use" or not b.get("id"):
                        continue
                    tin = b.get("input") if isinstance(b.get("input"), dict) else {}
                    if b.get("name") in _AGENT_TOOLS:
                        calls[str(b["id"])] = ts
                    elif b.get("name") == "SendMessage" and tin.get("to"):
                        sends[str(b["id"])] = str(tin["to"])
                    elif b.get("name") == "TaskStop":
                        for k in ("task_id", "agent_id", "id"):
                            if tin.get(k):
                                done[str(tin[k])] = ts
                continue
            if e.get("type") != "user":
                continue
            tur = e.get("toolUseResult") if isinstance(e.get("toolUseResult"), dict) else {}
            for b in _blocks(e):
                if b.get("type") != "tool_result":
                    continue
                tid = str(b.get("tool_use_id") or "")
                if tid in calls and tur.get("isAsync") is True:
                    agent = str(tur.get("agentId") or tid)
                    tid2agent[tid] = agent
                    launched[agent] = ts
                elif tid in sends and tur.get("success") is True:
                    launched[sends[tid]] = ts
            for tid in _TOOL_USE_ID.findall(ctx.send._entry_text(e)):
                done[tid2agent.get(tid, tid)] = ts
    from datetime import timedelta
    floor = now - timedelta(minutes=PENDING_MAX_MINUTES)
    out = []
    for a, t in launched.items():
        if t < floor or (since is not None and t <= since) or (a in done and done[a] >= t):
            continue
        x = _exit_ts(a)
        if x is not None and t <= x <= now:
            continue
        out.append((t, a))
    return [a for _, a in sorted(out)]


# A status line may not carry a result. Digits (outside provenance lines) and
# outcome words in EN, ES and DE make it a claim, which needs the panel.
_CLAIM_WORDS = re.compile(
    r"(?<![\w-])(?:pass(?:ed|es)?|fail(?:ed|s)?|needs-work|merged?|deployed|released|shipped|"
    r"published|sent|done|fixed|resolved|approved|completed?|finished|works|confirmed|verified|"
    r"found|green|correct|clean|success(?:ful)?|ready|"
    r"listos?|listas?|hech(?:o|a|as)|terminad[oa]s?|completad[oa]s?|mergead[oa]s?|fusionad[oa]s?|"
    r"desplegad[oa]s?|publicad[oa]s?|liberad[oa]s?|enviad[oa]s?|mandé|mandad[oa]s?|"
    r"arreglad[oa]s?|resuelt[oa]s?|aprobad[oa]s?|confirmad[oa]s?|verificad[oa]s?|funciona|"
    r"pasó|pasaron|falló|fallaron|encontró|arreglé|corregí|envié|quedó|aprobó|"
    r"fertig|erledigt|gemergt|veröffentlicht|veroeffentlicht|gesendet|behoben|bestanden|"
    r"genehmigt|bestätigt|bestaetigt|gefunden|gelöst|geloest|korrekt)(?![\w-])", re.IGNORECASE)
_DIGIT = re.compile(r"\d")


def status_claim(text: str) -> str:
    """The first claim marker in a status line, or "" when it carries none."""
    m = _CLAIM_WORDS.search(text)
    if m:
        return m.group(0)
    body = "\n".join(ln for ln in text.splitlines() if not _PROVENANCE.match(ln))
    m = _DIGIT.search(body)
    return m.group(0) if m else ""


def _pending_path(ctx) -> Path:
    return ctx.rl.receipts_dir() / _PENDING_FILE


def status_stops(ctx, session_id: str, prompt_uuid: str) -> int:
    """Status stops already exempted for this operator prompt. A ledger that
    exists and cannot be read is an error."""
    p = _pending_path(ctx)
    if not p.exists():
        return 0
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as e:
        raise GateError(f"spent ledger unreadable: {p} ({type(e).__name__})")
    n = 0
    for ln in text.splitlines():
        try:
            r = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if isinstance(r, dict) and r.get("session_id") == session_id \
                and r.get("prompt_uuid") == prompt_uuid:
            n += 1
    return n


def spend(ctx, tool_use_id: str, session_id: str, prompt_uuid: str = "") -> None:
    from datetime import datetime, timezone
    p = _pending_path(ctx)
    rec = {"kind": "reply-pending", "tool_use_id": tool_use_id, "session_id": session_id,
           "prompt_uuid": prompt_uuid,
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

    # v11 AC-25, in panel_pass_for's order (AC-26): every external PASS is
    # dropped, and the newest remaining receipt (harness PASS, harness
    # NEEDS-WORK, external NEEDS-WORK) must be a harness PASS newer than the
    # prompt. Only then does the quorum count, where an External_Review_Receipt
    # (receipt_ledger.external_panel_view) adds one distinct reviewer by its
    # tool_use_id. A harness PASS that a newer NEEDS-WORK revoked therefore
    # never lets external receipts form a quorum around it.
    deciding = [r for r in got if not (r.get("external") and r.get("verdict") == "PASS")]
    head = deciding[0] if deciding else None
    if not head or head.get("external") or head.get("verdict") != "PASS" or not newer(head):
        return 0
    if got[0].get("verdict") != "PASS" or not newer(got[0]):
        return 0
    return len({str(r.get("agent_id")) for r in got
                if r.get("verdict") == "PASS" and newer(r) and r.get("agent_id")})


# ---------------------------------------------------------------------------
# Source_Class (FR-06)
# ---------------------------------------------------------------------------
QUORUM = {"SELF": 3, "SOURCED": 1, "INPUT": 1}
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


# A token that starts with `self` names a source only as a path or file name:
# it contains a slash, or ends in a file extension. Backticked spans are paths.
_BACKTICK = re.compile(r"`[^`]*`")
_TOKEN_SPLIT = re.compile(r"[\s,;+&]+")
_FILE_EXT = re.compile(r"\.[A-Za-z0-9]{1,6}(?::[\d,-]+)?$")


def _self_token(basis: str) -> bool:
    """True when a token outside backticks starts with `self` (any case) and
    is not a path or file name: `self-review`, `self-assessment`, `SELF`."""
    for tok in _TOKEN_SPLIT.split(_BACKTICK.sub(" ", basis)):
        t = tok.strip("*_()[]\"'.:!?")
        if not t.lower().startswith("self"):
            continue
        if "/" in t or "\\" in t or _FILE_EXT.search(tok.strip("*_()[]\"',;:!?")):
            continue
        return True
    return False


def _self_basis(basis: str) -> bool:
    """True when the Basis names self or own reasoning as a source: a
    standalone self word anywhere, a token that starts with `self` and is
    not a path or file name (_self_token), or any item that is only a self
    source. `myself` inside a longer item and `self` inside a path are not."""
    if _SELF_WORD.search(basis) or _self_token(basis):
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


# input-needed: a short reply that ends on ONE question for a fact only the
# operator holds. The line names the unknown and ends with the question mark.
INPUT_CAP = 60
INPUT_CONTEXT_WORDS = 15
_INPUT_LINE = re.compile(r"^[ \t]*[*_]*input-needed[*_]*[ \t]*:[ \t]*(?P<q>.*\S.*\?)[*_ \t]*$",
                         re.IGNORECASE)
_NO_MENU = "g__stop__no-menu-question.py"


def _menu_or_consent(question: str) -> bool:
    """True when the no-menu gate reads the question as a menu, a permission
    or direction ask, or an irreducible operator step (consent, payment,
    login, send-ok). An error loading it reads as True: the reply then keeps
    its normal class, the stricter outcome."""
    try:
        nm = _load_file(_NO_MENU)
        cfg = nm._load_config()
        q = question.strip()
        if not q.lstrip("¿").strip(" ?"):
            return True
        if nm.is_choice_question(q, cfg):
            return True
        return bool(nm._irreducible_object(nm._fold(nm._trim_tail(q)), cfg))
    except Exception:
        return True


def input_needed(text: str) -> bool:
    """True for a reply that only asks the operator for a fact. Outside the
    footer (at most one provenance line, after the question) the reply is
    exactly the `input-needed:` line, ending with the only `?` of the reply,
    plus at most one context line before it of at most INPUT_CONTEXT_WORDS
    words. Neither line carries a claim marker (status_claim), and the
    question is neither a menu nor a consent ask (_menu_or_consent). The
    marker check is a speed bump; the INPUT reply still has its reviewer."""
    lines = (text or "").splitlines()
    prov = [i for i, ln in enumerate(lines) if _PROVENANCE.match(ln)]
    body = [(i, ln) for i, ln in enumerate(lines) if ln.strip() and i not in prov]
    if not body or len(body) > 2 or len(prov) > 1:
        return False
    qi, qline = body[-1]
    m = _INPUT_LINE.match(qline)
    if not m or (prov and prov[0] < qi):
        return False
    if len(body) == 2 and len(body[0][1].split()) > INPUT_CONTEXT_WORDS:
        return False
    if sum(len(ln.split()) for _, ln in body) > INPUT_CAP:
        return False
    if sum(ln.count("?") for _, ln in body) != 1:
        return False
    if status_claim("\n".join(ln for _, ln in body)):
        return False
    return not _menu_or_consent(m.group("q"))


def ledger_basis_is_self(entry: dict) -> bool:
    """The footer rules applied to a provenance-ledger entry's Basis
    (scripts/provenance_ledger.py): empty, naming nothing (_empty_basis), or
    naming self or own reasoning (_self_basis) is SELF."""
    basis = str((entry or {}).get("basis") or "").strip().strip("*_ ")
    return _empty_basis(basis) or _self_basis(basis)


def _explicit_self_basis(text: str, entries=()) -> bool:
    """True when a provenance line, or any fresh ledger entry, carries a
    Basis that is empty or names self (the stricter reading wins over INPUT)."""
    if any(ledger_basis_is_self(e) for e in entries or ()):
        return True
    for ln in _PROVENANCE.findall(text or ""):
        m = _BASIS.search(ln.strip().lstrip("*_ "))
        if m:
            basis = m.group(1).strip().strip("*_ ")
            if _empty_basis(basis) or _self_basis(basis):
                return True
    return False


def source_class(text: str, entries=()) -> str:
    """INPUT for an input-needed reply (input_needed) whose footer, if any,
    and whose ledger entries, if any, do not name self or an empty Basis;
    quorum 1 like SOURCED.
    Otherwise the provenance sources are every provenance line of the reply
    plus EVERY entry in `entries`: all provenance-ledger entries of this
    session that count for this reply (ledger_entries, quiet provenance).
    SELF when there is no source at all, or when ANY source is SELF (a line
    with no Basis field, a Basis that names nothing (see _empty_basis), or a
    Basis that names self or own reasoning in EN, ES or DE, see _self_basis;
    a ledger Basis is read with the same two helpers). Order never matters:
    a later SOURCED line, a code block included, or a later SOURCED ledger
    entry never lifts an earlier SELF one, the parity the footer lines have."""
    entries = list(entries or ())
    if input_needed(text) and not _explicit_self_basis(text, entries):
        return "INPUT"
    lines = _PROVENANCE.findall(text or "")
    if not lines and not entries:
        return "SELF"
    if any(_line_is_self(ln) for ln in lines):
        return "SELF"
    if any(ledger_basis_is_self(e) for e in entries):
        return "SELF"
    return "SOURCED"


def ledger_entries(session_id: str, prompt_ts: str, turn_entries: list, msg: str, now) -> list:
    """Every provenance-ledger entry that counts for the reply `msg`: newer
    than provenance_ledger.reply_anchor (the operator prompt, or a later
    full reply of this turn that already ended a stop) and not later than
    now + FUTURE_SKEW_S. An unreadable ledger is a GateError (fail closed); a
    missing one is no entry."""
    try:
        import provenance_ledger
        anchor = provenance_ledger.reply_anchor(prompt_ts, turn_entries, msg)
        return provenance_ledger.fresh_all(session_id, anchor, now)
    except OSError as e:
        raise GateError(f"provenance ledger unreadable ({type(e).__name__})")
    except Exception as e:
        raise GateError(f"provenance ledger: {type(e).__name__}: {e}")


def bound_reply_text(msg: str, entries) -> str:
    """The text the operator-reply digest is computed over. A reply with a
    visible provenance line, or with no ledger entry, is its own text
    (unchanged digest, back-compat). Otherwise the rendered footer line of the
    NEWEST entry used (the last of ledger_entries, which is sorted by
    effective time: the one recorded for this reply) is joined under it, so
    the reviewed block carries one Provenance line instead of a stack of
    every entry since the last full reply. A later record becomes the newest
    entry, so it still changes the digest (and voids the PASS). The source
    class and the quorum are NOT read from this text: source_class reads
    every entry used, so an older SELF entry still sets quorum 3 though its
    line is not in the block (R-19)."""
    entries = list(entries or ())
    if not entries or _PROVENANCE.findall(msg or ""):
        return msg
    import provenance_ledger
    return msg + "\n" + provenance_ledger.footer_line(entries[-1])


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
        turn, newest = turn_after(ctx, transcript, prompt["uuid"])
    except OSError as e:
        raise GateError(f"transcript unreadable: {transcript} ({type(e).__name__})")
    if len(msg.split()) <= STATUS_CAP and not status_claim(msg):
        try:
            pend = pending_agents(ctx, transcript, _now(ctx, newest), ctx.send._ts(prompt["ts"]))
        except OSError as e:
            raise GateError(f"transcript unreadable: {transcript} ({type(e).__name__})")
        if pend and status_stops(ctx, session_id, prompt["uuid"]) < STATUS_STOPS_MAX:
            spend(ctx, pend[-1], session_id, prompt["uuid"])
            return 0, ""
    used = ledger_entries(session_id, prompt["ts"], turn, msg, _now(ctx, newest))
    digest = ctx.pd.digest(bound_reply_text(msg, used), recipients=["operator"])
    cls = source_class(msg, used)
    need = QUORUM[cls]
    have = pass_reviewers(ctx, digest, session_id, prompt["ts"], _now(ctx, newest))
    if have >= need:
        return 0, ""
    return 2, (
        f"REPLY PANEL (FLOW.panel-before-reply): this reply is {cls} (source class) and "
        f"needs PASS receipts from {need} distinct reviewer(s) for its exact text, newer "
        f"than the operator's prompt, with a PASS deciding; it has {have} of {need}. "
        f"A reply is SOURCED only when it has provenance (a Provenance line, or an entry "
        f"recorded off-screen with `python3 ~/.claude/scripts/provenance_ledger.py record "
        f"--basis ...` after the operator's prompt and after your last full reply; "
        f"without a visible footer the newest entry's footer line is part of the digest, "
        f"so record BEFORE the panel request) and every Basis names a "
        f"source other than self or own reasoning; an INPUT reply only asks, on a last "
        f"line starting `input-needed:`, for a fact only the operator holds, and its "
        f"reviewer confirms that fact is not available from context. Digest: {digest}. "
        f"Write the reply to a file, run `{_REQUEST_CMD}` (it runs the other Stop gates on "
        f"the draft first and prints no block when one would change the text), and hand that block to "
        f"{need} reviewer subagent(s) whose agent type matches "
        f"qa|review|reality|evidence|checker|verif|audit|panel (Reality Checker, Code "
        f"Reviewer, Evidence Collector; general-purpose, claude and fork do not count). "
        f"Each reviewer writes the block byte for byte with PANEL-VERDICT and PANEL-SHA256 "
        f"to a file with ONE Bash call (cat <<'EOF' > /tmp/<dir>/panel-<sha8>.txt ... EOF; a "
        f"normal message also counts; a cat of the request file does not), then ends its "
        f"final report with only the PANEL-VERDICT and "
        f"PANEL-SHA256 lines (plus one line of finding if NEEDS-WORK); a final report that "
        f"repeats the whole block still counts. "
        f"A receipted review on another engine counts as one more reviewer, never as the "
        f"only one: at least one PASS must come from a harness reviewer subagent. "
        f"Then emit exactly the reviewed text. While a subagent runs, a status line of "
        f"at most {STATUS_CAP} words with no result in it (no outcome word, no digit) may "
        f"end the turn."
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
        if data.get("stop_hook_active") is True:
            # Block-once: the first block already showed the panel request; a
            # second one only loops (a reply is displayed before any Stop hook
            # runs). The skip is journaled so it stays visible.
            _journal_deny("reply panel skipped: stop_hook_active (block-once)", data)
            return 0
        code, message = decide(data)
    except GateError as e:
        code, message = 2, f"REPLY PANEL (FLOW.panel-before-reply) cannot decide: {e}"
    except Exception as e:
        code, message = 2, (f"REPLY PANEL (FLOW.panel-before-reply) cannot decide: "
                            f"{type(e).__name__}: {e}")
    if code == 2:
        print(_quiet(message, data), file=sys.stderr)
        _journal_deny(message[:300], data)
    return code


_SHORT_RE = re.compile(r"needs PASS receipts from (\d+) distinct.*?it has (\d+) of \d+", re.S)
_CLASS_RE = re.compile(r"this reply is (\w+) \(source class\)")


def _short(message: str) -> str:
    """The measured fact of a block, for the one line the operator sees:
    `REPLY PANEL <have>/<need> (<class>)`, or the cannot-decide cause."""
    m = _SHORT_RE.search(message or "")
    if m:
        c = _CLASS_RE.search(message)
        cls = f" ({c.group(1)})" if c else ""
        return f"REPLY PANEL {m.group(2)}/{m.group(1)}{cls}"
    return message


def _quiet(message: str, payload=None) -> str:
    """One short line naming the detail file the full text was written to
    (scripts/stop_block.py), or the FULL message when that write fails."""
    try:
        import stop_block
        return stop_block.shown(__file__, _short(message), message,
                                payload if isinstance(payload, dict) else None, _KERNEL_RULE)
    except Exception:
        return message


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

def _scrubbed_env(sandbox: Path) -> dict:
    import gate_selftest
    env = dict(os.environ)
    for k in gate_selftest._OVERRIDE_ENV + (_OFF_ENV, "OCTO_STOP_BLOCK_DIR",
                                             "OCTO_STOP_BLOCK_SESSION"):
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
        ext = r.get("external")
        if ext:
            # An External_Review_Receipt (v11 AC-24 to AC-27): Bash tool_use and
            # result in the session transcript, output copy, ledger rows and a
            # Reviewer_Registry pair, allowed unless the fixture says not.
            import panel_digest
            cwd, project = "~/.claude", ""
            if ext.get("arm"):
                cwd = panel_fixture_seed.seed_arm(sandbox, "fx-arm", ext["arm"])
                project = cwd if ext.get("with_project") else ""
            if ext.get("project_arm"):
                # The call ran from a directory under no arm (`cd` out of the
                # session's arm); the session's project dir is the arm.
                (sandbox / "elsewhere").mkdir(exist_ok=True)
                cwd = "~/elsewhere"
                project = panel_fixture_seed.seed_arm(sandbox, "fx-arm", ext["project_arm"])
            panel_fixture_seed.seed_external_receipt(
                sandbox, session, panel_digest.Message(r.get("text", msg), [], ["operator"]),
                r["verdict"], r["ts"], ext.get("tool_use_id") or f"toolu_fx_ext_{i}",
                ext.get("engine", "codex"), ext.get("model", "fx-review-model"), cwd,
                ext.get("allowed", True), project)
            continue
        agent_id = r.get("agent_id") or hashlib.sha256(f"{session}:{i}".encode()).hexdigest()[:17]
        panel_fixture_seed.seed_reply_receipt(
            sandbox, session, r.get("text", msg), r["verdict"], r["ts"], agent_id,
            r.get("agent_type", "Reality Checker"),
            short=bool(r.get("short")), block_verdict=r.get("block_verdict"))
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
    if fx.get("provenance"):
        # Quiet provenance: entries recorded off-screen with provenance_ledger.py,
        # each {"ts", "basis", ...} (session defaults to the payload's).
        pdir = sandbox / ".claude" / ".cache" / "provenance"
        pdir.mkdir(parents=True, exist_ok=True)
        with (pdir / "provenance.jsonl").open("a", encoding="utf-8") as fh:
            for row in fx["provenance"]:
                rec = {"kind": "provenance", "session_id": session}
                rec.update(row)
                fh.write(json.dumps(rec) + "\n")
    if fx.get("spent"):
        rdir.mkdir(parents=True, exist_ok=True)
        with (rdir / _PENDING_FILE).open("a", encoding="utf-8") as fh:
            for tid in fx["spent"]:
                rec = {"kind": "reply-pending", "session_id": session}
                rec.update(tid if isinstance(tid, dict) else {"tool_use_id": tid})
                fh.write(json.dumps(rec) + "\n")
    for agent, when in (fx.get("kernel_exit") or {}).items():
        # The SubagentStop reflex's `exit` line in the agent's kernel journal.
        from datetime import datetime
        jd = sandbox / ".claude" / ".cache" / "kernel" / "journal"
        jd.mkdir(parents=True, exist_ok=True)
        t = datetime.fromisoformat(when.replace("Z", "+00:00")).timestamp()
        (jd / f"{agent}.jsonl").write_text(json.dumps(
            {"seq": 1, "ts": t, "start_ts": t, "pid": agent, "kind": "exit"}) + "\n", encoding="utf-8")
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
        shown = cp.stderr or ""
        if cp.returncode != want:
            fails.append(f"{path.name}: exit {cp.returncode}, want {want} ({shown.strip()[:160]})")
        # A block shows ONE short line naming the detail file; the model reads
        # the full text there (scripts/stop_block.py). The text assertions run
        # on that full text, and the shown line is held to one line under the cap.
        err = shown
        if want == 2:
            import stop_block
            line = shown.strip()
            if "\n" in line or stop_block.words(line) > stop_block.WORD_CAP:
                fails.append(f"{path.name}: shown reason is not one line under "
                             f"{stop_block.WORD_CAP} words: {line[:160]!r}")
            det = line.rsplit(" · detail: ", 1)
            dpath = Path(det[1]) if len(det) == 2 else None
            if dpath is None or not dpath.is_file() or sandbox.resolve() not in dpath.resolve().parents:
                fails.append(f"{path.name}: shown reason names no detail file in the sandbox")
            else:
                err = dpath.read_text(encoding="utf-8")
            # AC-05: a missing-receipt block shows `REPLY PANEL <have>/<need> (<class>)`
            # and then only the detail path.
            if _SHORT_RE.search(err) and not re.fullmatch(
                    r"REPLY PANEL \d+/\d+ \((?:INPUT|SELF|SOURCED)\) · detail: \S.*", line):
                fails.append(f"{path.name}: missing-receipt line is not "
                             f"`REPLY PANEL <have>/<need> (<class>)` + path: {line[:160]!r}")
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
