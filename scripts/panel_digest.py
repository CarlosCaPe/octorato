#!/usr/bin/env python3
"""panel_digest.py: the digest a panel reviews and the outward-send gate checks.

WHY A DIGEST
Operator directive 2026-10-02: no message is ever sent without a panel, however
small it looks, and the rule is wired in code. A panel verdict typed by the
main loop is an invention; a verdict recorded by a hook from a reviewer
subagent is a receipt (r__subagent-stop__qa-receipt.py, kind "panel"). The
receipt has to name WHAT was reviewed, and the gate has to tell whether the
message about to leave is that same thing. Both sides compute this function.

THE DIGEST
    sha256(json({"text": normalized_text,
                 "attachments": sorted(sha256 of each attachment's bytes),
                 "recipients": sorted(normalized recipients),
                 "mentions": sorted(normalized mentions)}))

The "mentions" key is present only when the send mentions someone, so a
message with no mention keeps the digest it always had.

normalized_text: "\\r\\n" and "\\r" unified, every run of whitespace collapsed
to one space, ends stripped. A reflowed paragraph keeps its digest; a changed
word, attachment byte or recipient does not. Attachments are hashed by BYTES,
never by path.

THE REVIEWER BLOCK (what binds a receipt to a message)
A stated digest alone binds to nothing: the main loop could show a reviewer
text A and hand it the digest of text B. So the reviewer's final report must
carry the message itself, and the receipt consumer RECOMPUTES the digest from
that block, never trusting the stated line alone:

    PANEL-TO: <recipient>                 one line per recipient
    PANEL-MENTION: <who>                  one line per person mentioned
    PANEL-ATTACH: <sha256> <path>         one line per attachment
    PANEL-BODY-BEGIN
    <the exact text that leaves>
    PANEL-BODY-END
    PANEL-VERDICT: PASS | NEEDS-WORK
    PANEL-SHA256: <digest>

`panel_digest.py --panel-request ...` prints that block (without the verdict)
for the main loop to hand to the reviewer, who repeats it and adds its
verdict. The last block of the report is the one read.

WHICH FIELDS (per tool; any other key denies)
Each send tool has a KNOWN key set. A key outside it (a snake_case `draft_id`,
`html_body`, a field a server adds later) is an error, because a field the
gate does not read is a field that could carry what leaves. Text fields are
joined in a fixed order: subject, body, htmlBody, forwardText, message.
A draft sent by id is an error: its content is not in the call.

THE SUPPORT BRIDGE
`wa-soporte.sh <recipient> <message...> [--archivo <path>] [--menciones <a,b>]`
is read from the Bash command, only when it is the ONE command of the line: no
`;`, `&&`, `|`, redirection, newline, `$`, backtick or heredoc, and both shell
readings agree. Anything else could change what leaves after the gate read it
(`cp new.pdf doc.pdf && wa-soporte.sh ... --archivo doc.pdf`).

ONE READER FOR THE SCRIPT'S ARGUMENTS: `parse_bridge_args`. The script takes
its flags anywhere on the line and strips them with their value; whatever is
left is the recipient, then the message. The digest, the gate's recipient
readers and the sent-message ledger all call this one function, because a flag
the script knows and a reader does not is a send the reader misreads: the
flag's value becomes the recipient, or the flag becomes message text. A flag
added to the script is added to BRIDGE_VALUE_FLAGS, nowhere else. The reader is
stricter than the script where the script is lenient (a repeated flag, a value
that is itself a flag): those deny.

Mentions decide who gets notified, so they are part of what a panel approves.
The script also reads a WA_MENCIONES variable it inherits. A Bash call cannot
set it (an assignment in front of the script is refused below), and when the
hook's own environment carries it and the call has no `--menciones`, the call
denies: those mentions would leave bound to nothing. Residual, stated: a
variable present in the shell that runs the command and absent from the
hook's environment is not seen.

FAIL CLOSED: every case above raises PanelDigestError; the gate denies on it.
Residual, stated: a Gmail forward hashes the comment only, never the forwarded
original (named by id); a reply with no `to` hashes `message:<id>` as its
recipient, not the address the server resolves.

CLI
    panel_digest.py --body-file F [--to R ...] [--attach P ...] [--mention M ...]
    panel_digest.py --tool-input F.json --tool-name NAME
    either form plus --panel-request prints the reviewer block instead
A mail's body file is the subject line, then the body (then htmlBody).
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import shlex
import stat
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

TEXT_ORDER = ("subject", "body", "htmlBody", "forwardText", "message")
SUPPORT_SCRIPT = "wa-soporte.sh"
# Every flag of the support script that takes a value. The script strips each
# one and its value wherever it sits; so does parse_bridge_args.
BRIDGE_VALUE_FLAGS = ("--archivo", "--menciones")
MENTIONS_ENV = "WA_MENCIONES"
_WS = re.compile(r"\s+")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")

# Known keys per send tool, by the tool name's suffix. Metadata keys that never
# carry content are listed so they do not trip the unknown-key rule.
KNOWN_KEYS = {
    "mcp__gmail__send_email": {"to", "cc", "bcc", "subject", "body", "htmlBody", "mimeType",
                               "attachments", "threadId", "inReplyTo"},
    "mcp__claude_ai_Gmail__send_message": {"to", "cc", "bcc", "subject", "body", "htmlBody",
                                           "attachments", "draftId", "replyThreadId",
                                           "replyToMessageId"},
    "mcp__claude_ai_Gmail__reply": {"messageId", "body", "htmlBody", "to", "cc", "bcc", "replyAll"},
    "mcp__claude_ai_Gmail__forward": {"messageId", "forwardText", "htmlBody", "to", "cc", "bcc"},
    "mcp__whatsapp__send_message": {"recipient", "message"},
    "mcp__whatsapp__send_file": {"recipient", "media_path"},
    "mcp__whatsapp__send_audio_message": {"recipient", "media_path"},
}
_DRAFT_KEYS = ("draftId", "draft_id", "draftID")


class PanelDigestError(ValueError):
    """The outgoing message cannot be determined with certainty."""


class Message:
    def __init__(self, text: str, attachments: list, recipients: list, mentions=()):
        self.text = text
        self.attachments = attachments      # [(sha256, path)]
        self.recipients = recipients        # [str]
        self.mentions = list(mentions)      # [str]

    @property
    def digest(self) -> str:
        return digest(self.text, [h for h, _ in self.attachments], self.recipients, self.mentions)

    def panel_block(self) -> str:
        lines = [f"PANEL-TO: {r}" for r in sorted(norm_recipients(self.recipients))]
        lines += [f"PANEL-MENTION: {m}" for m in norm_mentions(self.mentions)]
        lines += [f"PANEL-ATTACH: {h} {p}" for h, p in self.attachments]
        lines += ["PANEL-BODY-BEGIN", self.text, "PANEL-BODY-END", f"PANEL-SHA256: {self.digest}"]
        return "\n".join(lines)


def normalize(text: str) -> str:
    t = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    return _WS.sub(" ", t).strip()


def norm_recipients(recipients) -> list:
    return sorted({str(r).strip().lower() for r in recipients if str(r).strip()})


def norm_mentions(mentions) -> list:
    return sorted({str(m).strip().lower() for m in mentions if str(m).strip()})


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


def digest(text: str, attachment_hashes=(), recipients=(), mentions=()) -> str:
    fields = {"text": normalize(text),
              "attachments": sorted(str(h).lower() for h in attachment_hashes),
              "recipients": norm_recipients(recipients)}
    who = norm_mentions(mentions)
    if who:
        # Only when someone is mentioned: a send with no mention keeps the
        # digest it had before mentions were part of it.
        fields["mentions"] = who
    payload = json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def is_digest(value: str) -> bool:
    return bool(_HEX64.match(str(value or "").strip().lower()))


# --------------------------------------------------------------------------
# The reviewer block
# --------------------------------------------------------------------------
_BLOCK = re.compile(r"PANEL-BODY-BEGIN[ \t]*\n(.*?)\n[ \t]*PANEL-BODY-END", re.DOTALL)
_TO = re.compile(r"^[ \t]*PANEL-TO\s*:\s*(\S.*?)\s*$", re.MULTILINE)
_ATTACH = re.compile(r"^[ \t]*PANEL-ATTACH\s*:\s*([0-9a-fA-F]{64})\b(.*)$", re.MULTILINE)
_MENTION = re.compile(r"^[ \t]*PANEL-MENTION\s*:\s*(\S.*?)\s*$", re.MULTILINE)


def recompute_from_report(report: str) -> dict | None:
    """The digest recomputed from the LAST reviewer block in a report, with the
    recipients, mentions and attachments that precede that block's body. None when the
    report carries no block. Lines before the previous block are not read, so a
    block quoted earlier cannot lend its recipients to the real one."""
    if not report:
        return None
    blocks = list(_BLOCK.finditer(report))
    if not blocks:
        return None
    last = blocks[-1]
    prev_end = blocks[-2].end() if len(blocks) > 1 else 0
    head = report[prev_end:last.start()]
    recipients = [m.group(1) for m in _TO.finditer(head)]
    attachments = [(m.group(1).lower(), m.group(2).strip()) for m in _ATTACH.finditer(head)]
    mentions = [m.group(1) for m in _MENTION.finditer(head)]
    text = last.group(1)
    return {"digest": digest(text, [h for h, _ in attachments], recipients, mentions),
            "attachments": attachments, "recipients": norm_recipients(recipients),
            "mentions": norm_mentions(mentions)}


# --------------------------------------------------------------------------
# What a send tool carries
# --------------------------------------------------------------------------

def _people(tool_input: dict) -> list:
    out = []
    for key in ("to", "cc", "bcc"):
        v = tool_input.get(key)
        if v is None:
            continue
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, list) and all(isinstance(x, str) for x in v):
            out.extend(v)
        else:
            raise PanelDigestError(f"field {key!r} is not a list of addresses")
    return out


def _mcp_message(tool_name: str, tool_input) -> Message:
    if not isinstance(tool_input, dict):
        raise PanelDigestError("tool input is not an object")
    known = KNOWN_KEYS.get(tool_name)
    if known is None:
        raise PanelDigestError(f"send tool {tool_name!r} has no known key set")
    if any(tool_input.get(k) for k in _DRAFT_KEYS):
        raise PanelDigestError("a draft sent by id: its content is not in the call")
    unknown = sorted(set(tool_input) - known)
    if unknown:
        raise PanelDigestError(f"unknown field(s) {unknown}: a field the gate does not read "
                               f"could carry what leaves")
    texts = []
    for key in TEXT_ORDER:
        val = tool_input.get(key)
        if val is None:
            continue
        if not isinstance(val, str):
            raise PanelDigestError(f"field {key!r} is not text")
        texts.append(val)
    attachments = []
    if tool_input.get("media_path") is not None:
        mp = tool_input["media_path"]
        if not isinstance(mp, str) or not mp.strip():
            raise PanelDigestError("media_path is not a path")
        attachments.append((file_sha256(mp), mp))
    atts = tool_input.get("attachments")
    if atts is not None:
        if not isinstance(atts, list):
            raise PanelDigestError("attachments is not a list")
        for a in atts:
            if isinstance(a, str):
                attachments.append((file_sha256(a), a))
            elif isinstance(a, dict) and isinstance(a.get("content"), str):
                try:
                    raw = base64.b64decode(a["content"], validate=True)
                except (binascii.Error, ValueError):
                    raise PanelDigestError("attachment content is not valid base64")
                attachments.append((hashlib.sha256(raw).hexdigest(), str(a.get("filename") or "inline")))
            else:
                raise PanelDigestError("attachment of an unknown shape")
    if "whatsapp" in tool_name:
        recipients = [str(tool_input.get("recipient") or "")]
    else:
        recipients = _people(tool_input)
        if tool_input.get("messageId"):
            recipients.append(f"message:{tool_input['messageId']}")
    if not norm_recipients(recipients):
        raise PanelDigestError("the send names no recipient")
    if not texts and not attachments:
        raise PanelDigestError("the send carries neither text nor an attachment")
    return Message("\n".join(texts), attachments, recipients)


def _readers():
    import receipt_ledger
    mod = receipt_ledger._qa_gate_module()
    return (mod._split_bash, mod._split_master)


_READER_NAMES = {"grep", "rg", "ag", "ls", "cat", "less", "more", "head", "tail", "wc",
                 "stat", "file", "diff", "vim", "nano", "code", "chmod", "chown", "git"}
_OPERATOR = re.compile(r"^[();<>|&]+$")


def names_bridge(command: str) -> bool:
    """True when any token of any sub-command is the bridge script, the first
    token not being a reader (`grep wa-soporte.sh` reads the name)."""
    import receipt_ledger
    for split in (None,) + tuple(_safe_readers()):
        for sc in receipt_ledger.subcommands(command, split):
            toks = receipt_ledger.tokens_of(sc)
            if toks and toks[0] in _READER_NAMES:
                continue
            if any(receipt_ledger._is_script_token(t, SUPPORT_SCRIPT) for t in toks):
                return True
    return False


def _safe_readers():
    try:
        return _readers()
    except Exception:
        return ()


def parse_bridge_args(rest) -> tuple:
    """(recipient, message, archivo, mentions) from the tokens that follow the
    support script, read the way the script reads them: a value flag and its
    value are stripped wherever they sit, the first token left is the
    recipient and the others are the message. Raises PanelDigestError when the
    line cannot be read with certainty. THE one reader of the script's
    arguments: the digest, the gate and the ledger all call it."""
    positionals, values, j = [], {}, 0
    rest = list(rest)
    while j < len(rest):
        tok = rest[j]
        if tok in BRIDGE_VALUE_FLAGS:
            if tok in values:
                raise PanelDigestError(f"{tok} given more than once")
            if j + 1 >= len(rest) or not str(rest[j + 1]).strip():
                raise PanelDigestError(f"{tok} without a value")
            value = rest[j + 1]
            if value.startswith("--"):
                raise PanelDigestError(f"{tok} takes {value!r} as its value: a flag where a "
                                       f"value belongs")
            values[tok] = value
            j += 2
            continue
        positionals.append(tok)
        j += 1
    if len(positionals) < 2:
        raise PanelDigestError("the support bridge call carries no message")
    mentions = []
    if "--menciones" in values:
        mentions = [m.strip() for m in values["--menciones"].split(",") if m.strip()]
        if not mentions:
            raise PanelDigestError("--menciones names nobody")
    return positionals[0], " ".join(positionals[1:]), values.get("--archivo"), mentions


def bridge_recipient(rest) -> str:
    """The recipient parse_bridge_args reads, "" when the line cannot be read.
    For callers that decide a waiver: no certain recipient, no waiver."""
    try:
        return str(parse_bridge_args(rest)[0]).strip()
    except PanelDigestError:
        return ""


def _one_bridge_call(command: str) -> tuple:
    """(recipient, message, archivo, mentions) of a command that is exactly one
    bridge invocation, or a PanelDigestError."""
    import receipt_ledger
    if any(m in command for m in ("$", "`", "<<")) or "\n" in command.strip():
        raise PanelDigestError("the bridge call carries shell expansion, a heredoc or a "
                               "newline: what the shell sends is not what the gate read")
    try:
        lex = shlex.shlex(command, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        toks = list(lex)
    except ValueError:
        raise PanelDigestError("the bridge call does not parse as one shell command")
    if any(_OPERATOR.match(t) for t in toks):
        raise PanelDigestError("the bridge call must be the only command of the line: no ;, &&, "
                               "|, & or redirection (an earlier command could change what leaves)")
    for split in _readers():
        parts = [p for p in split(command) if p.strip()]
        if len(parts) != 1:
            raise PanelDigestError("the bridge call must be the only command of the line")
    start = 1 if toks and toks[0] in ("bash", "sh") and len(toks) > 1 else 0
    if not toks or not receipt_ledger._is_script_token(toks[start], SUPPORT_SCRIPT) \
            or "=" in toks[start]:
        raise PanelDigestError("the support bridge is not invoked as a plain command "
                               "(a wrapper, a variable or an assignment)")
    recipient, message, archivo, mentions = parse_bridge_args(toks[start + 1:])
    if not mentions and os.environ.get(MENTIONS_ENV, "").strip():
        raise PanelDigestError(f"{MENTIONS_ENV} is set in the environment and the call has no "
                               f"--menciones: the script would mention people no panel saw. "
                               f"Pass them with --menciones, or unset the variable")
    return recipient, message, archivo, mentions


def support_sends(command: str) -> list:
    """[(recipient, message, archivo, mentions)] for a Bash command that sends through
    the bridge ([] when it names no bridge), or a PanelDigestError."""
    command = str(command or "")
    if not names_bridge(command):
        return []
    return [_one_bridge_call(command)]


def message_parts(tool_name: str, tool_input) -> list:
    """[Message], one per message the call sends."""
    if tool_name == "Bash":
        cmd = str((tool_input or {}).get("command", "")) if isinstance(tool_input, dict) else ""
        sends = support_sends(cmd)
        if not sends:
            raise PanelDigestError("no support-bridge send could be read from the command")
        return [Message(msg, [(file_sha256(a), a)] if a else [], [r], who)
                for r, msg, a, who in sends]
    return [_mcp_message(tool_name, tool_input)]


def digests_for(tool_name: str, tool_input) -> list:
    return [m.digest for m in message_parts(tool_name, tool_input)]


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _cli(argv: list) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Digest of an outgoing message for a panel receipt.")
    ap.add_argument("--body-file", help="file with the message text (mail: subject line, then body)")
    ap.add_argument("--to", action="append", default=[], help="recipient (repeatable)")
    ap.add_argument("--attach", action="append", default=[], help="attachment path (repeatable)")
    ap.add_argument("--mention", action="append", default=[],
                    help="person mentioned in the message (repeatable)")
    ap.add_argument("--tool-input", help="JSON file with the send tool's input")
    ap.add_argument("--tool-name", default="", help="send tool name, with --tool-input")
    ap.add_argument("--panel-request", action="store_true",
                    help="print the reviewer block (recipients, attachments, body, digest)")
    a = ap.parse_args(argv)
    try:
        if a.tool_input:
            msgs = message_parts(a.tool_name, json.loads(Path(a.tool_input).read_text(encoding="utf-8")))
        else:
            text = Path(a.body_file).read_text(encoding="utf-8") if a.body_file else sys.stdin.read()
            if not a.to:
                raise PanelDigestError("--to is required: the recipient is part of the digest")
            msgs = [Message(text, [(file_sha256(p), p) for p in a.attach], a.to, a.mention)]
        for m in msgs:
            print(m.panel_block() if a.panel_request else m.digest)
        return 0
    except (PanelDigestError, OSError, ValueError) as e:
        print(f"panel_digest: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
