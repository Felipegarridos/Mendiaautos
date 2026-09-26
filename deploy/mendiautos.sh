#!/usr/bin/env bash
# =============================================================================
#  mendiautos.sh — instala, publica y mantiene el sitio Mendiautos en una VPS
#  Ubuntu o Debian, servido por nginx.  Guía completa: deploy/README.md
#
#  Primera vez (desde tu PC, en PowerShell o en una terminal):
#    ssh root@IP_DE_LA_VPS "curl -fsSL https://raw.githubusercontent.com/Felipegarridos/Mendiaautos/main/deploy/mendiautos.sh | bash -s -- instalar"
#
#  Después, dentro de la VPS:
#    mendiautos estado                    qué versión está publicada
#    mendiautos actualizar                trae lo último de GitHub y lo publica
#    mendiautos revertir                  vuelve a la versión anterior
#    mendiautos dominio ejemplo.com [correo@ejemplo.com]   activa HTTPS
#    mendiautos hermes                    instala el asistente de Telegram
#    catalogo --help                      edita los autos del sitio
#    solicitudes pendientes               lo que llegó por los formularios
# =============================================================================
set -euo pipefail

# --------------------------------------------------------------- valores base
REPO_POR_DEFECTO="https://github.com/Felipegarridos/Mendiaautos.git"
RAMA_POR_DEFECTO="main"

CONF=/etc/mendiautos.conf           # repo, rama, dominio y correo elegidos
APP=/opt/mendiautos                 # copia del repositorio y caché
REPO_DIR=$APP/repo
CACHE=$APP/cache
WEB=/var/www/mendiautos
RELEASES=$WEB/releases              # una carpeta por versión publicada
CURRENT=$WEB/current                # enlace a la versión activa
ACME=/var/www/letsencrypt           # validación de Let's Encrypt
STATE=/var/lib/mendiautos
CATALOGO=$STATE/catalogo            # autos del sitio: los edita el comando catalogo
RESPALDOS=/var/backups/mendiautos   # copias diarias del catálogo
SITE=/etc/nginx/sites-available/mendiautos
SITE_LINK=/etc/nginx/sites-enabled/mendiautos
SNIP_SITIO=/etc/nginx/snippets/mendiautos-sitio.conf
SNIP_CABECERAS=/etc/nginx/snippets/mendiautos-cabeceras.conf
BIN=/usr/local/bin/mendiautos
BIN_CATALOGO=/usr/local/bin/catalogo
SUDOERS_CATALOGO=/etc/sudoers.d/mendiautos-catalogo
SOLICITUDES=$STATE/solicitudes      # formularios del sitio: los recibe el comando solicitudes
BIN_SOLICITUDES=/usr/local/bin/solicitudes
SUDOERS_SOLICITUDES=/etc/sudoers.d/mendiautos-solicitudes
TOKEN_SOLICITUDES=/etc/mendiautos/solicitudes.token   # clave del asistente de clientes
PUERTO_SOLICITUDES=8781             # receptor (solo en 127.0.0.1; nginx le pasa /api/)
MANTENER=5                          # versiones anteriores que se conservan

# ----------------------------------------------------------------- mensajes
if [ -t 1 ]; then
  C_AZ=$'\e[1;34m' C_VE=$'\e[1;32m' C_AM=$'\e[1;33m' C_RO=$'\e[1;31m' C_NO=$'\e[0m'
else
  C_AZ='' C_VE='' C_AM='' C_RO='' C_NO=''
fi
INFORMADO=0
info()  { printf '%s==>%s %s\n' "$C_AZ" "$C_NO" "$*"; }
ok()    { printf '%s ✓ %s %s\n' "$C_VE" "$C_NO" "$*"; }
aviso() { printf '%s ! %s %s\n' "$C_AM" "$C_NO" "$*" >&2; }
error() { printf '%s ✗ %s %s\n' "$C_RO" "$C_NO" "$*" >&2; INFORMADO=1; exit 1; }
al_salir() {
  local rc=$? cmd=$BASH_COMMAND
  if [ "$rc" -ne 0 ] && [ "$INFORMADO" = 0 ]; then
    printf '%s ✗ %s Se detuvo por un error (código %s) en: %s\n' "$C_RO" "$C_NO" "$rc" "$cmd" >&2
  fi
}
trap al_salir EXIT

# ------------------------------------------------------------- utilidades
requiere_root() {
  [ "$(id -u)" -eq 0 ] || error "Ejecútalo como root (o con sudo)."
}

cargar_conf() {
  REPO=$REPO_POR_DEFECTO RAMA=$RAMA_POR_DEFECTO DOMINIO="" CORREO="" AUTO=1 SITIO=""
  # Días que se guardan los documentos (cédulas, extractos) y las solicitudes.
  RETENER_DOCUMENTOS=90 RETENER_SOLICITUDES=730
  WEBHOOK_WHATSAPP=""               # puerto del WhatsApp oficial de clientes (lo pone mendiautos hermes)
  # shellcheck disable=SC1090
  [ -f "$CONF" ] && . "$CONF"
  return 0
}

guardar_conf() {
  umask 022
  {
    echo "# Configuración de mendiautos.sh (se puede editar)"
    printf 'REPO=%q\nRAMA=%q\nDOMINIO=%q\nCORREO=%q\nAUTO=%q\nSITIO=%q\n' \
      "$REPO" "$RAMA" "$DOMINIO" "$CORREO" "$AUTO" "$SITIO"
    printf 'RETENER_DOCUMENTOS=%q\nRETENER_SOLICITUDES=%q\nWEBHOOK_WHATSAPP=%q\n' \
      "$RETENER_DOCUMENTOS" "$RETENER_SOLICITUDES" "$WEBHOOK_WHATSAPP"
  } > "$CONF"
}

apt_instalar() {
  DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=600 -y -q \
    -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold \
    install --no-install-recommends "$@" > /dev/null
}

sha384() { printf 'sha384-%s' "$(openssl dgst -sha384 -binary "$1" | openssl base64 -A)"; }

ip_publica() {
  curl -4 -fsS --max-time 5 https://api.ipify.org 2>/dev/null ||
    curl -4 -fsS --max-time 5 https://ifconfig.me 2>/dev/null ||
    hostname -I 2>/dev/null | awk '{print $1}'
}

version_nginx_ge_1_25_1() {
  local v
  v=$(nginx -v 2>&1 | sed -n 's|.*nginx/\([0-9.]*\).*|\1|p')
  [ -n "$v" ] && printf '%s\n%s\n' 1.25.1 "$v" | sort -V -C
}

