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
cliente lleva mas del umbral sin respuesta, avisa por el canal que le toque
(ver "UN SOLO ARCHIVO, DOS CASAS"). El operador decide que hacer.

DOS SENSORES, UN VIGIA (6-ago). Nacio mirando solo WhatsApp y el correo no tenia
NINGUNA vigilancia durable: la unica forma de enterarse era que alguien
preguntara. El 5-ago eso costo dos correos del cliente sin leer durante dos
dias, porque el unico vigilante del buzon vivia dentro de una sesion y murio
con ella. El correo entra aqui, no en un script aparte, porque la pregunta del
operador nunca fue "¿contesto por WhatsApp?" sino "¿contesto el cliente?": la
unidad es el CLIENTE, no el canal.

El nombre `wa-` se quedo corto con ese cambio. Renombrarlo toca dos unidades de
systemd vivas y varios importadores, asi que va como cambio propio y separado.

UN SOLO ARCHIVO, DOS CASAS (11-ago). El puente de soporte se mudo a una
instancia de AWS y el vigia se quedo en la laptop midiendo una base que ya no
estaba ahi, asi que se apago y nadie vigilo ningun canal. La respuesta NO fue
copiar el script al servidor: dos copias se separan al primer ajuste y entonces
los dos mecanismos se contradicen, que es peor que uno solo. Lo que cambia entre
las dos casas es el ENTORNO, no la logica:

    WA_VIGIA_CONFIG   ruta de la config          (def. ~/.claude/company/...)
    WA_VIGIA_ESTADO   ruta del anti-repeticion   (def. ~/.cache/...)
    WA_VIGIA_CANAL    gmail | canario | whatsapp (def. gmail)
    WA_VIGIA_GMAIL    archivos | secretsmanager  (def. archivos)
    WA_VIGIA_WA_DEST  numero destino del canal whatsapp (o config)
    WA_VIGIA_WA_ENDPOINT  REST del puente (def. http://127.0.0.1:8081/api/send)

`gmail` no manda el correo desde aqui: sale con error y systemd dispara
`OnFailure=wa-alerta@%N.service`, que es quien tiene el OAuth. `canario`
publica el aviso EL MISMO en el tema de SNS que el canario de Cloudflare tiene
suscrito. `whatsapp` manda el aviso por el puente de soporte (REST local
127.0.0.1:8081) al numero del operador; ese numero sale de la config privada o
del entorno, NUNCA de este archivo, que es publico.

LA FUENTE DE LA CREDENCIAL TAMBIEN ES ENTORNO (11-ago). El sensor de correo
buscaba la credencial de Gmail como ARCHIVOS en `~/.gmail-mcp/`, asi que en la
instancia se saltaba solo y ningun remitente quedaba vigilado: la laptop tenia
el timer apagado y el servidor no podia mirar el buzon. Eso es un punto ciego
con cara de vigia sano. `WA_VIGIA_GMAIL=secretsmanager` lee la MISMA credencial
desde AWS Secrets Manager con el rol de la instancia, EN MEMORIA: se pide,
se usa y se tira. Nunca toca el disco del servidor, ni siquiera un rato, porque
un disco de instancia se lo puede llevar alguien y un secreto en disco es un
secreto perdido. El default sigue siendo `archivos`: la laptop no cambia.

Diseno
------
- Lee la config PRIVADA (`company/config/wa-puentes.json`). Los JID y los
  dominios son dato de cliente y este archivo vive en un repo publico, asi que
  aqui no hay ninguno. El ARN del tema de SNS tambien vive ahi: lleva el numero
  de cuenta y ese numero no se publica.
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
- Y ese "no pude mirar" VIAJA EN EL AVISO, no solo en el journal. Un vigia que
  revisa un sensor de dos y avisa igual que si hubiera revisado los dos es un
  falso verde: el operador lee "un silencio" y entiende "solo uno", cuando la
  verdad es "uno de los que si pude mirar". Por eso cada aviso lleva su linea
  de cobertura, tambien cuando la cobertura esta completa.
- `--selftest` prueba los dos sensores sin tocar nada real ni salir a la red.
  Los tiempos de las pruebas son RELATIVOS a `ahora` a proposito: con marcas
  fijas, un error de signo pasa igual y la prueba aprueba un detector muerto.

EL VERDE HAY QUE AFIRMARLO (11-ago). El vigia solo hablaba cuando habia
silencio NUEVO, asi que del lado del tablero la ausencia de aviso significaba
dos cosas OPUESTAS: "ya contestaron" o "el vigia se murio". Un tablero que no
sabe distinguirlas no puede pintar un verde honesto, y un verde que nadie
afirma es adivinanza. Por eso cada publicacion cierra con un bloque
estructurado que lleva el estado de TODOS los vigilados, tambien los sanos:

    --- canario:v1 ---
    {"emisor":..,"ts":..,"cobertura":{..},"chats":[{..}]}

Reglas del bloque, que son contrato con el receptor y no se cambian de un lado
solo:
- `chats` trae todos los chats y remitentes que SI se pudieron medir en esa
  vuelta. Un sano va con `silencio_min: null` y `desde: null`; sin los sanos no
  hay verdes. Lo que NO se pudo mirar se queda FUERA de la lista a proposito:
  mandarlo con null seria decir "esta bien" sin haberlo visto, que es el mismo
  falso verde con otro disfraz. Quien no pudo mirarse sale en `cobertura`.
- `cliente` es la identidad (un cliente puede tener varios canales) y `canal`
  es `whatsapp` o `correo`. Los dos salen de la config, no se adivinan aqui.
- `id` es un slug estable y unico: nombre del cliente, canal y una firma del
  JID o del dominio. Estable entre corridas y sin publicar el identificador.
- `prueba` marca lo que viene de un fixture o de una corrida de prueba, para
  que el receptor lo excluya del tablero. Se prende con WA_VIGIA_PRUEBA=1 o
  por entrada de config.
- `cobertura` dice que sensores alcanzaron a mirar, con su motivo.

EL PULSO (11-ago). El bloque no sirve de nada si el vigia solo publica cuando
algo falla: un tablero sin datos frescos no puede pintar verde, solo gris. Asi
que en el canal `canario` el estado completo se republica cada
WA_VIGIA_PULSO_MIN minutos (def. 30) aunque no haya ni un silencio. No cada 5,
que es cada cuanto corre el timer, porque un aviso cada 5 minutos se vuelve
ruido y el ruido se ignora. En el canal `gmail` NO hay pulso: ahi "avisar" es
salir con error y eso mandaria un correo cada media hora.

Uso
---
    wa-sin-respuesta.py              # revisa y avisa por el canal elegido
    wa-sin-respuesta.py --seco       # calcula e imprime, sin publicar nada
    wa-sin-respuesta.py --selftest   # prueba la logica sin tocar nada real
"""
import argparse
import hashlib
import io
import json
import os
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Las tres rutas y el canal salen del entorno para que el MISMO archivo corra en
# la laptop y en la instancia. Lo que cambia entre las dos casas es donde estan
# las cosas, no que hace el vigia.
CONFIG = Path(os.environ.get(
    "WA_VIGIA_CONFIG",
    str(Path.home() / ".claude" / "company" / "config" / "wa-puentes.json")))
ESTADO = Path(os.environ.get(
    "WA_VIGIA_ESTADO", str(Path.home() / ".cache" / "wa-sin-respuesta.json")))
CANALES = ("gmail", "canario", "whatsapp")
FUENTES_GMAIL = ("archivos", "secretsmanager")

# Marca del bloque estructurado. Es contrato con el receptor: si cambia aqui y
# no alla, el tablero deja de leer el estado y no lo dice, que es justo el modo
# de fallo silencioso que este bloque vino a matar.
MARCA_BLOQUE = "--- canario:v1 ---"
PULSO_MIN = 30

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


def es_prueba():
    """True cuando la corrida NO es operacion real.

    El receptor excluye del tablero todo lo que venga marcado, asi que probar
    en la instancia no ensucia el verde de un cliente. Va por entorno y no por
    una bandera de linea de comandos porque el timer no pasa banderas.
    """
    return os.environ.get("WA_VIGIA_PRUEBA", "").strip().lower() in (
        "1", "true", "si", "sí", "yes")


def _ascii_slug(s):
    """Texto a minusculas sin acentos ni signos. Vacio si no queda nada."""
    t = unicodedata.normalize("NFD", str(s or ""))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    limpio = "".join(c if (c.isascii() and c.isalnum()) else "-" for c in t)
    return "-".join(p for p in limpio.split("-") if p)[:40]


def slug_vigilado(cliente, canal, clave):
    """Slug ESTABLE y unico por chat o remitente.

    Estable porque solo depende de la config, no de la corrida: el receptor
    junta lecturas de distintas vueltas por este id y si cambiara, cada aviso
    inventaria un cliente nuevo. La `clave` (el JID o el dominio) entra HASHEADA
    y no en claro: el id viaja a un tablero y un JID es dato de cliente.
    """
    base = _ascii_slug(cliente) or _ascii_slug(canal) or "vigilado"
    firma = hashlib.sha256(f"{canal}|{clave}".encode()).hexdigest()[:10]
    return f"{base}-{canal}-{firma}"


def estado_vigilado(cliente, canal, clave, etiqueta, minutos=None, desde=None,
                    prueba=False):
    """Una linea del bloque. `minutos`/`desde` en None = sano, sin silencio."""
    return {
        "id": slug_vigilado(cliente, canal, clave),
        "cliente": cliente,
        "canal": canal,
        "etiqueta": etiqueta,
        "silencio_min": minutos,
        "desde": desde,
        "prueba": bool(prueba) or es_prueba(),
    }


def ultimo(con, jid, entrante):
    """Ultimo mensaje del chat. entrante=True -> del cliente; False -> nuestro."""
    fila = con.execute(
        "SELECT id, timestamp, media_type, content FROM messages "
        "WHERE chat_jid = ? AND is_from_me = ? ORDER BY timestamp DESC LIMIT 1",
        (jid, 0 if entrante else 1),
    ).fetchone()
    return fila


# Cuantos entrantes se traen para buscar donde empezo la espera. Un tope hace
# falta porque un chat sin respuesta puede tener miles; si se agota, el silencio
# reportado se queda CORTO, nunca largo, que es el lado seguro del error.
LIMITE_ENTRANTES = 500


def espera_abierta(con, jid):
    """(primer entrante sin contestar, cuantos hay). (None, 0) si no hay espera.

    EL RELOJ ARRANCA EN EL PRIMERO, NO EN EL ULTIMO (11-ago). Se medía desde el
    ULTIMO entrante, asi que cada mensaje nuevo del cliente REINICIABA el reloj:
    entre mas insistia una persona, menos probable era la alarma. Con umbral de
    20 minutos, alguien que escribe cada 15 no disparaba un aviso NUNCA. Se
    encontro en produccion: 23 minutos de espera reportados como verde, porque
    el ultimo mensaje de la persona llevaba 15.

    La espera empieza cuando la persona se queda sin respuesta, o sea en el
    PRIMER entrante posterior a nuestro ultimo saliente. Los mensajes que manda
    despues no reinician nada; si acaso son senal de que lleva mas rato ahi.

    La comparacion se hace con `parse_ts` y no en SQL: el puente guarda la marca
    como texto con desfase horario, y comparar eso como cadena es una trampa.
    """
    sal = ultimo(con, jid, False)
    t_sal = parse_ts(sal[1]) if sal else None
    filas = con.execute(
        "SELECT id, timestamp, media_type, content FROM messages "
        "WHERE chat_jid = ? AND is_from_me = 0 ORDER BY timestamp DESC LIMIT ?",
        (jid, LIMITE_ENTRANTES),
    ).fetchall()
    pendientes = []
    for f in filas:                  # vienen de lo mas nuevo a lo mas viejo
        if t_sal and parse_ts(f[1]) <= t_sal:
            break                    # aqui ya contestamos: lo de atras no espera
        pendientes.append(f)
    if not pendientes:
        return None, 0
    return pendientes[-1], len(pendientes)


def revisa(cfg, ahora=None, estados=None, cobertura=None):
    """Silencios de WhatsApp que superan el umbral.

    `estados` es una lista donde se ANOTA el estado de cada chat que SI se pudo
    medir, sano o no. Sin los sanos el tablero no puede pintar un verde: la
    ausencia de aviso significa a la vez "ya contestaron" y "el vigia se murio".

    `cobertura` recibe el hueco cuando el sensor no pudo mirar. Antes eso era un
    SystemExit, o sea que una base inalcanzable mataba tambien la revision del
    correo y no salia ningun aviso. Ahora el sensor se declara ciego, el otro
    sigue, y el bloque sale con `cobertura.whatsapp:false`.
    """
    ahora = ahora or datetime.now(timezone.utc)
    vig = cfg.get("vigilancia")
    if not vig:
        raise SystemExit("la config no trae seccion 'vigilancia'")
    huecos = cobertura if cobertura is not None else []
    vistos = estados if estados is not None else []

    def anota(texto, falla=True):
        huecos.append({"texto": texto, "falla": falla, "sensor": "whatsapp"})

    nombre_puente = vig.get("puente", "soporte")
    puente = (cfg.get("puentes") or {}).get(nombre_puente)
    if not puente or not puente.get("db"):
        anota(f"sensor de WhatsApp: la config no describe el puente "
              f"{nombre_puente!r}")
        return []
    db = Path(os.path.expanduser(puente["db"]))
    if not db.exists():
        anota(f"sensor de WhatsApp: no existe la base del puente {db}")
        return []

    umbral = timedelta(minutes=int(vig.get("umbral_minutos", 20)))
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        con.execute("SELECT 1 FROM messages LIMIT 1")
    except sqlite3.Error as e:
        anota(f"sensor de WhatsApp: no pude leer la base del puente ({e})")
        return []
    silencios = []

    for chat in vig["chats"]:
        jid, quien = chat["jid"], chat.get("quien", "chat")
        cliente = chat.get("cliente") or quien
        canal = chat.get("canal") or "whatsapp"

        def sano():
            vistos.append(estado_vigilado(cliente, canal, jid, quien,
                                          prueba=chat.get("prueba")))

        ent = ultimo(con, jid, True)
        if not ent:
            sano()
            continue

        # El reloj arranca en el PRIMER entrante sin contestar, no en el ultimo.
        # Ver `espera_abierta`: medir desde el ultimo hacia que insistir apagara
        # la alarma.
        primero, cuantos = espera_abierta(con, jid)
        if not primero:
            # Lo ultimo del chat es nuestro: no hay nadie esperando.
            sano()
            continue

        t_ent = parse_ts(primero[1])
        espera = ahora - t_ent
        if espera < umbral:
            # Aun no vence el umbral: nadie lleva esperando de mas, asi que va
            # como sano. Reportar los minutos aqui pintaria de ambar cualquier
            # mensaje recien llegado y el tablero seria ruido.
            sano()
            continue

        # Un acuse de recibo cierra la conversacion; nadie esta esperando. Se
        # mira el ULTIMO entrante a proposito: lo que cuenta para cerrar es la
        # ultima palabra de la persona, no la primera.
        if es_acuse(ent[3], ent[2]):
            sano()
            continue

        minutos = int(espera.total_seconds() // 60)
        desde = t_ent.isoformat(timespec="seconds")
        # Se muestra el mensaje que ARRANCO la espera, que es el que nadie
        # contesto. Los que vinieron despues se cuentan, porque insistir es
        # parte del dato: dice que la persona sigue ahi.
        cuerpo = f"[{primero[2]}]" if primero[2] else (primero[3] or "").replace("\n", " ")
        cuerpo = cuerpo[:160]
        if cuantos > 1:
            cuerpo += f"  (+{cuantos - 1} mensaje(s) suyos despues, sin respuesta)"
        silencios.append({
            # El id es el del ULTIMO entrante: si la persona manda otro mensaje
            # y sigue sin respuesta, eso es un silencio que vale otro aviso.
            "id": ent[0],
            "quien": quien,
            "cliente": cliente,
            "canal": canal,
            "minutos": minutos,
            "desde": desde,
            "texto": cuerpo,
        })
        vistos.append(estado_vigilado(cliente, canal, jid, quien, minutos,
                                      desde, chat.get("prueba")))

    con.close()
    return silencios


# ---------------------------------------------------------------- correo ---
# SEGUNDO SENSOR, MISMO VIGIA. Antes el correo no tenia ninguna vigilancia
# durable: la unica forma de enterarse era que alguien preguntara, y el 5-ago
# eso costo dos correos del cliente sin leer durante dos dias porque murieron
# con la sesion que los vigilaba. WhatsApp ya estaba resuelto aqui; el correo
# entra por la misma puerta en vez de por un script aparte, porque la pregunta
# del operador no es "¿contesto por WhatsApp?" sino "¿contesto el cliente?".


def fuente_gmail():
    """De donde sale la credencial. Un valor raro REVIENTA, no cae a un default.

    Mismo criterio que `canal_activo`: si un typo (`secretmanager`) cayera a
    `archivos` en la instancia, el vigia se veria corriendo y el sensor de
    correo estaria apagado, que es exactamente el punto ciego que esto cierra.
    """
    f = os.environ.get("WA_VIGIA_GMAIL", "archivos").strip().lower()
    if f not in FUENTES_GMAIL:
        raise SystemExit(f"WA_VIGIA_GMAIL={f!r} no existe. "
                         f"Validos: {', '.join(FUENTES_GMAIL)}")
    return f


def secreto_aws(nombre, region, corredor=None):
    """Lee un secreto con el rol de la instancia y lo devuelve EN MEMORIA.

    Sale por el `aws` de la CLI, igual que la publicacion a SNS, porque en la
    instancia no hay boto3 y el rol ya viaja en el metadata service. El valor
    nunca se escribe: se pide, se parsea y vive en la variable el rato que dura
    la corrida. Si `aws` falla, se levanta el error TAL CUAL lo dijo AWS, que
    es lo que distingue "no existe el secreto" de "no tengo permiso".
    """
    cmd = ["aws", "secretsmanager", "get-secret-value", "--region", region,
           "--secret-id", nombre, "--query", "SecretString", "--output", "text"]
    corredor = corredor or (lambda c: subprocess.run(
        c, capture_output=True, text=True, timeout=60))
    r = corredor(cmd)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip().replace("\n", " ")[:300]
                           or f"aws salio {r.returncode}: {shlex.join(cmd[:5])}")
    return json.loads(r.stdout)


def credenciales_gmail(secretos=None, lector=None):
    """(credenciales, claves OAuth) desde disco o desde Secrets Manager.

    `secretos` es el bloque `vigilancia.correo.secretos` de la config. Cuando
    viene, manda Secrets Manager y el disco NO se toca. Los nombres viven en la
    config y no aqui porque llevan el prefijo de la cuenta y este archivo es
    publico.
    """
    if not secretos:
        return (json.loads(GMAIL_CRED.read_text()),
                json.loads(GMAIL_KEYS.read_text()))
    lector = lector or secreto_aws
    region = secretos["region"]
    return (lector(secretos["credenciales"], region),
            lector(secretos["claves"], region))


def motivo_http(e):
    """Motivo legible de un rechazo. El cuerpo de un ERROR no trae token.

    Sin esto, un refresh_token caducado llega al aviso como "HTTP Error 400:
    Bad Request", que no le dice al operador que tiene que volver a autorizar.
    Google si lo dice, en el cuerpo: `invalid_grant`, `Token has been expired
    or revoked`.
    """
    try:
        cuerpo = e.read().decode("utf-8", "replace").strip().replace("\n", " ")
    except Exception:
        cuerpo = ""
    return f"{getattr(e, 'code', '?')} {getattr(e, 'reason', e)} {cuerpo}".strip()[:300]


def token_gmail(secretos=None, lector=None):
    """access_token fresco desde el refresh_token. Nunca lo imprime."""
    cred, keys = credenciales_gmail(secretos, lector)
    inst = keys.get("installed") or keys.get("web") or keys
    datos = urllib.parse.urlencode({
        "client_id": inst["client_id"], "client_secret": inst["client_secret"],
        "refresh_token": cred["refresh_token"], "grant_type": "refresh_token",
    }).encode()
    try:
        with urllib.request.urlopen("https://oauth2.googleapis.com/token",
                                    data=datos, timeout=30) as r:
            return json.loads(r.read().decode())["access_token"]
    except urllib.error.HTTPError as e:
        # Se convierte a RuntimeError A PROPOSITO, con el motivo dentro: quien
        # llama lo anota en la cobertura y el operador lee "invalid_grant" en
        # el aviso en vez de un 400 pelado que no le dice que hacer.
        raise RuntimeError(
            f"Google rechazo el refresh_token: {motivo_http(e)}") from None


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


def arranca_hilo(msgs):
    """(mensaje donde arranco la espera, cuantos pendientes) de un hilo.

    Mismo arreglo que en WhatsApp: la espera empieza en el PRIMER correo sin
    contestar, no en el ultimo. Midiendo desde el ultimo, un cliente que manda
    tres correos seguidos reiniciaba el reloj tres veces, y el hilo mas
    insistente era justo el que menos avisaba.

    Se saca aparte de `hilos_gmail` para poder probarlo sin red: la version de
    adentro solo se ejercitaba llamando a Gmail, o sea nunca.
    """
    pendientes = []
    for m in reversed(msgs or []):
        if "SENT" in (m.get("labelIds") or []):
            break
        pendientes.append(m)
    if pendientes:
        return pendientes[-1], len(pendientes)
    return (msgs[-1] if msgs else None), 0


def hilos_gmail(remitente, dias, secretos=None):
    """Hilos con correo de ese remitente. Devuelve (id, ultimo_de_ellos, ts_ms).

    Se mira el HILO, no el mensaje suelto, por la misma razon que en WhatsApp:
    si lo ultimo del hilo es mio, nadie esta esperando. Un mensaje entrante con
    respuesta posterior no es silencio.
    """
    at = token_gmail(secretos)
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
        arranca, cuantos = arranca_hilo(msgs)
        salida.append({
            "hilo": tid,
            "id": ultimo_msg["id"],
            "mio": mio,
            "auto": es_autorespuesta(cab, ultimo_msg.get("snippet") or ""),
            "ts": int(arranca.get("internalDate", 0)),
            "cuantos": cuantos,
            "extracto": (arranca.get("snippet") or "").replace("\n", " ")[:160],
        })
    return salida


def revisa_correo(cfg, ahora=None, buscador=None, cobertura=None, fuente=None,
                  estados=None):
    """Silencios de correo. `buscador` se inyecta para probar sin red.

    `cobertura` es una lista donde se ANOTA cada hueco, y cada hueco dice si es
    una FALLA o no. La diferencia importa: "esta casa no vigila correo" es una
    decision de configuracion y solo se reporta; "no pude leer la credencial" o
    "Google me rechazo" es una falla y por si sola tiene que sacar un aviso.
    Devolver [] sin decir por que es lo que convierte un sensor apagado en un
    falso verde.
    """
    ahora = ahora or datetime.now(timezone.utc)
    huecos = cobertura if cobertura is not None else []
    vistos = estados if estados is not None else []

    def anota(texto, falla=True):
        huecos.append({"texto": texto, "falla": falla, "sensor": "correo"})

    correo = (cfg.get("vigilancia") or {}).get("correo")
    if not correo:
        anota("sensor de correo: no configurado en esta casa", falla=False)
        return []

    secretos = correo.get("secretos")
    if buscador is None:
        # Sin este corte, cada remitente reventaria por separado y el motivo
        # real (no hay credencial) quedaria repartido en N lineas de ruido.
        if (fuente or fuente_gmail()) == "secretsmanager":
            if not secretos:
                anota("sensor de correo: SALTADO, WA_VIGIA_GMAIL=secretsmanager "
                      "pero la config no trae vigilancia.correo.secretos")
                return []
        else:
            secretos = None
            if not (GMAIL_CRED.exists() and GMAIL_KEYS.exists()):
                anota("sensor de correo: SALTADO, no hay credenciales de Gmail "
                      "en disco")
                return []
        buscador = lambda direccion, dias: hilos_gmail(direccion, dias, secretos)
    umbral = timedelta(minutes=int(correo.get("umbral_minutos", 240)))
    dias = int(correo.get("dias", 3))

    silencios = []
    for rem in correo.get("remitentes", []):
        etiqueta = rem.get("quien") if isinstance(rem, dict) else rem
        direccion = rem.get("de") if isinstance(rem, dict) else rem
        cliente = (rem.get("cliente") if isinstance(rem, dict) else None) or etiqueta
        canal = (rem.get("canal") if isinstance(rem, dict) else None) or "correo"
        marca = rem.get("prueba") if isinstance(rem, dict) else None
        try:
            hilos = buscador(direccion, dias)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError,
                RuntimeError, KeyError, ValueError) as e:
            # Un fallo de red NO puede tumbar la revision de WhatsApp. Se avisa
            # como ruido y se sigue; callar aqui haria que "no hay correo nuevo"
            # y "no pude mirar el correo" se vieran igual, que es lo peor.
            # Y este remitente NO entra al bloque: decir "sano" de lo que no se
            # pudo mirar es el falso verde que el bloque vino a evitar.
            print(f"AVISO: no se pudo revisar el correo de {direccion}: {e}")
            anota(f"sensor de correo: no pude revisar {direccion} ({e})")
            continue
        # Un remitente puede traer varios hilos callados. El bloque lleva UNA
        # linea por remitente, con el silencio mas viejo, porque el tablero es
        # por cliente y no por hilo. Los avisos si van uno por hilo.
        peor_min, peor_desde = None, None
        for h in hilos:
            if h["mio"] or h.get("auto"):
                continue
            t = datetime.fromtimestamp(h["ts"] / 1000, timezone.utc)
            espera = ahora - t
            if espera < umbral:
                continue
            minutos = int(espera.total_seconds() // 60)
            desde = t.isoformat(timespec="seconds")
            if peor_min is None or minutos > peor_min:
                peor_min, peor_desde = minutos, desde
            texto = h["extracto"]
            if int(h.get("cuantos") or 1) > 1:
                texto += (f"  (+{int(h['cuantos']) - 1} correo(s) suyos "
                          "despues, sin respuesta)")
            silencios.append({
                "id": h["id"],
                "quien": f"{etiqueta} (correo)",
                "cliente": cliente,
                "canal": canal,
                "minutos": minutos,
                "desde": desde,
                "texto": texto,
            })
        vistos.append(estado_vigilado(cliente, canal, direccion, etiqueta,
                                      peor_min, peor_desde, marca))
    return silencios


def lee_estado():
    """El archivo de anti-repeticion. Lee el formato viejo (lista) y el nuevo.

    Nacio como una lista pelada de ids avisados y ahora guarda tambien cuando
    salio el ultimo pulso. Se aceptan los dos para que una actualizacion no
    borre la memoria y vuelva a gritar todo lo ya avisado.
    """
    try:
        d = json.loads(ESTADO.read_text())
    except Exception:
        return {"avisados": [], "pulso": None}
    if isinstance(d, list):
        return {"avisados": d, "pulso": None}
    if isinstance(d, dict):
        return {"avisados": list(d.get("avisados") or []),
                "pulso": d.get("pulso")}
    return {"avisados": [], "pulso": None}


def guarda_estado(estado):
    ESTADO.parent.mkdir(parents=True, exist_ok=True)
    # Se conservan los ultimos 200 para que el archivo no crezca sin fin.
    ESTADO.write_text(json.dumps({"avisados": list(estado["avisados"])[-200:],
                                  "pulso": estado.get("pulso")}))


def toca_pulso(ahora=None, minutos=None):
    """True si toca republicar el estado completo aunque no haya novedad.

    Sin esto el tablero solo tiene datos cuando algo falla, y un tablero que
    solo sabe de fallas no pinta verdes: pinta grises. El intervalo NO es el
    del timer a proposito, porque un aviso cada 5 minutos se vuelve ruido.
    """
    ahora = ahora or datetime.now(timezone.utc)
    minutos = int(os.environ.get("WA_VIGIA_PULSO_MIN", minutos or PULSO_MIN))
    ultimo_pulso = lee_estado().get("pulso")
    if not ultimo_pulso:
        return True
    try:
        t = datetime.fromisoformat(ultimo_pulso)
    except ValueError:
        return True
    if not t.tzinfo:
        t = t.replace(tzinfo=timezone.utc)
    return (ahora - t) >= timedelta(minutes=minutos)


def marca_pulso(ahora=None):
    estado = lee_estado()
    estado["pulso"] = (ahora or datetime.now(timezone.utc)).isoformat(
        timespec="seconds")
    guarda_estado(estado)


def sin_avisar(ids):
    """Los que todavia no se han avisado. Un mensaje nuevo si vuelve a avisar."""
    visto = set(lee_estado()["avisados"])
    return [i for i in ids if i not in visto]


def marca_avisados(ids):
    """Apunta que ya salio el aviso de esos ids.

    Va SEPARADO de `sin_avisar` a proposito. Cuando las dos cosas pasaban
    juntas, un aviso que fallaba al salir dejaba el id marcado igual y ese
    silencio no se volvia a avisar NUNCA: el vigia se comia la unica alerta
    que importaba y se veia verde. Ahora se marca despues de que el aviso
    salio, asi que un fallo de canal se reintenta en la siguiente vuelta.
    """
    if not ids:
        return
    estado = lee_estado()
    estado["avisados"] = list(set(estado["avisados"]) | set(ids))
    guarda_estado(estado)


# ----------------------------------------------------------------- avisos ---
# Dos canales, un solo concepto. En la laptop el correo lo manda systemd por
# OnFailure (ahi vive el OAuth), asi que "avisar" es salir con error. En la
# instancia no hay OAuth ni debe haberlo, y el aviso se publica en el tema de
# SNS que el canario de Cloudflare tiene suscrito: la alerta sale del plano que
# se esta vigilando antes de que ese plano pueda tragarsela.


def canal_activo():
    """Canal elegido por entorno. Un valor raro REVIENTA, no cae a un default.

    Si un typo (`WA_VIGIA_CANAL=canaro`) cayera a `gmail` en la instancia, el
    vigia se veria corriendo y el aviso no saldria de ahi jamas: el peor modo
    de fallo posible para un vigia.
    """
    canal = os.environ.get("WA_VIGIA_CANAL", "gmail").strip().lower()
    if canal not in CANALES:
        raise SystemExit(
            f"WA_VIGIA_CANAL={canal!r} no existe. Validos: {', '.join(CANALES)}")
    return canal


def texto_cobertura(cobertura):
    """Una linea siempre, tambien cuando no falto nada."""
    if not cobertura:
        return "Cobertura: completa (WhatsApp + correo)."
    return "Cobertura REDUCIDA:\n" + "\n".join(
        f"  - {c['texto']}" for c in cobertura)


def id_degradacion(cobertura, ahora=None):
    """Id del aviso por sensor caido. None cuando ningun hueco es falla.

    Existe porque un sensor muerto tenia que coincidir con un silencio de
    WhatsApp para que alguien se enterara: sin silencios el vigia salia con 0 y
    la degradacion se quedaba en el journal, que nadie lee. Un sensor apagado
    ES la noticia.

    Lleva la FECHA para que vuelva a gritar cada dia mientras siga roto, y se
    le quitan los digitos al texto para que un id o un numero que cambia entre
    corridas no lo convierta en un aviso cada 5 minutos.
    """
    fallas = sorted(c["texto"] for c in cobertura if c.get("falla"))
    if not fallas:
        return None
    estable = "|".join("".join("#" if ch.isdigit() else ch for ch in f)
                       for f in fallas)
    ahora = ahora or datetime.now(timezone.utc)
    firma = hashlib.sha256(estable.encode()).hexdigest()[:10]
    return f"cobertura:{ahora:%Y-%m-%d}:{firma}"


NOMBRES_CANAL = {"whatsapp": ("chat", "chats"),
                 "correo": ("correo", "correos")}


def agrupa_silencios(silencios):
    """'Dragon (4 correos), Despacho (1 chat)'.

    Antes el asunto repetia la etiqueta por cada hallazgo, asi que cuatro
    correos del mismo remitente salian como cuatro veces el mismo nombre y el
    asunto no cabia ni decia nada. Se agrupa por CLIENTE, que es la unidad que
    le importa al operador, y dentro por canal. El orden es el de aparicion:
    lo primero que se encontro va primero.
    """
    orden, cuenta = [], {}
    for s in silencios:
        cliente = s.get("cliente") or s.get("quien") or "sin nombre"
        canal = s.get("canal") or "whatsapp"
        if cliente not in cuenta:
            orden.append(cliente)
            cuenta[cliente] = {}
        cuenta[cliente][canal] = cuenta[cliente].get(canal, 0) + 1
    partes = []
    for cliente in orden:
        trozos = []
        for canal, n in cuenta[cliente].items():
            uno, varios = NOMBRES_CANAL.get(canal, ("aviso", "avisos"))
            trozos.append(f"{n} {uno if n == 1 else varios}")
        partes.append(f"{cliente} ({', '.join(trozos)})")
    return ", ".join(partes)


def abiertos(estados):
    """Los vigilados que traen un silencio en pie, ya avisado o no."""
    return [e for e in (estados or []) if e.get("silencio_min") is not None]


def asunto_aviso(silencios, cobertura, estados=None):
    """El asunto tiene que decir QUE pasa sin abrir el cuerpo."""
    if silencios:
        return "Octorato: sin respuesta en " + agrupa_silencios(silencios)
    fallas = [c["texto"] for c in cobertura if c.get("falla")]
    if fallas:
        return "Octorato: vigia DEGRADADO, " + "; ".join(fallas)
    # Publicacion de pulso. "Nuevo" y "abierto" no son lo mismo: un silencio ya
    # avisado sigue abierto, y decir "ningun silencio" mientras el bloque
    # reporta 6770 minutos seria contradecirse en el mismo mensaje.
    espera = abiertos(estados)
    if espera:
        return ("Octorato: vigia OK, sin aviso nuevo, sigue esperando "
                + agrupa_silencios(espera))
    return (f"Octorato: vigia OK, {len(estados or [])} vigilado(s), "
            "ningun silencio abierto")


def cuerpo_aviso(silencios, cobertura, host, estados=None, ahora=None):
    """El texto que lee el operador MAS el bloque que lee el tablero.

    El bloque va SIEMPRE y va AL FINAL: el receptor lo busca por la marca y
    parsea todo lo que sigue, asi que nada puede ir despues.
    """
    if silencios:
        lineas = [f"Vigia de silencio en {host}.",
                  f"{len(silencios)} silencio(s) nuevo(s) sin respuesta.", ""]
    elif any(c.get("falla") for c in cobertura):
        # Este aviso sale por la degradacion, no por un silencio. Decirlo asi
        # evita que se lea como "todo bien, cero silencios".
        lineas = [f"Vigia de silencio en {host}.",
                  "Sin silencios nuevos, pero el vigia NO pudo mirar todo. "
                  "Lo que sigue no es una revision completa.", ""]
    elif abiertos(estados):
        lineas = [f"Vigia de silencio en {host}.",
                  "Sin silencios NUEVOS, pero lo ya avisado sigue abierto. "
                  "El detalle por cliente va en el bloque de abajo.", ""]
    else:
        lineas = [f"Vigia de silencio en {host}.",
                  "Ningun silencio abierto. Va el estado completo para que el "
                  "tablero pueda pintar un verde con dato fresco.", ""]
    for s in silencios:
        lineas.append(f"- {s['quien']}: {s['minutos']} min desde {s['desde']}")
        lineas.append(f"    {s['texto']}")
    lineas += ["", texto_cobertura(cobertura), "",
               bloque_canario(estados, cobertura, ahora, host)]
    return "\n".join(lineas)


def cobertura_bloque(cobertura):
    """Que sensores alcanzaron a mirar, en la forma que espera el receptor.

    Un hueco de cualquier tipo apaga su sensor, tambien el que no es falla:
    "esta casa no vigila correo" no es una averia, pero tampoco es haber
    mirado, y el tablero no puede leerlo como si lo fuera.
    """
    caidos = {c.get("sensor", "correo") for c in cobertura}
    return {"whatsapp": "whatsapp" not in caidos,
            "correo": "correo" not in caidos,
            "nota": "; ".join(c["texto"] for c in cobertura)}


def bloque_canario(estados, cobertura, ahora=None, host=None):
    """La marca y el JSON en UNA linea. Contrato con el receptor."""
    ahora = ahora or datetime.now(timezone.utc)
    datos = {
        "emisor": host or os.uname().nodename,
        "ts": ahora.isoformat(timespec="seconds"),
        "cobertura": cobertura_bloque(cobertura or []),
        "chats": list(estados or []),
    }
    return MARCA_BLOQUE + "\n" + json.dumps(datos, separators=(",", ":"))


def publica_sns(tema, asunto, cuerpo, corredor=None):
    """Publica en SNS con el rol de la instancia. Sin credenciales en disco.

    La region sale del propio ARN (campo 4) en vez de una constante: un tema
    que se mueva de region no puede dejar el aviso apuntando a la vieja.
    """
    partes = tema.split(":")
    if len(partes) < 6 or partes[0] != "arn":
        raise RuntimeError(f"ARN de tema mal formado: {tema!r}")
    # SNS: el asunto es ASCII imprimible, sin saltos, maximo 100.
    asunto = "".join(c if 32 <= ord(c) < 127 else " " for c in asunto)[:99]
    cmd = ["aws", "sns", "publish", "--region", partes[3], "--topic-arn", tema,
           "--subject", asunto, "--message", cuerpo,
           "--query", "MessageId", "--output", "text"]
    corredor = corredor or (lambda c: subprocess.run(
        c, capture_output=True, text=True, timeout=60))
    r = corredor(cmd)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip()[:300]
                           or f"aws salio {r.returncode}: {shlex.join(cmd[:6])}")
    return r.stdout.strip()


def avisa_canario(cfg, silencios, cobertura, host=None, corredor=None,
                  estados=None, ahora=None):
    """Publica el aviso donde el canario lo va a ver. Devuelve el MessageId."""
    tema = ((cfg.get("vigilancia") or {}).get("canario") or {}).get("tema")
    if not tema:
        raise RuntimeError(
            "falta vigilancia.canario.tema en la config (ARN del tema de SNS)")
    host = host or os.uname().nodename
    return publica_sns(tema, asunto_aviso(silencios, cobertura, estados),
                       cuerpo_aviso(silencios, cobertura, host, estados, ahora),
                       corredor)


def selftest():
    # Se declaran arriba porque el selftest los cambia por dobles para no salir
    # a la red ni a AWS: una prueba que llama a la nube deja de ser prueba.
    global ESTADO, secreto_aws
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
        # G: INSISTE. El ULTIMO entrante lleva 14 min (bajo el umbral) pero el
        # PRIMERO sin contestar lleva 23 (encima). El bug real: se media desde el
        # ultimo, asi que insistir apagaba la alarma y esto salia verde con una
        # persona esperando 23 minutos.       -> DEBE avisar, y con 23, no con 14
        mete("g1", "G", 1, 24, "ahorita te contesto")
        mete("g2", "G", 0, 23, "oye pregunta")
        mete("g3", "G", 0, 23, "usarias este perfume?")
        mete("g4", "G", 0, 15, "agrega al final...")
        mete("g5", "G", 0, 14, "cuentame un chiste")
        # H: varios entrantes seguidos, pero YA conteste al final -> NO avisa
        mete("h1", "H", 0, 90, "me falla el acceso")
        mete("h2", "H", 0, 80, "sigue igual?")
        mete("h3", "H", 1, 40, "ya quedo, pruebalo")
        con.commit(); con.close()

        cfg = {"puentes": {"p": {"db": str(db)}},
               "vigilancia": {"puente": "p", "umbral_minutos": 20,
                              "chats": [{"jid": c, "quien": c, "cliente": c,
                                         "canal": "whatsapp"}
                                        for c in "ABCDEFGH"]}}
        est_wa, cob_wa = [], []
        silencios_wa = revisa(cfg, ahora, est_wa, cob_wa)
        r = {s["quien"] for s in silencios_wa}
        casos += 8  # A..H, cada chat es un caso
        for chat, debia in (("A", True), ("B", False), ("C", False),
                            ("D", False), ("E", True), ("F", True),
                            ("G", True), ("H", False)):
            if (chat in r) != debia:
                fallos.append(
                    f"chat {chat}: {'debia avisar y callo' if debia else 'no debia avisar y grito'}")

        # ---- el reloj arranca en el PRIMERO sin contestar -------------------
        # No basta con que G avise: tiene que avisar con la espera REAL. Si
        # midiera desde el ultimo entrante daria 14 min, por debajo del umbral,
        # y G ni siquiera estaria en la lista.
        casos += 1
        g = next((s for s in silencios_wa if s["quien"] == "G"), None)
        if not g:
            fallos.append("G no aviso: se esta midiendo desde el ultimo entrante "
                          "y por eso insistir apaga la alarma")
        elif g["minutos"] < 23:
            fallos.append(f"G aviso con {g['minutos']} min: el reloj arranco en "
                          "un mensaje posterior, no en el primero sin contestar")
        casos += 1
        # y el aviso tiene que decir que la persona insistio: son 4 mensajes
        if g and "+3 mensaje" not in g["texto"]:
            fallos.append(f"el aviso no dice cuantas veces insistio: {g['texto']!r}")

        # ---- el bloque: los SANOS tambien viajan --------------------------
        # Este es el bug que el bloque vino a cerrar. Con solo los que fallan,
        # el tablero no puede distinguir "ya contestaron" de "el vigia murio".
        casos += 1
        if len(est_wa) != 8:
            fallos.append(f"el bloque deberia traer los 8 chats, trajo "
                          f"{len(est_wa)}: {[e['id'] for e in est_wa]}")
        por_cliente = {e["cliente"]: e for e in est_wa}
        casos += 1
        sanos = [c for c in "BCDH" if por_cliente.get(c, {}).get("silencio_min")
                 is not None]
        if sanos:
            fallos.append(f"chats sanos con silencio en el bloque: {sanos}")
        casos += 1
        mudos = [c for c in "AEFG"
                 if por_cliente.get(c, {}).get("silencio_min") is None
                 or not por_cliente.get(c, {}).get("desde")]
        if mudos:
            fallos.append(f"chats con silencio que salieron sanos: {mudos}")
        casos += 1
        # el bloque es lo que ve el tablero: si ahi G sale en null, el vigia
        # esta pintando verde sobre una persona que lleva 23 minutos esperando
        g_bloque = (por_cliente.get("G") or {}).get("silencio_min")
        if g and g_bloque != g["minutos"]:
            fallos.append(f"el bloque dice {g_bloque} y el aviso {g['minutos']} "
                          "para el mismo chat")
        casos += 1
        if len({e["id"] for e in est_wa}) != 8:
            fallos.append("dos vigilados comparten id y uno pisa al otro")
        # el mismo chat, otra corrida, el MISMO id: el receptor junta lecturas
        # por id y un id que cambia inventa un cliente nuevo cada vuelta
        casos += 1
        otra = []
        revisa(cfg, ahora + timedelta(minutes=7), otra, [])
        if [e["id"] for e in otra] != [e["id"] for e in est_wa]:
            fallos.append("el id de un vigilado cambio entre corridas")
        casos += 1
        if cob_wa:
            fallos.append(f"con la base sana no deberia haber huecos: {cob_wa}")

        # una base que no existe NO puede matar la revision entera: se declara
        # ciego el sensor y el otro sigue. Antes era SystemExit y no salia nada.
        casos += 1
        cfg_sin_db = {"puentes": {"p": {"db": str(db) + ".no-existe"}},
                      "vigilancia": {"puente": "p", "chats": [
                          {"jid": "A", "quien": "A", "cliente": "A"}]}}
        cob_sin, est_sin = [], []
        try:
            r_sin = revisa(cfg_sin_db, ahora, est_sin, cob_sin)
        except SystemExit as e:
            r_sin, cob_sin = ["revento"], []
            fallos.append(f"una base ausente tumbo la revision entera: {e}")
        if r_sin != [] or not any(c["sensor"] == "whatsapp" and c["falla"]
                                  for c in cob_sin):
            fallos.append(f"una base ausente deberia salir en cobertura: {cob_sin}")
        casos += 1
        if est_sin:
            fallos.append("lo que no se pudo mirar no puede salir como sano "
                          f"en el bloque: {est_sin}")

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
        "remitentes": [{"de": "cliente.example", "quien": "Cliente",
                        "cliente": "Cliente", "canal": "correo"}]}}}
    vistos = {s["id"] for s in revisa_correo(cfg_correo, ahora, falso_buscador)}
    casos += 3
    casos += 1
    for mid, debia in (("g1", True), ("h1", False), ("i1", False), ("j1", False)):
        if (mid in vistos) != debia:
            fallos.append(
                f"correo {mid}: {'debia avisar y callo' if debia else 'no debia avisar y grito'}")

    # el remitente tambien entra al bloque, con el silencio mas viejo de sus
    # hilos: el tablero es por cliente, no por hilo
    casos += 1
    est_mail = []
    revisa_correo(cfg_correo, ahora, falso_buscador, estados=est_mail)
    if len(est_mail) != 1 or est_mail[0]["canal"] != "correo":
        fallos.append(f"el remitente no entro al bloque: {est_mail}")
    casos += 1
    if est_mail and est_mail[0]["silencio_min"] != 300:
        fallos.append(f"el bloque no tomo el silencio del hilo callado: {est_mail}")

    # el mismo bug del reloj, en correo: un hilo donde el cliente mando tres
    # correos seguidos. El ULTIMO lleva 100 min (bajo el umbral de 240) y el
    # PRIMERO sin contestar lleva 400 (encima). `hilos_gmail` tiene que traer el
    # ts del primero, asi que aqui se comprueba que revisa_correo lo respeta.
    casos += 1
    def buscador_insiste(direccion, dias):
        return [{"hilo": "K", "id": "k3", "mio": False, "cuantos": 3,
                 "ts": int((ahora - timedelta(minutes=400)).timestamp() * 1000),
                 "extracto": "te mande el archivo, me confirmas?"}]
    sil_k = revisa_correo(cfg_correo, ahora, buscador_insiste)
    if not sil_k or sil_k[0]["minutos"] < 400:
        fallos.append(f"el hilo insistente no aviso con la espera real: {sil_k}")
    casos += 1
    if sil_k and "+2 correo" not in sil_k[0]["texto"]:
        fallos.append(f"el aviso no dice que insistio por correo: {sil_k[0]['texto']!r}")

    # el recorrido del hilo, sin red: de donde arranca la espera
    hilo_insiste = [{"id": "m1", "internalDate": "100", "labelIds": ["SENT"]},
                    {"id": "m2", "internalDate": "200", "labelIds": ["INBOX"]},
                    {"id": "m3", "internalDate": "300", "labelIds": ["INBOX"]},
                    {"id": "m4", "internalDate": "400", "labelIds": ["INBOX"]}]
    casos += 1
    arranca, cuantos = arranca_hilo(hilo_insiste)
    if arranca["id"] != "m2" or cuantos != 3:
        fallos.append(f"el hilo arranco en el mensaje equivocado: {arranca['id']}, "
                      f"{cuantos} pendientes")
    casos += 1
    # si lo ultimo del hilo es mio, no hay espera abierta
    arranca, cuantos = arranca_hilo(hilo_insiste + [
        {"id": "m5", "internalDate": "500", "labelIds": ["SENT"]}])
    if cuantos != 0:
        fallos.append("un hilo ya contestado no puede traer pendientes")
    casos += 1
    # un hilo sin ninguna respuesta mia arranca en el primer mensaje de todos
    arranca, cuantos = arranca_hilo([m for m in hilo_insiste if "INBOX" in m["labelIds"]])
    if arranca["id"] != "m2" or cuantos != 3:
        fallos.append("un hilo sin respuesta mia deberia arrancar en el primero")

    # un remitente sin ningun hilo callado va SANO, en null. Sin esto no hay
    # verdes de correo.
    casos += 1
    est_mail = []
    revisa_correo(cfg_correo, ahora,
                  lambda d, dias: [{"hilo": "H", "id": "h1", "mio": True,
                                    "ts": 0, "extracto": ""}],
                  estados=est_mail)
    if len(est_mail) != 1 or est_mail[0]["silencio_min"] is not None:
        fallos.append(f"un remitente sin silencio deberia ir en null: {est_mail}")

    # sin seccion de correo en la config, el sensor calla en vez de reventar
    casos += 1
    if revisa_correo({"vigilancia": {}}, ahora, falso_buscador) != []:
        fallos.append("sin config de correo el sensor deberia devolver vacio")

    # un fallo de red NO puede tumbar la revision: se avisa y se sigue
    casos += 1
    def buscador_roto(direccion, dias):
        raise urllib.error.URLError("red caida de prueba")
    est_roto = []
    try:
        if revisa_correo(cfg_correo, ahora, buscador_roto, estados=est_roto) != []:
            fallos.append("con la red caida el sensor no deberia inventar silencios")
    except Exception as e:
        fallos.append(f"un fallo de red tumbo la revision entera: {e}")
    # ...y sobre todo NO puede declararlo sano: un null que nadie midio es un
    # verde inventado, que es peor que un hueco declarado.
    casos += 1
    if est_roto:
        fallos.append(f"un remitente que no se pudo mirar salio como sano: {est_roto}")

    # ---- cobertura. Un hueco que no se cuenta es un falso verde. ------------
    casos += 1
    cob = []
    revisa_correo({"vigilancia": {}}, ahora, falso_buscador, cob)
    if not any("no configurado" in c["texto"] for c in cob):
        fallos.append("sin seccion de correo, la cobertura deberia decirlo")

    # ...pero "esta casa no vigila correo" es configuracion, no averia: no
    # puede sacar un aviso de degradacion cada dia por si sola.
    casos += 1
    if any(c["falla"] for c in cob):
        fallos.append("'no configurado' no es una falla y se marco como tal")

    casos += 1
    cob = []
    revisa_correo(cfg_correo, ahora, buscador_roto, cob)
    if not any("no pude revisar" in c["texto"] for c in cob):
        fallos.append("con la red caida, la cobertura deberia decirlo")
    casos += 1
    if not all(c["falla"] for c in cob):
        fallos.append("una red caida SI es falla y no se marco")

    casos += 1
    cob = []
    revisa_correo(cfg_correo, ahora, falso_buscador, cob)
    if cob:
        fallos.append(f"sin huecos la cobertura deberia ir vacia, trajo {cob}")

    # el texto que VIAJA en el aviso, no solo la lista interna
    hueco = [{"texto": "sensor de correo: SALTADO", "falla": True}]
    casos += 1
    if "completa" not in texto_cobertura([]):
        fallos.append("sin huecos el aviso deberia decir cobertura completa")
    casos += 1
    if "REDUCIDA" not in texto_cobertura(hueco):
        fallos.append("con un hueco el aviso deberia gritar cobertura reducida")

    # el cuerpo del aviso tiene que llevar el silencio Y la cobertura
    casos += 1
    uno = [{"quien": "chat X", "minutos": 44,
            "desde": "2026-01-01T00:00:00+00:00", "texto": "me sigue fallando"}]
    cuerpo = cuerpo_aviso(uno, hueco, "maquina")
    if not ("chat X" in cuerpo and "44" in cuerpo and "REDUCIDA" in cuerpo):
        fallos.append(f"el cuerpo del aviso se comio algo: {cuerpo!r}")

    # ---- el bloque estructurado: contrato con el receptor -------------------
    def lee_bloque(texto):
        """Lo mismo que hace el receptor: buscar la marca y parsear lo que sigue."""
        i = texto.rfind(MARCA_BLOQUE)
        if i < 0:
            return None
        return json.loads(texto[i + len(MARCA_BLOQUE):])

    est_demo = [
        estado_vigilado("Dragon", "whatsapp", "1@g.us", "grupo de proyecto",
                        5371, "2026-08-07T18:07:00+00:00"),
        estado_vigilado("Despacho", "whatsapp", "2@lid", "privado"),
    ]
    casos += 1
    d = lee_bloque(cuerpo_aviso(uno, hueco, "maquina", est_demo, ahora))
    if not d or len(d.get("chats") or []) != 2:
        fallos.append(f"el aviso con silencios no llevo el bloque: {d}")
    # y tambien el aviso DEGRADADO, que es cuando mas falta hace saber que se vio
    casos += 1
    d = lee_bloque(cuerpo_aviso([], hueco, "maquina", est_demo, ahora))
    if not d or len(d.get("chats") or []) != 2:
        fallos.append(f"el aviso degradado no llevo el bloque: {d}")
    casos += 1
    if d.get("cobertura", {}).get("correo") is not False:
        fallos.append(f"con el sensor de correo caido, cobertura.correo deberia "
                      f"ser false: {d.get('cobertura')}")
    casos += 1
    if d.get("cobertura", {}).get("whatsapp") is not True:
        fallos.append("un hueco de correo no puede apagar el sensor de WhatsApp")
    casos += 1
    if "SALTADO" not in (d.get("cobertura", {}).get("nota") or ""):
        fallos.append(f"la nota de cobertura no dice el motivo: {d.get('cobertura')}")
    # el pulso sin nada roto: cobertura completa y ningun silencio
    casos += 1
    d = lee_bloque(cuerpo_aviso([], [], "maquina", est_demo, ahora))
    cb = (d or {}).get("cobertura") or {}
    if not (cb.get("whatsapp") and cb.get("correo") and cb.get("nota") == ""):
        fallos.append(f"sin huecos la cobertura del bloque deberia ir limpia: {cb}")
    casos += 1
    if d.get("emisor") != "maquina" or not d.get("ts"):
        fallos.append(f"el bloque no dice quien ni cuando: {d}")
    # nada puede ir DESPUES del JSON: el receptor parsea hasta el final
    casos += 1
    texto = cuerpo_aviso([], [], "maquina", est_demo, ahora)
    if not texto.rstrip().endswith("}"):
        fallos.append("el bloque no quedo al final del cuerpo")
    # un sano viaja con los dos campos en null, no ausentes
    casos += 1
    sano = [c for c in d["chats"] if c["cliente"] == "Despacho"][0]
    if sano["silencio_min"] is not None or sano["desde"] is not None:
        fallos.append(f"un chat sano deberia ir en null: {sano}")
    casos += 1
    if sano["prueba"] is not False:
        fallos.append("en operacion normal, prueba deberia ser false")

    # la marca de prueba: por entorno y por entrada de config
    previo_p = os.environ.get("WA_VIGIA_PRUEBA")
    try:
        casos += 1
        os.environ["WA_VIGIA_PRUEBA"] = "1"
        if estado_vigilado("X", "whatsapp", "j", "e")["prueba"] is not True:
            fallos.append("WA_VIGIA_PRUEBA=1 deberia marcar la corrida")
        casos += 1
        os.environ["WA_VIGIA_PRUEBA"] = "0"
        if estado_vigilado("X", "whatsapp", "j", "e", prueba=True)["prueba"] is not True:
            fallos.append("una entrada de fixture deberia marcarse aunque el "
                          "entorno diga que no")
    finally:
        os.environ.pop("WA_VIGIA_PRUEBA", None)
        if previo_p is not None:
            os.environ["WA_VIGIA_PRUEBA"] = previo_p

    # el id no publica el JID ni el dominio, que son dato de cliente
    casos += 1
    ident = slug_vigilado("Dragon", "whatsapp", "120363413996637804@g.us")
    if "120363413996637804" in ident or "@" in ident:
        fallos.append(f"el id del bloque esta publicando el JID: {ident}")
    casos += 1
    if slug_vigilado("Dragon", "whatsapp", "a@x") == slug_vigilado("Dragon", "correo", "a@x"):
        fallos.append("dos canales del mismo cliente comparten id")

    # ---- el asunto AGRUPA, no repite la etiqueta por hallazgo ---------------
    # Antes salia "sin respuesta en Dragon (correo), Dragon (correo), Dragon
    # (correo), Dragon (correo)": cuatro correos del mismo remitente, cuatro
    # repeticiones y un asunto que no decia nada.
    cuatro = [{"quien": "Dragon (correo)", "cliente": "Dragon",
               "canal": "correo", "minutos": 300 + i, "desde": "x",
               "texto": "t"} for i in range(4)]
    casos += 1
    a_cuatro = asunto_aviso(cuatro, [])
    if a_cuatro != "Octorato: sin respuesta en Dragon (4 correos)":
        fallos.append(f"el asunto no agrupo los hallazgos: {a_cuatro!r}")
    casos += 1
    if a_cuatro.count("Dragon") != 1:
        fallos.append(f"el asunto repite el cliente: {a_cuatro!r}")
    casos += 1
    mixto = cuatro + [{"quien": "grupo del despacho", "cliente": "Despacho",
                       "canal": "whatsapp", "minutos": 44, "desde": "x",
                       "texto": "t"}]
    a_mixto = asunto_aviso(mixto, [])
    if a_mixto != "Octorato: sin respuesta en Dragon (4 correos), Despacho (1 chat)":
        fallos.append(f"el asunto agrupado salio mal: {a_mixto!r}")
    casos += 1
    # un cliente con los dos canales sale una sola vez, con los dos conteos
    dos = cuatro[:2] + [{"quien": "Dragon", "cliente": "Dragon",
                         "canal": "whatsapp", "minutos": 44, "desde": "x",
                         "texto": "t"}]
    a_dos = asunto_aviso(dos, [])
    if a_dos != "Octorato: sin respuesta en Dragon (2 correos, 1 chat)":
        fallos.append(f"un cliente con dos canales salio mal: {a_dos!r}")
    casos += 1
    # y el asunto cabe en SNS, que corta en 99
    if len(asunto_aviso(mixto, [])) > 99:
        fallos.append("el asunto agrupado no cabe en el limite de SNS")
    # el pulso no puede contradecir a su propio bloque: si un silencio ya
    # avisado sigue abierto, el asunto NO puede decir "ningun silencio"
    casos += 1
    a_pulso = asunto_aviso([], [], est_demo)
    if "ningun silencio" in a_pulso or "Dragon" not in a_pulso:
        fallos.append(f"el pulso se contradice con su bloque: {a_pulso!r}")
    casos += 1
    sanos_solo = [e for e in est_demo if e["silencio_min"] is None]
    a_limpio = asunto_aviso([], [], sanos_solo)
    if "ningun silencio abierto" not in a_limpio:
        fallos.append(f"con todo sano el pulso deberia decirlo: {a_limpio!r}")
    casos += 1
    if len(a_pulso) > 99 or len(a_limpio) > 99:
        fallos.append("el asunto del pulso no cabe en el limite de SNS")
    casos += 1
    c_pulso = cuerpo_aviso([], [], "maquina", est_demo, ahora)
    if "NUEVOS" not in c_pulso:
        fallos.append(f"el cuerpo del pulso no distingue nuevo de abierto: {c_pulso!r}")

    # ---- degradacion: un sensor caido AVISA aunque no haya ni un silencio ---
    # Este es el modo que dejaba el punto ciego: sin silencios el vigia salia
    # con 0 y la unica huella quedaba en el journal.
    casos += 1
    if id_degradacion([]) is not None:
        fallos.append("sin fallas no deberia haber aviso de degradacion")
    casos += 1
    if id_degradacion([{"texto": "no configurado", "falla": False}]) is not None:
        fallos.append("un hueco que no es falla no deberia sacar aviso")
    casos += 1
    if id_degradacion(hueco, ahora) is None:
        fallos.append("una falla deberia sacar su propio aviso")

    # el mismo fallo dos veces = el MISMO id, o el vigia grita cada 5 min
    casos += 1
    if id_degradacion(hueco, ahora) != id_degradacion(list(hueco), ahora):
        fallos.append("el id de degradacion no es estable entre corridas")
    # y los digitos que cambian entre corridas no pueden mover el id
    casos += 1
    a = id_degradacion([{"texto": "no pude revisar x (id 123)", "falla": True}], ahora)
    b = id_degradacion([{"texto": "no pude revisar x (id 987)", "falla": True}], ahora)
    if a != b:
        fallos.append("un numero que cambia convierte el aviso en ruido cada vuelta")
    # un fallo DISTINTO si es un aviso distinto
    casos += 1
    otro = [{"texto": "Google rechazo el refresh_token", "falla": True}]
    if id_degradacion(hueco, ahora) == id_degradacion(otro, ahora):
        fallos.append("dos fallas distintas comparten id y una se pierde")
    # manana vuelve a gritar: un sensor roto no puede avisarse una sola vez
    casos += 1
    if id_degradacion(hueco, ahora) == id_degradacion(hueco, ahora + timedelta(days=1)):
        fallos.append("un sensor roto deberia volver a avisar al dia siguiente")

    # el aviso SIN silencios tiene que decir que esta degradado, no verse limpio
    casos += 1
    cuerpo = cuerpo_aviso([], hueco, "maquina")
    if "NO pudo mirar todo" not in cuerpo or "REDUCIDA" not in cuerpo:
        fallos.append(f"el aviso de degradacion se ve limpio: {cuerpo!r}")
    casos += 1
    if "DEGRADADO" not in asunto_aviso([], hueco):
        fallos.append("el asunto no dice que el vigia esta degradado")
    casos += 1
    if "chat X" not in asunto_aviso(uno, []):
        fallos.append("con silencios el asunto deberia nombrarlos")

    # ---- canal. Un typo NO puede caer en silencio al default. --------------
    previo = os.environ.get("WA_VIGIA_CANAL")
    try:
        for valor, debia_reventar in ((None, False), ("gmail", False),
                                      ("canario", False), ("CANARIO", False),
                                      ("whatsapp", False),
                                      ("canaro", True), ("", True)):
            casos += 1
            if valor is None:
                os.environ.pop("WA_VIGIA_CANAL", None)
            else:
                os.environ["WA_VIGIA_CANAL"] = valor
            try:
                canal_activo()
                reventado = False
            except SystemExit:
                reventado = True
            if reventado != debia_reventar:
                fallos.append(
                    f"canal {valor!r}: {'debia reventar y paso' if debia_reventar else 'no debia reventar y reventado'}")
    finally:
        os.environ.pop("WA_VIGIA_CANAL", None)
        if previo is not None:
            os.environ["WA_VIGIA_CANAL"] = previo

    # ---- publicacion. Sin red: se inyecta el corredor del subproceso. -------
    class Resp:
        def __init__(self, rc, out="", err=""):
            self.returncode, self.stdout, self.stderr = rc, out, err

    visto_cmd = {}

    def corredor_ok(cmd):
        visto_cmd["cmd"] = cmd
        return Resp(0, "abc-123\n")

    casos += 1
    cfg_c = {"vigilancia": {"canario": {
        "tema": "arn:aws:sns:mx-central-1:000000000000:tema-de-prueba"}}}
    mid = avisa_canario(cfg_c, [{"quien": "chat X", "minutos": 44,
                                 "desde": "2026-01-01T00:00:00+00:00",
                                 "texto": "hola"}], [], "maquina", corredor_ok)
    if mid != "abc-123":
        fallos.append(f"la publicacion no devolvio el MessageId: {mid!r}")

    # la region tiene que salir del ARN, no de una constante
    casos += 1
    cmd = visto_cmd.get("cmd") or []
    if "--region" not in cmd or cmd[cmd.index("--region") + 1] != "mx-central-1":
        fallos.append(f"la region no salio del ARN: {cmd}")

    # un ARN roto se rechaza antes de gastar una llamada
    casos += 1
    try:
        publica_sns("esto-no-es-un-arn", "a", "b", corredor_ok)
        fallos.append("un ARN roto deberia reventar y paso")
    except RuntimeError:
        pass

    # si aws falla, la publicacion NO puede verse exitosa
    casos += 1
    try:
        publica_sns("arn:aws:sns:mx-central-1:000000000000:t", "a", "b",
                    lambda c: Resp(255, "", "AccessDenied"))
        fallos.append("un aws que falla deberia reventar y paso")
    except RuntimeError:
        pass

    # sin tema en la config, el canal canario no puede fingir que aviso
    casos += 1
    try:
        avisa_canario({"vigilancia": {}}, [], [], "maquina", corredor_ok)
        fallos.append("sin tema de SNS deberia reventar y paso")
    except RuntimeError:
        pass

    # ---- whatsapp. Sin red: se inyecta el poster. El numero sale de la config
    # o del entorno, NUNCA del script. Sin destino, revienta.
    prev_wa_dest = os.environ.pop("WA_VIGIA_WA_DEST", None)
    try:
        visto_wa = {}

        def poster_ok(endpoint, cuerpo):
            visto_wa["endpoint"] = endpoint
            visto_wa["cuerpo"] = json.loads(cuerpo.decode())
            return '{"success":true,"message_id":"WA1"}'

        casos += 1
        cfg_wa = {"vigilancia": {"whatsapp": {"destino": "5210000000000"}}}
        avisa_whatsapp(cfg_wa, [{"quien": "chat X", "minutos": 44,
                                 "desde": "2026-01-01T00:00:00+00:00",
                                 "texto": "hola"}], [], poster=poster_ok)
        if visto_wa.get("cuerpo", {}).get("recipient") != "5210000000000":
            fallos.append(f"el aviso WA no fue al destino de la config: {visto_wa}")

        casos += 1
        if "chat X" not in (visto_wa.get("cuerpo", {}).get("message") or ""):
            fallos.append(f"el aviso WA no nombra el silencio: {visto_wa}")

        # sin destino (ni env ni config), el canal whatsapp NO puede fingir que
        # aviso: revienta, no le pega a un numero cualquiera.
        casos += 1
        try:
            avisa_whatsapp({"vigilancia": {}}, [], [], poster=poster_ok)
            fallos.append("sin destino WA deberia reventar y paso")
        except SystemExit:
            pass
    finally:
        if prev_wa_dest is not None:
            os.environ["WA_VIGIA_WA_DEST"] = prev_wa_dest

    # ---- fuente de la credencial. Sin red: se inyectan corredor y lector. ---
    # La laptop lee archivos y la instancia lee Secrets Manager, con el MISMO
    # archivo. Lo que se prueba aqui es que elegir mal no pase en silencio y
    # que el secreto no acabe nunca en disco ni en la linea de comando.
    previo_f = os.environ.get("WA_VIGIA_GMAIL")
    try:
        for valor, debia_reventar in ((None, False), ("archivos", False),
                                      ("secretsmanager", False),
                                      ("SecretsManager", False),
                                      ("secretmanager", True), ("", True)):
            casos += 1
            if valor is None:
                os.environ.pop("WA_VIGIA_GMAIL", None)
            else:
                os.environ["WA_VIGIA_GMAIL"] = valor
            try:
                fuente_gmail()
                reventado = False
            except SystemExit:
                reventado = True
            if reventado != debia_reventar:
                fallos.append(
                    f"fuente {valor!r}: {'debia reventar y paso' if debia_reventar else 'no debia reventar y reventado'}")
    finally:
        os.environ.pop("WA_VIGIA_GMAIL", None)
        if previo_f is not None:
            os.environ["WA_VIGIA_GMAIL"] = previo_f

    visto_sec = {}

    def corredor_secreto(cmd):
        visto_sec["cmd"] = cmd
        return Resp(0, '{"refresh_token": "no-real"}')

    casos += 1
    if secreto_aws("un/secreto", "mx-central-1", corredor_secreto).get(
            "refresh_token") != "no-real":
        fallos.append("secreto_aws no devolvio el JSON del secreto")
    casos += 1
    cmd = visto_sec.get("cmd") or []
    if "--region" not in cmd or cmd[cmd.index("--region") + 1] != "mx-central-1":
        fallos.append(f"secreto_aws no respeto la region pedida: {cmd}")
    casos += 1
    if "--secret-id" not in cmd or cmd[cmd.index("--secret-id") + 1] != "un/secreto":
        fallos.append(f"secreto_aws pidio otro secreto: {cmd}")

    # un secreto que no existe NO puede verse como una credencial vacia
    casos += 1
    try:
        secreto_aws("no/existe", "mx-central-1",
                    lambda c: Resp(254, "", "ResourceNotFoundException: "
                                           "Secrets Manager can't find the specified secret."))
        fallos.append("un secreto inexistente deberia reventar y paso")
    except RuntimeError as e:
        if "ResourceNotFound" not in str(e):
            fallos.append(f"el error de AWS se perdio por el camino: {e}")

    # con secretos en la config, el disco NO se toca
    casos += 1
    pedidos = []

    def lector_falso(nombre, region):
        pedidos.append(nombre)
        return ({"refresh_token": "r"} if nombre.endswith("credentials")
                else {"installed": {"client_id": "i", "client_secret": "s"}})

    secretos = {"region": "mx-central-1", "credenciales": "octo/credentials",
                "claves": "octo/keys"}
    cred, keys = credenciales_gmail(secretos, lector_falso)
    if pedidos != ["octo/credentials", "octo/keys"] or "refresh_token" not in cred:
        fallos.append(f"credenciales_gmail no leyo de Secrets Manager: {pedidos}")

    # WA_VIGIA_GMAIL=secretsmanager sin bloque en la config: SALTA y lo grita.
    # Callar aqui seria el mismo punto ciego con otro disfraz.
    casos += 1
    cob = []
    r = revisa_correo(cfg_correo, ahora, None, cob, "secretsmanager")
    if r != [] or not any("secretos" in c["texto"] and c["falla"] for c in cob):
        fallos.append(f"sin bloque de secretos deberia saltar y avisarlo: {cob}")

    # Google rechaza el refresh_token: el motivo tiene que llegar al aviso.
    casos += 1

    def urlopen_rechaza(url, data=None, timeout=None):
        raise urllib.error.HTTPError(
            "https://oauth2.googleapis.com/token", 400, "Bad Request", {},
            io.BytesIO(b'{"error":"invalid_grant","error_description":'
                       b'"Token has been expired or revoked."}'))

    real_urlopen = urllib.request.urlopen
    urllib.request.urlopen = urlopen_rechaza
    try:
        try:
            token_gmail(secretos, lector_falso)
            fallos.append("un refresh_token rechazado deberia reventar y paso")
        except RuntimeError as e:
            if "invalid_grant" not in str(e):
                fallos.append(f"el rechazo de Google no dijo por que: {e}")
        # y ese rechazo tiene que salir como COBERTURA, no tumbar la revision.
        # Se cambia el lector global para no salir a AWS de verdad: un
        # selftest que llama a la nube deja de ser una prueba y pasa a ser una
        # corrida que depende de credenciales.
        real_secreto = secreto_aws
        cfg_sec = {"vigilancia": {"correo": {
            "umbral_minutos": 240, "dias": 3, "secretos": secretos,
            "remitentes": [{"de": "cliente.example", "quien": "Cliente"}]}}}
        try:
            secreto_aws = lector_falso
            casos += 1
            cob = []
            try:
                r = revisa_correo(cfg_sec, ahora, None, cob, "secretsmanager")
            except Exception as e:
                r, cob = ["revento"], []
                fallos.append(f"un rechazo de Google tumbo la revision: {e}")
            if r != [] or not any("invalid_grant" in c["texto"] and c["falla"]
                                  for c in cob):
                fallos.append(f"el rechazo de Google no viajo en la cobertura: {cob}")

            # el ROJO de verdad: el secreto no existe. Tiene que salir en la
            # cobertura como falla, no como "no hay correo pendiente".
            casos += 1
            def secreto_ausente(nombre, region):
                raise RuntimeError("ResourceNotFoundException: Secrets Manager "
                                   "can't find the specified secret.")
            secreto_aws = secreto_ausente
            cob = []
            r = revisa_correo(cfg_sec, ahora, None, cob, "secretsmanager")
            if r != [] or not any("ResourceNotFound" in c["texto"] and c["falla"]
                                  for c in cob):
                fallos.append(f"un secreto inexistente no viajo en la cobertura: {cob}")
            casos += 1
            if id_degradacion(cob) is None:
                fallos.append("un secreto inexistente deberia sacar aviso solo")
        finally:
            secreto_aws = real_secreto
    finally:
        urllib.request.urlopen = real_urlopen

    # ---- estado: solo se marca lo que YA se aviso ---------------------------
    guardado = ESTADO
    try:
        with tempfile.TemporaryDirectory() as tmp:
            ESTADO = Path(tmp) / "estado.json"
            casos += 1
            if sin_avisar(["x1", "x2"]) != ["x1", "x2"]:
                fallos.append("con estado vacio todo deberia estar sin avisar")
            casos += 1
            marca_avisados(["x1"])
            if sin_avisar(["x1", "x2"]) != ["x2"]:
                fallos.append("marca_avisados no filtro lo ya avisado")
            casos += 1
            # el modo que costo la alerta: mirar sin marcar NO puede consumirla
            if sin_avisar(["x2"]) != ["x2"]:
                fallos.append("mirar sin marcar se comio el aviso pendiente")

            # ---- el pulso: el estado completo se republica cada tanto -------
            # Sin pulso, el tablero solo tiene dato cuando algo falla y nunca
            # puede pintar un verde fresco.
            casos += 1
            if not toca_pulso(ahora):
                fallos.append("sin pulso previo, el primero deberia salir")
            casos += 1
            marca_pulso(ahora)
            if toca_pulso(ahora):
                fallos.append("el pulso salio dos veces seguidas: seria ruido "
                              "cada 5 minutos")
            casos += 1
            if not toca_pulso(ahora + timedelta(minutes=PULSO_MIN)):
                fallos.append("pasado el intervalo, el pulso deberia volver")
            casos += 1
            # marcar el pulso NO puede borrar lo ya avisado, o el vigia repite
            # cada silencio viejo en la siguiente vuelta
            if sin_avisar(["x1", "x2"]) != ["x2"]:
                fallos.append("marcar el pulso se comio la memoria de avisados")
            casos += 1
            # el formato viejo del archivo (una lista pelada) se sigue leyendo
            ESTADO.write_text(json.dumps(["v1", "v2"]))
            if sin_avisar(["v1", "v3"]) != ["v3"]:
                fallos.append("el estado en formato viejo dejo de leerse y el "
                              "vigia va a repetir todo")
    finally:
        ESTADO = guardado

    for f in fallos:
        print("  FALLA:", f)
    print(f"selftest: {casos - len(fallos)}/{casos}"
          + (" OK" if not fallos else f"  ({len(fallos)} fallo(s))"))
    return 1 if fallos else 0


# --------------------------------------------------------------- whatsapp ---
# Tercer canal (14-ago): avisar por WhatsApp al numero del operador via el
# puente de soporte (REST local del server). El destino NO vive aqui: este
# script es publico, asi que sale de la config privada (vigilancia.whatsapp.
# destino) o del entorno (WA_VIGIA_WA_DEST). Sin destino, revienta; no se
# inventa un numero, que seria el peor modo de fallo (avisar a quien no es).
def _post_json(endpoint, cuerpo):
    import urllib.request
    req = urllib.request.Request(
        endpoint, data=cuerpo, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode()


def cuerpo_whatsapp(silencios, cobertura, estados=None, ahora=None):
    """Aviso corto para WhatsApp: el asunto y una linea por silencio nuevo.

    Reusa `asunto_aviso` para no tener dos definiciones del encabezado, y agrega
    los sensores caidos, porque un sensor muerto ES la noticia."""
    lineas = [asunto_aviso(silencios, cobertura, estados)]
    for s in silencios:
        linea = f"- {s['quien']}: {s['minutos']} min sin respuesta."
        if s.get("texto"):
            linea += f" {s['texto']}"
        lineas.append(linea)
    for c in (cobertura or []):
        if c.get("falla"):
            lineas.append(f"- sensor caido: {c['texto']}")
    return "\n".join(lineas)


def avisa_whatsapp(cfg, silencios, cobertura, estados=None, ahora=None,
                   poster=None):
    """Manda el aviso por WhatsApp al numero del operador. Devuelve la respuesta
    cruda del puente. `poster` se inyecta en las pruebas para no tocar la red.

    El destino NUNCA se codifica aqui: sale de WA_VIGIA_WA_DEST o de
    vigilancia.whatsapp.destino en la config privada. Sin destino, SystemExit,
    igual que un canal invalido: fallar fuerte, nunca avisar a un numero de mas."""
    vig = (cfg.get("vigilancia") or {}).get("whatsapp") or {}
    destino = os.environ.get("WA_VIGIA_WA_DEST") or vig.get("destino")
    if not destino:
        raise SystemExit(
            "falta el destino del aviso por WhatsApp: pon vigilancia.whatsapp."
            "destino en la config, o WA_VIGIA_WA_DEST en el entorno")
    endpoint = os.environ.get("WA_VIGIA_WA_ENDPOINT",
                              "http://127.0.0.1:8081/api/send")
    cuerpo = json.dumps(
        {"recipient": str(destino),
         "message": cuerpo_whatsapp(silencios, cobertura, estados, ahora)}
    ).encode()
    return (poster or _post_json)(endpoint, cuerpo)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--selftest", action="store_true")
    p.add_argument("--seco", action="store_true",
                   help="calcula e imprime el aviso, sin publicar ni marcar")
    a = p.parse_args()
    if a.selftest:
        sys.exit(selftest())

    canal = canal_activo()
    cfg = json.loads(CONFIG.read_text())
    ahora = datetime.now(timezone.utc)
    cobertura, estados = [], []
    silencios = (revisa(cfg, ahora, estados, cobertura)
                 + revisa_correo(cfg, ahora, cobertura=cobertura,
                                 estados=estados))
    for c in cobertura:
        print(f"COBERTURA: {c['texto']}")

    if a.seco:
        # Ni publica ni marca nada: sirve para ver el aviso exacto que saldria,
        # incluido el bloque, sin gastar una alerta real ni consumir el
        # anti-repeticion.
        host = os.uname().nodename
        print("ASUNTO: " + asunto_aviso(silencios, cobertura, estados))
        print(cuerpo_aviso(silencios, cobertura, host, estados, ahora))
        sys.exit(0)

    # Un sensor caido entra a la misma cola que un silencio, con su propio id.
    # Asi la degradacion sale por el mismo canal, con la misma anti-repeticion,
    # y NO depende de que ademas haya un silencio de WhatsApp para enterarse.
    ids = [s["id"] for s in silencios]
    id_falla = id_degradacion(cobertura)
    if id_falla:
        ids.append(id_falla)
    nuevos = sin_avisar(ids)

    for s in silencios:
        marca = "AVISO" if s["id"] in nuevos else "(ya avisado)"
        print(f"{marca}  {s['quien']}: lleva {s['minutos']} min sin respuesta "
              f"desde {s['desde']}  ->  {s['texto']}")

    # Solo se avisa por algo NUEVO, para no repetir el mismo aviso cada vuelta
    # del temporizador. La excepcion es el PULSO: cada cierto rato el estado
    # completo se republica aunque no haya novedad, porque un tablero sin dato
    # fresco no puede pintar verde. Solo en `canario`: en `gmail` avisar es
    # salir con error y eso mandaria un correo cada media hora.
    pulso = canal == "canario" and toca_pulso(ahora)
    if not nuevos and not pulso:
        if not silencios:
            print("sin silencios pendientes")
        sys.exit(0)

    if canal == "gmail":
        # El correo lo manda systemd por OnFailure. Salir con error ES el aviso.
        marca_avisados(nuevos)
        sys.exit(1)

    frescos = [s for s in silencios if s["id"] in nuevos]

    if canal == "whatsapp":
        try:
            avisa_whatsapp(cfg, frescos, cobertura, estados=estados,
                           ahora=ahora)
        except Exception as e:
            # Sin marcar: el silencio se reintenta la proxima vuelta. Sale con
            # error para que OnFailure levante el respaldo, la misma boca por
            # otro camino, igual que canario.
            print(f"FALLO el aviso por WhatsApp: {e}", file=sys.stderr)
            sys.exit(1)
        marca_avisados(nuevos)
        print(f"aviso enviado por WhatsApp, {len(frescos)} silencio(s) nuevo(s)")
        sys.exit(0)

    try:
        mid = avisa_canario(cfg, frescos, cobertura, estados=estados,
                            ahora=ahora)
    except Exception as e:
        # Sin marcar: el silencio se reintenta en la siguiente vuelta. Y se sale
        # con error para que OnFailure levante el respaldo, que es la misma
        # boca por otro camino.
        print(f"FALLO el aviso al canario: {e}", file=sys.stderr)
        sys.exit(1)
    marca_avisados(nuevos)
    if pulso:
        marca_pulso(ahora)
    print(f"aviso publicado al canario (MessageId {mid}), "
          f"{len(estados)} vigilado(s) en el bloque")
    sys.exit(0)


if __name__ == "__main__":
    main()
