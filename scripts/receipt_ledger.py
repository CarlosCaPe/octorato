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

Residual, stated plainly (QA cycle 2, 2026-09-05): the session transcript and
the agent transcripts are FILES under $HOME, and the model can append to them
through Bash. So a transcript anchor is not unforgeable; the only boundary the
model cannot cross is the harness environment (env vars set in the operator's
shell, the process that runs hooks). What the anchors buy is a higher bar and
VISIBILITY: a forged entry has to be appended to a harness-owned file, carry
the harness fields real entries carry (uuid, parentUuid, sessionId, timestamp),
sit in the right session's subagent directory, and it stays in the audit trail
for anyone who looks. Measured upstream (~5% hook bypass in the platform): the
promise is "visible and recorded", never "impossible". Same stance as
qa-merge-gate: the env is the boundary, the ledger is the trail.

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
# Only lookups that can REFUTE a claim: they return message bodies. Chat
# listings and "last interaction" metadata cannot, so they are not seeks.
SEEK_TOOL = re.compile(
    r"(list_messages|get_message_context|search_emails|search_threads|get_thread"
    r"|read_email|get_message)$",
    re.IGNORECASE,
)
# Wrappers an honest invocation may carry in front of the real command;
# peeled before matching a send or a seek at the sub-command head.
_WRAPPER = re.compile(
    r"^(?:bash|sh|zsh|dash|nohup|time|exec|command|nice(?:\s+-n\s*\d+)?"
    r"|timeout(?:\s+-\S+)*\s+\S+|sudo(?:\s+-\S+)*)\s+",
    re.IGNORECASE,
)
_SHELL_C = re.compile(r"^(?:bash|sh|zsh|dash)\s+-c\s+(.*)$", re.IGNORECASE | re.DOTALL)
# git exports these to its hooks; a child git inheriting them acts on the LIVE
# repo, not on the one named by -C (the 2026-09-05 stray-commit incident).
GIT_HOOK_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_PREFIX",
                "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY", "GIT_NAMESPACE",
                "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_QUARANTINE_PATH")
# Fields every entry written by the harness carries. A hand-appended line that
# lacks them is not anchored; one that fakes them is a forgery the trail shows.
HARNESS_FIELDS = ("uuid", "parentUuid", "sessionId", "timestamp")


