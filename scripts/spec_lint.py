#!/usr/bin/env python3
"""spec_lint.py: the deterministic reader of a v9 spec (Spec-Format: ears-1).

v9 makes "done" a verdict computed against a spec. That only works if a script
can read the spec, so acceptance criteria are written in EARS and plan tasks
follow one grammar. This CLI is the reader. It uses the standard library only
and makes no model call: the same input gives the same answer on every machine.

What it checks, per spec directory (a `feature.md`, optionally a `plan.md`):

  feature.md
    - any header-shaped `Spec-Format` line opts the file in; without one it is
      SKIPPED (exit 0), so specs written before v9 never break, and a sentence
      that merely mentions it does not opt in
    - the `Spec-Format` and `Status` headers are exactly `> **Spec-Format:** ears-1`
      and `> **Status:** draft|approved|converged`, once each, in the first 30
      lines; any other header-shaped form is a finding, because the push gate
      reads only the canonical one
    - a `## Glossary` section with at least one `- **Name**:` entry (names are
      letters, digits, `_` and `-`)
    - `## Acceptance Criteria` holds at least one criterion, and EVERY non-blank
      line in it is a `- [ ] AC-##: ` item with a unique id; prose there is a
      finding, because a criterion demoted to prose would drop out of coverage
    - every criterion is one EARS sentence whose subject is a Glossary name:
        THE <X> SHALL ...                    (ubiquitous)
        WHEN <trigger>, THE <X> SHALL ...    (event)
        WHILE <state>, THE <X> SHALL ...     (state)
        WHERE <feature>, THE <X> SHALL ...   (optional)
        IF <condition>, THEN THE <X> SHALL ...(unwanted behaviour)
    - at most 3 NEEDS CLARIFICATION markers; with --ready, zero. A marker is
      `[NEEDS CLARIFICATION]` or `[NEEDS CLARIFICATION: ...]`, any case, and
      may span lines

  plan.md (when present)
    - every task line is `- [ ] T## [AC-##, AC-##] <path>, <path>: <action>`;
      a `*` or `+` bullet that looks like a task is a finding, not a skip, and
      paths are separated by `, ` and contain no spaces or commas
    - task ids are unique; at least one and at most 20 tasks sit above the first
      `## Convergence` heading, and Convergence sections come last (converge
      passes append there). Residual, stated: the linter cannot tell who wrote a
      Convergence section, so an author who writes one by hand moves tasks past
      the cap; the converge receipt (v9 phase 3) is what ties those sections to
      a converge pass
    - every criterion is referenced by at least one task, and every referenced
      criterion exists

Markers, criteria and task lines inside fenced code blocks (``` or ~~~) are not
read, and markers inside inline code spans are not counted, so a document can
quote the grammar without tripping it.

Push gate (v9 phase 3, called by .githooks/pre-push once per pushed ref):
  spec_lint.py --push-range <base-sha> <head-sha>
    - lints, at <head>, every ears-1 spec whose feature.md or plan.md the range
      changes (AC-15)
    - for every ears-1 spec whose `Status:` header becomes `converged` in the
      range, requires a plan.md and the latest anchored converge receipt for
      that spec directory to say CONVERGED, with a transcript timestamp newer
      than the newest code commit on the branch (AC-14)
    - refuses a spec that stops being ears-1, and a docs/specs/ directory not
      named <yyyymmddHHMM>-<slug>
    The pushed head is compared, as one tree diff, with its merge base with the
    default remote branch, so the check covers what the branch changes, on every
    push of it. Without a default remote branch the comparison falls back to what
    the remote ref holds (<base>). Commit order and merge commits do not matter. The receipt lives in this machine's ledger, so the machine that
    ran the converge pass is the one that pushes the status change.

Usage:
  spec_lint.py [--ready] <spec-dir | feature.md> [...]
  spec_lint.py --push-range <base> <head>
  spec_lint.py --selftest registry/fixtures/FLOW.spec-contract
  spec_lint.py --selftest registry/fixtures/FLOW.done-is-a-verdict

Exit: 0 clean or skipped, 1 findings, 2 usage error.

Selftest: each subdirectory of the fixture dir is one case. `violation*` cases
must exit 1 and, when they carry an `expect.txt`, print that substring, so a
violation that fails for the wrong reason does not count. `benign*` cases must
exit 0. A case may carry an `args` file with extra flags (for example --ready).
A case that carries a `push.json` is a push scenario instead: the selftest builds
a throwaway git repository and a throwaway HOME with a receipt ledger, and runs
the push check against it.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

MAX_MARKERS = 3
MAX_TASKS = 20

HEAD_LINES = 30
STATUSES = ("draft", "approved", "converged")
# The canonical header lines. Anything header-SHAPED that is not exactly one of
# these is a finding, because the push gate reads only the canonical form: a
# spec that wrote `**Status**: converged` used to flip unseen (QA of v9 phase 3).
_CANON_FORMAT = re.compile(r"^> \*\*Spec-Format:\*\* ears-1\s*$")
_CANON_STATUS = re.compile(r"^> \*\*Status:\*\* (draft|approved|converged)\s*$")
# Header-shaped: optional quote/list/table markers and emphasis, the key, emphasis,
# a colon or a table bar, then a value this format recognises. Prose that merely
# mentions the key ("This spec does not use Spec-Format: ears-1") is not a header.
# Only `ears-1` opts in: a header naming another version (`ears-2`) does not declare
# this format, so the file is skipped like a legacy spec (AC-16). The push gate still
# refuses a spec that LEAVES ears-1 in a push.
_LOOSE_FORMAT = re.compile(
    r"^\s*(?:[>*+|-]\s*)*[*_]*\s*spec[-_ ]?format\s*[*_]*\s*[:|]\s*[*_]*\s*ears-1\b", re.IGNORECASE)
_LOOSE_STATUS = re.compile(
    r"^\s*(?:[>*+|-]\s*)*[*_]*\s*status\s*[*_]*\s*[:|]\s*[*_]*\s*(?:draft|approved|converged)\b", re.IGNORECASE)
_GLOSSARY_ENTRY = re.compile(r"^- \*\*([A-Za-z][\w-]*)\*\*:")
_AC_ITEM = re.compile(r"^- \[[ xX]\] (AC-\d+): (.*)$")
_MARKER = re.compile(r"\[\s*NEEDS\s+CLARIFICATION\s*(?::[^\]]*)?\]", re.IGNORECASE)
_INLINE_CODE = re.compile(r"`[^`\n]*`")
_EARS = [
    ("ubiquitous", re.compile(r"^THE ([\w-]+) SHALL\b")),
    ("event", re.compile(r"^WHEN .+?, THE ([\w-]+) SHALL\b")),
    ("state", re.compile(r"^WHILE .+?, THE ([\w-]+) SHALL\b")),
    ("optional", re.compile(r"^WHERE .+?, THE ([\w-]+) SHALL\b")),
    ("unwanted", re.compile(r"^IF .+?, THEN THE ([\w-]+) SHALL\b")),
]
_TASK_START = re.compile(r"^\s*[-*+] \[[ xX]\] T\d+\b")
_TASK = re.compile(
    r"^- \[[ xX]\] (T\d{2,}) \[(AC-\d+(?:, AC-\d+)*)\] (\S[^:]*?): (\S.*)$"
)
_CONVERGENCE = re.compile(r"^## Convergence\b")


@dataclass
class Report:
    path: Path
    findings: list = field(default_factory=list)
    skipped: bool = False

    def add(self, file: Path, line: int, msg: str) -> None:
        self.findings.append(f"{file}:{line}: {msg}")


def _readable_lines(text: str) -> list:
    """(line_no, line) with fenced blocks blanked, so quoted grammar is ignored.
    Only a fence that CLOSES hides its lines: an unclosed opening fence would
    otherwise hide every header after it and turn a spec into a silent skip."""
    lines = text.splitlines()
    marks = [i for i, line in enumerate(lines) if line.lstrip().startswith(("```", "~~~"))]
    if len(marks) % 2:
        marks = marks[:-1]
    hidden = set()
    for a, b in zip(marks[0::2], marks[1::2]):
        hidden.update(range(a, b + 1))
    return [(i + 1, "" if i in hidden else line) for i, line in enumerate(lines)]


def _sections(lines: list) -> dict:
    """'## Heading' -> [(line_no, line), ...] for the lines under it."""
    secs, cur = {}, None
    for i, line in lines:
        if line.startswith("## "):
            cur = line[3:].strip()
            secs.setdefault(cur, [])
            continue
        if cur is not None:
            secs[cur].append((i, line))
    return secs


def _ears_subject(sentence: str):
    for _name, pat in _EARS:
        m = pat.match(sentence)
        if m:
            return m.group(1)
    return None


def _header_lines(text: str, loose: re.Pattern) -> list:
    """(line_no, line) for every header-shaped line outside fences and inline code."""
    return [(i, line) for i, line in _readable_lines(text)
            if loose.match(_INLINE_CODE.sub("", line))]


def is_ears(text) -> bool:
    """A spec opts in with ANY header-shaped Spec-Format line, canonical or not, so a
    malformed header is a finding instead of a silent skip. Legacy specs carry none."""
    return bool(text) and bool(_header_lines(text, _LOOSE_FORMAT))


def spec_status(text) -> str:
    """The canonical status, or "?" when the header is missing, duplicated,
    malformed or outside the head: the linter reports those, the gate refuses them."""
    if not text:
        return ""
    found = _header_lines(text, _LOOSE_STATUS)
    if len(found) != 1:
        return "?"
    i, line = found[0]
    m = _CANON_STATUS.match(line)
    return m.group(1) if m and i <= HEAD_LINES else "?"


def _lint_headers(feature: Path, text: str, report: Report) -> None:
    for key, loose, canon, want in (
            ("Spec-Format", _LOOSE_FORMAT, _CANON_FORMAT, "> **Spec-Format:** ears-1"),
            ("Status", _LOOSE_STATUS, _CANON_STATUS, "> **Status:** draft|approved|converged")):
        found = _header_lines(text, loose)
        if not found:
            report.add(feature, 1, f"no {key} header in the first {HEAD_LINES} lines")
            continue
        if len(found) > 1:
            report.add(feature, found[1][0],
                       f"{key} header appears {len(found)} times; keep exactly one")
        for i, line in found:
            if not canon.match(line):
                report.add(feature, i, f"{key} header must be exactly `{want}`")
            elif i > HEAD_LINES:
                report.add(feature, i, f"{key} header must sit in the first {HEAD_LINES} lines")


def lint_feature(feature: Path, report: Report, ready: bool) -> set:
    """Returns the set of criterion ids, for the plan coverage check."""
    text = feature.read_text(encoding="utf-8")
    lines = _readable_lines(text)
    if not is_ears(text):
        report.skipped = True
        return set()
    _lint_headers(feature, text, report)

    secs = _sections(lines)
    glossary = {m.group(1) for _i, line in secs.get("Glossary", [])
                if (m := _GLOSSARY_ENTRY.match(line))}
    if not glossary:
        report.add(feature, 1, "no `## Glossary` section with `- **Name**:` entries")

    if "Acceptance Criteria" not in secs:
        report.add(feature, 1, "no `## Acceptance Criteria` section")
    ids: dict = {}
    for i, line in secs.get("Acceptance Criteria", []):
        if not line.strip():
            continue
        m = _AC_ITEM.match(line)
        if not m:
            report.add(feature, i, "line in Acceptance Criteria is not a `- [ ] AC-##: ` criterion")
            continue
        ac, sentence = m.group(1), m.group(2)
        if ac in ids:
            report.add(feature, i, f"{ac} duplicates line {ids[ac]}")
            continue
        ids[ac] = i
        bare = _MARKER.sub("", sentence).strip()
        subject = _ears_subject(bare)
        if subject is None:
            report.add(feature, i, f"{ac} matches no EARS pattern")
        elif glossary and subject not in glossary:
            report.add(feature, i, f"{ac} subject '{subject}' is not in the Glossary")

    if "Acceptance Criteria" in secs and not ids:
        report.add(feature, 1, "`## Acceptance Criteria` holds no criterion")

    # Markers are counted over the joined text so one split across lines counts.
    body = "\n".join(_INLINE_CODE.sub("", line) for _i, line in lines)
    markers = [(body.count("\n", 0, m.start()) + 1, 1) for m in _MARKER.finditer(body)]
    total = len(markers)
    if total > MAX_MARKERS:
        report.add(feature, markers[0][0],
                   f"{total} NEEDS CLARIFICATION markers, the cap is {MAX_MARKERS}")
    elif ready and total:
        where = ", ".join(str(i) for i, _n in markers)
        report.add(feature, markers[0][0],
                   f"not ready: {total} NEEDS CLARIFICATION marker(s) open (lines {where})")
    return set(ids)


def lint_plan(plan: Path, criteria: set, report: Report) -> None:
    lines = _readable_lines(plan.read_text(encoding="utf-8"))
    seen: dict = {}
    referenced: set = set()
    planned = 0
    in_convergence = False
    for i, line in lines:
        if _CONVERGENCE.match(line):
            in_convergence = True
            continue
        if line.startswith("## ") and in_convergence:
            report.add(plan, i, "a section follows a `## Convergence` section; Convergence sections come last")
            continue
        if not _TASK_START.match(line):
            continue
        m = _TASK.match(line)
        if not m:
            report.add(plan, i, "task does not follow `- [ ] T## [AC-##] <path>: <action>`")
            continue
        tid, acs, paths = m.group(1), m.group(2).split(", "), m.group(3)
        if tid in seen:
            report.add(plan, i, f"{tid} duplicates line {seen[tid]}")
        seen[tid] = i
        if any(not p.strip() or re.search(r"[\s,]", p.strip()) for p in paths.split(", ")):
            report.add(plan, i, f"{tid} has an empty path, or a path with spaces or a bare comma")
        if not in_convergence:
            planned += 1
        for ac in acs:
            referenced.add(ac)
            if ac not in criteria:
                report.add(plan, i, f"{tid} references unknown criterion {ac}")
    if seen and not planned:
        report.add(plan, 1, "no task sits above the first `## Convergence` heading")
    if planned > MAX_TASKS:
        report.add(plan, 1, f"{planned} tasks, the cap is {MAX_TASKS}")
    for ac in sorted(criteria - referenced, key=lambda a: int(a[3:])):
        report.add(plan, 1, f"{ac} is covered by no task")


def lint(target: Path, ready: bool = False) -> Report:
    feature = target / "feature.md" if target.is_dir() else target
    report = Report(feature)
    if not feature.is_file():
        report.add(feature, 0, "feature.md not found")
        return report
    criteria = lint_feature(feature, report, ready)
    if report.skipped:
        return report
    plan = feature.parent / "plan.md"
    if plan.is_file():
        lint_plan(plan, criteria, report)
    return report


# --------------------------------------------------------------------------
# Push gate
# --------------------------------------------------------------------------

ZERO_SHA = "0" * 40
SPEC_HOMES = ("docs/specs", "docs/specs-archive")
# Git tree modes of a regular file, an executable file and a directory. Anything else
# at a spec path (120000 symlink, 160000 submodule, or a mode git adds later) is
# refused: an allow-list, because the deny-list version missed the submodule.
PLAIN_MODES = ("100644", "100755", "040000")
_SPEC_DIR_NAME = re.compile(r"^\d{12}-[a-z0-9][a-z0-9-]*$")


def _git(repo: Path, *args: str) -> str:
    cp = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if cp.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {cp.stderr.strip()}")
    return cp.stdout


def _show(repo: Path, rev: str, path: str):
    cp = subprocess.run(["git", "-C", str(repo), "show", f"{rev}:{path}"],
                        capture_output=True, text=True)
    return cp.stdout if cp.returncode == 0 else None


def _default_remote_branches(repo: Path) -> list:
    """Remote-tracking refs of the default branch (origin/HEAD, else */main, */master)."""
    refs = _git(repo, "for-each-ref", "--format=%(refname)",
                "refs/remotes/").split()
    for ref in (r for r in refs if r.endswith("/HEAD")):
        cp = subprocess.run(["git", "-C", str(repo), "symbolic-ref", "-q", ref],
                            capture_output=True, text=True)
        if cp.returncode == 0 and cp.stdout.strip():
            return [cp.stdout.strip()]
    return [r for r in refs if r.rsplit("/", 1)[-1] in ("main", "master")]


def _before_rev(repo: Path, base: str, head: str):
    """The commit the push is compared against: the merge base of the pushed head
    and the default remote branch, so the comparison is "what this branch changes".
    Without a default remote branch it falls back to what the remote ref holds
    (<base>), and with neither to None: every file at head then counts as changed.

    Why the merge base and not the remote ref's own tip:
    - a spec that converged on the default branch through its own pull request
      reaches every other branch by merge or rebase. Against the ref's tip it read
      as that branch's flip, and the branch could not be pushed again;
    - a flip already pushed stays in the comparison, so code pushed after it (an
      ordinary second push, or a force push that slides code under the flip) meets
      the freshness check again.

    It is read from topology, never from the order `git rev-list` prints. That order
    follows commit dates, so a commit dated before its own parent moved the "before"
    onto a state that was already converged, and the flip went unseen (converge
    pass 1 of v9)."""
    for ref in _default_remote_branches(repo):
        cp = subprocess.run(["git", "-C", str(repo), "merge-base", head, ref],
                            capture_output=True, text=True)
        if cp.returncode == 0 and cp.stdout.strip():
            return cp.stdout.strip()
    if base != ZERO_SHA:
        cp = subprocess.run(["git", "-C", str(repo), "cat-file", "-e", f"{base}^{{commit}}"],
                            capture_output=True)
        if cp.returncode == 0:
            return base
    return None


def _changed_paths(repo: Path, before, head: str) -> set:
    """Every path whose content or mode differs between the before state and the
    pushed head. One tree diff, not a walk over the commits: `git diff-tree` on a
    merge commit prints nothing without -m, so a spec edited inside a merge commit
    never reached the check (converge pass 1 of v9). Renames are not paired, so both
    the old and the new path are listed. Submodule changes are always listed:
    porcelain `git diff` honours `diff.ignoreSubmodules` and a tracked `.gitmodules`
    with `ignore = all`, which hid a submodule placed over a spec directory."""
    if before is None:
        cmd = ["ls-tree", "-r", "--name-only", "-z", head]
    else:
        cmd = ["diff", "--name-only", "--no-renames", "--ignore-submodules=none", "-z",
               before, head]
    cp = subprocess.run(["git", "-C", str(repo), "-c", "core.quotePath=false", *cmd],
                        capture_output=True)
    if cp.returncode != 0:
        raise RuntimeError(f"git {' '.join(cmd)}: {cp.stderr.decode('utf-8', 'replace').strip()}")
    return {p for p in cp.stdout.decode("utf-8", "surrogateescape").split("\0") if p}


def _newest_branch_code(repo: Path, head: str, spec_dir: str) -> str:
    """The latest author OR committer date among the commits that are on this branch
    (reachable from head, not from the default remote branch) and touch a path
    outside the spec directory. A code commit pushed in an EARLIER push of the same
    branch still counts, which closes the two-push split. Both dates count because
    each one alone is slipped by an everyday command: an amend or a cherry-pick keeps
    the old author date, and only the committer date shows when the code landed.
    The cost is stated: a rebase after the verdict stales it, and the converge pass
    runs again. That only concerns the push that flips a spec, once per spec.
    "" when there is none."""
    not_refs = _default_remote_branches(repo)
    args = [head] + (["--not", *not_refs] if not_refs else [])
    out = _git(repo, "log", "--format=%aI %cI", *args,
               "--", ".", f":(exclude){spec_dir}").split()
    return max(out, key=_parse_ts) if out else ""


SPEC_FILES = ("feature.md", "plan.md")
# A Git LFS pointer, current or legacy: the spec URL changed twice
# (git-media.io, hawser.github.com, git-lfs.github.com), so the gate matches the
# shape the pointer format fixes: a `version` line, optional `ext-` lines, then the oid.
_LFS_POINTER = re.compile(r"\Aversion \S+\n(?:ext-\S+ [^\n]*\n)*oid sha256:[0-9a-f]{64}\s")


def _is_lfs_pointer(blob) -> bool:
    return bool(blob) and bool(_LFS_POINTER.match(blob))


def _home_at(parts: tuple, i: int) -> str:
    """The spec home spelled at parts[i:i+2], case-folded, or ""."""
    pair = "/".join(parts[i:i + 2]).casefold()
    return pair if pair in SPEC_HOMES else ""


def is_spec_dir(path: str) -> bool:
    """A spec lives in its own directory under docs/specs/ or docs/specs-archive/, at
    any depth of the repository (an arm keeps the same layout). Test fixtures, templates
    and any other feature.md elsewhere are not specs, and the gate never reads them:
    violation fixtures are malformed on purpose."""
    parts = Path(path).parts
    return any(_home_at(parts, i) and len(parts) == i + 3 for i in range(len(parts) - 1))


def is_canonical_spec_path(path: str) -> bool:
    """A spec path spelled exactly: the home in lower case and, for a file, a
    lower-case name. On a case-insensitive filesystem (Windows, macOS by default)
    `Docs/specs/x/Feature.md` lands on `docs/specs/x/feature.md`, so a gate that
    matched the spelling alone would miss a spec a person sees on disk. Matching
    uses casefold, not lower: `docſ` (long s) folds to `docs` and lower() leaves it."""
    parts = Path(path).parts
    for i in range(len(parts) - 1):
        if _home_at(parts, i):
            if "/".join(parts[i:i + 2]) not in SPEC_HOMES:
                return False
            tail = parts[i + 3:] if len(parts) > i + 3 else ()
            return all(x in SPEC_FILES for x in tail if x.casefold() in SPEC_FILES)
    return True


def _on_spec_path(path: str) -> bool:
    """True for a `docs` directory, a spec home (`docs/specs`, `docs/specs-archive`),
    a spec directory or a file in one, at any depth. A symlink at ANY of these hides
    real specs from a gate that reads the git tree, while a filesystem walk (the
    doctor, an editor, a person) follows the link and still sees them."""
    parts = Path(path).parts
    if not parts:
        return False
    if parts[-1].casefold() == "docs":
        return True
    if len(parts) >= 2 and _home_at(parts, len(parts) - 2):
        return True
    return is_spec_dir(path) or is_spec_dir(str(Path(path).parent))


def _parse_ts(value: str) -> _dt.datetime:
    ts = _dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return ts if ts.tzinfo else ts.replace(tzinfo=_dt.timezone.utc)


def push_findings(repo: Path, base: str, head: str) -> list:
    """Findings for one pushed ref. Empty list means the push may go."""
    findings: list = []
    before = _before_rev(repo, base, head)
    changed = _changed_paths(repo, before, head)
    if not changed:
        return findings
    for p in sorted(changed):
        if _on_spec_path(p):
            mode = _git(repo, "ls-tree", head, "--", p).split(" ", 1)[0]
            if mode and mode not in PLAIN_MODES:
                findings.append(f"{p}: a spec home, a spec directory or a spec file must be a "
                                f"plain file or directory, not a symlink or a submodule "
                                f"(mode {mode}); the gate reads the tree, and a link or a "
                                f"submodule hides the specs behind it")
    spec_paths = [p for p in changed
                  if Path(p).name.casefold() in SPEC_FILES and is_spec_dir(str(Path(p).parent))]
    for p in sorted(spec_paths):
        blob = _show(repo, head, p)
        if not is_canonical_spec_path(p):
            if blob is None:
                continue  # gone at the pushed head: a miscased spec may be deleted or renamed
            findings.append(f"{p}: a spec path is spelled `docs/specs/<name>/feature.md` (or "
                            f"plan.md, or docs/specs-archive) in lower case; on a "
                            f"case-insensitive filesystem another spelling lands on the "
                            f"same file")
            continue
        if _is_lfs_pointer(blob):
            findings.append(f"{p}: a spec file may not be a Git LFS pointer; the gate reads "
                            f"the tree, and the pointer hides the spec behind it")
    # A spec may not leave ears-1 by moving: the old path then reads as a deleted
    # spec and the new one as a file that never declared the format, and both are
    # allowed on their own. Paired by what the push does, not by git's rename
    # detection, which a large enough edit defeats (converge pass 2 of v9).
    features = [p for p in spec_paths if Path(p).name == "feature.md"]
    gone = [p for p in features
            if before and is_ears(_show(repo, before, p)) and _show(repo, head, p) is None]
    if gone:
        for p in features:
            now = _show(repo, head, p)
            if now is None or is_ears(now) or (before and _show(repo, before, p) is not None):
                continue
            findings.append(f"{p}: this push removes an ears-1 spec ({', '.join(gone)}) and adds "
                            f"this one without the Spec-Format header; a spec does not leave "
                            f"ears-1 by moving. Keep the header, or land the removal in its own pull request")
    spec_dirs = sorted({str(Path(p).parent) for p in spec_paths
                        if is_canonical_spec_path(p)
                        and not _is_lfs_pointer(_show(repo, head, p))})

    for sd in spec_dirs:
        feature_now = _show(repo, head, f"{sd}/feature.md")
        feature_before = _show(repo, before, f"{sd}/feature.md") if before else None
        if feature_now is None:
            continue  # the spec was deleted or moved away; deleting a spec is allowed
        if not is_ears(feature_now):
            if is_ears(feature_before):
                findings.append(f"{sd}: the spec stops being ears-1 in this push (its "
                                f"Spec-Format header was removed or broken); restore it")
            continue
        if sd.startswith("docs/specs/") and not _SPEC_DIR_NAME.match(sd[len("docs/specs/"):]):
            findings.append(f"{sd}: a spec directory under docs/specs/ is named "
                            f"<yyyymmddHHMM>-<lowercase-slug>")
        # AC-15: lint the spec as it is at the pushed head.
        plan_now = _show(repo, head, f"{sd}/plan.md")
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "feature.md").write_text(feature_now, encoding="utf-8")
            if plan_now is not None:
                (Path(tmp) / "plan.md").write_text(plan_now, encoding="utf-8")
            rep = lint(Path(tmp))
            findings += [f.replace(tmp, sd) for f in rep.findings]

        if spec_status(feature_now) == "converged" and plan_now is None:
            findings.append(f"{sd}: the spec says converged but has no plan.md; a converged "
                            f"spec keeps the plan it was judged against")
            continue
        # AC-14: a status flip to converged needs a fresh CONVERGED receipt.
        if spec_status(feature_now) != "converged":
            continue
        if spec_status(feature_before) == "converged":
            continue
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import receipt_ledger
        receipt = receipt_ledger.converge_latest_for(sd)
        if receipt is None:
            findings.append(f"{sd}: Status becomes converged, but this machine holds no "
                            f"converge receipt for {sd}. Run /sdd-converge as a verifier "
                            f"subagent, then push again. (The comparison is with the "
                            f"default remote branch; if that ref is stale, `git fetch` first.)")
            continue
        if receipt.get("verdict") != "CONVERGED":
            findings.append(f"{sd}: Status becomes converged, but the latest converge "
                            f"verdict for it is {receipt.get('verdict')} "
                            f"({receipt.get('verdict_ts') or receipt.get('ts', '?')}).")
            continue
        code = _newest_branch_code(repo, head, sd)
        if code:
            verdict_at = _parse_ts(receipt.get("verdict_ts") or receipt.get("ts"))
            if verdict_at <= _parse_ts(code):
                findings.append(f"{sd}: the CONVERGED verdict "
                                f"({receipt.get('verdict_ts') or receipt.get('ts')}) is older "
                                f"than a code commit on this branch ({code}). Run "
                                f"/sdd-converge again.")
    return findings


def _push_selftest_case(case: Path) -> list:
    """Build the scenario a push.json describes and return its findings."""
    spec = json.loads((case / "push.json").read_text())
    sd = spec.get("spec_dir", "docs/specs/202609300000-toy")
    home = Path(tempfile.mkdtemp(prefix="spec-push-home-"))
    repo = Path(tempfile.mkdtemp(prefix="spec-push-repo-"))
    saved = {k: os.environ.get(k) for k in ("HOME", "USERPROFILE")}
    try:
        os.environ["HOME"] = os.environ["USERPROFILE"] = str(home)
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")

        def commit(msg: str, when: str) -> str:
            e = dict(env, GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
            subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=e)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", msg, "--allow-empty"],
                           check=True, env=e, capture_output=True)
            return _git(repo, "rev-parse", "HEAD").strip()

        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        feature = (case / "feature.md").read_text()
        (repo / sd).mkdir(parents=True)
        (repo / sd / "feature.md").write_text(feature)
        (repo / sd / "plan.md").write_text((case / "plan.md").read_text())
        (repo / "app.py").write_text("x = 1\n")
        base = commit("base", "2026-09-30T10:00:00+00:00")
        pushed = base  # what the remote ref holds before the push
        if spec.get("remote_master_at_base"):
            subprocess.run(["git", "-C", str(repo), "update-ref",
                            "refs/remotes/origin/master", base], check=True)
        if spec.get("code_change"):
            (repo / "app.py").write_text("x = 2\n")
            commit("code", "2026-09-30T11:00:00+00:00")
        if spec.get("late_code_old_author"):
            # an amend or a cherry-pick: authored before the verdict, landed after it
            (repo / "app.py").write_text("x = 3\n")
            e = dict(env, GIT_AUTHOR_DATE="2026-09-30T11:00:00+00:00",
                     GIT_COMMITTER_DATE="2026-09-30T11:45:00+00:00")
            subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=e)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "late code"],
                           check=True, env=e, capture_output=True)
        text = feature
        if spec.get("flip", True):
            text = text.replace("> **Status:** approved",
                                spec.get("status_line", "> **Status:** converged"))
        if spec.get("append_status"):
            text = text.replace("## Summary", spec["append_status"] + "\n\n## Summary")
        if spec.get("remove_format"):
            text = text.replace("> **Spec-Format:** ears-1\n", "")
        if spec.get("replace_format"):
            text = text.replace("> **Spec-Format:** ears-1", spec["replace_format"])
        (repo / sd / "feature.md").write_text(text)
        if spec.get("rename_spec_to"):
            shutil.move(str(repo / sd), str(repo / spec["rename_spec_to"]))
        if spec.get("delete_plan"):
            (repo / sd / "plan.md").unlink()
        if spec.get("delete_spec"):
            shutil.rmtree(repo / sd)
        if spec.get("new_lfs_spec"):
            lfs = repo / "docs" / "specs" / "202609300001-lfs"
            lfs.mkdir(parents=True)
            version = spec["new_lfs_spec"]
            if version is True:
                version = "https://git-lfs.github.com/spec/v1"
            (lfs / "feature.md").write_text(
                f"version {version}\noid sha256:" + "0" * 64 + "\nsize 1234\n")
        if spec.get("symlink_home"):
            real = repo / "elsewhere" / "specs"
            real.mkdir(parents=True)
            shutil.move(str(repo / "docs" / "specs"), real.parent / "moved")
            os.symlink(os.path.relpath(real.parent / "moved", repo / "docs"), repo / "docs" / "specs")
        if spec.get("symlink_spec"):
            hidden = repo / "notes" / "hidden"
            hidden.mkdir(parents=True)
            shutil.move(str(repo / sd / "feature.md"), hidden / "feature.md")
            shutil.move(str(repo / sd / "plan.md"), hidden / "plan.md")
            shutil.rmtree(repo / sd)
            os.symlink(os.path.relpath(hidden, (repo / sd).parent), repo / sd)
        if spec.get("break_spec"):
            text = (repo / sd / "feature.md").read_text()
            (repo / sd / "feature.md").write_text(
                text.replace("THE Exporter SHALL write UTF-8.", "The exporter writes UTF-8."))
        if spec.get("in_merge"):
            # the spec edit lives ONLY in a merge commit: its tree differs from both
            # parents, and a per-commit diff without -m prints nothing for it
            def tree_commit(tree: str, parents: list, when: str) -> str:
                e = dict(env, GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
                args = [a for q in parents for a in ("-p", q)]
                return subprocess.run(["git", "-C", str(repo), "commit-tree", tree, *args,
                                       "-m", "m"], check=True, env=e, capture_output=True,
                                      text=True).stdout.strip()
            tip = _git(repo, "rev-parse", "HEAD").strip()
            side = tree_commit(_git(repo, "rev-parse", "HEAD^{tree}").strip(), [tip],
                               "2026-09-30T11:30:00+00:00")
            subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=env)
            merged = tree_commit(_git(repo, "write-tree").strip(), [tip, side],
                                 "2026-09-30T12:00:00+00:00")
            subprocess.run(["git", "-C", str(repo), "update-ref", "HEAD", merged], check=True)
            head = merged
        else:
            head = commit("status", "2026-09-30T12:00:00+00:00")
        if spec.get("child_dated_before_parent"):
            # F (the flip, 12:00) <- K (its child, dated 10:30, before every other
            # commit of the push) <- M (merge of K and F). `git rev-list` prints by
            # date, so K comes last, and reading "before" off the last one landed on
            # its parent F, which is already converged.
            def tree_commit(parents: list, when: str) -> str:
                e = dict(env, GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
                args = [a for q in parents for a in ("-p", q)]
                return subprocess.run(["git", "-C", str(repo), "commit-tree",
                                       _git(repo, "rev-parse", f"{head}^{{tree}}").strip(),
                                       *args, "-m", "m"], check=True, env=e,
                                      capture_output=True, text=True).stdout.strip()
            child = tree_commit([head], "2026-09-30T10:30:00+00:00")
            head = tree_commit([child, head], "2026-09-30T12:30:00+00:00")
            subprocess.run(["git", "-C", str(repo), "update-ref", "HEAD", head], check=True)
        if spec.get("code_after_flip"):
            # the flip went out in an earlier push; this push carries only code
            pushed = head
            (repo / "app.py").write_text("x = 9\n")
            head = commit("code after the flip", "2026-09-30T12:30:00+00:00")
        if spec.get("converged_on_master"):
            # the spec converges on the default branch through its own pull request,
            # and this branch, already pushed, takes it in by merging
            pushed = head
            e = dict(env, GIT_AUTHOR_DATE="2026-09-30T12:30:00+00:00",
                     GIT_COMMITTER_DATE="2026-09-30T12:30:00+00:00")

            def run(*a):
                subprocess.run(["git", "-C", str(repo), *a], check=True, env=e,
                               capture_output=True)
            branch = _git(repo, "symbolic-ref", "--short", "HEAD").strip()
            run("checkout", "-q", "-b", "default-branch", base)
            (repo / sd / "feature.md").write_text(
                feature.replace("> **Status:** approved", "> **Status:** converged"))
            run("commit", "-qam", "converged on the default branch")
            run("update-ref", "refs/remotes/origin/master", "HEAD")
            run("checkout", "-q", branch)
            run("merge", "-q", "--no-ff", "-m", "take the default branch in", "default-branch")
            head = _git(repo, "rev-parse", "HEAD").strip()
        if spec.get("gitlink_spec"):
            # a submodule at the spec directory: files on disk once initialised,
            # nothing in the superproject's tree
            e = dict(env, GIT_AUTHOR_DATE="2026-09-30T12:00:00+00:00",
                     GIT_COMMITTER_DATE="2026-09-30T12:00:00+00:00")
            if spec.get("gitmodules_ignore_all"):
                (repo / ".gitmodules").write_text(
                    f'[submodule "spec"]\n\tpath = {sd}\n\turl = ./spec\n\tignore = all\n')
                subprocess.run(["git", "-C", str(repo), "add", ".gitmodules"], check=True, env=e)
            subprocess.run(["git", "-C", str(repo), "rm", "-r", "-q", "--cached", sd],
                           check=True, env=e, capture_output=True)
            subprocess.run(["git", "-C", str(repo), "update-index", "--add", "--cacheinfo",
                            f"160000,{base},{sd}"], check=True, env=e)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "gitlink"],
                           check=True, env=e, capture_output=True)
            head = _git(repo, "rev-parse", "HEAD").strip()

        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import receipt_ledger
        for i, r in enumerate(spec.get("receipts", [])):
            aid = f"a{i:03d}"
            sid = "s-self"
            scope = r.get("scope", sd)
            tdir = home / ".claude" / "projects" / "p" / sid / "subagents"
            tdir.mkdir(parents=True, exist_ok=True)
            tp = tdir / f"agent-{aid}.jsonl"
            entry = {"type": "assistant", "uuid": f"u{i}", "parentUuid": f"p{i}",
                     "sessionId": sid, "timestamp": r.get("transcript_ts", r["ts"]),
                     "message": {"role": "assistant", "content": [{"type": "text",
                         "text": f"report\nCONVERGE-VERDICT: {r['verdict']}\nCONVERGE-SCOPE: {scope}"}]}}
            tp.write_text(json.dumps(entry) + "\n")
            receipt_ledger.append_global({"kind": "converge", "verdict": r["verdict"],
                                          "scope": scope, "agent_id": aid,
                                          "agent_type": r.get("agent_type", "Reality Checker"),
                                          "agent_transcript_path": str(tp),
                                          "session_id": sid, "ts": r["ts"]})
        return push_findings(repo, pushed, head)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(home, ignore_errors=True)
        shutil.rmtree(repo, ignore_errors=True)


def _print(report: Report) -> None:
    if report.skipped:
        print(f"skip {report.path}: no `Spec-Format: ears-1` header")
    elif report.findings:
        for f in report.findings:
            print(f)
    else:
        print(f"ok {report.path}")


def selftest(fixture_dir: Path) -> int:
    if not fixture_dir.is_absolute():
        fixture_dir = Path(__file__).resolve().parent.parent / fixture_dir
    cases = sorted(p for p in fixture_dir.iterdir() if p.is_dir()) if fixture_dir.is_dir() else []
    violations = [c for c in cases if c.name.startswith("violation")]
    benigns = [c for c in cases if c.name.startswith("benign")]
    if not violations or not benigns:
        print(f"selftest FAIL: need violation* and benign* cases in {fixture_dir}", file=sys.stderr)
        return 1
    failures = []
    for case in violations + benigns:
        args = (case / "args").read_text().split() if (case / "args").is_file() else []
        if (case / "push.json").is_file():
            found = _push_selftest_case(case)
        else:
            found = lint(case, ready="--ready" in args).findings
        out = "\n".join(found)
        if case in violations:
            if not found:
                failures.append(f"{case.name}: expected findings, got none")
            elif (case / "expect.txt").is_file():
                want = (case / "expect.txt").read_text().strip()
                if want not in out:
                    failures.append(f"{case.name}: findings lack '{want}': {out}")
        elif found:
            failures.append(f"{case.name}: expected clean, got: {out}")
    if failures:
        for f in failures:
            print(f"selftest FAIL: {f}", file=sys.stderr)
        return 1
    print(f"selftest PASS: {len(violations)} violation(s) block, {len(benigns)} benign(s) allow")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("targets", nargs="*", type=Path, help="spec directory or feature.md")
    ap.add_argument("--ready", action="store_true",
                    help="also fail while any NEEDS CLARIFICATION marker is open")
    ap.add_argument("--selftest", metavar="FIXTURE_DIR", type=Path)
    ap.add_argument("--push-range", nargs=2, metavar=("BASE", "HEAD"),
                    help="push gate: check one pushed ref (base may be all zeros)")
    ap.add_argument("--repo", type=Path, default=Path("."),
                    help="repository for --push-range (default: current directory)")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest(args.selftest)
    if args.push_range:
        try:
            found = push_findings(args.repo, *args.push_range)
        except (RuntimeError, ValueError, OSError) as exc:
            print(f"push check could not run: {exc}", file=sys.stderr)
            return 2
        for f in found:
            print(f)
        return 1 if found else 0
    if not args.targets:
        ap.print_usage(sys.stderr)
        return 2
    rc = 0
    for t in args.targets:
        rep = lint(t, ready=args.ready)
        _print(rep)
        if rep.findings:
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
