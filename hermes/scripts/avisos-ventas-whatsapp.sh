#!/usr/bin/env bash
# Avisos de ventas por WhatsApp: las solicitudes nuevas de los formularios del
# sitio. Es una tarea programada de Hermes que no usa IA (hermes cron …
# --no-agent), cada minuto: si no hay nada nuevo no imprime nada y no llega
# ningún mensaje. Cada solicitud se avisa una sola vez por canal; si el chat no
# recibió el aviso anterior (Hermes anota el error de entrega), se repite.
set -uo pipefail
export LC_ALL=C.UTF-8
TAREA=avisos-ventas-whatsapp
TAREAS=${HERMES_HOME:-$HOME/.hermes}/cron/jobs.json
fallo=$(python3 - "$TAREAS" "$TAREA" <<'PY' 2> /dev/null
import json, sys
try:
    datos = json.load(open(sys.argv[1], encoding='utf-8'))
except (OSError, ValueError):
    sys.exit(0)
for tarea in (datos.get('jobs') if isinstance(datos, dict) else datos) or []:
    if tarea.get('name') == sys.argv[2] and tarea.get('last_delivery_error'):
        print('si')
PY
)
exec /usr/local/bin/solicitudes avisar --canal whatsapp ${fallo:+--reintentar}
