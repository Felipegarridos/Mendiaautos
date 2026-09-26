#!/usr/bin/env bash
# =============================================================================
#  hermes/instalar.sh — instala y configura el asistente del equipo de
#  Mendiautos (Hermes Agent) en la VPS: catálogo del sitio y canal de ventas,
#  por Telegram y, si se activa, por WhatsApp. Se usa a través de mendiautos.sh:
#
#    ssh -t root@IP_DE_LA_VPS "mendiautos hermes"     (el -t permite responder)
#
#  El asistente de WhatsApp para clientes es aparte: mendiautos hermes --clientes
#  Guía completa: hermes/README.md
# =============================================================================
set -euo pipefail

AQUI=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
USUARIO=hermes
CASA=/home/$USUARIO
HH=$CASA/.hermes                        # datos de Hermes (HERMES_HOME)
HERMES=$CASA/.local/bin/hermes
TRABAJO=$CASA/mendiautos                # carpeta de trabajo, con AGENTS.md
SERVICIO=mendiautos-hermes
UNIDAD=/etc/systemd/system/$SERVICIO.service
INSTALADOR=https://hermes-agent.nousresearch.com/install.sh
REGISTRO=/var/log/mendiautos-hermes-instalacion.log
CONF=/etc/mendiautos.conf
# Fotos que el asistente puede mostrar en el chat: las del catálogo y las que
# mandan los clientes en sus solicitudes (los documentos privados no).
FOTOS_PERMITIDAS=/var/lib/mendiautos/catalogo/fotos,/var/lib/mendiautos/solicitudes/fotos
SKILLS=(catalogo-mendiautos ventas-mendiautos)
SCRIPTS=(vigilar-sitio.sh resumen-catalogo.sh avisos-ventas-telegram.sh avisos-ventas-whatsapp.sh resumen-ventas.sh)

if [ -t 1 ]; then
  C_AZ=$'\e[1;34m' C_VE=$'\e[1;32m' C_AM=$'\e[1;33m' C_RO=$'\e[1;31m' C_NO=$'\e[0m'
else
  C_AZ='' C_VE='' C_AM='' C_RO='' C_NO=''
fi
info()  { printf '%s==>%s %s\n' "$C_AZ" "$C_NO" "$*"; }
ok()    { printf '%s ✓ %s %s\n' "$C_VE" "$C_NO" "$*"; }
aviso() { printf '%s ! %s %s\n' "$C_AM" "$C_NO" "$*" >&2; }
error() { printf '%s ✗ %s %s\n' "$C_RO" "$C_NO" "$*" >&2; exit 1; }

uso() {
  cat <<'EOF'
mendiautos hermes — asistente del equipo: catálogo del sitio y canal de ventas.

  mendiautos hermes                   instala o completa la configuración
                                      (usa ssh -t para responder las preguntas)
  mendiautos hermes --token T --usuarios 111,222
                                      lo mismo, sin preguntas de Telegram
  mendiautos hermes --whatsapp        conecta un número de WhatsApp del equipo
                                      (muestra un QR para escanear)
  mendiautos hermes --clientes        asistente de WhatsApp oficial para clientes
                                      (mendiautos hermes --clientes --help)
  mendiautos hermes --reiniciar       reinicia el asistente
  mendiautos hermes --actualizar      actualiza Hermes y lo reinicia
  mendiautos hermes --detener         apaga el asistente (no borra nada)
  mendiautos hermes --solo-archivos   solo actualiza skills, reglas y tareas

Opciones de configuración:
  --token TOKEN          token del bot (lo da @BotFather en Telegram)
  --usuarios IDS         IDs numéricos de Telegram autorizados, separados por coma
  --avisos ID            chat de Telegram predeterminado para los avisos
                         (por defecto, el primero de --usuarios)
  --canal-ventas ID      chat o grupo de Telegram que recibe las solicitudes
                         nuevas y el resumen de ventas
  --canal-catalogo ID    chat o grupo de Telegram que recibe el vigilante del
                         sitio y el resumen del catálogo
  --whatsapp-usuarios N  números de WhatsApp del equipo autorizados, con
                         indicativo (573001234567), separados por coma
  --sin-servicio         configura todo pero no arranca el asistente

Los avisos también se pueden mover desde el chat: en el grupo, escríbele al
asistente «que los avisos de ventas lleguen aquí».
EOF
}

