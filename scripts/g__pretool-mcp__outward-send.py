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
     code spans; `send-ok` is the standing hatch. Checked last, so every
     earlier deny keeps its own name.

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
# A sub-command whose FIRST token is a reader never sends, whatever its argv
# names: `grep -rn wa-soporte.sh scripts/` reads the name, it does not run
# it (QA cycle 5 note). `find` is not here: `find -exec` runs things.
_READERS = {"grep", "rg", "ag", "ls", "cat", "less", "more", "head", "tail", "wc",
            "stat", "file", "diff", "vim", "nano", "code", "chmod", "chown", "git"}
_BODY_KEYS = ("body", "message", "text", "content", "html", "snippet",
              "caption", "subject", "description", "title", "command")
# A hatch counts only as a standalone word in the operator's prompt, outside
# quotes and code spans, and exempts only the class it names (send-ok: all).
_HATCH = re.compile(r"(?:^|(?<=[\s(\[]))(absence-ok|attribute-ok|draft-promise-ok|send-ok)(?=[\s,.;:!)\]]|$)", re.MULTILINE)
_QUOTE_SPAN = re.compile(r"\"[^\"\n]*\"|(?<!\w)'[^'\n]*'(?!\w)|`[^`\n]*`|«[^»]*»|[“”][^“”]*[“”]")


def hatches(prompt: str) -> set:
    return set(_HATCH.findall(_QUOTE_SPAN.sub(" ", prompt or "")))


# 4. A send ask is an imperative or infinitive send verb in the operator's prompt.
# ES: verb with an optional third-person clitic (mándalo, envíaselo); "me"/"nos"
# are excluded on purpose, "mándame el texto" is the paste-ready ask that must NOT
# transmit. EN: bare verb inside an imperative frame (clause start or after
# please/just/ok/go ahead and/can you...) and followed by an object or the end of
# the clause, so "reply came in" and "the release notes" do not count. Participles
# and nouns (enviado, publicación, el envío) never match. A negator anywhere
# earlier in the same clause negates the ask (no quiero que por ahora lo mande,
# ni se te ocurra enviarlo); a clause after the ask that is a bare retraction
# ("no", "espera", "wait", "todavía no") withdraws it.
_ES_ASK = (r"(?:m[aá]nda|m[aá]nde|mandar|env[ií]a|env[ií]e|enviar|resp[oó]nde|responda|responder"
           r"|cont[eé]sta|conteste|contestar|reenv[ií]a|reenv[ií]e|reenviar|publ[ií]ca|publique|publicar"
           r"|despliega|despliegue|desplegar|lanza|lance|lanzar)(?:lo|la|los|las|le|les|se|selo|sela|selos|selas)?")
_EN_FRAME = (r"(?:^|(?<![\w-])(?:please|just|ok|okay|go ahead and|can you|could you|would you|you can"
             r"|now|and|then|yes|yeah|sure|dale|s[ií]|don'?t|do not|not|never)\s+)")
_EN_ASK = (r"(?:send|reply|respond|forward|publish|deploy|release|ship)"
           r"(?=\s+(?:it|that|this|them|him|her|the|this|those|these|now|off|out|again|to|in|a|an|my|our|your|that|el|la|lo|ese|esa|eso)(?![\w-])|\s*$)")
_SEND_ASK = re.compile(r"(?<![\w-])(?P<es>" + _ES_ASK + r")(?![\w-])|" + _EN_FRAME + r"(?P<en>" + _EN_ASK + r")",
                       re.IGNORECASE)
_CLAUSE = re.compile(r"[.;:!?\n,]+")
_NEG_BEFORE = re.compile(r"(?<![\w-])(?:no|nunca|jam[aá]s|ni|sin|evita\w*|don'?t|do not|never|not|without|nothing)(?![\w-])",
                         re.IGNORECASE)
_RETRACT = re.compile(r"^\s*(?:(?:no|nope|nel)\s*$|(?:espera\w*|esp[eé]rate|aguanta|wait|hold on|todav[ií]a no|a[uú]n no"
                      r"|mejor no|not yet|cancel\w*|cancela\w*|olv[ií]dalo|forget it)(?![\w-]))", re.IGNORECASE)


def explicit_send_ask(prompt: str) -> bool:
    """True when the operator's prompt for the turn asks to send, non-negated and
    not retracted. Clause-scoped: split on . ; : ! ? newline and comma, so
    "no sé, mándalo" asks and "no lo mandes, déjalo listo" does not."""
    text = _QUOTE_SPAN.sub(" ", prompt or "")
    asked = False
    for clause in _CLAUSE.split(text):
        if asked and _RETRACT.match(clause):
            return False
        for m in _SEND_ASK.finditer(clause):
            # The EN frame token (don't, please...) is part of the match: negate on
            # what precedes the VERB, not the frame.
            verb_at = m.start("es") if m.start("es") != -1 else m.start("en")
            if _NEG_BEFORE.search(clause[:verb_at]):
                if asked:
                    return False  # "send it. actually don't send it"
                continue
            asked = True
            break
    return asked


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


def _deny(reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }, ensure_ascii=False))


def _bash_is_send(command: str) -> bool:
    import receipt_ledger
    for sc in receipt_ledger.subcommands(command):
        toks = receipt_ledger.tokens_of(sc)
        if toks and toks[0] in _READERS:
            continue
        for i, t in enumerate(toks):
            if any(receipt_ledger._is_script_token(t, n) for n in _SEND_SCRIPTS):
                return True
            if t.endswith("wrangler") and "deploy" in receipt_ledger.words_after(toks, i, 2):
                return True
            if t == "gh" and receipt_ledger.words_after(toks, i, 2) == ["release", "create"]:
                return True
    return False


def is_send(tool_name: str, tool_input: dict) -> bool:
    if tool_name == "Bash":
        return _bash_is_send(str((tool_input or {}).get("command", "")))
    return bool(_SEND_TOOL.search(tool_name))


def _ask_deny(human: str) -> str:
    """Requirement 4 as a deny reason, or "" when the operator asked for this send."""
    if explicit_send_ask(human):
        return ""
    return ("📬 ENVÍO SIN PEDIDO: el mensaje del operador en este turno no pide mandar "
            "nada (directiva 2026-08-14: entregar paste-ready y transmitir solo a pedido "
            "explícito, por mensaje). Entrega el texto en el chat y espera el 'mándalo'; "
            "'send-ok' en SU mensaje lo exime.")


def check(data: dict) -> str:
    """Return the deny reason, or "" to allow. Raises only on internal errors."""
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
                "(ai-pull y todo push lo hacen solos) y reintenta el envío. v7: nada sale sin recibos.")

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
    human = receipt_ledger.turn_last_human_text(transcript) if transcript else ""
    ok = hatches(human)
    if "send-ok" in ok:
        return ""
    body = "\n".join(ln for ln in "\n".join(found).splitlines()
                     if not ln.lstrip().startswith(">"))
    if not body.strip():
        # Nothing to read for the phrase checks, but a file or an audio still
        # leaves: requirement 4 applies to it exactly as to a text body.
        return _ask_deny(human)
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
    return _ask_deny(human)


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
        _deny(reason)
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
