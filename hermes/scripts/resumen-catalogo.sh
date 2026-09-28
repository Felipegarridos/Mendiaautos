#!/usr/bin/env bash
# Resumen semanal del catálogo para el equipo. Es una tarea programada de
# Hermes que no usa IA (hermes cron … --no-agent): lo que imprime llega por
# Telegram.
set -uo pipefail
export LC_ALL=C.UTF-8
/usr/local/bin/catalogo resumen --dias 7
