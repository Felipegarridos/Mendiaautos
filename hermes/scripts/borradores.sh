#!/usr/bin/env bash
# Aviso a cada persona del equipo de sus borradores que se borran mañana
# (7 días sin cambios). Hermes corre una copia por persona (borradores-<ID>.sh,
# la crea el instalador) todos los días a las 9:00 a. m.; si no hay nada que
# avisar no imprime nada y no llega ningún mensaje.
set -uo pipefail
export LC_ALL=C.UTF-8
[[ ${1:-} =~ ^[0-9]{3,20}$ ]] || { echo "Uso: borradores.sh <ID de Telegram>" >&2; exit 2; }
exec /usr/local/bin/catalogo borradores --por-vencer --de "$1"
