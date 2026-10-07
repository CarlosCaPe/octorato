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
     pivot phrase, an already-closed anchor plus a new prompt, or since v10 a
     TOPIC CHANGE: TWO consecutive goal-shaped operator prompts that share no
     content word with the root and are not obstacle reports; acks and bare
     questions in between are neutral, a prompt on the root or an obstacle
     report resets the streak, so one aside never retires the root). Only a
     REAL operator prompt (origin.kind human, or no origin and no harness-echo
     shape) can anchor, re-anchor or add silence: a pivot phrase quoted inside a
     <task-notification> or a peer message is not the operator.
     Residuals, stated: untagged pasted text is read as the operator's own words
     (two pasted blocks on another subject in a row re-anchor); obstacle reports
     are recognised by a fixed vocabulary, so one phrased without it counts as
     a new-topic prompt. "no me deja entrar" or "sale
     AccessDenied" are the operator reacting to the obstacle, NOT new goals, and
     keep the root. An acknowledgement or a hatch token of at most three words
     ("dale", "send-ok", "continue") never anchors and never re-anchors (v10
     AC-09), and neither does a go-ahead whose content words are only "carry on"
     vocabulary ("dale con tu recomendacion"). Pasted content and image markers
     are stripped before any of these decisions.
  3b. Silence counts only turns the operator opened: a turn opened by the
     machine (<task-notification>, a `!command` echo, local command output) does
     not add to turns_since_mention.
  3. Mention. Pull content words out of the anchor and look for them in the
     response. Two distinct ones are enough: turns_since_mention returns to 0.
  4. Fires only on the full conjunction (see _should_fire).
  5. Governor: hard ceiling of 2 interruptions per anchor; on the second one the
     anchor closes itself and the gate stops talking about it.

Conservative by construction: any doubt passes. A false positive here interrupts
real work; a false negative only lets one turn through.

State: ~/.claude/.cache/goal-anchor/<session_id>.json

