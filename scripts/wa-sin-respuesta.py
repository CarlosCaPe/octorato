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

Diseno
------
- Lee la config PRIVADA (`company/config/wa-puentes.json`). Los JID son dato de
  cliente y este archivo vive en un repo publico, asi que aqui no hay ninguno.
- Base de datos en modo SOLO LECTURA. El vigia nunca escribe en el puente.
- Avisa UNA vez por mensaje. Si el cliente manda otro y tampoco se contesta,
  ese si vuelve a avisar, porque es un silencio nuevo.
- `--selftest` prueba la logica contra una base temporal, sin tocar nada real.

Uso
---
    wa-sin-respuesta.py              # revisa y sale 1 si hay silencio
    wa-sin-respuesta.py --selftest   # prueba la logica
"""
import argparse
import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

CONFIG = Path.home() / ".claude" / "company" / "config" / "wa-puentes.json"
ESTADO = Path.home() / ".cache" / "wa-sin-respuesta.json"


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
    silencios = revisa(cfg)
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