# ------------------------------------------------------ preparación del VPS
revisar_sistema() {
  [ -r /etc/os-release ] || error "No reconozco este sistema operativo."
  # shellcheck disable=SC1091
  . /etc/os-release
  case " ${ID:-} ${ID_LIKE:-} " in
    *" debian "*|*" ubuntu "*) ;;
    *) error "Este script es para Ubuntu o Debian (detecté: ${PRETTY_NAME:-desconocido})." ;;
  esac
  ok "Sistema: ${PRETTY_NAME:-$ID}"
  command -v systemctl > /dev/null || error "Se necesita systemd."
}

revisar_puerto_80() {
  local ocupado
  ocupado=$(ss -Htlnp 'sport = :80' 2>/dev/null | grep -v nginx || true)
  if [ -n "$ocupado" ]; then
    aviso "El puerto 80 lo está usando otro programa:"
    printf '    %s\n' "$ocupado" >&2
    error "Libéralo primero (por ejemplo, si es Apache y no lo usas: systemctl disable --now apache2) y vuelve a correr la instalación."
  fi
}

instalar_paquetes() {
  info "Instalando paquetes (nginx, git, firewall, fail2ban, actualizaciones automáticas)…"
  DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=600 -q update > /dev/null
  apt_instalar nginx git curl ca-certificates openssl iproute2 ufw fail2ban \
    python3-systemd unattended-upgrades python3 python3-pil sudo
  systemctl enable --now nginx > /dev/null 2>&1 || true
  ok "Paquetes instalados"
}

configurar_actualizaciones() {
  cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
  ok "Actualizaciones de seguridad automáticas activadas"
}

configurar_firewall() {
  local puertos_ssh otros p
  # Puertos de SSH: los de la configuración, los que escucha sshd y el de la
  # sesión actual. Nunca se bloquea el puerto por el que estás conectado.
  puertos_ssh=$( {
    sshd -T 2>/dev/null | awk '$1 == "port" {print $2}' || true
    ss -Htlnp 2>/dev/null | awk '/sshd|"ssh"/ {n = split($4, a, ":"); print a[n]}' || true
    if [ -n "${SSH_CONNECTION:-}" ]; then awk '{print $4}' <<< "$SSH_CONNECTION"; fi
  } | grep -E '^[0-9]+$' | sort -un || true)
  [ -n "$puertos_ssh" ] || puertos_ssh=22

  if [[ $(ufw status 2>/dev/null || true) == *"Status: active"* ]]; then
    for p in $puertos_ssh; do ufw allow "$p/tcp" > /dev/null; done
    ufw allow 80/tcp > /dev/null
    ufw allow 443/tcp > /dev/null
    ok "Firewall (ya activo): abiertos 80 y 443, SSH en $(echo $puertos_ssh)"
    return
  fi

  # Otros servicios públicos que un firewall nuevo dejaría sin acceso.
  otros=$(ss -Htln 2>/dev/null | awk '{print $4}' |
    grep -vE '^(127\.|\[::1\]|::1)' | sed 's/.*://' | sort -un |
    grep -vxE "80|443|$(echo $puertos_ssh | tr ' ' '|')" || true)
  if [ -n "$otros" ]; then
    aviso "No activé el firewall: hay otros servicios escuchando en los puertos $(echo $otros). Revísalos y actívalo a mano (ufw allow <puerto>; ufw enable)."
    return
  fi
  ufw default deny incoming > /dev/null
  ufw default allow outgoing > /dev/null
  for p in $puertos_ssh; do ufw allow "$p/tcp" > /dev/null; done
  ufw allow 80/tcp > /dev/null
  ufw allow 443/tcp > /dev/null
  ufw --force enable > /dev/null
  ok "Firewall activo: solo SSH ($(echo $puertos_ssh)), HTTP (80) y HTTPS (443)"
}

configurar_fail2ban() {
  mkdir -p /etc/fail2ban/jail.d
  cat > /etc/fail2ban/jail.d/mendiautos.local <<'EOF'
# Bloquea por 1 hora las IP que fallan 5 veces el acceso SSH en 10 minutos.
[sshd]
enabled  = true
backend  = systemd
maxretry = 5
findtime = 10m
bantime  = 1h
EOF
  systemctl enable fail2ban > /dev/null 2>&1 || true
  if systemctl restart fail2ban > /dev/null 2>&1 && sleep 1 && systemctl is-active --quiet fail2ban; then
    ok "fail2ban activo (protección contra ataques de contraseña por SSH)"
  else
    aviso "fail2ban no pudo iniciar; el sitio funciona igual. Revisa: journalctl -u fail2ban"
  fi
}

# Solo desactiva el ingreso por contraseña si se confirma que TÚ entraste con
# llave SSH en esta misma sesión, para no dejarte fuera del servidor.
asegurar_ssh() {
  local usuario casa ip puerto
  usuario=${SUDO_USER:-root}
  casa=$(getent passwd "$usuario" | cut -d: -f6)
  if [ ! -s "$casa/.ssh/authorized_keys" ]; then
    aviso "SSH: $usuario no tiene llaves autorizadas; dejo el acceso por contraseña como está."
    return
  fi
  if ! grep -qsE '^[[:space:]]*Include[[:space:]]+/etc/ssh/sshd_config\.d/' /etc/ssh/sshd_config; then
    aviso "SSH: la configuración no incluye sshd_config.d; no la modifico."
    return
  fi
  read -r ip puerto _ <<< "${SSH_CONNECTION:-}"
  local patron="Accepted publickey for $usuario from ${ip:-x} port ${puerto:-x} "
  [ -n "${ip:-}" ] || patron="Accepted publickey for $usuario from "
  if ! grep -qsF "$patron" <(journalctl --since "-1 day" --no-pager -q 2>/dev/null) /var/log/auth.log; then
    aviso "SSH: no pude confirmar que entraste con llave; dejo el acceso por contraseña como está."
    return
  fi
  cat > /etc/ssh/sshd_config.d/00-mendiautos.conf <<'EOF'
# Generado por mendiautos.sh: solo se entra con llave SSH.
# Para deshacerlo (desde la consola web de tu proveedor):
#   rm /etc/ssh/sshd_config.d/00-mendiautos.conf && systemctl reload ssh
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
EOF
  if sshd -t 2> /dev/null; then
    systemctl reload ssh > /dev/null 2>&1 || systemctl reload sshd > /dev/null 2>&1 || true
    ok "SSH: solo con llave (contraseñas desactivadas)"
  else
    rm -f /etc/ssh/sshd_config.d/00-mendiautos.conf
    aviso "SSH: la configuración no validó; la dejé como estaba."
  fi
}

