#!/usr/bin/env python3
"""g__pretool-mcp__outward-send.py: the ONE outward-send gate (v7 phase 2).

THE FAILURE THIS EXISTS FOR
Every COMMS gate in this brain was born after an incident, keyed on the phrase
that caused it, and fires at Stop, after the reply is composed. A send tool
runs mid-turn, before Stop, so a mail that leaves inside a tool call is judged
only after it has left. On 2026-09-05 a formal complaint email shipped a false
"no origin" claim that way; the phrase gate written for it arrived after the
send. The structural gap is not the phrase, it is WHEN and WHERE the check
runs. This gate runs before the tool, on the body the tool is about to send.

WHAT IT GATES
PreToolUse on the send tools by name (mail send/reply/forward, WhatsApp send),
and on Bash when the command invokes an outward channel (the support bridge
sender, a deploy, a release). Drafts are not sends: draft_email/create_draft
stay with the Stop gates, because the operator reviews them before they leave.

WHAT IT REQUIRES (docs/architecture/v7-nothing-ships-unverified.md)
  1. Gate receipt. brain_doctor recorded a gate-liveness PASS for the brain's
     current HEAD (receipt_ledger.gate_receipt_ok). Without it the six phrase
     detectors below may be dead on this tree, and a dead gate that looks green
     is the failure mode the research found in every other project.
  2. Seek receipt, only when the body carries an ABSENCE claim ("no reconozco",
     "sin origen", "no corresponde a ningún servicio", "no record of"...). The
     turn must hold a seek receipt anchored to a real tool_use in the
     transcript. A body with no absence claim needs no seek.
  1b. A mail send whose subject opens with Re:/Fwd: must carry threadId or
     inReplyTo (a reply outside its thread cuts the sequence).
  3. No unsourced classifying attribute in a consent context, and no
     first-person promise: those are already blocks at Stop; here they block
     before the send, reusing the exact detectors of the Stop gates so the
     vocabulary lives in one place per class.
  4. Explicit send ask (operator directive 2026-08-14: deliver by default,
     transmit only the message that was asked for). A non-negated send verb
     must stand in the operator's own prompt for the turn, outside quotes and
     code spans; `send-ok` is the standing hatch. Checked after 1-3, so every
     earlier deny keeps its own name. v10 (AC-05..07): the tracked
     registry/send-ask.yaml adds the Send_Ask list, matched case- and
     accent-insensitively, and a bare go-ahead never counts; only an operator
     opener (origin.kind human, or no origin and neither a compact summary nor
     isMeta) carries hatches and its own ask; a turn opened by a notification,
     a peer message or a compact summary reads the ask from the operator's
     latest real prompt, only when this send's panel receipt was recorded
     after that prompt. A Bash command that names the support script
     ANYWHERE (as a word in the raw text, in a substitution, or in any token
     of any sub-command after quote removal) is a send unless the WHOLE
     command is one plain read (panel_digest.plain_read): a READER_NAMES
     program (cat, head, tail, grep, wc, stat, file, diff, ls, chmod, chown)
     with plain words, `sed -n <range>p <script>`, or `<script> --help|-h`,
     with no pipe, ; && || &, newline, redirect, $, backtick, ( ), braces,
     glob, ! or #, and no quoted string holding $, backtick, a backslash or a
     newline. There is no list of executors: text deny-lists did not converge
     (`| sh`, then `| nice sh`, then `|<newline>sh`, `bash -c '...'`,
     `> /tmp/f; sh /tmp/f`, `| $SHELL`, `| mksh`), so the exemption is the
     one exact shape and everything else that names the script is judged as
     a send. git, the editors, less, more, man, rg and ag are not readers,
     because each has an option, config key or env var that runs a command.
     Cost, stated: a pipe, a chain or a git or editor command that names the
     script (`grep x <script> | head`, `git log -- <script>`, `cd d && cat
     <script>`) is denied without a panel; read the script with one plain
     command and no pipe. Measured on 26,933 real commands: 18 allow to
     deny, 0 deny to allow. Residual, stated: a command that reaches the
     script without its name (a glob `wa-sop*.sh`, a brace `{wa-soporte,x}`,
     `find -name`, a variable, an alias, a function, a symlink, a copy made
     in an earlier call) is not tied to the script.
  5. Panel receipt (FLOW.panel-before-send, operator directive 2026-10-02: no
     message leaves without a panel, however small). Every MESSAGE send (mail
     send/reply/forward, WhatsApp send_message/send_file/send_audio_message,
     the support bridge, its --archivo included) computes panel_digest.py over
     the outgoing text plus the bytes of every attachment, and is denied
     unless the panel receipt that DECIDES that digest in this session, inside
     120 minutes, says PASS (receipt_ledger.panel_pass_for). A later
     NEEDS-WORK for the same digest revokes. NO hatch: send-ok, the
     autonomous-chat allowlist and a chat-typed send-ok waive requirement 4
     only, never this one. The digest covers the recipients too, the
     receipt must recompute from the body block the reviewer read, and a
     receipt authorises ONE send (sent.jsonl). A raw send that reaches a
     bridge's send path without the script or the MCP tool (/api/send,
     /api/react, a bridge port, SSM send-command) is denied outright.
     Fail closed: a body or attachment the gate cannot
     read with certainty (panel_digest.PanelDigestError), an unreadable
     ledger and a crash all deny. Checked LAST, so the earlier checks keep
     their own deny and their fixtures stay meaningful. Deploys and releases
     are not messages and are out of scope here.

The Stop gates are not replaced. They still catch drafts and prose; this gate
is the choke point for what actually leaves, and it imports their detectors so
"contributor" means literally the same function.

Deny shape: hookSpecificOutput.permissionDecision = "deny" with the missing
receipt named. Hatches (absence-ok, attribute-ok, draft-promise-ok, send-ok)
count only in the operator's own prompt for the turn, never in the body: a
token in the body would ship to the recipient and be self-serve. Fail-open on any error EXCEPT after a send was positively
identified and a receipt check itself crashed, which denies (same stance as
qa-merge-gate). Requirement 4 is fail-closed by construction: no readable
operator turn (missing transcript, forged or sidechain human entry) means no
ask, so the send is denied.

Autonomous chats: `~/.claude/company/config/outward-send-autonomous.json`
     ({"chats": [{"jid": "...", "label": "...", "since": "YYYY-MM-DD"}]}, private)
     names chats where the operator has standing instructions to reply and act;
     a send to a listed recipient skips requirement 4 only. A listed chat with
     "send_ok_from_chat": true also lets the operator type `send-ok` IN that
     chat (his own phone, is_from_me = 1 in the bridge store) to release a
     MESSAGE send to a third party within "window_minutes" (default 60, valid
     1..240); never a deploy or a release. The store is always
     ~/.config/whatsapp-mcp/store/messages.db (no per-chat path). Residual,
     stated plainly: that store and the config are files under $HOME a hooked
     process can write, so one config write plus one store row lifts the send
     ask for every message send to any recipient for up to 240 minutes; wider
     than the per-recipient allowlist, narrower than the prompt hatch (the row
     stays visible in the bridge database and the write lands in the kernel
     journal). One token covers every send in its window, not one send.
     Residual, stated: the config file is not on the arming surface (company/ is
     the operator's private config, not a gate body), so a hooked process CAN
     write it; measured ALLOW for a Write to it and for `tee` into it while a
     Write to hooks.json denies. A self-inserted JID lifts the send ask only:
     the gate receipt, absence, attribute, promise and thread checks still run,
     the write lands in the kernel journal, and the operator owns the list.

Selftest: CLAUDE_SESSION_ID=__selftest__ (set by gate_selftest, never reachable
from the model's inline env) makes the gate accept HEAD and gates "SELFTEST" in
the seeded global ledger, since a fixture cannot know the live tree.

Stdin:  PreToolUse payload {"session_id", "transcript_path", "tool_name",
        "tool_input", "cwd", ...}
Stdout: deny JSON on a hit, else nothing. Exit always 0.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

_SEND_TOOL = re.compile(
    r"(send_email|send_message|send_file|send_audio_message|__reply$|__forward$)",
    re.IGNORECASE,
)
# Bash sends are found by TOKEN in the argv of any sub-command (after the
# unquoted split and the wrapper peel): `bash -x`, `setsid`, `xargs`, `eval`
# and every interpreter form carry the script name as its own token, while a
# quoted commit message is one token that is not the name (QA cycle 3). The
# residual is indirection that hides the name from argv ($(echo ...),
# python -c subprocess, find -exec), accepted as in qa-merge-gate.
_SEND_SCRIPTS = ("wa-soporte.sh",)
# panel_digest.READER_NAMES (one list, two consumers) is the program set of the
# one plain-read shape, and the raw-send rules below skip those readers too.
# An import failure leaves the set EMPTY and plain_read unreachable, so no
# reader is exempt (fail closed).
try:
    import panel_digest as _panel_digest  # noqa: E402
    _READERS = _panel_digest.READER_NAMES
except Exception:
    _READERS = frozenset()
_BODY_KEYS = ("body", "message", "text", "content", "html", "snippet",
              "caption", "subject", "description", "title", "command")
# A hatch counts only as a standalone word in the operator's prompt, outside
# quotes and code spans, and exempts only the class it names (send-ok: all).
_HATCH = re.compile(r"(?:^|(?<=[\s(\[]))(absence-ok|attribute-ok|draft-promise-ok|send-ok)(?=[\s,.;:!)\]]|$)", re.MULTILINE)
_QUOTE_SPAN = re.compile(r"\"[^\"\n]*\"|(?<!\w)'[^'\n]*'(?!\w)|`[^`\n]*`|«[^»]*»|[“”][^“”]*[“”]")


def hatches(prompt: str) -> set:
    return set(_HATCH.findall(_QUOTE_SPAN.sub(" ", prompt or "")))


# 4. A send ask is a send verb in the operator's prompt inside a clause that
# carries no negation, deferral or opinion token, with no later clause carrying
# a negation or deferral. Clauses split on . ; : ! ? newline, comma, and the
# connectors pero/but/y/and/aunque/though. ES imperatives count anywhere in the
# clause (mándalo, envíaselo; "me"/"nos" clitics excluded, "mándame el texto" is
# the paste-ready ask that must NOT transmit); ES infinitives only at clause
# start or after an ask frame (puedes enviarlo, favor de mandarlo), never as a
# noun phrase (falta mandarlo, prohibido enviarlo, "TODO: mandarlo"); ES subjunctives only inside a
# "que ..." frame (quiero que lo mandes). EN verbs at clause start or after a
# frame token, followed by an object or the clause end ("reply came in" and
# "the release notes" do not count). Two blocker lists: _PRE_BLOCK tokens only
# count before the verb (sin enviar, ni lo mandes, ¿conviene mandarlo?, falta
# enviarlo) so "mándalo sin asunto" still asks; _ANY_BLOCK tokens count anywhere
# in the ask clause and in every later clause (mándalo pero no ahora, mándalo
# mañana, mandarlo sería un error, "mándalo. bueno, no"). Fail-closed by design:
# on a false deny the operator repeats the verb alone or uses send-ok.
_CLITIC = r"(?:lo|la|los|las|le|les|se|selo|sela|selos|selas)?"
_ES_IMP = (r"(?<![\w-])(?:m[aá]nda|m[aá]nde|env[ií]a|env[ií]e|resp[oó]nde|responda|cont[eé]sta|conteste"
           r"|reenv[ií]a|reenv[ií]e|publ[ií]ca|publique|despliega|despliegue|lanza|lance)" + _CLITIC + r"(?![\w-])")
_ES_INF = (r"(?:^|(?<![\w-])(?:puedes|podr[ií]as|puede|podr[ií]a|favor de|por favor|hay que|toca|procede"
           r"|ok|okay|s[ií]|yes|please|just|y|e|and)\s+)"
           r"(?:mandar|enviar|responder|contestar|reenviar|publicar|desplegar|lanzar)" + _CLITIC + r"(?![\w-])")
_ES_SUBJ = (r"(?<![\w-])que\s+(?:(?:me|te|se|lo|la|los|las|le|les)\s+){0,2}"
            r"(?:mandes|env[ií]es|respondas|contestes|reenv[ií]es|publiques|despliegues|lances)(?![\w-])")
_EN_ASK = (r"(?:^|(?<![\w-])(?:please|just|ok|okay|go ahead and|can you|could you|would you|you can"
           r"|now|then|yes|yeah|sure|dale|s[ií]|and|y)\s+)"
           r"(?:send|reply|respond|forward|publish|deploy|release|ship)"
           r"(?=\s+(?:it|that|this|them|him|her|the|those|these|now|off|out|again|to|in|a|an|my|our|your"
           r"|el|la|lo|ese|esa|eso)(?![\w-])|\s*$)")
_SEND_ASK = re.compile("|".join((_ES_IMP, _ES_INF, _ES_SUBJ, _EN_ASK)), re.IGNORECASE)
_CLAUSE = re.compile(r"[.;:!?\n,]+|\s+(?:pero|but|y|and|aunque|though)\s+", re.IGNORECASE)
_PRE_BLOCK = re.compile(
    r"(?<!\w)(?:sin|without|ni|evita\w*|abst[eé]nte|desaconsejo|dudo|falta|pendiente|salvo|excepto|except"
    r"|conviene|convendr[ií]a|vale la pena|tiene sentido|buena idea|good idea|wise|ok to|debes|deber[ií]as?|debe"
    r"|debo|should|shall|quieres|quiere|quieren|want me|do you want)(?!\w)", re.IGNORECASE)
_ANY_BLOCK = re.compile(
    r"(?<!\w)(?:no+|not|nunca|jam[aá]s|never|nel|nope|na|nah|nop|negativo|nothing|don'?t|do not"
    r"|todav[ií]a|a[uú]n|aun|despu[eé]s|luego|ma[ñn]ana|later|tomorrow|cuando|when|hasta|until"
    r"|s[oó]lo si|only if|espera\w*|esp[eé]rate|aguanta|wait|hold|cancel\w*|cancela\w*|olv[ií]dalo|forget"
    r"|ser[ií]a|would be|mu[eé]strame\w*|show me|broma|kidding|descartado|prohibido|jaja\w*|jeje\w*|lol"
    r"|🚫|❌|🙅)(?!\w)", re.IGNORECASE)
# A later clause withdraws the ask on any blocker of either list plus the
# sequencing words that are fine INSIDE the ask clause ("mándalo antes de las 5")
# but read as a deferral after a comma ("mándalo, antes revísalo tú").
_LATER_BLOCK = re.compile(_ANY_BLOCK.pattern + r"|" + _PRE_BLOCK.pattern
                          + r"|(?<!\w)(?:antes|before|primero|first|ojo)(?!\w)", re.IGNORECASE)


def explicit_send_ask(prompt: str) -> bool:
    """True when the operator's prompt for the turn asks to send and nothing in
    that clause or after it negates, defers or withdraws the ask."""
    text = _QUOTE_SPAN.sub(" ", prompt or "")
    asked = False
    for idx, clause in enumerate(c.strip() for c in _CLAUSE.split(text) if c.strip()):
        if asked:
            if _LATER_BLOCK.search(clause):
                return False
            continue
        if _ANY_BLOCK.search(clause):
            continue
        m = _SEND_ASK.search(clause)
        if m and not _PRE_BLOCK.search(clause[:m.start()]):
            # A bare infinitive opening any clause but the first ("pendiente:
            # mandarlo", "TODO: mandarlo", "1. mandarlo") is a noun, not an ask.
            labelled = idx > 0 and m.start() == 0 and m.group(0).lower().startswith(
                ("mandar", "enviar", "responder", "contestar", "reenviar", "publicar", "desplegar", "lanzar"))
            if not labelled:
                asked = True
    return asked


# v10 AC-05: the Send_Ask list. The verbs live in the tracked
# registry/send-ask.yaml, not here, so the list is reviewed as data. Matching
# folds case and accents (mándalo = MANDALO = mandalo) and reuses the clause
# machinery above, so a listed verb counts only when nothing in its clause or
# after it negates, defers or withdraws it. Spanish entries count anywhere in
# the clause (a plural clitic too: avísales); English entries count at clause
# start or after a frame word, like _EN_ASK. Only transmission verbs count: a
# bare go-ahead (dale, adelante, go ahead) never does, because "dale formato
# al mensaje" is an edit, not a send (QA of PR #382). The hatch token typed in
# another case (Send-ok) counts as a send ask only: it lifts requirement 4,
# never the checks the exact `send-ok` hatch skips.
# Fail-closed: an unreadable list adds nothing; explicit_send_ask still runs.
_SEND_ASK_FILE = _HERE.parent / "registry" / "send-ask.yaml"
_FOLD = str.maketrans("áéíóúüÁÉÍÓÚÜàèìòùÀÈÌÒÙ", "aeiouuAEIOUUaeiouAEIOU")


def _fold(text: str) -> str:
    return (text or "").translate(_FOLD).casefold()


def _load_send_ask(path: Path = _SEND_ASK_FILE) -> dict:
    """The lists of registry/send-ask.yaml ({key: [items]}), {} when unreadable.
    A two-level subset of YAML (`key:` then `  - item`), parsed here so the
    gate needs no third-party module on the hot path."""
    out, key = {}, None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    for raw in lines:
        line = raw.split(" #", 1)[0].rstrip() if not raw.lstrip().startswith("#") else ""
        if not line.strip():
            continue
        m = re.match(r"^([A-Za-z_][\w-]*):\s*$", line)
        if m:
            key = m.group(1)
            out[key] = []
            continue
        m = re.match(r"^\s+-\s+(.+)$", line)
        if m and key is not None:
            out[key].append(_fold(m.group(1).strip().strip("'\"")))
    return out


def _alt(items) -> str:
    return "|".join(re.escape(i) for i in sorted(items, key=len, reverse=True) if i)


_EN_OBJECT = (r"(?=\s+(?:it|that|this|them|him|her|the|those|these|now|off|out|again|to|in|a|an|my|our|your"
              r"|el|la|lo|ese|esa|eso)(?![\w-])|\s*$)")
_EN_FRAME = (r"(?:^|(?<![\w-])(?:please|just|ok|okay|go ahead and|can you|could you|would you|you can"
             r"|now|then|yes|yeah|sure|dale|si|and|y)\s+)")


def _listed_matcher(cfg: dict):
    """The ask regex of the Send_Ask list, or None when the list is empty."""
    es = list(cfg.get("spanish", []))
    en = list(cfg.get("english", []))
    hatch = list(cfg.get("hatch_as_ask", []))
    parts = []
    if es:
        parts.append(r"(?<![\w-])(?:" + _alt(es) + r")s?(?![\w-])")
    multi = [i for i in en if " " in i]
    single = [i for i in en if " " not in i]
    if multi:
        parts.append(_EN_FRAME + r"(?:" + _alt(multi) + r")(?![\w-])")
    if single:
        # A bare verb needs an object or the clause end after it, like _EN_ASK:
        # "send it to her" asks, "send failed again" does not.
        parts.append(_EN_FRAME + r"(?:" + _alt(single) + r")" + _EN_OBJECT)
    if hatch:
        parts.append(r"(?<![\w-])(?:" + _alt(hatch) + r")(?![\w-])")
    return re.compile("|".join(parts)) if parts else None


def listed_send_ask(prompt: str, cfg: dict | None = None) -> bool:
    """True when the prompt carries a Send_Ask from registry/send-ask.yaml
    that nothing in its clause or after it negates, defers or withdraws."""
    ask = _listed_matcher(_load_send_ask() if cfg is None else cfg)
    if ask is None:
        return False
    text = _fold(_QUOTE_SPAN.sub(" ", prompt or ""))
    asked = False
    for clause in (c.strip() for c in _CLAUSE.split(text) if c.strip()):
        if asked:
            if _LATER_BLOCK.search(clause):
                return False
            continue
        if _ANY_BLOCK.search(clause):
            continue
        m = ask.search(clause)
        if m and not _PRE_BLOCK.search(clause[:m.start()]):
            asked = True
    return asked


def send_ask(prompt: str) -> bool:
    """Requirement 4: the operator's prompt asks for this send (the original
    matcher, or the tracked Send_Ask list)."""
    return explicit_send_ask(prompt) or listed_send_ask(prompt)


# v10 AC-06: who opened the turn. Markers measured on the operator's
# transcripts (400 files, 2026-10-06), never guessed: a real prompt carries
# origin.kind "human"; a task notification origin.kind "task-notification";
# a subagent hand-back origin.kind "peer" with origin.handback true; a
# cross-session message origin.kind "peer" without it; a compact summary
# isCompactSummary. The opener is the OPERATOR only when origin.kind is
# "human", or when it has no origin and is neither a compact summary nor an
# isMeta entry (older prompts, interrupts, `!` commands), and it is a
# harness-written, non-sidechain entry. Only an operator opener carries
# hatches and its own send ask.
#
# A notification, peer or compact-summary opener carries no operator words,
# so the send ask is read from the operator's latest real prompt: the walk
# back skips only notifications, peer messages and isMeta entries and stops at
# anything else (a compact summary, an interrupt, a `!` command, a sidechain
# entry end it with no ask). Bounded twice: the prompt found is by
# construction the latest operator prompt, and the panel receipt for THIS
# send must be recorded after it (checked by the caller), so a reviewer that
# ran before the ask cannot carry it. Any other non-operator opener (an isMeta
# entry such as Stop-hook feedback) carries no ask at all.
#
# One read per call: the transcript is walked BACKWARDS in 1 MB chunks and the
# walk stops at the first entry that decides (the operator opener, or the
# human prompt behind a notification), so a long turn costs what its tail
# costs. A walk that reads _PROMPT_MAX bytes without deciding finds no ask.
_PROMPT_CHUNK = 1 << 20
_PROMPT_MAX = 64 << 20
_TURN_CACHE: dict = {}


def _origin(entry: dict) -> dict:
    o = entry.get("origin")
    return o if isinstance(o, dict) else {}


def _is_operator_opener(entry: dict) -> bool:
    import receipt_ledger
    if not receipt_ledger.harness_entry(entry) or entry.get("isSidechain"):
        return False
    o = entry.get("origin")
    if isinstance(o, dict):
        # isMeta is rejected here too: a harness meta entry never carries
        # operator words, whatever origin it was stamped with.
        return o.get("kind") == "human" and entry.get("isMeta") is not True
    return o is None and not entry.get("isCompactSummary") and entry.get("isMeta") is not True


def _walks_back(entry: dict) -> bool:
    """A notification, a peer message (hand-back or cross-session) or a
    compact summary opened the turn: read the ask from the operator's latest
    prompt, under the two bounds above."""
    return _origin(entry).get("kind") in ("task-notification", "peer") or bool(entry.get("isCompactSummary"))


def _reversed_lines(path: str):
    """The lines of a file, last first, read in chunks from the end."""
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        pos = fh.tell()
        rest = b""
        read = 0
        while pos > 0 and read < _PROMPT_MAX:
            step = min(_PROMPT_CHUNK, pos)
            pos -= step
            fh.seek(pos)
            buf = fh.read(step) + rest
            read += step
            lines = buf.split(b"\n")
            rest = lines[0]
            for ln in reversed(lines[1:]):
                yield ln
        if pos == 0 and rest:
            yield rest


def _prompt_entries_reversed(path: str):
    """User entries that are not tool results, last first."""
    for raw in _reversed_lines(path):
        if b'"user"' not in raw:
            continue
        try:
            e = json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            continue
        if not isinstance(e, dict) or e.get("type") != "user":
            continue
        c = (e.get("message") or {}).get("content")
        if isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
            continue
        yield e


def _entry_text(entry: dict) -> str:
    c = (entry.get("message") or {}).get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    return ""


def turn_read(transcript: str) -> dict:
    """{"hatch_text": the operator opener's words ("" when the opener is not
    the operator), "ask_text", "ask_ts", "walked"}. One backward read per
    transcript and call; fail-closed: any read error is no words at all."""
    if transcript in _TURN_CACHE:
        return _TURN_CACHE[transcript]
    out = {"hatch_text": "", "ask_text": "", "ask_ts": "", "walked": False}
    try:
        it = _prompt_entries_reversed(transcript) if transcript else iter(())
        opener = next(it, None)
        if opener is not None:
            if _is_operator_opener(opener):
                text = _entry_text(opener)
                out.update(hatch_text=text, ask_text=text, ask_ts=str(opener.get("timestamp") or ""))
            elif _walks_back(opener):
                out["walked"] = True
                for e in it:
                    o = _origin(e)
                    if o.get("kind") == "human":
                        if _is_operator_opener(e):
                            out.update(ask_text=_entry_text(e), ask_ts=str(e.get("timestamp") or ""))
                        break
                    if not e.get("isSidechain") and (
                            o.get("kind") in ("task-notification", "peer") or e.get("isMeta") is True):
                        continue
                    break
    except OSError:
        out = {"hatch_text": "", "ask_text": "", "ask_ts": "", "walked": False}
    _TURN_CACHE[transcript] = out
    return out


def ask_source(transcript: str) -> tuple:
    """(prompt text, prompt timestamp, walked_back) the send ask is read from."""
    t = turn_read(transcript)
    return t["ask_text"], t["ask_ts"], t["walked"]


def _ts(value):
    from datetime import datetime, timezone
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _panel_after(data: dict, prompt_ts: str) -> bool:
    """True when every message this call sends has a PASS panel receipt whose
    report was written after the operator prompt at `prompt_ts`. A send with
    no panel (a deploy, a release) never qualifies."""
    import receipt_ledger
    import panel_digest
    tool_name = str(data.get("tool_name", ""))
    tool_input = data.get("tool_input") or {}
    after = _ts(prompt_ts)
    if after is None or not _is_panel_send(tool_name, tool_input):
        return False
    try:
        digests = panel_digest.digests_for(tool_name, tool_input)
    except panel_digest.PanelDigestError:
        return False
    if not digests:
        return False
    session_id = data.get("session_id") or os.environ.get("CLAUDE_SESSION_ID") or ""
    now = _now_for(str(data.get("transcript_path") or ""))
    for d in digests:
        r = receipt_ledger.panel_pass_for(d, session_id, now)
        when = _ts((r or {}).get("verdict_ts"))
        if when is None or when <= after:
            return False
    return True


def _load(name: str):
    """Import a sibling gate by file name (hyphens are not identifiers)."""
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), _HERE / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _walk_strings(obj, out: list) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and str(k).lower() in _BODY_KEYS:
                out.append(v)
            else:
                _walk_strings(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk_strings(v, out)


# Autonomous chats: a private allowlist of chat JIDs (the operator's own
# family or household group, for instance) where the operator has standing
# instructions to answer and act without a per-message send ask. The list
# lives in the company brain (gitignored), never here, so the public gate
# carries no JID. Only requirement 4 (the explicit send ask) is waived for a
# listed recipient; the receipt, absence, attribute, promise and thread
# checks still run, because a household chat is still an outward send.
# Fail-closed: an unreadable or malformed file waives nothing.
_AUTONOMOUS_FILE = Path.home() / ".claude" / "company" / "config" / "outward-send-autonomous.json"
_WA_SEND = re.compile(r"whatsapp.*(send_message|send_file|send_audio_message)$", re.IGNORECASE)


def _autonomous_cfg() -> list:
    """The private allowlist's chat rows, [] when the file is absent or malformed."""
    try:
        cfg = json.loads(_AUTONOMOUS_FILE.read_text(encoding="utf-8"))
        return [c for c in (cfg.get("chats") or []) if isinstance(c, dict)]
    except Exception:
        return []