Read receipt (v10 T19, instrumentation only): at every Stop the gate appends one
line to ~/.claude/.cache/goal-anchor/receipts/<session_id>.jsonl saying WHAT it
read and what it decided: the byte offset it read the transcript up to, how
many lines its tail held, the uuid of the last record it parsed, the sha256 of
the reply it judged (whole, and cut to 1,200 chars the way the friction ledger
digests a blocked reply), a 16-hex id of the root it held, the open-turn count,
the decision and a reason code. It never holds text. The replay harness cuts
each Stop at that uuid, because the recorded transcript is not what the live
gate read at its Stop (the hook can read before the turn's last records land).
The write runs after the decision is printed, swallows every error and loses
only the receipt; `OCTO_GOAL_ANCHOR_RECEIPTS=0` turns it off. The hashes are
unsalted, so a very short reply can be recovered by hashing guesses: the file
is local and gitignored like the state beside it.

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

# Contenido pegado y marcadores de imagen: son material que el operador trae,
# no la frase con la que pide algo. Un ancla hecha de 240 caracteres de una
# pagina de GitHub pegada nunca se menciona en una respuesta y agota sus dos
# disparos (census v10, 2026-10-06). Se quitan antes de decidir si el prompt es
# un objetivo; el turno sigue contando como turno.
_RE_PASTED = re.compile(r"<pasted_content\b[^>]*>.*?(?:</pasted_content[^>]*>|\Z)", re.DOTALL)
_RE_IMAGE_TAG = re.compile(r"\[Image #\d+\]")

# ── acuses y fichas de escape: nunca son objetivo (v10 AC-09) ───────────────
# "dale", "send-ok", "continue", "ok mándalo": el operador autoriza o empuja el
# trabajo que ya existe. Anclarlos como raiz fue la primera causa de falsos
# positivos del census v10 (100 bloqueos, ~92% FP): la raiz quedaba en "dale con
# tu recomendacion" y ninguna respuesta podia mencionarla. Un acuse conserva la
# raiz anterior; no ancla ni re-ancla.
MAX_ACK_WORDS = 3
_RE_HATCH_TOKEN = re.compile(r"^[a-z]+(?:-[a-z]+)*-ok$")
_ACK_WORDS = {
    # español (sin acentos: se compara contra _normalize)
    "ok", "oki", "okey", "va", "vale", "dale", "si", "sip", "claro", "listo", "lista",
    "hecho", "ya", "sigue", "sigamos", "seguimos", "continua", "continuemos",
    "adelante", "procede", "hazlo", "haz", "eso", "perfecto", "bien", "gracias",
    "orale", "aja", "simon", "exacto", "correcto", "mandalo", "mandala", "envialo",
    "tambien", "todo", "porfa", "y", "a", "con", "sin", "parar", "pares", "no",
    "de", "nuevo", "tu", "asi", "esta", "como", "lo", "la", "el", "pues", "entonces",
    # ingles
    "okay", "yes", "yep", "yeah", "sure", "go", "ahead", "on", "continue", "proceed",
    "done", "thanks", "please", "do", "it", "fine", "good", "right", "keep", "going",
}
# Palabras de contenido que solo dicen "sigue con lo que ya hay". Un prompt
# cuyas palabras de contenido, quitadas estas, no llegan a MIN_MENTION_HITS
# tampoco es objetivo: "dale con tu recomendacion" o "dale a lo pendiente" son
# un acuse largo, no una tarea nueva.
_GO_AHEAD_WORDS = {
    "dale", "sigue", "sigamos", "continua", "continue", "continuemos", "adelante",
    "procede", "proceed", "hazlo", "recomendacion", "recomendaciones",
    "sugerencia", "sugerencias", "pendiente", "pendientes", "parar", "pares",
    "mandalo", "mandala", "listo", "hecho", "done", "okay", "vale", "perfecto",
    "gracias", "thanks", "ahead", "going", "keep",
}


def _strip_pasted(text: str) -> str:
    return _RE_IMAGE_TAG.sub(" ", _RE_PASTED.sub(" ", text or ""))


def is_ack(prompt: str) -> bool:
    """True si el prompt es SOLO un acuse o una ficha de escape de a lo mas
    tres palabras: "dale", "ok, sigue", "send-ok mándalo", "continue"."""
    words = re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", _normalize(_strip_pasted(prompt)))
    if not words or len(words) > MAX_ACK_WORDS:
        return False
    return all(w in _ACK_WORDS or _RE_HATCH_TOKEN.match(w) for w in words)

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
        lines = fh.read().decode("utf-8", errors="replace").splitlines()
        _READ["bytes"] = fh.tell()     # T19 receipt: where this read stopped
    _READ["lines"] = lines
    return lines


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
    r"|\A\s*\[Request interrupted by user"
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
    text = _strip_pasted(text).strip()
    if not text or is_ack(text):
        return False
    # Acuse largo: quitadas las palabras de "sigue con lo que hay", no queda
    # sustancia para un objetivo.
    if len(content_words(text) - _GO_AHEAD_WORDS) < MIN_MENTION_HITS:
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
    if is_ack(prompt):
        return False                   # AC-09: un acuse conserva la raiz
    return bool(state.get("closed"))


# Cambio de tema: hacen falta TOPIC_CHANGE_PROMPTS prompts reales seguidos del
# operador sobre el tema nuevo (con al menos una palabra de contenido en comun
# entre ellos). El QA del v10 mostro que con uno solo, un encargo suelto ("abre
# la presentacion") o un texto pegado sin etiqueta retiraban la raiz real para
# siempre; master la conservaba.
TOPIC_CHANGE_PROMPTS = 2


def _topic_step(state: dict, prompt: str) -> bool:
    """Avanza la racha de cambio de tema con un prompt REAL del operador.
    Devuelve True cuando la racha llega al umbral (hay que re-anclar)."""
    if is_ack(prompt) or not is_anchorable(prompt):
        return False                                   # acuse o pregunta: ni suma ni rompe
    if not is_topic_change(prompt, state.get("anchor") or ""):
        state.pop("topic_pending", None)               # volvio a la raiz o es obstaculo
        return False
    pending = state.setdefault("topic_pending", {"count": 0})
    pending["count"] = int(pending.get("count", 0)) + 1
    pending["anchor"] = extract_anchor(prompt)          # el ultimo encargo es la raiz nueva
    return pending["count"] >= TOPIC_CHANGE_PROMPTS


def is_topic_change(prompt: str, anchor: str) -> bool:
    """Cambio de trabajo, deterministico: el operador escribe algo con sustancia
    de objetivo (is_anchorable: ni acuse, ni eco del harness, ni pregunta suelta)
    que no comparte una sola palabra de contenido con la raiz vigente, y que no
    es un reporte de obstaculo.

    Los reportes de obstaculo ("no me deja entrar", "sale AccessDenied otra
    vez", "sigue fallando") conservan la raiz: son la clase que este gate existe
    para atrapar, el operador reaccionando al tropiezo mientras la raiz se
    erosiona. Todo lo demas sin traslape es trabajo nuevo: el census v10 encontro
    raices de 30 a 80 turnos atras que el operador ya habia dejado por encargos
    explicitos sobre otra cosa, y el gate le pedia cerrar esas.
    """
    if not is_anchorable(prompt):
        return False
    if _RE_OBSTACLE.search(_normalize(_strip_pasted(prompt))):
        return False
    new_words = content_words(_strip_pasted(prompt)) - _GO_AHEAD_WORDS
    return not (new_words & content_words(anchor))


# Reporte de obstaculo: negacion de capacidad o resultado, o vocabulario de
# error. Se compara contra el texto normalizado (minusculas, sin acentos).
_RE_OBSTACLE = re.compile(
    r"\bno\s+(?:me\s+|nos\s+|te\s+|le\s+)?(?:deja|dejo|puedo|puede|pude|pudo|sirve|sirvio"
    r"|funciona|funciono|jala|abre|carga|entra|conecta|arranca|sale|aparece)\b"
    r"|\bsigue\s+(?:sin|fallando|igual)\b|\botra\s+vez\b|\bde\s+nuevo\s+(?:sale|falla)\b"
    r"|\b(?:error|errores|falla|fallo|fallando|denied|accessdenied|forbidden|timeout"
    r"|traceback|exception|unauthorized|rechaz\w*|bloquead\w*)\b"
    r"|\b(?:doesn'?t|does not|can'?t|cannot|won'?t|still)\s+(?:work|open|load|connect|fail\w*)\b"
    r"|\bfails?\b|\bfailing\b|\bbroken\b",
)


def extract_anchor(prompt: str) -> str:
    """El objetivo, sin el marcador que lo introduce, cortado a 240 chars."""
    text = _RE_GOAL_PREFIX.sub("", _strip_pasted(prompt).strip(), count=1)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_ANCHOR_CHARS]


