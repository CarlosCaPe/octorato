#!/usr/bin/env python3
"""d__stop__wa-guardia.py — Stop detector: si mande un mensaje y espero respuesta, arma la guardia.

Directiva del operador (2026-08-04): "el hook que arme la guardia solo". Los
watchers le sirven, pero "a veces entran y a veces no" porque hasta ahora
dependian de que el modelo se acordara de armarlos, y una regla que depende de
la memoria del modelo se salta bajo carga (skills/reflexes-over-discipline).
Su propia acotacion fija el alcance: "al menos cuando esperemos algo, si no pues
no". Un watcher sin espera es ruido que entrena a ignorar avisos.

La condicion NO es mi intencion, es un hecho verificable en el store del puente:
mande un mensaje saliente hace poco a un chat y no hay guardia viva para ese
chat. La evidencia es el mensaje enviado, no lo que yo crea haber hecho.

Dispara sobre la CONJUNCION de:
  1. hay >=1 mensaje saliente en los ultimos VENTANA_MIN minutos, en cualquiera
     de los dos puentes,
  2. ese chat no tiene un proceso `wa-guardia.py ... --vigilar` corriendo,
  3. no se aviso ya por ese chat en esta sesion.

Sobre un acierto BLOQUEA una vez con el comando exacto, para que el modelo arme
el Monitor antes de cerrar el turno.

Que NO cuenta como espera:
  - los latidos de salud del puente (contenido "latido-...")
  - mensajes al propio numero del puente (auto-envios de diagnostico)

Loop safety: stop_hook_active=true significa que ya bloqueamos este turno, pasa.
Fail-open en todo error: un detector roto jamas debe secuestrar la conversacion.

Stdin:  {"transcript_path": str, "stop_hook_active": bool, "session_id": str, ...}
Stdout: {"decision": "block", "reason": "..."} sobre un acierto, si no nada.
Exit:   siempre 0.
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


def salientes_recientes(puente, ruta):
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
            "WHERE datetime(a.timestamp) > datetime('now', ?) "
            "  AND datetime(a.timestamp) <= datetime('now')",
            (f"-{VENTANA_MIN} minutes",),
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

    # costura de prueba y escape para instalaciones con los puentes fuera de la
    # ruta estandar. Un payload real de Claude Code nunca trae este campo, asi
    # que en produccion el mapa de puentes es siempre el de arriba.
    puentes = payload.get("wa_guardia_dbs") or PUENTES

    faltantes = []
    for puente, ruta in puentes.items():
        for _p, chat_jid in salientes_recientes(puente, ruta):
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
