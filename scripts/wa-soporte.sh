#!/usr/bin/env bash
# Envia un WhatsApp por el canal de SOPORTE, no por el numero personal del operador.
#
# Por que existe: el MCP `whatsapp` esta cableado al puente personal (puerto 8080).
# Cualquier mcp__whatsapp__send_message sale desde el numero del operador. Para
# hablarle a un cliente el canal correcto es el puente de soporte (puerto 8081).
# Se mando un aviso a una clienta desde el numero personal por no tener esta via.
#
# Uso:  wa-soporte.sh <destinatario> <mensaje>
#       destinatario: telefono con lada sin + ni signos, o JID completo
#
# Adjuntos:  wa-soporte.sh <destinatario> <mensaje> --archivo <ruta-local>
# El puente lee `media_path` en SU disco, y desde el cutover ese disco es el de
# la EC2, no el de aqui. Asi que el archivo viaja: local -> bucket de paso ->
# EC2 -> /api/send. Las dos copias intermedias se borran siempre, tambien si el
# envio falla. Antes esto se hacia a mano en cuatro pasos cada vez.
#
# Menciones (grupos): exporta WA_MENCIONES con los telefonos separados por coma.
# El texto TIENE que traer "@<telefono>" para que WhatsApp lo pinte como etiqueta;
# el celular de quien lee lo cambia por el nombre que tenga guardado. Sin esto la
# mencion no notifica a nadie, se ve como texto gris.
#   WA_MENCIONES=5215550001111 wa-soporte.sh 1203...@g.us "@5215550001111 buenos dias"
set -euo pipefail

PUERTO_SOPORTE=8081
PUERTO_PERSONAL=8080

archivo=""
argumentos=()
while [ $# -gt 0 ]; do
  case "$1" in
    --archivo)
      archivo=${2:-}
      if [ -z "$archivo" ]; then
        echo "--archivo necesita una ruta" >&2
        exit 64
      fi
      shift 2
      ;;
    *)
      argumentos+=("$1")
      shift
      ;;
  esac
done
set -- "${argumentos[@]}"

