/* Mendiautos · vista previa de un auto sin publicar.
   DetalleAuto.dc.html?previa=<clave> carga catalogo/previas/<clave>.js (lo
   genera el comando catalogo para cada borrador) antes de dibujar la ficha.
   Solo quien tiene el enlace ve el borrador; no aparece en ninguna lista. */
(function () {
  'use strict';
  var clave = '';
  try { clave = new URLSearchParams(location.search).get('previa') || ''; } catch (e) { /* sin parámetros */ }
  if (!/^[A-Za-z0-9_-]{22}$/.test(clave)) return;
  var meta = document.createElement('meta');
  meta.name = 'robots';
  meta.content = 'noindex, nofollow';
  document.head.appendChild(meta);
  // Tiene que cargar antes que la ficha, igual que assets/inventario.js.
  document.write('<script src="catalogo/previas/' + clave + '.js"><\/script>');
})();