def _qa_gate_helpers():
    """Borrow the command-boundary splitter the merge gate already proved."""
    spec = importlib.util.spec_from_file_location("qa_merge_gate", _HERE / "qa-merge-gate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._split_subcmds, mod._strip_leading


def _peel(sc: str) -> list:
    """Strip interpreter/wrapper prefixes; `bash -c "..."` unquotes and re-splits."""
    import shlex
    out, seen = [], set()
    stack = [sc]
    while stack:
        cur = stack.pop().strip()
        if not cur or cur in seen:
            continue
        seen.add(cur)
        m = _SHELL_C.match(cur)
        if m:
            inner = m.group(1).strip()
            try:
                parts = shlex.split(inner)
                inner = parts[0] if parts else inner
            except ValueError:
                pass
            stack.extend(_raw_split(inner))
            continue
        prev = None
        while prev != cur:
            prev = cur
            cur = _WRAPPER.sub("", cur, count=1)
        out.append(cur)
    return out


def _raw_split(command: str) -> list:
    try:
        split, strip = _qa_gate_helpers()
        return [strip(p) for p in split(command.replace("\\\n", " ")) if p.strip()]
    except Exception:
        return [command]


def subcommands(command: str) -> list:
    """Stripped sub-commands of a shell string: split on UNQUOTED separators,
    leading env/redirect/grouping removed, wrappers peeled, `sh -c` expanded."""
    out = []
    for sc in _raw_split(str(command or "")):
        out.extend(_peel(sc))
    return out


def tokens_of(subcmd: str) -> list:
    import shlex
    try:
        return shlex.split(subcmd)
    except ValueError:
        return subcmd.split()


def _is_script_token(tok: str, name: str) -> bool:
    return tok == name or tok.endswith("/" + name)


def bash_is_seek(command: str) -> bool:
    """A seek anywhere in the argv of any sub-command, by TOKEN (never by
    substring): wrappers, interpreters and indirection through argv are all
    covered by the same rule, and a quoted commit message stays one token that
    is not the script name (QA cycle 3)."""
    for sc in subcommands(str(command or "")):
        toks = tokens_of(sc)
        for i, t in enumerate(toks):
            if _is_script_token(t, "query_connectome.py") and "memory" in toks[i + 1:i + 2]:
                return True
            if any(_is_script_token(t, n) for n in ("impact-radius.py", "wa-guardia.py",
                                                     "generate_memory_map.py")):
                return True
            if t == "sqlite3" and any(x.endswith("messages.db") for x in toks[i + 1:]):
                return True
    return False


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


def harness_entry(entry: dict) -> bool:
    """True when the entry carries every field the harness writes."""
    return isinstance(entry, dict) and all(k in entry for k in HARNESS_FIELDS) \
        and bool(entry.get("uuid")) and bool(entry.get("sessionId")) and bool(entry.get("timestamp"))


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
            # The turn boundary is the last human prompt whatever its shape; a
            # hatch is read from it only when it is a harness-written entry.
            human = entry if harness_entry(entry) else None
            break
        if entry.get("type") == "assistant" and harness_entry(entry):
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


def scrubbed_env() -> dict:
    env = dict(os.environ)
    for k in GIT_HOOK_ENV:
        env.pop(k, None)
    return env


def _git(brain_dir: Path, *args, inp: str | None = None) -> str:
    try:
        cp = subprocess.run(["git", "-C", str(brain_dir), *args], input=inp,
                            capture_output=True, text=True, timeout=20, env=scrubbed_env())
        return cp.stdout.strip() if cp.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def brain_head(brain_dir: Path) -> str:
    return _git(brain_dir, "rev-parse", "HEAD")


def gate_tree_hash(brain_dir: Path) -> str:
    """Content identity of the gate surfaces at HEAD: the git object ids of the
    scripts/ and registry/ trees and the hooks.json blob. Changes whenever any
    gate, fixture, rule or wiring changes. The receipt is keyed on THIS, not on
    HEAD: a squash-merge with an identical gate tree keeps the receipt valid."""
    parts = [_git(brain_dir, "rev-parse", f"HEAD:{p}") for p in GATE_SURFACES]
    return ":".join(parts) if all(parts) else ""


def gate_surfaces_dirty(brain_dir: Path) -> list:
    """Anything under the gate surfaces that differs from HEAD, by three
    independent readings, because `git status` alone is silenced by
    `update-index --assume-unchanged` / `--skip-worktree` (QA cycle 2):
      1. porcelain status (modified, added, untracked)
      2. ls-files -v flags h (assume-unchanged) / S (skip-worktree)
      3. every tracked file's live blob id vs its HEAD blob id
    Returns one line per finding; empty means clean."""
    out = []
    for ln in _git(brain_dir, "status", "--porcelain", "--", *GATE_SURFACES).splitlines():
        if ln.strip():
            out.append(ln)
    for ln in _git(brain_dir, "ls-files", "-v", "--", *GATE_SURFACES).splitlines():
        if ln[:1] in ("h", "S"):
            out.append(f"{ln[:1]} {ln[2:]} (index flag hides changes)")
    head_blobs = {}
    for ln in _git(brain_dir, "ls-tree", "-r", "HEAD", "--", *GATE_SURFACES).splitlines():
        try:
            meta, path = ln.split("\t", 1)
            head_blobs[path] = meta.split()[2]
        except (ValueError, IndexError):
            continue
    if head_blobs:
        paths = sorted(head_blobs)
        live = _git(brain_dir, "hash-object", "--stdin-paths", inp="\n".join(paths) + "\n").splitlines()
        if len(live) == len(paths):
            for path, blob in zip(paths, live):
                if blob != head_blobs[path]:
                    out.append(f"M {path} (blob differs from HEAD)")
        else:
            out.append("? hash-object could not read every tracked gate file")
    return out


def gate_receipt_ok(gates: str) -> bool:
    if not gates:
        return False
    for r in read_global():
        if r.get("kind") == "gate-liveness" and r.get("ok") and r.get("gates") == gates:
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
    """Whole-token match: '#260', 'PR#260' and '260' name 260, never 26 or 2600."""
    t = re.escape(str(token).lstrip("#"))
    return bool(re.search(rf"(?<![\w]){t}(?![\w])", scope))


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


_AGENT_FILE = re.compile(r"^agent-([A-Za-z0-9]+)\.jsonl$")


def _harness_agent_transcript(path: Path, session_id: str, agent_id: str) -> bool:
    """The file must be where the harness writes subagent transcripts
    (<projects>/<slug>/<session>/subagents/agent-<id>.jsonl), for THIS session
    and THIS agent id, and its entries must carry the harness fields."""
    try:
        rp = path.resolve()
        rel = rp.relative_to(harness_projects_dir().resolve())
    except (ValueError, OSError):
        return False
    parts = rel.parts
    if len(parts) != 4 or parts[2] != "subagents":
        return False
    m = _AGENT_FILE.match(parts[3])
    if not m or (agent_id and m.group(1) != agent_id):
        return False
    if session_id and parts[1] != session_id:
        return False
    try:
        lines = _tail_lines(str(rp))
    except OSError:
        return False
    seen = 0
    for line in lines[-50:]:
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("type") in ("assistant", "user"):
            seen += 1
            if not harness_entry(e):
                return False
    return seen > 0


def qa_pass_for(token: str, session_id: str = "", transcript_path: str = "") -> dict | None:
    """Most recent qa receipt that (1) was written for a QA persona, (2) points
    at a harness-shaped agent transcript of this session and this agent id,
    and (3) whose last assistant text re-parses to PASS with a scope naming
    `token` as a whole token. Every other line is skipped, never trusted."""
    if not token:
        return None
    for r in reversed(read_global()):
        if r.get("kind") != "qa" or r.get("verdict") != "PASS":
            continue
        if not QA_AGENT_TYPE.search(str(r.get("agent_type", ""))):
            continue
        tp = str(r.get("agent_transcript_path") or "")
        if not tp or not _harness_agent_transcript(Path(tp), session_id, str(r.get("agent_id") or "")):
            continue
        verdict, scope = parse_verdict(last_assistant_text(tp))
        if verdict == "PASS" and scope_names(scope, token):
            return r
    return None
