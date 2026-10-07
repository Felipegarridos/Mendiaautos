# Despliegue de Mendiautos en una VPS

Todo el despliegue lo hace un solo script, [`mendiautos.sh`](mendiautos.sh).
Se ejecuta **dentro de la VPS**. Tú solo lo lanzas desde tu PC con un comando
SSH, usando tu llave (`C:\Users\<tu usuario>\.ssh\id_ed25519`), que nunca
sale de tu computador.

## Requisitos

- VPS con **Ubuntu 22.04 / 24.04** o **Debian 12 / 13** (recomendado: Ubuntu 24.04).
- Poder entrar por SSH con tu llave: `ssh root@IP_DE_LA_VPS` debe funcionar.
- En el panel de tu proveedor, los puertos **80** y **443** abiertos (y el 22 para SSH).

## 1. Publicar el sitio (una sola vez)

Abre **PowerShell** en tu PC y ejecuta (cambia la IP si hace falta):

```powershell
ssh root@2.28.140.187 "curl -fsSL https://raw.githubusercontent.com/Felipegarridos/Mendiaautos/main/deploy/mendiautos.sh | bash -s -- instalar"
```

- La primera vez SSH pregunta si confías en el servidor: escribe `yes`.
- Si tu usuario no es `root` (por ejemplo `ubuntu`), usa
  `ssh ubuntu@2.28.140.187 "curl -fsSL … | sudo bash -s -- instalar"`.
- Si la VPS no tiene `curl`, cambia `curl -fsSL` por `wget -qO-`.

Al terminar verás `✓ Listo. Tu sitio está publicado en: http://2.28.140.187`.

## 2. Poner un dominio con HTTPS (recomendado)

1. En el panel donde compraste el dominio, crea dos registros DNS **tipo A**:
   `tudominio.com → 2.28.140.187` y `www.tudominio.com → 2.28.140.187`.
2. Espera unos minutos y ejecuta:

```powershell
ssh root@2.28.140.187 "mendiautos dominio tudominio.com tu@correo.com"
```

El certificado de Let's Encrypt se renueva solo. HTTP pasa a HTTPS y
`www` redirige al dominio principal. Sin HTTPS los navegadores marcan el
sitio como «No seguro», algo que ahuyenta a quien va a dejar sus datos.

## 3. Publicar cambios

- **Automático:** cada 5 minutos la VPS revisa la rama `main` de GitHub y
  publica lo nuevo. Basta con subir los cambios a GitHub.
- **Inmediato:** `ssh root@2.28.140.187 "mendiautos actualizar"`

## 4. Catálogo de autos y asistente de Telegram

Los autos que muestra el sitio no viven en las páginas sino en un catálogo
aparte, en la VPS (`/var/lib/mendiautos/catalogo`). La instalación lo crea con
los autos de `assets/inventario.js` y desde ahí se edita con el comando
`catalogo` (por SSH) o con el asistente de Telegram:

```powershell
ssh -t root@2.28.140.187 "mendiautos hermes"
ssh root@2.28.140.187 "mendiautos equipo agregar 943010561 Felipe administrador"
```

Todo sobre el asistente y el equipo está en [`hermes/README.md`](../hermes/README.md).
Los cambios del catálogo se ven al instante y **no** se pierden al publicar
versiones nuevas desde GitHub.

- Un auto nuevo es un **borrador**: `assets/inventario.js` (lo que descarga el
  sitio) solo trae los autos disponibles y vendidos, sin datos internos. Cada
  borrador tiene una vista previa en `DetalleAuto.dc.html?previa=<clave>`, que
  nginx sirve desde `/catalogo/previas/` solo con la clave exacta.
- La portada del inicio (textos y foto o video de fondo) y los videos de
  YouTube de «Otros servicios» están en `sitio.json` → `assets/sitio.js`. La
  foto o el video van a `/catalogo/medios/`; el video se convierte con ffmpeg
  (que se instala solo) a un MP4 liviano, sin audio ni ubicación.
