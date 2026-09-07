#!/usr/bin/env python3
"""g__stop__goal-anchor.py: Stop gate: the goal stack does not erode.

The problem it solves: after chaining obstacles (a permission, a disabled
region, a missing binary), the agent closes the sub-goal with legitimate
evidence and reports victory. The ROOT goal of the session has gone unmentioned
for turns. Context rewrites `intent` at every obstacle, so the root is lost
without anyone noticing. No other mechanism in the brain persists it across
turns.

This gate persists it to disk and blocks ONCE when the agent declares closure
having lost sight of the root.

Per-turn cycle (all inside the same Stop; the payload carries transcript_path):
  1. Read the last operator message and the last assistant message from the
     transcript.
  2. Anchor. With no prior state: the operator prompt, cut to 240 chars.
     Re-anchors ONLY on a deterministic marker (prefix `objetivo:` / `goal:`, a
     pivot phrase, or an already-closed anchor plus a new prompt). Outside that
     the anchor is sticky for the whole session: "no me deja entrar" or "sale
     AccessDenied" are the operator reacting to the obstacle, NOT new goals.
  3. Mention. Pull content words out of the anchor and look for them in the
     response. Two distinct ones are enough: turns_since_mention returns to 0.
  4. Fires only on the full conjunction (see _should_fire).
  5. Governor: hard ceiling of 2 interruptions per anchor; on the second one the
     anchor closes itself and the gate stops talking about it.

Conservative by construction: any doubt passes. A false positive here interrupts
real work; a false negative only lets one turn through.

State: ~/.claude/.cache/goal-anchor/<session_id>.json

Deliberate escape: any line of the response carrying `goal-anchor-ok` exempts
the turn.

Stdin:  {"session_id": str, "transcript_path": str, "stop_hook_active": bool}
Stdout: {"decision": "block", "reason": "..."} on a hit, else nothing.
Exit:   always 0.
"""
from __future__ import annotations

import json
import os
import re
import signal as _signal_mod
import sys
import time
import unicodedata
from pathlib import Path

# Fuerza UTF-8 en stdout/stderr para que ⚓ y los acentos sobrevivan en shells
# de Windows que arrancan en cp1252. Sin esto el script hace bien su trabajo y
# aun asi truena con UnicodeEncodeError al imprimir.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
from claim_vocab import is_closure_claim  # noqa: E402  vocabulario compartido


BUDGET_S = 5  # auto-timeout duro; un Stop colgado congela la shell

MAX_ANCHOR_CHARS = 240
SILENCE_THRESHOLD = 4   # turnos sin mencionar la raiz antes de poder disparar
MAX_FIRES = 2           # techo duro de interrupciones por ancla
MIN_WORD_LEN = 4        # palabras mas cortas no distinguen nada
MIN_MENTION_HITS = 2    # dos palabras de contenido distintas = mencion

ESCAPE_TOKEN = "goal-anchor-ok"


# ── re-anclaje: solo marcadores deterministas ────────────────────────────────
# El prefijo explicito y las frases de pivote son declaraciones del operador de
# que el objetivo cambio. Todo lo demas (quejas, sintomas, correcciones) deja
# el ancla intacta.

_RE_GOAL_PREFIX = re.compile(r"^\s*(?:objetivo|goal)\s*:\s*", re.IGNORECASE)

# Las formas de RETORNO ("volvamos a", "regresemos a") se agregaron tras el
# primer disparo real en produccion, 2026-08-11: el operador escribio "volvamos
# al tema de mudanza" y el gate, que solo conocia formas de ABANDONO, siguio
# anclado al objetivo anterior y bloqueo 14 turnos despues. Un pivote es un
# pivote lo diga el operador yendose de un tema o volviendo a otro.
_RE_PIVOT = re.compile(
    r"\bolvida eso\b"
    r"|\bcambio de tema\b"
    # al? y no a\b: "volvamos AL tema" es la forma que de verdad se escribe, y
    # \b tras la "a" no casa porque la palabra sigue con letra. Salio de probar
    # la frase literal del operador en vez de una inventada.
    r"|\bahora vamos\s+al?\b"
    r"|\bvolvamos\s+al?\b"
    r"|\bregresemos\s+al?\b"
    r"|\bcambiemos\s+al?\b"
    r"|\bforget that\b"
    r"|\bnew task\b"
    r"|\blet'?s go back to\b"
    r"|\bswitching to\b",
    re.IGNORECASE,
)

