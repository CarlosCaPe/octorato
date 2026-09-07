#!/usr/bin/env python3
"""g__stop__paste-ready-raw.py: Stop gate: a message meant for pasting ships RAW and LAST.

The problem it solves (daily operator complaint, 2026-08-05 and 2026-08-11:
"todos los dias te repito esto una y otra vez"): he asks for a message to paste
into Teams or WhatsApp and the response wraps it in a blockquote, adds bold and
headings, or hangs the provenance footer behind it. The operator has to clean it
by hand BEFORE pasting, inside a window with a client. Every day. The rule has
been written in memory for months and is still broken, so it stops being
discipline and becomes a ganglion: a hook that fires on its own.

The deliverable IS the message. Three ways to break it, all three detected here:

  1. BLOCKQUOTE: the message ships with `>` at the start of every line. The
     operator deletes the `>` one by one before pasting.
  2. MARKDOWN INSIDE: bold, headings, asterisk bullets, `[x](y)` links. They
     paste literally into the client chat.
  3. TEXT AFTER: any line behind the block contaminates the selection. The
     provenance footer goes BEFORE the block, never after.

Fires only on the CONJUNCTION of two conditions:
  A. the last operator prompt asked for a message to paste
     ("pasame el mensaje", "sin formato", "para pegar", "paste-ready", ...), and
  B. the response breaks one of the three points.

Without condition A there is no deliverable to protect, so it does not even look.

False positives avoided on purpose (a gate that shouts too much gets ignored,
and that is exactly the failure this brain chases):
  - Quoting the INCOMING message of a third party with `>` is legitimate. If the
    response already carries a fenced block, that block is the deliverable and
    every `>` outside it is context: no fire.
  - A quote lead-in ("el te escribio:", "su mensaje dice:") marks the
    blockquote as incoming: no fire.
  - A `>` inside a code block does not count (fences are stripped before
    looking).
  - An analysis response that talks about a message without delivering it has
    neither a block nor a long blockquote: no fire.
  - A fenced block WITH a language tag (```bash) is code, not the message:
    rules 2 and 3 leave it alone.
  - Dash bullets (`- item`) are NOT flagged: in plain text they read fine and
    flagging them would be shouting. Only `*` and `+`, which are pure markdown.

When in doubt, PASS. A false negative costs a turn; a false positive teaches
people to ignore the gate and kills all the others.

Deliberate escape: any line of the response carrying `paste-raw-ok` exempts the
turn, in the style of `draft-promise-ok` and `goal-anchor-ok`.

Loop safety: stop_hook_active=true means we already blocked this turn, pass.
Fail-open on every error: a broken linter never hijacks the conversation.

Stdin:  {"transcript_path": str, "stop_hook_active": bool, ...}
Stdout: {"decision": "block", "reason": "..."} on a hit, else nothing.
Exit:   always 0.
"""
from __future__ import annotations

import json
import os
import re
import signal as _signal_mod
import sys

# Fuerza UTF-8 en stdout/stderr para que los glifos y acentos sobrevivan en
# shells de Windows que arrancan en cp1252. Sin esto el script hace bien su
# trabajo y aun asi truena con UnicodeEncodeError al imprimir.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


BUDGET_S = 5          # auto-timeout duro; un Stop colgado congela la shell
ESCAPE_TOKEN = "paste-raw-ok"

MIN_MESSAGE_CHARS = 40   # un bloque mas corto no es un mensaje entregable
MIN_QUOTE_CHARS = 60     # un blockquote mas corto es una cita, no el entregable
MIN_TRAILING_CHARS = 15  # ruido de una o dos palabras no cuenta como contaminacion

