#!/usr/bin/env bash
# =============================================================================
#  hermes/instalar.sh — instala y configura el asistente del equipo de
#  Mendiautos (Hermes Agent) en la VPS: catálogo del sitio, portada, informes
#  y solicitudes de clientes, por Telegram. Se usa a través de mendiautos.sh:
#
#    ssh -t root@IP_DE_LA_VPS "mendiautos hermes"     (el -t permite responder)
#
#  Quién lo usa y con qué rol: mendiautos equipo (ver hermes/README.md).
#  El asistente de WhatsApp para clientes es aparte: mendiautos hermes --clientes
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
EQUIPO=/etc/mendiautos/equipo.json
MENDIAUTOS=/usr/local/bin/mendiautos
MODELO_POR_DEFECTO=gemini-3.5-flash     # Gemini (Google AI Studio): ve las fotos y es rápido
AUDIOS_POR_DEFECTO=small                # modelo local para transcribir audios (base, small o medium)
# Fotos que el asistente puede mostrar en el chat: las del catálogo, las de la
# portada y las que mandan los clientes en sus solicitudes (los documentos no).
MEDIOS_PERMITIDOS=(/var/lib/mendiautos/catalogo/fotos /var/lib/mendiautos/catalogo/medios
                   /var/lib/mendiautos/solicitudes/fotos)
SCRIPTS=(vigilar-sitio.sh informe-semanal.sh informe-mensual.sh borradores.sh resumen-ventas.sh
         avisos-ventas-telegram.sh avisos-ventas-whatsapp.sh)
# El modelo no tiene terminal, archivos, internet ni memoria compartida: solo
# las herramientas de Mendiautos (plugin) y «clarify» para los botones.
SIN_HERRAMIENTAS='[terminal, file, web, search, browser, code_execution, delegation, memory, session_search,
  skills, cronjob, todo, vision, video, image_gen, video_gen, tts, homeassistant, computer_use, x_search,
  spotify, kanban, connections]'

if [ -t 1 ]; then
  C_AZ=$'\e[1;34m' C_VE=$'\e[1;32m' C_AM=$'\e[1;33m' C_RO=$'\e[1;31m' C_NO=$'\e[0m'
else
  C_AZ='' C_VE='' C_AM='' C_RO='' C_NO=''
fi
info()  { printf '%s==>%s %s\n' "$C_AZ" "$C_NO" "$*"; }
ok()    { printf '%s ✓ %s %s\n' "$C_VE" "$C_NO" "$*"; }
aviso() { printf '%s ! %s %s\n' "$C_AM" "$C_NO" "$*" >&2; }
error() { printf '%s ✗ %s %s\n' "$C_RO" "$C_NO" "$*" >&2; exit 1; }

# Solo «mendiautos hermes» (con terminal) hace preguntas. «mendiautos equipo» y
# las actualizaciones automáticas nunca preguntan: con la salida oculta, una
# pregunta dejaría el comando esperando sin que se vea.
PREGUNTAR=0
se_puede_preguntar() { [ "$PREGUNTAR" = 1 ] && [ -t 0 ]; }

