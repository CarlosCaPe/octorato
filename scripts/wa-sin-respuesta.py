#!/usr/bin/env python3
"""Vigia de silencio: avisa cuando un cliente escribio y nadie contesto.

Por que existe
--------------
El 2026-08-02 una clienta mando el dato que se le habia pedido, se le contesto
con silencio, y se fue a dormir creyendo que habia fallado. El arreglo ya estaba
aplicado y nadie se lo dijo. La causa no fue el puente, que estaba vivo: fue que
la unica vigilancia del canal corria DENTRO de una sesion de agente, y una
sesion no es infraestructura.

Este script no contesta por nadie. Solo rompe el silencio: si un mensaje de
cliente lleva mas del umbral sin respuesta, sale con error y systemd dispara el
correo de alerta. El operador decide que hacer.

DOS SENSORES, UN VIGIA (6-ago). Nacio mirando solo WhatsApp y el correo no tenia
NINGUNA vigilancia durable: la unica forma de enterarse era que alguien
preguntara. El 5-ago eso costo dos correos del cliente sin leer durante dos
dias, porque el unico vigilante del buzon vivia dentro de una sesion y murio
con ella. El correo entra aqui, no en un script aparte, porque la pregunta del
operador nunca fue "¿contesto por WhatsApp?" sino "¿contesto el cliente?": la
unidad es el CLIENTE, no el canal.

El nombre `wa-` se quedo corto con ese cambio. Renombrarlo toca dos unidades de
systemd vivas y varios importadores, asi que va como cambio propio y separado.

Diseno
------
- Lee la config PRIVADA (`company/config/wa-puentes.json`). Los JID y los
  dominios son dato de cliente y este archivo vive en un repo publico, asi que
  aqui no hay ninguno.
- Base de datos en modo SOLO LECTURA. El vigia nunca escribe en el puente, y
  contra Gmail solo hace GET.
- Avisa UNA vez por mensaje. Si el cliente manda otro y tampoco se contesta,
  ese si vuelve a avisar, porque es un silencio nuevo.
- Cada sensor trae su filtro de ruido, y los dos existen por la misma razon: un
  vigia que grita por algo que no pide respuesta entrena al operador a
  ignorarlo, y ahi se muere el mecanismo. En WhatsApp son los acuses; en correo
  son los autorespondedores.
- Un fallo de red del sensor de correo NO tumba el de WhatsApp. Se avisa como
  ruido y se sigue, porque "no llego nada" y "no pude mirar" no pueden verse
  igual.
- `--selftest` prueba los dos sensores sin tocar nada real ni salir a la red.
  Los tiempos de las pruebas son RELATIVOS a `ahora` a proposito: con marcas
  fijas, un error de signo pasa igual y la prueba aprueba un detector muerto.

Uso
---
    wa-sin-respuesta.py              # revisa y sale 1 si hay silencio
    wa-sin-respuesta.py --selftest   # prueba la logica de los dos sensores
"""
import argparse
import json
import os
import sqlite3
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

CONFIG = Path.home() / ".claude" / "company" / "config" / "wa-puentes.json"
ESTADO = Path.home() / ".cache" / "wa-sin-respuesta.json"

# Credencial de correo. En ~/.gmail-mcp hay DOS archivos con refresh_token y
# solo uno LEE: token.json trae scope gmail.compose (redacta, da 403 al listar)
# y credentials.json trae gmail.modify. Leer el equivocado cuesta un
# diagnostico falso de "faltan permisos".
GMAIL_CRED = Path.home() / ".gmail-mcp" / "credentials.json"
GMAIL_KEYS = Path.home() / ".gmail-mcp" / "gcp-oauth.keys.json"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"


def parse_ts(s):
    """El puente guarda '2026-08-03 04:32:36.862676867-06:00'.

    fromisoformat no traga 9 digitos de fraccion, asi que se recorta a 6. Es
    truncado, no redondeo: para medir minutos de silencio da exactamente igual.
    """
    s = s.strip()
    if "." in s:
        cabeza, resto = s.split(".", 1)
        digitos = ""
        for ch in resto:
            if ch.isdigit():
                digitos += ch
            else:
                resto = resto[len(digitos):]
                break
        else:
            resto = ""
        s = f"{cabeza}.{digitos[:6]}{resto}"
    t = datetime.fromisoformat(s)
    return t if t.tzinfo else t.astimezone()