# Corre un comando como el usuario del asistente, con un entorno limpio.
como_hermes() {
  runuser -u "$USUARIO" -- env -i HOME="$CASA" USER="$USUARIO" LOGNAME="$USUARIO" \
    SHELL=/bin/bash LANG=C.UTF-8 TERM="${TERM:-dumb}" HERMES_HOME="$HH" \
    PATH="$CASA/.local/bin:/usr/local/bin:/usr/bin:/bin" "$@"
}

apt_instalar() {
  DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=600 -y -q \
    -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold \
    install --no-install-recommends "$@" > /dev/null
}

leer_sitio() { sed -n 's/^SITIO=//p' "$CONF" 2> /dev/null | tr -d "'\"" | head -n 1; }

# Identifica esta versión del instalador (para aplicar sus cambios una vez).
huella() { sha256sum "$AQUI/instalar.sh" | cut -c1-16; }

# ------------------------------------------------------------------ pasos
crear_usuario() {
  if ! id -u "$USUARIO" > /dev/null 2>&1; then
    useradd --create-home --home-dir "$CASA" --shell /bin/bash \
      --comment "Asistente Hermes de Mendiautos" "$USUARIO"
    ok "Usuario $USUARIO creado (sin contraseña ni acceso por SSH)"
  fi
  asegurar_grupos || true
  chmod 0750 "$CASA"
}

