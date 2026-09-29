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
are not ignored), text only, 2 MB or smaller. Symlinks are skipped, and so is
any path whose real location is outside the root. A file name that is not
valid UTF-8 is swept like any other.

Matching is case-insensitive and line by line. A value matches as a whole
token: an alphanumeric edge needs a non-word character next to it, so "421"
does not match inside "9421" or "4210". A value made only of digits is read as
a number:
  - it does not match inside a longer number written with separators or
    decimals: "421" skips "1,421", "421,000", "0.421" and "421.5";
  - it still matches "421." at the end of a sentence, "$421", "421%", "-421"
    and "421-A";
  - a value of four or more digits also matches its written forms with a
    thousands separator: "1421" finds "1,421", "1.421", "1 421", "1'421" and
    the forms with a no-break space (U+00A0) or a narrow no-break space
    (U+202F). The written form is not matched when it is a piece of something
    else: followed by a separator and three more digits ("1 421 000"),
    preceded by a digit and a separator ("3 1 421"), or followed by a hyphen
    and a word character ("1.421-rc1");
  - an old value given in its written form ("1,421" or "1.421") is read as
    the number 1421 and matched the same way.

Exit codes: 0 for a search that ran (a finding is not an error), 2 on bad
usage or a root git cannot list.

What it cannot see: files outside the root, ignored files, symlinked files,
binaries (PDF, spreadsheets, images), UTF-16 text (it carries NUL bytes and is
skipped as binary), files over 2 MB, a value split across two lines, a number
spelled as words ("four hundred"), and a number with a letter-like sign
attached ("421\u00ba" does not match "421", because the ordinal sign is a
word character).

Readings it cannot tell apart, all reported: "1.421" as a decimal and as 1421
with a separator; "page 1 421 words", where 1 and 421 are two numbers; "421"
as the last group of a number written with a space or an apostrophe ("1 421"
and "1 421 000" are reported for "421"); and an old value "1.421" meant as a decimal, which is read as 1421.
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
    """Output stays bytes: one file name that is not UTF-8 must not abort the run."""
    return subprocess.run(["git", *args], cwd=str(cwd), env=_clean_env(),
                          capture_output=True, timeout=60)


def git_toplevel(cwd: Path):
    try:
        res = _git(["rev-parse", "--show-toplevel"], cwd)
    except Exception:
        return None
    top = os.fsdecode(res.stdout).strip()
    if res.returncode != 0 or not top:
        return None
    return Path(top)


def list_files(root: Path):
    """Paths relative to root, or None when git cannot list the root."""
    try:
        res = _git(["ls-files", "-z", "--cached", "--others", "--exclude-standard"], root)
    except Exception:
        return None
    if res.returncode != 0:
        return None
    return sorted({os.fsdecode(p) for p in res.stdout.split(b"\0") if p})


LEAD_BOUNDARY = r"(?<!\w)"
TRAIL_BOUNDARY = r"(?!\w)"
THOUSANDS_SEP = "[., '\u00a0\u202f]"
WRITTEN_VALUE_RE = re.compile(r"[0-9]{1,3}(?:[.,][0-9]{3})+")
# A digit and a separator before, or a separator and a digit after, mean this
# is a piece of a different number.
PLAIN_LEAD = r"(?<![0-9][.,])"
PLAIN_TRAIL = r"(?![.,][0-9])"
WRITTEN_LEAD = r"(?<![0-9]" + THOUSANDS_SEP + r")"
WRITTEN_TRAIL = r"(?!" + THOUSANDS_SEP + r"[0-9]{3})" + r"(?![.,][0-9])" + r"(?!-\w)"


def normalise(value: str) -> str:
    """An old value in its written form, "1,421" or "1.421", is the number 1421."""
    if WRITTEN_VALUE_RE.fullmatch(value):
        return re.sub(r"[.,]", "", value)
    return value


def value_pattern(value: str):
    value = normalise(value)
    if re.fullmatch(r"[0-9]+", value):
        groups, rest = [], value
        while len(rest) > 3:
            groups.insert(0, rest[-3:])
            rest = rest[:-3]
        groups.insert(0, rest)
        plain = LEAD_BOUNDARY + PLAIN_LEAD + value + TRAIL_BOUNDARY + PLAIN_TRAIL
        if len(groups) == 1:
            return re.compile(plain)
        written = (LEAD_BOUNDARY + WRITTEN_LEAD + THOUSANDS_SEP.join(groups)
                   + TRAIL_BOUNDARY + WRITTEN_TRAIL)
        return re.compile(plain + "|" + written)
    parts = [re.escape(p) for p in value.split()]
    body = r"[ \t]+".join(parts)
    head = LEAD_BOUNDARY if value[0].isalnum() else ""
    tail = TRAIL_BOUNDARY if value[-1].isalnum() else ""
    return re.compile(head + body + tail, re.IGNORECASE)


