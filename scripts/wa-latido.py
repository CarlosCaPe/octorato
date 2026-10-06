#!/usr/bin/env python3
"""Active heartbeat for WhatsApp bridges: it measures the PIPE, not the process.

WHY IT EXISTS. A bridge can be down for days without anyone noticing, because
the two obvious probes lie:

  1. "the process exists" (pgrep). A bridge can be alive, authenticated and with
     an open socket, and go hours without persisting a single message.
  2. "the database was written recently" (mtime). It does not tell BROKEN from
     QUIET. On a low-traffic channel, hours without a write can be legitimate
     silence or a jam, and the probe cannot say which.

The probe that does not lie is ACTIVE: send a message and check that it lands.
It is the difference between asking "are you breathing?" and holding a mirror to
the mouth.

HONEST SCOPE. It exercises the OUTBOUND path (API -> whatsmeow -> server ack ->
SQLite write). It does NOT exercise the INBOUND one, which is a different
handler of the same binary. A bridge that sends but has reception stuck would
pass green. It is far more than pgrep and less than "the whole pipe".

WHERE THE BRIDGE LIVES. A bridge can run on this machine or on a server. If its
config carries the `remoto` key, ALL the probes (process, link, landing) and the
cure go against that server over SSM, and starting the local binary is
FORBIDDEN. On 2026-08-18 this distinction did not exist: the support bridge
already lived on the EC2, the landing probe read the local replica (which
refreshes every 5 min, so a stamp from 40 seconds ago could never show up), and
the cure started the binary here. Result: a guaranteed FAIL every 10 minutes and
a second WhatsApp session cloned on every pass.

REJECTED CLIENT. WhatsApp retires old client versions: the bridge then logs
"Client outdated (405)" once and never reconnects, while its process stays up
and its account stays linked. A bridge with no own number (no send probe) read
"link OK" for hours in that state. So every bridge whose systemd unit is known
is also read for its CURRENT run (its InvocationID): if the last line that is a
405 or a successful login is a 405, the bridge is down, and a restart does not
cure it (the same binary is rejected again); it needs a rebuild.

AUTO-UPDATE NOTICES. A remote bridge may run an auto-update on its host that
rebuilds it after a 405 and records each attempt in a state file there. The
host can only notify over WhatsApp, which is what is down when it acts, so this
script reads that state file and hands each new result to a local notifier.

CONFIGURATION. The channel data (numbers, paths) lives in
company/config/wa-puentes.json, which is gitignored. This script is public and
must not contain any client identifier. Optional keys used here: `unidad` (the
systemd --user unit of a local bridge), and under `remoto`, `autoupdate` with
`estado` (path of the state file on the host) and `aviso` (the notifier argv,
where "{reason}" and "{detail}" are replaced).

Usage:
    wa-latido.py                 check, and cure if needed
    wa-latido.py --sin-curar     diagnose only
    wa-latido.py --selftest      self-test with fixtures
"""
import argparse
import fcntl
import json
import os
import secrets
import shlex
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request
from datetime import datetime

CONFIG = os.path.expanduser("~/.claude/company/config/wa-puentes.json")
ESTADO = os.path.expanduser("~/.cache/wa-latido.json")
AVISOS_VISTOS = os.path.expanduser("~/.cache/wa-latido-autoupdate.json")
LOCK = os.path.expanduser("~/.cache/wa-latido.lock")

ESPERA_MAX_S = 40      # se sondea hasta aqui, no se duerme a ciegas
SONDEO_S = 2
HTTP_TIMEOUT = 10
SSM_ESPERA_S = 60      # un comando de sonda no tarda mas que esto
SSM_SONDEO_S = 2

# Gancho de inyeccion para el selftest: una funcion (cfg, comando) -> str que
# sustituye a AWS. En produccion vale None y manda el SSM de verdad.
EJECUTOR_SSM = None
# Same idea for a LOCAL bridge's journal: a function (cfg) -> str returning the
# current run's log, newest first. None in production.
EJECUTOR_JOURNAL = None

REJECTED = "Client outdated (405)"
LOGGED_IN = "Successfully authenticated"
# An in_progress auto-update older than this is reported as stuck.
AUTOUPDATE_ATORADO_S = 1800
# Results older than this are not announced on a first run (no seen file yet).
AUTOUPDATE_VIGENCIA_S = 86400


class SondaRota(Exception):
    """La sonda no pudo medir. NO es lo mismo que 'el puente esta caido':
    curar aqui seria reiniciar un puente sano cada 10 minutos, para siempre."""


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def ssm(cfg, comando):
    """Corre un comando en la instancia remota y devuelve su salida estandar.

    Cualquier fallo de AWS (credencial expirada, SSM sin responder, instancia
    inalcanzable) es SondaRota y NO "el puente esta caido". La diferencia no es
    cosmetica: confundirlas reinicia un puente sano cada 10 minutos porque la
    laptop perdio la sesion de AWS.
    """
    if EJECUTOR_SSM is not None:
        return EJECUTOR_SSM(cfg, comando)
    r = cfg["remoto"]
    base = ["aws", "ssm", "--profile", r["perfil"], "--region", r["region"]]
    try:
        env = subprocess.run(
            base + ["send-command", "--instance-ids", r["instancia"],
                    "--document-name", "AWS-RunShellScript",
                    "--parameters", json.dumps({"commands": [comando]}),
                    "--query", "Command.CommandId", "--output", "text"],
            capture_output=True, text=True, timeout=SSM_ESPERA_S)
    except (OSError, subprocess.SubprocessError) as e:
        raise SondaRota(f"no pude invocar aws: {type(e).__name__}: {e}") from e
    if env.returncode != 0:
        raise SondaRota(f"send-command fallo: {env.stderr.strip()[:160]}")
    cid = env.stdout.strip()

    limite = time.time() + SSM_ESPERA_S
    consulta = base + ["get-command-invocation", "--command-id", cid,
                       "--instance-id", r["instancia"]]
    while time.time() < limite:
        q = subprocess.run(consulta + ["--query", "Status", "--output", "text"],
                           capture_output=True, text=True)
        estado = q.stdout.strip()
        if estado in ("Success", "Failed", "Cancelled", "TimedOut"):
            break
        time.sleep(SSM_SONDEO_S)
    else:
        raise SondaRota(f"el comando remoto no termino en {SSM_ESPERA_S}s")
    if estado != "Success":
        err = subprocess.run(
            consulta + ["--query", "StandardErrorContent", "--output", "text"],
            capture_output=True, text=True).stdout.strip()[:160]
        raise SondaRota(f"el comando remoto termino en {estado}: {err}")
    out = subprocess.run(
        consulta + ["--query", "StandardOutputContent", "--output", "text"],
        capture_output=True, text=True)
    return out.stdout


