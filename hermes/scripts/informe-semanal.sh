#!/usr/bin/env bash
# Informe semanal para el gerente y el administrador (sábados 8:00 a. m.): la
# semana que terminó ayer. Tarea programada de Hermes sin IA (hermes cron …
# --no-agent): lo que imprime llega por Telegram.
set -uo pipefail
export LC_ALL=C.UTF-8
/usr/local/bin/catalogo informe
echo
/usr/local/bin/solicitudes informe
