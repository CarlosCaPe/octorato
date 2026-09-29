#!/usr/bin/env python3
"""stale_value_sweep: find every file that still holds an OLD value.

When a counterpart closes a definition (a count, a periodicity, a catalog
size), the documents that carry the previous value are found by searching for
the value itself. Not from memory, and not by following references between
documents: the document nobody links to is the one that stays stale.

Usage:
  stale_value_sweep.py --old "421" [--old "3 cycles" ...] [--root <dir>] [--json]
  stale_value_sweep.py --selftest

Scope: files git knows about under the root (tracked, plus untracked files that
are not ignored), text only, 2 MB or smaller. A value matches as a whole token:
an alphanumeric edge needs a non-word character next to it, so "421" does not
match inside "14210". Matching is case-insensitive and line by line.

Exit codes: 0 for a search that ran (a finding is not an error), 2 on bad
usage or a root git cannot list.

What it cannot see: files outside the root, ignored files, binaries (PDF,
spreadsheets, images), a value split across two lines, and the same value in
another spelling ("four hundred", "1,421" for "1421").
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

MAX_BYTES = 2 * 1024 * 1024
SNIFF_BYTES = 8192


def _clean_env() -> dict:
    """A hook or a git hook exports GIT_DIR and friends; a child git would then
    answer for the wrong repository."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), env=_clean_env(),
                          capture_output=True, text=True, timeout=60)


def git_toplevel(cwd: Path):
    try:
        res = _git(["rev-parse", "--show-toplevel"], cwd)
    except Exception:
        return None
    if res.returncode != 0 or not res.stdout.strip():
        return None
    return Path(res.stdout.strip())


def list_files(root: Path):
    """Paths relative to root, or None when git cannot list the root."""
    try:
        res = _git(["ls-files", "-z", "--cached", "--others", "--exclude-standard"], root)
    except Exception:
        return None
    if res.returncode != 0:
        return None
    return sorted({p for p in res.stdout.split("\0") if p})


def value_pattern(value: str):
    parts = [re.escape(p) for p in value.split()]
    body = r"[ \t]+".join(parts)
    head = r"(?<!\w)" if value[0].isalnum() else ""
    tail = r"(?!\w)" if value[-1].isalnum() else ""
    return re.compile(head + body + tail, re.IGNORECASE)


def read_text(path: Path):
    """The file's text, or None when it is missing, too large or binary."""
    try:
        if not path.is_file() or path.stat().st_size > MAX_BYTES:
            return None
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\0" in raw[:SNIFF_BYTES]:
        return None
    return raw.decode("utf-8", errors="replace")


def sweep(root: Path, values):
    """Return the list of holders, or None when the root cannot be listed."""
    files = list_files(root)
    if files is None:
        return None
    patterns = [(v, value_pattern(v)) for v in values]
    holders = []
    for rel in files:
        text = read_text(root / rel)
        if text is None:
            continue
        hits, first, found = 0, None, []
        for number, line in enumerate(text.splitlines(), 1):
            for value, pattern in patterns:
                count = len(pattern.findall(line))
                if count:
                    hits += count
                    if first is None:
                        first = number
                    if value not in found:
                        found.append(value)
        if hits:
            holders.append({"file": rel, "hits": hits, "first_line": first,
                            "values": found})
    return holders


def receipt(values, holders, root: Path) -> str:
    word = "SWEEP-COMPLETE" if holders else "SWEEP-EMPTY"
    total = sum(h["hits"] for h in holders)
    return f"{word} old={len(values)} files={len(holders)} hits={total} root={root}"


def render(values, holders, root: Path) -> str:
    lines = []
    groups = {}
    for h in holders:
        top = h["file"].split("/", 1)[0] if "/" in h["file"] else "."
        groups.setdefault(top, []).append(h)
    for top in sorted(groups):
        lines.append(f"{top}/" if top != "." else "./")
        for h in groups[top]:
            lines.append(f"  {h['file']}  hits={h['hits']}  first_line={h['first_line']}")
    lines.append(receipt(values, holders, root))
    return "\n".join(lines)


