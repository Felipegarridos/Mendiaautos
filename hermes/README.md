# Asistente de Telegram para el catálogo (Hermes)

El equipo de Mendiautos le escribe a un bot de Telegram y el catálogo del sitio
se actualiza al instante:

> «Llegó una Mazda CX-5 Grand Touring 2022, gris, 41 mil km, automática, 98,5 millones»
> *(y luego las fotos)*
> «Se vendió el Onix» · «Bájale 2 millones al Duster» · «Pon la Hilux en la portada»
> «¿Qué autos no tienen fotos?» · «Deshaz lo último»

El bot es [Hermes Agent](https://hermes-agent.nousresearch.com) (Nous Research)
instalado en la misma VPS, con una skill hecha para este sitio.

## Cómo funciona

```
Telegram ──▶ Hermes (usuario «hermes», sin privilegios)
                │  solo puede usar el comando «catalogo»
                ▼
          catalogo ──▶ /var/lib/mendiautos/catalogo
                          inventario.json   los autos + historial para deshacer
                          inventario.js     lo que lee el sitio
                          fotos/            fotos procesadas (sin GPS, dos tamaños)
                ▼
          nginx sirve /assets/inventario.js y /catalogo/fotos/ ──▶ todas las páginas
```

- Las páginas (inicio, disponibles, vendidos, ficha, comparar) dibujan los
  autos desde `assets/inventario.js` con `assets/catalogo.js`.
- En el servidor, ese archivo lo genera el comando `catalogo` fuera de las
  versiones publicadas. Así, ni una versión nueva desde GitHub ni una nueva
  exportación de la herramienta de diseño pisan los autos cargados por Telegram.
  El `assets/inventario.js` del repositorio solo sirve para arrancar el catálogo
  la primera vez.

## Qué necesitas

1. El sitio instalado en la VPS (`mendiautos instalar`, ver `deploy/README.md`).
2. Una clave de API de un proveedor de IA: OpenRouter, Anthropic, OpenAI, Nous
   Portal u otro de los que soporta Hermes. Conviene un modelo que vea imágenes.
   Cada mensaje consume unos pocos tokens; revisa los precios de tu proveedor.
3. Un bot de Telegram: en Telegram abre **@BotFather**, envía `/newbot` y guarda
   el token que te da.
4. El ID numérico de Telegram de cada persona que usará el bot: cada una le
   escribe a **@userinfobot** y te pasa su «Id».

## Instalación (una vez)

Desde tu PC, en PowerShell:

```powershell
ssh -t root@2.28.140.187 "mendiautos hermes"
```

El `-t` permite responder las preguntas. El comando:

1. Crea el usuario `hermes` (sin contraseña ni acceso por SSH) y lo autoriza a
   usar **solo** el comando `catalogo`.
2. Instala Hermes para ese usuario (tarda unos minutos).
3. Copia la skill `catalogo-mendiautos`, las reglas (`AGENTS.md`) y la
   personalidad (`SOUL.md`) de esta carpeta.
4. Te pide el modelo de IA con el asistente propio de Hermes, luego el token
   del bot (sin mostrarlo en pantalla) y los IDs autorizados.
5. Programa dos tareas sin IA (no gastan tokens): el **vigilante** del sitio
   cada 30 minutos (avisa si la página no responde, si el certificado está por
   vencer o si el disco se llena) y el **resumen del catálogo** los lunes a las
   8:00 (vendidos, nuevos, autos sin fotos o sin precio).
6. Deja el asistente como servicio (`mendiautos-hermes`), que arranca con el
   servidor.

Los avisos llegan al primer ID autorizado. Para mandarlos a un grupo, agrega el
bot al grupo y escribe `/sethome` allí.

Para volver a correrlo sin preguntas:
`mendiautos hermes --token <TOKEN> --usuarios 111111111,222222222`.
Ojo: así el token queda en el historial de la consola.

## Uso diario

Escríbele al bot como a un compañero. Ejemplos:

| Mensaje | Qué hace |
|---|---|
| «Llegó un Kia Picanto 2021, 35 mil km, mecánico, 42 millones» | Lo agrega; si faltan datos, pregunta |
| *(fotos)* «Estas son del Picanto» | Sube las fotos; la primera es la portada |
| «Prepara el BMW X3 pero no lo publiques aún» | Lo deja oculto hasta que digas «publícalo» |
| «Pon de portada la tercera foto del Picanto» | Cambia la foto principal |
| «Bájale 2 millones al Duster» | Calcula y actualiza el precio |
| «Se vendió la Frontier» | Pasa a «Autos vendidos» |
| «Destaca el Corolla en la portada» | Aparece en «Autos disponibles» del inicio |
| «¿Qué autos tenemos?» / «¿Cuáles no tienen fotos?» | Lista o resumen |
| «Deshaz lo último» | Revierte el último cambio (se puede repetir) |

Consejos:

- Envía las fotos como **foto**, no como archivo. Las fotos HEIC de iPhone
  enviadas como archivo no se pueden procesar.
- El bot confirma cada cambio con el enlace del auto: ábrelo para revisar.
- Eliminar un auto pide confirmación. Si se vendió, es mejor «vender»: queda
  en «Autos vendidos» y da confianza a los clientes.

## Seguridad

- Solo responden las personas cuyos IDs están autorizados.
- Hermes corre como un usuario sin privilegios. La única puerta hacia el sitio
  es `catalogo`, que valida cada dato antes de publicarlo. El asistente no puede
  escribir los archivos del sitio aunque se lo pidan.
- Las fotos se re-codifican: se les quita la ubicación GPS y los datos del
  celular. De la placa solo se publica el último dígito.
- Cada cambio queda en el historial (`catalogo historial`) y se puede
  deshacer. Además hay un respaldo diario en `/var/backups/mendiautos` (se
  guardan 14).
- Los comandos peligrosos del asistente (borrar carpetas, etc.) piden
  aprobación por Telegram. Si no entiendes lo que pide, responde «no».
- Si el token del bot se filtra: en @BotFather usa `/revoke`, y luego
  `ssh -t root@IP "mendiautos hermes --token NUEVO"`.
- No agregues el bot a grupos abiertos.

## Administración (en la VPS)

| Comando | Qué hace |
|---|---|
| `mendiautos estado` | Estado del sitio, del catálogo y del asistente |
| `mendiautos hermes` | Instala o completa la configuración |
| `mendiautos hermes --reiniciar` | Reinicia el asistente |
| `mendiautos hermes --actualizar` | Actualiza Hermes y lo reinicia |
| `mendiautos hermes --detener` | Apaga el asistente (no borra nada) |
| `journalctl -u mendiautos-hermes -f` | Mensajes del asistente en vivo |
| `catalogo --help` | El catálogo a mano, sin asistente |

La skill y las reglas se actualizan solas cada vez que se publica una versión
nueva del sitio desde GitHub; no hace falta reiniciar.

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

### Recuperar un respaldo

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
- **«no tiene permiso para editar el catálogo»**: `mendiautos hermes` y luego
  `mendiautos hermes --reiniciar`.
- **Una foto no se sube**: las fotos que llegan por Telegram se borran del
  caché a las 24 horas; reenvíalas.
- **El sitio muestra datos viejos**: recarga la página. `catalogo validar`
  revisa el catálogo y regenera lo que haga falta.

## Si vuelves a exportar las páginas

Las páginas que muestran autos tienen conectado el catálogo: en el `<head>`
cargan `assets/inventario.js` y `assets/catalogo.js`, y sus listas de autos
están vacías en el diseño y se llenan al abrirse. Si vuelves a exportar
MendiautosHome, AutosDisponibles, AutosVendidos, DetalleAuto, ComparaAutos o
PanelInventario desde la herramienta de diseño, esos enlaces se pierden y la
página volverá a mostrar los autos de ejemplo del diseño. Avísale a quien
mantiene el sitio antes de reemplazarlas.

`PanelInventario.dc.html` es un panel de demostración: sus cambios quedan solo
en el navegador de quien lo usa y **no** modifican el catálogo real.

## Archivos de esta carpeta

| Archivo | Para qué |
|---|---|
| `instalar.sh` | Lo que corre `mendiautos hermes` |
| `skills/catalogo-mendiautos/SKILL.md` | Procedimientos del asistente con el catálogo |
| `AGENTS.md` | Reglas del espacio de trabajo (se copia a `/home/hermes/mendiautos`) |
| `SOUL.md` | Personalidad y tono del asistente |
| `scripts/vigilar-sitio.sh` | Vigilante del sitio (tarea sin IA) |
| `scripts/resumen-catalogo.sh` | Resumen semanal (tarea sin IA) |

El comando `catalogo` está en `deploy/catalogo.py`. `mendiautos.sh` lo instala
en `/usr/local/bin/catalogo`.
