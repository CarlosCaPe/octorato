#!/usr/bin/env python3
"""g__stop__diagram-first.py: Stop gate: every reply to the operator opens with a flow.

Operator decision (2026-11-17): 100% of replies to the operator in the terminal
are flows. A reply OPENS with an ASCII diagram in a code block; the text after
it is short and in bullets; more detail is given only when the operator asks,
or offered in one closing line. Rule: CLAUDE.md "Diagram-first", HOW in
skills/human-cadence/SKILL.md. Memory alone did not hold it under load, so it
is a ganglion: a hook that fires on its own.

Blocks when no exemption applies and EITHER check fails:
  1. FLOW: the reply has no opening diagram (a fenced block first, or after
     one short lead line, whose info string is empty/text/txt/ascii/plaintext/text-plain and whose
     body holds a diagram glyph: an arrow, a box-drawing branch, or an ASCII
     table row such as `| a | b |` or `+---+`). Status lines included. A fenced
     2D Delegate summary may lead; the diagram then follows it.
  2. SHORT TEXT: the Prose exceeds PROSE_MAX_WORDS (120), or holds a paragraph
     (a run of consecutive non-bullet, non-table lines) of more than
     PARAGRAPH_MAX_WORDS (40) words.

Exemptions: a paste-ready ask in the operator's prompt; an input-needed-only
reply (the last Prose line is `input-needed:` and the rest of the Prose is a
lead of at most INPUT_LEAD_MAX_WORDS, 30); the `diagram-ok` hatch;
stop_hook_active.

Prose is the reply minus fenced code, inline code, blockquotes, quoted spans,
the Provenance footer and the Disclose one-liners. The four shape detectors
(flow, before/after, status, structure) survive only as diagnostic text in the
block reason; they do not gate the decision.

Hatch: `diagram-ok` on any line of the reply exempts the turn.
Loop safety: stop_hook_active=true means we already blocked this turn, pass.
Fail-open on every error.

Stdin:  {"transcript_path": str, "stop_hook_active": bool, ...}
Stdout: {"decision": "block", "reason": "..."} on a hit, else nothing.
Exit:   always 0.

Spec: docs/specs/202611172031-diagram-always/ (supersedes docs/specs/202611151120-diagram-first/).
"""
from __future__ import annotations

import json
import os
import re
import sys
import unicodedata

for _stream in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

HATCH = "diagram-ok"
SIGNATURE = "DIAGRAM-FIRST"
PROSE_MAX_WORDS = 120    # cap on the Prose outside the diagram, footer and Disclose lines
PARAGRAPH_MAX_WORDS = 40 # a non-bullet paragraph longer than this is a wall of text
INPUT_LEAD_MAX_WORDS = 30
LEAD_LINE_MAX_WORDS = 20
MIN_ARROWS = 2
MIN_NUMBERED = 3
MIN_STATUS_ITEMS = 3
MIN_STRUCTURE_ITEMS = 4

_FOOTER = re.compile(r"^\s*[>*_\s]*(Provenance|Procedencia|Herkunft)\s*:", re.IGNORECASE)
_DISCLOSE = re.compile(r"^\s*(💡|☠)\s*\S*\s*(Unlock|Prune)[- ]?suggestion\s*:", re.IGNORECASE)
_INLINE = re.compile(r"`[^`\n]*`")
_QUOTED = re.compile(r'"[^"\n]*"|[“”][^“”\n]*[“”]|«[^»\n]*»')
_BLOCKQUOTE = re.compile(r"^\s{0,3}>")
_INPUT_LABEL = re.compile(r"^[*_\s]*input-needed[*_]*\s*:", re.IGNORECASE)
_WORD = re.compile(r"[^\W_]", re.UNICODE)
_LIST_MARKER = re.compile(r"^(?:\d{1,2}[.)]|[a-zA-Z][.)])$")