# ---------------------------------------------------------- repositorio
sincronizar_repo() {
  mkdir -p "$APP"
  if [ -d "$REPO_DIR/.git" ]; then
    git -C "$REPO_DIR" remote set-url origin "$REPO"
    git -C "$REPO_DIR" fetch -q --depth 1 origin "$RAMA"
    git -C "$REPO_DIR" checkout -q --force -B "$RAMA" FETCH_HEAD
  else
    rm -rf "$REPO_DIR"
    git clone -q --depth 1 --branch "$RAMA" "$REPO" "$REPO_DIR"
  fi
  git -C "$REPO_DIR" clean -q -ffdx
}

sha_remoto() {
  git ls-remote "$REPO" "refs/heads/$RAMA" 2>/dev/null | awk 'NR == 1 {print $1}' || true
}

# --------------------------------------------- librerías sin depender de CDN
# support.js carga React desde unpkg.com. Se descarga la misma versión, se
# comprueba contra la huella SRI que trae el propio support.js y se sirve
# desde el servidor. Si algo falla, el sitio sigue usando unpkg.com.
descargar_libreria() {
  local url=$1 ruta=$2 destino=$3 spec pkg ver interno
  mkdir -p "$(dirname "$destino")"
  curl -fsSL --max-time 60 -o "$destino" "$url" 2>/dev/null && return 0
  curl -fsSL --max-time 60 -o "$destino" "https://cdn.jsdelivr.net/npm/$ruta" 2>/dev/null && return 0
  # Último recurso: el paquete original del registro de npm.
  spec=${ruta%%/*}
  [[ $ruta == @* ]] && spec=$(cut -d/ -f1-2 <<< "$ruta")
  pkg=${spec%@*} ver=${spec##*@} interno=${ruta#"$spec"/}
  curl -fsSL --max-time 120 "https://registry.npmjs.org/$pkg/-/${pkg##*/}-$ver.tgz" 2>/dev/null |
    tar -xzO "package/$interno" > "$destino" 2>/dev/null && [ -s "$destino" ]
}