def sqlite_remoto(cfg, ruta, consulta):
    """Un COUNT(*) contra una base del servidor. Devuelve el entero."""
    salida = ssm(cfg, f"sqlite3 -readonly {shlex.quote(ruta)} "
                      f"{shlex.quote(consulta)}")
    for linea in reversed(salida.strip().splitlines()):
        linea = linea.strip()
        if linea.isdigit():
            return int(linea)
    raise SondaRota(f"salida ilegible de sqlite3: {salida.strip()[:80]!r}")


def reloj_del_store(cfg):
    """El corte temporal tiene que venir del reloj de QUIEN ESCRIBE la base.

    whatsmeow guarda la hora local del host del puente. Con el puente en la
    laptop eso coincidia con datetime.now() y nadie lo noto en 4 meses. Con el
    puente en un servidor en UTC ya no: el 18-ago-2026 el corte se calculo en
    hora de Madrid (15:43:24) y el sello aterrizado un segundo despues quedo
    guardado como 13:43:25 UTC, asi que la comparacion de texto lo descarto. El
    latido reportaba FAIL con la tuberia perfecta, y ese falso rojo es lo que
    dispara curas que nadie necesita.
    """
    if cfg.get("remoto"):
        salida = ssm(cfg, "date +'%Y-%m-%d %H:%M:%S'")
        for linea in reversed(salida.strip().splitlines()):
            linea = linea.strip()
            if len(linea) == 19 and linea[4] == "-" and linea[13] == ":":
                return linea
        raise SondaRota(f"no pude leer el reloj del servidor: "
                        f"{salida.strip()[:80]!r}")
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def es_fallo_de_tunel(cfg, detalle):
    """Un puente remoto se alcanza por un tunel local. Si el 127.0.0.1 no
    contesta, el roto es el TUNEL, no el puente: reiniciar el puente por esto
    seria curar la maquina sana y dejar la enferma igual."""
    if not cfg.get("remoto"):
        return False
    pistas = ("Connection refused", "ConnectionRefusedError", "URLError",
              "timed out", "TimeoutError", "RemoteDisconnected")
    return any(x in detalle for x in pistas)


def cura_tunel(cfg):
    """Reinicia la unidad local del tunel. Es local a proposito: el tunel SI
    vive aqui, y esto no puede clonar ninguna sesion de WhatsApp."""
    unidad = cfg["remoto"].get("tunel")
    if not unidad:
        log("el puente remoto no declara tunel en la config, no hay que curar")
        return False
    r = subprocess.run(["systemctl", "--user", "restart", unidad],
                       capture_output=True, text=True)
    if r.returncode != 0:
        log(f"no pude reiniciar {unidad} -> {r.stderr.strip()[:160]}")
        return False
    time.sleep(8)      # que el port-forward vuelva a escuchar
    return True


def carga():
    if not os.path.exists(CONFIG):
        raise SondaRota(f"falta {CONFIG}")
    with open(CONFIG) as f:
        cfgs = json.load(f)["puentes"]
    for c in cfgs.values():
        for k in ("dir", "db"):
            c[k] = os.path.expanduser(c[k])
    return cfgs


def pids(cfg):
    """PIDs del puente, verificados contra el ejecutable real.

    `pgrep -f 'nombre$'` NO sirve: compara la linea de comando completa, asi que
    un `tail -f /ruta/whatsapp-bridge` cuenta como puente vivo. Sobre eso se
    puede terminar mandando SIGKILL al editor de alguien, y ademas un puente
    muerto se reporta sano. Aqui se exige que /proc/<pid>/exe apunte al binario.
    """
    if cfg.get("remoto"):
        # En un puente remoto no hay proceso local que contar, y contarlo seria
        # justo el error: el unico proceso local posible es un clon.
        salida = ssm(cfg, f"systemctl show {shlex.quote(cfg['remoto']['unidad'])} "
                          "-p MainPID -p ActiveState")
        d = dict(l.split("=", 1) for l in salida.strip().splitlines() if "=" in l)
        pid = d.get("MainPID", "0").strip()
        activo = d.get("ActiveState", "").strip() == "active"
        return [pid] if activo and pid not in ("", "0") else []

    esperado = os.path.realpath(os.path.join(cfg["dir"], cfg["bin"]))
    # -f y no -x: Linux trunca /proc/<pid>/comm a 15 caracteres, asi que
    # `pgrep -x whatsapp-support-bridge` (23 chars) NO matchea JAMAS. El binario
    # aparece como 'whatsapp-suppor'. Con -x la funcion devolvia vacio siempre,
    # o sea que un puente vivo se reportaba muerto y reinicia() nunca mataba
    # nada, solo apilaba instancias. Se busca permisivo por linea de comando y
    # se filtra estricto por /proc/<pid>/exe, que es el guardia de verdad.
    r = subprocess.run(["pgrep", "-u", str(os.getuid()), "-f", cfg["bin"]],
                       capture_output=True, text=True)
    fuera = []
    for p in r.stdout.split():
        try:
            if os.path.realpath(f"/proc/{p}/exe") == esperado:
                fuera.append(p)
        except OSError:
            pass          # el proceso murio entre el pgrep y el readlink
    return fuera


