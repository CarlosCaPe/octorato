#!/usr/bin/env python3
"""Latido activo de puentes de WhatsApp: mide la TUBERIA, no el proceso.

POR QUE EXISTE. Un puente puede estar caido dias sin que nadie se entere, porque
las dos sondas obvias mienten:

  1. "el proceso existe" (pgrep). Un puente puede estar vivo, autenticado y con
     socket abierto, y llevar horas sin persistir un solo mensaje.
  2. "la base se escribio hace poco" (mtime). No distingue ROTO de QUIETO. En un
     canal de poco trafico, horas sin escribir puede ser silencio legitimo o un
     atasco, y la sonda no puede decir cual.

La sonda que no miente es ACTIVA: mandar un mensaje y comprobar que aterriza.
Es la diferencia entre preguntar "¿respiras?" y ponerle un espejo en la boca.

ALCANCE HONESTO. Ejercita el camino de SALIDA (API -> whatsmeow -> ack del
servidor -> escritura a SQLite). NO ejercita el de ENTRADA, que es otro manejador
del mismo binario. Un puente que envia pero tiene la recepcion atorada pasaria en
verde. Es mucho mas que pgrep y menos que "la tuberia completa".

CONFIGURACION. Los datos del canal (numeros, rutas) viven en
company/config/wa-puentes.json, que esta gitignored. Este script es publico y no
debe contener ningun identificador de cliente.

Uso:
    wa-latido.py                 comprueba, y si hace falta cura
    wa-latido.py --sin-curar     solo diagnostica
    wa-latido.py --selftest      autoprueba con fixtures
"""
import argparse
import fcntl
import json
import os
import secrets
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
LOCK = os.path.expanduser("~/.cache/wa-latido.lock")

ESPERA_MAX_S = 40      # se sondea hasta aqui, no se duerme a ciegas
SONDEO_S = 2
HTTP_TIMEOUT = 10


class SondaRota(Exception):
    """La sonda no pudo medir. NO es lo mismo que 'el puente esta caido':
    curar aqui seria reiniciar un puente sano cada 10 minutos, para siempre."""


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


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
    """Arranca el puente FUERA del cgroup de este servicio.

    Con Popen normal el hijo nace dentro de wa-latido.service, que es
    Type=oneshot: al terminar ExecStart systemd derriba el cgroup y se lleva al
    puente recien levantado. `start_new_session` cambia la sesion, NO el cgroup.
    Resultado sin este arreglo: curo, reporto PASS, systemd lo mata, y el ciclo
    se repite cada 10 min con verde en el journal. O sea el fallo silencioso que
    este script viene a matar, reconstruido.

    systemd-run le da su propia unidad transitoria y ahi sobrevive.
    """
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

    if not cfg.get("propio"):
        vivo = pids(cfg)
        log(f"{nombre}: sin numero propio -> proceso {'vivo' if vivo else 'MUERTO'}, "
            f"enlace OK ({detalle}). Sonda parcial: no ejercita el envio")
        return bool(vivo)

    for intento in (1, 2):
        sello = f"latido-{secrets.token_hex(8)}"   # impredecible: no falsificable
        desde = datetime.now().replace(microsecond=0).isoformat(sep=" ")
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
        else:
            log(f"{nombre}: no se pudo enviar -> {det}")

        if intento == 2 or not curar:
            return False
        log(f"{nombre}: curando, relanzo el puente en su propia unidad")
        vivos = reinicia(nombre, cfg)
        log(f"{nombre}: {'levantado PID '+vivos[0] if vivos else 'NO levanto'}")
    return False


def guarda(res, nota=""):
    try:
        os.makedirs(os.path.dirname(ESTADO), exist_ok=True)
        with open(ESTADO, "w") as f:
            json.dump({"cuando": datetime.now().isoformat(timespec="seconds"),
                       "resultado": res, "nota": nota}, f, indent=1)
    except Exception as e:
        log(f"no pude guardar el estado: {e}")


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
    global ESPERA_MAX_S
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
        chk("puente desvinculado NO se reporta como PASS",
            not late("fixture-suelto", dict(cfg, puerto=puerto_libre()),
                     curar=False))
        con = sqlite3.connect(wdb)
        con.execute("INSERT INTO whatsmeow_device VALUES ('1@s.whatsapp.net')")
        con.commit(); con.close()
        chk("con 1 dispositivo enlazado la sonda de enlace deja pasar",
            vinculado(cfg)[0] is True)

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
    finally:
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
            res[n] = "ok" if ok else "FALLO"
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
    if malos or rotas:
        log(f"FALLO: caidos={malos or 'ninguno'} sonda_rota={rotas or 'ninguna'}")
        sys.exit(1)
    log("todos los puentes responden")


if __name__ == "__main__":
    main()
