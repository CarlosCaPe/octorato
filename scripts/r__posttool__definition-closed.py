#!/usr/bin/env python3
"""r__posttool__definition-closed: PostToolUse Write|Edit reflex (advisory).

When an entry written to an ARM memory file records that a definition closed
(a closure marker next to a number), remind the agent to find every holder of
the PREVIOUS value by searching for the value, with the exact sweep command and
the arm root already resolved. The hook cannot know the previous value, so it
never guesses one: the command carries a placeholder the agent fills in.

Fires only when all of these hold:
  - the tool is Write or Edit and the path has the shape
    <arm root>/.claude/memory/<file>.md, outside the brain tree;
  - the NEW text of this call (Edit: new_string, Write: content) has a closure
    marker (English or Spanish) and an integer of 2+ digits in the same
    sentence or line;
  - this session has not been advised about this file yet.

Advisory only: emits additionalContext, always exits 0, never blocks. Fails
open on unparseable input and on any exception.

What it cannot see: a definition closed in chat and never written to arm
memory; a closure written through Bash or MultiEdit; a one-digit value or a
number spelled as a word; a marker and its number in different sentences; a
closure phrased with no listed marker. It also fires on a false positive such
as "confirmed 12 rows loaded", which is why it only advises.

Stdin:  {"session_id", "tool_name", "tool_input": {"file_path", ...}, ...}
Stdout: {"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                "additionalContext": "..."}} or nothing.
"""
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

CLAUDE_DIR = Path(__file__).resolve().parent.parent
LIVE_DIR = Path.home() / ".claude"
STATE_DIR = LIVE_DIR / ".cache" / "reflex" / "definition-closed"

MARKER_RE = re.compile(
    r"(?<!\w)(closed|confirmed|final|locked|cerrad[oa]|confirmad[oa]|"
    r"definitiv[oa]|queda[ \t]+en|quedan)(?!\w)", re.IGNORECASE)
NUMBER_RE = re.compile(r"(?<![\w.,])\d{2,}(?!\w)")
DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?;])\s+")


def _inside(path: str, root: Path) -> bool:
    try:
        base = os.path.normcase(os.path.realpath(str(root)))
    except OSError:
        return False
    return path == base or path.startswith(base + os.sep)


def arm_root(file_path: str, brain_roots=None):
    """The arm root when file_path is <arm root>/.claude/memory/<file>.md and
    sits outside the brain, else None. Judged on the real path, so a link into
    an arm memory directory resolves to the arm it belongs to."""
    if not file_path:
        return None
    real = os.path.realpath(os.path.expanduser(file_path))
    folded = os.path.normcase(real)
    for root in (brain_roots if brain_roots is not None else (CLAUDE_DIR, LIVE_DIR)):
        if _inside(folded, root):
            return None
    parts = Path(real).parts
    if len(parts) < 4 or not parts[-1].lower().endswith(".md"):
        return None
    if parts[-2].lower() != "memory" or parts[-3].lower() != ".claude":
        return None
    return str(Path(*parts[:-3]))


def closure_near_number(text: str) -> bool:
    if not text:
        return False
    for line in text.splitlines():
        for sentence in SENTENCE_SPLIT_RE.split(line):
            if MARKER_RE.search(sentence) and NUMBER_RE.search(DATE_RE.sub(" ", sentence)):
                return True
    return False


def first_time(session_id: str, file_path: str, state_dir: Path) -> bool:
    """True once per session per file. A state file that cannot be read or
    written never silences the advisory."""
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id or "no-session")[:120]
    state = state_dir / f"{safe}.json"
    seen = []
    try:
        loaded = json.loads(state.read_text(encoding="utf-8"))
        if isinstance(loaded, list):
            seen = [s for s in loaded if isinstance(s, str)]
    except (OSError, ValueError):
        pass
    key = os.path.realpath(file_path)
    if key in seen:
        return False
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        tmp = state.with_name(state.name + f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(seen + [key]), encoding="utf-8")
        os.replace(tmp, state)
    except OSError:
        pass
    return True


