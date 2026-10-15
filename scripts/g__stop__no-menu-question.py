#!/usr/bin/env python3
"""g__stop__no-menu-question.py: Stop gate: a reply never ENDS on a menu for the operator.

Operator directive, 2026-10-15, verbatim: *"cada que termines en pregunta de
opción múltiple, quiero que apliques choice, siempre, hasta que me llegues ya
con una sugerencia, 0% de preguntas de opción múltiple"*. A reply that closes
with "¿Dale a X o Y?", "Do you want A or B?", "¿Procedo?" hands the choosing
back to the operator on work the agent could decide and do itself. The method
that replaces the menu already exists: `/choice` (commands/choice.md, "From an
Idea to a Decision") develops, debates, weighs, defends and DECIDES. The gate
makes skipping it cost a rewrite turn.

WHEN IT FIRES. In the last assistant reply, the LAST prose sentence (footer,
Disclose one-liners, fenced code, inline code and blockquotes discarded) is a
choice question: it ends in `?` and either offers alternatives ("X o Y",
"A or B") or opens with a go-ahead / preference ask ("¿Dale", "¿Quieres",
"¿Procedo", "Shall I", "Do you want", "Which do you prefer").

WHAT DOES NOT FIRE.
  - A question whose subject is an irreducible operator step, listed in
    `registry/no-menu-question.yaml` (send-ok, OCTO_MERGE_APPROVE, a password,
    a login, a payment, a version cut). Those are his by construction; the
    rule asks that they travel as a step with its command, and the gate lets
    the question through rather than guess at the wording.
  - A quoted question (someone else's words), a question inside a code block
    or a blockquote (a draft, a transcript), a line carrying `menu-ok`.
  - A reply whose last sentence is a decision, even when a question sits
    earlier in the text: the rule is about how the turn CLOSES.

Blocks ONCE (stop_hook_active), like its siblings defer-today and
draft-promise. The block message says what to do instead: run /choice and
return the decision, executed or in execution; leave only the irreducible
operator step, stated as a step with its command.

FAILS OPEN. Any error exits 0 and silently, the same contract as the other
draft gates of this class (defer-today, draft-promise, unsourced-*).

Deliberate escape: put `menu-ok` on the line.

Stdin:  {"transcript_path": str, "stop_hook_active": bool,
         "last_assistant_message": str (optional fallback), ...}
Stdout: {"decision": "block", "reason": "..."} on a hit, else nothing.
Exit:   always 0.
"""
from __future__ import annotations

import json
import os
import re
import sys
import unicodedata

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


_HERE = os.path.dirname(os.path.abspath(__file__))
_CONFIG_FILE = os.path.join(_HERE, "..", "registry", "no-menu-question.yaml")
HATCH = "menu-ok"

_FOOTER = re.compile(r"^\s*[>*_\s]*(Provenance|Procedencia|Herkunft)\s*:", re.IGNORECASE)
# Disclose one-liners that CLAUDE.md orders to the END of a reply: they are
# machine receipts, not the closing sentence of the prose.
_DISCLOSE = re.compile(r"^\s*(💡|☠)\s*\S*\s*(Unlock|Prune)[- ]?suggestion\s*:", re.IGNORECASE)
_FENCE = re.compile(r"```.*?```", re.DOTALL)
_INLINE = re.compile(r"`[^`\n]*`")
_QUOTED = re.compile(r'"[^"]*"|[“”][^“”]*[“”]|«[^»]*»', re.DOTALL)
_BLOCKQUOTE = re.compile(r"^\s*>")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")

# "X o Y" / "A or B" inside the question: the menu itself. `o` and `or` as
# whole words; "o bien" and "either ... or" fall in the same net.
_ALTERNATIVES = re.compile(r"\s(o|u|or)\s", re.IGNORECASE)

# Built-in defaults, overridden by the YAML when it is readable. Kept here so
# a missing config never turns the gate off (a gate that depends on a file
# that can be deleted is not wired) and so the selftest proves the real path.
_DEFAULT_OPENERS = [
    # Spanish go-ahead / preference asks
    "dale", "le doy", "procedo", "proceso", "sigo", "avanzo", "lo hago", "hago",
    "lo cableo", "lo mando", "lo aplico", "lo cierro", "lo subo", "lo dejo",
    "quieres", "quieren", "prefieres", "te parece", "te late", "te va",
    "cuál prefieres", "cual prefieres", "cuál quieres", "cual quieres",
    "cuál elijo", "cual elijo", "cuál tomo", "cual tomo",
    # English go-ahead / preference asks
    "shall i", "should i", "do you want", "would you like", "want me to",
    "do you prefer", "which do you prefer", "which one", "which would",
    "go ahead", "proceed", "ok to", "okay to",
]
_DEFAULT_IRREDUCIBLE = [
    "send-ok", "octo_merge_approve", "octo_qa_ok", "contraseña", "password",
    "login", "inicia sesión", "pago", "pagar", "payment", "pay ", "cobro",
    "consentimiento", "consent", "corte de versión", "version cut", "release tag",
    "clic de consentimiento", "2fa", "otp", "código de verificación",
]