autoalojar_librerias() {
  local dst=$1 js=$1/support.js nombre url sri ruta cache patron n=0
  [ -f "$js" ] || return 0
  while read -r nombre url; do
    sri=$(sed -n "s/^[[:space:]]*var ${nombre}_SRI = \"\([^\"]*\)\";.*/\1/p" "$js" | awk 'NR == 1')
    [ -n "$sri" ] || continue
    ruta=${url#https://unpkg.com/}
    cache=$CACHE/vendor/$ruta
    if [ ! -s "$cache" ] || [ "$(sha384 "$cache")" != "$sri" ]; then
      if ! descargar_libreria "$url" "$ruta" "$cache.tmp" || [ "$(sha384 "$cache.tmp")" != "$sri" ]; then
        rm -f "$cache.tmp"
        aviso "No pude descargar/verificar $ruta; se seguirá cargando desde unpkg.com."
        continue
      fi
      mv -f "$cache.tmp" "$cache"
    fi
    mkdir -p "$(dirname "$dst/vendor/$ruta")"
    cp -f "$cache" "$dst/vendor/$ruta"
    patron=$(printf '%s' "$url" | sed 's/[.[\*^$]/\\&/g')
    sed -i "s|\"$patron\"|\"/vendor/$ruta\"|" "$js"
    n=$((n + 1))
  done < <(sed -n 's/^[[:space:]]*var \([A-Z_]*\)_URL = "\(https:\/\/unpkg\.com\/[^"]*\)";.*/\1 \2/p' "$js")
  [ "$n" -gt 0 ] && ok "Librerías servidas desde el propio servidor ($n)"
  return 0
}

# ------------------------------------------------------------ publicación
construir_version() {
  local sha id dst
  sha=$(git -C "$REPO_DIR" rev-parse HEAD)
  id="$(date -u +%Y%m%d-%H%M%S)-${sha:0:7}"
  dst=$RELEASES/$id
  mkdir -p "$dst"
  git -C "$REPO_DIR" archive --format=tar HEAD | tar -x -C "$dst"
  # Solo lo público: fuera scripts de despliegue, borradores y archivos ocultos.
  rm -rf "$dst/deploy" "$dst/scraps" "$dst/hermes"
  find "$dst" -mindepth 1 -maxdepth 1 \( -name '.*' -o -name '*.md' \) -exec rm -rf {} +
  # La portada del sitio es MendiautosHome.dc.html (index.html es su copia).
  [ -f "$dst/MendiautosHome.dc.html" ] && cp -f "$dst/MendiautosHome.dc.html" "$dst/index.html"
  [ -f "$dst/index.html" ] || { rm -rf "$dst"; error "La versión $id no tiene página de inicio (index.html)."; }
  autoalojar_librerias "$dst"
  printf '%s\n' "$sha" > "$dst/.version"
  chmod -R u=rwX,go=rX "$dst"
  VERSION_NUEVA=$dst
}

activar_version() {
  local dst=$1
  ln -sfn "$dst" "$WEB/.current-tmp"
  mv -Tf "$WEB/.current-tmp" "$CURRENT"
  mkdir -p "$STATE"
  cat "$dst/.version" > "$STATE/publicado"
  limpiar_versiones
}

limpiar_versiones() {
  local activa v i=0
  activa=$(readlink -f "$CURRENT" || true)
  while read -r v; do
    i=$((i + 1))
    [ "$i" -le "$MANTENER" ] && continue
    [ "$(readlink -f "$v")" = "$activa" ] && continue
    rm -rf "$v"
  done < <(find "$RELEASES" -mindepth 1 -maxdepth 1 -type d | sort -r)
}

publicar() {
  mkdir -p "$RELEASES" "$STATE"
  preparar_catalogo
  preparar_solicitudes
  construir_version
  configurar_nginx
  activar_version "$VERSION_NUEVA"
  rm -f "$STATE/omitir"
  actualizar_asistente
  ok "Publicada la versión $(basename "$VERSION_NUEVA")"
}

# Si los asistentes (equipo y clientes) están instalados, reciben las skills,
# reglas y herramientas de esta versión del repositorio.
actualizar_asistente() {
  if id -u hermes > /dev/null 2>&1 && [ -f "$REPO_DIR/hermes/instalar.sh" ]; then
    bash "$REPO_DIR/hermes/instalar.sh" --solo-archivos > /dev/null 2>&1 ||
      aviso "No pude actualizar los archivos del asistente (prueba: mendiautos hermes --solo-archivos)."
  fi
  if id -u hermes-clientes > /dev/null 2>&1 && [ -f "$REPO_DIR/hermes/clientes/instalar.sh" ]; then
    bash "$REPO_DIR/hermes/clientes/instalar.sh" --solo-archivos > /dev/null 2>&1 ||
      aviso "No pude actualizar el asistente de clientes (prueba: mendiautos hermes --clientes --solo-archivos)."
  fi
  return 0
}

# --------------------------------------------------------------- catálogo
# Los autos viven fuera de las versiones publicadas, en $CATALOGO: ni una
# versión nueva desde GitHub ni una exportación de la herramienta de diseño
# pisan lo que se cargó por Telegram. Solo el usuario del sistema «catalogo»
# escribe ahí; los demás (el asistente incluido) pasan por el comando
# catalogo, que valida cada dato antes de publicarlo.
asegurar_paquetes_catalogo() {
  local falta=() p
  for p in python3 python3-pil sudo git; do
    dpkg -s "$p" > /dev/null 2>&1 || falta+=("$p")
  done
  [ ${#falta[@]} -eq 0 ] && return 0
  info "Instalando ${falta[*]}…"
  apt_instalar "${falta[@]}" 2> /dev/null || {
    DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=600 -q update > /dev/null
    apt_instalar "${falta[@]}"
  }
}

preparar_catalogo() {
  asegurar_paquetes_catalogo
  getent group catalogo > /dev/null || groupadd --system catalogo
  id -u catalogo > /dev/null 2>&1 ||
    useradd --system --gid catalogo --home-dir "$CATALOGO" --no-create-home \
      --shell /usr/sbin/nologin --comment "Catalogo de Mendiautos" catalogo
  getent group editores-catalogo > /dev/null || groupadd --system editores-catalogo
  install -d -m 0755 "$STATE"
  install -d -m 0755 -o catalogo -g catalogo "$CATALOGO"
  install -d -m 0750 -o catalogo -g catalogo "$RESPALDOS"
  # El comando usa el Python del sistema en modo aislado (-I: ignora PYTHON*).
  sed '1s|^#!.*|#!/usr/bin/python3 -I|' "$REPO_DIR/deploy/catalogo.py" > "$BIN_CATALOGO.tmp"
  chmod 0755 "$BIN_CATALOGO.tmp"
  mv -f "$BIN_CATALOGO.tmp" "$BIN_CATALOGO"
  # Los del grupo editores-catalogo (el usuario del asistente) pueden correr
  # ese comando como «catalogo», y nada más.
  cat > "$SUDOERS_CATALOGO.tmp" <<EOF
# Generado por mendiautos.sh: los editores del catálogo solo pueden usar el
# comando catalogo, que corre como el usuario catalogo.
%editores-catalogo ALL=(catalogo) NOPASSWD: $BIN_CATALOGO
EOF
  chmod 0440 "$SUDOERS_CATALOGO.tmp"
  if visudo -cqf "$SUDOERS_CATALOGO.tmp" > /dev/null 2>&1; then
    mv -f "$SUDOERS_CATALOGO.tmp" "$SUDOERS_CATALOGO"
  else
    rm -f "$SUDOERS_CATALOGO.tmp"
    aviso "No pude validar la regla de sudo del catálogo; el asistente no podrá editarlo."
  fi
  if [ ! -f "$CATALOGO/inventario.json" ]; then
    "$BIN_CATALOGO" iniciar --desde "$REPO_DIR/assets/inventario.js" > /dev/null
    ok "Catálogo creado en $CATALOGO con los autos del repositorio"
  fi
  configurar_mantenimiento_catalogo
  [ -n "$SITIO" ] || recordar_sitio
}

configurar_mantenimiento_catalogo() {
  cat > /etc/systemd/system/mendiautos-catalogo.service <<EOF
[Unit]
Description=Mendiautos: revisar, limpiar y respaldar el catálogo de autos

[Service]
Type=oneshot
ExecStart=$BIN_CATALOGO mantenimiento
EOF
  cat > /etc/systemd/system/mendiautos-catalogo.timer <<'EOF'
[Unit]
Description=Mendiautos: mantenimiento diario del catálogo (3:40 a. m. en Colombia)

[Timer]
OnCalendar=*-*-* 08:40:00 UTC
RandomizedDelaySec=10min
Persistent=true

[Install]
WantedBy=timers.target
EOF
  systemctl daemon-reload
  systemctl enable --now mendiautos-catalogo.timer > /dev/null 2>&1 || true
}

# ------------------------------------------------------------ solicitudes
# Los formularios del sitio (contacto, vende tu auto, crédito…) llegan por
# /api/solicitud al receptor (deploy/solicitudes.py), que corre como el usuario
# del sistema «solicitudes»: solo él lee los datos de los clientes. El asistente
# del equipo los consulta con el comando solicitudes, que oculta lo sensible.
preparar_solicitudes() {
  local nuevo=0
  getent group solicitudes > /dev/null || groupadd --system solicitudes
  id -u solicitudes > /dev/null 2>&1 ||
    useradd --system --gid solicitudes --home-dir "$SOLICITUDES" --no-create-home \
      --shell /usr/sbin/nologin --comment "Solicitudes de clientes de Mendiautos" solicitudes
  getent group editores-solicitudes > /dev/null || groupadd --system editores-solicitudes
  install -d -m 0750 -o solicitudes -g solicitudes "$SOLICITUDES"
  # Clave para que el asistente de clientes (WhatsApp) registre interesados.
  install -d -m 0755 /etc/mendiautos
  [ -s "$TOKEN_SOLICITUDES" ] || (umask 077 && openssl rand -hex 32 > "$TOKEN_SOLICITUDES")
  chown root:solicitudes "$TOKEN_SOLICITUDES"
  chmod 0640 "$TOKEN_SOLICITUDES"
  sed '1s|^#!.*|#!/usr/bin/python3 -I|' "$REPO_DIR/deploy/solicitudes.py" > "$BIN_SOLICITUDES.tmp"
  chmod 0755 "$BIN_SOLICITUDES.tmp"
  if cmp -s "$BIN_SOLICITUDES.tmp" "$BIN_SOLICITUDES"; then
    rm -f "$BIN_SOLICITUDES.tmp"
  else
    mv -f "$BIN_SOLICITUDES.tmp" "$BIN_SOLICITUDES"
    nuevo=1
  fi
  cat > "$SUDOERS_SOLICITUDES.tmp" <<EOF
# Generado por mendiautos.sh: el equipo (el usuario del asistente) consulta y
# atiende las solicitudes solo con el comando solicitudes.
%editores-solicitudes ALL=(solicitudes) NOPASSWD: $BIN_SOLICITUDES
EOF
  chmod 0440 "$SUDOERS_SOLICITUDES.tmp"
  if visudo -cqf "$SUDOERS_SOLICITUDES.tmp" > /dev/null 2>&1; then
    mv -f "$SUDOERS_SOLICITUDES.tmp" "$SUDOERS_SOLICITUDES"
  else
    rm -f "$SUDOERS_SOLICITUDES.tmp"
    aviso "No pude validar la regla de sudo de las solicitudes; el asistente no podrá consultarlas."
  fi
  configurar_receptor "$nuevo"
}

configurar_receptor() {
  local unidad=/etc/systemd/system/mendiautos-solicitudes.service antes="" i
  [[ $RETENER_DOCUMENTOS =~ ^[0-9]+$ ]] || RETENER_DOCUMENTOS=90
  [[ $RETENER_SOLICITUDES =~ ^[0-9]+$ ]] || RETENER_SOLICITUDES=730
  [ -f "$unidad" ] && antes=$(cat "$unidad")
  cat > "$unidad" <<EOF
# Generado por mendiautos.sh.
[Unit]
Description=Mendiautos: receptor de los formularios del sitio
After=network.target

[Service]
Type=simple
User=solicitudes
Group=solicitudes
UMask=0027
ExecStart=$BIN_SOLICITUDES servir --host 127.0.0.1 --puerto $PUERTO_SOLICITUDES
Restart=always
RestartSec=5
# Solo puede escribir en su carpeta de datos.
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=$SOLICITUDES
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectKernelLogs=yes
ProtectControlGroups=yes
ProtectClock=yes
ProtectHostname=yes
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
RestrictNamespaces=yes
RestrictRealtime=yes
RestrictSUIDSGID=yes
LockPersonality=yes
MemoryDenyWriteExecute=yes
SystemCallArchitectures=native
CapabilityBoundingSet=
MemoryMax=512M
TasksMax=64

[Install]
WantedBy=multi-user.target
EOF
  cat > /etc/systemd/system/mendiautos-solicitudes-limpiar.service <<EOF
[Unit]
Description=Mendiautos: borrar documentos y solicitudes viejas (retención)

[Service]
Type=oneshot
ExecStart=$BIN_SOLICITUDES limpiar --dias-documentos $RETENER_DOCUMENTOS --dias-solicitudes $RETENER_SOLICITUDES
EOF
  cat > /etc/systemd/system/mendiautos-solicitudes-limpiar.timer <<'EOF'
[Unit]
Description=Mendiautos: retención diaria de solicitudes (3:50 a. m. en Colombia)

[Timer]
OnCalendar=*-*-* 08:50:00 UTC
RandomizedDelaySec=10min
Persistent=true

[Install]
WantedBy=timers.target
EOF
  systemctl daemon-reload
  systemctl enable mendiautos-solicitudes > /dev/null 2>&1 || true
  systemctl enable --now mendiautos-solicitudes-limpiar.timer > /dev/null 2>&1 || true
  # Si el receptor no arranca, el sitio se publica igual (los formularios
  # ofrecen WhatsApp) y el aviso de abajo lo cuenta.
  if [ "$1" = 1 ] || [ "$antes" != "$(cat "$unidad")" ] || ! systemctl is-active --quiet mendiautos-solicitudes; then
    systemctl restart mendiautos-solicitudes || true
  fi
  for i in 1 2 3 4 5 6 7 8 9 10; do
    curl -fsS --max-time 2 "http://127.0.0.1:$PUERTO_SOLICITUDES/api/salud" > /dev/null 2>&1 && return 0
    sleep 0.5
  done
  aviso "El receptor de formularios no responde; el sitio ofrecerá WhatsApp en su lugar. Revisa: journalctl -u mendiautos-solicitudes -n 30"
}

# Dirección pública del sitio; el comando catalogo la usa para los enlaces.
url_sitio() {
  if [ -n "$DOMINIO" ] && [ -s "/etc/letsencrypt/live/$DOMINIO/fullchain.pem" ]; then
    echo "https://$DOMINIO"
  else
    echo "http://${DOMINIO:-$(ip_publica)}"
  fi
}

recordar_sitio() {
  SITIO=$(url_sitio)
  guardar_conf
}

# ------------------------------------------------------------------ nginx
escribir_snippets() {
  mkdir -p /etc/nginx/snippets "$ACME"
  cat > "$SNIP_CABECERAS" <<'EOF'
# Generado por mendiautos.sh — cabeceras de seguridad del sitio.
add_header X-Content-Type-Options "nosniff" always;
add_header X-Frame-Options "SAMEORIGIN" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header Permissions-Policy "camera=(), microphone=(), geolocation=(), payment=(), usb=()" always;
add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-eval' https://unpkg.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com data:; img-src 'self' data: blob: https:; media-src 'self' blob:; frame-src https://maps.google.com https://www.google.com; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'self'" always;
EOF
  cat > "$SNIP_SITIO" <<EOF
# Generado por mendiautos.sh — contenido del sitio (se reescribe al publicar).
root $CURRENT;
index index.html;
charset utf-8;
server_tokens off;
client_max_body_size 1m;

gzip on;
gzip_vary on;
gzip_proxied any;
gzip_comp_level 5;
gzip_min_length 1024;
gzip_types text/css application/javascript text/javascript application/json image/svg+xml text/plain text/xml application/xml;

include $SNIP_CABECERAS;

location ^~ /.well-known/acme-challenge/ {
    root $ACME;
    default_type text/plain;
}

# Archivos y carpetas ocultos (.git, .env, .version…)
location ~ /\\. {
    return 404;
}

# Catálogo de autos: lo edita el comando catalogo, fuera de las versiones.
# Si todavía no existe, se sirve el inventario que trae el repositorio.
location = /assets/inventario.js {
    root $CATALOGO;
    expires -1;
    try_files /inventario.js @inventario_del_repositorio;
}
location @inventario_del_repositorio {
    expires -1;
    try_files \$uri =404;
}
# Fotos de los autos: solo los JPG que genera el comando (nombre = huella).
location ^~ /catalogo/fotos/ {
    root $STATE;
    if (\$uri !~ "^/catalogo/fotos/[a-z0-9-]+/[0-9a-f]{16}(-m)?\\.jpg\$") {
        return 404;
    }
    expires 30d;
    try_files \$uri =404;
}

# Formularios del sitio → receptor de solicitudes (deploy/solicitudes.py).
# nginx recibe el envío completo antes de pasarlo (protege al receptor).
location = /api/solicitud {
    limit_req zone=mendiautos_formularios burst=5 nodelay;
    limit_req_status 429;
    client_max_body_size 46m;
    client_body_timeout 120s;
    proxy_pass http://127.0.0.1:$PUERTO_SOLICITUDES;
    proxy_http_version 1.1;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header Connection "";
    proxy_read_timeout 120s;
}
location = /api/salud {
    proxy_pass http://127.0.0.1:$PUERTO_SOLICITUDES;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
}

# Librerías con la versión en la ruta: no cambian nunca.
location ^~ /vendor/ {
    include $SNIP_CABECERAS;
    add_header Cache-Control "public, max-age=31536000, immutable" always;
    try_files \$uri =404;
}

# Imágenes, video y fuentes: una semana en caché.
location ~* \\.(?:png|jpe?g|gif|webp|avif|svg|ico|mp4|webm|woff2?)\$ {
    expires 7d;
    try_files \$uri =404;
}

# Páginas, scripts y estilos: el navegador verifica si hay cambios cada vez.
location ~* \\.(?:html|js|css|json|txt|xml)\$ {
    expires -1;
    try_files \$uri =404;
}

location / {
    try_files \$uri \$uri/ =404;
}
EOF
}

# Líneas «listen» para IPv4 y, si el servidor tiene IPv6, también para IPv6.
escuchar() {
  printf '    listen %s;\n' "$1"
  [ -e /proc/net/if_inet6 ] && printf '    listen [::]:%s;\n' "$1"
  return 0
}

# Límite de envíos de formularios por IP (el receptor aplica otro por hora).
zona_formularios() {
  echo "limit_req_zone \$binary_remote_addr zone=mendiautos_formularios:1m rate=10r/m;"
}

# WhatsApp oficial de clientes (Cloud API): Meta avisa de cada mensaje a esta
# dirección, que solo existe con HTTPS y si el asistente de clientes está activo.
bloque_webhook() {
  [[ ${WEBHOOK_WHATSAPP:-} =~ ^[0-9]{2,5}$ ]] || return 0
  cat <<EOF

    location = /whatsapp/webhook {
        proxy_pass http://127.0.0.1:$WEBHOOK_WHATSAPP;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-Proto https;
        client_max_body_size 3m;
    }
EOF
}

escribir_sitio() {
  local http2_listen="" http2_dir="" default="default_server" www="" otros
  otros=$(grep -rlE 'listen[^;]*default_server' /etc/nginx/sites-enabled/ /etc/nginx/conf.d/ 2>/dev/null |
    grep -v "$SITE_LINK" || true)
  if [ -n "$otros" ]; then
    default=""
    aviso "Otro sitio de nginx es el predeterminado ($otros); este responderá solo a su dominio."
  fi
  if version_nginx_ge_1_25_1; then http2_dir="    http2 on;"; else http2_listen=" http2"; fi

  if [ -n "$DOMINIO" ] && [ -s "/etc/letsencrypt/live/$DOMINIO/fullchain.pem" ]; then
    grep -q "DNS:www.$DOMINIO" <(openssl x509 -noout -ext subjectAltName -in "/etc/letsencrypt/live/$DOMINIO/fullchain.pem" 2>/dev/null) && www="www.$DOMINIO"
    cat > "$SITE" <<EOF
# Generado por mendiautos.sh — no editar a mano (se reescribe al publicar).
$(zona_formularios)

# HTTP: solo validación de certificados y redirección a HTTPS.
server {
$(escuchar "80 $default")
    server_name $DOMINIO ${www:-} _;
    server_tokens off;
    location ^~ /.well-known/acme-challenge/ {
        root $ACME;
        default_type text/plain;
    }
    location / {
        return 301 https://$DOMINIO\$request_uri;
    }
}

server {
$(escuchar "443 ssl$http2_listen $default")
$http2_dir
    server_name $DOMINIO;

    ssl_certificate     /etc/letsencrypt/live/$DOMINIO/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$DOMINIO/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:mendiautos:10m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;

    add_header Strict-Transport-Security "max-age=31536000" always;
    include $SNIP_SITIO;
$(bloque_webhook)
}
EOF
    if [ -n "$www" ]; then
      cat >> "$SITE" <<EOF

server {
$(escuchar "443 ssl$http2_listen")
$http2_dir
    server_name $www;
    ssl_certificate     /etc/letsencrypt/live/$DOMINIO/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$DOMINIO/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    server_tokens off;
    return 301 https://$DOMINIO\$request_uri;
}
EOF
    fi
  else
    cat > "$SITE" <<EOF
# Generado por mendiautos.sh — no editar a mano (se reescribe al publicar).
$(zona_formularios)

server {
$(escuchar "80 $default")
    server_name ${DOMINIO:+$DOMINIO www.$DOMINIO} _;
    include $SNIP_SITIO;
}
EOF
  fi
}

configurar_nginx() {
  local respaldo=""
  [ -f "$SITE" ] && { respaldo=$(mktemp); cp "$SITE" "$respaldo"; }
  escribir_snippets
  escribir_sitio
  ln -sfn "$SITE" "$SITE_LINK"
  # El sitio de bienvenida de nginx ya no hace falta.
  if [ "$(readlink -f /etc/nginx/sites-enabled/default 2>/dev/null)" = "/etc/nginx/sites-available/default" ]; then
    rm -f /etc/nginx/sites-enabled/default
  fi
  if ! nginx -t > /dev/null 2>&1; then
    nginx -t || true
    if [ -n "$respaldo" ]; then cp "$respaldo" "$SITE"; else rm -f "$SITE_LINK"; fi
    error "La configuración de nginx no es válida; dejé la anterior."
  fi
  [ -n "$respaldo" ] && rm -f "$respaldo"
  systemctl reload nginx > /dev/null 2>&1 || systemctl restart nginx
}

# ----------------------------------------------------- actualización sola
configurar_temporizador() {
  cat > /etc/systemd/system/mendiautos-actualizar.service <<EOF
[Unit]
Description=Mendiautos: publicar los cambios nuevos de GitHub
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
ExecStart=$BIN actualizar --silencioso
EOF
  cat > /etc/systemd/system/mendiautos-actualizar.timer <<'EOF'
[Unit]
Description=Mendiautos: revisar GitHub cada 5 minutos

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
RandomizedDelaySec=30s

[Install]
WantedBy=timers.target
EOF
  systemctl daemon-reload
  if [ "$AUTO" = 1 ]; then
    systemctl enable --now mendiautos-actualizar.timer > /dev/null 2>&1
    ok "Actualización automática: cada 5 minutos se publica lo nuevo de la rama «$RAMA»"
  else
    systemctl disable --now mendiautos-actualizar.timer > /dev/null 2>&1 || true
    ok "Actualización automática desactivada (usa: mendiautos actualizar)"
  fi
}

instalar_comando() {
  install -m 0755 "$REPO_DIR/deploy/mendiautos.sh" "$BIN"
}

# ------------------------------------------------------------------- HTTPS
obtener_certificado() {
  local ip a www="" dominios
  command -v certbot > /dev/null || { info "Instalando certbot…"; apt_instalar certbot; }
  ip=$(ip_publica)
  a=$(getent ahostsv4 "$DOMINIO" 2>/dev/null | awk 'NR == 1 {print $1}' || true)
  if [ -z "$a" ]; then
    aviso "El dominio $DOMINIO todavía no apunta a ningún servidor."
    aviso "Crea un registro DNS tipo A: $DOMINIO → $ip  (y otro para www). Luego: mendiautos dominio $DOMINIO"
    return 1
  fi
  [ -n "$ip" ] && [ "$a" != "$ip" ] &&
    aviso "El dominio apunta a $a, pero este servidor es $ip. Si usas Cloudflare, desactiva el proxy (nube gris) mientras se emite el certificado."
  [ "$(getent ahostsv4 "www.$DOMINIO" 2>/dev/null | awk 'NR == 1 {print $1}' || true)" = "$a" ] && www="www.$DOMINIO"
  dominios=(-d "$DOMINIO")
  [ -n "$www" ] && dominios+=(-d "$www")
  info "Pidiendo el certificado de Let's Encrypt para $DOMINIO ${www:+y $www}…"
  local cuenta=(--register-unsafely-without-email)
  [ -n "$CORREO" ] && cuenta=(--email "$CORREO")
  if certbot certonly --webroot -w "$ACME" "${dominios[@]}" --cert-name "$DOMINIO" \
      --non-interactive --agree-tos --keep-until-expiring --expand "${cuenta[@]}" \
      --deploy-hook "systemctl reload nginx"; then
    ok "Certificado listo (se renueva solo)"
    return 0
  fi
  aviso "No se pudo obtener el certificado. Revisa que el dominio apunte a este servidor y que el puerto 80 esté abierto en el panel de tu proveedor."
  return 1
}

# --------------------------------------------------------------- comandos
cmd_instalar() {
  local repo="" rama="" dominio="" correo="" auto=""
  while [ $# -gt 0 ]; do
    case $1 in
      --repo) repo=$2; shift 2 ;;
      --rama) rama=$2; shift 2 ;;
      --dominio) dominio=$2; shift 2 ;;
      --correo) correo=$2; shift 2 ;;
      --sin-auto) auto=0; shift ;;
      *) error "Opción desconocida: $1" ;;
    esac
  done
  requiere_root
  cargar_conf
  REPO=${repo:-$REPO} RAMA=${rama:-$RAMA} DOMINIO=${dominio:-$DOMINIO}
  CORREO=${correo:-$CORREO} AUTO=${auto:-$AUTO}
  info "Instalando Mendiautos (repositorio $REPO, rama «$RAMA»)"
  revisar_sistema
  revisar_puerto_80
  instalar_paquetes
  configurar_actualizaciones
  configurar_firewall
  configurar_fail2ban
  asegurar_ssh
  info "Descargando el sitio desde GitHub…"
  sincronizar_repo
  [ -f "$REPO_DIR/deploy/mendiautos.sh" ] || error "La rama «$RAMA» no tiene deploy/mendiautos.sh."
  instalar_comando
  guardar_conf
  publicar
  configurar_temporizador
  if [ -n "$DOMINIO" ]; then
    obtener_certificado && configurar_nginx || true
  fi
  recordar_sitio
  resumen
}

