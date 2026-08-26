#!/usr/bin/env python3
"""Guardia de chat: que llego y no hemos contestado, aqui y ahora.

DONDE ENCAJA. La vigilancia DURABLE de un canal es de `wa-sin-respuesta.py`, que
corre como timer de systemd fuera de cualquier sesion y alerta por correo cuando
un cliente pasa el umbral sin respuesta. Ese es el dueño del concepto "nadie
contesto", y una sesion no es infraestructura.

Esto es la capa de SESION, y contesta otra pregunta: "ponme al dia AHORA".
No tiene umbral ni alerta, y no sustituye al vigia: si un chat importa de verdad,
va en la seccion `vigilancia` de la config, no colgado de una sesion viva.

Para no tener dos definiciones de lo mismo, la logica que decide QUE cuenta como
pendiente (el filtro de acuses) y DONDE viven los puentes se importan del vigia.
Un "gracias" no es un pendiente, y esa regla se escribe una sola vez.

  --desde-ultimo-mio  (por omision) lo entrante DESPUES de mi ultimo envio.
                      Responde "que me deben" sin fijar una ventana de horas a
                      mano, que siempre queda corta o larga.
  --vigilar           una linea por mensaje nuevo, no termina. Para colgarlo de
                      un Monitor mientras dura la sesion.

Solo LEE. Nunca escribe en la base ni manda nada.

Uso:
  wa-guardia.py <chat_jid> [--puente soporte|personal] [--vigilar] [--con-acuses]
  wa-guardia.py <chat_jid> --horas 24
"""
import argparse
import json
import os
import pathlib
import sqlite3
import sys
import time

# Una sola casa para "esto no deja a nadie esperando". El vigia ya trae esa
# puerta (`no_espera`: acuse corto del catalogo, o aviso de ausencia escrito por
# una maquina), asi que se importa en vez de copiarse: dos copias de esa regla se
# separan con el primer ajuste y entonces el vigia y la guardia se contradicen.
# El nombre del archivo lleva guion, que no es identificador valido, de ahi el
# import por ruta.
def _cargar_no_espera():
    import importlib.util
    ruta = pathlib.Path(__file__).resolve().parent / "wa-sin-respuesta.py"
    spec = importlib.util.spec_from_file_location("wa_sin_respuesta", ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.no_espera


try:
    no_espera = _cargar_no_espera()
except Exception as _e:
    # Sin el vigia a la mano no se inventa una segunda lista: se avisa y no se
    # filtra nada, que es el error seguro (reportar de mas, nunca de menos).
    print(f"AVISO: no se pudo cargar el filtro de acuses del vigia ({_e}); "
          "se reporta todo sin filtrar", file=sys.stderr)

    def no_espera(texto, media):
        return False

CONFIG = pathlib.Path.home() / ".claude" / "company" / "config" / "wa-puentes.json"
# Respaldo si la config privada no existe (clon nuevo, otra maquina).
PUENTES_POR_OMISION = {
    "soporte": "~/.config/whatsapp-support/bridge/store/messages.db",
    "personal": "~/.config/whatsapp-mcp/store/messages.db",
}


def ruta_puente(nombre):
    """La ruta sale de la config privada, que es la misma que usa el vigia."""
    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        return os.path.expanduser(cfg["puentes"][nombre]["db"])
    except Exception:
        return os.path.expanduser(PUENTES_POR_OMISION[nombre])


def chats_vigilados():
    """JIDs que ya tienen vigilancia durable, para no proponer parches encima."""
    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        return {c["jid"] for c in cfg.get("vigilancia", {}).get("chats", [])}
    except Exception:
        return set()


def abrir(nombre):
    ruta = ruta_puente(nombre)
    if not os.path.exists(ruta):
        sys.exit(f"ERROR: no existe la base del puente '{nombre}' en {ruta}")
    return sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)


def ultimo_envio_mio(con, chat):
    fila = con.execute(
        "SELECT max(timestamp) FROM messages WHERE chat_jid = ? AND is_from_me = 1",
        (chat,),
    ).fetchone()
    return fila[0] if fila and fila[0] else None