# ── condicion A: el operador pidio un mensaje para pegar ─────────────────────
# Lista corta y literal a proposito. Cada variante suelta ("escribe un mensaje")
# ampliaria el disparo a cualquier redaccion y el gate empezaria a gritar.
_ASK_PASTE = re.compile(
    r"p[aá]same\s+(?:el|un)\s+(?:mensaje|texto)"
    r"|d[aá]me\s+(?:el|un)\s+(?:mensaje|texto)\s+(?:para\s+pegar|crudo|en\s+plano)"
    r"|mensaje\s+(?:listo\s+)?para\s+pegar"
    r"|listo\s+para\s+pegar"
    r"|para\s+(?:copiar|pegar)\b"
    r"|copiar\s+(?:y\s+)?pegar"
    r"|copy[\s-]?paste"
    r"|sin\s+formato"
    r"|texto\s+plano"
    r"|plain\s+text"
    r"|paste[\s-]?ready"
    r"|ready\s+to\s+paste"
    r"|raw\s+(?:message|text)",
    re.IGNORECASE,
)

# ── lead-in que marca un blockquote como cita ENTRANTE, no como entregable ───
# "el te escribio:", "su mensaje dice:", "he wrote:". Citar al tercero es
# legitimo y frecuente; marcarlo seria el falso positivo mas obvio.
_INCOMING_LEADIN = re.compile(
    r"\b(?:te\s+)?(?:escribi[oó]|mand[oó]|contest[oó]|respondi[oó]|dice|dijo|puso)\b"
    r"|\bmensaje\s+(?:entrante|de|que\s+(?:te|le))\b"
    r"|\brecibiste\b|\bllego\b|\blleg[oó]\b"
    r"|\b(?:he|she|they)\s+(?:wrote|said|replied|sent)\b"
    r"|\bincoming\b|\btheir\s+message\b|\bhis\s+message\b|\bher\s+message\b",
    re.IGNORECASE,
)

# ── markdown que no debe viajar dentro del bloque ────────────────────────────
_MD_PATTERNS = (
    ("negrita", re.compile(r"\*\*[^\s*][^*]*\*\*|__[^\s_][^_\n]*__")),
    ("encabezado", re.compile(r"(?m)^\s{0,3}#{1,6}\s+\S")),
    ("vineta markdown", re.compile(r"(?m)^\s*[*+]\s+\S")),
    ("enlace markdown", re.compile(r"\[[^\]\n]+\]\([^)\s]+\)")),
    ("blockquote", re.compile(r"(?m)^\s*>\s?\S")),
)

_RE_SYSTEM_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)
_RE_COMMAND_TAG = re.compile(r"<command-(?:name|message|args)>.*?</command-\w+>", re.DOTALL)
_RE_HRULE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")


# ── transcript ───────────────────────────────────────────────────────────────
# Mismo patron que sus hermanos: solo la cola del archivo, porque un transcript
# de sesion larga pesa decenas de MB y la ultima entrada vive en los ultimos KB.

def _tail_lines(path: str, max_bytes: int = 262144) -> list:
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        fh.seek(max(0, size - max_bytes))
        return fh.read().decode("utf-8", errors="replace").splitlines()


def _blocks_text(entry: dict) -> str:
    """Solo los bloques de texto de una entrada. Los tool_result no son prosa."""
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
    """Texto de la ULTIMA entrada de asistente. Se detiene ahi tenga texto o no:
    caer a una entrada mas vieja evalua una respuesta rancia y produce bloqueos
    espurios cuando el ultimo acto fue una llamada a herramienta."""
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "assistant":
            continue
        return _blocks_text(entry)
    return ""


def last_user_text(lines: list) -> str:
    """Ultimo prompt real del operador. Salta entradas de usuario que solo
    cargan tool_result, resumenes de compactacion o recordatorios del sistema:
    no son cosas que el operador escribio, y leerlas como peticion inventa la
    condicion A."""
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (entry.get("type") != "user" or entry.get("isMeta")
                or entry.get("isCompactSummary")
                or entry.get("isVisibleInTranscriptOnly")):
            continue
        text = _blocks_text(entry)
        text = _RE_SYSTEM_REMINDER.sub(" ", text)
        text = _RE_COMMAND_TAG.sub(" ", text)
        if text.strip():
            return text.strip()
    return ""


