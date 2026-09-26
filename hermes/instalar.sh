#!/usr/bin/env bash
# =============================================================================
#  hermes/instalar.sh — instala y configura el asistente de Telegram de
#  Mendiautos (Hermes Agent) en la VPS. Se usa a través de mendiautos.sh:
#
#    ssh -t root@IP_DE_LA_VPS "mendiautos hermes"     (el -t permite responder)
#
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
mendiautos hermes — asistente de Telegram que mantiene el catálogo del sitio.

  mendiautos hermes                   instala o completa la configuración
                                      (usa ssh -t para responder las preguntas)
  mendiautos hermes --token T --usuarios 111,222
                                      lo mismo, sin preguntas de Telegram
  mendiautos hermes --reiniciar       reinicia el asistente
  mendiautos hermes --actualizar      actualiza Hermes y lo reinicia
  mendiautos hermes --detener         apaga el asistente (no borra nada)
  mendiautos hermes --solo-archivos   solo actualiza skill, reglas y tareas

Opciones de configuración:
  --token TOKEN      token del bot (lo da @BotFather en Telegram)
  --usuarios IDS     IDs numéricos de Telegram autorizados, separados por coma
  --avisos ID        chat que recibe los avisos automáticos
                     (por defecto, el primero de --usuarios)
  --sin-servicio     configura todo pero no arranca el asistente
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