cmd_actualizar() {
  local forzar=0 silencioso=0 remoto publicado omitir
  while [ $# -gt 0 ]; do
    case $1 in
      --forzar) forzar=1; shift ;;
      --silencioso) silencioso=1; shift ;;
      *) error "Opción desconocida: $1" ;;
    esac
  done
  requiere_root
  cargar_conf
  exec 9> /run/mendiautos.lock
  flock -n 9 || { [ "$silencioso" = 1 ] || aviso "Ya hay una publicación en curso."; exit 0; }
  remoto=$(sha_remoto)
  [ -n "$remoto" ] || error "No pude consultar GitHub ($REPO, rama «$RAMA»)."
  publicado=$(cat "$STATE/publicado" 2>/dev/null || true)
  omitir=$(cat "$STATE/omitir" 2>/dev/null || true)
  if [ "$forzar" = 0 ]; then
    if [ "$remoto" = "$publicado" ]; then
      [ "$silencioso" = 1 ] || ok "Ya está publicada la última versión (${remoto:0:7})."
      exit 0
    fi
    if [ "$remoto" = "$omitir" ]; then
      [ "$silencioso" = 1 ] || aviso "La versión ${remoto:0:7} se revirtió antes; no la vuelvo a publicar. Usa --forzar si quieres."
      exit 0
    fi
  fi
  info "Publicando ${remoto:0:7} de la rama «$RAMA»…"
  sincronizar_repo
  if ! cmp -s "$REPO_DIR/deploy/mendiautos.sh" "$BIN" 2>/dev/null; then
    # El script cambió en GitHub: se instala y se continúa con la versión nueva.
    instalar_comando
    exec "$BIN" publicar
  fi
  publicar
}

