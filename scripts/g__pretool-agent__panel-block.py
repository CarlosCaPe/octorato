#!/usr/bin/env python3
"""g__pretool-agent__panel-block.py: a panel review request carries its block.

THE FAILURE THIS EXISTS FOR
A panel receipt is written by r__subagent-stop__qa-receipt.py only when
panel_digest.recompute_from_report() reproduces the stated digest from the
block the reviewer repeats at the end of its report (PANEL-TO ...,
PANEL-BODY-BEGIN, the text, PANEL-BODY-END, PANEL-VERDICT, PANEL-SHA256).
More than once the main loop launched a reviewer whose prompt carried only the
digest and asked for a verdict-only ending. The reviewer could not repeat a
block it never saw, no receipt was written, and the reply-panel Stop gate
(FLOW.panel-before-reply) sent the turn back until the harness block cap.
Memory did not stop it from recurring, so this gate refuses the launch.

WHAT IS A PANEL REVIEW REQUEST
The prompt of an Agent / Task call, or the `message` of a SendMessage call,
that names a digest the way the protocol does: `PANEL-SHA256` followed (after
at most 12 non-word characters, so `:` or a space or backticks) by 64 hex
digits. A prompt that only mentions the token in prose, with no digest after
it, is not a request and passes untouched. Any other tool passes untouched.

THE ONE ACCEPTED SHAPE
Every digest the request names must be reproduced, with panel_digest's own
recompute_from_report(), by a block that has at least one PANEL-TO line, and
that block must be in one of two places:
  1. pasted in the prompt: the whole `panel_digest.py --panel-request` output,
     PANEL-TO through PANEL-BODY-END (its PANEL-SHA256 line may follow); or
  2. in a request file named on its own line `PANEL-REQUEST-FILE: <path>`
     (absolute, or starting with `~/`), a regular readable UTF-8 file of at
     most 1 MiB holding that same output, for the reviewer to cat.
Each block is recomputed with its own recipients, mentions and attachment
hashes (the lines after the previous block, as the receipt consumer reads
them). So a verdict-only prompt, a block truncated before PANEL-BODY-END, a
block for a different text or recipient, and a request file that is missing
or holds another digest are all denied, and the deny names which.

What it cannot see: whether the prompt also tells the reviewer to REPEAT the
block at the end of its report. That instruction is prose; the deny message
spells it out, and the receipt consumer remains the binding check.

FAIL POLICY: closed for a request, open for everything else
A request this gate cannot verify (panel_digest not importable, a payload it
cannot parse whose raw text names PANEL-SHA256, any exception after a request
was recognised) is denied with the error named: the cost of a wrong allow is
the receipt-less loop this gate exists to stop, the cost of a wrong deny is
one re-launch with the block pasted. A payload that does not name
PANEL-SHA256 at all is allowed even when malformed: it cannot be a panel
request, and denying every Agent call on a harness glitch would stop work that
has nothing to do with panels. No env unlock and no hatch word.

Stdin:  {"tool_name": "Agent"|"Task"|"SendMessage", "tool_input": {...}, ...}
Stdout: PreToolUse deny JSON when refused; nothing on allow.
Exit:   always 0 (the deny travels in the JSON).
Proof:  --selftest [fixture_dir] (default registry/fixtures/FLOW.panel-block-in-reviewer-prompt).
"""
from __future__ import annotations

import json
import os
import re
import stat
import sys
from pathlib import Path

for _stream in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

_KERNEL_RULE = "FLOW.panel-block-in-reviewer-prompt"
_HERE = Path(__file__).resolve().parent

# tool name -> the tool_input key that carries the text the subagent reads
_TEXT_KEY = {"Agent": "prompt", "Task": "prompt", "SendMessage": "message"}

_TOKEN = "PANEL-SHA256"
_STATED = re.compile(r"PANEL-SHA256\W{0,12}?([0-9a-fA-F]{64})(?![0-9a-fA-F])", re.IGNORECASE)
_REQ_FILE = re.compile(r"^[ \t]*PANEL-REQUEST-FILE[ \t]*:[ \t]*(\S.*?)[ \t]*$", re.MULTILINE)
_MAX_FILE = 1 << 20
# Same pattern as panel_digest._BLOCK, used before panel_digest is loaded.
_BODY = re.compile(r"PANEL-BODY-BEGIN[ \t]*\n(.*?)\n[ \t]*PANEL-BODY-END", re.DOTALL)

_FIX = (
    "Fix: run `python3 ~/.claude/scripts/panel_digest.py --panel-request --to <recipient> "
    "--body-file <file>` and paste its WHOLE output into the reviewer prompt, from the first "
    "PANEL-TO line through PANEL-BODY-END and the PANEL-SHA256 line (or save that output to a "
    "file and put `PANEL-REQUEST-FILE: <absolute path>` on its own line). Tell the reviewer to "
    "end its report by repeating that block byte for byte, PANEL-TO through PANEL-BODY-END, "
    "followed by `PANEL-VERDICT: PASS | NEEDS-WORK` and `PANEL-SHA256: <digest>`. A verdict-only "
    "ending writes no receipt. A builder prompt that needs a literal digest without asking for a "
    "review can write it without the PANEL-SHA256 prefix."
)

_RAW = {"text": ""}