# Puede usar los comandos catalogo y solicitudes (vía sudo, solo esos) y ver
# las fotos de las solicitudes. Devuelve 0 si tuvo que agregar algún grupo.
asegurar_grupos() {
  local g falta=()
  for g in editores-catalogo editores-solicitudes solicitudes; do
    getent group "$g" > /dev/null || error "Falta el grupo $g en el servidor. Primero publica el sitio: mendiautos actualizar --forzar"
    id -nG "$USUARIO" | tr ' ' '\n' | grep -qx "$g" || falta+=("$g")
  done
  [ ${#falta[@]} -gt 0 ] || return 1
  usermod -aG "$(IFS=,; echo "${falta[*]}")" "$USUARIO"
  return 0
}

instalar_hermes() {
  if [ -x "$HERMES" ]; then
    ok "Hermes ya está instalado ($(como_hermes "$HERMES" --version 2> /dev/null | head -n 1))"
    return 0
  fi
  apt_instalar git curl ca-certificates xz-utils
  info "Instalando Hermes Agent para el usuario $USUARIO (tarda unos minutos)…"
  if ! curl -fsSL "$INSTALADOR" | como_hermes bash -s -- --non-interactive --skip-browser > "$REGISTRO" 2>&1; then
    tail -n 15 "$REGISTRO" >&2
    error "La instalación de Hermes falló. Detalle: $REGISTRO"
  fi
  [ -x "$HERMES" ] || error "La instalación terminó sin el comando hermes. Detalle: $REGISTRO"
  ok "Hermes instalado"
}

# Skills, reglas y personalidad son de root: el asistente las lee, pero no las
# reescribe por su cuenta. Se actualizan con cada versión del repositorio.
instalar_archivos() {
  local sitio s
  sitio=$(leer_sitio)
  como_hermes mkdir -p "$HH/skills" "$HH/scripts"
  install -d -o root -g root -m 0755 "$TRABAJO"
  sed "s|{{SITIO}}|${sitio:-el sitio}|g" "$AQUI/AGENTS.md" > "$TRABAJO/AGENTS.md"
  chmod 0644 "$TRABAJO/AGENTS.md"
  install -d -o root -g root -m 0755 "$HH/skills/mendiautos"
  for s in "${SKILLS[@]}"; do
    install -d -o root -g root -m 0755 "$HH/skills/mendiautos/$s"
    install -o root -g root -m 0644 "$AQUI/skills/$s/SKILL.md" "$HH/skills/mendiautos/$s/SKILL.md"
  done
  if [ -f "$HH/SOUL.md" ] && [ ! -e "$HH/SOUL.md.original" ] && ! cmp -s "$HH/SOUL.md" "$AQUI/SOUL.md"; then
    cp -p "$HH/SOUL.md" "$HH/SOUL.md.original"
  fi
  install -o root -g root -m 0644 "$AQUI/SOUL.md" "$HH/SOUL.md"
  for s in "${SCRIPTS[@]}"; do
    install -o root -g root -m 0755 "$AQUI/scripts/$s" "$HH/scripts/$s"
  done
  ok "Skills del catálogo y de ventas, reglas, personalidad y tareas copiadas"
}

configurar_hermes() {
  como_hermes "$HERMES" config set terminal.cwd "$TRABAJO" > /dev/null
  como_hermes "$HERMES" config set timezone America/Bogota > /dev/null
  # Los comandos peligrosos (borrar carpetas, etc.) piden permiso por chat.
  como_hermes "$HERMES" config set approvals.mode manual > /dev/null
  # Puede mostrar en el chat las fotos del catálogo y de las solicitudes.
  como_hermes "$HERMES" config set gateway.media_delivery_allow_dirs "$FOTOS_PERMITIDAS" > /dev/null
  # En los grupos solo responde si lo mencionan o le contestan un mensaje;
  # así el equipo puede conversar sin que el asistente intervenga.
  como_hermes "$HERMES" config set telegram.require_mention true > /dev/null
  ok "Configuración: carpeta de trabajo, hora de Colombia, aprobación de comandos, fotos y grupos"
}

valor_env() { sed -n "s/^$1=//p" "$HH/.env" 2> /dev/null | tail -n 1 | tr -d "'\""; }

poner_env() {
  local tmp
  tmp=$(mktemp "$HH/.env.XXXXXX")
  grep -v "^$1=" "$HH/.env" > "$tmp" 2> /dev/null || true
  printf '%s=%s\n' "$1" "$2" >> "$tmp"
  chown "$USUARIO:$USUARIO" "$tmp"
  chmod 0600 "$tmp"
  mv -f "$tmp" "$HH/.env"
}

telegram_activo() { [ -n "$(valor_env TELEGRAM_BOT_TOKEN)" ] && [ -n "$(valor_env TELEGRAM_ALLOWED_USERS)" ]; }
whatsapp_activo() { [ "$(valor_env WHATSAPP_ENABLED)" = true ] && [ -n "$(ls -A "$HH/platforms/whatsapp/session" 2> /dev/null)" ]; }

configurar_telegram() {
  local token=$TOKEN usuarios=${USUARIOS// /} avisos=$AVISOS
  if [ -z "$token" ] && [ -z "$(valor_env TELEGRAM_BOT_TOKEN)" ] && [ -t 0 ]; then
    echo
    echo "Bot de Telegram"
    echo "  1. En Telegram, abre @BotFather y envía /newbot."
    echo "  2. Ponle un nombre (por ejemplo «Mendiautos Equipo») y un usuario que termine en «bot»."
    echo "  3. BotFather te da un token, algo como 123456789:AAH…"
    read -r -s -p "  Pega aquí el token (no se mostrará; Enter para omitir Telegram): " token
    echo
  fi
  if [ -n "$token" ]; then
    [[ $token =~ ^[0-9]{5,}:[A-Za-z0-9_-]{30,}$ ]] || error "Eso no parece un token de @BotFather."
    poner_env TELEGRAM_BOT_TOKEN "$token"
  fi
  if [ -z "$usuarios" ] && [ -n "$(valor_env TELEGRAM_BOT_TOKEN)" ] && [ -z "$(valor_env TELEGRAM_ALLOWED_USERS)" ] && [ -t 0 ]; then
    echo
    echo "Quién puede usar el bot"
    echo "  Cada persona del equipo le escribe a @userinfobot en Telegram y te pasa su «Id» (un número)."
    read -r -p "  IDs autorizados, separados por coma: " usuarios
    usuarios=${usuarios// /}
  fi
  if [ -n "$usuarios" ]; then
    [[ $usuarios =~ ^[0-9]{3,}(,[0-9]{3,})*$ ]] ||
      error "Los IDs son números separados por coma, por ejemplo 123456789,987654321."
    poner_env TELEGRAM_ALLOWED_USERS "$usuarios"
  fi
  [ -n "$avisos" ] || [ -n "$(valor_env TELEGRAM_HOME_CHANNEL)" ] || avisos=${usuarios%%,*}
  if [ -n "$avisos" ]; then
    [[ $avisos =~ ^-?[0-9]{3,}$ ]] || error "--avisos debe ser un ID numérico de Telegram."
    poner_env TELEGRAM_HOME_CHANNEL "$avisos"
  fi
  if telegram_activo; then
    ok "Telegram: bot configurado; autorizados: $(valor_env TELEGRAM_ALLOWED_USERS)"
    return 0
  fi
  aviso "Telegram sin configurar (token y usuarios). Para hacerlo: ssh -t root@IP mendiautos hermes"
  return 1
}

# WhatsApp del equipo: un número dedicado al asistente (no el de ventas ni uno
# personal), vinculado con un QR como WhatsApp Web. Es un puente no oficial.
configurar_whatsapp() {
  local usuarios=${WA_USUARIOS// /} n lista=() primero
  if [ -z "$usuarios" ] && [ -z "$(valor_env WHATSAPP_ALLOWED_USERS)" ] && [ -t 0 ]; then
    echo
    echo "WhatsApp del equipo"
    echo "  Números del equipo que podrán escribirle al asistente, con indicativo y sin"
    echo "  «+» ni espacios (por ejemplo 573001234567)."
    read -r -p "  Números autorizados, separados por coma: " usuarios
    usuarios=${usuarios// /}
  fi
  if [ -n "$usuarios" ]; then
    IFS=, read -r -a lista <<< "${usuarios//+/}"
    usuarios=""
    for n in "${lista[@]}"; do
      n=${n//[^0-9]/}
      [ ${#n} -eq 10 ] && [[ $n == 3* ]] && n=57$n
      [[ $n =~ ^[0-9]{11,15}$ ]] || error "«$n» no parece un número de WhatsApp con indicativo (ejemplo: 573001234567)."
      usuarios+=${usuarios:+,}$n
    done
    poner_env WHATSAPP_ALLOWED_USERS "$usuarios"
  fi
  if [ -z "$(valor_env WHATSAPP_ALLOWED_USERS)" ]; then
    aviso "WhatsApp del equipo: faltan los números autorizados (--whatsapp-usuarios 573001234567,…)."
    return 1
  fi
  primero=$(valor_env WHATSAPP_ALLOWED_USERS)
  poner_env WHATSAPP_ENABLED true
  poner_env WHATSAPP_MODE bot
  [ -n "$(valor_env WHATSAPP_HOME_CHANNEL)" ] || poner_env WHATSAPP_HOME_CHANNEL "${primero%%,*}"
  # A desconocidos no les contesta; en grupos, solo si lo mencionan.
  como_hermes "$HERMES" config set whatsapp.unauthorized_dm_behavior ignore > /dev/null
  como_hermes "$HERMES" config set whatsapp.group_policy open > /dev/null
  como_hermes "$HERMES" config set whatsapp.require_mention true > /dev/null
  if [ -z "$(ls -A "$HH/platforms/whatsapp/session" 2> /dev/null)" ]; then
    if [ ! -t 0 ]; then
      aviso "Falta vincular el número del asistente: ssh -t root@IP \"mendiautos hermes --whatsapp\" y escanea el QR."
      return 1
    fi
    echo
    echo "Vincular el número del asistente"
    echo "  Usa un número dedicado al asistente (una SIM aparte), no el WhatsApp de ventas"
    echo "  ni uno personal: WhatsApp no permite oficialmente estos puentes y podría"
    echo "  bloquear el número."
    echo "  En ese celular: WhatsApp → Ajustes → Dispositivos vinculados → Vincular."
    echo "  El asistente de Hermes pregunta el modo: elige «bot». Si pregunta usuarios o"
    echo "  chat de avisos, deja vacío (ya quedaron configurados)."
    echo
    systemctl stop "$SERVICIO" > /dev/null 2>&1 || true
    como_hermes "$HERMES" whatsapp || true
    poner_env WHATSAPP_ENABLED true
    poner_env WHATSAPP_MODE bot
  fi
  if whatsapp_activo; then
    chmod 0700 "$HH/platforms/whatsapp/session" 2> /dev/null || true
    ok "WhatsApp del equipo vinculado; autorizados: $(valor_env WHATSAPP_ALLOWED_USERS)"
    return 0
  fi
  aviso "El número de WhatsApp no quedó vinculado. Repite: ssh -t root@IP \"mendiautos hermes --whatsapp\""
  return 1
}

modelo_actual() {
  local m
  m=$(como_hermes "$HERMES" config get model.default 2>&1 | tail -n 1) || true
  [[ -n $m && $m != *"not set"* && $m != *rror* ]] && printf '%s' "$m"
}

configurar_modelo() {
  if [ -z "$(modelo_actual)" ] && [ -t 0 ]; then
    echo
    echo "Modelo de IA (el «cerebro» del asistente)"
    echo "  Se abre el asistente de Hermes: elige un proveedor (OpenRouter, Anthropic, OpenAI,"
    echo "  Nous Portal…) y pega tu clave de API. Recomendado: un modelo que vea imágenes."
    como_hermes "$HERMES" model || true
  fi
  if [ -n "$(modelo_actual)" ]; then
    ok "Modelo de IA: $(modelo_actual)"
    return 0
  fi
  aviso "Falta elegir el modelo de IA. Corre: ssh -t root@IP mendiautos hermes"
  return 1
}

# ------------------------------------------------------ tareas programadas
# Todas son sin IA (no gastan tokens): un script cuyo texto llega al chat.
dato_tarea() {
  python3 - "$HH/cron/jobs.json" "$1" "$2" <<'EOF' 2> /dev/null || true
import json, sys
try:
    datos = json.load(open(sys.argv[1], encoding='utf-8'))
except (OSError, ValueError):
    sys.exit(0)
for tarea in (datos.get('jobs') if isinstance(datos, dict) else datos) or []:
    if tarea.get('name') == sys.argv[2]:
        print(tarea.get(sys.argv[3]) or '')
        break
EOF
}

# Crea la tarea si no existe. Si ya existe, solo le cambia el destino cuando
# se pidió uno (--canal-…): así no se pierde lo que el equipo movió por chat.
asegurar_tarea() {
  local nombre=$1 horario=$2 script=$3 destino=$4 forzar=$5 id
  id=$(dato_tarea "$nombre" id)
  if [ -z "$id" ]; then
    como_hermes "$HERMES" cron create "$horario" --name "$nombre" --no-agent \
      --script "$script" --deliver "$destino" > /dev/null
  elif [ "$forzar" = 1 ] && [ "$(dato_tarea "$nombre" deliver)" != "$destino" ]; then
    como_hermes "$HERMES" cron edit "$id" --deliver "$destino" > /dev/null
  fi
}

quitar_tarea() {
  local id
  id=$(dato_tarea "$1" id)
  [ -z "$id" ] || como_hermes "$HERMES" cron remove "$id" > /dev/null 2>&1 || true
}

# «-1001234567890» o «telegram:-1001234567890[:tema]» → destino de Telegram.
destino_telegram() {
  local d=${1// /}
  d=${d#telegram:}
  [[ $d =~ ^-?[0-9]{3,}(:[0-9]+)?$ ]] || error "«$1» no es un chat de Telegram (ejemplo: -1001234567890)."
  printf 'telegram:%s' "$d"
}

configurar_tareas() {
  local base ventas catalogo fv=0 fc=0
  if telegram_activo; then base=telegram; else base=whatsapp; fi
  ventas=$base catalogo=$base
  [ -n "$CANAL_VENTAS" ] && { ventas=$(destino_telegram "$CANAL_VENTAS"); fv=1; }
  [ -n "$CANAL_CATALOGO" ] && { catalogo=$(destino_telegram "$CANAL_CATALOGO"); fc=1; }
  # Canal del catálogo
  asegurar_tarea vigilar-sitio "every 30m" vigilar-sitio.sh "$catalogo" "$fc"
  asegurar_tarea resumen-catalogo "0 8 * * 1" resumen-catalogo.sh "$catalogo" "$fc"
  # Canal de ventas
  asegurar_tarea resumen-ventas "30 7 * * *" resumen-ventas.sh "$ventas" "$fv"
  if telegram_activo; then
    asegurar_tarea avisos-ventas-telegram "every 1m" avisos-ventas-telegram.sh "$ventas" "$fv"
  else
    quitar_tarea avisos-ventas-telegram
  fi
  if whatsapp_activo; then
    asegurar_tarea avisos-ventas-whatsapp "every 1m" avisos-ventas-whatsapp.sh whatsapp 0
  else
    quitar_tarea avisos-ventas-whatsapp
  fi
  ok "Tareas: solicitudes nuevas cada minuto y resumen de ventas a las 7:30 ($(dato_tarea resumen-ventas deliver));" \
    "vigilante del sitio cada 30 min y resumen del catálogo los lunes ($(dato_tarea vigilar-sitio deliver))"
}

# Servicio de systemd propio: arranca con el servidor y se reinicia si cae.
escribir_unidad() {
  cat > "$UNIDAD" <<EOF
# Generado por hermes/instalar.sh (mendiautos hermes).
[Unit]
Description=Mendiautos: asistente del equipo (Hermes Agent)
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=$USUARIO
Group=$USUARIO
WorkingDirectory=$TRABAJO
Environment=HOME=$CASA HERMES_HOME=$HH LANG=C.UTF-8 PYTHONUNBUFFERED=1
Environment=PATH=$CASA/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=$HERMES gateway run --replace --external-supervisor
Restart=always
RestartSec=10
# Hermes sale con 1 cuando recibe SIGTERM (systemctl stop): es una parada normal.
SuccessExitStatus=1
KillMode=mixed
KillSignal=SIGTERM
TimeoutStopSec=90

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
}

activar_servicio() {
  escribir_unidad
  systemctl enable "$SERVICIO" > /dev/null 2>&1
  systemctl restart "$SERVICIO"
  sleep 8
  if ! systemctl is-active --quiet "$SERVICIO"; then
    journalctl -u "$SERVICIO" -n 25 --no-pager >&2 || true
    error "El asistente no arrancó; arriba están sus últimos mensajes."
  fi
  ok "Asistente en marcha (servicio $SERVICIO)"
}

# --------------------------------------------------------------- comandos
main() {
  TOKEN="" USUARIOS="" AVISOS="" CANAL_VENTAS="" CANAL_CATALOGO="" WA_USUARIOS=""
  local accion=instalar servicio=1 whatsapp=0
  if [ "${1:-}" = --clientes ]; then
    shift
    exec bash "$AQUI/clientes/instalar.sh" "$@"
  fi
  while [ $# -gt 0 ]; do
    case $1 in
      --token) TOKEN=${2:-}; shift 2 ;;
      --usuarios) USUARIOS=${2:-}; shift 2 ;;
      --avisos) AVISOS=${2:-}; shift 2 ;;
      --canal-ventas) CANAL_VENTAS=${2:-}; shift 2 ;;
      --canal-catalogo) CANAL_CATALOGO=${2:-}; shift 2 ;;
      --whatsapp) whatsapp=1; shift ;;
      --whatsapp-usuarios) WA_USUARIOS=${2:-}; whatsapp=1; shift 2 ;;
      --sin-servicio) servicio=0; shift ;;
      --solo-archivos) accion=archivos; shift ;;
      --reiniciar) accion=reiniciar; shift ;;
      --actualizar) accion=actualizar; shift ;;
      --detener) accion=detener; shift ;;
      --clientes) error "--clientes va solo, al principio: mendiautos hermes --clientes --help" ;;
      -h|--help|ayuda) uso; exit 0 ;;
      *) error "Opción desconocida: $1 (ver: mendiautos hermes --help)" ;;
    esac
  done
  [ "$(id -u)" -eq 0 ] || error "Ejecútalo como root: mendiautos hermes"
  [ -x /usr/local/bin/catalogo ] || error "Falta el comando catalogo. Primero: mendiautos instalar"
  [ -x /usr/local/bin/solicitudes ] || error "Falta el comando solicitudes. Primero: mendiautos actualizar --forzar"

  case $accion in
    archivos)
      id -u "$USUARIO" > /dev/null 2>&1 || exit 0   # sin asistente instalado no hay nada que hacer
      instalar_archivos
      # Un grupo nuevo o una versión nueva de este instalador (configuración,
      # tareas) se aplican solos; el servicio se reinicia solo si hace falta.
      local cambio=0
      asegurar_grupos && cambio=1
      if [ -x "$HERMES" ] && [ "$(cat "$HH/.mendiautos-instalador" 2> /dev/null)" != "$(huella)" ]; then
        configurar_hermes > /dev/null || true
        if telegram_activo || whatsapp_activo; then configurar_tareas > /dev/null || true; fi
        [ -f "$UNIDAD" ] && escribir_unidad
        huella > "$HH/.mendiautos-instalador"
        cambio=1
      fi
      if [ "$cambio" = 1 ] && systemctl is-active --quiet "$SERVICIO"; then
        systemctl restart "$SERVICIO"
      fi
      ;;
    reiniciar)
      systemctl restart "$SERVICIO" && ok "Asistente reiniciado"
      ;;
    detener)
      systemctl disable --now "$SERVICIO" > /dev/null 2>&1 || true
      ok "Asistente detenido. Para volver a encenderlo: mendiautos hermes"
      ;;
    actualizar)
      [ -x "$HERMES" ] || error "Hermes no está instalado. Primero: mendiautos hermes"
      info "Actualizando Hermes…"
      como_hermes "$HERMES" update --yes
      instalar_archivos
      systemctl restart "$SERVICIO" && ok "Asistente actualizado y reiniciado"
      ;;
    instalar)
      info "Asistente del equipo de Mendiautos"
      crear_usuario
      instalar_hermes
      instalar_archivos
      configurar_hermes
      local modelo=1 canales=0
      configurar_modelo || modelo=0
      configurar_telegram && canales=1 || true
      if [ "$whatsapp" = 1 ] || [ "$(valor_env WHATSAPP_ENABLED)" = true ]; then
        configurar_whatsapp && canales=1 || true
      fi
      if [ "$canales" = 0 ]; then
        aviso "Falta un canal para hablar con el asistente: Telegram (mendiautos hermes) o WhatsApp (mendiautos hermes --whatsapp)."
      fi
      if [ "$canales" = 1 ]; then
        configurar_tareas
        huella > "$HH/.mendiautos-instalador"
      fi
      if [ "$servicio" = 1 ] && [ "$modelo" = 1 ] && [ "$canales" = 1 ]; then
        activar_servicio
        echo
        ok "Listo. Escríbele al asistente, por ejemplo: «¿Qué autos tenemos publicados?» o «¿Qué solicitudes hay pendientes?»"
        echo "    Estado:       systemctl status $SERVICIO"
        echo "    Mensajes:     journalctl -u $SERVICIO -f"
        echo "    Reiniciar:    mendiautos hermes --reiniciar"
        echo "    Apagar:       mendiautos hermes --detener"
        echo "    Avisos:       en un grupo, dile al asistente «que los avisos de ventas lleguen aquí»"
      elif [ "$modelo" = 0 ] || [ "$canales" = 0 ]; then
        aviso "El asistente quedó instalado pero no arrancado: completa lo que falta y vuelve a correr «mendiautos hermes»."
      fi
      ;;
  esac
}

main "$@"