- El video del recorrido de cada auto (reel de Instagram o video de TikTok) y
  los videos de YouTube se ven con marcos (iframes) de `www.instagram.com`,
  `www.tiktok.com` (su reproductor oficial, `player/v1`) y
  `www.youtube-nocookie.com`, permitidos en la `Content-Security-Policy`.
  YouTube solo se carga cuando la persona toca el video. El enlace corto de
  TikTok (`vt.tiktok.com/…`) lo convierte `catalogo` al guardarlo, consultando
  a TikTok adónde lleva. La política de tratamiento de datos debe
  mencionarlos.
- Las **visitas** se cuentan en el propio servidor: nginx guarda el registro
  del sitio en `/var/log/nginx/mendiautos.access.log` y cada noche (0:20 a. m.)
  `mendiautos-visitas` ([`visitas.py`](visitas.py)) guarda solo totales por
  día en `/var/lib/mendiautos/visitas` (sin IPs ni cookies). Los usan los
  informes del asistente.

## 5. Formularios del sitio (solicitudes)

Los 8 formularios (contacto, busca tu auto, compra inmediata, consignación
física y virtual, otros servicios, alerta de inventario y solicitud de
crédito) envían lo que escribe el cliente, con sus fotos y documentos, a un
receptor que corre en la VPS ([`solicitudes.py`](solicitudes.py)). Cada envío
queda como una solicitud numerada (`S-1024`) y el asistente avisa al canal de
ventas en menos de un minuto. No hay que configurar nada: se instala solo al
publicar.

- `assets/solicitudes.js` envía los formularios a `/api/solicitud`. Reduce las
  fotos pesadas antes de subirlas, valida los campos obligatorios y la
  autorización de datos, y si el envío falla ofrece mandar el mismo resumen
  por WhatsApp (nunca muestra «¡Gracias!» si no llegó).
- Las solicitudes quedan en `/var/lib/mendiautos/solicitudes`, que solo puede
  leer el usuario del sistema `solicitudes`. Las fotos se re-codifican (sin
  GPS). Los documentos (cédula, extractos, tarjeta de propiedad) van a una
  carpeta privada que solo abre el administrador.
- Por chat nunca se muestran los datos sensibles de un crédito (documento,
  ingresos, fecha de nacimiento…): salen como «(privado)».
- Antispam: un campo trampa, tiempo mínimo de llenado y límites por IP (en
  nginx y en el receptor).
- Retención: los documentos se borran a los 90 días y las solicitudes a los 730
  (2 años). Se cambia en `/etc/mendiautos.conf` (`RETENER_DOCUMENTOS`,
  `RETENER_SOLICITUDES`) y se aplica con `mendiautos actualizar --forzar`.

Por SSH, el administrador las consulta con el comando `solicitudes`:

```bash
solicitudes pendientes                   # nuevas y en curso
solicitudes ver S-1024 --completo        # todo, incluso lo privado
solicitudes documentos S-1024 --destino /root/docs-S-1024
solicitudes atender S-1024 --nota "Lo llamó Laura"
```

## Comandos útiles (dentro de la VPS o con `ssh root@IP "…"`)

| Comando | Qué hace |
|---|---|
| `mendiautos estado` | Versión publicada, dirección, certificado y actualización automática |
| `mendiautos actualizar` | Publica lo último de GitHub (`--forzar` para republicar) |
| `mendiautos revertir` | Vuelve a la versión anterior (se guardan las últimas 5) |
| `mendiautos dominio D [correo]` | Configura el dominio y HTTPS |
| `mendiautos instalar --rama R` | Vuelve a instalar o cambia de rama |
| `mendiautos hermes` | Instala o configura el asistente del equipo (Telegram) |
| `mendiautos equipo` | Quién usa el asistente y con qué rol (`agregar <ID> <nombre> <rol>`, `quitar <ID>`) |
| `mendiautos hermes --clientes` | Instala o configura el asistente de WhatsApp para clientes |
| `mendiautos nginx` | Rehace la configuración de nginx |
| `catalogo listar` / `catalogo --help` | Ver y editar los autos del sitio |
| `solicitudes pendientes` / `solicitudes --help` | Lo que llegó por los formularios |

