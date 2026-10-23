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
  panel receipt    written by the same reflex when a reviewer ends with the
                   panel block (PANEL-TO / PANEL-ATTACH / PANEL-BODY, then
                   PANEL-VERDICT / PANEL-SHA256). Anchor: the exact transcript
                   entry re-reads to the same verdict, its digest RECOMPUTED
                   from the block equals the stated one, in THIS session, a
                   reviewer persona, inside 120 minutes; the newest decides,
                   and a receipt spent by a send (sent.jsonl) is spent.
  external receipt written by the Bash hook pair r__pretool-bash__external-review.py
                   and r__posttool-bash__external-review.py around one pinned
                   call to another engine's CLI (v11 phase 4, AC-18 to AC-28).
                   Anchor: its tool_use_id is a harness Bash tool_use of THIS
                   session's transcript whose command re-parses to the same
                   engine, model and prompt digest; the stored output re-hashes;
                   the output ENDS on a panel block that recomputes to the
                   digest; the Reviewer_Registry allows the engine and model;
                   the session's arm allows export. It adds a vote, never forms
                   a quorum, and never clears a send (panel_pass_for).
  sent record      written by r__posttool__sent-ledger.py after a message send
                   left (sent.jsonl): channel, recipient, message id, digest,
                   panel receipt id. A trail for a later recall step, not a gate.

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
  ~/.claude/.cache/receipts/global.jsonl         gate-liveness + qa + panel receipts
  ~/.claude/.cache/receipts/sent.jsonl           messages that left (sent-message ledger)

A line is JSON: {"kind": ..., "ts": ISO-8601 UTC, ...fields}.
"""
from __future__ import annotations

import datetime as _dt
import importlib.util
import json
import os
import re
import stat
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


_GATE_MOD = None


def _qa_gate_module():
    global _GATE_MOD
    if _GATE_MOD is None:
        spec = importlib.util.spec_from_file_location("qa_merge_gate", _HERE / "qa-merge-gate.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _GATE_MOD = mod
    return _GATE_MOD


def _qa_gate_helpers():
    """Borrow the command-boundary splitter the merge gate already proved: the
    union of its two readings, so a SEND is found wherever either finds it."""
    mod = _qa_gate_module()
    return mod._split_subcmds, mod._strip_leading


def _peel(sc: str, split=None) -> list:
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
            stack.extend(_raw_split(inner, split))
            continue
        prev = None
        while prev != cur:
            prev = cur
            cur = _WRAPPER.sub("", cur, count=1)
        out.append(cur)
    return out


def _raw_split(command: str, split=None) -> list:
    """Split the text of an `sh -c` with the SAME reader as the outer command,
    so a receipt that must hold under both readings holds at every level."""
    try:
        union, strip = _qa_gate_helpers()
        return [strip(p) for p in (split or union)(command) if p.strip()]
    except Exception:
        return [command]


def subcommands(command: str, split=None) -> list:
    """Sub-commands of a shell string: split on UNQUOTED separators, leading
    env/redirect/grouping removed, wrappers peeled, `sh -c` expanded. The RAW
    (unstripped) form of each is returned too, so an assignment such as
    `S=~/.claude/scripts/wa-soporte.sh && $S ...` keeps its value visible as a
    token (QA cycle 4: the strip peeled it only after `;`, not after `&&`)."""
    out = []
    try:
        union, strip = _qa_gate_helpers()
        raws = [pp for pp in (split or union)(str(command or "")) if pp.strip()]
    except Exception:
        raws = [str(command or "")]
    for raw in raws:
        try:
            _, strip = _qa_gate_helpers()
            stripped = strip(raw)
        except Exception:
            stripped = raw
        out.extend(_peel(stripped, split))
        if raw.strip() != stripped.strip():
            out.append(raw.strip())
    return out


def words_after(toks: list, i: int, n: int = 2) -> list:
    """The next `n` NON-flag tokens after position i: a flag (`-x`, `--long`)
    is skipped together with its value when it carries no `=` (so
    `gh release --repo x/y create v1` still reads as release create)."""
    out, j = [], i + 1
    while j < len(toks) and len(out) < n:
        t = toks[j]
        if t.startswith("-"):
            j += 1 if ("=" in t or len(t) <= 2 and t in ("-y", "-q", "-v", "-f")) else 2
            continue
        out.append(t)
        j += 1
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
    is not the script name (QA cycle 3). A seek is a RECEIPT, so it must hold
    under both of the merge gate's readings: the union that finds more sends
    would otherwise also find more seeks, and a looser receipt is a weaker gate."""
    try:
        mod = _qa_gate_module()
        readers = (mod._split_bash, mod._split_master)
    except Exception:
        return _seek_in(subcommands(str(command or "")))
    return all(_seek_in(subcommands(str(command or ""), r)) for r in readers)


def _seek_in(subs: list) -> bool:
    for sc in subs:
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


def _mirror_to_journal(pid: str, record: dict) -> None:
    """v8 Phase 4: copy this receipt's IDENTITY into the process journal.

    {kind, ts, tool_use_id, sha256(record)} and nothing else. The receipt itself
    stays here, in the ledger; the journal gets only enough to say "a receipt of
    this kind existed at this point in the run", so `octo replay` can show the
    seeks next to the calls and the refusals without the journal becoming a
    second copy of the ledger.

    FAIL-OPEN, and it matters: this runs inside a PostToolUse reflex. A journal
    error must never cost the ledger its write, which is why the mirror is the
    LAST thing the writer does and swallows everything. kernel_proc is loaded by
    path, so an absent kernel (a fresh clone, an older brain) is a no-op.
    """
    try:
        if not pid:
            return
        import importlib.util
        path = str(Path(__file__).resolve().parent / "kernel_proc.py")
        spec = importlib.util.spec_from_file_location("_kernel_proc_receipt", path)
        kp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(kp)
        kp.journal_receipt(pid, record.get("kind"), record.get("tool_use_id"),
                           record, record.get("ts"))
    except Exception:
        return


def append_session(session_id: str, record: dict) -> None:
    _append(session_path(session_id), record)
    # The LEDGER is keyed by session; the JOURNAL is keyed by process. A seek
    # made inside a subagent belongs to that subagent, so the mirror resolves
    # agent_id first and falls back to the session, the same order
    # kernel_proc.resolve_pid uses for every other kernel writer.
    _mirror_to_journal(str(record.get("agent_id") or session_id or ""), record)