# `-+>` covers `->`, `-->` and `--->` as ONE arrow each. Spelled this way, and
# not as a `-->` alternative, so a static analyzer does not read the arrow
# token as an HTML comment terminator (this gate parses no HTML).
_ARROW = re.compile(r"-+>|=>|→|⟶|─►")
_NUMBERED = re.compile(r"^\s*\d{1,2}[.)]\s+\S")
_LIST_ITEM = re.compile(r"^(?P<indent>\s*)(?:[-*+•]|\d{1,2}[.)])\s+\S")
_BULLET = re.compile(r"^(?P<indent>\s*)[-*+•]\s+\S")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEP = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
_LABEL_PREFIX = r"^\s*(?:[-*+•]\s+|#{1,6}\s+)?[*_]*\s*"
_BEFORE = re.compile(_LABEL_PREFIX + r"(?:before|antes|previously)\s*[*_]*\s*:", re.IGNORECASE)
_AFTER = re.compile(_LABEL_PREFIX + r"(?:after|now|despues|ahora)\s*[*_]*\s*:", re.IGNORECASE)
_STATE_GLYPHS = ("✓", "✗", "✅", "❌", "⚠")
_STATE_WORDS = re.compile(
    r"\b(?:done|pending|blocked|open|merged|failing|passing|green|red|"
    r"listo|pendiente|bloqueado|hecho|abierto|cerrado)\b")
_DIAGRAM_GLYPH = re.compile(
    r"─►|►|◄|├─|└─|┌|┐|┘|│|─{2,}|═|║|▼|▲|→|←|->|<-|=>|"
    r"^\s*\|.*\|\s*$|^\s*\+-[-+]*\+\s*$", re.MULTILINE)
_DIAGRAM_INFO = ("", "text", "txt", "ascii", "plaintext", "text-plain")  # not mermaid: the terminal shows it raw

_RE_SYSTEM_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)
_RE_COMMAND_TAG = re.compile(r"<command-(?:name|message|args)>.*?</command-\w+>", re.DOTALL)


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in text if not unicodedata.combining(ch))


# ── transcript ───────────────────────────────────────────────────────────────

def _tail_lines(path: str, max_bytes: int = 262144) -> list:
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        fh.seek(max(0, size - max_bytes))
        return fh.read().decode("utf-8", errors="replace").splitlines()


def _blocks_text(entry: dict) -> str:
    parts = []
    content = (entry.get("message") or {}).get("content") or []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
    elif isinstance(content, str):
        parts.append(content)
    return "\n".join(parts)


def last_assistant_text(lines: list) -> str:
    """Text of the LAST assistant entry; stops there with or without text."""
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") == "assistant":
            return _blocks_text(entry)
    return ""


def last_user_text(lines: list) -> str:
    """Last real operator prompt; skips tool results, meta and compaction entries."""
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (entry.get("type") != "user" or entry.get("isMeta")
                or entry.get("isCompactSummary") or entry.get("isVisibleInTranscriptOnly")):
            continue
        text = _RE_COMMAND_TAG.sub(" ", _RE_SYSTEM_REMINDER.sub(" ", _blocks_text(entry)))
        if text.strip():
            return text.strip()
    return ""


# ── paste-ready ask, reused from the sibling gate by file path ───────────────

