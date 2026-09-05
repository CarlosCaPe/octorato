#!/usr/bin/env python3
"""receipt_ledger.py: the v7 receipt ledger (shared library, not a hook).

THE CONTRACT IT SERVES
"Nothing ships unverified" (docs/architecture/v7-nothing-ships-unverified.md):
an outward action is allowed only when the turn carries machine receipts. A
receipt is written by a HOOK running in the harness process, never typed by
the model, and every consumer re-verifies it against something the model does
not own before trusting it. The ledger line is a pointer; the anchor is the
proof:

  seek receipt     written by r__posttool__receipt-seek.py after a chat, mail
                   or memory lookup. Anchor: the receipt's tool_use_id must be
                   a tool_use block in the CURRENT turn of the transcript AND
                   that block's tool must itself be a seek (a seek tool by
                   name, or a Bash sub-command that invokes a seek at a command
                   boundary). A hand-typed line pointing at a `Read` or at
                   `echo list_messages` names no seek and is ignored.
  gate receipt     written by brain_doctor when gate-liveness PASSES on a CLEAN
                   tree, carrying the brain's HEAD and the git tree hash of the
                   gate surfaces (scripts/, registry/, hooks.json). Anchor: both
                   must equal the live values and the gate surfaces must still
                   be clean; an uncommitted edit to a gate voids the receipt.
  qa receipt       written by r__subagent-stop__qa-receipt.py when a subagent
                   ends with the verdict protocol. Anchor: the agent transcript
                   must live under the harness projects dir, its LAST assistant
                   text must re-parse to PASS with a scope naming the PR as a
                   whole token, and the agent type must be a QA persona.

Residual, stated plainly: the model can write to any file under $HOME through
Bash, this ledger included. What it cannot do is make the transcript contain a
tool_use it never made, move the brain's HEAD or its tree hashes, or produce a
subagent transcript the harness did not write. Every consumer anchors on those.
Same stance as qa-merge-gate: the env and the harness are the boundary, the
file is the audit trail. Measured upstream (~5% hook bypass in the platform):
the promise is "visible and recorded", never "impossible".

Layout (gitignored, per machine):
  ~/.claude/.cache/receipts/<session_id>.jsonl   seek receipts for one session
  ~/.claude/.cache/receipts/global.jsonl         gate-liveness + qa receipts

A line is JSON: {"kind": ..., "ts": ISO-8601 UTC, ...fields}.
"""
from __future__ import annotations

import datetime as _dt
import importlib.util
import json
import os
import re
import subprocess
from pathlib import Path

SELFTEST_SESSION = "__selftest__"   # set by gate_selftest.py, never by the model
SELFTEST_HEAD = "SELFTEST"

_HERE = Path(__file__).resolve().parent

# Seek tools by name (chat history, mail history). Shared by the writer reflex
# and every consumer so "what counts as a seek" lives in exactly one place.
SEEK_TOOL = re.compile(
    r"(list_messages|get_message_context|get_chat|get_direct_chat_by_contact"
    r"|get_last_interaction|search_emails|search_threads|get_thread|read_email"
    r"|get_message|list_chats)$",
    re.IGNORECASE,
)
# Seek COMMANDS, matched at the start of a stripped shell sub-command only.
_SEEK_CMD_HEAD = re.compile(
    r"^(?:python3?\s+)?(?:\S*/)?(?:query_connectome\.py\s+memory|impact-radius\.py"
    r"|wa-guardia\.py|generate_memory_map\.py)\b"
    r"|^sqlite3\s+\S*messages\.db\b",
    re.IGNORECASE,
)