def append_global(record: dict) -> None:
    _append(global_path(), record)
    # A global receipt belongs to a process only when it names one. The QA
    # receipt does (agent_id, and its session as the fallback); the doctor's
    # gate-liveness receipt names neither, and a receipt that belongs to no
    # process is not mirrored rather than guessed into someone's journal.
    _mirror_to_journal(str(record.get("agent_id") or record.get("session_id") or ""),
                       record)


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
            # A sidechain entry is a subagent's prompt, written by the parent
            # model: it is never the operator's own turn (hatches, send asks).
            human = entry if harness_entry(entry) and not entry.get("isSidechain") else None
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


_QA_HEAD = re.compile(r"QA-HEAD\s*:\s*(\S+)", re.IGNORECASE)
_SHA40 = re.compile(r"[0-9a-fA-F]{40}")


def parse_qa_head(text: str) -> str:
    """The commit a QA reviewer declares it reviewed: the LAST `QA-HEAD:` line,
    lower-cased, and only when it is a full 40-digit commit. A malformed last
    line yields "" rather than falling back to an earlier one, so a quoted line
    earlier in the report can never stand in for the real declaration."""
    if not text:
        return ""
    hits = list(_QA_HEAD.finditer(text))
    if not hits:
        return ""
    sha = hits[-1].group(1).strip().rstrip(".,;")
    return sha.lower() if _SHA40.fullmatch(sha) else ""


_CONVERGE_VERDICT = re.compile(r"CONVERGE-VERDICT\s*:\s*(CONVERGED|GAPS)\b", re.IGNORECASE)
_CONVERGE_SCOPE = re.compile(r"CONVERGE-SCOPE\s*:\s*(\S+)", re.IGNORECASE)


def parse_converge(text: str) -> tuple:
    """(verdict, scope) from a converge pass's final report (v9): the LAST
    occurrence of each, like parse_verdict, so a protocol line quoted earlier in
    the report cannot stand in for the verdict at its end. The scope is a spec
    directory, normalised with no leading ./ and no trailing slash. ("", "")
    when absent."""
    if not text:
        return "", ""
    vms = list(_CONVERGE_VERDICT.finditer(text))
    sms = list(_CONVERGE_SCOPE.finditer(text))
    verdict = vms[-1].group(1).upper() if vms else ""
    scope = normalize_spec_dir(sms[-1].group(1).strip("`'\"")) if sms else ""
    return verdict, scope


def normalize_spec_dir(path: str) -> str:
    p = str(path or "").strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p.rstrip("/")


def converge_latest_for(spec_dir: str, session_id: str = "") -> dict | None:
    """Most recent anchored `converge` receipt for `spec_dir`, whatever its
    verdict: written for a verifier persona, pointing at a harness-shaped agent
    transcript, and whose transcript re-parses to the same verdict and to this
    exact scope. A prefix match would let one spec's verdict cover another's.
    `session_id` empty means any session: the push gate runs outside one.

    A row that names its transcript entry (`entry_uuid`, written by the reflex
    since docs/specs/202610012100-qa-receipt-bound-to-head) is re-read from
    that exact entry over the whole transcript, so a resumed verifier's later
    reply cannot change what the receipt says and a verdict beyond the 256 KB
    tail stays readable. An anchored CONVERGED stands only when its run ends
    on a report that also says CONVERGED for this spec and no later run says
    GAPS for it or for no scope (the hook that records receipts fails open). A row with no
    anchor keeps the tail read. The newest entry timestamp decides, never the
    ledger order; on an equal timestamp, or an unreadable one, GAPS wins."""
    want = normalize_spec_dir(spec_dir)
    if not want:
        return None
    cands = []
    for r in read_global():
        if r.get("kind") != "converge" or r.get("verdict") not in ("CONVERGED", "GAPS"):
            continue
        if normalize_spec_dir(r.get("scope", "")) != want:
            continue
        if not QA_AGENT_TYPE.search(str(r.get("agent_type", ""))):
            continue
        tp = str(r.get("agent_transcript_path") or "")
        if not tp or not _harness_agent_transcript(Path(tp), session_id, str(r.get("agent_id") or "")):
            continue
        uuid = str(r.get("entry_uuid") or "")
        if uuid:
            got = report_at(tp, uuid)
            if got is None:
                continue
            report, verdict_ts = got
        else:
            report, verdict_ts = last_assistant_report(tp)
        verdict, scope = parse_converge(report)
        if verdict != r.get("verdict") or scope != want:
            continue
        key = _ts_key(verdict_ts)
        if key is None:
            if verdict != "GAPS":
                continue
            key = _NEVER_OLDER  # an unreadable time cannot drop a GAPS
        cands.append((key, verdict == "GAPS", r, tp, uuid, verdict_ts))
    # Newest first, GAPS first on a tie; only a candidate that could win pays
    # for the whole-transcript check.
    cands.sort(key=lambda c: (c[0], c[1]), reverse=True)
    same = lambda rep_: parse_converge(rep_) == ("CONVERGED", want)
    revokes = lambda rep_: (parse_converge(rep_)[0] == "GAPS"
                            and parse_converge(rep_)[1] in (want, ""))
    for key, is_gaps, r, tp, uuid, verdict_ts in cands:
        if not is_gaps and uuid and not _anchor_stands(tp, uuid, same, revokes):
            continue
        return dict(r, verdict_ts=verdict_ts)
    return None


def converge_pass_for(spec_dir: str, session_id: str = "") -> dict | None:
    """The latest anchored converge receipt for `spec_dir`, only when it says
    CONVERGED. A CONVERGED followed by a later GAPS is stale, not a pass."""
    r = converge_latest_for(spec_dir, session_id)
    return r if r and r.get("verdict") == "CONVERGED" else None


def scope_names(scope: str, token: str) -> bool:
    """Whole-token match: '#260', 'PR#260' and '260' name 260, never 26 or 2600."""
    t = re.escape(str(token).lstrip("#"))
    return bool(re.search(rf"(?<![\w]){t}(?![\w])", scope))


# A subagent can end by calling this tool instead of writing a final text block:
# its `message` input IS the report the parent receives. Measured 2026-09-30: a
# Reality Checker whose transcript ended thinking -> SubagentHandback -> result
# carried its verdict only there, so reading text blocks alone found no verdict,
# wrote no receipt, and the merge gate refused a PASS it could not see.
HANDBACK_TOOL = "SubagentHandback"