def _send_recipient(tool_name: str, tool_input) -> str:
    """The recipient of a WhatsApp send: the MCP field, or the first positional
    after the support-bridge script in a Bash command ("" when none)."""
    if not isinstance(tool_input, dict):
        return ""
    if _WA_SEND.search(str(tool_name)):
        return str(tool_input.get("recipient") or "").strip()
    if tool_name == "Bash":
        import receipt_ledger
        for sc in receipt_ledger.subcommands(str(tool_input.get("command", ""))):
            toks = receipt_ledger.tokens_of(sc)
            for i, t in enumerate(toks):
                if any(receipt_ledger._is_script_token(t, n) for n in _SEND_SCRIPTS):
                    # The script takes `--archivo <path>` anywhere and strips
                    # it; the recipient is the first positional that is left.
                    rest = toks[i + 1:]
                    j = 0
                    while j < len(rest):
                        if rest[j] == "--archivo":
                            j += 2
                            continue
                        if not rest[j].startswith("-"):
                            return rest[j].strip()
                        j += 1
                    return ""
    return ""


def _bash_recipients(command: str, split=None) -> list:
    """Every support-bridge recipient in *command* under one reading."""
    import receipt_ledger
    out = []
    for sc in receipt_ledger.subcommands(command, split):
        toks = receipt_ledger.tokens_of(sc)
        for i, t in enumerate(toks):
            if any(receipt_ledger._is_script_token(t, n) for n in _SEND_SCRIPTS):
                rest = toks[i + 1:]
                j = 0
                while j < len(rest):
                    if rest[j] == "--archivo":
                        j += 2
                        continue
                    if not rest[j].startswith("-"):
                        out.append(rest[j].strip())
                        break
                    j += 1
                else:
                    out.append("")
                break
        else:
            # The script named inside a token (a pager, an alias, an editor
            # command) has no recipient the gate can read: no waiver rests on it.
            if any(_names_script(t) for t in toks):
                out.append("")
    return out


