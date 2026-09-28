# Asistente del equipo · requerimientos acordados (fase 2)

Cerrados con el cliente el 27/09/2026, a partir de
[`formulario-requerimientos-hermes.md`](formulario-requerimientos-hermes.md) y
sus aclaraciones por chat.

## Usuarios y permisos

Canal: **Telegram, en chat privado**.

| Persona | Rol | ID de Telegram | Puede |
|---|---|---|---|
| Nelson | Gerente | pendiente | Todo |
| Felipe | Administrador | 943010561 | Todo |
| Vendedor 1 (nombre pendiente) | Vendedor | pendiente | Subir autos (datos, fotos y enlace de video) y corregir los que él subió. Publica sin aprobación. No ve solicitudes ni informes, no marca vendidos, no cambia la portada ni los destacados |

Los permisos los hace cumplir el sistema, no solo una instrucción al asistente.
Los avisos de solicitudes nuevas y los informes llegan solo a Nelson y Felipe.

## Menú

Sale con **botones** al saludar. También se puede escribir libremente
(«se vendió el Onix») para cualquier opción.

1. Subir auto
2. Editar auto
3. Fotos y videos de un auto
4. Marcar vendido
5. Portada: título, texto y foto o video propios del bloque principal
6. Informe de movimiento
7. Solicitudes de clientes
8. Destacar autos (5 en el inicio)

La edición de las demás secciones de la página queda fuera por ahora.

## Subir auto

- Acepta varios datos en un mismo mensaje o audio y pregunta solo lo que falte.
- Confirma cada dato («Año: 2022 ✓») y se corrige hablando normal («cambia el
  precio a 95 millones»).
- Obligatorios, en este orden (se acepta «no aplica» donde corresponda): marca,
  modelo, versión, año, precio, ¿negociable?, kilometraje, transmisión,
  combustible, carrocería, tracción, motor o cilindraje, color exterior e
  interior, último dígito de la placa, ciudad, número de dueños, blindado,
  asegurable, permuta, financiación, SOAT y técnico-mecánica (vigencia),
  siniestros, prenda, comparendos, mantenimientos y HP.
- Descripción: la propone el asistente a partir de los datos y el usuario la
  aprueba.
- Velocidad máxima: no se pide ni se muestra. 0-100: no se pide y se oculta si
  está vacío.
- Mínimo 5 fotos y máximo 15. Con menos de 5, pide las que faltan y no publica.
- Resumen final con los datos y un enlace de vista previa. Solo se publica con
  la palabra «Publicar»; mientras tanto el auto queda oculto.
- Borrador sin terminar: se borra a los 7 días (con aviso el día anterior).

## Voz

Español de Colombia. Si no entiende un audio, transcribe y pide confirmar.
Responde solo con texto.

## Fotos

La primera es la portada. El orden se cambia por voz o texto («la 3 de
primera», «orden 2,1,4,3»). Llegan como foto. Sin marca de agua y sin ocultar
la placa.

## Videos

- Recorrido de cada auto: enlace de un reel de **Instagram**, que se ve en la
  página como en festivalviajes.com.ar.
- Otros servicios: enlaces de **YouTube** que se reproducen en la página
  (posventa, trámites de tránsito, fotografía y acompañamiento de compra). Los
  monta el desarrollador, como el resto de esa sección.
- Portada: el video se sube por chat (hasta 20 MB, límite de Telegram).
- Antes de publicar un video confirma el lugar («Este video irá en: ficha de
  Mazda CX-5. ¿Confirmas?»).

## Vendidos

- La confirmación muestra marca, modelo, año, precio, color y último dígito de
  la placa.
- Registra la fecha. Se muestran siempre en «Autos vendidos».
- Se puede revertir; al hacerlo pide actualizar el kilometraje y el precio.

## Portada y destacados

5 autos destacados en el inicio. Si se vende uno, avisa para elegir otro.

## Edición

Todo se puede editar. Los cambios de precio quedan en el historial. No se
muestra el precio anterior tachado.

## Informes

Por mensaje de chat, a Nelson y Felipe: los sábados a las 8:00 a. m. (la
semana) y el día 1 de cada mes (el mes anterior).

- Autos que entraron, autos vendidos y total en inventario.
- Solicitudes de clientes recibidas y atendidas.
- Visitas a la página y autos más vistos, contadas en el propio servidor (sin
  Google Analytics).
- Días promedio en inventario.
- Autos sin fotos o con datos incompletos.

No incluye quién hizo cada cambio.

## Estilo y reglas

Cercano (tú) y con emojis. Deshacer sin límite. Nunca borra sin confirmar,
nunca inventa datos y nunca publica sin «Publicar».

## Fuera de alcance por ahora

- Fotos, textos y videos de las demás secciones (Sobre nosotros, Vende tu auto,
  Aprende, horarios, teléfono, dirección).
- Logos de bancos aliados: los pone el equipo a mano.

## Prioridad

1. Subir auto guiado
2. Fotos y su orden
3. Videos y vendidos
4. Portada y destacados
5. Informes

## Lo que falta

Las claves y tokens **no se envían por chat**: el cliente los pega
directamente en la VPS durante la instalación.

### Por chat, al desarrollador

- [ ] Merge de la PR #1 (la fase 2 va en una PR aparte).
- [ ] Captura o video corto de la parte de festivalviajes.com.ar que quieren
      copiar (dónde y cómo se ve el video de Instagram).
- [ ] Enlaces de YouTube de los 4 videos de servicios (públicos o «no listados»,
      con «permitir insertar» activo).
- [ ] Un auto real de prueba: datos, 5 o más fotos y el enlace de su reel de
      Instagram (la cuenta debe ser pública).
- [ ] ID de Telegram de Nelson, y nombre e ID del vendedor 1 (cada uno le
      escribe a @userinfobot y copia su «Id»).
- [ ] Qué proveedor de IA se usa (solo el nombre).
- [ ] Audios: Groq (rápido y más preciso, pide otra clave) o en el servidor
      (gratis, más lento).

### En la VPS

- [ ] Instalar el asistente (`mendiautos hermes`) y pegar la clave de IA y el
      token del bot creado con @BotFather. La clave de Groq, si se eligió, se
      pega al instalar la fase 2.
- [ ] Nelson, Felipe y el vendedor 1 le escriben «/start» al bot una vez (un
      bot de Telegram no puede escribirle primero a nadie).
- [ ] Credenciales de Meta para el WhatsApp de clientes (fase 1): ver
      [`hermes/README.md`](../hermes/README.md), «Asistente de clientes».

### Decisiones por defecto (si no se dice otra cosa)

- PanelInventario, CargarAuto y PanelMedios se retiran del sitio: son de
  demostración y no cambian el catálogo real.
- «Autos vendidos» arranca vacío; las ventas anteriores se pueden cargar
  después por chat.
- Retención: documentos 90 días y solicitudes 730 días.
- WhatsApp del equipo: no se activa, porque todo va por Telegram.

### Antes de abrir el sitio al público

- [ ] Política de tratamiento de datos (Ley 1581 de 2012), que mencione también
      los videos de YouTube e Instagram insertados en la página.
- [ ] El correo real de ventas (la página dice ventas@mendiautos.com).
- [ ] Opcional: logos de los bancos (PNG o SVG, fondo transparente) si se
      quiere que los monte el desarrollador.