def _qa_gate_helpers():
    """Borrow the command-boundary splitter the merge gate already proved."""
    spec = importlib.util.spec_from_file_location("qa_merge_gate", _HERE / "qa-merge-gate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._split_subcmds, mod._strip_leading


def subcommands(command: str) -> list:
    """Stripped sub-commands of a shell string, split on UNQUOTED separators."""
    try:
        split, strip = _qa_gate_helpers()
        return [strip(p) for p in split(command.replace("\\\n", " ")) if p.strip()]
    except Exception:
        return [command]


def bash_is_seek(command: str) -> bool:
    return any(_SEEK_CMD_HEAD.search(sc) for sc in subcommands(str(command or "")))


def is_seek_tool(tool_name: str, tool_input) -> bool:
    if SEEK_TOOL.search(str(tool_name or "")):
        return True
    if tool_name == "Bash" and isinstance(tool_input, dict):
        return bash_is_seek(tool_input.get("command", ""))
    return False


# --------------------------------------------------------------------------
# Paths + IO
# --------------------------------------------------------------------------

def receipts_dir() -> Path:
    return Path(os.path.expanduser("~")) / ".claude" / ".cache" / "receipts"


def harness_projects_dir() -> Path:
    return Path(os.path.expanduser("~")) / ".claude" / "projects"


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name or "")[:120] or "unknown"


def session_path(session_id: str) -> Path:
    return receipts_dir() / f"{_safe(session_id)}.jsonl"


def global_path() -> Path:
    return receipts_dir() / "global.jsonl"


def _append(path: Path, record: dict) -> None:
    record = dict(record)
    record.setdefault("ts", _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def append_session(session_id: str, record: dict) -> None:
    _append(session_path(session_id), record)


def append_global(record: dict) -> None:
    _append(global_path(), record)


def _read(path: Path, max_bytes: int = 1 << 20) -> list:
    out = []
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - max_bytes))
            for line in fh.read().decode("utf-8", errors="replace").splitlines():
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    out.append(obj)
    except OSError:
        pass
    return out


def read_session(session_id: str) -> list:
    return _read(session_path(session_id))


def read_global() -> list:
    return _read(global_path())


# --------------------------------------------------------------------------
# Transcript anchoring
# --------------------------------------------------------------------------

def _tail_lines(path: str, max_bytes: int = 262144) -> list:
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        fh.seek(max(0, size - max_bytes))
        return fh.read().decode("utf-8", errors="replace").splitlines()


def _turn_entries(transcript_path: str) -> tuple:
    """(assistant_entries_newest_first, last_human_entry) since the last HUMAN
    prompt. A tool RESULT is also a type "user" entry; the walk must not stop
    there (measured on a real session: 656 of 764 user entries are results).
    This is the same walk the Stop gates use, so "the turn" means one thing."""
    try:
        lines = _tail_lines(transcript_path)
    except OSError:
        return [], None
    entries, human = [], None
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") == "user":
            content = (entry.get("message") or {}).get("content")
            if isinstance(content, list) and any(
                    isinstance(b, dict) and b.get("type") == "tool_result"
                    for b in content):
                continue
            human = entry
            break
        if entry.get("type") == "assistant":
            entries.append(entry)
    return entries, human


def turn_tool_uses(transcript_path: str) -> list:
    """[(tool_use_id, tool_name, tool_input)] for every tool_use in the turn."""
    entries, _ = _turn_entries(transcript_path)
    uses = []
    for entry in entries:
        content = (entry.get("message") or {}).get("content") or []
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                uses.append((str(block.get("id", "")), str(block.get("name", "")),
                             block.get("input") or {}))
    return uses