def _within(path, real_root: str) -> bool:
    try:
        real = os.path.realpath(path)
    except OSError:
        return False
    return real == real_root or real.startswith(real_root.rstrip(os.sep) + os.sep)


def read_text(path: Path):
    """The file's text, or None when it is missing, too large or binary."""
    try:
        if os.path.islink(path):
            return None
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
    real_root = os.path.realpath(root)
    holders = []
    for rel in files:
        if not _within(root / rel, real_root):
            continue
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


def printable(name: str) -> str:
    """A file name on one line: control and unprintable characters escaped."""
    return "".join(c if c.isprintable() else c.encode("unicode_escape", "backslashreplace").decode("ascii")
                   for c in name)


def render(values, holders, root: Path) -> str:
    lines = []
    groups = {}
    for h in holders:
        top = h["file"].split("/", 1)[0] if "/" in h["file"] else "."
        groups.setdefault(top, []).append(h)
    for top in sorted(groups):
        lines.append(f"{printable(top)}/" if top != "." else "./")
        for h in groups[top]:
            lines.append(f"  {printable(h['file'])}  hits={h['hits']}  first_line={h['first_line']}")
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
        (repo / "docs" / "lead.md").write_text("Part number 9421 ships.\n", encoding="utf-8")
        (repo / "docs" / "trail.md").write_text("Part number 4210 ships.\n", encoding="utf-8")
        (repo / "cases").mkdir()
        # file -> (text, found by --old 421, found by --old 1421). A 421 that
        # follows a space or an apostrophe is reported for --old 421: that is
        # the stated limit, pinned here so a change to it is a choice.
        cases = {
            "comma_before.md": ("Total 1,421 seats.", False, True),
            "comma_after.md": ("Total 421,000 seats.", False, False),
            "decimal_before.md": ("Ratio 0.421 now.", False, False),
            "decimal_after.md": ("Ratio 421.5 now.", False, False),
            "sentence_end.md": ("Headcount is 421.", True, False),
            "currency.md": ("Costs $421 each.", True, False),
            "percent.md": ("Up 421% since.", True, False),
            "negative.md": ("Delta -421 units.", True, False),
            "suffix.md": ("Model 421-A ships.", True, False),
            "plain_thousands.md": ("Total 1421 seats.", False, True),
            "dot_thousands.md": ("Total 1.421 seats.", False, True),
            "longer_thousands.md": ("Total 11,421 seats.", False, False),
            "thousands_then_more.md": ("Total 1,421,000 seats.", False, False),
            "spaced_then_more.md": ("Total 1 421 000 seats.", True, False),
            "dotted_then_more.md": ("Total 1.421.000 seats.", False, False),
            "spaced_piece.md": ("Total 3 1 421 seats.", True, False),
            "comma_piece.md": ("Total 3,1 421 seats.", True, False),
            "version.md": ("Release 1.421-rc1 shipped.", False, False),
            "apostrophe.md": ("Total 1'421 seats.", True, True),
            "no_break_space.md": ("Total 1\u00a0421 seats.", True, True),
            "narrow_no_break_space.md": ("Total 1\u202f421 seats.", True, True),
            "written_then_dash_space.md": ("Total 1,421 - final.", False, True),
            "ordinal.md": ("Item 421\u00ba listed.", False, False),
        }
        for name, (text, _a, _b) in cases.items():
            (repo / "cases" / name).write_text(text + "\n", encoding="utf-8")
        # "1 421" is its own case: --old 1421 must find it, and --old 421 finds
        # it too (a stated limit), so it stays out of the table above.
        (repo / "spaced").mkdir()
        (repo / "spaced" / "space_thousands.md").write_text("Total 1 421 seats.\n", encoding="utf-8")
        outside = tmp / "outside.md"
        outside.write_text("headcount 421\n", encoding="utf-8")
        linked = True
        try:
            os.symlink(outside, repo / "docs" / "link.md")
            # A link to a holder inside the root would count that holder twice.
            os.symlink(repo / "notes" / "old" / "estimate.md", repo / "docs" / "link_inside.md")
        except (OSError, NotImplementedError):
            linked = False
        # A tracked directory that is later replaced by a link to the outside:
        # git still lists moved/held.md, and the file itself is not a link.
        (repo / "moved").mkdir()
        (repo / "moved" / "held.md").write_text("nothing here\n", encoding="utf-8")
        (tmp / "elsewhere").mkdir()
        (tmp / "elsewhere" / "held.md").write_text("headcount 421\n", encoding="utf-8")
        odd_name = True
        try:
            with open(os.path.join(os.fsencode(str(repo / "docs")), b"odd\xff\xfe.md"), "wb") as fh:
                fh.write(b"headcount 421\n")
        except (OSError, ValueError):
            odd_name = False
        (repo / "docs" / "blob.bin").write_bytes(b"\0\1\2 421 \0")
        (repo / ".gitignore").write_text("ignored.md\n", encoding="utf-8")
        (repo / "ignored.md").write_text("headcount 421\n", encoding="utf-8")
        for args in (["init", "-q"], ["add", "--", "README.md", "docs", "notes", "moved", ".gitignore"]):
            res = _git(args, repo)
            if res.returncode != 0:
                print(f"selftest FAIL: git {args[0]}: "
                      f"{os.fsdecode(res.stderr).strip()}", file=sys.stderr)
                return 1
        # cases/ and spaced/ stay untracked on purpose: untracked files that
        # are not ignored are swept too.
        if linked:
            shutil.rmtree(repo / "moved")
            os.symlink(tmp / "elsewhere", repo / "moved")

        holders = sweep(repo, ["421"])
        if holders is None:
            failures.append("the sweep could not list the repo")
        names = [h["file"] for h in (holders or [])]
        unlinked = [h for h in (holders or []) if h["file"] == "notes/old/estimate.md"]
        if not unlinked:
            failures.append(f"unlinked holder not found: {names}")
        elif unlinked[0]["first_line"] != 2 or unlinked[0]["hits"] != 1:
            failures.append(f"hit count or first line wrong: {unlinked[0]}")
        if "docs/lead.md" in names:
            failures.append("leading boundary: 421 matched inside 9421")
        if "docs/trail.md" in names:
            failures.append("trailing boundary: 421 matched inside 4210")
        if "docs/blob.bin" in names:
            failures.append("binary file was searched")
        if "ignored.md" in names:
            failures.append("ignored file was searched")
        if linked and "docs/link.md" in names:
            failures.append("a symlink to a file outside the root was reported")
        if linked and "docs/link_inside.md" in names:
            failures.append("a symlink to a holder inside the root was reported twice")
        if linked and "moved/held.md" in names:
            failures.append("a file reached through a linked directory outside the root was reported")
        if odd_name and not any(n.startswith("docs/odd") for n in names):
            failures.append(f"the holder with a non-UTF-8 name was not reported: {names}")
        thousands = [h["file"] for h in (sweep(repo, ["1421"]) or [])]
        for name, (text, by_421, by_1421) in cases.items():
            rel = f"cases/{name}"
            if (rel in names) != by_421:
                failures.append(f"--old 421 on {text!r}: expected match={by_421}")
            if (rel in thousands) != by_1421:
                failures.append(f"--old 1421 on {text!r}: expected match={by_1421}")
        if "spaced/space_thousands.md" not in thousands:
            failures.append("--old 1421 did not match the written form '1 421'")
        for written in ("1,421", "1.421"):
            if sorted(h["file"] for h in (sweep(repo, [written]) or [])) != sorted(thousands):
                failures.append(f"--old {written} was not read as the number 1421")
        if value_pattern("1,42").pattern == value_pattern("142").pattern:
            failures.append("'1,42' is not a written thousands form and must stay literal")

        (repo / "odd").mkdir()
        try:
            (repo / "odd" / "two\nlines\x1b.md").write_text("headcount 777\n", encoding="utf-8")
            shown = render(["777"], sweep(repo, ["777"]) or [], repo).splitlines()
            if len(shown) != 3 or "two\\nlines\\x1b.md" not in shown[1]:
                failures.append(f"a control character in a file name broke the listing: {shown}")
        except OSError:
            pass
        line = receipt(["421"], holders or [], repo)
        total = sum(h["hits"] for h in (holders or []))
        if not line.startswith(f"SWEEP-COMPLETE old=1 files={len(names)} hits={total} "):
            failures.append("receipt for a finding is wrong: " + line)

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
    skipped = [label for label, ran in (("symlink", linked), ("non-UTF-8 name", odd_name))
               if not ran]
    print("selftest PASS: unlinked holder found, absent value empty, binary, ignored "
          "and symlinked skipped, non-UTF-8 name swept, 421 not matched inside 9421 "
          "or 4210, 23 numeric cases, 1421 matches 1,421 / 1.421 / 1 421 / 1'421, "
          "written old value normalised, control characters escaped, phrase "
          "case-insensitive"
          + (f" (not run on this filesystem: {', '.join(skipped)})" if skipped else ""))
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