# ── decision ─────────────────────────────────────────────────────────────────

def _fire_code(state: dict, reply: str, reanchored: bool, stop_hook_active: bool) -> str:
    """Conjuncion completa. Falta una condicion y el turno pasa. Devuelve "fire"
    o el codigo de la primera condicion que falto: el recibo (v10 T19) guarda
    ese codigo, asi que la misma evaluacion decide y se registra, sin repetirla."""
    if stop_hook_active:
        return "stop-hook-active"                       # contrato one-shot
    if not state.get("anchor") or state.get("closed"):
        return "closed"                                 # nada abierto que anclar
    if reanchored:
        return "reanchored"                             # el objetivo acaba de cambiar
    if state.get("fires", 0) >= MAX_FIRES:
        return "governor"                               # gobernador agotado
    if state.get("turns_since_mention", 0) < SILENCE_THRESHOLD:
        return "recent-mention"                         # la raiz sigue viva en la prosa
    if not is_closure_claim(reply):
        return "no-closure"                             # no declaro cierre
    if anchor_mentioned(state["anchor"], reply):
        return "mentioned"                              # si la nombro
    if any(ESCAPE_TOKEN in ln for ln in reply.splitlines()):
        return "escape-token"                           # exencion deliberada
    return "fire"


def _should_fire(state: dict, reply: str, reanchored: bool, stop_hook_active: bool) -> bool:
    return _fire_code(state, reply, reanchored, stop_hook_active) == "fire"


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
    real = False
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
                    pairs.append((prompt, reply or "", real))
                prompt = text.strip()
                reply = None
                real = is_operator_prompt(entry, prompt)
        elif entry.get("type") == "assistant" and prompt is not None:
            reply = _blocks_text(entry)
    if prompt is not None:
        pairs.append((prompt, reply or "", real))
    return pairs


def is_operator_prompt(entry: dict, text: str) -> bool:
    """Solo un prompt REAL del operador puede anclar, re-anclar o contar como
    silencio: origin.kind == "human", o sin origin y sin forma de eco del
    harness. Un <task-notification>, un mensaje de un par o el eco de un
    `!comando` no son el operador, aunque citen "forget that" o "switching to"
    (el QA del v10 re-anclo una raiz desde el resumen de un monitor)."""
    origin = entry.get("origin")
    if isinstance(origin, dict) and origin.get("kind"):
        return origin.get("kind") == "human" and not _RE_HARNESS_ECHO.search(text)
    return not _RE_HARNESS_ECHO.search(text)