def turn_last_human_text(transcript_path: str) -> str:
    """The operator's own words that opened this turn (the only place a hatch
    token counts: a token inside an outbound body would ship to the recipient
    and be self-serve)."""
    _, human = _turn_entries(transcript_path)
    if not human:
        return ""
    content = (human.get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text")
    return ""


def seek_receipts_in_turn(session_id: str, transcript_path: str) -> list:
    """Seek receipts of this session whose tool_use_id names a tool_use in the
    current turn THAT IS ITSELF A SEEK. A receipt without an id never counts."""
    by_id = {u: (n, i) for u, n, i in turn_tool_uses(transcript_path) if u}
    hits = []
    for r in read_session(session_id):
        if r.get("kind") != "seek":
            continue
        tid = r.get("tool_use_id")
        if not tid or tid not in by_id:
            continue
        name, inp = by_id[tid]
        if is_seek_tool(name, inp):
            hits.append(r)
    return hits


# --------------------------------------------------------------------------
# Gate receipt
# --------------------------------------------------------------------------

GATE_SURFACES = ("scripts", "registry", "hooks.json")


def _git(brain_dir: Path, *args) -> str:
    try:
        cp = subprocess.run(["git", "-C", str(brain_dir), *args],
                            capture_output=True, text=True, timeout=10)
        return cp.stdout.strip() if cp.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def brain_head(brain_dir: Path) -> str:
    return _git(brain_dir, "rev-parse", "HEAD")


def gate_tree_hash(brain_dir: Path) -> str:
    """Content identity of the gate surfaces at HEAD: the git object ids of the
    scripts/ and registry/ trees and the hooks.json blob. Changes whenever any
    gate, fixture, rule or wiring changes, even across commits with equal
    HEAD-relative paths."""
    parts = [_git(brain_dir, "rev-parse", f"HEAD:{p}") for p in GATE_SURFACES]
    return ":".join(parts) if all(parts) else ""


def gate_surfaces_dirty(brain_dir: Path) -> list:
    """Uncommitted changes under the gate surfaces (each line of porcelain)."""
    out = _git(brain_dir, "status", "--porcelain", "--", *GATE_SURFACES)
    return [ln for ln in out.splitlines() if ln.strip()]


def gate_receipt_ok(head: str, gates: str) -> bool:
    if not head or not gates:
        return False
    for r in read_global():
        if (r.get("kind") == "gate-liveness" and r.get("ok")
                and r.get("head") == head and r.get("gates") == gates):
            return True
    return False


# --------------------------------------------------------------------------
# QA receipt
# --------------------------------------------------------------------------

_VERDICT = re.compile(r"QA-VERDICT\s*:\s*(PASS|FAIL|NEEDS[ -]WORK)\b", re.IGNORECASE)
_SCOPE = re.compile(r"QA-SCOPE\s*:\s*([^\n]+)", re.IGNORECASE)
# Personas that count as an independent verifier. A cheap Explore agent told
# to print two lines is not QA.
QA_AGENT_TYPE = re.compile(r"(qa|review|reality|evidence|checker|verif|audit)", re.IGNORECASE)


def parse_verdict(text: str) -> tuple:
    """(verdict, scope) from a QA agent's final message: the LAST occurrence
    of each, so a quoted protocol line earlier in the message cannot stand in
    for the real verdict at the end. ("", "") when absent."""
    if not text:
        return "", ""
    vms = list(_VERDICT.finditer(text))
    sms = list(_SCOPE.finditer(text))
    verdict = vms[-1].group(1).upper().replace(" ", "-") if vms else ""
    scope = sms[-1].group(1).strip() if sms else ""
    return verdict, scope


def scope_names(scope: str, token: str) -> bool:
    """Whole-token match: '#260' names 260, never 26 or 2600."""
    t = re.escape(str(token))
    return bool(re.search(rf"(?<![\w#]){'#?' if not t.startswith('#') else ''}{t}(?![\w])", scope))


def last_assistant_text(transcript_path: str) -> str:
    try:
        lines = _tail_lines(transcript_path)
    except OSError:
        return ""
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "assistant":
            continue
        content = (entry.get("message") or {}).get("content") or []
        if isinstance(content, str):
            return content
        texts = [b.get("text", "") for b in content
                 if isinstance(b, dict) and b.get("type") == "text"]
        if texts:
            return "\n".join(texts)
    return ""


def qa_pass_for(token: str) -> dict | None:
    """Most recent qa receipt that (1) was written for a QA persona, (2) points
    at an agent transcript under the harness projects dir, and (3) whose last
    assistant text re-parses to PASS with a scope naming `token` as a whole
    token. Every other line is skipped, never trusted."""
    if not token:
        return None
    root = harness_projects_dir().resolve()
    for r in reversed(read_global()):
        if r.get("kind") != "qa" or r.get("verdict") != "PASS":
            continue
        if not QA_AGENT_TYPE.search(str(r.get("agent_type", ""))):
            continue
        tp = str(r.get("agent_transcript_path") or "")
        if not tp:
            continue
        try:
            rp = Path(tp).resolve()
            rp.relative_to(root)
        except (ValueError, OSError):
            continue
        if not rp.is_file():
            continue
        verdict, scope = parse_verdict(last_assistant_text(str(rp)))
        if verdict == "PASS" and scope_names(scope, token):
            return r
    return None