def vinculado(cfg):
    """El proceso puede estar vivo y la CUENTA desvinculada.

    whatsmeow guarda la sesion en whatsapp.db, junto a messages.db. Si el
    telefono cierra la sesion (o se cambia de numero), esa tabla queda VACIA:
    el puente sigue escuchando en su puerto y contestando, pero no manda ni
    recibe nada. La sonda de proceso lo reporta sano, y en un puente sin numero
    propio la sonda de tuberia ni siquiera corre. Ese es el agujero por el que
    se pierden dias sin que nada avise.

    Devuelve (estado, detalle). estado None = no se pudo comprobar, que NO es lo
    mismo que desvinculado; por eso no se colapsan en un bool.
    """
    if cfg.get("remoto"):
        # La sesion que importa es la del servidor. El whatsapp.db local es la
        # sesion decomisionada del cutover: leerlo reporta enlazado un puente
        # que aqui ya no existe.
        try:
            n = sqlite_remoto(cfg, cfg["remoto"]["sesion"],
                              "SELECT COUNT(*) FROM whatsmeow_device")
        except SondaRota as e:
            return None, str(e)
        return n > 0, f"{n} dispositivo(s) enlazado(s) en el servidor"

    ruta = os.path.join(os.path.dirname(cfg["db"]), "whatsapp.db")
    if not os.path.exists(ruta):
        return None, f"no existe {ruta}"
    try:
        con = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True, timeout=5)
        try:
            n = con.execute("SELECT COUNT(*) FROM whatsmeow_device").fetchone()[0]
        finally:
            con.close()
    except sqlite3.DatabaseError as e:
        return None, f"sqlite: {e}"
    return n > 0, f"{n} dispositivo(s) enlazado(s)"


