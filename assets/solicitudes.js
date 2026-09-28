/* Mendiautos · formularios del sitio.
   Contacto, Busca tu auto, Vende tu auto (compra inmediata y consignaciones),
   Otros servicios, la alerta de inventario y la solicitud de crédito envían lo
   que escribe el cliente al receptor del servidor (/api/solicitud, ver
   deploy/solicitudes.py). El receptor lo guarda y el asistente avisa al equipo
   de ventas. Si el envío falla, se ofrece mandar el mismo resumen por WhatsApp.
   El clic se atiende en fase de captura, antes que la lógica de cada página. */
(function () {
  'use strict';

  var API = 'api/solicitud';
  var WHATSAPP = '573118058132';
  var MAX_FOTOS = 12, MAX_DOCS = 8, MAX_TOTAL = 44 * 1024 * 1024;
  var MAX_BYTES_FOTO = 15 * 1024 * 1024, MAX_BYTES_DOC = 12 * 1024 * 1024;
  var ROJO = '#d9534f';
  var cargada = Date.now();
  var pagina = decodeURIComponent(location.pathname.split('/').pop() || '');

  // Formularios de cada página: el botón que envía, el tipo de solicitud, el
  // bloque con los campos (por defecto, la tarjeta del botón) y el «¡Gracias!».
  var FORMULARIOS = {
    'Contacto.dc.html': [{ boton: '.mnd-enviar', tipo: 'contacto', ok: '.mnd-ok' }],
    'BuscaTuAuto.dc.html': [{ boton: '.mnd-enviar', tipo: 'busca', ok: '.mnd-ok' }],
    'CompraInmediata.dc.html': [{ boton: '.mnd-enviar', tipo: 'compra', ok: '.mnd-ok' }],
    'ConsignacionFisica.dc.html': [{ boton: '.mnd-enviar', tipo: 'consignacion-fisica', ok: '.mnd-ok' }],
    'ConsignacionVirtual.dc.html': [{ boton: '.mnd-enviar', tipo: 'consignacion-virtual', ok: '.mnd-ok' }],
    'OtrosServicios.dc.html': [
      { boton: '.mnd-p-send', tipo: 'servicio', zona: '.mnd-svc-panel', ok: '.mnd-p-ok' },
      { boton: '.mnd-acomp-btn', tipo: 'acompanamiento', ok: '.mnd-acomp-ok' }
    ],
    'AutosDisponibles.dc.html': [
      { boton: '.mnd-al-save', tipo: 'alerta', zona: '.mnd-alerta-form', ok: '.mnd-al-ok', mostrar: 'inline', estadoEnFila: true }
    ],
    'SolicitudCredito.dc.html': [{ boton: '.mnd-siguiente', tipo: 'credito', ok: '.mnd-ok', credito: true }]
  };
  var TITULOS = {
    contacto: 'Contacto', busca: 'Busca tu auto', compra: 'Compra inmediata',
    'consignacion-fisica': 'Consignación física', 'consignacion-virtual': 'Consignación virtual',
    servicio: 'Otros servicios', acompanamiento: 'Acompañamiento de compra',
    alerta: 'Alerta de inventario', credito: 'Solicitud de crédito'
  };
  var CONFS = FORMULARIOS[pagina] || [];
  if (!CONFS.length) return;

  var ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  function esc(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) { return ESCAPES[c]; });
  }
  function cada(lista, fn) { Array.prototype.forEach.call(lista || [], fn); }
  function miles(n) { return String(Math.round(+n || 0)).replace(/\B(?=(\d{3})+(?!\d))/g, '.'); }
  function parametro(k) {
    try { return new URLSearchParams(location.search).get(k) || ''; } catch (e) { return ''; }
  }

  // Campo trampa: invisible para las personas; los robots lo llenan.
  var trampa = document.createElement('input');
  trampa.type = 'text';
  trampa.name = 'mnd-hp-campo';
  trampa.tabIndex = -1;
  trampa.autocomplete = 'off';
  trampa.setAttribute('aria-hidden', 'true');
  trampa.style.cssText = 'position:absolute;left:-9999px;top:0;width:1px;height:1px;opacity:0';
  (document.body || document.documentElement).appendChild(trampa);

  // ------------------------------------------------------------- campos
  function limpiarEtiqueta(t) {
    return String(t || '').replace(/\(opcional\)/ig, '').replace(/\*/g, '').replace(/\s+/g, ' ').trim().replace(/:$/, '');
  }
  function primerTexto(b) {
    var n = b.firstChild;
    return String(n && n.nodeType === 3 ? n.textContent : b.textContent).trim();
  }
  // Valor de un campo: lo escrito o elegido, y las opciones marcadas (chips).
  function valorDe(cont) {
    var escrito = [], marcado = [];
    cada(cont.querySelectorAll('input, select, textarea'), function (c) {
      if (/^(file|checkbox|radio|hidden|button|submit)$/.test(c.type)) return;
      var v = String(c.value || '').trim();
      if (v) escrito.push(v);
    });
    cada(cont.querySelectorAll('.mnd-chip.on, .mnd-seg.on'), function (b) {
      var t = primerTexto(b);
      if (t) marcado.push(t);
    });
    return escrito.concat(marcado.length ? [marcado.join(', ')] : []).join(' ');
  }
  // Cada <label> nombra el campo que está junto a ella en su mismo contenedor.
  function recoger(zona) {
    var pares = [], campos = [], archivos = [];
    cada(zona.querySelectorAll('label'), function (lab) {
      if (lab.classList.contains('mnd-up') || lab.querySelector('input[type=checkbox], input[type=file]')) return;
      var cont = lab.parentElement;
      if (!cont || cont === zona) return;
      var etiqueta = limpiarEtiqueta(lab.textContent);
      var valor = valorDe(cont);
      // Lo que se escribe (no las listas, que siempre traen algo) decide si está lleno.
      var escritos = Array.prototype.filter.call(cont.querySelectorAll('input, textarea'), function (c) {
        return !/^(file|checkbox|radio|hidden|button|submit)$/.test(c.type);
      });
      var vacio = escritos.filter(function (c) { return !String(c.value || '').trim(); })[0];
      campos.push({
        etiqueta: etiqueta, valor: valor, requerido: !!lab.querySelector('.mnd-req'),
        lleno: escritos.length ? !vacio : !!valor,
        ctrl: vacio || cont.querySelector('input:not([type=file]):not([type=checkbox]), select, textarea')
      });
      if (etiqueta && valor) pares.push([etiqueta, valor]);
    });
    cada(zona.querySelectorAll('input[type=file]'), function (inp) {
      var caja = inp.closest('label') || inp.parentElement;
      var t = caja && caja.querySelector('.mnd-up-t');
      var etiqueta = limpiarEtiqueta(t ? t.textContent : 'Archivo') || 'Archivo';
      // Solo imágenes = fotos del auto; lo que admite PDF = documentos (privados).
      var clase = (inp.getAttribute('accept') || '').trim() === 'image/*' ? 'foto' : 'documento';
      cada(inp.files, function (f) { archivos.push({ clase: clase, etiqueta: etiqueta, archivo: f }); });
    });
    return { pares: pares, campos: campos, archivos: archivos };
  }

  // ------------------------------------------------------------- crédito
  function pasoCredito() {
    for (var n = 3; n >= 1; n--) {
      var b = document.querySelector('.mnd-p' + n);
      if (b && b.style.display !== 'none') return n;
    }
    return 1;
  }
  function irAPaso(n) {
    var atras = document.querySelector('.mnd-atras');
    for (var p = pasoCredito(), i = 0; atras && p > n && i < 3; p = pasoCredito(), i++) atras.click();
  }
  function autoDeInteres() {
    var id = parametro('auto'), inv = window.MND_INVENTARIO;
    if (!id) return null;
    if (Array.isArray(inv)) {
      for (var i = 0; i < inv.length; i++) if (inv[i] && inv[i].id === id) return inv[i];
    }
    return { id: id };
  }
  function nombreAuto(a) {
    return [a.marca, a.modelo, a.anio].filter(function (x) { return x != null && String(x).trim(); }).join(' ');
  }
  function extrasCredito() {
    var pares = [];
    var seg = document.querySelector('.mnd-tipo .mnd-seg.on');
    if (seg) pares.push(['Tipo de crédito', primerTexto(seg)]);
    var a = autoDeInteres();
    if (a) pares.push(['Auto de interés', nombreAuto(a) ? nombreAuto(a) + ' (ref. ' + a.id + ')' : a.id]);
    var precio = parametro('precio');
    if (precio) {
      pares.push(['Simulación', [
        'vehículo $' + miles(precio),
        parametro('inicial') ? 'inicial $' + miles(parametro('inicial')) : '',
        parametro('plazo') ? parametro('plazo') + ' meses' : '',
        parametro('cuota') ? 'cuota $' + miles(parametro('cuota')) : ''
      ].filter(Boolean).join(' · ')]);
    }
    return pares;
  }
  // Si viene de la ficha de un auto, «Tu simulación» dice cuál es. Se espera a
  // que la página esté dibujada: antes solo existe la plantilla (<x-dc>).
  function mostrarAutoEnSimulacion() {
    var a = autoDeInteres(), intentos = 0;
    if (!a || !nombreAuto(a)) return;
    (function poner() {
      var precio = document.querySelector('.mnd-r-precio');
      if (precio && precio.closest('x-dc')) precio = null;
      var rotulo = precio && precio.previousElementSibling;
      if (!rotulo) {
        if (++intentos < 100) setTimeout(poner, 100);
        return;
      }
      rotulo.textContent = nombreAuto(a);
      rotulo.title = nombreAuto(a);
      rotulo.style.cssText += ';overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-right:12px';
    })();
  }

  // ------------------------------------------------------------ validar
  function digitos(v) { return String(v || '').replace(/\D/g, ''); }
  function validar(datos, zona, bloque, final) {
    var faltan = datos.campos.filter(function (c) {
      return c.requerido && !c.lleno && (!bloque || (c.ctrl && bloque.contains(c.ctrl)));
    });
    if (faltan.length) {
      return {
        mensaje: 'Completa ' + (faltan.length === 1 ? 'el campo' : 'los campos') + ': ' +
          faltan.map(function (c) { return c.etiqueta; }).join(', ') + '.',
        campos: faltan.map(function (c) { return c.ctrl; })
      };
    }
    if (!final) return null;
    var cel = null, correo = null;
    datos.campos.forEach(function (c) {
      if (!cel && /celular|tel[eé]fono|whatsapp/i.test(c.etiqueta)) cel = c;
      if (!correo && /correo|e-?mail/i.test(c.etiqueta)) correo = c;
    });
    var celOk = cel && digitos(cel.valor).length >= 10 && digitos(cel.valor).length <= 15;
    var correoOk = correo && /^[^@\s]+@[^@\s]+\.[a-z]{2,}$/i.test(correo.valor);
    if (cel && cel.valor && !celOk && !correoOk) {
      return { mensaje: 'Revisa tu número de celular: escribe los 10 dígitos.', campos: [cel.ctrl] };
    }
    if (!celOk && !correoOk) {
      return {
        mensaje: cel ? 'Déjanos tu celular (WhatsApp)' + (correo ? ' o tu correo' : '') + ' para poder contactarte.'
          : 'Déjanos tu correo para poder contactarte.',
        campos: [(cel || correo || {}).ctrl]
      };
    }
    if (correo && correo.requerido && !correoOk) {
      return { mensaje: 'Revisa tu correo electrónico.', campos: [correo.ctrl] };
    }
    var acepto = zona.querySelector('.mnd-terms');
    if (acepto && !acepto.checked) {
      return { mensaje: 'Para enviar, marca la autorización de tratamiento de datos.', campos: [acepto] };
    }
    return null;
  }

  function marcar(ctrl) {
    if (!ctrl) return;
    var caja = ctrl;
    if (ctrl.type === 'checkbox') caja = ctrl.closest('label') || ctrl;
    else if (parseFloat(getComputedStyle(ctrl).borderTopWidth) === 0 && ctrl.parentElement) caja = ctrl.parentElement;
    var antes = { borde: caja.style.borderColor, linea: caja.style.outline, sep: caja.style.outlineOffset };
    if (ctrl.type === 'checkbox') {
      caja.style.outline = '1px dashed ' + ROJO;
      caja.style.outlineOffset = '6px';
    } else {
      caja.style.borderColor = ROJO;
    }
    function quitar() {
      caja.style.borderColor = antes.borde;
      caja.style.outline = antes.linea;
      caja.style.outlineOffset = antes.sep;
      ctrl.removeEventListener('input', quitar);
      ctrl.removeEventListener('change', quitar);
    }
    ctrl.addEventListener('input', quitar);
    ctrl.addEventListener('change', quitar);
  }

  // -------------------------------------------------------------- avisos
  var ICONO_WA = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M21 11.5a8.4 8.4 0 0 1-12.3 7.4L3 21l2.1-5.7A8.4 8.4 0 1 1 21 11.5Z" stroke-linejoin="round"></path></svg>';

  // El panel de un servicio (Otros servicios) se despliega con max-height:
  // si su contenido crece, hay que agrandarlo.
  function reajustar(zona) {
    var panel = zona.closest ? zona.closest('.mnd-svc-panel') : null;
    if (panel && panel.classList.contains('open')) panel.style.maxHeight = panel.scrollHeight + 'px';
  }
  function cajaEstado(zona, boton, conf) {
    var el = zona.querySelector('.mnd-sol-estado');
    if (el) return el;
    el = document.createElement('div');
    el.className = 'mnd-sol-estado';
    el.setAttribute('role', 'status');
    el.setAttribute('aria-live', 'polite');
    var ancla = conf.credito ? (boton.closest('.mnd-nav') || boton) : conf.estadoEnFila ? boton.parentElement : boton;
    ancla.parentNode.insertBefore(el, ancla.nextSibling);
    return el;
  }
  function estado(zona, boton, conf, clase, html) {
    var el = cajaEstado(zona, boton, conf);
    var error = clase === 'error';
    el.style.cssText = 'display:' + (html ? 'block' : 'none') + ';margin-top:14px;padding:13px 16px;border-radius:10px;' +
      "font:600 13px/1.55 'Open Sans',sans-serif;text-align:left;" +
      (error ? 'border:1px solid rgba(217,83,79,.45);background:rgba(217,83,79,.08);color:' + ROJO
        : 'border:1px solid var(--ln);background:transparent;color:var(--t-2)');
    el.innerHTML = html || '';
    reajustar(zona);
    return el;
  }
  function enlaceWhatsApp(conf, pares, archivos) {
    var l = ['Hola Mendiautos, les escribo desde la página web (' + (TITULOS[conf.tipo] || 'solicitud') + ').', ''];
    pares.forEach(function (p) { l.push(p[0] + ': ' + p[1]); });
    var fotos = archivos.filter(function (a) { return a.clase === 'foto'; }).length;
    var docs = archivos.length - fotos;
    if (archivos.length) {
      l.push('', 'Tengo ' + [fotos ? 'fotos' : '', docs ? 'documentos' : ''].filter(Boolean).join(' y ') +
        ' para enviarles por este chat.');
    }
    var t = l.join('\n');
    if (t.length > 1800) t = t.slice(0, 1799) + '…';
    return 'https://wa.me/' + WHATSAPP + '?text=' + encodeURIComponent(t);
  }
  function botonWhatsApp(url) {
    return '<a href="' + esc(url) + '" target="_blank" rel="noopener" style="display:inline-flex;align-items:center;gap:9px;' +
      'margin-top:12px;border:1px solid var(--ln-strong);color:var(--t-strong);border-radius:10px;padding:12px 18px;' +
      "font:700 11.5px/1 'Open Sans',sans-serif;letter-spacing:.08em;text-transform:uppercase;text-decoration:none\">" +
      ICONO_WA + 'Enviar por WhatsApp</a>';
  }
  function mostrarError(zona, boton, conf, error) {
    (error.campos || []).forEach(marcar);
    var primero = (error.campos || [])[0];
    var el = estado(zona, boton, conf, 'error', esc(error.mensaje) + (error.whatsapp ? '<br>' + botonWhatsApp(error.whatsapp) : ''));
    if (primero && primero.focus) {
      try { primero.focus({ preventScroll: true }); } catch (e) { primero.focus(); }
      primero.scrollIntoView({ behavior: 'smooth', block: 'center' });
    } else {
      el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }

  // -------------------------------------------------------------- fotos
  // Las fotos del celular pesan varios MB: se reducen a 2000 px antes de
  // subirlas (el servidor las deja en 1600 px). Si no se puede, va la original.
  function reducir(f) {
    return new Promise(function (listo) {
      if (!/^image\/(jpeg|png|webp)$/i.test(f.type || '') || f.size < 1500000 || !window.URL || !URL.createObjectURL) {
        listo(f);
        return;
      }
      var url = URL.createObjectURL(f), im = new Image(), hecho = false;
      function fin(b) {
        if (hecho) return;
        hecho = true;
        try { URL.revokeObjectURL(url); } catch (e) { /* nada */ }
        listo(b && b.size && b.size < f.size ? b : f);
      }
      im.onload = function () {
        try {
          var k = Math.min(1, 2000 / Math.max(im.naturalWidth, im.naturalHeight));
          var c = document.createElement('canvas');
          c.width = Math.max(1, Math.round(im.naturalWidth * k));
          c.height = Math.max(1, Math.round(im.naturalHeight * k));
          var g = c.getContext('2d');
          g.fillStyle = '#fff';
          g.fillRect(0, 0, c.width, c.height);
          g.drawImage(im, 0, 0, c.width, c.height);
          if (c.toBlob) c.toBlob(fin, 'image/jpeg', 0.85);
          else fin(null);
        } catch (e) { fin(null); }
      };
      im.onerror = function () { fin(null); };
      setTimeout(function () { fin(null); }, 20000);
      im.src = url;
    });
  }
  function prepararArchivos(lista, avance) {
    var res = [], hechas = 0, fotos = lista.filter(function (a) { return a.clase === 'foto'; }).length;
    return lista.reduce(function (p, a) {
      return p.then(function () {
        if (a.clase === 'foto' && fotos > 1) avance(++hechas, fotos);
        return (a.clase === 'foto' ? reducir(a.archivo) : Promise.resolve(a.archivo)).then(function (b) {
          var nombre = a.archivo.name || 'archivo';
          if (b !== a.archivo) nombre = nombre.replace(/\.[^.]*$/, '') + '.jpg';
          res.push({ clase: a.clase, etiqueta: a.etiqueta, blob: b, nombre: nombre });
        });
      });
    }, Promise.resolve()).then(function () { return res; });
  }
  function revisarArchivos(archivos) {
    var fotos = archivos.filter(function (a) { return a.clase === 'foto'; });
    if (fotos.length > MAX_FOTOS) return 'Puedes enviar hasta ' + MAX_FOTOS + ' fotos; elige las mejores.';
    if (archivos.length - fotos.length > MAX_DOCS) return 'Puedes enviar hasta ' + MAX_DOCS + ' documentos.';
    var total = 0;
    for (var i = 0; i < archivos.length; i++) {
      var a = archivos[i], tam = (a.blob || a.archivo).size, max = a.clase === 'foto' ? MAX_BYTES_FOTO : MAX_BYTES_DOC;
      if (tam > max) return 'El archivo «' + (a.nombre || a.archivo.name) + '» pesa más de ' + Math.round(max / 1048576) + ' MB.';
      total += tam;
    }
    if (total > MAX_TOTAL) return 'Los archivos pesan demasiado para enviarlos juntos. Envía menos o mándalos por WhatsApp.';
    return '';
  }

  // -------------------------------------------------------------- envío
  function subir(fd, avance) {
    return new Promise(function (listo) {
      var x = new XMLHttpRequest();
      x.open('POST', API, true);
      x.timeout = 180000;
      x.setRequestHeader('Accept', 'application/json');
      if (x.upload && avance) {
        x.upload.onprogress = function (ev) { if (ev.lengthComputable) avance(ev.loaded / ev.total); };
      }
      x.onload = function () {
        var r = null;
        try { r = JSON.parse(x.responseText); } catch (e) { /* no es JSON: el receptor no está */ }
        listo({ codigo: x.status, r: r });
      };
      x.onerror = x.ontimeout = x.onabort = function () { listo({ codigo: 0, r: null }); };
      x.send(fd);
    });
  }

  function ocupado(boton, si) {
    if (si) {
      boton.__mndAntes = { opacidad: boton.style.opacity, cursor: boton.style.cursor };
      boton.disabled = true;
      boton.setAttribute('aria-busy', 'true');
      boton.style.opacity = '.6';
      boton.style.cursor = 'progress';
    } else {
      var a = boton.__mndAntes || {};
      boton.disabled = false;
      boton.removeAttribute('aria-busy');
      boton.style.opacity = a.opacidad || '';
      boton.style.cursor = a.cursor || '';
    }
  }

  function exito(zona, boton, conf, r) {
    estado(zona, boton, conf, 'info', '');
    var ok = zona.querySelector(conf.ok);
    if (conf.credito) {
      ['.mnd-p1', '.mnd-p2', '.mnd-p3', '.mnd-nav', '.mnd-step-count'].forEach(function (s) {
        var el = document.querySelector(s);
        if (el) el.style.display = 'none';
      });
      cada(document.querySelectorAll('.mnd-step'), function (b) { b.classList.add('on'); });
      if (ok) ok.style.display = 'block';
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } else if (ok) {
      ok.style.display = conf.mostrar || 'block';
      ok.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
    if (r && r.avisos && r.avisos.length) {
      estado(zona, boton, conf, 'info', esc('Recibimos tu solicitud. Ojo: ' + r.avisos.join(' ') +
        ' Si quieres, envíanos esos archivos por WhatsApp.'));
    }
    reajustar(zona);
  }

  function enviar(zona, boton, conf) {
    var datos = recoger(zona);
    if (conf.credito) datos.pares = extrasCredito().concat(datos.pares);
    var error = validar(datos, zona, null, true);
    if (error) {
      if (conf.credito && error.campos[0]) {
        for (var n = 1; n <= 2; n++) {
          var b = document.querySelector('.mnd-p' + n);
          if (b && b.contains(error.campos[0])) { irAPaso(n); break; }
        }
      }
      mostrarError(zona, boton, conf, error);
      return;
    }
    var whatsapp = enlaceWhatsApp(conf, datos.pares, datos.archivos);
    var problema = revisarArchivos(datos.archivos);
    if (problema) {
      mostrarError(zona, boton, conf, { mensaje: problema, whatsapp: whatsapp });
      return;
    }
    // Un segundo clic con los mismos datos no crea otra solicitud.
    var firma = JSON.stringify(datos.pares) + '|' + datos.archivos.map(function (a) {
      return a.clase + a.archivo.name + a.archivo.size;
    }).join('|');
    if (zona.__mndFirma === firma) {
      exito(zona, boton, conf, null);
      return;
    }
    zona.__mndEnviando = true;
    ocupado(boton, true);
    estado(zona, boton, conf, 'info', 'Enviando…');
    var acepto = zona.querySelector('.mnd-terms');
    prepararArchivos(datos.archivos, function (i, total) {
      estado(zona, boton, conf, 'info', 'Preparando fotos (' + i + ' de ' + total + ')…');
    }).then(function (archivos) {
      problema = revisarArchivos(archivos);
      if (problema) return { codigo: -1, r: { error: problema } };
      var fd = new FormData();
      fd.append('meta', JSON.stringify({
        tipo: conf.tipo, pagina: pagina.replace(/\.dc\.html$/, ''), t: Date.now() - cargada,
        hp: trampa.value, consentimiento: acepto ? acepto.checked : null
      }));
      fd.append('campos', JSON.stringify(datos.pares));
      archivos.forEach(function (a) { fd.append(a.clase + ':' + a.etiqueta, a.blob, a.nombre); });
      estado(zona, boton, conf, 'info', 'Enviando…');
      return subir(fd, archivos.length ? function (p) {
        estado(zona, boton, conf, 'info', 'Enviando… ' + Math.min(99, Math.round(p * 100)) + '%');
      } : null);
    }).then(function (res) {
      zona.__mndEnviando = false;
      ocupado(boton, false);
      if (res.codigo === 200 && res.r && res.r.ok) {
        zona.__mndFirma = firma;
        exito(zona, boton, conf, res.r);
        return;
      }
      var mensaje = (res.r && res.r.error) || 'No pudimos enviar tu solicitud en este momento.';
      if (!/whatsapp/i.test(mensaje)) mensaje += ' También puedes enviárnosla por WhatsApp:';
      mostrarError(zona, boton, conf, { mensaje: mensaje, whatsapp: whatsapp });
    }, function () {
      zona.__mndEnviando = false;
      ocupado(boton, false);
      mostrarError(zona, boton, conf, { mensaje: 'No pudimos enviar tu solicitud. Envíanosla por WhatsApp:', whatsapp: whatsapp });
    });
  }

  function atender(e, boton, conf) {
    var zona = conf.zona ? boton.closest(conf.zona) : (boton.closest('.mnd-reveal') || boton.parentElement);
    if (!zona) return;
    if (conf.credito) {
      var paso = pasoCredito();
      if (paso < 3) {
        // «Continuar»: revisa los obligatorios del paso y deja que la página avance.
        var error = validar(recoger(zona), zona, document.querySelector('.mnd-p' + paso), false);
        if (error) {
          e.preventDefault();
          e.stopPropagation();
          mostrarError(zona, boton, conf, error);
        } else {
          estado(zona, boton, conf, 'info', '');
        }
        return;
      }
    }
    e.preventDefault();
    e.stopPropagation();
    if (zona.__mndEnviando) return;
    enviar(zona, boton, conf);
  }

  document.addEventListener('click', function (e) {
    var t = e.target;
    if (!t || !t.closest) return;
    for (var i = 0; i < CONFS.length; i++) {
      var boton = t.closest(CONFS[i].boton);
      if (boton) {
        atender(e, boton, CONFS[i]);
        return;
      }
    }
  }, true);

  if (pagina === 'SolicitudCredito.dc.html') mostrarAutoEnSimulacion();
})();