def _fold(text: str) -> str:
    """Lower-case and strip accents so 'cuál' and 'cual' are one entry."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch)).lower()


def _load_config(path: str = _CONFIG_FILE) -> dict:
    """Two-level YAML subset (`key:` then `  - item`), no third-party parser.

    Same shape as registry/send-ask.yaml. An unreadable or empty file yields
    the built-in defaults; a readable file replaces a key only when it lists
    at least one item under it.
    """
    cfg = {"openers": list(_DEFAULT_OPENERS), "irreducible": list(_DEFAULT_IRREDUCIBLE)}
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return cfg
    parsed: dict = {}
    key = None
    for raw in lines:
        line = raw.split("#", 1)[0].rstrip() if not raw.lstrip().startswith("- ") else raw.rstrip()
        if not line.strip():
            continue
        if not line.startswith((" ", "\t")) and line.endswith(":"):
            key = line[:-1].strip()
            parsed.setdefault(key, [])
            continue
        if key and line.lstrip().startswith("- "):
            item = line.lstrip()[2:].strip().strip('"').strip("'")
            if item:
                parsed[key].append(item)
    for k, items in parsed.items():
        if items:
            cfg[k] = items
    return cfg


def _tail_lines(path: str, max_bytes: int = 262144) -> list:
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        fh.seek(max(0, size - max_bytes))
        return fh.read().decode("utf-8", errors="replace").splitlines()


def _last_assistant_text(transcript_path: str) -> str:
    """Text blocks of the LAST assistant entry; stops there whether or not it
    has text, so a stale earlier reply is never linted."""
    text_parts: list = []
    try:
        lines = _tail_lines(transcript_path)
    except OSError:
        return ""
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "assistant":
            continue
        content = (entry.get("message") or {}).get("content") or []
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
        elif isinstance(content, str):
            text_parts.append(content)
        break
    return "\n".join(text_parts)


def _strip_non_prose(text: str) -> str:
    text = _FENCE.sub("", text)
    text = re.sub(r"```.*", "", text, flags=re.DOTALL)   # unclosed trailing fence
    text = _INLINE.sub("", text)
    kept = []
    for ln in text.splitlines():
        if _FOOTER.match(ln) or _DISCLOSE.match(ln) or _BLOCKQUOTE.match(ln):
            continue
        if HATCH in ln:
            continue
        kept.append(ln)
    return "\n".join(kept)


def last_sentence(prose: str) -> str:
    """The closing sentence of the prose, quoted spans removed first."""
    prose = _QUOTED.sub(" ", prose)
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(prose) if s.strip()]
    return sentences[-1] if sentences else ""


def is_choice_question(sentence: str, cfg: dict) -> str:
    """Return the reason the sentence is a menu ('alternatives' or 'opener'),
    or '' when it is not a choice question or is an irreducible operator step."""
    s = sentence.strip()
    if not s.endswith("?"):
        return ""
    folded = _fold(s)
    for word in cfg.get("irreducible", ()):
        if _fold(word) in folded:
            return ""
    body = folded.lstrip("¿? \t").strip()
    for opener in cfg.get("openers", ()):
        op = _fold(opener)
        if body.startswith(op + " ") or body == op or body.startswith(op + "?"):
            return "opener"
        # "ya está X. ¿dale?"-style: the opener right after the inverted mark
        if ("¿" + op + " ") in ("¿" + body) and body.startswith(op):
            return "opener"
    if _ALTERNATIVES.search(" " + folded + " "):
        return "alternatives"
    return ""


def find_menu(raw: str, cfg: dict) -> tuple:
    """(sentence, reason) when the reply closes on a choice question, else ('', '')."""
    prose = _strip_non_prose(raw)
    if not prose.strip():
        return "", ""
    sentence = last_sentence(prose)
    reason = is_choice_question(sentence, cfg)
    return (sentence, reason) if reason else ("", "")


def main() -> int:
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        return 0

    if data.get("stop_hook_active"):
        return 0

    try:
        raw = ""
        transcript = data.get("transcript_path") or ""
        if transcript:
            raw = _last_assistant_text(transcript)
        if not raw.strip():
            raw = data.get("last_assistant_message") or ""
        if not raw.strip():
            return 0
        sentence, reason = find_menu(raw, _load_config())
    except Exception:
        return 0

    if not reason:
        return 0

    try:
        print(json.dumps({
            "decision": "block",
            "reason": (
                f"🔀 SIN-MENÚ: el turno cierra con una pregunta de opción múltiple al "
                f"operador (…{sentence[:90]}…). Directiva canónica 2026-10-15: 0% de "
                f"preguntas de opción múltiple. Corre /choice (desarrolla, debate, "
                f"pondera, defiende, decide) y regresa con la DECISIÓN ya ejecutada o "
                f"en ejecución, no con el menú. Solo queda sin decidir el paso "
                f"irreducible del operador (dinero, consentimiento, envío, merge, "
                f"corte de versión, login), y viaja como paso con su comando, no como "
                f"pregunta. Para dejar la pregunta a propósito, pon `{HATCH}` en la línea. "
                f"Ver CLAUDE.md 'No menu questions'."
            ),
        }))
        _journal_deny(f"turn closed on a choice question to the operator: {sentence[:90]}", data)
    except Exception:
        pass
    return 0


# -- v8 kernel journal (Phase 4, v8-kernel.md) --------------------------------
_KERNEL_RULE = "COMMS.no-menu-question"


def _journal_deny(reason, payload=None, tool_use_id=None) -> None:
    """Mirror this refusal into the refusing process's journal. FAIL-OPEN by
    contract: every error is swallowed and the verdict is unchanged."""
    try:
        import importlib.util
        _path = os.path.join(_HERE, "kernel_proc.py")
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
        else "registry/fixtures/COMMS.no-menu-question"
    return gate_selftest.run_gate_selftest(__file__, fixture)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
