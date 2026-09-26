/* Mendiautos · comportamiento compartido por todas las páginas.
   Se carga desde el <head> de cada página (ver deploy/README.md). */
(function () {
  'use strict';

  // Botón «Volver» (dentro de [data-mnd-back]): regresa a la página anterior
  // del sitio; si se llegó desde otro sitio o directo, va al inicio.
  function volver() {
    var ref = document.referrer;
    var mismoSitio = false;
    try { mismoSitio = !!ref && new URL(ref).origin === location.origin; } catch (e) { /* URL inválida */ }
    if (mismoSitio && ref !== location.href) {
      if (history.length > 1) history.back();
      else location.href = ref;
    } else {
      location.href = 'MendiautosHome.dc.html';
    }
  }

  // Se escucha en fase de captura para atender el clic antes que React.
  document.addEventListener('click', function (e) {
    var el = e.target;
    var boton = el && el.closest ? el.closest('[data-mnd-back] button') : null;
    if (!boton) return;
    e.preventDefault();
    e.stopPropagation();
    volver();
  }, true);
})();