# ── estructura de la respuesta ───────────────────────────────────────────────

def parse_fences(lines: list) -> list:
    """Bloques cercados de la respuesta: {info, body, start, end}.

    `start` es el indice de la linea de apertura y `end` el de la de cierre (o
    la ultima linea si la cerca quedo abierta). Se necesita la estructura, no
    solo el texto, porque la regla 3 mide lo que viene DESPUES del cierre.
    """
    fences = []
    open_at = None
    info = ""
    body = []
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("```"):
            if open_at is None:
                open_at = i
                info = ln.lstrip()[3:].strip()
                body = []
            else:
                fences.append({"info": info, "body": "\n".join(body),
                               "start": open_at, "end": i})
                open_at = None
                info = ""
                body = []
        elif open_at is not None:
            body.append(ln)
    if open_at is not None:  # cerca sin cerrar: cuenta hasta el final
        fences.append({"info": info, "body": "\n".join(body),
                       "start": open_at, "end": len(lines) - 1})
    return fences


def message_fence(fences: list):
    """El bloque que ES el mensaje: el ULTIMO sin etiqueta de lenguaje y con
    cuerpo de mensaje. Una cerca ```bash o ```json es codigo, no el entregable,
    y tocarla seria gritar sobre una respuesta tecnica legitima."""
    for f in reversed(fences):
        body = f["body"].strip()
        if f["info"]:
            continue
        if len(body) < MIN_MESSAGE_CHARS or " " not in body:
            continue
        return f
    return None


def quote_blocks(lines: list, fences: list) -> list:
    """Bloques contiguos de `>` FUERA de toda cerca, con su lead-in.

    Devuelve [{text, lead_in, line}]. El `>` dentro de codigo no cuenta: se
    excluyen los rangos de cerca antes de mirar.
    """
    inside = set()
    for f in fences:
        inside.update(range(f["start"], f["end"] + 1))

    blocks = []
    current = None
    for i, ln in enumerate(lines):
        if i in inside:
            if current:
                blocks.append(current)
                current = None
            continue
        if re.match(r"^\s{0,3}>", ln):
            if current is None:
                lead = ""
                j = i - 1
                while j >= 0 and not lines[j].strip():
                    j -= 1
                if j >= 0 and j not in inside:
                    lead = lines[j]
                current = {"text": [], "lead_in": lead, "line": i + 1}
            current["text"].append(re.sub(r"^\s{0,3}>\s?", "", ln))
        elif current is not None and not ln.strip():
            continue  # una linea en blanco no parte la cita
        elif current is not None:
            blocks.append(current)
            current = None
    if current:
        blocks.append(current)
    for b in blocks:
        b["text"] = "\n".join(b["text"]).strip()
    return blocks


# ── las tres reglas ──────────────────────────────────────────────────────────

def check_blockquote(lines: list, fences: list) -> str:
    """Regla 1. Solo cuando NO hay bloque cercado que entregue el mensaje: si
    ya hay cerca, el entregable es la cerca y todo `>` de afuera es contexto."""
    if message_fence(fences):
        return ""
    for b in quote_blocks(lines, fences):
        if len(b["text"]) < MIN_QUOTE_CHARS:
            continue                                   # cita corta, no entregable
        if _INCOMING_LEADIN.search(b["lead_in"]):
            continue                                   # cita del tercero, legitima
        snippet = b["text"].replace("\n", " ")[:70]
        return (f"BLOCKQUOTE: el mensaje va con `>` desde la linea {b['line']} "
                f"(«{snippet}…»). El operador tiene que borrar cada `>` antes de "
                f"pegar. Entregalo en UN bloque cercado sin `>`.")
    return ""


