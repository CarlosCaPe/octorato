#!/usr/bin/env python3
"""octo.py: the terminal view of the v8 kernel (docs/architecture/v8-kernel.md).

Phase 1a gave every run a pid, a parent, a worktree and a hash-chained journal.
Nothing could READ any of it. This is that half: five subcommands over the same
`kernel_proc` library, no second copy of the ptable or the chain rules.

    octo ps                  who is running, who exited, and how old they are
    octo ps --release <pid>  free a stuck lane from the terminal (operator only)
    octo top                 live plus the last 24 h, by tool calls and denies
    octo replay <pid>        the run as it happened, refusals included
    octo journal <pid>       the raw lines, nothing interpreted
    octo bench               what the hot-path gate costs, measured

Two things are load-bearing and easy to miss.

RELEASE IS AGENT-PROOF. `--release` frees a lane a live process holds, which is
exactly what an agent denied by Phase 2 would want to do to itself. So it
refuses inside an agent shell, by importing the very `_looks_like_agent_shell()`
markers `octo-dim approve-prod` already uses (octo-dim.py:492): the operator
runs it in their own terminal, where no hook fires. Phase 2 adds the second
half, a Bash gate that denies a command whose boundary-split tokens invoke this
CLI with `--release`, so stripping the markers with `env -u` does not help.

REPLAY IS BYTE-STABLE. Every line of `replay` is derived from the journal alone:
offsets are relative to `start_ts`, never wall clock, and no age, no hostname,
no absolute path that the machine chose. That is what lets a golden fixture
compare exactly (`--fixture DIR` replays DIR/journal.jsonl against
DIR/expected.txt), and it is why the `chain` line is printed whether or not
`--verify` was passed: `--verify` decides the EXIT CODE, never the bytes.

CLI: `python3 scripts/octo.py --selftest registry/fixtures/ARCHITECTURE.kernel-process`
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import kernel_proc  # noqa: E402

DAY = 24 * 3600
BENCH_RUNS = 20
BENCH_BUDGET_MS = 100.0


# ── borrowed helpers ────────────────────────────────────────────────────────

def _looks_like_agent_shell() -> str:
    """The `approve-prod` markers, imported rather than re-typed.

    A second copy of the marker list is a second place to forget one, and the
    whole point of the check is that it is the SAME check the merge and prod
    approvals already trust (receipt_ledger.py:90-96 borrows from
    qa-merge-gate.py the same way; the filename has a dash, so importlib is the
    only way in).
    """
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "octo-dim.py")
    try:
        spec = importlib.util.spec_from_file_location("octo_dim", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod._looks_like_agent_shell()
    except Exception:
        # Fail CLOSED on the identity question: if the borrowed check cannot be
        # loaded we cannot prove the caller is the operator, so we answer as if
        # it is an agent and the release refuses.
        return "octo-dim unavailable"


# ── formatting ──────────────────────────────────────────────────────────────

def _age(seconds) -> str:
    """A compact age. Deterministic, so `ps` output diffs read cleanly."""
    if seconds is None:
        return "-"
    s = int(max(0, seconds))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    if s < DAY:
        return f"{s // 3600}h{(s % 3600) // 60:02d}m"
    return f"{s // DAY}d{(s % DAY) // 3600:02d}h"


def _table(headers, rows) -> str:
    """Column widths from the data. A session id is 36 chars and an agent type
    is a free-text phrase, so fixed widths would truncate exactly the two
    columns a reader needs."""
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    out = ["  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)).rstrip()]
    for row in rows:
        out.append("  ".join(str(c).ljust(widths[i]) for i, c in enumerate(row)).rstrip())
    return "\n".join(out)


# ── journal reading ─────────────────────────────────────────────────────────

def _read_lines(pid=None, path=None) -> list:
    """Parsed journal lines. `None` marks a line that does not parse (a torn
    write); replay names it rather than hiding it."""
    if path is None:
        return kernel_proc.read_journal(pid)
    out = []
    try:
        with open(path, "rb") as fh:
            for raw in fh:
                raw = raw.rstrip(b"\n")
                if not raw:
                    continue
                try:
                    out.append(json.loads(raw.decode("utf-8", "replace")))
                except ValueError:
                    out.append(None)
    except FileNotFoundError:
        return []
    return out


def _stats(lines: list) -> dict:
    """One pass over a journal: what `ps`, `top` and `replay` all need.

    `refused` counts the calls that were actually REFUSED: a deny id that also
    appears on a `tool` line. A deny with no matching tool line is a refusal of
    something the hot-path gate never journaled (a Stop block, a harness denial
    on a call that was denied before PreToolUse ran), and counting it as a
    refused TOOL CALL would report more refusals than there were calls. Those
    still show on the timeline and in `denies`; they just do not inflate the
    tool count. Both id sets are collected in this same pass.
    """
    denied, tool_ids, deny_rows = set(), set(), []
    st = {"tools": 0, "denies": 0, "tokens": 0, "has_tokens": False,
          "exit": None, "status": None, "start_ts": None, "last_ts": None,
          "type": None, "worktree": None, "source": None, "opens": 0,
          "by_tool": {}, "by_rule": {}, "by_receipt": {},
          "by_rule_paired": {}, "by_rule_other": {}}
    for rec in lines:
        if not isinstance(rec, dict):
            continue
        kind = rec.get("kind")
        if st["start_ts"] is None and rec.get("start_ts") is not None:
            st["start_ts"] = float(rec["start_ts"])
        if rec.get("ts") is not None:
            st["last_ts"] = float(rec["ts"])
        for key in ("type", "worktree", "source"):
            if rec.get(key) and not st[key]:
                st[key] = str(rec[key])
        if rec.get("tokens") is not None:
            try:
                st["tokens"] += int(rec["tokens"])
                st["has_tokens"] = True
            except (TypeError, ValueError):
                pass
        if kind == "tool":
            st["tools"] += 1
            name = str(rec.get("tool_name") or "?")
            st["by_tool"][name] = st["by_tool"].get(name, 0) + 1
            if rec.get("tool_use_id"):
                tool_ids.add(str(rec["tool_use_id"]))
        elif kind == "deny":
            st["denies"] += 1
            rule = str(rec.get("rule") or "(unnamed)")
            st["by_rule"][rule] = st["by_rule"].get(rule, 0) + 1
            deny_rows.append((rule, str(rec.get("tool_use_id") or "")))
            if rec.get("tool_use_id"):
                denied.add(str(rec["tool_use_id"]))
        elif kind == "receipt":
            rk = str(rec.get("receipt_kind") or "?")
            st["by_receipt"][rk] = st["by_receipt"].get(rk, 0) + 1
        elif kind == "exit":
            st["exit"] = rec
            st["status"] = str(rec.get("status") or "")
        elif kind == "open":
            st["opens"] += int(rec.get("count") or 0)
    st["refused"] = len(denied & tool_ids)
    # Split the same rows the tool-id set already decided: a deny whose call the
    # hot path journaled refused a CALL; anything else refused something the
    # gate never saw (a turn, a call denied before PreToolUse ran).
    for rule, tuid in deny_rows:
        bucket = "by_rule_paired" if tuid and tuid in tool_ids else "by_rule_other"
        st[bucket][rule] = st[bucket].get(rule, 0) + 1
    return st


def _counts(mapping: dict, empty: str = "(none)") -> str:
    """A count map as one deterministic line: biggest first, ties by name."""
    if not mapping:
        return empty
    items = sorted(mapping.items(), key=lambda kv: (-kv[1], kv[0]))
    return ", ".join(f"{k} {v}" for k, v in items)


# ── ps ──────────────────────────────────────────────────────────────────────

UNKNOWN_TYPE = kernel_proc.UNKNOWN_TYPE


def _row_type(row) -> str:
    """The process type, or `?` when the kernel does not know it.

    `top` unions the ptable with the journal files on disk, so it can reach a
    pid that has no row. `or "main"` printed those as main loops, which is two
    claims the kernel cannot make: that the process is a main loop, and that it
    is a process the register hooks ever saw. A `?` says only what is known.
    `ps` reads the ptable alone and every row carries a type, so this changes
    nothing there; it is written once so the two readers cannot drift apart,
    the way they already share `_row_state`.
    """
    return str(row.get("type") or UNKNOWN_TYPE)


def _print_dropped(dropped) -> None:
    """Say what the read repaired, or say nothing.

    `read_ptable` drops a ptable value that is not an object so one corrupt row
    cannot take `ps`, `top`, `replay`, the doctor and both register hooks down
    with it. Dropping it silently would trade a loud failure for a quiet one:
    the reader would see a shorter table and no reason for it. So the pids are
    named here, and the fix is named too, because a row that only disappears on
    the next write is not obviously gone.
    """
    if not dropped:
        return
    shown = ", ".join(sorted(dropped)[:5])
    more = f" (+{len(dropped) - 5} more)" if len(dropped) > 5 else ""
    print(f"{len(dropped)} unreadable row(s) dropped on read: {shown}{more}. "
          f"A ptable value that is not an object is not a process; the next "
          f"register hook rewrites the table without them.")


def _row_state(pid, row, table, now) -> str:
    if kernel_proc.is_live(pid, table, now):
        return "live"
    if row.get("status"):
        return str(row["status"])
    if kernel_proc.has_exit(pid):
        return "exited"
    return "expired"


def cmd_ps(args) -> int:
    if args.release:
        return _release(args.release)
    kernel_proc.prune_locked()
    table, dropped = kernel_proc.read_ptable_detail()
    procs = table.get("processes", {})
    now = time.time()
    rows, live_n = [], 0
    for pid, row in procs.items():
        state = _row_state(pid, row, table, now)
        if state == "live":
            live_n += 1
        lines = kernel_proc.read_journal(pid)
        st = _stats(lines)
        started = row.get("registered_ts") or st["start_ts"]
        age = (now - float(started)) if started else None
        rows.append((0 if state == "live" else 1, -(started or 0), [
            pid, row.get("ppid") or "-", _row_type(row),
            st["tools"], state, _age(age), row.get("worktree") or "-",
        ]))
    if not rows:
        print("no processes: the kernel has registered nothing on this machine yet")
        _print_dropped(dropped)
        return 0
    rows.sort(key=lambda r: (r[0], r[1]))
    print(_table(["PID", "PPID", "TYPE", "TOOLS", "EXIT", "AGE", "WORKTREE"],
                 [r[2] for r in rows]))
    print(f"\n{len(rows)} process(es), {live_n} live "
          f"(liveness: TTL {kernel_proc.TTL}s, v8-kernel.md section 2)")
    _print_dropped(dropped)
    return 0


def _release(pid: str) -> int:
    """Free the lanes a stuck process holds, and journal that it happened."""
    marker = _looks_like_agent_shell()
    if marker:
        print(
            f"x octo ps --release REFUSED: agent shell detected ({marker}).\n"
            "  A held lane is freed by the OPERATOR in their own terminal, never\n"
            "  by the agent that wants the lane. Run in your shell:\n"
            f"    octo ps --release {pid}\n"
            f"  (or python3 ~/.claude/scripts/octo.py ps --release {pid})",
            file=sys.stderr,
        )
        return 2
    safe = kernel_proc.safe_pid(pid)
    table = kernel_proc.read_ptable()
    row = (table.get("processes", {}) or {}).get(safe)
    if row is None and not os.path.exists(kernel_proc.journal_path(safe)):
        print(f"x no process {safe}: nothing to release", file=sys.stderr)
        return 1
    lanes = list((row or {}).get("lanes") or [])
    by = os.environ.get("USER") or "operator"
    try:
        kernel_proc.append(safe, {"kind": "release", "by": by, "lanes": lanes,
                                  "lane_count": len(lanes)})
    except OSError as exc:
        print(f"x could not journal the release: {exc}", file=sys.stderr)
        return 1
    if row is not None:
        # An empty list, not a deleted key: `update_row` merges, and a row that
        # says "lanes: []" is a process that provably holds nothing, which is a
        # different statement from a row that never claimed any.
        kernel_proc.update_row(safe, {"lanes": [], "released_ts": round(time.time(), 6),
                                      "released_by": by})
    print(f"released {safe}: {len(lanes)} lane(s) freed, journaled as `release` by {by}")
    return 0


# ── top ─────────────────────────────────────────────────────────────────────

def cmd_top(args) -> int:
    table, dropped = kernel_proc.read_ptable_detail()
    procs = table.get("processes", {})
    now = time.time()
    cutoff = now - DAY
    seen, rows, by_rule = set(), [], {}
    jdir = kernel_proc.journal_dir()
    names = []
    if os.path.isdir(jdir):
        names = [n[:-6] for n in os.listdir(jdir) if n.endswith(".jsonl")]
    for pid in sorted(set(list(procs) + names)):
        path = kernel_proc.journal_path(pid)
        mt = None
        try:
            mt = os.stat(path).st_mtime
        except OSError:
            pass
        live = kernel_proc.is_live(pid, table, now)
        if not live and (mt is None or mt < cutoff):
            continue
        st = _stats(kernel_proc.read_journal(pid))
        row = procs.get(pid) or {}
        seen.add(pid)
        for rule, n in st["by_rule"].items():
            by_rule[rule] = by_rule.get(rule, 0) + n
        # One vocabulary for both readers. `top` used to print "exited" for a
        # process with no exit line whose journal had simply aged past the TTL,
        # while `ps` called the same process "expired": two words for one state,
        # and the two commands disagreeing about a process is exactly the kind
        # of drift a replay surface cannot afford.
        rows.append([pid, _row_type(row), st["tools"], st["denies"],
                     st["tokens"] if st["has_tokens"] else "-",
                     _row_state(pid, row, table, now)])
    if not rows:
        print("no activity in the last 24 h and nothing live")
        _print_dropped(dropped)
        return 0
    rows.sort(key=lambda r: (-int(r[2]), r[0]))
    tools = sum(int(r[2]) for r in rows)
    denies = sum(int(r[3]) for r in rows)
    # Totals come off the numbers, never off the rendered cells: a process with
    # no tokens renders as "-", and summing the rendered column is how a total
    # turns into a crash the moment one process reports tokens and another
    # does not.
    tokens = sum(int(r[4]) for r in rows if r[4] != "-")
    any_tokens = any(r[4] != "-" for r in rows)
    headers = ["PID", "TYPE", "TOOLS", "DENIES", "TOKENS", "STATUS"]
    if not any_tokens:
        # The runtime has not exposed token counts to any hook yet. An empty
        # column would read as "zero tokens used", which is a claim; dropping
        # it says only what is known.
        headers = [h for h in headers if h != "TOKENS"]
        rows = [[c for i, c in enumerate(r) if i != 4] for r in rows]
    print(_table(headers, rows))
    print(f"\n{len(rows)} process(es), {tools} tool call(s), {denies} deny(s)"
          + (f", {tokens} token(s)" if any_tokens else "")
          + " (live plus the last 24 h)")
    # Counted off the ptable, never off the rendered `?` cells: a row that
    # exists but carries no type also renders `?`, and the number the reader
    # needs is how many of these pids the process table does not know at all.
    unknown = sum(1 for r in rows if r[0] not in procs)
    if unknown:
        # Shown, never hidden: a journal with no row is either a process whose
        # register hook lost its race (real work, worth reading) or a leftover,
        # and the reader is the one who can tell. What is NOT printed is a type
        # the kernel never learned. `ps` reads the ptable, so it lists 0 of
        # these; the difference between the two counts is the point.
        print(f"{unknown} of them have a journal but no ptable row, so their "
              f"type reads `{UNKNOWN_TYPE}` (not shown by `octo ps`)")
    _print_dropped(dropped)
    if by_rule:
        # WHICH rules are refusing is the number that changes behaviour; a bare
        # deny total says only that something did.
        print("\ndenies by rule")
        for rule, n in sorted(by_rule.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"  {rule}  {n}")
    return 0


# ── replay ──────────────────────────────────────────────────────────────────

def _cell(rec: dict, key: str, default: str = "-") -> str:
    v = rec.get(key)
    return str(v) if v not in (None, "") else default


def _src(rec: dict) -> str:
    """`source=harness ` on a refusal the RUNTIME made, empty on an Octorato one.

    A reader who cannot tell the two apart cannot act on either: one is a gate
    to argue with, the other is a permission to grant. Absent means Octorato,
    so the common case stays unannotated.
    """
    source = rec.get("source")
    return f"source={source}  " if source else ""


def replay_text(pid: str, lines: list, table: dict = None,
                receipts: list = None, chain: tuple = None,
                receipts_label: str = "receipts") -> str:
    """The run as text. Journal-derived only, so the bytes are reproducible.

    `receipts_label` names where the receipts came from. The ledger is keyed by
    SESSION, so a child's replay shows its PARENT's receipts; labelling that
    section `receipts (session)` stops a reader from crediting the child with
    seeks it never made.
    """
    st = _stats(lines)
    start_ts = st["start_ts"]
    denies = {}
    for rec in lines:
        if isinstance(rec, dict) and rec.get("kind") == "deny" and rec.get("tool_use_id"):
            denies.setdefault(str(rec["tool_use_id"]), rec)

    out = [f"process {pid}"]
    # UNKNOWN_TYPE, not "main": `replay` reads a journal, so like `top` it can be
    # handed a pid with no row, and saying `main` there would make `octo top` and
    # `octo replay` disagree about the same process. That is the drift this
    # constant exists to prevent, and QA caught it here after it was fixed in top.
    out.append(f"  type      {st['type'] or UNKNOWN_TYPE}")
    out.append(f"  worktree  {st['worktree'] or '-'}")
    out.append(f"  lines     {len(lines)}")
    out.append(f"  tools     {st['tools']} ({st['refused']} refused)")
    if st["exit"] is not None:
        e = st["exit"]
        dur = e.get("duration")
        dur_s = f"{float(dur):.3f}s" if isinstance(dur, (int, float)) else "-"
        out.append(f"  exit      {st['status'] or '-'} after {dur_s}")
    else:
        out.append("  exit      (no exit line: still running, or expired)")
    if chain is not None:
        code, why = chain
        out.append(f"  chain     {'ok' if code == 0 else 'BROKEN'}: {why}")

    kids = [(c, r) for c, r in sorted((table or {}).get("processes", {}).items())
            if r.get("ppid") == pid]

    # The summary answers the three questions a reader opens a replay with:
    # what did this run DO, what was it refused, and what did it prove. The
    # timeline below is the evidence; this is the verdict.
    out.append("")
    out.append("summary")
    out.append(f"  tools     {_counts(st['by_tool'])}")
    # Two lines, because they answer two questions. `refused` is the calls the
    # hot-path gate journaled and a gate then refused, so it reconciles with the
    # header's "(N refused)". `other denies` is everything else that refused
    # something: a Stop block ends a TURN, a harness denial can land on a call
    # PreToolUse never saw. Listing both under one `refused` label made the
    # summary contradict the header two lines above it.
    out.append(f"  refused   {_counts(st['by_rule_paired'])}")
    if st["by_rule_other"]:
        out.append(f"  other denies  {_counts(st['by_rule_other'])}")
    out.append(f"  receipts  {_counts(st['by_receipt'])}")
    out.append(f"  children  {len(kids)}"
               + (": " + ", ".join(c for c, _ in kids) if kids else ""))
    if st["exit"] is not None:
        out.append(f"  exit      {st['status'] or '-'}")
    else:
        out.append("  exit      (none yet)")
    if st["opens"]:
        out.append(f"  unjournaled  {st['opens']} call(s) ran in open mode")

    out.append("")
    out.append("timeline")
    folded = set()
    for i, rec in enumerate(lines):
        if not isinstance(rec, dict):
            out.append(f"  #{i:<4} {'':>9}  {'torn':<8} line does not parse")
            continue
        seq = rec.get("seq")
        seq_s = str(seq) if seq is not None else str(i)
        ts = rec.get("ts")
        off = (f"+{float(ts) - float(start_ts):.3f}s"
               if (ts is not None and start_ts is not None) else "-")
        kind = str(rec.get("kind") or "?")
        tuid = _cell(rec, "tool_use_id")
        if kind == "tool" and tuid in denies:
            d = denies[tuid]
            folded.add(id(d))
            rest = (f"{_cell(d, 'rule')}  {_src(d)}{_cell(rec, 'tool_name')}  {tuid}"
                    f"  {_cell(d, 'reason', '')}").rstrip()
            out.append(f"  #{seq_s:<4} {off:>9}  {'REFUSED':<8} {rest}")
            continue
        if kind == "deny":
            if id(rec) in folded:
                continue
            rest = (f"{_cell(rec, 'rule')}  {_src(rec)}{tuid}  "
                    f"{_cell(rec, 'reason', '')}").rstrip()
        elif kind == "tool":
            rest = f"{_cell(rec, 'tool_name')}  {tuid}"
        elif kind == "start":
            rest = f"source={_cell(rec, 'source')}  worktree={_cell(rec, 'worktree')}"
        elif kind == "exit":
            rest = (f"{_cell(rec, 'status')}  tools={_cell(rec, 'tool_count')}"
                    f"  transcript={_cell(rec, 'agent_transcript_path')}")
        elif kind == "open":
            rest = f"count={_cell(rec, 'count')}  (ran unjournaled)"
        elif kind == "release":
            rest = f"by={_cell(rec, 'by')}  lanes={_cell(rec, 'lane_count', '0')}"
        elif kind == "receipt":
            rest = f"{_cell(rec, 'receipt_kind')}  {tuid}"
        elif kind == "quota":
            rest = f"{_cell(rec, 'quota')}  {_cell(rec, 'reason', '')}".rstrip()
        else:
            rest = _cell(rec, "reason", "")
        out.append(f"  #{seq_s:<4} {off:>9}  {kind:<8} {rest}".rstrip())

    out.append("")
    out.append("children")
    out.extend([f"  {child}  {_row_type(row)}  "
                f"{row.get('status') or 'no exit recorded'}"
                for child, row in kids] or ["  (none)"])

    out.append("")
    out.append(receipts_label)
    recs = receipts or []
    shown = [f"  {r.get('kind') or '?'}  {r.get('tool_use_id') or '-'}  {r.get('ts') or '-'}"
             for r in recs[:10]]
    out.extend(shown or ["  (none)"])
    if len(recs) > 10:
        out.append(f"  (+{len(recs) - 10} more)")
    return "\n".join(out) + "\n"


def _fixture_receipts(fdir: str) -> list:
    path = os.path.join(fdir, "receipts.jsonl")
    out = []
    try:
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if raw:
                    try:
                        out.append(json.loads(raw))
                    except ValueError:
                        continue
    except FileNotFoundError:
        return []
    return out


def _fixture_table(fdir: str) -> dict:
    """A golden fixture may ship its own ptable, so the children section is part
    of the byte-for-byte contract instead of depending on whatever the running
    machine happens to hold."""
    try:
        with open(os.path.join(fdir, "ptable.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        # Through the same shape rule as a real table: a fixture is read by the
        # same renderer, so a second parser here is exactly how the two drift.
        return kernel_proc.sane_table(data)[0]
    except (FileNotFoundError, ValueError, OSError):
        return {"processes": {}}


def _session_receipts(pid: str, table: dict) -> list:
    """The receipt ledger is keyed by SESSION (receipt_ledger.py:270-274), so a
    subagent's receipts live under its parent's id, not its own."""
    row = (table.get("processes", {}) or {}).get(pid) or {}
    sid = row.get("ppid") or pid
    try:
        import importlib.util
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "receipt_ledger.py")
        spec = importlib.util.spec_from_file_location("receipt_ledger_ro", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.read_session(str(sid))
    except Exception:
        return []


def cmd_replay(args) -> int:
    if args.fixture:
        fdir = args.fixture
        path = os.path.join(fdir, "journal.jsonl")
        if not os.path.isfile(path):
            print(f"x no golden journal at {path}", file=sys.stderr)
            return 1
        lines = _read_lines(path=path)
        pid = args.pid or next((str(r.get("pid")) for r in lines
                                if isinstance(r, dict) and r.get("pid")), "fixture")
        chain = _verify_raw(path)
        text = replay_text(pid, lines, table=_fixture_table(fdir),
                           receipts=_fixture_receipts(fdir), chain=chain)
        sys.stdout.write(text)
        return 1 if (args.verify and chain[0] != 0) else 0

    if not args.pid:
        print("x replay needs a pid (or --fixture DIR)", file=sys.stderr)
        return 1
    pid = kernel_proc.safe_pid(args.pid)
    lines = kernel_proc.read_journal(pid)
    if not lines:
        print(f"x no journal for {pid}", file=sys.stderr)
        return 1
    table = kernel_proc.read_ptable()
    chain = kernel_proc.verify_detail(pid)
    row = (table.get("processes", {}) or {}).get(pid) or {}
    sid = str(row.get("ppid") or "")
    label = "receipts (session)" if sid and sid != pid else "receipts"
    text = replay_text(pid, lines, table=table,
                       receipts=_session_receipts(pid, table), chain=chain,
                       receipts_label=label)
    sys.stdout.write(text)
    return 1 if (args.verify and chain[0] != 0) else 0


def _verify_raw(path: str) -> tuple:
    """`verify_detail` for a file outside the kernel dir (a fixture). Same rules,
    same wording: the chain check lives in kernel_proc, this only rebinds where
    the journal is read from."""
    import hashlib
    try:
        with open(path, "rb") as fh:
            raws = [r.rstrip(b"\n") for r in fh]
    except OSError:
        return 1, f"cannot read {path}"
    raws = [r for r in raws if r]
    if not raws:
        return 1, "empty journal"
    prev_raw, start_ts, breaks = None, None, []
    for i, raw in enumerate(raws):
        try:
            rec = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            rec = None
        if not isinstance(rec, dict):
            breaks.append(f"line {i} does not parse")
            prev_raw = raw
            continue
        if rec.get("seq") != i:
            breaks.append(f"line {i} carries seq {rec.get('seq')}")
        want = None if prev_raw is None else hashlib.sha256(prev_raw).hexdigest()
        if rec.get("prev") != want:
            breaks.append(f"line {i} prev {rec.get('prev')} != {want}")
        if start_ts is None:
            start_ts = rec.get("start_ts")
        elif rec.get("start_ts") != start_ts:
            breaks.append(f"line {i} start_ts moved to {rec.get('start_ts')}")
        prev_raw = raw
    if breaks:
        return 1, f"{len(breaks)} break(s): " + "; ".join(breaks[:4])
    return 0, f"{len(raws)} line(s) chain"


# ── journal ─────────────────────────────────────────────────────────────────

def cmd_journal(args) -> int:
    path = kernel_proc.journal_path(args.pid)
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        print(f"x cannot read {path}: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(data.decode("utf-8", "replace"))
    return 0


# ── bench ───────────────────────────────────────────────────────────────────

def bench(runs: int = BENCH_RUNS) -> dict:
    """Time the hot path as the harness runs it: the real gate, a real payload,
    stdin to stdout, in a sandbox HOME so the first invocation pays for creating
    the journal directory and the journal itself (the first-write cost Phase 2
    will amortize a lane claim onto).

    A subprocess measurement includes the interpreter start, which is exactly
    what the harness pays too. Timing is never a gate: `brain_doctor` reports
    this as a WARN, never a FAIL (v8-kernel.md section 3)."""
    import shutil
    import subprocess
    import tempfile

    scripts = os.path.dirname(os.path.abspath(__file__))
    gate = os.path.join(scripts, "g__pretool__kernel.py")
    sandbox = tempfile.mkdtemp(prefix="octo-bench-")
    samples = []
    try:
        env = kernel_proc._sandbox_env(sandbox)
        payload = json.dumps({
            "hook_event_name": "PreToolUse", "session_id": "octo-bench",
            "tool_name": "Bash", "tool_use_id": "toolu_bench",
            "tool_input": {"command": "true"}, "cwd": sandbox,
        })
        for _ in range(runs):
            t0 = time.perf_counter()
            subprocess.run([sys.executable, gate], input=payload, capture_output=True,
                           text=True, cwd=sandbox, env=env, timeout=60)
            samples.append((time.perf_counter() - t0) * 1000.0)
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)
    ordered = sorted(samples)
    n = len(ordered)
    median = ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2
    return {"runs": n, "median_ms": round(median, 2), "min_ms": round(ordered[0], 2),
            "max_ms": round(ordered[-1], 2), "first_write_ms": round(samples[0], 2),
            "budget_ms": BENCH_BUDGET_MS}


def cmd_bench(args) -> int:
    data = bench(args.runs)
    if args.json:
        print(json.dumps(data, sort_keys=True))
        return 0
    print(f"bench: {data['runs']} invocation(s) of g__pretool__kernel.py, "
          f"median {data['median_ms']} ms "
          f"(min {data['min_ms']}, max {data['max_ms']}, "
          f"first-write {data['first_write_ms']}, budget {data['budget_ms']})")
    if args.no_fail:
        return 0
    if data["median_ms"] > BENCH_BUDGET_MS:
        print(f"x median {data['median_ms']} ms is over the {BENCH_BUDGET_MS} ms budget",
              file=sys.stderr)
        return 1
    return 0


# ── selftest (bespoke: golden compare plus a state-dependent smoke) ─────────

def _run_octo(argv, sandbox, env, extra_env=None, unset=()):
    import subprocess
    e = dict(env)
    if extra_env:
        e.update(extra_env)
    for key in unset:
        e.pop(key, None)
    cp = subprocess.run([sys.executable, os.path.abspath(__file__)] + argv,
                        capture_output=True, text=True, cwd=sandbox, env=e, timeout=60)
    return cp.returncode, cp.stdout, cp.stderr


def selftest(fixture_dir: str = None) -> int:
    """Golden replay compared byte for byte, plus a ps/top/release smoke.

    No timing assert anywhere: `bench` is not run here (v8-kernel.md section 3,
    "unit tests assert the hot path runs and journals, never its duration").
    """
    import shutil
    import tempfile

    scripts = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(scripts)
    fdir = fixture_dir or os.path.join("registry", "fixtures", "ARCHITECTURE.kernel-process")
    if not os.path.isabs(fdir):
        fdir = os.path.join(root, fdir)
    rdir = os.path.join(fdir, "replay")
    expected_path = os.path.join(rdir, "expected.txt")
    journal_path = os.path.join(rdir, "journal.jsonl")
    failures = []
    for path in (journal_path, expected_path):
        if not os.path.isfile(path):
            print(f"selftest FAIL: fixture missing: {path}", file=sys.stderr)
            return 1

    sandbox = tempfile.mkdtemp(prefix="octo-selftest-")
    try:
        seed = os.path.join(fdir, "home")
        if os.path.isdir(seed):
            shutil.copytree(seed, sandbox, dirs_exist_ok=True)
        env = kernel_proc._sandbox_env(sandbox)

        with open(expected_path, "rb") as fh:
            expected = fh.read()

        # 1. the golden replay, byte for byte, with and without --verify
        for argv in (["replay", "--fixture", rdir], ["replay", "--fixture", rdir, "--verify"]):
            rc, out, err = _run_octo(argv, sandbox, env)
            if rc != 0:
                failures.append(f"{' '.join(argv)} exited {rc}: {err.strip()[:120]}")
            if out.encode("utf-8") != expected:
                failures.append(f"{' '.join(argv)} does not match expected.txt byte for byte")

        # 2. a tampered copy must fail --verify (and only with --verify)
        tdir = os.path.join(sandbox, "tampered")
        os.makedirs(tdir, exist_ok=True)
        with open(journal_path, "rb") as fh:
            raw = fh.read()
        with open(os.path.join(tdir, "journal.jsonl"), "wb") as fh:
            fh.write(raw.replace(b'"kind":"tool"', b'"kind":"toox"', 1))
        rc, _, _ = _run_octo(["replay", "--fixture", tdir, "--verify"], sandbox, env)
        if rc == 0:
            failures.append("a tampered golden journal still verified")

        # 3. ps / top over a real seeded state, through the real register hooks
        with open(os.path.join(fdir, "start.json"), encoding="utf-8") as fh:
            start = json.load(fh)
        with open(os.path.join(fdir, "subagent_start.json"), encoding="utf-8") as fh:
            sub = json.load(fh)
        parent, child = str(start.get("session_id")), str(sub.get("agent_id"))
        kernel_proc._feed("r__session__proc-register.py", start, sandbox, env)
        kernel_proc._feed("r__subagent-start__proc-register.py", sub, sandbox, env)
        for i in range(2):
            kernel_proc._feed("g__pretool__kernel.py", {
                "session_id": parent, "agent_id": child, "tool_name": "Bash",
                "tool_use_id": f"toolu_octo_{i}", "tool_input": {"command": "true"},
                "cwd": sandbox}, sandbox, env)

        rc, out, err = _run_octo(["ps"], sandbox, env)
        if rc != 0:
            failures.append(f"ps exited {rc}: {err.strip()[:120]}")
        for pid in (parent, child):
            if pid not in out:
                failures.append(f"ps does not show {pid}")
        if "Reality Checker" not in out:
            failures.append("ps does not show the child's agent type")

        rc, out, err = _run_octo(["top"], sandbox, env)
        if rc != 0:
            failures.append(f"top exited {rc}: {err.strip()[:120]}")
        if child not in out:
            failures.append("top does not show the child")

        rc, out, err = _run_octo(["replay", child], sandbox, env)
        if rc != 0 or "timeline" not in out or "toolu_octo_1" not in out:
            failures.append("replay of a real pid does not print its tool calls")

        # 4. --release: refused in an agent shell, allowed outside it
        rc, _, err = _run_octo(["ps", "--release", child], sandbox, env,
                               {"CLAUDECODE": "1"})
        if rc != 2 or "REFUSED" not in err:
            failures.append(f"--release was not refused in an agent shell (rc={rc})")
        # An operator's terminal carries none of the harness markers. The
        # selftest itself runs INSIDE one (that is why the leg above passes), so
        # the allowed leg has to strip them to model the shell the operator
        # actually types in.
        rc, out, err = _run_octo(["ps", "--release", child], sandbox, env,
                                 unset=("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT",
                                        "CLAUDE_CODE_SESSION_ID"))
        if rc != 0:
            failures.append(f"--release outside an agent shell exited {rc}: {err.strip()[:120]}")
        # Save what we are about to overwrite. Popping HOME instead of restoring
        # it left the rest of THIS process running without a HOME, so anything
        # after the selftest read the kernel from a different place than the
        # caller does. A sandbox must be reversible, not one-way.
        saved = (os.environ.get("HOME"), os.environ.get("USERPROFILE"))
        os.environ["HOME"], os.environ["USERPROFILE"] = sandbox, sandbox
        try:
            kinds = [l.get("kind") for l in kernel_proc.read_journal(child)
                     if isinstance(l, dict)]
            if "release" not in kinds:
                failures.append("--release wrote no `release` line")
            if kernel_proc.verify(child) != 0:
                failures.append("the chain broke after a release")
        finally:
            for key, was in zip(("HOME", "USERPROFILE"), saved):
                if was is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = was
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)

    if failures:
        print("selftest FAIL: " + "; ".join(failures), file=sys.stderr)
        return 1
    print(f"selftest PASS: golden replay matches, ps/top read the table, "
          f"release is operator-only (octo vs {os.path.basename(fdir)})")
    return 0


# ── cli ─────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="octo", description="read the v8 kernel: processes, journals, replay")
    p.add_argument("--selftest", nargs="?", const="", metavar="FIXTURE_DIR",
                   help="prove this CLI against registry/fixtures/ARCHITECTURE.kernel-process")
    sub = p.add_subparsers(dest="cmd")

    ps = sub.add_parser("ps", help="processes: live and recently exited")
    ps.add_argument("--release", metavar="PID",
                    help="free the lanes PID holds (operator terminal only)")
    ps.set_defaults(func=cmd_ps)

    top = sub.add_parser("top", help="live plus the last 24 h, by tool calls")
    top.set_defaults(func=cmd_top)

    rp = sub.add_parser("replay", help="one run as it happened, refusals included")
    rp.add_argument("pid", nargs="?")
    rp.add_argument("--verify", action="store_true",
                    help="exit non-zero when the hash chain is broken")
    rp.add_argument("--fixture", metavar="DIR",
                    help="replay DIR/journal.jsonl instead of a live journal")
    rp.set_defaults(func=cmd_replay)

    jr = sub.add_parser("journal", help="the raw journal lines")
    jr.add_argument("pid")
    jr.set_defaults(func=cmd_journal)

    bn = sub.add_parser("bench", help="time the PreToolUse hot path")
    bn.add_argument("--runs", type=int, default=BENCH_RUNS)
    bn.add_argument("--json", action="store_true", help="machine-readable, never exits 1")
    bn.add_argument("--no-fail", action="store_true",
                    help="report the median without failing over the budget")
    bn.set_defaults(func=cmd_bench)
    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.selftest is not None:
        return selftest(args.selftest or None)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    if getattr(args, "json", False):
        args.no_fail = True
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