def _paste_ask_regex():
    """The sibling's _ASK_PASTE, loaded by path so the two gates never drift.
    None when the load fails (spec R-04): the exemption is then off."""
    try:
        import importlib.util
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "g__stop__paste-ready-raw.py")
        spec = importlib.util.spec_from_file_location("_paste_ready_raw_gate", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod._ASK_PASTE
    except Exception:
        return None


# ── reply structure ──────────────────────────────────────────────────────────

def parse_fences(lines: list) -> list:
    """Fenced blocks: {info, body, start, end}; an unclosed fence runs to the end."""
    fences, open_at, info, body = [], None, "", []
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("```"):
            if open_at is None:
                open_at, info, body = i, ln.lstrip()[3:].strip().lower(), []
            else:
                fences.append({"info": info, "body": "\n".join(body), "start": open_at, "end": i})
                open_at, info, body = None, "", []
        elif open_at is not None:
            body.append(ln)
    if open_at is not None:
        fences.append({"info": info, "body": "\n".join(body), "start": open_at, "end": len(lines) - 1})
    return fences


def is_diagram_fence(fence: dict) -> bool:
    return fence["info"] in _DIAGRAM_INFO and bool(_DIAGRAM_GLYPH.search(fence["body"]))


def prose_lines(lines: list, fences: list) -> list:
    """The Prose, line by line (spec Glossary)."""
    inside = set()
    for f in fences:
        inside.update(range(f["start"], f["end"] + 1))
    kept = []
    for i, ln in enumerate(lines):
        if i in inside or _BLOCKQUOTE.match(ln) or _FOOTER.match(ln) or _DISCLOSE.match(ln):
            continue
        if HATCH in ln:
            continue
        kept.append(_QUOTED.sub("", _INLINE.sub("", ln)))
    return kept


def count_words(prose: list) -> int:
    return sum(1 for ln in prose for tok in ln.split()
               if _WORD.search(tok) and not _LIST_MARKER.match(tok))


def _is_2d_summary(fence: dict) -> bool:
    """The fenced 2D Delegate summary (skills/4d-paradigm-protocol, Mandatory Output
    Format). It may lead a reply; the diagram follows it."""
    if fence["info"] not in _DIAGRAM_INFO:
        return False
    first = next((ln.strip() for ln in fence["body"].splitlines() if ln.strip()), "")
    return first.startswith("2D Delegate")


def has_opening_diagram(lines: list, fences: list) -> bool:
    """A diagram fence is the first non-blank element, or follows one short lead line.
    A leading fenced 2D Delegate summary is skipped before that check."""
    nonblank = [i for i, ln in enumerate(lines) if ln.strip()]
    if not nonblank:
        return False
    by_start = {f["start"]: f for f in fences}
    if nonblank[0] in by_start and _is_2d_summary(by_start[nonblank[0]]):
        end = by_start[nonblank[0]]["end"]
        nonblank = [i for i in nonblank if i > end]
        if not nonblank:
            return False
    first = nonblank[0]
    if first in by_start:
        return is_diagram_fence(by_start[first])
    lead = lines[first]
    if _LIST_ITEM.match(lead) or len(lead.split()) > LEAD_LINE_MAX_WORDS:
        return False
    if len(nonblank) > 1 and nonblank[1] in by_start:
        return is_diagram_fence(by_start[nonblank[1]])
    return False


# ── the four shapes ──────────────────────────────────────────────────────────

def _flow(prose: list) -> str:
    arrows = sum(len(_ARROW.findall(ln)) for ln in prose)
    if arrows >= MIN_ARROWS:
        return f"flow ({arrows} arrows in prose)"
    # A line indented deeper than the numbered item (a sub-bullet or a wrapped
    # continuation) belongs to that item and does not break the run.
    run = best = 0
    item_indent = None
    for ln in prose:
        line = ln.expandtabs(4)
        indent = len(line) - len(line.lstrip())
        if _NUMBERED.match(ln):
            run += 1
            best = max(best, run)
            item_indent = indent
        elif ln.strip() and (item_indent is None or indent <= item_indent):
            run, item_indent = 0, None
    if best >= MIN_NUMBERED:
        return f"flow ({best} numbered steps)"
    return ""


def _before_after(prose: list) -> str:
    folded = [_fold(ln) for ln in prose]
    for i, ln in enumerate(folded):
        if _BEFORE.match(ln) and any(_AFTER.match(x) for x in folded[i + 1:]):
            return "before/after"
    return ""


def _status(prose: list) -> str:
    n = 0
    for ln in prose:
        is_item = _LIST_ITEM.match(ln) or (_TABLE_ROW.match(ln) and not _TABLE_SEP.match(ln))
        if not is_item:
            continue
        if any(g in ln for g in _STATE_GLYPHS) or _STATE_WORDS.search(_fold(ln)):
            n += 1
    return f"status of {n} items" if n >= MIN_STATUS_ITEMS else ""


def _structure(prose: list) -> str:
    indents = []
    for ln in prose:
        m = _BULLET.match(ln)
        if m:
            indents.append(len(m.group("indent").expandtabs(4)))
    if len(indents) >= MIN_STRUCTURE_ITEMS and len(set(indents)) >= 2:
        return f"structure ({len(indents)} nested items)"
    return ""


def explanatory_shape(prose: list) -> str:
    for check in (_flow, _before_after, _status, _structure):
        hit = check(prose)
        if hit:
            return hit
    return ""


# ── verdict ──────────────────────────────────────────────────────────────────

def _paragraph_words(prose: list) -> int:
    """Words in the longest paragraph: a run of consecutive non-blank lines that
    are not list items or table rows. A line indented under a list item is that
    item's continuation, not a paragraph."""
    best = run = 0
    in_item = False
    for ln in prose:
        if not ln.strip():
            run, in_item = 0, False
            continue
        if _LIST_ITEM.match(ln) or _TABLE_ROW.match(ln):
            run, in_item = 0, bool(_LIST_ITEM.match(ln))
            continue
        if in_item and ln[:1].isspace():
            continue
        in_item = False
        run += count_words([ln])
        best = max(best, run)
    return best


def find_violation(prompt: str, reply: str, paste_rx=None) -> str:
    """The block detail, or '' (the spec's Blocking_Condition, in full)."""
    if not reply or not reply.strip():
        return ""
    lines = reply.splitlines()
    if any(HATCH in ln for ln in lines):
        return ""
    if paste_rx is not None and prompt and paste_rx.search(prompt):
        return ""
    fences = parse_fences(lines)
    prose = prose_lines(lines, fences)
    tail = [ln for ln in prose if ln.strip()]
    if tail and _INPUT_LABEL.match(tail[-1]) and count_words(tail[:-1]) <= INPUT_LEAD_MAX_WORDS:
        return ""
    shape = explanatory_shape(prose)
    what = f" (it carries a {shape})" if shape else ""
    if not has_opening_diagram(lines, fences):
        if any(is_diagram_fence(f) for f in fences):
            return f"a diagram is in the reply but not at the top{what}; move it to the top"
        return f"the reply has no opening diagram{what}"
    words = count_words(prose)
    if words > PROSE_MAX_WORDS:
        return f"the text after the diagram is {words} words, over the {PROSE_MAX_WORDS}-word cap"
    para = _paragraph_words(prose)
    if para > PARAGRAPH_MAX_WORDS:
        return (f"the text holds a {para}-word paragraph, over the {PARAGRAPH_MAX_WORDS}-word "
                f"limit for non-bullet text")
    return ""


def build_reason(detail: str) -> str:
    return (
        f"🗺 {SIGNATURE}: {detail}. Rule (CLAUDE.md 'Diagram-first'): flow first; text short "
        f"and in bullets; offer more detail in one line instead of writing it. Open with an "
        f"ASCII diagram in a code block (`──►` steps, `├─` / `└─` branches, ✓ / ? / ✗ state, "
        f"a plain `| a | b |` table also counts), then at most {PROSE_MAX_WORDS} words of short "
        f"bullets, no paragraph over {PARAGRAPH_MAX_WORDS} words (skills/human-cadence/SKILL.md). "
        f"Rewrite the reply that way. To keep it as is, put `{HATCH}` on a line."
    )


def run_turn(data: dict) -> str:
    transcript = data.get("transcript_path") or ""
    if not transcript:
        return ""
    try:
        lines = _tail_lines(transcript)
    except OSError:
        return ""
    detail = find_violation(last_user_text(lines), last_assistant_text(lines), _paste_ask_regex())
    return build_reason(detail) if detail else ""


def main() -> int:
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        return 0
    if not isinstance(data, dict) or data.get("stop_hook_active"):
        return 0
    try:
        reason = run_turn(data)
        if reason:
            print(json.dumps({"decision": "block", "reason": reason}))
            _journal_deny(reason, data)
    except Exception:
        pass
    return 0


# -- v8 kernel journal (Phase 4, v8-kernel.md) --------------------------------
_KERNEL_RULE = "COMMS.diagram-first"


def _journal_deny(reason, payload=None, tool_use_id=None) -> None:
    """Mirror this refusal into the refusing process's journal. FAIL-OPEN: every
    error is swallowed and the verdict is unchanged. kernel_proc is loaded by
    PATH, so nothing on sys.path can shadow it."""
    try:
        import importlib.util
        _path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kernel_proc.py")
        _spec = importlib.util.spec_from_file_location("_kernel_proc_journal", _path)
        _kp = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_kp)
        _payload = payload if isinstance(payload, dict) else {}
        _kp.journal_deny(_KERNEL_RULE, reason,
                         tool_use_id if tool_use_id is not None else _payload.get("tool_use_id"),
                         _kp.resolve_pid(_payload))
    except Exception:
        pass


def _selftest() -> int:
    import gate_selftest
    argv = sys.argv
    fixture = argv[argv.index("--selftest") + 1] if len(argv) > argv.index("--selftest") + 1 \
        else "registry/fixtures/COMMS.diagram-first"
    return gate_selftest.run_gate_selftest(__file__, fixture)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
