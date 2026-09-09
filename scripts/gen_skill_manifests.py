#!/usr/bin/env python3
"""gen_skill_manifests.py: mint a `skill.json` per skill from its SKILL.md front matter.

One-shot backfill for the v8 PACKAGE primitive. Every skill directory needs a
manifest so `octo pkg` can reason about identity, vintage and terms, and hand-writing
233 of them is the kind of toil that produces typos, not care.

What it derives:
  name         front-matter `name`, else the directory slug
  version      1.0.0 (the first manifest of an existing skill is its 1.0.0)
  license      the skill's own LICENSE when its terms are recognized; else the
               skill's own front-matter `license:` when it declares one; else the repo
               default, and ONLY when the skill declares nothing and carries no license
               file at all. Anything else present is reported and never defaulted:
               unrecognized terms, terms the bytes will not decode as, a name that
               holds no readable regular file, two license files that disagree, and a
               front-matter declaration that contradicts the license file.
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
and carries no license file, and for every skill that asserts no license at all
(SPDX NOASSERTION). Those are the classes the corpus check cannot see, because there is
no license file to compare against; whether this repo's terms may speak for someone
else's material is a human's call, and the report exists so the question is asked.

Three ways a wrong license used to be written in silence, and where each stands now:

  * The license-name test DECIDES "absent", and absent decides the repo default. A name
    it does not recognize is not "no license here", it is "not looked for", and both
    were written into the manifest as this repo's own terms. The EXTENSION half is no
    longer an allow-list: a name whose words say license is read unless its extension
    says the bytes are code or a binary, so a shape nobody enumerated ends in a refusal
    rather than in a silent default. The STEM half is still a list, and that is the
    RESIDUAL: a license named `TERMS.md` or `EULA.txt` is still read as absent. The
    measured enumeration of the class, with real counts, sits above `_LICENSE_STEMS`.
  * Only MIT and BSD-3-Clause are matched WORD FOR WORD. Apache-2.0, GPL-3.0,
    AGPL-3.0 and MPL-2.0 are anchored at both ends and checked section by section, so
    text spliced in the middle of a 200-line license with the section headings intact
    is not detected. RESIDUAL, and measured: an inserted clause between two intact
    Apache section headings still resolves to Apache-2.0. Prepended, appended and
    clause-count changes are caught for all six, each against a verbatim published text.
  * Front-matter `license:` was WRITTEN by eight skills and READ by nothing. Closed: it
    is compared against the license file and a disagreement is refused, and where there
    is no license file the declaration is honoured instead of being overwritten with
    the repo default.

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
# THE NAME TEST DECIDES "ABSENT", AND ABSENT DECIDES THE REPO DEFAULT. A name this
# function does not recognize is not "no license found", it is "not looked for", and
# both were written into the manifest as the same thing: this repo's own terms over
# somebody else's material.
#
# It used to be two allow-lists, a stem list AND an extension list, and an allow-list
# on the EXTENSION is the wrong polarity for that decision. Missing a member costs a
# silent false legal claim; including one costs a refusal, which is a human being
# asked. The two are not comparable, so the extension is a DENY-list now: a name whose
# words say license holds terms unless its extension says the bytes are code or a
# binary. Polarity alone was not enough, and the first draft of this comment claimed it
# was: EVERY exclusion here is its own road back to the default, because a name this
# test declines is a name nothing reads and `resolve_license` used to answer for it with
# the same `(None, "")` it uses for an empty directory. `license_setaside` closes that,
# and its docstring lists the five shapes that reached MIT in silence before it existed.
# The stems are still an allow-list (that is the residual, named below), but
# they are matched per word part with a trailing version token stripped, so `COPYING`,
# `COPYINGv3`, `COPYING3` and `LICENSES-en` are one shape rather than four entries
# somebody has to think of.
#
# ENUMERATION OF THE CLASS, so the next reader can check the claim without reading the
# code. A SNAPSHOT of one developer machine, not a constant: the counts move as packages
# come and go, and only the SHAPES are the evidence. Reproduce the selection with
#
#   find $HOME /usr/lib/python3 /usr/share/doc -xdev \
#        \( -iname 'licen[cs]e*' -o -iname 'copying*' -o -iname 'unlicen[cs]e*' \
#           -o -iname 'copyright' \) | sed 's#.*/##' | sort | uniq -c | sort -rn
#
# Everything it returned above 40 copies, and what this test does with each:
#
#   8803 LICENSE          2087 COPYING        2041 copyright     1649 LICENSE.txt
#   1284 licenses/        1099 license         777 LICENSE-MIT     723 LICENSE-APACHE
#    609 LICENSE.md        270 LICENSE-MPL-2.0 241 LICENSE.TXT     195 COPYING.LIB
#    187 LICENSE.BSD       178 LICENSE.APACHE  145 COPYRIGHT       113 LICENSES/
#     64 COPYING.LGPL       63 COPYINGv2        63 COPYING.LESSERv3 58 LICENSES-en.txt
#     58 COPYINGv3          53 COPYING.LESSERv2 44 COPYING.LESSER   44 COPYING.GPL
#     41 license.terms
#
# All of them are recognized. The previous revision missed the last seven shapes
# (`COPYING.LIB` at 195 copies, the GNU name for the LGPL, is four times commoner than
# the `COPYING.LESSER` it did cover), which is the failure this file exists to stop:
# closing one member of a class and calling the class closed, where the member left
# open is the more common one.
#
# NOT license files, and each one measured against this test: `LICENSE-3RD-PARTY.txt`,
# `THIRD-PARTY-NOTICES.txt`, `ThirdPartyNotices.txt` (they list OTHER people's terms),
# `NOTICE` (Apache attribution, not a grant), `license.py`, `license.png`,
# `licenseRule.json`, `licensing.md`.
#
# RESIDUAL, and it is the stem list: a license under a name carrying none of these
# words (`TERMS.md`, `EULA.txt`, or `/usr/share/common-licenses/Artistic`, which is
# named after its license and nothing else) is still read as absent and still takes
# the repo default. Nothing here detects that; only reading every file in the
# directory would, and this generator does not.
_LICENSE_STEMS = {"license", "licence", "licenses", "licences", "licenseref",
                  "licenceref", "copying", "unlicense", "unlicence", "copyright"}
# A trailing version token on a stem: `COPYINGv3`, `COPYING3`, `LESSERv2`. It is
# numbering, not a different document, so it is stripped before the stem is matched.
_VERSION_TAIL = re.compile(r"v?\d+(?:[._]\d+)*$")
# Extensions whose bytes are NOT a license document: source code, structured data,
# images, archives and binaries. Deliberately absent: `.pdf`, `.rtf`, `.doc` and every
# other unreadable DOCUMENT format, because a `LICENSE.pdf` holds terms nobody here can
# read, and the honest answer to that is the refusal `read_license` already raises, not
# the silent absence that an extension allow-list produced.
_NON_DOCUMENT_EXTS = {
    "py", "pyc", "pyi", "pyx", "js", "mjs", "cjs", "jsx", "ts", "tsx", "coffee",
    "c", "h", "cc", "cpp", "cxx", "hpp", "cs", "go", "rs", "rb", "java", "kt", "kts",
    "swift", "php", "pl", "pm", "lua", "sh", "bash", "zsh", "fish", "ps1", "psm1",
    "bat", "cmd", "vb", "scala", "clj", "ex", "exs", "erl", "hs", "ml", "dart", "sql",
    "json", "jsonc", "json5", "yaml", "yml", "toml", "ini", "cfg", "conf", "properties",
    "xml", "xsd", "xsl", "plist", "lock", "csv", "tsv", "proto", "graphql", "mk",
    "cmake", "gradle", "gemspec", "podspec", "cabal", "nix", "tf", "tfvars", "bzl",
    "png", "jpg", "jpeg", "gif", "svg", "ico", "webp", "bmp", "tiff", "psd",
    "zip", "gz", "bz2", "xz", "zst", "tar", "tgz", "7z", "rar", "whl", "deb", "rpm",
    "exe", "dll", "so", "dylib", "o", "a", "bin", "wasm", "class", "jar", "pyd",
    "woff", "woff2", "ttf", "otf", "eot", "mp3", "mp4", "wav", "ogg", "webm", "mov",
}
# Directories whose CONTENTS are license documents (the REUSE layout ships every
# license the project uses under `LICENSES/`). A directory named `LICENSE` singular is
# still an error: it is one document's name holding no document.
_LICENSE_DIRS = {"licenses", "licences"}
# Names that say license and are NOT this package's own terms. A notices file lists
# what OTHER people's code in the tree is under; reading it as the skill's license is
# the mirror of the bug above -- it stamps the package with a third party's id.
_NOTICES_TOKENS = {"3rd", "third", "thirdparty", "3rdparty", "party", "parties",
                   "notices", "vendor", "vendored", "bundled", "deps", "dependencies",
                   "exceptions", "aggregate"}
# Preference order only decides which file is REPORTED first. It never decides which
# license governs: two license files that disagree are a question for a human.
_LICENSE_ORDER = ("license.txt", "license", "license.md")

_NAME_SPLIT = re.compile(r"[._\-\s]+")


def _is_notices_name(name: str) -> bool:
    """True for a file that lists OTHER people's terms rather than this package's."""
    parts = set(_NAME_SPLIT.split(name.lower()))
    return bool(parts & _NOTICES_TOKENS)


def _is_license_name(name: str) -> bool:
    """True when this file NAME claims to hold license terms for this package.

    Matched on the name's word parts rather than on a stem prefix, so `LICENSE_APACHE`
    and `APACHE-LICENSE` are seen as readily as `LICENSE-MIT`; the trailing version
    token is stripped, so `COPYINGv3` is `COPYING`; and the extension only EXCLUDES,
    so a shape nobody enumerated fails toward being read and refused rather than
    toward being silently absent.
    """
    low = name.lower()
    if _is_notices_name(low):
        return False
    ext = low.rpartition(".")[2] if "." in low else ""
    if ext in _NON_DOCUMENT_EXTS:
        return False
    return any(_VERSION_TAIL.sub("", part) in _LICENSE_STEMS
               for part in _NAME_SPLIT.split(low))


# --- words, not typography ----------------------------------------------------
# A license is a sequence of WORDS. Everything else on the page -- the quote glyph an
# editor curled, `*AS IS*` in emphasis markers, `'Software'` in single quotes,
# `NON-INFRINGEMENT` with the hyphen, an rst underline, a C comment fence, where the
# lines happen to wrap -- is typography, and typography is not terms. Comparing raw
# text made this recognizer refuse real MIT files over a curled quote and, worse, name a
# cause that was not the difference: a family of packages that writes `'Software'` with
# apostrophes was told its "grant sentence is not MIT's". No percentage is quoted here:
# the only corpus big enough to measure one is a live developer disk, two runs of the
# same selection days apart returned different denominators, and a figure nobody else can
# reproduce is decoration. What IS reproducible is the shape: each glyph in _TRANSLATE
# below was found refusing a real license file, and reverting any of them turns the
# matching test in TestTypographyIsNotTerms red. A refusal that misdiagnoses sends
# whoever fixes it to read the wrong sentence, so the comparison runs over words and the
# refusal names the word that actually differs.
_TRANSLATE = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "«": '"', "»": '"', "′": "'", "″": '"',
    " ": " ", " ": " ", " ": " ", "﻿": "",
    "­": "", "‐": "-", "‑": "-", "‒": "-", "–": "-",
    "—": "-", "―": "-", "−": "-",
})
# A comment fence at the edge of a line. A license shipped inside a source file (`//`,
# `#`, ` * `, `<!-- -->`, a Python docstring) is the same license.
_FENCE_HEAD = re.compile(r"^[ \t]*(?:/\*+|\*+/|//+|<!--|-->|\"\"\"|'''|;+|%+|--(?=\s)|\#+|\*(?!\S))[ \t]*")
_FENCE_TAIL = re.compile(r"[ \t]*(?:\*/|-->|\"\"\"|''')[ \t]*$")
_WORD = re.compile(r"[0-9]+|[a-z]+")
_INTRA_HYPHEN = re.compile(r"(?<=[a-z])-(?=[a-z])")


def _unfence(line: str) -> str:
    """One line with its comment/markup fence removed."""
    prev = None
    out = line.translate(_TRANSLATE)
    while out != prev:
        prev = out
        out = _FENCE_TAIL.sub("", _FENCE_HEAD.sub("", out))
    return out


def words(s: str) -> list[str]:
    """The words of a fragment: lowercased, punctuation dropped, intra-word hyphens
    closed up so NON-INFRINGEMENT and NONINFRINGEMENT are the same word."""
    return _WORD.findall(_INTRA_HYPHEN.sub("", s.translate(_TRANSLATE).lower()))


# --- ornament: what may sit around a license without changing it ---------------
# A title, a copyright line and its holder continuations, an SPDX tag, a horizontal
# rule, an rst underline, a bare URL. None of these grants, restricts or disclaims
# anything. Everything else around the text is text this generator will not vouch for
# and reports by the line it found.
# A line that is nothing but a license's NAME. Checked only OUTSIDE a located license
# body, for the same reason copyright notices are: `Apache License` is this recognizer's
# own start anchor for Apache-2.0, and `TERMS AND CONDITIONS` is a heading inside it, so
# a title dropped unconditionally would delete the anchor it was meant to skip past.
# The MIT-only version of this list refused every BSD-3-Clause file that carries a
# "BSD 3-Clause License" title above its text, which is how most of them ship.
_TITLE_WORDS = frozenset({
    "the", "license", "licence", "licenses", "licensing", "agreement", "terms",
    "conditions", "and", "or", "notice", "information", "text", "copyright",
    "mit", "expat", "bsd", "clause", "apache", "gnu", "general", "public", "affero",
    "lesser", "library", "mozilla", "isc", "zlib", "boost", "artistic", "unlicense",
    "eclipse", "common", "creative", "commons", "python", "openssl", "software",
    "free", "open", "source", "version", "v", "modified", "new", "simplified",
    "revised", "clear", "0", "1", "2", "3", "4", "5", "10", "11", "20", "21", "30",
})


def _is_title_line(ws: list[str]) -> bool:
    """A line that is nothing but a license's NAME.

    "modified" is in the vocabulary because "Modified BSD License" is a published name
    for BSD-3-Clause. It is a name there and a WARNING anywhere else: "Modified MIT
    License" over verbatim MIT text was measured resolving to plain MIT, and a title
    saying the terms were changed is the one line in the document a reader must not
    skip. So the word is a title word only where it names a license, next to bsd.
    """
    if not ws or len(ws) > 8 or not all(w in _TITLE_WORDS for w in ws):
        return False
    return "modified" not in ws or "bsd" in ws


_COPYRIGHT_LINE = re.compile(r"^\s*(?:copyright\b|\(c\)|©|&copy;)", re.I)
_COPYRIGHT_EVIDENCE = re.compile(r"\(c\)|©|&copy;|\b(?:19|20)\d{2}\b|@|https?://", re.I)
_COPYRIGHT_KEYWORD = re.compile(r"\bcopyright\b|\(c\)|©|&copy;", re.I)
_ALL_RIGHTS = re.compile(r"^\s*all\s+rights\s+reserved\.?\s*$", re.I)
_ALL_RIGHTS_TAIL = re.compile(r"\ball\s+rights\s+reserved\b\.?", re.I)
_SPDX_LINE = re.compile(r"^\s*spdx-(?:license-identifier|filecopyrighttext)\s*:", re.I)
# A markdown link-reference definition: `[others]: https://example.com/contributors`.
# It is a link TARGET, so it carries no prose and cannot state terms, and json5 puts one
# under its MIT text. Without this it reaches _name_like, which now requires a
# continuation to continue a copyright notice, and a link definition continues nothing.
_LINK_DEF_LINE = re.compile(r"^\s*\[[^\]]+\]:\s*<?(?:https?://|www\.|mailto:)\S+>?\s*$", re.I)
_BARE_URL_LINE = re.compile(r"^\s*[<(\[]?\s*(?:https?://|www\.)\S+?\s*[>)\]]?\s*[.,]?\s*$", re.I)
# A CONTACT: an address, a handle, a link. It identifies a person or an organisation and
# it is the signal a signature block carries. A YEAR is not one: it is the weakest
# attribution signal there is, and it is exactly what a time limit carries too, which is
# why a year-only line has to earn its place by sitting under a copyright notice while a
# contact line stands on its own wherever it sits.
_CONTACT_SIGNAL = re.compile(r"@|https?://|www\.|<[^>]*>")
_ATTRIB_SIGNAL = re.compile(r"@|https?://|www\.|<[^>]*>|\b(?:19|20)\d{2}\b")
# A second clause on the copyright line. A holder is one phrase, so a full stop followed
# by another word ends the notice and starts a sentence: "Copyright 2020 Foo. Revoked
# 2026." resolved to plain MIT because "Revoked" is capitalised and the lower-case test
# above could not see it. Abbreviations are the exception a name really does carry, so a
# single initial and the corporate forms below do not count as a break.
_SENTENCE_BREAK = re.compile(
    r"(?<!\b[A-Z])(?<!\bInc)(?<!\bLtd)(?<!\bCo)(?<!\bCorp)(?<!\bLLC)(?<!\bJr)"
    r"(?<!\bSr)(?<!\bSt)(?<!\bDr)(?<!\bMr)(?<!\bMs)(?<!\bMrs)\.\s+[A-Z]")
_PARTICLES = frozenset({"van", "von", "de", "del", "der", "den", "di", "da", "dos",
                        "du", "la", "le", "el", "of", "and", "the", "for", "inc",
                        "llc", "ltd", "gmbh", "co", "corp", "et", "al", "bv", "ab"})
# Words that mean the line is saying something about TERMS. Any line carrying one of
# these is never ornament, however name-shaped it otherwise looks: "NON-COMMERCIAL USE
# ONLY" is three capitalised words and it is not a holder.
_TERMS_VOCAB = frozenset({
    "license", "licensed", "licence", "licensing", "permission", "permitted",
    "permit", "granted", "grant", "grants", "restriction", "restrictions",
    "restricted", "prohibited", "prohibit", "forbidden", "warranty", "warranties",
    "liability", "liable", "shall", "must", "may", "not", "no", "only", "use",
    "using", "redistribution", "redistribute", "redistributed", "commercial",
    "noncommercial", "modify", "modified", "copy", "copies", "distribute",
    "distributed", "distribution", "sublicense", "sell", "terms", "conditions",
    "condition", "agreement", "rights", "reserved", "patent", "patents",
    "trademark", "trademarks", "disclaimer", "provided", "subject", "except",
    "evaluation", "confidential", "proprietary", "additional", "clause",
    "obligations", "royalty", "fee", "fees", "attribution", "notwithstanding",
    # Time limits and audience limits. A grant that expires, or that reaches only
    # students, is terms, and none of these words appeared above: "Valid until 2026",
    # "Trial ends 2026", "Expires 2027-01-01", "Academic Purposes 2024" and "Copyright
    # 2020 Foo, exclusively for Acme Inc." were each measured resolving to plain MIT.
    # THIS HALF IS AN ALLOW-LIST AND STAYS INCOMPLETE: the structural rules (a notice is
    # one sentence, a continuation continues a notice) catch the shapes, and a
    # restriction phrased in words nobody listed still reads as a holder. Adding a word
    # here costs a refusal, which is a human reading the line, so err toward adding.
    "expires", "expire", "expired", "expiry", "expiration", "until", "valid",
    "void", "revoked", "revoke", "revocation", "trial", "temporary", "academic",
    "educational", "exclusively", "exclusive", "internal", "personal", "purposes",
    "purpose", "nonprofit", "students", "student",
})


def _name_like(raw: str, ws: list[str]) -> bool:
    """A holder continuation, an indented holder list entry, a signature block.

    Tight on purpose. It is vetoed outright by any word that talks about terms, and it
    needs either an attribution signal (an email, a URL, an angle bracket, a year) or a
    line made only of capitalised name words. "Redistribution prohibited." carries a
    terms word; "  Alice Smith <a@example.com>" does not.

    THE VETO IS AN ALLOW-LIST AND THEREFORE INCOMPLETE, which is the same shape as the
    extension list two hundred lines up. A year is an attribution signal, so any short
    line carrying one and no vocabulary word came through: "Valid until 2026", "Trial
    ends 2026", "Void After 2026", "Expires 2027-01-01", "Academic Purposes 2024" were
    each measured resolving a document to plain MIT. A time limit is terms. So the
    vocabulary is not the only gate any more. `_Doc.outside_is_ornament` requires a
    continuation to actually CONTINUE something: a name-like line counts only when the
    nearest line above it is a copyright notice or another accepted continuation, which
    is what a holder list and a signature block both are and what a restriction floating
    over the license never is. That rule is structural, not a longer word list.
    """
    if not ws or len(ws) > 10:
        return False
    if any(w in _TERMS_VOCAB for w in ws):
        return False
    if _ATTRIB_SIGNAL.search(raw):
        return True
    alpha = re.findall(r"[A-Za-z][A-Za-z'’.-]*", raw)
    return bool(alpha) and all(a[0].isupper() or a.lower() in _PARTICLES for a in alpha)


def _is_copyright_notice(raw: str, ws: list[str]) -> bool:
    """A copyright NOTICE: the keyword, no terms, short.

    "Copyright Steven Loria and contributors" carries no year and is one. "Shellfloat
    is copyright (c) 2020 by Michael Wood." puts the keyword mid-sentence and is one.
    "Neither the name of the copyright holders, nor those of its contributors" is NOT
    one: it is clause three of BSD-3-Clause, and it says "copyright" only in passing.
    Which is why this test never runs on a line inside a license body -- see _Doc.
    """
    # The length cap is generous because the terms vocabulary is what actually does
    # the work here, and because real notices are long: "Copyright (c) 1998-2000 Thai
    # Open Source Software Center Ltd and Clark Cooper" is thirteen words and is the
    # first line of expat's MIT file.
    if not _COPYRIGHT_KEYWORD.search(raw) or len(ws) > 25:
        return False
    body = _ALL_RIGHTS_TAIL.sub("", raw)      # "All rights reserved" ends a notice
    if any(w in _TERMS_VOCAB for w in words(body)):
        return False
    # A notice is ONE clause. The vocabulary veto above is an allow-list, so it passed
    # "Copyright 2020 Foo. Educational purposes." and "Copyright 2020 Foo. Revoked
    # 2026.", both measured resolving their document to plain MIT. A second SENTENCE is
    # structural and catches those without anyone having to think of the word they used.
    # What was tried and REJECTED: requiring every lower-case word to be a particle or a
    # corporate form. It reads well and it refused 139 of 1183 real license files in one
    # sweep, because "Copyright (c) 2017-present, Jon Schlinkert." and "Copyright (c)
    # 2014, Nathan LaFreniere and other contributors" are holders and neither "present"
    # nor "other" belongs on any list somebody would write. A rule that expensive is not
    # a rule, and the residual it would have covered is named in _TERMS_VOCAB instead.
    rest = _COPYRIGHT_KEYWORD.sub("", body, count=1)
    # An address is attribution, not prose: strip contact forms before reading words,
    # or `Alice Smith <alice@example.com>` is refused for the lower-case "example".
    rest = re.sub(r"<[^>]*>|\S+@\S+|https?://\S+|www\.\S+", " ", rest)
    rest = re.sub(r"\(c\)|©|&copy;|\b(?:19|20)\d{2}(?:\s*[-,]\s*(?:19|20)?\d{2,4})*",
                  " ", rest, flags=re.I)
    return not _SENTENCE_BREAK.search(rest)


def _is_ornament(raw: str, ws: list[str]) -> bool:
    """True when this line CANNOT carry terms, wherever it sits: blank, a rule, an rst
    underline, a bare license title, "All rights reserved", an SPDX tag, a bare URL.

    Every test here is anchored to the WHOLE line, and that is the point. A test that
    merely looked for a keyword inside the line deleted clause three of BSD-3-Clause
    from 285 files (it contains the word "copyright") and deleted the wrapped
    "COPYRIGHT HOLDERS BE LIABLE ..." line out of the middle of MIT's own disclaimer,
    and each time the file was then refused for not carrying the clause this function
    had just removed. Nothing that could be terms is dropped from the document. What
    may sit AROUND a license -- a copyright notice, a holder list, a signature -- is
    judged separately, and only once the license body has been located: _Doc.
    """
    if not ws:                                   # blank, ---, ===, ***, an rst underline
        return True
    if (_SPDX_LINE.match(raw.strip()) or _BARE_URL_LINE.match(raw)
            or _LINK_DEF_LINE.match(raw)):
        return True
    return bool(_ALL_RIGHTS.match(raw))


class _Doc:
    """A license document as a word stream that remembers where each word came from.

    Ornament lines contribute no words, so a title, a copyright block or a trailing
    rule cannot decide whether a license is recognized; every other line contributes
    its words AND its line number, so a refusal can quote the line that broke it.
    """

    def __init__(self, text: str):
        self.lines = [_unfence(ln) for ln in text.splitlines()]
        self.words: list[str] = []
        self.at: list[int] = []          # parallel: source line index per word
        self.ornament: list[bool] = []   # per source line
        for i, ln in enumerate(self.lines):
            ws = words(ln)
            orn = _is_ornament(ln, ws)
            self.ornament.append(orn)
            if orn:
                continue
            self.words.extend(ws)
            self.at.extend([i] * len(ws))

    def line_of(self, w_index: int) -> str:
        if not 0 <= w_index < len(self.at):
            return ""
        return self.lines[self.at[w_index]].strip()

    def outside_is_ornament(self, lo: int, hi: int) -> tuple[bool, str]:
        """Is every line contributing a word outside [lo, hi) harmless?

        This is where a copyright notice, a holder list and a signature block are
        allowed, and it runs ONLY here: outside the located license body. Inside it,
        every line is terms and none of them is ever dropped. (True, "") when the text
        around the license says nothing about the terms; otherwise the offending line,
        so the refusal can quote it back.

        THE COST, measured and deliberate: a friendly lead-in is refused too. Sampling
        real refusals on this machine, `archy` ("This software is released under the MIT
        license:"), Node.js ("Node.js is licensed for use as follows:") and LLVM ("The
        LLVM Project is under the Apache License v2.0 with LLVM Exceptions") are all
        refused for a sentence above the license. Two of those three are harmless and
        the third is a real exception that changes the terms, and NOTHING in the text
        tells them apart from "This software is NOT licensed under the terms below".
        So the answer is a refusal a human reads, not a rule that guesses. Widening this
        to admit lead-in sentences reopens the negation hole; do not.
        """
        for i in list(range(0, lo)) + list(range(hi, len(self.words))):
            at = self.at[i]
            raw = self.lines[at]
            ws = words(raw)
            if _is_title_line(ws) or _is_copyright_notice(raw, ws):
                continue
            # A NAME-LIKE LINE EARNS ITS PLACE TWO WAYS, and a year is neither. It
            # carries a contact, which identifies somebody and is what a trailing
            # signature block has; or it continues a copyright notice, which is what a
            # holder list under one is. Without this, "Valid until 2026" and "Trial ends
            # 2026" were holders: short, capitalised, carrying a year, using no word
            # anybody had thought to put in the terms vocabulary.
            if _name_like(raw, ws) and (_CONTACT_SIGNAL.search(raw)
                                        or self._continues_a_notice(at)):
                continue
            return False, f"{'above' if i < lo else 'after'} it, the line " \
                          f"{raw.strip()[:70]!r}"
        return True, ""

    def _continues_a_notice(self, at: int) -> bool:
        """Is the nearest non-blank line above `at` a copyright notice, or itself a
        continuation of one? Walks up through ornament, which is where the blank line
        between a notice and its indented holder list lives.

        THE COST, measured: over 1,183 readable license files this rule flipped exactly
        one from recognized to refused, `azure_cli_telemetry`, whose file opens with the
        product name "Azure CLI" above the copyright block. A bare product-name header
        and "Valid until 2026" are the same shape to any reader that has not been told
        which words are restrictions, and being told is the mechanism this is replacing.
        One refusal a human reads, against an open class of restrictions nobody listed,
        is the trade taken here on purpose.
        """
        i = at - 1
        while i >= 0:
            raw = self.lines[i]
            ws = words(raw)
            if not ws:
                i -= 1
                continue
            if _is_copyright_notice(raw, ws):
                return True
            if _name_like(raw, ws):
                i -= 1
                continue
            return False
        return False


class _Slot:
    """A variable run of words inside a license template: the copyright holder, which
    the SPDX MIT template marks as a variable in the disclaimer ("IN NO EVENT SHALL
    <copyright holders> BE LIABLE") and which real files fill with a company name; or
    the clause enumerator, which real BSD files write as `1.`, as `*`, or not at all.

    A slot absorbs NAMES AND NUMBERING, never terms. Any word in the terms vocabulary
    inside a slot is refused, so a variable-width hole in a template cannot be used to
    smuggle a restriction into the middle of a license this generator then calls clean.
    """

    def __init__(self, lo: int, hi: int, what: str):
        self.lo, self.hi, self.what = lo, hi, what

    def admits(self, ws: list[str]) -> bool:
        return not any(w in _TERMS_VOCAB for w in ws)


def _template(*parts) -> list:
    """A license template: literal word runs with variable slots between them."""
    out = []
    for part in parts:
        out.append(part if isinstance(part, _Slot) else words(part))
    return out


def _match_template(doc: "_Doc", start: int, tmpl: list) -> tuple[int, str]:
    """Match tmpl against doc.words from `start`.

    Returns (end_index, "") on a match, or (-1, why) naming the FIRST word that
    differs, in the license's words and in the file's, with the line it sits on.
    """
    # The FURTHEST the match ever got, and why it stopped there. A slot that simply
    # said "no copyright holder here" hid every divergence downstream of it, so files
    # were refused for a missing holder they plainly carried while the real difference
    # sat later in the sentence and the slot ate the message. The deepest failure is
    # the true one, so it is the one reported.
    best = [-1, ""]

    def fail(at: int, why: str) -> tuple[int, str]:
        if at > best[0]:
            best[0], best[1] = at, why
        return -1, why

    def walk(i: int, k: int) -> tuple[int, str]:
        if k == len(tmpl):
            return i, ""
        part = tmpl[k]
        if isinstance(part, _Slot):
            for n in range(part.lo, part.hi + 1):
                if i + n > len(doc.words):
                    break
                if not part.admits(doc.words[i:i + n]):
                    return fail(i + n - 1,
                                f"puts {' '.join(doc.words[i:i + n])[:60]!r} where the "
                                f"license names only a {part.what}, so it states terms "
                                f"the license does not")
                end, why = walk(i + n, k + 1)
                if end >= 0:
                    return end, why
            return fail(i, f"names no {part.what} where the license has one")
        for j, w in enumerate(part):
            if i + j >= len(doc.words):
                return fail(i + j, f"stops after {len(doc.words) - start} words, before "
                                   f"the license ends; the next word should be {w!r}")
            if doc.words[i + j] != w:
                got = doc.words[i + j]
                where = doc.line_of(i + j)
                return fail(i + j,
                            f"differs from the license text: it should read {w!r} and "
                            f"this file reads {got!r}, on the line {where[:70]!r}")
        return walk(i + len(part), k + 1)

    end, why = walk(start, 0)
    return (end, "") if end >= 0 else (-1, best[1] or why)


def _find(doc: "_Doc", seq: list[str], start: int = 0) -> int:
    """Index of the first occurrence of a word sequence, or -1."""
    n, m = len(doc.words), len(seq)
    if not m:
        return start
    for i in range(start, n - m + 1):
        if doc.words[i:i + m] == seq:
            return i
    return -1


# --- MIT, word for word --------------------------------------------------------
_MIT_TMPL = _template(
    'Permission is hereby granted, free of charge, to any person obtaining a copy '
    'of this software and associated documentation files (the "Software"), to deal '
    'in the Software without restriction, including without limitation the rights '
    'to use, copy, modify, merge, publish, distribute, sublicense, and/or sell '
    'copies of the Software, and to permit persons to whom the Software is '
    'furnished to do so, subject to the following conditions: '
    'The above copyright notice and this permission notice shall be included in all '
    'copies or substantial portions of the Software. '
    'THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR '
    'IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, '
    'FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL',
    _Slot(1, 12, "copyright holder"),
    'BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER '
    'LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, '
    'OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE '
    'SOFTWARE.')
_MIT_OPENING = words("Permission is hereby granted, free of charge")


def mit_diagnosis(text: str) -> tuple[bool, str]:
    """(is_verbatim_mit, why-not).

    The reason is the point, and it has to be the REAL reason. MIT is matched word for
    word from its first word to its last: a spliced restriction, a Commons Clause, an
    appended indemnity and a proprietary EULA that borrows MIT's opening are each
    refused by the word where they diverge, quoted back with the line they sit on.
    An empty reason means the document has no MIT grant at all.
    """
    doc = _Doc(text)
    start = _find(doc, _MIT_OPENING)
    if start < 0:
        return False, ""
    end, why = _match_template(doc, start, _MIT_TMPL)
    if end < 0:
        return False, f"opens with MIT's first words but {why}"
    clean, offender = doc.outside_is_ornament(start, end)
    if not clean:
        return False, (f"carries the MIT text and, {offender}, so it is MIT plus terms "
                       f"MIT does not carry")
    return True, ""


def is_verbatim_mit(text: str) -> bool:
    """True when the document IS the MIT license, header line or not, end to end."""
    return mit_diagnosis(text)[0]


# --- the other recognizers, anchored the same way -------------------------------
# MIT and BSD-3-Clause are short enough to hold word for word. The four long licenses
# are anchored at BOTH ENDS instead: the document must OPEN with the license's own
# title and END with its own last sentence, every numbered section must appear in
# order, and any line carrying terms outside those anchors is a refusal. That is what
# catches the appended Commons Clause, the appended ADDITIONAL TERMS block, the
# "This software is NOT licensed under the terms below" heading and a notices file
# holding several licenses at once -- every one of which the previous `search`-based
# matchers answered with a clean SPDX id.
#
# RESIDUAL, stated because it is the honest half: BETWEEN those anchors the four long
# licenses are checked by section markers, not word for word. A clause rewritten in
# the middle of a 200-line Apache text with every section heading left in place is not
# detected. MIT and BSD-3-Clause carry no such residual.
class _Anchored:
    """A long license: its title, the sections that must appear in order, and every
    form its LAST line legitimately takes.

    `ends` is a LIST because one license has several published shipping forms and a
    single end phrase makes the other forms unrecognized: requests, and everything that
    vendored it, stops at the end of clause 9 with no "END OF TERMS AND CONDITIONS" and
    no appendix, and those are whole copies of the license. The LAST end form that occurs is the document's end; whatever follows
    it has to be ornament.
    """

    def __init__(self, spdx: str, title: str, interior: list[str], ends: list[str]):
        self.spdx = spdx
        self.title = words(title)
        self.interior = [words(s) for s in interior]
        self.ends = [words(e) for e in ends]


_BSD3_TMPL = _template(
    'Redistribution and use in source and binary forms, with or without modification, '
    'are permitted provided that the following conditions are met:',
    _Slot(0, 2, "clause number"),
    'Redistributions of source code must retain the above copyright notice, this '
    'list of conditions and the following disclaimer.',
    _Slot(0, 2, "clause number"),
    'Redistributions in binary form must reproduce the above copyright notice, '
    'this list of conditions and the following disclaimer in the documentation and/or '
    'other materials provided with the distribution.',
    _Slot(0, 2, "clause number"),
    'Neither the name of',
    _Slot(1, 20, "copyright holder"),
    'may be used to endorse or promote products '
    'derived from this software without specific prior written permission.'
    ' THIS SOFTWARE IS PROVIDED BY',
    _Slot(1, 14, "copyright holder"),
    'AS IS AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE '
    'IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE '
    'DISCLAIMED. IN NO EVENT SHALL',
    _Slot(1, 14, "copyright holder"),
    'BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR '
    'CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE '
    'GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) '
    'HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT '
    'LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF '
    'THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.')
_BSD3_OPENING = words("Redistribution and use in source and binary forms")

_ANCHORED = [
    _Anchored("AGPL-3.0-only", "GNU AFFERO GENERAL PUBLIC LICENSE Version 3, 19 November 2007",
              ["TERMS AND CONDITIONS", "0. Definitions.", "2. Basic Permissions.",
               "13. Remote Network Interaction; Use with the GNU General Public License.",
               "15. Disclaimer of Warranty.",
               "17. Interpretation of Sections 15 and 16."],
              ["END OF TERMS AND CONDITIONS",
               "how to apply and follow the GNU AGPL, see"]),
    _Anchored("GPL-3.0-only", "GNU GENERAL PUBLIC LICENSE Version 3, 29 June 2007",
              ["TERMS AND CONDITIONS", "0. Definitions.", "2. Basic Permissions.",
               "15. Disclaimer of Warranty.",
               "17. Interpretation of Sections 15 and 16."],
              ["END OF TERMS AND CONDITIONS",
               "use the GNU Lesser General Public License instead of this License. "
               "But first, please read"]),
    _Anchored("Apache-2.0", "Apache License Version 2.0, January 2004",
              ["TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION",
               "1. Definitions.", "2. Grant of Copyright License.",
               "3. Grant of Patent License.", "4. Redistribution.",
               "5. Submission of Contributions.", "6. Trademarks.",
               "7. Disclaimer of Warranty.", "8. Limitation of Liability.",
               "9. Accepting Warranty or Additional Liability."],
              ["of your accepting any such warranty or additional liability.",
               "END OF TERMS AND CONDITIONS",
               "See the License for the specific language governing permissions and "
               "limitations under the License."]),
    _Anchored("MPL-2.0", "Mozilla Public License Version 2.0",
              ["1. Definitions", "2. License Grants and Conditions",
               "3. Responsibilities", "6. Disclaimer of Warranty",
               "10. Versions of the License"],
              ["Exhibit A - Source Code Form License Notice",
               "This Source Code Form is subject to the terms of the Mozilla Public "
               "License, v. 2.0.",
               "Incompatible With Secondary Licenses, as defined by the Mozilla Public "
               "License, v. 2.0."]),
]


def _anchored_terms(doc: "_Doc") -> tuple[str | None, str]:
    """(SPDX id, why-not) for the four long licenses and BSD-3-Clause."""
    start = _find(doc, _BSD3_OPENING)
    if start >= 0:
        end, why = _match_template(doc, start, _BSD3_TMPL)
        if end < 0:
            return None, (f"opens with the BSD redistribution clause but {why}")
        clean, offender = doc.outside_is_ornament(start, end)
        if not clean:
            return None, (f"carries the BSD-3-Clause text and, {offender}, so it is "
                          f"BSD-3-Clause plus other terms")
        return "BSD-3-Clause", ""

    for spec in _ANCHORED:
        title_at = _find(doc, spec.title)
        if title_at < 0:
            continue
        lead_ok, lead_offender = doc.outside_is_ornament(title_at, len(doc.words))
        if not lead_ok:
            return None, (f"names the {spec.spdx} title and, {lead_offender}, so "
                          f"something is said about these terms outside them")
        cur = title_at + len(spec.title)
        for marker in spec.interior:
            nxt = _find(doc, marker, cur)
            if nxt < 0:
                return None, (f"opens as {spec.spdx} but does not carry "
                              f"{' '.join(marker)[:60]!r} where that license does")
            cur = nxt + len(marker)
        end = -1
        for form in spec.ends:
            at = _find(doc, form, cur - len(spec.interior[-1]))
            while at >= 0:                      # the LAST occurrence of this form
                end = max(end, at + len(form))
                at = _find(doc, form, at + 1)
        if end < 0:
            return None, (f"opens as {spec.spdx} but does not end the way any published "
                          f"form of {spec.spdx} ends")
        clean, offender = doc.outside_is_ornament(title_at, end)
        if not clean:
            return None, (f"carries the {spec.spdx} text and, {offender}, so it is "
                          f"{spec.spdx} plus terms {spec.spdx} does not carry")
        return spec.spdx, ""
    return None, ""


# --- SPDX tags -----------------------------------------------------------------
# SPDX identifiers are CASE-INSENSITIVE by the spec, so `mit` is `MIT`. The `-only` /
# `-or-later` suffix is not decoration either: GPL-3.0-or-later and GPL-3.0-only sit
# over IDENTICAL text, and the tag is the ONLY carrier of the difference. Refusing
# `GPL-3.0-or-later` for "contradicting" a GPL-3 body threw away the one fact the file
# had to give. So the tag and the body are compared by FAMILY, and where they agree
# the TAG wins, because it is the more specific of the two.
_SPDX_CANON = {}
for _id in ("MIT", "Apache-2.0", "BSD-3-Clause", "BSD-2-Clause", "ISC", "MPL-2.0",
            "GPL-2.0-only", "GPL-2.0-or-later", "GPL-3.0-only", "GPL-3.0-or-later",
            "LGPL-2.1-only", "LGPL-2.1-or-later", "LGPL-3.0-only", "LGPL-3.0-or-later",
            "AGPL-3.0-only", "AGPL-3.0-or-later", "Unlicense", "CC0-1.0", "Zlib",
            "BSL-1.0", "EPL-2.0", "PSF-2.0", "OFL-1.1", "Artistic-2.0"):
    _SPDX_CANON[_id.lower()] = _id
# Deprecated ids and their SPDX replacements. `GPL-3.0` was withdrawn precisely
# because it did not say whether "or later" was granted; it is read as the `-only`
# form its replacement names, never invented into `-or-later`.
_SPDX_DEPRECATED = {
    "gpl-2.0": "GPL-2.0-only", "gpl-3.0": "GPL-3.0-only", "agpl-3.0": "AGPL-3.0-only",
    "lgpl-2.1": "LGPL-2.1-only", "lgpl-3.0": "LGPL-3.0-only",
    "gpl-2.0+": "GPL-2.0-or-later", "gpl-3.0+": "GPL-3.0-or-later",
    "agpl-3.0+": "AGPL-3.0-or-later", "lgpl-2.1+": "LGPL-2.1-or-later",
    "lgpl-3.0+": "LGPL-3.0-or-later",
}
_SPDX_DECL = re.compile(r"^\s*\W{0,4}\s*SPDX-License-Identifier:\s*(.+?)\s*$", re.M | re.I)
_BARE_SPDX = re.compile(r"[A-Za-z0-9.+-]+")


def spdx_canon(expr: str) -> str:
    """An SPDX id in its canonical spelling. Case is not information; a deprecated id
    is answered with its published replacement."""
    low = expr.strip().lower()
    low = _SPDX_DEPRECATED.get(low, low)
    return _SPDX_CANON.get(low.lower(), expr.strip())


def spdx_family(ident: str) -> str:
    """The license behind an id, without the `-only` / `-or-later` choice. Two ids in
    one family sit over the same document text."""
    low = spdx_canon(ident).lower()
    for suffix in ("-or-later", "-only", "+"):
        if low.endswith(suffix):
            return low[: -len(suffix)]
    return low


def license_terms(text: str) -> tuple[str | None, str]:
    """(SPDX id, why-not) for a license document.

    A recognizer must key on text that only the real license body carries; anything it
    does not recognize is reported, never guessed, because a wrong license on a
    distributable package is a legal claim about someone else's work.
    """
    doc = _Doc(text)
    ident, why = _anchored_terms(doc)
    if ident is None:
        is_mit, mit_why = mit_diagnosis(text)
        if is_mit:
            ident = "MIT"
        elif mit_why:
            return None, mit_why
        elif why:
            return None, why

    decl = _SPDX_DECL.search(text)
    if decl:
        expr = decl.group(1).strip()
        if not _BARE_SPDX.fullmatch(expr):
            return None, (f"declares the license expression {expr!r}; a manifest carries "
                          f"ONE identifier, and choosing a side of an expression drops "
                          f"the option its author granted")
        canon = spdx_canon(expr)
        if ident is None:
            return None, (f"declares SPDX {expr!r} but does not carry that license's "
                          f"text, so nothing here can be checked against the claim")
        if spdx_family(canon) != spdx_family(ident):
            return None, (f"declares SPDX {canon} while its text is {ident}")
        # The tag is the more specific of the two: it is what carries "or later".
        return canon, ""
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
    """Every entry whose NAME says license, regular file or not, plus the contents of
    a REUSE `LICENSES/` directory.

    Not filtered by is_file(): a dangling symlink, a directory or a socket named
    LICENSE is a file that EXISTS and holds no readable terms. Dropping it here is how
    it silently became "this skill has no LICENSE" and took the repo default.
    """
    try:
        entries = list(skill_dir.iterdir())
    except OSError:
        return []
    # `LICENSES/` is a container of license documents, not a document, and it is read
    # by the loop below. It has to be dropped HERE or the plural stem that makes the
    # name recognizable also makes the directory itself an entry holding no terms,
    # which turns the whole REUSE layout into a refusal. A directory named `LICENSE`
    # singular is still that refusal: that name promises one document and holds none.
    found = [p for p in entries if _is_license_name(p.name)
             and not (p.is_dir() and p.name.lower() in _LICENSE_DIRS)]
    for d in entries:
        if d.is_dir() and d.name.lower() in _LICENSE_DIRS:
            try:
                found.extend(p for p in d.iterdir() if not _is_notices_name(p.name))
            except OSError:
                continue

    def rank(p: Path) -> tuple[int, str]:
        low = p.name.lower()
        return (_LICENSE_ORDER.index(low) if low in _LICENSE_ORDER else len(_LICENSE_ORDER),
                str(p))
    return sorted(found, key=rank)


def _has_license_stem(name: str) -> bool:
    """True when a NAME carries a license word, whatever its extension says."""
    return any(_VERSION_TAIL.sub("", part) in _LICENSE_STEMS
               for part in _NAME_SPLIT.split(name.lower()))


def license_setaside(skill_dir: Path) -> list[str]:
    """Entries this directory holds that say license and that nothing above will READ.

    `license_entries` returns what will be read. It cannot, by itself, tell "there is
    nothing here" from "there is something here and I declined to look at it", and
    collapsing those two is the same bug as reading an unreadable LICENSE as absent,
    one level out: every exclusion above is a road to the repo default.

    Five roads, each measured before this existed, each ending in a silent MIT:
      * an empty `LICENSES/`, or one holding only notices, so the container exists and
        nothing survives the filter;
      * `LICENSE-EXCEPTIONS`, `LICENSE.vendor`, `THIRD-PARTY-LICENSE` as the ONLY
        license-named entry. Excluding a notices file BESIDE a real license is right;
        excluding the only one there is deciding the question by not asking it;
      * `LICENSE.json`, `LICENSE.xml`, `license.yml` holding real license text, dropped
        by the extension deny-list;
      * a license that lives one directory down, `docs/LICENSE.txt`, which the top-level
        scan never sees.

    A set-aside is never adopted as the package's terms: a nested LICENSE usually
    belongs to a bundled sample, and a notices file belongs to somebody else. It only
    stops the default, and only when nothing readable was found beside it.
    """
    out: list[str] = []
    try:
        entries = list(skill_dir.iterdir())
    except OSError:
        return out
    accepted = {p for p in license_entries(skill_dir)}
    for p in entries:
        if p.is_dir() and p.name.lower() in _LICENSE_DIRS:
            try:
                kids = list(p.iterdir())
            except OSError:
                continue
            if not any(k in accepted for k in kids):
                out.append(f"{p.name}/ holds no license document this generator reads")
            continue
        if p not in accepted and _has_license_stem(p.name):
            out.append(p.name)
    for p in skill_dir.rglob("*"):
        if p.is_file() and p.parent != skill_dir and _has_license_stem(p.name):
            out.append(str(p.relative_to(skill_dir)))
    return sorted(set(out))


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
        setaside = license_setaside(skill_dir)
        if setaside:
            return None, (f"holds license-named material this generator does not read "
                          f"({', '.join(setaside[:4])}) and no license file it does, so "
                          f"'no license here' is a guess about files nobody opened; "
                          f"{_HAND}")
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


# --- what a skill says about where it came from --------------------------------
# A REPOSITORY LISTING ANSWERS "WHAT IS THERE NOW". PROVENANCE IS A QUESTION ABOUT A
# DATE, so it is answered against the tree at the commit the material entered, never
# against the current tree. This is not theory: `sandbox-sdk` was published here as
# NOASSERTION, in the license field of a public repo, on the sentence "this name is NOT
# present in https://github.com/cloudflare/skills". The name is absent TODAY because
# upstream renamed the skill on 2026-08-07 (f96bff75); the tree at 60147cbb, the last
# commit before the 2026-05-23 bundle, carries `skills/sandbox-sdk/SKILL.md`, and our
# copy differs from it by one locally appended section. Two API calls with a `ref` would
# have said so, and the check that was run could not have: it asked the wrong question.
# The same trap sits under a GitHub-reported license, which is a classifier's verdict on
# today's file, not the terms: `cloudflare/sandbox-sdk` reads NOASSERTION there and
# Apache-2.0 to this generator, because its LICENSE omits the appendix.
# Provenance markers. Front matter is PARSED AS YAML, not grepped: the old prose regex
# ran over the raw front-matter text, so a block scalar `origin: >-` handed back the
# source ">-" and a list handed back "- https://...". 48 of the 233 skills declare one of
# the keys below and every one of them writes a plain scalar today, so the regex was
# reading them correctly BY LUCK: the first author to reach for `>-` would have had the
# YAML punctuation reported as their origin. A parser reads what the author wrote.
_FM_SOURCE_KEYS = ("origin", "source", "sources", "upstream", "originally-from",
                   "adapted-from", "ported-from", "forked-from", "vendored-from",
                   "derived-from", "based-on", "credits", "attribution", "author",
                   "authors", "original")
# Prose conventions. The first pass looked for three of these and missed eight, which
# is how manifests claiming this repo's MIT over Cloudflare-authored material were
# invisible to a report whose whole job was to see them.
_UPSTREAM_LINE = re.compile(
    r"^[>\s*_#|-]*(?P<lead1>(?:sources?|upstream|origin|original|credits?|attribution)"
    r"\s*:\s*)(?P<t1>\S.*)$"
    r"|^[>\s*_#-]*(?P<lead2>(?:adapted|ported|forked|vendored|copied|taken|borrowed"
    r"|derived)\s+from\s+)(?P<t2>\S.*)$"
    r"|^[>\s*_#-]*(?P<lead3>(?:based on|inspired by|courtesy of|originally from)\s+)"
    r"(?P<t3>\S.*)$", re.I | re.M)
# `Repo: <url>` / `**Repo**: <url>`, the header a skill written ABOUT a third-party
# tool puts under its title, usually with that tool's own license on the next line.
# It is the one provenance convention in this corpus that no other marker sees: three
# skills carry it and nothing else (`agent-browser` names Apache 2.0 in its prose while
# its manifest says MIT), and adding it fires on those three and on no other skill of
# the 233. An EXTERNAL URL is required in the target. 19 skills name an owner/repo-shaped
# URL outside code fences and 10 of those still report no upstream source through any
# marker; none of the 10 writes that URL as the value of a `Repo:` key, because theirs are
# placeholders (`github.com/user/repo` in a `render-deploy` example), catalogues the skill
# installs FROM, or a link list.
_REPO_LINE = re.compile(r"^[>\s*_#|-]*\*{0,2}(?P<lead>repo(?:sitory)?)\*{0,2}"
                        r"\s*:\s*(?P<t>\S.*)$", re.I | re.M)
# A `## Retrieval Sources` heading with external URLs under it is a provenance claim.
# A `| Source |` COLUMN is not, and this is measured rather than assumed: all eight
# `| Source |` rows in this repo are the HEADER row of a multi-column runtime table
# (`| Source | How to retrieve | Use for |`), not one skill's key-and-value provenance
# row. Reading them as upstream material would report `web.dev` as the origin of
# `web-perf`, which is false, and would bury a report that has to stay readable to be
# read. The heading is what separates the two, and it is what the Cloudflare skills
# carry: `_source_section` finds them there, not in the table.
_SOURCE_HEADING = re.compile(
    r"^\s{0,3}#{1,6}\s*(?:retrieval\s+sources?|sources?|credits?|attribution|"
    r"provenance|upstream|origin|acknowledge?ments?)\s*:?\s*$", re.I)
_ANY_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+\S")
_EXTERNAL_URL = re.compile(r"https?://[^\s|)\]>,]+")
# A cross-reference is not a provenance claim. "Based on Section 2.7.2 (445 active SPs
# observed in 1 hour)" points at a paragraph of this same document, and reporting it as
# an upstream source is noise in exactly the report that has to stay readable to be read.
_NOT_A_SOURCE = re.compile(
    r"^(?:section|chapter|table|figure|step|item|appendix|paragraph|line|"
    r"the\s+above|the\s+below|this|that|these|those|it|them|which|what|our|my)\b",
    re.I)
_FENCE_LINE = re.compile(r"^\s*(?:```|~~~)")


def _prose(text: str) -> str:
    """The document with its front matter and its fenced code blocks removed.

    A fence is a template, not a claim. `# Source: <recording webUrl>` inside a shell
    block is an instruction to whoever runs it, and `Source: /etc/profile` is a path;
    reading either as this skill's upstream invents provenance out of sample code.
    """
    lines = text.splitlines()
    if lines and lines[0].startswith("---"):
        for i in range(1, len(lines)):
            if lines[i].startswith("---"):
                lines = lines[i + 1:]
                break
    out, fenced = [], False
    for ln in lines:
        if _FENCE_LINE.match(ln):
            fenced = not fenced
            continue
        out.append("" if fenced else ln)
    return "\n".join(out)


def _flatten(value) -> str:
    """A front-matter value as one line, whatever YAML shape the author used."""
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value.strip())
    if isinstance(value, (list, tuple)):
        return "; ".join(x for x in (_flatten(v) for v in value) if x)
    if isinstance(value, dict):
        return "; ".join(f"{k}: {_flatten(v)}" for k, v in value.items() if _flatten(v))
    return "" if value is None else re.sub(r"\s+", " ", str(value).strip())


def _source_section(body: str) -> str | None:
    """The first external URL under a heading that says these are this skill's
    sources. Returns None when the section names no URL outside this repo."""
    lines = body.splitlines()
    for i, ln in enumerate(lines):
        if not _SOURCE_HEADING.match(ln):
            continue
        for nxt in lines[i + 1:]:
            if _ANY_HEADING.match(nxt):
                break
            url = _EXTERNAL_URL.search(nxt)
            if url:
                return f"{ln.strip('# ').strip()}: {url.group(0)}"
    return None


def upstream_source(skill_dir: Path) -> str | None:
    """What this skill says its material came from, or None.

    Front matter (parsed), then prose outside code fences, then a provenance line in a
    sibling README. A skill that borrowed its material almost always says so somewhere;
    what it had stopped doing is saying so in the three places this function looked.
    """
    text = _read(skill_dir / "SKILL.md")
    if not text:
        return None
    fm = frontmatter(text)
    meta = fm.get("metadata") if isinstance(fm.get("metadata"), dict) else {}
    for key in _FM_SOURCE_KEYS:
        for holder in (meta, fm):
            flat = _flatten(holder.get(key))
            if flat:
                return flat[:200]
    for body in (_prose(text), _prose(_read(skill_dir / "README.md"))):
        for m in _UPSTREAM_LINE.finditer(body):
            g = m.groupdict()
            lead = next((g[k] for k in ("lead1", "lead2", "lead3") if g.get(k)), "")
            target = next((g[k] for k in ("t1", "t2", "t3") if g.get(k)), "")
            target = re.sub(r"\s+", " ", target.strip()).strip("|").strip()
            # The target, not the connector, decides. "Based on Section 2.7.2 (445
            # active SPs observed in 1 hour)" points at a paragraph of this same
            # document, and testing the whole phrase let "Based" answer for "Section".
            if target and not _NOT_A_SOURCE.match(target):
                return re.sub(r"\s+", " ", f"{lead}{target}").strip()[:200]
        # `Repo: <external url>`. The URL is required: without it this marker matches
        # every example command and every placeholder path that happens to say "repo".
        for m in _REPO_LINE.finditer(body):
            target = re.sub(r"\s+", " ", m.group("t").strip()).strip("|").strip()
            if _EXTERNAL_URL.search(target):
                return f"{m.group('lead')}: {target}"[:200]
        found = _source_section(body)
        if found:
            return found[:200]
    # An Author line plus a copyright naming someone else is a provenance claim too,
    # written the way a vendored file writes it.
    for body in (text, _read(skill_dir / "README.md")):
        author = re.search(r"^[>\s*_#-]*authors?\s*:\s*(\S.*)$", _prose(body), re.I | re.M)
        third = re.search(r"^[>\s*_#-]*(copyright\b.*)$", _prose(body), re.I | re.M)
        if author and third:
            return re.sub(r"\s+", " ", f"{author.group(1).strip()} / "
                                        f"{third.group(1).strip()}")[:200]
    return None


# --- what a skill says its own license is --------------------------------------
def declared_license(skill_dir: Path) -> tuple[str | None, str | None]:
    """(canonical SPDX id, raw value) from the skill's own front matter.

    Eight skills WRITE this field (seven at the top level, one under `metadata`) and
    nothing read it. All eight happen to declare MIT, which is also the repo default,
    so nothing visibly diverged: the manifests were right by coincidence, not by
    mechanism. The same code would have written MIT over a `license: Apache-2.0`
    declaration, silently, over someone else's material, in a public repo. It is read
    now. `(None, raw)` means the skill declared something that is not a bare SPDX id,
    which is a claim that must be answered by a human rather than parsed into one.
    """
    text = _read(skill_dir / "SKILL.md")
    if not text:
        return None, None
    fm = frontmatter(text)
    meta = fm.get("metadata") if isinstance(fm.get("metadata"), dict) else {}
    raw = None
    for holder in (fm, meta):
        value = holder.get("license") or holder.get("licence")
        if isinstance(value, str) and value.strip():
            raw = value.strip()
            break
    if raw is None:
        return None, None
    return (spdx_canon(raw) if _BARE_SPDX.fullmatch(raw) else None), raw


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
    declared, raw = declared_license(skill_dir)
    if raw is not None and declared is None:
        return None, (f"its front matter declares the license {raw!r}, which is not a "
                      f"bare SPDX identifier, so what the manifest should carry is a "
                      f"reading of that sentence and not a parse of it; {_HAND}")
    if declared and lic and spdx_family(declared) != spdx_family(lic):
        return None, (f"its front matter declares {declared} while its license file "
                      f"says {lic}; a skill that contradicts its own license file is "
                      f"not resolved by preferring one of them, {_HAND}")
    # No license file and a declaration: the declaration is the claim, and it stands.
    # Overwriting it with the repo default is how `license: Apache-2.0` became a
    # published MIT claim over someone else's material without anyone deciding to.
    lic = lic or declared
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
    skipped, problems, upstream, unasserted = [], [], [], []

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
        if (declared_license(skill_dir)[0] or "").upper() == "NOASSERTION":
            unasserted.append((skill_dir.name, src or "no source recorded"))
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

    # NOASSERTION is SPDX's own token for "the preparer has made no assertion", and it
    # is the only honest value where the evidence names two licenses and settles on
    # neither. It is printed on every run so it cannot quietly become the answer: an
    # unanswered question that nothing repeats is an answered one.
    if unasserted:
        print(f"\n{len(unasserted)} skill(s) assert NO license (SPDX NOASSERTION). Each "
              f"is third-party material whose terms this repo could not establish, and "
              f"each is a question still open for a human:")
        for name, src in unasserted:
            print(f"  [NOASSERTION] {name}: {src}")

    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