def autonomous_chat(tool_name: str, tool_input) -> bool:
    """True when this send targets a chat the private allowlist names. For a
    Bash send, EVERY recipient under BOTH of the merge gate's readings must be
    listed: the waiver lifts a check, so it must not rest on the reading that
    happens to put an allowlisted chat first."""
    allowed = {str(c.get("jid", "")).strip() for c in _autonomous_cfg()} - {""}
    if not allowed or not isinstance(tool_input, dict):
        return False
    if tool_name != "Bash":
        recipient = _send_recipient(tool_name, tool_input)
        return bool(recipient) and recipient in allowed
    import receipt_ledger
    command = str(tool_input.get("command", ""))
    try:
        mod = receipt_ledger._qa_gate_module()
        readers = (mod._split_bash, mod._split_master)
    except Exception:
        readers = (None,)
    for reader in readers:
        recips = _bash_recipients(command, reader)
        if not recips or any(r not in allowed for r in recips):
            return False
    return True


# send-ok FROM the chat (operator directive 2026-09-24): in a listed chat that
# carries "send_ok_from_chat": true, the operator types the hatch in the group
# itself instead of in this prompt, and a MESSAGE send to a THIRD PARTY (mail,
# another chat, the support bridge) that follows within "window_minutes"
# (default 60, valid 1..240; a value outside that range disables the
# hatch for the chat) is treated as asked for. A deploy or a release is never
# released by a chat token: those are not messages. The row must be the
# operator's own phone (is_from_me = 1 in the personal bridge store, always
# ~/.config/whatsapp-mcp/store/messages.db: no per-chat path, so the config
# cannot point the check at a store the model made). Residual, stated
# plainly: that store is a file under $HOME the model can write (measured:
# an insert through python's sqlite3 module and a `cp` over the file both
# pass g__pretool__arming-surface.py), and so is the config file, so ONE
# config write plus ONE store row lifts the send ask for EVERY message send
# to ANY recipient for up to 240 minutes; that is wider than the allowlist
# above (per recipient, no clock) and narrower than the prompt hatch (the
# store row is a fact in the bridge database, it stays visible, and the
# write lands in the kernel journal). One token covers every send in its
# window, not one send: the operator scopes it by timing.
_DEFAULT_WA_STORE = Path.home() / ".config" / "whatsapp-mcp" / "store" / "messages.db"
_WINDOW_MAX_MINUTES = 240.0