def _set_anchor(state: dict, anchor: str) -> None:
    state["anchor"] = anchor
    state["anchor_ts"] = time.time()
    state["anchor_turn"] = state["turn"]
    state["turns_since_mention"] = 0
    state["closed"] = False
    state["fires"] = 0
    state.pop("topic_pending", None)


def _absorb(state: dict, prompt: str, reply: str, real: bool = True) -> bool:
    """Pasos 2 (anclaje) y 3 (mencion) de UN turno. No dispara ni persiste.
    Devuelve si este turno re-anclo. Solo un prompt real del operador (`real`)
    puede anclar, re-anclar o sumar silencio."""
    state["turn"] = int(state.get("turn", 0)) + 1

    # 2. anclaje
    reanchored = False
    if not real:
        pass
    elif not state.get("anchor"):
        # is_anchorable, no "if prompt": un eco del harness o una pregunta
        # suelta no son objetivos, y un ancla mala no se cae sola.
        if is_anchorable(prompt):
            _set_anchor(state, extract_anchor(prompt))
    elif is_reanchor(prompt, state):
        # Ya cerrada se retiro con su razon; viva se retira como pivote.
        if not state.get("closed"):
            _retire(state, "pivot")
        # Un pivote hacia algo que no es objetivo retira el ancla vieja sin
        # poner una mala en su lugar: mejor sin raiz que con una falsa.
        _set_anchor(state, extract_anchor(prompt) if is_anchorable(prompt) else "")
        reanchored = True
    elif _topic_step(state, prompt):
        first = state["topic_pending"]["anchor"]
        _retire(state, "superseded")
        _set_anchor(state, first)
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
        # Solo cuentan los turnos que abrio el operador. Un turno abierto por la
        # maquina (aviso de tarea en segundo plano, eco de `!comando`, salida de
        # un comando local) no es silencio sobre la raiz: nadie pregunto nada.
        # En el census v10 la mitad del silencio acumulado venia de rafagas de
        # <task-notification> de vigias y QA corriendo.
        if real:
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
        _READ["code"] = "no-turns"
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
        for past_prompt, past_reply, past_real in pairs[:-1]:
            _absorb(state, past_prompt, past_reply, past_real)

    prompt, reply, real = pairs[-1]
    reanchored = _absorb(state, prompt, reply, real)
    _READ["reply"] = reply

    anchor = state.get("anchor") or ""
    if not anchor:
        _READ["code"] = "no-anchor"
        save_state(session_id, state)
        return ""

    _note_judged(state)
    # 4. disparo + 6. gobernador
    reason = ""
    code = _fire_code(state, reply, reanchored, bool(data.get("stop_hook_active")))
    _READ["code"] = code
    if code == "fire":
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

    _signal = None
    try:
        def _bail(*_):
            raise TimeoutError()
        _signal_mod.signal(_signal_mod.SIGALRM, _bail)
        _signal_mod.alarm(BUDGET_S)
        _signal = _signal_mod
        _READ["deadline"] = time.monotonic() + BUDGET_S
    except Exception:
        pass

    reason = ""
    try:
        if data.get("stop_hook_active"):
            # Ya bloqueamos este turno. Nunca ciclar. (La alarma ya esta armada:
            # el recibo de este Stop tambien queda dentro del presupuesto.)
            _READ["code"] = "stop-hook-active"
        else:
            reason = run_turn(data)
            if reason:
                print(json.dumps({"decision": "block", "reason": reason}))
                sys.stdout.flush()
                _journal_deny(reason, data)
    except Exception:
        pass  # fail-open: un gate roto jamas secuestra la conversacion
    finally:
        # Despues de imprimir y bajo la misma alarma: el recibo nunca cambia la
        # decision, y si falla o se agota solo se pierde el recibo.
        try:
            _write_receipt(data, reason)
        finally:
            if _signal is not None:
                try:
                    _signal.alarm(0)
                except Exception:
                    pass
    return 0


# -- read receipt (v10 T19) ---------------------------------------------------
# Instrumentation only. Nothing here feeds the decision: _READ is filled while
# run_turn reads, and the receipt is written after the verdict is printed.

