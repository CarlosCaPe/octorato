#!/usr/bin/env bash
# Sends a WhatsApp through the SUPPORT channel, never through the operator's personal number.
#
# Why it exists: the `whatsapp` MCP is wired to the personal bridge (port 8080).
# Every mcp__whatsapp__send_message leaves from the operator's number. To talk
# to a client the right channel is the support bridge (port 8081). A notice
# once went out to a client from the personal number because this path did not exist.
#
# Usage:  wa-soporte.sh <recipient> <message>
#         recipient: phone with country code, no + or symbols, or a full JID
#
# Attachments:  wa-soporte.sh <recipient> <message> --archivo <local-path>
# The bridge reads `media_path` on ITS disk, and since the cutover that disk is
# the EC2's, not this machine's. So the file travels: local -> staging bucket ->
# EC2 -> /api/send. Both intermediate copies are always deleted, also when the
# send fails. This used to be four manual steps every time.
#
# Mentions (groups): export WA_MENCIONES with comma-separated phone numbers.
# The text MUST contain "@<telefono>" for WhatsApp to render it as a tag; the
# reader's phone swaps it for the saved contact name. Without it the mention
# notifies nobody and shows as grey text.
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

# Since the 2026-08-14 cutover the bridge lives on the octorato-ops EC2.
# Fast path: the local SSM tunnel (localhost:8081). When the tunnel is down
# (laptop just booted, another machine, a cloud session) it does NOT fall back
# to the personal bridge: it sends DIRECTLY over SSM by running curl ON the
# server. The channel no longer depends on this laptop; it only needs the AWS
# ops profile credentials.
INSTANCIA_PUENTE="i-0c0112bf1431dc99e"
REGION_PUENTE="mx-central-1"
PERFIL_PUENTE="dataqbs-ops"
VIA="tunel"
if ! ss -lnt 2>/dev/null | grep -q ":${PUERTO_SOPORTE} "; then
  VIA="ssm"
fi

# ---- Attachment: the file must exist on the BRIDGE's disk -----------------
# The instance id, region, profile and staging bucket come from the PRIVATE
# config, not from here: this script is published.
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