uso() {
  cat <<'EOF'
mendiautos hermes — asistente del equipo: catálogo, portada, informes y solicitudes.

  mendiautos hermes                   instala o completa la configuración
                                      (usa ssh -t para responder las preguntas)
  mendiautos hermes --token           cambia el token del bot de Telegram (lo pide sin mostrarlo)
  mendiautos hermes --clave-gemini    vuelve a pedir la clave de Gemini
  mendiautos hermes --modelo M        modelo de Gemini (por defecto gemini-3.5-flash)
  mendiautos hermes --otro-proveedor  elegir otro proveedor de IA con el asistente de Hermes
  mendiautos hermes --audios base|small|medium
                                      modelo para transcribir audios en el servidor
                                      (por defecto small; base gasta menos memoria)
  mendiautos hermes --clientes        asistente de WhatsApp oficial para clientes
                                      (mendiautos hermes --clientes --help)
  mendiautos hermes --whatsapp        (opcional) WhatsApp del equipo con un número dedicado
  mendiautos hermes --reiniciar       reinicia el asistente
  mendiautos hermes --actualizar      actualiza Hermes y lo reinicia
  mendiautos hermes --detener         apaga el asistente (no borra nada)
  mendiautos hermes --solo-archivos   solo actualiza reglas, extensión y tareas

Quién usa el asistente y con qué rol (administrador, gerente o vendedor):
  mendiautos equipo agregar <ID de Telegram> <nombre> <rol>
Cada persona ve su ID escribiéndole a @userinfobot en Telegram.
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

# Identifica esta versión del instalador y de la extensión (para aplicar sus cambios una vez).
huella() { cat "$AQUI/instalar.sh" "$AQUI"/plugin/mendiautos/*.py "$AQUI"/plugin/mendiautos/*.yaml | sha256sum | cut -c1-16; }

# ----------------------------------------------------------------- equipo
# id<TAB>nombre<TAB>rol por persona (lo escribe «mendiautos equipo»).
equipo() {
  python3 - "$EQUIPO" <<'EOF' 2> /dev/null || true
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding='utf-8'))
except (OSError, ValueError):
    sys.exit(0)
for m in d.get('miembros') or []:
    if isinstance(m, dict) and str(m.get('id', '')).isdigit() and m.get('rol') in ('administrador', 'gerente', 'vendedor'):
        print(f"{m['id']}\t{m.get('nombre', '')}\t{m['rol']}")
EOF
}
ids_de() {  # ids_de rol1 rol2… → IDs separados por coma
  local roles=" $* " id nombre rol res=""
  while IFS=$'\t' read -r id nombre rol; do
    [[ $roles == *" $rol "* ]] && res+=${res:+,}$id
  done < <(equipo)
  printf '%s' "$res"
}

pedir_equipo() {
  [ -n "$(equipo)" ] && return 0
  se_puede_preguntar || { aviso "El equipo está vacío: mendiautos equipo agregar <ID> <nombre> <rol>"; return 1; }
  echo
  echo "Equipo: quién puede usar el asistente"
  echo "  Cada persona le escribe a @userinfobot en Telegram y te pasa su «Id» (un número)."
  echo "  Roles: administrador y gerente (todo) · vendedor (sube autos y corrige los suyos)."
  local id nombre rol
  while :; do
    read -r -p "  ID de Telegram (Enter para terminar): " id
    id=${id// /}
    [ -n "$id" ] || break
    read -r -p "  Nombre: " nombre
    read -r -p "  Rol (administrador, gerente o vendedor): " rol
    MENDIAUTOS_SIN_APLICAR=1 "$MENDIAUTOS" equipo agregar "$id" "$nombre" "$rol" || true
  done
  [ -n "$(equipo)" ] || { aviso "El equipo quedó vacío: mendiautos equipo agregar <ID> <nombre> <rol>"; return 1; }
}

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
  apt_instalar git curl ca-certificates xz-utils libatomic1   # libatomic1: el Node.js que trae Hermes
  info "Instalando Hermes Agent para el usuario $USUARIO (tarda unos minutos)…"
  if ! curl -fsSL "$INSTALADOR" | como_hermes bash -s -- --non-interactive --skip-browser > "$REGISTRO" 2>&1; then
    tail -n 15 "$REGISTRO" >&2
    error "La instalación de Hermes falló. Detalle: $REGISTRO"
  fi
  [ -x "$HERMES" ] || error "La instalación terminó sin el comando hermes. Detalle: $REGISTRO"
  ok "Hermes instalado"
}

# Reglas, personalidad, extensión y tareas son de root: el asistente las usa,
# pero no las reescribe. Se actualizan con cada versión del repositorio.
instalar_archivos() {
  local sitio s
  sitio=$(leer_sitio)
  como_hermes mkdir -p "$HH/scripts" "$HH/plugins"
  install -d -o root -g root -m 0755 "$TRABAJO"
  sed "s|{{SITIO}}|${sitio:-el sitio}|g" "$AQUI/AGENTS.md" > "$TRABAJO/AGENTS.md"
  chmod 0644 "$TRABAJO/AGENTS.md"
  if [ -f "$HH/SOUL.md" ] && [ ! -e "$HH/SOUL.md.original" ] && ! cmp -s "$HH/SOUL.md" "$AQUI/SOUL.md"; then
    cp -p "$HH/SOUL.md" "$HH/SOUL.md.original"
  fi
  install -o root -g root -m 0644 "$AQUI/SOUL.md" "$HH/SOUL.md"
  # La extensión de Mendiautos: herramientas con permisos por persona.
  install -d -o root -g root -m 0755 "$HH/plugins/mendiautos"
  for s in "$AQUI"/plugin/mendiautos/*.py "$AQUI"/plugin/mendiautos/*.yaml; do
    install -o root -g root -m 0644 "$s" "$HH/plugins/mendiautos/$(basename "$s")"
  done
  rm -rf "$HH/plugins/mendiautos/__pycache__"
  for s in "${SCRIPTS[@]}"; do
    install -o root -g root -m 0755 "$AQUI/scripts/$s" "$HH/scripts/$s"
  done
  # De la versión anterior: las skills (ahora todo va en AGENTS.md) y el resumen del lunes.
  rm -rf "$HH/skills/mendiautos"
  rm -f "$HH/scripts/resumen-catalogo.sh"
  ok "Reglas, personalidad, extensión de Mendiautos y tareas copiadas"
}

# config.yaml: solo Telegram con las herramientas de Mendiautos, fotos que
# llegan como imagen, audios transcritos en el servidor y comandos «/» solo
# para el gerente y el administrador.
configurar_hermes() {
  python3 -c 'import yaml' 2> /dev/null || apt_instalar python3-yaml
  local cfg=$HH/config.yaml audios
  [ -f "$cfg" ] || como_hermes touch "$cfg"
  # El modelo de voz que ya se eligió (--audios) se conserva; si no, el predeterminado.
  # Solo cuenta si lo puso este instalador (stt.provider: local): Hermes siembra «base».
  audios=${AUDIOS:-$(python3 -c '
import sys, yaml
stt = (yaml.safe_load(open(sys.argv[1])) or {}).get("stt")
stt = stt if isinstance(stt, dict) else {}
local = stt.get("local") if isinstance(stt.get("local"), dict) else {}
print(local.get("model") or "" if stt.get("provider") == "local" else "")' \
    "$cfg" 2> /dev/null | grep -Ex 'tiny|base|small|medium' || true)}
  python3 - "$cfg" "$TRABAJO" "$SIN_HERRAMIENTAS" "${audios:-$AUDIOS_POR_DEFECTO}" "$(ids_de administrador gerente)" \
    "${MEDIOS_PERMITIDOS[@]}" <<'EOF' || { aviso "No pude escribir la configuración de Hermes ($cfg)."; return 1; }
import sys, yaml
ruta, trabajo, sin, audios, jefes = sys.argv[1:6]
medios = sys.argv[6:]
with open(ruta, encoding='utf-8') as f:
    cfg = yaml.safe_load(f) or {}


def seccion(d, clave):
    # Las versiones nuevas de Hermes siembran config.yaml con secciones vacías («gateway:»).
    v = d.get(clave)
    if not isinstance(v, dict):
        v = d[clave] = {}
    return v


seccion(cfg, 'terminal')['cwd'] = trabajo
cfg['timezone'] = 'America/Bogota'
seccion(cfg, 'approvals')['mode'] = 'manual'
agente = seccion(cfg, 'agent')
agente['disabled_toolsets'] = yaml.safe_load(sin)
agente['image_input_mode'] = 'native'           # las fotos llegan al modelo como imagen
herramientas = seccion(cfg, 'platform_toolsets')
herramientas['telegram'] = ['clarify', 'mendiautos', 'no_mcp']
herramientas['whatsapp'] = ['clarify', 'mendiautos', 'no_mcp']
plugins = seccion(cfg, 'plugins')
activos = [p for p in (plugins.get('enabled') or []) if p != 'mendiautos'] + ['mendiautos']
plugins['enabled'] = activos
pasarela = seccion(cfg, 'gateway')
pasarela['strict'] = True
pasarela['media_delivery_allow_dirs'] = medios
pasarela['trust_recent_files'] = False           # solo se envían archivos de esas carpetas y de la caché
tg = seccion(cfg, 'telegram')
tg['require_mention'] = True                     # en grupos, solo si lo mencionan
tg['unauthorized_dm_behavior'] = 'ignore'        # a quien no es del equipo no le contesta
lista = [x for x in jefes.split(',') if x]
if lista:
    tg['allow_admin_from'] = lista               # comandos «/» (modelo, reinicio…): solo ellos
    tg['user_allowed_commands'] = ['new', 'stop']
else:
    tg.pop('allow_admin_from', None)
# Hermes actual esconde herramientas tras un buscador (tool_search/tool_call): aquí son pocas
# y deben verse directo. Tampoco se ofrece la entrevista de perfil ni los consejos de Hermes.
seccion(seccion(cfg, 'tools'), 'tool_search')['enabled'] = 'off'
bienvenida = seccion(cfg, 'onboarding')
bienvenida['profile_build'] = 'off'
seccion(bienvenida, 'seen').update(profile_build_offered=True, busy_input_prompt=True, tool_progress_prompt=True)
seccion(cfg, 'cron')['wrap_response'] = False   # avisos e informes llegan limpios, sin encabezado técnico
voz = seccion(cfg, 'stt')
voz.update(enabled=True, echo_transcripts=True, provider='local', language='es')
seccion(voz, 'local').update(model=audios, language='es')
with open(ruta + '.tmp', 'w', encoding='utf-8') as f:
    yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
EOF
  chown "$USUARIO:$USUARIO" "$cfg.tmp"
  chmod 0600 "$cfg.tmp"
  mv -f "$cfg.tmp" "$cfg"
  ok "Configuración: solo las herramientas de Mendiautos, fotos como imagen y audios en español en el servidor (${audios:-$AUDIOS_POR_DEFECTO})"
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
  local token=$TOKEN todos admin
  if [ -z "$token" ] && { [ -z "$(valor_env TELEGRAM_BOT_TOKEN)" ] || [ "$PEDIR_TOKEN" = 1 ]; } && se_puede_preguntar; then
    echo
    echo "Bot de Telegram"
    if [ "$PEDIR_TOKEN" = 1 ]; then
      echo "  En @BotFather: /mybots → tu bot → API Token (o «Revoke current token» para uno nuevo)."
    else
      echo "  1. En Telegram, abre @BotFather y envía /newbot."
      echo "  2. Ponle un nombre (por ejemplo «Mendiautos Equipo») y un usuario que termine en «bot»."
      echo "  3. BotFather te da un token, algo como 123456789:AAH…"
    fi
    echo "  Al pegarlo no se ve nada en pantalla: es normal. Pégalo una vez y presiona Enter."
    read -r -s -p "  Token (Enter sin pegar nada para omitir): " token
    echo
    token=${token//[[:space:]]/}
    [ -n "$token" ] || [ "$PEDIR_TOKEN" = 0 ] || aviso "No cambié el token."
  fi
  if [ -n "$token" ]; then
    [[ $token =~ ^[0-9]{5,}:[A-Za-z0-9_-]{30,}$ ]] || error "Eso no parece un token de @BotFather."
    poner_env TELEGRAM_BOT_TOKEN "$token"
    ok "Token de Telegram recibido y guardado"
  fi
  # Quién puede escribirle: todo el equipo. Los avisos de Hermes van al primer administrador.
  todos=$(ids_de administrador gerente vendedor)
  admin=$(ids_de administrador)
  admin=${admin%%,*}
  if [ -n "$todos" ]; then
    poner_env TELEGRAM_ALLOWED_USERS "$todos"
    poner_env TELEGRAM_HOME_CHANNEL "${admin:-${todos%%,*}}"
  fi
  if telegram_activo; then
    instalar_extra telegram || { aviso "No pude instalar el soporte de Telegram de Hermes (detalle: $REGISTRO)."; return 1; }
    ok "Telegram: bot configurado; equipo: $(equipo | awk -F '\t' '{printf "%s%s (%s)", (NR > 1 ? ", " : ""), $2, $3}')"
    return 0
  fi
  if [ -z "$(valor_env TELEGRAM_BOT_TOKEN)" ]; then
    aviso "Telegram: falta el token del bot; lo pide «mendiautos hermes» (o: mendiautos hermes --token)."
  else
    aviso "Telegram: falta el equipo (mendiautos equipo agregar <ID> <nombre> <rol>)."
  fi
  return 1
}

# WhatsApp del equipo (opcional): un número dedicado al asistente, vinculado
# con un QR como WhatsApp Web. Es un puente no oficial. Los permisos por
# persona funcionan por Telegram: por WhatsApp el asistente solo conversa.
configurar_whatsapp() {
  local usuarios=${WA_USUARIOS// /} n lista=() primero
  if [ -z "$usuarios" ] && [ -z "$(valor_env WHATSAPP_ALLOWED_USERS)" ] && se_puede_preguntar; then
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
  [[ -n $m && $m != *"not set"* && $m != *rror* && $m != None ]] && printf '%s' "$m"
}

# Revisa la clave con Google sin mostrarla (no queda en la lista de procesos).
probar_clave_gemini() {
  local codigo
  codigo=$(printf 'header = "x-goog-api-key: %s"\n' "$1" |
    curl -sS -o /dev/null -w '%{http_code}' --max-time 20 -K - \
      'https://generativelanguage.googleapis.com/v1beta/models?pageSize=1' 2> /dev/null) || codigo=000
  case $codigo in
    200) return 0 ;;
    400|401|403) return 1 ;;
    *) aviso "No pude comprobar la clave con Google (respuesta $codigo); la guardo igual."; return 0 ;;
  esac
}

# Gemini: se pide la clave de Google AI Studio y se configura directo (el
# asistente interactivo de Hermes no acepta claves del plan gratuito). Hermes
# siembra config.yaml con un modelo de ejemplo de otro proveedor: ese no cuenta.
# Solo se usa otro proveedor si se eligió con --otro-proveedor.
OTRO=$HH/.mendiautos-otro-proveedor

poner_modelo_gemini() {  # poner_modelo_gemini MODELO
  local cfg=$HH/config.yaml
  python3 - "$cfg" "$1" <<'EOF' || return 1
import sys, yaml
ruta, modelo = sys.argv[1:3]
with open(ruta, encoding='utf-8') as f:
    cfg = yaml.safe_load(f) or {}
anterior = cfg.get('model') if isinstance(cfg.get('model'), dict) else {}
# La clave va en .env (GEMINI_API_KEY); no se arrastran la URL ni la clave de otro proveedor.
cfg['model'] = {k: v for k, v in anterior.items() if k not in ('provider', 'default', 'base_url', 'api_key', 'api_mode')}
cfg['model'].update(provider='gemini', default=modelo)
with open(ruta + '.tmp', 'w', encoding='utf-8') as f:
    yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
EOF
  chown "$USUARIO:$USUARIO" "$cfg.tmp"
  chmod 0600 "$cfg.tmp"
  mv -f "$cfg.tmp" "$cfg"
}

configurar_modelo() {
  local clave="" proveedor actual
  if [ "$OTRO_PROVEEDOR" = 1 ]; then
    [ -t 0 ] || error "--otro-proveedor necesita responder preguntas: ssh -t root@IP \"mendiautos hermes --otro-proveedor\""
    echo
    echo "Modelo de IA: elige proveedor y modelo, y pega la clave. Recomendado: uno que vea imágenes."
    como_hermes "$HERMES" model || true
    touch "$OTRO"
  fi
  if [ -f "$OTRO" ] && [ "$PEDIR_CLAVE" = 0 ] && [ -z "$MODELO" ]; then
    proveedor=$(como_hermes "$HERMES" config get model.provider 2> /dev/null | tail -n 1)
    if [ -n "$(modelo_actual)" ] && [[ $proveedor != auto && $proveedor != *"not set"* ]]; then
      ok "Modelo de IA: $(modelo_actual) ($proveedor)"
      return 0
    fi
    aviso "Falta elegir el modelo de IA: ssh -t root@IP \"mendiautos hermes --otro-proveedor\" (o --clave-gemini para volver a Gemini)"
    return 1
  fi
  if { [ -z "$(valor_env GEMINI_API_KEY)" ] || [ "$PEDIR_CLAVE" = 1 ]; } && se_puede_preguntar; then
    echo
    echo "Clave de Gemini (Google AI Studio)"
    echo "  1. Entra a https://aistudio.google.com/apikey con la cuenta de Google de la empresa."
    echo "  2. «Create API key» y cópiala. Mejor en un proyecto con facturación activa: el plan"
    echo "     gratuito tiene pocos mensajes por minuto y Google puede usar esos datos."
    echo "  Al pegarla no se ve nada en pantalla: es normal. Pégala una vez y presiona Enter."
    read -r -s -p "  Clave (Enter sin pegar nada para dejarla pendiente): " clave
    echo
    clave=${clave//[[:space:]]/}
  fi
  if [ -n "$clave" ]; then
    [[ $clave =~ ^[A-Za-z0-9_-]{30,80}$ ]] || error "Eso no parece una clave de Google AI Studio."
    probar_clave_gemini "$clave" || error "Google rechazó la clave. Revísala en https://aistudio.google.com/apikey"
    poner_env GEMINI_API_KEY "$clave"
  fi
  if [ -z "$(valor_env GEMINI_API_KEY)" ]; then
    aviso "Falta la clave de Gemini. Corre: ssh -t root@IP \"mendiautos hermes\""
    return 1
  fi
  # El modelo: --modelo, o el de Gemini que ya estaba, o el predeterminado.
  actual=$(modelo_actual)
  [ "$(como_hermes "$HERMES" config get model.provider 2> /dev/null | tail -n 1)" = gemini ] && [[ $actual == gemini* ]] || actual=""
  poner_modelo_gemini "${MODELO:-${actual:-$MODELO_POR_DEFECTO}}" || error "No pude guardar el modelo en $HH/config.yaml"
  rm -f "$OTRO"
  ok "Modelo de IA: $(modelo_actual) (Gemini)"
}

# Hermes actual instala aparte lo de cada plataforma o función (su gestor «pm»);
# se deja listo aquí para no depender de que el servicio lo instale al arrancar.
# Hermes 0.19 y anteriores no tienen pm (ya traían Telegram).
con_pm() { como_hermes "$HERMES" pm --help > /dev/null 2>&1; }

instalar_extra() {  # instalar_extra NOMBRE
  con_pm || return 0
  como_hermes "$HERMES" pm install --extra "$1" < /dev/null >> "$REGISTRO" 2>&1
}

# Deja listo el modelo de voz (se descarga una vez, unos cientos de MB) para
# que el primer audio no tarde. Si falla, se reintenta solo con el primer audio.
instalar_voz() {
  if con_pm; then
    como_hermes "$HERMES" pm install --extra stt-whisper < /dev/null
  else
    como_hermes bash -c "
      py=\$(head -n 1 '$HERMES' | sed -n 's|^#! *||p' | awk '{print \$1}')
      [ -x \"\$py\" ] || py=python3
      \"\$py\" -c 'from tools.lazy_deps import activate_durable_lazy_target as a, ensure
a(); ensure(\"stt.faster_whisper\", prompt=False)'"
  fi
}

# Descarga y carga el modelo con el mismo Python con el que corre Hermes.
precargar_voz() {
  como_hermes python3 - "$HERMES" "$1" <<'EOF'
import json, subprocess, sys
hermes, modelo = sys.argv[1:3]
codigo = ('from faster_whisper import WhisperModel\n'
          f'WhisperModel({modelo!r}, device="cpu", compute_type="int8")\n')
marca = "runpy.run_module('hermes_cli.main', run_name='__main__', alter_sys=True)"
cmd = None
try:
    salida = subprocess.run([hermes, '--print-runtime-command'], capture_output=True, text=True, timeout=120).stdout
    cmd = json.loads(salida)
    i = next(i for i, parte in enumerate(cmd) if marca in parte)
    cmd[i] = cmd[i].replace(marca, f'exec({codigo!r})')
except Exception:
    # Hermes 0.19 y anteriores: el script hermes es Python y su primera línea dice cuál.
    with open(hermes, encoding='utf-8', errors='replace') as f:
        primera = f.readline()
    cmd = [primera[2:].split()[0], '-c', codigo] if primera.startswith('#!') and 'python' in primera else None
if not cmd:
    sys.exit('No encontré el Python de Hermes.')
sys.exit(subprocess.run(cmd).returncode)
EOF
}

preparar_audios() {
  local modelo
  modelo=$(como_hermes "$HERMES" config get stt.local.model 2> /dev/null | tail -n 1)
  [[ $modelo =~ ^(tiny|base|small|medium)$ ]] || modelo=$AUDIOS_POR_DEFECTO
  [ -f "$HH/.mendiautos-audios-$modelo" ] && return 0
  info "Preparando la transcripción de audios en el servidor (modelo $modelo; la primera vez tarda)…"
  if instalar_voz >> "$REGISTRO" 2>&1 && precargar_voz "$modelo" >> "$REGISTRO" 2>&1; then
    touch "$HH/.mendiautos-audios-$modelo"
    ok "Audios: se transcriben en el servidor (español, modelo $modelo)"
  else
    aviso "No pude preparar la transcripción de audios ahora; se intentará con el primer audio (detalle: $REGISTRO)."
  fi
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
        v = tarea.get(sys.argv[3])
        print(','.join(v) if isinstance(v, list) else (v or ''))
        break
EOF
}

nombres_tareas() {
  python3 - "$HH/cron/jobs.json" <<'EOF' 2> /dev/null || true
import json, sys
try:
    datos = json.load(open(sys.argv[1], encoding='utf-8'))
except (OSError, ValueError):
    sys.exit(0)
for tarea in (datos.get('jobs') if isinstance(datos, dict) else datos) or []:
    print(tarea.get('name') or '')
EOF
}

# Crea la tarea, o la rehace si cambió su horario, su script o su destino.
asegurar_tarea() {
  local nombre=$1 horario=$2 script=$3 destino=$4 id
  id=$(dato_tarea "$nombre" id)
  if [ -n "$id" ] && [ "$(dato_tarea "$nombre" script)" = "$script" ] &&
     [ "$(dato_tarea "$nombre" deliver)" = "$destino" ] && [ "$(dato_tarea "$nombre" schedule_display)" = "$horario" ]; then
    return 0
  fi
  [ -z "$id" ] || como_hermes "$HERMES" cron remove "$id" > /dev/null 2>&1 || true
  como_hermes "$HERMES" cron create "$horario" --name "$nombre" --no-agent --script "$script" --deliver "$destino" > /dev/null
}

quitar_tarea() {
  local id
  id=$(dato_tarea "$1" id)
  [ -z "$id" ] || como_hermes "$HERMES" cron remove "$id" > /dev/null 2>&1 || true
}

# Script de una línea por persona (Hermes no pasa argumentos a los scripts).
script_de() {  # script_de base.sh ID → nombre del script de esa persona
  local base=$1 id=$2 nombre
  nombre="${base%.sh}-$id.sh"
  [ "$base" = avisos-ventas-telegram.sh ] && nombre="avisos-ventas-$id.sh"
  printf '#!/usr/bin/env bash\n# Generado por hermes/instalar.sh para %s.\nexec bash "$(dirname "$0")/%s" %s\n' \
    "$id" "$base" "$id" > "$HH/scripts/$nombre.tmp"
  chown root:root "$HH/scripts/$nombre.tmp"
  chmod 0755 "$HH/scripts/$nombre.tmp"
  mv -f "$HH/scripts/$nombre.tmp" "$HH/scripts/$nombre"
  printf '%s' "$nombre"
}

destinos() {  # "111,222" → "telegram:111,telegram:222"
  local id res=""
  for id in ${1//,/ }; do res+=${res:+,}telegram:$id; done
  printf '%s' "$res"
}

# Quién recibe qué, según el equipo:
#   gerente y administrador: solicitudes nuevas (cada uno por su chat), resumen
#   de ventas diario, informe semanal (sábado 8:00) y mensual (día 1, 8:00);
#   administrador: vigilante del sitio; cada persona: sus borradores por vencer.
configurar_tareas() {
  local jefes admins todos id nombre usadas=() t
  jefes=$(ids_de administrador gerente)
  admins=$(ids_de administrador)
  todos=$(ids_de administrador gerente vendedor)
  [ -n "$jefes" ] || { aviso "No hay gerente ni administrador en el equipo: no programo avisos ni informes."; return 1; }
  asegurar_tarea vigilar-sitio "every 30m" vigilar-sitio.sh "$(destinos "${admins:-$jefes}")"
  asegurar_tarea resumen-ventas "30 7 * * *" resumen-ventas.sh "$(destinos "$jefes")"
  asegurar_tarea informe-semanal "0 8 * * 6" informe-semanal.sh "$(destinos "$jefes")"
  asegurar_tarea informe-mensual "0 8 1 * *" informe-mensual.sh "$(destinos "$jefes")"
  usadas+=(vigilar-sitio resumen-ventas informe-semanal informe-mensual)
  for id in ${jefes//,/ }; do
    asegurar_tarea "avisos-ventas-$id" "every 1m" "$(script_de avisos-ventas-telegram.sh "$id")" "telegram:$id"
    usadas+=("avisos-ventas-$id")
  done
  for id in ${todos//,/ }; do
    asegurar_tarea "borradores-$id" "0 9 * * *" "$(script_de borradores.sh "$id")" "telegram:$id"
    usadas+=("borradores-$id")
  done
  if whatsapp_activo; then
    asegurar_tarea avisos-ventas-whatsapp "every 1m" avisos-ventas-whatsapp.sh whatsapp
    usadas+=(avisos-ventas-whatsapp)
  fi
  # Tareas de personas que ya no están (o de la versión anterior).
  while read -r t; do
    [[ $t =~ ^(avisos-ventas-|borradores-|resumen-catalogo$|avisos-ventas-telegram$|avisos-ventas-whatsapp$) ]] || continue
    [[ " ${usadas[*]} " == *" $t "* ]] || quitar_tarea "$t"
  done < <(nombres_tareas)
  for t in "$HH"/scripts/avisos-ventas-[0-9]*.sh "$HH"/scripts/borradores-[0-9]*.sh; do
    [ -e "$t" ] || continue
    [[ " ${usadas[*]} " == *" $(basename "${t%.sh}") "* ]] || rm -f "$t"
  done
  ok "Tareas: solicitudes nuevas y resumen de ventas (7:30) para el gerente y el administrador;" \
    "informe los sábados y el día 1 a las 8:00; vigilante del sitio; aviso de borradores por vencer a cada uno"
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

# El equipo cambió (mendiautos equipo): quién puede escribirle, los comandos
# «/» y a quién le llegan los avisos e informes.
aplicar_equipo() {
  [ -x "$HERMES" ] || return 0
  configurar_hermes > /dev/null
  configurar_telegram > /dev/null || true
  if telegram_activo; then configurar_tareas > /dev/null || true; fi
  if systemctl is-active --quiet "$SERVICIO"; then
    systemctl restart "$SERVICIO"
    ok "Asistente actualizado con el equipo nuevo y reiniciado"
  else
    ok "Equipo guardado; el asistente lo usará cuando arranque (mendiautos hermes)"
  fi
}

# --------------------------------------------------------------- comandos
main() {
  TOKEN="" WA_USUARIOS="" MODELO="" AUDIOS="" PEDIR_CLAVE=0 PEDIR_TOKEN=0 OTRO_PROVEEDOR=0
  local accion=instalar servicio=1 whatsapp=0
  if [ "${1:-}" = --clientes ]; then
    shift
    exec bash "$AQUI/clientes/instalar.sh" "$@"
  fi
  while [ $# -gt 0 ]; do
    case $1 in
      --token)   # sin valor: lo pide sin mostrarlo (un valor escrito aquí queda en el historial)
        if [ $# -ge 2 ] && [[ $2 != -* ]]; then TOKEN=$2; shift 2; else PEDIR_TOKEN=1; shift; fi ;;
      --modelo) MODELO=${2:-}; shift 2 ;;
      --clave-gemini) PEDIR_CLAVE=1; shift ;;
      --otro-proveedor) OTRO_PROVEEDOR=1; shift ;;
      --audios) AUDIOS=${2:-}; shift 2 ;;
      --whatsapp) whatsapp=1; shift ;;
      --whatsapp-usuarios) WA_USUARIOS=${2:-}; whatsapp=1; shift 2 ;;
      --sin-servicio) servicio=0; shift ;;
      --solo-archivos) accion=archivos; shift ;;
      --equipo) accion=equipo; shift ;;
      --reiniciar) accion=reiniciar; shift ;;
      --actualizar) accion=actualizar; shift ;;
      --detener) accion=detener; shift ;;
      --usuarios|--avisos|--canal-ventas|--canal-catalogo)
        error "$1 ya no se usa: el equipo y sus roles se manejan con «mendiautos equipo» (avisos e informes llegan al gerente y al administrador)." ;;
      --clientes) error "--clientes va solo, al principio: mendiautos hermes --clientes --help" ;;
      -h|--help|ayuda) uso; exit 0 ;;
      *) error "Opción desconocida: $1 (ver: mendiautos hermes --help)" ;;
    esac
  done
  [ -z "$AUDIOS" ] || [[ $AUDIOS =~ ^(tiny|base|small|medium)$ ]] || error "--audios es base, small o medium."
  [ -z "$MODELO" ] || [[ $MODELO =~ ^gemini-[a-z0-9.-]+$ ]] || error "--modelo es un modelo de Gemini, por ejemplo $MODELO_POR_DEFECTO."
  [ "$(id -u)" -eq 0 ] || error "Ejecútalo como root: mendiautos hermes"
  [ -x /usr/local/bin/catalogo ] || error "Falta el comando catalogo. Primero: mendiautos instalar"
  [ -x /usr/local/bin/solicitudes ] || error "Falta el comando solicitudes. Primero: mendiautos actualizar --forzar"
  if [ "$accion" = instalar ]; then
    PREGUNTAR=1
    [ "$PEDIR_TOKEN" = 0 ] || [ -t 0 ] || error "--token pregunta el token sin mostrarlo; usa: ssh -t root@IP \"mendiautos hermes --token\""
  fi

  case $accion in
    archivos)
      id -u "$USUARIO" > /dev/null 2>&1 || exit 0   # sin asistente instalado no hay nada que hacer
      instalar_archivos
      # Un grupo nuevo o una versión nueva de este instalador o de la extensión
      # se aplican solos; el servicio se reinicia solo si hace falta.
      local cambio=0
      asegurar_grupos && cambio=1
      if [ -x "$HERMES" ] && [ "$(cat "$HH/.mendiautos-instalador" 2> /dev/null)" != "$(huella)" ]; then
        # La huella se guarda solo si la configuración quedó aplicada; si no, se reintenta.
        local aplicada=1
        configurar_hermes > /dev/null || aplicada=0
        configurar_telegram > /dev/null || true
        if telegram_activo || whatsapp_activo; then configurar_tareas > /dev/null || aplicada=0; fi
        [ -f "$UNIDAD" ] && escribir_unidad
        [ "$aplicada" = 0 ] || huella > "$HH/.mendiautos-instalador"
        cambio=1
      fi
      if [ "$cambio" = 1 ] && systemctl is-active --quiet "$SERVICIO"; then
        systemctl restart "$SERVICIO"
      fi
      ;;
    equipo)
      id -u "$USUARIO" > /dev/null 2>&1 || exit 0
      aplicar_equipo
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
      pedir_equipo || true
      configurar_hermes
      local modelo=1 canales=0
      configurar_modelo || modelo=0
      configurar_telegram && canales=1 || true
      if [ "$whatsapp" = 1 ] || [ "$(valor_env WHATSAPP_ENABLED)" = true ]; then
        configurar_whatsapp && canales=1 || true
      fi
      preparar_audios
      if [ "$canales" = 0 ]; then
        aviso "Falta el bot de Telegram o el equipo: ssh -t root@IP \"mendiautos hermes\" y mendiautos equipo agregar …"
      fi
      if [ "$canales" = 1 ]; then
        configurar_tareas || true
        huella > "$HH/.mendiautos-instalador"
      fi
      if [ "$servicio" = 1 ] && [ "$modelo" = 1 ] && [ "$canales" = 1 ]; then
        activar_servicio
        echo
        ok "Listo. Cada persona del equipo le escribe «/start» al bot una vez (un bot no puede escribir primero)."
        echo "    Equipo:       mendiautos equipo"
        echo "    Estado:       systemctl status $SERVICIO"
        echo "    Mensajes:     journalctl -u $SERVICIO -f"
        echo "    Reiniciar:    mendiautos hermes --reiniciar"
        echo "    Apagar:       mendiautos hermes --detener"
      elif [ "$modelo" = 0 ] || [ "$canales" = 0 ]; then
        aviso "El asistente quedó instalado pero no arrancado: completa lo que falta y vuelve a correr «mendiautos hermes»."
      fi
      ;;
  esac
}

main "$@"
