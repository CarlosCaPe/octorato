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

# el puente de soporte tiene que estar vivo: si no, NO se cae al personal en
# silencio, porque eso es exactamente el error que este script previene
if ! curl -sf -m 3 -o /dev/null "http://localhost:${PUERTO_SOPORTE}/api/send" -X POST -d '{}' 2>/dev/null; then
  if ! ss -lnt 2>/dev/null | grep -q ":${PUERTO_SOPORTE} "; then
    echo "ERROR: el puente de soporte (puerto ${PUERTO_SOPORTE}) no esta escuchando." >&2
    echo "       NO se envia por el personal (${PUERTO_PERSONAL}); levanta el puente primero." >&2
    exit 69
  fi
fi

respuesta=$(python3 - "$destinatario" "$mensaje" "$PUERTO_SOPORTE" <<'PY'
import json, sys, urllib.request
destinatario, mensaje, puerto = sys.argv[1], sys.argv[2], sys.argv[3]
datos = json.dumps({"recipient": destinatario, "message": mensaje}).encode()
req = urllib.request.Request(f"http://localhost:{puerto}/api/send", data=datos,
                             headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=30) as r:
    print(r.read().decode())
PY
)
echo "$respuesta"
