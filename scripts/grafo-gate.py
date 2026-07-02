#!/usr/bin/env python3
"""PreToolUse Bash hook: the forcing function for graph-before-grep.

v6 G3 gives this two verdicts:

  DENY (fail-closed, narrow): a RECURSIVE grep/rg over a brain CONTENT dir
  (~/.claude/{skills,agents,docs,memory}) when the per-turn ledger records NO seek
  this turn. That is the exact codified failure the rule forbids: grepping brain
  memory the graph could have answered, with no seek first. The three legit grep
  classes pass by construction: a single-file grep (not recursive), `git log --grep`
  (git's own index), and any non-brain path. Operator override: OCTO_GRAFO_OVERRIDE=1
  (agent-proof env). This closes the rule's standing waiver.

  RECORD + NUDGE (fail-open, broader): any other impact-shaped brain SCAN (e.g. over
  scripts/, or a content scan AFTER a seek) is recorded to the per-turn ledger and
  nudged; the Stop hook (grafo-ledger-check) classifies known-vs-unlit off the hot path.

Conservative by design: when in doubt it PASSES. A broken hook fails open.
"""
import os
import re
import sys
import json
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


LEDGER = Path.home() / ".claude" / ".cache" / "graph-ledger"


def turn_file():
    sid = os.environ.get("CLAUDE_SESSION_ID", "adhoc")
    return LEDGER / f"{sid}.turn.jsonl"


def is_brain_scan(cmd: str) -> bool:
    if not re.search(r"\b(grep|rg)\b", cmd):
        return False
    if "git log" in cmd or "git grep" in cmd:
        return False  # git's own index, legitimate
    # recursive scan only (grep -r / -rl / -rn / -ril, or ripgrep)
    if not (re.search(r"\bgrep\b[^|]*\s-[a-zA-Z]*r", cmd) or re.search(r"\brg\b", cmd)):
        return False
    # targeting a brain surface?
    return bool(re.search(r"~/\.claude|\$HOME/\.claude|/\.claude/|(?<![\w/])skills/|(?<![\w/])agents/|CLAUDE\.md", cmd))


def extract_term(cmd: str):
    m = re.search(r"""(?:grep|rg)\b[^'"]*?['"]([^'"]+)['"]""", cmd)
    return m.group(1) if m else None


# ── G3 narrow deny predicate ──────────────────────────────────────────────────

# a brain CONTENT dir (not scripts/, code greps are legitimate daily flow)
_BRAIN_CONTENT_DIR = re.compile(r"~/\.claude/(?:skills|agents|docs|memory)(?:/\S*)?")
_SINGLE_FILE_TAIL = re.compile(r"\.(md|py|json|ya?ml|txt|toml|sh|cfg|ini)$", re.IGNORECASE)


def is_brain_content_scan(cmd: str) -> bool:
    """A RECURSIVE grep/rg over a brain content DIR (not a single file)."""
    if "git log" in cmd or "git grep" in cmd:
        return False
    recursive = bool(re.search(r"\bgrep\b[^|]*\s-[a-zA-Z]*r", cmd) or re.search(r"\brg\b", cmd))
    if not recursive:
        return False
    m = _BRAIN_CONTENT_DIR.search(cmd)
    if not m:
        return False
    # a path that names a specific file is a single-file read, never a dir scan
    if _SINGLE_FILE_TAIL.search(m.group(0)):
        return False
    return True


def seeked_this_turn() -> bool:
    """True if this turn already recorded a seek (SEEK-COMPLETE or GREP-FALLBACK)."""
    tf = turn_file()
    if not tf.exists():
        return False
    try:
        for line in tf.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("state") in ("SEEK-COMPLETE", "GREP-FALLBACK"):
                return True
    except OSError:
        pass
    return False


def _record_scan(term: str) -> None:
    try:
        tf = turn_file()
        tf.parent.mkdir(parents=True, exist_ok=True)
        with tf.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"event": "brain_scan", "term": term}) + "\n")
    except OSError:
        pass


def _deny(term: str) -> None:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": (
            f"⛔ ¿y el grafo? DENY: recursive grep of brain content (grep '{term}') with NO "
            f"seek this turn. SEEK first, it is deterministic and ~100x cheaper: "
            f"impact-radius.py \"{term}\" (surfaces) or query_connectome.py query \"{term}\" "
            f"(skills/agents). Legit external greps (single file, git log --grep, non-brain "
            f"paths) are never blocked. Operator override: OCTO_GRAFO_OVERRIDE=1."
        ),
    }}))


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    cmd = (data.get("tool_input", {}) or {}).get("command", "") or ""

    # ── G3 DENY: recursive brain-content grep with no seek this turn ──────────
    if (is_brain_content_scan(cmd)
            and not seeked_this_turn()
            and os.environ.get("OCTO_GRAFO_OVERRIDE") != "1"):
        term = extract_term(cmd) or "?"
        _record_scan(term)  # the denied scan still counts toward the ledger
        _deny(term)
        return 0

    if not is_brain_scan(cmd):
        return 0
    term = extract_term(cmd) or "?"
    _record_scan(term)
    # Best-effort nudge (harmless if the harness ignores additionalContext on PreToolUse).
    try:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": (
                f"♦ ¿y el grafo? You are SCANNING the brain (grep '{term}'). If the graph "
                f"knows this, SEEK instead: impact-radius.py \"{term}\" (surfaces) or "
                f"query_connectome.py query \"{term}\" (skills/agents), deterministic, ~100x cheaper."
            ),
        }}))
    except Exception:
        pass
    return 0


def _selftest() -> int:
    import gate_selftest
    argv = sys.argv
    fixture = argv[argv.index("--selftest") + 1] if len(argv) > argv.index("--selftest") + 1 \
        else "registry/fixtures/FLOW.graph-before-grep"
    return gate_selftest.run_gate_selftest(__file__, fixture)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # fail-open: never break the user's command
