#!/usr/bin/env bash
# Vigilante del sitio de Mendiautos. Es una tarea programada de Hermes que no
# usa IA (hermes cron … --no-agent): si todo está bien no imprime nada; si algo
# falla, lo que imprime llega por Telegram. Repite el aviso cada 6 horas
# mientras el problema siga y avisa cuando se resuelve.
set -uo pipefail
export LC_ALL=C.UTF-8
CATALOGO=/usr/local/bin/catalogo
ESTADO=${HOME:-/tmp}/.cache/mendiautos-vigilante
mkdir -p "$(dirname "$ESTADO")"

SITIO=$(sed -n 's/^SITIO=//p' /etc/mendiautos.conf 2>/dev/null | tr -d "'\"" | head -n 1)
problemas=()

if [ -z "$SITIO" ]; then
  problemas+=("No encuentro la dirección del sitio en /etc/mendiautos.conf.")
else
  codigo=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 "$SITIO/" 2> /dev/null) || codigo=000
  if [ "$codigo" = 000 ]; then
    problemas+=("La página ($SITIO) no responde: el servidor web no contesta.")
  elif [ "$codigo" != 200 ]; then
    problemas+=("La página ($SITIO) responde con error $codigo.")
  fi
  inventario=$(curl -fsS --max-time 20 "$SITIO/assets/inventario.js" 2> /dev/null | head -c 400) || true
  [[ $inventario == *MND_INVENTARIO* ]] || problemas+=("El catálogo (assets/inventario.js) no se está sirviendo bien.")
  if [[ $SITIO == https://* ]]; then
    host=${SITIO#https://}
    host=${host%%/*}
    fin=$(timeout 20 openssl s_client -servername "$host" -connect "$host:443" < /dev/null 2> /dev/null |
      openssl x509 -noout -enddate 2> /dev/null | cut -d= -f2)
    if [ -n "$fin" ]; then
      dias=$(( ($(date -d "$fin" +%s) - $(date +%s)) / 86400 ))
      [ "$dias" -ge 14 ] || problemas+=("El certificado HTTPS vence en $dias días; debería renovarse solo (revisar: certbot renew).")
    else
      problemas+=("No pude leer el certificado HTTPS de $host.")
    fi
  fi
fi

uso=$(df -P / | awk 'NR == 2 {gsub("%", "", $5); print $5}')
[ "${uso:-0}" -lt 90 ] || problemas+=("El disco del servidor está al ${uso}%.")

if ! salida=$("$CATALOGO" validar 2>&1); then
  problemas+=("El catálogo tiene problemas: $(tail -n 3 <<< "$salida" | tr '\n' ' ')")
fi

if [ ${#problemas[@]} -eq 0 ]; then
  if [ -s "$ESTADO" ]; then
    rm -f "$ESTADO"
    echo "✅ Sitio de Mendiautos: todo volvió a la normalidad."
  fi
  exit 0
fi

texto=$(printf '• %s\n' "${problemas[@]}")
huella=$(md5sum <<< "$texto" | cut -c1-12)
ahora=$(date +%s)
{ read -r huella_antes hora_antes < "$ESTADO"; } 2> /dev/null || true
if [ "$huella" = "${huella_antes:-}" ] && [ $((ahora - ${hora_antes:-0})) -lt 21600 ]; then
  exit 0  # el mismo problema ya se avisó hace menos de 6 horas
fi
echo "$huella $ahora" > "$ESTADO"
printf '⚠️ Sitio de Mendiautos (%s):\n%s\n' "$(TZ=COT5 date '+%d/%m %H:%M')" "$texto"
