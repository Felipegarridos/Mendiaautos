#!/usr/bin/env bash
# Avisos de ventas por Telegram: las solicitudes nuevas de los formularios del
# sitio, para una persona (el gerente o el administrador). Hermes corre una
# copia por persona (avisos-ventas-<ID>.sh, la crea el instalador) cada minuto,
# sin IA: si no hay nada nuevo no imprime nada y no llega ningún mensaje. Cada
# solicitud se avisa una sola vez por persona; si el aviso anterior no llegó
# (Hermes anota el error de entrega), se repite.
set -uo pipefail
export LC_ALL=C.UTF-8
DESTINO=${1:-}
[[ $DESTINO =~ ^[0-9]{3,20}$ ]] || { echo "Uso: avisos-ventas-telegram.sh <ID de Telegram>" >&2; exit 2; }
TAREA=avisos-ventas-$DESTINO
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
exec /usr/local/bin/solicitudes avisar --canal "tg-$DESTINO" ${fallo:+--reintentar}
