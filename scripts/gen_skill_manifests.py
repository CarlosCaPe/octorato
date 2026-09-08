#!/usr/bin/env python3
"""gen_skill_manifests.py: mint a `skill.json` per skill from its SKILL.md front matter.

One-shot backfill for the v8 PACKAGE primitive. Every skill directory needs a
manifest so `octo pkg` can reason about identity, vintage and terms, and hand-writing
233 of them is the kind of toil that produces typos, not care.

What it derives:
  name         front-matter `name`, else the directory slug
  version      1.0.0 (the first manifest of an existing skill is its 1.0.0)
  license      the skill's own LICENSE when its terms are recognized, else the repo
               default when the skill has NO license file at all. Anything else that
               is present is reported and never defaulted: unrecognized terms, terms
               the bytes will not decode as, a name that holds no readable regular
               file, and two license files that disagree.
  description  front-matter `description`, else `metadata.short-description`,
               else the first markdown heading
  kind         skill

What it deliberately does NOT write: `tree_sha256` and `signature`. An in-repo skill
changes on every edit, so a hash embedded in it would be stale within the hour and a
stale hash reads as a tampered tree. The hash and the signature are minted at
PUBLISH time, when a version is cut, by whoever holds the release key.

Dry-run by default (brain rule: destructive operations preview, live execution is
opt-in). `--write` performs it; an existing manifest is left alone unless `--force`.

All or none. Every skill is described before anything is written, so a run that cannot
describe one of them writes NONE and exits 1. Writing inside the loop left the manifests
the run had already reached on disk while the report said nothing was written.

It also prints a report, never a refusal, for every skill that names an upstream source
and carries no license file. Those take the repo default and the corpus check has no
license file to compare against, so the class is invisible unless something names it.
Whether this repo's terms may speak for someone else's material is a human's call.

    python3 scripts/gen_skill_manifests.py --root skills --dry-run
    python3 scripts/gen_skill_manifests.py --root skills --write
    python3 scripts/gen_skill_manifests.py --root <tmpdir> --write --only sample-package

Exit codes: 0 ok, 1 at least one skill could not be described, 2 usage error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

BRAIN = Path(__file__).resolve().parent.parent
SKIP_DIRS = {"vendor", "learned"}

# --- license recognition -----------------------------------------------------
# LICENSE file names we look for. Matched case-insensitively (`LICENSE.TXT` is the
# same document as `LICENSE.txt`, and a case-sensitive lookup that silently misses it
# reads exactly like "this skill has no LICENSE"), and by STEM rather than by an exact
# list, so `COPYING` (the GNU convention) and `LICENSE-MIT` (the dual-licensed
# convention) are seen. A name that says license and is not read is the same blind
# spot as a name that is never looked for.
_LICENSE_STEMS = {"license", "licence", "copying"}
_LICENSE_EXTS = {"", "txt", "md", "rst"}
# Preference order only decides which file is REPORTED first. It never decides which
# license governs: two license files that disagree are a question for a human.
_LICENSE_ORDER = ("license.txt", "license", "license.md")


def _is_license_name(name: str) -> bool:
    low = name.lower()
    stem, dot, ext = low.rpartition(".")
    if not dot:
        stem, ext = low, ""
    return stem.split("-", 1)[0] in _LICENSE_STEMS and ext in _LICENSE_EXTS


def _sentence_rx(text: str) -> str:
    """Regex source for one literal license sentence: the exact words in the exact
    order, indifferent to how the file wraps them and to the quote glyph an editor
    may have curled."""
    rx = r"\s+".join(re.escape(w) for w in text.split())
    return rx.replace('"', "[\"“”]?")


# The MIT license, in full. The recognizer is a WHOLE-DOCUMENT match, not three
# prefix probes: a grant sentence anchored only through "obtaining a copy" accepts a
# proprietary evaluation EULA that opens with those words, and an as-is clause matched
# by prefix accepts an indemnity appended after it. Both of those ARE the false claim
# this generator exists to refuse, so the document must be MIT from its first word to
# its last, and any text spliced in or appended is a reason to report, not to relabel.
_MIT_GRANT_TEXT = (
    'Permission is hereby granted, free of charge, to any person obtaining a copy '
    'of this software and associated documentation files (the "Software"), to deal '
    'in the Software without restriction, including without limitation the rights '
    'to use, copy, modify, merge, publish, distribute, sublicense, and/or sell '
    'copies of the Software, and to permit persons to whom the Software is '
    'furnished to do so, subject to the following conditions:')
_MIT_NOTICE_TEXT = (
    'The above copyright notice and this permission notice shall be included in all '
    'copies or substantial portions of the Software.')
_MIT_DISCLAIMER_TEXT = (
    'THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR '
    'IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, '
    'FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE '
    'AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER '
    'LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, '
    'OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE '
    'SOFTWARE.')

_MIT_GRANT = re.compile(_sentence_rx(_MIT_GRANT_TEXT), re.I)
_MIT_NOTICE = re.compile(_sentence_rx(_MIT_NOTICE_TEXT), re.I)
_MIT_DISCLAIMER = re.compile(
    _sentence_rx(_MIT_DISCLAIMER_TEXT).replace(
        r"AUTHORS\s+OR\s+COPYRIGHT\s+HOLDERS", r"AUTHORS?\s+OR\s+COPYRIGHT\s+HOLDERS?"),
    re.I)
# The first six words of the grant. Present without the rest, they mean the document
# borrows MIT's opening and then says something else, which is worth a different
# message than "unrecognized": it tells whoever fixes it where to look.
_MIT_OPENING = re.compile(r"Permission is hereby granted, free of charge", re.I)

# Lines that may sit ABOVE the license body without changing what it says: a title,
# a markdown heading, an SPDX tag line, a copyright line, a reservation-of-rights
# line. Everything else above the grant is text this generator will not vouch for.
_MIT_PREAMBLE = re.compile(
    r"^\s*#*\s*(?:the\s+)?mit\s+license(?:\s*\(mit\))?\s*$"
    r"|^\s*\W{0,4}\s*spdx-license-identifier:\s*[\w.+-]+\s*$"
    r"|^\s*copyright\b"
    r"|^\s*all rights reserved\.?\s*$", re.I)

_SPDX_DECL = re.compile(r"^\s*\W{0,4}\s*SPDX-License-Identifier:\s*(.+?)\s*$", re.M | re.I)
_BARE_SPDX = re.compile(r"[A-Za-z0-9.+-]+")

_WS = re.compile(r"\s+")


def _line(text: str) -> re.Pattern:
    """A line that is nothing but this text. A `search` for a license title matches
    'This software is NOT licensed under the Apache License, Version 2.0' and hands
    back Apache-2.0; a line anchor does not."""
    return re.compile(r"^[ \t]*" + _sentence_rx(text) + r"[ \t]*$", re.M | re.I)


def _phrase(text: str) -> re.Pattern:
    return re.compile(_sentence_rx(text), re.I)


# A license is recognized by markers that only its real, whole text carries: the title
# LINE plus something from deep inside the terms. A grant NOTICE that merely names a
# license ("GNU GENERAL PUBLIC LICENSE Version 3 or any later version") is not that
# license's text, and answering it with a single SPDX id both invents the text and
# drops the "or later" the notice actually granted.
_SPDX_TEXTS = [
    ("AGPL-3.0-only", [_line("GNU AFFERO GENERAL PUBLIC LICENSE"),
                       _line("Version 3, 19 November 2007"),
                       _line("TERMS AND CONDITIONS")]),
    ("GPL-3.0-only", [_line("GNU GENERAL PUBLIC LICENSE"),
                      _line("Version 3, 29 June 2007"),
                      _line("TERMS AND CONDITIONS")]),
    ("Apache-2.0", [_line("Apache License"),
                    _line("Version 2.0, January 2004"),
                    _line("TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION")]),
    ("MPL-2.0", [_line("Mozilla Public License Version 2.0"),
                 _line("1. Definitions")]),
    ("BSD-3-Clause", [_phrase("Redistribution and use in source and binary forms"),
                      _phrase("Neither the name of"),
                      _phrase("THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS")]),
]


def mit_body(text: str) -> str:
    """The document with its title/SPDX/copyright preamble removed and its whitespace
    normalized, so line wrapping cannot decide whether a license is recognized."""
    lines = text.lstrip("\ufeff").splitlines()
    i = 0
    while i < len(lines) and (not lines[i].strip() or _MIT_PREAMBLE.match(lines[i])):
        i += 1
    return _WS.sub(" ", "\n".join(lines[i:])).strip()


def mit_diagnosis(text: str) -> tuple[bool, str]:
    """(is_verbatim_mit, why-not).

    The reason is the point. A document that borrows MIT's opening and then reserves
    every right is not "unrecognized terms": it is MIT plus something, and saying so
    sends the reader to the sentence that differs instead of to the whole file.
    An empty reason means the document has no MIT grant at all.
    """
    body = mit_body(text)
    m = _MIT_GRANT.match(body)
    if not m:
        if _MIT_GRANT.search(body):
            return False, ("carries text above the MIT grant, so it is MIT with terms "
                           "stacked on top of it, not MIT")
        if _MIT_OPENING.search(body):
            return False, ("opens with MIT's first words and then grants something "
                           "else; its grant sentence is not MIT's")
        return False, ""
    rest = body[m.end():].lstrip()
    m = _MIT_NOTICE.match(rest)
    if not m:
        return False, "has an MIT grant but not MIT's permission-notice clause"
    rest = rest[m.end():].lstrip()
    m = _MIT_DISCLAIMER.match(rest)
    if not m:
        return False, "has an MIT grant but not MIT's warranty disclaimer"
    tail = rest[m.end():].strip()
    if tail:
        return False, (f"continues past the end of the MIT text with {tail[:60]!r}, so it "
                       f"adds terms MIT does not carry")
    return True, ""


def is_verbatim_mit(text: str) -> bool:
    """True when the document IS the MIT license, header line or not, end to end."""
    return mit_diagnosis(text)[0]


def license_terms(text: str) -> tuple[str | None, str]:
    """(SPDX id, why-not) for a license document.

    A recognizer must key on text that only the real license body carries; anything it
    does not recognize is reported, never guessed, because a wrong license on a
    distributable package is a legal claim about someone else's work.
    """
    ident = None
    for candidate, markers in _SPDX_TEXTS:
        if all(rx.search(text) for rx in markers):
            ident = candidate
            break
    if ident is None:
        is_mit, why = mit_diagnosis(text)
        if is_mit:
            ident = "MIT"
        elif why:
            return None, why

    decl = _SPDX_DECL.search(text)
    if decl:
        expr = decl.group(1).strip()
        if not _BARE_SPDX.fullmatch(expr):
            return None, (f"declares the license expression {expr!r}; a manifest carries "
                          f"ONE identifier, and choosing a side of an expression drops "
                          f"the option its author granted")
        if ident is None:
            return None, (f"declares SPDX {expr!r} but does not carry that license's "
                          f"text, so nothing here can be checked against the claim")
        if expr != ident:
            return None, (f"declares SPDX {expr!r} while its text is {ident}")
    if ident is None:
        return None, "carries terms this generator does not recognize"
    return ident, ""


def spdx_of(text: str) -> str | None:
    return license_terms(text)[0]


class LicenseUnreadable(Exception):
    """A LICENSE file is present but its terms could not be read."""


class LicenseUndecodable(LicenseUnreadable):
    """A LICENSE file is present and its bytes are not text this generator can read.

    A distinct class because the CAUSE has to be right in the report: a UTF-16 or
    binary LICENSE answered with "does not recognize the terms" sends whoever fixes it
    to read a document nobody could decode.
    """


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def read_license(p: Path) -> str:
    """Read a LICENSE. Raises instead of returning '': present-and-unreadable is not
    the same fact as absent, and collapsing the two is how a package gets stamped with
    a license nobody ever looked at. Decoding is STRICT for the same reason: bytes
    replaced by U+FFFD are bytes nobody read."""
    try:
        raw = p.read_bytes()
    except OSError as e:
        raise LicenseUnreadable(str(e)) from e
    if b"\x00" in raw:
        raise LicenseUndecodable("contains NUL bytes, so it is not UTF-8 text "
                                 "(UTF-16 or binary)")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise LicenseUndecodable(f"not valid UTF-8 at byte {e.start}") from e
    # Reading bytes means universal newlines are ours to do. A CRLF LICENSE is the same
    # document as an LF one, and a line anchor that trips over a trailing \r would call
    # every Windows-checked-out Apache file unrecognized.
    return text.replace("\r\n", "\n").replace("\r", "\n")


def license_entries(skill_dir: Path) -> list[Path]:
    """Every entry whose NAME says license, regular file or not.

    Not filtered by is_file(): a dangling symlink, a directory or a socket named
    LICENSE is a file that EXISTS and holds no readable terms. Dropping it here is how
    it silently became "this skill has no LICENSE" and took the repo default.
    """
    try:
        entries = list(skill_dir.iterdir())
    except OSError:
        return []
    def rank(p: Path) -> tuple[int, str]:
        low = p.name.lower()
        return (_LICENSE_ORDER.index(low) if low in _LICENSE_ORDER else len(_LICENSE_ORDER),
                p.name)
    return sorted((p for p in entries if _is_license_name(p.name)), key=rank)


def license_file(skill_dir: Path) -> Path | None:
    """The skill's preferred READABLE license file, or None. Callers that must not
    default on a license they could not read want resolve_license, which answers about
    every candidate rather than the first openable one."""
    for p in license_entries(skill_dir):
        if p.is_file():
            return p
    return None


_HAND = ("write the manifest's license by hand "
         "(the repo default would be a false claim)")


def resolve_license(skill_dir: Path) -> tuple[str | None, str]:
    """(SPDX id, problem) for a directory.

    (None, "") is the ONLY road to a default: it means no entry in this directory is
    named like a license, so there are no terms here to contradict the repo's own.
    Every other state answers for itself.
    """
    entries = license_entries(skill_dir)
    if not entries:
        return None, ""
    derived: dict[str, str] = {}
    for p in entries:
        if not p.is_file():
            what = ("a dangling symlink" if p.is_symlink() else
                    "a directory" if p.is_dir() else "not a regular file")
            return None, (f"{p.name} is present but is {what}, so it holds no terms to "
                          f"read; {_HAND}")
        try:
            text = read_license(p)
        except LicenseUndecodable as e:
            return None, f"{p.name} is present but is not readable text ({e}); {_HAND}"
        except LicenseUnreadable as e:
            return None, (f"{p.name} is present but unreadable ({e}); its terms cannot "
                          f"be defaulted, {_HAND}")
        ident, why = license_terms(text)
        if ident is None:
            return None, f"{p.name} {why}; {_HAND}"
        derived.setdefault(ident, p.name)
    if len(derived) > 1:
        pairs = "; ".join(f"{f} says {i}" for i, f in sorted(derived.items()))
        return None, (f"its license files disagree ({pairs}). Which one governs the "
                      f"package is not a preference order, {_HAND}")
    return next(iter(derived)), ""


def frontmatter(text: str) -> dict:
    """Parse the YAML front matter block. Returns {} when there is none."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    try:
        import yaml
        data = yaml.safe_load(text[3:end])
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def first_heading(text: str) -> str:
    for line in text.splitlines():
        m = re.match(r"^#+\s+(.+)", line)
        if m:
            return m.group(1).strip()
    return ""


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(name).strip().lower()).strip("-")
    return re.sub(r"-{2,}", "-", s)


