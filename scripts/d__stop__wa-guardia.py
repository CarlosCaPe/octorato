#!/usr/bin/env python3
"""d__stop__wa-guardia.py: Stop detector: if I sent a message and I am waiting on a reply, arm the watch.

Operator directive (2026-08-04): "el hook que arme la guardia solo" (the hook
should arm the watch by itself). The watchers are useful to him, but "a veces
entran y a veces no" (sometimes they fire and sometimes they do not) because so
far they depended on the model remembering to arm them, and a rule that depends
on the model memory gets skipped under load (skills/reflexes-over-discipline).
His own qualifier sets the scope: "al menos cuando esperemos algo, si no pues
no" (at least when we are waiting on something, otherwise no). A watcher with
nothing to wait for is noise that trains you to ignore alerts.

The condition is NOT my intent, it is a verifiable fact in the bridge store: I
sent an outbound message to a chat recently and there is no live watch for that
chat. The evidence is the sent message, not what I believe I did.

Fires on the CONJUNCTION of:
  0. THIS turn made a message send (v10 AC-21): the transcript shows, after the
     last real operator prompt, a WhatsApp MCP send_* call or a Bash call that
     sends through the support bridge, whose result is not an error. The API
     window below is then also bounded below by the start of the turn,
  1. there is >=1 outbound message in the last VENTANA_MIN minutes, on either
     of the two bridges,
  2. that chat has no `wa-guardia.py ... --vigilar` process running,
  3. no alert was raised for that chat in this session already.

On a hit it BLOCKS once with the exact command, so the model arms the Monitor
before closing the turn.

What does NOT count as waiting:
  - bridge health heartbeats (content "latido-...")
  - messages to the bridge own number (diagnostic self-sends)

Loop safety: stop_hook_active=true means we already blocked this turn, pass.
Fail-open on every error: a broken detector must never hijack the conversation.

Stdin:  {"transcript_path": str, "stop_hook_active": bool, "session_id": str, ...}
Stdout: {"decision": "block", "reason": "..."} on a hit, else nothing.
Exit:   always 0.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import sqlite3
import subprocess
import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "lib"))
try:
    from hook_flags import should_run
except Exception:  # el gating es un lujo, no una dependencia dura
    def should_run(_id, **_kw):
        return True

HOOK_ID = "stop:wa-guardia"
VENTANA_MIN = 20
GUARDIA = str(pathlib.Path.home() / ".claude" / "scripts" / "wa-guardia.py")
PUENTES = {
    "soporte": "~/.config/whatsapp-support/bridge/store/messages.db",
    "personal": "~/.config/whatsapp-mcp/store/messages.db",
}
ESTADO = pathlib.Path.home() / ".claude" / ".cache" / "wa-guardia-avisada"
RUIDO = re.compile(r"^\s*latido[-_]", re.IGNORECASE)
# Misma config privada que usa el vigia. Un chat listado ahi ya tiene vigilancia
# durable y no necesita que la sesion le ponga un parche encima.
CONFIG = pathlib.Path.home() / ".claude" / "company" / "config" / "wa-puentes.json"


def chats_vigilados():
    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        return {c["jid"] for c in cfg.get("vigilancia", {}).get("chats", [])}
    except Exception:
        return set()


def salientes_recientes(puente, ruta, desde=None, ahora="now"):
    """Chats con envio por la API del puente dentro de la ventana. `desde`
    (texto UTC 'YYYY-MM-DD HH:MM:SS') sube la cota inferior al arranque del
    turno; `ahora` existe para la evaluacion historica, en produccion es 'now'."""
    ruta = os.path.expanduser(ruta)
    if not os.path.exists(ruta):
        return []
    con = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
    try:
        # La fuente es api_sends, NO messages.is_from_me. is_from_me solo dice
        # "salio de esta cuenta", y eso incluye lo que el operador escribe desde
        # su telefono: pedirle guardia por un mensaje que el mando a mano es un
        # falso positivo, y los falsos positivos enseñan a ignorar el aviso.
        # api_sends solo tiene lo que salio por la API del puente, o sea yo.
        #
        # datetime() en las dos puntas NO es adorno: el puente guarda el instante
        # como texto con offset ('...-06:00') y datetime('now') devuelve UTC
        # pelado. Comparar crudo es comparar cadenas, '10:' nunca es mayor que
        # '16:', y la consulta daba 0 filas SIEMPRE: asi nacio muerto este
        # detector la primera vez.
        # La ventana lleva las DOS cotas a proposito. Con solo la inferior, un
        # signo invertido ('+20 minutes') deja pasar el selftest en verde y mata
        # el detector en produccion, porque ningun envio real cae en el futuro.
        # La cota superior ancla el lado correcto: un envio con fecha futura no
        # existe, y probar eso obliga al fixture a usar instantes reales.
        filas = con.execute(
            "SELECT DISTINCT a.chat_jid, coalesce(m.content,'') "
            "FROM api_sends a "
            "LEFT JOIN messages m ON m.id = a.id AND m.chat_jid = a.chat_jid "
            "WHERE datetime(a.timestamp) > datetime(?, ?) "
            "  AND datetime(a.timestamp) <= datetime(?) "
            "  AND (? IS NULL OR datetime(a.timestamp) >= datetime(?))",
            (ahora, f"-{VENTANA_MIN} minutes", ahora, desde, desde),
        ).fetchall()
    except sqlite3.OperationalError:
        # puente sin api_sends (version vieja): no puede distinguir agente de
        # humano, asi que NO aporta candidatos. Callar es correcto aqui; inventar
        # avisos desde is_from_me es justo el bug que se esta arreglando.
        return []
    finally:
        con.close()
    chats = set()
    for chat_jid, contenido in filas:
        if RUIDO.match(contenido or ""):
            continue
        chats.add((puente, chat_jid))
    return sorted(chats)


# ── el turno mismo tiene que haber mandado (v10 AC-21) ──────────────────────
# Antes bastaba un envio por la API del puente en los ultimos 20 minutos, y el
# puente de soporte manda por API todo el dia (el bot, otras sesiones): el
# census v10 midio 37 bloqueos con ~90% FP, cualquier turno de trabajo en el
# brain que cerraba cerca de un envio ajeno. El hecho que cuenta ahora es del
# transcript: entre el ultimo prompt real del operador y este Stop hay una
# llamada de envio de mensaje (MCP de WhatsApp send_*, o Bash que manda por el
# puente de soporte) cuyo resultado no fue error. Sin eso no hay nada que
# esperar de un tercero y el detector calla.

_WA_SEND_TOOL = re.compile(r"whatsapp.*__send_(?:message|file|audio_message)$", re.IGNORECASE)


# Un Bash que nombra el puente puede ser solo una lectura del script (sed, grep,
# un diff): lo que distingue un envio es el ACUSE que el puente devuelve,
# {"success":true, ..., "message_id": "..."}. Se lee del resultado y no del
# comando, porque el comando trae prefijos de entorno y expansiones que el
# parser del panel rechaza aunque el mensaje haya salido.
_RE_ACUSE_PUENTE = re.compile(r'"success"\s*:\s*true.*?"message_id"\s*:\s*"[^"]+"', re.DOTALL)


def _texto(contenido):
    if isinstance(contenido, str):
        return contenido
    if isinstance(contenido, list):
        return "\n".join(str(b.get("text", "")) if isinstance(b, dict) else str(b) for b in contenido)
    return str(contenido or "")


def _es_envio(nombre, entrada, resultado):
    if _WA_SEND_TOOL.search(nombre or ""):
        return True
    if nombre == "Bash" and "wa-soporte" in str((entrada or {}).get("command", "")):
        return bool(_RE_ACUSE_PUENTE.search(_texto(resultado)))
    return False


def _es_prompt_real(entrada):
    if entrada.get("type") != "user" or entrada.get("isMeta") or entrada.get("isCompactSummary") \
            or entrada.get("isVisibleInTranscriptOnly"):
        return False
    contenido = (entrada.get("message") or {}).get("content")
    if isinstance(contenido, str):
        return bool(contenido.strip())
    return isinstance(contenido, list) and any(
        isinstance(b, dict) and b.get("type") == "text" and (b.get("text") or "").strip() for b in contenido)


def envios_del_turno(transcript_path):
    """(hubo_envio, inicio_utc). inicio_utc es el instante del ultimo prompt real
    en 'YYYY-MM-DD HH:MM:SS' UTC, o None si el transcript no lo trae."""
    try:
        with open(transcript_path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - 1048576))
            lineas = fh.read().decode("utf-8", errors="replace").splitlines()
    except (OSError, TypeError):
        return False, None
    entradas = []
    for linea in lineas:
        try:
            entradas.append(json.loads(linea))
        except ValueError:
            continue
    inicio = 0
    for i in range(len(entradas) - 1, -1, -1):
        if _es_prompt_real(entradas[i]):
            inicio = i
            break
    else:
        return False, None
    usos, resultados = {}, {}
    for e in entradas[inicio:]:
        for b in (e.get("message") or {}).get("content") or []:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use":
                usos[b.get("id")] = (b.get("name"), b.get("input"))
            elif b.get("type") == "tool_result":
                resultados[b.get("tool_use_id")] = b
    hubo = False
    for uid, (nombre, entrada) in usos.items():
        r = resultados.get(uid)
        if r is None or r.get("is_error"):
            continue                    # negado por un gate, fallido, o sin resultado
        if _es_envio(nombre, entrada, r.get("content")):
            hubo = True
            break
    ts = str(entradas[inicio].get("timestamp") or "")
    inicio_utc = None
    if ts:
        try:
            from datetime import datetime, timezone
            t = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
            inicio_utc = t.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            inicio_utc = None
    return hubo, inicio_utc


def guardia_viva(chat_jid):
    # el chat_jid lleva '@' y '.', que en pgrep -f son parte del patron; se
    # escapan para que no valgan como comodines de regex
    patron = f"wa-guardia.py.*{re.escape(chat_jid)}.*--vigilar"
    try:
        r = subprocess.run(["pgrep", "-f", patron], capture_output=True, text=True)
    except OSError:
        # pgrep es POSIX y no existe en Windows. Sin captura, el FileNotFoundError
        # subia hasta el except general de __main__ y salia con 0: el detector
        # encontraba el chat pendiente y aun asi el gate callaba, en el selftest y
        # en produccion. No poder comprobar el vigia NO es haberlo comprobado, asi
        # que se asume que no hay y el gate avisa. Misma postura que ya_avisado:
        # sin forma de saber, avisar de mas antes que callarse.
        return False
    return r.returncode == 0 and r.stdout.strip() != ""


def ya_avisado(sesion, chat_jid):
    clave = f"{sesion}|{chat_jid}"
    try:
        if ESTADO.exists() and clave in ESTADO.read_text(encoding="utf-8").splitlines():
            return True
        ESTADO.parent.mkdir(parents=True, exist_ok=True)
        with ESTADO.open("a", encoding="utf-8") as fh:
            fh.write(clave + "\n")
    except Exception:
        # sin memoria de estado preferimos avisar de mas que callarnos
        return False
    return False


def _siembra_bases(fixture: pathlib.Path) -> None:
    """Genera las bases del fixture con instantes RELATIVOS a ahora.

    Un fixture con fecha fija no puede probar una ventana relativa: el QA
    demostro que con instantes de 2099 el selftest seguia en verde tras
    invertirle el signo a la ventana, o sea aprobaba un detector muerto. Y un
    fixture con fecha fija en el pasado caduca solo y aprueba por vencido.
    La salida es no versionar las bases y generarlas en cada corrida: los
    payloads .json siguen siendo la fuente versionada, los .db son derivados.
    """
    import sqlite3 as _sq

    seed = fixture / "home" / ".wa-fixture"
    seed.mkdir(parents=True, exist_ok=True)

    esquema = (
        "CREATE TABLE chats (jid TEXT PRIMARY KEY, name TEXT, last_message_time TIMESTAMP);"
        "CREATE TABLE messages (id TEXT, chat_jid TEXT, sender TEXT, content TEXT,"
        " timestamp TIMESTAMP, is_from_me BOOLEAN, media_type TEXT, filename TEXT,"
        " url TEXT, media_key BLOB, file_sha256 BLOB, file_enc_sha256 BLOB,"
        " file_length INTEGER, PRIMARY KEY (id, chat_jid),"
        " FOREIGN KEY (chat_jid) REFERENCES chats(jid));"
        "CREATE TABLE api_sends (id TEXT PRIMARY KEY, chat_jid TEXT NOT NULL,"
        " timestamp TIMESTAMP NOT NULL);"
    )
    CH1, CH2 = "5215550001111@s.whatsapp.net", "5215550002222@s.whatsapp.net"
    DENTRO, FUERA = "-5 minutes", "-9 hours"

    def crear(nombre, filas, con_api=True):
        ruta = seed / nombre
        ruta.unlink(missing_ok=True)
        con = _sq.connect(ruta)
        con.executescript(esquema if con_api else esquema.split("CREATE TABLE api_sends")[0])
        for jid, ident, contenido, desfase, por_api in filas:
            cuando = con.execute("SELECT datetime('now', ?)", (desfase,)).fetchone()[0]
            con.execute("INSERT OR IGNORE INTO chats VALUES (?,?,?)", (jid, jid, cuando))
            con.execute("INSERT INTO messages (id,chat_jid,sender,content,timestamp,is_from_me)"
                        " VALUES (?,?,?,?,?,1)", (ident, jid, "yo", contenido, cuando))
            if por_api and con_api:
                con.execute("INSERT INTO api_sends VALUES (?,?,?)", (ident, jid, cuando))
        con.commit()
        con.close()

    crear("con-espera.db", [(CH1, "m1", "Te mando el avance, me confirmas?", DENTRO, True)])
    crear("sin-espera.db", [(CH1, "m2", "latido-abc123", DENTRO, True),
                            (CH2, "m3", "envio viejo ya contestado", FUERA, True)])
    crear("humano-desde-el-telefono.db", [(CH1, "m4", "Ahorita lo veo, gracias", DENTRO, False)])
    crear("puente-sin-api-sends.db", [(CH1, "m5", "cualquier cosa", DENTRO, False)], con_api=False)


def _selftest() -> int:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import gate_selftest

    argv = sys.argv
    i = argv.index("--selftest")
    fixture = argv[i + 1] if len(argv) > i + 1 else None
    if fixture:
        _siembra_bases(pathlib.Path(fixture).resolve())
    return gate_selftest.run_gate_selftest(__file__, fixture)


def main():
    if not should_run(HOOK_ID):
        return

    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    if payload.get("stop_hook_active"):
        return
    sesion = str(payload.get("session_id", "sin-sesion"))

    hubo_envio, inicio_turno = envios_del_turno(payload.get("transcript_path") or "")
    if not hubo_envio:
        return

    # costura de prueba y escape para instalaciones con los puentes fuera de la
    # ruta estandar. Un payload real de Claude Code nunca trae este campo, asi
    # que en produccion el mapa de puentes es siempre el de arriba.
    puentes = payload.get("wa_guardia_dbs") or PUENTES

    faltantes = []
    for puente, ruta in puentes.items():
        for _p, chat_jid in salientes_recientes(puente, ruta, desde=inicio_turno):
            if guardia_viva(chat_jid):
                continue
            if ya_avisado(sesion, chat_jid):
                continue
            faltantes.append((puente, chat_jid))

    if not faltantes:
        return

    lineas = [
        "GUARDIA SIN ARMAR. Mandaste mensaje(s) en los ultimos "
        f"{VENTANA_MIN} min y no hay watcher para la respuesta.",
        "",
        "Regla (operador, 2026-08-04): si el turno cierra esperando algo de un",
        "tercero, se arma guardia ANTES de cerrar. Si no esperas nada, no.",
        "",
    ]

    durables = chats_vigilados()
    sin_durable = [c for _p, c in faltantes if c not in durables]

    if sin_durable:
        lineas += [
            "ARREGLO DE FONDO primero: estos chats no tienen vigilancia durable,",
            "asi que al morir la sesion se quedan ciegos. Agregalos a la seccion",
            f"'vigilancia' de {CONFIG} y los cubre wa-sin-respuesta.py, que corre",
            "como timer de systemd fuera de cualquier sesion:",
            "",
        ]
        lineas += [f"  {c}" for c in sin_durable]
        lineas.append("")

    lineas += [
        "Y para enterarte AHORA, mientras dura la sesion, un Monitor persistente:",
        "",
    ]
    for puente, chat_jid in faltantes:
        lineas.append(
            f"  python3 {GUARDIA} {chat_jid} --puente {puente} --vigilar --intervalo 60"
        )
    lineas += [
        "",
        "Monitor(persistent=true). El vigia alerta por umbral y sobrevive a la",
        "sesion; el Monitor avisa al instante y muere con ella. Se complementan,",
        "no se sustituyen. Detalle en skills/wa-guardia/SKILL.md.",
        "Si ese envio no espera respuesta (aviso de una via, cierre de hilo),",
        "dilo en una linea y sigue: este aviso no se repite para ese chat.",
    ]

    print(json.dumps({"decision": "block", "reason": "\n".join(lineas)}))


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    try:
        main()
    except Exception:
        # fail-open, siempre
        pass