# ------------------------------------------------------------------ pasos
crear_usuario() {
  if ! id -u "$USUARIO" > /dev/null 2>&1; then
    useradd --create-home --home-dir "$CASA" --shell /bin/bash \
      --comment "Asistente Hermes de Mendiautos" "$USUARIO"
    ok "Usuario $USUARIO creado (sin contraseña ni acceso por SSH)"
  fi
  # Puede usar el comando catalogo (vía sudo, solo ese comando) y nada más.
  usermod -aG editores-catalogo "$USUARIO"
  chmod 0750 "$CASA"
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

# Skill, reglas y personalidad son de root: el asistente las lee, pero no las
# reescribe por su cuenta. Se actualizan con cada versión del repositorio.
instalar_archivos() {
  local sitio
  sitio=$(leer_sitio)
  como_hermes mkdir -p "$HH/skills" "$HH/scripts"
  install -d -o root -g root -m 0755 "$TRABAJO"
  sed "s|{{SITIO}}|${sitio:-el sitio}|g" "$AQUI/AGENTS.md" > "$TRABAJO/AGENTS.md"
  chmod 0644 "$TRABAJO/AGENTS.md"
  install -d -o root -g root -m 0755 "$HH/skills/mendiautos" "$HH/skills/mendiautos/catalogo-mendiautos"
  install -o root -g root -m 0644 "$AQUI/skills/catalogo-mendiautos/SKILL.md" \
    "$HH/skills/mendiautos/catalogo-mendiautos/SKILL.md"
  if [ -f "$HH/SOUL.md" ] && [ ! -e "$HH/SOUL.md.original" ] && ! cmp -s "$HH/SOUL.md" "$AQUI/SOUL.md"; then
    cp -p "$HH/SOUL.md" "$HH/SOUL.md.original"
  fi
  install -o root -g root -m 0644 "$AQUI/SOUL.md" "$HH/SOUL.md"
  install -o root -g root -m 0755 "$AQUI/scripts/vigilar-sitio.sh" "$AQUI/scripts/resumen-catalogo.sh" "$HH/scripts/"
  ok "Skill del catálogo, reglas, personalidad y tareas copiadas"
}

configurar_hermes() {
  como_hermes "$HERMES" config set terminal.cwd "$TRABAJO" > /dev/null
  como_hermes "$HERMES" config set timezone America/Bogota > /dev/null
  # Los comandos peligrosos (borrar carpetas, etc.) piden permiso por Telegram.
  como_hermes "$HERMES" config set approvals.mode manual > /dev/null
  ok "Configuración: carpeta de trabajo, hora de Colombia, comandos peligrosos con aprobación"
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

configurar_telegram() {
  local token=$TOKEN usuarios=${USUARIOS// /} avisos=$AVISOS
  if [ -z "$token" ] && [ -z "$(valor_env TELEGRAM_BOT_TOKEN)" ] && [ -t 0 ]; then
    echo
    echo "Bot de Telegram"
    echo "  1. En Telegram, abre @BotFather y envía /newbot."
    echo "  2. Ponle un nombre (por ejemplo «Mendiautos Catálogo») y un usuario que termine en «bot»."
    echo "  3. BotFather te da un token, algo como 123456789:AAH…"
    read -r -s -p "  Pega aquí el token (no se mostrará): " token
    echo
  fi
  if [ -n "$token" ]; then
    [[ $token =~ ^[0-9]{5,}:[A-Za-z0-9_-]{30,}$ ]] || error "Eso no parece un token de @BotFather."
    poner_env TELEGRAM_BOT_TOKEN "$token"
  fi
  if [ -z "$usuarios" ] && [ -z "$(valor_env TELEGRAM_ALLOWED_USERS)" ] && [ -t 0 ]; then
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
  if [ -n "$(valor_env TELEGRAM_BOT_TOKEN)" ] && [ -n "$(valor_env TELEGRAM_ALLOWED_USERS)" ]; then
    ok "Telegram: bot configurado; autorizados: $(valor_env TELEGRAM_ALLOWED_USERS)"
    return 0
  fi
  aviso "Falta configurar Telegram (token y usuarios). Corre: ssh -t root@IP mendiautos hermes"
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

configurar_tareas() {
  local lista
  lista=$(como_hermes "$HERMES" cron list 2> /dev/null || true)
  grep -q 'vigilar-sitio' <<< "$lista" ||
    como_hermes "$HERMES" cron create "every 30m" --name vigilar-sitio --no-agent \
      --script vigilar-sitio.sh --deliver telegram > /dev/null
  grep -q 'resumen-catalogo' <<< "$lista" ||
    como_hermes "$HERMES" cron create "0 8 * * 1" --name resumen-catalogo --no-agent \
      --script resumen-catalogo.sh --deliver telegram > /dev/null
  ok "Tareas: vigilante del sitio cada 30 min y resumen del catálogo los lunes a las 8:00"
}

# Servicio de systemd propio: arranca con el servidor y se reinicia si cae.
activar_servicio() {
  cat > "$UNIDAD" <<EOF
# Generado por hermes/instalar.sh (mendiautos hermes).
[Unit]
Description=Mendiautos: asistente de Telegram (Hermes Agent)
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=$USUARIO
Group=$USUARIO
WorkingDirectory=$TRABAJO
Environment=HOME=$CASA HERMES_HOME=$HH LANG=C.UTF-8
Environment=PATH=$CASA/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=$HERMES gateway run --replace --external-supervisor
Restart=always
RestartSec=10
KillMode=mixed
KillSignal=SIGTERM
TimeoutStopSec=90

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
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
  TOKEN="" USUARIOS="" AVISOS=""
  local accion=instalar servicio=1
  while [ $# -gt 0 ]; do
    case $1 in
      --token) TOKEN=${2:-}; shift 2 ;;
      --usuarios) USUARIOS=${2:-}; shift 2 ;;
      --avisos) AVISOS=${2:-}; shift 2 ;;
      --sin-servicio) servicio=0; shift ;;
      --solo-archivos) accion=archivos; shift ;;
      --reiniciar) accion=reiniciar; shift ;;
      --actualizar) accion=actualizar; shift ;;
      --detener) accion=detener; shift ;;
      -h|--help|ayuda) uso; exit 0 ;;
      *) error "Opción desconocida: $1 (ver: mendiautos hermes --help)" ;;
    esac
  done
  [ "$(id -u)" -eq 0 ] || error "Ejecútalo como root: mendiautos hermes"
  [ -x /usr/local/bin/catalogo ] || error "Falta el comando catalogo. Primero: mendiautos instalar"

  case $accion in
    archivos)
      id -u "$USUARIO" > /dev/null 2>&1 || exit 0   # sin asistente instalado no hay nada que hacer
      instalar_archivos
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
      info "Asistente de Telegram de Mendiautos"
      crear_usuario
      instalar_hermes
      instalar_archivos
      configurar_hermes
      local listo=1
      configurar_modelo || listo=0
      configurar_telegram || listo=0
      configurar_tareas
      if [ "$servicio" = 1 ] && [ "$listo" = 1 ]; then
        activar_servicio
        echo
        ok "Listo. Escríbele a tu bot en Telegram, por ejemplo: «¿Qué autos tenemos publicados?»"
        echo "    Estado:       systemctl status $SERVICIO"
        echo "    Mensajes:     journalctl -u $SERVICIO -f"
        echo "    Reiniciar:    mendiautos hermes --reiniciar"
        echo "    Apagar:       mendiautos hermes --detener"
      elif [ "$listo" = 0 ]; then
        aviso "El asistente quedó instalado pero no arrancado: completa lo que falta y vuelve a correr «mendiautos hermes»."
      fi
      ;;
  esac
}

main "$@"