cmd_publicar() {
  requiere_root
  cargar_conf
  [ -d "$REPO_DIR/.git" ] || error "Primero ejecuta: mendiautos instalar"
  publicar
  configurar_temporizador > /dev/null
}

cmd_revertir() {
  requiere_root
  cargar_conf
  local activa anterior="" v
  activa=$(readlink -f "$CURRENT" 2>/dev/null) || error "No hay ninguna versión publicada."
  while read -r v; do
    if [ "$v" = "$activa" ]; then read -r anterior || true; break; fi
  done < <(find "$RELEASES" -mindepth 1 -maxdepth 1 -type d | sort -r)
  [ -n "$anterior" ] || error "No hay una versión anterior guardada."
  cat "$activa/.version" > "$STATE/omitir"
  activar_version "$anterior"
  ok "Volviste a la versión $(basename "$anterior")."
  aviso "La versión retirada no se volverá a publicar sola; la próxima que subas a GitHub sí."
}

cmd_dominio() {
  requiere_root
  cargar_conf
  [ $# -ge 1 ] || error "Uso: mendiautos dominio ejemplo.com [correo@ejemplo.com]"
  local d=${1,,}
  d=${d#http://} d=${d#https://} d=${d%%/*} d=${d#www.}
  [[ $d =~ ^([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$ ]] || error "«$1» no parece un dominio válido."
  DOMINIO=$d
  CORREO=${2:-$CORREO}
  guardar_conf
  configurar_nginx
  if obtener_certificado; then
    configurar_nginx
    ok "Sitio disponible en https://$DOMINIO"
  else
    ok "Por ahora el sitio sigue disponible por HTTP; repite este comando cuando el DNS apunte aquí."
  fi
  recordar_sitio
}

cmd_estado() {
  cargar_conf
  local activa sha
  activa=$(readlink -f "$CURRENT" 2>/dev/null || true)
  sha=$(cat "$STATE/publicado" 2>/dev/null || true)
  echo "Repositorio:   $REPO (rama $RAMA)"
  echo "Publicado:     ${activa:+$(basename "$activa")}${sha:+  (commit ${sha:0:7})}"
  echo "Dominio:       ${DOMINIO:-(ninguno, se usa la IP)}"
  if [ -n "$DOMINIO" ] && [ -s "/etc/letsencrypt/live/$DOMINIO/fullchain.pem" ]; then
    echo "Dirección:     https://$DOMINIO"
    echo "Certificado:   vence $(openssl x509 -enddate -noout -in "/etc/letsencrypt/live/$DOMINIO/fullchain.pem" | cut -d= -f2)"
  else
    echo "Dirección:     http://${DOMINIO:-$(ip_publica)}"
  fi
  echo "nginx:         $(systemctl is-active nginx 2>/dev/null || true)"
  echo "Auto-update:   $(systemctl is-active mendiautos-actualizar.timer 2>/dev/null || true)"
  echo "Versiones:     $(find "$RELEASES" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l) guardadas en $RELEASES"
  if [ -x "$BIN_CATALOGO" ] && [ -f "$CATALOGO/inventario.json" ]; then
    echo "Catálogo:      $("$BIN_CATALOGO" validar 2>&1 | tail -n 1)"
    echo "Último cambio: $("$BIN_CATALOGO" historial -n 1 2>/dev/null | sed -n '2s/^ *//p')"
    echo "Respaldos:     $(find "$RESPALDOS" -name 'catalogo-*.tar.gz' 2>/dev/null | wc -l) en $RESPALDOS"
  else
    echo "Catálogo:      (todavía no existe; se crea al publicar)"
  fi
  if [ -x "$BIN_SOLICITUDES" ]; then
    echo "Formularios:   receptor $(systemctl is-active mendiautos-solicitudes 2>/dev/null || true) · $(
      "$BIN_SOLICITUDES" listar -n 1 2>/dev/null | head -n 1 | sed 's/ (.*//; s/:$//' || true)"
    echo "Retención:     documentos $RETENER_DOCUMENTOS días, solicitudes $RETENER_SOLICITUDES días"
  else
    echo "Formularios:   (el receptor se instala al publicar)"
  fi
  estado_asistentes
}

estado_asistentes() {
  if id -u hermes > /dev/null 2>&1; then
    echo "Asistente:     equipo $(systemctl is-active mendiautos-hermes 2>/dev/null || true) (servicio mendiautos-hermes)"
  else
    echo "Asistente:     no instalado (mendiautos hermes)"
  fi
  if id -u hermes-clientes > /dev/null 2>&1; then
    echo "Clientes:      WhatsApp oficial $(systemctl is-active mendiautos-clientes 2>/dev/null || true) (servicio mendiautos-clientes)"
  fi
  return 0
}

cmd_hermes() {
  requiere_root
  cargar_conf
  [ -f "$REPO_DIR/hermes/instalar.sh" ] || error "Falta hermes/instalar.sh; primero: mendiautos actualizar"
  [ -x "$BIN_CATALOGO" ] || error "Primero publica el sitio: mendiautos instalar"
  [ -x "$BIN_SOLICITUDES" ] || { cmd_publicar; cargar_conf; }
  INFORMADO=1
  exec bash "$REPO_DIR/hermes/instalar.sh" "$@"
}

# Rehace la configuración de nginx (la usa el instalador del asistente de
# clientes al activar o quitar el WhatsApp oficial).
cmd_nginx() {
  requiere_root
  cargar_conf
  configurar_nginx
  ok "nginx actualizado"
}

resumen() {
  echo
  ok "Listo. Tu sitio está publicado en: $SITIO"
  echo "    Ver estado:        mendiautos estado"
  echo "    Publicar ya:       mendiautos actualizar"
  echo "    Volver atrás:      mendiautos revertir"
  [ -n "$DOMINIO" ] || echo "    Activar HTTPS:     mendiautos dominio tudominio.com tu@correo.com"
  echo "    Ver el catálogo:   catalogo listar"
  echo "    Formularios:       solicitudes pendientes"
  echo "    Asistente:         mendiautos hermes   (lo maneja por Telegram)"
}

ayuda() {
  cat <<'EOF'
mendiautos — publica y mantiene el sitio Mendiautos en esta VPS.

Comandos:
  instalar [--rama R] [--repo URL] [--dominio D] [--correo C] [--sin-auto]
  actualizar [--forzar]       publica lo último de GitHub si hay cambios
  revertir                    vuelve a la versión anterior
  dominio D [correo]          configura el dominio y HTTPS (Let's Encrypt)
  estado                      muestra lo que está publicado
  hermes [opciones]           instala o reconfigura el asistente de Telegram
                              (mendiautos hermes --help)
  nginx                       rehace la configuración de nginx

El catálogo de autos se edita con el comando «catalogo» (catalogo --help).
Lo que llega por los formularios del sitio: «solicitudes» (solicitudes --help).
EOF
}

main() {
  [ -t 0 ] || exec < /dev/null
  local cmd=${1:-ayuda}
  [ $# -gt 0 ] && shift
  case $cmd in
    instalar|install|setup) cmd_instalar "$@" ;;
    actualizar|update) cmd_actualizar "$@" ;;
    publicar|deploy) cmd_publicar "$@" ;;
    revertir|rollback) cmd_revertir "$@" ;;
    dominio|https|domain) cmd_dominio "$@" ;;
    estado|status) cmd_estado "$@" ;;
    hermes|asistente) cmd_hermes "$@" ;;
    nginx) cmd_nginx "$@" ;;
    ayuda|help|-h|--help) ayuda ;;
    *) error "Comando desconocido: $cmd (usa: mendiautos ayuda)" ;;
  esac
}

main "$@"