# Markers a skill uses to say its material came from somewhere else. Front matter
# first (`metadata.source`), then the prose conventions ("Source: <url>", "Adapted
# from <project>"). None of these is a license, which is exactly the point: a skill
# that names an upstream and ships no LICENSE takes the repo default, and the corpus
# check that compares declared-vs-derived has nothing to compare.
_UPSTREAM_LINE = re.compile(
    r"^[>\s*_-]*(?:source|upstream|origin)\s*:\s*(\S.*)$"
    r"|^[>\s*_-]*(adapted from\s+\S.*)$"
    r"|^[>\s*_-]*(?:based on|derived from)\s+(\S.*)$", re.I | re.M)


def upstream_source(skill_dir: Path) -> str | None:
    """What this skill says its material came from, or None."""
    text = _read(skill_dir / "SKILL.md")
    if not text:
        return None
    fm = frontmatter(text)
    meta = fm.get("metadata") if isinstance(fm.get("metadata"), dict) else {}
    for value in (meta.get("source"), meta.get("upstream"), fm.get("source")):
        if isinstance(value, str) and value.strip():
            return re.sub(r"\s+", " ", value.strip())[:200]
    m = _UPSTREAM_LINE.search(text)
    if m:
        found = next(g for g in m.groups() if g)
        return re.sub(r"\s+", " ", found.strip())[:200]
    return None