def advisory(root: str) -> str:
    return (
        "Definition closed: this memory entry looks like it closes a definition "
        "(a closure marker next to a number). Before updating documents, find "
        "every holder of the previous value by searching for the value itself, "
        "not from memory and not by following links between documents; the "
        "document nobody links to is the one that stays stale. Run: "
        f"python3 ~/.claude/scripts/stale_value_sweep.py --root {root} "
        '--old "<previous value>" (replace <previous value> with the value that '
        "was in force before this entry; this hook does not know it). Advisory "
        "only, nothing was blocked.")


def evaluate(raw: str, state_dir: Path = STATE_DIR, brain_roots=None):
    """The advisory text for this hook event, or None to stay silent."""
    try:
        event = json.loads(raw or "{}")
    except ValueError:
        return None
    if not isinstance(event, dict):
        return None
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    tool = event.get("tool_name") or ""
    if tool == "Edit":
        text = tool_input.get("new_string")
    elif tool == "Write":
        text = tool_input.get("content")
    else:
        return None
    file_path = tool_input.get("file_path")
    if not isinstance(text, str) or not isinstance(file_path, str):
        return None
    root = arm_root(file_path, brain_roots)
    if root is None or not closure_near_number(text):
        return None
    if not first_time(str(event.get("session_id") or ""), file_path, state_dir):
        return None
    return advisory(root)


def main() -> int:
    try:
        message = evaluate(sys.stdin.read())
        if message:
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PostToolUse", "additionalContext": message}}))
    except Exception:
        pass
    return 0


def _selftest() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="definition-closed-"))
    failures = []
    try:
        arm = tmp / "arm"
        memory = arm / ".claude" / "memory"
        memory.mkdir(parents=True)
        brain = tmp / "brain"
        (brain / ".claude" / "memory").mkdir(parents=True)
        roots = (brain,)
        state = tmp / "state"
        note = str(memory / "decisions.md")

        def event(path, text, tool="Write", session="s1"):
            key = "content" if tool == "Write" else "new_string"
            return json.dumps({"session_id": session, "tool_name": tool,
                               "tool_input": {"file_path": path, key: text}})

        def run(raw):
            return evaluate(raw, state_dir=state, brain_roots=roots)

        out = run(event(note, "Headcount closed at 438 after the review."))
        expected = f"stale_value_sweep.py --root {os.path.realpath(str(arm))} --old \"<previous value>\""
        if not out or expected not in out:
            failures.append(f"violation did not produce the advisory with the arm root: {out!r}")
        if out and "438" in out:
            failures.append("the advisory guessed a value")
        if run(event(note, "Headcount closed at 438 after the review.")) is not None:
            failures.append("debounce: fired twice for one file in one session")
        if run(event(note, "Headcount closed at 438.", session="s2")) is None:
            failures.append("debounce: a new session stayed silent")
        if run(event(str(memory / "b.md"), "Periodicidad confirmada: queda en 12 periodos.", tool="Edit")) is None:
            failures.append("Spanish marker on Edit did not fire")

        benign = {
            "non-memory path": event(str(arm / "docs" / "plan.md"), "Headcount closed at 438."),
            "no closure marker": event(str(memory / "c.md"), "Headcount might be 438."),
            "marker without a number": event(str(memory / "d.md"), "The scope is closed."),
            "one-digit number": event(str(memory / "e.md"), "Scope closed at 3."),
            "marker and only a date": event(str(memory / "f.md"), "Confirmed on 2026-01-15."),
            "marker and number in different sentences": event(
                str(memory / "g.md"), "The scope is closed. Headcount might be 438."),
            "brain memory": event(str(brain / ".claude" / "memory" / "x.md"), "Headcount closed at 438."),
            "non-markdown file": event(str(memory / "h.txt"), "Headcount closed at 438."),
            "other tool": event(str(memory / "i.md"), "Headcount closed at 438.", tool="Read"),
            "malformed JSON": "{not json",
            "empty stdin": "",
            "JSON that is not an object": "[1, 2]",
        }
        for name, raw in benign.items():
            if run(raw) is not None:
                failures.append(f"benign input fired: {name}")
    except Exception as exc:  # a selftest that crashes is a failure, not a pass
        failures.append(f"selftest raised {type(exc).__name__}: {exc}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if failures:
        for f in failures:
            print(f"selftest FAIL: {f}", file=sys.stderr)
        return 1
    print("selftest PASS: advisory on an arm memory closure (Write and Edit, "
          "English and Spanish), once per session per file, silent on 12 benign inputs")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    sys.exit(main())
