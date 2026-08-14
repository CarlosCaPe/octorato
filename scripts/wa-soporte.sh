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
# Menciones (grupos): exporta WA_MENCIONES con los telefonos separados por coma.
# El texto TIENE que traer "@<telefono>" para que WhatsApp lo pinte como etiqueta;
# el celular de quien lee lo cambia por el nombre que tenga guardado. Sin esto la
# mencion no notifica a nadie, se ve como texto gris.
#   WA_MENCIONES=5215550001111 wa-soporte.sh 1203...@g.us "@5215550001111 buenos dias"
set -euo pipefail

PUERTO_SOPORTE=8081
PUERTO_PERSONAL=8080

if [ $# -lt 2 ]; then
  echo "uso: $(basename "$0") <destinatario> <mensaje>" >&2
  exit 64
fi

destinatario=$1
shift
mensaje=$*

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
