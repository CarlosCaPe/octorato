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
                 "recipients": sorted(normalized recipients)}))

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
`wa-soporte.sh <recipient> <message...> [--archivo <path>]` is read from the
Bash command, only when it is the ONE command of the line: no `;`, `&&`, `|`,
redirection, newline, `$`, backtick or heredoc, and both shell readings agree.
Anything else could change what leaves after the gate read it
(`cp new.pdf doc.pdf && wa-soporte.sh ... --archivo doc.pdf`).

FAIL CLOSED: every case above raises PanelDigestError; the gate denies on it.
Residual, stated: a Gmail forward hashes the comment only, never the forwarded
original (named by id); a reply with no `to` hashes `message:<id>` as its
recipient, not the address the server resolves.

CLI
    panel_digest.py --body-file F [--to R ...] [--attach P ...]
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
    def __init__(self, text: str, attachments: list, recipients: list):
        self.text = text
        self.attachments = attachments      # [(sha256, path)]
        self.recipients = recipients        # [str]

    @property
    def digest(self) -> str:
        return digest(self.text, [h for h, _ in self.attachments], self.recipients)

    def panel_block(self) -> str:
        lines = [f"PANEL-TO: {r}" for r in sorted(norm_recipients(self.recipients))]
        lines += [f"PANEL-ATTACH: {h} {p}" for h, p in self.attachments]
        lines += ["PANEL-BODY-BEGIN", self.text, "PANEL-BODY-END", f"PANEL-SHA256: {self.digest}"]
        return "\n".join(lines)


def normalize(text: str) -> str:
    t = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    return _WS.sub(" ", t).strip()


def norm_recipients(recipients) -> list:
    return sorted({str(r).strip().lower() for r in recipients if str(r).strip()})


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


def digest(text: str, attachment_hashes=(), recipients=()) -> str:
    payload = json.dumps({"text": normalize(text),
                          "attachments": sorted(str(h).lower() for h in attachment_hashes),
                          "recipients": norm_recipients(recipients)},
                         ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def is_digest(value: str) -> bool:
    return bool(_HEX64.match(str(value or "").strip().lower()))


# --------------------------------------------------------------------------
# The reviewer block
# --------------------------------------------------------------------------
_BLOCK = re.compile(r"PANEL-BODY-BEGIN[ \t]*\n(.*?)\n[ \t]*PANEL-BODY-END", re.DOTALL)
_TO = re.compile(r"^[ \t]*PANEL-TO\s*:\s*(\S.*?)\s*$", re.MULTILINE)
_ATTACH = re.compile(r"^[ \t]*PANEL-ATTACH\s*:\s*([0-9a-fA-F]{64})\b(.*)$", re.MULTILINE)


def recompute_from_report(report: str) -> dict | None:
    """The digest recomputed from the LAST reviewer block in a report, with the
    recipients and attachments that precede that block's body. None when the
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
    text = last.group(1)
    return {"digest": digest(text, [h for h, _ in attachments], recipients),
            "attachments": attachments, "recipients": norm_recipients(recipients)}


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


# A sub-command whose FIRST token is one of these only reads its arguments, so
# naming the bridge script there is not a send. The list is the exemption, so
# it holds only programs with NO option, config key or environment variable
# that runs a command: git (-c alias.x=!cmd, core.pager, GIT_PAGER), vim, vi,
# nvim, nano, code, emacs, less, more, man (LESSOPEN, `!cmd`, +cmd) and rg
# (--pre) used to be here and each ran the bridge with no panel. The outward
# send gate imports this set, so the two never drift.
READER_NAMES = frozenset({"grep", "ag", "ls", "cat", "head", "tail", "wc",
                          "stat", "file", "diff", "chmod", "chown"})
_OPERATOR = re.compile(r"^[();<>|&]+$")
# The script name standing as a WORD anywhere inside a token: the whole token,
# a path ending in it, or a word of a command line carried inside one token
# (`alias.x=!<script> ...`, `core.pager=<script> ...`, `GIT_PAGER=<script> ...`,
# vim's `-c '!<script> ...'`). A suffix such as `<script>:` or `<script>.bak`
# is not the word, so a commit message that names the file stays a message.
_SEP = r"\s!=:'\"(;|&`{,<>"
SCRIPT_WORD = re.compile(r"(?:^|[" + _SEP + r"])(?:[^" + _SEP + r"]*/)?"
                         + re.escape(SUPPORT_SCRIPT) + r"(?=$|[\s'\")};|&`<>])")


# A substitution runs its command before the reader in front of it ever sees
# the output: `cat <(<script> ...)`, `cat $(<script> ...)`, `cat \`<script>\``.
SUBST_RUNS_SCRIPT = re.compile(r"(?:[<>$]\(|`)[^)`]*" + re.escape(SUPPORT_SCRIPT))


def names_script(tok: str) -> bool:
    """True when *tok* names the bridge script as a word (see SCRIPT_WORD)."""
    return bool(SCRIPT_WORD.search(str(tok)))


def names_bridge(command: str) -> bool:
    """True when any token of any sub-command names the bridge script as a
    word, the first token not being a pure reader (`grep wa-soporte.sh`), or
    when a substitution runs it behind any command."""
    import receipt_ledger
    if SUBST_RUNS_SCRIPT.search(str(command or "")):
        return True
    for split in (None,) + tuple(_safe_readers()):
        for sc in receipt_ledger.subcommands(command, split):
            toks = receipt_ledger.tokens_of(sc)
            if toks and toks[0] in READER_NAMES:
                continue
            if any(names_script(t) for t in toks):
                return True
    return False


def _safe_readers():
    try:
        return _readers()
    except Exception:
        return ()


def _one_bridge_call(command: str) -> tuple:
    """(recipient, message, archivo) of a command that is exactly one bridge
    invocation, or a PanelDigestError."""
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
    return positionals[0], " ".join(positionals[1:]), archivo


def support_sends(command: str) -> list:
    """[(recipient, message, archivo)] for a Bash command that sends through
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
        return [Message(msg, [(file_sha256(a), a)] if a else [], [r]) for r, msg, a in sends]
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
            msgs = [Message(text, [(file_sha256(p), p) for p in a.attach], a.to)]
        for m in msgs:
            print(m.panel_block() if a.panel_request else m.digest)
        return 0
    except (PanelDigestError, OSError, ValueError) as e:
        print(f"panel_digest: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
