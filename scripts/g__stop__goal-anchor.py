#!/usr/bin/env python3
"""g__stop__goal-anchor.py — Stop gate: la pila de objetivos no se erosiona.

Problema que resuelve: tras encadenar obstaculos (un permiso, una region
apagada, un binario que falta), el agente cierra el sub-objetivo con evidencia
legitima y reporta victoria. El objetivo RAIZ de la sesion lleva turnos sin
mencionarse. El contexto reescribe `intent` en cada obstaculo, asi que la raiz
se pierde sin que nadie lo note. Ningun otro mecanismo del cerebro la persiste
entre turnos.

Este gate la persiste en disco y bloquea UNA vez cuando el agente declara
cierre habiendo perdido de vista la raiz.

Ciclo por turno (todo dentro del mismo Stop; el payload trae transcript_path):
  1. Lee del transcript el ultimo mensaje del operador y el ultimo del asistente.
  2. Ancla. Sin estado previo: el prompt del operador, cortado a 240 chars.
     Re-ancla SOLO con marcador determinista (prefijo `objetivo:` / `goal:`,
     frase de pivote, o un ancla ya cerrada mas prompt nuevo). Fuera de eso el
     ancla es pegajosa toda la sesion: "no me deja entrar" o "sale AccessDenied"
     son reacciones del operador al obstaculo, NO objetivos nuevos.
  3. Mencion. Saca palabras de contenido del ancla y las busca en la respuesta.
     Dos distintas bastan: turns_since_mention vuelve a 0.
  4. Dispara solo con la conjuncion completa (ver _should_fire).
  5. Gobernador: techo duro de 2 interrupciones por ancla; en la segunda el
     ancla se cierra sola y el gate no vuelve a hablar de ella.

Conservador por construccion: cualquier duda pasa. Un falso positivo aqui
interrumpe trabajo real; un falso negativo solo deja pasar un turno.

Estado: ~/.claude/.cache/goal-anchor/<session_id>.json

Escape deliberado: cualquier linea de la respuesta con `goal-anchor-ok` exime
el turno.

Stdin:  {"session_id": str, "transcript_path": str, "stop_hook_active": bool}
Stdout: {"decision": "block", "reason": "..."} al disparar, si no nada.
Exit:   siempre 0.
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

_RE_PIVOT = re.compile(
    r"\bolvida eso\b"
    r"|\bcambio de tema\b"
    r"|\bahora vamos a\b"
    r"|\bforget that\b"
    r"|\bnew task\b",
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
        if entry.get("type") != "user" or entry.get("isMeta"):
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

    reply = _last_assistant_text(lines)
    prompt = _last_user_text(lines)

    state = load_state(session_id)
    state["session_id"] = session_id
    state["cwd"] = data.get("cwd") or state.get("cwd") or os.getcwd()
    state["turn"] = int(state.get("turn", 0)) + 1
    state.setdefault("history", [])

    # 2. anclaje
    reanchored = False
    if not state.get("anchor"):
        if prompt:
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
        state["anchor"] = extract_anchor(prompt)
        state["anchor_ts"] = time.time()
        state["anchor_turn"] = state["turn"]
        state["turns_since_mention"] = 0
        state["closed"] = False
        state["fires"] = 0
        reanchored = True

    anchor = state.get("anchor") or ""
    if not anchor:
        save_state(session_id, state)
        return ""

    # 3. mencion
    if anchor_mentioned(anchor, reply):
        state["turns_since_mention"] = 0
        if is_closure_claim(reply) and not state.get("closed"):
            state["closed"] = True
            _retire(state, "done")
    else:
        state["turns_since_mention"] = int(state.get("turns_since_mention", 0)) + 1

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