if [ $# -lt 2 ]; then
  echo "uso: $(basename "$0") <destinatario> <mensaje> [--archivo <ruta>]" >&2
  exit 64
fi

destinatario=$1
shift
mensaje=$*

if [ -n "$archivo" ] && [ ! -f "$archivo" ]; then
  echo "no existe el archivo: $archivo" >&2
  exit 66
fi

# Desde el cutover del 14-ago-2026 el puente vive en la EC2 octorato-ops.
# Camino rapido: el tunel SSM local (localhost:8081). Si el tunel no esta
# (laptop recien encendida, otra maquina, sesion en la nube), NO se cae al
# personal: se envia DIRECTO por SSM ejecutando curl EN el servidor. El canal
# deja de depender de esta laptop; solo pide credenciales AWS dataqbs-ops.
INSTANCIA_PUENTE="i-0c0112bf1431dc99e"
REGION_PUENTE="mx-central-1"
PERFIL_PUENTE="dataqbs-ops"
VIA="tunel"
if ! ss -lnt 2>/dev/null | grep -q ":${PUERTO_SOPORTE} "; then
  VIA="ssm"
fi

# ---- Adjunto: el archivo tiene que existir en el disco DEL PUENTE ----------
# El identificador de la instancia, la region, el perfil y el bucket de paso
# salen de la config PRIVADA, no de aqui: este script se publica.
if [ -n "$archivo" ]; then
  respuesta=$(WA_MENCIONES="${WA_MENCIONES:-}" python3 - "$destinatario" "$mensaje" "$archivo" "$PUERTO_SOPORTE" <<'PY'
import base64, json, os, shlex, subprocess, sys, time, uuid
from pathlib import Path

destinatario, mensaje, archivo, puerto = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
cfg_path = Path.home() / ".claude" / "company" / "config" / "wa-puentes.json"
try:
    remoto = json.loads(cfg_path.read_text())["puentes"]["soporte"]["remoto"]
    instancia, region = remoto["instancia"], remoto["region"]
    perfil, bucket = remoto["perfil"], remoto["bucket_tmp"]
except (OSError, KeyError, ValueError) as e:
    print(json.dumps({"success": False,
                      "message": f"falta puentes.soporte.remoto (instancia/region/perfil/"
                                 f"bucket_tmp) en {cfg_path}: {e}"}))
    raise SystemExit(1)

nombre = os.path.basename(archivo)
clave = f"tmp/wa-adjunto-{uuid.uuid4().hex[:12]}/{nombre}"
aws = ["aws", "--profile", perfil, "--region", region]
s3_uri = f"s3://{bucket}/{clave}"
destino_remoto = f"/tmp/wa-envio-{uuid.uuid4().hex[:8]}"

subida = subprocess.run(aws + ["s3", "cp", archivo, s3_uri, "--only-show-errors"],
                        capture_output=True, text=True, timeout=180)
if subida.returncode != 0:
    print(json.dumps({"success": False,
                      "message": f"no se pudo subir: {subida.stderr.strip()[:200]}"}))
    raise SystemExit(1)

try:
    cuerpo = {"recipient": destinatario, "message": mensaje,
              "media_path": f"{destino_remoto}/{nombre}"}
    menciones = [m.strip() for m in os.environ.get("WA_MENCIONES", "").split(",") if m.strip()]
    if menciones:
        cuerpo["mentions"] = menciones
    b64 = base64.b64encode(json.dumps(cuerpo).encode()).decode()
    # El borrado del temporal remoto va en trap: si el envio falla, el archivo
    # de un cliente NO se queda tirado en el servidor.
    q_dir = shlex.quote(destino_remoto)
    q_uri = shlex.quote(s3_uri)
    q_dst = shlex.quote(f"{destino_remoto}/{nombre}")
    remoto_sh = (
        f"set -e; trap 'rm -rf {q_dir}' EXIT; mkdir -p {q_dir}; "
        f"aws s3 cp {q_uri} {q_dst} --only-show-errors; "
        f"echo {b64} | base64 -d | curl -s -m 60 -X POST http://localhost:{puerto}/api/send "
        f"-H 'Content-Type: application/json' --data-binary @-"
    )
    cid = subprocess.run(aws + ["ssm", "send-command", "--instance-ids", instancia,
                                "--document-name", "AWS-RunShellScript",
                                "--parameters", json.dumps({"commands": [remoto_sh]}),
                                "--query", "Command.CommandId", "--output", "text"],
                         capture_output=True, text=True, timeout=60).stdout.strip()
    if not cid:
        print(json.dumps({"success": False, "message": "SSM no acepto el comando"}))
        raise SystemExit(1)
    for _ in range(20):
        time.sleep(3)
        r = subprocess.run(aws + ["ssm", "get-command-invocation", "--command-id", cid,
                                  "--instance-id", instancia,
                                  "--query", "[Status,StandardOutputContent,StandardErrorContent]",
                                  "--output", "json"], capture_output=True, text=True, timeout=60)
        try:
            estado, salida, err = json.loads(r.stdout)
        except Exception:
            continue
        if estado in ("Success", "Failed", "Cancelled", "TimedOut"):
            if estado == "Success" and salida.strip():
                print(salida.strip())
            else:
                print(json.dumps({"success": False,
                                  "message": f"SSM {estado}: {(err or salida).strip()[:200]}"}))
            break
    else:
        print(json.dumps({"success": False, "message": "SSM sin respuesta"}))
finally:
    subprocess.run(aws + ["s3", "rm", s3_uri, "--only-show-errors"],
                   capture_output=True, timeout=60)
PY
)
  echo "$respuesta"
  exit 0
fi

respuesta=$(WA_MENCIONES="${WA_MENCIONES:-}" WA_VIA="$VIA" WA_INSTANCIA="$INSTANCIA_PUENTE" WA_REGION="$REGION_PUENTE" WA_PERFIL="$PERFIL_PUENTE" python3 - "$destinatario" "$mensaje" "$PUERTO_SOPORTE" <<'PY'
import json, os, subprocess, sys, time, urllib.request
destinatario, mensaje, puerto = sys.argv[1], sys.argv[2], sys.argv[3]
cuerpo = {"recipient": destinatario, "message": mensaje}
menciones = [m.strip() for m in os.environ.get("WA_MENCIONES", "").split(",") if m.strip()]
if menciones:
    cuerpo["mentions"] = menciones
datos = json.dumps(cuerpo).encode()

if os.environ.get("WA_VIA") == "ssm":
    # Sin tunel local: curl EN el servidor via SSM. El JSON viaja en base64
    # para que ninguna comilla se rompa en el camino shell -> SSM -> shell.
    import base64
    b64 = base64.b64encode(datos).decode()
    aws = ["aws", "--profile", os.environ["WA_PERFIL"], "--region", os.environ["WA_REGION"], "ssm"]
    comando = f"echo {b64} | base64 -d | curl -s -m 25 -X POST http://localhost:{puerto}/api/send -H 'Content-Type: application/json' --data-binary @-"
    cid = subprocess.run(aws + ["send-command", "--instance-ids", os.environ["WA_INSTANCIA"],
                                "--document-name", "AWS-RunShellScript",
                                "--parameters", json.dumps({"commands": [comando]}),
                                "--query", "Command.CommandId", "--output", "text"],
                         capture_output=True, text=True, timeout=30).stdout.strip()
    for _ in range(10):
        time.sleep(3)
        r = subprocess.run(aws + ["get-command-invocation", "--command-id", cid,
                                  "--instance-id", os.environ["WA_INSTANCIA"],
                                  "--query", "[Status,StandardOutputContent]", "--output", "json"],
                          capture_output=True, text=True, timeout=30)
        try:
            estado, salida = json.loads(r.stdout)
        except Exception:
            continue
        if estado in ("Success", "Failed", "Cancelled", "TimedOut"):
            print(salida.strip() if estado == "Success" else json.dumps({"success": False, "message": f"SSM {estado}"}))
            break
    else:
        print(json.dumps({"success": False, "message": "SSM sin respuesta"}))
else:
    req = urllib.request.Request(f"http://localhost:{puerto}/api/send", data=datos,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        print(r.read().decode())
PY
)
echo "$respuesta"
