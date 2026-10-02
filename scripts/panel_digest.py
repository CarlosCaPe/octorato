#!/usr/bin/env python3
"""panel_digest.py: the digest a panel reviews and the outward-send gate checks.

WHY A DIGEST
Operator directive 2026-10-02: no message leaves without a panel, however small
it looks, and the rule is wired in code. A panel verdict typed by the main loop
is an invention; a verdict recorded by a hook from a reviewer subagent is a
receipt (see r__subagent-stop__qa-receipt.py, kind "panel"). The receipt has to
name WHAT was reviewed, and the gate has to tell whether the message about to
leave is that same thing. Both sides compute one function, this one, so a
reviewed body that is edited afterwards, or an attachment that is swapped, no
longer matches and the send is denied.

THE DIGEST
    sha256( normalized_text + "\\n" + "\\n".join(sorted(sha256(file) for file)) )

normalized_text: the message text with "\\r\\n" and "\\r" unified to "\\n",
every run of whitespace collapsed to one space, and the ends stripped. So a
reflowed paragraph keeps its digest and a changed word does not. The
attachment hashes are of the file BYTES, never the path: a different file at
the same path is a different message.

WHICH TEXT (message_parts)
A send tool carries its text in named fields. They are read in this fixed order
and joined with a newline, which normalization turns into one space:
    subject, body, htmlBody, forwardText, message, caption
WhatsApp send_file / send_audio_message carry no text, only `media_path`. The
support bridge (`wa-soporte.sh <recipient> <message...> [--archivo <path>]`)
is read from the Bash command: its message is every positional after the
recipient, joined by one space, exactly as the script builds `$*`.

FAIL CLOSED
message_parts raises PanelDigestError whenever it cannot say with certainty
what leaves: a draft sent by id (the body is not in the call), an attachment
that is not a readable regular file or not valid base64, a Bash send hidden
behind a wrapper, a variable, a substitution or a heredoc, or two shell
readings that disagree. The gate turns that into a deny.

Residuals, stated: the recipient is not part of the digest (a reviewed message
sent to another chat still matches); a Gmail forward hashes the comment text
only, never the forwarded original, which the call names by id.

CLI (for the main loop when it hands a message to a panel):
    panel_digest.py --body-file F [--attach P ...]
    panel_digest.py --attach P ...            (text from stdin)
    panel_digest.py --tool-input F.json --tool-name NAME
A mail's body file is the subject line, then the body (then the HTML body, if
the send carries one). Prints the 64-hex digest.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

TEXT_KEYS = ("subject", "body", "htmlBody", "forwardText", "message", "caption")
SUPPORT_SCRIPT = "wa-soporte.sh"
_WS = re.compile(r"\s+")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
# Shell syntax whose value the hook cannot know: the message would be whatever
# the shell expands at run time, not what the gate read.
_UNKNOWABLE = ("$", "`", "<<", "{}")


class PanelDigestError(ValueError):
    """The outgoing message cannot be determined with certainty."""


def normalize(text: str) -> str:
    t = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    return _WS.sub(" ", t).strip()


def file_sha256(path: str) -> str:
    p = Path(os.path.expanduser(str(path)))
    try:
        st = os.stat(p)
    except OSError as e:
        raise PanelDigestError(f"attachment not readable: {path} ({type(e).__name__})")
    if not stat.S_ISREG(st.st_mode):
        raise PanelDigestError(f"attachment is not a regular file: {path}")
    h = hashlib.sha256()
    try:
        with open(p, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    except OSError as e:
        raise PanelDigestError(f"attachment not readable: {path} ({type(e).__name__})")
    return h.hexdigest()


def bytes_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest(text: str, attachment_hashes=()) -> str:
    hashes = sorted(str(h).lower() for h in attachment_hashes)
    payload = normalize(text) + "\n" + "\n".join(hashes)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def is_digest(value: str) -> bool:
    return bool(_HEX64.match(str(value or "").strip().lower()))


# --------------------------------------------------------------------------
# What a send tool carries
# --------------------------------------------------------------------------

def _mcp_parts(tool_name: str, tool_input: dict) -> list:
    """[(text, [attachment sha256...])] for one MCP send call."""
    if not isinstance(tool_input, dict):
        raise PanelDigestError("tool input is not an object")
    if tool_input.get("draftId"):
        raise PanelDigestError("a draft sent by id: its body is not in the call")
    texts = []
    for key in TEXT_KEYS:
        val = tool_input.get(key)
        if val is None:
            continue
        if not isinstance(val, str):
            raise PanelDigestError(f"field {key!r} is not text")
        texts.append(val)
    hashes = []
    for key in ("media_path", "attachment", "file_path"):
        if tool_input.get(key) is not None:
            if not isinstance(tool_input[key], str) or not tool_input[key].strip():
                raise PanelDigestError(f"field {key!r} is not a path")
            hashes.append(file_sha256(tool_input[key]))
    atts = tool_input.get("attachments")
    if atts is not None:
        if not isinstance(atts, list):
            raise PanelDigestError("attachments is not a list")
        for a in atts:
            if isinstance(a, str):
                hashes.append(file_sha256(a))
            elif isinstance(a, dict) and isinstance(a.get("content"), str):
                try:
                    raw = base64.b64decode(a["content"], validate=True)
                except (binascii.Error, ValueError):
                    raise PanelDigestError("attachment content is not valid base64")
                hashes.append(bytes_sha256(raw))
            else:
                raise PanelDigestError("attachment of an unknown shape")
    if not texts and not hashes:
        raise PanelDigestError("the send carries neither text nor an attachment")
    return [("\n".join(texts), hashes)]


def _readers():
    import receipt_ledger
    mod = receipt_ledger._qa_gate_module()
    return (mod._split_bash, mod._split_master)


def _support_sends(command: str, split) -> list:
    """Every support-bridge invocation under one shell reading, as
    (recipient, message, archivo or None). Raises when one is not plain."""
    import receipt_ledger
    out = []
    for sc in receipt_ledger.subcommands(command, split):
        toks = receipt_ledger.tokens_of(sc)
        if not any(receipt_ledger._is_script_token(t, SUPPORT_SCRIPT) for t in toks):
            continue
        if toks and toks[0] in _reader_names():
            continue
        start = 0
        if toks and toks[0] in ("bash", "sh") and len(toks) > 1:
            start = 1
        if not receipt_ledger._is_script_token(toks[start], SUPPORT_SCRIPT) or \
                "=" in toks[start]:
            raise PanelDigestError("the support bridge is not invoked as a plain command "
                                   "(a wrapper, a variable or an assignment)")
        rest = toks[start + 1:]
        positionals, archivo, j = [], None, 0
        while j < len(rest):
            if rest[j] == "--archivo":
                if j + 1 >= len(rest) or archivo is not None:
                    raise PanelDigestError("--archivo without a single path")
                archivo = rest[j + 1]
                j += 2
                continue
            positionals.append(rest[j])
            j += 1
        if len(positionals) < 2:
            raise PanelDigestError("the support bridge call carries no message")
        out.append((positionals[0], " ".join(positionals[1:]), archivo))
    return out


def _reader_names():
    # Same set as the gate's _READERS: a sub-command that only reads the name.
    return {"grep", "rg", "ag", "ls", "cat", "less", "more", "head", "tail", "wc",
            "stat", "file", "diff", "vim", "nano", "code", "chmod", "chown", "git"}


def support_sends(command: str) -> list:
    """(recipient, message, archivo) for every support-bridge send in a Bash
    command, the same under both of the merge gate's shell readings, or a
    PanelDigestError. [] when the command sends nothing through the bridge."""
    command = str(command or "")
    readings = []
    for split in _readers():
        sends = sorted(set(_support_sends(command, split)), key=repr)
        readings.append(sends)
    if any(r != readings[0] for r in readings[1:]):
        raise PanelDigestError("the two shell readings disagree on what the bridge sends")
    sends = readings[0]
    if sends and any(m in command for m in _UNKNOWABLE):
        raise PanelDigestError("the command carries shell expansion ($, backtick, heredoc "
                               "or {}): the message the shell sends is not the one the gate reads")
    return sends


def message_parts(tool_name: str, tool_input) -> list:
    """[(text, [attachment sha256...])], one per message the call sends."""
    if tool_name == "Bash":
        cmd = str((tool_input or {}).get("command", "")) if isinstance(tool_input, dict) else ""
        sends = support_sends(cmd)
        if not sends:
            raise PanelDigestError("no support-bridge send could be read from the command")
        return [(msg, [file_sha256(a)] if a else []) for _, msg, a in sends]
    return _mcp_parts(tool_name, tool_input)


def digests_for(tool_name: str, tool_input) -> list:
    return [digest(t, h) for t, h in message_parts(tool_name, tool_input)]


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _cli(argv: list) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Digest of an outgoing message for a panel receipt.")
    ap.add_argument("--body-file", help="file with the message text (mail: subject line, then body)")
    ap.add_argument("--attach", action="append", default=[], help="attachment path (repeatable)")
    ap.add_argument("--tool-input", help="JSON file with the send tool's input")
    ap.add_argument("--tool-name", default="", help="send tool name, with --tool-input")
    a = ap.parse_args(argv)
    try:
        if a.tool_input:
            data = json.loads(Path(a.tool_input).read_text(encoding="utf-8"))
            for d in digests_for(a.tool_name, data):
                print(d)
            return 0
        text = Path(a.body_file).read_text(encoding="utf-8") if a.body_file else sys.stdin.read()
        print(digest(text, [file_sha256(p) for p in a.attach]))
        return 0
    except (PanelDigestError, OSError, ValueError) as e:
        print(f"panel_digest: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
