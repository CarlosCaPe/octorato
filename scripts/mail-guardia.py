#!/usr/bin/env python3
"""Mail watch: what arrived and we have not answered. Sibling of wa-guardia.py.

SAME CONCEPT, DIFFERENT CHANNEL. `wa-guardia.py` covers WhatsApp and
`wa-sin-respuesta.py` is the durable sentry of that channel. This is the
equivalent for email, which had no watch at all: the only way to find out was
for someone to ask.

Why it exists with its own credential and not through MCP: an MCP only answers
inside the agent turn. Watching needs a process that keeps running when the
agent is gone, and that means talking to the API directly.

MIND THE CREDENTIAL. `~/.gmail-mcp/` holds TWO files with a refresh_token and
only one can read:
  - token.json        -> scope gmail.compose. Drafts, does NOT read. 403 on list.
  - credentials.json  -> scope gmail.modify. This is the good one.
Reading the wrong one costs a false "missing permissions" diagnosis and ends in
asking the operator for an OAuth consent that was never needed.

Read only: it only does GET. It never marks, archives or sends.

Usage:
  mail-guardia.py --de dragon.com.mx                  # unanswered, right now
  mail-guardia.py --de dragon.com.mx --vigilar        # one line per new mail
  mail-guardia.py --consulta "in:all newer_than:3d from:alguien@x.com"
"""
import argparse
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = pathlib.Path.home() / ".gmail-mcp"
CRED = BASE / "credentials.json"          # el que SI lee (gmail.modify)
KEYS = BASE / "gcp-oauth.keys.json"
API = "https://gmail.googleapis.com/gmail/v1/users/me"


def token_de_acceso():
    """Un access_token fresco a partir del refresh_token. Nunca lo imprime."""
    try:
        cred = json.loads(CRED.read_text())
        keys = json.loads(KEYS.read_text())
    except Exception as e:
        sys.exit(f"ERROR: no se pudo leer la credencial de Gmail: {e}")
    inst = keys.get("installed") or keys.get("web") or keys
    datos = urllib.parse.urlencode({
        "client_id": inst["client_id"], "client_secret": inst["client_secret"],
        "refresh_token": cred["refresh_token"], "grant_type": "refresh_token",
    }).encode()
    with urllib.request.urlopen("https://oauth2.googleapis.com/token", data=datos, timeout=30) as r:
        return json.loads(r.read().decode())["access_token"]


def pide(ruta, at, **params):
    url = f"{API}/{ruta}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {at}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def cabecera(msg, nombre):
    for h in msg.get("payload", {}).get("headers", []):
        if h.get("name", "").lower() == nombre.lower():
            return h.get("value", "")
    return ""


def entrantes(at, consulta, limite=25):
    """Correos que empatan la consulta, ya resueltos a remitente y asunto."""
    d = pide("messages", at, q=consulta, maxResults=limite)
    salida = []
    for m in d.get("messages", []) or []:
        det = pide(f"messages/{m['id']}", at, format="metadata",
                   metadataHeaders="From")
        # metadataHeaders acepta un solo valor por parametro en esta forma, asi
        # que el asunto se toma del snippet/subject via una segunda lectura solo
        # si hace falta; para avisar basta con quien escribe y el extracto.
        salida.append({
            "id": m["id"],
            "hilo": det.get("threadId", ""),
            "de": cabecera(det, "From"),
            "extracto": (det.get("snippet") or "").replace("\n", " ")[:160],
        })
    return salida


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--de", help="dominio o correo del remitente a vigilar")
    p.add_argument("--consulta", help="consulta Gmail completa (gana sobre --de)")
    p.add_argument("--dias", type=int, default=3, help="ventana cuando se usa --de")
    p.add_argument("--vigilar", action="store_true", help="no termina: una linea por correo nuevo")
    p.add_argument("--intervalo", type=int, default=120, help="segundos entre sondeos")
    args = p.parse_args()

    if args.consulta:
        consulta = args.consulta
    elif args.de:
        # in:all a proposito: in:inbox se salta Spam y Papelera, que es justo
        # donde caen cobranza, legal y seguridad. Y -from:mi para no contar lo
        # que yo mismo mande, que no espera respuesta MIA.
        consulta = f"in:all newer_than:{args.dias}d from:{args.de}"
    else:
        sys.exit("hace falta --de o --consulta")

    if args.vigilar:
        try:
            at = token_de_acceso()
            vistos = {m["id"] for m in entrantes(at, consulta)}
        except Exception as e:
            sys.exit(f"ERROR al arrancar: {e}")

        # La red se cae a ratos (DNS, handshake, conexion cerrada) y cada tropiezo
        # NO es noticia: un vigia que grita por cada fallo transitorio entrena al
        # operador a ignorarlo, y ahi se muere el mecanismo. Se calla mientras el
        # fallo sea pasajero y se habla cuando ya es una caida sostenida.
        #
        # Callar del todo tampoco sirve: el silencio se ve igual que "no ha
        # llegado nada". Por eso avisa al tercer fallo seguido, repite de vez en
        # cuando si sigue caido, y avisa tambien al recuperarse, que es lo que
        # convierte el silencio posterior en una senal confiable.
        FALLOS_PARA_AVISAR = 3
        REPETIR_CADA = 20
        fallos = 0
        avisado = False

        while True:
            try:
                at = token_de_acceso()      # se refresca solo, el access dura ~1h
                for m in entrantes(at, consulta):
                    if m["id"] not in vistos:
                        vistos.add(m["id"])
                        print(f"CORREO NUEVO de {m['de']}: {m['extracto']}", flush=True)
                if avisado:
                    minutos = fallos * args.intervalo // 60
                    print(f"AVISO: consulta restablecida tras {fallos} intento(s) "
                          f"fallidos (~{minutos} min sin poder leer)", flush=True)
                fallos = 0
                avisado = False
            except (urllib.error.URLError, urllib.error.HTTPError, OSError, KeyError) as e:
                # una consulta fallida no puede tumbar la guardia
                fallos += 1
                if fallos == FALLOS_PARA_AVISAR or (avisado and fallos % REPETIR_CADA == 0):
                    minutos = fallos * args.intervalo // 60
                    print(f"AVISO: llevo {fallos} consultas fallidas seguidas "
                          f"(~{minutos} min sin poder leer el correo). Ultimo error: {e}",
                          flush=True)
                    avisado = True
            time.sleep(args.intervalo)

    at = token_de_acceso()
    msgs = entrantes(at, consulta)
    print(f"consulta: {consulta}")
    if not msgs:
        print("SIN CORREOS NUEVOS")
        return
    print(f"{len(msgs)} CORREO(S):")
    for m in msgs:
        print(f"  de {m['de']}\n     {m['extracto']}  (id={m['id']})")


if __name__ == "__main__":
    main()