def _row_age_minutes(ts: str, now) -> float:
    """Minutes from a bridge timestamp ("YYYY-MM-DD HH:MM:SS[.frac]+HH:MM") to now."""
    from datetime import datetime, timezone
    m = re.match(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})(?:\.(\d+))?\s*(Z|[+-]\d{2}:?\d{2})?$", str(ts).strip())
    if not m:
        return float("inf")
    frac = (m.group(3) or "")[:6].ljust(6, "0")
    tz = m.group(4) or "+00:00"
    if tz == "Z":
        tz = "+00:00"
    if ":" not in tz:
        tz = tz[:3] + ":" + tz[3:]
    dt = datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}.{frac}{tz}")
    return (now - dt.astimezone(timezone.utc)).total_seconds() / 60.0


def _now_for(transcript: str):
    """Wall clock, except under selftest, where the fixture's own turn timestamp
    is the clock so the window is proven in both directions on static rows."""
    import receipt_ledger
    from datetime import datetime, timezone
    if os.environ.get("CLAUDE_SESSION_ID") == receipt_ledger.SELFTEST_SESSION and transcript:
        _, human = receipt_ledger._turn_entries(transcript)
        ts = str((human or {}).get("timestamp") or "")
        if ts:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def chat_send_ok(transcript: str = "") -> bool:
    """True when the operator's own phone typed `send-ok` in a listed chat
    that carries send_ok_from_chat, inside that chat's window."""
    import sqlite3
    now = _now_for(transcript)
    db = _DEFAULT_WA_STORE
    if not db.is_file():
        return False
    for c in _autonomous_cfg():
        if c.get("send_ok_from_chat") is not True:
            continue
        jid = str(c.get("jid", "")).strip()
        if not jid:
            continue
        try:
            window = float(c.get("window_minutes", 60))
            if not (1.0 <= window <= _WINDOW_MAX_MINUTES):
                continue
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            # No ORDER BY on the timestamp column: it is text and the live
            # store mixes UTC offsets, so text order is not time order. Every
            # candidate row is aged in Python instead.
            rows = con.execute(
                "SELECT content, timestamp FROM messages WHERE chat_jid = ? AND is_from_me = 1 "
                "AND content LIKE '%send-ok%'", (jid,)).fetchall()
            con.close()
        except Exception:
            continue
        for content, ts in rows:
            if "send-ok" not in _HATCH.findall(str(content or "")):
                continue
            age = _row_age_minutes(ts, now)
            # A row from the future is a clock error, never an authorization.
            if 0 <= age <= window:
                return True
    return False


# -- v8 kernel journal (Phase 4, v8-kernel.md) --------------------------------
_KERNEL_RULE = "COMMS.outward-send-gate"


def _journal_deny(reason, payload=None, tool_use_id=None) -> None:
    """Mirror this refusal into the refusing process's journal.

    FAIL-OPEN by contract: every error is swallowed and the verdict this gate
    just reached is unchanged. A journal that cannot be written must never turn
    a deny into an allow. kernel_proc is loaded by PATH through importlib, not
    by name, so nothing on sys.path can shadow it.
    """
    try:
        import importlib.util
        import os as _os
        _path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "kernel_proc.py")
        _spec = importlib.util.spec_from_file_location("_kernel_proc_journal", _path)
        _kp = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_kp)
        _payload = payload if isinstance(payload, dict) else {}
        _kp.journal_deny(_KERNEL_RULE, reason,
                         tool_use_id if tool_use_id is not None else _payload.get("tool_use_id"),
                         _kp.resolve_pid(_payload))
    except Exception:
        pass


def _deny(reason: str, payload: dict = None) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }, ensure_ascii=False))
    _journal_deny(reason, payload)


# The one exemption: a Bash command that names the support script anywhere is a
# send unless the WHOLE command is one plain read (panel_digest.plain_read):
#   <reader> <plain words>                  (READER_NAMES: cat, head, tail,
#                                             grep, wc, stat, file, diff, ls,
#                                             chmod, chown)
#   sed -n <print-range> <script-path>      (print ranges only: GNU sed runs a
#                                             shell with `e`, writes with `w`)
#   <script-path> --help | -h                (the script has no help handler;
#                                             with fewer than two arguments it
#                                             prints its usage and exits 64)
# with no pipe, no ; && || &, no newline, no redirect, no <( or >(, no $(,
# backtick, braces, glob, ! or #, and no quoted string that holds $, backtick,
# a backslash or a newline. There is no list of executors: everything else
# that names the script is judged as a send.
def support_script_plain_read(command: str) -> bool:
    """True only for one plain read (panel_digest.plain_read); with
    panel_digest unloadable, nothing is a plain read (fail closed)."""
    try:
        return _panel_digest.plain_read(command)
    except Exception:
        return False


# Two shapes that RUN the support script while a reader or sed sits in
# front: a substitution (`cat <(wa-soporte.sh ...)`, and its `$(...)` and
# backtick twins) and a sed script that names it (`sed -n 'e wa-soporte.sh
# ...' /dev/null`, GNU sed's `e` runs a shell). Both are also outside the
# plain-read shape; this check stays as a substring floor under the word rule.
_PROC_SUBST = re.compile(r"(?:[<>$]\(|`)[^)`]*(?:" + "|".join(re.escape(n) for n in _SEND_SCRIPTS) + r")")


def _names_bridge(command: str) -> bool:
    """The support script named anywhere in a command that is not one plain
    read (panel_digest.names_bridge); with panel_digest unloadable, any
    substring counts (fail closed)."""
    try:
        return _panel_digest.names_bridge(command)
    except Exception:
        return any(n in str(command) for n in _SEND_SCRIPTS)


def _names_script(tok: str) -> bool:
    """The support script as a word anywhere in *tok*; with panel_digest
    unloadable, any substring counts (fail closed)."""
    try:
        return _panel_digest.names_script(tok)
    except Exception:
        return any(n in str(tok) for n in _SEND_SCRIPTS)


def _runs_script_behind_reader(command: str, toks_list: list) -> bool:
    if _PROC_SUBST.search(command):
        return True
    import receipt_ledger
    for toks in toks_list:
        if toks and os.path.basename(toks[0]) == "sed":
            for t in toks[1:]:
                if any(n in t for n in _SEND_SCRIPTS) and not any(
                        receipt_ledger._is_script_token(t, n) for n in _SEND_SCRIPTS):
                    return True
    return False


def _bash_is_send(command: str) -> bool:
    import receipt_ledger
    if support_script_plain_read(command):
        return False
    toks_list = [receipt_ledger.tokens_of(sc) for sc in receipt_ledger.subcommands(command)]
    if _names_bridge(command) or _runs_script_behind_reader(command, toks_list):
        return True
    for toks in toks_list:
        if toks and toks[0] in _READERS:
            continue
        for i, t in enumerate(toks):
            if _names_script(t):
                return True
            if t.endswith("wrangler") and "deploy" in receipt_ledger.words_after(toks, i, 2):
                return True
            if t == "gh" and receipt_ledger.words_after(toks, i, 2) == ["release", "create"]:
                return True
    return False


def _is_message_send(tool_name: str, tool_input: dict) -> bool:
    """A send of a MESSAGE (mail, chat, the support bridge): the only shape a
    chat-typed send-ok may release. Deploys and releases are sends for the
    gate but never messages, so they stay on the prompt hatch."""
    if tool_name == "Bash":
        return bool(_send_recipient(tool_name, tool_input))
    return bool(_SEND_TOOL.search(tool_name))


def is_send(tool_name: str, tool_input: dict) -> bool:
    if tool_name == "Bash":
        cmd = str((tool_input or {}).get("command", ""))
        return _bash_is_send(cmd) or raw_bridge_send(cmd)
    return bool(_SEND_TOOL.search(tool_name))


def _ask_deny(data: dict) -> str:
    """Requirement 4 as a deny reason, or "" when the operator asked for this
    send: in the prompt of this turn, or (AC-06) in the latest operator prompt
    when a notification or a hand-back opened the turn and this send's panel
    receipt was recorded after that prompt."""
    text, ts, walked = ask_source(str(data.get("transcript_path") or ""))
    asked = send_ask(text)
    if asked and (not walked or _panel_after(data, ts)):
        return ""
    if asked:
        return ("📬 ENVÍO SIN PEDIDO en este turno: lo abrió una notificación o un hand-back, y "
                "el último mensaje del operador sí pide mandar, pero el recibo de panel de este "
                "envío no es posterior a ese mensaje (o el envío no lleva panel). Pasa el mensaje "
                "por panel después del pedido, o 'send-ok' en SU mensaje.")
    return ("📬 ENVÍO SIN PEDIDO: el mensaje del operador en este turno no pide mandar "
            "nada (directiva 2026-08-14: entregar paste-ready y transmitir solo a pedido "
            "explícito, por mensaje). Entrega el texto en el chat y espera el 'mándalo'; "
            "'send-ok' en SU mensaje lo exime.")