# Acuses de recibo: cierran la conversacion, no piden respuesta. Un vigia que
# grita por un "Enterada" entrena al operador a ignorarlo, y ahi se muere el
# mecanismo. Por eso el filtro es DOBLE y a proposito conservador: la frase
# tiene que estar en esta lista Y el mensaje tiene que ser corto. Asi
# "gracias, pero me sigue fallando" si avisa, porque no es corto.
ACUSES = {
    "ok", "oka", "okay", "okey", "va", "vale", "sale", "listo", "enterada",
    "enterado", "enteradas", "gracias", "graciasss", "perfecto", "excelente",
    "de acuerdo", "muchas gracias", "va que va", "buenas noches", "buen dia",
    "nos vemos", "nos vemos manana", "nos vemos mañana", "si", "sí", "sip",
}
LARGO_ACUSE = 25


def es_acuse(texto, media):
    """True si el ultimo mensaje del cliente cierra en vez de preguntar."""
    if media:                     # una foto o un audio casi siempre pide algo
        return False
    t = (texto or "").strip().lower()
    if not t:
        return False
    if len(t) > LARGO_ACUSE:
        return False
    # se quitan signos y emoji del final para que "Enterada 👍" siga contando
    limpio = "".join(c for c in t if c.isalpha() or c.isspace()).strip()
    return limpio in ACUSES


def ultimo(con, jid, entrante):
    """Ultimo mensaje del chat. entrante=True -> del cliente; False -> nuestro."""
    fila = con.execute(
        "SELECT id, timestamp, media_type, content FROM messages "
        "WHERE chat_jid = ? AND is_from_me = ? ORDER BY timestamp DESC LIMIT 1",
        (jid, 0 if entrante else 1),
    ).fetchone()
    return fila


