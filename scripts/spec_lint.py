#!/usr/bin/env python3
"""spec_lint.py: the deterministic reader of a v9 spec (Spec-Format: ears-1).

v9 makes "done" a verdict computed against a spec. That only works if a script
can read the spec, so acceptance criteria are written in EARS and plan tasks
follow one grammar. This CLI is the reader. It uses the standard library only
and makes no model call: the same input gives the same answer on every machine.

What it checks, per spec directory (a `feature.md`, optionally a `plan.md`):

  feature.md
    - a header LINE in the first 30 lines reads `Spec-Format: ears-1` (bold and a
      `>` quote allowed), else the file is SKIPPED (exit 0), so specs written
      before v9 never break; a sentence that merely mentions it does not opt in
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

Usage:
  spec_lint.py [--ready] <spec-dir | feature.md> [...]
  spec_lint.py --selftest registry/fixtures/FLOW.spec-contract

Exit: 0 clean or skipped, 1 findings, 2 usage error.

Selftest: each subdirectory of the fixture dir is one case. `violation*` cases
must exit 1 and, when they carry an `expect.txt`, print that substring, so a
violation that fails for the wrong reason does not count. `benign*` cases must
exit 0. A case may carry an `args` file with extra flags (for example --ready).
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

MAX_MARKERS = 3
MAX_TASKS = 20

_FORMAT = re.compile(r"^\s*(?:>\s*)?\**Spec-Format:\**\s*ears-1\s*$", re.MULTILINE)
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
    """(line_no, line) with fenced blocks blanked, so quoted grammar is ignored."""
    out, fenced = [], False
    for i, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            out.append((i, ""))
            continue
        out.append((i, "" if fenced else line))
    return out


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


def lint_feature(feature: Path, report: Report, ready: bool) -> set:
    """Returns the set of criterion ids, for the plan coverage check."""
    text = feature.read_text(encoding="utf-8")
    lines = _readable_lines(text)
    head = "\n".join(line for _i, line in lines[:30])
    if not _FORMAT.search(head):
        report.skipped = True
        return set()

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
        rep = lint(case, ready="--ready" in args)
        out = "\n".join(rep.findings)
        if case in violations:
            if not rep.findings:
                failures.append(f"{case.name}: expected findings, got none")
            elif (case / "expect.txt").is_file():
                want = (case / "expect.txt").read_text().strip()
                if want not in out:
                    failures.append(f"{case.name}: findings lack '{want}': {out}")
        elif rep.findings:
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
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest(args.selftest)
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
