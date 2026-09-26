#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mcp_clientes: las herramientas del asistente de WhatsApp para clientes.

Es un servidor MCP (JSON-RPC por la entrada y salida estándar, solo biblioteca
estándar de Python) que Hermes arranca para el asistente de clientes. Le da
cuatro herramientas y nada más:

  buscar_autos       autos publicados en el sitio (solo lo que el sitio muestra)
  ver_auto           la ficha de un auto, con su enlace y sus fotos
  info_mendiautos    datos del negocio: ubicación, horario, servicios, créditos
  registrar_interes  deja una solicitud para que un asesor contacte al cliente

No puede cambiar el catálogo ni leer las solicitudes de otros: lee el catálogo
público (assets/inventario.js) y entrega los interesados al receptor del sitio
con una clave interna. Todo lo que devuelve es texto para el modelo de IA.
"""
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

AQUI = Path(__file__).resolve().parent
INVENTARIO = Path(os.environ.get('MENDIAUTOS_INVENTARIO') or '/var/lib/mendiautos/catalogo/inventario.js')
RAIZ_FOTOS = Path(os.environ.get('MENDIAUTOS_RAIZ_FOTOS') or '/var/lib/mendiautos')  # + catalogo/fotos/…
EMPRESA = Path(os.environ.get('MENDIAUTOS_EMPRESA') or AQUI / 'empresa.json')
TOKEN_F = Path(os.environ.get('MENDIAUTOS_TOKEN_CLIENTES') or '/etc/mendiautos/clientes.token')
CONF = Path(os.environ.get('MENDIAUTOS_CONF') or '/etc/mendiautos.conf')
RECEPTOR = os.environ.get('MENDIAUTOS_RECEPTOR') or 'http://127.0.0.1:8781'
VERSION = '1.0.0'

MOTIVOS = {
    'comprar': 'Quiere comprar un auto', 'vender': 'Quiere vender su auto',
    'credito': 'Quiere un crédito', 'servicio': 'Pide un servicio (trámites, fotos, acompañamiento)',
    'otro': 'Otra consulta',
}
MAX_REGISTROS_HORA, MAX_POR_NUMERO_HORA = 30, 3
_registros = []           # (momento, celular) de los registros de la última hora
_cache = {'mtime': None, 'autos': []}


class ErrorHerramienta(Exception):
    """Mensaje para el modelo: qué salió mal y qué hacer."""


# ------------------------------------------------------------------ datos
def sin_acentos(s):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(s)) if not unicodedata.combining(c)).lower()


def miles(n):
    return f'{int(n):,}'.replace(',', '.')


def sitio():
    try:
        for linea in CONF.read_text(encoding='utf-8').splitlines():
            if linea.startswith('SITIO='):
                return linea[6:].strip().strip('\'"').rstrip('/')
    except OSError:
        pass
    return os.environ.get('MENDIAUTOS_SITIO', '').rstrip('/')


def autos():
    """Autos publicados (sin los ocultos), leídos del mismo archivo que usa el sitio."""
    try:
        mtime = INVENTARIO.stat().st_mtime
    except OSError:
        raise ErrorHerramienta('El catálogo no está disponible en este momento. Ofrece registrar el interés '
                               'del cliente para que un asesor le escriba.')
    if _cache['mtime'] != mtime:
        m = re.search(r'window\.MND_INVENTARIO\s*=\s*(\[.*\])\s*;?\s*$', INVENTARIO.read_text(encoding='utf-8'), re.S)
        lista = json.loads(m.group(1)) if m else []
        _cache['autos'] = [a for a in lista if isinstance(a, dict) and a.get('id') and a.get('marca')
                           and a.get('modelo') and a.get('estado') != 'oculto']
        _cache['mtime'] = mtime
    return _cache['autos']


def hay(v):
    return v not in (None, '', '—') and str(v).strip() != ''


def nombre(a):
    return ' '.join(str(a[k]) for k in ('marca', 'modelo', 'version', 'anio') if hay(a.get(k)))


def precio(a):
    try:
        p = int(float(a.get('precio') or 0))
    except (TypeError, ValueError):
        p = 0
    return p


def enlace(a):
    base = sitio()
    return f'{base}/DetalleAuto.dc.html?id={a["id"]}' if base else f'DetalleAuto.dc.html?id={a["id"]}'


def texto_busqueda(a):
    campos = ('marca', 'modelo', 'version', 'anio', 'carroceria', 'tipo_carroceria', 'combustible',
              'transmision', 'traccion', 'color_exterior', 'ciudad')
    return sin_acentos(' '.join(str(a.get(k) or '') for k in campos))


def linea_auto(a):
    partes = [nombre(a)]
    if hay(a.get('km')):
        try:
            partes.append(f'{miles(float(a["km"]))} km')
        except (TypeError, ValueError):
            pass
    for k in ('transmision', 'combustible'):
        if hay(a.get(k)):
            partes.append(str(a[k]).lower())
    partes.append('VENDIDO' if a.get('estado') == 'vendido' else (f'${miles(precio(a))}' if precio(a) else 'precio a consultar'))
    return ' · '.join(partes) + f'\n  ficha: {enlace(a)} (id: {a["id"]})'


def fotos_locales(a, maximo=3):
    res = []
    for web in a.get('fotos') or []:
        if not isinstance(web, str) or not re.fullmatch(r'catalogo/fotos/[a-z0-9-]+/[0-9a-f]{16}\.jpg', web):
            continue
        ruta = RAIZ_FOTOS / web
        mediana = ruta.with_name(ruta.stem + '-m.jpg')
        elegida = mediana if mediana.is_file() else ruta
        if elegida.is_file():
            res.append(str(elegida))
        if len(res) >= maximo:
            break
    return res


def buscar_uno(ref):
    lista = autos()
    ref = str(ref or '').strip()
    exacto = [a for a in lista if a['id'] == ref]
    if exacto:
        return exacto[0], []
    palabras = [p for p in re.split(r'\W+', sin_acentos(ref)) if p]
    if not palabras:
        raise ErrorHerramienta('Indica el id del auto o palabras que lo identifiquen (marca, modelo, año).')
    candidatos = [a for a in lista if all(p in texto_busqueda(a) for p in palabras)]
    if len(candidatos) == 1:
        return candidatos[0], []
    return None, candidatos


# ----------------------------------------------------------- herramientas
SINONIMOS = {
    'camioneta': ('suv', 'camioneta', 'pickup'), 'camionetas': ('suv', 'camioneta', 'pickup'),
    'automatico': ('automatica',), 'automatica': ('automatica',), 'mecanico': ('mecanica',),
    'diesel': ('diesel',), 'electrico': ('electrico',), 'hibrido': ('hibrido',),
}
IGNORAR = {'carro', 'carros', 'auto', 'autos', 'vehiculo', 'vehiculos', 'un', 'una', 'de', 'del', 'la', 'el',
           'los', 'las', 'con', 'que', 'y', 'o', 'en', 'para', 'busco', 'quiero', 'tienen', 'hay'}


def buscar_autos(args):
    lista = autos()
    incluir_vendidos = bool(args.get('incluir_vendidos'))
    if not incluir_vendidos:
        lista = [a for a in lista if (a.get('estado') or 'disponible') == 'disponible']

    def num(k):
        v = args.get(k)
        if v in (None, ''):
            return None
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
        digitos = re.sub(r'\D', '', str(v))  # «80.000.000» → 80000000
        if not digitos:
            raise ErrorHerramienta(f'«{k}» debe ser un número.')
        return float(digitos)

    pmin, pmax, amin, amax, kmax = num('precio_min'), num('precio_max'), num('anio_min'), num('anio_max'), num('km_max')
    filtrados = []
    for a in lista:
        p = precio(a)
        if pmin is not None and (not p or p < pmin):
            continue
        if pmax is not None and (not p or p > pmax):
            continue
        try:
            anio = int(a.get('anio') or 0)
            km = float(a.get('km') or 0)
        except (TypeError, ValueError):
            anio, km = 0, 0
        if amin is not None and anio < amin or amax is not None and anio > amax:
            continue
        if kmax is not None and km > kmax:
            continue
        filtrados.append(a)
    for k in ('carroceria', 'transmision', 'combustible', 'marca'):
        if args.get(k):
            q = sin_acentos(args[k])
            filtrados = [a for a in filtrados if q in sin_acentos(f'{a.get(k) or ""} {a.get("tipo_carroceria") or ""}'
                                                                   if k == 'carroceria' else a.get(k) or '')]
    nota = ''
    palabras = [p for p in re.split(r'\W+', sin_acentos(args.get('texto') or '')) if p and p not in IGNORAR]
    if palabras:
        puntuados = []
        for a in filtrados:
            t = texto_busqueda(a)
            puntos = sum(1 for p in palabras if any(s in t for s in SINONIMOS.get(p, (p,))))
            if puntos:
                puntuados.append((puntos, a))
        puntuados.sort(key=lambda x: (-x[0], precio(x[1]) or 10 ** 12))
        completos = [a for p, a in puntuados if p == len(palabras)]
        if completos or not puntuados:
            filtrados = completos
        else:
            filtrados = [a for _, a in puntuados]
            nota = 'Ninguno coincide con todo lo pedido; estos se parecen (dilo así al cliente):'
    else:
        filtrados.sort(key=lambda a: (not a.get('destacado'), precio(a) or 10 ** 12))
    try:
        limite = max(1, min(10, int(args.get('limite') or 6)))
    except (TypeError, ValueError):
        limite = 6
    if not filtrados:
        marcas = sorted({a['marca'] for a in autos() if (a.get('estado') or 'disponible') == 'disponible'})
        return ('No hay autos publicados que coincidan. Marcas disponibles hoy: ' + (', '.join(marcas) or 'ninguna') +
                '. Puedes ofrecer registrar lo que busca (registrar_interes, motivo «comprar») para que un asesor '
                'le avise cuando llegue uno.')
    res = [nota] if nota else []
    res.append(f'{len(filtrados)} auto(s) encontrados' + (f'; los {limite} primeros:' if len(filtrados) > limite else ':'))
    res += [linea_auto(a) for a in filtrados[:limite]]
    res.append('Los precios y la disponibilidad cambian; confirma con un asesor antes de prometer algo.')
    return '\n'.join(res)


def ver_auto(args):
    a, varios = buscar_uno(args.get('auto'))
    if not a:
        if varios:
            return 'Hay varios autos que coinciden; pregunta cuál:\n' + '\n'.join(linea_auto(x) for x in varios[:8])
        return 'No encontré ese auto en el catálogo publicado. Usa buscar_autos para ver los disponibles.'
    etiquetas = (('anio', 'Año'), ('km', 'Kilómetros'), ('transmision', 'Transmisión'), ('combustible', 'Combustible'),
                 ('carroceria', 'Carrocería'), ('traccion', 'Tracción'), ('motor', 'Motor'), ('cilindraje', 'Cilindraje'),
                 ('color_exterior', 'Color'), ('ciudad', 'Ciudad'), ('placa_fin', 'Placa termina en'),
                 ('unico_dueno', 'Único dueño'), ('blindado', 'Blindado'), ('negociable', 'Precio negociable'),
                 ('financiacion', 'Financiación'), ('permuta', 'Acepta permuta'))
    res = [nombre(a), 'Estado: ' + ('VENDIDO' if a.get('estado') == 'vendido' else 'disponible'),
           'Precio: ' + (f'${miles(precio(a))}' if precio(a) else 'a consultar con un asesor')]
    for k, et in etiquetas:
        v = a.get(k)
        if isinstance(v, bool):
            v = 'Sí' if v else 'No'
        if hay(v):
            if k == 'km':
                try:
                    v = miles(float(v))
                except (TypeError, ValueError):
                    pass
            res.append(f'{et}: {v}')
    if hay(a.get('descripcion')):
        d = re.sub(r'\s+', ' ', str(a['descripcion'])).strip()
        res.append('Descripción: ' + d[:700] + ('…' if len(d) > 700 else ''))
    res.append(f'Ficha en el sitio: {enlace(a)}')
    fotos = fotos_locales(a)
    if fotos:
        res.append('Fotos (para enviarlas en tu respuesta, escribe una línea MEDIA:<ruta> por foto):')
        res += fotos
    else:
        res.append('Este auto no tiene fotos publicadas todavía.')
    return '\n'.join(res)


def info_mendiautos(args):
    try:
        empresa = json.loads(EMPRESA.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise ErrorHerramienta('No tengo la información del negocio a mano. Ofrece registrar la consulta para '
                               'que un asesor responda.')
    tema = sin_acentos(args.get('tema') or '')
    secciones = empresa.get('secciones') or {}
    base = sitio()
    res = []
    for clave, sec in secciones.items():
        if tema and tema not in sin_acentos(clave + ' ' + ' '.join(sec.get('palabras', []))):
            continue
        texto = sec.get('texto', '')
        if base:
            texto = texto.replace('{{SITIO}}', base)
        res.append(f'## {sec.get("titulo", clave)}\n{texto}')
    if not res:
        res = [f'## {s.get("titulo", c)}\n{s.get("texto", "").replace("{{SITIO}}", base)}' for c, s in secciones.items()]
    return '\n\n'.join(res)


def celular_valido(v):
    d = re.sub(r'\D', '', str(v or ''))
    if len(d) == 10 and d.startswith('3'):
        d = '57' + d
    return d if 11 <= len(d) <= 15 else ''


def registrar_interes(args):
    if str(args.get('autoriza_datos')).strip().lower() not in ('true', '1', 'si', 'sí', 'yes'):
        raise ErrorHerramienta('Antes de registrar, pregúntale al cliente si autoriza a Mendiautos a guardar sus datos '
                               'y contactarlo (Ley 1581 de 2012). Solo si dice que sí, llama de nuevo con '
                               'autoriza_datos=true.')
    nom = re.sub(r'\s+', ' ', str(args.get('nombre') or '')).strip()[:80]
    cel = celular_valido(args.get('celular'))
    motivo = str(args.get('motivo') or '').strip().lower()
    detalle = str(args.get('detalle') or '').strip()[:1500]
    if not nom:
        raise ErrorHerramienta('Falta el nombre del cliente: pregúntaselo.')
    if not cel:
        raise ErrorHerramienta('Falta un celular válido (10 dígitos, por ejemplo 3001234567): pregúntaselo.')
    if motivo not in MOTIVOS:
        raise ErrorHerramienta('motivo debe ser uno de: ' + ', '.join(MOTIVOS))
    ahora = time.time()
    _registros[:] = [r for r in _registros if ahora - r[0] < 3600]
    if len(_registros) >= MAX_REGISTROS_HORA or sum(1 for r in _registros if r[1] == cel) >= MAX_POR_NUMERO_HORA:
        raise ErrorHerramienta('Ya se registraron varias solicitudes en poco tiempo. Dile al cliente que un asesor '
                               'ya tiene sus datos y le escribirá pronto.')
    datos = [['Motivo', MOTIVOS[motivo]]]
    if args.get('auto'):
        a, _ = buscar_uno(args['auto'])
        datos.append(['Auto de interés', f'{nombre(a)} (ref. {a["id"]})' if a else str(args['auto'])[:120]])
    if detalle:
        datos.append(['Mensaje', detalle])
    try:
        token = TOKEN_F.read_text().strip()
    except OSError:
        token = ''
    cuerpo = json.dumps({'tipo': 'whatsapp', 'contacto': {'nombre': nom, 'celular': cel}, 'datos': datos,
                         'consentimiento': True, 'origen': 'whatsapp', 'pagina': 'WhatsApp (asistente)'}).encode()
    peticion = urllib.request.Request(RECEPTOR.rstrip('/') + '/interno/solicitud', data=cuerpo, method='POST',
                                      headers={'Content-Type': 'application/json', 'X-Mendiautos-Token': token})
    try:
        with urllib.request.urlopen(peticion, timeout=15) as r:
            respuesta = json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        print(f'registrar_interes: el receptor respondió {e.code}', file=sys.stderr)
        respuesta = {}
    except (OSError, ValueError) as e:
        print(f'registrar_interes: {e.__class__.__name__}', file=sys.stderr)
        respuesta = {}
    if not respuesta.get('ok'):
        raise ErrorHerramienta('No pude registrar la solicitud en este momento. Pídele al cliente que escriba al '
                               'WhatsApp de ventas que aparece en info_mendiautos.')
    _registros.append((ahora, cel))
    return (f'Registrada la solicitud {respuesta["id"]}. Un asesor de Mendiautos le escribirá a {nom} al '
            f'{cel[2:] if cel.startswith("57") else cel}. No prometas una hora exacta: dile que lo contactarán '
            'en horario de atención.')


HERRAMIENTAS = {
    'buscar_autos': (buscar_autos, {
        'description': 'Busca en los autos publicados en el sitio de Mendiautos (los que están a la venta). '
                       'Úsala antes de hablar de cualquier auto: nunca inventes autos, precios ni datos.',
        'inputSchema': {'type': 'object', 'properties': {
            'texto': {'type': 'string', 'description': 'Lo que busca el cliente: marca, modelo, tipo, color… '
                                                       '(ej. «Mazda CX-5», «camioneta automática»)'},
            'marca': {'type': 'string'},
            'precio_max': {'type': 'number', 'description': 'Presupuesto máximo en pesos colombianos'},
            'precio_min': {'type': 'number', 'description': 'Precio mínimo en pesos colombianos'},
            'anio_min': {'type': 'integer'}, 'anio_max': {'type': 'integer'},
            'km_max': {'type': 'number', 'description': 'Kilometraje máximo'},
            'carroceria': {'type': 'string', 'description': 'SUV, sedán, hatchback, pickup…'},
            'transmision': {'type': 'string', 'description': 'automática o mecánica'},
            'combustible': {'type': 'string', 'description': 'gasolina, diésel, híbrido, eléctrico'},
            'incluir_vendidos': {'type': 'boolean', 'description': 'Incluir los ya vendidos (por defecto no)'},
            'limite': {'type': 'integer', 'description': 'Cuántos mostrar (1 a 10, por defecto 6)'},
        }, 'additionalProperties': False},
    }),
    'ver_auto': (ver_auto, {
        'description': 'Ficha completa de un auto publicado: datos, precio, enlace y rutas de sus fotos '
                       '(para enviarlas por el chat).',
        'inputSchema': {'type': 'object', 'properties': {
            'auto': {'type': 'string', 'description': 'El id del auto (de buscar_autos) o palabras que lo '
                                                      'identifiquen, como «duster 2023»'},
        }, 'required': ['auto'], 'additionalProperties': False},
    }),
    'info_mendiautos': (info_mendiautos, {
        'description': 'Información del negocio: ubicación, horario, contacto, cómo vender el auto, créditos, '
                       'otros servicios y enlaces del sitio. Úsala en vez de suponer.',
        'inputSchema': {'type': 'object', 'properties': {
            'tema': {'type': 'string', 'description': 'Opcional: ubicacion, horario, contacto, vender, credito, '
                                                      'servicios, comprar'},
        }, 'additionalProperties': False},
    }),
    'registrar_interes': (registrar_interes, {
        'description': 'Deja una solicitud al equipo de ventas para que un asesor contacte al cliente por WhatsApp. '
                       'Úsala cuando el cliente quiera ver un auto, negociar, vender el suyo, pedir crédito o hablar '
                       'con una persona. Antes pídele nombre y celular, y pregúntale si autoriza el tratamiento de '
                       'sus datos.',
        'inputSchema': {'type': 'object', 'properties': {
            'nombre': {'type': 'string', 'description': 'Nombre del cliente'},
            'celular': {'type': 'string', 'description': 'Celular del cliente, 10 dígitos (ej. 3001234567)'},
            'motivo': {'type': 'string', 'enum': sorted(MOTIVOS), 'description': 'Qué quiere el cliente'},
            'auto': {'type': 'string', 'description': 'Opcional: id del auto que le interesa'},
            'detalle': {'type': 'string', 'description': 'Resumen corto de lo que pidió (sin datos sensibles)'},
            'autoriza_datos': {'type': 'boolean', 'description': 'true solo si el cliente dijo que autoriza el '
                                                                 'tratamiento de sus datos'},
        }, 'required': ['nombre', 'celular', 'motivo', 'autoriza_datos'], 'additionalProperties': False},
    }),
}


# ------------------------------------------------------------ protocolo MCP
def enviar(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + '\n')
    sys.stdout.flush()


def atender(msg):
    if not isinstance(msg, dict):
        return {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32600, 'message': 'Invalid Request'}}
    metodo, ident, params = msg.get('method'), msg.get('id'), msg.get('params') or {}
    if ident is None:          # notificación (initialized, cancelled…): sin respuesta
        return None
    if metodo == 'initialize':
        resultado = {
            'protocolVersion': params.get('protocolVersion') or '2025-06-18',
            'capabilities': {'tools': {'listChanged': False}},
            'serverInfo': {'name': 'mendiautos', 'version': VERSION},
            'instructions': 'Herramientas del catálogo público y de contacto de Mendiautos.',
        }
    elif metodo == 'ping':
        resultado = {}
    elif metodo == 'tools/list':
        resultado = {'tools': [dict(name=n, **d) for n, (_, d) in HERRAMIENTAS.items()]}
    elif metodo == 'tools/call':
        nombre_h = params.get('name')
        if nombre_h not in HERRAMIENTAS:
            return {'jsonrpc': '2.0', 'id': ident, 'error': {'code': -32602, 'message': f'Herramienta desconocida: {nombre_h}'}}
        args = params.get('arguments') or {}
        try:
            texto = HERRAMIENTAS[nombre_h][0](args if isinstance(args, dict) else {})
            error = False
        except ErrorHerramienta as e:
            texto, error = str(e), True
        except Exception as e:  # un fallo no debe tumbar el servidor
            print(f'{nombre_h}: {e.__class__.__name__}: {e}', file=sys.stderr)
            texto, error = 'Hubo un problema con esta herramienta. Ofrece registrar la consulta para un asesor.', True
        resultado = {'content': [{'type': 'text', 'text': texto}], 'isError': error}
    elif metodo in ('resources/list', 'prompts/list'):
        resultado = {'resources': []} if metodo == 'resources/list' else {'prompts': []}
    else:
        return {'jsonrpc': '2.0', 'id': ident, 'error': {'code': -32601, 'message': f'Método no soportado: {metodo}'}}
    return {'jsonrpc': '2.0', 'id': ident, 'result': resultado}


def main():
    for crudo in sys.stdin.buffer:
        crudo = crudo.strip()
        if not crudo:
            continue
        try:
            msg = json.loads(crudo.decode('utf-8'))
        except ValueError:
            enviar({'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'Parse error'}})
            continue
        for m in (msg if isinstance(msg, list) else [msg]):
            r = atender(m)
            if r is not None:
                enviar(r)


if __name__ == '__main__':
    main()