_READ: dict = {}
RECEIPT_ENV = "OCTO_GOAL_ANCHOR_RECEIPTS"
RECEIPT_REPLY_CUT = 1200   # friction_ledger.INPUT_CUT: the ledger digests a blocked reply this way


def _sha256(data: bytes) -> str:
    """sha256 hex without importing hashlib: its OpenSSL backend costs ~4 ms of
    import on every Stop, measured, while the builtin module costs ~0.1 ms."""
    for name in ("_sha2", "_sha256"):          # 3.12+, then 3.11
        try:
            return __import__(name).sha256(data).hexdigest()
        except (ImportError, AttributeError):
            continue
    import hashlib
    return hashlib.sha256(data).hexdigest()


def _note_judged(state: dict) -> None:
    """Snapshot, before the fire step mutates the state, what the gate judged.
    Reads only; the reason code comes from _fire_code's own evaluation. The
    budget alarm is never swallowed here: it must reach main's fail-open."""
    try:
        _READ["anchor_id"] = _sha256((state.get("anchor") or "").encode("utf-8"))[:16]
        _READ["open_turns"] = int(state.get("turns_since_mention", 0))
        _READ["turn"] = int(state.get("turn", 0))
        _READ["fires_before"] = int(state.get("fires", 0))
    except TimeoutError:
        raise
    except Exception:
        pass


def _receipt_path(session_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", session_id)[:120] or "unknown"
    return _state_dir() / "receipts" / f"{safe}.jsonl"


def _last_uuid(lines: list) -> str:
    """uuid of the last whole record the tail held (a line still being written
    does not parse and is skipped, as the decision path skips it)."""
    for line in reversed(lines or []):
        if '"uuid"' not in line:
            continue                   # no uuid to find: skip the parse
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and entry.get("uuid"):
            return str(entry["uuid"])
    return ""


def build_receipt(data: dict, reason: str) -> dict:
    """The receipt line: ids, sizes, digests and codes. Never text."""
    transcript = data.get("transcript_path") or ""
    session_id = data.get("session_id") or os.environ.get("CLAUDE_SESSION_ID") or ""
    if not session_id and transcript:
        session_id = Path(transcript).stem
    reply = _READ.get("reply")
    whole = None if reply is None else _sha256(reply.encode("utf-8"))
    cut = whole if reply is None or len(reply) <= RECEIPT_REPLY_CUT else \
        _sha256(reply[:RECEIPT_REPLY_CUT].encode("utf-8"))
    now = time.time()
    rec = {
        "v": 1,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now)) + f".{int(now * 1000) % 1000:03d}Z",
        "session": session_id,
        "bytes": _READ.get("bytes"),
        "tail_lines": len(_READ["lines"]) if "lines" in _READ else None,
        "last_uuid": _last_uuid(_READ.get("lines")) or None,
        "reply_sha256": whole,
        "reply_digest": cut,
        "anchor_id": _READ.get("anchor_id"),
        "turn": _READ.get("turn"),
        "open_turns": _READ.get("open_turns"),
        "fires_before": _READ.get("fires_before"),
        "decision": "block" if reason else "allow",
        "code": _READ.get("code") or ("no-transcript" if not transcript else
                                      "unreadable" if "lines" not in _READ else "error"),
    }
    return rec


def _write_receipt(data: dict, reason: str) -> None:
    """Append the receipt. FAIL-OPEN: any error loses the receipt and nothing else.

    Runs after the verdict is printed and flushed. Skipped once the budget is
    spent (the one-shot alarm may already have fired). Opened non-blocking and
    written only to a regular file, so a FIFO or a device at the path costs
    nothing; a hung mount is bounded by the alarm. The alarm's TimeoutError is
    re-raised, never swallowed.
    """
    try:
        if os.environ.get(RECEIPT_ENV, "1") == "0":
            return
        if time.monotonic() >= _READ.get("deadline", float("inf")):
            return
        rec = build_receipt(data, reason)
        path = _receipt_path(rec["session"] or "unknown")
        path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NONBLOCK", 0)
        fd = os.open(str(path), flags, 0o600)
        try:
            import stat
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                return
            os.write(fd, (json.dumps(rec, sort_keys=True) + "\n").encode("utf-8"))
        finally:
            os.close(fd)
    except TimeoutError:
        raise
    except Exception:
        pass


# -- v8 kernel journal (Phase 4, v8-kernel.md) --------------------------------
_KERNEL_RULE = "FLOW.root-goal-anchor"


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
