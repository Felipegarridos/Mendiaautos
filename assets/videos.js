/* Mendiautos · videos insertados.
   - Recorrido de un auto (ficha): un reel de Instagram, que se ve como en la
     sección de Instagram de festivalviajes.com.ar, un video de TikTok (con su
     reproductor oficial para páginas) o un video de YouTube.
   - «Otros servicios»: un video de YouTube por servicio, según
     window.MND_SITIO.servicios (assets/sitio.js, lo cambia el asistente).
   YouTube se carga solo cuando la persona toca el video (antes se ve la
   miniatura) y desde youtube-nocookie.com. Nada de esto usa scripts de
   Instagram, TikTok ni YouTube dentro de la página: solo marcos (iframes). */
(function () {
  'use strict';

  var RE_YOUTUBE = /^https:\/\/www\.youtube\.com\/watch\?v=([A-Za-z0-9_-]{11})$/;
  var RE_CODIGO = /^[A-Za-z0-9_-]{5,40}$/;

  function crear(etiqueta, atributos, estilo) {
    var el = document.createElement(etiqueta);
    Object.keys(atributos || {}).forEach(function (k) { el.setAttribute(k, atributos[k]); });
    if (estilo) el.style.cssText = estilo;
    return el;
  }

  // Instagram avisa el alto de su tarjeta con un mensaje «MEASURE»; así el
  // marco queda del tamaño justo, como con el código oficial de inserción.
  var marcosInstagram = [];
  window.addEventListener('message', function (e) {
    if (e.origin !== 'https://www.instagram.com') return;
    var d = e.data;
    try { if (typeof d === 'string') d = JSON.parse(d); } catch (err) { return; }
    var alto = d && d.type === 'MEASURE' && d.details && +d.details.height;
    if (!alto || alto < 100 || alto > 4000) return;
    marcosInstagram.forEach(function (m) {
      if (m.contentWindow === e.source) m.style.height = Math.round(alto) + 'px';
    });
  });

  function instagram(zona, ruta, codigo, titulo) {
    if (!zona || !RE_CODIGO.test(codigo || '') || !/^(reel|p|tv)$/.test(ruta || '')) return;
    var enlace = 'https://www.instagram.com/' + ruta + '/' + codigo + '/';
    var ancho = Math.min(540, Math.max(300, zona.clientWidth || 340));
    var marco = crear('iframe', {
      src: enlace + 'embed/?cr=1&v=14&wp=' + ancho,
      title: 'Video en Instagram · ' + (titulo || 'Mendiautos'),
      loading: 'lazy', scrolling: 'no', allowtransparency: 'true',
      allow: 'autoplay; encrypted-media; fullscreen; picture-in-picture; clipboard-write',
      referrerpolicy: 'strict-origin-when-cross-origin'
    }, 'display:block;width:100%;max-width:540px;min-width:280px;height:' + Math.round(ancho * 1.25 + 190) +
       'px;margin:0 auto;border:0;border-radius:12px;background:#fff;overflow:hidden');
    marcosInstagram.push(marco);
    poner(zona, marco, enlace, 'Ver el video en Instagram');
  }

  // TikTok: su reproductor oficial para páginas (www.tiktok.com/player/v1), en
  // vertical como el video y sin el texto de la publicación encima. Con rel=0,
  // al terminar sugiere otros videos de la misma cuenta y no de otras.
  function tiktok(zona, cuenta, id, titulo) {
    if (!zona || !/^\d{8,25}$/.test(id || '') || !/^[A-Za-z0-9_.]{1,30}$/.test(cuenta || '')) return;
    var marco = crear('iframe', {
      src: 'https://www.tiktok.com/player/v1/' + id + '?rel=0',
      title: 'Video en TikTok · ' + (titulo || 'Mendiautos'),
      loading: 'lazy', allowfullscreen: '',
      allow: 'autoplay; encrypted-media; fullscreen; picture-in-picture',
      referrerpolicy: 'strict-origin-when-cross-origin'
    }, 'display:block;width:100%;max-width:340px;aspect-ratio:9 / 16;margin:0 auto;border:0;border-radius:12px;background:#000');
    poner(zona, marco, 'https://www.tiktok.com/@' + cuenta + '/video/' + id, 'Ver el video en TikTok');
  }

  // El marco y, debajo, el enlace para verlo en la red social por si no carga.
  function poner(zona, marco, enlace, texto) {
    var respaldo = crear('a', { href: enlace, target: '_blank', rel: 'noopener' },
      'display:block;margin-top:10px;text-align:center;font:600 12px/1.4 \'Open Sans\',sans-serif;color:#1E50A2');
    respaldo.textContent = texto;
    zona.textContent = '';
    zona.appendChild(marco);
    zona.appendChild(respaldo);
  }

  // YouTube: miniatura con botón; el reproductor se carga al tocarla.
  function youtube(zona, id, titulo) {
    if (!zona || !/^[A-Za-z0-9_-]{11}$/.test(id || '')) return;
    zona.setAttribute('data-youtube', id);
    zona.setAttribute('role', 'button');
    zona.setAttribute('tabindex', '0');
    zona.setAttribute('aria-label', 'Reproducir video' + (titulo ? ': ' + titulo : ''));
    if (getComputedStyle(zona).position === 'static') zona.style.position = 'relative';
    if (!zona.style.aspectRatio && !zona.clientHeight) zona.style.aspectRatio = '16 / 9';
    if (!zona.querySelector('.mnd-yt-mini')) {
      var mini = crear('img', { src: 'https://i.ytimg.com/vi/' + id + '/hqdefault.jpg', alt: '', loading: 'lazy',
        'class': 'mnd-yt-mini' }, 'position:absolute;inset:0;width:100%;height:100%;object-fit:cover');
      zona.insertBefore(mini, zona.firstChild);
    }
    if (!zona.querySelector('.mnd-play')) {
      var boton = crear('div', { 'class': 'mnd-play' },
        'position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);width:64px;height:64px;border-radius:50%;' +
        'background:#1E50A2;display:flex;align-items:center;justify-content:center;color:#fff;cursor:pointer');
      boton.innerHTML = '<svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"></path></svg>';
      zona.appendChild(boton);
    } else {
      zona.querySelector('.mnd-play').style.zIndex = '1';
    }
    Array.prototype.forEach.call(zona.querySelectorAll('span'), function (s) {
      if (/^VIDEO ·/.test(s.textContent || '')) s.style.display = 'none';  // rótulo del diseño
    });
  }

  function reproducir(zona) {
    var id = zona.getAttribute('data-youtube');
    if (!id || zona.querySelector('iframe')) return;
    var marco = crear('iframe', {
      src: 'https://www.youtube-nocookie.com/embed/' + id + '?autoplay=1&rel=0&playsinline=1',
      title: zona.getAttribute('aria-label') || 'Video',
      allow: 'accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share',
      allowfullscreen: '', referrerpolicy: 'strict-origin-when-cross-origin'
    }, 'position:absolute;inset:0;width:100%;height:100%;border:0;z-index:2');
    zona.appendChild(marco);
  }
  // Un solo escuchador para toda la página: sigue funcionando aunque la página
  // vuelva a dibujar sus bloques.
  document.addEventListener('click', function (e) {
    var zona = e.target.closest ? e.target.closest('[data-youtube]') : null;
    if (zona) reproducir(zona);
  }, true);
  document.addEventListener('keydown', function (e) {
    if ((e.key === 'Enter' || e.key === ' ') && e.target.hasAttribute && e.target.hasAttribute('data-youtube')) {
      e.preventDefault();
      reproducir(e.target);
    }
  }, true);

  // «Otros servicios»: los bloques .mnd-vid[data-video="posventa"|…].
  function servicios() {
    var lista = window.MND_SITIO && window.MND_SITIO.servicios || {};
    var n = 0;
    Array.prototype.forEach.call(document.querySelectorAll('.mnd-vid[data-video]'), function (zona) {
      if (zona.closest('x-dc')) return;  // la plantilla sin dibujar
      n++;
      var m = RE_YOUTUBE.exec(lista[zona.getAttribute('data-video')] || '');
      if (m && !zona.hasAttribute('data-youtube')) youtube(zona, m[1], zona.textContent.replace(/^\s*VIDEO ·\s*/, ''));
    });
    return n;
  }
  function esperarServicios(intentos) {
    if (servicios() || intentos <= 0) return;
    setTimeout(function () { esperarServicios(intentos - 1); }, 100);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { esperarServicios(150); });
  } else {
    esperarServicios(150);
  }

  window.MND_VIDEOS = { instagram: instagram, tiktok: tiktok, youtube: youtube };
})();
