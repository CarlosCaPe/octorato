#!/usr/bin/env python3
"""cadence-lint.py — mechanical enforcement of the human-cadence no-rules.

The 10 no-rules (skills/human-cadence/SKILL.md) lived only as INSTRUCTION in
CLAUDE.md §Communication. Violations kept shipping because instructions depend
on discipline and never reach sub-agents or arm content pipelines. This linter
turns the regex-provable subset into a REFLEX:

  rule 1  em-dash (—)
  rule 2  AI filler vocabulary (EN/ES blocklists, stem-matched)
  rule 3  "not only X, but Y" / "no solo X, sino Y"
  rule 5  rigid transitions (sentence-initial)
  rule 6  filler openers
  rule 9  conclusion tails (sentence-initial)
  rule 11 machine-register greetings (sentence/doc-initial)
  rule 12 machine-register closings
  rule 13 post-hoc recap openers
  rule 14 mood/health references
  rule 15 unsolicited tip openers

Rules 4/7/8/10 (triads, rhythm, bullets-in-prose, voice) are judgment calls
and stay with the model; this script covers everything a regex can prove.

Modes:
  cadence-lint.py --file <path>      CLI report; exit 1 on violations (CI / arm use)
  ... | cadence-lint.py              lint stdin text
  cadence-lint.py --hook             PostToolUse Write|Edit hook: lints ONLY the
                                     newly written content of prose files,
                                     emits additionalContext, always exit 0.

Escapes:
  - canon files that quote the blocklists as content are excluded by path
    (human-cadence skill, CLAUDE.md, this script, cadence-named memories)
  - a line containing `cadence-ok` is skipped (deliberate quotation)
Prose targets only in hook mode: .md .txt .markdown
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
# Force UTF-8 on stdout/stderr so the ✓ / ✗ / em-dash glyphs in reports
# survive on Windows shells defaulting to cp1252. Without this, a script
# can do its work correctly and still crash with UnicodeEncodeError when
# printing success. Applied repo-wide by _apply-utf8-reconfigure.py.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


# ── rule definitions ─────────────────────────────────────────────────────────

# rule 2 — stems, EN+ES merged (utiliz/robust/optimiz/multifacet overlap).
# 'navega*' (ES) is OMITTED deliberately: navegador/navegación are everyday
# technical Spanish, not AI-tells; flagging them would cry wolf until the
# whole lint gets ignored. The EN 'navigat' stem stays (rarely legit in prose).
_FILLER_STEMS = [
    "delv", "tapestr", "tapiz", "tapice", "leverag", "utiliz", "robust",
    "seamless", "multifacet", "multifacétic", "navigat", "optimiz",
    "foster", "foment", "comprehensiv", "exhaustiv", "ahond", "fluido",
]
_RE_FILLER = re.compile(r"\b(" + "|".join(_FILLER_STEMS) + r")\w*\b", re.IGNORECASE)

_RE_EMDASH = re.compile("—")

# rule 3 — contrast frame; gap excludes sentence enders so the match never
# spans two sentences (cross-sentence "not only … but" is a false positive)
_RE_CONTRAST = re.compile(
    r"(not only\b[^.!?]{0,80}?\bbut(\s+also)?\b|no s[oó]lo\b[^.!?]{0,80}?\bsino\b)",
    re.IGNORECASE,
)

# rule 5 — sentence-initial rigid transitions
_RE_TRANSITION = re.compile(
    r"(?:^|[.!?:]\s+)(moreover|furthermore|additionally|in conclusion|"
    r"además|asimismo|adicionalmente|en conclusión)\b",
    re.IGNORECASE | re.MULTILINE,
)

# rule 6 — filler openers, anywhere
_RE_OPENER = re.compile(
    r"(i hope this (message|email)? ?finds you well|in today's fast-paced world|"
    r"in the realm of|it('|’)s worth noting that|it is worth noting that|"
    r"espero que este mensaje te encuentre bien|en el vertiginoso mundo actual|"
    r"en el ámbito de|cabe destacar que)",
    re.IGNORECASE,
)

# rule 6 — flattery openers (message- or sentence-initial only, to avoid
# mid-sentence false positives like "the good news is ...").
_RE_FLATTERY = re.compile(
    r"(?:^|[.!?]\s+)("
    r"(good|great|excellent|nice|fair)\s+question|"
    r"thanks\s+all|good\s+news|happy\s+to\s+report|"
    r"buena\s+pregunta|excelente\s+pregunta|buenas\s+noticias)\b",
    re.IGNORECASE | re.MULTILINE,
)

# rule 9 — sentence-initial conclusion tails
_RE_TAIL = re.compile(
    r"(?:^|[.!?]\s+)(overall,|in summary|to wrap up|"
    r"en general,|en resumen|para finalizar)\b",
    re.IGNORECASE | re.MULTILINE,
)

# rule 11 — machine-register greetings (sentence-initial or document-initial)
# Note: use días?/tardes?/noches? so the group ends at a real word boundary;
# 'día' alone matches only 3 chars of 'días', leaving 's' as next char and
# causing the outer \b to fail between two word chars.
_RE_GREETING = re.compile(
    r"(?:^|[.!?]\s+)(buen[ao]s?\s+(d[ií]as?|tardes?|noches?)|"
    r"hope\s+this\s+finds\s+you|i\s+hope\s+you('re|\s+are)|"
    r"espero\s+que\s+est[eé]s?|hola\b)\b",
    re.IGNORECASE | re.MULTILINE,
)

# rule 12 — machine-register closings
_RE_CLOSING = re.compile(
    r"(?:^|[.!?]\s+)(good\s+luck\b|buena\s+suerte\b|saludos\b|cheers\b|"
    r"best\s+regards\b|hasta\s+luego\b|cu[ií]date\b|take\s+care\b|"
    r"happy\s+to\s+(pair|help|walk|assist|jump|chat|sync|discuss)|"
    r"con\s+gusto\b|encantado\s+de\s+ayudar)\b",
    re.IGNORECASE | re.MULTILINE,
)

# rule 13 — post-hoc recap openers
_RE_RECAP = re.compile(
    r"(?:^|[.!?]\s+)(en\s+resumen\b|to\s+summarize\b|in\s+summary\b|"
    r"overall\b|to\s+recap\b|as\s+a\s+summary\b|en\s+conclusi[oó]n\b)\b",
    re.IGNORECASE | re.MULTILINE,
)

# rule 14 — mood/health references
_RE_MOOD = re.compile(
    r"(espero\s+que\s+te\s+recuperes?|feel\s+better\b|get\s+well\s+soon\b|"
    r"hope\s+you('re|\s+are)\s+(feeling|doing|well|ok|okay)|"
    r"cu[ií]date\s+mucho\b)",
    re.IGNORECASE,
)

# rule 15 — unsolicited tips opener
_RE_UNSOLICITED_TIP = re.compile(
    r"(?:^|[.!?]\s+)(pro\s+tip\b|tip\b:\s|by\s+the\s+way\b|"
    r"just\s+a\s+(heads[- ]up|reminder|note|tip)\b|"
    r"also\s+note\s+that\b|worth\s+mentioning\b)",
    re.IGNORECASE | re.MULTILINE,
)

_RULES = [
    (1, "em-dash", _RE_EMDASH),
    (2, "AI filler word", _RE_FILLER),
    (3, "not-only/no-solo contrast frame", _RE_CONTRAST),
    (5, "rigid transition", _RE_TRANSITION),
    (6, "filler opener", _RE_OPENER),
    (6, "flattery opener", _RE_FLATTERY),
    (9, "conclusion tail", _RE_TAIL),
    (11, "machine-register greeting", _RE_GREETING),
    (12, "machine-register closing", _RE_CLOSING),
    (13, "post-hoc recap opener", _RE_RECAP),
    (14, "mood/health reference", _RE_MOOD),
    (15, "unsolicited tip opener", _RE_UNSOLICITED_TIP),
]

_PROSE_SUFFIXES = {".md", ".txt", ".markdown"}

# canon files that legitimately QUOTE the banned patterns as content
_EXCLUDED_PARTS = ("human-cadence",)
_EXCLUDED_NAMES = ("CLAUDE.md", "cadence-lint.py")


def _excluded(path_str: str) -> bool:
    if not path_str:
        return False
    p = Path(path_str)
    if p.name in _EXCLUDED_NAMES:
        return True
    if "cadence" in p.name.lower():
        return True
    return any(part in _EXCLUDED_PARTS for part in p.parts)


def lint_text(text: str) -> list:
    """Return [(rule_no, label, line_no, snippet)] for every violation."""
    hits = []
    for line_no, line in enumerate(text.splitlines(), 1):
        if "cadence-ok" in line:
            continue
        for rule_no, label, rx in _RULES:
            for m in rx.finditer(line):
                frag = line[max(0, m.start() - 20):m.end() + 20].strip()
                hits.append((rule_no, label, line_no, frag))
    return hits


def _format_report(hits: list, source: str) -> str:
    lines = [f"✍ CADENCE [{source}]: {len(hits)} violation(s) of the human-cadence no-rules:"]
    for rule_no, label, line_no, frag in hits[:12]:
        lines.append(f"  rule {rule_no} ({label}) line {line_no}: …{frag}…")
    if len(hits) > 12:
        lines.append(f"  … and {len(hits) - 12} more")
    lines.append("  Fix before shipping — canon: skills/human-cadence/SKILL.md")
    return "\n".join(lines)


# ── modes ────────────────────────────────────────────────────────────────────

def run_cli(args) -> int:
    if args.file:
        path = Path(args.file)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"cadence-lint: cannot read {path}: {exc}", file=sys.stderr)
            return 2
        source = str(path)
    else:
        text = sys.stdin.read()
        source = "stdin"
    hits = lint_text(text)
    if not hits:
        print(f"✓ cadence clean [{source}]")
        return 0
    print(_format_report(hits, source))
    return 1


def run_hook() -> int:
    """PostToolUse Write|Edit. Lints only the NEW content; never blocks."""
    try:
        data = json.loads(sys.stdin.read())
        tool_input = data.get("tool_input") or {}
        file_path = tool_input.get("file_path") or ""
        if _excluded(file_path):
            return 0
        if Path(file_path).suffix.lower() not in _PROSE_SUFFIXES:
            return 0
        new_text = tool_input.get("content") or tool_input.get("new_string") or ""
        if not new_text and isinstance(tool_input.get("edits"), list):
            # MultiEdit shape: {"edits": [{"old_string", "new_string"}, ...]}
            new_text = "\n".join(
                e.get("new_string", "") for e in tool_input["edits"]
                if isinstance(e, dict)
            )
        if not new_text:
            return 0
        hits = lint_text(new_text)
        if not hits:
            return 0
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": _format_report(hits, Path(file_path).name),
            }
        }))
    except Exception:
        pass  # fail-open: a lint must never break a write
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Lint text against the human-cadence no-rules")
    ap.add_argument("--file", help="File to lint (default: stdin)")
    ap.add_argument("--hook", action="store_true", help="PostToolUse hook mode")
    args = ap.parse_args()
    if args.hook:
        return run_hook()
    return run_cli(args)


if __name__ == "__main__":
    sys.exit(main())
