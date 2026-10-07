# Asistente del equipo · requerimientos acordados (fase 2)

Cerrados con el cliente el 27/09/2026, a partir de
[`formulario-requerimientos-hermes.md`](formulario-requerimientos-hermes.md) y
sus aclaraciones por chat.

## Usuarios y permisos

Canal: **Telegram, en chat privado**.

| Persona | Rol | ID de Telegram | Puede |
|---|---|---|---|
| Nelson (dueño) | Administrador | 8560493493 | Todo |
| Felipe (pruebas) | Administrador | 943010561 | Todo |
| Duban (pruebas) | Administrador | 1715388212 | Todo |
| Vendedores (cuando entren) | Vendedor | — | Subir autos (datos, fotos y enlace de video) y corregir los que él subió. Publica sin aprobación. No ve solicitudes ni informes, no marca vendidos, no cambia la portada ni los destacados |

Por ahora Felipe y Duban tienen acceso total porque prueban el asistente
(30/09/2026). El rol de vendedor queda listo para cuando entre el primero.

Los permisos los hace cumplir el sistema, no solo una instrucción al asistente.
Los avisos de solicitudes nuevas y los informes llegan a los administradores y
gerentes (hoy Nelson, Felipe y Duban), no a los vendedores.

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

El botón «Menú» de Telegram (junto al campo de texto) está en español, con
solo tres opciones: ver el menú con botones (/menu), empezar de cero (/new) y
detener lo que está haciendo el asistente (/stop) (ajustado el 03/10/2026:
antes mostraba unos 60 comandos de Hermes en inglés).

## Subir auto

- Acepta varios datos en un mismo mensaje o audio y pregunta solo lo que falte,
  **todo en un solo mensaje** (no de a uno), hasta completar el auto. Si en un
  audio vienen varios autos, crea un borrador por cada uno (ajustado el
  03/10/2026: al cliente le cansaba dar los datos de a uno).
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
- Mínimo 5 fotos y máximo 20 (cambiado el 02/10/2026; antes 15). Con menos de
  5, pide las que faltan y no publica.
- Resumen final con los datos y un enlace de vista previa. Solo se publica con
  la palabra «Publicar»; mientras tanto el auto queda oculto.
- Borrador sin terminar: se borra a los 7 días (con aviso el día anterior).

## Voz

Español de Colombia. No devuelve la transcripción del audio: guarda lo que
entendió y, si algo no quedó claro, pregunta solo por eso, en concreto
(ajustado el 06/10/2026: antes reenviaba la transcripción completa y alargaba
la conversación). Responde solo con texto.

## Fotos

La primera es la portada. El orden se cambia por voz o texto («la 3 de
primera», «orden 2,1,4,3»). Llegan como foto. Sin marca de agua y sin ocultar
la placa.

## Videos

- Recorrido de cada auto: enlace de un reel de **Instagram**, que se ve en la
  página como en festivalviajes.com.ar, o de un video de **TikTok**, que se ve
  con el reproductor oficial de TikTok en el mismo lugar (agregado el
  07/10/2026). Sirve el enlace corto que copia la app de TikTok.
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

Por mensaje de chat, a los administradores y gerentes: los sábados a las
8:00 a. m. (la semana) y el día 1 de cada mes (el mes anterior).

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

## Estado (28/09/2026)

Hecho en la fase 2 (ver `hermes/README.md`): todo lo de arriba. Decisiones
tomadas: IA con **Gemini**, audios transcritos **en el servidor**, el reel de
Instagram se ve como en festivalviajes.com.ar (la tarjeta oficial de
Instagram, en la ficha del auto, debajo del precio).

## Lo que falta

Las claves y tokens **no se envían por chat**: el cliente los pega
directamente en la VPS durante la instalación.

### Por chat, al desarrollador

- [ ] Enlaces de YouTube de los 4 videos de servicios (públicos o «no listados»,
      con «permitir insertar» activo). También los puede poner el gerente por
      el asistente.
- [ ] El auto real de prueba: datos y 5 o más fotos (el reel ya llegó).

### En la VPS

- [ ] Publicar la fase 2 y registrar al equipo (en una sesión `ssh root@2.28.140.187`):
      `mendiautos actualizar`, luego
      `mendiautos equipo agregar 8560493493 Nelson administrador`,
      `mendiautos equipo agregar 943010561 Felipe administrador` y
      `mendiautos equipo agregar 1715388212 Duban administrador`.
- [ ] Instalar el asistente: `mendiautos hermes`. Pide la clave de Gemini y el
      token del bot de @BotFather. El primer intento (30/09, con el instalador
      de la fase 1) instaló Hermes y se detuvo en la configuración; con la
      fase 2 publicada, termina.
- [ ] Nelson, Felipe y Duban le escriben «/start» al bot una vez (un bot de
      Telegram no puede escribirle primero a nadie).
- [ ] Credenciales de Meta para el WhatsApp de clientes (fase 1): ver
      [`hermes/README.md`](../hermes/README.md), «Asistente de clientes».

### Decisiones por defecto (si no se dice otra cosa)

- PanelInventario, CargarAuto y PanelMedios se retiraron del sitio.
- «Autos vendidos» arranca vacío; las ventas anteriores se pueden cargar
  después por chat.
- Retención: documentos 90 días y solicitudes 730 días.
- WhatsApp del equipo: no se activa, porque todo va por Telegram.
- Los 9 autos de ejemplo del diseño siguen publicados hasta que se borren o
  se reemplacen por los reales.

### Antes de abrir el sitio al público

- [ ] Política de tratamiento de datos (Ley 1581 de 2012), que mencione también
      los videos de YouTube, Instagram y TikTok insertados en la página.
- [ ] El correo real de ventas (la página dice ventas@mendiautos.com).
- [ ] Opcional: logos de los bancos (PNG o SVG, fondo transparente) si se
      quiere que los monte el desarrollador.
