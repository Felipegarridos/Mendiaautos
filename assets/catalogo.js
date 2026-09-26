/* Mendiautos · catálogo de autos.
   Todas las páginas que muestran autos (inicio, disponibles, vendidos, detalle
   y comparar) los dibujan desde window.MND_INVENTARIO, definido en
   assets/inventario.js. En el servidor ese archivo lo reemplaza el catálogo
   que administra el asistente por Telegram (ver hermes/README.md).
   Todo texto del catálogo se escapa antes de insertarlo en la página. */
(function () {
  'use strict';

  var SIGLAS = {
    'renault': 'RN', 'chevrolet': 'CH', 'toyota': 'TO', 'mazda': 'MZ', 'kia': 'KI',
    'nissan': 'NI', 'hyundai': 'HY', 'ford': 'FO', 'volkswagen': 'VW', 'suzuki': 'SZ',
    'mercedes-benz': 'MB', 'bmw': 'BMW', 'audi': 'AU', 'peugeot': 'PG', 'jac': 'JC',
    'honda': 'HO', 'tesla': 'TS', 'porsche': 'PO', 'land rover': 'LR', 'aston martin': 'AM',
    'citroën': 'CI', 'citroen': 'CI', 'jeep': 'JP', 'mitsubishi': 'MI', 'subaru': 'SB',
    'volvo': 'VO', 'fiat': 'FI', 'byd': 'BYD', 'mg': 'MG', 'dodge': 'DG', 'ram': 'RAM',
    'chery': 'CY', 'changan': 'CA', 'great wall': 'GW', 'lexus': 'LX', 'mini': 'MN'
  };
  var FOTO_VALIDA = /^(catalogo\/fotos|assets)\/[A-Za-z0-9._\-\/]+\.(jpe?g|png|webp)$/i;
  var ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

  function esc(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) { return ESCAPES[c]; });
  }
  function miles(n) {
    return String(Math.round(+n || 0)).replace(/\B(?=(\d{3})+(?!\d))/g, '.');
  }
  function hay(v) { return v !== undefined && v !== null && String(v).trim() !== '' && v !== '—'; }
  function precio(n) { return +n > 0 ? '$' + miles(n) : 'Consultar'; }
  function km(n) { return hay(n) && !isNaN(+n) ? miles(n) + ' km' : ''; }
  function siNo(v) { return v === true ? 'Sí' : v === false ? 'No' : '—'; }
  function texto(v) { return hay(v) ? String(v) : '—'; }

  // Los autos «ocultos» están en preparación: no salen en ninguna página.
  function autos() {
    var d = window.MND_INVENTARIO;
    return Array.isArray(d) ? d.filter(function (a) {
      return a && a.id && a.marca && a.modelo && a.estado !== 'oculto';
    }) : [];
  }
  function disponibles() {
    return autos().filter(function (a) { return (a.estado || 'disponible') === 'disponible'; });
  }
  function vendidos() {
    return autos().filter(function (a) { return a.estado === 'vendido'; }).sort(function (x, y) {
      return String(y.vendido_el || '').localeCompare(String(x.vendido_el || ''));
    });
  }
  function buscar(id) {
    var l = autos();
    for (var i = 0; i < l.length; i++) if (l[i].id === id) return l[i];
    return null;
  }

  function nombre(a) { return [a.marca, a.modelo, a.version].filter(hay).join(' '); }
  function titulo(a) { return [nombre(a), a.anio].filter(hay).join(' '); }
  function siglas(marca) {
    var m = String(marca || '').trim().toLowerCase();
    return SIGLAS[m] || m.replace(/[^a-z]/g, '').slice(0, 2).toUpperCase() || '··';
  }
  function fotos(a) {
    return (Array.isArray(a.fotos) ? a.fotos : []).filter(function (u) {
      return typeof u === 'string' && FOTO_VALIDA.test(u) && u.indexOf('..') < 0;
    });
  }
  function enlace(a) { return 'DetalleAuto.dc.html?id=' + encodeURIComponent(a.id); }
  // Días de calendario (hora local) desde una fecha AAAA-MM-DD.
  function diasDesde(fecha) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(fecha || '');
    if (!m) return null;
    var hoy = new Date();
    hoy.setHours(0, 0, 0, 0);
    return Math.max(0, Math.round((hoy - new Date(+m[1], +m[2] - 1, +m[3])) / 86400000));
  }
  function vendidoHace(a) {
    var d = diasDesde(a.vendido_el);
    if (d === null) return 'Vendido';
    if (d === 0) return 'Vendido hoy';
    if (d === 1) return 'Vendido ayer';
    return 'Vendido hace ' + d + ' días';
  }

  // ------------------------------------------------------------ tarjetas
  // Las fotos que sube el comando catalogo vienen en dos tamaños: <huella>.jpg
  // (1600 px) y <huella>-m.jpg (800 px). El navegador elige según «sizes».
  var TAM_TARJETA = '(max-width: 640px) 92vw, 300px';
  function img(url, alt, sizes) {
    var mediana = /^catalogo\/fotos\/.+\.jpg$/i.test(url) ? url.replace(/\.jpg$/i, '-m.jpg') : '';
    return '<img src="' + esc(mediana || url) + '"' +
      (mediana ? ' srcset="' + esc(mediana) + ' 800w, ' + esc(url) + ' 1600w" sizes="' + esc(sizes || TAM_TARJETA) + '"' : '') +
      ' alt="' + esc(alt) + '" loading="lazy" decoding="async"' +
      ' style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover">';
  }
  function puntos(n) {
    if (n === 1) return '';
    var total = n > 1 ? Math.min(n, 5) : 4, h = '';
    for (var i = 0; i < total; i++) {
      h += i === 0
        ? '<span style="width:18px;height:6px;border-radius:100px;background:#fff"></span>'
        : '<span style="width:6px;height:6px;border-radius:50%;background:rgba(255,255,255,.5)"></span>';
    }
    return '<div style="position:absolute;bottom:12px;left:50%;transform:translateX(-50%);display:flex;gap:6px;align-items:center">' + h + '</div>';
  }
  function zonaFoto(a, alto) {
    var f = fotos(a);
    return '<div style="padding:8px 8px 0"><div class="mnd-photo" style="position:relative;height:' + alto +
      'px;border-radius:12px;overflow:hidden;background:repeating-linear-gradient(45deg,#17130f 0 15px,#211b16 15px 30px);display:flex;align-items:flex-end;padding:12px">' +
      (f.length ? img(f[0], nombre(a))
        : '<span style="font:400 10px/1 ui-monospace,monospace;color:rgba(255,255,255,.4)">FOTO · ' + esc(a.marca + ' ' + a.modelo) + '</span>') +
      puntos(f.length) + '</div></div>';
  }
  var FLECHA = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M7 17 17 7M9 7h8v8" stroke-linecap="round" stroke-linejoin="round"></path></svg>';
  function chevron(color) {
    return '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="' + color + '" stroke-width="2.2"><path d="M6 9l6 6 6-6" stroke-linecap="round" stroke-linejoin="round"></path></svg>';
  }
  function botonFicha(a) {
    return '<a href="' + esc(enlace(a)) + '" aria-label="Ver ' + esc(titulo(a)) + '" style="width:34px;height:34px;border-radius:8px;background:rgba(30,80,162,.14);display:flex;align-items:center;justify-content:center;color:#1E50A2">' + FLECHA + '</a>';
  }
  function marcaFila(a, envolvente, estiloMarca) {
    return '<div' + envolvente + ' style="display:flex;align-items:center;gap:10px"><span style="width:26px;height:26px;border-radius:50%;border:1px solid var(--ln-strong);display:flex;align-items:center;justify-content:center;font:700 9px/1 \'Open Sans\',sans-serif;color:var(--t-2);background:var(--c-circle)">' +
      esc(siglas(a.marca)) + '</span><span style="font:600 11px/1 \'Open Sans\',sans-serif;letter-spacing:.2em;text-transform:uppercase;color:var(--t-2)' + estiloMarca + '">' + esc(a.marca) + '</span></div>';
  }
  function atributos(a) {
    return ' data-id="' + esc(a.id) + '" data-href="' + esc(enlace(a)) + '"';
  }

  // Inicio: carrusel «Autos disponibles».
  function tarjetaInicio(a) {
    return '<div class="mnd-card"' + atributos(a) + ' style="flex:0 0 300px;background:var(--c-card);border:1px solid var(--ln);border-radius:18px;overflow:hidden">' +
      zonaFoto(a, 178) +
      '<div style="padding:18px 20px 20px">' + marcaFila(a, ' class="mnd-brandrow"', '') +
      '<h3 style="margin:14px 0 0;font:500 22px/1.15 \'Open Sans\',sans-serif;color:var(--t-strong)">' + esc(nombre(a)) + '</h3>' +
      '<div style="margin-top:12px;font:400 13px/1 \'Open Sans\',sans-serif;color:var(--t-2)">' + esc(km(a.km)) + '</div>' +
      '<div style="margin-top:18px;padding-top:16px;border-top:1px solid var(--ln);display:flex;align-items:center;justify-content:space-between">' +
      '<span style="display:inline-flex;align-items:center;gap:8px;font:700 20px/1 \'Open Sans\',sans-serif;color:var(--t-strong)">' + esc(precio(a.precio)) + chevron('var(--t-2)') + '</span>' +
      botonFicha(a) + '</div></div></div>';
  }

  // Catálogo (disponibles) y archivo (vendidos).
  function tarjetaCatalogo(a) {
    var vendido = a.estado === 'vendido';
    return '<div class="mnd-card mnd-reveal"' + atributos(a) + ' style="background:var(--c-card);border:1px solid var(--ln);border-radius:18px;overflow:hidden">' +
      zonaFoto(a, 230) +
      '<div style="padding:18px 20px 20px">' + marcaFila(a, '', '') +
      '<h3 style="margin:14px 0 0;font:500 20px/1.2 \'Open Sans\',sans-serif;color:var(--t-strong)">' + esc(titulo(a)) + '</h3>' +
      '<div style="margin-top:12px;font:400 13px/1 \'Open Sans\',sans-serif;color:var(--t-2)">' + esc(km(a.km)) + '</div>' +
      (vendido ? '<div style="margin-top:8px;display:inline-flex;align-items:center;gap:6px;font:600 11px/1 \'Open Sans\',sans-serif;color:#1E50A2"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"></circle><path d="M12 7v5l3 2" stroke-linecap="round" stroke-linejoin="round"></path></svg>' + esc(vendidoHace(a)) + '</div>' : '') +
      '<div style="margin-top:18px;padding-top:16px;border-top:1px solid var(--ln);display:flex;align-items:center;justify-content:space-between">' +
      '<span style="display:inline-flex;align-items:center;gap:8px;font:700 19px/1 \'Open Sans\',sans-serif;color:var(--t-strong)">' +
      (vendido ? 'Vendido' : esc(precio(a.precio)) + chevron('var(--t-3)')) + '</span>' +
      botonFicha(a) + '</div></div></div>';
  }

  // Detalle: carrusel «Recomendados para ti».
  function tarjetaRecomendado(a) {
    var f = fotos(a);
    return '<a href="' + esc(enlace(a)) + '" style="flex:0 0 270px;scroll-snap-align:start;background:var(--c-card);border:1px solid var(--ln);border-radius:14px;overflow:hidden;display:block">' +
      '<div style="position:relative;height:170px;background:repeating-linear-gradient(45deg,#17130f 0 15px,#211b16 15px 30px)">' +
      (f.length ? img(f[0], nombre(a)) : '') +
      '<span style="position:absolute;top:10px;left:10px;background:#1E50A2;color:#fff;font:700 9px/1 \'Open Sans\',sans-serif;letter-spacing:.1em;padding:6px 9px;border-radius:4px">DISPONIBLE</span></div>' +
      '<div style="padding:16px 18px 18px"><div style="font:700 15px/1.2 \'Open Sans\',sans-serif;color:var(--t-strong)">' + esc(nombre(a)) + '</div>' +
      '<div style="margin-top:6px;font:400 12px/1 \'Open Sans\',sans-serif;color:var(--t-3)">' + esc([a.anio, km(a.km)].filter(hay).join(' · ')) + '</div>' +
      '<div style="margin-top:12px;font:700 17px/1 \'Open Sans\',sans-serif;color:var(--t-strong)">' + esc(precio(a.precio)) + '</div></div></a>';
  }

  function vacio(mensaje) {
    return '<div class="mnd-catalogo-vacio" style="grid-column:1/-1;flex:1 1 100%;padding:48px 20px;text-align:center;font:400 15px/1.6 \'Open Sans\',sans-serif;color:var(--t-3)">' + esc(mensaje) + '</div>';
  }

  // ------------------------------------------------------------- pintar
  function pintarInicio(el) {
    if (!el) return;
    var l = disponibles(), d = l.filter(function (a) { return a.destacado; });
    d = (d.length ? d : l).slice(0, 12);
    el.innerHTML = d.length ? d.map(tarjetaInicio).join('') : vacio('Muy pronto publicaremos nuevos autos.');
  }
  // El filtro «Marca» trae botones fijos con logo; se agregan (con sus siglas)
  // las marcas del catálogo que no estén, para que también se puedan filtrar.
  // Corre antes de que la página conecte los clics de esos botones.
  function completarMarcas(lista) {
    var rejilla = document.querySelector('.mnd-filt[data-f="marca"] .mnd-brand-grid');
    if (!rejilla) return;
    var hay = {};
    Array.prototype.forEach.call(rejilla.querySelectorAll('.mnd-brand-chip'), function (b) {
      hay[String(b.getAttribute('data-brand') || '').toLowerCase()] = true;
    });
    lista.forEach(function (a) {
      var m = String(a.marca || '').trim();
      if (!m || hay[m.toLowerCase()]) return;
      hay[m.toLowerCase()] = true;
      rejilla.insertAdjacentHTML('beforeend', '<button class="mnd-brand-chip" data-brand="' + esc(m) +
        '" type="button"><span class="mnd-blogo">' + esc(siglas(m)) + '</span>' + esc(m) + '</button>');
    });
  }
  function pintarDisponibles(el) {
    if (!el) return;
    var l = disponibles();
    completarMarcas(l);
    el.innerHTML = l.length ? l.map(tarjetaCatalogo).join('') : vacio('Estamos preparando nuevos autos. Escríbenos y te ayudamos a encontrar el tuyo.');
  }
  function pintarVendidos(el) {
    if (!el) return;
    var l = vendidos();
    completarMarcas(l);
    el.innerHTML = l.length ? l.map(tarjetaCatalogo).join('') : vacio('Aquí verás los autos que ya encontraron dueño.');
  }
  function pintarRecomendados(el, excluirId) {
    if (!el) return;
    var l = disponibles().filter(function (a) { return a.id !== excluirId; }).slice(0, 8);
    // El carrusel se desplaza -50 %: la lista va dos veces para que el giro sea continuo.
    el.innerHTML = l.length ? l.concat(l).map(tarjetaRecomendado).join('') : '';
  }

  // ------------------------------------------------------------- detalle
  function autoDeLaPagina() {
    var id = '';
    try { id = new URLSearchParams(location.search).get('id') || ''; } catch (e) { /* sin parámetros */ }
    if (id) return buscar(id);
    var l = disponibles();
    return l.filter(function (a) { return a.destacado; })[0] || l[0] || autos()[0] || null;
  }

  // Valores ya formateados para los {{a.campo}} de DetalleAuto.dc.html.
  function detalle(a) {
    if (!a) {
      a = { id: '', marca: '', modelo: '' };
      var vacio = detalle(a);
      vacio.existe = false;
      vacio.titulo = 'Auto no disponible';
      return vacio;
    }
    var h = a.historial || {}, f = fotos(a), partes = String(a.descripcion || '').split(/\n\s*\n/);
    var vendido = a.estado === 'vendido';
    return {
      existe: true, id: a.id, vendido: vendido, disponible: !vendido,
      titulo: titulo(a), nombre: nombre(a), marca: texto(a.marca), modelo: texto(a.modelo),
      version: texto(a.version), anio: texto(a.anio),
      precio: vendido ? 'VENDIDO' : precio(a.precio),
      precioColor: vendido ? '#1E50A2' : 'var(--t-strong)',
      km: hay(a.km) ? miles(a.km) : '—',
      combustible: texto(a.combustible), transmision: texto(a.transmision),
      carroceria: texto(a.carroceria), tipoCarroceria: texto(a.tipo_carroceria || a.carroceria),
      traccion: texto(a.traccion), motor: texto(a.motor || a.cilindraje),
      motorCorto: texto(a.motor_corto || (a.cilindraje ? String(a.cilindraje).replace(/\.(\d)00\s*cc/i, '.$1').replace(/\s*cc/i, '') : '')),
      hp: texto(a.hp), velocidad: texto(a.velocidad_max),
      aceleracion: hay(a.aceleracion) ? String(a.aceleracion).replace('.', ',') + ' s' : '—',
      negociable: siNo(a.negociable), blindado: siNo(a.blindado), unicoDueno: siNo(a.unico_dueno),
      asegurable: siNo(a.asegurable), financiacion: siNo(a.financiacion), permuta: siNo(a.permuta),
      colorExterior: texto(a.color_exterior), colorInterior: texto(a.color_interior),
      referencia: texto(a.referencia), placaFin: texto(a.placa_fin), ciudad: texto(a.ciudad || 'Bucaramanga'),
      resumen: texto(a.resumen), condicion: texto(a.condicion), garantia: texto(a.garantia),
      descripcion1: partes[0] || '', descripcion2: partes.slice(1).join('\n\n'),
      tieneDescripcion2: partes.length > 1,
      duenos: texto(h.duenos), siniestros: texto(h.siniestros), mantenimientos: texto(h.mantenimientos),
      rtm: texto(h.rtm), soat: texto(h.soat), prenda: texto(h.prenda), comparendos: texto(h.comparendos),
      tieneLinea: Array.isArray(h.linea) && h.linea.length > 0,
      fotoEtiqueta: 'FOTO · ' + a.marca + ' ' + a.modelo, sinFotos: f.length === 0, numFotos: f.length
    };
  }

  // Galería de la ficha: foto principal, miniaturas y flechas.
  function pintarGaleria(a) {
    var zona = document.querySelector('.mnd-gal-img');
    var tira = document.querySelector('.mnd-gal-tira');
    if (!zona || !tira || !a) return;
    var f = fotos(a), actual = 0;
    function mostrar(i) {
      if (!f.length) return;
      actual = (i + f.length) % f.length;
      zona.innerHTML = img(f[actual], nombre(a) + ' · foto ' + (actual + 1), '(max-width: 900px) 100vw, 60vw');
      zona.firstChild.removeAttribute('loading');
      var ths = tira.querySelectorAll('.mnd-thumb');
      for (var k = 0; k < ths.length; k++) ths[k].classList.toggle('sel', k === actual);
    }
    if (f.length) {
      tira.innerHTML = f.map(function (u, i) {
        return '<div class="mnd-thumb" data-i="' + i + '" style="position:relative">' + img(u, nombre(a) + ' · miniatura ' + (i + 1), '160px') + '</div>';
      }).join('');
      tira.onclick = function (e) {
        var t = e.target.closest ? e.target.closest('.mnd-thumb') : null;
        if (t) mostrar(+t.getAttribute('data-i'));
      };
      mostrar(0);
    } else {
      var h = '';
      for (var i = 0; i < 9; i++) h += '<div class="mnd-thumb' + (i ? '' : ' sel') + '"></div>';
      tira.innerHTML = h;
    }
    var prev = document.querySelector('.mnd-gal-prev'), next = document.querySelector('.mnd-gal-next');
    if (prev) prev.onclick = function () { mostrar(actual - 1); };
    if (next) next.onclick = function () { mostrar(actual + 1); };
  }

  function pintarLinea(el, a) {
    if (!el || !a) return;
    var l = (a.historial && Array.isArray(a.historial.linea)) ? a.historial.linea : [];
    el.innerHTML = l.map(function (p, i) {
      return '<div style="position:relative;' + (i < l.length - 1 ? 'margin-bottom:22px' : '') + '"><span style="position:absolute;left:-26px;top:2px;width:14px;height:14px;border-radius:50%;background:' +
        (i === 0 ? '#1E50A2' : 'var(--ln-strong)') + ';border:3px solid var(--bg)"></span><div style="font:700 13px/1.3 \'Open Sans\',sans-serif;color:var(--t-strong)">' +
        esc(p && p.titulo) + '</div><div style="margin-top:4px;font:400 13px/1.6 \'Open Sans\',sans-serif;color:var(--t-2)">' + esc(p && p.texto) + '</div></div>';
    }).join('');
  }

  window.MND_CATALOGO = {
    autos: autos, disponibles: disponibles, vendidos: vendidos, buscar: buscar,
    esc: esc, precio: precio, km: km, nombre: nombre, titulo: titulo, fotos: fotos, enlace: enlace,
    pintarInicio: pintarInicio, pintarDisponibles: pintarDisponibles, pintarVendidos: pintarVendidos,
    pintarRecomendados: pintarRecomendados, autoDeLaPagina: autoDeLaPagina, detalle: detalle,
    pintarGaleria: pintarGaleria, pintarLinea: pintarLinea
  };
})();