def _selftest() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="stale-value-sweep-"))
    failures = []
    try:
        repo = tmp / "repo"
        (repo / "docs").mkdir(parents=True)
        (repo / "notes" / "old").mkdir(parents=True)
        (repo / "README.md").write_text("See docs/plan.md for the plan.\n", encoding="utf-8")
        (repo / "docs" / "plan.md").write_text("Headcount is 438.\n", encoding="utf-8")
        # Nothing links to this one, and it still holds the previous value.
        (repo / "notes" / "old" / "estimate.md").write_text(
            "intro\nBudget assumes headcount 421 and 3 Cycles per year.\n", encoding="utf-8")
        (repo / "docs" / "serial.md").write_text("Part number 14210 ships.\n", encoding="utf-8")
        (repo / "docs" / "blob.bin").write_bytes(b"\0\1\2 421 \0")
        (repo / ".gitignore").write_text("ignored.md\n", encoding="utf-8")
        (repo / "ignored.md").write_text("headcount 421\n", encoding="utf-8")
        for args in (["init", "-q"], ["add", "--", "README.md", "docs", "notes", ".gitignore"]):
            res = _git(args, repo)
            if res.returncode != 0:
                print(f"selftest FAIL: git {args[0]}: {res.stderr.strip()}", file=sys.stderr)
                return 1

        holders = sweep(repo, ["421"])
        names = [h["file"] for h in (holders or [])]
        if names != ["notes/old/estimate.md"]:
            failures.append(f"unlinked holder: expected only notes/old/estimate.md, got {names}")
        elif holders[0]["first_line"] != 2 or holders[0]["hits"] != 1:
            failures.append(f"hit count or first line wrong: {holders[0]}")
        if "docs/serial.md" in names:
            failures.append("421 matched inside 14210")
        if "docs/blob.bin" in names:
            failures.append("binary file was searched")
        if "ignored.md" in names:
            failures.append("ignored file was searched")
        if not receipt(["421"], holders or [], repo).startswith("SWEEP-COMPLETE old=1 files=1 hits=1 "):
            failures.append("receipt for a finding is wrong: " + receipt(["421"], holders or [], repo))

        words = sweep(repo, ["3 cycles"])
        if [h["file"] for h in (words or [])] != ["notes/old/estimate.md"]:
            failures.append(f"case-insensitive phrase not found: {words}")

        empty = sweep(repo, ["999"])
        if empty != [] or not receipt(["999"], empty or [], repo).startswith("SWEEP-EMPTY old=1 files=0 hits=0 "):
            failures.append(f"absent value did not yield SWEEP-EMPTY: {empty}")

        if sweep(tmp, ["421"]) is not None:
            failures.append("a root outside any git repo was listed")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if failures:
        for f in failures:
            print(f"selftest FAIL: {f}", file=sys.stderr)
        return 1
    print("selftest PASS: unlinked holder found, absent value empty, binary and "
          "ignored skipped, 421 not matched inside 14210, phrase case-insensitive")
    return 0


def main(argv) -> int:
    if "--selftest" in argv:
        return _selftest()
    parser = argparse.ArgumentParser(
        prog="stale_value_sweep.py",
        description="Find every file under a git root that still holds an old value.")
    parser.add_argument("--old", action="append", default=[], metavar="VALUE",
                        help="the previous value; repeat for several")
    parser.add_argument("--root", help="directory to sweep (default: git toplevel of the cwd)")
    parser.add_argument("--json", action="store_true", help="machine output")
    args = parser.parse_args(argv)  # exits 2 on bad usage

    values = [v.strip() for v in args.old if v and v.strip()]
    if not values:
        print("usage error: give at least one non-empty --old value", file=sys.stderr)
        return 2
    if args.root:
        root = Path(args.root).expanduser()
        if not root.is_dir():
            print(f"usage error: --root is not a directory: {root}", file=sys.stderr)
            return 2
        root = root.resolve()
    else:
        root = git_toplevel(Path.cwd())
        if root is None:
            print("usage error: the cwd is not inside a git repo; pass --root", file=sys.stderr)
            return 2

    holders = sweep(root, values)
    if holders is None:
        print(f"usage error: git cannot list files under {root}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"root": str(root), "old": values, "holders": holders,
                          "files": len(holders),
                          "hits": sum(h["hits"] for h in holders),
                          "receipt": receipt(values, holders, root)}, indent=2))
    else:
        print(render(values, holders, root))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