def entrantes(con, chat, desde):
    # datetime() en las DOS puntas. El puente guarda el instante como texto con
    # offset ('...-06:00') y datetime('now') es UTC pelado: comparar crudo es
    # comparar cadenas y el filtro miente en silencio, que se ve igual que "no
    # hay mensajes". Normalizados, ambos quedan en UTC.
    base = ("SELECT id, datetime(timestamp,'localtime'), sender, "
            "coalesce(media_type,''), coalesce(content,'') FROM messages "
            "WHERE chat_jid = ? AND is_from_me = 0")
    if desde:
        return list(con.execute(base + " AND datetime(timestamp) > datetime(?)"
                                       " ORDER BY timestamp", (chat, desde)))
    return list(con.execute(base + " ORDER BY timestamp", (chat,)))


def linea(m, corte=None):
    _id, cuando, quien, tipo, texto = m
    cuerpo = texto.replace("\n", " ") if texto else f"[{tipo or 'media'}]"
    if corte:
        cuerpo = cuerpo[:corte]
    return f"[{cuando}] {quien}: {cuerpo}  (id={_id})"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("chat_jid")
    p.add_argument("--puente", choices=sorted(PUENTES_POR_OMISION), default="soporte")
    p.add_argument("--vigilar", action="store_true",
                   help="no termina: una linea por mensaje nuevo")
    p.add_argument("--intervalo", type=int, default=60, help="segundos entre sondeos")
    p.add_argument("--horas", type=int, help="ventana fija en vez de 'desde mi ultimo envio'")
    p.add_argument("--con-acuses", action="store_true",
                   help="no filtrar los acuses ('gracias', 'enterada')")
    args = p.parse_args()

    def pendiente(m):
        # m = (id, cuando, quien, media_type, content)
        if args.con_acuses:
            return True
        return not no_espera(m[4], m[3])

    if args.vigilar:
        con = abrir(args.puente)   # al ARRANCAR si se exige que exista
        vistos = {m[0] for m in entrantes(con, args.chat_jid, None)}
        con.close()
        while True:
            try:
                ruta = ruta_puente(args.puente)
                if not os.path.exists(ruta):
                    # Re-parear el puente tras un bloqueo por antispam recrea el
                    # archivo. Antes esto salia por sys.exit() desde abrir(), que
                    # SystemExit no atrapa el except de abajo: la guardia moria
                    # justo cuando el canal estaba inestable, que es cuando mas
                    # se necesita. Ausencia temporal se trata como lectura fallida.
                    raise sqlite3.OperationalError(f"la base no esta ahora mismo: {ruta}")
                con = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
                try:
                    for m in entrantes(con, args.chat_jid, None):
                        if m[0] not in vistos:
                            vistos.add(m[0])
                            if pendiente(m):
                                print(f"MENSAJE NUEVO {linea(m, 400)}", flush=True)
                finally:
                    con.close()
            except (sqlite3.Error, OSError) as e:
                # una lectura fallida no puede tumbar la guardia
                print(f"AVISO: lectura fallida, sigo vigilando: {e}", flush=True)
            time.sleep(args.intervalo)

    con = abrir(args.puente)
    if args.horas:
        corte = con.execute("SELECT datetime('now', ?)", (f"-{args.horas} hours",)).fetchone()[0]
        etiqueta = f"ultimas {args.horas} h"
    else:
        corte = ultimo_envio_mio(con, args.chat_jid)
        etiqueta = "desde mi ultimo envio" if corte else "todo el historial (nunca he escrito aqui)"

    todos = entrantes(con, args.chat_jid, corte)
    pendientes = [m for m in todos if pendiente(m)]
    acuses = len(todos) - len(pendientes)

    durable = args.chat_jid in chats_vigilados()
    print(f"chat {args.chat_jid} | puente {args.puente} | {etiqueta}")
    print("vigilancia durable: " + ("SI, esta en wa-sin-respuesta" if durable
                                    else "NO, solo lo ve la sesion viva"))
    if not pendientes:
        print("SIN MENSAJES NUEVOS" + (f" ({acuses} acuse(s) filtrado(s))" if acuses else ""))
        return
    print(f"{len(pendientes)} MENSAJE(S) SIN CONTESTAR"
          + (f", mas {acuses} acuse(s) filtrado(s)" if acuses else "") + ":")
    for m in pendientes:
        print("  " + linea(m))


if __name__ == "__main__":
    main()
