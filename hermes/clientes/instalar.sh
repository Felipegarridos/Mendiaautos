#!/usr/bin/env bash
# =============================================================================
#  hermes/clientes/instalar.sh — asistente de WhatsApp para clientes, por el
#  WhatsApp oficial (Cloud API de Meta). Se usa a través de mendiautos.sh:
#
#    ssh -t root@IP_DE_LA_VPS "mendiautos hermes --clientes"
#
#  Es una instalación de Hermes aparte, con su propio usuario del sistema y sin
#  terminal, archivos ni internet: solo tiene las cuatro herramientas de
#  mcp_clientes.py (catálogo público, información del negocio y registrar
#  interesados). No puede leer las solicitudes ni cambiar el catálogo.
#  Guía completa: hermes/README.md
# =============================================================================
set -euo pipefail

AQUI=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
USUARIO=hermes-clientes
CASA=/home/$USUARIO
HH=$CASA/.hermes
HERMES=$CASA/.local/bin/hermes
TRABAJO=$CASA/mendiautos
SERVICIO=mendiautos-clientes
UNIDAD=/etc/systemd/system/$SERVICIO.service
LIB=/usr/local/lib/mendiautos             # herramientas (de root; el asistente solo las lee)
TOKEN_ORIGEN=/etc/mendiautos/solicitudes.token
TOKEN=/etc/mendiautos/clientes.token
CONF=/etc/mendiautos.conf
BIN=/usr/local/bin/mendiautos
PUERTO=8090                               # webhook de Meta (solo en 127.0.0.1; nginx lo publica)
INSTALADOR=https://hermes-agent.nousresearch.com/install.sh
REGISTRO=/var/log/mendiautos-clientes-instalacion.log
FOTOS_CATALOGO=/var/lib/mendiautos/catalogo/fotos
# Todo lo que Hermes trae y este asistente no debe tener.
SIN_HERRAMIENTAS='[terminal, file, web, search, browser, code_execution, delegation, memory, session_search,
  skills, cronjob, todo, vision, video, image_gen, video_gen, tts, homeassistant, computer_use, x_search,
  spotify, kanban, connections, clarify]'

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
mendiautos hermes --clientes — asistente de WhatsApp para clientes (WhatsApp oficial).

  mendiautos hermes --clientes          instala o completa la configuración
                                        (pide lo que falte; usa ssh -t)
  mendiautos hermes --clientes --reiniciar | --actualizar | --detener
  mendiautos hermes --clientes --solo-archivos   actualiza reglas y herramientas

Credenciales de Meta (developers.facebook.com → tu app → WhatsApp → Configuración
de la API), también se pueden dar sin preguntas:
  --numero-id ID        «Identificador del número de teléfono»
  --token-meta TOKEN    token permanente de un usuario del sistema (Business Manager)
  --app-secret CLAVE    «Clave secreta de la app» (Configuración → Básica)

Necesita el sitio con dominio y HTTPS (mendiautos dominio …): Meta solo entrega
los mensajes a una dirección https://.
EOF
}

como_usuario() {
  runuser -u "$USUARIO" -- env -i HOME="$CASA" USER="$USUARIO" LOGNAME="$USUARIO" \
    SHELL=/bin/bash LANG=C.UTF-8 TERM="${TERM:-dumb}" HERMES_HOME="$HH" \
    PATH="$CASA/.local/bin:/usr/local/bin:/usr/bin:/bin" "$@"
}

apt_instalar() {
  DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=600 -y -q \
    -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold \
    install --no-install-recommends "$@" > /dev/null
}

leer_conf() { sed -n "s/^$1=//p" "$CONF" 2> /dev/null | tr -d "'\"" | head -n 1; }

poner_conf() {
  if grep -q "^$1=" "$CONF" 2> /dev/null; then
    sed -i "s|^$1=.*|$1=$2|" "$CONF"
  else
    printf '%s=%s\n' "$1" "$2" >> "$CONF"
  fi
}

