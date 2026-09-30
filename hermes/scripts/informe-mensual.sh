#!/usr/bin/env bash
# Informe mensual para el gerente y el administrador (día 1, 8:00 a. m.): el
# mes anterior completo. Tarea programada de Hermes sin IA (hermes cron …
# --no-agent): lo que imprime llega por Telegram.
set -uo pipefail
export LC_ALL=C.UTF-8
/usr/local/bin/catalogo informe --mes
echo
/usr/local/bin/solicitudes informe --mes
