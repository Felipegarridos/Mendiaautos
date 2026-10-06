/* Mendiautos · vista previa de un auto sin publicar.
   DetalleAuto.dc.html?previa=<clave> carga catalogo/previas/<clave>.js (lo
   genera el comando catalogo para cada borrador) antes de dibujar la ficha.
   Solo quien tiene el enlace ve el borrador; no aparece en ninguna lista.
   Si el auto ya se publicó, ese archivo lleva a su ficha.
   La clave son 22 caracteres: lo que venga pegado detrás (un «\n», un punto,
   un paréntesis que el chat incluyó en el enlace) se ignora. */
(function () {
  'use strict';
  var clave = '';
  try { clave = new URLSearchParams(location.search).get('previa') || ''; } catch (e) { /* sin parámetros */ }
  var m = /^[A-Za-z0-9_-]{22}/.exec(clave);
  if (!m) return;
  var meta = document.createElement('meta');
  meta.name = 'robots';
  meta.content = 'noindex, nofollow';
  document.head.appendChild(meta);
  // Tiene que cargar antes que la ficha, igual que assets/inventario.js: por eso document.write (un script
  // creado con createElement correría después). m[0] solo tiene letras, números, «_» y «-».
  document.write('<script src="catalogo/previas/' + m[0] + '.js"><\/script>');
})();