def check_markdown(fence) -> str:
    """Regla 2. Markdown dentro del bloque: se pega literal en Teams o WhatsApp."""
    if not fence:
        return ""
    for label, rx in _MD_PATTERNS:
        m = rx.search(fence["body"])
        if m:
            frag = m.group(0).replace("\n", " ")[:50]
            return (f"MARKDOWN DENTRO: el bloque trae {label} («{frag}»). Eso se "
                    f"pega literal en el chat. Dentro del bloque va texto crudo, "
                    f"enlaces desnudos, sin sintaxis.")
    return ""


def check_trailing(lines: list, fence) -> str:
    """Regla 3. Texto despues del bloque: contamina la seleccion al copiar."""
    if not fence:
        return ""
    leftovers = []
    for i in range(fence["end"] + 1, len(lines)):
        ln = lines[i]
        if not ln.strip() or _RE_HRULE.match(ln) or ESCAPE_TOKEN in ln:
            continue
        leftovers.append((i + 1, ln.strip()))
    if not leftovers:
        return ""
    total = sum(len(t) for _, t in leftovers)
    if total < MIN_TRAILING_CHARS:
        return ""                                      # ruido, no contaminacion
    line_no, first = leftovers[0]
    return (f"TEXTO DESPUES: hay {len(leftovers)} linea(s) detras del bloque, "
            f"desde la linea {line_no} («{first[:70]}…»). Cualquier cosa detras "
            f"entra en la seleccion al copiar. El bloque va al FINAL y el footer "
            f"o la nota van ANTES.")


def find_violation(prompt: str, reply: str) -> str:
    """Motivo del bloqueo, o cadena vacia. Conjuncion completa: falta la
    peticion de pegar o falta la falla y el turno pasa."""
    if not prompt or not reply:
        return ""
    if not _ASK_PASTE.search(prompt):
        return ""                                      # no hay entregable que proteger
    if any(ESCAPE_TOKEN in ln for ln in reply.splitlines()):
        return ""                                      # exencion deliberada
    lines = reply.splitlines()
    fences = parse_fences(lines)
    fence = message_fence(fences)
    for check in (check_blockquote(lines, fences),
                  check_markdown(fence),
                  check_trailing(lines, fence)):
        if check:
            return check
    return ""


def build_reason(detail: str) -> str:
    return (
        f"📋 PASTE-READY: pediste un mensaje para pegar y el entregable sale sucio. "
        f"{detail} Regla: el mensaje va en UN bloque cercado, crudo, y ese bloque es "
        f"lo ULTIMO de la respuesta. Reescribe la respuesta asi y vuelve a entregarla. "
        f"Para dejar el formato tal cual, pon `{ESCAPE_TOKEN}` en una linea."
    )


def run_turn(data: dict) -> str:
    transcript = data.get("transcript_path") or ""
    if not transcript:
        return ""
    try:
        lines = _tail_lines(transcript)
    except OSError:
        return ""
    detail = find_violation(last_user_text(lines), last_assistant_text(lines))
    return build_reason(detail) if detail else ""


def main() -> int:
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        return 0

    if data.get("stop_hook_active"):
        # Contrato one-shot: Claude Code lo marca true en el Stop posterior a
        # nuestro bloqueo. Una reescritura forzada por turno, nunca un ciclo.
        return 0

    _signal = None
    try:
        def _bail(*_):
            raise TimeoutError()
        _signal_mod.signal(_signal_mod.SIGALRM, _bail)
        _signal_mod.alarm(BUDGET_S)
        _signal = _signal_mod
    except Exception:
        pass

    try:
        reason = run_turn(data)
        if reason:
            print(json.dumps({"decision": "block", "reason": reason}))
    except Exception:
        pass  # fail-open: un gate roto jamas secuestra la conversacion
    finally:
        if _signal is not None:
            try:
                _signal.alarm(0)
            except Exception:
                pass
    return 0


def _selftest() -> int:
    import gate_selftest
    argv = sys.argv
    fixture = argv[argv.index("--selftest") + 1] if len(argv) > argv.index("--selftest") + 1 \
        else "registry/fixtures/COMMS.paste-ready-raw-message"
    return gate_selftest.run_gate_selftest(__file__, fixture)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
