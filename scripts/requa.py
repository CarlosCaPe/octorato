#!/usr/bin/env python3
"""Base_Update_Verifier helper for `/requa <pr>` (spec v10, AC-12).

`commands/requa.md` is the protocol; this file holds the three steps of it that
can be decided without the network, so a test can pin them:

  parents     the new head has exactly two parents and the reviewed head is one
              of them, compared as full SHAs (a prefix never matches)
  on-master   the remote compare of the second parent against master says
              `identical` or `ahead`, so that parent is a commit of master
  compare     the patch of each head over its merge base, normalized for what a
              base update changes by itself (blob hashes on `index` lines and the
              line numbers of hunk headers), is the same byte for byte

Every remote answer (the parents, the compare status, both merge bases) is an
INPUT. The command reads them through `gh api` and passes them in; this helper
never reads master, never fetches and never calls the network, so a moved local
ref cannot feed it. Its git diffs take only full content-addressed SHAs: a ref
name such as `origin/master` or `HEAD` is refused before git is called.

Exit codes: 0 when the step holds, 1 when it does not (the verdict is
NEEDS-WORK), 2 on a usage error. It never sets OCTO_MERGE_APPROVE, never
merges, and never touches the merge gate.
"""
from __future__ import annotations

import argparse
import difflib
import re
import subprocess
import sys

SHA_RE = re.compile(r"\A(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
# Patches are handled as BYTES end to end: decoding with text=True folds
# `\r\n` and `\r` into `\n`, so a CR-only edit would read as no edit.
_INDEX_RE = re.compile(rb"^index [0-9a-f]+\.\.[0-9a-f]+")
# Only the two line ranges go; the function-context text after the second @@
# stays, because it names the function a hunk lands in.
_HUNK_RE = re.compile(rb"^@@ -[0-9]+(,[0-9]+)? \+[0-9]+(,[0-9]+)? @@")
_FILE_RE = re.compile(rb"^diff --git ")
_BINARY_RE = re.compile(rb"^(GIT binary patch|Binary files .* differ)$")
_LINE_RE = re.compile(rb"[^\n]*\n|[^\n]+\Z")
ON_MASTER = ("identical", "ahead")


def is_sha(value: str) -> bool:
    return bool(SHA_RE.match(value or ""))


def check_parents(old: str, parents: list[str]) -> tuple[bool, str, str]:
    """(ok, second_parent, reason). OK only for exactly two full-SHA parents
    with `old` among them, compared by equality, never by prefix."""
    if not is_sha(old):
        return False, "", f"reviewed head {old!r} is not a full commit SHA"
    bad = [p for p in parents if not is_sha(p)]
    if bad:
        return False, "", f"parent {bad[0]!r} is not a full commit SHA"
    if len(parents) != 2:
        return False, "", f"the new head has {len(parents)} parent(s), not exactly two"
    if old not in parents:
        return False, "", f"the reviewed head {old} is not a parent of the new head"
    second = parents[1] if parents[0] == old else parents[0]
    if second == old:
        return False, "", "both parents are the reviewed head"
    return True, second, "two parents, the reviewed head among them"


def on_master(status: str) -> bool:
    """The compare of P2...MASTER must say P2 is master or behind it."""
    return status in ON_MASTER


def _lines(patch: bytes) -> list[bytes]:
    """Split on \\n only, keeping it; a \\r stays part of its line."""
    return _LINE_RE.findall(patch)


def normalize(patch: bytes) -> bytes:
    """Drop the `index` line of each TEXT file block and the line numbers of
    hunk headers. A BINARY block keeps its `index` line: with no hunks, the
    blob hashes are its identity, and a base update cannot change them for a
    file master did not touch."""
    blocks: list[list[bytes]] = []
    for line in _lines(patch):
        if _FILE_RE.match(line) or not blocks:
            blocks.append([])
        blocks[-1].append(line)
    out = []
    for block in blocks:
        binary = any(_BINARY_RE.match(ln.rstrip(b"\n")) for ln in block)
        for line in block:
            if not binary and _INDEX_RE.match(line):
                continue
            out.append(_HUNK_RE.sub(b"@@", line, count=1))
    return b"".join(out)


def git_patch(repo: str, base: str, head: str) -> bytes:
    for sha in (base, head):
        if not is_sha(sha):
            raise ValueError(f"{sha!r} is not a full commit SHA; read it from the remote with gh")
    cp = subprocess.run(
        # --binary: a binary file's bytes travel in the patch instead of
        # "Binary files ... differ". --no-textconv: a configured converter
        # cannot stand in for the bytes.
        ["git", "-C", repo, "diff", "--no-color", "--no-ext-diff", "--no-textconv", "--binary",
         f"{base}..{head}"],
        capture_output=True)
    if cp.returncode != 0:
        err = cp.stderr.decode("utf-8", "replace").strip()
        raise ValueError(f"git diff {base[:12]}..{head[:12]} failed: {err}")
    return cp.stdout


def compare(repo: str, mb_old: str, old: str, mb_new: str, new: str) -> tuple[bool, bytes]:
    """(identical, unified diff of the two normalized patches)."""
    a = normalize(git_patch(repo, mb_old, old))
    b = normalize(git_patch(repo, mb_new, new))
    if a == b:
        return True, b""
    diff = b"".join(difflib.diff_bytes(difflib.unified_diff, _lines(a), _lines(b),
                                       b"old.patch", b"new.patch"))
    return False, diff


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("parents", help="check the new head's parents; prints the second parent")
    p.add_argument("--old", required=True, help="the head that holds the QA PASS")
    p.add_argument("parents", nargs="*", help="the new head's parents, as gh api returned them")
    m = sub.add_parser("on-master", help="check the compare status of P2...MASTER")
    m.add_argument("status")
    c = sub.add_parser("compare", help="compare the two normalized patches")
    c.add_argument("--repo", default=".")
    c.add_argument("mb_old")
    c.add_argument("old")
    c.add_argument("mb_new")
    c.add_argument("new")
    args = ap.parse_args(argv)

    if args.cmd == "parents":
        ok, second, why = check_parents(args.old, args.parents)
        if not ok:
            print(f"NEEDS-WORK: {why}")
            return 1
        print(second)
        return 0
    if args.cmd == "on-master":
        if on_master(args.status):
            print(f"OK: second parent is on master ({args.status})")
            return 0
        print(f"NEEDS-WORK: second parent is not on master (compare status {args.status!r})")
        return 1
    try:
        same, diff = compare(args.repo, args.mb_old, args.old, args.mb_new, args.new)
    except ValueError as exc:
        print(f"NEEDS-WORK: {exc}")
        return 1
    if same:
        print("IDENTICAL")
        return 0
    sys.stdout.flush()
    sys.stdout.buffer.write(diff)
    sys.stdout.buffer.flush()
    print("DIFFERS")
    return 1


if __name__ == "__main__":
    sys.exit(main())