def revisa(cfg, ahora=None):
    """Devuelve la lista de silencios que superan el umbral."""
    ahora = ahora or datetime.now(timezone.utc)
    vig = cfg.get("vigilancia")
    if not vig:
        raise SystemExit("la config no trae seccion 'vigilancia'")

    nombre_puente = vig.get("puente", "soporte")
    puente = cfg["puentes"][nombre_puente]
    db = Path(os.path.expanduser(puente["db"]))
    if not db.exists():
        raise SystemExit(f"no existe la base del puente: {db}")

    umbral = timedelta(minutes=int(vig.get("umbral_minutos", 20)))
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    silencios = []

    for chat in vig["chats"]:
        jid, quien = chat["jid"], chat.get("quien", "chat")
        ent = ultimo(con, jid, True)
        if not ent:
            continue
        sal = ultimo(con, jid, False)

        t_ent = parse_ts(ent[1])
        # Si lo ultimo del chat es nuestro, no hay nadie esperando.
        if sal and parse_ts(sal[1]) > t_ent:
            continue

        espera = ahora - t_ent
        if espera < umbral:
            continue

        # Un acuse de recibo cierra la conversacion; nadie esta esperando.
        if es_acuse(ent[3], ent[2]):
            continue

        cuerpo = f"[{ent[2]}]" if ent[2] else (ent[3] or "").replace("\n", " ")
        silencios.append({
            "id": ent[0],
            "quien": quien,
            "minutos": int(espera.total_seconds() // 60),
            "desde": t_ent.isoformat(timespec="seconds"),
            "texto": cuerpo[:160],
        })

    con.close()
    return silencios


# ---------------------------------------------------------------- correo ---
# SEGUNDO SENSOR, MISMO VIGIA. Antes el correo no tenia ninguna vigilancia
# durable: la unica forma de enterarse era que alguien preguntara, y el 5-ago
# eso costo dos correos del cliente sin leer durante dos dias porque murieron
# con la sesion que los vigilaba. WhatsApp ya estaba resuelto aqui; el correo
# entra por la misma puerta en vez de por un script aparte, porque la pregunta
# del operador no es "¿contesto por WhatsApp?" sino "¿contesto el cliente?".


def token_gmail():
    """access_token fresco desde el refresh_token. Nunca lo imprime."""
    cred = json.loads(GMAIL_CRED.read_text())
    keys = json.loads(GMAIL_KEYS.read_text())
    inst = keys.get("installed") or keys.get("web") or keys
    datos = urllib.parse.urlencode({
        "client_id": inst["client_id"], "client_secret": inst["client_secret"],
        "refresh_token": cred["refresh_token"], "grant_type": "refresh_token",
    }).encode()
    with urllib.request.urlopen("https://oauth2.googleapis.com/token",
                                data=datos, timeout=30) as r:
        return json.loads(r.read().decode())["access_token"]


def gmail_get(ruta, at, **params):
    url = f"{GMAIL_API}/{ruta}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {at}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


# El equivalente de ACUSES para el correo. Un "estare fuera de la oficina" no
# espera respuesta, y avisar por el entrena al operador a ignorar el vigia,
# que es la unica forma real de que este mecanismo muera. Se descubrio en la
# primera corrida real: el segundo aviso fue un autorespondedor.
FRASES_AUTO = (
    "fuera de la oficina", "out of office", "estare fuera",
    "estaré fuera", "automatic reply", "respuesta automatica",
    "respuesta automática", "de vacaciones", "no leo este correo",
)


def es_autorespuesta(cabeceras, extracto):
    """True si el ultimo mensaje del hilo lo escribio una maquina.

    Doble via, igual que el filtro de acuses: la cabecera estandar cuando el
    servidor la pone, y la frase cuando no. Outlook no siempre manda
    Auto-Submitted, asi que la cabecera sola deja pasar la mitad.
    """
    auto = (cabeceras.get("auto-submitted") or "").lower()
    if auto and auto != "no":
        return True
    if (cabeceras.get("x-autoreply") or cabeceras.get("x-autorespond")):
        return True
    if "auto_reply" in (cabeceras.get("precedence") or "").lower():
        return True
    t = (extracto or "").lower()
    return any(f in t for f in FRASES_AUTO)


def hilos_gmail(remitente, dias):
    """Hilos con correo de ese remitente. Devuelve (id, ultimo_de_ellos, ts_ms).

    Se mira el HILO, no el mensaje suelto, por la misma razon que en WhatsApp:
    si lo ultimo del hilo es mio, nadie esta esperando. Un mensaje entrante con
    respuesta posterior no es silencio.
    """
    at = token_gmail()
    q = f"in:all newer_than:{dias}d from:{remitente}"
    d = gmail_get("messages", at, q=q, maxResults=25)
    hilos = {}
    for m in d.get("messages") or []:
        hilos[m["threadId"]] = None
    salida = []
    for tid in hilos:
        th = gmail_get(f"threads/{tid}", at, format="metadata",
                       metadataHeaders="Auto-Submitted")
        msgs = th.get("messages") or []
        if not msgs:
            continue
        ultimo_msg = msgs[-1]
        cab = {h["name"].lower(): h["value"]
               for h in ultimo_msg.get("payload", {}).get("headers", [])}
        # SENT en las etiquetas es la senal fiable de "lo mande yo". El header
        # From se puede parecer al mio por alias y no distingue.
        mio = "SENT" in (ultimo_msg.get("labelIds") or [])
        salida.append({
            "hilo": tid,
            "id": ultimo_msg["id"],
            "mio": mio,
            "auto": es_autorespuesta(cab, ultimo_msg.get("snippet") or ""),
            "ts": int(ultimo_msg.get("internalDate", 0)),
            "extracto": (ultimo_msg.get("snippet") or "").replace("\n", " ")[:160],
        })
    return salida


def revisa_correo(cfg, ahora=None, buscador=None):
    """Silencios de correo. `buscador` se inyecta para probar sin red."""
    ahora = ahora or datetime.now(timezone.utc)
    correo = (cfg.get("vigilancia") or {}).get("correo")
    if not correo:
        return []
    buscador = buscador or hilos_gmail
    umbral = timedelta(minutes=int(correo.get("umbral_minutos", 240)))
    dias = int(correo.get("dias", 3))

    silencios = []
    for rem in correo.get("remitentes", []):
        etiqueta = rem.get("quien") if isinstance(rem, dict) else rem
        direccion = rem.get("de") if isinstance(rem, dict) else rem
        try:
            hilos = buscador(direccion, dias)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError,
                KeyError, ValueError) as e:
            # Un fallo de red NO puede tumbar la revision de WhatsApp. Se avisa
            # como ruido y se sigue; callar aqui haria que "no hay correo nuevo"
            # y "no pude mirar el correo" se vieran igual, que es lo peor.
            print(f"AVISO: no se pudo revisar el correo de {direccion}: {e}")
            continue
        for h in hilos:
            if h["mio"] or h.get("auto"):
                continue
            t = datetime.fromtimestamp(h["ts"] / 1000, timezone.utc)
            espera = ahora - t
            if espera < umbral:
                continue
            silencios.append({
                "id": h["id"],
                "quien": f"{etiqueta} (correo)",
                "minutos": int(espera.total_seconds() // 60),
                "desde": t.isoformat(timespec="seconds"),
                "texto": h["extracto"],
            })
    return silencios


def ya_avisado(ids):
    """Filtra los que ya se avisaron. Un mensaje nuevo si vuelve a avisar."""
    try:
        visto = set(json.loads(ESTADO.read_text()))
    except Exception:
        visto = set()
    nuevos = [i for i in ids if i not in visto]
    if nuevos:
        ESTADO.parent.mkdir(parents=True, exist_ok=True)
        # Se conservan los ultimos 200 para que el archivo no crezca sin fin.
        ESTADO.write_text(json.dumps(list(visto | set(ids))[-200:]))
    return nuevos


def selftest():
    fallos = []
    casos = 0
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "m.db"
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE messages (id TEXT, chat_jid TEXT, "
                    "is_from_me INT, timestamp TEXT, media_type TEXT, content TEXT)")
        ahora = datetime.now(timezone.utc)

        def mete(mid, jid, mio, hace_min, txt="hola"):
            t = (ahora - timedelta(minutes=hace_min)).astimezone()
            con.execute("INSERT INTO messages VALUES (?,?,?,?,?,?)",
                        (mid, jid, mio, t.isoformat(sep=" "), None, txt))

        # A: cliente escribio hace 45 min y nadie contesto  -> DEBE avisar
        mete("a1", "A", 0, 45, "me sigue sin abrir, que hago")
        # B: cliente escribio hace 45 min y se le contesto hace 5 -> NO avisa
        mete("b1", "B", 0, 45); mete("b2", "B", 1, 5)
        # C: cliente escribio hace 3 min, aun no vence el umbral -> NO avisa
        mete("c1", "C", 0, 3, "tengo una duda")
        # D: acuse de recibo viejo, nadie espera nada           -> NO avisa
        mete("d1", "D", 0, 900, "Enterada")
        # E: empieza como acuse pero SI pregunta                -> DEBE avisar
        mete("e1", "E", 0, 60, "gracias, pero me sigue marcando el mismo error")
        # F: una foto sin texto siempre pide algo               -> DEBE avisar
        t = (ahora - timedelta(minutes=60)).astimezone()
        con.execute("INSERT INTO messages VALUES (?,?,?,?,?,?)",
                    ("f1", "F", 0, t.isoformat(sep=" "), "image", None))
        con.commit(); con.close()

        cfg = {"puentes": {"p": {"db": str(db)}},
               "vigilancia": {"puente": "p", "umbral_minutos": 20,
                              "chats": [{"jid": c, "quien": c}
                                        for c in "ABCDEF"]}}
        r = {s["quien"] for s in revisa(cfg, ahora)}
        casos += 6  # A..F, cada chat es un caso
        for chat, debia in (("A", True), ("B", False), ("C", False),
                            ("D", False), ("E", True), ("F", True)):
            if (chat in r) != debia:
                fallos.append(
                    f"chat {chat}: {'debia avisar y callo' if debia else 'no debia avisar y grito'}")

        # la fraccion de 9 digitos del puente real no debe romper el parseo
        casos += 1
        try:
            t = parse_ts("2026-08-03 04:32:36.862676867-06:00")
            if t.utcoffset() != timedelta(hours=-6):
                fallos.append("parse_ts perdio la zona horaria")
        except Exception as e:
            fallos.append(f"parse_ts murio con la fraccion larga: {e}")

    # ---- sensor de correo. Sin red: se inyecta el buscador. -----------------
    # Los tiempos son RELATIVOS a `ahora` a proposito. Con marcas fijas en el
    # futuro, un error de signo en la comparacion pasa igual y el selftest
    # aprueba un detector muerto, que ya paso una vez con este mismo patron.
    def falso_buscador(direccion, dias):
        def ms(hace_min):
            return int((ahora - timedelta(minutes=hace_min)).timestamp() * 1000)
        return [
            # G: el cliente escribio hace 5 h y nadie contesto   -> DEBE avisar
            {"hilo": "G", "id": "g1", "mio": False, "de": direccion,
             "ts": ms(300), "extracto": "quedo pendiente tu confirmacion"},
            # H: el cliente escribio, pero lo ULTIMO del hilo es mio -> NO avisa
            {"hilo": "H", "id": "h1", "mio": True, "de": "yo",
             "ts": ms(300), "extracto": "ya te respondi"},
            # I: entrante reciente, aun no vence el umbral       -> NO avisa
            {"hilo": "I", "id": "i1", "mio": False, "de": direccion,
             "ts": ms(10), "extracto": "una duda rapida"},
            # J: autorespondedor viejo, nadie espera nada        -> NO avisa
            {"hilo": "J", "id": "j1", "mio": False, "auto": True,
             "de": direccion, "ts": ms(600),
             "extracto": "Estare fuera de la oficina regresando el lunes"},
        ]

    cfg_correo = {"vigilancia": {"correo": {
        "umbral_minutos": 240, "dias": 3,
        "remitentes": [{"de": "cliente.example", "quien": "Cliente"}]}}}
    vistos = {s["id"] for s in revisa_correo(cfg_correo, ahora, falso_buscador)}
    casos += 3
    casos += 1
    for mid, debia in (("g1", True), ("h1", False), ("i1", False), ("j1", False)):
        if (mid in vistos) != debia:
            fallos.append(
                f"correo {mid}: {'debia avisar y callo' if debia else 'no debia avisar y grito'}")

    # sin seccion de correo en la config, el sensor calla en vez de reventar
    casos += 1
    if revisa_correo({"vigilancia": {}}, ahora, falso_buscador) != []:
        fallos.append("sin config de correo el sensor deberia devolver vacio")

    # un fallo de red NO puede tumbar la revision: se avisa y se sigue
    casos += 1
    def buscador_roto(direccion, dias):
        raise urllib.error.URLError("red caida de prueba")
    try:
        if revisa_correo(cfg_correo, ahora, buscador_roto) != []:
            fallos.append("con la red caida el sensor no deberia inventar silencios")
    except Exception as e:
        fallos.append(f"un fallo de red tumbo la revision entera: {e}")

    for f in fallos:
        print("  FALLA:", f)
    print(f"selftest: {casos - len(fallos)}/{casos}"
          + (" OK" if not fallos else f"  ({len(fallos)} fallo(s))"))
    return 1 if fallos else 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--selftest", action="store_true")
    a = p.parse_args()
    if a.selftest:
        sys.exit(selftest())

    cfg = json.loads(CONFIG.read_text())
    silencios = revisa(cfg) + revisa_correo(cfg)
    if not silencios:
        print("sin silencios pendientes")
        sys.exit(0)

    nuevos = ya_avisado([s["id"] for s in silencios])
    for s in silencios:
        marca = "AVISO" if s["id"] in nuevos else "(ya avisado)"
        print(f"{marca}  {s['quien']}: lleva {s['minutos']} min sin respuesta "
              f"desde {s['desde']}  ->  {s['texto']}")

    # Solo se sale con error cuando hay un silencio NUEVO, para no repetir el
    # mismo correo cada vuelta del temporizador.
    sys.exit(1 if nuevos else 0)


if __name__ == "__main__":
    main()
