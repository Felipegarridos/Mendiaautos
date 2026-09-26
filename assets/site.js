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

  // Menú «Compra tu auto» → «Marcas disponibles»: las marcas y cuántos autos
  // disponibles tiene cada una salen del catálogo (assets/inventario.js).
  var LOGOS = {
    'aston martin': 'aston-martin', 'audi': 'audi', 'bmw': 'bmw', 'citroen': 'citroen', 'citroën': 'citroen',
    'ford': 'ford', 'honda': 'honda', 'hyundai': 'hyundai', 'jac': 'jac', 'kia': 'kia', 'land rover': 'land-rover',
    'mercedes-benz': 'mercedes-benz', 'mercedes benz': 'mercedes-benz', 'peugeot': 'peugeot', 'porsche': 'porsche',
    'renault': 'renault', 'suzuki': 'suzuki', 'tesla': 'tesla', 'toyota': 'toyota'
  };
  var SIGLAS = {
    'chevrolet': 'CH', 'mazda': 'MZ', 'nissan': 'NI', 'volkswagen': 'VW', 'mitsubishi': 'MI', 'subaru': 'SB',
    'volvo': 'VO', 'fiat': 'FI', 'byd': 'BYD', 'mg': 'MG', 'dodge': 'DG', 'ram': 'RAM', 'chery': 'CY',
    'changan': 'CA', 'great wall': 'GW', 'lexus': 'LX', 'mini': 'MN', 'jeep': 'JP', 'skoda': 'SK', 'seat': 'SE'
  };

  function pintarFila(fila, marca, n) {
    var k = marca.toLowerCase();
    var logo = fila.querySelector('.mnd-brand-logo');
    var nombre = fila.querySelector('.mnd-brand-name');
    var cuenta = fila.querySelector('.mnd-brand-count');
    if (nombre) nombre.textContent = marca;
    if (cuenta) cuenta.setAttribute('data-count', String(n));
    if (!logo) return;
    var img = logo.querySelector('img');
    if (LOGOS[k]) {
      if (!img) {
        logo.textContent = '';
        img = document.createElement('img');
        logo.appendChild(img);
      }
      img.src = 'assets/marcas/' + LOGOS[k] + '.png';
      img.alt = marca;
    } else {
      logo.textContent = SIGLAS[k] || k.replace(/[^a-z]/g, '').slice(0, 2).toUpperCase() || '··';
    }
  }

  function marcasDelMenu() {
    var rejilla = document.querySelector('.mnd-brands-grid2');
    var inventario = window.MND_INVENTARIO;
    // Antes de dibujarse la página solo existe la plantilla (<x-dc>): se espera.
    if (!rejilla || rejilla.closest('x-dc') || !Array.isArray(inventario)) return false;
    var filas = rejilla.querySelectorAll('.mnd-brand-row');
    if (!filas.length) return true;
    var cuentas = {}, nombres = {};
    inventario.forEach(function (a) {
      if (!a || !a.id || !a.marca || !a.modelo || (a.estado || 'disponible') !== 'disponible') return;
      var m = String(a.marca).trim(), k = m.toLowerCase();
      if (!m) return;
      cuentas[k] = (cuentas[k] || 0) + 1;
      nombres[k] = nombres[k] || m;
    });
    var marcas = Object.keys(cuentas).sort(function (x, y) { return cuentas[y] - cuentas[x] || x.localeCompare(y); });
    marcas.forEach(function (k, i) {
      var fila = filas[i];
      if (!fila) {
        // Más marcas que filas del diseño: se agrega una igual a la primera.
        fila = filas[0].cloneNode(true);
        fila.setAttribute('data-mnd-marca-extra', '');
        fila.style.animationDelay = (0.08 + i * 0.14) + 's';
        fila.style.cursor = 'pointer';
        rejilla.appendChild(fila);
      }
      pintarFila(fila, nombres[k], cuentas[k]);
      fila.style.display = '';
    });
    for (var i = marcas.length; i < filas.length; i++) filas[i].style.display = 'none';
    var sub = document.querySelector('.mnd-brands-sub');
    if (sub) {
      sub.textContent = marcas.length === 0 ? 'Muy pronto, nuevos autos'
        : marcas.length === 1 ? '1 marca en inventario' : marcas.length + ' marcas en inventario';
    }
    return true;
  }

  // Las filas agregadas no tienen el clic que la página les pone a las suyas.
  document.addEventListener('click', function (e) {
    var fila = e.target && e.target.closest ? e.target.closest('[data-mnd-marca-extra]') : null;
    if (!fila) return;
    var nombre = fila.querySelector('.mnd-brand-name');
    location.href = 'AutosDisponibles.dc.html?q=' + encodeURIComponent(nombre ? nombre.textContent.trim() : '');
  });

  // El menú lo dibuja la página al cargar: se espera a que exista.
  var intentos = 0;
  (function esperarMenu() {
    if (marcasDelMenu() || ++intentos > 150) return;
    setTimeout(esperarMenu, 100);
  })();
})();