# Dominio con certificado de HTTPS (vacío si todavía no hay).
dominio_https() {
  local d
  d=$(leer_conf DOMINIO)
  [ -n "$d" ] && [ -s "/etc/letsencrypt/live/$d/fullchain.pem" ] && printf '%s' "$d"
  return 0
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

# ------------------------------------------------------------------ pasos
crear_usuario() {
  if ! id -u "$USUARIO" > /dev/null 2>&1; then
    # Sin grupos extra: no puede usar catalogo ni solicitudes, ni leer al otro asistente.
    useradd --create-home --home-dir "$CASA" --shell /bin/bash \
      --comment "Asistente de clientes de Mendiautos" "$USUARIO"
    ok "Usuario $USUARIO creado (sin contraseña, sin acceso por SSH y sin permisos especiales)"
  fi
  chmod 0750 "$CASA"
}

instalar_hermes() {
  if [ -x "$HERMES" ]; then
    ok "Hermes ya está instalado para $USUARIO"
    return 0
  fi
  apt_instalar git curl ca-certificates xz-utils
  info "Instalando Hermes Agent para el usuario $USUARIO (tarda unos minutos)…"
  if ! curl -fsSL "$INSTALADOR" | como_usuario bash -s -- --non-interactive --skip-browser > "$REGISTRO" 2>&1; then
    tail -n 15 "$REGISTRO" >&2
    error "La instalación de Hermes falló. Detalle: $REGISTRO"
  fi
  [ -x "$HERMES" ] || error "La instalación terminó sin el comando hermes. Detalle: $REGISTRO"
  ok "Hermes instalado"
}

# Reglas, personalidad y herramientas son de root: el asistente las lee pero no
# las cambia. Devuelve 0 si cambió el servidor de herramientas (hay que reiniciar).
instalar_archivos() {
  local sitio igual=1
  sitio=$(leer_conf SITIO)
  install -d -o root -g root -m 0755 "$LIB" "$TRABAJO"
  cmp -s "$AQUI/mcp_clientes.py" "$LIB/mcp_clientes.py" || igual=0
  install -o root -g root -m 0755 "$AQUI/mcp_clientes.py" "$LIB/mcp_clientes.py"
  install -o root -g root -m 0644 "$AQUI/empresa.json" "$LIB/empresa.json"
  sed "s|{{SITIO}}|${sitio:-el sitio}|g" "$AQUI/AGENTS.md" > "$TRABAJO/AGENTS.md"
  chmod 0644 "$TRABAJO/AGENTS.md"
  como_usuario mkdir -p "$HH"
  install -o root -g root -m 0644 "$AQUI/SOUL.md" "$HH/SOUL.md"
  # Clave para registrar interesados en el receptor de solicitudes.
  [ -s "$TOKEN_ORIGEN" ] || error "Falta $TOKEN_ORIGEN. Primero: mendiautos actualizar --forzar"
  install -o root -g "$USUARIO" -m 0640 "$TOKEN_ORIGEN" "$TOKEN"
  return "$igual"
}

# config.yaml de este Hermes: solo WhatsApp oficial, solo las herramientas de
# Mendiautos, solo fotos del catálogo, pocas vueltas por mensaje.
configurar_hermes() {
  python3 -c 'import yaml' 2> /dev/null || apt_instalar python3-yaml
  local cfg=$HH/config.yaml
  [ -f "$cfg" ] || como_usuario touch "$cfg"
  python3 - "$cfg" "$TRABAJO" "$LIB/mcp_clientes.py" "$FOTOS_CATALOGO" "$SIN_HERRAMIENTAS" <<'EOF'
import sys, yaml
ruta, trabajo, mcp, fotos, sin = sys.argv[1:6]
with open(ruta, encoding='utf-8') as f:
    cfg = yaml.safe_load(f) or {}
cfg.setdefault('terminal', {})['cwd'] = trabajo
cfg['timezone'] = 'America/Bogota'
agente = cfg.setdefault('agent', {})
agente['disabled_toolsets'] = yaml.safe_load(sin)
agente['max_turns'] = 8
cfg.setdefault('platform_toolsets', {})['whatsapp_cloud'] = ['mendiautos']
pasarela = cfg.setdefault('gateway', {})
pasarela['strict'] = True
pasarela['media_delivery_allow_dirs'] = [fotos]
cfg.setdefault('mcp_servers', {})['mendiautos'] = {
    'command': '/usr/bin/python3', 'args': ['-I', mcp], 'timeout': 30, 'connect_timeout': 30,
    'tools': {'resources': False, 'prompts': False},
}
with open(ruta + '.tmp', 'w', encoding='utf-8') as f:
    yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
EOF
  chown "$USUARIO:$USUARIO" "$cfg.tmp"
  chmod 0600 "$cfg.tmp"
  mv -f "$cfg.tmp" "$cfg"
  ok "Configuración: solo WhatsApp oficial y las 4 herramientas de Mendiautos (sin terminal, archivos ni internet)"
}

modelo_actual() {
  local m
  m=$(como_usuario "$HERMES" config get model.default 2>&1 | tail -n 1) || true
  [[ -n $m && $m != *"not set"* && $m != *rror* ]] && printf '%s' "$m"
}

configurar_modelo() {
  if [ -z "$(modelo_actual)" ] && [ -t 0 ]; then
    echo
    echo "Modelo de IA del asistente de clientes"
    echo "  Elige proveedor y pega la clave de API (puede ser la misma del asistente del equipo)."
    echo "  Conviene un modelo rápido y económico: responde a cada mensaje de los clientes."
    como_usuario "$HERMES" model || true
  fi
  if [ -n "$(modelo_actual)" ]; then
    ok "Modelo de IA: $(modelo_actual)"
    return 0
  fi
  aviso "Falta elegir el modelo de IA: ssh -t root@IP \"mendiautos hermes --clientes\""
  return 1
}

pedir() {  # pedir VARIABLE "texto" oculto(0|1) patrón valor-dado
  local var=$1 texto=$2 oculto=$3 patron=$4 valor=$5
  if [ -z "$valor" ] && [ -z "$(valor_env "$var")" ] && [ -t 0 ]; then
    if [ "$oculto" = 1 ]; then
      read -r -s -p "  $texto (no se mostrará; Enter para dejarlo pendiente): " valor
      echo
    else
      read -r -p "  $texto (Enter para dejarlo pendiente): " valor
    fi
  fi
  valor=${valor// /}
  if [ -n "$valor" ]; then
    [[ $valor =~ $patron ]] || error "Eso no parece válido para $var."
    poner_env "$var" "$valor"
  fi
}

configurar_whatsapp_cloud() {
  if [ -t 0 ] && { [ -z "$(valor_env WHATSAPP_CLOUD_PHONE_NUMBER_ID)" ] || [ -z "$(valor_env WHATSAPP_CLOUD_ACCESS_TOKEN)" ] ||
      [ -z "$(valor_env WHATSAPP_CLOUD_APP_SECRET)" ]; }; then
    echo
    echo "WhatsApp oficial (Cloud API de Meta)"
    echo "  Los datos están en developers.facebook.com → tu app → WhatsApp → Configuración de la API."
  fi
  pedir WHATSAPP_CLOUD_PHONE_NUMBER_ID "Identificador del número de teléfono" 0 '^[0-9]{6,20}$' "$NUMERO_ID"
  pedir WHATSAPP_CLOUD_ACCESS_TOKEN "Token permanente (usuario del sistema)" 1 '^[A-Za-z0-9_-]{40,}$' "$TOKEN_META"
  pedir WHATSAPP_CLOUD_APP_SECRET "Clave secreta de la app" 1 '^[A-Za-z0-9]{16,64}$' "$APP_SECRET"
  # Lo que no es secreto de Meta se genera o se fija aquí.
  [ -n "$(valor_env WHATSAPP_CLOUD_VERIFY_TOKEN)" ] || poner_env WHATSAPP_CLOUD_VERIFY_TOKEN "$(openssl rand -hex 20)"
  poner_env WHATSAPP_CLOUD_WEBHOOK_HOST 127.0.0.1
  poner_env WHATSAPP_CLOUD_WEBHOOK_PORT "$PUERTO"
  poner_env WHATSAPP_CLOUD_ALLOW_ALL_USERS true      # atiende a cualquier cliente
  local falta=()
  [ -n "$(valor_env WHATSAPP_CLOUD_PHONE_NUMBER_ID)" ] || falta+=("identificador del número")
  [ -n "$(valor_env WHATSAPP_CLOUD_ACCESS_TOKEN)" ] || falta+=("token permanente")
  [ -n "$(valor_env WHATSAPP_CLOUD_APP_SECRET)" ] || falta+=("clave secreta de la app")
  if [ ${#falta[@]} -gt 0 ]; then
    aviso "Credenciales de Meta pendientes: $(IFS=,; echo "${falta[*]}" | sed 's/,/, /g')."
    return 1
  fi
  ok "WhatsApp oficial: credenciales de Meta configuradas"
}

# nginx publica /whatsapp/webhook solo con HTTPS y con el asistente activo.
publicar_webhook() {
  [ "$(leer_conf WEBHOOK_WHATSAPP)" = "$1" ] && return 0
  poner_conf WEBHOOK_WHATSAPP "$1"
  "$BIN" nginx > /dev/null
}

activar_servicio() {
  cat > "$UNIDAD" <<EOF
# Generado por hermes/clientes/instalar.sh (mendiautos hermes --clientes).
[Unit]
Description=Mendiautos: asistente de WhatsApp para clientes (Hermes Agent)
Wants=network-online.target
After=network-online.target mendiautos-solicitudes.service

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
# Atiende a desconocidos: solo puede escribir en su propia carpeta y no ve al
# asistente del equipo ni las solicitudes.
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=$CASA
InaccessiblePaths=-/home/hermes -/var/lib/mendiautos/solicitudes -/etc/mendiautos/solicitudes.token
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectKernelLogs=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
RestrictNamespaces=yes
LockPersonality=yes
MemoryMax=1500M

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable "$SERVICIO" > /dev/null 2>&1
  systemctl restart "$SERVICIO"
  local espera=0
  until curl -fsS --max-time 2 "http://127.0.0.1:$PUERTO/health" > /dev/null 2>&1 || [ "$espera" -ge 30 ]; do
    sleep 1
    espera=$((espera + 1))
  done
  if ! systemctl is-active --quiet "$SERVICIO"; then
    journalctl -u "$SERVICIO" -n 25 --no-pager >&2 || true
    error "El asistente de clientes no arrancó; arriba están sus últimos mensajes."
  fi
  ok "Asistente de clientes en marcha (servicio $SERVICIO)"
}

# Simula la verificación que hace Meta, por la dirección pública.
probar_webhook() {
  local dominio=$1 vt reto respuesta
  local intento=0
  vt=$(valor_env WHATSAPP_CLOUD_VERIFY_TOKEN)
  reto=prueba$RANDOM
  # nginx tarda un momento en aplicar la configuración nueva.
  until [ "${respuesta:-}" = "$reto" ] || [ "$intento" -ge 10 ]; do
    [ "$intento" -gt 0 ] && sleep 1
    respuesta=$(curl -fsS --max-time 10 "https://$dominio/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=$vt&hub.challenge=$reto" 2> /dev/null || true)
    intento=$((intento + 1))
  done
  if [ "$respuesta" = "$reto" ]; then
    ok "El webhook responde en https://$dominio/whatsapp/webhook"
  else
    aviso "El webhook no respondió por https://$dominio/whatsapp/webhook. Revisa: journalctl -u $SERVICIO -n 30"
  fi
}

instrucciones_meta() {
  local dominio=$1
  echo
  echo "Último paso, en developers.facebook.com → tu app → WhatsApp → Configuración:"
  echo "    URL de devolución de llamada:  https://$dominio/whatsapp/webhook"
  echo "    Token de verificación:         $(valor_env WHATSAPP_CLOUD_VERIFY_TOKEN)"
  echo "  Pulsa «Verificar y guardar» y, en «Campos del webhook», suscribe «messages»."
  echo "  Luego escríbele al número desde otro WhatsApp para probar."
}

# --------------------------------------------------------------- comandos
main() {
  NUMERO_ID="" TOKEN_META="" APP_SECRET=""
  local accion=instalar
  while [ $# -gt 0 ]; do
    case $1 in
      --numero-id) NUMERO_ID=${2:-}; shift 2 ;;
      --token-meta) TOKEN_META=${2:-}; shift 2 ;;
      --app-secret) APP_SECRET=${2:-}; shift 2 ;;
      --solo-archivos) accion=archivos; shift ;;
      --reiniciar) accion=reiniciar; shift ;;
      --actualizar) accion=actualizar; shift ;;
      --detener) accion=detener; shift ;;
      -h|--help|ayuda) uso; exit 0 ;;
      *) error "Opción desconocida: $1 (ver: mendiautos hermes --clientes --help)" ;;
    esac
  done
  [ "$(id -u)" -eq 0 ] || error "Ejecútalo como root: mendiautos hermes --clientes"
  [ -x /usr/local/bin/solicitudes ] || error "Falta el receptor de solicitudes. Primero: mendiautos actualizar --forzar"

  case $accion in
    archivos)
      id -u "$USUARIO" > /dev/null 2>&1 || exit 0
      if instalar_archivos && systemctl is-active --quiet "$SERVICIO"; then
        systemctl restart "$SERVICIO"   # el servidor de herramientas cambió
      fi
      ;;
    reiniciar)
      systemctl restart "$SERVICIO" && ok "Asistente de clientes reiniciado"
      ;;
    detener)
      systemctl disable --now "$SERVICIO" > /dev/null 2>&1 || true
      publicar_webhook ""
      ok "Asistente de clientes detenido (no borra nada). Para encenderlo: mendiautos hermes --clientes"
      ;;
    actualizar)
      [ -x "$HERMES" ] || error "No está instalado. Primero: mendiautos hermes --clientes"
      info "Actualizando Hermes del asistente de clientes…"
      como_usuario "$HERMES" update --yes
      instalar_archivos || true
      configurar_hermes
      systemctl restart "$SERVICIO" && ok "Asistente de clientes actualizado y reiniciado"
      ;;
    instalar)
      info "Asistente de WhatsApp para clientes de Mendiautos"
      local dominio listo=1
      dominio=$(dominio_https)
      crear_usuario
      instalar_hermes
      instalar_archivos || true
      configurar_hermes
      configurar_modelo || listo=0
      configurar_whatsapp_cloud || listo=0
      if [ -z "$dominio" ]; then
        aviso "Falta el dominio con HTTPS: Meta solo envía los mensajes a una dirección https://. Cuando tengas el acceso: mendiautos dominio tudominio.com"
        listo=0
      fi
      if [ "$listo" = 1 ]; then
        activar_servicio
        publicar_webhook "$PUERTO"
        probar_webhook "$dominio"
        instrucciones_meta "$dominio"
        echo
        ok "Listo. Estado: systemctl status $SERVICIO · Mensajes: journalctl -u $SERVICIO -f"
      else
        echo
        aviso "El asistente de clientes quedó instalado pero apagado. Cuando tengas lo pendiente, vuelve a correr: ssh -t root@IP \"mendiautos hermes --clientes\""
      fi
      ;;
  esac
}

main "$@"