# Ruido estructural del transcript que no es prosa del operador.
_RE_SYSTEM_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)
_RE_COMMAND_TAG = re.compile(r"<command-(?:name|message|args)>.*?</command-\w+>", re.DOTALL)

# Palabras vacias es/en. Solo se filtran palabras de >=4 chars, asi que la
# lista cubre ese rango; los articulos cortos caen solos por longitud.
_STOPWORDS = {
    # español
    "para", "pero", "porque", "como", "cuando", "donde", "mientras", "aunque",
    "esto", "esta", "este", "estos", "estas", "eso", "esos", "esas", "aquel",
    "todo", "toda", "todos", "todas", "otro", "otra", "otros", "otras",
    "cada", "alguno", "alguna", "algunos", "algunas", "nada", "nadie",
    "aqui", "alli", "alla", "ahora", "luego", "antes", "despues", "entonces",
    "tambien", "ademas", "sobre", "entre", "desde", "hasta", "hacia", "segun",
    "muy", "mas", "menos", "poco", "mucho", "bien", "solo", "mismo", "misma",
    "hacer", "haces", "hace", "hacen", "tiene", "tienen", "tener", "puede",
    "pueden", "poder", "debe", "deben", "estar", "estan", "siendo", "sido",
    "quiero", "quiere", "quieres", "favor", "gracias", "necesito", "necesita",
    "vamos", "vaya", "cosa", "cosas", "algo", "sea", "ser",
    # ingles
    "that", "this", "these", "those", "with", "from", "into", "then", "than",
    "when", "where", "which", "what", "have", "has", "had", "been", "will",
    "would", "should", "could", "they", "them", "their", "there", "here",
    "your", "yours", "about", "after", "before", "over", "under", "some",
    "any", "more", "most", "less", "just", "only", "also", "very", "much",
    "need", "needs", "want", "wants", "make", "makes", "does", "doing",
    "being", "else", "such", "each", "both", "same", "other", "please",
    "thanks", "thing", "things", "were", "was", "are", "the", "and",
}


# ── transcript ───────────────────────────────────────────────────────────────
# El patron de lectura viene de claim-verify-stop.py: solo la cola del archivo,
# porque un transcript de sesion larga pesa decenas de MB y la ultima entrada
# vive en los ultimos KB.

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


def _last_assistant_text(lines: list) -> str:
    """Texto de la ULTIMA entrada de asistente. Se detiene ahi tenga texto o no:
    caer a una entrada mas vieja evalua una respuesta rancia."""
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "assistant":
            continue
        return _blocks_text(entry)
    return ""


def _last_user_text(lines: list) -> str:
    """Ultimo prompt real del operador. Salta entradas de usuario que solo
    cargan tool_result o recordatorios del sistema: no son cosas que el
    operador escribio, y tomarlas como objetivo ancla ruido de la maquina."""
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


# ── normalizacion y mencion ──────────────────────────────────────────────────