def _refused_handbacks(entry: dict) -> set:
    """tool_use ids of SubagentHandback calls the harness answered with
    `success: false`. Read from `toolUseResult` on a harness-written tool
    result; measured over 157 real handbacks, 152 carried true and 5 false
    ("not active for this agent", "already delivered")."""
    if entry.get("type") != "user" or not harness_entry(entry):
        return set()
    result = entry.get("toolUseResult")
    if not isinstance(result, dict) or result.get("success") is not False:
        return set()
    content = (entry.get("message") or {}).get("content") or []
    return {b.get("tool_use_id") for b in content
            if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id")}


def _delivered_results(entry: dict) -> set:
    """tool_use ids the harness answered with `success: true`: evidence that
    a SubagentHandback was delivered, as opposed to merely not refused (an
    error string or a missing result is not a delivery)."""
    if entry.get("type") != "user" or not harness_entry(entry):
        return set()
    result = entry.get("toolUseResult")
    if not isinstance(result, dict) or result.get("success") is not True:
        return set()
    content = (entry.get("message") or {}).get("content") or []
    return {b.get("tool_use_id") for b in content
            if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id")}


def _entry_report(entry: dict, refused: set):
    """The report one assistant entry carries, or None: a delivered
    SubagentHandback message wins over text blocks in the same entry."""
    content = (entry.get("message") or {}).get("content") or []
    if isinstance(content, str):
        return content
    handbacks = [b.get("input", {}).get("message") for b in content
                 if isinstance(b, dict) and b.get("type") == "tool_use"
                 and b.get("name") == HANDBACK_TOOL
                 and b.get("id") not in refused
                 and isinstance(b.get("input"), dict)
                 and isinstance(b["input"].get("message"), str)]
    if handbacks:
        return handbacks[-1]
    texts = [b.get("text", "") for b in content
             if isinstance(b, dict) and b.get("type") == "text"]
    if texts:
        return "\n".join(texts)
    return None


def last_assistant_entry(transcript_path: str) -> tuple:
    """The final report of a transcript: the newest assistant entry carrying
    either text blocks or a delivered SubagentHandback message. When one entry
    has both, the handback wins, because it is what the parent was handed.

    A handback the harness REFUSED never reached the parent, so it is not a
    report: it is skipped and the walk goes on to older entries. A handback
    with no result written yet still counts, because SubagentStop can read the
    transcript before the harness appends the result, and a refusal is always
    written at once with the call it refuses.

    Returns (report, timestamp, uuid) of the entry that carries it. Timestamp
    and uuid are harness-written: a consumer measuring freshness reads them
    here rather than the ledger line, which anyone can append with any `ts`,
    and a receipt anchors to the uuid so a later reply of a resumed agent
    cannot change what an earlier receipt says."""
    try:
        lines = _tail_lines(transcript_path)
    except OSError:
        return "", "", ""
    refused: set = set()
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        refused |= _refused_handbacks(entry)
        if entry.get("type") != "assistant":
            continue
        report = _entry_report(entry, refused)
        if report is not None:
            return report, str(entry.get("timestamp") or ""), str(entry.get("uuid") or "")
    return "", "", ""


def last_assistant_report(transcript_path: str) -> tuple:
    """(report, timestamp) of the final report; see last_assistant_entry."""
    report, ts, _ = last_assistant_entry(transcript_path)
    return report, ts


def _regular_file(path) -> bool:
    """Only a regular file is ever opened as a transcript: a FIFO or a device
    placed where a transcript belongs would hold the read open until the hook
    is killed, and a killed hook reads as allow."""
    try:
        return stat.S_ISREG(os.stat(path).st_mode)
    except OSError:
        return False


def report_at(transcript_path: str, uuid: str):
    """(report, timestamp) of the exact assistant entry whose own `uuid` field
    is `uuid`, read from the WHOLE transcript, or None.

    The whole file, because a resumed reviewer's earlier verdict often sits far
    from the end (36 of 200 anchored verdicts in real transcripts lay beyond the
    256 KB tail every other reader keeps). The `uuid` FIELD, never a substring:
    the next entry names its parent by the same value in `parentUuid`. When
    several lines carry that uuid (the harness repeats some, identical but for
    `cwd`), they must all yield the same report, or there is no answer."""
    if not uuid or not _regular_file(transcript_path):
        return None
    needle = uuid.encode()
    refused: set = set()
    found = []
    try:
        with open(transcript_path, "rb") as fh:
            for raw in fh:
                if needle not in raw and b"toolUseResult" not in raw:
                    continue
                try:
                    entry = json.loads(raw.decode("utf-8", errors="replace"))
                except json.JSONDecodeError:
                    continue
                if not isinstance(entry, dict):
                    continue
                refused |= _refused_handbacks(entry)
                if entry.get("type") == "assistant" and entry.get("uuid") == uuid \
                        and harness_entry(entry):
                    found.append(entry)
    except OSError:
        return None
    if not found:
        return None
    reports = {_entry_report(e, refused) for e in found}
    if len(reports) != 1 or None in reports:
        return None
    return reports.pop(), str(found[0].get("timestamp") or "")


_INJECTED = ("<system-reminder>", "[SYSTEM NOTIFICATION")
# How the harness writes a SendMessage resume: an isMeta user entry.
_RESUME = ("The coordinator sent a message", "Another Claude session sent a message",
           "The user sent a new message")


def _is_resume(entry: dict) -> bool:
    content = (entry.get("message") or {}).get("content")
    return (entry.get("type") == "user" and isinstance(content, str)
            and content.lstrip().startswith(_RESUME))


def _awaits_tool(entry, refused: set = frozenset()) -> bool:
    """True when an assistant entry left a tool call pending: the agent was
    mid-work. A SubagentHandback that delivered the report ends the turn; one
    the harness refused does not (the agent keeps working after it)."""
    blocks = ((entry or {}).get("message") or {}).get("content") or []
    return isinstance(blocks, list) and any(
        isinstance(b, dict) and b.get("type") == "tool_use"
        and (b.get("name") != HANDBACK_TOOL or b.get("id") in refused)
        for b in blocks)


def _message_id(entry) -> str:
    return str(((entry or {}).get("message") or {}).get("id") or "")


def _is_prompt(entry: dict) -> bool:
    """A user entry that starts a new run (a prompt or a resume). Not one the
    harness injects mid-run (`isMeta`: notifications, skill loads, reminders)
    and not one that carries a tool result back to the agent, even when it
    also holds text ("Tool loaded.")."""
    if entry.get("type") != "user" or entry.get("isMeta"):
        return False
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return not content.lstrip().startswith(_INJECTED)
    if not isinstance(content, list):
        return False
    if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
        return False
    texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
    return bool(texts) and not all(t.lstrip().startswith(_INJECTED) for t in texts)


def _anchor_stands(transcript_path: str, uuid: str, same, revokes) -> bool:
    """True when the run that holds the anchored assistant entry ENDS on a
    report that says the same thing (`same(final_report)`) and no report in a
    later run satisfies `revokes(report)`. A run ends at a real prompt, or at
    a SendMessage resume that follows an ended turn (no tool call pending, no
    refused handback, and the next assistant entry starts a new message).

    Residual, stated: an agent killed right after a mid-run text entry (or a
    thinking-only tail of the same message), and then resumed or never
    resumed, leaves that entry as its run's last report. It cannot be told
    apart from an ordinary turn that ended on text (48 real resumes follow
    exactly that shape), so such a quote reads as the run's final report.

    A receipt is recorded by a hook that fails open, so a resumed reviewer's
    later NEEDS-WORK or GAPS may never reach the ledger; reading it from the
    transcript keeps a passing verdict from outliving its own revocation. And
    the ledger is writable, so a hand-written row naming a mid-run entry that
    merely quotes the protocol lines stands only if the run's own final
    report carries the same verdict."""
    if not uuid or not _regular_file(transcript_path):
        return False
    entries, refused, ok_ids = [], set(), set()
    try:
        with open(transcript_path, "rb") as fh:
            for raw in fh:
                try:
                    entry = json.loads(raw.decode("utf-8", errors="replace"))
                except json.JSONDecodeError:
                    continue
                if not isinstance(entry, dict) or not harness_entry(entry):
                    continue
                refused |= _refused_handbacks(entry)
                ok_ids |= _delivered_results(entry)
                if entry.get("type") in ("assistant", "user"):
                    entries.append(entry)
    except OSError:
        return False
    at = next((i for i, e in enumerate(entries)
               if e.get("type") == "assistant" and e.get("uuid") == uuid), None)
    if at is None:
        return False
    tail = entries[at:]
    # The message id of the next assistant entry after each position, so a
    # resume followed by the SAME message (the turn went on) is not a boundary.
    next_mid, nxt = [""] * len(tail), ""
    for i in range(len(tail) - 1, -1, -1):
        next_mid[i] = nxt
        if tail[i].get("type") == "assistant":
            nxt = _message_id(tail[i])
    final, in_run, last_asst, delivered = None, True, None, False
    for i, e in enumerate(tail):
        # A run ends at a real prompt, or at a resume that arrives after the
        # agent ended its turn; one that arrives mid tool loop ("while you
        # were working") is not an end (205 of 212 real resumes are ends). A
        # refused handback leaves the turn open, unless a handback the harness
        # confirmed (`success: true`) already delivered the run's report.
        boundary = _is_prompt(e) or (
            _is_resume(e) and last_asst is not None
            and not _awaits_tool(last_asst, frozenset() if delivered else refused)
            and not (_message_id(last_asst) and next_mid[i] == _message_id(last_asst)))
        if e.get("type") == "assistant":
            last_asst = e
            blocks = (e.get("message") or {}).get("content") or []
            if isinstance(blocks, list) and any(
                    isinstance(b, dict) and b.get("type") == "tool_use"
                    and b.get("name") == HANDBACK_TOOL and b.get("id") in ok_ids
                    and b.get("id") not in refused
                    for b in blocks):
                delivered = True  # confirmed by the harness and never refused
        if boundary:
            delivered = False
            if in_run and (final is None or not same(final)):
                return False  # the run did not end on this verdict
            in_run = False
            continue
        if e.get("type") != "assistant":
            continue
        report = _entry_report(e, refused)
        if report is None:
            continue
        if in_run:
            final = report
        elif revokes(report):
            return False
    if in_run and (final is None or not same(final)):
        return False
    return True


def last_assistant_text(transcript_path: str) -> str:
    return last_assistant_report(transcript_path)[0]


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
    if not _regular_file(rp):
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


def _ts_key(ts: str):
    try:
        t = _dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=_dt.timezone.utc)
    except ValueError:
        return None


_NEVER_OLDER = _dt.datetime.max.replace(tzinfo=_dt.timezone.utc)


def _revokes_pass(report: str, token: str, head: str) -> bool:
    """A later report that revokes a PASS for this pull request at this
    commit: FAIL or NEEDS-WORK naming the PR or no scope at all, at the same
    commit or none."""
    verdict, scope = parse_verdict(report)
    if verdict not in ("FAIL", "NEEDS-WORK"):
        return False
    if scope and not scope_names(scope, token):
        return False  # a scope-less revocation in the same transcript revokes
    return parse_qa_head(report) in (head, "")


def qa_latest_for(token: str, head: str) -> dict | None:
    """The qa receipt that decides pull request `token` at commit `head`,
    whatever its verdict; None when no receipt names both.

    Ledger rows are narrowed by their own kind and scope only, so the cost is
    one pull request's receipts and no transcript of another is opened. Each
    remaining row must be a verifier persona's, point at a harness-shaped,
    regular-file agent transcript (any session), and name the transcript entry
    it was recorded from (`entry_uuid`). That exact entry is re-read: its
    verdict, scope and commit must equal the row's, name this pull request and
    this commit. A FAIL or NEEDS-WORK whose report carries no valid commit
    names every commit of the pull request. A row without an anchor, or whose
    entry is gone or now says something else, is skipped. Of what is left, the receipt whose entry the
    harness wrote last decides, never the ledger order, which anyone can
    re-append to."""
    head = str(head or "").lower()
    if not token or not _SHA40.fullmatch(head):
        return None
    cands = []
    for r in read_global():
        if r.get("kind") != "qa" or r.get("verdict") not in ("PASS", "FAIL", "NEEDS-WORK"):
            continue
        if not scope_names(str(r.get("scope") or ""), token):
            continue
        if not QA_AGENT_TYPE.search(str(r.get("agent_type", ""))):
            continue
        tp, uuid = str(r.get("agent_transcript_path") or ""), str(r.get("entry_uuid") or "")
        if not tp or not uuid:
            continue
        if not _harness_agent_transcript(Path(tp), "", str(r.get("agent_id") or "")):
            continue
        got = report_at(tp, uuid)
        if got is None:
            continue
        report, ts = got
        verdict, scope = parse_verdict(report)
        if verdict != r.get("verdict") or scope != str(r.get("scope") or ""):
            continue
        report_head = parse_qa_head(report)
        if str(r.get("head") or "") != report_head:
            continue
        # A revocation that names no valid commit revokes the whole pull
        # request: a reviewer who forgot or shortened QA-HEAD must not leave
        # an earlier PASS standing. A PASS always needs the exact commit.
        if report_head != head and not (report_head == "" and verdict != "PASS"):
            continue
        if not scope_names(scope, token):
            continue
        key = _ts_key(ts)
        if key is None:
            if verdict == "PASS":
                continue
            key = _NEVER_OLDER  # an unreadable time cannot drop a revocation
        cands.append((key, verdict != "PASS", r, tp, uuid, ts, scope))
    cands.sort(key=lambda c: (c[0], c[1]), reverse=True)
    for key, is_revocation, r, tp, uuid, ts, scope in cands:
        if not is_revocation:
            same = lambda rep_, sc=scope: (parse_verdict(rep_) == ("PASS", sc)
                                           and parse_qa_head(rep_) == head)
            if not _anchor_stands(tp, uuid, same, lambda rep_: _revokes_pass(rep_, token, head)):
                continue
        return dict(r, verdict_ts=ts)
    return None


# --------------------------------------------------------------------------
# Panel receipt (FLOW.panel-before-send)
# --------------------------------------------------------------------------
# A reviewer subagent ends its report with
#     PANEL-VERDICT: PASS | NEEDS-WORK
#     PANEL-SHA256: <64 hex>          (panel_digest.py of the reviewed message)
# and r__subagent-stop__qa-receipt.py records a `panel` receipt anchored to the
# harness transcript entry, the same way it records a QA verdict. The
# outward-send gate honours only the receipt that DECIDES that digest.

_PANEL_VERDICT = re.compile(r"PANEL-VERDICT\s*:\s*(PASS|NEEDS[ -]WORK)\b", re.IGNORECASE)
_PANEL_SHA = re.compile(r"PANEL-SHA256\s*:\s*(\S+)", re.IGNORECASE)
_SHA64 = re.compile(r"[0-9a-f]{64}")
# A panel is a reviewer persona: the QA set plus an explicit "panel" type.
PANEL_AGENT_TYPE = re.compile(QA_AGENT_TYPE.pattern + r"|panel", re.IGNORECASE)
PANEL_WINDOW_MINUTES = 120


def panel_recompute(report: str) -> str:
    """The digest recomputed from the reviewer block of a report (the exact
    body, its PANEL-TO recipients and PANEL-ATTACH hashes), "" when the report
    carries no block. A stated PANEL-SHA256 alone binds to nothing: the main
    loop could show the reviewer one text and hand it the digest of another."""
    try:
        import importlib
        pd = importlib.import_module("panel_digest")
        got = pd.recompute_from_report(report)
    except Exception:
        return ""
    return (got or {}).get("digest", "")


def parse_panel(text: str) -> tuple:
    """(verdict, digest) from a reviewer's final report: the LAST occurrence of
    each, so a protocol line quoted earlier cannot stand in for the verdict at
    the end. A malformed last digest yields "" (never an earlier one)."""
    if not text:
        return "", ""
    vms = list(_PANEL_VERDICT.finditer(text))
    sms = list(_PANEL_SHA.finditer(text))
    verdict = vms[-1].group(1).upper().replace(" ", "-") if vms else ""
    sha = sms[-1].group(1).strip().strip("`'\"").rstrip(".,;").lower() if sms else ""
    return verdict, (sha if _SHA64.fullmatch(sha) else "")


def panel_receipts_for(digest: str, session_id: str, now=None,
                       window_minutes: float = PANEL_WINDOW_MINUTES) -> list:
    """Every panel receipt for `digest` in session `session_id` that passes
    validation, deciding first (newest; on an equal time a NEEDS-WORK first).
    Each is the ledger row plus `verdict_ts`, the harness time of its entry.

    A ledger row counts only when it was written for a reviewer persona, points
    at a harness-shaped agent transcript of THIS session and agent id, names the
    transcript entry it came from (`entry_uuid`), and that exact entry re-reads
    to the same verdict and digest. Its time is the entry's harness timestamp,
    never the ledger line's. Rows older than `window_minutes` (or from the
    future) are dropped. Of the rest the newest decides; on an equal or an
    unreadable time a NEEDS-WORK wins. A PASS also has to stand in its own
    transcript: the run must end on the same PASS and no later run of that
    reviewer may say NEEDS-WORK for this digest (the recording hook fails open,
    so a revocation can be missing from the ledger)."""
    want = str(digest or "").lower()
    if not _SHA64.fullmatch(want) or not session_id:
        return []
    now = now or _dt.datetime.now(_dt.timezone.utc)
    cands = []
    for r in read_global():
        if r.get("kind") != "panel" or r.get("verdict") not in ("PASS", "NEEDS-WORK"):
            continue
        if str(r.get("digest") or "").lower() != want:
            continue
        if not PANEL_AGENT_TYPE.search(str(r.get("agent_type", ""))):
            continue
        tp, uuid = str(r.get("agent_transcript_path") or ""), str(r.get("entry_uuid") or "")
        if not tp or not uuid:
            continue
        # A `~` path resolves under THIS process's HOME (fixtures seed it that
        # way); it still has to land in the harness projects dir below.
        tp = os.path.expanduser(tp)
        if not _harness_agent_transcript(Path(tp), session_id, str(r.get("agent_id") or "")):
            continue
        got = report_at(tp, uuid)
        if got is None:
            continue
        report, ts = got
        verdict, sha = parse_panel(report)
        if verdict != r.get("verdict") or sha != want or panel_recompute(report) != want:
            continue
        key = _ts_key(ts)
        if key is None:
            if verdict == "PASS":
                continue
            key = _NEVER_OLDER
        else:
            age = (now - key).total_seconds() / 60.0
            if age < 0 or age > window_minutes:
                continue
        cands.append((key, verdict != "PASS", r, tp, uuid, ts))
    seen_ext, ledger = set(), read_global()
    for r in ledger:
        if r.get("kind") != "external" or r.get("state") != "complete":
            continue
        if str(r.get("panel_digest") or "").lower() != want:
            continue
        tid = str(r.get("tool_use_id") or "")
        if not tid or tid in seen_ext:
            continue
        seen_ext.add(tid)
        try:
            got = external_panel_view(r, session_id, want, now, window_minutes, ledger)
        except Exception:
            got = None
        if got is None:
            continue
        cands.append((_ts_key(got["verdict_ts"]), got["verdict"] != "PASS", got, None, None,
                      got["verdict_ts"]))
    cands.sort(key=lambda c: (c[0], c[1]), reverse=True)
    same = lambda rep_: parse_panel(rep_) == ("PASS", want) and panel_recompute(rep_) == want
    revokes = lambda rep_: parse_panel(rep_) == ("NEEDS-WORK", want)
    out = []
    for key, is_revocation, r, tp, uuid, ts in cands:
        if r.get("external"):
            out.append(r)  # validated by external_panel_view; no agent transcript
            continue
        if not is_revocation:
            # A malformed reviewer transcript must not raise out of here for
            # the send gate or the sent ledger: a PASS whose anchor cannot be
            # checked does not stand.
            try:
                stands = _anchor_stands(tp, uuid, same, revokes)
            except Exception:
                stands = False
            if not stands:
                continue
        out.append(dict(r, verdict_ts=ts))
    return out


def panel_latest_for(digest: str, session_id: str, now=None,
                     window_minutes: float = PANEL_WINDOW_MINUTES) -> dict | None:
    """The panel receipt that decides `digest` in session `session_id`,
    whatever its verdict, or None: the first of panel_receipts_for."""
    got = panel_receipts_for(digest, session_id, now, window_minutes)
    return got[0] if got else None


def panel_pass_for(digest: str, session_id: str, now=None) -> dict | None:
    """The deciding panel receipt for `digest`, only when it is a HARNESS
    reviewer's PASS (v11 AC-26). Every external PASS is dropped first; then the
    newest of what remains decides (harness PASS, harness NEEDS-WORK, external
    NEEDS-WORK; a NEEDS-WORK wins an equal or unreadable time, the order
    panel_receipts_for already gives). So an external receipt can revoke a
    send's PASS but never clear one: the send gate and the sent-message ledger
    read only this function."""
    got = [r for r in panel_receipts_for(digest, session_id, now)
           if not (r.get("external") and r.get("verdict") == "PASS")]
    r = got[0] if got else None
    return r if r and r.get("verdict") == "PASS" and not r.get("external") else None


# --------------------------------------------------------------------------
# External receipt (v11 phase 4: a review on another engine)
# --------------------------------------------------------------------------
# Written by the Bash hook pair around one Accepted_Review_Call
# (scripts/external_review.py). The ledger line is a pointer; every field that
# matters is re-derived here from things the line does not own: the stored
# output's bytes, the session transcript's harness Bash entry and its tool
# result, the Reviewer_Registry and the arm's Export_Policy.

EXTERNAL_MAX_OUTPUT = 4 << 20


def _external_lib():
    """scripts/external_review.py, the parser and registry reader the hook
    pair uses, loaded from beside this file whatever sys.path holds."""
    import sys
    mod = sys.modules.get("external_review")
    if mod is None:
        spec = importlib.util.spec_from_file_location("external_review",
                                                      _HERE / "external_review.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["external_review"] = mod
        try:
            spec.loader.exec_module(mod)
        except Exception:
            sys.modules.pop("external_review", None)
            raise
    return mod


def _session_transcript_ok(tp: str, session_id: str) -> bool:
    """A transcript of THIS session, where the harness writes one: the main
    loop's <projects>/<slug>/<session_id>.jsonl, or a subagent's
    <projects>/<slug>/<session_id>/subagents/agent-<id>.jsonl (a reviewer
    subagent runs the external call itself, AC-28). A regular file."""
    try:
        rp = Path(tp).resolve()
        rel = rp.relative_to(harness_projects_dir().resolve())
    except (ValueError, OSError):
        return False
    parts = rel.parts
    main = len(parts) == 2 and parts[1] == f"{session_id}.jsonl"
    sub = (len(parts) == 4 and parts[1] == session_id and parts[2] == "subagents"
           and bool(_AGENT_FILE.match(parts[3])))
    return (main or sub) and _regular_file(rp)


def _external_transcripts(r: dict, session_id: str) -> list:
    """Where the Bash tool_use of an external row can live: the transcript the
    hook payload named and, when the call came from a subagent, that agent's
    own transcript beside it."""
    tp = os.path.expanduser(str(r.get("transcript_path") or ""))
    out = [tp] if tp else []
    agent = str(r.get("agent_id") or "")
    if tp and agent and re.fullmatch(r"[A-Za-z0-9]+", agent):
        out.append(str(Path(tp).parent / session_id / "subagents" / f"agent-{agent}.jsonl"))
    return out


def bash_tool_use(tp: str, tool_use_id: str, session_id: str):
    """(command, tool_result timestamp) of the harness Bash tool_use with this
    id in the session transcript, or None. Every line that carries the id must
    agree on the command, and the harness must have written its result."""
    if not tool_use_id or not _session_transcript_ok(tp, session_id):
        return None
    needle = tool_use_id.encode()
    commands, result_ts = set(), ""
    try:
        with open(tp, "rb") as fh:
            for raw in fh:
                if needle not in raw:
                    continue
                try:
                    entry = json.loads(raw.decode("utf-8", errors="replace"))
                except json.JSONDecodeError:
                    continue
                if not harness_entry(entry) or entry.get("sessionId") != session_id:
                    continue
                content = (entry.get("message") or {}).get("content") or []
                if not isinstance(content, list):
                    continue
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    if entry.get("type") == "assistant" and b.get("type") == "tool_use" \
                            and b.get("id") == tool_use_id:
                        inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                        cmd = inp.get("command")
                        commands.add(cmd if b.get("name") == "Bash" and isinstance(cmd, str)
                                     else None)
                    elif entry.get("type") == "user" and b.get("type") == "tool_result" \
                            and b.get("tool_use_id") == tool_use_id:
                        result_ts = str(entry.get("timestamp") or "")
    except OSError:
        return None
    if len(commands) != 1 or None in commands or not result_ts:
        return None
    return commands.pop(), result_ts


def session_arm_allows(cwd: str, project_dir: str = "") -> bool:
    """AC-27 through the Export_Guard's own Arm_Resolution: True when neither
    the call's cwd nor the session's CLAUDE_PROJECT_DIR resolves to an arm (a
    brain session, or directories under no registered arm), or when the
    guard's decide() accepts both together, which refuses a cwd and project
    dir in different arms or a cwd moved out of a deny arm (`cd /tmp`).
    Anything unreadable is False."""
    try:
        spec = importlib.util.spec_from_file_location(
            "_export_guard_for_ledger", _HERE / "g__wrap__export-guard.py")
        g = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(g)
        home = os.path.expanduser("~")
        real = g._real_dir(os.path.expanduser(str(cwd or "")), "cwd")
        proj = None
        if project_dir:
            proj = g._real_dir(os.path.expanduser(str(project_dir)), "CLAUDE_PROJECT_DIR")
        brains = g.brain_paths(home)
        roots = g.load_arm_roots(home, brains)
        dirs = [d for d in (real, proj) if d]
        in_arm = [d for d in dirs if not any(g._contains(b, d) for b in brains)
                  and any(g._contains(r, d) for _n, r in roots)]
        if not in_arm:
            return True
        g.decide(json.dumps({"cwd": real}).encode(), home=home, project_dir=proj)
        return True
    except Exception:
        return False


def external_checked(r: dict, session_id: str, now=None,
                     window_minutes: float = PANEL_WINDOW_MINUTES, rows=None):
    """The AC-24 checks of one complete external row OTHER than the digest
    match, plus AC-27. Returns {output, verdict_ts, engine, requested_model,
    tool_use_id} or None."""
    if r.get("kind") != "external" or r.get("state") != "complete":
        return None
    tid, sid = str(r.get("tool_use_id") or ""), str(r.get("session_id") or "")
    if not tid or not session_id or sid != session_id:
        return None
    code = r.get("exit_code")
    if not isinstance(code, int) or isinstance(code, bool) or code != 0:
        return None
    engine, model = r.get("engine"), r.get("requested_model")
    psha = str(r.get("prompt_sha256") or "")
    if not isinstance(model, str) or not model or model == "unknown" \
            or not _SHA64.fullmatch(psha):
        return None
    er = _external_lib()
    if engine not in er.ENGINES or not er.reviewer_allowed(engine, model):
        return None
    pend = [p for p in (read_global() if rows is None else rows) if p.get("kind") == "external"
            and p.get("state") == "pending" and p.get("tool_use_id") == tid
            and p.get("session_id") == sid]
    if not pend or pend[-1].get("pre_problems") != [] or any(
            pend[-1].get(k) != r.get(k) for k in ("engine", "requested_model", "prompt_sha256",
                                                   "interpreter", "script", "cwd",
                                                   "project_dir", "transcript_path",
                                                   "agent_id")):
        return None
    out_path = receipts_dir() / "external" / f"{_safe(tid)}.out"
    if not _regular_file(out_path):
        return None
    try:
        if out_path.stat().st_size > EXTERNAL_MAX_OUTPUT:
            return None
        raw = out_path.read_bytes()
    except OSError:
        return None
    if er.sha256_bytes(raw) != r.get("output_sha256"):
        return None
    got = None
    for tp in _external_transcripts(r, session_id):
        got = bash_tool_use(tp, tid, session_id)
        if got is not None:
            break
    if got is None:
        return None
    command, ts = got
    call, _why = er.parse_call(command, {engine: (r.get("interpreter"), r.get("script"))})
    if not call or call["prompt_sha256"] != psha or call["requested_model"] != model:
        return None
    key = _ts_key(ts)
    if key is None:
        return None
    now = now or _dt.datetime.now(_dt.timezone.utc)
    age = (now - key).total_seconds() / 60.0
    if age < 0 or age > window_minutes:
        return None
    if not session_arm_allows(str(r.get("cwd") or ""), str(r.get("project_dir") or "")):
        return None
    return {"output": raw.decode("utf-8", errors="replace"), "verdict_ts": ts,
            "engine": engine, "requested_model": model, "tool_use_id": tid}


def _ends_on_panel(output: str) -> bool:
    """Nothing but whitespace after the output's last PANEL-SHA256 line."""
    ms = list(_PANEL_SHA.finditer(output or ""))
    return bool(ms) and not output[ms[-1].end():].strip()


def external_panel_view(r: dict, session_id: str, want: str, now=None,
                        window_minutes: float = PANEL_WINDOW_MINUTES, rows=None):
    """A complete external row as a panel reviewer for digest `want` (AC-24),
    or None. Its reviewer id is its tool_use_id. `rows` is the ledger already
    read by the caller, so one Stop reads it once."""
    v = external_checked(r, session_id, now, window_minutes, rows)
    if v is None:
        return None
    out = v["output"]
    verdict, sha = parse_panel(out)
    if verdict not in ("PASS", "NEEDS-WORK") or sha != want or verdict != r.get("panel_verdict"):
        return None
    if not _ends_on_panel(out) or panel_recompute(out) != want:
        return None
    return {"kind": "external", "external": True, "verdict": verdict, "digest": want,
            "agent_id": v["tool_use_id"], "agent_type": f"external:{v['engine']}",
            "engine": v["engine"], "requested_model": v["requested_model"],
            "tool_use_id": v["tool_use_id"], "session_id": session_id,
            "verdict_ts": v["verdict_ts"]}


_REVIEW_EXTERNAL = re.compile(r"REVIEW-EXTERNAL\s*:\s*(\S+)", re.IGNORECASE)


def parse_review_external(text: str) -> list:
    """Every tool_use_id a reviewer's report names on a `REVIEW-EXTERNAL:` line."""
    out = []
    for m in _REVIEW_EXTERNAL.finditer(text or ""):
        tid = m.group(1).strip("`'\".,;")
        if tid and tid not in out:
            out.append(tid)
    return out


def external_reviewers_for(report: str, session_id: str, kind: str, verdict: str,
                           now=None) -> list:
    """AC-28: [{tool_use_id, engine, requested_model}] for each REVIEW-EXTERNAL
    line of `report` naming a complete external receipt of this session that
    passes every AC-24 check other than the digest match and AC-27, and whose
    stored output ends on the same verdict as the report (`kind` qa or
    panel). The harness receipt that carries this list is unchanged."""
    out, ledger = [], read_global()
    for tid in parse_review_external(report):
        rows = [r for r in ledger if r.get("kind") == "external"
                and r.get("state") == "complete" and r.get("tool_use_id") == tid]
        for r in reversed(rows):
            v = external_checked(r, session_id, now, rows=ledger)
            if v is None:
                continue
            said = (parse_verdict(v["output"])[0] if kind == "qa"
                    else parse_panel(v["output"])[0] if kind == "panel" else "")
            if said and said == verdict:
                out.append({"tool_use_id": tid, "engine": v["engine"],
                            "requested_model": v["requested_model"]})
            break
    return out


def panel_receipt_consumed(entry_uuid: str) -> bool:
    """True when a sent record already spent this panel receipt: a receipt
    authorises ONE send. A send whose channel reported failure (ok false) did
    not leave, so it does not spend the receipt."""
    if not entry_uuid:
        return False
    return any(rec.get("panel_receipt") == entry_uuid and rec.get("ok") is not False
               for rec in read_sent())


# --------------------------------------------------------------------------
# Sent-message ledger (written after a send; read by a later recall step)
# --------------------------------------------------------------------------

def sent_path() -> Path:
    return receipts_dir() / "sent.jsonl"


def append_sent(record: dict) -> None:
    _append(sent_path(), dict(record, kind="sent"))


def read_sent() -> list:
    return _read(sent_path())


# --------------------------------------------------------------------------
# Selftest: forged external receipts are bounded (v11 AC-38)
# --------------------------------------------------------------------------

def _selftest_external() -> int:
    """Seed FORGED complete external receipts (written by hand, every anchor
    consistent, the strongest forgery the residuals allow: a swap between
    check and exec, a shell environment no hook sees) and show, through
    panel_pass_for and through the Reply_Panel_Gate itself, that a forged
    PASS never meets a quorum without a harness PASS (AC-25) and never makes
    panel_pass_for return a PASS (AC-26), and that a forged NEEDS-WORK only
    revokes. Exit 0 when every case holds."""
    import shutil
    import subprocess
    import sys
    import tempfile
    sys.path.insert(0, str(_HERE))
    import panel_digest
    import panel_fixture_seed as pfs

    sourced = ("The fix is in and the suite passes.\n\n"
               "Provenance: Basis: scripts/tests run log \u00b7 Engine: main loop")
    selfish = ("The fix is in and the suite passes.\n\n"
               "Provenance: Basis: own reasoning \u00b7 Engine: main loop")
    t = lambda m: f"2026-10-14T10:0{m}:00.000Z"
    # (name, reply text, [(who, verdict, minute)], panel_pass_for wants, gate exit)
    cases = [
        ("forged-pass-alone-sourced", sourced, [("ext", "PASS", 4)], None, 2),
        ("three-forged-passes-self", selfish,
         [("ext", "PASS", 2), ("ext", "PASS", 3), ("ext", "PASS", 4)], None, 2),
        ("forged-needs-work-revokes", sourced, [("h", "PASS", 2), ("ext", "NEEDS-WORK", 4)],
         None, 2),
        ("forged-needs-work-older-cannot-revoke", sourced,
         [("ext", "NEEDS-WORK", 1), ("h", "PASS", 3)], "h", 0),
        ("forged-pass-adds-one-vote-beside-harness", sourced,
         [("h", "PASS", 2), ("ext", "PASS", 4)], "h", 0),
        ("forged-passes-complete-self-quorum-beside-harness", selfish,
         [("h", "PASS", 2), ("ext", "PASS", 3), ("ext", "PASS", 4)], "h", 0),
        ("forged-pass-after-revoked-harness-pass-sourced", sourced,
         [("h", "PASS", 2), ("h", "NEEDS-WORK", 3), ("ext", "PASS", 4)], None, 2),
        ("three-forged-passes-after-revoked-harness-pass-self", selfish,
         [("h", "PASS", 1), ("h", "NEEDS-WORK", 2), ("ext", "PASS", 3), ("ext", "PASS", 4),
          ("ext", "PASS", 4)], None, 2),
    ]
    fails = []
    # os.path.expanduser reads USERPROFILE on Windows and ignores HOME: both move.
    old_home = {k: os.environ.get(k) for k in ("HOME", "USERPROFILE")}
    for name, text, seeds, want_pass, want_exit in cases:
        sb = Path(tempfile.mkdtemp(prefix="ledger-external-selftest-"))
        session = f"fx-ledger-{name}"
        try:
            os.environ["HOME"] = os.environ["USERPROFILE"] = str(sb)
            msg = panel_digest.Message(text, [], ["operator"])
            for i, (who, verdict, minute) in enumerate(seeds):
                if who == "ext":
                    pfs.seed_external_receipt(sb, session, msg, verdict, t(minute),
                                              f"toolu_forged_{i}")
                else:
                    pfs.seed_receipt(sb, session, msg, verdict, t(minute), f"harness{i}")
            now = _dt.datetime(2026, 10, 14, 10, 6, tzinfo=_dt.timezone.utc)
            got = panel_pass_for(msg.digest, session, now)
            if want_pass is None and got is not None:
                fails.append(f"{name}: panel_pass_for returned {got.get('agent_id')}")
            if want_pass == "h" and (got is None or got.get("external")):
                fails.append(f"{name}: panel_pass_for did not return the harness PASS")
            tp = sb / "stop-transcript.jsonl"
            rows = [
                {"type": "user", "message": {"role": "user", "content": "Is the fix in?"},
                 "uuid": "00000000-0000-4000-8000-000000000001", "parentUuid": None,
                 "sessionId": session, "timestamp": "2026-10-14T10:00:00.000Z",
                 "origin": {"kind": "human"}},
                {"type": "assistant", "message": {"role": "assistant",
                                                  "content": [{"type": "text", "text": text}]},
                 "uuid": "00000000-0000-4000-8000-000000000002",
                 "parentUuid": "00000000-0000-4000-8000-000000000001",
                 "sessionId": session, "timestamp": "2026-10-14T10:05:00.000Z"},
            ]
            tp.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            env = {k: v for k, v in os.environ.items()
                   if k not in ("OCTO_REPLY_PANEL", "OCTO_MERGE_APPROVE", "OCTO_QA_OK")}
            env.update({"HOME": str(sb), "USERPROFILE": str(sb),
                        "CLAUDE_SESSION_ID": SELFTEST_SESSION})
            payload = {"session_id": session, "transcript_path": str(tp),
                       "stop_hook_active": False, "last_assistant_message": text,
                       "hook_event_name": "Stop"}
            cp = subprocess.run([sys.executable, str(_HERE / "g__stop__reply-panel.py")],
                                input=json.dumps(payload), capture_output=True, text=True,
                                encoding="utf-8", errors="replace", cwd=str(sb), env=env,
                                timeout=60)
            if cp.returncode != want_exit:
                fails.append(f"{name}: reply gate exit {cp.returncode}, want {want_exit} "
                             f"({(cp.stderr or '').strip()[:120]})")
        finally:
            for k, v in old_home.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            shutil.rmtree(sb, ignore_errors=True)
    if fails:
        print("selftest FAIL (receipt_ledger external, AC-38): " + "; ".join(fails),
              file=sys.stderr)
        return 1
    print(f"selftest PASS: {len(cases)} forged-receipt cases bounded "
          "(panel_pass_for and g__stop__reply-panel.py, AC-25, AC-26, AC-38)")
    return 0


if __name__ == "__main__":
    import sys as _sys
    if "--selftest-external" in _sys.argv:
        _sys.exit(_selftest_external())
    print("receipt_ledger.py is a library; --selftest-external runs the AC-38 selftest",
          file=_sys.stderr)
    _sys.exit(2)