# Raw bridge sends (operator directive 2026-10-02: never): a message that
# reaches a WhatsApp bridge without the bridge script or the MCP tool would
# leave with no panel at all. Denied outright, every pattern read on the raw
# text AND after quote removal (as bash reads it, so `/api/'send'` is
# `/api/send`):
#   - an outward endpoint of the bridges, /api/send or /api/react
#   - ANY request to a bridge port, `:8080` or `:8081` (leading zeros too)
#     on any host (127.1,
#     0x7f.1, [::1], a hostname, httpie's bare `:8081`), whatever the method,
#     unless its path is on the READ ALLOWLIST: the routes both bridges'
#     main.go expose that send nothing (/api/revoke, /api/download,
#     /api/group-participants). A path the gate cannot read ($p, a built
#     string, a `$` in a URL's host or port) denies. The text is
#     percent-decoded until stable, split string literals are joined, and
#     /api/ paths are normalized before every match, so /api/sen%64,
#     'sen'+'d' and /api/x/../send all read as /api/send. /api/revoke is on
#     the list on purpose: it is the recall path, and a revoke carries no
#     content to panel. This replaced a write-shape test
#     that fused flags (-d'..', -Fx=y), httpie's implied POST, urlopen's
#     positional data and a method built at run time all walked past.
#   - an `ssm send-command` that mentions a bridge (a bridge port, /api/send,
#     /api/react, the bridge script) in any payload, on any instance; and one
#     whose payload is not plaintext-inspectable (a decoder such as base64,
#     b64decode, xxd, openssl enc, gzip -d, gunzip, zcat; eval; a pipe into a
#     shell or an interpreter; $( or a backtick; sh -c; a file:// parameter
#     file; any interpreter run, `sh file` / `python -c` / `./file` / source)
#     when the target instance HOSTS A BRIDGE. On such a target the rule is an
#     ALLOWLIST since QA cycle 5: plain reads (sqlite3 without write SQL or
#     .shell/.system, journalctl, systemctl status|is-active|show, ls, cat,
#     tail, head, stat, df, du, ss, ps, grep, wc, echo with no redirection,
#     cd, find without -exec/-delete, cut, tr, md5sum, sha256sum, base64
#     without -d; not sort, uniq or date, which write with no redirection),
#     the deploy below, and
#     `systemctl daemon-reload`; anything else (awk system, exec, crontab, at,
#     nohup, setsid, timeout ...) denies. One exception, operator
#     decision 2026-10-03: a DEPLOY that only writes files under /opt, every
#     command being `echo|printf <base64> | base64 -d [| gunzip] > /opt/...`
#     (or `| [sudo] tee [-a] /opt/... [>/dev/null]`, `>>`), chmod, chown,
#     mkdir -p, mv or cp on paths strictly under a directory of /opt (no /opt
#     itself, no `.`/`..` or hidden components), or `systemctl daemon-reload` (it starts
#     nothing new; start, restart, enable --now and reload stay denied). Every
#     base64 blob in ANY ssm payload is decoded (gzip inside base64 too) and
#     its content run through the bridge-term, raw-send and HTTP checks
#     (url-safe alphabet too, quote- or newline-split fragments joined); on a
#     bridge host a candidate that looks encoded but does not decode denies.
#     Residuals: one decode layer only (a second layer is reachable only
#     through the timer residual below), and a symlink under /opt cannot be
#     resolved from here, so a write through one lands wherever it points. Residual, accepted by the
#     operator 2026-10-03: a file written under /opt can be run later by an
#     existing timer or unit; the decode inspection reduces that, it does
#     not remove it. Bridge-hosting instances
#     are read from the private bridge config (company/config/wa-puentes.json,
#     puentes.*.remoto.instancia). Fail closed: a missing or unreadable config,
#     targets given by --targets (tags, wildcards) or an instance id the gate
#     cannot read count as bridge-hosting. Residual: that config is a file
#     under $HOME a hooked process can write.
#   - inline interpreter code (python -c, node/perl/ruby -e, a heredoc or
#     stdin into an interpreter) that names a bridge port off the allowlist
#     (the rule above), or carries an HTTP or socket primitive, a
#     bridge-shaped target ('808' or 'api/' not preceded by a word character)
#     and a write shape, which catches a URL built by string concatenation
#     while a local socket lab or a file edit mentioning fetch( goes
#   - curl, wget or httpie whose URL argument is built at run time ($(, a
#     backtick, ${): a URL the shell computes cannot be judged
# A sub-command whose first token only READS (grep, cat, git, ss, lsof ...)
# is not a send. Accepted false positives are named in the spec.
_RAW_READERS = _READERS | {"ss", "lsof", "netstat", "ps", "pgrep", "systemctl", "journalctl"}
_RAW_ENDPOINT = re.compile(r"/api/(?:send|react)\b", re.IGNORECASE)
_RAW_PORT = re.compile(r":\s*0*808[01]\b")
_PORT_PATH = re.compile(r":\s*0*808[01]\b(\S*)")
# A client URL whose host or port the shell fills in (`localhost:$P`,
# `http://$H/...`) cannot be judged by the port rule.
_DYNAMIC_AUTHORITY = re.compile(r"(?:https?://|\s:)[^\s/'\"]*\$", re.IGNORECASE)
_API_PATH = re.compile(r"/api/[^\s'\"?#;|&)]*")
# Routes the two bridges expose that send nothing (verified in both main.go:
# the personal bridge has send, react, revoke, download; the support bridge
# adds group-add, a write, and group-participants, a read). /api/status is
# not a route of either, so it is not here.
_READ_ROUTES = {"/api/revoke", "/api/download", "/api/group-participants"}
_SSM_SEND = re.compile(r"\bssm\b.*\bsend-command\b", re.IGNORECASE | re.DOTALL)
_SSM_OPAQUE = re.compile(
    r"base64|b64decode|\bxxd\b|openssl\s+enc|gzip\s+-d|\bgunzip\b|\bzcat\b|\beval\b"
    r"|\|\s*(?:sudo\s+)?(?:sh|bash|zsh|dash|ksh|python\d*(?:\.\d+)?|perl|node|ruby|php)\b"
    r"|\$\(|`|\b(?:sh|bash|zsh|dash)\s+-[a-z]*c\b|file://|808[01]|api/send|api/react|wa-soporte"
    r"|(?:^|[\s;&|(\[\'\"])(?:sudo\s+)?(?:/\S*/)?(?:sh|bash|zsh|dash|ksh|python\d*(?:\.\d+)?"
    r"|perl|node|nodejs|ruby|php)\b(?!-)"
    r"|(?:^|[\s;&|(\[\'\"])(?:\./\S+|source\s+\S|\.\s+/\S)",
    re.IGNORECASE)
_INTERP_INLINE = re.compile(
    r"(?:^|[\s;&|(])(?:\S*/)?(?:python\d*(?:\.\d+)?|node|nodejs|perl|ruby|deno|bun|php)\b"
    r"(?:[^\n;&|]*?\s-[A-Za-z]*[ceEr]\b|[^\n;&|]*?<<|\s+-(?:\s|$))")
_HTTP_PRIMITIVE = re.compile(
    r"urllib|\brequests\b|http\.client|httplib|httpx|aiohttp|\bsocket\b|fetch\s*\(|net\.connect"
    r"|https?\.(?:get|request)|\bLWP\b|Net::HTTP|HTTP::Tiny|IO::Socket|open-uri|Faraday"
    r"|curl_exec|file_get_contents|fsockopen|createConnection|require\(\s*net\s*\)|\bnet\.connect",
    re.IGNORECASE)
_LOCAL_TARGET = re.compile(r"808|localhost|127\.|::1|api/", re.IGNORECASE)
_HTTP_CLIENTS = {"curl", "wget", "http", "https", "httpie", "xh"}
# curl/wget flags whose next token is a value, not the URL (`--url` is the URL).
_CLIENT_VALUE_FLAGS = {"-H", "--header", "-d", "--data", "--data-raw", "--data-binary",
                       "--data-urlencode", "-F", "--form", "-u", "--user", "-o", "--output",
                       "-A", "--user-agent", "-e", "--referer", "-b", "--cookie", "-c",
                       "--cookie-jar", "-T", "--upload-file", "-X", "--request", "-m",
                       "--max-time", "--connect-timeout", "-w", "--write-out", "-K", "--config",
                       "-O", "--output-document", "--header", "--post-data", "--post-file",
                       "-U", "--cacert", "--cert", "--key", "-x", "--proxy", "-r", "--range"}
_DYNAMIC = ("$(", "`", "${")


def _dequote(text: str) -> str:
    return re.sub(r"['\"\\]", "", text)


def _pct_decode(text: str) -> str:
    """Percent-decode until stable (bounded): /api/sen%2564 -> %64 -> d."""
    from urllib.parse import unquote
    for _ in range(8):
        nxt = unquote(text)
        if nxt == text:
            break
        text = nxt
    return text


def _join_concat(text: str) -> str:
    """'http://local'+'host' -> 'http://localhost': string concatenation in
    inline code joined back, so a split literal reads whole."""
    return re.sub(r"['\"]\s*\+\s*['\"]", "", text)


def _norm_api(text: str) -> str:
    """Every /api/... path normalized (/api/x/../send -> /api/send)."""
    import posixpath
    return _API_PATH.sub(lambda m: posixpath.normpath(m.group(0)), text)


def _readings(text: str) -> tuple:
    """The forms a command is matched in: raw, quote-removed, concatenation
    joined, each percent-decoded until stable, and each with its /api/ paths
    normalized."""
    base = (text, _dequote(text), _dequote(_join_concat(text)))
    out = []
    for t in base:
        for u in (t, _pct_decode(t)):
            out.extend((u, _norm_api(u)))
    return tuple(dict.fromkeys(out))