def _normalize(text: str) -> str:
    """Minusculas sin acentos. 'Región' y 'region' son la misma palabra."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def content_words(anchor: str) -> set:
    """Palabras de contenido del ancla: >=4 chars y fuera de la lista vacia."""
    tokens = re.findall(r"[a-z0-9]+", _normalize(anchor))
    return {t for t in tokens if len(t) >= MIN_WORD_LEN and t not in _STOPWORDS}


def anchor_mentioned(anchor: str, reply: str) -> bool:
    """True si al menos MIN_MENTION_HITS palabras de contenido distintas del
    ancla aparecen en la respuesta."""
    words = content_words(anchor)
    if not words:
        return False
    haystack = _normalize(reply)
    hits = {w for w in words if re.search(r"\b" + re.escape(w) + r"\b", haystack)}
    return len(hits) >= MIN_MENTION_HITS


# ── estado ───────────────────────────────────────────────────────────────────

def _state_dir() -> Path:
    return Path(os.path.expanduser("~")) / ".claude" / ".cache" / "goal-anchor"


def _state_path(session_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", session_id)[:120] or "unknown"
    return _state_dir() / f"{safe}.json"


def load_state(session_id: str) -> dict:
    try:
        raw = _state_path(session_id).read_text(encoding="utf-8")
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(session_id: str, state: dict) -> None:
    """Best-effort. Si el disco falla el gate deja pasar, no revienta el turno."""
    try:
        path = _state_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def _retire(state: dict, reason: str) -> None:
    """Manda el ancla vigente al historial con su razon de cierre."""
    anchor = state.get("anchor")
    if not anchor:
        return
    history = state.setdefault("history", [])
    history.append({
        "anchor": anchor,
        "closed_ts": time.time(),
        "reason": reason,
    })
    del history[:-20]  # el historial es contexto, no bitacora


# ── que puede ser un objetivo ────────────────────────────────────────────────
# El anclaje inicial aceptaba cualquier prompt no vacio. El 2026-08-19 eso fijo
# como raiz un bloque de bash-stderr ("fatal: not a git repository") y, mas
# tarde, una pregunta de tramite ("que no servian los sticky notes?"), y el gate
# pidio cerrar objetivos que nunca existieron. Como solo un marcador
# determinista o un cierre retiran un ancla, la mala se queda y agota sus dos
# disparos.
#
# El filtro rechaza DOS clases y nada mas. De mas seria peor: un gate que no
# ancla nunca es un gate apagado, y el modo de fallo caro es no avisar.

# a) eco del harness: el turno no es prosa del operador sino salida de una
#    herramienta o un comando local que el transcript guarda como user.
_RE_HARNESS_ECHO = re.compile(
    r"<bash-(?:input|stdout|stderr)>"
    r"|<function_(?:calls|results)>"
    r"|<local-command-(?:stdout|stderr)>"
    r"|<task-notification>"
    r"|^\s*(?:fatal|error|traceback|usage):",
    re.IGNORECASE | re.MULTILINE,
)

# b) pregunta pura: interrogacion sin ningun verbo de encargo. "arregla el DNS"
#    ancla; "que no servian los stickies?" no. El imperativo gana sobre el signo
#    de interrogacion, porque "puedes arreglar X?" SI es un encargo.
_RE_TASK_VERB = re.compile(
    r"\b(?:arregla|arreglar|corrige|corregir|haz|hacer|implementa|implementar"
    r"|escribe|escribir|crea|crear|agrega|agregar|quita|quitar|borra|borrar"
    r"|actualiza|actualizar|publica|publicar|manda|mandar|envia|enviar"
    r"|revisa|revisar|verifica|verificar|corre|correr|ejecuta|ejecutar"
    r"|investiga|investigar|documenta|documentar|dame|damelo|necesito que"
    r"|fix|repair|implement|write|create|add|remove|delete|update|publish"
    r"|send|review|verify|run|execute|investigate|document|build|make|refactor"
    r"|migrate|deploy|generate)\b",
    re.IGNORECASE,
)


def is_anchorable(prompt: str) -> bool:
    """Si este prompt puede ser la raiz de la sesion.

    El prefijo explicito siempre gana: si el operador escribe "objetivo: X",
    X es la raiz aunque parezca cualquier otra cosa.
    """
    text = (prompt or "").strip()
    if not text:
        return False
    if _RE_GOAL_PREFIX.search(text):
        return True
    if _RE_HARNESS_ECHO.search(text):
        return False
    # Interrogativa sin verbo de encargo en ninguna parte del texto. El signo se
    # busca EN CUALQUIER POSICION, no solo al final: el caso real que fallo fue
    # "que no servian los sticky notes? tiene el svg up to date aqui", donde la
    # pregunta va a media frase y el prompt no termina en interrogacion.
    if ("?" in text or "¿" in text) and not _RE_TASK_VERB.search(text):
        return False
    # Sustancia minima. Sin esto el filtro solo mueve el problema: rechazado el
    # primer prompt, el ancla CAE al siguiente, y el siguiente suele ser un acuse
    # de dos letras ("ok", "va", "dale"). El umbral es el mismo MIN_MENTION_HITS
    # que ya usa anchor_mentioned, y no por simetria estetica: un ancla que el
    # propio gate nunca podria reconocer como mencionada no puede ser un ancla.
    if len(content_words(text)) < MIN_MENTION_HITS:
        return False
    return True


def is_reanchor(prompt: str, state: dict) -> bool:
    """Re-anclaje solo por marcador determinista. Sin estado no hay re-ancla:
    hay anclaje inicial, que es otra cosa."""
    if not state.get("anchor"):
        return False
    if not prompt.strip():
        return False
    if _RE_GOAL_PREFIX.search(prompt) or _RE_PIVOT.search(prompt):
        return True
    return bool(state.get("closed"))


def extract_anchor(prompt: str) -> str:
    """El objetivo, sin el marcador que lo introduce, cortado a 240 chars."""
    text = _RE_GOAL_PREFIX.sub("", prompt.strip(), count=1)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_ANCHOR_CHARS]


# ── decision ─────────────────────────────────────────────────────────────────

def _should_fire(state: dict, reply: str, reanchored: bool, stop_hook_active: bool) -> bool:
    """Conjuncion completa. Falta una condicion y el turno pasa."""
    if stop_hook_active:
        return False                                    # contrato one-shot
    if not state.get("anchor") or state.get("closed"):
        return False                                    # nada abierto que anclar
    if reanchored:
        return False                                    # el objetivo acaba de cambiar
    if state.get("fires", 0) >= MAX_FIRES:
        return False                                    # gobernador agotado
    if state.get("turns_since_mention", 0) < SILENCE_THRESHOLD:
        return False                                    # la raiz sigue viva en la prosa
    if not is_closure_claim(reply):
        return False                                    # no declaro cierre
    if anchor_mentioned(state["anchor"], reply):
        return False                                    # si la nombro
    if any(ESCAPE_TOKEN in ln for ln in reply.splitlines()):
        return False                                    # exencion deliberada
    return True


def build_reason(state: dict) -> str:
    return (
        f"⚓ ANCLA: declaraste cierre sin nombrar el objetivo raiz de la sesion, "
        f"abierto hace {state.get('turns_since_mention', 0)} turnos: "
        f"«{state.get('anchor', '')}». Cierra el turno con el estado de ese "
        f"objetivo y el siguiente paso hacia el. Si ya se cumplio, dilo y queda cerrado."
    )


def _turn_pairs(lines: list) -> list:
    """Pares (prompt, reply) en orden. Un turno abre con un prompt real del
    operador y cierra con la ULTIMA entrada de asistente antes del siguiente
    prompt real (misma regla que _last_assistant_text: la ultima aunque venga
    vacia). Entradas meta y tool_result no abren turno."""
    pairs = []
    prompt = None
    reply = None
    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (entry.get("type") == "user" and not entry.get("isMeta")
                and not entry.get("isCompactSummary")
                and not entry.get("isVisibleInTranscriptOnly")):
            # Las banderas van ANTES de mirar el texto: el resumen de
            # compactacion llega como type:user y CITA marcadores viejos del
            # operador, asi que filtrar solo por contenido ancla basura. Tres
            # disparos en falso en produccion (2026-08-12) por esto.
            text = _blocks_text(entry)
            text = _RE_SYSTEM_REMINDER.sub(" ", text)
            text = _RE_COMMAND_TAG.sub(" ", text)
            if text.strip():
                if prompt is not None:
                    pairs.append((prompt, reply or ""))
                prompt = text.strip()
                reply = None
        elif entry.get("type") == "assistant" and prompt is not None:
            reply = _blocks_text(entry)
    if prompt is not None:
        pairs.append((prompt, reply or ""))
    return pairs


def _absorb(state: dict, prompt: str, reply: str) -> bool:
    """Pasos 2 (anclaje) y 3 (mencion) de UN turno. No dispara ni persiste.
    Devuelve si este turno re-anclo."""
    state["turn"] = int(state.get("turn", 0)) + 1

    # 2. anclaje
    reanchored = False
    if not state.get("anchor"):
        # is_anchorable, no "if prompt": un eco del harness o una pregunta
        # suelta no son objetivos, y un ancla mala no se cae sola.
        if is_anchorable(prompt):
            state["anchor"] = extract_anchor(prompt)
            state["anchor_ts"] = time.time()
            state["anchor_turn"] = state["turn"]
            state["turns_since_mention"] = 0
            state["closed"] = False
            state["fires"] = 0
    elif is_reanchor(prompt, state):
        # Ya cerrada se retiro con su razon; viva se retira como pivote.
        if not state.get("closed"):
            _retire(state, "pivot")
        # Un pivote hacia algo que no es objetivo retira el ancla vieja sin
        # poner una mala en su lugar: mejor sin raiz que con una falsa.
        state["anchor"] = extract_anchor(prompt) if is_anchorable(prompt) else ""
        state["anchor_ts"] = time.time()
        state["anchor_turn"] = state["turn"]
        state["turns_since_mention"] = 0
        state["closed"] = False
        state["fires"] = 0
        reanchored = True

    anchor = state.get("anchor") or ""
    if not anchor:
        return reanchored

    # 3. mencion
    if anchor_mentioned(anchor, reply):
        state["turns_since_mention"] = 0
        if is_closure_claim(reply) and not state.get("closed"):
            state["closed"] = True
            _retire(state, "done")
    else:
        state["turns_since_mention"] = int(state.get("turns_since_mention", 0)) + 1
    return reanchored


def run_turn(data: dict) -> str:
    """Procesa un turno. Devuelve la razon a bloquear, o cadena vacia."""
    transcript = data.get("transcript_path") or ""
    if not transcript:
        return ""
    session_id = data.get("session_id") or os.environ.get("CLAUDE_SESSION_ID") or ""
    if not session_id:
        session_id = Path(transcript).stem

    try:
        lines = _tail_lines(transcript)
    except OSError:
        return ""

    pairs = _turn_pairs(lines)
    if not pairs:
        return ""

    state = load_state(session_id)
    state["session_id"] = session_id
    state["cwd"] = data.get("cwd") or state.get("cwd") or os.getcwd()
    state.setdefault("history", [])

    # Estado virgen con transcript viejo (archivo de estado perdido, o primera
    # corrida sobre una sesion ya andada, como el selftest): reconstruir
    # reproduciendo los turnos previos. Sin esto el gate evalua solo el ultimo
    # turno y el contador de silencio nace en cero, asi que jamas dispararia.
    if not state.get("anchor") and not state.get("history") and len(pairs) > 1:
        for past_prompt, past_reply in pairs[:-1]:
            _absorb(state, past_prompt, past_reply)

    prompt, reply = pairs[-1]
    reanchored = _absorb(state, prompt, reply)

    anchor = state.get("anchor") or ""
    if not anchor:
        save_state(session_id, state)
        return ""

    # 4. disparo + 6. gobernador
    reason = ""
    if _should_fire(state, reply, reanchored, bool(data.get("stop_hook_active"))):
        state["fires"] = int(state.get("fires", 0)) + 1
        reason = build_reason(state)
        if state["fires"] >= MAX_FIRES:
            # Segunda y ultima interrupcion: el ancla se cierra sola. Insistir
            # una tercera vez seria regaño, no señal.
            state["closed"] = True
            _retire(state, "exhausted")

    save_state(session_id, state)
    return reason


def main() -> int:
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        return 0

    if data.get("stop_hook_active"):
        # Ya bloqueamos este turno. Nunca ciclar.
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
        else "registry/fixtures/FLOW.root-goal-anchor"
    return gate_selftest.run_gate_selftest(__file__, fixture)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
