repo: Felipegarridos/Mendiaautos
branch: main

## Last sync
date: 2026-10-14T02:55:00Z
Nota: GitHub (main) tiene una versión MÁS reciente que este proyecto. Subir SOLO los
archivos listados en "Archivos modificados" y "Archivos nuevos". No pisar los de
"NO sobrescribir".

### Archivos modificados (subir)
- MendiautosHome.dc.html: imágenes reales en las 6 tarjetas del menú (Autos disponibles, Vende tu Auto, Solicita tu crédito, Otros servicios, Busca tu auto, Autos Vendidos); foto del vehículo destacado (BMW Serie 8) con máscara/filtro para fundirse con el fondo; quitados los guiones decorativos y el enlace "VER TODO"; quitado el panel "Marcas disponibles"; botón de la tarjeta "Busca tu auto" igualado al resto (círculo + flecha + VER MÁS); marcas del párrafo en color normal (ya no rojo); quitadas Porsche y Aston Martin del carrusel de marcas.
- AutosDisponibles.dc.html: hero "La Colección" con foto real (encuadre subido para que se vean los autos); hero y panel de filtros compactados + reglas móviles (@media 640px); línea azul del hero eliminada.
- AutosVendidos.dc.html: hero "Vendido · Archivo" con foto real; línea azul del hero eliminada.
- VendeTuAuto.dc.html: quitado el panel "Marcas disponibles"; hero corregido (se quitaron posiciones fijas left:83px/top:212px y el offset left:-30px/top:4px; título anclado abajo-izquierda como las demás páginas) y eliminado el remanente vacío de la línea azul. HTML balanceado (44/44 divs, sin </div> de más).
- assets/site.js: mapa de logos ampliado (Chevrolet, Mazda, Nissan, Ferrari, Volkswagen, Volvo, Mini); si una marca no tiene PNG o el PNG falla, se pinta un monograma limpio (nunca queda vacío/roto). Afecta el panel "Marcas disponibles" del menú.
- assets/catalogo.js: mapa de logos equivalente + logo real en las tarjetas de auto (antes solo iniciales), con respaldo a monograma; círculo de la marca más grande (26→38px, logo 18→28px); menos espacios en blanco dentro de las tarjetas (padding/márgenes) sin reducir el texto.
- github.md: este archivo.

### Archivos nuevos (subir)
- assets/card-autos-disponibles.jpg
- assets/card-vende-tu-auto.jpg
- assets/card-solicita-credito.jpg
- assets/card-otros-servicios.jpg
- assets/card-busca-tu-auto.jpg
- assets/card-autos-vendidos.jpg
- assets/foto-destacado.jpg
- assets/hero-coleccion.jpg
- assets/hero-vendidos.jpg
- assets/marcas/chevrolet.png
- assets/marcas/mazda.png
- assets/marcas/nissan.png
- assets/marcas/ferrari.png
- assets/marcas/volkswagen.png
- assets/marcas/volvo.png
- assets/marcas/mini.png
- assets/marcas/audi.png (reemplazo del existente)
- assets/marcas/bmw.png (reemplazo del existente)
- assets/marcas/hyundai.png (reemplazo del existente)
- assets/marcas/tesla.png (reemplazo del existente)

### NO sobrescribir (ni en GitHub ni en el servidor)
- assets/inventario.js — aquí es una demo; el inventario real lo administra el bot de Telegram.
- catalogo/fotos/ — fotos reales de los autos del cliente (no existe en este proyecto).
- assets/hero-video.mp4 — la de este proyecto es la vieja (DASH fragmentado que a veces no corre en iPhone); en GitHub ya está la corregida. NO incluida en el ZIP.
- assets/hero-video-movil.mp4
- assets/hero-poster.jpg
- support.js — runtime; usar el de GitHub.
- index.html — es copia exacta de MendiautosHome.dc.html (ver nota abajo).

### Nota sobre index.html
MendiautosHome.dc.html SÍ cambió en esta tanda. Como index.html es una copia exacta
de MendiautosHome.dc.html, hay que copiar el nuevo MendiautosHome.dc.html también
sobre index.html al publicar.

## Sync history
- 2026-10-14T01:51: descargada la última versión del repo (20 páginas + support.js + assets/); añadida Login.dc.html.
- 2026-09-23: repo asociado vacío (sin commits); publicación manual.

## Screen map
| Pantalla | Archivo |
| --- | --- |
| Home | MendiautosHome.dc.html |
| Autos disponibles | AutosDisponibles.dc.html |
| Autos vendidos | AutosVendidos.dc.html |
| Detalle del auto | DetalleAuto.dc.html |
| Comparar autos | ComparaAutos.dc.html |
| Vende tu auto | VendeTuAuto.dc.html |
| Compra inmediata | CompraInmediata.dc.html |
| Consignación física | ConsignacionFisica.dc.html |
| Consignación virtual | ConsignacionVirtual.dc.html |
| Créditos (simulador) | Creditos.dc.html |
| Solicitud de crédito | SolicitudCredito.dc.html |
| El inversionista | Inversionista.dc.html |
| Dashboard inversiones | DashboardInversiones.dc.html |
| Busca tu auto | BuscaTuAuto.dc.html |
| Aprende (videos) | Aprende.dc.html |
| Sobre nosotros | SobreNosotros.dc.html |
| Contacto | Contacto.dc.html |
| Otros servicios | OtrosServicios.dc.html |