def _port_off_allowlist(text: str) -> bool:
    """True when the text names a bridge port whose path is not a read route
    (or cannot be read)."""
    import posixpath
    for t in _readings(text):
        for m in _PORT_PATH.finditer(t):
            path = re.split(r"[?#\s'\"),;|&]", m.group(1) or "", maxsplit=1)[0]
            if "$" in path or not path.startswith("/"):
                return True
            if posixpath.normpath(path) not in _READ_ROUTES:
                return True
        if _DYNAMIC_AUTHORITY.search(t):
            return True
    return False


_SSM_MENTION = re.compile(r"808[01]|api/send|api/react|wa-soporte", re.IGNORECASE)
_WRITE_SHAPE = re.compile(
    r"(?:^|\s)(?:-d|--data(?:-[a-z]+)?|-F|--form(?:-string)?|-T|--upload-file|--post-data|--post-file"
    r"|--json)(?=[\s=@]|$)"
    r"|(?:-X|--request|--method)[\s=]*(?:POST|PUT|PATCH|DELETE)\b"
    r"|\b(?:https?|xh)\s+(?:POST|PUT|PATCH|DELETE)\b"
    r"|\bdata\s*=|\bjson\s*=|method\s*[=:]\s*\W?(?:POST|PUT|PATCH|DELETE)\b"
    r"|\.(?:post|put|patch)\s*\(|\bsend(?:all)?\s*\(|\.write\s*\(|\.end\s*\(|\breact\b",
    re.IGNORECASE)
_LOCAL_HINT = re.compile(r"localhost|127\.|::1|0\.0\.0\.0|808", re.IGNORECASE)
_BRIDGE_TARGET = re.compile(r"808|(?<![\w])api/", re.IGNORECASE)
_INSTANCE_ID = re.compile(r"^i-[0-9a-f]{8,17}$")
_BRIDGE_CFG = Path.home() / ".claude" / "company" / "config" / "wa-puentes.json"


def _bridge_instances():
    """Instance ids that host a bridge, from the private bridge config, or
    None when the config is missing, unreadable or names none (then every
    instance counts as bridge-hosting)."""
    try:
        cfg = json.loads(_BRIDGE_CFG.read_text(encoding="utf-8"))
        ids = set()
        for entry in (cfg.get("puentes") or {}).values():
            inst = ((entry or {}).get("remoto") or {}).get("instancia")
            if isinstance(inst, str) and inst.strip():
                ids.add(inst.strip())
        return ids or None
    except Exception:
        return None


def _ssm_parts(text: str):
    """(payloads, instance_ids) of an ssm send-command as bash passes them, or
    None when the command cannot be read. instance_ids is None when the
    targets cannot be read: --targets (tags, wildcards), a variable the
    command does not assign, or anything that is not a literal instance id."""
    import shlex
    try:
        toks = shlex.split(text, posix=True)
    except ValueError:
        return None
    assigned = {}
    for t in toks:
        m = re.match(r"^([A-Za-z_]\w*)=(.*)$", t)
        if m:
            assigned[m.group(1)] = m.group(2).rstrip(";&|")
    payloads, raw_ids, unreadable = [], [], False
    i = 0
    while i < len(toks):
        t = toks[i]
        if t == "--parameters" and i + 1 < len(toks):
            payloads.append(toks[i + 1])
        elif t.startswith("--parameters="):
            payloads.append(t.split("=", 1)[1])
        elif t == "--targets" or t.startswith("--targets="):
            unreadable = True
        elif t == "--instance-ids":
            j = i + 1
            while j < len(toks) and not toks[j].startswith("-"):
                raw_ids.append(toks[j])
                j += 1
        elif t.startswith("--instance-ids="):
            raw_ids.append(t.split("=", 1)[1])
        i += 1
    ids = []
    for r in raw_ids:
        for part in re.split(r"[,\s]+", r):
            if not part:
                continue
            m = re.match(r"^\$\{?([A-Za-z_]\w*)\}?$", part)
            if m:
                part = assigned.get(m.group(1), "")
            if not _INSTANCE_ID.match(part):
                unreadable = True
            else:
                ids.append(part)
    if not ids:
        unreadable = True
    return payloads, (None if unreadable else ids)


_B64_BLOB = re.compile(r"[A-Za-z0-9+/_-]{16,}={0,2}")
# A candidate the gate must be able to decode: long, and mixed like encoded
# bytes are (upper, lower and a digit), so paths and words do not qualify.
_B64_CANDIDATE = re.compile(r"(?=[A-Za-z0-9+/_-]*[A-Z])(?=[A-Za-z0-9+/_-]*[a-z])"
                            r"(?=[A-Za-z0-9+/_-]*\d)[A-Za-z0-9+/_-]{24,}={0,2}")
# Fragments the shell glues together: 'AAA''BBB', "AAA"'BBB', 'AAA'+'BBB'.
_B64_GLUE = re.compile(r"(?<=[A-Za-z0-9+/_=-])(?:['\"]\s*\+?\s*['\"]|\\?\n)(?=[A-Za-z0-9+/_-])")
# A file path strictly under a directory of /opt: /opt/<dir>/<name>[...]
# (mkdir -p may name /opt/<dir> itself), every
# component starting with a letter, digit or underscore (no `.`, `..`,
# hidden names, empty components or /opt itself). A symlink under /opt
# cannot be resolved from here; that is a stated residual.
_OPT_COMP = r"[A-Za-z0-9_][A-Za-z0-9_.+-]*"
_OPT_DIR = r"/opt/" + _OPT_COMP + r"(?:/" + _OPT_COMP + r")*(?![\w./-])"
_OPT_PATH = r"/opt/" + _OPT_COMP + r"(?:/" + _OPT_COMP + r")+(?![\w./-])"
_DEPLOY_SEGMENTS = (
    re.compile(r"^(?:echo|printf)(?:\s+-n)?(?:\s+['\"]?%s['\"]?)?\s+['\"]?(?P<b64>[A-Za-z0-9+/]+={0,2})['\"]?"
               r"\s*\|\s*base64\s+(?:-d|--decode)(?:\s+-[iw]0?)?(?P<gz>\s*\|\s*(?:gunzip|gzip\s+-d)(?:\s+-c)?)?"
               r"\s*(?:>>?\s*" + _OPT_PATH + r"|\|\s*(?:sudo\s+)?tee\s+(?:-a\s+)?" + _OPT_PATH
               + r"(?:\s*>\s*/dev/null)?)$"),
    re.compile(r"^(?:sudo\s+)?(?:chmod|chown)\s+(?:-R\s+)?[\w.:+=,-]+(?:\s+" + _OPT_DIR + r")+$"),
    re.compile(r"^(?:sudo\s+)?mkdir\s+-p(?:\s+" + _OPT_DIR + r")+$"),
    re.compile(r"^(?:sudo\s+)?(?:mv|cp)(?:\s+-[fpa]+)?\s+" + _OPT_PATH + r"\s+" + _OPT_PATH + r"$"),
    re.compile(r"^(?:sudo\s+)?systemctl\s+daemon-reload$"),
)


def _ssm_commands(payload: str) -> list | None:
    """The command strings of an ssm --parameters value, or None when its
    shape is not one the gate reads: JSON {"commands": [...]} or the CLI
    shorthand commands=[...] with quoted items."""
    import ast
    import shlex
    p = payload.strip()
    try:
        if p.startswith("{"):
            cmds = json.loads(p).get("commands")
        elif p.startswith("commands="):
            rest = p[len("commands="):].strip()
            if rest.startswith("["):
                cmds = ast.literal_eval(rest)
            elif rest[:1] in "'\"":
                # Shorthand scalar in quotes: one command, as the CLI reads it.
                cmds = [ast.literal_eval(rest)]
            else:
                # Shorthand scalar: the CLI splits an unquoted value on commas.
                cmds = [c for c in rest.split(",") if c.strip()]
        else:
            return None
    except Exception:
        return None
    del shlex
    if isinstance(cmds, str):
        cmds = [cmds]
    if not isinstance(cmds, list) or not all(isinstance(c, str) for c in cmds):
        return None
    return cmds


def _decode_blob(blob: str, gz: bool):
    """Decoded text of a base64 blob, standard or url-safe alphabet
    (gunzipped when asked or when the bytes are gzip), or None when it does
    not decode. One layer only: a blob inside the decoded text is checked as
    text, never decoded again (a stated residual)."""
    import base64
    import binascii
    import gzip
    try:
        if "-" in blob or "_" in blob:
            blob = blob.replace("-", "+").replace("_", "/")
        raw = base64.b64decode(blob + "=" * (-len(blob) % 4), validate=True)
        if gz or raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return raw.decode("utf-8", errors="replace")
    except (binascii.Error, ValueError, OSError, EOFError):
        return None


def _content_hits(text: str) -> bool:
    """Decoded content that names a bridge, reaches a bridge send path, or
    carries an HTTP primitive with a bridge-shaped target and a write."""
    for t in _readings(text):
        if _SSM_MENTION.search(t) or _RAW_ENDPOINT.search(t):
            return True
    if _port_off_allowlist(text):
        return True
    flat = _pct_decode(_dequote(text))
    return bool(_HTTP_PRIMITIVE.search(flat) and _BRIDGE_TARGET.search(flat)
                and _WRITE_SHAPE.search(flat))


def _blob_texts(payload: str):
    """(blob, decoded or None) for every blob in a payload, quote- or
    newline-split fragments joined first, both alphabets."""
    for text in dict.fromkeys((payload, _B64_GLUE.sub("", payload))):
        for m in _B64_BLOB.finditer(text):
            yield m.group(0), _decode_blob(m.group(0), gz=False)


def _blobs_hit(payloads: list, strict: bool = False) -> bool:
    """Every base64-looking blob in any payload that decodes is inspected;
    one whose content hits a check denies on any instance. With `strict`
    (a bridge-hosting target) a candidate that looks encoded but does not
    decode denies too."""
    for p in payloads:
        for blob, text in _blob_texts(p):
            if text is not None and _content_hits(text):
                return True
            if strict and text is None and _B64_CANDIDATE.fullmatch(blob):
                return True
    return False