def describe(skill_dir: Path, default_license: str) -> tuple[dict | None, str]:
    """Return (manifest, problem). manifest is None when the skill cannot be described."""
    md = skill_dir / "SKILL.md"
    text = _read(md)
    if not text:
        return None, "SKILL.md unreadable or empty"
    fm = frontmatter(text)
    meta = fm.get("metadata") if isinstance(fm.get("metadata"), dict) else {}

    name = slugify(fm.get("name") or skill_dir.name)
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) or not 2 <= len(name) <= 64:
        return None, f"cannot derive a valid slug from '{fm.get('name') or skill_dir.name}'"

    desc = (fm.get("description") or meta.get("short-description")
            or meta.get("description") or first_heading(text) or "").strip()
    desc = re.sub(r"\s+", " ", desc)[:1024]
    if not desc:
        return None, "no description in front matter and no heading to fall back on"

    # Absent LICENSE -> the repo default, which is what every file in this repo is under.
    # Anything else present -> its own terms or a report. resolve_license answers about
    # EVERY license-named entry in the directory, so an unreadable one, an undecodable
    # one, a name that holds no terms at all and two files that disagree each get their
    # own sentence instead of collapsing into "this skill has no LICENSE".
    lic, problem = resolve_license(skill_dir)
    if problem:
        return None, problem
    manifest = {
        "kind": "skill",
        "name": name,
        "version": "1.0.0",
        "license": lic or default_license,
        "description": desc,
    }
    return manifest, ""


