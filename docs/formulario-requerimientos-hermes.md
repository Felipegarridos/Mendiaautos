# Formulario de requerimientos · Asistente de Mendiautos (Hermes)

**Cliente:** Mendiautos · **Fecha:** ____ · **Responde:** ____

Instrucciones: marca con `[x]` la opción elegida y completa los espacios.
Donde diga «ejemplo», puedes copiar un mensaje real como lo escribiría tu equipo.

---

## 0. Usuarios y canal

1. ¿Por qué canal usará el equipo el asistente?
   - [ ] Solo Telegram  - [ ] Solo WhatsApp (número dedicado)  - [ ] Ambos
2. ¿Quiénes lo usarán? (nombre, rol, ID de Telegram o celular)

   | Nombre | Rol | Telegram ID / Celular | ¿Puede publicar? | ¿Puede marcar vendidos? | ¿Puede cambiar la portada? |
   |---|---|---|---|---|---|
   | | | | [ ] | [ ] | [ ] |
   | | | | [ ] | [ ] | [ ] |

3. ¿Todos pueden hacer todo, o hay acciones solo para un administrador? ¿Cuáles?
   ____
4. ¿El asistente trabajará en chat privado, en un grupo, o en ambos? ____

## 1. Menú principal

5. ¿Qué opciones debe tener el menú y en qué orden? (marca y numera)
   - [ ] __ Subir auto
   - [ ] __ Editar auto
   - [ ] __ Fotos y videos de un auto
   - [ ] __ Marcar vendido
   - [ ] __ Auto destacado de la portada
   - [ ] __ Imágenes/videos de secciones de la página
   - [ ] __ Informe de movimiento
   - [ ] __ Solicitudes de clientes (formularios)
   - [ ] __ Otra: ____
6. ¿El menú debe salir como **botones** para tocar, o como lista numerada para responder con el número? ____
7. ¿Cuándo aparece el menú? - [ ] Al escribir «menú» o /start  - [ ] Al saludar  - [ ] Al terminar cada tarea
8. ¿El equipo podrá también escribir libremente («se vendió el Onix») sin pasar por el menú?
   - [ ] Sí, ambas formas  - [ ] No, solo por menú

## 2. Subir auto: características y orden

9. Marca las características que se piden, en qué orden (número) y si son **obligatorias (O)** u **opcionales (Op)**:

   | Orden | Característica | O / Op | Ejemplo de valor |
   |---|---|---|---|
   | | Marca | | Mazda |
   | | Modelo | | CX-5 |
   | | Versión | | Grand Touring |
   | | Año | | 2022 |
   | | Precio | | 98.500.000 |
   | | ¿Precio negociable? | | Sí |
   | | Kilometraje | | 41.000 |
   | | Transmisión | | Automática |
   | | Combustible | | Gasolina |
   | | Carrocería | | SUV |
   | | Tracción | | 4x2 |
   | | Motor / cilindraje | | 2.5 |
   | | Color exterior / interior | | Gris / Negro |
   | | Último dígito de la placa | | 3 |
   | | Ciudad | | Bucaramanga |
   | | Número de dueños | | 1 |
   | | Blindado / asegurable / permuta / financiación | | |
   | | SOAT y técnico-mecánica (vigencia) | | |
   | | Descripción (texto libre) | | |
   | | Otra: ____ | | |

10. ¿El asistente pregunta **una característica por mensaje**, o acepta que el usuario mande varias en un solo audio/texto y solo pregunte las que falten?
    - [ ] Una por una siempre  - [ ] Acepta varias y pregunta lo que falte
11. ¿Se pueden saltar las opcionales con «siguiente» / «no sé»? - [ ] Sí - [ ] No
12. ¿La descripción del auto la escribe el equipo, o el asistente propone un texto a partir de los datos para que lo aprueben? ____
13. Ejemplo de un auto real tal como lo dictarían por voz:
    > ____

## 3. Confirmaciones

14. Después de cada característica, ¿cómo confirma?
    - [ ] Repite el dato y sigue («Año: 2022 ✓»)  - [ ] Pide «sí» antes de seguir
15. ¿Con qué palabra se corrige? (ej. «corregir precio: 97 millones») ____
16. Confirmación final antes de publicar: ¿qué palabra o botón? (ej. «PUBLICAR») ____
17. En el resumen final, ¿qué se muestra? - [ ] Todos los datos  - [ ] Datos + fotos en orden  - [ ] Datos + enlace de vista previa
18. Si el usuario abandona a mitad de camino: - [ ] Se guarda como borrador  - [ ] Se descarta  ¿Por cuánto tiempo se guarda? ____
19. ¿Un auto puede quedar guardado **sin publicar** (oculto) hasta que lleguen las fotos? - [ ] Sí - [ ] No

## 4. Voz

20. ¿En qué idioma/acento hablarán? (español Colombia por defecto) ____
21. Si el asistente no entiende bien un audio, ¿qué prefiere? - [ ] Que transcriba y pida confirmar  - [ ] Que pida repetir
22. ¿El asistente debe **responder con audio** también, o solo con texto? ____

## 5. Fotos