def _journal_deny(reason, payload=None) -> None:
    """Mirror this refusal into the refusing process's journal. FAIL-OPEN by
    contract: a journal that cannot be written never changes the verdict.
    kernel_proc is loaded by path, so nothing on sys.path can shadow it."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("_kernel_proc_journal",
                                                      str(_HERE / "kernel_proc.py"))
        kp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(kp)
        p = payload if isinstance(payload, dict) else {}
        kp.journal_deny(_KERNEL_RULE, reason, p.get("tool_use_id"), kp.resolve_pid(p))
    except Exception:
        pass


def _deny(reason: str, payload=None) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }, ensure_ascii=False))
    _journal_deny(reason, payload)


def _panel_digest():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_panel_digest_gate", str(_HERE / "panel_digest.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(_HERE))
    spec.loader.exec_module(mod)
    return mod


def block_digests(pd, text: str) -> dict:
    """digest -> number of PANEL-TO recipients, for every block in `text`, each
    recomputed by panel_digest.recompute_from_report over the text up to that
    block's end (so its head is the span after the previous block, exactly as
    the receipt consumer reads the last block of a report)."""
    out = {}
    for m in pd._BLOCK.finditer(text):
        got = pd.recompute_from_report(text[:m.end()])
        if got:
            d = got["digest"]
            out[d] = max(out.get(d, 0), len(got["recipients"]))
    return out


def _read_request_file(pd, raw_path: str):
    """(text, error). The path must be absolute or `~/`-relative."""
    path = raw_path.strip().strip("`'\"")
    if not (path.startswith("~/") or os.path.isabs(path)):
        return None, f"PANEL-REQUEST-FILE {path!r} is not an absolute or ~/ path"
    full = pd._bash_tilde(path)
    try:
        st = os.stat(full)
    except OSError as e:
        return None, f"PANEL-REQUEST-FILE {path!r} does not exist or is unreadable ({type(e).__name__})"
    if not stat.S_ISREG(st.st_mode):
        return None, f"PANEL-REQUEST-FILE {path!r} is not a regular file"
    if st.st_size > _MAX_FILE:
        return None, f"PANEL-REQUEST-FILE {path!r} is larger than 1 MiB"
    try:
        return Path(full).read_text(encoding="utf-8"), None
    except (OSError, UnicodeDecodeError) as e:
        return None, f"PANEL-REQUEST-FILE {path!r} cannot be read as UTF-8 ({type(e).__name__})"


def judge(text: str):
    """None to allow, or the deny reason."""
    stated = []
    # A digest quoted INSIDE a pasted body is reviewed content, not the request:
    # blank each body before reading the digests the request names.
    outside = _BODY.sub(lambda m: "PANEL-BODY-BEGIN\n\nPANEL-BODY-END", text)
    for m in _STATED.finditer(outside):
        d = m.group(1).lower()
        if d not in stated:
            stated.append(d)
    if not stated:
        return None
    try:
        pd = _panel_digest()
    except Exception as e:
        return (f"PANEL BLOCK GATE ({_KERNEL_RULE}) cannot verify this panel request: "
                f"panel_digest.py failed to load ({type(e).__name__}: {e}).")
    found = block_digests(pd, text)
    problems = []
    for raw in _REQ_FILE.findall(text):
        body, err = _read_request_file(pd, raw)
        if err:
            problems.append(err)
            continue
        for d, n in block_digests(pd, body).items():
            found[d] = max(found.get(d, 0), n)
    missing = [d for d in stated if found.get(d, 0) < 1]
    if not missing:
        return None
    if not found:
        why = ("the prompt names a panel digest but carries no complete block "
               "(PANEL-TO, PANEL-BODY-BEGIN, the text, PANEL-BODY-END), pasted or in a "
               "PANEL-REQUEST-FILE")
    else:
        why = ("no complete block in the prompt or its PANEL-REQUEST-FILE recomputes to "
               + ", ".join(d[:12] + "..." for d in missing)
               + " (a block for another text, recipient or attachment, or one without a "
                 "PANEL-TO line, does not count)")
    if problems:
        why += "; " + "; ".join(problems)
    return (f"PANEL BLOCK GATE ({_KERNEL_RULE}): {why}. The reviewer cannot repeat a block it "
            f"never saw, so r__subagent-stop__qa-receipt.py would write no receipt and the "
            f"reply-panel Stop gate would loop. {_FIX}")


def main() -> int:
    raw = sys.stdin.read()
    _RAW["text"] = raw
    try:
        data = json.loads(raw)
    except ValueError:
        if _TOKEN.lower() in raw.lower():
            _deny(f"PANEL BLOCK GATE ({_KERNEL_RULE}): the hook payload is not JSON but names "
                  f"{_TOKEN}; the panel request cannot be verified. {_FIX}")
        return 0
    if not isinstance(data, dict):
        if _TOKEN.lower() in raw.lower():
            _deny(f"PANEL BLOCK GATE ({_KERNEL_RULE}): the hook payload is not an object but "
                  f"names {_TOKEN}; the panel request cannot be verified. {_FIX}")
        return 0
    key = _TEXT_KEY.get(str(data.get("tool_name") or ""))
    tin = data.get("tool_input")
    if not key or not isinstance(tin, dict):
        return 0
    text = tin.get(key)
    if not isinstance(text, str) or _TOKEN.lower() not in text.lower():
        return 0
    reason = judge(text)
    if reason:
        _deny(reason, data)
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        sys.path.insert(0, str(_HERE))
        from gate_selftest import run_gate_selftest
        fixtures = sys.argv[2] if len(sys.argv) > 2 else f"registry/fixtures/{_KERNEL_RULE}"
        raise SystemExit(run_gate_selftest(__file__, fixtures))
    try:
        main()
    except Exception as e:
        # fail-CLOSED for a request, open for anything that cannot be one
        if _TOKEN.lower() in _RAW["text"].lower():
            try:
                _deny(f"PANEL BLOCK GATE ({_KERNEL_RULE}) internal error "
                      f"({type(e).__name__}: {e}); the panel request cannot be verified. {_FIX}")
            except Exception:
                pass
    raise SystemExit(0)