def _deploy_only(payloads: list) -> bool:
    """True when every payload is a deploy that only writes files under /opt
    (see the header), and every blob it writes decodes to clean content."""
    for p in payloads:
        cmds = _ssm_commands(p)
        if not cmds:
            return False
        for c in cmds:
            if any(m in c for m in ("$(", "`", "${")):
                return False
            for seg in re.split(r"\s*(?:&&|;|\n)\s*", c.strip()):
                if not seg:
                    continue
                m = None
                for rx in _DEPLOY_SEGMENTS:
                    m = rx.match(seg)
                    if m:
                        break
                if not m:
                    return False
                if "b64" in (m.groupdict() or {}) and m.group("b64"):
                    text = _decode_blob(m.group("b64"), gz=bool(m.group("gz")))
                    if text is None or _content_hits(text):
                        return False
    return True


# `sort`, `uniq` and `date` are not here: they write with no redirection
# (sort -o, uniq's second positional, date -s).
_SSM_READ_CMDS = {"sqlite3", "journalctl", "ls", "cat", "tail", "head", "stat", "df", "du", "ss",
                  "ps", "grep", "wc", "echo", "cd", "find", "cut", "tr",
                  "md5sum", "sha256sum", "base64"}
_FIND_ACTS = re.compile(r"(?:^|\s)-(?:exec|execdir|ok|okdir|delete|fprint\w*|fls)\b")
_SQLITE_WRITE = re.compile(
    r"\.(?:shell|system|output|once|import|save|backup|restore|load|excel)\b"
    r"|\b(?:insert|update|delete|drop|create|attach|alter|vacuum|reindex)\b"
    r"|\breplace\b(?!\s*\()", re.IGNORECASE)
_REDIRECT_OK = re.compile(r"\s+2>(?:&1|/dev/null)")