23. ¿Cuántas fotos por auto (mínimo / máximo)? ____ / ____
24. ¿Cuál es la portada? - [ ] La primera que envían  - [ ] La eligen ellos
25. ¿Orden estándar de fotos? (ej. frente, lateral, atrás, interior, tablero, motor…) ____
26. Para cambiar el orden, ¿cómo lo dirían? (ej. «la 3 de primera», «orden 2,1,4,3») ____
27. ¿Las fotos llegan desde el celular, desde un fotógrafo, o ambos? ¿Cómo las mandan? - [ ] Como foto  - [ ] Como archivo  - [ ] Enlace (Drive, etc.)
28. ¿Se debe poner marca de agua o logo en las fotos? - [ ] Sí - [ ] No
29. ¿Se debe ocultar/borrosear la placa en las fotos? - [ ] Sí - [ ] No

## 6. Videos

30. ¿Qué videos subirán? - [ ] Recorrido de cada auto  - [ ] Video principal (hero) de la portada  - [ ] Videos de «Aprende»  - [ ] Videos de servicios  - [ ] Otro: ____
31. Duración y tamaño aproximado de cada video (ej. 1 min, grabado con celular) ____
32. ¿Los videos se alojan en el servidor o prefieren YouTube/Instagram y pegar el enlace?
    - [ ] Servidor  - [ ] YouTube  - [ ] Otro: ____
33. Antes de publicar un video, ¿cómo confirma el lugar? (ej. «Este video irá en: Ficha de Mazda CX-5. ¿Confirmas?») ____

## 7. Secciones de la página (imágenes y textos)

34. Marca qué partes de la página quieren poder cambiar por chat:
    - [ ] Imagen/video principal de la portada  - [ ] Textos de la portada
    - [ ] Fotos de «Sobre nosotros»  - [ ] Fotos de Vende tu auto / Compra inmediata / Consignaciones
    - [ ] Fotos y videos de «Otros servicios»  - [ ] Videos de «Aprende»
    - [ ] Logos de bancos aliados  - [ ] Horarios, teléfono, dirección
    - [ ] Otra: ____
35. ¿Quién puede cambiar las secciones de la página? (solo administrador / todos) ____

## 8. Editar autos publicados

36. ¿Qué se puede editar después de publicado? - [ ] Todo  - [ ] Todo menos ____
37. ¿Los cambios de precio deben quedar registrados (historial)? - [ ] Sí - [ ] No
38. ¿Se muestra al público un precio anterior tachado cuando baja el precio? - [ ] Sí - [ ] No

## 9. Autos vendidos

39. ¿Qué datos del auto se muestran en la confirmación antes de marcar vendido? (ej. foto portada, marca, modelo, año, precio) ____
40. ¿Se registra algo adicional al vender? - [ ] Fecha  - [ ] Precio final (privado)  - [ ] Vendedor  - [ ] Nombre del comprador (privado)  - [ ] Nada
41. ¿El auto vendido se sigue mostrando en «Autos vendidos»? ¿Por cuánto tiempo? ____
42. ¿Se puede revertir una venta («volver a disponible»)? - [ ] Sí - [ ] No

## 10. Auto destacado de la portada

43. ¿Cuántos autos destacados en la portada? - [ ] 1  - [ ] Varios (hasta ___)
44. ¿Qué se puede cambiar del destacado? - [ ] Qué auto  - [ ] Texto/descripción propia de portada  - [ ] Foto/video propio de portada
45. ¿Cuando se vende el destacado, qué pasa? - [ ] Lo reemplaza el siguiente automáticamente  - [ ] Avisa para elegir otro

## 11. Informes de movimiento

46. ¿Qué debe incluir el informe? (marca)
    - [ ] Autos nuevos, vendidos y cambios de precio
    - [ ] Quién hizo cada cambio
    - [ ] Solicitudes de clientes recibidas y atendidas
    - [ ] Visitas a la página y autos más vistos (requiere analítica web)
    - [ ] Días promedio en inventario
    - [ ] Autos sin fotos / datos incompletos
    - [ ] Otro: ____
47. ¿Cada cuánto? - [ ] A pedido  - [ ] Diario  - [ ] Semanal (día y hora: ____)  - [ ] Mensual
48. ¿En qué formato? - [ ] Mensaje de chat  - [ ] PDF  - [ ] Excel
49. ¿Quién lo recibe? ____
50. Para visitas a la página: ¿ya usan Google Analytics u otra herramienta? ¿Tienen acceso? ____

## 12. Estilo y reglas

51. ¿Cómo debe hablar el asistente? - [ ] Formal (usted)  - [ ] Cercano (tú)  - [ ] Con emojis  - [ ] Sin emojis
52. ¿Hay algo que el asistente **nunca** debe hacer? ____
53. ¿Cuánto tiempo de «deshacer» necesitan? (hoy se puede deshacer cualquier cambio) ____

## 13. Prioridades y prueba

54. Ordena por prioridad (1 = primero): __ Subir auto guiado · __ Fotos y orden · __ Videos · __ Vendidos · __ Portada · __ Secciones de la página · __ Informes
55. ¿Quién del equipo probará el asistente la primera semana? ____
56. ¿Fecha en que lo necesitan funcionando? ____

---

### Para el implementador (no mostrar al cliente)
- Ya existe: agregar/editar/vender/ocultar/destacar, fotos con orden y portada, deshacer, historial, resumen semanal y avisos de solicitudes.
- Falta según requerimiento: menú con botones, flujo guiado paso a paso con borrador, confirmación final explícita, videos (autos y secciones), edición de imágenes/textos de secciones y portada, informes ampliados (analítica web si la piden).
- Pendientes generales: proveedor de IA y clave, política de datos, credenciales de Meta.
