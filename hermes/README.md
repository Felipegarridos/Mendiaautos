# Asistentes de Mendiautos (Hermes)

Mendiautos tiene dos asistentes, hechos con
[Hermes Agent](https://hermes-agent.nousresearch.com) (Nous Research) e
instalados en la misma VPS del sitio. Cada uno tiene su propio bot o número y
viven separados: el de clientes no puede ver nada del equipo.

| | Asistente del equipo | Asistente de clientes |
|---|---|---|
| Quién le escribe | Solo las personas autorizadas del equipo | Cualquier cliente |
| Por dónde | Telegram (y, si lo activas, un WhatsApp del equipo) | El WhatsApp oficial de Mendiautos (Cloud API de Meta) |
| Qué hace | Mantiene el catálogo del sitio y avisa y ayuda a atender las solicitudes de los formularios | Responde sobre autos, ventas, créditos y servicios, y deja los interesados al equipo |
| Instalación | `mendiautos hermes` | `mendiautos hermes --clientes` |

## Cómo funciona

```
Formularios del sitio ─▶ receptor (usuario «solicitudes») ─▶ /var/lib/mendiautos/solicitudes
                                  ▲                                   │
   Asistente de clientes ─────────┘ registrar_interes                 │ cada minuto
   (WhatsApp oficial, sin terminal,                                   ▼
    solo 4 herramientas)                 Asistente del equipo ◀── avisos de ventas
                                         (Telegram / WhatsApp)
                                           │  solo los comandos «catalogo» y «solicitudes»
                                           ▼
                          catalogo ─▶ /var/lib/mendiautos/catalogo ─▶ el sitio (al instante)
```

- Las páginas dibujan los autos desde `assets/inventario.js`, que en el
  servidor genera el comando `catalogo` fuera de las versiones publicadas: ni
  una versión nueva desde GitHub ni una exportación nueva de las páginas pisan
  lo que se cargó por chat.
- Los formularios del sitio llegan al receptor (ver `deploy/README.md`,
  sección 5). El asistente del equipo los consulta con el comando
  `solicitudes`, que oculta los datos sensibles.

## Qué necesitas

1. El sitio instalado en la VPS (`mendiautos instalar`, ver `deploy/README.md`).
2. Una clave de API de un proveedor de IA: OpenRouter, Anthropic, OpenAI, Nous
   Portal u otro de los que soporta Hermes. Para el equipo conviene un modelo
   que vea imágenes (fotos de autos); para clientes, uno rápido y económico.
   Los dos asistentes pueden usar la misma clave.
3. Asistente del equipo: un bot de Telegram (en Telegram abre **@BotFather**,
   envía `/newbot` y guarda el token) y el ID numérico de cada persona (cada
   una le escribe a **@userinfobot** y te pasa su «Id»).
4. Opcional, WhatsApp del equipo: un número dedicado al asistente (una SIM
   aparte, no el WhatsApp de ventas ni uno personal).
5. Asistente de clientes: el dominio con HTTPS y las credenciales de Meta (ver
   más abajo).

Las claves y tokens los pegas tú en la VPS durante la instalación (no se
muestran en pantalla). No los envíes por chat ni por correo.

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
3. Copia las skills `catalogo-mendiautos` y `ventas-mendiautos`, las reglas
   (`AGENTS.md`) y la personalidad (`SOUL.md`) de esta carpeta.
4. Te pide el modelo de IA con el asistente propio de Hermes, luego el token
   del bot (sin mostrarlo en pantalla) y los IDs autorizados.
5. Programa las tareas automáticas (ver «Avisos automáticos»).
6. Deja el asistente como servicio (`mendiautos-hermes`), que arranca con el
   servidor.

Para volver a correrlo sin preguntas:
`mendiautos hermes --token <TOKEN> --usuarios 111111111,222222222`.
Ojo: así el token queda en el historial de la consola.

### Un canal de ventas y otro de catálogo

Al principio todos los avisos llegan al chat privado de la primera persona
autorizada. Lo recomendado es tener dos grupos de Telegram, con el bot y el
equipo en ambos:

1. Crea los grupos, por ejemplo «Mendiautos · Ventas» y «Mendiautos ·
   Catálogo», y agrega el bot a los dos.
2. Haz al bot **administrador** de cada grupo (o, antes de agregarlo,
   desactiva su modo privacidad en @BotFather: *Bot Settings → Group Privacy →
   Turn off*). Si no, el bot no lee los mensajes del grupo.
3. En el grupo de ventas escríbele: «@TuBot que los avisos de ventas lleguen
   aquí». En el del catálogo: «@TuBot que los avisos del catálogo lleguen
   aquí».

En los grupos el asistente solo responde cuando lo mencionan (`@TuBot …`) o le
contestan un mensaje; así el equipo puede conversar sin que intervenga. Por
chat privado responde siempre.

Si prefieres dar los grupos por su ID (números que empiezan por `-100`):
`mendiautos hermes --canal-ventas -1001234567890 --canal-catalogo -1009876543210`.

### Avisos automáticos

Son tareas sin IA (no gastan tokens): un script cuyo texto llega al chat.

| Tarea | Qué avisa | Cuándo | Canal |
|---|---|---|---|
| `avisos-ventas-telegram` | Cada solicitud nueva de los formularios (o del WhatsApp de clientes), con el enlace para escribirle al cliente y sus fotos | Cada minuto | Ventas |
| `avisos-ventas-whatsapp` | Lo mismo, al WhatsApp del equipo (si está activo) | Cada minuto | Ventas |
| `resumen-ventas` | Lo que llegó en el día y lo que sigue pendiente | 7:30 a. m. | Ventas |
| `vigilar-sitio` | Si el sitio, el catálogo o los formularios fallan, si el certificado HTTPS está por vencer o si el disco se llena | Cada 30 min | Catálogo |
| `resumen-catalogo` | Vendidos, nuevos, autos sin fotos o sin precio | Lunes 8:00 a. m. | Catálogo |

Cada solicitud se avisa una vez por canal. Si un aviso no llega (Telegram
caído), se repite en el siguiente minuto; y lo pendiente siempre sale en el
resumen de la mañana.

### Uso diario

Escríbele como a un compañero. Catálogo:

| Mensaje | Qué hace |
|---|---|
| «Llegó un Kia Picanto 2021, 35 mil km, mecánico, 42 millones» | Lo agrega; si faltan datos, pregunta |
| *(fotos)* «Estas son del Picanto» | Sube las fotos; la primera es la portada |
| «Prepara el BMW X3 pero no lo publiques aún» | Lo deja oculto hasta que digas «publícalo» |
| «Bájale 2 millones al Duster» | Calcula y actualiza el precio |
| «Se vendió la Frontier» | Pasa a «Autos vendidos» |
| «¿Qué autos no tienen fotos?» / «Deshaz lo último» | Resumen / revierte el último cambio |

Ventas:

| Mensaje | Qué hace |
|---|---|
| «¿Qué hay pendiente?» | Lista las solicitudes nuevas y en curso |
| «Muéstrame la 1024» / «las fotos del auto de la 1030» | La solicitud completa (sin datos privados) y sus fotos |
| «La 1024 la tomo yo» | La deja «en curso» con tu nombre |
| «Atendí la 1024, le mandé la oferta» | La marca atendida con esa nota |
| «Descarta la 1025, era spam» | La marca descartada |
| «¿Cuántas llegaron esta semana?» | Resumen de los últimos 7 días |

Consejos:

- Envía las fotos de los autos como **foto**, no como archivo. Las fotos HEIC
  de iPhone enviadas como archivo no se pueden procesar.
- Cada aviso de ventas trae un enlace «Escribirle» que abre WhatsApp con el
  cliente y un saludo listo. El asistente no les escribe a los clientes: lo
  hace una persona del equipo.
- Eliminar un auto pide confirmación. Si se vendió, es mejor «vender»: queda
  en «Autos vendidos» y da confianza a los clientes.

### WhatsApp del equipo (opcional)

Además de Telegram, el equipo puede hablarle al asistente por WhatsApp. Se
vincula un número dedicado con un QR, como WhatsApp Web:

```powershell
ssh -t root@2.28.140.187 "mendiautos hermes --whatsapp --whatsapp-usuarios 573001234567,573111234567"
```

- Los números autorizados van con indicativo (57) y sin `+` ni espacios. A
  desconocidos no les contesta.
- Cuando aparezca el QR, en el celular del número del asistente: WhatsApp →
  Ajustes → Dispositivos vinculados → Vincular un dispositivo. Si el asistente
  de Hermes pregunta el modo, elige «bot».
- Para un grupo de WhatsApp: agrega el número del asistente al grupo y
  escríbele «@asistente que los avisos de ventas lleguen aquí».
- **Advertencia**: WhatsApp no permite oficialmente este tipo de puentes y
  podría bloquear el número. Por eso debe ser un número aparte, nunca el de
  ventas. Si WhatsApp lo desvincula, repite el comando para escanear otro QR.

## Asistente de clientes (WhatsApp oficial)

Atiende a cualquier persona que escriba al WhatsApp oficial de Mendiautos:
busca autos del catálogo y comparte fichas y fotos, explica cómo vender el
auto, los créditos y los servicios, y cuando el cliente quiere avanzar le pide
nombre, celular y autorización de datos y deja una solicitud: el equipo la
recibe en el canal de ventas como «WhatsApp (asistente de clientes)».

### Qué necesitas (pendiente)

1. **El dominio con HTTPS.** Meta solo entrega los mensajes a una dirección
   `https://`. Cuando tengas acceso al DNS del dominio:
   `ssh root@2.28.140.187 "mendiautos dominio tudominio.com tu@correo.com"`.
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
Hermes para él, te pide el modelo de IA y las tres credenciales de Meta, genera
el token de verificación del webhook y publica `https://tudominio.com/whatsapp/webhook`
en nginx. Si falta algo (dominio, credenciales), lo instala todo pero lo deja
apagado y te dice qué falta; vuelve a correr el comando cuando lo tengas.

Al final muestra la **URL de devolución de llamada** y el **token de
verificación** que se pegan en Meta (WhatsApp → Configuración → Webhook →
«Verificar y guardar»); allí mismo suscribe el campo `messages`.

### Qué puede y qué no

- Solo tiene cuatro herramientas: buscar autos publicados, ver la ficha de un
  auto (con sus fotos), la información del negocio y registrar un interesado.
  No tiene terminal, archivos, internet ni memoria, no ve las solicitudes ni
  las conversaciones de otros clientes y no puede cambiar el catálogo.
- No inventa precios ni promete descuentos, créditos ni citas: dice que un
  asesor lo confirma. No pide cédula, ingresos ni documentos por chat.
- Solo responde a quien le escribe, dentro de las 24 horas que permite Meta.
  Hoy no envía mensajes por su cuenta (plantillas); el seguimiento lo hace el
  equipo desde su WhatsApp.
- La información que da del negocio (dirección, horario, servicios, créditos)
  está en `clientes/empresa.json`: corrígela ahí y publica.
- Costos: el del proveedor de IA por cada mensaje. Meta hoy no cobra las
  respuestas a quien escribió primero (dentro de las 24 horas); revisa su tabla
  de precios vigente.

## Seguridad

- El asistente del equipo solo responde a las personas autorizadas. Corre como
  un usuario sin privilegios cuya única puerta al sitio son los comandos
  `catalogo` y `solicitudes`, que validan todo antes de publicar o guardar.
- El asistente de clientes corre como otro usuario, sin permisos, en un
  servicio de systemd que no le deja ver al asistente del equipo ni las
  solicitudes; solo puede mandar fotos del catálogo.
- Lo que escribe un cliente (formularios o WhatsApp) se trata como datos, nunca
  como instrucciones. Los datos sensibles de un crédito no pasan por los chats:
  salen como «(privado)». Los documentos solo los descarga el administrador
  (`solicitudes documentos S-… --destino …`).
- Las fotos se re-codifican: se les quita la ubicación GPS y los datos del
  celular. Del catálogo, de la placa solo se publica el último dígito.
- Cada cambio del catálogo queda en el historial (`catalogo historial`) y se
  puede deshacer. Además hay un respaldo diario en `/var/backups/mendiautos`
  (se guardan 14). Cada solicitud guarda quién la atendió y cuándo.
- Los comandos peligrosos del asistente del equipo (borrar carpetas, etc.)
  piden aprobación por chat. Si no entiendes lo que pide, responde «no».
- Si el token del bot de Telegram se filtra: en @BotFather usa `/revoke`, y
  luego `ssh -t root@IP "mendiautos hermes --token NUEVO"`. Si se filtra el de
  Meta, revócalo en Business Manager y vuelve a correr
  `mendiautos hermes --clientes --token-meta NUEVO`.
- No agregues el bot del equipo a grupos abiertos.

## Administración (en la VPS)

| Comando | Qué hace |
|---|---|
| `mendiautos estado` | Estado del sitio, del catálogo, de los formularios y de los asistentes |
| `mendiautos hermes` | Instala o completa el asistente del equipo |
| `mendiautos hermes --reiniciar` / `--actualizar` / `--detener` | Reinicia, actualiza Hermes o apaga el asistente del equipo |
| `mendiautos hermes --clientes` | Instala o completa el asistente de clientes |
| `mendiautos hermes --clientes --reiniciar` / `--actualizar` / `--detener` | Lo mismo para el de clientes (`--detener` también quita el webhook) |
| `journalctl -u mendiautos-hermes -f` | Mensajes del asistente del equipo en vivo |
| `journalctl -u mendiautos-clientes -f` | Mensajes del asistente de clientes en vivo |
| `catalogo --help` | El catálogo a mano, sin asistente |
| `solicitudes --help` | Las solicitudes a mano, sin asistente |

Las skills, reglas y herramientas se actualizan solas cada vez que se publica
una versión nueva del sitio desde GitHub.

### El catálogo a mano

El mismo comando que usa el asistente sirve por SSH:

```bash
catalogo listar
catalogo agregar marca=Kia modelo=Picanto anio=2021 precio=42000000 km=35000 transmision=mecanica
catalogo foto agregar picanto /root/fotos/*.jpg
catalogo vender picanto
catalogo deshacer
catalogo campos        # todos los datos que se pueden cargar
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
  `journalctl -u mendiautos-hermes -n 50`. Revisa que el token y los IDs estén
  bien (`mendiautos hermes` los vuelve a pedir si faltan) y que tu proveedor de
  IA tenga saldo.
- **No llegan los avisos de ventas**: `solicitudes pendientes` muestra si hay
  solicitudes; `mendiautos estado` dice si el receptor está activo. En un
  grupo, revisa que el bot siga siendo administrador.
- **«no tiene permiso para editar el catálogo» o «para ver las solicitudes»**:
  `mendiautos hermes` y luego `mendiautos hermes --reiniciar`.
- **Una foto no se sube**: las fotos que llegan por Telegram se borran del
  caché a las 24 horas; reenvíalas.
- **El sitio muestra datos viejos**: recarga la página. `catalogo validar`
  revisa el catálogo y regenera lo que haga falta.
- **El asistente de clientes no contesta**: `journalctl -u mendiautos-clientes -n 50`.
  En Meta, revisa que el webhook esté verificado y suscrito a `messages`, y
  que el token permanente no haya sido revocado.

## Si vuelves a exportar las páginas

Las páginas que muestran autos tienen conectado el catálogo: en el `<head>`
cargan `assets/inventario.js` y `assets/catalogo.js`, y sus listas de autos
están vacías en el diseño y se llenan al abrirse. Las que tienen formularios
cargan `assets/solicitudes.js`. Si vuelves a exportar alguna desde la
herramienta de diseño, esos enlaces se pierden: la página volverá a mostrar los
autos de ejemplo o su formulario dejará de enviar. Avísale a quien mantiene el
sitio antes de reemplazarlas.

`PanelInventario.dc.html` es un panel de demostración: sus cambios quedan solo
en el navegador de quien lo usa y **no** modifican el catálogo real.

## Archivos de esta carpeta

| Archivo | Para qué |
|---|---|
| `instalar.sh` | Lo que corre `mendiautos hermes` (asistente del equipo) |
| `skills/catalogo-mendiautos/SKILL.md` | Procedimientos con el catálogo |
| `skills/ventas-mendiautos/SKILL.md` | Procedimientos con las solicitudes y los avisos |
| `AGENTS.md` / `SOUL.md` | Reglas y personalidad del asistente del equipo |
| `scripts/` | Tareas automáticas sin IA (avisos, resúmenes, vigilante) |
| `clientes/instalar.sh` | Lo que corre `mendiautos hermes --clientes` |
| `clientes/mcp_clientes.py` | Las cuatro herramientas del asistente de clientes |
| `clientes/empresa.json` | La información del negocio que da a los clientes |
| `clientes/AGENTS.md` / `clientes/SOUL.md` | Reglas y personalidad del asistente de clientes |

Los comandos `catalogo` y `solicitudes` están en `deploy/catalogo.py` y
`deploy/solicitudes.py`; `mendiautos.sh` los instala en `/usr/local/bin`.
