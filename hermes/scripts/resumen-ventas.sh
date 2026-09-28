#!/usr/bin/env bash
# Resumen diario de ventas para el equipo: lo que llegó en las últimas 24 horas
# y lo que sigue pendiente. Tarea programada de Hermes sin IA (hermes cron …
# --no-agent); si no hay nada que contar, no llega ningún mensaje.
set -uo pipefail
export LC_ALL=C.UTF-8
exec /usr/local/bin/solicitudes resumen --dias 1 --silencioso-si-vacio