def repo_default_license(root: Path) -> str | None:
    """The repo's own license, or None when it cannot be established.

    None, never a constant. The old fallback returned "MIT" when the repo LICENSE was
    missing or unrecognized, which is the same guess this generator refuses to make for
    a skill, only about the file the default itself comes from.
    """
    return resolve_license(root)[0]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="skills",
                    help="directory of skill dirs (default: skills, relative to the brain)")
    ap.add_argument("--only", nargs="*", help="restrict to these skill directory names")
    ap.add_argument("--write", action="store_true", help="actually write (default: preview)")
    ap.add_argument("--dry-run", action="store_true", help="explicit no-op preview (the default)")
    ap.add_argument("--force", action="store_true", help="overwrite an existing skill.json")
    ap.add_argument("--default-license",
                    help="SPDX id when a skill has no LICENSE (default: the repo's)")
    args = ap.parse_args(argv if argv is not None else sys.argv[1:])

    root = Path(args.root)
    if not root.is_absolute():
        root = BRAIN / root
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2

    default_license = args.default_license or repo_default_license(BRAIN)
    if not default_license:
        print(f"error: cannot establish the repo default license from {BRAIN}; "
              f"pass --default-license <SPDX id>", file=sys.stderr)
        return 2
    only = set(args.only or [])
    planned: list[tuple[Path, dict]] = []
    skipped, problems, upstream = [], [], []

    # Two passes on purpose. Writing inside the loop made a failing run leave the
    # manifests it had already reached on disk, so the run reported "nothing was
    # written" while the tree said otherwise. Every skill is described first; only a
    # run with no problems writes, and it writes all of them or none.
    for skill_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        if skill_dir.name in SKIP_DIRS or skill_dir.is_symlink():
            continue
        if only and skill_dir.name not in only:
            continue
        if not (skill_dir / "SKILL.md").is_file():
            continue
        src = upstream_source(skill_dir)
        if src and not license_entries(skill_dir):
            upstream.append((skill_dir.name, src))
        target = skill_dir / "skill.json"
        if target.exists() and not args.force:
            skipped.append(skill_dir.name)
            continue
        manifest, problem = describe(skill_dir, default_license)
        if manifest is None:
            problems.append(f"{skill_dir.name}: {problem}")
            continue
        planned.append((target, manifest))

    wrote = 0
    if args.write and not problems:
        for target, manifest in planned:
            target.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                              encoding="utf-8")
            wrote += 1

    verb = "wrote" if wrote else "would write"
    print(f"{verb} {len(planned)} manifest(s); {len(skipped)} already had one; "
          f"{len(problems)} need a hand-written manifest")
    for problem in problems:
        print(f"  [needs hand] {problem}")
    if problems:
        print("  nothing was written: a run that cannot describe every skill it was "
              "asked about writes none of them, so the tree never disagrees with the "
              "exit code.")
    elif not args.write:
        print("  preview only. Re-run with --write to apply.")

    # A report, never a refusal. A skill that names an upstream source and ships no
    # LICENSE takes the repo default, and the corpus check cannot see it precisely
    # because there is no license file to compare against. Whether this repo's own
    # terms may speak for someone else's material is a question for a human; the
    # generator's job is to stop the question from being invisible.
    if upstream:
        print(f"\n{len(upstream)} skill(s) declare an upstream source and carry no "
              f"license file, so each takes the repo default ({default_license}). "
              f"Nothing here is wrong by construction and nothing here was checked:")
        for name, src in upstream:
            print(f"  [upstream, no LICENSE] {name}: {src}")

    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