## Qué configura el script

| Área | Configuración |
|---|---|
| Servidor web | nginx con compresión gzip, caché por tipo de archivo y soporte de video por rangos |
| Cabeceras | `Content-Security-Policy`, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy` y HSTS con HTTPS |
| Librerías | React se descarga una vez, se verifica con su huella SRI y se sirve desde la VPS; si falla, se sigue usando unpkg.com |
| Privacidad | Solo se publica el sitio: `deploy/`, `hermes/`, `docs/`, `scraps/`, los `*.md` de cualquier carpeta y los archivos ocultos quedan fuera (responden 404) |
| Firewall (ufw) | Solo SSH, 80 y 443. Si ya hay otros servicios escuchando, no lo activa y te avisa |
| fail2ban | Bloquea 1 hora las IP con 5 intentos fallidos de SSH en 10 minutos |
| SSH | Desactiva el ingreso por contraseña **solo** si confirma que entraste con llave en esa misma sesión |
| Sistema | Actualizaciones de seguridad automáticas (`unattended-upgrades`) |
| Versiones | Cada publicación va a una carpeta nueva y el cambio es instantáneo; `revertir` vuelve atrás |
| Catálogo | Fuera de las versiones, editable solo con `catalogo` (usuario del sistema propio); borradores que vencen a los 7 días sin cambios, historial para deshacer y respaldo diario (14 días) |
| Portada y vistas previas | `/assets/sitio.js`, `/catalogo/medios/` y `/catalogo/previas/` desde el catálogo, con nombres fijos que nginx valida |
| Visitas | Registro propio de nginx y conteo nocturno `mendiautos-visitas` (solo totales por día; se guardan 400 días) |
| Formularios | Receptor `mendiautos-solicitudes` (solo en 127.0.0.1:8781, servicio endurecido de systemd) detrás de nginx en `/api/solicitud`; límite de envíos por IP; retención diaria |
| WhatsApp de clientes | Solo con dominio y HTTPS, y si el asistente de clientes está activo: nginx publica `/whatsapp/webhook` hacia 127.0.0.1:8090 |

Dónde queda cada cosa:

- Sitio publicado: `/var/www/mendiautos/current`, un enlace a `releases/<fecha>-<commit>`.
- Configuración: `/etc/mendiautos.conf` y `/etc/nginx/sites-available/mendiautos`.
- Copia del repositorio: `/opt/mendiautos/repo`.
- Catálogo de autos y portada: `/var/lib/mendiautos/catalogo`; respaldos en `/var/backups/mendiautos`.
- Equipo del asistente: `/etc/mendiautos/equipo.json` (lo escribe `mendiautos equipo`).
- Visitas por día: `/var/lib/mendiautos/visitas`.
- Solicitudes de los formularios: `/var/lib/mendiautos/solicitudes`; clave interna
  del asistente de clientes en `/etc/mendiautos/`.
- Registros: `journalctl -u mendiautos-actualizar`, `journalctl -u mendiautos-catalogo`
  (mantenimiento diario del catálogo), `journalctl -u mendiautos-solicitudes`
  (formularios; sin datos personales) y `/var/log/nginx/`.

## Verificar después de publicar

- Celular y escritorio: abre el sitio y recorre el menú.
- Cabeceras de seguridad: <https://securityheaders.com> (esperado: A).
- HTTPS, cuando haya dominio: <https://www.ssllabs.com/ssltest/> (esperado: A o A+).
- Rendimiento: Lighthouse, en las herramientas de desarrollador de Chrome.
- Disponibilidad: un monitor gratuito como UptimeRobot que te avise si el sitio cae.

## Solución de problemas

- **«El puerto 80 lo está usando otro programa»**: suele ser Apache.
  Si no lo usas: `systemctl disable --now apache2` y vuelve a instalar.
- **El certificado no se emite**: revisa que el dominio apunte a la IP
  (`ping tudominio.com`) y que el puerto 80 esté abierto en el panel del
  proveedor. Si usas Cloudflare, deja la nube en gris mientras se emite.
- **Te quedaste sin acceso por contraseña**: entra con tu llave o desde la
  consola web del proveedor y borra `/etc/ssh/sshd_config.d/00-mendiautos.conf`,
  luego `systemctl reload ssh`.
- **Algo se ve mal tras una actualización**: `mendiautos revertir`.

## Notas sobre las páginas

- La versión móvil está en `assets/site.css`: son reglas `r-*` que solo
  actúan en pantallas de hasta 900 px, así que el escritorio no cambia.
  El botón «Volver» funciona gracias a `assets/site.js`. Si vuelves a
  exportar las páginas desde la herramienta de diseño, conserva en el
  `<head>` las líneas de `site.css` y `site.js` y las clases `r-*`, o se
  perderá la adaptación a celulares.
- `index.html` se genera en cada publicación a partir de
  `MendiautosHome.dc.html`: edita el diseño del inicio en ese archivo. Los
  textos y el fondo del bloque principal los cambia el asistente
  (`assets/sitio.js`); sin cambios, se ve el diseño original.
- Las páginas con autos (inicio, disponibles, vendidos, ficha y comparar) los
  dibujan desde `assets/inventario.js` con `assets/catalogo.js`. La ficha,
  además, carga `assets/previa.js` (vista previa de borradores) y
  `assets/videos.js` (el video del recorrido: Instagram, TikTok o YouTube).
  Si las vuelves a exportar desde la herramienta de diseño, conserva esas dos
  líneas del `<head>` y el código que llena las listas; si no, volverán los
  autos de ejemplo (detalles en `hermes/README.md`).
- Ajustes para celulares (07/10/2026):
  - Las filas que avanzan solas (categorías y destacados del inicio,
    «Recomendados para ti» de la ficha) usan `carrusel` de
    `assets/catalogo.js`: se deslizan con el dedo y se detienen mientras las
    tocan.
  - En el menú «Compra tu auto», «Autos disponibles» y «Carros vendidos»
    abren su página con un toque (`assets/site.js`).
  - `support.js`, el motor de las páginas, trae un ajuste marcado
    «Mendiautos»: un campo con valor en la plantilla lo toma como valor
    inicial. Sin él, los deslizadores de los simuladores (ficha, Créditos e
    Inversionista) vuelven solos a su valor. Si la herramienta de diseño
    entrega un `support.js` nuevo, hay que volver a aplicarlo.
  - El video del inicio del diseño es un MP4 normal (el anterior venía
    fragmentado y el iPhone no siempre lo reproducía), con una versión de
    720p para pantallas de hasta 900 px (`assets/hero-video-movil.mp4`) y
    una imagen fija (`assets/hero-poster.jpg`) que queda si el video no carga.
- Los formularios envían los datos con `assets/solicitudes.js` (ver la
  sección 5). Si vuelves a exportar una página con formulario (Contacto,
  BuscaTuAuto, CompraInmediata, ConsignacionFisica, ConsignacionVirtual,
  OtrosServicios, AutosDisponibles o SolicitudCredito), conserva en el
  `<head>` la línea de `assets/solicitudes.js`: sin ella el formulario vuelve a
  mostrar «¡Gracias!» **sin enviar nada**.
- El menú cuenta las marcas del catálogo real (en `assets/site.js`, con
  `assets/inventario.js`), así que no hay que editar los números a mano.
- El inicio de sesión solo muestra un mensaje. Los paneles de demostración
  (PanelInventario, CargarAuto y PanelMedios) se retiraron: el catálogo se
  maneja con el asistente.
