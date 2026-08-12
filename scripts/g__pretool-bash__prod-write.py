#!/usr/bin/env python3
"""PreToolUse Bash hook — compuerta de ESCRITURA EN PRODUCCION (FAIL-CLOSED).

Por que existe: en una sola sesion tres agentes distintos escribieron a produccion
(sobrescribir /opt y /etc de una instancia EC2 por `aws ssm send-command`, reiniciar
servicios vivos, limpiar estado, desplegar un Worker con `npx wrangler deploy`) y el
arnes levanto alerta las tres veces con la misma razon: no habia mensaje visible del
operador autorizando el despliegue. La autorizacion existia, pero vivia solo en las
instrucciones que el agente orquestador le paso a cada constructor. Nadie la exigia y
nadie la registraba. Esta compuerta la exige y la registra.

Frontera de seguridad (misma postura que qa-merge-gate.py):
  - El match por regex sobre el comando es un tope para el error honesto. La frontera
    real es el canal de aprobacion A PRUEBA DE AGENTE: un hook PreToolUse corre en el
    proceso del ARNES, asi que un `OCTO_PROD_APPROVE=x aws ssm send-command ...` en
    linea NO llega hasta aca. Solo quien hace `export` en su propia terminal antes de
    lanzar Claude Code puede prender esa variable.
  - La indireccion de shell (`bash -c "$(echo aws) ssm ..."`, `$(...)`) sigue siendo
    riesgo residual aceptado por diseno, igual que en qa-merge-gate.

Canales de aprobacion, los dos POR DESTINO y con caducidad corta:
  1. OCTO_PROD_APPROVE=<destino>[,<destino>...]  env, a prueba de agente. Preferido.
  2. ~/.claude/connectome/prod-approvals.json    archivo, lo escribe
     `octo-dim.py approve-prod <destino>`, que se NIEGA a correr cuando detecta que
     lo invoca un agente (CLAUDECODE en el ambiente). El agente todavia podria
     fabricar el JSON a mano; eso es ruidoso y auditable, y el canal env sigue siendo
     la frontera real.

Ventana: 600 s (10 min) por omision. Justificacion: la aprobacion debe cubrir UNA
operacion, no una jornada. Un despliegue de Worker o un round trip de SSM se mide en
minutos, no en horas, y el incidente que motivo esta compuerta fue justamente una
autorizacion que se quedo viva mas alla del momento en que se dio. qa-merge-gate usa
900 s para merges; una escritura a produccion es mas consecuente, asi que la ventana
es mas corta, no mas larga.

Aprobar un destino NO aprueba otro: el token se compara por igualdad exacta contra
cada destino que el comando toca, y si el comando toca varios, TODOS deben estar
aprobados.

Direccion fail-closed: en cuanto se identifica positivamente un canal de escritura a
produccion, cualquier duda posterior (payload ilegible, destino irresoluble, crash del
propio hook) DENIEGA. Solo un comando positivamente clasificado como lectura pasa.

Cero falsos positivos en lectura es requisito duro: si esto bloquea un
`aws ec2 describe-instances`, alguien lo apaga y entonces no protege nada.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Fuerza UTF-8 en stdout/stderr para que los glifos ✓ / ✗ sobrevivan en shells
# de Windows que arrancan en cp1252. Mismo preambulo que el resto de los hooks.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


_APPROVALS_FILE = Path.home() / ".claude" / "connectome" / "prod-approvals.json"
_TTL_DEFAULT = 600  # segundos; ver la nota de ventana en el docstring

# Se prende en cuanto un canal de escritura a produccion queda identificado. El
# manejador de __main__ lee esta bandera para decidir si un crash abre o cierra.
_PROD_IDENTIFIED = False


# ---------------------------------------------------------------------------
# Corte del comando en sub-comandos reales, respetando comillas.
# Copiado a proposito en vez de importado: un hook debe ser autocontenido. Un
# modulo compartido roto tumbaria TODAS las compuertas a la vez, y ese es el
# mismo patron que ya siguen qa-merge-gate.py y g__pretool-bash__git-discipline.py.
# ---------------------------------------------------------------------------

def _join_continuations(cmd: str) -> str:
    """Une las continuaciones backslash-newline para no cortar un token a la mitad."""
    return re.sub(r"\\\n", " ", cmd)


def _split_subcmds(cmd: str) -> list:
    """Corta en ; && || | y newline, pero solo FUERA de comillas.

    Sin esto, un `git commit -m "wrangler deploy quedo listo"` dispararia la
    compuerta por una mencion dentro de un argumento entrecomillado.
    """
    parts: list = []
    buf: list = []
    in_single = False
    in_double = False
    i = 0
    n = len(cmd)
    while i < n:
        ch = cmd[i]
        if ch == "'" and not in_double:
            in_single = not in_single
            buf.append(ch)
            i += 1
        elif ch == '"' and not in_single:
            in_double = not in_double
            buf.append(ch)
            i += 1
        elif not in_single and not in_double:
            if cmd[i:i + 2] in ("&&", "||"):
                parts.append("".join(buf))
                buf = []
                i += 2
            elif ch in (";", "|", "\n"):
                parts.append("".join(buf))
                buf = []
                i += 1
            else:
                buf.append(ch)
                i += 1
        else:
            buf.append(ch)
            i += 1
    parts.append("".join(buf))
    return parts


# Envoltorios que hay que pelar antes de anclar el patron al inicio del sub-comando.
# Sin pelarlos, `env A=1 command npx wrangler deploy` se escapa del ancla.
_W_GROUP = re.compile(r"^[({]\s*")
_W_ASSIGN = re.compile(r"^[A-Za-z_]\w*=\S*\s+")
_W_REDIR = re.compile(r"^\d*[<>]+\S*\s+")
_W_ENV = re.compile(r"^env\b\s*")
_W_ENVARG = re.compile(r"^(?:-\S+|[A-Za-z_]\w*=\S*)\s+")
_W_COMMAND = re.compile(r"^command\s+")
_W_SUDO = re.compile(r"^sudo\s+(?:-\S+\s+|-u\s+\S+\s+)*")
_W_TIME = re.compile(r"^(?:time|nohup|nice(?:\s+-n\s+\S+)?|timeout\s+\S+)\s+")


def _strip_leading(s: str) -> str:
    """Quita agrupadores, asignaciones, redirecciones, env, command, sudo y timeout."""
    s = s.lstrip()
    prev = None
    while s != prev:
        prev = s
        for pat in (_W_GROUP, _W_ASSIGN, _W_REDIR, _W_COMMAND, _W_SUDO, _W_TIME):
            m = pat.match(s)
            if m:
                s = s[m.end():]
                break
        else:
            m = _W_ENV.match(s)
            if m:
                s = s[m.end():]
                while True:
                    m2 = _W_ENVARG.match(s)
                    if not m2:
                        break
                    s = s[m2.end():]
    return s


def _effective_cwd(cmd: str, matched_sub: str, session_cwd: str) -> str:
    """cwd de la sesion ajustado por los `cd` que van ANTES del sub-comando visto.

    Solo entiende `cd <ruta>` plano. `cd -`, `pushd` y subshells quedan sin ajustar,
    lo que solo puede sobre-resolver, nunca sub-resolver.
    """
    cwd = session_cwd or os.getcwd()
    for raw in _split_subcmds(_join_continuations(cmd)):
        if raw == matched_sub:
            break
        m = re.match(r"^cd\s+(\S+)", _strip_leading(raw).strip())
        if m:
            p = os.path.expanduser(m.group(1).strip("'\""))
            cwd = p if os.path.isabs(p) else os.path.join(cwd, p)
    return cwd


# ---------------------------------------------------------------------------
# Deteccion de escritura dentro de un payload remoto (SSM, ssh).
# ---------------------------------------------------------------------------

# Rutas del host que cuentan como produccion. La mirada atras (?<![\w/]) evita que
# `s3://bucket/opt/x` cuente como /opt: ahi el slash viene pegado a una palabra.
_PROTECTED = r"/(?:opt|etc|usr|var/lib)(?:/|\b)"
_PROTECTED_RE = re.compile(r"(?<![\w/])" + _PROTECTED)

# Redireccion a una ruta protegida: > /etc/x  o  >> "/opt/y"
_REDIR_PROT_RE = re.compile(r">>?\s*\\?['\"]?" + _PROTECTED)

# Postura DENTRO del payload remoto: si la unidad menciona una ruta protegida, se
# deniega salvo que su primer token este en la allowlist explicita de lectura.
# Una lista de verbos de escritura no sirve aca: en produccion nadie manda `cp`
# suelto por SSM, manda un script (`bash /opt/app/deploy.sh`, `tar xzf ... -C /opt`,
# `make -C /opt install`, `docker compose -f /opt/... up -d`). Enumerar escrituras
# es una carrera perdida; enumerar lecturas es finito y auditable.
_READ_ONLY_CMDS = {
    "cat", "bat", "less", "more", "head", "tail", "nl", "tac", "strings",
    "ls", "dir", "tree", "stat", "file", "readlink", "realpath", "dirname", "basename",
    "grep", "egrep", "fgrep", "rg", "ag", "awk", "cut", "sort", "uniq", "wc", "tr",
    "diff", "cmp", "md5sum", "sha1sum", "sha256sum", "cksum", "b2sum",
    "du", "df", "lsblk", "blkid", "mountpoint", "findmnt",
    "journalctl", "dmesg", "systemctl", "service", "systemd-analyze",
    "ps", "pgrep", "top", "uptime", "free", "vmstat", "iostat", "uname", "hostname",
    "id", "whoami", "groups", "date", "env", "printenv", "echo", "printf",
    "which", "type", "command", "pwd", "getent", "getconf",
    "ss", "netstat", "ip", "ifconfig", "dig", "host", "nslookup", "ping",
    "jq", "yq", "xmllint", "base64", "openssl", "test", "[",
    "sqlite3", "psql", "mysql", "redis-cli", "aws", "curl", "wget", "sed", "find",
    "python", "python3", "perl", "ruby", "node", "true", "false", ":",
}

# systemctl / service: solo los verbos de CICLO DE VIDA escriben.
# is-active, is-enabled, show, status, cat, list-units son lectura y deben pasar.
# Los limites \b bastan: "status" no contiene "stop" y "is-enabled" no casa \benable\b.
_SYSTEMCTL_WRITE_RE = re.compile(
    r"\b(?:start|restart|stop|reload|daemon-reload|daemon-reexec|enable|disable|"
    r"mask|unmask|kill|isolate|set-property|edit|link|revert|reset-failed)\b"
)

# Separadores dentro de un payload: los de shell, los de un arreglo JSON y el
# salto de linea ESCAPADO (\n literal, dos caracteres). Ese ultimo es el caso que
# importa: un script de despliegue viaja como UNA sola entrada de `commands` con
# los renglones unidos por \n, asi que sin partirlo ahi todo el script queda en una
# unidad y solo se mira su primer token.
_UNIT_SPLIT_RE = re.compile(
    r"&&|\|\||[;|\n\r]|\\{1,2}[nr]|\\?\",\s*\\?\"|',\s*'"
)


def _wrapping_quote(s: str):
    """Si s es EXACTAMENTE una cadena entre comillas (la que abre en 0 cierra
    en el ultimo caracter y nunca antes), devuelve el interior; si no, None.
    Pelar sin verificar que envuelven era un bypass: en
    `'cat /a' && cp x /etc/y && echo 'z'` el primer y ultimo caracter son la
    misma comilla sin ser par, y recortarlos corrompia la cadena hasta fundir
    el `cp` dentro de una comilla fantasma."""
    if len(s) < 2 or s[0] not in "'\"":
        return None
    q = s[0]
    i, n = 1, len(s)
    while i < n:
        ch = s[i]
        if q == '"' and ch == "\\" and i + 1 < n:
            i += 2
            continue
        if ch == q:
            return s[1:-1] if i == n - 1 else None
        i += 1
    return None  # nunca cerro: desbalanceada, que decida el llamador


def _unquote_wrap(s: str) -> str:
    """Pela capas de comillas que envuelven de verdad, con unescape de \\" al
    pelar dobles. Idempotente sobre cadenas sin envoltura."""
    while True:
        inner = _wrapping_quote(s)
        if inner is None:
            return s
        if s[0] == '"':
            inner = inner.replace('\\"', '"')
        s = inner.strip()


def _split_top(s: str, commas: bool = False):
    """Corta una linea de shell en unidades SOLO por separadores de nivel
    superior (;, |, &&, ||, saltos, \\n literales y, opcionalmente, comas).
    Dentro de comillas nada corta: un `;` en un one-liner de python -c es
    contenido, no separador. Devuelve None si las comillas quedan
    DESBALANCEADAS: una comilla sin cerrar puede estar ocultando un separador
    y con ella no se clasifica, se deniega."""
    units, buf = [], []
    q = ""
    i, n = 0, len(s)

    def flush():
        u = "".join(buf).strip()
        if u:
            units.append(u)
        buf.clear()

    while i < n:
        ch = s[i]
        if q:
            if q == '"' and ch == "\\" and i + 1 < n:
                buf.append(ch)
                buf.append(s[i + 1])
                i += 2
                continue
            if ch == q:
                q = ""
            buf.append(ch)
            i += 1
            continue
        if ch in "'\"":
            q = ch
            buf.append(ch)
            i += 1
            continue
        if s.startswith("&&", i) or s.startswith("||", i):
            flush()
            i += 2
            continue
        if ch in ";|\n\r" or (commas and ch == ","):
            flush()
            i += 1
            continue
        if ch == "\\" and i + 1 < n and s[i + 1] in "nr":
            flush()
            i += 2
            continue
        buf.append(ch)
        i += 1
    if q:
        return None
    flush()
    return units


def _split_units(payload: str):
    """Unidades de comando de un payload. Devuelve la lista, o None si el
    payload no se puede cortar con certeza (JSON ilegible o comillas
    desbalanceadas) y entonces el llamador deniega en vez de adivinar.
    Niveles: `commands=[...]` se parsea como JSON; la forma corta del CLI
    (`commands="c1","c2"` o `commands="c1; c2"`) se parte por comas de nivel
    superior y cada elemento se desenvuelve; todo elemento se corta al final
    como shell de nivel superior."""
    s = _unquote_wrap(payload.strip())
    m = re.match(r"^\s*(?:\{\s*\"?commands\"?\s*[:=]|commands\s*=)\s*(.*)$", s, re.S)
    if m:
        val = m.group(1).strip()
        if val.startswith("["):
            try:
                elems = json.loads(val.rstrip("}").strip())
            except ValueError:
                return None
            if not isinstance(elems, list):
                return None
            units = []
            for e in elems:
                sub_units = _split_top(str(e))
                if sub_units is None:
                    return None
                units.extend(sub_units)
            return units
        parts = _split_top(val, commas=True)
        if parts is None:
            return None
        units = []
        for p in parts:
            sub_units = _split_top(_unquote_wrap(p))
            if sub_units is None:
                return None
            units.extend(sub_units)
        return units
    return _split_top(s)

# Prefijos que hay que pelar de cada unidad del payload antes de mirar su primer token.
_UNIT_LEAD_PATS = (
    re.compile(r"^[\s\[\]{}()'\"\\]+"),
    re.compile(r"^(?:commands|parameters|Values|Key|workingDirectory|executionTimeout)=", re.I),
    re.compile(r"^sudo\s+(?:-\S+\s+|-u\s+\S+\s+)*"),
    re.compile(r"^env\s+"),
    re.compile(r"^[A-Za-z_]\w*=\S*\s+"),
    re.compile(r"^(?:/bin/|/usr/bin/)?(?:ba|z|k|da)?sh\s+-[a-z]*c\s+"),
    re.compile(r"^(?:time|nohup|nice|exec)\s+"),
)


def _norm_unit(u: str) -> str:
    """Pela envoltorios y ruido JSON hasta dejar el primer token real de la unidad."""
    prev = None
    s = u
    while s != prev:
        prev = s
        for pat in _UNIT_LEAD_PATS:
            m = pat.match(s)
            if m and m.end() > 0:
                s = s[m.end():]
                break
    return s.strip()


def _read_only_disqualifier(cmd0: str, u: str) -> str:
    """Motivo por el que un comando de la allowlist DEJA de ser lectura en esta unidad."""
    if cmd0 == "sed" and re.search(r"(?:^|\s)-[a-zA-Z]*i", u):
        return "sed -i edita en sitio"
    if cmd0 in ("curl", "wget") and re.search(r"(?:^|\s)(?:-o|-O|--output(?:-document)?)\b", u):
        return "la descarga se escribe en disco"
    if cmd0 == "find" and re.search(r"(?:^|\s)-(?:delete|exec|execdir|ok)\b", u):
        return "find con -delete/-exec ejecuta acciones sobre lo que encuentra"
    if cmd0 in ("python", "python3", "perl", "ruby", "node") and "mode=ro" not in u:
        # Un interprete es codigo arbitrario. Solo pasa cuando declara lectura
        # explicita (sqlite abierto con mode=ro es el caso legitimo del brief).
        return "interprete con codigo arbitrario y sin mode=ro declarado"
    if cmd0 in ("sqlite3", "psql", "mysql", "redis-cli") and not re.search(
            r"(?i)\b(?:select|show|describe|explain|pragma|\\d|info|get|keys|ttl)\b", u):
        return "cliente de base sin una consulta de lectura visible"
    if cmd0 == "aws":
        service, op = _aws_service_op(u)
        if not op or not _AWS_READ_PREFIX.match(op):
            return f"aws {service or '?'} {op or '?'} no es una operacion de lectura"
    if cmd0 in ("systemctl", "service") and _SYSTEMCTL_WRITE_RE.search(u):
        return "verbo de ciclo de vida"
    return ""


def _unit_write_reason(unit: str) -> str:
    """Devuelve el motivo si esta unidad del payload ESCRIBE, o cadena vacia si lee."""
    u = _norm_unit(unit)
    if not u:
        return ""

    # Redireccion a ruta protegida: aplica sin importar cual sea el verbo.
    if _REDIR_PROT_RE.search(u):
        return "redireccion (> o >>) hacia una ruta protegida"

    # systemctl y systemd-run escriben sin nombrar ninguna ruta.
    if re.match(r"^(?:systemctl|service)\b", u) and _SYSTEMCTL_WRITE_RE.search(u):
        return "systemctl con verbo de ciclo de vida (start/restart/stop/enable/daemon-reload)"
    if re.match(r"^systemd-run\b", u):
        return "systemd-run ejecuta una unidad arbitraria en el host"

    # Inversion fail-closed: ruta protegida presente => se deniega salvo lectura probada.
    if not _PROTECTED_RE.search(u):
        return ""
    cmd0 = os.path.basename((u.split() or [""])[0]).strip("'\"")
    if cmd0 not in _READ_ONLY_CMDS:
        return (f"'{cmd0}' toca una ruta protegida y no esta en la allowlist de lectura "
                f"(un script, un extractor o un runner escriben lo que quieran)")
    dq = _read_only_disqualifier(cmd0, u)
    if dq:
        return f"'{cmd0}' sobre una ruta protegida: {dq}"
    return ""


def _payload_write_reason(payload: str) -> str:
    """Primer motivo de escritura hallado en el payload, o cadena vacia si todo es lectura."""
    units = _split_units(payload)
    if units is None:
        return "lista de comandos ilegible: no se puede clasificar y no se adivina"
    for unit in units:
        r = _unit_write_reason(unit)
        if r:
            return r
    return ""


# ---------------------------------------------------------------------------
# Clasificacion por canal.
# Cada clasificador devuelve None (no es escritura a produccion) o una tupla
# (destinos, motivo). destinos es una lista no vacia de tokens aprobables.
# ---------------------------------------------------------------------------

def _tokens(sub: str) -> list:
    """Tokeniza barato respetando comillas simples y dobles."""
    out = re.findall(r"'[^']*'|\"[^\"]*\"|\S+", sub)
    return [t.strip("'\"") for t in out]


def _flag_values(sub: str, flag: str) -> list:
    """Valores de --flag v1 v2 / --flag=v1,v2 hasta la siguiente bandera."""
    toks = _tokens(sub)
    vals: list = []
    i = 0
    while i < len(toks):
        t = toks[i]
        if t == flag:
            j = i + 1
            while j < len(toks) and not toks[j].startswith("-"):
                vals.extend([v for v in re.split(r"[,\s]+", toks[j]) if v])
                j += 1
            i = j
            continue
        if t.startswith(flag + "="):
            vals.extend([v for v in re.split(r"[,\s]+", t[len(flag) + 1:]) if v])
        i += 1
    return vals


def _sanitize(tok: str) -> str:
    """Token de destino legible y tecleable: sin espacios ni comillas."""
    t = re.sub(r"\s+", "", tok.strip().strip("'\""))
    return t or "unresolved"


def _fallback_dest(channel: str, sub: str) -> str:
    """Destino estable cuando no se puede resolver. Es tecleable y determinista."""
    h = hashlib.sha1(sub.strip().encode("utf-8", "replace")).hexdigest()[:8]
    return f"{channel}:unresolved-{h}"


# --- AWS ------------------------------------------------------------------

# Banderas globales de la CLI que van entre `aws` y el servicio.
_AWS_GLOBAL_WITH_VAL = {
    "--region", "--profile", "--output", "--endpoint-url", "--color",
    "--cli-read-timeout", "--cli-connect-timeout", "--ca-bundle", "--query",
}
_AWS_GLOBAL_FLAGS = {"--no-cli-pager", "--no-verify-ssl", "--debug", "--no-paginate", "--no-sign-request"}

# Prefijos de operacion que son SIEMPRE lectura. Esta lista es lo que garantiza
# cero falsos positivos: se evalua antes que cualquier regla destructiva.
_AWS_READ_PREFIX = re.compile(
    r"^(?:describe|get|list|search|lookup|head|batch-get|select|scan|query|"
    r"filter|preview|estimate|simulate|generate-credential-report|wait|help|"
    r"test-|check-|validate|view|export-)"
)

# Operaciones destructivas por servicio. Se comparan contra la operacion completa.
_AWS_DESTRUCTIVE = {
    "ec2": r"^(?:terminate-instances|stop-instances|reboot-instances|start-instances|"
           r"delete-.*|modify-instance-attribute|detach-volume|revoke-.*|authorize-.*)$",
    "iam": r"^(?:put-role-policy|put-user-policy|put-group-policy|attach-role-policy|"
           r"attach-user-policy|attach-group-policy|detach-.*|delete-.*|"
           r"update-assume-role-policy|create-access-key|remove-role-from-instance-profile)$",
    "secretsmanager": r"^(?:put-secret-value|delete-secret|update-secret|create-secret|"
                      r"restore-secret|rotate-secret|tag-resource)$",
    "ssm": r"^(?:start-session|put-parameter|delete-parameter|delete-parameters|"
           r"delete-document|update-document|create-document)$",
    "lambda": r"^(?:update-function-code|update-function-configuration|delete-function|"
              r"add-permission|remove-permission|publish-version|update-alias)$",
    "ecs": r"^(?:update-service|delete-service|stop-task|delete-cluster|"
           r"register-task-definition|deregister-task-definition)$",
    "rds": r"^(?:delete-db-instance|delete-db-cluster|modify-db-instance|modify-db-cluster|"
           r"reboot-db-instance|stop-db-instance|restore-.*)$",
    "cloudformation": r"^(?:deploy|delete-stack|update-stack|create-stack|execute-change-set)$",
    "s3api": r"^(?:delete-bucket|delete-bucket-policy|delete-objects?|put-bucket-policy|"
             r"put-bucket-acl|delete-bucket-website)$",
    "elbv2": r"^(?:delete-.*|modify-.*|set-.*)$",
    "autoscaling": r"^(?:delete-.*|update-auto-scaling-group|terminate-instance-in-auto-scaling-group|"
                   r"set-desired-capacity)$",
    "route53": r"^change-resource-record-sets$",
    "cloudfront": r"^(?:create-invalidation|update-distribution|delete-distribution)$",
}

# Banderas de las que se saca el destino, por servicio.
_AWS_DEST_FLAGS = {
    "ec2": ["--instance-ids", "--instance-id"],
    "iam": ["--role-name", "--user-name", "--group-name", "--policy-arn"],
    "secretsmanager": ["--secret-id"],
    "lambda": ["--function-name"],
    "ecs": ["--service", "--cluster"],
    "rds": ["--db-instance-identifier", "--db-cluster-identifier"],
    "cloudformation": ["--stack-name"],
    "s3api": ["--bucket"],
    "elbv2": ["--load-balancer-arn", "--target-group-arn"],
    "autoscaling": ["--auto-scaling-group-name"],
    "route53": ["--hosted-zone-id"],
    "cloudfront": ["--distribution-id"],
    "ssm": ["--instance-ids", "--name"],
}


def _aws_service_op(sub: str):
    """(servicio, operacion) de un sub-comando `aws ...`, o (None, None)."""
    toks = _tokens(sub)
    if not toks or os.path.basename(toks[0]) != "aws":
        return None, None
    i = 1
    while i < len(toks):
        t = toks[i]
        if t in _AWS_GLOBAL_WITH_VAL:
            i += 2
            continue
        if t in _AWS_GLOBAL_FLAGS or (t.startswith("--") and "=" in t):
            i += 1
            continue
        if t.startswith("-"):
            i += 1
            continue
        break
    if i >= len(toks):
        return None, None
    service = toks[i]
    op = toks[i + 1] if i + 1 < len(toks) else ""
    return service, op


def _ssm_destinations(sub: str) -> list:
    """Instancias o targets que toca un send-command."""
    dests = [d for d in _flag_values(sub, "--instance-ids") if d]
    dests += [d for d in _flag_values(sub, "--instance-id") if d]
    if not dests:
        # --targets "Key=instanceids,Values=i-1,i-2"  o  Key=tag:Name,Values=web
        for raw in re.findall(r"--targets[=\s]+((?:'[^']*'|\"[^\"]*\"|\S+)(?:\s+(?!-)\S+)*)", sub):
            raw = raw.strip().strip("'\"")
            vals = re.findall(r"Values=([^,\s\"']+(?:,[^,\s\"']+)*)", raw)
            if vals:
                for v in vals:
                    dests.extend([x for x in v.split(",") if x])
            elif raw:
                dests.append(raw)
    return [_sanitize(d) for d in dests if d]


def _ssm_payload(sub: str) -> str:
    """Texto del payload de un send-command, o cadena vacia si no se puede ver."""
    if re.search(r"--(?:parameters|cli-input-json)[=\s]+\S*file://", sub):
        return ""  # el payload vive en un archivo: ilegible desde aca
    m = re.search(r"--parameters\b", sub)
    if m:
        return sub[m.end():]
    m = re.search(r"--cli-input-json\b", sub)
    if m:
        return sub[m.end():]
    return ""


def _classify_aws(sub: str):
    service, op = _aws_service_op(sub)
    if service is None:
        return None

    # `aws s3` no expone operaciones con prefijo; se trata aparte y de forma angosta
    # para no romper el flujo diario de cp/sync hacia buckets de trabajo.
    if service == "s3":
        # --dryrun solo lista lo que borraria. Es el paso de preview obligatorio.
        if re.search(r"(?:^|\s)--dry-?run\b", sub):
            return None
        if op == "rb" or (op == "rm" and re.search(r"(?:^|\s)--recursive\b", sub)):
            bucket = next((t for t in _tokens(sub) if t.startswith("s3://")), None)
            return ([_sanitize(bucket or _fallback_dest("s3", sub))],
                    f"aws s3 {op} borra objetos o un bucket completo")
        return None

    if not op:
        return None

    # Lectura primero. Esto es lo que mantiene el ruido en cero.
    if _AWS_READ_PREFIX.match(op):
        return None

    if service == "ssm" and op == "send-command":
        payload = _ssm_payload(sub)
        dests = _ssm_destinations(sub) or [_fallback_dest("ssm", sub)]
        if not payload:
            return (dests,
                    "aws ssm send-command con payload ilegible "
                    "(file:// o sin --parameters): no se puede clasificar, se deniega")
        if re.search(r"AWS-Run(?:PowerShell|Remote)\w*", sub, re.I):
            # El escaner razona en shell POSIX. Un payload de PowerShell (rutas
            # C:\, Copy-Item, Set-Content) no se puede clasificar aqui, asi que
            # se deniega en vez de dejarlo pasar por no entenderlo.
            return (dests,
                    "payload de PowerShell: el escaner solo clasifica shell POSIX, "
                    "no se puede decidir y se deniega")
        reason = _payload_write_reason(payload)
        if reason:
            return (dests, f"payload de SSM escribe en el host: {reason}")
        return None  # payload de solo lectura: pasa sin ruido

    pat = _AWS_DESTRUCTIVE.get(service)
    if pat and re.match(pat, op):
        dests: list = []
        for flag in _AWS_DEST_FLAGS.get(service, []):
            dests += _flag_values(sub, flag)
        dests = [_sanitize(d) for d in dests if d] or [_fallback_dest(service, sub)]
        return (dests, f"aws {service} {op} modifica o destruye un recurso vivo")

    return None


# --- Wrangler / Cloudflare -------------------------------------------------

# Envoltorios de ejecucion de paquetes. Se pelan para llegar al token `wrangler`.
# Incluye la forma corta de pnpm y yarn (`pnpm wrangler deploy`), que no lleva
# ni dlx ni exec y por eso se colaba.
_RUNNER_RE = re.compile(
    r"^(?:npx|bunx|(?:pnpm|yarn|npm|bun)(?:\s+(?:dlx|exec|x|run))?)\s+"
    r"(?:-[-\w]+(?:=\S+)?\s+)*"
)

_WRANGLER_WRITE = (
    r"^(?:deploy|publish|delete|rollback|"
    r"secret\s+(?:put|delete|bulk)|"
    r"kv\s+key\s+(?:put|delete)|kv:key\s+(?:put|delete)|"
    r"kv\s+bulk\s+(?:put|delete)|kv:bulk\s+(?:put|delete)|"
    r"kv\s+namespace\s+(?:create|delete|rename)|kv:namespace\s+(?:create|delete)|"
    r"pages\s+(?:deploy|publish)|pages\s+project\s+(?:create|delete)|"
    r"pages\s+secret\s+(?:put|delete|bulk)|"
    r"r2\s+object\s+(?:put|delete)|r2\s+bucket\s+(?:create|delete)|"
    r"d1\s+(?:delete|create)|"
    r"versions\s+(?:deploy|upload)|deployments\s+rollback|triggers\s+deploy|"
    r"queues\s+(?:create|delete)|dispatch-namespace\s+(?:create|delete)|"
    r"hyperdrive\s+(?:create|delete|update)|vectorize\s+(?:create|delete|insert|upsert))\b"
)

# Lectura explicita. Generosa a proposito: un wrangler de lectura jamas debe hacer ruido.
_WRANGLER_READ = (
    r"^(?:whoami|tail|dev|login|logout|init|generate|types|docs|check|"
    r"secret\s+list|"
    r"kv\s+key\s+(?:get|list)|kv:key\s+(?:get|list)|"
    r"kv\s+namespace\s+list|kv:namespace\s+list|"
    r"pages\s+(?:project\s+list|deployment\s+list|download)|"
    r"r2\s+(?:object\s+get|bucket\s+list)|"
    r"d1\s+(?:list|info|migrations\s+list)|"
    r"deployments\s+(?:list|view|status)|versions\s+(?:list|view)|"
    r"queues\s+list|hyperdrive\s+list|vectorize\s+list)\b"
)

_WRANGLER_CONFIGS = ("wrangler.jsonc", "wrangler.json", "wrangler.toml")


def _wrangler_config_name(cwd: str) -> str:
    """Nombre del Worker leido del wrangler.* del directorio efectivo."""
    for fn in _WRANGLER_CONFIGS:
        p = Path(cwd) / fn
        try:
            txt = p.read_text(encoding="utf-8")
        except OSError:
            continue
        m = re.search(r'^\s*"?name"?\s*[:=]\s*"([^"]+)"', txt, re.MULTILINE)
        if m:
            return m.group(1)
    return ""


_WRANGLER_READ_VERBS = {"list", "info", "status", "view", "get", "tail",
                        "download", "preview", "help"}


def _wrangler_cmd_path(rest: str) -> list:
    """Tokens de comando de una invocacion wrangler: pela cada flag y su valor
    (`--flag valor` y `--flag=valor`). Lo que queda son sub-comandos y
    posicionales; un posicional nunca convierte lectura en escritura porque la
    rama de escritura se evalua aparte y gana."""
    toks = rest.split()
    path = []
    i = 0
    while i < len(toks):
        t = toks[i]
        if t.startswith("-"):
            if "=" not in t and i + 1 < len(toks) and not toks[i + 1].startswith("-"):
                i += 2
                continue
            i += 1
            continue
        path.append(t)
        i += 1
    return path


def _classify_wrangler(sub: str, cmd: str, raw_sub: str, session_cwd: str):
    s = sub
    m = _RUNNER_RE.match(s)
    if m:
        s = s[m.end():]
    # Acepta wrangler invocado por ruta absoluta o relativa, no solo por nombre pelado.
    m = re.match(r"^(?:[\w./~-]*/)?wrangler(?:@[\w.^~-]+)?(?:\s+(.*))?$", s, re.S)
    if m is None:
        return None
    rest = (m.group(1) or "").strip()

    if not rest or re.match(r"^(?:-h|--help|-v|--version)\b", rest):
        return None
    if re.match(_WRANGLER_READ, rest):
        return None
    # --dry-run compila local y no toca Cloudflare. Es el chequeo previo estandar,
    # bloquearlo es ruido puro.
    if re.search(r"(?:^|\s)--dry-run\b", rest):
        return None
    # Cualquier sub-comando cuyo CAMINO de comando trae un verbo de consulta es
    # lectura, siempre que ninguna rama de escritura conocida aplique. Cubre
    # `r2 bucket info`, `d1 time-travel info`, `pages deployment tail`,
    # `telemetry status` sin tener que enumerar cada rama del CLI. El camino se
    # calcula pelando flags Y sus valores: mirar el "ultimo token pelado"
    # tropezaba con el posicional final (`r2 bucket info MI-BUCKET`) y con el
    # valor de un flag (`pages deployment tail --project-name X`).
    if (any(t in _WRANGLER_READ_VERBS for t in _wrangler_cmd_path(rest))
            and not re.match(_WRANGLER_WRITE, rest)
            and not re.match(r"^d1\s+(?:execute|migrations)\b", rest)):
        return None

    # d1 execute solo escribe produccion con --remote; en local es flujo diario.
    if re.match(r"^d1\s+execute\b", rest):
        if not re.search(r"(?:^|\s)--remote\b", rest):
            return None
        # Un --command que solo consulta es lectura. Si el SQL viene de --file o
        # trae cualquier verbo de escritura, se deniega.
        cmd_sql = re.search(r"--command[=\s]+('[^']*'|\"[^\"]*\"|\S+)", rest)
        if cmd_sql and not re.search(r"(?:^|\s)--file\b", rest):
            sql = cmd_sql.group(1).strip("'\"")
            if re.match(r"(?i)^\s*(?:select|pragma|explain)\b", sql) and not re.search(
                    r"(?i)\b(?:insert|update|delete|drop|alter|create|replace|attach|vacuum)\b", sql):
                return None
        reason = "wrangler d1 execute --remote corre SQL contra la base de produccion"
    elif re.match(r"^d1\s+migrations\s+apply\b", rest):
        if not re.search(r"(?:^|\s)--remote\b", rest):
            return None
        reason = "wrangler d1 migrations apply --remote migra la base de produccion"
    elif re.match(_WRANGLER_WRITE, rest):
        reason = f"wrangler {' '.join(rest.split()[:3])} publica o modifica un recurso de Cloudflare"
    else:
        # Ni lectura conocida ni escritura conocida: no se puede decidir, se deniega.
        reason = (f"sub-comando de wrangler no reconocido ('{rest.split()[0]}'): "
                  f"la compuerta no puede clasificarlo y no adivina")

    dest = ""
    for flag in ("--name", "--project-name", "--script-name", "--database", "--binding"):
        vals = _flag_values(rest, flag)
        if vals:
            dest = vals[0]
            break
    if not dest:
        m2 = re.match(r"^(?:-n)\s+(\S+)", rest)
        if m2:
            dest = m2.group(1)
    if not dest:
        dest = _wrangler_config_name(_effective_cwd(cmd, raw_sub, session_cwd))
    if not dest:
        dest = _fallback_dest("wrangler", sub)
    return ([_sanitize(dest)], reason)


# --- ssh / scp / rsync remotos --------------------------------------------
# Adicion razonada: una compuerta que cierra la puerta de AWS y deja ssh abierto es
# decoracion. Se dispara SOLO por marcador de escritura en el payload, asi que un
# `ssh host journalctl -u x` pasa sin ruido.

def _classify_remote_shell(sub: str):
    toks = _tokens(sub)
    if not toks:
        return None
    exe = os.path.basename(toks[0])

    if exe == "ssh":
        i = 1
        host = ""
        while i < len(toks):
            t = toks[i]
            if t.startswith("-"):
                # banderas de ssh que consumen un valor
                if re.match(r"^-[bcDEeFIiJLlmOoPpQRSWw]$", t):
                    i += 2
                    continue
                i += 1
                continue
            host = t
            break
        if not host:
            return None
        payload = " ".join(toks[i + 1:]) if i + 1 < len(toks) else ""
        if not payload:
            return None  # sesion interactiva: el arnes no la puede usar, sin ruido
        reason = _payload_write_reason(payload)
        if reason:
            return ([_sanitize(host)], f"ssh ejecuta una escritura en el host remoto: {reason}")
        return None

    if exe in ("scp", "rsync"):
        # Solo el ULTIMO argumento posicional es el DESTINO. Tomar "el ultimo token
        # remoto de la lista" confunde origen con destino y bloquea una descarga de
        # lectura pura (`scp host:/etc/nginx/nginx.conf /tmp/`), que es justo el tipo
        # de ruido que hace que alguien apague la compuerta.
        positional = [t for t in toks[1:] if not t.startswith("-")]
        if not positional:
            return None
        target = positional[-1]
        m = re.match(r"^([\w.-]+@[\w.-]+|[\w][\w.-]*):(.*)$", target)
        if not m:
            return None  # destino local: no es una escritura remota
        host, path = m.group(1), m.group(2)
        if _PROTECTED_RE.search(path):
            return ([_sanitize(host)],
                    f"{exe} copia hacia una ruta protegida del host remoto")
        return None

    return None


# ---------------------------------------------------------------------------

def _classify(cmd: str, session_cwd: str):
    """(raw_sub, destinos, motivo) del primer sub-comando que escribe produccion."""
    cmd = _join_continuations(cmd)
    for raw_sub in _split_subcmds(cmd):
        sub = _strip_leading(raw_sub).strip()
        if not sub:
            continue
        for verdict in (
            _classify_aws(sub),
            _classify_wrangler(sub, cmd, raw_sub, session_cwd),
            _classify_remote_shell(sub),
        ):
            if verdict is not None:
                dests, reason = verdict
                return raw_sub, dests, reason
    return None, [], ""


# ---------------------------------------------------------------------------
# Aprobacion
# ---------------------------------------------------------------------------

def _env_approved() -> set:
    raw = os.environ.get("OCTO_PROD_APPROVE", "")
    return {t.strip() for t in re.split(r"[,\s]+", raw) if t.strip()}


def _file_approvals() -> dict:
    try:
        data = json.loads(_APPROVALS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    ap = data.get("approvals")
    return ap if isinstance(ap, dict) else {}


def _is_fresh(record: dict) -> bool:
    """True si (ahora - ts) cabe dentro del ttl. Cualquier error es False."""
    try:
        ts = datetime.fromisoformat(str(record.get("ts", "")))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        delta = (datetime.now(timezone.utc) - ts).total_seconds()
        return 0 <= delta <= int(record.get("ttl", _TTL_DEFAULT))
    except Exception:
        return False


def _missing_approvals(dests: list) -> list:
    """Destinos SIN aprobacion viva. Vacio quiere decir que todos estan aprobados."""
    env_ok = _env_approved()
    files = _file_approvals()
    missing = []
    for d in dests:
        if d in env_ok:
            continue
        rec = files.get(d)
        if isinstance(rec, dict) and _is_fresh(rec):
            continue
        missing.append(d)
    return missing


def _nudge(text: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": text,
        }
    }))


def _deny(dests: list, missing: list, reason: str, sub: str) -> int:
    joined = " ".join(missing)
    print(
        "✗ PROD-WRITE GATE (fail-closed): escritura a produccion sin autorizacion "
        "explicita del operador.\n"
        f"  Destino(s):   {', '.join(dests)}\n"
        f"  Sin aprobar:  {', '.join(missing)}\n"
        f"  Motivo:       {reason}\n"
        f"  Sub-comando:  {sub.strip()[:200]}\n"
        "  El OPERADOR (no el agente) debe correr UNA de estas EN SU PROPIA TERMINAL:\n"
        f"    export OCTO_PROD_APPROVE={joined}\n"
        f"    python3 ~/.claude/scripts/octo-dim.py approve-prod {joined} --by <nombre>\n"
        f"  La aprobacion es POR DESTINO y caduca en {_TTL_DEFAULT // 60} min. "
        "Aprobar un destino no aprueba los demas.\n"
        "  Un `OCTO_PROD_APPROVE=... <comando>` en linea NO sirve: el hook corre en el "
        "arnes y no ve el env que el agente pone en el prefijo.",
        file=sys.stderr,
    )
    return 2


def main() -> int:
    # stdin ilegible: no hay comando que clasificar, asi que no hay nada que negar.
    # Denegar aqui tumbaria toda llamada a Bash ante un payload raro del arnes.
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    try:
        cmd = (data.get("tool_input") or {}).get("command") or ""
    except Exception:
        return 0
    if not cmd:
        return 0

    session_cwd = data.get("cwd") or ""
    sub, dests, reason = _classify(cmd, session_cwd)
    if sub is None:
        return 0

    # Identificado positivamente: de aqui en adelante un crash CIERRA.
    global _PROD_IDENTIFIED
    _PROD_IDENTIFIED = True

    missing = _missing_approvals(dests)
    if not missing:
        _nudge(f"✓ prod-write gate: destino(s) {', '.join(dests)} con aprobacion viva del operador.")
        return 0
    return _deny(dests, missing, reason, sub)


def _selftest() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import gate_selftest
    argv = sys.argv
    i = argv.index("--selftest")
    fixture = argv[i + 1] if len(argv) > i + 1 else "registry/fixtures/SEC.prod-write-gate"
    return gate_selftest.run_gate_selftest(__file__, fixture)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    try:
        result = main()
    except Exception as exc:
        if _PROD_IDENTIFIED:
            print(
                "✗ PROD-WRITE GATE (fail-closed): la compuerta revento DESPUES de "
                f"identificar una escritura a produccion ({type(exc).__name__}). "
                "Se bloquea en vez de abrir.",
                file=sys.stderr,
            )
            result = 2
        else:
            result = 0  # sin canal identificado, un crash no puede tumbar la sesion
    sys.exit(result)