def _corrida_actual(cfg):
    """The current run of the bridge's systemd unit, newest line first, or None
    when the unit is not known. Raises SondaRota when it cannot be read."""
    if cfg.get("remoto"):
        unidad = shlex.quote(cfg["remoto"]["unidad"])
        return ssm(cfg, f"inv=$(systemctl show {unidad} -p InvocationID --value); "
                        f"[ -n \"$inv\" ] && journalctl _SYSTEMD_INVOCATION_ID=$inv "
                        f"-r -o cat --no-pager | grep -m 1 -F -e "
                        f"{shlex.quote(REJECTED)} -e {shlex.quote(LOGGED_IN)}")
    if not cfg.get("unidad"):
        return None
    if EJECUTOR_JOURNAL is not None:
        return EJECUTOR_JOURNAL(cfg)
    try:
        inv = subprocess.run(["systemctl", "--user", "show", cfg["unidad"], "-p",
                              "InvocationID", "--value"], capture_output=True,
                             text=True, timeout=15).stdout.strip()
        if not inv:
            return ""
        r = subprocess.run(["journalctl", "--user", f"_SYSTEMD_INVOCATION_ID={inv}",
                            "-r", "-o", "cat", "--no-pager"], capture_output=True,
                           text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        raise SondaRota(f"no pude leer el journal de {cfg['unidad']}: {e}") from e
    return r.stdout


def rechazado(cfg):
    """(state, detail). state True: the current run's last 405-or-login line is
    a 405, so WhatsApp rejected this client version. False: it is a login, or
    neither appears yet. None: the unit is not configured or could not be read,
    which is NOT the same as not rejected."""
    try:
        salida = _corrida_actual(cfg)
    except SondaRota as e:
        return None, str(e)
    if salida is None:
        return None, "sin unidad configurada: no se lee el rechazo de version"
    for linea in salida.splitlines():
        if REJECTED in linea:
            return True, "WhatsApp rechaza esta version del cliente (405)"
        if LOGGED_IN in linea:
            return False, "la corrida actual inicio sesion"
    return False, "la corrida actual no ha escrito ni 405 ni inicio de sesion"


def manda(cfg, texto):
    datos = json.dumps({"recipient": cfg["propio"], "message": texto}).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{cfg['puerto']}/api/send", data=datos,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
            cuerpo = r.read().decode()[:200]
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    # 200 no basta: el puente puede responder 200 con success=false, y ese
    # cuerpo trae el motivo exacto. Ignorarlo produce el log mas confuso posible.
    try:
        if json.loads(cuerpo).get("success") is False:
            return False, f"el puente contesto success=false: {cuerpo}"
    except ValueError:
        pass
    return True, cuerpo


def aterrizo(cfg, sello, desde):
    """Lectura de SOLO LECTURA por URI: toma un shared lock y da una vista
    consistente. Copiar el archivo puede capturar una transaccion a medias y
    lanzar DatabaseError, que se leeria como 'no aterrizo' y dispararia una cura
    innecesaria.

    La consulta va ACOTADA a mensajes propios y posteriores al inicio de esta
    corrida. Sin eso, cualquiera que mande un WhatsApp con ese texto marca la
    tuberia como sana.
    """
    if cfg.get("remoto"):
        # Contra el store DEL SERVIDOR, nunca contra el de aqui: el local es una
        # replica de S3 que se refresca cada 5 min, asi que un sello de hace 40
        # segundos no puede estar. Preguntarle a la replica es preguntarle al
        # pasado y leer su "no" como un puente roto.
        return sqlite_remoto(
            cfg, cfg["remoto"]["db"],
            "SELECT COUNT(*) FROM messages WHERE content='%s' "
            "AND is_from_me=1 AND timestamp >= '%s'" % (sello, desde)) > 0

    if not os.path.exists(cfg["db"]):
        raise SondaRota(f"no existe {cfg['db']}")
    try:
        con = sqlite3.connect(f"file:{cfg['db']}?mode=ro", uri=True, timeout=5)
        try:
            n = con.execute(
                "SELECT COUNT(*) FROM messages "
                "WHERE content=? AND is_from_me=1 AND timestamp >= ?",
                (sello, desde)).fetchone()[0]
        finally:
            con.close()
        return n > 0
    except sqlite3.DatabaseError as e:
        raise SondaRota(f"sqlite: {e}") from e


def reinicia(nombre, cfg):
    """Cura el puente donde de verdad vive."""
    if cfg.get("remoto"):
        unidad = cfg["remoto"]["unidad"]
        log(f"{nombre}: el puente vive en el servidor, reinicio {unidad} por SSM")
        ssm(cfg, f"systemctl restart {shlex.quote(unidad)}")
        time.sleep(20)      # autenticar + conectar
        return pids(cfg)
    return reinicia_local(nombre, cfg)


def reinicia_local(nombre, cfg):
    """Arranca el puente FUERA del cgroup de este servicio.

    Con Popen normal el hijo nace dentro de wa-latido.service, que es
    Type=oneshot: al terminar ExecStart systemd derriba el cgroup y se lleva al
    puente recien levantado. `start_new_session` cambia la sesion, NO el cgroup.
    Resultado sin este arreglo: curo, reporto PASS, systemd lo mata, y el ciclo
    se repite cada 10 min con verde en el journal. O sea el fallo silencioso que
    este script viene a matar, reconstruido.

    systemd-run le da su propia unidad transitoria y ahi sobrevive.
    """
    # GUARDIA FAIL-CLOSED. Un puente declarado remoto no se levanta aqui jamas,
    # ni aunque un cambio futuro llegue por otro camino. El 18-ago-2026 esta
    # funcion arranco el binario local de un puente que ya corria en la EC2: se
    # autentico con la misma sesion de WhatsApp en un segundo y el timer lo
    # relanzo cada 10 minutos. Dos clientes en la misma cuenta es lo que
    # desvincula el numero.
    if cfg.get("remoto"):
        raise SondaRota(
            "puente declarado remoto: prohibido levantar el binario local")

    for p in pids(cfg):
        subprocess.run(["kill", p], capture_output=True)
    time.sleep(3)
    for p in pids(cfg):
        subprocess.run(["kill", "-9", p], capture_output=True)
    time.sleep(2)

    unidad = f"wa-puente-{nombre}"
    subprocess.run(["systemctl", "--user", "reset-failed", f"{unidad}.service"],
                   capture_output=True)
    r = subprocess.run(
        ["systemd-run", "--user", f"--unit={unidad}", "--collect",
         f"--working-directory={cfg['dir']}",
         os.path.join(cfg["dir"], cfg["bin"])],
        capture_output=True, text=True)
    if r.returncode != 0:
        log(f"{nombre}: systemd-run fallo -> {r.stderr.strip()[:160]}")
        return []
    time.sleep(20)      # autenticar + conectar
    return pids(cfg)


def late(nombre, cfg, curar=True):
    # Primero el enlace: una cuenta desvinculada NO se cura reiniciando, se cura
    # escaneando un QR. Sin este corte, un puente desvinculado con numero propio
    # entraria al bucle de cura y se relanzaria solo, para siempre, sin arreglar
    # nada; y uno sin numero propio se reportaria sano por tener el proceso vivo.
    enlazado, detalle = vinculado(cfg)
    if enlazado is False:
        log(f"{nombre}: FAIL, el proceso corre pero la CUENTA esta desvinculada "
            f"({detalle}). No se cura con reinicio: hay que reenlazar por QR")
        return False
    if enlazado is None:
        log(f"{nombre}: aviso, no pude comprobar el enlace ({detalle})")

    # A rejected client version is down whatever the process and the link say,
    # and a restart brings back the same rejection: no cure here, only a rebuild.
    rech, det_rech = rechazado(cfg)
    if rech:
        log(f"{nombre}: FAIL, {det_rech}. No se cura con reinicio: hay que "
            f"recompilar el puente con una version nueva de whatsmeow")
        return False
    if rech is None and (cfg.get("unidad") or cfg.get("remoto")):
        log(f"{nombre}: aviso, no pude comprobar el rechazo de version ({det_rech})")

    if not cfg.get("propio"):
        vivo = pids(cfg)
        # El detalle NO se etiqueta como "enlace OK" cuando es None: ahi el enlace
        # no se comprobo, y decir OK convierte el journal en un testigo falso.
        estado = f"enlace OK ({detalle})" if enlazado else "enlace NO COMPROBADO"
        alcance = ("Sonda parcial: no ejercita el envio" if enlazado
                   else "Sonda MINIMA: ni enlace ni envio comprobados")
        log(f"{nombre}: sin numero propio -> proceso {'vivo' if vivo else 'MUERTO'}, "
            f"{estado}. {alcance}")
        return bool(vivo)

    for intento in (1, 2):
        sello = f"latido-{secrets.token_hex(8)}"   # impredecible: no falsificable
        desde = reloj_del_store(cfg)
        ok, det = manda(cfg, sello)
        if ok:
            # sondeo, no sleep ciego: un puente sano pero lento no debe fallar
            limite = time.time() + ESPERA_MAX_S
            while time.time() < limite:
                if aterrizo(cfg, sello, desde):
                    log(f"{nombre}: PASS, el latido salio y aterrizo "
                        f"(intento {intento})")
                    return True
                time.sleep(SONDEO_S)
            log(f"{nombre}: el envio dijo OK pero NO aterrizo en {ESPERA_MAX_S}s")
            tunel_roto = False
        else:
            log(f"{nombre}: no se pudo enviar -> {det}")
            tunel_roto = es_fallo_de_tunel(cfg, det)
            if tunel_roto:
                # Se dice SIEMPRE, tambien en --sin-curar: un diagnostico que
                # solo grita "caido" manda a revisar el servidor equivocado.
                log(f"{nombre}: el puente vive en el servidor, asi que el "
                    f"sospechoso es el tunel local, no el puente")

        if intento == 2 or not curar:
            return False
        if tunel_roto:
            # El puente esta en el servidor y el que no contesta es el 127.0.0.1
            # de esta maquina. Reiniciar el puente por esto es curar al sano.
            log(f"{nombre}: el puerto local no contesta y el puente es remoto "
                f"-> curo el TUNEL, no el puente")
            cura_tunel(cfg)
            continue
        vivos = reinicia(nombre, cfg)
        # Se dice DONDE. Un "levantado PID 509900" a secas es indistinguible de
        # un puente local recien clonado, que es justo el fallo que se vigila.
        donde = "en el servidor" if cfg.get("remoto") else "aqui"
        log(f"{nombre}: {'levantado '+donde+', PID '+vivos[0] if vivos else 'NO levanto'}")
    return False


def guarda(res, nota=""):
    try:
        os.makedirs(os.path.dirname(ESTADO), exist_ok=True)
        with open(ESTADO, "w") as f:
            json.dump({"cuando": datetime.now().isoformat(timespec="seconds"),
                       "resultado": res, "nota": nota}, f, indent=1)
    except Exception as e:
        log(f"no pude guardar el estado: {e}")


def _lee_vistos():
    try:
        with open(AVISOS_VISTOS) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _guarda_vistos(d):
    try:
        os.makedirs(os.path.dirname(AVISOS_VISTOS), exist_ok=True)
        tmp = AVISOS_VISTOS + ".tmp"
        with open(tmp, "w") as f:
            json.dump(d, f)
        os.replace(tmp, AVISOS_VISTOS)
    except OSError as e:
        log(f"no pude guardar los avisos vistos: {e}")


def avisa_autoupdate(cfgs, ahora=None):
    """Read each remote bridge's auto-update state and hand every NEW result to
    the configured notifier. Returns the list of notices sent, for the selftest.

    A result is new when its ts is past the last one announced for that bridge.
    An in_progress record is only announced once it is older than
    AUTOUPDATE_ATORADO_S (the run is stuck or was killed). On a first run, with
    nothing announced yet, results older than AUTOUPDATE_VIGENCIA_S are marked
    as seen without a notice, so turning this on does not replay history."""
    ahora = time.time() if ahora is None else ahora
    vistos = _lee_vistos()
    enviados = []
    for nombre, cfg in cfgs.items():
        au = (cfg.get("remoto") or {}).get("autoupdate")
        if not au or not au.get("estado") or not au.get("aviso"):
            continue
        try:
            crudo = ssm(cfg, f"cat {shlex.quote(au['estado'])} 2>/dev/null || true").strip()
        except SondaRota as e:
            log(f"{nombre}: no pude leer el estado de la actualizacion -> {e}")
            continue
        if not crudo:
            continue
        try:
            st = json.loads(crudo.splitlines()[0])
            ts = int(st["ts"])
            resultado = str(st["result"])
        except (ValueError, KeyError, TypeError, IndexError):
            log(f"{nombre}: el estado de la actualizacion no se puede leer")
            continue
        visto = vistos.get(nombre)
        if isinstance(visto, (int, float)) and ts <= visto:
            continue
        if visto is None and ahora - ts > AUTOUPDATE_VIGENCIA_S:
            vistos[nombre] = ts
            continue
        if resultado == "in_progress":
            if ahora - ts < AUTOUPDATE_ATORADO_S:
                continue
            resultado = "atorado"
        motivo = f"actualizacion automatica del puente {nombre}: {resultado}"
        detalle = (f"whatsmeow {st.get('from') or '?'} -> {st.get('to') or '?'}. "
                   f"{st.get('detail') or ''}").strip()
        argv = [a.replace("{reason}", motivo).replace("{detail}", detalle)
                for a in au["aviso"]]
        try:
            r = subprocess.run(argv, capture_output=True, text=True, timeout=120)
            ok = r.returncode == 0
        except (OSError, subprocess.SubprocessError) as e:
            ok, r = False, None
            log(f"{nombre}: no pude avisar -> {e}")
        if ok:
            vistos[nombre] = ts
            enviados.append(motivo)
            log(f"{nombre}: avisado -> {motivo}")
        elif r is not None:
            log(f"{nombre}: el aviso fallo (rc {r.returncode}): {r.stderr.strip()[:160]}")
    _guarda_vistos(vistos)
    return enviados


def puerto_libre():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def selftest():
    """Fixtures. Cubren los DOS fallos que originaron este script y el bug de
    pgrep que encontro la revision, no solo el camino feliz."""
    import http.server
    import tempfile
    import threading
    global ESPERA_MAX_S, EJECUTOR_JOURNAL, AVISOS_VISTOS
    casos = fallas = 0

    def chk(n, ok):
        nonlocal casos, fallas
        casos += 1
        fallas += 0 if ok else 1
        print(f"  {n:<58} {'PASS' if ok else 'FAIL'}")

    d = tempfile.mkdtemp()
    try:
        db = os.path.join(d, "m.db")
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE messages "
                    "(content TEXT, is_from_me INT, timestamp TEXT)")
        con.execute("INSERT INTO messages VALUES ('latido-aa',1,'2026-01-01 00:00:00')")
        con.execute("INSERT INTO messages VALUES ('latido-ajeno',0,'2026-01-01 00:00:00')")
        con.commit(); con.close()
        cfg = {"db": db, "dir": d, "bin": "nada", "puerto": 1, "propio": "1"}

        chk("detecta un sello propio que SI aterrizo",
            aterrizo(cfg, "latido-aa", "2025-01-01 00:00:00"))
        chk("NO cuenta un sello de un tercero (is_from_me=0)",
            not aterrizo(cfg, "latido-ajeno", "2025-01-01 00:00:00"))
        chk("NO cuenta un sello anterior a esta corrida",
            not aterrizo(cfg, "latido-aa", "2026-06-01 00:00:00"))

        try:
            aterrizo({"db": "/no/existe.db"}, "x", "2025-01-01")
            chk("base ausente lanza SondaRota, no un False silencioso", False)
        except SondaRota:
            chk("base ausente lanza SondaRota, no un False silencioso", True)

        # EL caso que origino el script: envio 200 OK y mensaje que NUNCA aterriza
        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(200); self.end_headers()
                self.wfile.write(b'{"success":true}')
            def log_message(self, *a): pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        viejo, ESPERA_MAX_S = ESPERA_MAX_S, 3
        r = late("fixture", dict(cfg, puerto=srv.server_address[1]), curar=False)
        ESPERA_MAX_S = viejo
        srv.shutdown()
        chk("envio 200 OK sin aterrizar NO se reporta como PASS", not r)

        ok, _ = manda(dict(cfg, puerto=puerto_libre()), "x")
        chk("puerto cerrado NO se reporta como envio exitoso", not ok)

        # el agujero real de 2026-08-04: proceso vivo, cuenta cerrada. Antes de
        # este corte la sonda decia "sano" y nadie se enteraba.
        chk("sin whatsapp.db el enlace es None, NO False", vinculado(cfg)[0] is None)
        wdb = os.path.join(d, "whatsapp.db")
        con = sqlite3.connect(wdb)
        con.execute("CREATE TABLE whatsmeow_device (jid TEXT)")
        con.commit(); con.close()
        chk("cuenta desvinculada (0 dispositivos) se detecta",
            vinculado(cfg)[0] is False)
        con = sqlite3.connect(wdb)
        con.execute("INSERT INTO whatsmeow_device VALUES ('1@s.whatsapp.net')")
        con.commit(); con.close()
        chk("con 1 dispositivo enlazado la sonda de enlace deja pasar",
            vinculado(cfg)[0] is True)

        # PAR DISTINGUIDOR. Aqui hubo un fixture que decia "puente desvinculado NO
        # se reporta como PASS" y no probaba eso: usaba un puerto cerrado, asi que
        # late() fallaba por no poder enviar, no por el enlace. Un revisor
        # independiente lo mostro mutando el codigo, borro la comprobacion entera y
        # el selftest siguio en 11/11. Este par la aisla: el proceso esta VIVO y no
        # hay "propio", asi que no existe envio que pueda fallar y lo UNICO que
        # mueve el resultado es la tabla de dispositivos. Sin la comprobacion en
        # late(), el segundo caso se pone rojo.
        sleepbin = shutil.which("sleep")
        binreal = os.path.join(d, "puente-fixture")
        shutil.copy(sleepbin, binreal)
        proc = subprocess.Popen([binreal, "30"])
        time.sleep(0.5)
        suelto = {"db": db, "dir": d, "bin": "puente-fixture", "puerto": 1}
        try:
            chk("control positivo: pids() ve vivo el proceso del fixture",
                len(pids(suelto)) > 0)
            chk("mismo caso, ENLAZADO -> PASS",
                late("fx-on", suelto, curar=False))

            # REJECTED-VERSION PAIR. Same live, linked bridge with no own number,
            # the case that read "link OK" for hours while WhatsApp rejected it.
            # Only the current run's journal (newest line first) changes, so
            # only the rejected-version check can move the result.
            con_unidad = dict(suelto, unidad="puente-fixture.service")
            try:
                EJECUTOR_JOURNAL = lambda c: (
                    "00:31:10.237\x1b[31m [Client ERROR] Client outdated (405) "
                    "connect failure\x1b[0m\n"
                    "\u2713 Connected to WhatsApp! Type 'help' for commands.\n")
                chk("405 en la corrida actual -> FAIL aunque vivo y enlazado",
                    not late("fx-405", con_unidad, curar=False))
                EJECUTOR_JOURNAL = lambda c: (
                    "14:07:06.109\x1b[36m [Client INFO] Successfully authenticated\x1b[0m\n"
                    "00:31:10.237 [Client ERROR] Client outdated (405) connect failure\n")
                chk("login mas nuevo que el 405 -> PASS",
                    late("fx-login", con_unidad, curar=False))
                EJECUTOR_JOURNAL = lambda c: ""
                chk("corrida sin 405 ni login (arrancando) no es rechazo",
                    rechazado(con_unidad)[0] is False)
                chk("sin unidad configurada el rechazo es None, NO False",
                    rechazado(suelto)[0] is None)
            finally:
                EJECUTOR_JOURNAL = None
            con = sqlite3.connect(wdb)
            con.execute("DELETE FROM whatsmeow_device")
            con.commit(); con.close()
            chk("mismo caso, DESVINCULADO -> FAIL (aisla la comprobacion)",
                not late("fx-off", suelto, curar=False))
        finally:
            proc.kill(); proc.wait()

        # el bug que encontro la revision: un lector del binario contandose
        # nombre de 24 chars a proposito: con -x este caso pasaba porque no
        # matcheaba nada, no porque el filtro por exe funcionara.
        falso = os.path.join(d, "whatsapp-fixture-bridge")
        open(falso, "w").close()
        t = subprocess.Popen(["tail", "-f", falso], stdout=subprocess.DEVNULL)
        time.sleep(0.5)
        n = len(pids({"dir": d, "bin": "whatsapp-fixture-bridge"}))
        t.kill(); t.wait()
        chk("un 'tail -f <binario>' NO se cuenta como puente vivo", n == 0)

        # ---- puentes REMOTOS. El fallo del 18-ago-2026: el puente ya vivia en
        # la EC2 y las sondas seguian midiendo esta maquina. Cada caso de aqui
        # se pone rojo si alguien vuelve a apuntar una sonda al lado local.
        global EJECUTOR_SSM
        remoto = {"instancia": "i-fixture", "region": "r", "perfil": "p",
                  "unidad": "puente-remoto.service",
                  "db": "/opt/remoto/store/messages.db",
                  "sesion": "/opt/remoto/store/whatsapp.db",
                  "tunel": "tunel-fixture.service"}
        rcfg = dict(cfg, remoto=remoto)
        vistos = []
        journal_remoto = [""]
        estado_remoto = [""]

        def falso_ssm(c, comando):
            vistos.append(comando)
            if "_SYSTEMD_INVOCATION_ID" in comando:
                return journal_remoto[0]
            if comando.startswith("cat "):
                return estado_remoto[0]
            if "ActiveState" in comando:
                return "MainPID=4242\nActiveState=active\n"
            if "whatsmeow_device" in comando:
                return "1\n"
            if "FROM messages" in comando:
                return "1\n"
            if comando.startswith("date "):
                # el servidor va en UTC: 2 horas atras de Madrid. Si alguien
                # vuelve a calcular el corte con el reloj local, este valor deja
                # de coincidir y el caso se pone rojo.
                return "2026-08-18 13:43:24\n"
            return ""

        EJECUTOR_SSM = falso_ssm
        try:
            vistos.clear()
            paso = aterrizo(rcfg, "latido-zz", "2026-01-01 00:00:00")
            chk("remoto: el aterrizaje se consulta y da PASS", paso)
            chk("remoto: consulta el store DEL SERVIDOR, no la replica local",
                any(remoto["db"] in c for c in vistos)
                and not any(cfg["db"] in c for c in vistos))

            vistos.clear()
            chk("remoto: pids() lee la unidad del servidor",
                pids(rcfg) == ["4242"]
                and any("puente-remoto.service" in c for c in vistos))

            vistos.clear()
            chk("remoto: el enlace se comprueba en la sesion del servidor",
                vinculado(rcfg)[0] is True
                and any(remoto["sesion"] in c for c in vistos))

            vistos.clear()
            reinicia("fx", rcfg)
            chk("remoto: la cura reinicia la unidad REMOTA",
                any(c.startswith("systemctl restart") for c in vistos))
            chk("remoto: la cura NO menciona el binario local",
                not any(cfg["dir"] in c for c in vistos))

            vistos.clear()
            chk("remoto: el corte temporal sale del reloj DEL SERVIDOR",
                reloj_del_store(rcfg) == "2026-08-18 13:43:24"
                and any(c.startswith("date ") for c in vistos))
            chk("local: el corte temporal sigue saliendo del reloj de aqui",
                reloj_del_store(cfg)[:2] == "20" and len(reloj_del_store(cfg)) == 19)

            vistos.clear()
            journal_remoto[0] = "[Client ERROR] Client outdated (405) connect failure\n"
            chk("remoto: el 405 se lee de la corrida de la unidad DEL SERVIDOR",
                rechazado(rcfg)[0] is True
                and any("puente-remoto.service" in c and "InvocationID" in c
                        for c in vistos))
            journal_remoto[0] = "[Client INFO] Successfully authenticated\n"
            chk("remoto: con login la corrida no esta rechazada",
                rechazado(rcfg)[0] is False)

            # ---- auto-update notices
            AVISOS_VISTOS = os.path.join(d, "avisos-vistos.json")
            buzon = os.path.join(d, "buzon.txt")
            escribe = [sys.executable, "-c",
                       "import sys; open(sys.argv[1], 'a').write(sys.argv[2] + '\\n')",
                       buzon, "{reason} | {detail}"]
            au = {"estado": "/var/lib/fx/state.json", "aviso": escribe}
            cfgs = {"fx": dict(rcfg, remoto=dict(remoto, autoupdate=au))}
            ahora = 2_000_000_000

            def estado(ts, res):
                estado_remoto[0] = json.dumps({"ts": ts, "unit": "u", "result": res,
                                               "from": "v1", "to": "v2",
                                               "detail": "d"}) + "\n"

            def lineas():
                return open(buzon).read().splitlines() if os.path.exists(buzon) else []

            estado(ahora - 60, "updated")
            env = avisa_autoupdate(cfgs, ahora)
            chk("aviso: un resultado nuevo se avisa una vez",
                len(env) == 1 and "updated" in env[0] and len(lineas()) == 1)
            chk("aviso: el detalle lleva ambas versiones",
                "v1 -> v2" in lineas()[0])
            chk("aviso: el mismo resultado NO se vuelve a avisar",
                avisa_autoupdate(cfgs, ahora + 600) == [] and len(lineas()) == 1)
            estado(ahora + 900, "in_progress")
            chk("aviso: in_progress reciente se calla",
                avisa_autoupdate(cfgs, ahora + 960) == [])
            env = avisa_autoupdate(cfgs, ahora + 900 + AUTOUPDATE_ATORADO_S + 1)
            chk("aviso: in_progress viejo se avisa como atorado",
                len(env) == 1 and "atorado" in env[0])
            os.remove(AVISOS_VISTOS)
            estado(ahora - AUTOUPDATE_VIGENCIA_S - 10, "rolled_back")
            antes = len(lineas())
            chk("aviso: en la primera corrida la historia vieja no se repite",
                avisa_autoupdate(cfgs, ahora) == [] and len(lineas()) == antes
                and avisa_autoupdate(cfgs, ahora) == [])
            estado(ahora + 5000, "build_failed")
            cfgs_mal = {"fx": dict(rcfg, remoto=dict(remoto, autoupdate=dict(
                au, aviso=[sys.executable, "-c", "import sys; sys.exit(3)"])))}
            chk("aviso: si el aviso falla no se marca visto...",
                avisa_autoupdate(cfgs_mal, ahora + 5010) == [])
            chk("...y la siguiente corrida lo reintenta",
                len(avisa_autoupdate(cfgs, ahora + 5020)) == 1)
            estado_remoto[0] = "garbage{"
            chk("aviso: un estado ilegible no rompe ni avisa",
                avisa_autoupdate(cfgs, ahora + 6000) == [])
            chk("aviso: un puente sin autoupdate configurado no se lee",
                avisa_autoupdate({"fx": rcfg}, ahora) == [])

            EJECUTOR_SSM = lambda c, x: (_ for _ in ()).throw(
                SondaRota("AWS caido de prueba"))
            try:
                aterrizo(rcfg, "x", "2026-01-01 00:00:00")
                chk("remoto: SSM caido es SondaRota, no un FAIL que cure", False)
            except SondaRota:
                chk("remoto: SSM caido es SondaRota, no un FAIL que cure", True)

            # El guardia que impide reconstruir el clon por otro camino. Va
            # DENTRO del bloque con SSM falso a proposito: con el ejecutor real
            # este caso pasaba en verde aunque se borrara el guardia, porque
            # pids() llamaba a un `aws` que no responde y ese SondaRota se leia
            # como si fuera el del guardia. Un fixture que pasa por el motivo
            # equivocado no vigila nada. Por eso ademas se exige el TEXTO.
            try:
                reinicia_local("fx", rcfg)
                chk("remoto: levantar el binario local esta PROHIBIDO", False)
            except SondaRota as e:
                chk("remoto: levantar el binario local esta PROHIBIDO",
                    "prohibido" in str(e))
        finally:
            EJECUTOR_SSM = None

        chk("un 8081 que no contesta en puente remoto se lee como TUNEL roto",
            es_fallo_de_tunel(rcfg, "URLError: Connection refused"))
        chk("el mismo error en puente LOCAL no culpa a ningun tunel",
            not es_fallo_de_tunel(cfg, "URLError: Connection refused"))
    finally:
        AVISOS_VISTOS = os.path.expanduser("~/.cache/wa-latido-autoupdate.json")
        shutil.rmtree(d, ignore_errors=True)

    print(f"\n  {casos-fallas}/{casos}")
    return 1 if fallas else 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sin-curar", action="store_true")
    p.add_argument("--selftest", action="store_true")
    a = p.parse_args()
    if a.selftest:
        sys.exit(selftest())

    # un solo latido a la vez: dos reinicios concurrentes = dos puentes
    # peleando el mismo puerto y la misma sesion de WhatsApp
    os.makedirs(os.path.dirname(LOCK), exist_ok=True)
    lock = open(LOCK, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("ya hay otro latido corriendo, salgo sin hacer nada")
        sys.exit(0)

    try:
        cfgs = carga()
    except SondaRota as e:
        log(f"SONDA ROTA: {e}")
        guarda({}, str(e))
        sys.exit(1)

    res, malos, rotas = {}, [], []
    for n, cfg in cfgs.items():
        try:
            ok = late(n, cfg, curar=not a.sin_curar)
            # Un fallo por cuenta desvinculada NO es del mismo tipo que uno de
            # tuberia: el segundo se cura solo, el primero pide un humano con el
            # telefono. Si el archivo de estado los llama igual, quien escale no
            # puede distinguir "reinicia" de "escanea el QR", y el latido va a
            # fallar cada 10 minutos sin que nadie sepa que la cura es de mano.
            res[n] = "ok" if ok else (
                "FALLO: requiere reenlace por QR" if vinculado(cfg)[0] is False
                else "FALLO: cliente rechazado (405), requiere recompilar"
                if rechazado(cfg)[0] is True
                else "FALLO")
            if not ok:
                malos.append(n)
        except SondaRota as e:
            res[n] = f"SONDA ROTA: {e}"     # no se cura lo que no se pudo medir
            rotas.append(n)
            log(f"{n}: SONDA ROTA, no curo -> {e}")
        except Exception as e:
            res[n] = f"ERROR: {type(e).__name__}: {e}"
            rotas.append(n)
            log(f"{n}: error inesperado -> {type(e).__name__}: {e}")

    guarda(res)
    try:
        avisa_autoupdate(cfgs)
    except Exception as e:      # a notice that fails must not fail the heartbeat
        log(f"avisos de actualizacion: error -> {type(e).__name__}: {e}")
    if malos or rotas:
        log(f"FALLO: caidos={malos or 'ninguno'} sonda_rota={rotas or 'ninguna'}")
        sys.exit(1)
    log("todos los puentes responden")


if __name__ == "__main__":
    main()
