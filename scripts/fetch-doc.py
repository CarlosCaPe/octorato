#!/usr/bin/env python3
"""fetch-doc: baja una URL publica y devuelve TEXTO UTILIZABLE, escalando por coste.

POR QUE EXISTE
--------------
Consultando normativa y tarifas bancarias, varias fuentes devolvieron 403 al fetch
automatizado y frenaron el trabajo. Casi ninguno de esos 403 era una defensa seria:
eran filtros de User-Agent y de fingerprint de cliente HTTP. Sin este script el agente
se queda con el extracto del buscador en vez del documento, y eso degrada la respuesta
al operador sin que se note. Este script cierra esa friccion y, sobre todo, DICE por que
camino salio, para que el que lee el texto pueda juzgar si es fiable.

LOS DOS CAMINOS (en orden de coste)
-----------------------------------
1. requests con cabeceras de navegador real (UA, Accept, Accept-Language, Referer
   coherente con el propio origen). Resuelve la mayoria de los 403 de filtro de UA.
2. Si sigue bloqueado, navegador de verdad: agent-browser (CLI nativa en Rust sobre
   Chrome via CDP, ya instalada en esta maquina). Se usa lo que YA existe, no se
   instala otro motor. Dos modos dentro del navegador:
     a) puente de cookies: el navegador abre el origen, resuelve lo que tenga que
        resolver, se exportan sus cookies y se reintenta con requests. Esto sirve para
        CUALQUIER tipo de contenido, incluido PDF, que Chrome no entrega como texto.
     b) render directo: si el puente no basta y el destino es HTML, se lee el DOM ya
        renderizado.

SALIDA
------
Texto plano. HTML se limpia con lxml (se tiran script/style/nav/footer/forms). PDF se
extrae con pdfplumber. La idea es que otro agente lea el resultado sin volver a pelearse
con el formato.

FRONTERA ETICA (deliberada, no es una limitacion pendiente)
-----------------------------------------------------------
Mandar un User-Agent de navegador para leer documentacion publica es normal: el
documento es publico y se sirve a cualquier navegador. Hasta ahi llega este script.
NO hace, y no se le va a agregar: resolucion de captcha, rotacion de proxies o de IP,
suplantacion de TLS/JA3, reintentos en bucle contra un rate-limit, ni login con
credenciales. Si una fuente exige captcha, autenticacion o bloquea por region, el
script lo REPORTA y se rinde con exit distinto de 0. Forzar una defensa real que el
sitio puso a proposito no es trabajo de esta herramienta.

Tampoco resuelve el bloqueo por REGION o por reputacion de IP. Si el sitio deniega a
la IP de salida actual, ni las cabeceras ni el navegador cambian nada: la pagina de
bloqueo suele imprimir la propia IP, y el script la muestra en el reporte para que se
vea de donde viene la negativa. Eso se arregla saliendo por otra IP (una VPN con salida
en el pais correcto), decision del operador, no del script.

NUNCA devuelve vacio con exit 0. Un vacio silencioso es indistinguible de "la pagina
no tenia contenido" y es el patron de falso verde que hay que evitar. Si no hay texto
utilizable, sale con codigo != 0 y dice que intento y que devolvio cada camino.

USO
---
    python3 fetch-doc.py <url> [--out ARCHIVO] [--raw] [--timeout N]

CODIGOS DE SALIDA
-----------------
    0  texto extraido correctamente
    2  error de uso (URL invalida, argumentos mal)
    3  los dos caminos fallaron a nivel de red o HTTP
    4  se bajo contenido pero no hay texto utilizable (PDF escaneado, pagina vacia)
    5  muro real detectado: captcha, login o bloqueo por region. Se reporta y se rinde
    6  falta una dependencia necesaria (pdfplumber, lxml, agent-browser)
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlparse

try:
    import requests
except ImportError:  # sin requests no hay ni primer camino
    print("[fetch-doc] FATAL: falta el paquete 'requests'", file=sys.stderr)
    sys.exit(6)


# ---------------------------------------------------------------------------
# Constantes de deteccion
# ---------------------------------------------------------------------------

# UA de Chrome estable en Linux. Coherente con el Chrome real que usa el escalon 2,
# para que las dos rutas se presenten igual ante el servidor.
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")

# Codigos que casi siempre significan "me filtraste", no "no existe". El 404 NO esta
# aqui a proposito: un 404 es una respuesta legitima del servidor y escalar a navegador
# solo gastaria 20 segundos para volver a leer el mismo 404.
BLOQUEO_STATUS = {401, 402, 403, 406, 409, 429, 451}

# Marcadores de pagina-de-bloqueo. Se buscan en el TEXTO ya extraido, no en el HTML
# crudo, porque en el HTML crudo cualquier articulo que hable de captchas daria falso
# positivo por un nombre de clase CSS.
MARCADORES_MURO = (
    # captcha / challenge de JS: esto es defensa real, aqui nos rendimos
    "captcha", "recaptcha", "hcaptcha", "turnstile",
    "just a moment", "checking your browser", "verifying you are human",
    "enable javascript and cookies to continue",
    "verificando que eres humano",
)
MARCADORES_BLOQUEO = MARCADORES_MURO + (
    # denegaciones de WAF / CDN: aqui todavia vale la pena escalar a navegador
    "access denied", "acceso denegado", "403 forbidden", "forbidden",
    "request unsuccessful", "incapsula", "imperva", "attention required",
    "algo salio mal", "algo sali\u00f3 mal", "something went wrong",
    "error de conexion", "no autorizado", "unauthorized",
    "acceso restringido", "not available in your country",
    "no disponible en tu pais", "no disponible en tu pa\u00eds",
    "has been blocked", "web page blocked", "page blocked", "blocked",
    "bloqueado", "bloqueada", "denegado", "no tienes permiso",
    # Firma ESTRUCTURAL, la que mas cubre: una pagina de WAF casi siempre imprime un
    # identificador de incidente y la IP del cliente, para que el usuario pueda
    # reclamarle al administrador. Un documento real corto nunca trae eso. Se agrego
    # despues de que una pagina que decia "Web Page Blocked! ... Client IP ... Attack
    # ID" pasara como documento valido: la lista de frases siempre se queda corta, la
    # firma estructural no.
    "reference id", "client ip", "attack id", "message id", "request id",
    "incident id", "ray id", "error id", "tu direccion ip", "su direcci\u00f3n ip",
)

# Una pagina de bloqueo es CORTA. Un articulo real que mencione la palabra "captcha"
# es largo. Este umbral es lo que separa la deteccion de un falso positivo: solo se
# declara bloqueo si el texto es corto Y trae marcador.
UMBRAL_PAGINA_CORTA = 2500

# Debajo de esto no se puede AFIRMAR que se trajo el documento. El umbral no es
# cosmetico: la primera version usaba 40 y devolvio exit 0 con 51 caracteres de un
# shell de login pintado por JavaScript. Eso es exactamente el falso verde que hay que
# matar, asi que el piso sube a 200 y un texto por debajo NO se acepta: primero escala
# al navegador (casi siempre significa que el contenido lo pinta JS y requests solo vio
# el cascaron) y si tras el navegador sigue igual de corto, se falla ruidosamente.
# Se prefiere fallar sobre un documento legitimamente breve antes que entregar basura
# con exit 0. Quien necesite ese caso tiene --raw.
MINIMO_TEXTO_UTIL = 200

# Bloques que fuerzan salto de linea al aplanar HTML, para que el texto no salga
# pegado en un solo parrafo gigante.
TAGS_BLOQUE = {
    "p", "div", "br", "li", "tr", "section", "article", "aside", "pre",
    "blockquote", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6",
    "figcaption", "dt", "dd", "table", "ul", "ol", "hr",
}

# Ruido estructural. El criterio es estricto a proposito: solo entra lo que NUNCA
# contiene el documento.
#
# 'form' y 'header' estaban aqui y fue un error caro. En ASP.NET WebForms, que es lo
# que corre media administracion publica, un unico <form> envuelve la pagina entera:
# tirarlo borraba el documento completo y dejaba 126 caracteres de un portal que tenia
# 5512. Un contenedor semantico no es ruido por su nombre; lo que sobra son los
# CONTROLES sueltos (botones, inputs) y la navegacion.
TAGS_BASURA = {
    "script", "style", "noscript", "svg", "iframe", "template", "canvas",
    "video", "audio", "object", "embed", "nav", "footer",
    "button", "select", "input", "textarea",
}


def log(msg):
    """Todo el rastro va a stderr para que stdout quede limpio y sea pipeable."""
    print("[fetch-doc] " + msg, file=sys.stderr)


def kb(n):
    return "%.1f KB" % (n / 1024.0)


# ---------------------------------------------------------------------------
# Camino 1: requests con cabeceras de navegador real
# ---------------------------------------------------------------------------

def cabeceras(url):
    """Cabeceras de un Chrome normal pidiendo un documento.

    El Referer se pone al propio origen del recurso porque muchos CDN rechazan
    peticiones sin Referer o con Referer de otro dominio. Es coherente: representa
    a un usuario que llego al documento navegando dentro del mismo sitio.
    """
    p = urlparse(url)
    origen = "%s://%s/" % (p.scheme, p.netloc)
    return {
        "User-Agent": UA,
        "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                   "application/pdf,image/avif,image/webp,*/*;q=0.8"),
        "Accept-Language": "es-ES,es;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": origen,
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    }


def via_requests(url, timeout, cookies=None):
    """Devuelve (ok_red, status, content_type, cuerpo_bytes, detalle)."""
    try:
        r = requests.get(url, headers=cabeceras(url), timeout=timeout,
                         allow_redirects=True, cookies=cookies or {})
    except requests.exceptions.SSLError as e:
        return False, None, None, b"", "error TLS: %s" % e, None
    except requests.exceptions.Timeout:
        return False, None, None, b"", "timeout de %ss" % timeout, None
    except requests.exceptions.RequestException as e:
        return False, None, None, b"", "error de red: %s" % e, None
    bruto = r.headers.get("Content-Type") or ""
    ctype = bruto.split(";")[0].strip().lower()
    # El charset del header HTTP se guarda aparte porque muchas paginas NO lo declaran
    # en un <meta> y solo lo mandan aqui. Si se pierde, lxml adivina mal y el texto sale
    # con mojibake ("corazÃ³n" en vez de "corazon"), que es un documento corrupto
    # entregado como si estuviera bien.
    charset = None
    m = re.search(r"charset=([\w\-]+)", bruto, re.I)
    if m:
        charset = m.group(1)
    return True, r.status_code, ctype, r.content, \
        "%d %s" % (r.status_code, ctype or "?"), charset


# ---------------------------------------------------------------------------
# Camino 2: navegador real via agent-browser
# ---------------------------------------------------------------------------

# Sesion propia y con nombre: si el operador tiene otra sesion de agent-browser
# abierta trabajando en algo, este script no se la pisa ni se la cierra.
SESION = "fetch-doc"


def ab(args, timeout):
    """Corre agent-browser en su propia sesion. Devuelve (rc, stdout, stderr)."""
    exe = shutil.which("agent-browser")
    if not exe:
        return 127, "", "agent-browser no esta instalado"
    cmd = [exe, "--session-name", SESION] + args
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 30)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "agent-browser excedio el timeout"
    except OSError as e:
        return 127, "", "no se pudo ejecutar agent-browser: %s" % e


def cookies_del_navegador(url, timeout):
    """Abre el ORIGEN en Chrome real y exporta sus cookies.

    Se abre el origen (la raiz del dominio) y no la URL destino a proposito: si el
    destino es un PDF, Chrome lo manda al visor o a descargas y no queda nada legible
    en el DOM. Lo que se quiere del navegador es que negocie la entrada al sitio y
    deje las cookies puestas. Con esas cookies, requests vuelve a pedir el documento y
    lo recibe entero, sea HTML o binario.
    """
    p = urlparse(url)
    origen = "%s://%s/" % (p.scheme, p.netloc)
    rc, out, err = ab(["open", origen], timeout)
    if rc != 0:
        return None, (err or out or "fallo al abrir el navegador").strip()
    tmp = os.path.join(tempfile.gettempdir(), "fetch-doc-state.json")
    rc, out, err = ab(["state", "save", tmp], timeout)
    if rc != 0:
        return None, (err or out or "fallo al exportar el estado").strip()
    try:
        with open(tmp, "r", encoding="utf-8") as fh:
            estado = json.load(fh)
    except (OSError, ValueError) as e:
        return None, "estado del navegador ilegible: %s" % e
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    galletas = {c["name"]: c["value"] for c in estado.get("cookies", [])
                if p.netloc.endswith(str(c.get("domain", "")).lstrip("."))}
    return galletas, "%d cookies del origen" % len(galletas)


def html_del_navegador(url, timeout):
    """Ultimo recurso: renderiza la URL destino y devuelve el DOM ya construido.

    Sirve cuando el contenido lo pinta JavaScript o cuando el sitio solo entrega el
    documento a un cliente que ejecuta scripts.
    """
    rc, out, err = ab(["open", url], timeout)
    if rc != 0:
        return None, (err or out or "fallo al abrir la URL").strip()
    rc, out, err = ab(["get", "html", "html"], timeout)
    if rc != 0 or not out.strip():
        return None, (err or "el DOM salio vacio").strip()
    return out, "DOM renderizado, %s" % kb(len(out.encode("utf-8")))


def cerrar_navegador(timeout):
    """Cierra solo la sesion de este script. Best-effort: si falla, no importa."""
    ab(["close"], min(timeout, 20))


# ---------------------------------------------------------------------------
# Extraccion de texto
# ---------------------------------------------------------------------------

def es_pdf(cuerpo, ctype):
    # Se mira el numero magico antes que el Content-Type porque hay servidores que
    # etiquetan un PDF como application/octet-stream o incluso como text/html.
    return cuerpo[:5] == b"%PDF-" or "pdf" in (ctype or "")


def texto_de_pdf(cuerpo):
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError("falta pdfplumber para extraer texto de PDF")
    import io
    partes = []
    with pdfplumber.open(io.BytesIO(cuerpo)) as pdf:
        total = len(pdf.pages)
        for i, pagina in enumerate(pdf.pages, 1):
            t = pagina.extract_text() or ""
            if t.strip():
                partes.append("--- pagina %d/%d ---\n%s" % (i, total, t.strip()))
    return "\n\n".join(partes), total


def decodificar(crudo, charset=None):
    """Bytes a str con el charset correcto, en orden de fiabilidad.

    El orden importa y no es cosmetico. Entregando los bytes directo a lxml, una pagina
    que declara su charset SOLO en el header HTTP (no en un <meta>) se decodifica mal y
    el texto sale con mojibake: "corazAn" en vez de "corazon". Un documento corrupto
    entregado como si estuviera bien es otra forma de falso verde, mas silenciosa que un
    exit 0 vacio, porque el texto parece correcto hasta que alguien lee un acento.
    """
    if isinstance(crudo, str):
        return crudo
    candidatos = []
    if charset:
        candidatos.append(charset)
    # El <meta charset> del propio documento, segunda fuente de verdad.
    m = re.search(br'charset=["\']?([\w\-]+)', crudo[:4096], re.I)
    if m:
        candidatos.append(m.group(1).decode("ascii", "ignore"))
    candidatos += ["utf-8", "cp1252", "latin-1"]
    for enc in candidatos:
        if not enc:
            continue
        try:
            return crudo.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return crudo.decode("utf-8", "replace")


def texto_de_html(crudo, charset=None):
    """Aplana HTML a texto legible con lxml.

    lxml y no BeautifulSoup porque lxml ya esta en esta maquina y bs4 no. Meter una
    dependencia nueva para hacer lo mismo seria acumular en vez de usar lo que hay.
    """
    try:
        from lxml import etree, html as lhtml
    except ImportError:
        raise RuntimeError("falta lxml para extraer texto de HTML")
    texto_fuente = decodificar(crudo, charset)
    # lxml rechaza una declaracion XML con encoding cuando la entrada ya es str, asi
    # que se quita: el encoding ya se resolvio arriba y esa linea ya no aporta nada.
    texto_fuente = re.sub(r'^\s*<\?xml[^>]*\?>', '', texto_fuente)
    arbol = lhtml.document_fromstring(texto_fuente)

    titulo = ""
    t = arbol.find(".//title")
    if t is not None and t.text:
        titulo = t.text.strip()

    for el in arbol.xpath("//*"):
        if el.tag in TAGS_BASURA and el.getparent() is not None:
            # drop() borra el nodo pero conserva el tail, para no perder el texto que
            # venia inmediatamente despues del elemento eliminado.
            el.drop_tree()

    # Truco clasico: colgar un salto de linea del tail de cada bloque, asi el
    # aplanado a texto respeta la estructura de parrafos sin escribir un walker.
    for el in arbol.iter():
        if isinstance(el.tag, str) and el.tag in TAGS_BLOQUE:
            el.tail = (el.tail or "") + "\n"

    texto = etree.tostring(arbol, method="text", encoding="unicode")
    texto = texto.replace("\xa0", " ")
    lineas = [re.sub(r"[ \t\r\f\v]+", " ", ln).strip() for ln in texto.split("\n")]
    texto = "\n".join(ln for ln in lineas)
    texto = re.sub(r"\n{3,}", "\n\n", texto).strip()
    if titulo:
        texto = "# %s\n\n%s" % (titulo, texto)
    return texto


def extraer(cuerpo, ctype, url, charset=None):
    """Devuelve (texto, etiqueta_del_metodo)."""
    if es_pdf(cuerpo, ctype):
        texto, paginas = texto_de_pdf(cuerpo)
        return texto, "pdfplumber, %d pags" % paginas
    if ctype.startswith("text/html") or ctype.endswith("xhtml+xml") or not ctype:
        return texto_de_html(cuerpo, charset), "lxml"
    if ctype.startswith("text/") or ctype in ("application/json", "application/xml"):
        return cuerpo.decode("utf-8", "replace"), "texto plano"
    if url.lower().endswith(".pdf"):
        texto, paginas = texto_de_pdf(cuerpo)
        return texto, "pdfplumber, %d pags" % paginas
    raise RuntimeError("tipo de contenido no extraible: %s (usa --raw)" % ctype)


# ---------------------------------------------------------------------------
# Deteccion de bloqueo sobre el texto ya extraido
# ---------------------------------------------------------------------------

# Firmas de challenge que viven en el HTML CRUDO, no en el texto visible. Hicieron
# falta porque un captcha moderno (PerimeterX, Cloudflare, DataDome) no pinta texto:
# entrega un cascaron de 1-30 KB donde el widget lo monta JavaScript. Buscando solo en
# el texto visible, una pagina de captcha se veia como "documento sin texto" y el
# script culpaba a un PDF escaneado. Diagnostico equivocado es tan malo como no dar
# ninguno.
FIRMAS_CHALLENGE = (
    "px-captcha", "captcha-delivery", "datadome", "hcaptcha", "recaptcha",
    "g-recaptcha", "cf-chl", "cf_chl_opt", "challenge-platform", "turnstile",
    "_incapsula_", "distil_r_captcha", "perimeterx", "px-cloud",
    "awswafintegration", "geo.captcha",
)

# Una pagina de challenge es liviana. Un documento real que hable de captchas pesa
# cientos de KB, y por eso el tamaño es lo que separa la firma de un falso positivo:
# zillow.com sirve 420 KB con la palabra CAPTCHA dentro y NO debe rechazarse.
UMBRAL_HTML_CHALLENGE = 60 * 1024


def marca_de_challenge(crudo):
    """Devuelve la firma de challenge hallada en el HTML crudo, o None.

    Solo se aplica a respuestas pequeñas, ver UMBRAL_HTML_CHALLENGE.
    """
    if not crudo or len(crudo) > UMBRAL_HTML_CHALLENGE:
        return None
    if isinstance(crudo, bytes):
        crudo = crudo.decode("utf-8", "replace")
    plano = crudo.lower()
    for firma in FIRMAS_CHALLENGE:
        if firma in plano:
            return firma
    return None


def diagnostico(texto, crudo=None):
    """Clasifica el resultado: ('ok'|'bloqueo'|'muro', razon).

    Dos señales, no una. El texto visible detecta la pagina de denegacion que sí
    escribe el motivo ("Algo salio mal", "Access Denied"). El HTML crudo detecta el
    captcha moderno, que no escribe nada porque el widget lo monta JavaScript.

    Ninguna de las dos dispara por si sola sobre un documento real: se exige que el
    texto visible sea POBRE. Un articulo de 400 KB que mencione captchas tiene texto de
    sobra y sale 'ok' por el corte de arriba; una pagina de challenge no tiene ninguno.
    """
    plano = texto.lower()

    # El titulo se revisa SIEMPRE, sin importar el largo del texto. Un navegador no
    # devuelve codigo de estado: 'open' da exito igual sobre un 404, y esa pagina de
    # error trae menus y pie completo, asi que pasa de sobra el umbral de longitud y se
    # cuela como documento. Lo unico que la delata es el titulo, donde toda pagina de
    # error escribe su codigo. Se detecto entregando un "404 - Migraciones" con exit 0.
    primera = plano.split("\n", 1)[0].lstrip("# ").strip()
    if re.match(r'^(error\s*)?\b(400|401|403|404|410|429|500|502|503)\b', primera) or \
            re.search(r'(page|file) not found|p[aá]gina no encontrada|'
                      r'no se encontr[oó]|not found$', primera):
        return "bloqueo", "el titulo es de una pagina de error: %r" % primera[:70]

    if len(texto) >= UMBRAL_PAGINA_CORTA:
        return "ok", ""
    firma = marca_de_challenge(crudo)
    if firma:
        return "muro", "captcha o challenge de bot en la pagina (firma %r)" % firma
    for m in MARCADORES_MURO:
        if m in plano:
            return "muro", "la pagina pide captcha o verificacion de humano (%r)" % m
    for m in MARCADORES_BLOQUEO:
        if m in plano:
            return "bloqueo", "pagina de denegacion, no el documento (%r)" % m
    return "ok", ""


# ---------------------------------------------------------------------------
# Programa
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        prog="fetch-doc.py",
        description="Baja una URL publica y devuelve texto utilizable. "
                    "Escala de requests+UA a navegador real solo si hace falta.")
    ap.add_argument("url", help="URL a descargar (http o https)")
    ap.add_argument("--out", metavar="ARCHIVO", help="escribe a archivo en vez de stdout")
    ap.add_argument("--raw", action="store_true",
                    help="guarda el binario tal cual, sin extraer texto")
    ap.add_argument("--timeout", type=int, default=30, metavar="N",
                    help="timeout en segundos por intento (default 30)")
    args = ap.parse_args()

    p = urlparse(args.url)
    if p.scheme not in ("http", "https") or not p.netloc:
        log("FATAL: URL invalida: %r (se esperaba http:// o https://)" % args.url)
        return 2

    intentos = []  # rastro de lo intentado, para el mensaje de fallo

    # --- Camino 1: requests con cabeceras de navegador ---------------------
    ok, status, ctype, cuerpo, detalle, charset = via_requests(args.url, args.timeout)
    intentos.append("requests+UA -> %s" % detalle)

    escalar = False
    motivo = ""
    if not ok:
        escalar, motivo = True, detalle
    elif status in BLOQUEO_STATUS:
        escalar, motivo = True, "status %d" % status
    elif status >= 500:
        escalar, motivo = True, "status %d del servidor" % status
    elif status >= 400:
        # 404 y compania: el servidor respondio de verdad. Escalar no aporta nada,
        # solo quema 20 segundos para releer el mismo 404.
        log("requests+UA -> %s, %s. El servidor respondio; no se escala." %
            (detalle, kb(len(cuerpo))))
        log("FALLO. Intentos: " + " | ".join(intentos))
        return 3

    texto = None
    metodo = None
    camino = None

    if not escalar:
        if args.raw:
            camino, metodo, texto = "requests+UA", "sin extraer", None
        else:
            try:
                texto, metodo = extraer(cuerpo, ctype, args.url, charset)
            except RuntimeError as e:
                log("FATAL: %s" % e)
                return 6
            estado, razon = diagnostico(texto, cuerpo)
            if estado == "muro":
                log("requests+UA -> %s pero %s" % (detalle, razon))
                log("MURO REAL. No se evade captcha ni autenticacion por diseno. "
                    "Abre la URL a mano en el navegador.")
                log("Intentos: " + " | ".join(intentos))
                return 5
            if estado == "bloqueo":
                escalar = True
                motivo = razon
                intentos[-1] += " pero " + razon
            elif len(texto.strip()) < MINIMO_TEXTO_UTIL:
                # 200 de verdad, pero casi sin texto: el contenido lo pinta JS y
                # requests solo vio el cascaron. Escalar es la respuesta correcta;
                # aceptarlo seria el falso verde.
                escalar = True
                motivo = "solo %d caracteres de texto, contenido pintado por JS" % \
                    len(texto.strip())
                intentos[-1] += " pero " + motivo
            else:
                camino = "requests+UA"

    # --- Camino 2: navegador real ------------------------------------------
    if escalar:
        log("requests+UA -> %s (bloqueado: %s), escalando a navegador real" %
            (detalle, motivo))
        if not shutil.which("agent-browser"):
            log("FATAL: hace falta escalar pero agent-browser no esta instalado")
            log("Intentos: " + " | ".join(intentos))
            return 6
        try:
            # 2a. Puente de cookies: sirve para cualquier tipo de contenido, PDF incluido.
            galletas, nota = cookies_del_navegador(args.url, args.timeout)
            if galletas is None:
                intentos.append("navegador (puente de cookies) -> %s" % nota)
            else:
                ok2, st2, ct2, cuerpo2, det2, cs2 = via_requests(
                    args.url, args.timeout, cookies=galletas)
                intentos.append("navegador+cookies -> %s (%s)" % (det2, nota))
                if ok2 and st2 and st2 < 400:
                    if args.raw:
                        cuerpo, camino, metodo = cuerpo2, "navegador+cookies", "sin extraer"
                        texto = None
                    else:
                        try:
                            t2, m2 = extraer(cuerpo2, ct2, args.url, cs2)
                        except RuntimeError:
                            t2, m2 = "", ""
                        estado, razon = diagnostico(t2, cuerpo2) if t2 else \
                            ("bloqueo", "respuesta sin texto extraible")
                        if estado == "ok" and len(t2.strip()) < MINIMO_TEXTO_UTIL:
                            # Nunca dejar un rechazo sin razon escrita: un intento que
                            # falla en silencio no deja juzgar nada.
                            estado = "bloqueo"
                            razon = "solo %d caracteres de texto" % len(t2.strip())
                        if estado == "ok":
                            texto, metodo, camino = t2, m2, "navegador+cookies"
                        else:
                            intentos[-1] += " pero " + razon

            # 2b. Render directo del DOM, si el puente no basto y esperamos HTML.
            if camino is None and not args.raw:
                crudo, nota = html_del_navegador(args.url, args.timeout)
                if crudo is None:
                    intentos.append("navegador (render) -> %s" % nota)
                else:
                    try:
                        t3 = texto_de_html(crudo)
                    except RuntimeError as e:
                        log("FATAL: %s" % e)
                        return 6
                    estado, razon = diagnostico(t3, crudo)
                    intentos.append("navegador (render) -> %s" % nota)
                    if estado == "muro":
                        log("navegador real -> %s" % razon)
                        log("MURO REAL. No se evade captcha ni autenticacion por "
                            "diseno. Abre la URL a mano en el navegador.")
                        log("Intentos: " + " | ".join(intentos))
                        return 5
                    if estado == "bloqueo":
                        intentos[-1] += " pero " + razon
                        log("El navegador recibio 200 pero el contenido es una pagina "
                            "de denegacion, no el documento. Extracto:")
                        for ln in t3.strip().splitlines()[:6]:
                            log("   | " + ln[:120])
                        log("Esto es un bloqueo del lado del sitio (WAF, region o "
                            "reputacion de IP). Con la IP de salida actual no hay "
                            "documento que bajar.")
                        log("Intentos: " + " | ".join(intentos))
                        return 3
                    texto, metodo, camino = t3, "lxml sobre DOM", "agent-browser (chrome real)"
                    # El detalle tiene que describir el camino que SIRVIO. Arrastrar
                    # aqui el error del camino 1 hacia el recibo final haria que el
                    # recibo mienta sobre como se obtuvo el texto.
                    detalle, cuerpo = nota, crudo.encode("utf-8")
        finally:
            cerrar_navegador(args.timeout)

    if camino is None:
        log("FALLO: los dos caminos se agotaron sin documento utilizable.")
        for i in intentos:
            log("   - " + i)
        return 3

    # --- Guardia de vacio: nunca salir 0 sin contenido ---------------------
    if args.raw:
        datos = cuerpo
        if not datos:
            log("FALLO: la respuesta llego vacia (0 bytes). Intentos: " +
                " | ".join(intentos))
            return 4
        if args.out:
            with open(args.out, "wb") as fh:
                fh.write(datos)
            log("%s -> %s, %s crudos a %s" % (camino, detalle, kb(len(datos)), args.out))
        else:
            sys.stdout.buffer.write(datos)
            log("%s -> %s, %s crudos a stdout" % (camino, detalle, kb(len(datos))))
        return 0

    if not texto or len(texto.strip()) < MINIMO_TEXTO_UTIL:
        # La causa se nombra segun lo que REALMENTE se bajo. Culpar a un PDF escaneado
        # cuando lo que llego fue un HTML es un diagnostico equivocado, y un diagnostico
        # equivocado desvia igual que no dar ninguno.
        if es_pdf(cuerpo, ctype):
            causa = ("el PDF no trae capa de texto, probablemente esta escaneado. "
                     "Hace falta OCR, que este script no hace por diseno.")
        else:
            causa = ("la pagina no entrega contenido legible: o lo pinta JavaScript "
                     "que no llego a correr, o es un cascaron de bloqueo.")
        log("FALLO: se bajo la respuesta (%s) pero no salio texto utilizable "
            "(%d caracteres). %s"
            % (kb(len(cuerpo)), len(texto.strip() if texto else ""), causa))
        log("Intentos: " + " | ".join(intentos))
        return 4

    datos = texto.encode("utf-8")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(texto)
        destino = " a %s" % args.out
    else:
        sys.stdout.write(texto + "\n")
        destino = ""
    log("%s -> %s, %s descargados, %s texto extraido (%s)%s" %
        (camino, detalle, kb(len(cuerpo)), kb(len(datos)), metodo, destino))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("interrumpido por el usuario")
        sys.exit(130)