def _read_segment(seg: str) -> bool:
    """A plain read on the bridge host: every pipeline stage a read command
    (sqlite3 without write SQL or dot-commands that write or run, journalctl,
    systemctl status|is-active|show, ls, cat, tail, head, stat, df, du, ss,
    ps, grep, wc, echo, cd, find without -exec/-delete, cut, tr, md5sum,
    sha256sum, base64), no redirection other than 2>&1 or
    2>/dev/null. Quote-aware: a `|` or `>` inside a quoted SQL string is
    text, not an operator."""
    import shlex
    seg = _REDIRECT_OK.sub(" ", seg)
    try:
        lex = shlex.shlex(seg, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        toks = list(lex)
    except ValueError:
        return False
    stages, cur = [], []
    for t in toks:
        if t == "|":
            stages.append(cur)
            cur = []
        elif re.fullmatch(r"[();<>|&]+", t):
            return False
        else:
            cur.append(t)
    stages.append(cur)
    for st in stages:
        if st and st[0] == "sudo":
            st = st[1:]
        if not st:
            return False
        name = os.path.basename(st[0])
        if name == "systemctl":
            verbs = [t for t in st[1:] if not t.startswith("-")]
            if not verbs or verbs[0] not in ("status", "is-active", "show"):
                return False
            continue
        if name not in _SSM_READ_CMDS:
            return False
        text = " ".join(st)
        if name == "sqlite3" and _SQLITE_WRITE.search(text):
            return False
        if name == "find" and _FIND_ACTS.search(text):
            return False
        if name == "base64" and re.search(r"\s-(?:d|-decode)\b", text):
            return False
    return True


def _bridge_payload_ok(payloads: list) -> bool:
    """The ONLY payloads that may run on a bridge-hosting instance: plain
    reads, the operator-approved deploy under /opt (blobs decoded and
    inspected), and `systemctl daemon-reload`. Everything else denies."""
    if not payloads:
        return False
    for p in payloads:
        cmds = _ssm_commands(p)
        if not cmds:
            return False
        for c in cmds:
            if any(m in c for m in ("$(", "`", "${")):
                return False
            for seg in re.split(r"\s*(?:&&|\|\||;|\n)\s*", c.strip()):
                if not seg:
                    continue
                if _read_segment(seg):
                    continue
                if not _deploy_only([json.dumps({"commands": [seg]})]):
                    return False
    return True


def _ssm_hit(text: str) -> bool:
    """An ssm send-command that mentions a bridge (any instance), or whose
    payload is not plaintext-inspectable while the target hosts a bridge. The
    shell around the aws call (`CID=$(aws ssm ...)`) is not the payload."""
    if any(_SSM_MENTION.search(t) for t in _readings(text)):
        return True
    parts = _ssm_parts(text)
    if parts is None:
        return True
    payloads, ids = parts
    bridges = _bridge_instances()
    bridge_target = bridges is None or ids is None or any(i in bridges for i in ids)
    if payloads and _blobs_hit(payloads, strict=bridge_target):
        return True
    if not bridge_target:
        # Not a bridge host: only bridge terms (above) and decoded blobs deny.
        return False
    # Bridge-hosting (or unknown) target: an ALLOWLIST of payload shapes.
    return not _bridge_payload_ok(payloads)


def _raw_hit(text: str) -> bool:
    for t in _readings(text):
        if _RAW_ENDPOINT.search(t):
            return True
    if _port_off_allowlist(text):
        return True
    if _SSM_SEND.search(text) or _SSM_SEND.search(_dequote(text)):
        return _ssm_hit(text)
    return False


def _interp_hit(command: str) -> bool:
    if not _INTERP_INLINE.search(command):
        return False
    if _port_off_allowlist(command):
        return True
    for flat in _readings(command):
        if not _HTTP_PRIMITIVE.search(flat):
            continue
        if _BRIDGE_TARGET.search(flat) and _WRITE_SHAPE.search(flat):
            return True
        # A target computed inside the code ('...:'+str(8000+81)+'/api/...'):
        # an HTTP primitive, an api/ path and a local host hint deny even
        # with no write shape the gate can read.
        if "api/" in flat.lower() and _LOCAL_HINT.search(flat):
            return True
    return False


_HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?\n\s*\2\s*(?:\n|$)", re.DOTALL)
_PREFIX_WORDS = {"sudo", "env", "nice", "nohup", "command", "exec", "time", "timeout", "stdbuf",
                 "setsid", "ionice", "doas"}


def _dynamic_url_hit(command: str) -> bool:
    """curl / wget / httpie IN COMMAND POSITION with a URL argument the shell
    builds at run time. Heredoc bodies are dropped first (they are documents,
    not commands), and each line is read on its own, so the word `http` in a
    commit message or a document is not a client."""
    import shlex
    text = _HEREDOC.sub("\n", command)
    stops = {";", "&&", "||", "|", "&", "|&", ";;", "(", ")", "{", "}"}
    for line in text.splitlines():
        if not any(m in line for m in _DYNAMIC):
            continue
        try:
            lex = shlex.shlex(line, posix=True, punctuation_chars=True)
            lex.whitespace_split = True
            toks = list(lex)
        except ValueError:
            if re.search(r"(?:^|[;&|(]\s*)(?:curl|wget|https?|xh)\b", line):
                return True
            continue
        i, at_start = 0, True
        while i < len(toks):
            t = toks[i]
            if t in stops:
                at_start = True
                i += 1
                continue
            if at_start and (re.match(r"^[A-Za-z_]\w*=", t) or t in _PREFIX_WORDS
                             or (toks[i - 1] == "timeout" if i else False) and re.match(r"^[\d.]+[smh]?$", t)):
                i += 1
                continue
            if not at_start or os.path.basename(t) not in _HTTP_CLIENTS:
                at_start = False
                i += 1
                continue
            j = i + 1
            while j < len(toks) and toks[j] not in stops:
                a = toks[j]
                if a in _CLIENT_VALUE_FLAGS or a in (">", ">>", "<", "2>", "&>"):
                    j += 2
                    continue
                if a.startswith("-"):
                    j += 1
                    continue
                nxt = toks[j + 1] if j + 1 < len(toks) else ""
                if any(m in a for m in _DYNAMIC) or (a.endswith("$") and nxt.startswith("(")):
                    return True
                j += 1
            i, at_start = j, False
    return False


def raw_bridge_send(command: str) -> bool:
    """True when a Bash command reaches a bridge's send path directly, or
    carries a send the gate cannot judge (opaque SSM payload, inline
    interpreter HTTP to a local target, a run-time URL)."""
    import receipt_ledger
    command = str(command or "")
    if _interp_hit(command) or _dynamic_url_hit(command):
        return True
    if not _raw_hit(command):
        return False
    try:
        mod = receipt_ledger._qa_gate_module()
        readers = (None, mod._split_bash, mod._split_master)
    except Exception:
        readers = (None,)
    seen_in_sub = False
    for reader in readers:
        for sc in receipt_ledger.subcommands(command, reader):
            if not _raw_hit(sc):
                continue
            seen_in_sub = True
            toks = receipt_ledger.tokens_of(sc)
            if toks and os.path.basename(toks[0]) in _RAW_READERS:
                continue
            return True
    # The whole command matched while no single sub-command did. In a heredoc
    # (a script body split across lines) what runs it cannot be told, so it
    # sends; otherwise the parts came from different commands (a GET probe
    # next to an unrelated POST) and nothing writes to a bridge.
    return not seen_in_sub and "<<" in command


def _is_panel_send(tool_name: str, tool_input) -> bool:
    """A MESSAGE send, the shape requirement 5 covers: every MCP send tool,
    and a Bash command that invokes the support bridge under EITHER shell
    reading (the union finds more sends, and a send found is a send gated)."""
    if tool_name != "Bash":
        return bool(_SEND_TOOL.search(tool_name))
    import panel_digest
    command = str((tool_input or {}).get("command", "")) if isinstance(tool_input, dict) else ""
    return panel_digest.names_bridge(command)


def _panel_deny(data: dict) -> str:
    """Requirement 5 as a deny reason, or "" when every message this call
    sends carries a PASS panel receipt for its exact digest."""
    import receipt_ledger
    import panel_digest
    tool_name = str(data.get("tool_name", ""))
    tool_input = data.get("tool_input") or {}
    if not _is_panel_send(tool_name, tool_input):
        return ""
    try:
        digests = panel_digest.digests_for(tool_name, tool_input)
    except panel_digest.PanelDigestError as e:
        return (f"🧑‍⚖️ NO PANEL POSSIBLE: the gate cannot tell with certainty what this send "
                f"carries ({e}). Send the message as a plain call (MCP tool, or the support "
                f"bridge with a literal message and no $, backtick or heredoc), with every "
                f"attachment a readable local file, then get a panel for it.")
    session_id = data.get("session_id") or os.environ.get("CLAUDE_SESSION_ID") or ""
    now = _now_for(str(data.get("transcript_path") or ""))
    missing, spent = [], []
    for d in digests:
        r = receipt_ledger.panel_pass_for(d, session_id, now)
        if not r:
            missing.append(d)
        elif receipt_ledger.panel_receipt_consumed(str(r.get("entry_uuid") or "")):
            spent.append(d)
    if spent and not missing:
        return (f"🧑‍⚖️ PANEL RECEIPT ALREADY USED (sha256 {', '.join(spent)}): a panel receipt "
                f"authorises one send, and the sent-message ledger shows this one left already. "
                f"A second send of the same message needs a new panel.")
    if not missing:
        return ""
    listing = ", ".join(missing)
    return (f"🧑‍⚖️ NO PANEL RECEIPT for this message (sha256 {listing}). Operator directive "
            f"2026-10-02: no message leaves without a panel. Write this call's input to a JSON "
            f"file and run `python3 ~/.claude/scripts/panel_digest.py --tool-input <file.json> "
            f"--tool-name {tool_name} --panel-request`; it prints the panel block (PANEL-TO, "
            f"PANEL-ATTACH, PANEL-BODY-BEGIN..END, PANEL-SHA256). Hand that block to a reviewer "
            f"subagent (a reviewer persona: Reality Checker, Code Reviewer, ...) and have it end "
            f"its report with the same block plus 'PANEL-VERDICT: PASS' (or NEEDS-WORK). The "
            f"receipt records only when the digest recomputed from that block equals "
            f"PANEL-SHA256. It counts in this session for 120 minutes and for ONE send; a later "
            f"NEEDS-WORK revokes it; an edited body, recipient or attachment is a new digest. "
            f"No hatch: send-ok does not waive this.")


def check(data: dict) -> str:
    """Return the deny reason, or "" to allow. Raises only on internal errors.
    Requirements 1-4 first, each keeping its own deny; the panel (5) last."""
    if str(data.get("tool_name", "")) == "Bash" and raw_bridge_send(
            str((data.get("tool_input") or {}).get("command", ""))):
        return (f"🧑‍⚖️ RAW BRIDGE SEND: this command reaches a WhatsApp bridge's send path "
                f"(/api/send, /api/react, a bridge port on any host, an SSM send-command whose "
                f"payload is not plain text, inline interpreter HTTP to a local target, or a URL "
                f"built at run time) without the bridge script or the MCP tool, so no panel can "
                f"gate it. "
                f"Operator directive 2026-10-02: never. Send through {_SEND_SCRIPTS[0]} or the "
                f"WhatsApp MCP, with a panel receipt.")
    reason = _receipt_checks(data)
    if reason:
        return reason
    return _panel_deny(data)


def _receipt_checks(data: dict) -> str:
    """Requirements 1-4. Returns the deny reason, or ""."""
    import receipt_ledger
    tool_name = str(data.get("tool_name", ""))
    tool_input = data.get("tool_input") or {}
    session_id = data.get("session_id") or os.environ.get("CLAUDE_SESSION_ID") or ""
    transcript = data.get("transcript_path") or ""

    # 1. Gate receipt: the phrase detectors below are proven live on THIS tree.
    #    Keyed on the git tree hash of the gate surfaces (HEAD is recorded, not
    #    required: a squash-merge with the same gate tree keeps it valid) and
    #    voided by any uncommitted or index-hidden edit under them.
    brain = _HERE.parent
    selftest = os.environ.get("CLAUDE_SESSION_ID") == receipt_ledger.SELFTEST_SESSION
    if selftest:
        gates = receipt_ledger.SELFTEST_HEAD
        dirty = []
    else:
        gates = receipt_ledger.gate_tree_hash(brain)
        dirty = receipt_ledger.gate_surfaces_dirty(brain)
    if dirty:
        return ("🧾 GATES SIN COMMIT: hay cambios sin confirmar (o escondidos con assume-unchanged) "
                f"bajo scripts/, registry/ o hooks.json del brain ({len(dirty)} archivo(s)); un gate "
                "editado y no probado es un gate muerto. Confirma o descarta esos cambios, corre "
                "brain_doctor y reintenta el envío.")
    if not receipt_ledger.gate_receipt_ok(gates):
        return ("🧾 SIN RECIBO DE GATES: ningún brain_doctor ha probado los gates en este "
                "estado del brain. Corre `python3 ~/.claude/scripts/brain_doctor.py --gate-receipt` "
                "(ai-pull, tras su perfil --fast, y todo push lo hacen solos) y reintenta el envío. v7: nada sale sin recibos.")

    found: list = []
    if tool_name == "Bash":
        # The message travels as a quoted shell argument; unquote it, otherwise
        # the detectors read the quotes as the counterpart's own words.
        import shlex
        try:
            found = shlex.split(str(tool_input.get("command", "")))
        except ValueError:
            found = [str(tool_input.get("command", ""))]
    else:
        _walk_strings(tool_input, found)
    # Quoted-reply lines ("> ...") are the counterpart's words, exactly as the
    # Stop gates treat them; a hatch token counts only in the operator's own
    # prompt for this turn, never inside the body (that would ship to the
    # recipient and be self-serve).
    human = turn_read(transcript)["hatch_text"] if transcript else ""
    ok = hatches(human)
    if "send-ok" in ok:
        return ""
    # A listed autonomous chat waives requirement 4 only; everything below
    # still runs on the body.
    waive_ask = autonomous_chat(tool_name, tool_input) or (
        _is_message_send(tool_name, tool_input) and chat_send_ok(transcript))
    body = "\n".join(ln for ln in "\n".join(found).splitlines()
                     if not ln.lstrip().startswith(">"))
    if not body.strip():
        # Nothing to read for the phrase checks, but a file or an audio still
        # leaves: requirement 4 applies to it exactly as to a text body.
        return "" if waive_ask else _ask_deny(data)
    # A send is the model's own text: a quotation inside it is the model
    # quoting itself, and a claim split across lines is still one claim.
    flat = re.sub(r"\s+", " ", body)

    # 1b. A reply belongs in its thread: a mail SEND whose subject opens with
    #     Re:/Fwd: and carries no threadId/inReplyTo cuts the sequence for the
    #     counterpart (recurrent lesson, promoted from the reflex triage).
    if re.search(r"(send_email|__send_message)$", tool_name) and isinstance(tool_input, dict):
        subject = str(tool_input.get("subject") or "")
        if re.match(r"\s*(re|fwd?|rv)\s*:", subject, re.IGNORECASE) and not (
                tool_input.get("threadId") or tool_input.get("inReplyTo")
                or tool_input.get("thread_id") or tool_input.get("in_reply_to")):
            return ("📎 RESPUESTA FUERA DEL HILO: el asunto empieza con Re:/Fwd: y el envío no "
                    "lleva threadId ni inReplyTo. Un reply fuera de su hilo corta la secuencia "
                    "para la contraparte. Usa la herramienta reply o pasa threadId + inReplyTo.")

    # 2. Absence claim needs a seek receipt anchored in this turn.
    absence = _load("g__stop__unsourced-absence.py")
    claims = [] if "absence-ok" in ok else absence.find_absence_claims(flat, mask_quotes=False)
    if claims:
        seeks = receipt_ledger.seek_receipts_in_turn(session_id, transcript) if transcript else []
        if not seeks:
            listing = "; ".join(f"«{c}»" for c in claims[:4])
            return (f"🔎 AUSENCIA SIN BÚSQUEDA en el envío ({listing}): en este turno no hay "
                    f"ningún recibo de búsqueda (chat, correo o memoria) que pudiera refutarlo. "
                    f"Busca primero (list_messages con el monto, query_connectome.py memory, "
                    f"search_emails) o redáctalo como pregunta. 'absence-ok' en TU mensaje "
                    f"(no en el cuerpo) lo exime.")

    # 3. The other two contributors, before the send instead of after the reply.
    attribute = _load("g__stop__unsourced-attribute.py")
    attrs = [] if "attribute-ok" in ok else attribute.find_attributes(body)
    if attrs:
        listing = "; ".join(f"«{a}»" for a in attrs[:4])
        return (f"🏷 ATRIBUTO SIN FUENTE en el envío ({listing}): clasifica algo de la "
                f"contraparte dentro de un contexto de autorización con una categoría que "
                f"ella no dijo. Cita su frase textual, pregúntalo, o quítalo. "
                f"'attribute-ok' en la línea lo exime.")
    promise = _load("g__stop__draft-promise.py")
    promises = [] if "draft-promise-ok" in ok else promise.find_promises(body)
    if promises:
        listing = "; ".join(f"«{p}»" for p in promises[:4])
        return (f"✍ PROMESA en el envío ({listing}): lo que sale no lleva compromisos a "
                f"futuro en primera persona; ejecuta o refuta primero y manda el recibo. "
                f"'draft-promise-ok' en la línea lo exime.")

    # 4. Explicit send ask: operator directive 2026-08-14, deliver by default and
    #    transmit only the message that was asked for, per message. send-ok is the
    #    standing hatch (returned above). Last, so earlier denies keep their name.
    #    A listed autonomous chat is the other standing hatch, per recipient.
    return "" if waive_ask else _ask_deny(data)


def main() -> int:
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        return 0
    tool_name = str(data.get("tool_name", ""))
    tool_input = data.get("tool_input") or {}
    try:
        if not is_send(tool_name, tool_input):
            return 0
    except Exception:
        return 0
    # Positively a send from here: a crash in the checks denies, never allows.
    try:
        reason = check(data)
    except Exception as e:
        reason = (f"🧾 GATE DE SALIDA falló al verificar recibos ({type(e).__name__}); "
                  f"se niega el envío en vez de abrirse. Revisa ~/.claude/.cache/receipts.")
    if reason:
        _deny(reason, data)
    return 0


def _selftest() -> int:
    import gate_selftest
    argv = sys.argv
    fixture = argv[argv.index("--selftest") + 1] if len(argv) > argv.index("--selftest") + 1 \
        else "registry/fixtures/COMMS.outward-send-gate"
    return gate_selftest.run_gate_selftest(__file__, fixture)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
