# Asistentes de Mendiautos (Hermes)

Mendiautos tiene dos asistentes, hechos con
[Hermes Agent](https://hermes-agent.nousresearch.com) (Nous Research) e
instalados en la misma VPS del sitio. Cada uno tiene su propio bot o número y
viven separados: el de clientes no puede ver nada del equipo.

| | Asistente del equipo | Asistente de clientes |
|---|---|---|
| Quién le escribe | Las personas del equipo, cada una con su rol | Cualquier cliente |
| Por dónde | Telegram, en chat privado | El WhatsApp oficial de Mendiautos (Cloud API de Meta) |
| Qué hace | Sube y corrige autos, fotos y videos; vendidos; portada y destacados del inicio; informes; solicitudes de clientes | Responde sobre autos, ventas, créditos y servicios, y deja los interesados al equipo |
| Instalación | `mendiautos hermes` | `mendiautos hermes --clientes` |

Los dos usan **Gemini** (Google AI Studio) con la misma clave. Lo acordado con
el cliente está en [`docs/requerimientos-asistente.md`](../docs/requerimientos-asistente.md).

## Cómo funciona

```
Formularios del sitio ─▶ receptor (usuario «solicitudes») ─▶ /var/lib/mendiautos/solicitudes
                                  ▲                                   │
   Asistente de clientes ─────────┘ registrar_interes                 │ cada minuto, al gerente
   (WhatsApp oficial, sin terminal,                                   ▼ y al administrador
    solo 4 herramientas)                 Asistente del equipo ◀── avisos de ventas
                                         (Telegram, 3 herramientas propias)
                                           │  catalogo / solicitudes con --por <ID de quien escribe>
                                           ▼
                          catalogo ─▶ /var/lib/mendiautos/catalogo ─▶ el sitio (al instante)
```

- Las páginas dibujan los autos desde `assets/inventario.js` y la portada del
  inicio desde `assets/sitio.js`. En el servidor los genera el comando
  `catalogo` fuera de las versiones publicadas: ni una versión nueva desde
  GitHub ni una exportación nueva de las páginas pisan lo que se cargó por chat.
- Un auto nuevo es un **borrador**: no sale en el sitio (ni siquiera en
  `inventario.js`) hasta que alguien dice «Publicar». Mientras tanto se ve con
  un enlace de vista previa que solo tiene quien lo pidió.
- Los formularios del sitio llegan al receptor (ver `deploy/README.md`,
  sección 5). El asistente los consulta con el comando `solicitudes`, que
  oculta los datos sensibles.

### Permisos por persona

El equipo y sus roles están en `/etc/mendiautos/equipo.json` y se manejan con
`mendiautos equipo` (ver abajo).

| | Administrador y gerente | Vendedor |
|---|---|---|
| Subir autos, fotos y el reel de Instagram | Sí | Sí, y corrige solo los que él subió |
| Publicar | Sí | Sí, sin aprobación |
| Marcar vendido / volver a poner en venta | Sí | No |
| Portada del inicio y 5 destacados | Sí | No |
| Solicitudes de clientes e informes | Sí | No |
| Comandos «/» de Telegram (modelo, reinicio…) | Sí | Solo `/menu`, `/new` y `/stop` |

Esto lo hace cumplir el sistema, no solo una instrucción al asistente:

- El modelo **no tiene terminal, archivos, internet ni memoria**. Solo tiene
  tres herramientas de la extensión `plugin/mendiautos` (`catalogo`,
  `solicitudes` y `menu`) y los botones de Telegram (`clarify`).
- La extensión lee de Hermes el ID de Telegram de quien escribe (el modelo no
  lo puede cambiar), busca su rol y se lo pasa a los comandos con `--por`. Los
  comandos vuelven a revisar el permiso: por `sudo`, un cambio sin `--por` o
  de alguien que no está en el equipo se rechaza.
- Solo se publica un auto si la persona **escribió o tocó «Publicar»** (vale
  también por audio). Vender, borrar, quitar fotos y poner un video esperan a
  que la persona confirme («sí», «confirmo») en un mensaje posterior.
- Las fotos y videos solo pueden venir del caché de lo que llegó por el chat.

## Qué necesitas

1. El sitio instalado en la VPS (`mendiautos instalar`, ver `deploy/README.md`).
2. Una **clave de Gemini**: en https://aistudio.google.com/apikey, con la cuenta
   de Google de la empresa, «Create API key». Mejor en un proyecto con
   facturación activa: el plan gratuito tiene pocos mensajes por minuto y
   Google puede usar esos datos para mejorar sus productos.
3. Un **bot de Telegram**: en Telegram abre **@BotFather**, envía `/newbot`,
   ponle un nombre (por ejemplo «Mendiautos Equipo») y un usuario que termine
   en «bot». Te da un token (123456789:AAH…).
4. El **ID de Telegram** de cada persona: cada una le escribe a **@userinfobot**
   y copia su «Id» (un número).

La clave y el token se pegan en la VPS durante la instalación (no se muestran
en pantalla). No los envíes por chat ni por correo.

## Asistente del equipo

### Instalación (una vez)

Desde tu PC, en PowerShell:

```powershell
ssh -t root@2.28.140.187 "mendiautos hermes"
```

El `-t` permite responder las preguntas. El comando:

1. Crea el usuario `hermes` (sin contraseña ni acceso por SSH) y lo autoriza a
   usar **solo** los comandos `catalogo` y `solicitudes`.
2. Instala Hermes para ese usuario (tarda unos minutos).
3. Copia la extensión de Mendiautos, las reglas (`AGENTS.md`), la personalidad
   (`SOUL.md`) y las tareas automáticas.
4. Pregunta el equipo si está vacío (ID, nombre y rol de cada persona).
5. Pide la clave de Gemini y el token del bot, sin mostrarlos.
6. Prepara la transcripción de audios en el servidor (descarga el modelo de
   voz una vez, unos cientos de MB).
7. Programa las tareas automáticas y deja el asistente como servicio
   (`mendiautos-hermes`), que arranca con el servidor.

Al final, **cada persona del equipo le escribe «/start» al bot una vez**: un
bot de Telegram no puede escribirle primero a nadie, y sin eso no le llegan los
avisos ni los informes.

La clave y el token se pegan **solo cuando el instalador los pide** («Clave»,
«Token»). Al pegarlos no se ve nada en pantalla: es normal; se pega una vez y se
presiona Enter. Nunca los pegues en la línea de comandos (`root@…:~#`): quedan
en el historial del servidor. Si pasa, cámbialos (ver «Seguridad»).

Opciones útiles:

| Comando | Para qué |
|---|---|
| `mendiautos hermes --clave-gemini` | Cambiar la clave de Gemini |
| `mendiautos hermes --modelo gemini-3.5-flash` | Elegir otro modelo de Gemini |
| `mendiautos hermes --otro-proveedor` | Usar otro proveedor de IA (asistente de Hermes) |
| `mendiautos hermes --audios base` | Modelo de voz más liviano (por defecto `small`; `medium` entiende mejor, pero es más lento) |
| `mendiautos hermes --token` | Cambiar el token del bot (lo pide sin mostrarlo) |

### El equipo

```bash
mendiautos equipo                                   # quién está y con qué rol
mendiautos equipo agregar 943010561 Felipe administrador
mendiautos equipo agregar 123456789 Nelson gerente
mendiautos equipo agregar 987654321 Carlos vendedor
mendiautos equipo quitar 987654321
```

Cada cambio se aplica solo: quién puede escribirle al bot, quién puede usar
los comandos «/», a quién le llegan los avisos e informes y a quién los avisos
de sus borradores. El asistente se reinicia (tarda unos segundos).

### Uso diario

Al saludar («hola»), con /start o con /menu, el asistente muestra el **menú
con botones**, que queda fijo abajo del chat. También se le puede escribir o
dictar por audio lo que sea: «se vendió el Onix».

El botón **Menú** de Telegram (junto al campo de texto) está en español y solo
tiene tres opciones: `/menu` (ver el menú con botones), `/new` (empezar de
cero; los borradores no se pierden) y `/stop` (detener lo que está haciendo el
asistente). Los demás comandos de Hermes siguen funcionando si un
administrador los escribe. Los avisos propios de Hermes también salen en
español.

| Botón | Qué hace |
|---|---|
| 🚗 Subir auto | Flujo guiado: saca todos los datos de un mensaje o audio (aunque vengan en desorden), los guarda de una vez, confirma con ✓ y pide en un solo mensaje todo lo que falta («no aplica» donde corresponde), hasta completarlo; propone la descripción, pide de 5 a 20 fotos y el reel de Instagram, muestra un resumen con la vista previa y publica solo con «Publicar» |
| ✏️ Editar auto | Cambia cualquier dato: «cámbiale el precio a 95 millones» |
| 📸 Fotos y videos | Agrega fotos, cambia el orden («la 3 de primera», «orden 2,1,4,3»), quita fotos o pone el reel de Instagram |
| ✅ Marcar vendido | Muestra marca, modelo, año, precio, color y placa para confirmar; queda en «Autos vendidos» con la fecha |
| 🏠 Portada | Texto corto, título y foto o video (hasta 20 MB) del bloque principal del inicio |
| 📊 Informe | El informe de la semana o del mes |
| 📥 Solicitudes | Lo que llegó por los formularios: ver, tomar, atender, descartar |
| ⭐ Destacados | Los 5 autos del inicio; si hay 5, pregunta cuál sale |
| 📝 Mis borradores | (vendedor) Retomar un auto a medio subir |

Consejos:

- Envía las fotos como **foto**, no como archivo (las HEIC de iPhone enviadas
  como archivo no se pueden procesar). La primera es la portada del auto.
- Un borrador sin cambios en 7 días se borra solo; el día anterior le llega un
  aviso a quien lo subió.
- «Deshaz lo último» deshace el último cambio de quien lo pide (se puede
  repetir). Los cambios de precio quedan en el historial.
- Para quitar un auto que se vendió, márcalo vendido: queda en «Autos
  vendidos» y da confianza a los clientes.

### Avisos e informes automáticos

Son tareas sin IA (no gastan tokens): un script cuyo texto llega al chat.

| Tarea | Qué avisa | Cuándo | A quién |
|---|---|---|---|
| `avisos-ventas-<ID>` | Cada solicitud nueva de los formularios (o del WhatsApp de clientes), con el enlace para escribirle y sus fotos | Cada minuto | Gerente y administrador, cada uno por su chat |
| `resumen-ventas` | Lo que llegó en el día y lo que sigue pendiente | 7:30 a. m. | Gerente y administrador |
| `informe-semanal` | Autos que entraron y vendidos, total en inventario, solicitudes recibidas y atendidas, visitas y autos más vistos, días promedio en inventario, autos sin fotos o incompletos | Sábados 8:00 a. m. (la semana que terminó el viernes) | Gerente y administrador |
| `informe-mensual` | Lo mismo, del mes anterior | Día 1, 8:00 a. m. | Gerente y administrador |
| `borradores-<ID>` | Los borradores de esa persona que se borran al día siguiente | 9:00 a. m. | Cada persona |
| `vigilar-sitio` | Si el sitio, el catálogo o los formularios fallan, si el certificado HTTPS está por vencer o si el disco se llena | Cada 30 min | Administrador |

Las visitas se cuentan en el propio servidor (sin Google Analytics ni cookies):
cada noche se leen los registros de nginx y se guardan solo totales por día
(`mendiautos-visitas`, ver `deploy/README.md`).

### Audios

Los audios se transcriben en el servidor (faster-whisper, en español) antes de
llegar al modelo; el asistente responde siempre con texto. Si algo no se
entiende, repite lo que entendió y pide confirmar. El modelo de voz se
descarga una vez desde Hugging Face.

## Asistente de clientes (WhatsApp oficial)

Atiende a cualquier persona que escriba al WhatsApp oficial de Mendiautos:
busca autos del catálogo y comparte fichas, fotos y el reel del recorrido,
explica cómo vender el auto, los créditos y los servicios, y cuando el cliente
quiere avanzar le pide nombre, celular y autorización de datos y deja una
solicitud: el equipo la recibe como «WhatsApp (asistente de clientes)».

### Qué necesitas (pendiente)

1. **El dominio con HTTPS**: listo (`mendiautos.co`).
2. **Una cuenta de Meta Business** (business.facebook.com), idealmente
   verificada, y una app en developers.facebook.com con el producto WhatsApp.
3. **El número del WhatsApp oficial** registrado en esa app. Puede ser un
   número nuevo o el actual de ventas (Meta permite migrarlo; averigua si
   quieres seguir usando también la app de WhatsApp Business en ese número).
4. De la app de Meta: el **identificador del número de teléfono** (WhatsApp →
   Configuración de la API), la **clave secreta de la app** (Configuración →
   Básica) y un **token permanente** de un usuario del sistema (Business
   Manager → Usuarios del sistema → generar token con los permisos
   `whatsapp_business_messaging` y `whatsapp_business_management`).

### Instalación

```powershell
ssh -t root@2.28.140.187 "mendiautos hermes --clientes"
```

Crea el usuario `hermes-clientes` (sin ningún permiso especial), instala otro
Hermes para él con Gemini (usa la clave del asistente del equipo si ya está),
te pide las tres credenciales de Meta, genera el token de verificación del
webhook y publica `https://mendiautos.co/whatsapp/webhook` en nginx. Si falta
algo, lo instala todo pero lo deja apagado y te dice qué falta; vuelve a correr
el comando cuando lo tengas.

Al final muestra la **URL de devolución de llamada** y el **token de
verificación** que se pegan en Meta (WhatsApp → Configuración → Webhook →
«Verificar y guardar»); allí mismo suscribe el campo `messages`.

### Qué puede y qué no

- Solo tiene cuatro herramientas: buscar autos publicados, ver la ficha de un
  auto (con sus fotos y su reel), la información del negocio y registrar un
  interesado. No tiene terminal, archivos, internet ni memoria, no ve las
  solicitudes ni las conversaciones de otros clientes, no ve borradores y no
  puede cambiar el catálogo.
- No inventa precios ni promete descuentos, créditos ni citas: dice que un
  asesor lo confirma. No pide cédula, ingresos ni documentos por chat.
- Solo responde a quien le escribe, dentro de las 24 horas que permite Meta.
  Hoy no envía mensajes por su cuenta (plantillas); el seguimiento lo hace el
  equipo desde su WhatsApp.
- La información que da del negocio (dirección, horario, servicios, créditos)
  está en `clientes/empresa.json`: corrígela ahí y publica.
- Costos: el de Gemini por cada mensaje. Meta hoy no cobra las respuestas a
  quien escribió primero (dentro de las 24 horas); revisa su tabla de precios
  vigente.

## Seguridad

- El asistente del equipo solo responde a las personas del equipo (a
  desconocidos no les contesta). Corre como un usuario sin privilegios cuya
  única puerta al sitio son los comandos `catalogo` y `solicitudes`, que validan
  todo y revisan el rol de quien pide cada cambio.
- El asistente de clientes corre como otro usuario, sin permisos, en un
  servicio de systemd que no le deja ver al asistente del equipo ni las
  solicitudes; solo puede mandar fotos del catálogo.
- Lo que escribe un cliente (formularios o WhatsApp) se trata como datos, nunca
  como instrucciones. Los datos sensibles de un crédito no pasan por los chats:
  salen como «(privado)». Los documentos solo los descarga el administrador
  (`solicitudes documentos S-… --destino …`).
- Las fotos y el video de la portada se re-codifican: se les quita la ubicación
  GPS y los datos del celular (y el audio al video). De la placa solo se
  publica el último dígito.
- Cada cambio del catálogo y de la portada queda en el historial con quién lo
  pidió (`catalogo historial`) y se puede deshacer. Además hay un respaldo
  diario en `/var/backups/mendiautos` (se guardan 14). Cada solicitud guarda
  quién la atendió y cuándo.
- Si el token del bot de Telegram se filtra (por ejemplo, se pegó en un chat,
  en una captura o en la línea de comandos): en @BotFather, `/mybots` → el bot →
  «API Token» → «Revoke current token», y el nuevo se pone con
  `ssh -t root@IP "mendiautos hermes --token"`. Si se filtra la clave de
  Gemini, bórrala en AI Studio y `mendiautos hermes --clave-gemini`. Si se
  filtra el token de Meta, revócalo en Business Manager y
  `mendiautos hermes --clientes --token-meta`. Los tres se piden sin mostrarlos.
- Cuando alguien sale del equipo: `mendiautos equipo quitar <ID>`.

## Administración (en la VPS)

| Comando | Qué hace |
|---|---|
| `mendiautos estado` | Estado del sitio, del catálogo, de los formularios, del equipo y de los asistentes |
| `mendiautos equipo` | Quién usa el asistente y con qué rol |
| `mendiautos hermes` | Instala o completa el asistente del equipo |
| `mendiautos hermes --reiniciar` / `--actualizar` / `--detener` | Reinicia, actualiza Hermes o apaga el asistente del equipo |
| `mendiautos hermes --clientes` | Instala o completa el asistente de clientes |
| `mendiautos hermes --clientes --reiniciar` / `--actualizar` / `--detener` | Lo mismo para el de clientes (`--detener` también quita el webhook) |
| `journalctl -u mendiautos-hermes -f` | Mensajes del asistente del equipo en vivo |
| `journalctl -u mendiautos-clientes -f` | Mensajes del asistente de clientes en vivo |
| `catalogo --help` | El catálogo a mano, sin asistente |
| `solicitudes --help` | Las solicitudes a mano, sin asistente |

La extensión, las reglas y las tareas se actualizan solas cada vez que se
publica una versión nueva del sitio desde GitHub.

### El catálogo a mano

El mismo comando que usa el asistente sirve por SSH (como root no hace falta
`--por`):

```bash
catalogo listar                         # disponibles; también --borradores, --vendidos, --todos
catalogo agregar marca=Kia modelo=Picanto anio=2021      # queda como borrador
catalogo faltan picanto                 # lo que le falta para publicarse
catalogo editar picanto "precio=42 millones" km=35000 hp="no aplica"
catalogo foto agregar picanto /root/fotos/*.jpg
catalogo previa picanto                 # enlace de vista previa
catalogo publicar picanto
catalogo vender picanto --confirmar
catalogo reactivar picanto km=36000 precio=41000000
catalogo destacar picanto --en-lugar-de duster
catalogo portada textos texto=Kia "titulo=Picanto | 2021" auto=picanto
catalogo portada video /root/video.mp4  # o portada foto …; portada original
catalogo servicios video posventa https://youtu.be/…
catalogo informe --mes
catalogo deshacer
catalogo campos                         # todos los datos y los obligatorios
```

### Recuperar un respaldo del catálogo

```bash
systemctl stop mendiautos-hermes
cd /var/lib/mendiautos && mv catalogo catalogo.antes
tar -xzf /var/backups/mendiautos/catalogo-AAAAMMDD-HHMMSS.tar.gz
chown -R catalogo:catalogo catalogo
systemctl start mendiautos-hermes
```

## Si algo falla

- **El bot no responde**: `systemctl status mendiautos-hermes` y
  `journalctl -u mendiautos-hermes -n 50`. Revisa el token, que la persona esté
  en `mendiautos equipo` y que la clave de Gemini tenga saldo o cupo.
- **«no está registrado en el equipo»**: `mendiautos equipo agregar …`.
- **No llegan los avisos o los informes**: la persona debe haberle escrito
  «/start» al bot al menos una vez. `solicitudes pendientes` muestra si hay
  solicitudes; `mendiautos estado` dice si el receptor está activo.
- **No entiende los audios**: `journalctl -u mendiautos-hermes -n 50`. La
  primera vez descarga el modelo de voz; si el servidor tiene poca memoria,
  `mendiautos hermes --audios base`.
- **Una foto no se sube**: lo que llega por Telegram se borra del caché a las
  24 horas; reenvíalas.
- **El sitio muestra datos viejos**: recarga la página. `catalogo validar`
  revisa el catálogo y regenera lo que haga falta.
- **El asistente de clientes no contesta**: `journalctl -u mendiautos-clientes -n 50`.
  En Meta, revisa que el webhook esté verificado y suscrito a `messages`, y
  que el token permanente no haya sido revocado.

## Si vuelves a exportar las páginas

Las páginas que muestran autos tienen conectado el catálogo: en el `<head>`
cargan `assets/inventario.js` y `assets/catalogo.js` (y la ficha,
`assets/previa.js` y `assets/videos.js`; el inicio, `assets/sitio.js`). Sus
listas de autos, la portada y el reel se llenan al abrirse. Las que tienen
formularios cargan `assets/solicitudes.js`, y «Otros servicios»,
`assets/sitio.js` y `assets/videos.js`. Si vuelves a exportar alguna desde la
herramienta de diseño, esos enlaces se pierden: avísale a quien mantiene el
sitio antes de reemplazarlas.

## Pruebas

Corren solas en GitHub Actions con cada cambio (`.github/workflows/pruebas.yml`),
nunca en la VPS:

- `hermes/pruebas`: confirmaciones con botones («Publicar», «Sí»), texto
  limpio en el chat y estrés (20.000 textos al azar, 32 hilos a la vez, 200
  publicaciones simultáneas).
- `deploy/pruebas`: el comando `catalogo` sobre un catálogo temporal —flujo
  completo, vistas previas, textos maliciosos, límites, permisos del vendedor—
  y estrés: tres personas a la vez, 30 cambios simultáneos al mismo auto, el
  candado ocupado por un cambio largo y flujos completos en paralelo.

A mano: `python -m unittest discover -s hermes/pruebas -v` y, en Linux con
Pillow, `python -m unittest discover -s deploy/pruebas -v`.

## Archivos de esta carpeta

| Archivo | Para qué |
|---|---|
| `instalar.sh` | Lo que corre `mendiautos hermes` (asistente del equipo) |
| `plugin/mendiautos/` | La extensión de Hermes: herramientas `catalogo`, `solicitudes` y `menu`, con los permisos por persona; además limpia lo que llega al chat (saltos de línea, Markdown en los botones, razonamiento en inglés) |
| `pruebas/` | Pruebas de la extensión, incluidas las de estrés (ver «Pruebas») |
| `AGENTS.md` / `SOUL.md` | Procedimientos, reglas y personalidad del asistente del equipo |
| `scripts/` | Tareas automáticas sin IA (avisos, informes, borradores, vigilante) |
| `clientes/instalar.sh` | Lo que corre `mendiautos hermes --clientes` |
| `clientes/mcp_clientes.py` | Las cuatro herramientas del asistente de clientes |
| `clientes/empresa.json` | La información del negocio que da a los clientes |
| `clientes/AGENTS.md` / `clientes/SOUL.md` | Reglas y personalidad del asistente de clientes |

Los comandos `catalogo` y `solicitudes` están en `deploy/catalogo.py` y
`deploy/solicitudes.py`; `mendiautos.sh` los instala en `/usr/local/bin`.
